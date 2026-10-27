#!/usr/bin/env python3
"""Units (Noah, Oct 21 2026: "a new unit system based on fractional Kelly that is uniquely tailored to our models and
aims to be much more aggressive"). One unit model for the Predictions picks (scripts/games_picks.py) and the paper book
(scripts/paper_book.py). DU compounds (Noah: "we are going to keep investing winnings back"): 1 DU = 1% of the bankroll
as it stands when the bet is placed, so stakes grow as bets hit and shrink in a drawdown. Kelly assumes exactly that,
and every growth, drawdown and ruin number here is compounded (log growth per slate, bankroll multiplied through).

    python3 scripts/units.py --fit     # data/units_fit.json (numpy). games_picks.py --rules runs it at the end, so a
                                       # game model or pick change (wf file -> --fit -> --rules) refits the units
    python3 scripts/units.py --test    # self-check of the live stake

The stake, per sport and market (spread, total; a moneyline is sized as its spread's market):

    ev      = w x B - l                         the model's expected return (w, push, l: the calibrated chance, the
                                                close moving k points per point of edge; B = decimal price - 1)
    edge    = min(ev, a + b x (gap - gbar))     what a pick at that gap has been worth at the close (never more than ev)
    u       = edge^2 / (edge^2 + var(edge))     the edge-uncertainty shrink (Baker and McHale 2013)
    stake   = lam x u x edge / (B x (w + l)) x slate      the Kelly stake on that edge, clipped to [0.25u, cap]

edge (a, b, gbar): our expectations are too confident, so they are calibrated before they are bet. On the held-out
seasons, every expectation made with k fit on the other blocks of slates (5 blocks in time order) so no pick prices
itself: the level a is what the market's picks were worth at the close (scripts/clv.py) and what they actually returned
at the price (ROI: the cover or win rate against the odds), combined by precision (a result swings ~0.95 a bet, the
close ~0.15, so the close leads until results pile up); the slope b is how much more a pick has been worth at the close
per point of gap (model minus line), the market's own, shrunk by its evidence (b x b^2 / (b^2 + se^2)) and never
negative. The gap, not the expectation, because the gap is what the close pays: NBA totals (Oct 21 2026, 274 test picks)
were worth 2.5% at 4.5-5.5 points and 7.0% at 7.5-10 (b .011 a point, t 2.9) while their expectations ran flat (r .01);
one level and slope per market, so a market's segments are one edge, not five. Standard errors clustered by slate
(floored at iid) give var(edge). Graded live picks (the games_picks logs and the paper
book) are pooled in by precision once there are 20, so the units refit themselves as picks grade.
slate = (1 + (nbar - 1) rho) / (1 + (n - 1) rho): bets on one slate (a day in basketball, a week in football) settle
together. rho is the within-slate correlation of the model's side against the close (one-way ANOVA, every held-out game
with an edge), nbar the backtest's picks per slate, so lam is fit at the slate size it was tested on.
lam: the aggression dial. Every lam from 0.1 to 3 and every cap is run on the held-out picks at stakes from the fold's
own calibration, and scored by log growth at the close (each slate's results drawn 400 times from the close's chances,
correlated at rho; growth on the actual results is shown beside it). Kelly on the true edge is the top of that curve:
past it more stake lowers growth, and at about twice it growth is gone. lam is the curve's top, the most aggressive
setting that does not lower held-out growth (ties go to the bigger stake); a thin market's lam is pulled toward 1 (full
Kelly on the calibrated edge) with weight 100 / (n + 100). The cap is the one with the most growth at that lam.
Drawdown and ruin: 2,000 seasons stitched from the held-out slates at the chosen stakes, results drawn from the close:
the chance of a 25% and a 50% fall from the peak, the median and the 5th to 95th percentile season, per market and for
the whole book (every market at once).

The NBA history is an upper bound (the walk-forward model saw tip-time injury news the open did not have), so its
picks' close value is halved before anything is fit (the close's chances moved to match in the draws): the
calibration, lam, the cap and the ruin odds all come from that halved world. Live picks pool in at full weight. NFL has no
opening lines in the history and gets the default (half Kelly on the raw expectation, 3u cap) until it has live picks.
"""
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIT = os.path.join(ROOT, 'data', 'units_fit.json')
sys.path.insert(0, HERE)

