#!/usr/bin/env python3
"""Historical comps for the CFB board (audit #41): each player's nearest neighbours among the 2014-22 FBS seasons the
FV backtest rebuilds, with what those players did in the NFL.

    node scripts/cfb_fv_refit.mjs --wide --comps=scripts/.cache/fvdist/cfb_comps_rows.json   # the pool (needs the wide caches)
    node scripts/cfb_fv_refit.mjs --dist=scripts/.cache/fvdist/cfb_rows.json                 # fv_dist's rows (the shape test)
    python3 scripts/cfb_comps.py     -> scripts/data/cfb_comps_pool.json (read by scripts/cfb_comps.mjs), data/cfb_comps.json

Profile, within position (QB, RB, WR, TE, EDGE, DT, LB: PFN's lines before 2024): production z (3-season blend, the FV
input), 247 pedigree z (walk-on -1.5), years on campus, listed height and weight (z within position) and combine
testing (only once the player has tested) and team strength (start-of-season Elo z; live: last season's SP+ z). Distance is a weighted Euclidean over the inputs both sides have; the
weights are picked by coordinate descent on the held-out RPS of the comps' outcome mix (one draft class out). A comp
is a player, not a season: each player's nearest season counts once. Outcome: NFL AV a season after the draft through
2025 on the FV scale (fv_dist_fit's ladder), plus the pick, All-Pro and Pro Bowl counts.

Shape test (fv_dist, 2019-22 rows, draft class held out, comp weights refit inside the training classes): the comps'
outcome mix as (a) a mixture weight on fv_dist's tier odds and (b) a spread term (the comps' outcome SD) in the
ordered probit. Either ships only if it beats the shipped model's held-out RPS (.0400) by the selection margin.
"""
import json, os, sys
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fv_dist_fit as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'fvdist')
POOL_OUT = os.path.join(ROOT, 'scripts', 'data', 'cfb_comps_pool.json')
OUT = os.path.join(ROOT, 'data', 'cfb_comps.json')
FEATS = ['z', 'hs', 'years', 'ht', 'wt', 'lvl', 'ath']
NB = len(F.EDGES) + 1
K = 25            # neighbours in the outcome mix
PRIOR = 5.0       # pseudo-count of the position's base rates in the mix
SHOW = 3          # comps shown on the board


def load_pool():
    f = os.path.join(CACHE, 'cfb_comps_rows.json')
    if not os.path.exists(f): sys.exit(f'missing {f}: run node scripts/cfb_fv_refit.mjs --wide --comps={f}')
    rows = json.load(open(f))
    size = {}
    for g in sorted({r['g'] for r in rows}):
        P = [r for r in rows if r['g'] == g]
        size[g] = {m: [float(np.mean([r[m] for r in P if r[m]])), float(np.std([r[m] for r in P if r[m]]))] for m in ('ht', 'wt')}
    for r in rows:
        r['y'] = F.fv_of_av(r['av']); r['k'] = F.bin_of(r['y'])
        r['key'] = r['g'] + '|' + r['name'] + '|' + str(r['last'])
        r['x'] = feat(r, size[r['g']])
    return rows, size


def feat(r, sz):
    """the profile vector (nan = unknown)."""
    v = lambda x: np.nan if x is None else float(x)
    zs = lambda m: (r[m] - sz[m][0]) / sz[m][1] if r.get(m) else np.nan
    return np.array([v(r['z']), v(r['hs']), v(r['years']), zs('ht'), zs('wt'), v(r.get('lvl')), v(r.get('ath'))])


def dist(xt, X, w):
    """weighted RMS distance over the inputs both sides have (rows with nothing shared: inf)."""
    d = (X - xt[None, :]) ** 2
    m = ~np.isnan(d)
    ww = np.where(m, w[None, :], 0.0)
    den = ww.sum(1)
    return np.where(den > 0, np.sqrt(np.where(m, d, 0).dot(w) / np.maximum(den, 1e-9) * w.sum()), np.inf)


def comp_ix(xt, X, keys, w, k):
    """the k nearest players (each player's nearest season), as indices into X."""
    d = dist(xt, X, w)
    order = np.argsort(d, kind='stable')
    seen, out = set(), []
    for i in order:
        if not np.isfinite(d[i]): break
        if keys[i] in seen: continue
        seen.add(keys[i]); out.append(i)
        if len(out) == k: break
    return out, d


def mix_of(ix, d, kb, base):
    """the comps' outcome mix: kernel-weighted bin shares (nearer comps count more) shrunk to the position's base rate."""
    if not ix: return base.copy()
    dd = d[ix]; h = max(np.median(dd), 1e-6)
    wt = np.exp(-(dd / h) ** 2 / 2)
    M = np.bincount(kb[ix], weights=wt, minlength=NB)
    return (M + PRIOR * base) / (wt.sum() + PRIOR)


