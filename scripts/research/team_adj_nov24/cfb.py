#!/usr/bin/env python3
"""CFB two-way WAR driver (cWAR a full share = CWAR_V[pos] + SAV_W[pos] x z, points of margin a game; z = PFN impact
score on the season's starter pool, as scripts/cfb_av_backtest.mjs) with the team adjustment to opponent-adjusted
margin (SRS, ESPN FBS results). One shift a team (SRS has no offense / defense split). Exposure = games played / team
games, the team's players by playing time filling each position's starter slots (as the backtest and the board). Rows: node scripts/research/team_adj_nov24/cfb_export.mjs. Gate on the pairs with all ten positions graded
(2024-25, 2025-26); 2019-25 (seven positions before 2024) reported too."""
import json, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..', '..'); sys.path.insert(0, HERE)
import core

STARTERS = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'EDGE': 2, 'DL': 2, 'LB': 2, 'CB': 3, 'S': 2}
J = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'av', 'team_adj_cfb.json')))
D = {}
for y in range(2019, 2027):
    parts, num, den, grp, by = [], defaultdict(float), defaultdict(float), {}, defaultdict(list)
    for r in J['rows']:
        if r['season'] == y and r['sh'] > 0 and r.get('z') is not None: by[(r['tid'], r['pos'])].append(r)
    for (tid, pos), rs in by.items():          # the team's players by playing time fill the position's starter slots
        T = 0.0
        for r in sorted(rs, key=lambda r: -r['sh']):
            e = min(r['sh'], STARTERS[pos] - T)
            if e <= 0: break
            T += e; pid = r['id'] + '|' + pos; v = J['CWAR_V'][pos] + J['SAV_W'][pos] * r['z']
            parts.append((pid, tid, e)); num[pid] += v * e; den[pid] += e; grp[pid] = pos
    team = {t: (s * J['TG'][str(y)][t], J['TG'][str(y)][t]) for t, s in J['SRS'][str(y)].items()}
    D[y] = {'parts': parts, 'val': {k: num[k] / den[k] for k in num}, 'team': team, 'grp': grp}
out = {'allTen': core.run({y: D[y] for y in (2024, 2025, 2026)}, [2024, 2025], .25, .4, 'cfb 10 pos', pk=.2),
       'all': core.run(D, list(range(2019, 2026)), .25, .4, 'cfb 2019-26', pk=.2)}
out['pass'] = out['allTen']['pass']
json.dump(out, open(os.path.join(HERE, 'cfb.json'), 'w'), indent=1)
