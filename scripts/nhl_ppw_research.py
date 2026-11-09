#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Does the NHL game model's xG rating overweight the power play? (Noah, Nov 2 2026; lead from scripts/unit_badges.py:
team power-play ratings fit a negative slope on the model's residual in 2024-26 after a positive one in 2017-23.)
The xG rating counts every expected goal alike; here power-play xG is weighted ppw (penalty kills follow, being the
other side's power play). Each ppw reruns the walk-forward with the shipped params and inputs; win log loss and
total MAE are compared with ppw = 1 on 2017-23 (pick) and 2024-26 (held), t clustered by day. Ship rule: the tune pick
beats 1 at t <= -1.5 on tune and is not worse held (held d < 0, t <= -1.0 to change).
    python3 scripts/nhl_ppw_research.py -> data/nhl_ppw_research.json"""
import datetime
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import nhl_games as N  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'data', 'nhl_ppw_research.json')
GRID = [1.0, 0.75, 0.5, 0.25, 0.0]


def main():
    fit = json.load(open(N.FIT))
    hist = N.load_hist()
    mv = N.hist_moves(hist)
    res = {}
    for w in GRID:
        P = dict(fit['params'], ppw=w)
        _, rows, _ = N.walk(hist, P, moves=mv)
        S, y, mg, tot, pc, tc, day = N.arrays(rows)
        p = N.walk_logit(N.design(rows, fit['feats']), y, S, N.SCORE_FROM + 1)
        That = N.walk_ols(N.design(rows, N.TFEATS), tot, S, N.FIRST_TEST, ~np.isnan(tc))
        res[w] = dict(S=S, day=day, ll=H.logloss(p, y), ae=np.abs(That - tot), lined=~np.isnan(pc))
        print('ppw', w, 'done', flush=True)
    b = res[1.0]
    tune = (b['S'] >= N.SCORE_FROM + 1) & (b['S'] < N.HOLD_FROM)
    held = b['S'] >= N.HOLD_FROM
    out = {}
    for w in GRID[1:]:
        r = res[w]
        o = {}
        for nm, m in (('tune', tune), ('held', held), ('held_lined', held & b['lined'])):
            ok = m & ~np.isnan(r['ll']) & ~np.isnan(b['ll'])
            a = H.paired(r['ll'][ok], b['ll'][ok], b['day'][ok])
            ok2 = m & ~np.isnan(r['ae']) & ~np.isnan(b['ae'])
            t = H.paired(r['ae'][ok2], b['ae'][ok2], b['day'][ok2])
            o[nm] = {'ll_d': round(a['d'] * 1000, 3), 'll_t': round(a['t'], 2), 'tot_mae_d': round(t['d'], 4),
                     'tot_t': round(t['t'], 2), 'n': int(ok.sum())}
        out[str(w)] = o
        print('ppw', w, o, flush=True)
    pick = min(GRID[1:], key=lambda w: out[str(w)]['tune']['ll_d'])
    o = out[str(pick)]
    ship = o['tune']['ll_t'] <= -1.5 and o['held']['ll_d'] < 0 and o['held']['ll_t'] <= -1.0
    json.dump({'asof': datetime.date.today().isoformat(), 'grid': out, 'pick': pick, 'ship': bool(ship),
               'rule': 'tune pick: ll t <= -1.5 (2017-23); held 2024-26 d < 0 and t <= -1.0'}, open(OUT, 'w'), indent=1)
    print('pick', pick, 'ship', ship)


if __name__ == '__main__':
    main()
