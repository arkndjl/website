#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT preview blend under the priced five: a x logit(elo/talent) + b x RWA gap / 100.

    python3 scripts/esea_blend_research.py [--out FILE]   # research/esea_matches.json.gz -> data/esea_blend_research.json (~2 min)

The elo/talent term exists only where the page saved its rankings (S59), so the tune seasons (S54-S57) cannot
refit the pair. They can say how the RWA slope moves when a side is priced as the expected (sharp) five instead
of the five who played: b = shipped b x (tune slope, sharp five) / (tune slope, actual five). That b is scored
against the shipped one on the held rows that have the page's inputs, paired by match, clustered by match day."""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esea_standin_research as SR  # noqa: E402
import esea_rwa_research as R  # noqa: E402

OUT = os.path.join(SR.ROOT, 'data', 'esea_blend_research.json')
SHIPPED = (0.316, 14.2)


def pnorm(t):
    return 0.5 * math.erfc(-t / math.sqrt(2))


def main():
    out_ = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else OUT
    d, ms = SR.load()
    SR.predicted_fives(ms)
    fit = json.load(open(R.OUT))
    M = R.Maps(ms)
    cuts = R.weekly(ms)
    av = R.ark_values(M, (M.gseason >= 53) & (M.gseason <= R.TUNE[1]))
    p = fit['params']
    X = {five: R.rwa_gaps(ms, M, av, p, cuts, five) for five in SR.FIVES}
    ok = [m for m in ms if m['pf_ok'] and m['season'] > SR.BURN and all(m['id'] in X[f] for f in SR.FIVES)]
    day = {m['id']: int(m['at'] // SR.DAY) for m in ms}
    tune = [m for m in ok if R.TUNE[0] <= m['season'] <= R.TUNE[1]]
    y = [m['y'] for m in tune]
    s_act = SR.logit_fit([[X['actual'][m['id']]] for m in tune], y)[0]
    s_shp = SR.logit_fit([[X['sharp'][m['id']]] for m in tune], y)[0]
    r = s_shp / s_act
    a0, b0 = SHIPPED
    b1 = b0 * r
    res = {'asof': d.get('asof'), 'params': p, 'shipped': {'a': a0, 'b': b0},
           'tune': {'n': len(tune), 'slope_actual': round(s_act, 4), 'slope_sharp': round(s_shp, 4), 'r': round(r, 5)},
           'candidate': {'a': a0, 'b': round(b1, 4)}}
    tl = lambda s: {m['id']: SR.ll(SR.sig(s * X['sharp'][m['id']]), m['y']) for m in tune}
    res['tune']['one_term_sharp_vs_actual_slope'] = SR.day_t(tl(s_shp), tl(s_act), day)
    # held rows with the page's own inputs
    snaps = SR.snapshots()
    rows = []
    for m in ok:
        if not (R.HELD[0] <= m['season'] <= R.HELD[1]) or not snaps:
            continue
        prior = [x for x in snaps if x[0] < m['at'] - 60]
        if not prior:
            continue
        S = prior[-1][1]
        a, b = S.get(m['f1']['id']), S.get(m['f2']['id'])
        if not a or not b or not a.get('elo') or not b.get('elo'):
            continue
        ta, tb = (a.get('talent') or {}).get('exact'), (b.get('talent') or {}).get('exact')
        pe = 1 / (1 + 10 ** (-(a['elo'] - b['elo']) / 600))
        pv = SR.sig(0.8 * SR.lg(pe) + 0.2 * SR.lg(SR.sig(0.48 * (ta - tb)))) if ta is not None and tb is not None else pe
        rows.append({'id': m['id'], 'y': m['y'], 'season': m['season'], 'pv': SR.lg(pv), 'x': X['sharp'][m['id']]})
    loss = lambda a, b: {q['id']: SR.ll(SR.sig(a * q['pv'] + b * q['x']), q['y']) for q in rows}
    res['held_rows'] = {'n': len(rows), 'seasons': sorted({q['season'] for q in rows}), 'snapshots': len(snaps)}
    if len(rows) >= 30:
        h = SR.day_t(loss(a0, b1), loss(a0, b0), day)
        tt = res['tune']['one_term_sharp_vs_actual_slope']
        res['B1'] = {'held': h, 'p': round(pnorm(h['t']), 4), 'tune_t': tt['t'],
                     'pass': bool(h['t'] <= -1.65 and h['diff'] < 0 and tt['t'] < 0)}
        fa, fb = SR.logit_fit([[q['pv'], q['x']] for q in rows], [q['y'] for q in rows])
        L = loss(fa, fb)
        res['reported'] = {'s59_refit_in_sample': {'a': round(fa, 3), 'b': round(fb, 3), 'll': round(sum(L.values()) / len(L), 4),
                                                   'note': 'fit on the held rows themselves; not a test'}}
    json.dump(res, open(out_, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
