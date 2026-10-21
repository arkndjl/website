#!/usr/bin/env python3
"""Picks for every sport (Noah, Oct 21 2026): the games page and each sport's picks tab show these same rows.

    python3 scripts/games_picks.py --rules         # data/games_picks_rules.json: X per sport and market (after --fit)

The rule: the model's side wherever it sits X+ points off the line, X per sport and market set on the tuning seasons by
closing line value (scripts/clv.py), a market on only where its held-out picks beat the close. One pick a game: the
spread, the moneyline on that side, or the total, whichever expects the most at the calibrated chance (the close
assumed to move k points per point of edge, k from that market's held-out picks); stakes in Dengler Units (DU,
scripts/units.py; 1 DU = 1% of bankroll), refit at the end of --rules. See fit_rules(). The expected-return calibration
below (--fit) now only supplies the caps and slopes.

Earlier design, kept for --fit: every bet on the board (each side of the spread,
the moneyline, the over and the under) priced by a calibrated chance, ranked by expected return, sized by Kelly.

    python3 scripts/games_picks.py --fit           # data/games_picks_fit.json (numpy), from the walk-forward files
    python3 scripts/games_picks.py nfl             # live picks for one sport (stdlib): data/games_picks_nfl.json
                                                   # (cfb, nfl, cbb, nba; run after that sport's game build)

The walk-forward files, one per sport (scripts/games_wf/; re-run after a sport's model changes, then --fit):
    node scripts/games_wf/cfb_wf.mjs md.json.gz scripts/data/games_wf/cfb.json.gz [espn_odds.json]
                                         # the "cfb game research" workflow's model-input dump; season-swap folds
    python3 scripts/games_wf/nfl_wf.py   # the live model's walk (nflverse), 2015 on
    python3 scripts/nba_games.py --fit && python3 scripts/games_wf/nba_wf.py
    python3 scripts/games_wf/cbb_wf.py   # the committed tuning (2016-20) walked forward, 2016 on

Calibration. Each sport's game model already has a walk-forward history: every past game predicted by weights fit only
on the seasons before it (scripts/data/games_wf/<sport>.json.gz; how each was made is in that sport's notes below).
For each market the chance a bet wins is a logistic on the model's disagreement with the line, with the market's own
no-vig price as the offset:

    logit P(home covers)  = logit q(spread prices) + b * (model margin - line)
    logit P(home wins)    = logit q(moneylines)    + b * (model margin - line)
    logit P(over)         = logit q(total prices)  + b * (model total - total)

b = 0 is the market itself; b is fit, in each test season, on the seasons before it, so b says how much of the model's
disagreement with the closing line has held up. No intercept: a home or favorite lean in the past is not a bet. Expected
return = P x payout - (1 - P) at the price on the board.

Thresholds. A market is bet when its expected return clears a cut. The cut is chosen on the tuning seasons only (the
cut with the best return there, 40+ bets and t >= 1); a market whose best cut doesn't reach that is off. The seasons
after the tuning ones never touched the cut or the fit and are the held-out record shown on the page. One side bet per
game (the spread or the moneyline, whichever expects more) and one total.

Units: the Kelly stake at the calibrated chance over the average Kelly stake of that market's backtest bets, clipped
0.25-3 and rounded to quarters, so the average pick is 1 unit. Live picks are logged at the line and price when first
flagged and graded from ESPN's final score.

Judged by the close first (Oct 21 2026, scripts/clv.py): each graded pick gets the points the line moved its way and the
return it was worth at the closing line (clvRet); the record leads with those, ROI second. Every build also appends
the board's lines and the model's numbers to the timed odds archive (scripts/data/odds/<sport>-<yyyy-mm>.jsonl): the
close is a game's last archived line before the start, and the archive's snapshots by hours to the start are the bet
timing table.
"""
import datetime
import gzip
import json
import math
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WF = os.path.join(HERE, 'data', 'games_wf')
FIT = os.path.join(ROOT, 'data', 'games_picks_fit.json')
OUT = os.path.join(ROOT, 'data', 'games_picks_{}.json')
SPORTS = ('cfb', 'nfl', 'cbb', 'nba')
NAMES = {'cfb': 'college football', 'nfl': 'NFL', 'cbb': 'college basketball', 'nba': 'NBA'}
# first held-out season: the same split each sport's game model reports (CFB has two seasons: 2025 tunes, 2026 tests)
HELD = {'cfb': 2026, 'nfl': 2021, 'cbb': 2021, 'nba': 2022}
MARKETS = ('spread', 'ml', 'total')
CUTS = [round(0.01 * i, 2) for i in range(0, 16)]
MIN_N, MIN_T = 40, 1.0
ML_CAP = 300                      # moneylines past +-300 are left out (the calibration is thin in the tails)
KELLY_MIN, KELLY_CAP = 0.25, 3.0
ESPN = {'cfb': 'football/college-football', 'nfl': 'football/nfl', 'cbb': 'basketball/mens-college-basketball', 'nba': 'basketball/nba'}
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'
ODDS = os.path.join(HERE, 'data', 'odds')
SNAP = ('L', 'T', 'mlH', 'mlA', 'oH', 'oA', 'm', 'tm')
sys.path.insert(0, HERE)
import clv as C


