# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""PREREG.md M3 secondary: the same placebo recipes as a column of the real NBA design (the ledger's drop-one path)."""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import nba_games as N  # noqa: E402
import nba_games_fit as NF  # noqa: E402
import placebo as PB  # noqa: E402

F = json.load(open(os.path.join(ROOT, 'data', 'nba_games_fit.json')))
games, names = N.load_hist()
inj = NF.load_inj()
P, prm, feats = F['P'], dict(F['params']), list(F['feats'])
D, X, TX, y, ty, S, line, tline = NF.design(games, names, P, prm, inj, feats)
keep = np.asarray(S) <= 2026
Xm = NF.mat(X, feats)
full = NF.wf(Xm, y, S)
ok = ~np.isnan(full) & keep
rows = [dict(S=int(g['S']), day=g['tip'][:10], h=g['h'], a=g['a'], miss=(float(y[i] - full[i]) if ok[i] else 0.0)) for i, (g, _, _) in enumerate(D)]
order = np.arange(len(rows))
src = PB.sources(rows)
day = np.array([r['day'] for r in rows]); team = np.array([f"{r['h']}|{r['S']}" for r in rows])
tune, held = H.season_masks(S, (N.SCORE_FROM, N.HOLD_FROM - 1), N.HOLD_FROM, ok)
slate = [np.flatnonzero(day == k) for k in np.unique(day)]
hts = {}
for i, r in enumerate(rows):
    hts.setdefault(r['S'], {}).setdefault(r['h'], []).append(i)
hts = {s: {k: np.array(v) for k, v in t.items()} for s, t in hts.items()}
rng = np.random.default_rng(PB.SEED + 1)
base = H.ae(full, y)
hs = sorted(set(np.asarray(S)[held].tolist()))
res = []
for kind in ('P1', 'P2'):
    for _ in range(100):
        z = PB.placebo(kind, src[:, int(rng.integers(3))], rows, slate, hts, rng)
        d = H.ae(NF.wf(np.column_stack([Xm, z]), y, S), y) - base
        a = H.paired(d[tune], 0 * d[tune], [day[tune], team[tune]]); b = H.paired(d[held], 0 * d[held], [day[held], team[held]])
        maj = sum(d[(np.asarray(S) == s) & held].mean() < 0 for s in hs) > len(hs) / 2
        res.append([kind, a['t'], b['t'], a['d'], bool(maj)])
        if len(res) % 20 == 0:
            print(len(res), flush=True)
th = np.array([r[2] for r in res]); tt = np.array([r[1] for r in res]); dt = np.array([r[3] for r in res]); mj = np.array([r[4] for r in res])
out = {'n': len(res), 'G_old': int(((tt <= -1.5) & (th <= -2) & mj).sum()), 'G_brief': int(((th <= -2) & (dt < 0) & mj).sum()),
       'heldT2': int((th <= -2).sum()), 'heldT': [round(float(th.mean()), 3), round(float(th.std(ddof=1)), 3)], 'detail': res}
json.dump(out, open(os.path.join(PB.OUT, 'placebo_nba_design.json'), 'w'))
print({k: v for k, v in out.items() if k != 'detail'})
