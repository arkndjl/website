#!/usr/bin/env python3
"""Soccer GAR and SVAR (goals over replacement) with the team adjustment to actual goal difference, big five 2014-15 ..
2025-26. Exposure = matches of minutes (min / 90) per club stint (static/data/soccer-war rows); result = league goal
difference from ESPN's game log (scripts/soccer_games_hist.json.gz, Understat is down), names via data/soccer_logos.json.
Teams centred within league-season (as soccer_players.py's fit), so the league-strength term stays in every value."""
import gzip, json, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..', '..'); sys.path.insert(0, HERE)
import core

ESPN = json.load(open(os.path.join(ROOT, 'data', 'soccer_logos.json')))['espn']
G = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))
BIG5 = {'eng.1', 'esp.1', 'ita.1', 'ger.1', 'fra.1'}


def results(S):
    lo, hi = f'{S - 1}-07-20', f'{S}-07-19'
    gd, gp = defaultdict(float), defaultdict(int)
    for g in G:
        if g['lg'] in BIG5 and lo <= g['day'] <= hi and g.get('st') == 'FT' and g.get('hs') is not None:
            for t, d in ((g['h'], g['hs'] - g['as']), (g['a'], g['as'] - g['hs'])):
                gd[(g['lg'], t)] += d; gp[(g['lg'], t)] += 1
    return gd, gp


def season(S, key):
    w = json.load(open(os.path.join(ROOT, 'static', 'data', 'soccer-war', f'{S}.json')))
    gd, gp = results(S)
    parts, num, den, grp, team, cg, miss = [], defaultdict(float), defaultdict(float), {}, {}, {}, set()
    for p in w['players']:
        if not p.get('min') or p.get(key) is None: continue
        tid = ESPN.get(p['team'])
        if not tid or (p['lg'], tid) not in gp: miss.add(p['team']); continue
        t = f"{p['lg']}|{tid}"; e = p['min'] / 90
        parts.append((p['p'], t, e)); num[p['p']] += p[key]; den[p['p']] += e; grp[p['p']] = p['pos']
        team[t] = (gd[(p['lg'], tid)], gp[(p['lg'], tid)]); cg[t] = p['lg']
    if miss: print(S, 'unmatched', sorted(miss)[:10], flush=True)
    return {'parts': parts, 'val': {k: num[k] / den[k] for k in num if den[k]}, 'team': team, 'grp': grp, 'cg': cg}


out = {}
for key, nm in (('gar', 'GAR'), ('svar', 'SVAR')):
    D = {S: season(S, key) for S in range(2015, 2027)}
    for S in D: print(S, key, len(D[S]['team']), 'teams', sum(e for _, _, e in D[S]['parts']) / max(1, sum(g for _, g in D[S]['team'].values())), 'player-matches a team-match', flush=True)
    out[nm] = core.run(D, list(range(2015, 2026)), 10, 10, nm)
json.dump(out, open(os.path.join(HERE, 'soccer.json'), 'w'), indent=1)
