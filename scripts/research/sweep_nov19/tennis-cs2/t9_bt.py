#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T9: market rating, a ridge Bradley-Terry fit on close residuals (Bet365 bed 2007-22), beside market memory CM."""
import pickle, time
from tcommon import *
HLS = (30, 60, 90); LAM = 3.0; SPAN = 365


class BT(M.Model):
    def __init__(self, P, lag):
        super().__init__(P, lag)
        self.cl, self._half, self._d, self.mr, self.dirty = [], None, None, [{} for _ in HLS], False

    def _mres(self, p, day, v):
        super()._mres(p, day, v)
        if self._half is None: self._half = (p, day, v)
        else:
            w, d0, v0 = self._half; self._half = None
            self.cl.append((d0, w, p, v0))

    def release(self, d):
        n0 = len(self.cl)
        super().release(d)
        if d != self._d or len(self.cl) != n0: self._d, self.dirty = d, True

    def solve(self):
        """lazy: only a scored row asks; ATP and WTA never meet, so each tour is its own system"""
        self.dirty = False
        ref = (M.ymd(self._d) - M.DAY0).days
        while self.cl and self.cl[0][0] < ref - SPAN - 30: self.cl.pop(0)
        self.mr = [{} for _ in HLS]
        for t in 'aw':
            rows = [c for c in self.cl if ref - c[0] <= SPAN and c[1][0] == t]
            if len(rows) < 20: continue
            ids = {}
            for _, w, l, _ in rows:
                ids.setdefault(w, len(ids)); ids.setdefault(l, len(ids))
            iw = np.array([ids[c[1]] for c in rows]); il = np.array([ids[c[2]] for c in rows])
            v = np.array([c[3] for c in rows]); age = np.array([max(0, ref - c[0]) for c in rows], float)
            n = len(ids)
            for j, hl in enumerate(HLS):
                wt = 0.5 ** (age / hl)
                A = np.zeros((n, n)); b = np.zeros(n)
                np.add.at(A, (iw, iw), wt); np.add.at(A, (il, il), wt)
                np.add.at(A, (iw, il), -wt); np.add.at(A, (il, iw), -wt)
                np.add.at(b, iw, wt * v); np.add.at(b, il, -wt * v)
                m = np.linalg.solve(A + LAM * np.eye(n), b)
                self.mr[j].update({p: float(m[i]) for p, i in ids.items()})

    def ctx(self, a, b, day):
        if self.dirty and self._d is not None: self.solve()
        return super().ctx(a, b, day) + [mr.get(a, 0.0) - mr.get(b, 0.0) for mr in self.mr]


rows, players, tn = load_rows()
C = pickle.load(open('/mnt/project-files/tennis/odds/closes_2007_2022.pkl', 'rb'))
n = 0; R = []
for r in rows:
    if r[0] > 20221231: break
    if r[14] is None and r[0] < 20230201:
        pc = C.get((r[0], r[6], r[7], r[8], r[4]))
        if pc: r = r[:14] + [min(max(pc, .01), .99)] + r[15:]; n += 1
    R.append(r)
print('closes placed', n, flush=True)
P = live_P()
p = os.path.join(CACHE, 't9rec.pkl')
if os.path.exists(p): rec = pickle.load(open(p, 'rb'))
else:
    t0 = time.time()
    m = BT(P, M.CM_LAG); M.mark_two_week(R); rec = []
    for r in R:
        m.release(r[0])
        if M.scored(r, 2009, 2021):
            day = M.dnum(r[0], r[4], r[2], r[6])
            pb, pe, pp, gx, cx = m.predict(r[7], r[8], r[1], r[3], day, r[5])
            rec.append((r, pe, pp, gx, cx))
        m.update(r)
    pickle.dump(rec, open(p, 'wb')); print('pass', round(time.time() - t0), 's', flush=True)
F, meta = arrays(rec)
y, tid = meta['y'], meta['tid']
zb = wf_logit(F[:, LIVE], meta)
out = {'closes_placed': n, 'rows_2012_21': int(((y >= 2012) & (y <= 2021)).sum()), 'grid': {}}
tune, held = (y >= 2012) & (y <= 2016), (y >= 2017) & (y <= 2021)
Z = {}
for j, hl in enumerate(HLS):
    Z[hl] = wf_logit(F[:, LIVE + [NB + j]], meta)
    out['grid'][hl] = {'tune_d1e4': round(float((nll(Z[hl][tune]) - nll(zb[tune])).mean() * 1e4), 3),
                       'share_nonzero': round(float((F[:, NB + j] != 0).mean()), 3)}
best = min(HLS, key=lambda h: nll(Z[h][tune]).mean())
d = nll(Z[best]) - nll(zb)
out['best_hl'] = best
out['tune'] = tclust(d[tune], tid[tune]); out['held'] = tclust(d[held], tid[held])
out['seasons'] = {int(s): round(float(d[y == s].mean() * 1e4), 2) for s in range(2012, 2022)}
out['held_better'] = sum(out['seasons'][s] < 0 for s in range(2017, 2022))
out['ll'] = {'base_held': round(float(nll(zb[held]).mean()), 5), 'cand_held': round(float(nll(Z[best][held]).mean()), 5)}
out['pass'] = bool(out['held']['t'] <= -2 and out['tune']['d1e4'] < 0 and out['held_better'] >= 4)
print(json.dumps(out, indent=1)); save('t9_results', out)
