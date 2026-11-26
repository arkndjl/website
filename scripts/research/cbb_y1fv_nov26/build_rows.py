#!/usr/bin/env python3
"""Season-end board grades of every freshman season (scripts/cbb_draftday.build: the returner model on next preseason's
row, the player's college class held out for 2009-16 seasons, then the June draft boards as the live board reads them in
draft week), each score at its mean outcome -> fr_rows.json."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_draftday as DD

ex, tr, fwd, ft, fin, y, fit = DD.build()
e_tr = np.array([r['s'] for r in tr])          # the draft-week score: the model's E[FV] and the June boards (the live board's stage)
M = DD.calmap(e_tr, y)                        # mean outcome at each season-end score (2009-16 season-end rows)
out = []
for r in ex:
    if r['yr'] != 'Fr': continue
    out.append({'pid': r['pid'], 'name': r['name'], 'team': r['team'], 'year': r['year'], 'e': round(r['f']['e'], 4),
                'fv': round(float(DD.apply_map(M, np.array([r['s']]))[0]), 2), 'y': r['y'], 'last': r['last']})
json.dump({'map': [list(map(float, M[0])), list(map(float, M[1])), M[2]], 'rows': out}, open(os.path.join(HERE, 'fr_rows.json'), 'w'), separators=(',', ':'))
print(len(out), 'freshman seasons', np.percentile([o['fv'] for o in out], [50, 90, 99, 99.9]))