def price(x, default=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if abs(v) >= 100 else default


def dec(o):
    return 1 + o / 100 if o > 0 else 1 + 100 / -o


def lg(p):
    return math.log(p / (1 - p))


def sig(z):
    return 1 / (1 + math.exp(-z))


def novig(a, b):
    pa, pb = 1 / dec(a), 1 / dec(b)
    return pa / (pa + pb)


CAP = {}                          # per sport: (spread, total) disagreement past which a game is skipped (set by fit)


def markets(g, cap=(None, None)):
    """the bets on one game: {market: (x, offset, (home/over price, away/under price))}; g has m, L, tm, T and prices.
    A game is skipped when the model and the line disagree by more than three standard deviations of that sport's
    disagreement (in the history these are mostly bad lines: a sign flipped, a stale number), or when the spread and
    the moneyline name different favorites."""
    out = {}
    m, L = g.get('m'), g.get('L')
    mh, ma = price(g.get('mlH')), price(g.get('mlA'))
    if L is not None and mh is not None and ma is not None and abs(L) >= 3 and (mh < ma) != (L > 0):
        return out
    if m is not None and L is not None and (cap[0] is None or abs(m - L) <= cap[0]):
        a, b = price(g.get('oH'), -110), price(g.get('oA'), -110)
        out['spread'] = (m - L, lg(novig(a, b)), (a, b))
        if mh is not None and ma is not None and max(abs(mh), abs(ma)) <= ML_CAP:
            out['ml'] = (m - L, lg(novig(mh, ma)), (mh, ma))
    if g.get('tm') is not None and g.get('T') is not None and (cap[1] is None or abs(g['tm'] - g['T']) <= cap[1]):
        a, b = price(g.get('oO'), -110), price(g.get('oU'), -110)
        out['total'] = (g['tm'] - g['T'], lg(novig(a, b)), (a, b))
    return out


def outcome(g, mk):
    """1 home/over wins, 0 loses, None push"""
    if mk == 'spread':
        d = g['res'] - g['L']
    elif mk == 'ml':
        d = g['res']
    else:
        d = g['tot'] - g['T']
    return None if d == 0 else (1 if d > 0 else 0)


def bets_for(g, coef, cap=(None, None)):
    """every bet on a game with its calibrated chance and expected return: list of dicts"""
    out = []
    for mk, (x, off, (pa, pb)) in markets(g, cap).items():
        b = coef.get(mk)
        if b is None:
            continue
        ph = sig(off + b * x)
        for side, p, o in (('home' if mk != 'total' else 'over', ph, pa), ('away' if mk != 'total' else 'under', 1 - ph, pb)):
            pay = dec(o) - 1
            ev = p * pay - (1 - p)
            out.append({'mk': mk, 'side': side, 'p': p, 'price': o, 'ev': ev, 'kelly': max(ev, 0) / pay})
    return out


def choose(bets, cuts):
    """the bets that clear their market's cut: the best side bet (spread or moneyline) and the best total"""
    pick = []
    for fam in (('spread', 'ml'), ('total',)):
        c = [b for b in bets if b['mk'] in fam and cuts.get(b['mk']) is not None and b['ev'] > cuts[b['mk']]]
        if c:
            pick.append(max(c, key=lambda b: b['ev']))
    return pick


def summ(bs):
    n = len(bs)
    pr = [b['profit'] for b in bs]
    u = sum(pr)
    mu = u / n if n else 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in pr) / (n - 1)) if n > 1 else 0.0
    risked = sum(b.get('units', 1.0) for b in bs)
    su = sum(b.get('units', 1.0) * b['profit'] for b in bs)
    return {'n': n, 'w': sum(1 for x in pr if x > 0), 'l': sum(1 for x in pr if x < 0), 'units': round(u, 1),
            'roi': round(mu, 3) if n else None, 't': round(mu / (sd / math.sqrt(n)), 2) if n > 1 and sd else None,
            'ev': round(sum(b['ev'] for b in bs) / n, 3) if n else None,
            'sized': {'units': round(su, 1), 'risked': round(risked, 1), 'roi': round(su / risked, 3) if risked else None}}


def load_wf(sport):
    fn = os.path.join(WF, sport + '.json.gz')
    return [r for r in json.load(gzip.open(fn)) if r.get('L') is not None] if os.path.exists(fn) else []


def fit_b(rows, mk, cap=(None, None)):
    """MLE of the one slope (no intercept) by Newton, tiny ridge"""
    D = []
    for r in rows:
        x = markets(r, cap).get(mk)
        y = outcome(r, mk) if x else None
        if x and y is not None:
            D.append((x[0], x[1], y))
    if len(D) < 200:
        return None, len(D)
    b = 0.0
    for _ in range(30):
        g = h = 0.0
        for x, off, y in D:
            p = sig(off + b * x)
            g += (y - p) * x
            h += p * (1 - p) * x * x
        g -= 1e-3 * b
        h += 1e-3
        b += g / h
    return b, len(D)


