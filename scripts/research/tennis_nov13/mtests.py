#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family M (prereg.md): match-model tests against the live blend, walk-forward, t clustered by tournament."""
import sys, os, math, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
import numpy as np
from scipy import stats

def newton(X, y, ridge=1e-3, w0=None):
    w = np.zeros(X.shape[1]) if w0 is None else w0.copy()
    for _ in range(30):
        p = 1 / (1 + np.exp(-(X @ w)))
        H = (X * (p * (1 - p))[:, None]).T @ X
        w = w + np.linalg.solve(H + ridge * np.eye(len(w)), X.T @ (y - p) - ridge * w)
    return w

def arrays(rec, extra=None):
    F = np.array([M.feats(x) + (extra(x) if extra else []) for x in rec])
    meta = dict(y=np.array([x[0][0] // 10000 for x in rec]), d=np.array([x[0][0] for x in rec]),
                tour=np.array([x[0][1] for x in rec]), tid=np.array([x[0][6] for x in rec]),
                sf=np.array([x[0][3] for x in rec]), lv=np.array([x[0][2] for x in rec]), bo=np.array([x[0][5] for x in rec]),
                pc=np.array([x[0][14] if (x[0][14] and 0 < x[0][14] < 1) else np.nan for x in rec], float),
                key=[(x[0][0], x[0][6], x[0][7], x[0][8], x[0][4]) for x in rec])
    return F, meta

def wf_logit(F, meta, groups=None):
    """walk-forward logits (winner's side): each season from a no-intercept logistic on the 3 seasons before;
    groups: array of labels fit separately (M1)"""
    z = np.full(len(F), np.nan)
    for y in sorted(set(meta['y'])):
        if y < 2012: continue
        for g in ([None] if groups is None else sorted(set(groups))):
            tr = (meta['d'] >= (y - M.WIN) * 10000) & (meta['d'] < y * 10000)
            te = meta['y'] == y
            if g is not None: tr &= groups == g; te &= groups == g
            X = F[tr]
            w0 = np.zeros(F.shape[1]); w0[0] = 1
            w = newton(np.vstack([X, -X]), np.r_[np.ones(len(X)), np.zeros(len(X))], w0=w0)
            z[te] = F[te] @ w
    return z

def nll(z):
    return np.log1p(np.exp(-z))

def compare(zb, mb, zt, mt, label):
    """paired log loss difference test minus base on shared matches; returns dict"""
    ib = {k: i for i, k in enumerate(mb['key'])}
    idx = [(ib[k], j) for j, k in enumerate(mt['key']) if k in ib]
    a = np.array([i for i, _ in idx]); b = np.array([j for _, j in idx])
    d = nll(zt[b]) - nll(zb[a])
    ok = ~np.isnan(d)
    y, tid, pc = mb['y'][a], mb['tid'][a], mb['pc'][a]
    out = {'test': label}
    def tt(mask):
        mask = mask & ok
        g = {}
        for v, t in zip(d[mask], tid[mask]): g[t] = g.get(t, 0.0) + v
        s = np.array(list(g.values()))
        if len(s) < 3: return None
        t = s.sum() / (s.std(ddof=1) * len(s) ** .5)
        return {'n': int(mask.sum()), 'd1e4': round(float(d[mask].mean() * 1e4), 2), 't': round(float(t), 2),
                'p1': float(stats.t.cdf(t, len(s) - 1))}
    out['tune'] = tt((y >= 2012) & (y <= 2022))
    out['held'] = tt(y >= 2023)
    out['seasons'] = {int(s): round(float(d[(y == s) & ok].mean() * 1e4), 2) for s in range(2012, 2027)}
    out['held_better'] = sum(1 for s in range(2023, 2027) if out['seasons'][s] < 0)
    out['tune_better'] = sum(1 for s in range(2012, 2023) if out['seasons'][s] < 0)
    out['close'] = tt(~np.isnan(pc))
    return out

# ---------------------------------------------------------------- model variants
class Var(M.Model):
    """M2 (KLV_C), M3 (LAY c), extras for M4/M5 recorded in cx"""
    def __init__(self, P=None, cm_lag=0, klv_c=1.0, lay=0.0, extras=False):
        super().__init__(P, cm_lag)
        self.klv_c, self.lay, self.extras = klv_c, lay, extras
        self.boost = {}
        self._lv = ''
        self.d180 = {}
    def update(self, r):
        self._lv = r[2]
        day = M.dnum(r[0], r[4], r[2], r[6])
        if self.lay:
            for p in (r[7], r[8]):
                last = self.last.get(p)
                b = self.boost.get(p, 0.0)
                if last is not None and day - last > 30:
                    b += self.lay * min(day - last, 365) / 365
                self.boost[p] = b
        super().update(r)
        if self.lay:
            for p in (r[7], r[8]): self.boost[p] *= 0.8
    def elo_update(self, w, l, sf, mult=1.0):
        if self._lv == 'C': mult *= self.klv_c
        if not self.lay:
            return super().elo_update(w, l, sf, mult)
        ew, el = self._e(w), self._e(l)
        mw, ml = 1 + self.boost.get(w, 0.0), 1 + self.boost.get(l, 0.0)
        for get in (lambda e: e, lambda e: e[2][sf]):
            a, b = get(ew), get(el)
            p = 1 / (1 + 10 ** ((b[0] - a[0]) / 400))
            a0, b0 = a[0], b[0]
            a[0] = a0 + mult * mw * self._k(a[1]) * (1 - p)
            b[0] = b0 - mult * ml * self._k(b[1]) * (1 - p)
            a[1] += 1; b[1] += 1
    def predict(self, a, b, tour, sf, day, bo=3, match=True):
        pb, pe, pp, gx, cx = super().predict(a, b, tour, sf, day, bo, match)
        if self.extras:
            ea, eb = self._e(a), self._e(b)
            k = math.log(10) / 400
            so = k * ((ea[2][sf][0] - eb[2][sf][0]) - (ea[0] - eb[0]))
            def u(p):
                n = sum(1 for x in self.days.get(p, []) if 0 <= day - x <= 180)
                return 1 / math.sqrt(1 + n)
            cx = list(cx) + [so if sf == 'C' else 0.0, so if sf == 'G' else 0.0, M.logit(pe) * (u(a) + u(b))]
        return pb, pe, pp, gx, cx

def run_var(rows, P, name, **kw):
    p = os.path.join(CACHE, name + '.pkl')
    if os.path.exists(p): return pickle.load(open(p, 'rb'))
    m = Var(P, M.CM_LAG, **kw)
    M.mark_two_week(rows)
    out = []
    for r in rows:
        m.release(r[0])
        if M.scored(r, 2012 - M.WIN, 2100):
            day = M.dnum(r[0], r[4], r[2], r[6])
            pb, pe, pp, gx, cx = m.predict(r[7], r[8], r[1], r[3], day, r[5])
            out.append((r, pe, pp, gx, cx))
        m.update(r)
    pickle.dump(out, open(p, 'wb'))
    return out

def base8(x): return []
if __name__ == '__main__':
    rows, players, tn = load_rows()
    P = live_P()
    rec = base_rec(rows)
    Fb, mb = arrays(rec)
    zb = wf_logit(Fb, mb)
    ok = mb['y'] >= 2012
    print('base check: tune', round(nll(zb[(mb['y'] >= 2012) & (mb['y'] <= 2022)]).mean(), 5), 'held', round(nll(zb[mb['y'] >= 2023]).mean(), 5))
    res = []
    # M1 tour blend
    res.append(compare(zb, mb, wf_logit(Fb, mb, groups=mb['tour']), mb, 'M1 tour blend'))
    print(json.dumps(res[-1])); sys.stdout.flush()
    # M2 Challenger K
    best = None
    for v in (0.7, 0.85):
        rv = run_var(rows, P, f'klvc{v}', klv_c=v)
        F, m_ = arrays([x[:4] + (x[4][:5],) for x in rv]); z = wf_logit(F, m_)
        c = compare(zb, mb, z, m_, f'M2 Challenger K {v}')
        print(json.dumps(c)); sys.stdout.flush()
        if best is None or c['tune']['t'] < best['tune']['t']: best = c
    res.append(best)
    # M3 layoff K
    best = None
    for v in (0.5, 1.0):
        rv = run_var(rows, P, f'lay{v}', lay=v)
        F, m_ = arrays(rv); z = wf_logit(F, m_)
        c = compare(zb, mb, z, m_, f'M3 layoff K {v}')
        print(json.dumps(c)); sys.stdout.flush()
        if best is None or c['tune']['t'] < best['tune']['t']: best = c
    res.append(best)
    # M4 / M5 extras
    rx = run_var(rows, P, 'extras', extras=True)
    Fx, mx = arrays([x[:4] + (x[4][:5],) for x in rx], extra=lambda x: [])
    E = np.array([x[4][5:] for x in rx])
    z0 = wf_logit(Fx, mx)
    print('extras base parity', round(float(np.nanmax(np.abs(z0 - zb))), 6))
    res.append(compare(zb, mb, wf_logit(np.hstack([Fx, E[:, :2]]), mx), mx, 'M4 surface share clay/grass'))
    print(json.dumps(res[-1])); sys.stdout.flush()
    res.append(compare(zb, mb, wf_logit(np.hstack([Fx, E[:, 2:3]]), mx), mx, 'M5 activity shrink'))
    print(json.dumps(res[-1])); sys.stdout.flush()
    # M6 tree stack
    from sklearn.ensemble import HistGradientBoostingClassifier
    cat = np.c_[(mb['tour'] == 'atp').astype(float), (mb['sf'] == 'C').astype(float), (mb['sf'] == 'G').astype(float),
                (mb['bo'] == 5).astype(float), np.array([{'G': 3, 'M': 2, 'F': 2, 'O': 2}.get(l, 1) for l in mb['lv']], float)]
    zt = np.full(len(Fb), np.nan)
    for y in sorted(set(mb['y'])):
        if y < 2012: continue
        tr = (mb['d'] >= (y - M.WIN) * 10000) & (mb['d'] < y * 10000); te = mb['y'] == y
        X = np.vstack([np.c_[Fb[tr], cat[tr]], np.c_[-Fb[tr], cat[tr]]])
        yy = np.r_[np.ones(tr.sum()), np.zeros(tr.sum())]
        g = HistGradientBoostingClassifier(max_depth=3, learning_rate=.05, max_iter=200, min_samples_leaf=200, random_state=0).fit(X, yy)
        p1 = g.predict_proba(np.c_[Fb[te], cat[te]])[:, 1]; p2 = 1 - g.predict_proba(np.c_[-Fb[te], cat[te]])[:, 1]
        zg = (np.log(p1 / (1 - p1)) + np.log(p2 / (1 - p2))) / 2
        zt[te] = (zb[te] + zg) / 2
    res.append(compare(zb, mb, zt, mb, 'M6 tree stack'))
    print(json.dumps(res[-1])); sys.stdout.flush()
    # Holm on held p
    ps = sorted([(r['held']['p1'], r['test']) for r in res])
    m = len(ps); adj = {}; run = 0
    for i, (p, t) in enumerate(ps):
        run = max(run, min(1.0, (m - i) * p)); adj[t] = run
    for r in res:
        r['held_holm_p'] = round(adj[r['test']], 4)
        r['pass'] = bool(r['tune']['t'] <= -2 and r['held_holm_p'] < .05 and r['held_better'] >= 3 and r['close']['d1e4'] <= 0)
        print(r['test'], 'tune', r['tune']['d1e4'], r['tune']['t'], 'held', r['held']['d1e4'], r['held']['t'], 'holm', r['held_holm_p'],
              'seasons', r['held_better'], '/4 close', r['close']['d1e4'], r['close']['t'], 'PASS' if r['pass'] else 'fail')
    json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'm_results.json'), 'w'), indent=1)
