"""NFL questionable players by their last practice (Nov 1 2026 sweep). The injury term prices a questionable non-QB
at P(plays) .75 (.5 if he missed the team's last game) whatever his week. The report also says how he practised on
the last day (full / limited / did not participate). Measured on nflverse injuries x snap counts (played = any snap),
2016-20 to fit, 2021-25 held. Writes data/sweep_nov01/nfl_practice.json."""
import csv, json, os, sys
from collections import defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
C = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
pfr = {r['gsis_id']: r['pfr_id'] for r in csv.DictReader(open(os.path.join(C, 'players.csv'))) if r['pfr_id']}

def prac(s):
    s = (s or '').lower()
    return 'full' if s.startswith('full') else 'limited' if s.startswith('limited') else 'dnp' if s.startswith('did not') else 'none'

out = {}
cnt = defaultdict(lambda: [0, 0])
for y in range(2016, 2026):
    snaps = defaultdict(set); weeks = defaultdict(set)
    for r in csv.DictReader(open(os.path.join(C, f'snap_counts_{y}.csv'))):
        if int(r['offense_snaps'] or 0) + int(r['defense_snaps'] or 0) + int(r['st_snaps'] or 0) > 0:
            snaps[(int(r['week']), r['pfr_player_id'])] = True
        weeks[r['team']].add(int(r['week']))
    inj = list(csv.DictReader(open(os.path.join(C, f'injuries_{y}.csv'))))
    listed = defaultdict(dict)
    for r in inj:
        listed[int(r['week'])][r['gsis_id']] = r['report_status']
    for r in inj:
        if r['report_status'] != 'Questionable' or r['position'] == 'QB' or r.get('game_type', 'REG') != 'REG':
            continue
        p = pfr.get(r['gsis_id']); w = int(r['week'])
        if not p:
            continue
        # missed the team's last game: no snaps the week before (team played) -- rough 'recent' flag
        prev = max([x for x in weeks.get(r['team'], ()) if x < w] or [0])
        recent = prev == 0 or bool(snaps.get((prev, p)))
        played = bool(snaps.get((w, p)))
        era = 'tune' if y <= 2020 else 'held'
        for k in ((era, prac(r['practice_status']), recent), (era, 'all', recent)):
            cnt[k][0] += played; cnt[k][1] += 1
for k in sorted(cnt, key=str):
    a, n = cnt[k]
    out['|'.join(map(str, k))] = {'n': n, 'played': round(a / n, 3)}
    print(k, n, round(a / n, 3))
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nfl_practice.json'), 'w'), indent=1)

# player-level held-out check: Brier of played on 2021-25 questionable non-QBs, practice table (fit 2016-20) vs flat
import math
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H
import numpy as np
a, b, cl = [], [], []
for y in range(2021, 2026):
    snaps = {}; weeks = defaultdict(set)
    for r in csv.DictReader(open(os.path.join(C, f'snap_counts_{y}.csv'))):
        if int(r['offense_snaps'] or 0) + int(r['defense_snaps'] or 0) + int(r['st_snaps'] or 0) > 0:
            snaps[(int(r['week']), r['pfr_player_id'])] = True
        weeks[r['team']].add(int(r['week']))
    for r in csv.DictReader(open(os.path.join(C, f'injuries_{y}.csv'))):
        if r['report_status'] != 'Questionable' or r['position'] == 'QB' or r.get('game_type', 'REG') != 'REG':
            continue
        p = pfr.get(r['gsis_id']); w = int(r['week'])
        if not p:
            continue
        prev = max([x for x in weeks.get(r['team'], ()) if x < w] or [0])
        recent = prev == 0 or bool(snaps.get((prev, p)))
        pl = float(bool(snaps.get((w, p))))
        k = f"tune|{prac(r['practice_status'])}|{recent}"
        q = out[k]['played'] if k in out and out[k]['n'] >= 100 else (0.75 if recent else 0.5)
        a.append((pl - q) ** 2); b.append((pl - (0.75 if recent else 0.5)) ** 2); cl.append(f'{y}-{w}')
r = H.paired(np.array(a), np.array(b), cluster=np.array(cl))
out['held_brier'] = {'n': len(a), 'table': round(float(np.mean(a)), 4), 'flat': round(float(np.mean(b)), 4), 't': round(r['t'], 2)}
print(out['held_brier'])
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nfl_practice.json'), 'w'), indent=1)
