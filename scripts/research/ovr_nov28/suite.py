# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The OVR test suite, run the same way in every sport (scripts/research/ovr_nov28/run.py).

Variants against the base (next season's rate ~ the predictive rate P, recalibrated on the training seasons):
  holistic   P + D (this season's descriptive rate): the weight on D is whatever least squares gives it held out
  holisticN  P + D x n / (n + K): the descriptive weight grows with this season's sample
  shrink     P + P x R, R = sample / (sample + K): the slope on P is allowed to grow with career sample (extra shrinkage)
  age        P + (age - 27) + (age - 27)^2
  pos        P + position offsets
  rookie     P + (FV, 1) x K / (K + career sample) on rows with a final pre-pro FV (his first seasons): the prior's weight
             fades as pro minutes come in; K picked held out, the smallest K inside one SE of the best (fast updating)
Bands: 80% band from residual variance a + b / (sample + c), fit on the training seasons; coverage held out.
Sub-ratings: next season's O (D) from this season's O (D) part against the total times the league share."""
import math, statistics as st
from engine import Engine, passes, coverage, paired_t, wls, pearson


def builders(R, age0):
    """feature builders: name -> (row -> list); P is always first"""
    medn = st.median([r['n'] for r in R]); K = st.median([r['n'] + r['car'] for r in R])
    P = sorted({r['pos'] for r in R if r.get('pos')})
    dv = lambda r: r['D'] if r.get('D') is not None else r['P']
    ag = lambda r: (r['age'] or age0) - age0
    return {'holistic': lambda r: [dv(r)],
            'holisticN': lambda r: [dv(r) * r['n'] / (r['n'] + medn)],
            'shrink': lambda r: [r['P'] * (r['n'] + r['car']) / (r['n'] + r['car'] + K)],
            'age': lambda r: [ag(r), ag(r) ** 2],
            'pos': lambda r: [1.0 if r.get('pos') == p else 0.0 for p in P[1:]]}, {'medn': medn, 'K': K, 'pos': P, 'age0': age0}


def feats(B, names):
    return lambda r: [r['P']] + [v for nm in names for v in B[nm](r)]


def run(rows, cap, repl, kgrid, nkey='n', min_yn=0, age0=27.0, rookie=True, sub=True, extra=None, skip=()):
    E = Engine(rows, cap, repl, min_yn=min_yn)
    R = E.rows
    out = {'n': len(R), 'seasons': [E.seasons[0], E.seasons[-1]], 'nSeasons': len(E.seasons)}
    B, consts = builders(R, age0); out['consts'] = consts
    base = E.score(lambda tr: feats(B, []), 'base')
    res = {'base': base}
    for nm in skip: B.pop(nm, None)
    for nm in B: res[nm] = E.score(lambda tr, nm=nm: feats(B, [nm]), nm)
    out['tests'] = {k: Engine.compare(v, base) for k, v in res.items() if k != 'base'}
    for k, c in out['tests'].items(): c['pass'] = passes(c)
    out['tests']['base'] = {'mse': base['MSE'], 'r': base['R'], 'team': base['TEAM']}
    # holistic weight on D (pooled fit, reported)
    X = [[1.0, r['P'], r['D'] if r.get('D') is not None else r['P']] for r in R]
    out['holisticBeta'] = [round(b, 3) for b in wls(X, [r['Y'] for r in R], [E.w(r) for r in R])]
    # combination of the passing ones (holistic and holisticN are one idea: the better of the two)
    ok = [k for k in B if out['tests'][k]['pass']]
    if 'holistic' in ok and 'holisticN' in ok:
        ok.remove('holistic' if out['tests']['holisticN']['mse'] <= out['tests']['holistic']['mse'] else 'holisticN')
    # every subset of the passing ideas; keep the one with the lowest held-out error that still passes against the base
    import itertools
    best = None
    for m in range(1, len(ok) + 1):
        for sub_ in itertools.combinations(ok, m):
            v = E.score(lambda tr, sub_=sub_: feats(B, list(sub_)), 'combo'); c = Engine.compare(v, base)
            if passes(c) and (best is None or v['MSE'] < best[0]['MSE'] - 1e-9): best = (v, list(sub_))
    ship = best[1] if best else []
    if ship:
        combo = E.score(lambda tr: feats(B, ship), 'combo'); c = Engine.compare(combo, base); c['pass'] = passes(c)
        out['combo'] = dict(c, feats=ship)
        res['combo'] = combo
        if not c['pass']: ship = []
    out['ship'] = ship
    f = feats(B, ship)
    out['beta'] = [round(b, 5) for b in wls([[1.0] + f(r) for r in R], [r['Y'] for r in R], [E.w(r) for r in R])]
    # rookie prior from the final pre-pro FV
    if rookie:
        rk = [r for r in R if r.get('fv2') is not None]
        out['rookie'] = rookie_tests(rk, cap, repl, kgrid)
    out['bands'] = bands(E, res.get('combo', base))
    if sub: out['sub'] = subratings(R, cap)
    return out, res


def rookie_tests(rk, cap, repl, kgrid):
    if len(rk) < 60: return {'n': len(rk), 'note': 'too few rows'}
    E = Engine(rk, cap, repl)
    b = E.score(lambda tr: (lambda r: [r['P']]), 'base')
    grid = []; icpt = {}
    for k in kgrid:
        def f(tr, k=k):
            return lambda r: [r['P'], r['fv2'] * k / (k + r['car'] + r['n']), k / (k + r['car'] + r['n'])]
        v = E.score(f, f'k{k}'); c = Engine.compare(v, b); c['k'] = k
        # the same weight with no FV in it (a rookie offset alone): FV has to beat this too
        i = E.score(lambda tr, k=k: (lambda r: [r['P'], k / (k + r['car'] + r['n'])]), f'i{k}')
        ci = Engine.compare(v, i); c['vsOffset'] = {x: ci[x] for x in ('t', 'tR', 'tTeam', 'wins')}; c['passOffset'] = passes(ci)
        grid.append((v, c))
    best = min(grid, key=lambda g: g[0]['MSE'])
    se = st.pstdev([x - y for x, y in zip(best[0]['mse'], b['mse'])]) / math.sqrt(len(b['mse']))
    for g in grid: g[1]['pass'] = passes(g[1]) and g[1]['passOffset']
    ok = [g for g in grid if g[1]['pass']]
    pick = min(ok, key=lambda g: g[1]['k']) if ok else min((g for g in grid if g[0]['MSE'] <= best[0]['MSE'] + se), key=lambda g: g[1]['k'])
    # FV -> rate this season (the rookie season), pooled and by held-out season
    first = [r for r in rk if r.get('fv') is not None and r.get('D') is not None]
    cal = wls([[1.0, r['fv']] for r in first], [r['D'] for r in first], [min(r['n'], cap) for r in first]) if first else None
    calY = wls([[1.0, r['fv']] for r in first], [r['Y'] for r in first], [min(r['Yn'], cap) for r in first]) if first else None
    return {'n': len(rk), 'nFirst': len(first), 'base': b['MSE'], 'grid': [g[1] for g in grid], 'best': best[1], 'pick': pick[1],
            'pass': passes(pick[1]), 'fvToRate': [round(x, 4) for x in cal] if cal else None,
            'fvToNext': [round(x, 4) for x in calY] if calY else None,
            'rFvRate': round(pearson([r['fv'] for r in first], [r['D'] for r in first]), 3) if first else None}


def bands(E, base, ymin=None):
    """talent band: held-out residual^2 = tau^2(sample) + sigma^2 / Yn, tau^2 = t0 + t1 / (sample + c0) (sample = this
    season + career). The 80% band on next season's rate uses tau^2 + sigma^2 / Yn (checked held out on rows with Yn >= ymin);
    the OVR band shows tau alone (true talent)"""
    R = E.rows; ymin = ymin or E.cap / 10; c0 = st.median([r['n'] + r['car'] for r in R]) / 4
    def fit(rows):
        X = [[1.0, 1.0 / (r['n'] + r['car'] + c0), 1.0 / r['Yn']] for r in rows]
        a = wls(X, [(r['Y'] - base['preds'][(r['s'], r['id'])]) ** 2 for r in rows], [1.0] * len(rows))
        return [max(x, 0.0) for x in a]
    cov = []
    for s in E.seasons:
        tr = [r for r in R if r['s'] != s and r['Yn'] >= ymin]; te = [r for r in R if r['s'] == s and r['Yn'] >= ymin]
        a = fit(tr)
        def band(r, p, a=a):
            v = max(a[0] + a[1] / (r['n'] + r['car'] + c0) + a[2] / r['Yn'], 1e-6)
            return p - 1.2816 * math.sqrt(v), p + 1.2816 * math.sqrt(v)
        cov.append(coverage(te, base['preds'], band))
    a = fit([r for r in R if r['Yn'] >= ymin])
    return {'cover80': round(st.mean(cov), 3), 'min': min(cov), 'max': max(cov), 't0': round(a[0], 5), 't1': round(a[1], 4),
            'c0': round(c0, 1), 'sig2': round(a[2], 3), 'ymin': ymin}


def subratings(R, cap):
    """own part against the total x its pooled share, next season, leave one season out"""
    rr = [r for r in R if None not in (r.get('Po'), r.get('Pd'), r.get('Yo'), r.get('Yd'))]
    if len(rr) < 100: return None
    seasons = sorted({r['s'] for r in rr}); out = {}
    for side, own, tgt in (('o', 'Po', 'Yo'), ('d', 'Pd', 'Yd')):
        e_own, e_tot = [], []
        for s in seasons:
            tr = [r for r in rr if r['s'] != s]; te = [r for r in rr if r['s'] == s]
            w = lambda r: min(r['Yn'], cap)
            b1 = wls([[1.0, r[own]] for r in tr], [r[tgt] for r in tr], [w(r) for r in tr])
            b2 = wls([[1.0, r['Po'] + r['Pd']] for r in tr], [r[tgt] for r in tr], [w(r) for r in tr])
            W = sum(w(r) for r in te)
            e_own.append(sum(w(r) * (r[tgt] - b1[0] - b1[1] * r[own]) ** 2 for r in te) / W)
            e_tot.append(sum(w(r) * (r[tgt] - b2[0] - b2[1] * (r['Po'] + r['Pd'])) ** 2 for r in te) / W)
        out[side] = {'own': round(st.mean(e_own), 4), 'total': round(st.mean(e_tot), 4), 't': paired_t(e_own, e_tot),
                     'wins': sum(1 for a, b in zip(e_own, e_tot) if a < b), 'of': len(seasons)}
    out['pass'] = all(out[s]['t'] <= -2 for s in ('o', 'd'))
    return out
