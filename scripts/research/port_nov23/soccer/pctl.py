#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""M9 soccer projection percentiles (port of NFL/NBA/NHL P20/P50/P80): P20 / P80 around pj (GAR next season) and p3.

Residual quantiles (target - prediction of the board's picked form, leave one season out) in 5 bins of the
prediction, per season share f. Test: every season's bins are fit on the other seasons (the prediction itself LOSO
too); coverage of P20 and P80 overall (gate +-.03), per f (+-.05), per position (+-.06), per season (+-.08).
Split-half stability: bin edges' quantiles from odd vs even seasons, r reported.

    python3 scripts/research/port_nov23/soccer/pctl.py     # -> pctl.json here (the fit + the test)
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCRIPTS)
import soccer_data as D             # noqa: E402
import soccer_players as SP         # noqa: E402
import soccer_proj_research as PR   # noqa: E402

NB = 5
OUT = os.path.join(HERE, 'pctl.json')


def frames(tgt):
    SF = PR.season_files()
    snap = D.load(PR.SNAPS)
    dob = SP.proj_dobs()
    F = json.load(open(PR.OUT))
    form = F[tgt]['form']
    cols = SP.PROJ_COLS
    ix = {'age': ['one', 'g0', 'p1', 'lm0', 'a', 'a2', 'am']}
    ix['agepos'] = ix['age'] + ['d', 'm', 'fw', 'ad', 'am_', 'af']
    ix = [cols.index(c) for c in ix[form]]
    last = 2025 if tgt == '1y' else 2023
    out = {}
    for f in PR.FS:
        X, Y, SS, POS = [], [], [], []
        for S in range(PR.S_FIRST, last + 1):
            if f < 1:
                sn = snap[f'{S}_{f}']; cur, fl = sn['p'], sn['f']
            else:
                cur, fl = SF[S], PR.full_f(S)
            nxt = SF.get(S + 1, {})
            for p, (mn, g, pos, lg) in cur.items():
                if p not in nxt or p not in dob or lg not in fl:
                    continue
                y = nxt[p][1] if tgt == '1y' else sum(SF.get(S + k, {}).get(p, [0, 0.0])[1] for k in (1, 2, 3))
                x1, x2 = SF.get(S - 1, {}).get(p), SF.get(S - 2, {}).get(p)
                pr = [(x1 or [0, 0.0])[0], (x1 or [0, 0.0])[1], (x2 or [0, 0.0])[0], (x2 or [0, 0.0])[1]]
                X.append(SP.proj_x(mn, g, pos, SP.age_on(S, dob[p]), pr, max(fl[lg], 0.05)))
                Y.append(y); SS.append(S); POS.append(pos)
        X, Y, SS = np.array(X), np.array(Y), np.array(SS)
        pred = np.zeros(len(Y))
        for s in sorted(set(SS.tolist())):
            tr, te = SS != s, SS == s
            b = np.linalg.lstsq(X[tr][:, ix], Y[tr], rcond=None)[0]
            pred[te] = X[te][:, ix] @ b
        out[f] = (pred, Y, SS, np.array(POS))
    return out


def fit_bins(pred, e):
    edges = np.quantile(pred, np.linspace(0, 1, NB + 1)[1:-1]).tolist()
    b = np.searchsorted(edges, pred)
    q = [[float(np.quantile(e[b == i], 0.2)), float(np.quantile(e[b == i], 0.8))] for i in range(NB)]
    return {'edges': [round(x, 3) for x in edges], 'q': [[round(a, 3), round(c, 3)] for a, c in q]}


def apply(B, pred):
    b = np.searchsorted(B['edges'], pred)
    q = np.array(B['q'])
    return pred + q[b, 0], pred + q[b, 1]


def main():
    res = {}
    for tgt in ('1y', '3y'):
        fr = frames(tgt)
        res[tgt] = {'grid': [], 'test': {}}
        allc = defaultdict(list)
        for f, (pred, Y, SS, POS) in fr.items():
            e = Y - pred
            res[tgt]['grid'].append({'f': f, **fit_bins(pred, e), 'n': int(len(Y))})
            lo, hi = np.zeros(len(Y)), np.zeros(len(Y))
            for s in sorted(set(SS.tolist())):
                tr, te = SS != s, SS == s
                B = fit_bins(pred[tr], e[tr])
                lo[te], hi[te] = apply(B, pred[te])
            b20, b80 = (Y < lo), (Y < hi)
            allc['all'] += list(zip(b20, b80))
            allc[f'f{f}'] = list(zip(b20, b80))
            for p in set(POS.tolist()):
                allc[f'pos{p}'] += list(zip(b20[POS == p], b80[POS == p]))
            for s in sorted(set(SS.tolist())):
                allc[f'S{s}'] += list(zip(b20[SS == s], b80[SS == s]))
            # split half: odd vs even seasons' bin quantiles
            od, ev = SS % 2 == 1, SS % 2 == 0
            Bo, Be = fit_bins(pred[od], e[od]), fit_bins(pred[ev], e[ev])
            qo = [x for pair in Bo['q'] for x in pair]; qe = [x for pair in Be['q'] for x in pair]
            res[tgt]['test'][f'splitHalfR_f{f}'] = round(float(np.corrcoef(qo, qe)[0, 1]), 3)
        ok = True
        cov = {}
        for k, v in allc.items():
            a = np.array(v, dtype=float)
            c20, c80 = float(a[:, 0].mean()), float(a[:, 1].mean())
            tol = .03 if k == 'all' else .05 if k.startswith('f') else .06 if k.startswith('pos') else .08
            good = abs(c20 - .2) <= tol and abs(c80 - .8) <= tol
            ok &= good
            cov[k] = {'n': len(v), 'p20': round(c20, 3), 'p80': round(c80, 3), 'ok': good}
        res[tgt]['test']['coverage'] = cov
        res[tgt]['test']['pass'] = bool(ok)
        print(tgt, ok, json.dumps({k: (v['p20'], v['p80'], v['ok']) for k, v in cov.items()}), flush=True)
        print(tgt, {k: v for k, v in res[tgt]['test'].items() if k.startswith('split')})
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
