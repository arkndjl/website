# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""xMV snapshot rows for the S2 test, GAR on the fringe line the live xMV fit was trained on.

    python3 scripts/research/leads_nov14/s2_snaps.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_players as SP
import soccer_mv as MV

OUT = os.environ.get('LEADS_OUT', '/home/user/scratch-soccer')
F = json.load(open(SP.FIT))
F['repl'] = dict(F['replFringe'])
del F['replFringe']
SP.FIT = os.path.join(OUT, 'war_fit_fringe.json')
json.dump(F, open(SP.FIT, 'w'))
MV.SNAP = os.path.join(OUT, 'mv_snaps_fringe.json.gz')
MV.snaps()