def rps(P, k):
    O = np.zeros_like(P); O[np.arange(len(k)), k] = 1
    return float(((np.cumsum(P, 1) - np.cumsum(O, 1)) ** 2).sum(1).mean() / (P.shape[1] - 1))


class Pool:
    """the comp pool by position, for one set of training classes."""
    def __init__(self, rows, keep=lambda r: True):
        self.by = {}
        for g in sorted({r['g'] for r in rows}):
            R = [r for r in rows if r['g'] == g and keep(r)]
            kb = np.array([r['k'] for r in R])
            self.by[g] = (R, np.array([r['x'] for r in R]), np.array([r['key'] for r in R]), kb, np.bincount(kb, minlength=NB) / max(1, len(R)))

    def mix(self, r, w, k=K, xt=None, excl=None):
        R, X, keys, kb, base = self.by[r['g']]
        xt = r['x'] if xt is None else xt
        if excl is not None:
            ok = np.array([q['last'] != excl for q in R])
            X, keys, kb2 = X[ok], keys[ok], kb[ok]
        else: kb2 = kb
        ix, d = comp_ix(xt, X, keys, w, k)
        return mix_of(ix, d, kb2, base), ix, d


def no_ath(r):
    x = r['x'].copy(); x[-1] = np.nan; return x


def objective(rows, w, targets, classes):
    """held-out RPS of the comp mix alone: each target's comps from the other draft classes."""
    P, ks = [], []
    for c in classes:
        pool = Pool(rows, lambda r: r['last'] != c)
        for r in targets:
            if r['last'] != c: continue
            M, _, _ = pool.mix(r, w, xt=no_ath(r) if r.get('_noath') else None)
            P.append(M); ks.append(r['k'])
    return rps(np.array(P), np.array(ks))


def tune(rows, classes, sample=1500, seed=11):
    """coordinate descent on the feature weights (the testing weight is tuned on final seasons that tested)."""
    rng = np.random.default_rng(seed)
    T = [r for r in rows if r['last'] in classes]
    T = [T[i] for i in rng.choice(len(T), min(sample, len(T)), replace=False)]
    for r in T: r['_noath'] = True
    w = np.ones(len(FEATS)); w[-1] = 0.0
    best = objective(rows, w, T, classes)
    for step in (1.0, 0.5, 0.25):
        moved = True
        while moved:
            moved = False
            for j in range(len(FEATS) - 1):
                for dlt in (step, -step):
                    t = w.copy(); t[j] = max(0.0, t[j] + dlt)
                    if t[:-1].sum() == 0: continue
                    s = objective(rows, t, T, classes)
                    if s < best - 1e-6: w, best, moved = t, s, True
    for r in T: r.pop('_noath', None)
    # testing: on final seasons with a combine line, profile as it stood at the draft
    TA = [r for r in rows if r['last'] in classes and r['final'] and r.get('ath') is not None]
    TA = [TA[i] for i in rng.choice(len(TA), min(800, len(TA)), replace=False)]
    sa = {a: objective(rows, np.r_[w[:-1], a], TA, classes) for a in (0.0, 0.5, 1.0, 2.0)}
    w[-1] = min(sa, key=sa.get)
    return w, best, {str(a): round(v, 5) for a, v in sa.items()}


