#!/usr/bin/env python3
"""Close predictor and market softness index (betting plan item 3, Oct 21 2026).

    python3 scripts/close_model.py --fit     # data/close_fit.json (numpy): spec chosen on the tuning seasons, the
                                             # held-out walk-forward, the softness index by cell, the candidate rules
    python3 scripts/close_model.py --test    # self-check

The target is the closing line, not the result. For every game with an opening line:

    close - open = b(cell, gap) x (model - open) + controls

b is the share of our disagreement with the open that the market later agrees with: the market's softness. A close
that never moves toward us (b = 0) means the open already knew what the model knows; b = 1 means the open was wrong by
our whole gap. b bends with the gap: a big gap is more often our error than the market's, so the move per point of gap
falls past a knot (a hinge in |gap|, knot chosen on the tuning seasons). Cells (pre-registered below, fixed before any
held-out season was scored): conference tier, the part of the season, line size and, for basketball, neutral court or
back-to-back. Each cell shifts b, shrunk toward the pooled b by a ridge whose strength is also chosen on the tuning
seasons, so a thin cell has to earn its own slope.

The bet: the model's side at the open when the predicted close makes it worth something, E[clvRet] = the return a
-110 bet at the open is worth if the close lands where predicted (scripts/clv.py), above a cut tau chosen on the tuning
seasons. Because the predicted move rises with the gap at a rate set by the cell, this is a gap rule whose cut differs by
cell: a softer cell needs a smaller gap. The break-even gap is where E[clvRet] crosses 0 at -110.

Seasons: tuning CFB 2025, CBB 2024, NBA 2015-17; held out CFB 2026, CBB 2025-26, NBA 2024-26 (the same split as the pick
rules). Held-out seasons are predicted walk-forward: each by a fit on the seasons before it with the spec fixed on
tuning. Scored by out-of-sample R^2 of the line move and by the close-implied return of the bets it selects against the
plain gap rule (X chosen on tuning the way scripts/games_picks.py picks it). Cells are tested held out with a one-sided
t on clvRet and Benjamini-Hochberg at q .10 across every pre-registered cell; a cell that passes goes to the paper book
as a candidate rule with its own clock. NBA held-out numbers are an upper bound: the walk-forward model saw tip-time
injury news the open did not have.

Live (stdlib only): expected(sport, mk, g) -> the predicted close and E[clvRet] for a game dict with the open, the model
and the cell fields, from the final fit (all seasons) in data/close_fit.json. scripts/paper_book.py imports it.

Dense snapshots (thread A's scripts/data/odds_dense, and scripts/data/odds): hours to the start and the line's moves so
far join the controls once a season of them exists; until then --fit only counts them.
"""
import datetime
import gzip
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import clv  # noqa: E402


class _Units:
    # scripts/units.py imports this module, so it is loaded on first use
    def __getattr__(self, k):
        import units
        return getattr(units, k)


UN = _Units()

OUT = os.path.join(ROOT, 'data', 'close_fit.json')
WF = os.path.join(HERE, 'data', 'games_wf')
GP_FIT = os.path.join(ROOT, 'data', 'games_picks_fit.json')
WEATHER = os.path.join(HERE, 'data', 'cfb_weather.json')
NAMES = {'cfb': 'CFB', 'cbb': 'CBB', 'nba': 'NBA'}

