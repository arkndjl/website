"""D1 follow-up: full-sample refit weights, XV vs D1 paired, D1 weights on the predict test (not a new candidate)."""
import json, os, numpy as np, harness as H
line = lambda y, t: np.array([sum(H.CWAR_V[H.g_(p)] * e for p, tt, e in H.PARTS[(y, 7)] if tt == t)])
o1, sq1 = H.describe(H.M['pfn_z'], 7, H.YEARS, by_pos=True, lam=1.0, extra=line)
o3, sq3 = H.describe(H.M['xv'], 7, H.YEARS)
rows = [r for y in H.YEARS for r in H.centre(H.feats(y, 7, H.M['pfn_z'], by_pos=True, extra=line), H.SRS[y])]
w = H.fit(rows, 1.0); bline = w[-1]; W = {g: round(float(w[i] / bline), 3) for i, g in enumerate(H.P7)}
cw = lambda y, p: H.CWAR_V[H.g_(p)] + W[H.g_(p)] * H.R[y][p]['z']
base, sqb = H.predict(H.M['cwar'], 7, H.PAIRS); d1p, sqd = H.predict(cw, 7, H.PAIRS)
out = dict(xv_vs_d1=H.paired(sq1, sq3), d1_weights_per_line_unit=W, sav_w={g: H.SAV_W[g] for g in H.P7},
           predict_base=dict(team=base['teamOOS'], r=base['playerR']), predict_d1w=dict(team=d1p['teamOOS'], r=d1p['playerR'], **H.paired(sqb, sqd)))
print(out); json.dump(out, open(os.path.join(H.HERE, 'd1_check.json'), 'w'), indent=1)
