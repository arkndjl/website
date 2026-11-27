#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""DECT in CFB Transfer% (prereg.md T5, T6), on top of scripts/cfb_transfer_fit.py's live features.

    python3 scripts/cfb_transfer_fit.py                          # rows (scripts/.cache/transfer/rows.json)
    python3 scripts/research/dect_features_nov27/cfb_move.py     # -> results_cfb_move.json here

Players on the last fall PFF board before the draft (hist.py: drafts 2025 and 2026 are the 2024 and 2025 seasons) carry
DECT's staying edge (T5: asinh($M / .25), with an on-board flag) or a College verdict (T6). Everyone else 0. Main fold:
fit 2024->25, score 2025->26 (the live split); second fold the other way. Gate t >= 2 clustered by team on the main
fold, second fold t > -1. T7 (a G5 producer's price a level up) is the existing pct_g5 term times a constant and is not
a new term. The rows' head-coach labels come back empty from the cloud container (ESPN's coach endpoint), so the hc
term is 0 in both base and candidate here.
"""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR); sys.path.insert(0, HERE)
import cfb_transfer_fit as T  # noqa: E402
import harness as H  # noqa: E402
import hist  # noqa: E402

OUT = os.path.join(HERE, 'results_cfb_move.json')


def main():
    rows = json.load(open(os.path.join(SCR, '.cache', 'transfer', 'rows.json')))
    T.talent(rows)
    h = hist.load()
    D = {}
    for r in h['cfb'] + h['cfb_extra']:
        if r.get('ce') is None: continue
        D[(T.norm(r['name']), r['draft'] - 1)] = (math.asinh(r['ce'] / 0.25), float(r['ce'] > 0 and not r['even']))
    for r in rows:
        v = D.get((T.norm(r['name']), r['season']))
        r['_d'] = v
    y = lambda rs: np.array([r['y'] == 'transfer' for r in rs], float)
    ll = lambda p, yy: -(yy * np.log(p) + (1 - yy) * np.log(1 - p))
    ext = {'T5 dect_ce': lambda r: [r['_d'][0] if r['_d'] else 0.0, 1.0 if r['_d'] else 0.0],
           'T6 dect_college': lambda r: [r['_d'][1] if r['_d'] else 0.0, 1.0 if r['_d'] else 0.0]}
    out = {'matched': {s: int(sum(1 for r in rows if r['season'] == s and r['_d'])) for s in (2024, 2025)},
           'movedOnBoard': {s: round(float(np.mean([r['y'] == 'transfer' for r in rows if r['season'] == s and r['_d']] or [0])), 4) for s in (2024, 2025)}, 'terms': {}}
    folds = {'main': (2024, 2025), 'back': (2025, 2024)}
    for name, fn in ext.items():
        out['terms'][name] = {}
        for f, (a, b) in folds.items():
            A = [r for r in rows if r['season'] == a]; B = [r for r in rows if r['season'] == b]
            Xa, _ = T.design(A); Xb, _ = T.design(B)
            b0, _ = T.logit_fit(Xa, y(A), T.LAM); p0 = T.sig(Xb @ b0)
            Ea = np.array([fn(r) for r in A]); Eb = np.array([fn(r) for r in B])
            b1, _ = T.logit_fit(np.c_[Xa, Ea], y(A), T.LAM); p1 = T.sig(np.c_[Xb, Eb] @ b1)
            pr = H.paired(ll(p1, y(B)), ll(p0, y(B)), np.array([r['tid'] for r in B]))
            out['terms'][name][f] = {'t': round(-float(pr['t']), 2), 'd': round(float(pr['d']), 6), 'n': int(pr['n']), 'coef': round(float(b1[-2]), 3),
                                     'auc': round(T.auc(p1, y(B)), 4), 'aucBase': round(T.auc(p0, y(B)), 4)}
        v = out['terms'][name]; v['pass'] = bool(v['main']['t'] >= 2 and v['back']['t'] > -1)
        print(name, v, flush=True)
    print(out['matched'], out['movedOnBoard'])
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
