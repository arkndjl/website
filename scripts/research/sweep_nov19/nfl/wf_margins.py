#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The live NFL margin model's walk-forward forecasts 2015-25 (coefficients fit on the seasons before), one row a
played game, for the stack and prior tests in this folder.

    python3 wf_margins.py <out json>"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import nfl_games as N              # noqa: E402
import nfl_season_backtest as SB   # noqa: E402


def main():
    F = json.load(open(N.FIT))
    G, box, qbs = N.load(2025)
    N.index_qbs(qbs, G); N.load_qb_teams(2025)
    inj = N.injury_history(G, range(N.INJ_FIRST, 2026))
    data, _ = SB.walk(G, box, qbs, F['params'], inj, ())
    B, D, X, y, S, line, pred = SB.coefs(data)
    out = []
    for (g, x), p, yy, s, l in zip(D, pred, y, S, line):
        if p == p:
            out.append({'id': g['game_id'], 's': int(s), 'w': int(g['week']), 'gt': g['game_type'], 'h': N.team(g['home_team']),
                        'a': N.team(g['away_team']), 'pred': round(float(p), 3), 'y': float(yy), 'line': None if l != l else float(l),
                        'x': {f: round(float(x[f]), 4) for f in N.FEATS}})
    json.dump({'rows': out, 'coef': {str(s): {f: float(v) for f, v in b.items()} for s, b in B.items()}}, open(sys.argv[1], 'w'))
    print('rows', len(out))


if __name__ == '__main__':
    main()