# ---- the pre-registration (Oct 21 2026): seasons, markets, cells. Nothing below changes after the held-out run.
SPEC = {
    'cfb': {'tune': [2023, 2024], 'held': [2025, 2026], 'markets': ('spread', 'total')},   # ESPN opens from 2023 (Oct 23 2026)
    'cbb': {'tune': [2024], 'held': [2025, 2026], 'markets': ('spread',)},     # no opening totals in the CBB history
    'nba': {'tune': [2015, 2016, 2017], 'held': [2024, 2025, 2026], 'markets': ('spread', 'total')},
}
P4 = {'SEC', 'Big Ten', 'Big 12', 'ACC'}
CBB_HIGH = {'ACC', 'B10', 'B12', 'SEC', 'BE'}
CBB_MID = {'A10', 'Amer', 'MWC', 'WCC', 'MVC', 'P12'}
# each dimension: name -> levels in display order (the first is the reference level of the main effect)
DIMS = {
    'cfb': {'tier': ('P4', 'G5', 'FCS'), 'phase': ('wk 1-4', 'wk 5+'), 'size': ('small', 'mid', 'big')},
    'cbb': {'tier': ('high', 'mid', 'low'), 'phase': ('nov', 'dec', 'jan-feb', 'mar'), 'court': ('home', 'neutral'),
            'size': ('small', 'mid', 'big')},
    'nba': {'phase': ('oct-nov', 'dec-feb', 'mar-apr', 'playoffs'), 'rest': ('rested', 'back-to-back'),
            'size': ('small', 'mid', 'big')},
}
# line-size cuts: spreads by |open| in points, totals by the open total (terciles of the tuning seasons, set in --fit)
SIZE_SPREAD = {'cfb': (7, 17), 'cbb': (5, 12), 'nba': (4, 9)}
KNOTS = (None, 2, 3, 4, 5, 6, 8)          # None: a straight b
LAMS = (0.03, 0.1, 0.3, 1.0, 3.0, None)   # ridge on the cell shifts, as a share of the cell's own x^2; None: no cells
TAUS = (0.0, 0.01, 0.02, 0.03, 0.05)
XGRID = tuple(x / 2 for x in range(2, 21))  # plain gap rule cuts 1-10
MIN_N, MIN_T, KEEP_T, FDR_Q = 40, 1.0, 1.65, 0.10
PRICE = -110


# ---------------------------------------------------------------- rows and cells (stdlib)

def tier(sport, g, conf):
    if sport == 'cfb':
        if g.get('fcs'):
            return 'FCS'
        return 'P4' if all(conf.get(t) in P4 or t == 'Notre Dame' for t in (g['home'], g['away'])) else 'G5'
    if sport == 'cbb':
        cs = [conf.get(t) for t in (g['home'], g['away'])]
        return 'high' if any(c in CBB_HIGH for c in cs) else 'mid' if any(c in CBB_MID for c in cs) else 'low'
    return None


def phase(sport, g):
    if sport == 'cfb':
        return 'wk 1-4' if (g.get('wk') or 0) <= 4 else 'wk 5+'
    mo = int(g['date'][5:7])
    if sport == 'cbb':
        return 'mar' if g.get('po') or mo in (3, 4) else 'nov' if mo == 11 else 'dec' if mo == 12 else 'jan-feb'
    if g.get('po'):
        return 'playoffs'
    return 'oct-nov' if mo in (10, 11) else 'dec-feb' if mo in (12, 1, 2) else 'mar-apr'


def size(sport, mk, o, tcuts):
    a, b = SIZE_SPREAD[sport] if mk == 'spread' else tcuts
    v = abs(o) if mk == 'spread' else o
    return 'small' if v < a else 'mid' if v < b else 'big'


def cells(sport, mk, g, tcuts):
    o = g['Lo'] if mk == 'spread' else g['To']
    c = {'size': size(sport, mk, o, tcuts or (0, 0))}
    if 'tier' in DIMS[sport]:
        c['tier'] = g['_tier']
    c['phase'] = phase(sport, g)
    if sport == 'cbb':
        c['court'] = 'neutral' if g.get('neutral') else 'home'
    if sport == 'nba':
        c['rest'] = 'back-to-back' if g.get('_b2b') else 'rested'
    return c


def local_day(d):
    # ESPN times are UTC; an evening US game is the next UTC day. Six hours back puts it on the local date.
    if len(d) <= 10:
        return datetime.date.fromisoformat(d)
    t = datetime.datetime.fromisoformat(d.replace('Z', '+00:00'))
    return (t - datetime.timedelta(hours=6)).date()


