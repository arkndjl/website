#!/usr/bin/env python3
"""Junior / amateur club development effect as a hockey draft-model FV driver (research, Nov 2 2026).

New angle (the drafting NHL team's past residual failed Oct 31): does the club a prospect plays for in his draft
year (London Knights, a Swedish academy, the USNTDP...) carry information the draft slot and stats miss, because
some programs develop players better after the draft, or because scouts over/under-rate their products?
clubEff for a pick in class Y = shrunk mean residual (outcome FV minus the kept draft model fit on classes < Y only,
in-sample there) of the same club's picks in classes before Y: sum / (n + K), K = 8. No class Y outcome enters it.
Gate (the board's): leave-one-class-out MSE gain t >= 2 and 8 of 12 classes; top 64 picks MSE not worse; forward
(fit 2008-15, grade 2016-19) MSE and top-64 MSE not worse. Rows: frozen scripts/data/hockey_rows.json.gz.
Result (Nov 2 2026): FAILED. Class-out MSE 90.06 -> 90.04 (t 0.42, 8/12), top-64 114.9 vs 115.0, forward 83.32 vs 83.33
but forward top-64 113.91 vs 113.66 (worse).
Writes data/hockey_club_research.json."""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hockey_prospects as H  # noqa: E402

K = 8


def main():
    W = H.war_tables()
    rows = H.read_rows(W)
    H.nhl_so_far(rows, W)
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr])
    cls = np.array([r['year'] for r in tr])
    F = [H.feats(r) for r in tr]
    fit = json.load(open(H.FIT))
    kept = [c for c in fit.get('kept') or fit.get('draft', {}).get('kept') or [] if c != 'cs']
    if not kept:
        kept, _, _ = H.select(F, y, cls, H.BASE, H.CANDS)
    print('kept', kept, flush=True)
    X = np.array([[f[c] for c in kept] for f in F])
    club = [(r.get('club') or '') + '|' + (r.get('league') or '') for r in tr]
    for Y in sorted(set(cls)):
        m = cls < Y
        eff = defaultdict(lambda: [0.0, 0])
        if m.sum() > 50:
            b = H.ols(X[m], y[m])
            res = y[m] - H.pred(b, X[m])
            for i, e in zip(np.where(m)[0], res):
                eff[club[i]][0] += e; eff[club[i]][1] += 1
        for i in np.where(cls == Y)[0]:
            s, n = eff.get(club[i], [0.0, 0])
            F[i]['clubEff'] = s / (n + K) / 10
    out = {'note': __doc__.split('\n')[0], 'kept': kept, 'K': K}
    s0, p0 = H.score(F, y, cls, kept)
    s1, p1 = H.score(F, y, cls, kept + ['clubEff'])
    d = s0 - s1
    out['loco'] = {'mse': [round(float(s0.mean()), 2), round(float(s1.mean()), 2)], 'gain': round(float(d.mean()), 3),
                   't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'wins': int((d > 0).sum()), 'of': len(d)}
    top = np.array([r['pick'] <= 64 for r in tr])
    out['top64'] = {'mse': [round(float(np.mean((p0[top] - y[top]) ** 2)), 2), round(float(np.mean((p1[top] - y[top]) ** 2)), 2)]}
    fw_tr, fw_te = cls <= 2015, (cls >= 2016) & (cls <= 2019)
    res = {}
    for nm, cols in (('base', kept), ('club', kept + ['clubEff'])):
        Xc = np.array([[f[c] for c in cols] for f in F])
        b = H.ols(Xc[fw_tr], y[fw_tr])
        p = np.clip(H.pred(b, Xc[fw_te]), 20, 80)
        res[nm] = (float(np.mean((p - y[fw_te]) ** 2)), float(np.mean((p[top[fw_te]] - y[fw_te][top[fw_te]]) ** 2)), [round(float(v), 3) for v in b])
    out['forward'] = {'mse': [round(res['base'][0], 2), round(res['club'][0], 2)], 'top64mse': [round(res['base'][1], 2), round(res['club'][1], 2)],
                      'coefClubEff': res['club'][2][-1]}
    ok = out['loco']['t'] >= 2 and out['loco']['wins'] >= 8 and out['top64']['mse'][1] <= out['top64']['mse'][0] and \
        out['forward']['mse'][1] <= out['forward']['mse'][0] and out['forward']['top64mse'][1] <= out['forward']['top64mse'][0]
    out['pass'] = bool(ok)
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(H.ROOT if hasattr(H, 'ROOT') else os.path.dirname(HERE), 'data', 'hockey_club_research.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
