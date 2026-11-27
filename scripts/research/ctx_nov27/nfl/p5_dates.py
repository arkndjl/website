#!/usr/bin/env python3
"""P5: the dates each NFL fit file carries (the checkout has no history, so the files' own stamps and keys are read).

    python3 scripts/research/ctx_nov27/nfl/p5_dates.py
"""
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
FILES = ['data/nfl_xv.json', 'data/nfl_war_fit.json', 'data/nfl_war_pos.json', 'data/nfl_war_calib.json', 'data/nfl_war_def.json',
         'data/nfl_rate_fit.json', 'data/nfl_war_proj_fit.json', 'data/pctl_fit_nfl.json', 'data/nfl_roster_fit.json',
         'data/nfl_games_fit.json', 'data/xaav_fit.json', 'data/nfl_rookie_prior.json', 'data/nfl_breakout_fit.json',
         'data/nfl_badge_backtest.json', 'data/awards_fit.json', 'data/refit_state.json', 'scripts/data/refit_state.json']

for f in FILES:
    try:
        s = open(os.path.join(ROOT, f)).read()
    except OSError:
        print(f, 'missing')
        continue
    d = json.loads(s)
    top = {k: v for k, v in d.items() if isinstance(v, str) and re.match(r'20\d\d-\d\d', v)} if isinstance(d, dict) else {}
    stamps = sorted(set(re.findall(r'"([a-zA-Z_]*)": ?"(20\d\d-\d\d-\d\d)', s)))[:6]
    print(f, top, stamps, list(d.keys())[:12] if isinstance(d, dict) else '')
