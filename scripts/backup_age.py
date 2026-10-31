"""Backup watch age term (Noah, Oct 31 2026): rank each backup by xGap, his gap over the starter projected over the
next two seasons from today's gap and the age gap (starter's age - his; on the college boards the class gap, Fr 1 ..
Sr 4), with the terms scripts/backup_age_fit.py fit on past seasons (data/backup_age.json). A missing age adds
nothing. Used by scripts/backup_watch.py and scripts/soccer_players.py; scripts/backup_watch_cfb.mjs has the same
few lines."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLS = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4, 'Gr': 5}


def cls_num(c):
    """eligibility year from a class tag (a redshirt keeps his eligibility year: RS-Sr is in his last season)"""
    return CLS.get(re.sub(r'^RS-', '', c or '')) if c else None


def gap_of(sport, r):
    if sport in ('cfb', 'cbb'):
        b, s = cls_num(r.get('cls')), cls_num(r['starter'].get('cls'))
    else:
        b, s = r.get('age'), r['starter'].get('age')
    return 0.0 if b is None or s is None else float(s - b)


def apply(sport, rows):
    """sets r['xgap'] and orders the rows by it (ties: the gap today)"""
    try:
        T = json.load(open(os.path.join(ROOT, 'data', 'backup_age.json')))['sports'][sport]
    except (OSError, KeyError, ValueError):
        return rows
    nd = 1 if sport in ('cfb', 'cbb') else 2 if sport in ('nba',) else 3
    for r in rows:
        r['xgap'] = round(T['a'] + T['b'] * r['gap'] + T['c'] * gap_of(sport, r), nd)
    rows.sort(key=lambda r: (-r['xgap'], -r['gap']))
    return rows
