# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB class-score panel: one row per D-I program and class, each commit's history points (the live E[share] points by
consensus rank), season ratings (the recruit history's program net rating z), win % from the game history.
Writes scripts/.cache/classscore/cbb_panel.json."""
import gzip, json, os, sys
from collections import Counter, defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as N  # noqa: E402
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'classscore')


def points_map():
    d = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json')))
    rows = [x for c in d['classes'] for x in c['list'] if x.get('rk')]
    lr = np.log([x['rk'] for x in rows]); e = np.array([x['ets'] for x in rows])
    edges = np.unique(np.quantile(lr, np.linspace(0, 1, 26)))
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (lr >= a) & (lr <= b)
        if m.sum(): xs.append(float(lr[m].mean())); ys.append(float(e[m].mean()))
    top = [(float(np.log(k)), float(np.mean([x['ets'] for x in rows if x['rk'] == k]))) for k in (1, 2, 3, 4, 5) if any(x['rk'] == k for x in rows)]
    pts = sorted(top + [(x, y) for x, y in zip(xs, ys) if x > np.log(5.5)])
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    f = lambda rk: float(np.interp(np.log(rk), xs, ys))
    a, b = [], []
    for c in d['classes']:
        by = defaultdict(list)
        for x in c['list']:
            if x.get('team') and x.get('rk'): by[x['team']].append(x)
        for t, v in by.items(): a.append(sum(x['ets'] for x in v)); b.append(sum(f(x['rk']) for x in v))
    chk = {'classes': len(a), 'r': round(float(np.corrcoef(a, b)[0, 1]), 4), 'slope': round(float(np.polyfit(b, a, 1)[0]), 3),
           'player_r': round(float(np.corrcoef([x['ets'] for x in rows], [f(x['rk']) for x in rows])[0, 1]), 4)}
    return f, chk


def main():
    H = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')))
    f, chk = points_map(); print('map check', chk)
    pairs = defaultdict(Counter)
    for r in H['recruits']:
        if r.get('team') and r.get('college'): pairs[r['team']][r['college']['team']] += 1
    smap = {s: c.most_common(1)[0][0] for s, c in pairs.items() if c.most_common(1)[0][1] >= 3}
    classes, miss = defaultdict(lambda: defaultdict(list)), Counter()
    for r in H['recruits']:
        if not r.get('rk'): continue
        t = smap.get(r.get('team')) or ((r.get('college') or {}).get('team') if not r.get('team') or r.get('team') not in smap else None)
        if not t: miss[r.get('team')] += 1; continue
        classes[r['cls']][t].append([r['name'], r['rk'], round(f(r['rk']), 3)])
    print('unmapped commits', sum(miss.values()), miss.most_common(8))
    # win % by season from the game history (ESPN names -> rating names by the shared team key)
    G = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_games_hist.json.gz')))
    tk = {}
    for y, v in H['teams'].items():
        for t in v: tk.setdefault(N.team_key(t), t)
    wp = defaultdict(lambda: [0, 0]); un = Counter()
    for g in G:
        if g.get('hs') is None or g.get('as') is None: continue
        for nm, won in ((g['hn'], g['hs'] > g['as']), (g['an'], g['as'] > g['hs'])):
            t = tk.get(N.team_key(nm))
            if not t: un[nm] += 1; continue
            wp[(g['season'], t)][0] += won; wp[(g['season'], t)][1] += 1
    seasons = {}
    for y, v in H['teams'].items():
        seasons[y] = {t: {'z': z, 'wp': round(wp[(int(y), t)][0] / wp[(int(y), t)][1], 4) if wp[(int(y), t)][1] >= 15 else None} for t, z in v.items()}
    print('win % coverage', {y: sum(1 for t in v.values() if t['wp'] is not None) for y, v in seasons.items() if int(y) >= 2014}, 'of', len(seasons['2020']))
    P = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cbb_team_prior.json')))
    prior = {y: {t: {'ret': v.get('ret'), 'tr': v.get('tr'), 'rret': v.get('rret')} for t, v in d.items()} for y, d in P.items()}
    json.dump({'check': chk, 'seasons': seasons, 'classes': {y: dict(v) for y, v in classes.items()}, 'prior': prior}, open(os.path.join(CACHE, 'cbb_panel.json'), 'w'))
    for y in (2015, 2022): print(y, len(classes[y]), sorted(((round(sum(p[2] for p in v), 1), t, len(v)) for t, v in classes[y].items()), reverse=True)[:6])


if __name__ == '__main__': main()
