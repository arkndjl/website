#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""C2 of PREREG.md: the 1Y / 3Y WAR projection with the market's read (draft slot on a rookie deal, cap share after).

    python3 scripts/player_pctl.py --frames nfl            # once
    python3 scripts/research/nfl_nov13/proj_test.py        # data/nfl_audit_nov13.json ('proj')
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import harness as H                 # noqa: E402
import nfl_war_proj_research as PR  # noqa: E402
import market as MK                 # noqa: E402

OUT = os.path.join(PR.ROOT, 'data', 'nfl_audit_nov13.json')


def extra(r):
    """by group: rookie-deal flag, flag x -ln pick, veteran x ln cap %"""
    s = MK.signal(r['pid'], r['S'])
    x = []
    for G in PR.GROUPS:
        d = 1.0 if r['g'] == G else 0.0
        x += [d * (1.0 if s and s[0] == 'r' else 0.0), d * (s[1] if s and s[0] == 'r' else 0.0), d * (s[1] if s and s[0] == 'v' else 0.0)]
    return x


def main():
    F, rate, B = PR.load()
    T = PR.season_tab(F)
    live = json.load(open(PR.OUT))['form']
    res = {'liveForm': live, 'cells': {}}
    ps = []
    for w in ('9', 'end'):
        R = []
        for S in sorted(F):
            R += PR.rows_at(F, T, B, rate, S, w)[0]
        for tgt in ('y1', 'y3'):
            Q = [r for r in R if r[tgt] is not None and r['S'] >= 2015]
            y = np.array([r[tgt] for r in Q]); S = np.array([r['S'] for r in Q])
            X0 = PR.X_of(live, Q)
            X1 = np.column_stack([X0, np.array([extra(r) for r in Q])])
            e0 = (PR.loso(X0, y, S) - y) ** 2; p1 = PR.loso(X1, y, S); e1 = (p1 - y) ** 2
            d = e1 - e0
            seasons = sorted(set(S))
            ds = np.array([d[S == s].mean() for s in seasons])
            t = PR.tstat(d)
            p = H.t_cdf(t, len(d) - 1)
            ps.append(p)
            c = {'n': len(Q), 'rmse': [round(float(np.sqrt(e0.mean())), 4), round(float(np.sqrt(e1.mean())), 4)], 't': round(t, 2), 'p': p,
                 'tSeason': round(PR.tstat(ds), 2), 'won': f'{int((ds < 0).sum())}/{len(seasons)}',
                 'slope': round(float(np.polyfit(p1, y, 1)[0]), 3),
                 'pass': bool(t <= -2 and (ds < 0).sum() * 2 > len(seasons))}
            G = np.array([r['g'] for r in Q])
            c['byGroup'] = {g: round(PR.tstat(d[G == g]), 2) for g in PR.GROUPS}
            b = PR.fit_all(X1, y)[-3 * len(PR.GROUPS):]
            c['coef'] = {g: [round(float(v), 4) for v in b[3 * i:3 * i + 3]] for i, g in enumerate(PR.GROUPS)}
            res['cells'][f'{w}:{tgt}'] = c
            print(w, tgt, {k: c[k] for k in ('n', 'rmse', 't', 'tSeason', 'won', 'slope', 'pass')}, flush=True)
    res['p'] = max(ps)
    res['pass'] = all(c['pass'] for c in res['cells'].values())
    old = json.load(open(OUT))
    old['proj'] = res
    json.dump(old, open(OUT, 'w'), indent=1)
    print('pass', res['pass'], 'p', res['p'])
    print(json.dumps({k: (c['byGroup'], c['coef']) for k, c in res['cells'].items() if k.startswith('end')}))


if __name__ == '__main__':
    main()
