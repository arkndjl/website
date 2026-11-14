#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""G2 of PREREG.md, and the production check of J3/J4: the lineup term with scripts/nba_play.py's chances against the
status x streak table, on the live model's walk-forward (each season's play fit is from the seasons before it).

    python3 scripts/nba_play.py --fit
    python3 scripts/research/inj_nov14/nba_games_test.py       # writes data/inj_nov14_nba_games.json
"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import harness as H
import nba_games as N
import nba_games_fit as NF
import nba_play as NP
from logit_ridge import logloss

OUT = os.path.join(N.ROOT, 'data', 'inj_nov14_nba_games.json')


def main():
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj = N.load_inj()
    res = {'prereg': 'scripts/research/inj_nov14/PREREG.md'}
    # J3/J4 through the production code: fit on 2020-22, scored on 2023-26
    R = NP.rows(games, names, inj)
    S = np.array([r[0] for r in R]); y = np.array([r[3] for r in R]); w = np.array([r[2]['R'] for r in R]); day = np.array([r[1] for r in R])
    st = np.array([r[2]['st'] for r in R]); bk = np.array([r[2]['bk'] for r in R])
    A, B = S <= 2022, S >= 2023
    f = NP.fit_rows(R, A)
    pc = np.array([NP.prob(r[2], f) for r in R]); p3 = np.array([NP.prob(r[2], {'j3': f['j3']}) for r in R])
    tab = {}
    for s_ in set(st):
        k = A & (st == s_); tab[s_ + 'all'] = float((w[k] * y[k]).sum() / w[k].sum()) if k.any() else 0.9
        for b_ in range(5):
            k2 = k & (bk == b_)
            if k2.sum() >= 30:
                tab[s_ + str(b_)] = float((w[k2] * y[k2]).sum() / w[k2].sum())
    p0 = np.array([tab.get(a + str(b), tab.get(a + 'all', 0.9)) for a, b in zip(st, bk)])
    wn = w / w.mean()

    def cmp(pa, pb, k):
        r = H.paired(wn[k] * logloss(pa[k], y[k]), wn[k] * logloss(pb[k], y[k]), cluster=day[k])
        return {'n': int(k.sum()), 'base': round(float((wn[k] * logloss(pb[k], y[k])).sum() / wn[k].sum()), 4),
                'cand': round(float((wn[k] * logloss(pa[k], y[k])).sum() / wn[k].sum()), 4), 't': round(r['t'], 2)}
    L = np.isin(st, NP.LISTED) & np.array([r[2]['prev'] is not None for r in R])
    res['players'] = {'rows': len(R), 'j3_vsTable': {'tune': cmp(p3, p0, A), 'held': cmp(p3, p0, B)}, 'j4_vsJ3_listed': {'tune': cmp(pc, p3, A & L), 'held': cmp(pc, p3, B & L)},
                      'live_vsTable': {'held': cmp(pc, p0, B), 'heldByStatus': {s_: cmp(pc, p0, B & (st == s_)) for s_ in ('none', 'Questionable', 'Probable', 'Doubtful', 'Available')}}}
    print(json.dumps(res['players'], indent=1), flush=True)

    # G2: the game model's walk with the table and with the fitted chances (walk fits: no season reads its own rows)
    params = F['params']
    _, _, PT = NF.measure_P(games, names, inj, params)
    out = {}
    for on in (False, True):
        N.PLAY_MODEL = on
        D, X, TX, yv, ty, Sg, line, tline = NF.design(games, names, PT, params, inj, F['feats'])
        Xm = NF.mat(X, F['feats'])
        out[on] = (NF.wf(Xm, yv, Sg), np.linalg.lstsq(Xm, yv, rcond=None)[0], X['lin'].copy())
    N.PLAY_MODEL = True
    days = np.array([str(N.gday(N.tipdt(g))) for g, _, _ in D])
    ok = ~np.isnan(line) & ~np.isnan(out[True][0])
    p1, p0g = out[True][0], out[False][0]

    def gcmp(k):
        r = H.paired(np.abs(p1[k] - yv[k]), np.abs(p0g[k] - yv[k]), cluster=days[k])
        return {'n': int(k.sum()), 'maeBase': round(float(np.abs(p0g[k] - yv[k]).mean()), 4), 'maeCand': round(float(np.abs(p1[k] - yv[k]).mean()), 4),
                'maeLine': round(float(np.abs(line[k] - yv[k]).mean()), 4), 'd': round(r['d'], 4), 't': round(r['t'], 2), 'p': r['p']}
    res['G2'] = {'tune2022': gcmp(ok & (Sg == 2022)), 'held2023_26': gcmp(ok & (Sg >= 2023)),
                 'bySeason': {int(s): gcmp(ok & (Sg == s))['d'] for s in range(2022, 2027)},
                 'linCoef': [round(float(out[False][1][F['feats'].index('lin')]), 3), round(float(out[True][1][F['feats'].index('lin')]), 3)],
                 'linMoveSd': round(float((out[True][2] - out[False][2])[Sg >= 2022].std()), 3)}
    mv = p1 - p0g; k = ok & (Sg >= 2023) & (np.abs(mv) > 1e-9)
    bb = float((mv[k] @ (yv[k] - line[k])) / (mv[k] @ mv[k])); rr = (yv[k] - line[k]) - bb * mv[k]
    res['G2']['vsCloseHeld'] = {'b': round(bb, 2), 't': round(bb / float(np.sqrt(rr @ rr / (k.sum() - 1) / (mv[k] @ mv[k]))), 2)}
    print(json.dumps(res['G2'], indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
