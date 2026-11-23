# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL award races (Hart, Norris, Vezina, Calder): candidate pools and features for scripts/awards_research.py and
scripts/awards.py.

History: Hockey-Reference award voting and standings (scripts/.cache/awards/nhl_*_<season>.html), joined by name
(scripts/names.py) to the board's WAR files (static/data/nhl-war/<season>.json)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM
from awards_nba import fetch, table, f, ROOT

WAR = os.path.join(ROOT, 'static', 'data', 'nhl-war')
FIRST, LAST = 2010, 2026
HR_TM = {'VEG': 'VGK', 'PHX': 'UTA', 'ARI': 'UTA', 'ATL': 'WPG'}
AWARDS = {'hart': 'hart_stats', 'norris': 'norris_stats', 'vezina': 'vezina_stats', 'calder': 'calder_stats'}

HART_COLS = ['war', 'pts', 'g', 'tpct', 'gfrac', 'goalie', 'prev_hart']
NORRIS_COLS = ['war', 'pts', 'toipg', 'tpct', 'gd', 'prev_norris']
VEZINA_COLS = ['gsax', 'war', 'gp', 'tpct', 'prev_vezina']
CALDER_COLS = ['war', 'pts', 'g', 'gfrac', 'goalie', 'tpct']
# winners before the first modelled season (prior-award counts), Hockey-Reference ids -> NHL names
PRE = {'hart': ['Alex Ovechkin', 'Alex Ovechkin', 'Sidney Crosby', 'Joe Thornton', 'Martin St. Louis'],
       'norris': ['Zdeno Chara', 'Nicklas Lidstrom', 'Nicklas Lidstrom', 'Nicklas Lidstrom', 'Nicklas Lidstrom'],
       'vezina': ['Tim Thomas', 'Martin Brodeur', 'Martin Brodeur', 'Miikka Kiprusoff', 'Martin Brodeur']}


def war(season):
    p = os.path.join(WAR, f'{season}.json')
    return json.load(open(p))['players'] if os.path.exists(p) else []


def votes(season):
    h = fetch(f'nhl_awards_{season}.html', f'https://www.hockey-reference.com/awards/voting-{season}.html')
    out = {}
    for aw, tid in AWARDS.items():
        rows = [(r.get('player', ''), r.get('_tm', ''), f(r.get('votes'))) for r in table(h, tid) if r.get('player')]
        out[aw] = sorted([r for r in rows if r[2] > 0], key=lambda t: -t[2])
    return out


def standings(season):
    h = fetch(f'nhl_season_{season}.html', f'https://www.hockey-reference.com/leagues/NHL_{season}.html')
    out = {}
    for tid in ('standings_EAS', 'standings_WES', 'standings'):            # 2020-21: one divisional table
        for r in table(h, tid):
            t = r.get('_tm')
            if t and r.get('points_pct'): out[HR_TM.get(t, t)] = f(r['points_pct'])
    return out


def seasons_data():
    races = {a: [] for a in AWARDS}
    prev = {a: {} for a in PRE}
    for a, ns in PRE.items():
        for n in ns: prev[a][NM.key(n)] = prev[a].get(NM.key(n), 0) + 1
    hist = {}                                                # name key -> list of past gp (rookie test)
    for s in range(FIRST - 1, FIRST):
        for r in war(s): hist.setdefault(NM.key(r['n']), []).append(r.get('gp') or 0)
    for s in range(FIRST, LAST + 1):
        W, st, v = war(s), standings(s), votes(s)
        ng = max((r.get('gp') or 0) for r in W) or 82
        rows = []
        for r in W:
            k = NM.key(r['n'])
            past = hist.get(k, [])
            rookie = (not any(g > 25 for g in past)) and sum(g > 6 for g in past[-2:]) < 2 and (r.get('age') or 30) < 26
            gp = r.get('gp') or 0
            rows.append({'id': r['id'], 'n': r['n'], 'tm': r['tm'], 'pos': r['pos'], 'grp': r['grp'], 'gp': gp,
                         'toi': r.get('toi') or 0, 'toipg': (r.get('toi') or 0) / max(gp, 1),
                         'war': r.get('war') or 0, 'gd': r.get('gd') or 0, 'pts': r.get('pts') or 0,
                         'g': r.get('g') or 0, 'gsax': r.get('gsax') or 0, 'goalie': 1.0 if r['grp'] == 'G' else 0.0,
                         'tpct': st.get(r['tm'].split('/')[-1], .5), 'gfrac': gp / ng,
                         'prev_hart': prev['hart'].get(k, 0), 'prev_norris': prev['norris'].get(k, 0),
                         'prev_vezina': prev['vezina'].get(k, 0), 'rookie': rookie and s > FIRST + 1})
        pools = {'hart': [r for r in rows if r['gp'] >= 30],
                 'norris': [r for r in rows if r['grp'] == 'D' and r['gp'] >= 30],
                 'vezina': [r for r in rows if r['grp'] == 'G' and r['gp'] >= 20],
                 'calder': [r for r in rows if r['rookie'] and r['gp'] >= 20]}
        for aw, pool in pools.items():
            if aw == 'calder' and s <= FIRST + 1: continue
            m = NM.Matcher(pool, name='n', team=lambda r: r['tm'].split('/')[-1], pos=None, sport='hockey')
            order, miss = [], []
            for n, t, _ in v[aw]:
                row, how = m.find(n, team=HR_TM.get(t, t))
                if row is None: row, how = m.find(n)
                if row is None: miss.append(n); continue
                i = pool.index(row)
                if i not in order: order.append(i)
            if any(n in miss for n, _, _ in v[aw][:3]): print('nhl', s, aw, 'top-3 vote-getter outside pool', miss[:3])
            races[aw].append((s, pool, order))
        for aw in PRE:
            if v[aw]:
                k = NM.key(v[aw][0][0]); prev[aw][k] = prev[aw].get(k, 0) + 1
        for r in W: hist.setdefault(NM.key(r['n']), []).append(r.get('gp') or 0)
    return races