# ---------------------------------------------------------------- shape test against fv_dist
def shape_test(rows, w_all):
    D = F.cfb_rows()
    byk = {(r['g'], r['name'], r['s']): r for r in rows}
    D = [d for d in D if (d['g'], d['name'], d['s']) in byk]
    folds = np.array([d['last'] for d in D]); ys = np.array([d['y'] for d in D]); kk = np.array([F.bin_of(y) for y in ys]); fl = F.floor_share(ys)
    fit = json.load(open(F.OUT))['cfb']
    _, extra = F.cfb_terms()
    kept = [t for t in extra if t[0] in fit['kept']]
    print('shape test rows', len(D), 'kept', [t[0] for t in kept])
    # comps for every dist row, weights refit without its draft class
    Mx = np.zeros((len(D), NB)); csd = np.zeros(len(D)); wf = {}
    for f in sorted(set(folds)):
        tr_classes = sorted({r['last'] for r in rows if r['last'] != f})
        w, _, _ = tune(rows, tr_classes, sample=1000)
        wf[str(f)] = [round(x, 2) for x in w]
        pool = Pool(rows, lambda r: r['last'] != f)
        for i in np.where(folds == f)[0]:
            r = byk[(D[i]['g'], D[i]['name'], D[i]['s'])]
            M, ix, _ = pool.mix(r, w, xt=no_ath(r))
            Mx[i] = M
            R = pool.by[r['g']][0]; yy = np.array([R[j]['y'] for j in ix])
            csd[i] = float(yy.std()) if len(yy) > 1 else 0.0
        print('fold', f, 'weights', wf[str(f)])
    zsd = (csd - csd.mean()) / csd.std()
    for d, z in zip(D, zsd): d['compsd'] = float(z)
    base = F.held_out(D, folds, [('model', kept)])['model']
    with_sd = F.held_out(D, folds, [('m', kept + [('compsd', lambda r: r['compsd'])])])['m']
    # mixture: weight picked on the other classes' held-out odds
    Pm = np.zeros_like(base); wmix = {}
    for f in sorted(set(folds)):
        tr = folds != f
        grid = np.arange(0, 0.61, 0.05)
        s = [rps((1 - a) * base[tr] + a * Mx[tr], kk[tr]) for a in grid]
        a = float(grid[int(np.argmin(s))]); wmix[str(f)] = round(a, 2)
        Pm[~tr] = (1 - a) * base[~tr] + a * Mx[~tr]
    res = {}
    for name, P in [('shipped', base), ('+ comp spread', with_sd), ('+ comp mix', Pm), ('comps alone', Mx)]:
        s = F.scores(P, ys, fl, fast=True)
        pf = {str(f): round(rps(P[folds == f], kk[folds == f]), 5) for f in sorted(set(folds))}
        res[name] = {**s, 'perFold': pf}
        print(f'{name:16s}', s, pf)
    for name in ('+ comp spread', '+ comp mix'):
        dl = np.array([((np.cumsum(res_p, 1) - np.cumsum(np.eye(NB)[kk], 1)) ** 2).sum(1) / (NB - 1) for res_p in [base, with_sd if 'spread' in name else Pm]])
        diff = dl[1] - dl[0]
        res[name]['t'] = round(float(diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))), 2)
        res[name]['foldsWon'] = sum(res[name]['perFold'][f] < res['shipped']['perFold'][f] for f in res['shipped']['perFold'])
    return {'rows': len(D), 'heldOut': res, 'mixWeight': wmix, 'weightsByFold': wf}


def main():
    rows, size = load_pool()
    classes = sorted({r['last'] for r in rows})
    print('pool rows', len(rows), 'players', len({r['key'] for r in rows}), 'classes', classes)
    w, obj, sa = tune(rows, classes)
    print('weights', dict(zip(FEATS, w.round(2))), 'held-out RPS of the comp mix', round(obj, 5), 'testing', sa)
    # yardstick: the position's base rates alone, held out
    base = []
    for c in classes:
        pool = Pool(rows, lambda r: r['last'] != c)
        base += [(pool.by[r['g']][4], r['k']) for r in rows if r['last'] == c]
    base_rps = rps(np.array([b for b, _ in base]), np.array([k for _, k in base]))
    print('base rates alone', round(base_rps, 5))
    test = shape_test(rows, w) if '--noshape' not in sys.argv else None
    # the pool the board reads: each player-season's profile and the player's outcome
    cols = ['name', 'team', 's', 'g', 'years', 'ht', 'wt', 'z', 'hs', 'lvl', 'ath', 'pick', 'av', 'ap', 'pb', 'y']
    rnd = lambda v, n=2: None if v is None else round(float(v), n)
    pool = [[r['name'], r['team'], r['s'], r['g'], r['years'], r['ht'], r['wt'], rnd(r['z']), rnd(r['hs']), rnd(r.get('lvl')), rnd(r.get('ath')),
             r['pick'], rnd(r['av']), r['ap'] or 0, r['pb'] or 0, rnd(r['y'], 1)] for r in rows]
    os.makedirs(os.path.dirname(POOL_OUT), exist_ok=True)
    json.dump({'cols': cols, 'weights': dict(zip(FEATS, [round(float(x), 2) for x in w])), 'size': size, 'k': SHOW, 'rows': pool},
              open(POOL_OUT, 'w'), separators=(',', ':'))
    out = {'asof': __import__('datetime').date.today().isoformat(), 'method': 'scripts/cfb_comps.py', 'pool': {'rows': len(rows), 'classes': classes},
           'weights': dict(zip(FEATS, [round(float(x), 2) for x in w])), 'compMixRps': round(obj, 5), 'baseRatesRps': round(base_rps, 5),
           'testingWeight': sa, 'shape': test}
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', POOL_OUT, OUT)


if __name__ == '__main__':
    main()