def fit():
    res = {'asof': datetime.date.today().isoformat(), 'minN': MIN_N, 'minT': MIN_T, 'cuts': CUTS, 'mlCap': ML_CAP,
           'kelly': [KELLY_MIN, KELLY_CAP], 'sports': {}}
    for sport in SPORTS:
        rows = load_wf(sport)
        if not rows:
            continue
        seasons = sorted({r['S'] for r in rows})
        held = HELD[sport]
        sd = lambda v: math.sqrt(sum(x * x for x in v) / len(v) - (sum(v) / len(v)) ** 2)
        tv = [r['tm'] - r['T'] for r in rows if r.get('tm') is not None and r.get('T') is not None]
        cap = (round(3 * sd([r['m'] - r['L'] for r in rows]), 1), round(3 * sd(tv), 1) if tv else None)
        # walk-forward: every season's bets priced by b fit on the seasons before it (CFB: on the other season)
        allb = {mk: [] for mk in MARKETS}
        bs_by = {}
        for S in seasons:
            tr = [r for r in rows if (r['S'] != S if sport == 'cfb' else r['S'] < S)]
            coef = {}
            for mk in MARKETS:
                coef[mk] = fit_b(tr, mk, cap)[0]
            bs_by[S] = coef
            for r in rows:
                if r['S'] != S:
                    continue
                for b in bets_for(r, coef, cap):
                    y = outcome(r, b['mk'])
                    if y is None:
                        continue
                    won = (y == 1) == (b['side'] in ('home', 'over'))
                    allb[b['mk']].append({**b, 'S': S, 'id': r['id'], 'profit': dec(b['price']) - 1 if won else -1.0})
        # cuts on the tuning seasons
        mkt = {}
        cuts = {}
        for mk in MARKETS:
            tune = [b for b in allb[mk] if b['S'] < held]
            best = None
            grid = []
            for c in CUTS:
                s = summ([b for b in tune if b['ev'] > c])
                grid.append({'cut': c, 'n': s['n'], 'roi': s['roi'], 't': s['t']})
                if s['n'] >= MIN_N and s['roi'] is not None and s['roi'] > 0 and (s['t'] or 0) >= MIN_T and (best is None or s['roi'] > best[1]):
                    best = (c, s['roi'])
            cuts[mk] = best[0] if best else None
            mkt[mk] = {'cut': cuts[mk], 'grid': grid, 'n': len(allb[mk]) // 2}
        # the shipped rule on every season: the chosen bets per game (one side bet, one total). A market whose own
        # tuning record under that rule misses the gate (the side bet went to the other market) is turned off and
        # the rest re-chosen.
        by_game = {}
        for mk in MARKETS:
            for b in allb[mk]:
                by_game.setdefault((b['S'], b['id']), []).append(b)
        for _ in range(3):
            chosen = [b for bs in by_game.values() for b in choose(bs, cuts)]
            bad = []
            for mk in MARKETS:
                if cuts[mk] is None:
                    continue
                s_ = summ([b for b in chosen if b['mk'] == mk and b['S'] < held])
                if s_['n'] < MIN_N or (s_['roi'] or 0) <= 0 or (s_['t'] or 0) < MIN_T:
                    bad.append(mk)
            if not bad:
                break
            for mk in bad:
                cuts[mk] = None
                mkt[mk]['cut'] = None
                mkt[mk]['dropped'] = True
        # Kelly units, each season's scale from the other seasons
        for b in chosen:
            other = [x['kelly'] for x in chosen if x['mk'] == b['mk'] and x['S'] != b['S']]
            sc = sum(other) / len(other) if other else None
            b['units'] = min(KELLY_CAP, max(KELLY_MIN, b['kelly'] / sc)) if sc else 1.0
        for mk in MARKETS:
            cb = [b for b in chosen if b['mk'] == mk]
            mkt[mk].update({'tune': summ([b for b in cb if b['S'] < held]), 'held': summ([b for b in cb if b['S'] >= held]),
                            'bySeason': [{'season': S, **{k: v for k, v in summ([b for b in cb if b['S'] == S]).items() if k in ('n', 'w', 'l', 'roi')}} for S in seasons],
                            'scale': round(sum(b['kelly'] for b in cb) / len(cb), 4) if cb else None})
            # how far the expected return ran ahead of the result, held out (every bet with positive expected return)
            pos = [b for b in allb[mk] if b['S'] >= held and b['ev'] > 0]
            mkt[mk]['heldAll'] = summ(pos)
        # the live slope: fit on every season
        live = {mk: fit_b(rows, mk, cap) for mk in MARKETS}
        res['sports'][sport] = {'name': NAMES[sport], 'cap': list(cap), 'seasons': [seasons[0], seasons[-1]], 'held': held, 'games': len(rows),
                                'b': {mk: round(v[0], 4) if v[0] is not None else None for mk, v in live.items()},
                                'bN': {mk: v[1] for mk, v in live.items()},
                                'bBySeason': {str(S): {mk: round(v, 4) if v is not None else None for mk, v in c.items()} for S, c in bs_by.items()},
                                'markets': mkt,
                                'all': {'tune': summ([b for b in chosen if b['S'] < held]), 'held': summ([b for b in chosen if b['S'] >= held])}}
        on = [mk for mk in MARKETS if cuts[mk] is not None]
        print(sport, 'b', res['sports'][sport]['b'], 'on', {mk: cuts[mk] for mk in on})
        for mk in MARKETS:
            m = mkt[mk]
            print(f"  {mk:6s} cut {m['cut']}  tune {m['tune']['n']} {m['tune']['roi']} t {m['tune']['t']}  held {m['held']['n']} {m['held']['roi']} t {m['held']['t']}"
                  f"  (held, every +EV bet: {m['heldAll']['n']} roi {m['heldAll']['roi']} vs ev {m['heldAll']['ev']})")
    with open(FIT, 'w') as f:
        json.dump(res, f, indent=1)


# ---------------------------------------------------------------- the pick rules (Noah, Oct 21 2026)
# A pick is the model's side whenever it sits at least X points off the line when the board publishes. X is set per
# sport and market on the tuning seasons, by the return the picks were worth at the closing line (scripts/clv.py), and
# a market is turned on only if its picks beat the close on the validation season(s) after them, and measured on the
# test seasons after those, which pick nothing (Oct 21 2026: one window both switching a market on and measuring it
# flattered it). CFB has two seasons of opens, so it is switched on on the tuning season at a stricter t and measured
# on 2026. Opening lines the history got wrong (clv.bad_open) are left out everywhere. The history's opening line
# stands in for the line at publish time. NFL has no opening lines, so its X is set on results at the close and it is
# judged by the close live. No opening moneylines exist, so the moneyline isn't a pick market.
RULES = os.path.join(ROOT, 'data', 'games_picks_rules.json')
RULE_TUNE = {'cfb': (2025,), 'cbb': (2024,), 'nba': (2015, 2016, 2017), 'nfl': tuple(range(2015, 2021))}
RULE_VAL = {'cfb': (), 'cbb': (2025,), 'nba': (2024,), 'nfl': (2021, 2022)}   # switch on here; () = on the tuning season
TUNE_KEEP_T = 2.0               # the t a market needs where its X was also picked (no separate validation season)
RULE_GRID = {'spread': [x / 2 for x in range(2, 17)], 'total': [x / 2 for x in range(2, 21)]}
RULE_MIN_N, KEEP_T = 40, 1.65


def calib(sport, mk, side, line, edge, k, ml=False):
    """(win, push, loss) for the model's side at `line`, priced as if the close moves k x edge toward it; ml: the
    moneyline on that side, from the same expected close"""
    sgn = 1 if side in ('home', 'over') else -1
    close = line + sgn * k * edge
    return C.chances(sport, 'ml' if ml else mk, side, line, close)


def stake_du(sport, mk, c, o, n=None):
    """Dengler Units (scripts/units.py): the stake in % of bankroll, n picks on the slate"""
    import units as DU
    return DU.stake(sport, mk, c, o, n)


def rule_bets(sport, rows, mk, x, at_open, cap=None):
    """the model's side on every game it sits x+ off the line (the open, or the close when at_open is False); a gap
    past cap (three standard deviations of the sport's disagreement) is a bad line, not a bet"""
    out = []
    for g in rows:
        if mk == 'spread':
            line, m, close, res = (g.get('Lo') if at_open else g['L']), g['m'], g['L'], g['res']
        else:
            line, m, close, res = (g.get('To') if at_open else g.get('T')), g.get('tm'), g.get('T'), g.get('tot')
        if line is None or m is None or close is None or res is None or abs(m - line) < x:
            continue
        if cap is not None and abs(m - line) > cap:
            continue
        if at_open and C.bad_open(sport, mk, line, close):
            continue                # a swapped or impossible opening line (clv.bad_open): never a bet anyone had
        side = ('home' if m > line else 'away') if mk == 'spread' else ('over' if m > line else 'under')
        if at_open:
            price = -110
        else:
            price = price_of(g, mk, side)
        e = C.judge({}, sport, mk, side, line, price, close) if at_open else {}
        d = (res - line) if side in ('home', 'over') else (line - res)
        e.update({'S': g['S'], 'profit': 0.0 if d == 0 else (dec(price) - 1 if d > 0 else -1.0), 'g': g, 'side': side, 'line': line, 'edge': abs(m - line)})
        out.append(e)
    return out


def price_of(g, mk, side):
    k = {('spread', 'home'): 'oH', ('spread', 'away'): 'oA', ('total', 'over'): 'oO', ('total', 'under'): 'oU'}[(mk, side)]
    return price(g.get(k), -110)


def rule_stats(es):
    def mt(xs):
        n = len(xs)
        if n < 2:
            return None, None
        m = sum(xs) / n
        s = math.sqrt(sum((v - m) ** 2 for v in xs) / (n - 1))
        return round(m, 4), (round(m / (s / math.sqrt(n)), 2) if s else None)
    cr = [e['clvRet'] for e in es if e.get('clvRet') is not None]
    c, ct = mt(cr)
    r, rt = mt([e['profit'] for e in es])
    pts = [e['clv'] for e in es if e.get('clv') is not None]
    beat = [e['beat'] for e in es if e.get('beat') is not None]
    return {'n': len(es), 'clvRet': c, 'clvT': ct, 'clv': round(sum(pts) / len(pts), 2) if pts else None,
            'beat': round(sum(1 for b in beat if b > 0) / len(beat), 3) if beat else None,
            'w': sum(1 for e in es if e['profit'] > 0), 'l': sum(1 for e in es if e['profit'] < 0), 'roi': r, 'roiT': rt}


def fit_rules():
    """data/games_picks_rules.json: X and the record for every sport and market"""
    F = json.load(open(FIT))['sports']
    res = {'asof': datetime.date.today().isoformat(), 'minN': RULE_MIN_N, 'keepT': KEEP_T, 'sports': {}}
    for sport in SPORTS:
        rows = [r for r in load_wf(sport) if r.get('res') is not None]
        at_open = any(r.get('Lo') is not None for r in rows)
        tune = set(RULE_TUNE[sport])
        out = {'name': NAMES[sport], 'basis': 'close' if at_open else 'results', 'tune': sorted(tune), 'markets': {}}
        caps = F.get(sport, {}).get('cap') or [None, None]
        for mk in ('spread', 'total'):
            cap = caps[0] if mk == 'spread' else caps[1]
            RB = lambda rr, x: rule_bets(sport, rr, mk, x, at_open, cap)
            rs = [r for r in rows if (r.get('Lo') if mk == 'spread' else r.get('To')) is not None] if at_open else rows
            val = set(RULE_VAL[sport])
            held = sorted({r['S'] for r in rs if r['S'] > max(tune | val)})
            if not rs or not held:
                out['markets'][mk] = {'on': False, 'why': 'no opening lines for this market in the history'}
                continue
            grid, best = [], None
            for x in RULE_GRID[mk]:
                es = RB([r for r in rs if r['S'] in tune], x)
                st = rule_stats(es)
                score = st['clvRet'] if at_open else st['roi']
                tt = st['clvT'] if at_open else st['roiT']
                grid.append({'x': x, **{k: st[k] for k in ('n', 'clvRet', 'clvT', 'roi', 'roiT')}})
                if st['n'] >= RULE_MIN_N and score is not None and score > 0 and (tt or 0) >= 1 and (best is None or score > best[1]):
                    best = (x, score)
            m = {'grid': grid, 'held': held, 'val': sorted(val)}
            if best is None:
                m.update({'on': False, 'x': None, 'why': 'no edge cut beat the ' + ('close' if at_open else 'vig') + ' on the tuning seasons'})
                out['markets'][mk] = m
                continue
            x = best[0]
            tb = RB([r for r in rs if r['S'] in tune], x)
            tu = rule_stats(tb)
            vb = RB([r for r in rs if r['S'] in val], x) if val else tb
            vo = rule_stats(vb)
            hb = RB([r for r in rs if r['S'] in held], x)
            ho = rule_stats(hb)
            # switched on on the validation season(s) (or the tuning one, at a stricter t), then a test-season veto: a
            # market that loses to the close where nothing was chosen is off
            needT = KEEP_T if val else TUNE_KEEP_T
            if at_open:
                on = vo['n'] >= 30 and (vo['clvRet'] or 0) > 0 and (vo['clvT'] or 0) >= needT
                why = None if on else 'did not beat the close on the ' + ('validation' if val else 'tuning') + ' season'
                if on and (ho['n'] < 20 or (ho['clvRet'] or 0) <= 0):
                    on, why = False, 'did not beat the close on the test seasons'
            else:
                on = vo['n'] >= 30 and (vo['roi'] or 0) > 0 and ho['n'] >= 30 and (ho['roi'] or 0) > 0
                why = None if on else 'lost on the validation or test seasons'
            # calibration: the close moved k points toward the pick per point of edge on the validation picks; a pick's
            # chance is priced as if the close lands there (scripts/clv.py), which is what it was worth at the close
            k = None
            if at_open:
                k = round(sum(e['clv'] for e in vb if e.get('clv') is not None) / sum(e['edge'] for e in vb), 3) if vb else None
            # the stake: Dengler Units (scripts/units.py), refit from these rules at the end of --rules
            frac = None
            m.update({'on': on, 'x': x, 'tuneRec': tu, 'valRec': vo if val else None, 'heldRec': ho, 'why': why, 'k': k, 'frac': frac, 'cap': cap,
                      'bySeason': [{'season': S, **rule_stats([e for e in hb if e['S'] == S])} for S in held]})
            out['markets'][mk] = m
        out['markets']['ml'] = {'on': False, 'why': 'no opening moneylines in the history, so moneyline picks can\'t be judged by the close'}
        if sport == 'nba':
            out['leak'] = 'the walk-forward model saw tip-time injury news the open did not have, so the held-out numbers are an upper bound'
        if not at_open:
            out['note'] = 'no opening lines in the history: X set on results at the close; judged by the close live'
        res['sports'][sport] = out
        for mk in ('spread', 'total'):
            m = out['markets'][mk]
            print(sport, mk, 'on' if m.get('on') else 'off', 'x', m.get('x'), 'tune', m.get('tuneRec'), 'held', m.get('heldRec'), m.get('why') or '')
    fit_segments(res)
    with open(RULES, 'w') as f:
        json.dump(res, f, indent=1)
    # Dengler Units refit on these rules (any game model or pick change reruns --fit then --rules, so the units follow)
    import units as DU
    du = DU.fit()
    for sport, S in res['sports'].items():
        for mk, m in S['markets'].items():
            u = (du['sports'].get(sport) or {}).get(mk)
            if u:
                m['frac'] = u['live']['lam']
                m['du'] = {'lam': u['live']['lam'], 'cap': u['live']['cap'], 'edge': u['median']['edge'], 'units': u['median']['units'],
                           'n': u['n'], 'gClose': u['compare'][1]['gClose'], 'dd25': u['compare'][1]['dd25'], 'dd50': u['compare'][1]['dd50']}
        for z in S.get('segments') or []:
            z['frac'] = (S['markets'].get(z['mk']) or {}).get('frac')
    res['du'] = {'book': du.get('book'), 'asof': du['asof']}
    with open(RULES, 'w') as f:
        json.dump(res, f, indent=1)


# ---------------------------------------------------------------- segments (Noah, Oct 21 2026: "more picks on the board")
# Each market split by conference and tier, conference game, home or road, favorite or dog, line band, total band and
# early or late season. A segment's edge is shrunk toward its parent market's (empirical Bayes: the spread between the
# segments of one family, net of sampling noise, sets how far each moves), X is set on the tuning seasons on the shrunk
# value, a segment is switched on only if its validation-season picks beat the close after a Benjamini-Hochberg cut
# over every segment tested (q SEG_Q), and it is measured (and vetoed if it loses to the close) on the test seasons.
# A kept segment adds picks only where its X sits below the market's own. No validation season (CFB): no segments.
SEG_Q, SEG_MIN_TUNE, SEG_MIN_HELD = 0.10, 25, 20
P4 = {'cfb': {'SEC', 'Big Ten', 'Big 12', 'ACC'}, 'cbb': {'ACC', 'B10', 'B12', 'SEC', 'BE'}}
_CONF = {}


def conf_map(sport):
    if sport not in _CONF:
        m = {}
        try:
            if sport == 'cfb':
                m = {t['team']: t['conf'] for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']}
            elif sport == 'cbb':
                m = {t['t']: t['conf'] for t in json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']}
        except (OSError, ValueError, KeyError):
            pass
        _CONF[sport] = m
    return _CONF[sport]


def seg_of(sport, g, mk, side, line):
    """{family: value} for a pick: the families every sport has, plus conference ones in college"""
    out = {}
    d = str(g.get('date') or g.get('kick') or '')
    mo, dy = (int(d[5:7]), int(d[8:10])) if len(d) >= 10 else (0, 0)
    early = {'cfb': mo in (8, 9), 'nfl': mo == 9, 'cbb': mo == 11 or (mo == 12 and dy < 15), 'nba': mo in (10, 11)}[sport]
    out['season'] = 'early' if early else 'late'
    if mk == 'spread':
        out['venue'] = 'neutral' if g.get('neutral') else side
        L = g.get('L') if line is None else line
        fav = (L > 0) == (side == 'home') if L else False
        out['role'] = 'favorite' if fav else 'dog'
        a = abs(L or 0)
        bands = (3, 7, 14) if sport in ('cfb', 'nfl') else (4, 9, 15)
        out['line'] = f'<{bands[0]}' if a < bands[0] else f'{bands[0]}-{bands[1]}' if a < bands[1] else f'{bands[1]}-{bands[2]}' if a < bands[2] else f'{bands[2]}+'
    else:
        out['side'] = side
        T = g.get('T') if line is None else line
        cut = {'cfb': (48, 58), 'nfl': (41, 47), 'cbb': (137, 150), 'nba': (215, 232)}[sport]
        out['total'] = 'low' if T < cut[0] else 'high' if T >= cut[1] else 'mid'
    cm = conf_map(sport)
    if cm:
        ch, ca = cm.get(g.get('home'), 'FCS' if sport == 'cfb' else 'other'), cm.get(g.get('away'), 'FCS' if sport == 'cfb' else 'other')
        hi = (ch in P4[sport]) + (ca in P4[sport])
        out['tier'] = ('power' if hi == 2 else 'mixed' if hi == 1 else ('G5' if sport == 'cfb' else 'mid-major'))
        out['game'] = 'conference' if ch == ca else 'non-conference'
        if ch == ca:
            out['conf'] = ch
    return out


def bh(ps, q):
    """Benjamini-Hochberg: the indexes kept at false-discovery rate q"""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    k = 0
    for r, i in enumerate(order, 1):
        if ps[i] <= q * r / len(ps):
            k = r
    return set(order[:k])


def fit_segments(res):
    """add res['sports'][sport]['segments']: the kept segment rules, and res['segmentTests']: every one tested"""
    F = json.load(open(FIT))['sports']
    cands = []
    for sport in ('cfb', 'cbb', 'nba'):
        rows = [r for r in load_wf(sport) if r.get('res') is not None]
        tune, val = set(RULE_TUNE[sport]), set(RULE_VAL[sport])
        if not val:
            continue
        caps = F.get(sport, {}).get('cap') or [None, None]
        for mk in ('spread', 'total'):
            rs = [r for r in rows if (r.get('Lo') if mk == 'spread' else r.get('To')) is not None]
            if not rs:
                continue
            cap = caps[0] if mk == 'spread' else caps[1]
            held = sorted({r['S'] for r in rs if r['S'] > max(tune | val)})
            par = res['sports'][sport]['markets'][mk]
            # every pick at the smallest X, tagged with its segments; larger X filter these
            allp = rule_bets(sport, rs, mk, RULE_GRID[mk][0], True, cap)
            for e in allp:
                e['seg'] = seg_of(sport, e['g'], mk, e['side'], e['line'])
            tp = [e for e in allp if e['S'] in tune]
            vp = [e for e in allp if e['S'] in val]
            hp = [e for e in allp if e['S'] in held]
            fams = sorted({f for e in allp for f in e['seg']})
            for fam in fams:
                vals = sorted({e['seg'][fam] for e in allp if fam in e['seg']})
                # shrunk tuning mean per value and X
                best = {}
                for x in RULE_GRID[mk]:
                    px = [e['clvRet'] for e in tp if e['edge'] >= x]
                    if len(px) < SEG_MIN_TUNE:
                        continue
                    mu = sum(px) / len(px)
                    st = {}
                    for v in vals:
                        xs = [e['clvRet'] for e in tp if e['edge'] >= x and e['seg'].get(fam) == v]
                        if len(xs) >= 5:
                            m_ = sum(xs) / len(xs)
                            s2 = sum((a - m_) ** 2 for a in xs) / max(1, len(xs) - 1)
                            st[v] = (m_, s2, len(xs))
                    if len(st) < 2:
                        continue
                    ms = [a[0] for a in st.values()]
                    mm = sum(ms) / len(ms)
                    tau2 = max(0.0, sum((a - mm) ** 2 for a in ms) / (len(ms) - 1) - sum(a[1] / a[2] for a in st.values()) / len(st))
                    for v, (m_, s2, n) in st.items():
                        B = tau2 / (tau2 + s2 / n) if tau2 + s2 / n > 0 else 0.0
                        sh = mu + B * (m_ - mu)
                        if n >= SEG_MIN_TUNE and sh > 0 and (v not in best or sh > best[v][1]):
                            best[v] = (x, sh, m_, n)
                for v, (x, sh, m_, n) in best.items():
                    if par.get('on') and x >= par['x']:
                        continue            # adds nothing over the market's own rule
                    vb = [e for e in vp if e['edge'] >= x and e['seg'].get(fam) == v]
                    vs = rule_stats(vb)
                    hb = [e for e in hp if e['edge'] >= x and e['seg'].get(fam) == v]
                    st = rule_stats(hb)
                    t = vs['clvT'] or 0.0
                    pv = 1 - 0.5 * (1 + math.erf(t / math.sqrt(2))) if len(vb) >= SEG_MIN_HELD else 1.0
                    cands.append({'sport': sport, 'mk': mk, 'fam': fam, 'val': v, 'x': x, 'tuneShrunk': round(sh, 4), 'tuneRaw': round(m_, 4),
                                  'tuneN': n, 'valRec': vs, 'held': st, 'p': round(pv, 5), 'vb': vb, 'hb': hb, 'seasons': held})
    keep = bh([c['p'] for c in cands], SEG_Q)
    # a segment must also beat the close on the validation picks it adds (those under its market's own X)
    for i in list(keep):
        c = cands[i]
        par = res['sports'][c['sport']]['markets'][c['mk']]
        inc = [e['clvRet'] for e in c['vb'] if not (par.get('on') and e['edge'] >= par['x'])]
        c['addN'] = len(inc)
        c['addClv'] = round(sum(inc) / len(inc), 4) if inc else None
        if not inc or c['addClv'] <= 0:
            keep.discard(i)
    res['segQ'] = SEG_Q
    tests = []
    for i, c in enumerate(cands):
        hb, vb = c.pop('hb'), c.pop('vb')
        # the test-season veto: switched on on validation, off if its test picks lose to the close (or are too few)
        on = i in keep and c['held']['n'] >= 10 and (c['held']['clvRet'] or 0) > 0
        c['on'] = on
        if i in keep and not on:
            c['why'] = 'lost to the close on the test seasons'
        if on:
            c['k'] = round(sum(e['clv'] for e in vb if e.get('clv') is not None) / sum(e['edge'] for e in vb), 3)
            par = res['sports'][c['sport']]['markets'][c['mk']]
            c['frac'] = par.get('frac') or 0.25
            res['sports'][c['sport']].setdefault('segments', []).append({k: c.get(k) for k in ('mk', 'fam', 'val', 'x', 'k', 'frac', 'valRec', 'held', 'tuneShrunk', 'tuneN', 'addN', 'addClv')})
            c['_hb'] = hb
        tests.append(c)
    # what the kept segments add: held-out picks no market rule already makes, per week
    add = {}
    for c in tests:
        if not c['on']:
            continue
        par = res['sports'][c['sport']]['markets'][c['mk']]
        for e in c.pop('_hb'):
            if par.get('on') and e['edge'] >= par['x']:
                continue
            add.setdefault(c['sport'], {})[(e['g']['id'], c['mk'])] = e
    for sport, d in add.items():
        es = list(d.values())
        wk = lambda e: datetime.date.fromisoformat(str(e['g']['date'])[:10]).isocalendar()[:2]
        # weeks with games in the held-out seasons (any game of the sport, not only picks)
        allw = {wk({'g': r}) for r in load_wf(sport) if r['S'] in {e['S'] for e in es}}
        res['sports'][sport]['segAdds'] = {**rule_stats(es), 'seasons': sorted({e['S'] for e in es}), 'weeks': len(allw),
                                           'perWeek': round(len(es) / len(allw), 1) if allw else None}
    res['segmentTests'] = [{k: v for k, v in c.items()} for c in tests]
    print('segments tested', len(tests), 'kept', sum(c['on'] for c in tests))
    for c in tests:
        if c['on'] or c['p'] < 0.05:
            print(' ', 'KEEP' if c['on'] else 'drop', c['sport'], c['mk'], c['fam'], c['val'], 'x', c['x'], 'tune', c['tuneShrunk'], c['tuneN'],
                  'val', c['valRec']['n'], c['valRec']['clvRet'], c['valRec']['clvT'],
                  'held', c['held']['n'], c['held']['clvRet'], c['held']['clvT'], c['held']['w'], c['held']['l'], c['held']['roi'], 'p', c['p'])
    for sport in res['sports']:
        if 'segAdds' in res['sports'][sport]:
            print(sport, 'adds', res['sports'][sport]['segAdds'])


# ---------------------------------------------------------------- live

def board(sport):
    """this slate from the sport's own build: list of {id, espn, kick, home, away, m, L, tm, T, mlH, mlA, oH, oA}"""
    out = []
    if sport == 'cfb':
        d = json.load(open(os.path.join(ROOT, 'data', 'cfb_games.json')))
        for g in d.get('games', []):
            p = g.get('proj') or {}
            if g.get('market') is None or p.get('margin') is None:
                continue
            ml, so = g.get('ml') or {}, g.get('spreadOdds') or {}
            out.append({'id': str(g['id']), 'espn': str(g['id']), 'kick': g['date'], 'home': g['home']['name'], 'away': g['away']['name'],
                        'm': p['margin'], 'L': -float(g['market']), 'tm': p.get('total'), 'T': g.get('total'),
                        'mlH': ml.get('home'), 'mlA': ml.get('away'), 'oH': so.get('home'), 'oA': so.get('away'),
                        'neutral': int(bool(g.get('neutral')))})
        return out
    d = json.load(open(os.path.join(ROOT, 'data', f'{sport}_games.json')))
    for g in d.get('games', []):
        if g.get('line') is None or g.get('final'):
            continue
        ml = g.get('ml') or {}
        h, a = g['home'], g['away']
        out.append({'id': str(g['id']), 'espn': str(g.get('espn') or g['id']), 'kick': g.get('kick') or g.get('tip'),
                    'home': h['n'] if isinstance(h, dict) else h, 'away': a['n'] if isinstance(a, dict) else a,
                    'm': g['margin'], 'L': float(g['line']), 'tm': g.get('total'), 'T': g.get('tline'),
                    'mlH': ml.get('home'), 'mlA': ml.get('away'), 'neutral': int(bool(g.get('neutral')))})
    return out


def espn_final(sport, eid):
    try:
        req = urllib.request.Request(f'https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/summary?event={eid}', headers={'User-Agent': UA})
        j = json.load(urllib.request.urlopen(req, timeout=20))
        c = j['header']['competitions'][0]
        if not c['status']['type'].get('completed'):
            return None
        sc = {x['homeAway']: float(x['score']) for x in c['competitors']}
        return sc['home'], sc['away']
    except Exception:
        return None


def iso(t):
    return datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))


def archive_rows(sport):
    """every snapshot in the odds archive for a sport, oldest first"""
    rows = []
    if os.path.isdir(ODDS):
        for fn in sorted(os.listdir(ODDS)):
            if fn.startswith(sport + '-') and fn.endswith('.jsonl'):
                with open(os.path.join(ODDS, fn)) as f:
                    rows += [json.loads(x) for x in f if x.strip()]
    return rows


def archive(sport, games, now, rows):
    """The timed odds archive (scripts/data/odds/<sport>-<yyyy-mm>.jsonl): each game not yet started, at every build that
    sees its line or price or the model's number change, with the time it was seen and the model's margin and total
    as they stood then (so a bet-timing test never uses news the line didn't have). Returns the new rows."""
    last = {}
    for r in rows:
        last[r['id']] = r
    new = []
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    for g in games:
        if not g.get('kick') or iso(g['kick']) <= now or g.get('L') is None:
            continue
        snap = {k: (round(float(g[k]), 2) if k in ('m', 'tm') else g[k]) if g.get(k) is not None else None for k in SNAP}
        kick = iso(g['kick']).strftime('%Y-%m-%dT%H:%M:%SZ')
        prev = last.get(str(g['id']))
        if prev and all(prev.get(k) == snap[k] for k in SNAP) and prev.get('k') == kick:
            continue
        new.append({'t': stamp, 'id': str(g['id']), 'k': kick, **snap})
    if new:
        os.makedirs(ODDS, exist_ok=True)
        with open(os.path.join(ODDS, f'{sport}-{now:%Y-%m}.jsonl'), 'a') as f:
            for r in new:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    return new


def rule_options(sport, g, R, segs=()):
    """(picks, misses) for one game under the rules: a pick is the model's side of a market it sits x+ off, x from
    the market's rule or a kept segment the pick falls in (the lowest that applies), bet on the spread or the moneyline
    (the side) or the total, priced on the calibrated chance; misses carry why"""
    opts, near = [], []
    for mk in ('spread', 'total'):
        r = R.get(mk) or {}
        m, line = (g.get('m'), g.get('L')) if mk == 'spread' else (g.get('tm'), g.get('T'))
        if m is None or line is None:
            continue
        edge = abs(m - line)
        side = ('home' if m > line else 'away') if mk == 'spread' else ('over' if m > line else 'under')
        sg = seg_of(sport, g, mk, side, line)
        rules = [{'x': r['x'], 'k': r['k'], 'frac': r.get('frac'), 'seg': None}] if r.get('on') and r.get('k') else []
        rules += [{'x': z['x'], 'k': z['k'], 'frac': z.get('frac'), 'seg': f"{z['fam']}: {z['val']}"} for z in segs
                  if z['mk'] == mk and sg.get(z['fam']) == z['val']]
        base = {'mk': mk, 'side': side, 'line': line, 'edge': round(edge, 1), 'price': price_of(g, mk, side)}
        if not rules:
            near.append({**base, 'x': None, 'why': f'{mk} market off'})
            continue
        rule = min(rules, key=lambda z: z['x'])
        base['x'] = rule['x']
        if r.get('cap') is not None and edge > r['cap'] or R.get('_cap', {}).get(mk) is not None and edge > R['_cap'][mk]:
            near.append({**base, 'why': 'gap too big: a bad line'})
            continue
        if edge < rule['x']:
            near.append({**base, 'why': f"edge under {rule['x']:g}" + (f" ({rule['seg']})" if rule['seg'] else '')})
            continue
        if rule['seg']:
            base['seg'] = rule['seg']
        inst = [(mk, line, base['price'], False)]
        if mk == 'spread':
            o = price(g.get('mlH') if side == 'home' else g.get('mlA'))
            if o is not None and abs(o) <= ML_CAP:
                inst.append(('ml', None, o, True))
        for imk, iline, o, ml in inst:
            c = calib(sport, mk, side, line, edge, rule['k'], ml)
            if c is None:
                continue
            w, _, l = c
            ev = w * (dec(o) - 1) - l
            if ev <= 0:
                continue
            opts.append({**base, 'mk': imk, 'line': iline, 'price': o, 'p': round(w, 3), 'ev': round(ev, 3),
                         'units': stake_du(sport, imk, c, o), '_c': c})
    return opts, near


def live(sport):
    F = json.load(open(FIT))['sports'].get(sport)
    fn = OUT.format(sport)
    try:
        old = json.load(open(fn))
    except (OSError, ValueError):
        old = {}
    log = old.get('log', [])
    if not F:
        return print(f'{sport} picks: no fit')
    coef = F['b']
    cap = tuple(F.get('cap') or (None, None))
    try:
        RS = json.load(open(RULES))['sports'][sport]
    except (OSError, ValueError, KeyError):
        RS = {}
    R, SEGS = dict(RS.get('markets') or {}), RS.get('segments') or []
    R['_cap'] = {'spread': cap[0], 'total': cap[1]}
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    games = board(sport)
    arch = archive_rows(sport)
    arch += archive(sport, games, now, arch)
    # the close: each game's last archived snapshot before its kick
    closes = {}
    for r in arch:
        if r['t'] < r['k']:
            closes[r['id']] = r
    # a pick not yet started whose rule has since been switched off (a refit; Oct 21 2026, when bad opening lines were
    # cleaned out) is withdrawn: the rules the record is judged by never made it. The game can be flagged again below.
    segl = {(z['mk'], f"{z['fam']}: {z['val']}"): z['x'] for z in SEGS}

    def ruled(e):
        rmk = 'spread' if e['mk'] == 'ml' else e['mk']
        r = R.get(rmk) or {}
        if r.get('on') and e['edge'] >= r['x']:
            return True
        x = segl.get((rmk, e.get('seg')))
        return x is not None and e['edge'] >= x
    gone = [e for e in log if e.get('res') is None and iso(e['kick']) > now and not ruled(e)]
    if gone:
        log = [e for e in log if e not in gone]
        print(f'{sport}: withdrew {len(gone)} open picks whose rule is off:', ', '.join(f"{e['away']}@{e['home']} {e['mk']} {e['side']}" for e in gone))
    seen = {e['id'] for e in log}
    G = {g['id']: g for g in games}
    cur = {}
    top = []
    gtab = {}
    # every upcoming game's options first: picks on one slate (an ET day; the football board is one week) size together
    ahead = {g['id']: rule_options(sport, g, R, SEGS) for g in games if g['kick'] and iso(g['kick']) > now}
    slate = lambda g: 'week' if sport in ('cfb', 'nfl') else (iso(g['kick']) - datetime.timedelta(hours=4)).date().isoformat()
    n_slate = {}
    for g in games:
        if ahead.get(g['id'], ([], []))[0]:
            n_slate[slate(g)] = n_slate.get(slate(g), 0) + 1
    for g in games:
        if g['id'] not in ahead:
            continue
        opts, near = ahead[g['id']]
        pick = max(opts, key=lambda o: o['ev']) if opts else None
        if pick:
            pick['units'] = stake_du(sport, pick['mk'], pick.pop('_c'), pick['price'], n_slate[slate(g)])
            cur[g['id']] = {'mk': pick['mk'], 'side': pick['side'], 'line': pick['line'], 'price': pick['price'], 'ev': pick['ev'], 'units': pick['units']}
            gtab[str(g['id'])] = {**{k: pick[k] for k in ('mk', 'side', 'line', 'price', 'ev', 'edge', 'units')}, 'home': g['home'], 'away': g['away'], 'state': 'pick'}
            if g['id'] not in seen:
                seen.add(g['id'])
                log.append({'id': g['id'], 'espn': g['espn'], 'sport': sport, 'kick': g['kick'], 'home': g['home'], 'away': g['away'],
                            **{k: pick[k] for k in ('mk', 'side', 'line', 'price', 'p', 'ev', 'units', 'edge', 'x')}, **({'seg': pick['seg']} if pick.get('seg') else {}),
                            'm': round(g['m'], 1), 'tm': round(g['tm'], 1) if g.get('tm') is not None else None, 'flagged': stamp})
        elif near:
            n = max(near, key=lambda o: o['edge'])
            gtab[str(g['id'])] = {**{k: n[k] for k in ('mk', 'side', 'line', 'price', 'edge')}, 'ev': None, 'units': 0.0,
                                  'home': g['home'], 'away': g['away'], 'state': 'off' if n['x'] is None else 'under'}
            # the board: the games that miss, by how close they come to their market's cut
            top.append({'id': g['id'], 'sport': sport, 'kick': g['kick'], 'home': g['home'], 'away': g['away'],
                        **{k: n[k] for k in ('mk', 'side', 'line', 'price', 'edge', 'x')}, 'why': n['why'],
                        'm': round(g['m'], 1), 'tm': round(g['tm'], 1) if g.get('tm') is not None else None})
    # an open pick still at its flagged line and side takes the current stake (units follow a refit until the start)
    for e in log:
        c = cur.get(e['id'])
        if e.get('res') is None and iso(e['kick']) > now and c and (c['mk'], c['side'], c['line']) == (e['mk'], e['side'], e['line']):
            e['units'] = c['units']
    # the line at kickoff (the last one this build saw before the game) for closing line value; then the final
    for e in log:
        g = G.get(e['id'])
        if g and e.get('res') is None and iso(g['kick']) > now:
            e['close'] = g['T'] if e['mk'] == 'total' else g['L']
        if e.get('res') is not None or iso(e['kick']) > now - datetime.timedelta(hours=3):
            continue
        fin = espn_final(sport, e['espn'])
        if not fin:
            continue
        hs, as_ = fin
        e['score'] = [as_, hs]
        if e['mk'] == 'total':
            d = hs + as_ - e['line']
            win = None if d == 0 else (d > 0) == (e['side'] == 'over')
        elif e['mk'] == 'spread':
            d = hs - as_ - e['line']
            win = None if d == 0 else (d > 0) == (e['side'] == 'home')
        else:
            d = hs - as_
            win = None if d == 0 else (d > 0) == (e['side'] == 'home')
        e['res'] = 'p' if win is None else ('w' if win else 'l')
        e['profit'] = 0.0 if win is None else round(dec(e['price']) - 1 if win else -1.0, 3)
    # closing line value: the pick's line and price against the close (the last line archived before the start, else
    # the last this build saw), as points and as the return the bet was worth if the close is the true price
    for e in log:
        if e.get('res') is None:
            continue
        c = closes.get(str(e['id']))
        if c:
            e['close'] = c['T'] if e['mk'] == 'total' else c['L']
            if e['mk'] == 'ml':
                e['closeML'] = [c.get('mlH'), c.get('mlA')]
        if e.get('close') is None:
            continue
        cml = tuple(e['closeML']) if e.get('closeML') and None not in e['closeML'] else None
        C.judge(e, sport, e['mk'], e['side'], e['line'], e['price'], e['close'], cml)
    done = [e for e in log if e.get('res') is not None]
    rec = summ([{'profit': e['profit'], 'units': e['units'], 'ev': e['ev']} for e in done]) if done else {'n': 0}
    if done:
        # DU compounds: each pick is a % of the bankroll when it was flagged, so the record's bankroll multiplies through
        # the graded picks in kick order (1 DU = 1% of the bankroll then; every win is reinvested)
        bank = 1.0
        for e in sorted(done, key=lambda e: e['kick']):
            bank *= 1 + e['units'] / 100 * e['profit']
        rec['sized']['bank'] = round(bank, 4)
    rec.update(C.summary(done))
    rec['byMarket'] = {mk: {**C.summary([e for e in done if e['mk'] == mk]), 'n': sum(1 for e in done if e['mk'] == mk)} for mk in MARKETS}
    picks = []
    for e in log:
        if e.get('res') is None and iso(e['kick']) > now - datetime.timedelta(hours=4):
            p = dict(e)
            c = cur.get(e['id'])
            p['now'] = c if c and c['mk'] == e['mk'] and c['side'] == e['side'] else None
            picks.append(p)
    picks.sort(key=lambda p: -p['ev'])
    top.sort(key=lambda b: (b['x'] is None, -(b['edge'] / b['x']) if b['x'] else -b['edge']))
    # bet timing: the model's side at each archived line, by hours before the start, judged by the close
    mins = {'cfb': 3, 'nfl': 2, 'cbb': 3, 'nba': 2}
    timing = C.timing(sport, arch, mins[sport])
    out = {'sport': sport, 'name': NAMES[sport], 'asof': stamp, 'picks': picks, 'board': top[:25], 'games': gtab, 'record': rec,
           'timing': {'minEdge': mins[sport], 'snapshots': len(arch), 'buckets': timing},
           'recent': sorted(done, key=lambda e: e['kick'], reverse=True)[:40], 'log': log}
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in out.items() if k != 'asof'})):
        return print(f'{sport} picks: no change')
    with open(fn, 'w') as f:
        json.dump(out, f, indent=1)
    print(f'{sport} picks: {len(picks)} open, {len(done)} graded')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--fit':
        fit()
    elif a and a[0] == '--rules':
        fit_rules()
    elif a and a[0] in SPORTS:
        live(a[0])
    else:
        print(__doc__)
