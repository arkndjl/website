#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The live rule monitor (Oct 21 2026): every rule that bets, checked against the closing line as it goes, and stopped
when it is losing to the close. Stdlib only.

    python3 scripts/rule_monitor.py          # data/rule_monitor.json: the report on the Predictions page
    python3 scripts/rule_monitor.py --test   # self-check

What it covers: the Predictions pick rules (each sport's market rule and each kept segment, scripts/games_picks.py),
Dengler Units on top of them (does sizing add: close value weighted by stake against flat), and the paper book rules
(scripts/paper_book.py). For each: n judged by the close, close value (clvRet) with a t clustered by game day, how often
the line moved our way, flat ROI, the last week alone, and the live record against what the backtest expected.

The switch (scripts/monitor_rules.json, pre-registered): decide() is the one test; games_picks.py calls it where the
bets are made and keeps the stop with the rule, and this report reads its state. A stopped rule comes back only by a
refit, which restarts its clock.

A pick rule, with minN+ bets judged since its clock started, stops on any of three, each by game day with the day
deflated by 1 + (n - 1) rho (rho the within-slate correlation of close value on the rule's held-out picks):
  - losing to the close: the one-sided CUSUM around zero (z = clvRet / the rule's backtest sd, k, h) past h;
  - under the edge its stakes assume (mu1 = expected_live()): the CUSUM of the log likelihood ratio of "worth
    nothing" against "worth mu1" (reference mu1 / 2) past cusum.hL;
  - the drift test: the same ratio as a sequential test from the clock.
The last `window` bets' clustered t is shown, not a stop.

A rule with no slate structure passed (the model monitor's standardised losses) keeps the test against zero alone: the
window's clustered t below the Student cut at the level `t` stands for (minDays+ game days), or the per-bet CUSUM.
"""
import datetime
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRE = os.path.join(HERE, 'monitor_rules.json')
OUT = os.path.join(ROOT, 'data', 'rule_monitor.json')
SPORTS = ('cfb', 'nfl', 'cbb', 'nba')


def params():
    return json.load(open(PRE))


def iso(t):
    return datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))


def day(kick):
    """the game day a bet belongs to (US Eastern date of the start): the cluster"""
    from zoneinfo import ZoneInfo
    return iso(kick).astimezone(ZoneInfo('America/New_York')).date().isoformat()


def fp(d):
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:10]


def clustered(xs, groups, ws=None):
    """weighted mean with a cluster-robust standard error (CR1, one cluster a game day), never under the iid one (a few
    game days can put the clustered se far below it: 80 bets on 3 days once read t -9.95): (mean, se, t, clusters)"""
    n = len(xs)
    if not n:
        return None, None, None, 0
    ws = ws or [1.0] * n
    W = sum(ws)
    if W <= 0:
        return None, None, None, 0
    m = sum(w * x for w, x in zip(ws, xs)) / W
    acc = {}
    for x, g, w in zip(xs, groups, ws):
        acc[g] = acc.get(g, 0.0) + w * (x - m)
    G = len(acc)
    if G < 2:
        return m, None, None, G
    se = math.sqrt(sum(v * v for v in acc.values()) * G / (G - 1)) / W
    iid = math.sqrt(sum((w * (x - m)) ** 2 for x, w in zip(xs, ws)) * n / (n - 1)) / W
    se = max(se, iid)
    return m, se, (m / se if se else None), G


def _betacf(a, b, x):
    """the continued fraction of the incomplete beta function (Lentz)"""
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        for num in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)), -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1 + num * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + num / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-12:
            break
    return h


def t_cdf(t, df):
    """P(T <= t) for Student's t on df degrees of freedom"""
    x = df / (df + t * t)
    a, b = df / 2.0, 0.5
    if x <= 0:
        tail = 0.0
    elif x >= 1:
        tail = 0.5
    else:
        lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
        ib = math.exp(lb) * _betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - math.exp(lb) * _betacf(b, a, 1 - x) / b
        tail = ib / 2
    return tail if t < 0 else 1 - tail


def t_p(t, G, P=None):
    """the one-sided p of a clustered t on G game days (Student, G - 1 df); None under minDays clusters: no verdict"""
    P = P or params()
    if t is None or G < P.get('minDays', 8):
        return None
    return t_cdf(t, G - 1)


def sd_of(rec):
    """a backtest record's sd of close value, from its mean, t and n"""
    if not rec:
        return None
    m, t, n = rec.get('clvRet'), rec.get('clvT'), rec.get('clvN') or rec.get('n')
    if m is None or not t or not n:
        return None
    return abs(m / t) * math.sqrt(n)


def cusum(xs, sd, k, h):
    """the lower CUSUM path on close value: (S now, max S, the bet it first crossed h at or None)"""
    S, top, hit = 0.0, 0.0, None
    for i, x in enumerate(xs):
        S = max(0.0, S - x / sd - k)
        top = max(top, S)
        if hit is None and S >= h:
            hit = i + 1
    return S, top, hit


def day_llr(xs, mu1, sd, rho):
    """one game day's log likelihood ratio of "worth mu1 a bet" against "worth nothing": (s - n mu1 / 2) mu1 /
    (sd^2 (1 + (n - 1) rho)), s the day's summed close value over n bets, rho their within-slate correlation"""
    n = len(xs)
    return (sum(xs) - n * mu1 / 2) * mu1 / (sd * sd * (1 + (n - 1) * rho))


def cusum_llr(days, mu1, sd, rho, h, min_n=0):
    """the lower CUSUM of the game-day log likelihood ratio (reference mu1 / 2: it rises while the rule runs under half
    the edge its stakes assume). days: lists of close values in game-day order. (S now, max S, the bet count at the
    end of the first day S stood at h or more with min_n+ bets, or None)"""
    S, top, hit, n = 0.0, 0.0, None, 0
    for xs in days:
        n += len(xs)
        S = max(0.0, S - day_llr(xs, mu1, sd, rho))
        top = max(top, S)
        if hit is None and S >= h and n >= min_n:
            hit = n
    return S, top, hit


def cusum_days(days, sd, k, h, rho, min_n=0):
    """cusum() by game day: a day adds its bets' summed (-z - k) over 1 + (n - 1) rho, so a slate that moved together
    counts as the bets it is worth (per bet, undeflated, a rule at its edge stopped 9-52% of the time on the history's
    slates). Same returns as cusum_llr"""
    S, top, hit, n = 0.0, 0.0, None, 0
    for xs in days:
        n += len(xs)
        S = max(0.0, S + sum(-x / sd - k for x in xs) / (1 + (len(xs) - 1) * rho))
        top = max(top, S)
        if hit is None and S >= h and n >= min_n:
            hit = n
    return S, top, hit


def decide(bets, sd=None, P=None, mu1=None, rho=None):
    """the one test. bets: dicts with kick (or k) and clvRet, any order; sd the rule's backtest sd of close value.
    Returns the window's clustered stats, the CUSUM and stop (True when the rule should stop now) with why.
    A pick rule passes rho (the within-slate correlation of its close value, rho_for) and mu1 (the edge its stakes
    assume, expected_live): its picks are judged at units.BASE with no moneylines (as drift()), by game day, and it
    stops on the CUSUM around zero (losing to the close) or the CUSUM against mu1 (out['edge']: running under half the
    stakes' edge); the window's t is reported, not a stop. Without rho (the paper book, the model monitor) the test is
    against zero alone: the window's t under the Student cut, or the per-bet CUSUM"""
    P = P or params()
    sd = sd or P['sdDefault']
    jc = sorted([b for b in bets if b.get('clvRet') is not None], key=lambda b: b.get('kick') or b.get('k'))
    w = jc[-P['window']:]
    m, se, t, G = clustered([b['clvRet'] for b in w], [day(b.get('kick') or b.get('k')) for b in w])
    p = t_p(t, G, P)
    h = P['cusum']['h']
    why, hit, edge = [], None, None
    if rho is not None:
        jb = sorted([{**b, 'clvRet': at_base(b)} for b in bets if at_base(b) is not None], key=lambda b: b.get('kick') or b.get('k'))
        by = {}
        for b in jb:
            by.setdefault(day(b.get('kick') or b.get('k')), []).append(b['clvRet'])
        days = [by[d] for d in sorted(by)]
        S, top, hit = cusum_days(days, sd, P['cusum']['k'], h, rho, P['minN'])
        if len(jb) >= P['minN'] and S >= h:
            why.append(f"CUSUM {S:.1f} past {h:g}")
        if mu1 and mu1 > 0:
            hL = P['cusum']['hL']
            Se, tope, hite = cusum_llr(days, mu1, sd, rho, hL, P['minN'])
            edge = {'cusum': round(Se, 2), 'cusumMax': round(tope, 2), 'h': hL, **({'hitAt': hite} if hite else {})}
            if len(jb) >= P['minN'] and Se >= hL:
                why.append(f"under half the edge its stakes assume (CUSUM {Se:.1f} past {hL:g})")
    else:
        S, top, _ = cusum([b['clvRet'] for b in jc], sd, P['cusum']['k'], h)
        if len(jc) >= P['minN']:
            if p is not None and p < 0.5 * (1 + math.erf(P['t'] / math.sqrt(2))):
                why.append(f"last {len(w)} worth t {t:.2f} at the close")
            if S >= h:
                why.append(f"CUSUM {S:.1f} past {h:g}")
    return {'n': len(jc), 'window': len(w), 'mean': None if m is None else round(m, 4), 't': None if t is None else round(t, 2),
            'p': None if p is None else round(p, 4), 'days': G, 'sd': round(sd, 4), 'cusum': round(S, 2), 'cusumMax': round(top, 2),
            'h': h, **({'hitAt': hit} if hit else {}), **({'rho': round(rho, 3)} if rho is not None else {}),
            **({'edge': edge} if edge else {}), 'stop': bool(why), 'why': '; '.join(why)}


# ---------------------------------------------------------------- the drift test: is a rule worth what its backtest said?

def expected_live(sport, held):
    """the close value a rule's live picks should be worth if its backtest holds: the held-out record's clvRet times the
    haircuts the stakes already take (units.TIMING: live picks are bet after part of the open's move; units.LEAK: NBA
    history saw news the open did not). None when the backtest has no positive record to test against"""
    if not held or not (held.get('clvRet') or 0) > 0:
        return None
    import units as DU
    # the haircut is on the edge over a fair coin at BASE, as units.adj stakes it (Nov 2 2026 audit: scaling the return
    # itself tested CBB spreads against .0181 where the stakes assume .0108, and paused a rule earning exactly its
    # stakes' edge 22-34% of the time in simulation, against 3-6% this way)
    return max(0.0, DU.adj(held['clvRet'], 0.0, DU.TIMING * DU.LEAK.get(sport, 1.0)))


def at_base(b):
    """a live pick's close value judged at units.BASE, the price mu1 is at (a DraftKings -110 fallback reads ~3 points
    lower than the same pick at -103). Moneylines are left out of the test: their return is on another scale (one +203
    pick showed clvRet 1.045). None when it cannot be judged."""
    if b.get('clvRet') is None or b.get('mk') == 'ml':
        return None
    if b.get('mk') in ('spread', 'total') and b.get('line') is not None and b.get('close') is not None and b.get('sport'):
        try:
            import clv as C
            import units as DU
            r = C.ret(b['sport'], b['mk'], b['side'], b['line'], DU.BASE, b['close'])
            if r is not None:
                return r
        except Exception as e:
            print(f'rule monitor: close value recompute failed ({e!r}), the stored clvRet', file=sys.stderr)
    return b['clvRet']


def rho_for(sport, mk, held=None):
    """the within-slate correlation of a rule's close value: the ICC of clvRet by slate on its held-out picks
    (games_picks.py stores it as the held record's clvIcc). units' rho is the correlation of RESULTS against the close
    (about 0), the right one for stakes and the wrong one here: close value moves together on a slate (CBB totals .06,
    NFL totals .23), and at 27 bets a day that is a design effect of 2.5. A record without it falls back to units'."""
    if held and held.get('clvIcc') is not None:
        return max(0.0, held['clvIcc'])
    try:
        import units as DU
        return max(0.0, DU.params(sport, mk).get('rho') or 0.0)
    except Exception as e:
        print(f'rule monitor: no units rho for {sport} {mk} ({e!r}), 0', file=sys.stderr)
        return 0.0


def drift(bets, mu1, sd=None, rho=0.0, P=None):
    """Wald's sequential test of "the rule is worth its backtest" (mean close value mu1, the edge its stakes assume)
    against "the rule is worth nothing" (0: the backtest was overfit). Each game day adds its log likelihood ratio
    (s - n mu1 / 2) mu1 / (sd^2 (1 + (n - 1) rho)), s the day's summed clvRet over n bets, rho the within-slate
    correlation of close value (rho_for). In game-day order, the first crossing decides: down past -ln(B) pauses the rule, up past ln(A)
    confirms it and retires the test (the close switch in decide() still runs). Since LLR = (sum e^2 / sd^2) x
    (r - 1/2) with r the realization rate (live close value over mu1, here r = mean / mu1), the test is the same as
    asking whether the rule realises more or less than half its expected edge, with a margin that shrinks as bets come in."""
    P = P or params()
    D = P['drift']
    sd = sd or P['sdDefault']
    jc = sorted([{**b, 'clvRet': at_base(b)} for b in bets if at_base(b) is not None], key=lambda b: b.get('kick') or b.get('k'))
    out = {'mu1': None if mu1 is None else round(mu1, 4), 'n': len(jc), 'sd': round(sd, 4), 'rho': round(rho, 3),
           'lo': round(-math.log(D['B']), 3), 'hi': round(math.log(D['A']), 3)}
    if not mu1 or mu1 <= 0:
        return {**out, 'state': 'no test', 'llr': None, 'path': []}
    days = {}
    for b in jc:
        days.setdefault(day(b.get('kick') or b.get('k')), []).append(b['clvRet'])
    llr, path, state, at, n = 0.0, [], 'watching', None, 0
    for d in sorted(days):
        xs = days[d]
        m = len(xs)
        n += m
        llr += day_llr(xs, mu1, sd, rho)
        path.append([d, n, round(llr, 3)])
        if state == 'watching' and n >= D['minN']:
            if llr <= out['lo']:
                state, at = 'paused', [d, n]
            elif llr >= out['hi']:
                state, at = 'confirmed', [d, n]
    m = sum(x for xs in days.values() for x in xs) / n if n else None
    info = n * mu1 * mu1 / (sd * sd) if n else 0.0          # sum e^2 / sd^2: the evidence the bets carry, rho aside
    r = None if m is None else m / mu1
    rse = None if not n else sd * math.sqrt(1 + (n / max(1, len(days)) - 1) * rho) / math.sqrt(n) / mu1
    # bets until a rule exactly at its backtest, or at nothing, would reach a boundary on average (Wald: ln bound / drift)
    need = round(math.log(D['A']) / (mu1 * mu1 / (2 * sd * sd)))
    return {**out, 'state': state, 'at': at, 'llr': round(llr, 3), 'info': round(info, 2),
            'real': None if r is None else round(r, 3), 'realSe': None if rse is None else round(rse, 3),
            'need': need, 'path': path[-60:]}


# ---------------------------------------------------------------- the pooled sport test and the paper switch

# Nov 11 2026 picks audit: the per-rule tests need 240-1,000 bets each for a verdict, while the pooled evidence was plain:
# 383 graded picks outside the NBA realised -0.06 (se .06) of the edge their stakes assumed, and the pooled game-pick SPRT
# sat at LLR -5.5 with no single rule past its bound. Noah (Nov 11): every market outside the NBA goes PAPER until it
# beats the close live; the pooled test below sends any sport (the NBA too) to paper when it pauses.
POOLED_FROM = '2026-10-28T15:35:00Z'      # the paper book's reset (scripts/paper_rules.json registered)
PAPER = {'cbb': '2026-11-11T20:00:00Z', 'cfb': '2026-11-11T20:00:00Z', 'nfl': '2026-11-11T20:00:00Z',
         'nflprops': '2026-11-11T20:00:00Z'}
PAPER_GO = '2026-11-11T20:00:00Z'       # nothing flagged before the switch turns paper after the fact
PAPER_BACK = (30, 1.65)                   # back live: 30+ judged since paper, clvRet > 0 at day-clustered t this or more


def pooled(bets, sd=None, rho=None, P=None):
    """Wald's test of a sport's whole book: H1 every pick is worth the edge its stake sized on (evDU, at its own price),
    H0 worth nothing. Each game day adds sum(x mu - mu^2 / 2) / (sd^2 (1 + (n - 1) rho)); moneylines are out (their
    return is on another scale, as in drift()). Same bounds and minimum as drift (monitor_rules.json "pooled")."""
    P = P or params()
    D = P.get('pooled') or P['drift']
    rho = D.get('rho', 0.05) if rho is None else rho
    jc = sorted([b for b in bets if b.get('clvRet') is not None and b.get('mk') != 'ml' and (b.get('evDU') or 0) > 0],
                key=lambda b: b.get('kick') or '')
    xs = [b['clvRet'] for b in jc]
    if sd is None:
        sd = P['sdDefault']
        if len(xs) > 30:
            m0 = sum(xs) / len(xs)
            sd = max(sd, math.sqrt(sum((x - m0) ** 2 for x in xs) / (len(xs) - 1)))
    lo, hi = -math.log(D['B']), math.log(D['A'])
    days = {}
    for b in jc:
        days.setdefault(day(b['kick']), []).append(b)
    llr, n, state, at = 0.0, 0, 'watching', None
    for d in sorted(days):
        bs = days[d]
        n += len(bs)
        llr += sum(b['clvRet'] * b['evDU'] - b['evDU'] ** 2 / 2 for b in bs) / (sd * sd * (1 + (len(bs) - 1) * rho))
        if state == 'watching' and n >= D['minN']:
            if llr <= lo:
                state, at = 'paused', d
            elif llr >= hi:
                state, at = 'confirmed', d
    sxx = sum(b['evDU'] ** 2 for b in jc)
    real = sum(b['clvRet'] * b['evDU'] for b in jc) / sxx if sxx else None
    return {'n': n, 'days': len(days), 'llr': round(llr, 3), 'lo': round(lo, 3), 'hi': round(hi, 3), 'state': state,
            'at': at, 'sd': round(sd, 4), 'rho': rho, 'real': None if real is None else round(real, 3),
            'realSe': round(sd / math.sqrt(sxx), 3) if sxx else None,
            'clvRet': round(sum(xs) / len(xs), 4) if xs else None,
            'evDU': round(sum(b['evDU'] for b in jc) / len(jc), 4) if jc else None}


def paper_state(sport, log, P=None):
    """is the sport's book paper now: {'paper', 'since', 'why', 'back': the return test, 'pooled': the pooled test}.
    Paper from PAPER[sport] (Noah, Nov 11 2026), or from the day the pooled test pauses; back live once the picks judged
    since then beat the close at PAPER_BACK. log: every flagged pick (log + withdrawnLog)."""
    js = [e for e in log if judged(e) and (e.get('flagged') or '') >= POOLED_FROM]
    pl = pooled(js, P=P)
    since, why = PAPER.get(sport), 'owner: paper until live picks beat the close (Nov 11 2026)'
    if pl['state'] == 'paused' and (since is None or pl['at'] < since[:10]):
        since, why = pl['at'], f"pooled test paused: picks realised {pl['real']} of their staked edge over {pl['n']}"
    out = {'paper': False, 'since': since, 'why': None, 'pooled': pl}
    if since is None:
        return out
    bk = [e for e in log if judged(e) and e.get('clvRet') is not None and (e.get('flagged') or '') >= since]
    m, se, t, G = clustered([e['clvRet'] for e in bk], [day(e['kick']) for e in bk])
    back = len(bk) >= PAPER_BACK[0] and (m or 0) > 0 and (t or 0) >= PAPER_BACK[1]
    out['back'] = {'n': len(bk), 'clvRet': None if m is None else round(m, 4), 't': None if t is None else round(t, 2), 'days': G}
    out['paper'], out['why'] = not back, (None if back else why)
    return out


# ---------------------------------------------------------------- the pick rules' state (kept in games_picks_<sport>.json)

def pick_rules(R):
    """{rule id: (definition used for the clock, the full fit entry, the backtest record, label)} for one sport's rules
    (data/games_picks_rules.json 'sports'[sport]); the market rule owns the spread, its moneylines and the total"""
    out = {}
    for mk in ('spread', 'total'):
        r = (R.get('markets') or {}).get(mk) or {}
        if r.get('on') and r.get('x') is not None:
            out[mk] = ({'mk': mk, 'x': r['x'], 'k': r.get('k')}, r, r.get('heldRec'), f"{mk} {r['x']:g}+")
    for z in R.get('segments') or []:
        if z.get('on', True) and z.get('x') is not None:
            seg = f"{z['fam']}: {z['val']}"
            out[f"{z['mk']} | {seg}"] = ({'mk': z['mk'], 'seg': seg, 'x': z['x'], 'k': z.get('k')},
                                        {k: v for k, v in z.items() if k != 'vb'}, z.get('held'), f"{z['mk']} {z['x']:g}+ ({seg})")
    return out


def rule_of(e):
    """the rule id a logged pick belongs to"""
    mk = 'spread' if e['mk'] == 'ml' else e['mk']
    return f"{mk} | {e['seg']}" if e.get('seg') else mk


def bet(e):
    """a logged pick that was a bet: not pass (since Nov 4 2026, Noah: pass only when the model moved, so the model no
    longer clears the cut at the flagged line) and not a void (never played)"""
    return not e.get('pass') and not (e.get('void') or e.get('res') == 'void')


def judged(e):
    """a logged pick that counts toward its rule's tests (stop, drift): every pick the rule flagged that was played,
    passes included. A pass is a pick the model later left, and the model moves on news the line also moves on: passed
    picks were worth -3.4% at the close against -1.1% for the rest (NBA -5.8% against +2.6%), and whoever took the flag
    price cannot undo it. The stake calibration (units.live_pairs) counts the same picks. The displayed record and the
    bankroll stay the bets alone (bet())"""
    return not (e.get('void') or e.get('res') == 'void')


# k (the close's move per point of edge) is refit on every game model change and wanders in its third decimal (CBB
# total .378 -> .379 -> .376, spread .221 -> .216, Nov 3-5 2026). Keying the clock on its exact value restarted every
# CBB and NBA clock at each model PR, so the stop and drift tests never reached their 50 / 30 bets (CBB's first 147
# graded bets, -3.1% at the close, sat before the clocks). A clock now restarts when the market, segment or X changes,
# or k moves more than K_TOL of the k it started with.
K_TOL = 0.10


def same_rule(c, defn):
    """an existing clock c still stands for the rule defn (see K_TOL). Clocks from before Nov 5 2026 hold only the hash:
    matched by trying the k values within K_TOL at the three decimals k is written with"""
    k = defn.get('k')
    if 'x' in c:
        k0 = c.get('k0')
        return (c['x'] == defn.get('x') and c.get('seg') == defn.get('seg') and c.get('mk') == defn.get('mk')
                and (k == k0 or (k is not None and k0 is not None and abs(k - k0) <= K_TOL * abs(k0))))
    if k is None:
        return False
    span = int(abs(k) * K_TOL * 1000)
    return any(fp({**defn, 'k': round(k + j / 1000, 3)}) == c['hash'] for j in range(-span, span + 1))


# clocks the pre-Nov 5 2026 rule restarted on k noise alone, outside CBB (which was restored by hand on Nov 5): the rule's
# market, segment and X never changed and k stayed within K_TOL from these starts (replayed from the commit history of
# data/games_picks_rules.json under same_rule). Without them the CFB total test saw 2 of its graded picks, the NBA total
# 18 of 48. A floor applies only while the clock still stands for the same rule (x and k within K_TOL of the floor's k0).
CLOCK_FLOOR = {
    ('cfb', 'total'): ('2026-11-02T21:28:21Z', 0.162, 3.0),
    ('cfb', 'spread | line: 3-7'): ('2026-11-02T22:34:22Z', 0.102, 7.5),
    ('cfb', 'spread | line: 7-14'): ('2026-10-29T20:05:15Z', 0.131, 8.0),
    ('cfb', 'spread | role: favorite'): ('2026-10-28T02:43:16Z', 0.183, 8.0),
    ('cfb', 'spread | season: late'): ('2026-10-29T20:05:15Z', 0.132, 6.0),
    ('cfb', 'spread | venue: home'): ('2026-10-29T20:05:15Z', 0.114, 8.0),
    ('nba', 'total'): ('2026-10-28T02:11:55Z', 0.641, 3.0),
    ('nba', 'spread | line: 9-15'): ('2026-11-01T21:37:43Z', 0.198, 3.0),
    ('nfl', 'spread'): ('2026-10-28T02:43:16Z', 0.348, 4.0),
}


def live_from(sport):
    """the stamp a sport's live picks count from (units.LIVE_FROM), None when it has none"""
    import units as DU
    return DU.LIVE_FROM.get(sport)


def floored(sport, i, c, defn):
    """clock c with its start moved back to CLOCK_FLOOR's when the floor stands for the same rule"""
    f = CLOCK_FLOOR.get((sport, i))
    if not f or c.get('since', '') <= f[0]:
        return c
    since, k0, x = f
    k = defn.get('k')
    if defn.get('x') != x or c.get('x') != x or k is None or abs(k - k0) > K_TOL * abs(k0):
        return c
    return {**c, 'since': since, 'k0': k0}


def legacy_k(c, defn):
    """the k an old hash-only clock was started with (same_rule's search), else defn's"""
    k = defn.get('k')
    if k is None:
        return None
    span = int(abs(k) * K_TOL * 1000)
    for j in range(-span, span + 1):
        if fp({**defn, 'k': round(k + j / 1000, 3)}) == c['hash']:
            return round(k + j / 1000, 3)
    return k


def pick_state(sport, RS, log, old, stamp, P=None):
    """clocks and stops for one sport's pick rules: (state, stopped ids). old: the state games_picks.py kept last run;
    log: every flagged pick (the log and the withdrawn picks kept beside it).
    A rule's clock restarts when its market, segment or X changes or k moves past K_TOL, and only that clears a stop
    (Nov 5 2026: a refit that re-tests the rule is one that changes it; before, any refit whose fit entry moved, which
    every game model PR does, cleared the stop, so a stop rarely outlived the next merge)."""
    P = P or params()
    old = old or {}
    clocks, stops = dict(old.get('clocks') or {}), dict(old.get('stopped') or {})
    rules = pick_rules(RS)
    since0 = (RS.get('_asof') or stamp)[:10]
    checks = {}
    for i, (defn, full, held, _) in rules.items():
        h, fh = fp(defn), fp(full)
        c = clocks.get(i)
        rule = {'mk': defn.get('mk'), 'x': defn.get('x'), **({'seg': defn['seg']} if defn.get('seg') else {})}
        if c is None or (c['hash'] != h and not same_rule(c, defn)):
            clocks[i] = {'hash': h, 'since': since0 if c is None else stamp, **rule, 'k0': defn.get('k')}
            stops.pop(i, None)
        elif 'x' not in c or c['hash'] != h:
            # the same rule (k within K_TOL): the clock keeps its start; it records the rule and the k it began with
            clocks[i] = {**c, 'hash': h, **rule, 'k0': c['k0'] if 'k0' in c else legacy_k(c, defn)}
        clocks[i] = floored(sport, i, clocks[i], defn)
        lf = live_from(sport)
        if lf and clocks[i].get('since', '') < lf:
            # the sport's live record restarts (units.LIVE_FROM): the clock moves up and a stop on the older picks clears
            clocks[i] = {**clocks[i], 'since': lf}
            stops.pop(i, None)
        bs = [e for e in log if judged(e) and rule_of(e) == i and (e.get('flagged') or '') >= clocks[i]['since']]
        mu1, rho = expected_live(sport, held), rho_for(sport, defn['mk'], held)
        d = decide(bs, sd_of(held), P, mu1, rho)
        dr = drift(bs, mu1, sd_of(held), rho, P)
        d = {**d, 'drift': {k: v for k, v in dr.items() if k != 'path'}}
        if dr['state'] == 'paused':
            w = (f"drift test: live worth {dr['real']:.2f} of the backtest's expected edge over {dr['n']} bets, "
                 f"{P['drift']['B']}x likelier no edge than the backtest's")
            d = {**d, 'stop': True, 'why': '; '.join(x for x in (d['why'], w) if x), 'test': 'drift'}
        checks[i] = d
        if d['stop'] and i not in stops:
            stops[i] = {'at': stamp, 'n': d['n'], 't': d['t'], 'cusum': d['cusum'], 'why': d['why'], 'fit': fh,
                        'test': d.get('test', 'close')}
    return {'clocks': clocks, 'stopped': stops, 'checks': checks}, set(stops)


# ---------------------------------------------------------------- the report

def summary(bs, now, P, sd=None, exp=None, weights=None):
    jc = [b for b in bs if b.get('clvRet') is not None]
    days = [day(b.get('kick') or b.get('k')) for b in jc]
    m, se, t, G = clustered([b['clvRet'] for b in jc], days)
    beat = [b['beat'] for b in jc if b.get('beat') is not None]
    st = [b for b in bs if b.get('res') in ('w', 'l', 'p')]
    rets = [b['ret'] if 'ret' in b else b.get('profit', 0.0) for b in st]
    cut = (now - datetime.timedelta(days=P['weekDays'])).date().isoformat()
    wk = [b for b, d in zip(jc, days) if d >= cut]
    wm, _, wt, _ = clustered([b['clvRet'] for b in wk], [day(b.get('kick') or b.get('k')) for b in wk])
    out = {'n': len(bs), 'clvN': len(jc), 'clvRet': None if m is None else round(m, 4), 'clvT': None if t is None else round(t, 2),
           'days': G, 'beat': round(sum(1 for x in beat if x > 0) / len(beat), 3) if beat else None,
           'settled': len(st), 'w': sum(1 for b in st if b['res'] == 'w'), 'l': sum(1 for b in st if b['res'] == 'l'),
           'roi': round(sum(rets) / len(rets), 4) if rets else None,
           'week': {'n': len(wk), 'clvRet': None if wm is None else round(wm, 4), 'clvT': None if wt is None else round(wt, 2)}}
    if exp and exp.get('clvRet') is not None:
        e = exp['clvRet']
        out['exp'] = {'clvRet': e, 'beat': exp.get('beat'), 'roi': exp.get('roi'), 'n': exp.get('clvN') or exp.get('n')}
        # live against the backtest: the gap over the live record's clustered se (the backtest's own se when the live
        # record is too thin to have one)
        s = se if se else ((sd or P['sdDefault']) / math.sqrt(len(jc)) if jc else None)
        if m is not None and s:
            z = (m - e) / s
            out['vsExp'] = {'gap': round(m - e, 4), 'z': round(z, 2),
                            'read': 'below the backtest' if z <= -P['zFlag'] else 'above the backtest' if z >= P['zFlag'] else 'in line'}
    return out


def build(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    P = params()
    try:
        RJ = json.load(open(os.path.join(ROOT, 'data', 'games_picks_rules.json')))
    except (OSError, ValueError):
        RJ = {'sports': {}}
    import units as DU
    rows, du_rows = [], []
    for s in SPORTS:
        try:
            gp = json.load(open(os.path.join(ROOT, 'data', f'games_picks_{s}.json')))
        except (OSError, ValueError):
            gp = {}
        log = gp.get('log', [])
        mon = gp.get('monitor') or {}
        RS = RJ['sports'].get(s) or {}
        rules = pick_rules(RS)
        ids = list(rules) + [i for i in (mon.get('stopped') or {}) if i not in rules]
        for i in ids:
            defn, full, held, label = rules.get(i, (None, None, None, i))
            since = ((mon.get('clocks') or {}).get(i) or {}).get('since') or (RJ.get('asof') or '')[:10]
            # the record shown is the bets; the tests count every flagged pick (judged())
            bs = [e for e in log if bet(e) and rule_of(e) == i and (e.get('flagged') or '') >= since]
            bt = [e for e in log + gp.get('withdrawnLog', []) if judged(e) and rule_of(e) == i and (e.get('flagged') or '') >= since]
            sd = sd_of(held)
            mu1, rho = expected_live(s, held), rho_for(s, (defn or {}).get('mk') or i.split(' | ')[0], held)
            chk = (mon.get('checks') or {}).get(i) or decide(bt, sd, P, mu1, rho)
            stop = (mon.get('stopped') or {}).get(i)
            dr = drift(bt, mu1, sd, rho, P)
            rows.append({'id': f'pick:{s}:{i}', 'book': 'picks', 'sport': s, 'label': f"{s.upper()} {label}", 'since': since[:10],
                         'status': 'stopped' if stop else ('on' if i in rules else 'off'), 'stopped': stop,
                         **summary(bs, now, P, sd, held), 'check': chk, 'drift': dr})
        # Dengler Units on the same picks: close value weighted by stake against flat, and against the edge DU staked on
        for mk in ('spread', 'total'):
            bs = [e for e in log if bet(e) and ('spread' if e['mk'] == 'ml' else e['mk']) == mk and e.get('clvRet') is not None and e.get('units')]
            if not bs and mk not in {d['mk'] for d, *_ in rules.values()}:
                continue
            days = [day(e['kick']) for e in bs]
            u = [e['units'] for e in bs]
            wm, _, wt, _ = clustered([e['clvRet'] for e in bs], days, u)
            fm, _, _, _ = clustered([e['clvRet'] for e in bs], days)
            dp = DU.params(s, mk)
            ex = [DU.edge(dp, e.get('ev') or 0.0, e.get('edge'))[0] for e in bs]
            em = sum(a * b for a, b in zip(u, ex)) / sum(u) if bs else None
            du_rows.append({'sport': s, 'mk': mk, 'label': f"{s.upper()} {mk}", 'n': len(bs), 'du': round(sum(u), 2),
                            'clvRet': None if wm is None else round(wm, 4), 'clvT': None if wt is None else round(wt, 2),
                            'flat': None if fm is None else round(fm, 4), 'adds': None if wm is None or fm is None else round(wm - fm, 4),
                            'expEdge': None if em is None else round(em, 4), 'basis': dp.get('basis')})
    try:
        pb = json.load(open(os.path.join(ROOT, 'data', 'paper_book.json')))
    except (OSError, ValueError):
        pb = {}
    try:
        seed = json.load(open(os.path.join(ROOT, 'data', 'paper_seed.json')))['rules']
    except (OSError, ValueError, KeyError):
        seed = {}
    ledger = pb.get('ledger', [])
    for r in pb.get('rules', []):
        i = r['id']
        since = ((pb.get('clocks') or {}).get(i) or {}).get('since') or pb.get('registered') or ''
        bs = [b for b in ledger if b['rule'] == i and b['placed'] >= since]
        sd_ = seed.get(i) or {}
        exp = sd_.get('clean') if (sd_.get('clean') or {}).get('clvRet') is not None else sd_
        exp = {**exp, 'beat': exp.get('beat', sd_.get('beat')), 'roi': exp.get('roi', sd_.get('roi'))} if exp else None
        sd = sd_of(exp)
        rows.append({'id': f'paper:{i}', 'book': 'paper', 'sport': r['sport'], 'label': r['label'], 'since': since[:10],
                     'status': r.get('status', 'on'), 'stopped': (pb.get('killed') or {}).get(i),
                     **summary(bs, now, P, sd, exp), 'check': decide(bs, sd, P)})
    import units as DU
    out = {'asof': stamp, 'pre': {**{k: P[k] for k in ('registered', 'window', 'minN', 'minDays', 't', 'cusum', 'weekDays', 'zFlag', 'drift') if k in P},
                                  'timing': DU.TIMING, 'leak': DU.LEAK},
           'rules': rows, 'du': du_rows,
           'stopped': [x['id'] for x in rows if x['status'] == 'stopped'],
           'flags': [x['id'] for x in rows if (x.get('vsExp') or {}).get('read') == 'below the backtest'],
           'drift': {st: [x['id'] for x in rows if (x.get('drift') or {}).get('state') == st] for st in ('watching', 'confirmed', 'paused')}}
    old = {}
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        pass
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in out.items() if k != 'asof'})):
        return print('rule monitor: no change')
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1, allow_nan=False)
    print(f"rule monitor: {len(rows)} rules, {len(out['stopped'])} stopped, {len(out['flags'])} below their backtest")


# ---------------------------------------------------------------- self-check

def test():
    import random
    P = params()
    rnd = random.Random(3)
    k0 = datetime.datetime(2026, 11, 1, 23, tzinfo=datetime.timezone.utc)

    def bets(mu, n, per=4):
        return [{'kick': (k0 + datetime.timedelta(days=i // per)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'clvRet': rnd.gauss(mu, 0.12)} for i in range(n)]
    # clustered se: equal weights, one bet a cluster is the plain se (x G/(G-1))
    xs = [0.1, -0.05, 0.02, 0.07]
    m, se, t, G = clustered(xs, ['a', 'b', 'c', 'd'])
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / 3)
    assert abs(se - sd / 2) < 1e-9 and G == 4, (se, sd)
    # never under the iid se: 60 bets on 3 game days whose day means agree read t -19 clustered, -3.7 floored; under
    # minDays game days the t carries no verdict; Student's cdf
    xs = [-0.05 + 0.1 * ((i % 7) - 3) / 3 for i in range(60)]
    gs = ['abc'[i // 20] for i in range(60)]
    m, se, t, G = clustered(xs, gs)
    iid = math.sqrt(sum((x - m) ** 2 for x in xs) / 59 / 60)
    assert G == 3 and abs(se - iid) < 1e-12 and t_p(t, G, P) is None and t_p(t, 8, P) is not None, (se, iid)
    assert abs(t_cdf(-1.0, 2) - 0.21132) < 1e-4 and abs(t_cdf(-2.262, 9) - 0.025) < 1e-4 and abs(t_cdf(1.0, 2) - 0.78868) < 1e-4
    # a pick rule (rho passed): the window's t is not a stop, and a slate that moved together counts as the bets it is
    # worth. 60 bets on 3 days at -3%: the zero test's old cut (t < -1) would have stopped it
    sl3 = [{'kick': (k0 + datetime.timedelta(days=i // 20)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'clvRet': -0.03 + 0.1 * ((i % 7) - 3) / 3} for i in range(60)]
    d = decide(sl3, 0.12, P, 0.015, 0.06)
    assert d['t'] < -1 and d['p'] is None and not d['stop'] and d['edge']['h'] == P['cusum']['hL'], d
    # the day's deflation: one day of 20 bets at rho .1 adds its sum over 2.9
    S1, _, _ = cusum_days([[-0.12] * 20], 0.12, 0.25, 99, 0.1)
    assert abs(S1 - 20 * 0.75 / 2.9) < 1e-9, S1
    assert abs(day_llr([0.02, 0.0], 0.02, 0.1, 0.5) - 0.0) < 1e-12 and cusum_llr([[0.0] * 10] * 3, 0.02, 0.1, 0.0, 0.5, 20)[2] == 30
    # at the edge its stakes assume a pick rule runs on (false stops over 600 bets: rare); worth nothing or losing, it stops
    pk = lambda mu, n: decide(bets(mu, n), 0.12, P, 0.015, 0.0)
    fe = sum(pk(0.015, 600)['stop'] for _ in range(100)) / 100
    assert fe <= 0.08, fe
    assert sum('hitAt' in pk(0.0, 1500)['edge'] for _ in range(40)) >= 28
    d = pk(-0.06, 200)
    assert d['stop'] and d['hitAt'] <= 120, d
    # too few bets never stop; a rule at its edge doesn't stop; one losing half an sd a bet does, quickly
    assert not decide(bets(-0.2, 30), 0.12, P)['stop']
    assert not decide(bets(0.03, 600), 0.12, P)['stop']
    d = decide(bets(-0.06, 120), 0.12, P)
    assert d['stop'] and 'CUSUM' in d['why'], d
    # the zero test (no rho): false alarms for a rule exactly at the close over 300 bets
    fa = sum(decide(bets(0.0, 300), 0.12, P)['stop'] for _ in range(200)) / 200
    assert fa < 0.5, fa
    # a slow bleed the CUSUM misses, the window t catches
    d = decide(bets(-0.025, 300), 0.12, P)
    assert d['t'] is not None
    # the pick-rule state: a stop sticks through runs and through refits that leave the rule alone; a new X clears it
    RS = {'markets': {'total': {'on': True, 'x': 5.5, 'k': 0.6, 'heldRec': {'clvRet': 0.1, 'clvT': 10, 'n': 186}}}, '_asof': '2026-11-01'}
    log = [{'mk': 'total', 'flagged': '2026-11-01T12:00:00Z', 'kick': b['kick'], 'clvRet': b['clvRet'] - 0.1} for b in bets(0.0, 120)]
    st, off = pick_state('nba', RS, log, {}, '2026-11-30T00:00:00Z', P)
    assert off == {'total'}, st['checks']
    st2, off2 = pick_state('nba', RS, log, st, '2026-12-01T00:00:00Z', P)
    assert off2 == {'total'} and st2['stopped']['total']['at'] == '2026-11-30T00:00:00Z'
    RS2 = {**RS, 'markets': {'total': {**RS['markets']['total'], 'heldRec': {'clvRet': 0.09, 'clvT': 9, 'n': 200}}}}
    st3, off3 = pick_state('nba', RS2, log, st2, '2026-12-02T00:00:00Z', P)
    assert off3 == {'total'} and st3['clocks']['total']['since'] == st2['clocks']['total']['since'], st3['clocks']
    RS3 = {**RS, 'markets': {'total': {**RS['markets']['total'], 'x': 6.0}}}
    st4, off4 = pick_state('nba', RS3, log, st2, '2026-12-03T00:00:00Z', P)
    assert not off4 and st4['clocks']['total']['since'] == '2026-12-03T00:00:00Z'
    # k refit noise keeps the clock (and the stop); a real move in k restarts it; an old hash-only clock is matched
    RSk = lambda k: {**RS, 'markets': {'total': {**RS['markets']['total'], 'k': k}}}
    s0, _ = pick_state('nba', RS, [], {}, '2026-11-02T00:00:00Z', P)
    s1, _ = pick_state('nba', RSk(0.603), [], s0, '2026-11-03T00:00:00Z', P)
    assert s1['clocks']['total']['since'] == '2026-11-01' and s1['clocks']['total']['k0'] == 0.6, s1['clocks']
    s2, _ = pick_state('nba', RSk(0.59), [], s1, '2026-11-04T00:00:00Z', P)
    assert s2['clocks']['total']['since'] == '2026-11-01', s2['clocks']
    s3, _ = pick_state('nba', RSk(0.7), [], s2, '2026-11-05T00:00:00Z', P)
    assert s3['clocks']['total']['since'] == '2026-11-05T00:00:00Z' and s3['clocks']['total']['k0'] == 0.7, s3['clocks']
    # CLOCK_FLOOR: a k-noise restart is moved back to the floor while the rule is the floor's; X past it is not
    RSf = lambda x, k: {**RS, 'markets': {'total': {**RS['markets']['total'], 'x': x, 'k': k}}}
    f0, _ = pick_state('nba', RSf(3.0, 0.637), [], {'clocks': {'total': {'hash': 'h', 'since': '2026-11-05T02:15:12Z', 'mk': 'total', 'x': 3.0, 'k0': 0.637}}}, '2026-11-11T00:00:00Z', P)
    assert f0['clocks']['total']['since'] == CLOCK_FLOOR[('nba', 'total')][0], f0['clocks']
    f1, _ = pick_state('nba', RSf(3.5, 0.637), [], f0, '2026-11-12T00:00:00Z', P)
    assert f1['clocks']['total']['since'] == '2026-11-12T00:00:00Z', f1['clocks']
    old = {'clocks': {'total': {'hash': fp({'mk': 'total', 'x': 5.5, 'k': 0.6}), 'since': '2026-10-21'}}}
    s4, _ = pick_state('nba', RSk(0.598), [], old, '2026-11-06T00:00:00Z', P)
    assert s4['clocks']['total']['since'] == '2026-10-21' and s4['clocks']['total']['k0'] == 0.6, s4['clocks']
    stk, offk = pick_state('nba', {**RS, 'markets': {'total': {**RS['markets']['total'], 'k': 0.601}}}, log, st2, '2026-12-04T00:00:00Z', P)
    # a k-only refit inside the band is not a re-test: the stop stays; k past the band clears it and restarts the clock
    assert offk == {'total'} and stk['stopped']['total']['at'] == '2026-11-30T00:00:00Z', stk['stopped']
    stj, offj = pick_state('nba', RSk(0.7), log, st2, '2026-12-05T00:00:00Z', P)
    assert not offj and stj['clocks']['total']['since'] == '2026-12-05T00:00:00Z', stj['clocks']
    # the drift test: a rule worth nothing pauses, one worth its backtest confirms, and a pause stops the rule
    def wk(mu, n, per=18):
        return [{'kick': (k0 + datetime.timedelta(days=7 * (i // per))).strftime('%Y-%m-%dT%H:%M:%SZ'), 'clvRet': rnd.gauss(mu, 0.123)} for i in range(n)]
    runs = [drift(wk(0.0, 1000), 0.018, 0.123, 0.0, P)['state'] for _ in range(100)]
    assert runs.count('paused') >= 85, runs.count('paused')
    runs = [drift(wk(0.018, 1000), 0.018, 0.123, 0.0, P)['state'] for _ in range(100)]
    assert runs.count('paused') <= 12 and runs.count('confirmed') >= 80, (runs.count('paused'), runs.count('confirmed'))
    assert drift(wk(-0.3, 20), 0.018, 0.123, 0.0, P)['state'] == 'watching'          # minN
    assert drift(wk(0.0, 50), None, 0.123, 0.0, P)['state'] == 'no test'
    d = drift([{'kick': '2026-11-07T20:00:00Z', 'clvRet': 0.02}, {'kick': '2026-11-07T21:00:00Z', 'clvRet': 0.0}], 0.02, 0.1, 0.5, P)
    assert abs(d['llr'] - (0.02 - 0.02) * 0.02 / (0.01 * 1.5)) < 1e-9, d
    RSd = {'markets': {'total': {'on': True, 'x': 2.5, 'k': 0.2, 'heldRec': {'clvRet': 0.036, 'clvT': 9.2, 'n': 983}}}, '_asof': '2026-11-01'}
    logd = [{'mk': 'total', 'flagged': '2026-11-01T15:00:00Z', 'kick': b['kick'], 'clvRet': b['clvRet']} for b in wk(-0.005, 600)]
    st5, off5 = pick_state('cfb', RSd, logd, {}, '2026-12-30T00:00:00Z', P)
    assert off5 == {'total'} and st5['stopped']['total']['test'] == 'drift', st5['checks']['total']
    # pass picks (the model moved before the start) were flagged at a line someone could take: they count toward the
    # tests like any pick, as do withdrawn ones; a void (never played) does not
    st6, off6 = pick_state('nba', RS, [{**e, 'pass': True} for e in log], {}, '2026-11-30T00:00:00Z', P)
    assert off6 == {'total'} and st6['checks']['total']['n'] == len(log), st6['checks']['total']
    assert judged({'pass': True}) and judged({'withdrawn': 'x'}) and not bet({'pass': True}) and not judged({'res': 'void'})
    st7, _ = pick_state('nba', RS, [{**e, 'void': True} for e in log], {}, '2026-11-30T00:00:00Z', P)
    assert st7['checks']['total']['n'] == 0, st7['checks']['total']
    print('rule monitor: ok, false-alarm share at the close over 300 bets', fa)


def restore_clock(sport, rule, since, k0):
    """set one pick rule's clock start in data/games_picks_<sport>.json (and the k it started with); the next
    games_picks.py run judges every pick since then. Re-apply after a merge conflict on the picks file:
        python3 scripts/rule_monitor.py --restore-clock cbb spread 2026-11-01T00:09:20Z 0.221
        python3 scripts/rule_monitor.py --restore-clock cbb total 2026-11-01T00:50:25Z 0.378
        python3 scripts/games_picks.py cbb && python3 scripts/rule_monitor.py && python3 scripts/paper_book.py"""
    fn = os.path.join(ROOT, 'data', f'games_picks_{sport}.json')
    d = json.load(open(fn))
    R = json.load(open(os.path.join(ROOT, 'data', 'games_picks_rules.json')))['sports'][sport]
    defn = pick_rules(R)[rule][0]
    c = (d.setdefault('monitor', {}).setdefault('clocks', {})).get(rule) or {}
    d['monitor']['clocks'][rule] = {**c, 'hash': fp(defn), 'since': since, 'mk': defn['mk'], 'x': defn['x'],
                                    **({'seg': defn['seg']} if defn.get('seg') else {}), 'k0': float(k0)}
    with open(fn, 'w') as f:
        json.dump(d, f, indent=1, allow_nan=False)
    print(f'{sport} {rule}: clock from {since} (k0 {k0})')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--test':
        test()
    elif a and a[0] == '--restore-clock' and len(a) == 5:
        restore_clock(*a[1:])
    else:
        sys.path.insert(0, HERE)
        build()
