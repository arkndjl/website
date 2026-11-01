#!/usr/bin/env python3
"""Trades in the NHL game model's lineup value (Nov 1 2026; Noah: "make all of our pro sports models account for
trades").

    python3 scripts/nhl_trades_research.py      # numpy; writes data/nhl_trades_research.json

rv prices the skaters each club dressed in its last game. After a trade that lineup still has the player who left
and lacks the one who came in, for one game. The fix (nhl_games.moved_lineup): skaters gone to another club out,
acquired skaters in, the lowest-valued scratched or a replacement call-up so the counts hold. Backtest on the frozen
lineups (nhl_games.hist_moves), the shipped inputs and settings (data/nhl_games_fit.json), walk-forward log loss on
win, t clustered by day, every game 2017-23 / 2024-26 and the lined seasons 2021-23 / 2024-26, and on the games the
fix moves.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H      # noqa: E402
import nhl_games as G    # noqa: E402

OUT = os.path.join(G.ROOT, 'data', 'nhl_trades_research.json')


def main():
    fit = json.load(open(G.FIT))
    P, feats = fit['params'], fit['feats']
    hist = G.load_hist()
    _, r0, _ = G.walk(hist, P)
    _, r1, _ = G.walk(hist, P, moves=G.hist_moves(hist))
    S, y, m, tot, pc, tc, day = G.arrays(r0)
    rv0 = np.array([f['rv'] for _, f in r0]); rv1 = np.array([f['rv'] for _, f in r1])
    moved = np.abs(rv1 - rv0) > 1e-9
    res = {'feats': feats, 'gamesMoved': {int(s): int((moved & (S == s)).sum()) for s in sorted(set(S.tolist()))},
           'rvShift': {'mean|d|': round(float(np.abs(rv1 - rv0)[moved].mean()), 4) if moved.any() else 0.0,
                       'sdRv': round(float(rv0.std()), 4)}}
    print(res, flush=True)
    for lab, lined, first, tune in (('every', False, G.SCORE_FROM + 1, (G.SCORE_FROM + 1, G.TUNE[1])),
                                    ('lined', True, G.FIRST_TEST, G.TUNE)):
        ok = ~np.isnan(pc) if lined else np.ones(len(y), bool)
        fs = feats if lined else [f for f in feats if f != 'mkt']
        p0 = G.walk_logit(G.design(r0, fs), y, S, first, ok)
        p1 = G.walk_logit(G.design(r1, fs), y, S, first, ok)
        l0, l1 = H.logloss(p0, y), H.logloss(p1, y)
        out = {}
        for blk, k in (('tune', (S >= tune[0]) & (S <= tune[1]) & ok), ('held', (S >= G.HOLD_FROM) & ok)):
            for sub, kk in (('all', k), ('moved', k & moved)):
                kk = kk & ~np.isnan(l0) & ~np.isnan(l1)
                if kk.sum() < 5:
                    continue
                r = H.paired(l1[kk], l0[kk], day[kk])
                out[f'{blk}/{sub}'] = {'dLL_x1000': round(r['d'] * 1000, 3), 't': round(r['t'], 2), 'n': int(kk.sum())}
        res[lab] = out
        print(lab, out, flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
