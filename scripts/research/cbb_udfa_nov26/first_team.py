"""Which NBA teams give undrafted rookies their first NBA games? (Nov 26 2026)
Undrafted rookie = first season in the NBA files (static/data/nba-xpm, season file y+1 after draft y), age <= 24,
never in scripts/nba_draft.json. His team = the team of his row (TOT: skipped)."""
import json, glob, os, collections, math
R = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(R, '..', '..', '..')
D = json.load(open(os.path.join(ROOT, 'scripts', 'nba_draft.json')))
drafted = {b for rows in D.values() for _, b, _, _ in rows if b}
NB = {}
for f in sorted(glob.glob(os.path.join(ROOT, 'static', 'data', 'nba-xpm', '*.json'))):
    NB[int(os.path.basename(f)[:4])] = json.load(open(f))['players']
seen = set(); first = collections.defaultdict(list)
for y in sorted(NB):
    for p in NB[y]:
        if p['id'] in seen: continue
        seen.add(p['id'])
        if y == min(NB): continue
        if p['id'] in drafted or (p.get('age') or 99) > 24: continue
        first[y - 1].append(p)
teams = sorted({p['tm'] for ps in NB.values() for p in ps if p['tm'] and p['tm'] not in ('TOT', '2TM', '3TM')})
print('teams', len(teams), teams)
print({y: len(v) for y, v in first.items()})
dteams = sorted({t for rows in D.values() for *_, t in rows})
print('draft teams', dteams)
json.dump({str(y): [[p['id'], p['n'], p['tm'], p.get('mp')] for p in v] for y, v in first.items()}, open(os.path.join(R, 'udfa_first.json'), 'w'))
