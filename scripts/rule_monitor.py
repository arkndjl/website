#!/usr/bin/env python3
"""The live rule monitor (Oct 21 2026): every rule that bets, checked against the closing line as it goes, and stopped
when it is losing to the close. Stdlib only.

    python3 scripts/rule_monitor.py          # data/rule_monitor.json: the report on the Predictions page
    python3 scripts/rule_monitor.py --test   # self-check

What it covers: the Predictions pick rules (each sport's market rule and each kept segment, scripts/games_picks.py),
Dengler Units on top of them (does sizing add: close value weighted by stake against flat), and the paper book rules
(scripts/paper_book.py). For each: n judged by the close, close value (clvRet) with a t clustered by game day, how often
the line moved our way, flat ROI, the last week alone, and the live record against what the backtest expected.

The switch (scripts/monitor_rules.json, pre-registered): with minN+ bets judged since the rule's clock started, a rule
stops when its last `window` bets are worth clustered t below `t` at the close, or when a one-sided CUSUM on close
value (z = clvRet / the rule's backtest sd, S = max(0, S - z - k)) crosses h. decide() is the one test; games_picks.py
and paper_book.py call it where the bets are made and keep the stop with the rule, and this report reads their state.
A stopped rule comes back only by a refit, which restarts its clock.
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
    """weighted mean with a cluster-robust standard error (CR1, one cluster a game day): (mean, se, t, clusters)"""
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
    return m, se, (m / se if se else None), G


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


def decide(bets, sd=None, P=None):
    """the one test. bets: dicts with kick (or k) and clvRet, any order; sd the rule's backtest sd of close value.
    Returns the window's clustered stats, the CUSUM and stop (True when the rule should stop now) with why"""
    P = P or params()
    jc = sorted([b for b in bets if b.get('clvRet') is not None], key=lambda b: b.get('kick') or b.get('k'))
    xs = [b['clvRet'] for b in jc]
    sd = sd or P['sdDefault']
    w = jc[-P['window']:]
    m, se, t, G = clustered([b['clvRet'] for b in w], [day(b.get('kick') or b.get('k')) for b in w])
    S, top, hit = cusum(xs, sd, P['cusum']['k'], P['cusum']['h'])
    why = []
    if len(jc) >= P['minN']:
        if t is not None and t < P['t']:
            why.append(f"last {len(w)} worth t {t:.2f} at the close")
        if S >= P['cusum']['h']:
            why.append(f"CUSUM {S:.1f} past {P['cusum']['h']:g}")
    return {'n': len(jc), 'window': len(w), 'mean': None if m is None else round(m, 4), 't': None if t is None else round(t, 2),
            'days': G, 'sd': round(sd, 4), 'cusum': round(S, 2), 'cusumMax': round(top, 2), 'h': P['cusum']['h'],
            'stop': bool(why), 'why': '; '.join(why)}


# ---------------------------------------------------------------- the drift test: is a rule worth what its backtest said?

def expected_live(sport, held):
    """the close value a rule's live picks should be worth if its backtest holds: the held-out record's clvRet times the
    haircuts the stakes already take (units.TIMING: live picks are bet after part of the open's move; units.LEAK: NBA
    history saw news the open did not). None when the backtest has no positive record to test against"""
    if not held or not (held.get('clvRet') or 0) > 0:
        return None
    import units as DU
    return held['clvRet'] * DU.TIMING * DU.LEAK.get(sport, 1.0)


def rho_for(sport, mk):
    try:
        import units as DU
        return max(0.0, DU.params(sport, mk).get('rho') or 0.0)
    except Exception:
        return 0.0


def drift(bets, mu1, sd=None, rho=0.0, P=None):
    """Wald's sequential test of "the rule is worth its backtest" (mean close value mu1, the edge its stakes assume)
    against "the rule is worth nothing" (0: the backtest was overfit). Each game day adds its log likelihood ratio
    (s - n mu1 / 2) mu1 / (sd^2 (1 + (n - 1) rho)), s the day's summed clvRet over n bets, rho the within-slate
    correlation. In game-day order, the first crossing decides: down past -ln(B) pauses the rule, up past ln(A)
    confirms it and retires the test (the close switch in decide() still runs). Since LLR = (sum e^2 / sd^2) x
    (r - 1/2) with r the realization rate (live close value over mu1, here r = mean / mu1), the test is the same as
    asking whether the rule realises more or less than half its expected edge, with a margin that shrinks as bets come in."""
    P = P or params()
    D = P['drift']
    sd = sd or P['sdDefault']
    jc = sorted([b for b in bets if b.get('clvRet') is not None], key=lambda b: b.get('kick') or b.get('k'))
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
        llr += (sum(xs) - m * mu1 / 2) * mu1 / (sd * sd * (1 + (m - 1) * rho))
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