def load(sport):
    rows = json.load(gzip.open(os.path.join(WF, sport + '.json.gz')))
    conf = {}
    if sport == 'cfb':
        conf = {t['team']: t['conf'] for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']}
    elif sport == 'cbb':
        conf = {p['t']: p['conf'] for p in json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']}
    if sport == 'nba':
        played = {}
        for g in rows:
            d = local_day(g['date'])
            for t in (g['home'], g['away']):
                played.setdefault(t, set()).add(d)
        for g in rows:
            d = local_day(g['date']) - datetime.timedelta(days=1)
            g['_b2b'] = int(d in played.get(g['home'], ()) or d in played.get(g['away'], ()))
    out = []
    for g in rows:
        if g.get('Lo') is None or g.get('L') is None or g.get('m') is None or g['S'] not in SPEC[sport]['tune'] + SPEC[sport]['held']:
            continue
        g['_tier'] = tier(sport, g, conf)
        out.append(g)
    return out


def mirrored(o, c):
    """an open that is the close with home and away swapped (-4.5 then 4.5): clv.mirrored, the shared cleaner"""
    return clv.mirrored(o, c)


def market_rows(sport, mk, rows, cap):
    """(o, c, m, res, S, date, game) per game with an open and a close in this market; gaps past the cap are bad
    lines, and so are mirrored spreads and the shared cleaner's bad opens (scripts/units.py bad_open)"""
    out = []
    for g in rows:
        o, c, m, res = (g['Lo'], g['L'], g['m'], g['res']) if mk == 'spread' else (g.get('To'), g.get('T'), g.get('tm'), g.get('tot'))
        if None in (o, c, m, res) or (cap is not None and abs(m - o) > cap) or (mk == 'spread' and mirrored(o, c)):
            continue
        if UN.bad_open(sport, mk, g):    # the shared cleaner: also opens whose move to the close is too big to be real
            continue
        out.append({'o': o, 'c': c, 'm': m, 'res': res, 'S': g['S'], 'date': g['date'], 'g': g})
    return out


# ---------------------------------------------------------------- the predictor (numpy for the fit, stdlib to apply)

def hinge(x, k):
    return 0.0 if k is None else math.copysign(max(abs(x) - k, 0.0), x)


def features(sport, mk, r, spec):
    """the design row: [controls..., x, hinge(x), x * cell level...] and which columns the ridge penalizes"""
    o, x = r['o'], r['m'] - r['o']
    cl = r['cells']
    ctrl = [1.0, o / 10 if mk == 'spread' else (o - spec['oMean']) / 10]
    if mk == 'spread' and sport != 'nba':
        ctrl.append(1.0 if r['g'].get('neutral') else 0.0)
    for lv in DIMS[sport]['phase'][1:]:
        ctrl.append(1.0 if cl['phase'] == lv else 0.0)
    gap = [] if spec.get('gap') is False else [x] + ([hinge(x, spec['knot'])] if spec['knot'] is not None else [])
    shifts = []
    if spec['lam'] is not None:
        for d, lvs in DIMS[sport].items():
            for lv in lvs:
                shifts.append(x if cl[d] == lv else 0.0)
    return ctrl + gap + shifts, len(ctrl) + len(gap)


def fit_spec(sport, mk, rs, knot, lam, oMean, gap=True):
    import numpy as np
    spec = {'knot': knot, 'lam': lam, 'oMean': oMean, 'gap': gap}
    X, ncore = [], 0
    for r in rs:
        f, ncore = features(sport, mk, r, spec)
        X.append(f)
    X, y = np.asarray(X), np.asarray([r['c'] - r['o'] for r in rs])
    P = np.full(X.shape[1], 1e-6 * len(rs))     # keeps a fold without one phase solvable
    if lam is not None:
        # every shift's penalty is lam x the market's whole sum of x^2: a cell with share p of the gap variance keeps
        # about p / (p + lam) of its own slope, so a thin cell stays near the pooled b
        P[ncore:] += lam * sum((r['m'] - r['o']) ** 2 for r in rs)
    beta = np.linalg.solve(X.T @ X + np.diag(P), X.T @ y)
    spec['beta'] = [round(float(b), 5) for b in beta]
    return spec


def predict(sport, mk, r, spec):
    f, _ = features(sport, mk, r, spec)
    return sum(a * b for a, b in zip(f, spec['beta']))


def e_ret(sport, mk, r, move):
    """the side the predicted close moves toward, taken at the open, and what it is worth at -110 if the close lands
    at open + move. With no drift terms that is the model's side; the controls can move it."""
    side = ('home' if move > 0 else 'away') if mk == 'spread' else ('over' if move > 0 else 'under')
    return side, clv.ret(sport, mk, side, r['o'], PRICE, r['o'] + move)


def realized(sport, mk, r, side):
    e = clv.judge({}, sport, mk, side, r['o'], PRICE, r['c'])
    d = (r['res'] - r['o']) if side in ('home', 'over') else (r['o'] - r['res'])
    e['profit'] = 0.0 if d == 0 else (clv.dec(PRICE) - 1 if d > 0 else -1.0)
    return e


def folds(rs, seasons):
    """inner folds on the tuning seasons: leave a season out, or five date blocks within one season"""
    if len(seasons) > 1:
        return [[i for i, r in enumerate(rs) if r['S'] == s] for s in seasons]
    order = sorted(range(len(rs)), key=lambda i: rs[i]['date'])
    k = 5
    return [order[j * len(order) // k:(j + 1) * len(order) // k] for j in range(k)]


def oof(sport, mk, rs, seasons, knot, lam, oMean):
    pred = [None] * len(rs)
    for idx in folds(rs, seasons):
        held = set(idx)
        spec = fit_spec(sport, mk, [r for i, r in enumerate(rs) if i not in held], knot, lam, oMean)
        for i in idx:
            pred[i] = predict(sport, mk, rs[i], spec)
    return pred


def rec(es):
    b = clv.block(es) if es else {'clvN': 0}
    b['n'] = len(es)
    return b


def one_sided_p(t):
    return None if t is None else 0.5 * math.erfc(t / math.sqrt(2))


def bh(ps, q):
    """Benjamini-Hochberg: which of the p-values pass at false-discovery rate q"""
    m = len([p for p in ps if p is not None])
    order = sorted([(p, i) for i, p in enumerate(ps) if p is not None])
    cut = 0
    for k, (p, _) in enumerate(order, 1):
        if p <= q * k / m:
            cut = k
    keep = {i for _, i in order[:cut]}
    return [i in keep for i in range(len(ps))]


def r2(y, p, base=None):
    sse = sum((a - b) ** 2 for a, b in zip(y, p))
    sst = sum((a - (0.0 if base is None else c)) ** 2 for a, c in zip(y, base or [0.0] * len(y)))
    return round(1 - sse / sst, 4) if sst else None


def breakeven(sport, mk, spec, cl, o, neutral=0):
    """the smallest gap (points, on the home/over side) where E[clvRet] at -110 crosses 0 for a game in cells cl"""
    for i in range(1, 81):
        x = i / 4
        r = {'o': o, 'm': o + x, 'cells': cl, 'g': {'neutral': neutral}}
        side, e = e_ret(sport, mk, r, predict(sport, mk, r, spec))
        if side in ('home', 'over') and e is not None and e >= 0:
            return x
    return None


def curve(sport, mk, spec, cl, o):
    out = []
    for x in (2, 4, 6, 8, 10):
        r = {'o': o, 'm': o + x, 'cells': cl, 'g': {'neutral': 0}}
        out.append({'gap': x, 'move': round(predict(sport, mk, r, spec), 2)})
    return out


# ---------------------------------------------------------------- --fit

def fit():
    import numpy as np
    caps = {s: (v.get('cap') or [None, None]) for s, v in json.load(open(GP_FIT))['sports'].items()}
    res = {'asof': datetime.date.today().isoformat(), 'price': PRICE, 'fdrQ': FDR_Q, 'keepT': KEEP_T,
           'registered': '2026-10-21', 'sports': {}, 'candidates': []}
    allcells = []           # (sport, mk, dim, level, held entries) for the FDR pass
    for sport, S in SPEC.items():
        rows = load(sport)
        sres = {'name': NAMES[sport], 'tune': S['tune'], 'held': S['held'], 'markets': {}}
        for mk in S['markets']:
            cap = caps[sport][0 if mk == 'spread' else 1]
            rs = market_rows(sport, mk, rows, cap)
            if len(rs) < 200:
                continue
            tune = [r for r in rs if r['S'] in S['tune']]
            # total size: terciles of each season's own opens (NBA totals rose 25 points between the eras)
            tcuts = {}
            for ss in {r['S'] for r in rs}:
                tt = sorted(r['o'] for r in rs if r['S'] == ss)
                tcuts[ss] = (tt[len(tt) // 3], tt[2 * len(tt) // 3]) if mk == 'total' else None
            for r in rs:
                r['cells'] = cells(sport, mk, r['g'], tcuts[r['S']])
            tcuts = tcuts[max(tcuts)]
            oMean = float(np.mean([r['o'] for r in tune]))
            ytune = [r['c'] - r['o'] for r in tune]
            # 1. the spec on tuning only: knot and ridge by out-of-fold squared error of the line move
            grid = []
            for knot in KNOTS:
                for lam in LAMS:
                    p = oof(sport, mk, tune, S['tune'], knot, lam, oMean)
                    grid.append({'knot': knot, 'lam': lam, 'sse': sum((a - b) ** 2 for a, b in zip(ytune, p)), 'p': p})
            best = min(grid, key=lambda g: g['sse'])
            lin = next(g for g in grid if g['knot'] is None and g['lam'] is None)
            knot, lam = best['knot'], best['lam']
            # 2. the bet cut tau on tuning (out-of-fold predictions), and the plain gap rule's X the same way
            def model_bets(sub, preds, tau):
                out = []
                for r, mv in zip(sub, preds):
                    side, e = e_ret(sport, mk, r, mv)
                    if e is not None and e > tau:
                        out.append({**realized(sport, mk, r, side), 'S': r['S'], 'E': e, 'cells': r['cells']})
                return out

            def gap_bets(sub, x):
                out = []
                for r in sub:
                    g = r['m'] - r['o']
                    if abs(g) >= x:
                        side = ('home' if g > 0 else 'away') if mk == 'spread' else ('over' if g > 0 else 'under')
                        out.append({**realized(sport, mk, r, side), 'S': r['S'], 'cells': r['cells']})
                return out

            def pick(cands):
                ok = [(k, b) for k, b in cands if b['clvN'] >= MIN_N and (b['clvT'] or -9) >= MIN_T]
                return max(ok, key=lambda kb: kb[1]['clvRet']) if ok else (None, None)

            tau, tauRec = pick([(t, rec(model_bets(tune, best['p'], t))) for t in TAUS])
            X, xRec = pick([(x, rec(gap_bets(tune, x))) for x in XGRID])
            # 3. held out, walk-forward: each held season from a fit on the seasons before it
            hp, hl, hd, hr = [], [], [], []
            for hs in S['held']:
                past = [r for r in rs if r['S'] < hs]
                cur = [r for r in rs if r['S'] == hs]
                sp = fit_spec(sport, mk, past, knot, lam, oMean)
                sl = fit_spec(sport, mk, past, None, None, oMean)
                hp += [predict(sport, mk, r, sp) for r in cur]
                sd = fit_spec(sport, mk, past, None, None, oMean, gap=False)
                hl += [predict(sport, mk, r, sl) for r in cur]
                hd += [predict(sport, mk, r, sd) for r in cur]
                hr += cur
            yh = [r['c'] - r['o'] for r in hr]
            mb = model_bets(hr, hp, tau if tau is not None else 0.0)
            mb0 = model_bets(hr, hp, 0.0)
            gb = gap_bets(hr, X) if X is not None else []
            # the same number of bets, ranked by predicted worth vs ranked by the gap
            n_match = len(mb0)
            ranked_e = sorted(model_bets(hr, hp, -9), key=lambda e: -e['E'])[:n_match]
            ranked_g = sorted(hr, key=lambda r: -abs(r['m'] - r['o']))[:n_match]
            gbm = []
            for r in ranked_g:
                g = r['m'] - r['o']
                side = ('home' if g > 0 else 'away') if mk == 'spread' else ('over' if g > 0 else 'under')
                gbm.append({**realized(sport, mk, r, side), 'S': r['S']})
            # calibration of the predicted worth: realized clvRet on E across every held game (the paper book's Kelly
            # scale), and the model's bets season by season
            allb = model_bets(hr, hp, -9)
            cal = clv.slope([e['E'] for e in allb], [e['clvRet'] for e in allb])
            by_season = {str(hs): rec([e for e in mb if e['S'] == hs]) for hs in S['held']}
            # 4. the final fit on every season (live use), the curve and the break-even gaps by cell
            final = fit_spec(sport, mk, rs, knot, lam, oMean)
            ref = {d: lvs[0] for d, lvs in DIMS[sport].items()}
            ref.update({d: max(lvs, key=lambda lv: sum(1 for r in rs if r['cells'][d] == lv)) for d, lvs in DIMS[sport].items()})
            # the reference game: the commonest level of each dimension, the median open (spreads: the home side
            # favored by the median line), its size cell matching that open
            oRef = float(np.median([abs(r['o']) if mk == 'spread' else r['o'] for r in rs]))
            ref['size'] = size(sport, mk, oRef, tcuts or (0, 0))
            lin_all = clv.slope([r['m'] - r['o'] for r in rs], [r['c'] - r['o'] for r in rs])
            mres = {
                'games': len(rs), 'gamesHeld': len(hr), 'cap': cap, 'totalCuts': tcuts,
                'spec': {'knot': knot, 'lam': lam, 'oofSse': round(best['sse'], 1), 'oofSseLinear': round(lin['sse'], 1),
                         'grid': [{'knot': g['knot'], 'lam': g['lam'], 'sse': round(g['sse'], 1)} for g in grid]},
                'slope': lin_all,
                'held': {'r2': r2(yh, hp), 'r2Linear': r2(yh, hl), 'r2VsLinear': r2(yh, hp, hl), 'r2Drift': r2(yh, hd),
                         'meanAbsMove': round(float(np.mean(np.abs(yh))), 2)},
                'tau': tau, 'tauTune': tauRec, 'x': X, 'xTune': xRec, 'calib': cal,
                'meanE': round(sum(e['E'] for e in mb) / len(mb), 4) if mb else None, 'bySeason': by_season,
                'bets': {'model': rec(mb), 'model0': rec(mb0), 'gap': rec(gb), 'linear': rec(model_bets(hr, hl, 0.0)),
                         'drift': rec(model_bets(hr, hd, 0.0)),
                         'matched': {'n': n_match, 'model': rec(ranked_e), 'gap': rec(gbm)}},
                'final': final, 'ref': ref, 'oRef': round(oRef, 1),
                'curve': curve(sport, mk, final, ref, oRef),
                'curveLinear': curve(sport, mk, fit_spec(sport, mk, rs, None, None, oMean), ref, oRef),
                'breakeven': breakeven(sport, mk, final, ref, oRef),
                'breakevenLinear': breakeven(sport, mk, fit_spec(sport, mk, rs, None, None, oMean), ref, oRef),
                'cells': [],
            }
            # 5. the softness index: b by cell (all seasons, tuning and held), the cell's break-even gap from the
            # final fit, and the held-out bets the model picked in that cell
            for d, lvs in DIMS[sport].items():
                for lv in lvs:
                    sub = [r for r in rs if r['cells'][d] == lv]
                    if len(sub) < 30:
                        continue
                    sl = lambda q: clv.slope([r['m'] - r['o'] for r in q], [r['c'] - r['o'] for r in q])
                    cl = {**ref, d: lv}
                    hb = [e for e in mb if e['cells'][d] == lv]
                    row = {'dim': d, 'level': lv, 'n': len(sub), 'b': sl(sub),
                           'bTune': sl([r for r in sub if r['S'] in S['tune']]),
                           'bHeld': sl([r for r in sub if r['S'] in S['held']]),
                           'breakeven': breakeven(sport, mk, final, cl, oRef, 1 if lv == 'neutral' else 0),
                           'heldBets': rec(hb)}
                    mres['cells'].append(row)
                    allcells.append((sport, mk, row))
            sres['markets'][mk] = mres
            print(sport, mk, 'knot', knot, 'lam', lam, 'held r2', mres['held'], 'tau', tau, 'X', X)
            for k in ('model', 'model0', 'gap', 'linear', 'drift'):
                b = mres['bets'][k]
                print(f"   {k}: n {b['n']} clvRet {b.get('clvRet')} t {b.get('clvT')} roi {b.get('roi')}")
            print('   calib', cal, 'meanE', mres['meanE'], {k: (v.get('clvN'), v.get('clvRet'), v.get('clvT')) for k, v in by_season.items()})
            print('   matched', n_match, mres['bets']['matched']['model'].get('clvRet'), mres['bets']['matched']['gap'].get('clvRet'))
            print('   breakeven', mres['breakeven'], 'linear', mres['breakevenLinear'], 'curve', mres['curve'])
        res['sports'][sport] = sres
    # 6. false-discovery control across every pre-registered cell, on the held-out bets
    ps = [one_sided_p(c[2]['heldBets'].get('clvT')) if (c[2]['heldBets'].get('clvN') or 0) >= 30 else None for c in allcells]
    passed = bh(ps, FDR_Q)
    for (sport, mk, row), p, ok in zip(allcells, ps, passed):
        row['p'] = None if p is None else round(p, 4)
        row['fdr'] = bool(ok)
        hb = row['heldBets']
        if ok and (hb.get('clvRet') or 0) > 0:
            res['candidates'].append({'sport': sport, 'mk': mk, 'dim': row['dim'], 'level': row['level'],
                                      'cut': row['breakeven'], 'heldN': hb['clvN'], 'heldClvRet': hb['clvRet'],
                                      'heldT': hb['clvT'], 'p': row['p'], 'kind': 'cell'})
    # whole-market rules: the model's selection where its held-out bets beat the close (t 1.65+, 30+ bets)
    for sport, sres in res['sports'].items():
        for mk, m in sres['markets'].items():
            b = m['bets']['model']
            held_ok = bool((b.get('clvN') or 0) >= 30 and (b.get('clvRet') or 0) > 0 and (b.get('clvT') or 0) >= KEEP_T)
            # a cut picked on tuning and a held-out pass: a candidate. No cut held up on tuning (bets at cut 0 shown):
            # held out only, the same gate that keeps the plain gap rule off, so paper only and flagged
            m['on'] = held_ok and m['tau'] is not None
            m['status'] = 'candidate' if m['on'] else 'held out only' if held_ok else 'off'
            if held_ok:
                res['candidates'].append({'sport': sport, 'mk': mk, 'dim': None, 'level': None, 'cut': m['breakeven'],
                                          'tau': m['tau'] if m['tau'] is not None else 0.0, 'heldN': b['clvN'], 'heldClvRet': b['clvRet'],
                                          'heldT': b['clvT'], 'kind': 'market', 'status': m['status']})
    res['dense'] = dense_status()
    if os.path.exists(WEATHER):
        res['weather'] = weather()
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print('candidates', json.dumps(res['candidates'], indent=1))


def dense_status():
    """how many games the timed archives hold with three or more pre-start snapshots (the dense controls need a season)"""
    out = {}
    for d in ('odds', 'odds_dense'):
        p = os.path.join(HERE, 'data', d)
        if not os.path.isdir(p):
            continue
        for fn in sorted(os.listdir(p)):
            if not fn.endswith('.jsonl'):
                continue
            sp = fn.split('-')[0]
            by = {}
            for line in open(os.path.join(p, fn)):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                by.setdefault(r.get('id'), []).append(r)
            o = out.setdefault(sp, {'games': 0, 'snapshots': 0})
            o['games'] += sum(1 for v in by.values() if len(v) >= 3)
            o['snapshots'] += sum(len(v) for v in by.values())
    return out


# ---------------------------------------------------------------- weather side test (CFB totals, research only)

def weather():
    """does wind or cold at kickoff move CFB totals, and did the close already have it? Observed weather (an upper
    bound on a forecast). Outdoor games only. Report only: the game model is not changed."""
    import numpy as np
    W = json.load(open(WEATHER))
    G, V = W['games'], W['venues']
    rows = []
    for g in json.load(gzip.open(os.path.join(WF, 'cfb.json.gz'))):
        w = G.get(g['id'])
        if not w or g.get('To') is None or g.get('T') is None or g.get('tot') is None or g.get('tm') is None or UN.bad_open('cfb', 'total', g):
            continue
        v = V.get(w.get('venue')) or {}
        if v.get('indoor') or w.get('wind') is None or (w.get('km') or 0) > 50:
            continue                    # indoors, no station data, or the nearest station too far to stand in
        rows.append({**g, 'wind': w['wind'], 'temp': w.get('temp'), 'rain': w.get('rain') or 0.0})
    if len(rows) < 100:
        return {'n': len(rows), 'note': 'too few games with weather'}

    def ols(names, X, y):
        X = np.column_stack([np.ones(len(y))] + X)
        y = np.asarray(y, float)
        XtXi = np.linalg.inv(X.T @ X)
        b = XtXi @ X.T @ y
        e = y - X @ b
        n, k = X.shape
        V = XtXi @ (X.T * e ** 2) @ X @ XtXi * n / (n - k)
        return {nm: {'b': round(float(b[i + 1]), 3), 't': round(float(b[i + 1] / math.sqrt(V[i + 1, i + 1])), 2)} for i, nm in enumerate(names)}

    wind = [r['wind'] for r in rows]
    w15 = [max(r['wind'] - 10, 0.0) for r in rows]         # points per mph past 10 mph
    temp = [r['temp'] if r['temp'] is not None else 60.0 for r in rows]
    cold = [max(50 - t, 0.0) for t in temp]                 # points per degree under 50F
    rain = [1.0 if r['rain'] >= 0.1 else 0.0 for r in rows]
    X = [w15, cold, rain]
    nm = ['wind past 10 mph', 'cold under 50F', 'rain 0.1in+']
    out = {'n': len(rows), 'seasons': sorted({r['S'] for r in rows}), 'meanWind': round(float(np.mean(wind)), 1),
           'windy': sum(1 for x in wind if x >= 15), 'rainy': int(sum(rain)),
           # the market's move from the open to the close: did forecasts reach the line?
           'move': ols(nm, X, [r['T'] - r['To'] for r in rows]),
           # the final total against the close: did the close miss the weather?
           'missClose': ols(nm, X, [r['tot'] - r['T'] for r in rows]),
           # our model (no weather term) against the final total
           'missModel': ols(nm, X, [r['tot'] - r['tm'] for r in rows])}
    # the under at the open in windy games (15+ mph), judged by the close and by results
    bets = []
    for r in rows:
        if r['wind'] >= 15:
            e = clv.judge({}, 'cfb', 'total', 'under', r['To'], PRICE, r['T'])
            d = r['To'] - r['tot']
            e['profit'] = 0.0 if d == 0 else (clv.dec(PRICE) - 1 if d > 0 else -1.0)
            bets.append(e)
    out['windUnder'] = rec(bets)
    return out


# ---------------------------------------------------------------- live (stdlib)

_F = None
_CONF = {}


def game_cells(sport, mk, g, fit=None):
    """the cells of a live game. g in the walk-forward style: home, away, date (ISO), Lo or To (the open), and as the
    sport has them wk, fcs, neutral, po, b2b (1 when either team played the day before)"""
    if sport not in _CONF:
        try:
            _CONF[sport] = {t['team']: t['conf'] for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']} if sport == 'cfb' \
                else {p['t']: p['conf'] for p in json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']} if sport == 'cbb' else {}
        except (OSError, ValueError, KeyError):
            _CONF[sport] = {}
    m = (((fit or _load()).get('sports') or {}).get(sport) or {}).get('markets', {}).get(mk) or {}
    g = {**g, '_tier': tier(sport, g, _CONF[sport]), '_b2b': g.get('b2b')}
    return cells(sport, mk, g, m.get('totalCuts'))


def _load():
    global _F
    if _F is None:
        try:
            _F = json.load(open(OUT))
        except (OSError, ValueError):
            _F = {}
    return _F


def expected(sport, mk, g, fit=None):
    """g: {'o': the line taken (home margin or total), 'm': the model, 'neutral', 'cells': {dim: level}} (game_cells()
    builds the cells). -> {'move', 'close', 'side', 'E'}: the predicted move to the close, the predicted close, the side
    it moves toward and that side's worth at -110 if the close lands there; None when the market has no fit."""
    fit = fit or _load()
    m = ((fit.get('sports') or {}).get(sport) or {}).get('markets', {}).get(mk)
    if not m or g.get('o') is None or g.get('m') is None:
        return None
    r = {'o': g['o'], 'm': g['m'], 'cells': g['cells'], 'g': {'neutral': g.get('neutral', 0)}}
    mv = predict(sport, mk, r, m['final'])
    side, e = e_ret(sport, mk, r, mv)
    return {'move': round(mv, 2), 'close': round(g['o'] + mv, 1), 'side': side, 'E': None if e is None else round(e, 4)}


def test():
    assert hinge(5, 3) == 2 and hinge(-5, 3) == -2 and hinge(2, 3) == 0 and hinge(4, None) == 0
    assert bh([0.001, 0.2, 0.03, None], 0.1) == [True, False, True, False]
    assert size('cbb', 'spread', -13, None) == 'big' and size('nba', 'total', 230, (215, 225)) == 'big'
    spec = {'knot': 4, 'lam': None, 'oMean': 0, 'beta': [0, 0, 0, 0, 0, 0, 0.3, -0.2]}
    r = {'o': 3, 'm': 9, 'cells': {'phase': 'nov', 'tier': 'high', 'court': 'home', 'size': 'small'}, 'g': {'neutral': 0}}
    assert abs(predict('cbb', 'spread', r, spec) - (0.3 * 6 - 0.2 * 2)) < 1e-9
    side, e = e_ret('cbb', 'spread', r, 2.0)
    assert side == 'home' and e is not None
    print('close_model: ok')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--fit':
        fit()
    elif a and a[0] == '--weather':
        print(json.dumps(weather(), indent=1))
    elif a and a[0] == '--test':
        test()
    else:
        print(__doc__)