UNIT_MIN = 0.25                 # % of bankroll: the smallest stake on a listed pick
LAMS = [round(0.05 * i, 2) for i in range(2, 61)]
CAPS = (1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 25.0)  # % of bankroll a bet
FOLDS, DRAWS, SEASONS_SIM = 5, 400, 2000
LAM_N0 = 100                    # picks of prior weight on lam = 1
LEAK = {'nba': 0.5}             # the backtest edge's multiplier where the history saw news the open did not
# the price the history is priced at (Oct 27 2026): picks are bet on Novig, whose main rungs hold ~1-2% (about -103 a
# side; DraftKings was -110). A live price other than this is repriced from the calibrated chance (priced())
BASE = -103
# the history's edges are at the OPEN; a live pick is bet at the line when it is posted, after part of the move
# (Oct 27 2026): the odds archive's first week (Oct 21-27, CFB + NBA, ~220 sides) was worth 0.44 of what the open-based
# calibration said at the same gap (CFB spread .60, NBA spread .79, CFB total .23, NBA total .34). Every backtest edge
# over a fair coin is scaled by TIMING (with LEAK on top); walk-forward, a 0.5 haircut beat the Oct 21 rules whether the
# true live share was 0.3 or 1 (scripts/pick_recal.py). Graded live picks pool in at full weight, so they correct it
TIMING = 0.5
LIVE_MIN = 20                   # graded live picks before they count
# held caps until a refit is verified (Oct 21 2026): CBB spread jumped to 6.5 DU on one refit, half its history's
# picks were bad opens and its segments were chosen on the held-out seasons; 2 DU until the pick rules are refit
# without bad opens
HOLD = {('cbb', 'spread'): 2.0}
# still 2 (Oct 23 2026): CBB spreads now come only from the 'inj: with' segment, whose DU fit rests on 54 test picks
# NBA totals at 5 (Oct 21 2026): past 5 DU the held-out log growth barely moves (17.7% to 18.1% a season at 7.5)
# while the chance of a 50% fall roughly doubles, on a history that is an upper bound (tip-time injury news)
HOLD[('nba', 'total')] = 5.0
# NBA spreads at 5 too, by the same rule (Oct 21 2026): cap 5 keeps 9.0% of the 10.1% held-out growth a season that cap 10
# gets, on the same injury-leak history
HOLD[('nba', 'spread')] = 5.0
# CBB spreads up to 5 too (Oct 27 2026): the bad opens are cleaned out of the rules (PR #304) and its fit now rests on
# 1,041 test picks; walk-forward (scripts/pick_recal.py) caps 3, 5 and 10 grow alike, 5 for every market
HOLD[('cbb', 'spread')] = 5.0
# the system before DU (PR #281): Kelly fraction picked on held-out log growth, on the raw expectation, 0.25-3u
OLD_FRAC = {('cfb', 'total'): 1.0, ('cbb', 'spread'): 0.25, ('nba', 'spread'): 0.1, ('nba', 'total'): 0.25}
DEFAULT = {'a': 0.0, 'b': 0.5, 'evbar': 0.0, 'V': [[0.0, 0.0], [0.0, 0.0]], 'lam': 1.0, 'cap': 3.0, 'rho': 0.0, 'nbar': 1.0,
           'basis': 'default: half Kelly on the expected return'}
_FIT = {}


def dec(o):
    o = float(o)
    return 1 + (o / 100 if o > 0 else 100 / -o)


# ---------------------------------------------------------------- live (stdlib)

def load():
    if 'fit' not in _FIT:
        try:
            _FIT['fit'] = json.load(open(FIT))
        except (OSError, ValueError):
            _FIT['fit'] = {}
    return _FIT['fit']


def params(sport, mk):
    """the unit model for a sport and market: a, b, evbar, V (the edge's calibration), lam, cap (% a bet), rho, nbar"""
    mk = 'spread' if mk == 'ml' else mk
    m = ((load().get('sports') or {}).get(sport) or {}).get(mk)
    return {**DEFAULT, **m['live']} if m and m.get('live') else dict(DEFAULT)


def edge(p, ev, gap=None):
    """(the calibrated edge, its uncertainty shrink u) for a model expectation ev at this gap (model minus line, points);
    a calibration on the gap with no gap given prices the pick at the market's average gap"""
    if p.get('on') == 'gap':
        d = (gap - p['evbar']) if gap is not None else 0.0
    else:
        d = ev - p['evbar']
    e = min(ev, p['a'] + p['b'] * d)      # calibration only takes edge away: never more than the model itself expects
    V = p['V']
    # the uncertainty past the market's average gap is held at the average's (Oct 21 2026): the line's wider spread out
    # there shrank a bigger gap's stake below a smaller one's; this way a bigger gap never gets less
    dv = min(d, 0.0)
    var = max(0.0, V[0][0] + 2 * dv * V[0][1] + dv * dv * V[1][1])
    return e, (e * e / (e * e + var) if e > 0 and e * e + var > 0 else 0.0)


def priced(p, c, o, gap=None, ml=False):
    """(win chance, return at price o, uncertainty shrink u) of the calibrated edge. The calibration is fit on picks at
    BASE, so its edge is a BASE return: it becomes a win chance there and that chance is repriced at o (Oct 21 2026
    audit; before, the -110 return was divided by o's smaller payout, so a worse price got a bigger stake). A
    moneyline's price is its line, so it keeps the calibrated return at its own price."""
    w, pu, l = c
    if ml:
        ev = w * (dec(o) - 1) - l
        if ev <= 0:
            return w, ev, 0.0
        e, u = edge(p, ev, gap)
        return (e + 1 - pu) / dec(o), e, u
    B0 = dec(BASE) - 1
    ev0 = w * B0 - l
    if ev0 <= 0 or w + l <= 0:
        return w, w * (dec(o) - 1) - l, 0.0
    e0, u = edge(p, ev0, gap)
    ws = (e0 + 1 - pu) / (B0 + 1)
    return ws, ws * (dec(o) - 1) - (1 - pu - ws), u


def view(sport, mk, c, o, gap=None):
    """(win chance, expected return) a pick is staked on: the calibrated edge at this gap, as a chance at price o"""
    w, e, _ = priced(params(sport, mk), c, o, gap, mk == 'ml')
    return w, e


def slate_scale(p, n):
    rho, nbar = p.get('rho') or 0.0, max(1.0, p.get('nbar') or 1.0)
    n = max(1, n or 1)
    return (1 + (nbar - 1) * rho) / (1 + (n - 1) * rho)


def kelly_pct(p, c, o, gap=None, ml=False):
    """% of bankroll at lam 1 before the slate scale and cap: Kelly on the calibrated edge at price o, shrunk by its
    uncertainty"""
    _, pu, _ = c
    B = dec(o) - 1
    w, e, u = priced(p, c, o, gap, ml)
    if e <= 0 or u <= 0:
        return 0.0
    return max(0.0, u * e / (B * (1 - pu))) * 100