def pick_state(sport, RS, log, old, stamp, P=None):
    """clocks and stops for one sport's pick rules: (state, stopped ids). old: the state games_picks.py kept last run.
    A rule's clock restarts when its X or k changes; a stop clears when a refit changes the rule or re-tests it."""
    P = P or params()
    old = old or {}
    clocks, stops = dict(old.get('clocks') or {}), dict(old.get('stopped') or {})
    rules = pick_rules(RS)
    since0 = (RS.get('_asof') or stamp)[:10]
    checks = {}
    for i, (defn, full, held, _) in rules.items():
        h, fh = fp(defn), fp(full)
        c = clocks.get(i)
        if c is None or c['hash'] != h:
            clocks[i] = {'hash': h, 'since': since0 if c is None else stamp}
            stops.pop(i, None)
        elif i in stops and stops[i].get('fit') != fh:
            clocks[i] = {'hash': h, 'since': stamp}
            stops.pop(i)
        bs = [e for e in log if rule_of(e) == i and (e.get('flagged') or '') >= clocks[i]['since']]
        d = decide(bs, sd_of(held), P)
        dr = drift(bs, expected_live(sport, held), sd_of(held), rho_for(sport, defn['mk']), P)
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
            bs = [e for e in log if rule_of(e) == i and (e.get('flagged') or '') >= since]
            sd = sd_of(held)
            chk = (mon.get('checks') or {}).get(i) or decide(bs, sd, P)
            stop = (mon.get('stopped') or {}).get(i)
            dr = drift(bs, expected_live(s, held), sd, rho_for(s, (defn or {}).get('mk') or i.split(' | ')[0]), P)
            rows.append({'id': f'pick:{s}:{i}', 'book': 'picks', 'sport': s, 'label': f"{s.upper()} {label}", 'since': since[:10],
                         'status': 'stopped' if stop else ('on' if i in rules else 'off'), 'stopped': stop,
                         **summary(bs, now, P, sd, held), 'check': chk, 'drift': dr})
        # Dengler Units on the same picks: close value weighted by stake against flat, and against the edge DU staked on
        for mk in ('spread', 'total'):
            bs = [e for e in log if ('spread' if e['mk'] == 'ml' else e['mk']) == mk and e.get('clvRet') is not None and e.get('units')]
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
    out = {'asof': stamp, 'pre': {**{k: P[k] for k in ('registered', 'window', 'minN', 't', 'cusum', 'weekDays', 'zFlag', 'drift')},
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
    # too few bets never stop; a rule at its edge doesn't stop; one losing half an sd a bet does, quickly
    assert not decide(bets(-0.2, 30), 0.12, P)['stop']
    assert not decide(bets(0.03, 600), 0.12, P)['stop']
    d = decide(bets(-0.06, 120), 0.12, P)
    assert d['stop'] and 'CUSUM' in d['why'], d
    # false alarms for a rule exactly at the close over 300 bets: rare
    fa = sum(decide(bets(0.0, 300), 0.12, P)['stop'] for _ in range(200)) / 200
    assert fa < 0.5, fa
    # a slow bleed the CUSUM misses, the window t catches
    d = decide(bets(-0.025, 300), 0.12, P)
    assert d['t'] is not None
    # the pick-rule state: a stop sticks through runs, clears on a refit that re-tests the rule, restarts on a new X
    RS = {'markets': {'total': {'on': True, 'x': 5.5, 'k': 0.6, 'heldRec': {'clvRet': 0.1, 'clvT': 10, 'n': 186}}}, '_asof': '2026-11-01'}
    log = [{'mk': 'total', 'flagged': '2026-11-01T12:00:00Z', 'kick': b['kick'], 'clvRet': b['clvRet'] - 0.1} for b in bets(0.0, 120)]
    st, off = pick_state('nba', RS, log, {}, '2026-11-30T00:00:00Z', P)
    assert off == {'total'}, st['checks']
    st2, off2 = pick_state('nba', RS, log, st, '2026-12-01T00:00:00Z', P)
    assert off2 == {'total'} and st2['stopped']['total']['at'] == '2026-11-30T00:00:00Z'
    RS2 = {**RS, 'markets': {'total': {**RS['markets']['total'], 'heldRec': {'clvRet': 0.09, 'clvT': 9, 'n': 200}}}}
    st3, off3 = pick_state('nba', RS2, log, st2, '2026-12-02T00:00:00Z', P)
    assert not off3 and st3['clocks']['total']['since'] == '2026-12-02T00:00:00Z'
    RS3 = {**RS, 'markets': {'total': {**RS['markets']['total'], 'x': 6.0}}}
    st4, off4 = pick_state('nba', RS3, log, st2, '2026-12-03T00:00:00Z', P)
    assert not off4 and st4['clocks']['total']['since'] == '2026-12-03T00:00:00Z'
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
    print('rule monitor: ok, false-alarm share at the close over 300 bets', fa)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--test':
        test()
    else:
        sys.path.insert(0, HERE)
        build()
