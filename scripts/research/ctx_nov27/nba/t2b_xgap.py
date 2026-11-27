"""T2 guard: the backup watch's xGap fit (scripts/backup_age_fit.py: two-season future gap on today's gap + age gap,
walk-forward) with the old grade (1 / .5 / .25, k 500 to -1.4) and with pXPM. Also the same pairs scored both ways:
on the OLD grade's pairs, which gap predicts the future gap better.  -> t2b_xgap.json"""
import json, os
import numpy as np
import common as C
import backup_age_fit as B
nba = {y: d for y, d in B.seasons('nba-xpm').items() if y <= C.LAST}
kw = dict(key=lambda p: p['id'], team=lambda p: p['tm'],
          grp=lambda p: {'PG': 'G', 'SG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'C'}.get(p['pos'].split('-')[0], 'F'),
          shape={'G': 2, 'F': 2, 'C': 1}, nxt={'G': ['G', 'F'], 'F': ['F', 'C', 'G'], 'C': ['C', 'F']},
          val=lambda p: p.get('xpm'), use=lambda p: p['mp'], age=lambda p, y: p.get('age'),
          k=lambda g: 500, repl=lambda y, g: B.VORX_REP, w=(1, .5, .25), mn=50)
res = {}
for lab, g in (('old grade', None), ('pXPM grade', lambda p: p.get('sxpm'))):
    f = B.fit(B.pro_pairs(nba, grade=g, **kw))
    res[lab] = {k: f[k] for k in ('n', 'held', 'mse_gap', 'mse_age', 't', 'a', 'b', 'c')}
    print(lab, res[lab])
json.dump(res, open(os.path.join(C.HERE, 't2b_xgap.json'), 'w'), indent=1)
