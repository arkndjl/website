# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer Potential Breakout improvement sweep: new signals, model form and calibration on the first-time-at-the-bar
rows of scripts/soccer_breakout_research.py, leave-one-season-out, Holm across every test (the list and the pass bar
were written down before the run: project files next-up/prereg-soccer.md).

    python3 scripts/soccer_breakout_sweep_research.py     # -> data/soccer_breakout_sweep.json (+ the shipped parts
                                                          #    into data/soccer_breakout_fit.json 'sweep')

Needs the Understat match cache (scripts/.cache/soccer, for the half-season split) and Wikidata (head-coach stints,
cached). If the within-season trend ships it writes scripts/data/soccer_breakout_halves.json.gz (first-half minutes,
npxG + xA and starts per player-season) for the live build."""
import gzip
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import soccer_breakout as B  # noqa: E402
import soccer_breakout_research as R  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'soccer_breakout_sweep.json')
WDC = os.path.join(ROOT, 'scripts', '.cache', 'soccer', 'wd_coaches.json')
SPARQL = ('SELECT ?club ?tm ?coach ?start ?prec ?end WHERE { ?club wdt:P7223 ?tm . ?club p:P286 ?st . '
          '?st ps:P286 ?coach . ?st pqv:P580 ?sv . ?sv wikibase:timeValue ?start . ?sv wikibase:timePrecision ?prec . '
          'OPTIONAL {?st pq:P582 ?end} }')


# ---------- inputs ----------
def halves(seasons):
    """{S: {p: [first-half minutes, first-half npxG + xA, first-half starts]}}, {S: {team: first-half matches}}"""
    import soccer_players as SP
    H, TM = {}, {}
    for S in seasons:
        h, tm = defaultdict(lambda: [0, 0.0, 0]), defaultdict(int)
        for r in SP.build_rows(S, S, before=f'{S}-01-01'):
            v = h[r['p']]
            v[0] += r['min']; v[1] += r['x'] - r['pen'] + r['xA']; v[2] += r['start']
            tm[r['team']] = max(tm[r['team']], r['mp'])
        H[S] = {p: [v[0], round(v[1], 3), v[2]] for p, v in h.items()}
        TM[S] = dict(tm)
    return H, TM


def coach_changes():
    """team title -> sorted days a new head coach started (Wikidata, day precision)"""
    if not os.path.exists(WDC):
        u = 'https://query.wikidata.org/sparql?' + urllib.parse.urlencode({'query': SPARQL, 'format': 'json'})
        r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'research-script/1.0'}), timeout=300)
        json.dump(json.load(r)['results']['bindings'], open(WDC, 'w'))
    st = defaultdict(list)
    for b in json.load(open(WDC)):
        if b['prec']['value'] == '11':
            st[b['tm']['value']].append((b['start']['value'][:10], b['coach']['value'].rsplit('/', 1)[-1]))
    e2t = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'soccer_squad_mv.json.gz')))['espn2tm']
    out = {}
    for team, e in json.load(open(B.LOGOS)).get('espn', {}).items():
        Ls = sorted(st.get(str(e2t.get(str(e))), []))
        if Ls:
            out[team] = [Ls[i][0] for i in range(1, len(Ls)) if Ls[i][1] != Ls[i - 1][1]]
    return out


def coach_feats(CH, team_now, team_base, s):
    """None when neither club has stints on Wikidata"""
    if team_now not in CH and team_base not in CH:
        return None
    return (float(any(f'{s}-06-01' <= d <= f'{s}-09-15' for d in CH.get(team_now, []))),
            float(any(f'{s - 1}-09-16' <= d <= f'{s}-05-31' for d in CH.get(team_base, []))))


def half_feats(H, TM, Tfull, a):
    h = H.get(a['S'], {}).get(a['p'])
    if not h:
        return None
    full = max((r['mp'] for r in Tfull[a['team']]['ps']), default=0)
    return (h[0], h[1], a['st'] - h[2], full - TM.get(a['S'], {}).get(a['team'], 0))


# ---------- models ----------
def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def run(S, y, pred):
    """pred(train mask, test mask) -> probabilities; returns ({season: (loss sum, n)}, held-out p)"""
    ph = np.zeros(len(y))

    def fp(trn, te):
        ph[te] = pred(trn, te)
        return ph[te]
    return L.loso(S, fp, lambda p, te: (float(ll(p, y[te]).sum()), float(te.sum()))), ph


def logit_pred(X, y):
    def f(trn, te):
        b0, b = L.logit(X[trn], y[trn])
        return L.sig(b0 + X[te] @ b)
    return f


def hinges(X, cols, trn):
    out = [X]
    for c in cols:
        for q in np.percentile(X[trn, c], (25, 50, 75)):
            out.append(np.maximum(0.0, X[:, c] - q)[:, None])
    return np.column_stack(out)


def spline_pred(X, y, cols):
    def f(trn, te):
        Z = hinges(X, cols, trn)
        b0, b = L.logit(Z[trn], y[trn])
        return L.sig(b0 + Z[te] @ b)
    return f


NB, DEPTH, LR, SUB, LEAF, TREES, PAT = 32, 2, 0.05, 0.7, 40, 400, 30


def gbt_fit(X, y, n_trees, rng, Xv=None, yv=None):
    """depth-2 boosted trees on logistic loss (histogram splits). Returns (f0, trees, best tree count on Xv)"""
    edges = [np.unique(np.percentile(X[:, j], np.linspace(0, 100, NB + 1)[1:-1])) for j in range(X.shape[1])]
    Bn = np.column_stack([np.searchsorted(e, X[:, j]) for j, e in enumerate(edges)])
    p0 = np.clip(y.mean(), 1e-4, 1 - 1e-4)
    f0 = math.log(p0 / (1 - p0))
    F = np.full(len(y), f0)
    Fv = np.full(len(yv), f0) if Xv is not None else None
    trees, best, bi = [], 1e18, 0

    def split(idx, g, h):
        G, Hs = g[idx].sum(), h[idx].sum()
        top = (0.0, None)
        for j in range(X.shape[1]):
            nb = len(edges[j]) + 1
            gs = np.bincount(Bn[idx, j], weights=g[idx], minlength=nb).cumsum()[:-1]
            hs = np.bincount(Bn[idx, j], weights=h[idx], minlength=nb).cumsum()[:-1]
            ns = np.bincount(Bn[idx, j], minlength=nb).cumsum()[:-1]
            ok = (ns >= LEAF) & (len(idx) - ns >= LEAF)
            if not ok.any():
                continue
            gain = gs ** 2 / (hs + 1.0) + (G - gs) ** 2 / (Hs - hs + 1.0) - G ** 2 / (Hs + 1.0)
            gain[~ok] = -1
            k = int(gain.argmax())
            if gain[k] > top[0]:
                top = (float(gain[k]), (j, k))
        return top[1]

    def grow(idx, g, h, d):
        sp = split(idx, g, h) if d < DEPTH and len(idx) >= 2 * LEAF else None
        if sp is None:
            return [round(float(LR * g[idx].sum() / (h[idx].sum() + 1.0)), 6)]
        j, k = sp
        left = Bn[idx, j] <= k
        return [j, round(float(edges[j][k]), 6), grow(idx[left], g, h, d + 1), grow(idx[~left], g, h, d + 1)]
    for t in range(n_trees):
        p = L.sig(F)
        g, h = y - p, p * (1 - p)
        idx = np.flatnonzero(rng.random(len(y)) < SUB)
        tr = grow(idx, g, h, 0)
        trees.append(tr)
        F += tree_eval(tr, X)
        if Xv is not None:
            Fv += tree_eval(tr, Xv)
            e = float(ll(L.sig(Fv), yv).mean())
            if e < best - 1e-6:
                best, bi = e, t + 1
            elif t + 1 - bi >= PAT:
                break
    return f0, trees, bi


def tree_eval(tr, X):
    if len(tr) == 1:
        return np.full(len(X), tr[0])
    j, thr, lo, hi = tr
    m = X[:, j] <= thr          # bin k holds values <= edges[k] (searchsorted left)
    out = np.empty(len(X))
    out[m] = tree_eval(lo, X[m])
    out[~m] = tree_eval(hi, X[~m])
    return out


def gbt_pred(X, y, S):
    def f(trn, te):
        rng = np.random.default_rng(7)
        u = sorted(set(S[trn].tolist()))
        hold = trn & np.isin(S, u[1::3])
        _, _, n = gbt_fit(X[trn & ~hold], y[trn & ~hold], TREES, rng, X[hold], y[hold])
        f0, trees, _ = gbt_fit(X[trn], y[trn], max(10, n), np.random.default_rng(7))
        return L.sig(f0 + sum(tree_eval(t, X[te]) for t in trees))
    return f


def pav(x, y):
    """isotonic fit of y on x -> (knot x, knot value)"""
    o = np.argsort(x)
    xs, ys = x[o], y[o]
    v, w, lo = [], [], []
    for i in range(len(ys)):
        v.append(float(ys[i])); w.append(1.0); lo.append(i)
        while len(v) > 1 and v[-2] >= v[-1]:
            a, b = v.pop(), w.pop()
            lo.pop()
            v[-1] = (v[-1] * w[-1] + a * b) / (w[-1] + b)
            w[-1] += b
    kx = [float(xs[i:i + int(n)].mean()) for i, n in zip(lo, w)]
    return np.array(kx), np.array(v)


def calib_pred(X, y, S, kind):
    def f(trn, te):
        inner = np.zeros(len(y))
        for s in sorted(set(S[trn].tolist())):
            ite = trn & (S == s)
            itr = trn & ~ite
            b0, b = L.logit(X[itr], y[itr])
            inner[ite] = L.sig(b0 + X[ite] @ b)
        b0, b = L.logit(X[trn], y[trn])
        p = L.sig(b0 + X[te] @ b)
        lg = lambda q: np.log(np.clip(q, 1e-6, 1 - 1e-6) / (1 - np.clip(q, 1e-6, 1 - 1e-6)))  # noqa: E731
        if kind == 'platt':
            c0, c = L.logit(lg(inner[trn])[:, None], y[trn], lam=1e-6)
            return L.sig(c0 + c[0] * lg(p))
        kx, kv = pav(inner[trn], y[trn])
        return np.clip(np.interp(p, kx, kv), 0.002, 0.9)
    return f


def bins(ph, y):
    out = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (ph >= lo) & (ph < hi)
        if m.sum():
            out.append([lo, hi, int(m.sum()), round(float(ph[m].mean()), 3), round(float(y[m].mean()), 3)])
    return out


def main():
    P, T, squad, last = R.data()
    fit = json.load(open(B.FIT))
    keep = fit['breakout']['keep']
    H, TM = halves([s for s in B.seasons() if s <= last])
    CH = coach_changes()
    C = B.careers(P)
    rows, ncoach, nhalf = [], 0, 0
    for (p, s), a in P.items():
        b = P.get((p, s + 1))
        if s + 1 > last or not b or a['pos'] == 'GK' or a['min'] < B.MIN_BASE or a['inv'] < 5:
            continue
        ref = max(v for q, v in C[p] if q <= s)
        if ref >= B.LEVEL:
            continue
        s0, f = B.bo_row(a, B.history(P, p, s), T[s], b['team'], squad[s + 1][b['team']], ref)
        mates = [P[(q, s)] for q in squad[s + 1][b['team']] if q != p and (q, s) in P]
        co, hf = coach_feats(CH, b['team'], a['team'], s), half_feats(H, TM, T[s], a)
        ncoach += co is not None; nhalf += hf is not None
        x = B.bo_extra(a, s0, mates, co, hf, b['lg'])
        rows.append((s, sum([f[k] for k in ['base'] + keep], []), x,
                     1.0 if (b['min'] >= B.MIN_NEXT and B.shr(b['g90'], b['min']) >= B.LEVEL) else 0.0))
    S = np.array([r[0] + 1 for r in rows], float)
    y = np.array([r[3] for r in rows])
    X0 = np.array([r[1] for r in rows])
    EX = {k: np.array([r[2][k] for r in rows]) for k in B.BO_EXTRA}
    print('rows', len(y), 'rate', round(float(y.mean()), 4), 'coach coverage', ncoach, 'half coverage', nhalf, flush=True)
    r0, p0 = run(S, y, logit_pred(X0, y))
    tests = {}
    for k in B.BO_EXTRA:
        tests['signal: ' + k] = L.compare(r0, run(S, y, logit_pred(np.column_stack([X0, EX[k]]), y))[0])
        print(k, tests['signal: ' + k], flush=True)
    soft = [k for k in B.BO_EXTRA if tests['signal: ' + k]['t'] >= 2 and tests['signal: ' + k]['won'] * 2 > tests['signal: ' + k]['seasons']]
    X1 = np.column_stack([X0] + [EX[k] for k in soft])
    r1, p1 = run(S, y, logit_pred(X1, y))
    print('logistic + signals at t >= 2', soft, L.compare(r0, r1), flush=True)
    # model form, on the same columns as that logistic
    off, ix = 3, {}
    probe = B.bo_feats(next(iter(P.values())), 0.0, 0.0, None, 0.0, 0.0, 0.0)
    for k in keep:
        ix[k] = off
        off += len(probe[k])
    sp_cols = [0] + ([ix['age curve']] if 'age curve' in ix else []) + \
        ([ix['market value'] + 1] if 'market value' in ix else []) + ([ix['club strength']] if 'club strength' in ix else [])
    rg, pg = run(S, y, gbt_pred(X1, y, S))
    tests['model: gradient-boosted trees vs logistic'] = L.compare(r1, rg)
    print('gbt', tests['model: gradient-boosted trees vs logistic'], flush=True)
    rs, ps = run(S, y, spline_pred(X1, y, sp_cols))
    tests['model: logistic + splines vs logistic'] = L.compare(r1, rs)
    print('splines', tests['model: logistic + splines vs logistic'], flush=True)
    cal = {}
    for kind in ('platt', 'isotonic'):
        rc, pc = run(S, y, calib_pred(X1, y, S, kind))
        tests[f'calibration: {kind} vs none'] = L.compare(r1, rc)
        cal[kind] = bins(pc, y)
        print(kind, tests[f'calibration: {kind} vs none'], cal[kind][-1], flush=True)
    L.holm(tests)
    ship = [k for k in B.BO_EXTRA if tests['signal: ' + k]['pass']]
    Xf = np.column_stack([X0] + [EX[k] for k in ship])
    rf, pf = run(S, y, logit_pred(Xf, y))
    final = L.compare(r0, rf)
    b0, b = L.logit(Xf, y)
    print('shipped', ship, final, bins(pf, y), flush=True)
    for k, v in tests.items():
        print(' ', k, v['t'], v['won'], v['p'], v['pass'], flush=True)
    out = {'prereg': 'project files next-up/prereg-soccer.md', 'n': len(y), 'rate': round(float(y.mean()), 4),
           'coverage': {'coaching change': int(ncoach), 'within-season trend': int(nhalf)},
           'baseline': {'keep': keep, 'logloss': L.compare(r0, r0)['base'], 'calib_heldout': bins(p0, y)},
           'tests': tests, 'not run': {'play-type / tracking style rates': 'no free source covers 2014-15 onward'},
           'model form columns': soft, 'ship': ship, 'final vs baseline': final, 'calib_heldout': bins(pf, y),
           'calib_tested': cal,
           'fit': {'b0': round(b0, 5), 'b': [round(float(v), 6) for v in b], 'mu': [round(float(v), 5) for v in Xf.mean(axis=0)]}}
    json.dump(out, open(OUT, 'w'), indent=1)
    fit['sweep'] = {'ship': ship, 'final vs baseline': final, 'calib_heldout': out['calib_heldout'], 'fit': out['fit']}
    json.dump(fit, open(B.FIT, 'w'), indent=1)
    if 'within-season trend' in ship:      # the live build needs the half-season split only if the signal ships
        json.dump({'H': {str(s): v for s, v in H.items()}, 'TM': {str(s): v for s, v in TM.items()}},
                  gzip.open(os.path.join(ROOT, 'scripts', 'data', 'soccer_breakout_halves.json.gz'), 'wt'),
                  separators=(',', ':'))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