def stake(sport, mk, c, o, n=None, p=None, gap=None):
    """units (% of bankroll) for a pick with calibrated chances c = (win, push, loss) at American price o and gap
    (model minus line, points), n picks on its slate (None: the backtest's average slate). 0 when the model sees no edge at this price; a listed pick with an
    edge gets at least 0.25u; never more than the market's cap; quarter units."""
    p = p or params(sport, mk)
    w, _, l = c
    if w * (dec(o) - 1) - l <= 0:
        return 0.0
    f = p['lam'] * kelly_pct(p, c, o, gap, mk == 'ml') * (slate_scale(p, n) if n else 1.0)
    if f <= 0:
        return 0.0          # no calibrated edge at this price (Oct 27 2026: a pick qualifies only where it has one)
    return min(p['cap'], max(UNIT_MIN, round(f * 4) / 4))


# ---------------------------------------------------------------- fit (numpy)

def adj(r, pu, m, o=None):
    """a return r at price o (BASE) with its edge over a fair coin scaled by m: what a fair coin returns there, plus m x
    the rest (the history's leak and the timing haircut)"""
    B = dec(BASE if o is None else o) - 1
    r0 = (1 - pu) * (B - 1) / 2
    return r0 + m * (r - r0)


def _blocks(keys, k):
    """slate -> fold, k contiguous blocks in time order"""
    ks = sorted(set(keys))
    return {s: min(k - 1, i * k // max(1, len(ks))) for i, s in enumerate(ks)}


def _affine(x, y, g):
    """y on x with an intercept, x centered: {a (at the mean), b, evbar, V (slate-clustered)} or None"""
    import numpy as np
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 10:
        return None
    xb = float(x.mean())
    X = np.column_stack([np.ones(len(x)), x - xb])
    XtX = X.T @ X
    if abs(np.linalg.det(XtX)) < 1e-12:
        return None
    Xi = np.linalg.inv(XtX)
    beta = Xi @ X.T @ y
    e = y - X @ beta
    sc = {}
    for gi, xi, ei in zip(g, X, e):
        sc[gi] = sc.get(gi, 0.0) + xi * ei
    G = len(sc)
    M = sum(np.outer(s, s) for s in sc.values())
    V = Xi @ M @ Xi * (G / (G - 1) if G > 1 else 1.0)
    Vi = Xi * float(e @ e) / max(1, len(x) - 2)          # few slates understate a clustered error: floor at iid
    V = np.maximum(V, np.diag(np.diag(Vi))) if True else V
    V[0, 1] = V[1, 0] = 0.0
    return {'a': float(beta[0]), 'b': float(beta[1]), 'evbar': xb, 'V': V.tolist(), 'n': len(x)}


def _clip(cf):
    """a calibration whose slope is negative or past 1.5 is no evidence that the size of the edge matters that much"""
    return {**cf, 'b': max(0.0, min(1.5, cf['b']))}


def _scale(cf, s):
    return {**cf, 'a': cf['a'] * s, 'b': cf['b'] * s, 'V': [[v * s * s for v in r] for r in cf['V']]}


def _pool(bt, lv):
    """the backtest and live calibrations by precision, coefficient by coefficient, at the backtest's evbar"""
    a_l = lv['a'] + lv['b'] * (bt['evbar'] - lv['evbar'])
    va_l = lv['V'][0][0] + (bt['evbar'] - lv['evbar']) ** 2 * lv['V'][1][1]
    out = dict(bt)
    for k, (x0, v0, x1, v1) in {'a': (bt['a'], bt['V'][0][0], a_l, va_l), 'b': (bt['b'], bt['V'][1][1], lv['b'], lv['V'][1][1])}.items():
        if v0 <= 0 or v1 <= 0:
            continue
        w0, w1 = 1 / v0, 1 / v1
        out[k] = (x0 * w0 + x1 * w1) / (w0 + w1)
        out['V'] = [list(r) for r in out['V']]
        i = 0 if k == 'a' else 1
        out['V'][i][i] = 1 / (w0 + w1)
    out['V'][0][1] = out['V'][1][0] = 0.0
    out['n'] = bt['n'] + lv['n']
    return out


def _icc(groups):
    """one-way ANOVA within-group correlation"""
    gs = [v for v in groups.values() if len(v) >= 2]
    if len(gs) < 5:
        return 0.0
    N = sum(len(v) for v in gs)
    a = len(gs)
    m = sum(sum(v) for v in gs) / N
    ssb = sum(len(v) * (sum(v) / len(v) - m) ** 2 for v in gs)
    ssw = sum(sum((x - sum(v) / len(v)) ** 2 for x in v) for v in gs)
    msb, msw = ssb / (a - 1), ssw / (N - a)
    n0 = (N - sum(len(v) ** 2 for v in gs) / N) / (a - 1)
    r = (msb - msw) / (msb + (n0 - 1) * msw) if msb + (n0 - 1) * msw > 0 else 0.0
    return max(0.0, min(0.5, r))


def slate_of(sport, g):
    if sport in ('cfb', 'nfl') and g.get('wk') is not None:
        return f"{g['S']}-w{int(g['wk']):02d}"
    return str(g.get('date') or '')[:10]


def bad_open(sport, mk, g):
    """an opening line the history got wrong: a mirrored spread or an impossible move to the close (clv.bad_open, the
    shared cleaner). Neither could have been bet, and both show up as huge closing line value."""
    import clv as C
    return C.bad_open_g(sport, mk, g)


def picks_history(sport, res):
    """the held-out picks the live rules would have made at the open, one a game: [{slate, S, mk, side, line, edge,
    rule, clv, clvRet, profit, close, g}] and the rules they came from"""
    import games_picks as GP
    F = json.load(open(GP.FIT))['sports']
    RS = res['sports'][sport]
    R = RS['markets']
    caps = F.get(sport, {}).get('cap') or [None, None]
    # every rule switched on on validation, the ones the test seasons then vetoed included (Oct 21 2026 audit): the
    # veto is a choice made on the test picks, so calibrating on the survivors' test picks alone counted only the
    # rules that happened to win there (CBB venue:home was calibrated on its own 34 test picks; line 15+ and tier
    # mixed, vetoed at -0.8% and -1.0%, were left out). The live rules are the survivors; the history is all of them.
    VETO = ('did not beat the close on the test seasons', 'lost to the close on the test seasons')
    rules, live = [], []
    for mk in ('spread', 'total'):
        m = R.get(mk) or {}
        if m.get('x') is not None and (m.get('on') and m.get('k') or m.get('why') == VETO[0]):
            rules.append({'id': f'{mk}', 'mk': mk, 'x': m['x'], 'fam': None, 'live': bool(m.get('on'))})
    for z in [c for c in res.get('segmentTests') or [] if c.get('sport') == sport and (c.get('on') or c.get('why') == VETO[1])]:
        rules.append({'id': f"{z['mk']}:{z['fam']}:{z['val']}", 'mk': z['mk'], 'x': z['x'], 'fam': z['fam'], 'val': z['val'], 'live': bool(z.get('on'))})
    live = [r for r in rules if r['live']]
    if not live:
        return [], live
    rules = [r for r in rules if r['mk'] in {x['mk'] for x in live}]
    rows = [r for r in GP.load_wf(sport) if r.get('res') is not None]
    # the test seasons only (games_picks.py since PR #304: X picked on tuning, switched on on validation, the test
    # seasons pick nothing but a veto, and the vetoed rules' picks stay in), so the history is not chosen by its results
    test = {S for mk in ('spread', 'total') for S in (R.get(mk) or {}).get('held') or []}
    out = []
    for mk in ('spread', 'total'):
        mr = [r for r in rules if r['mk'] == mk]
        if not mr:
            continue
        rs = [r for r in rows if (r.get('Lo') if mk == 'spread' else r.get('To')) is not None and r['S'] in test]
        cap = caps[0] if mk == 'spread' else caps[1]
        for e in GP.rule_bets(sport, rs, mk, min(r['x'] for r in mr), True, cap):
            sg = GP.seg_of(sport, e['g'], mk, e['side'], e['line'])
            ap = [r for r in mr if r['fam'] is None or sg.get(r['fam']) == r['val']]
            if not ap:
                continue
            rule = min(ap, key=lambda r: r['x'])
            if e['edge'] < rule['x'] or e.get('clvRet') is None or bad_open(sport, mk, e['g']):
                continue
            g = e['g']
            out.append({'slate': slate_of(sport, g), 'S': g['S'], 'id': g['id'], 'mk': mk, 'side': e['side'], 'line': e['line'],
                        'edge': e['edge'], 'rule': rule['id'], 'clv': e.get('clv') or 0.0, 'mult': LEAK.get(sport, 1.0) * TIMING,
                        'clvRet': adj(e['clvRet'], 0.0, LEAK.get(sport, 1.0) * TIMING),
                        'profit': e['profit'], 'close': g['L'] if mk == 'spread' else g['T'],
                        'res': g['res'] if mk == 'spread' else g['tot']})
    return out, live


def rho_of(sport, mk):
    """within-slate correlation of the model's side against the close, every held-out game with an edge"""
    import games_picks as GP
    tune = set(GP.RULE_TUNE[sport])
    rows = [r for r in GP.load_wf(sport) if r.get('res') is not None and r['S'] > max(tune)
            and (r.get('Lo') if mk == 'spread' else r.get('To')) is not None]
    groups = {}
    for e in GP.rule_bets(sport, rows, mk, GP.RULE_GRID[mk][0], True):
        g = e['g']
        close, res = (g['L'], g['res']) if mk == 'spread' else (g.get('T'), g.get('tot'))
        if close is None or res is None:
            continue
        sgn = 1 if e['side'] in ('home', 'over') else -1
        groups.setdefault(slate_of(sport, g), []).append(sgn * (res - close))
    return _icc(groups)


def live_pairs(sport, mk):
    """(gap, clvRet, slate) of graded live picks: the games_picks log and the paper book"""
    out = []
    try:
        for e in json.load(open(os.path.join(ROOT, 'data', f'games_picks_{sport}.json'))).get('log', []):
            if e.get('clvRet') is not None and e.get('edge') is not None and ('spread' if e['mk'] == 'ml' else e['mk']) == mk:
                out.append((e['edge'], e['clvRet'], 'g' + str(e.get('kick', ''))[:10]))
    except (OSError, ValueError):
        pass
    try:
        for b in json.load(open(os.path.join(ROOT, 'data', 'paper_book.json'))).get('ledger', []):
            # staked bets only, and no totals where DU's gap is the recentred one (games_picks.RC_SPORTS): the paper
            # book's totals gap is the raw model minus the line (Oct 21 2026 audit)
            if b.get('sport') == sport and b.get('mk') == mk and b.get('clvRet') is not None and b.get('gap') is not None \
                    and (b.get('stake') or 0) > 0 and not (mk == 'total' and sport in ('nba', 'cfb')):
                out.append((b['gap'], b['clvRet'], 'p' + str(b.get('k', ''))[:10]))
    except (OSError, ValueError):
        pass
    return out


def crossfit(sport, picks):
    """each held-out pick's expected return from k fit on the other blocks of slates, and its fold's calibration (fit
    on the other blocks too); one pick a game (the market with the most expected return), as live"""
    import games_picks as GP
    import clv as C
    fold = _blocks([p['slate'] for p in picks], FOLDS)
    for p in picks:
        p['fold'] = fold[p['slate']]

    def ev_of(p, k):
        c = GP.calib(sport, p['mk'], p['side'], p['line'], p['edge'], k)
        return (c, (c[0] * (dec(BASE) - 1) - c[2]) if c else None)

    def ks_of(tr):
        # one k per market, not per rule: a market's segments are overlapping slices of one edge (Oct 21 2026: NBA
        # totals early/late/under/over/mid), so DU prices every pick in a market on the same line move per point
        ks = {}
        for mk in {p['mk'] for p in picks}:
            rr = [p for p in tr if p['mk'] == mk]
            se = sum(p['edge'] for p in rr)
            k = sum(p['clv'] for p in rr) / se if se > 0 else 0.0
            for rid in {p['rule'] for p in picks if p['mk'] == mk}:
                ks[rid] = k
        return ks
    # every pick's expectation out of its own fold
    oof = {}
    for f in range(FOLDS):
        ks = ks_of([p for p in picks if p['fold'] != f])
        for i, p in enumerate(picks):
            if p['fold'] == f:
                oof[i] = (ks[p['rule']],) + ev_of(p, ks[p['rule']])
    chosen = []
    best = {}
    for i, p in enumerate(picks):
        k, c, ev = oof[i]
        if ev is None or ev <= 0:
            continue
        q = {**p, 'c': c, 'ev': ev, 'k': k, 'truth': C.chances(sport, p['mk'], p['side'], p['line'], p['close'])}
        if q['truth'] is None:
            continue
        if p['mult'] != 1.0:
            # the close's chance moved toward a fair coin so the bet's edge over one is mult (leak x timing) x what it
            # was at the close
            w, pu, l = q['truth']
            w2 = (1 - pu + p['mult'] * (w - l)) / 2
            q['truth'] = (w2, pu, 1 - pu - w2)
        if p['id'] not in best or ev > best[p['id']]['ev']:
            best[p['id']] = q
    return list(best.values())


def calibrate(units, key, fold=None):
    """the edge's calibration for one market on the gap: its level (close value and ROI by precision, at its mean gap)
    and its own slope per point of gap, shrunk by its evidence, never negative. fold: leave that block out."""
    keep = lambda x: fold is None or x['fold'] != fold
    xs = [x for x in units[key]['bets'] if keep(x)]
    own = _affine([x['edge'] for x in xs], [x['clvRet'] for x in xs], [x['slate'] for x in xs])
    if not own:
        return None
    vb = own['V'][1][1]
    b = max(0.0, own['b']) * (own['b'] ** 2 / (own['b'] ** 2 + vb) if vb > 0 else 1.0)
    # the level: what the market's picks were worth at the close and what they actually returned (ROI at the price,
    # which is the cover or win rate against the odds), by precision; results swing ~0.95 a bet against ~0.15 at the
    # close, so the close carries most of the weight until results pile up
    rf = _affine([x['edge'] for x in xs], [adj(x['profit'], 0.0, x['mult']) for x in xs], [x['slate'] for x in xs])
    a_c, v_c = own['a'], own['V'][0][0]
    a, va = a_c, v_c
    if rf and rf['V'][0][0] > 0 and v_c > 0:
        va = 1 / (1 / v_c + 1 / rf['V'][0][0])
        a = (a_c / v_c + rf['a'] / rf['V'][0][0]) * va
    dec_ = [x for x in xs if x['profit'] != 0]
    return {**own, 'on': 'gap', 'a': a, 'b': min(1.5, b), 'V': [[va, 0.0], [0.0, vb]], 'bOwn': own['b'], 'seBOwn': math.sqrt(vb),
            'aClose': a_c, 'seClose': math.sqrt(v_c), 'aRoi': rf['a'] if rf else None, 'seRoi': math.sqrt(rf['V'][0][0]) if rf else None,
            'cover': sum(1 for x in dec_ if x['profit'] > 0) / len(dec_) if dec_ else None}


def draws(bets, rho, seed=7):
    """results drawn from the close's chances, DRAWS times, correlated at rho within a slate (a shared normal shock):
    (draws x bets results per unit, slate index per bet, slate keys)"""
    import numpy as np
    from statistics import NormalDist
    rng = np.random.default_rng(seed)
    sl = sorted({b['slate'] for b in bets})
    idx = {s: i for i, s in enumerate(sl)}
    gi = np.array([idx[b['slate']] for b in bets])
    N = NormalDist()
    cut = lambda q: N.inv_cdf(min(1 - 1e-9, max(1e-9, q)))
    zw = np.array([cut(b['truth'][0]) for b in bets])
    zp = np.array([cut(b['truth'][0] + b['truth'][1]) for b in bets])
    z = math.sqrt(rho) * rng.standard_normal((DRAWS, len(sl)))[:, gi] + math.sqrt(1 - rho) * rng.standard_normal((DRAWS, len(bets)))
    X = np.where(z < zw, dec(BASE) - 1, np.where(z < zp, 0.0, -1.0))
    return X, gi, sl


def simulate(bets, stakes, D):
    """per slate: mean log growth at the close (over the draws D) and the realized log growth"""
    import numpy as np
    X, gi, sl = D
    st = np.asarray(stakes, float) / 100
    tot = np.zeros((len(sl), X.shape[0]))
    np.add.at(tot, gi, (X * st).T)
    real = np.zeros(len(sl))
    np.add.at(real, gi, np.array([b['profit'] for b in bets]) * st)
    return np.log(np.maximum(1 + tot, 1e-9)).mean(axis=1), np.log(np.maximum(1 + real, 1e-9)), sl, tot


def path_stats(logs):
    import numpy as np
    eq = np.exp(np.cumsum(np.concatenate([[0.0], logs])))
    peak = np.maximum.accumulate(eq)
    return float((1 - eq / peak).max()), float(eq[-1])


def ruin(bets, stakes, D, per_season, seed=11):
    """seasons stitched from random (slate, draw) pairs at these stakes: drawdown odds and the season's spread"""
    import numpy as np
    rng = np.random.default_rng(seed)
    _, _, sl, tot = simulate(bets, stakes, D)
    lg = np.log(np.maximum(1 + tot, 1e-9))                  # slates x draws
    n = max(1, int(round(per_season)))
    L = lg[rng.integers(0, lg.shape[0], (SEASONS_SIM, n)), rng.integers(0, lg.shape[1], (SEASONS_SIM, n))]
    eq = np.concatenate([np.ones((SEASONS_SIM, 1)), np.exp(np.cumsum(L, axis=1))], axis=1)
    mdd = (1 - eq / np.maximum.accumulate(eq, axis=1)).max(axis=1)
    fin = eq[:, -1]
    return {'dd25': round(float((mdd >= 0.25).mean()), 3), 'dd50': round(float((mdd >= 0.5).mean()), 3),
            'mddMed': round(float(np.median(mdd)), 3), 'finMed': round(float(np.median(fin)), 3),
            'fin05': round(float(np.quantile(fin, 0.05)), 3), 'fin95': round(float(np.quantile(fin, 0.95)), 3)}


def fit():
    import numpy as np
    import games_picks as GP
    res = json.load(open(GP.RULES))
    units = {}
    for sport in GP.SPORTS:
        picks, rules = picks_history(sport, res) if sport != 'nfl' else ([], [])
        if not picks:
            continue
        chosen = crossfit(sport, picks)
        seasons = sorted({p['S'] for p in picks})
        for mk in ('spread', 'total'):
            bs = [b for b in chosen if b['mk'] == mk]
            if len(bs) < 20:
                continue
            units[(sport, mk)] = {'bets': bs, 'rho': rho_of(sport, mk), 'nbar': len(bs) / len({b['slate'] for b in bs}),
                                  'seasons': seasons, 'perSeason': len({b['slate'] for b in bs}) / len(seasons),
                                  'rules': [r['id'] for r in rules if r['mk'] == mk]}
    B = dec(BASE) - 1
    for key, U in units.items():
        cals = {f: calibrate(units, key, f) for f in range(FOLDS)}
        for x in U['bets']:
            x['cal'] = cals[x['fold']]
        U['bets'] = [x for x in U['bets'] if x['cal']]

    def stakes_at(U, lam, cap):
        import numpy as np
        p = {'rho': U['rho'], 'nbar': U['nbar']}
        n_sl = {}
        for x in U['bets']:
            n_sl[x['slate']] = n_sl.get(x['slate'], 0) + 1
        base = np.array([kelly_pct(x['cal'], x['c'], BASE, x['edge']) * slate_scale(p, n_sl[x['slate']]) for x in U['bets']])
        return np.clip(np.where(base > 0, np.maximum(UNIT_MIN, lam * base), UNIT_MIN), 0, cap)

    out = {'asof': datetime.date.today().isoformat(), 'lams': [LAMS[0], LAMS[-1]], 'caps': list(CAPS), 'unitMin': UNIT_MIN,
           'default': DEFAULT, 'leak': LEAK, 'sports': {}}
    book = []
    for (sport, mk), U in units.items():
        bs = U['bets']
        n = len(bs)
        D = U['D'] = draws(bs, U['rho'])
        G = {}
        for cap in CAPS:
            for lam in LAMS:
                st = stakes_at(U, lam, cap)
                gc, gr, _, _ = simulate(bs, st, D)
                G[(lam, cap)] = (float(gc.sum()) / n, float(gr.sum()) / n, float(st.mean()))
        # lam on the uncapped curve (a binding cap makes every lam alike), pulled toward 1 when thin; then the cap
        top = max(G[(lm, CAPS[-1])][0] for lm in LAMS)
        lam_own = max(lm for lm in LAMS if G[(lm, CAPS[-1])][0] >= top - 1e-12)
        cap_own = max((c for c in CAPS), key=lambda c: (G[(lam_own, c)][0], c))
        w = n / (n + LAM_N0)
        lam = round(round((w * lam_own + (1 - w) * 1.0) / 0.05) * 0.05, 2)
        ct = max(G[(lam, c)][0] for c in CAPS)
        cap = max(c for c in CAPS if G[(lam, c)][0] >= ct - 1e-12)
        peak = max(LAMS, key=lambda lm: G[(lm, cap)][0])
        zero = next((lm for lm in LAMS if lm > peak and G[(lm, cap)][0] <= 0), None)
        # uncapped: where more stake stops paying and where it stops growing at all
        zero_u = next((lm for lm in LAMS if lm > lam_own and G[(lm, CAPS[-1])][0] <= 0), None)
        free = [{'lam': lm, 'g': round(G[(lm, CAPS[-1])][0] * n / len(U['seasons']) * 100, 2), 'mean': round(G[(lm, CAPS[-1])][2], 2)}
                for lm in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)]

        def row(lm, cp, label=None, st=None):
            st = stakes_at(U, lm, cp) if st is None else st
            gc, gr, sl, _ = simulate(bs, st, D)
            mdd, fin = path_stats(gr[np.argsort(sl)])
            r = {'lam': lm, 'cap': cp, 'mean': round(float(st.mean()), 2), 'max': round(float(st.max()), 2),
                 'gClose': round(float(gc.sum()) / len(U['seasons']) * 100, 2), 'gReal': round(float(gr.sum()) / len(U['seasons']) * 100, 2),
                 'mddReal': round(mdd, 3), 'finReal': round(fin, 3), **ruin(bs, st, D, U['perSeason'])}
            if label:
                r['label'] = label
            return r
        # the old system: the fraction picked on held-out picks x Kelly on the model's own expectation, 0.25-3u
        old = OLD_FRAC.get((sport, mk), 0.25)
        st_old = np.array([min(3.0, max(UNIT_MIN, round(max(0.0, x['ev'] / B) * old * 100 * 4) / 4)) for x in bs])
        curve = [row(lm, cap) for lm in (0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)]
        mult = [row(lm, CAPS[-1], f'{lm:g}x Kelly') for lm in (0.5, 1.0, 1.5, 2.0)]
        cmp = [row(old, 3.0, f'old: {old:g} Kelly on the raw expectation, 3u cap', st_old), row(lam, cap, 'new')]
        book.append((U, lam, cap))
        # the live calibration: every held-out pick's expectation out of fold, the leak taken out, live picks pooled in
        cf = calibrate(units, (sport, mk))
        bt = dict(cf)
        lv_pairs = live_pairs(sport, mk)
        lv = _affine([x[0] for x in lv_pairs], [x[1] for x in lv_pairs], [x[2] for x in lv_pairs]) if len(lv_pairs) >= LIVE_MIN else None
        live = dict(bt)                 # the history's close value was already scaled by LEAK
        if lv:
            live = _clip(_pool(live, lv))
        xm = sorted(bs, key=lambda x: x['edge'])[len(bs) // 2]
        mid = xm['ev']
        e_mid, u_mid = edge(live, mid, xm['edge'])
        lam_l, cap_l = lam, cap
        if live['a'] + live['b'] * (max(x['edge'] for x in bs) - live['evbar']) <= 0:
            lam_l, cap_l = 0.0, UNIT_MIN    # no calibrated edge anywhere in the market: listed picks get the floor
        if (sport, mk) in HOLD:
            cap_l = min(cap_l, HOLD[(sport, mk)])
        book[-1] = (U, lam_l, cap_l)        # the whole book at the stakes live will use
        live.update({'lam': lam_l, 'cap': cap_l, 'hold': HOLD.get((sport, mk)), 'rho': round(U['rho'], 3), 'nbar': round(U['nbar'], 2),
                     'basis': 'backtest + live picks' if lv else 'backtest'})
        out['sports'].setdefault(sport, {})[mk] = {
            'live': {k: (round(v, 5) if isinstance(v, float) else v) for k, v in live.items()},
            'backtest': {'on': 'gap', 'a': round(cf['a'], 4), 'b': round(cf['b'], 4), 'gbar': round(cf['evbar'], 2),
                         'seA': round(math.sqrt(cf['V'][0][0]), 4), 'seB': round(math.sqrt(cf['V'][1][1]), 3),
                         'bOwn': round(cf['bOwn'], 3), 'seBOwn': round(cf['seBOwn'], 3), 'n': n,
                         'aClose': round(cf['aClose'], 4), 'seClose': round(cf['seClose'], 4),
                         'aRoi': None if cf['aRoi'] is None else round(cf['aRoi'], 4), 'seRoi': None if cf['seRoi'] is None else round(cf['seRoi'], 4),
                         'cover': None if cf['cover'] is None else round(cf['cover'], 3)},
            'livePicks': ({'a': round(lv['a'], 4), 'b': round(lv['b'], 3), 'n': lv['n']} if lv else {'n': len(lv_pairs)}),
            'leak': LEAK.get(sport), 'n': n, 'seasons': U['seasons'], 'slatesPerSeason': round(U['perSeason'], 1), 'rules': U['rules'],
            'lamOwn': lam_own, 'capOwn': cap_own, 'lamW': round(w, 3), 'peakLam': peak, 'zeroLam': zero, 'zeroLamFree': zero_u, 'free': free,
            'median': {'gap': xm['edge'], 'ev': round(mid, 4), 'edge': round(e_mid, 4), 'u': round(u_mid, 3),
                       'units': stake(sport, mk, xm['c'], BASE, p={**DEFAULT, **live}, gap=xm['edge'])},
            'curve': curve, 'compare': cmp, 'kellyX': mult, 'capGrowth': {str(c): round(G[(lam, c)][0] * n / len(U['seasons']) * 100, 2) for c in CAPS}}
        r = cmp[1]
        print(f"{sport} {mk} (n {n}): edge = {cf['a']:.3f} + {cf['b']:.4f} (gap - {cf['evbar']:.2f}) [se {math.sqrt(cf['V'][0][0]):.3f}, {math.sqrt(cf['V'][1][1]):.4f}; own b {cf['bOwn']:.4f} se {cf['seBOwn']:.4f}; close {cf['aClose']:.3f} se {cf['seClose']:.3f}, roi {cf['aRoi']:.3f} se {cf['seRoi']:.3f}, cover {cf['cover']:.3f}]; "
              f"rho {U['rho']:.3f} nbar {U['nbar']:.1f}; lam own {lam_own} cap {cap_own} -> lam {lam} cap {cap}; peak {peak}, growth 0 at {zero} (uncapped {zero_u})")
        print('   uncapped', [(f['lam'], f['mean'], f['g']) for f in free])
        print(f"   new: mean {r['mean']}u max {r['max']}u, growth/season close {r['gClose']}% real {r['gReal']}%, dd25 {r['dd25']} dd50 {r['dd50']}, season {r['fin05']}-{r['finMed']}-{r['fin95']}")
        r = cmp[0]
        print(f"   old: mean {r['mean']}u max {r['max']}u, growth/season close {r['gClose']}% real {r['gReal']}%, dd25 {r['dd25']} dd50 {r['dd50']}, season {r['fin05']}-{r['finMed']}-{r['fin95']}")
        print('   median pick', out['sports'][sport][mk]['median'])
        print('   caps at lam', out['sports'][sport][mk]['capGrowth'])
        for r in mult:
            print(f"   {r['label']}: mean {r['mean']}u, growth/season {r['gClose']}%, dd25 {r['dd25']} dd50 {r['dd50']}, season {r['fin05']}-{r['finMed']}-{r['fin95']}")
    # the whole book, compounded: every market's season at once, slates interleaved at random, at DU and at multiples
    # of it (stakes and caps scaled), and a sample season from $1,000 (the median one)
    def book_at(m):
        rng = np.random.default_rng(13)
        seasons = []
        for U, lm, cp in book:
            _, _, _, tot = simulate(U['bets'], stakes_at(U, lm * m, cp * max(1.0, m)), U['D'])
            lg = np.log(np.maximum(1 + tot, 1e-9))
            n = max(1, int(round(U['perSeason'])))
            seasons.append(lg[rng.integers(0, lg.shape[0], (SEASONS_SIM, n)), rng.integers(0, lg.shape[1], (SEASONS_SIM, n))])
        L = np.concatenate(seasons, axis=1)
        L = np.take_along_axis(L, np.argsort(rng.random(L.shape), axis=1), axis=1)
        eq = np.concatenate([np.ones((SEASONS_SIM, 1)), np.exp(np.cumsum(L, axis=1))], axis=1)
        mdd = (1 - eq / np.maximum.accumulate(eq, axis=1)).max(axis=1)
        fin = eq[:, -1]
        path = eq[int(np.argsort(fin)[len(fin) // 2])] * 1000
        return {'mult': m, 'g': round(float(np.log(fin).mean()) * 100, 1), 'dd25': round(float((mdd >= 0.25).mean()), 3),
                'dd50': round(float((mdd >= 0.5).mean()), 3), 'mddMed': round(float(np.median(mdd)), 3),
                'finMed': round(float(np.median(fin)), 3), 'fin05': round(float(np.quantile(fin, 0.05)), 3),
                'fin95': round(float(np.quantile(fin, 0.95)), 3), 'lose': round(float((fin < 1).mean()), 3),
                'slates': int(L.shape[1]), 'sample': {'low': int(path.min()), 'high': int(path.max()), 'end': int(path[-1]),
                                                     'path': [int(v) for v in path[::max(1, len(path) // 12)]] + [int(path[-1])]}}
    if book:
        out['bookX'] = [book_at(m) for m in (0.5, 0.75, 1.0, 1.25, 1.5)]
        out['book'] = next(b for b in out['bookX'] if b['mult'] == 1.0)
        for b in out['bookX']:
            print('book', b)
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    _FIT.clear()
    return out


def test():
    p = {**DEFAULT, 'a': 0.0, 'b': 1.0, 'evbar': 0.0, 'lam': 1.0, 'cap': 10.0}
    c = (0.55, 0.0, 0.45)
    B = 1 / 1.1
    k = (0.55 * B - 0.45) / B
    assert abs(kelly_pct(p, c, -110) - k * 100) < 1e-9                         # b 1, no uncertainty: plain Kelly
    assert stake('cbb', 'spread', c, -110, p=p) == round(k * 100 * 4) / 4
    assert stake('cbb', 'spread', (0.5, 0.0, 0.5), -110, p=p) == 0.0          # no edge at this price
    assert stake('cbb', 'spread', (0.53, 0.0, 0.47), BASE, p={**p, 'b': 0.05}) == UNIT_MIN   # a small edge: the floor
    assert stake('cbb', 'spread', (0.53, 0.0, 0.47), -110, p={**p, 'b': 0.05}) == 0.0        # gone at a worse price
    assert stake('cbb', 'spread', (0.7, 0.0, 0.3), -110, p=p) == 10.0         # the cap
    q = {**p, 'V': [[0.0004, 0.0], [0.0, 0.0]]}                               # an uncertain edge stakes less
    assert kelly_pct(q, c, -110) < kelly_pct(p, c, -110)
    r = {**p, 'rho': 0.2, 'nbar': 3.0}
    assert abs(slate_scale(r, 3) - 1) < 1e-9 and slate_scale(r, 6) < 1 < slate_scale(r, 1)
    assert kelly_pct(p, (0.5, 0.1, 0.4), -110) > kelly_pct(p, (0.5, 0.0, 0.5), -110)
    g = {**p, 'on': 'gap', 'a': 0.03, 'b': 0.01, 'evbar': 6.0}                   # on the gap: bigger gaps stake more
    assert kelly_pct(g, c, BASE, 8.0) > kelly_pct(g, c, BASE, 6.0) > kelly_pct(g, c, BASE, 4.5)
    assert kelly_pct(g, c, -106, 6.0) < kelly_pct(g, c, BASE, 6.0) < kelly_pct(g, c, -101, 6.0)  # a worse price, a smaller stake
    assert kelly_pct(g, c, -110, 6.0) == 0.0                                  # past the edge: no stake
    assert view('cbb', 'spread', c, -115, 6.0)[0] == view('cbb', 'spread', c, -110, 6.0)[0]       # the chance does not move with price
    assert abs(kelly_pct(g, c, -110) - kelly_pct(g, c, -110, 6.0)) < 1e-12    # no gap: the market's average gap
    assert edge(g, 0.02, 9.0)[0] == 0.02                                      # never more than the model expects
    print('units: ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--fit':
        fit()
    elif a and a[0] == '--test':
        test()
    else:
        print(__doc__)
