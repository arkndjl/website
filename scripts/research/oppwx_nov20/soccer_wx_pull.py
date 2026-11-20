# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Weather at kickoff for the walk-forward soccer matches of the big five's first and second divisions (research).
    python3 scripts/research/oppwx_nov20/soccer_wx_pull.py GEO_JSON CACHE_DIR OUT_JSON
"""
import datetime as dt, gzip, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wx_iem as WX
ROOT = os.path.join(HERE, '..', '..', '..')
geo = json.load(open(sys.argv[1])); cache = sys.argv[2]; os.makedirs(cache, exist_ok=True)
FIX = {'110': (45.478, 9.124), '174': (43.7277, 7.4156), '6997': (48.4029, -4.4617), '122': (50.9335, 6.875), '90': (43.3687, -8.4174),
       '6990': (46.317, -0.489), '238': (45.4354, 10.9686), '3266': (48.07, -0.77), '3849': (50.598, 12.711), '3958': (44.8397, 11.6077),
       '7719': (44.35, 2.566), '7707': (41.93, 8.777), '11884': (48.919, 2.343), '135': (48.1108, 11.5744), '20179': (42.5, 1.52)}
for k, v in FIX.items(): geo[k] = [k, k, v[0], v[1], 0]
st = WX.stations(['GB__ASOS', 'ES__ASOS', 'DE__ASOS', 'IT__ASOS', 'FR__ASOS'], cache)
print(len(st), 'stations', flush=True)
hist = {r['id']: r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))}
wf = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'soccer.json.gz')))
LG = {a + '.' + b for a in ('eng', 'esp', 'ger', 'ita', 'fra') for b in ('1', '2')}
need = {}
for g in wf:
    if g['lg'] not in LG or g['h'] not in geo: continue
    h = hist.get(g['id'])
    if not h or h.get('neu') or not h.get('t'): continue
    need[g['id']] = (g['h'], g['S'], h['day'], h['t'])
print(len(need), 'matches', flush=True)
near = {t: WX.nearest(st, geo[t][2], geo[t][3]) for t in {v[0] for v in need.values()}}
out = {}
H = {}
bad = set()
for i, (gid, (t, S, day, tm)) in enumerate(sorted(need.items(), key=lambda kv: (kv[1][1], kv[1][0]))):
    k0 = dt.datetime.strptime(day + ' ' + tm[:5], '%Y-%m-%d %H:%M')
    S_ = k0.year + 1 if k0.month >= 7 else k0.year
    for dist, sid in near[t]:
        if dist > 60 or (sid, S_) in bad: continue
        if (sid, S_) not in H:
            H[(sid, S_)] = WX.hours(sid, S_, cache)
            if H[(sid, S_)] is None or len(H[(sid, S_)]) < 3000:
                bad.add((sid, S_)); continue
        hh = H[(sid, S_)]
        obs = [hh.get((k0 + dt.timedelta(hours=j)).strftime('%Y-%m-%d %H')) for j in (0, 1, 2)]
        obs = [o for o in obs if o]
        if len(obs) < 2: continue
        tv = [o[0] for o in obs if o[0] is not None]; wv = [o[1] for o in obs if o[1] is not None]; gv = [o[2] for o in obs if o[2] is not None]
        if not tv or not wv: continue
        out[gid] = [round(sum(tv) / len(tv), 1), round(sum(wv) / len(wv), 1), round(max(gv), 1) if gv else None,
                    int(any(o[3] for o in obs)), int(any(o[4] for o in obs)), sid, round(dist, 1)]
        break
    if i % 2000 == 0:
        print(i, len(out), len(H), flush=True)
        json.dump(out, open(sys.argv[3], 'w'))
json.dump(out, open(sys.argv[3], 'w'))
print('done', len(out), 'of', len(need))
