# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 12: team-specific preseason sigma from incoming transfers (pre-registered in prereg.md).
sigma'^2 = sigma^2 * max(.25, 1 + c * zbar), zbar = mean of the two teams' z(offIn); weeks 1-4, FBS v FBS."""
import gzip, json, math, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
W = json.load(gzip.open(os.path.join(ROOT, 'scripts/data/games_wf/cfb.json.gz')))
F = json.load(open(os.path.join(ROOT, 'scripts/data/cfb_roster_feats.json')))['feats']
T = {str(t['tid']): t for t in json.load(open(os.path.join(ROOT, 'data/cfb_teams.json')))['teams']}
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names
tk = {}
for tid, t in T.items():
    for n in (t.get('team'), t.get('full')):
        if n: tk[names.team_key(n) if hasattr(names, 'team_key') else n.lower()] = tid
key = lambda n: tk.get(names.team_key(n) if hasattr(names, 'team_key') else n.lower())
Z = {}
for S, f in F.items():
    v = {t: x['offIn'] for t, x in f.items() if x.get('offIn') is not None}
    m, sd = np.mean(list(v.values())), np.std(list(v.values())) or 1
    Z[int(S)] = {t: (x - m) / sd for t, x in v.items()}
rows = []
for g in W:
    if g.get('fcs') or not (1 <= (g.get('wk') or 99) <= 4) or g.get('res') is None or g.get('m') is None or not g.get('sigma'): continue
    S = g['S']
    if S not in Z or S < 2022: continue
    if S == 2026 and g['wk'] > 10: continue
    zs = [Z[S].get(key(g['home']) or '', 0.0), Z[S].get(key(g['away']) or '', 0.0)]
    hit = sum(1 for n in (g['home'], g['away']) if (key(n) or '') in Z[S])
    if g['res'] == 0: continue
    rows.append((S, g['wk'], g['m'], g['sigma'], 1 if g['res'] > 0 else 0, float(np.mean(zs)), hit))
R = np.array(rows, float)
phi = lambda x: 0.5 * (1 + np.vectorize(math.erf)(x / math.sqrt(2)))
def ll(r, c):
    s = r[:, 3] * np.sqrt(np.maximum(.25, 1 + c * r[:, 5]))
    p = np.clip(phi(r[:, 2] / s), 1e-6, 1 - 1e-6)
    return -(r[:, 4] * np.log(p) + (1 - r[:, 4]) * np.log(1 - p))
tune, held = R[R[:, 0] <= 2023], R[R[:, 0] >= 2024]
grid = [round(-.30 + .05 * i, 2) for i in range(13)]
tl = {c: float(ll(tune, c).mean()) for c in grid}
c = min(tl, key=tl.get)
def clus(r, c):
    d = ll(r, c) - ll(r, 0)
    ks = sorted({(a, b) for a, b in r[:, :2]}); means = np.array([d[(r[:, 0] == a) & (r[:, 1] == b)].sum() for a, b in ks])
    n = len(ks); t = means.mean() / (means.std(ddof=1) / math.sqrt(n)) if means.std() > 0 else 0.0
    return float(d.mean()), float(t), n
out = {'n_tune': len(tune), 'n_held': len(held), 'teams_matched': float(R[:, 6].mean() / 2), 'tune_ll_by_c': tl, 'c': c,
       'tune': clus(tune, c), 'held': clus(held, c), 'held_by_season': {int(s): clus(held[held[:, 0] == s], c)[0] for s in sorted(set(held[:, 0]))},
       'base_ll_held': float(ll(held, 0).mean())}
print(json.dumps(out, indent=1))
