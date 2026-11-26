#!/usr/bin/env python3
"""pXPM round 3 record: the board form as the input of the roster prior / game model and of FV (prereg.md
"pXPM round 3"). Reads pxpm3.json and pxpm3b_*.json; the FV arm numbers are the cbb_fit.py / fv_dist_fit.py --cbb
runs with cbb_xpm.CORE True (box) and False (board). Writes data/cbb_xpm_research.json 'pxpm3'."""
import json, os
H = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(H, '..', '..', '..', 'data', 'cbb_xpm_research.json')
a = json.load(open(os.path.join(H, 'pxpm3.json')))
rt = {k: json.load(open(os.path.join(H, f'pxpm3b_{k}.json'))) for k in ('core', 'full')}
best = {k: min(((v['tune'], n) for n, v in rt[k].items()), key=lambda x: x[0])[1] for k in rt}
fv = {'nestedR2': [.1073, .1138], 'top300Corr2010_16': [.420, .429], 'top300Corr2017_19': [.386, .377], 'boardsBetter2017_19': 0,
      'top50Fv2017_19': [39.17, 39.03], 'draftAuc': [.962, .963], 'rps': [.07888, .07910], 'cover80': [.910, .908]}
d = json.load(open(R))
d['pxpm3'] = {'roster': a['roster'], 'game': {k: v for k, v in a['game'].items() if k != 'bySeason'},
              'gameSeasonsWorse': sum(1 for v in a['game']['bySeason'].values() if v > 0), 'gameSeasons': len(a['game']['bySeason']),
              'retune': {k: {'at': best[k], **rt[k][best[k]]} for k in rt}, 'fv': fv,
              'read': 'box form stays in FV, the roster prior and the game model'}
json.dump(d, open(R, 'w'), indent=1); print(json.dumps(d['pxpm3'])[:700])
