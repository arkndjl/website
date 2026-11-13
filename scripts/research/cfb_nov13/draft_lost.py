# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL draft value a team lost each April: sum over its draftees of ln(262/pick)/ln(262), by season and ESPN team id
(season S = the April S draft), raw and z across FBS. -> /tmp/cfb_draft_lost.json (research)"""
import csv, gzip, json, math, os, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import names as N
H = json.load(gzip.open('scripts/data/cfb_hist_md.json.gz'))
fbs = {}
for S, gs in H['games'].items():
    d = {}
    for g in gs:
        if g['homeClassification'] == 'fbs': d[str(g['homeId'])] = g['homeTeam']
        if g['awayClassification'] == 'fbs': d[str(g['awayId'])] = g['awayTeam']
    fbs[int(S)] = d
fbs[2026] = dict(fbs[2025])
EXTRA = {'ala-birmingham': 'UAB', 'boston col.': 'Boston College', 'central florida': 'UCF', 'miami (fl)': 'Miami', 'mississippi': 'Ole Miss', 'pittsburgh': 'Pittsburgh', 'southern miss': 'Southern Miss',
         'texas christian': 'TCU', 'southern methodist': 'SMU', 'brigham young': 'BYU', 'nevada-las vegas': 'UNLV', 'texas-el paso': 'UTEP', 'texas-san antonio': 'UTSA', 'louisiana st.': 'LSU', 'la-monroe': 'UL Monroe',
         'louisiana': 'Louisiana', 'la-lafayette': 'Louisiana', 'north carolina st.': 'NC State', 'middle tenn. st.': 'Middle Tennessee', 'western kentucky': 'Western Kentucky', 'massachusetts': 'Massachusetts', 'hawaii': "Hawai'i", 'san jose st.': 'San José State',
         'florida international': 'Florida International', 'southern california': 'USC', 'connecticut': 'UConn', 'appalachian st.': 'App State'}
def k(s): return N.team_key(s.replace('St.', 'State'))
out, miss = {}, collections.Counter()
picks = list(csv.DictReader(open('/tmp/draft_picks.csv')))
for S in range(2016, 2027):
    by = {k(n): t for t, n in fbs[S - 1].items()}     # the team he played for last season
    by.update({k(n): t for t, n in fbs[S].items() if k(n) not in by})
    v = collections.Counter()
    for r in picks:
        if int(r['season']) != S or not r['college']: continue
        c = r['college']; key = k(EXTRA.get(c.lower(), c))
        t = by.get(key)
        if t is None: miss[c] += 1; continue
        v[t] += math.log(262 / min(262, int(r['pick']))) / math.log(262)
    ids = list(fbs[S]); xs = [v.get(t, 0) for t in ids]; m = sum(xs) / len(xs); sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** .5 or 1
    out[S] = {t: round((v.get(t, 0) - m) / sd, 3) for t in ids}
    top = sorted(ids, key=lambda t: -v.get(t, 0))[:3]
    print(S, 'picks matched', sum(1 for r in picks if int(r['season']) == S), round(sum(v.values()), 1), [(fbs[S][t], round(v[t], 2)) for t in top])
print('unmatched (top):', miss.most_common(25))
json.dump(out, open('/tmp/cfb_draft_lost.json', 'w'))
