#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family C (prereg-market.md): the market-memory term on Bet365 closes 2007-2021."""
import sys, os, json, pickle, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import *
from mtests import newton, arrays, wf_logit, nll, compare
import numpy as np
from scipy import stats
GRID = list(itertools.product((8, 16), (120, 365), (3, 6)))
class MM(M.Model):
    def _mres(self, p, day, v):
        q = self.mres.setdefault(p, [])
        q.append((day, v)); del q[:-16]
    def ctx(self, a, b, day):
        keep = self.mres
        # the live term reads the last 8
        self.mres = {p: keep.get(p, [])[-8:] for p in (a, b)}
        cx = super().ctx(a, b, day)
        self.mres = keep
        ex = []
        for N, W, S in GRID:
            v = []
            for p in (a, b):
                mr = [z for d_, z in keep.get(p, [])[-N:] if day - d_ <= W]
                v.append(sum(mr) / (len(mr) + S))
            ex.append(v[0] - v[1])
        return cx + ex
rows, players, tn = load_rows()
C = pickle.load(open(os.path.join(CACHE, 'closes.pkl'), 'rb'))
n = 0
R = []
for r in rows:
    if r[14] is None and r[0] < 20230201:
        pc = C.get((r[0], r[6], r[7], r[8], r[4]))
        if pc: r = r[:14] + [min(max(pc, .01), .99)] + r[15:]; n += 1
    R.append(r)
print('closes placed', n)
P = live_P()
p = os.path.join(CACHE, 'crec.pkl')
if os.path.exists(p): rec = pickle.load(open(p, 'rb'))
else:
    m = MM(P, M.CM_LAG); M.mark_two_week(R); rec = []
    for r in R:
        m.release(r[0])
        if M.scored(r, 2009, 2021):
            day = M.dnum(r[0], r[4], r[2], r[6])
            pb, pe, pp, gx, cx = m.predict(r[7], r[8], r[1], r[3], day, r[5])
            rec.append((r, pe, pp, gx, cx))
        m.update(r)
    pickle.dump(rec, open(p, 'wb'))
F, meta = arrays([x[:4] + (x[4][:5],) for x in rec])
E = np.array([x[4][5:] for x in rec])
print('live CM equals grid (8,120,3):', float(np.abs(F[:, 7] - E[:, GRID.index((8, 120, 3))]).max()), 'share of rows with CM != 0:', round(float((F[:, 7] != 0).mean()), 3))
z_with = wf_logit(F, meta)
z_wo = wf_logit(F[:, :7], meta)
def tt(d, mask):
    g = {}
    for v, t in zip(d[mask], meta['tid'][mask]): g[t] = g.get(t, 0.0) + v
    s = np.array(list(g.values())); t = s.sum() / (s.std(ddof=1) * len(s) ** .5)
    return round(float(d[mask].mean() * 1e4), 2), round(float(t), 2), float(stats.t.cdf(t, len(s) - 1))
y = meta['y']
d = nll(z_with) - nll(z_wo)
ok = (y >= 2012) & (y <= 2021)
c1 = tt(d, ok); seas = {int(s): round(float(d[y == s].mean() * 1e4), 2) for s in range(2012, 2022)}
print('C1 CM vs no CM 2012-21: d x1e4, t, p', c1, 'seasons', seas, 'better', sum(v < 0 for v in seas.values()), '/10')
# weights of CM by season window
for s in (2012, 2015, 2018, 2021):
    tr = (meta['d'] >= (s - 3) * 10000) & (meta['d'] < s * 10000); X = F[tr]
    w0 = np.zeros(8); w0[0] = 1
    print('  CM weight, window before', s, round(float(newton(np.vstack([X, -X]), np.r_[np.ones(len(X)), np.zeros(len(X))], w0=w0)[7]), 3))
# C2 grid on 2012-16
res = {}
for j, g in enumerate(GRID):
    Fg = F.copy(); Fg[:, 7] = E[:, j]
    zg = wf_logit(Fg, meta); res[g] = zg
    print('  grid', g, 'tune LL 2012-16', round(float(nll(zg[(y >= 2012) & (y <= 2016)]).mean()), 6), 'held 2017-21', round(float(nll(zg[(y >= 2017) & (y <= 2021)]).mean()), 6))
best = min(GRID, key=lambda g: nll(res[g][(y >= 2012) & (y <= 2016)]).mean())
d2 = nll(res[best]) - nll(z_with)
h = (y >= 2017) & (y <= 2021)
c2 = tt(d2, h); seas2 = {int(s): round(float(d2[y == s].mean() * 1e4), 2) for s in range(2017, 2022)}
print('C2 best on tune', best, 'vs live on 2017-21:', c2, seas2, 'better', sum(v < 0 for v in seas2.values()), '/5')
ps = sorted([(c1[2], 'C1'), (c2[2], 'C2')]); print('Holm:', {t: round(min(1, (2 - i) * p), 5) for i, (p, t) in enumerate(ps)})
# the close itself
pc = meta['pc']; m_ = ok & ~np.isnan(pc)
zc = np.log(pc[m_] / (1 - pc[m_]))
print('close rows 2012-21', int(m_.sum()), 'LL model', round(float(nll(z_with[m_]).mean()), 5), 'no CM', round(float(nll(z_wo[m_]).mean()), 5), 'Bet365 close', round(float(nll(zc).mean()), 5))
X = np.c_[zc, z_with[m_] - zc]; w = newton(np.vstack([X, -X]), np.r_[np.ones(len(X)), np.zeros(len(X))], ridge=1e-9, w0=np.array([1., 0.]))
print('result on close + (model - close):', np.round(w, 3))
json.dump(dict(c1=c1, c1_seasons=seas, c2_best=best, c2=c2, c2_seasons=seas2), open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'c_results.json'), 'w'), indent=1)
