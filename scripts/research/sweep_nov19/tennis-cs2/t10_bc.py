#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T10: 2-d blade-chest matchup term learned online on Elo residuals, as one more blend input."""
import pickle, time
from tcommon import *
ETAS = (.02, .05); LV = set('GMAFODCQ'); DEC = 1e-3


class BC(M.Model):
    def __init__(self, P, lag):
        super().__init__(P, lag)
        self.rng = np.random.RandomState(7)
        self.v = [{} for _ in ETAS]          # pid -> [blade(2), chest(2)]

    def _v(self, j, p):
        x = self.v[j].get(p)
        if x is None: x = self.v[j][p] = self.rng.normal(0, .1, 4)
        return x

    def mm(self, j, a, b):
        xa, xb = self._v(j, a), self._v(j, b)
        return float(xa[:2] @ xb[2:] - xb[:2] @ xa[2:])

    def ctx(self, a, b, day):
        return super().ctx(a, b, day) + [self.mm(j, a, b) for j in range(len(ETAS))]

    def update(self, r):
        w, l, sf = r[7], r[8], r[3]
        if r[2] in LV and r[0] >= 20000101:
            pe = self.elo_p(w, l, sf)
            if r[5] == 5: pe = M.bo5(pe)
            ze = M.logit(min(max(pe, 1e-6), 1 - 1e-6))
            for j, eta in enumerate(ETAS):
                xw, xl = self._v(j, w), self._v(j, l)
                g = 1 - M.sig(ze + float(xw[:2] @ xl[2:] - xl[:2] @ xw[2:]))
                gw = np.r_[xl[2:], -xl[:2]]; gl = np.r_[-xw[2:], xw[:2]]
                xw += eta * (g * gw - DEC * xw); xl += eta * (g * gl - DEC * xl)
        super().update(r)


rows, players, tn = load_rows()
P = live_P()
p = os.path.join(CACHE, 't10rec.pkl')
if os.path.exists(p): rec = pickle.load(open(p, 'rb'))
else:
    t0 = time.time()
    m = BC(P, M.CM_LAG); M.mark_two_week(rows); rec = []
    for r in rows:
        m.release(r[0])
        if M.scored(r, 2012 - M.WIN, 2100):
            day = M.dnum(r[0], r[4], r[2], r[6])
            pb, pe, pp, gx, cx = m.predict(r[7], r[8], r[1], r[3], day, r[5])
            rec.append((r, pe, pp, gx, cx))
        m.update(r)
    pickle.dump(rec, open(p, 'wb')); print('pass', round(time.time() - t0), 's', flush=True)
F, meta = arrays(rec)
y, tid = meta['y'], meta['tid']
zb = wf_logit(F[:, LIVE], meta)
tune, held = (y >= 2012) & (y <= 2022), y >= 2023
out = {'grid': {}}; Z = {}
for j, eta in enumerate(ETAS):
    Z[eta] = wf_logit(F[:, LIVE + [NB + j]], meta)
    out['grid'][eta] = {'tune_d1e4': round(float((nll(Z[eta][tune]) - nll(zb[tune])).mean() * 1e4), 3),
                        'sd_term': round(float(F[:, NB + j].std()), 4)}
best = min(ETAS, key=lambda e: nll(Z[e][tune]).mean())
d = nll(Z[best]) - nll(zb)
out['best_eta'] = best
out['tune'] = tclust(d[tune], tid[tune]); out['held'] = tclust(d[held], tid[held])
out['seasons'] = {int(s): round(float(d[y == s].mean() * 1e4), 2) for s in range(2012, 2027)}
out['held_better'] = sum(out['seasons'][s] < 0 for s in range(2023, 2027))
out['ll'] = {'base_held': round(float(nll(zb[held]).mean()), 5), 'cand_held': round(float(nll(Z[best][held]).mean()), 5)}
out['pass'] = bool(out['held']['t'] <= -2 and out['tune']['d1e4'] < 0 and out['held_better'] >= 3)
print(json.dumps(out, indent=1)); save('t10_results', out)
# the baseline walk-forward logits for the other tests (winner's side)
pickle.dump({'key': meta['key'], 'z': zb, 'y': y, 'tid': tid, 'd': meta['d'], 'pc': meta['pc'], 'lv': meta['lv'], 'bo': meta['bo'],
             'score': [x[0][9] for x in rec], 'tour': meta['tour']}, open(os.path.join(CACHE, 'base_z.pkl'), 'wb'))
