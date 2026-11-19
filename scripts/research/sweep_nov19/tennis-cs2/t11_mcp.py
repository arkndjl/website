#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T11 (test only, CC BY-NC-SA source: never shipped): Match Charting Project short-point share x surface as one
more blend input. Files are read from a scratch folder given as argv[1]; nothing from them is written to the repo."""
import csv, pickle, bisect
from tcommon import *
SRC = sys.argv[1]
rows, players, tn = load_rows()
R = Resolver(players, rows, 19900101)
hist = {}                                   # pid -> sorted [(date, short points, points)]
for tour, tag in (('atp', 'm'), ('wta', 'w')):
    info = {}
    for x in csv.DictReader(open(os.path.join(SRC, f'charting-{tag}-matches.csv'), encoding='utf-8', errors='replace')):
        try: d = int(x['Date'])
        except (ValueError, TypeError): continue
        if d > LOCK: continue
        info[x['match_id']] = (d, x['Player 1'], x['Player 2'])
    tot, sh = {}, {}
    for x in csv.DictReader(open(os.path.join(SRC, f'charting-{tag}-stats-Rally.csv'), encoding='utf-8', errors='replace')):
        if x['match_id'] not in info: continue
        try: n = int(x['pts'])
        except (ValueError, TypeError): continue
        if x['row'] == 'Total': tot[x['match_id']] = n
        elif x['row'] == '1-3': sh[x['match_id']] = n
    for mid, (d, p1, p2) in info.items():
        if not tot.get(mid) or mid not in sh: continue
        for nme in (p1, p2):
            pid = R.pid(nme, tour)
            if pid: hist.setdefault(pid, []).append((d, sh[mid], tot[mid]))
for v in hist.values(): v.sort()
print('players with charted matches', len(hist), 'matches-player rows', sum(len(v) for v in hist.values()))
rec = pickle.load(open(os.path.join(CACHE, 't10rec.pkl'), 'rb'))
F, meta = arrays(rec)
y, tid = meta['y'], meta['tid']
# tour mean short share by season (charted matches before the season)
allm = {'a': [], 'w': []}
for pid, v in hist.items():
    for d, s, n in v: allm[pid[0]].append((d, s / n))
for k in allm: allm[k].sort()
def tour_mean(t, d):
    a = allm[t]; i = bisect.bisect_left(a, (d, -1))
    return sum(x[1] for x in a[:i]) / i if i else .55
tm_cache = {}
def sps(pid, d):
    v = hist.get(pid, []); i = bisect.bisect_left(v, (d, -1, -1))
    key = (pid[0], d // 10000)
    if key not in tm_cache: tm_cache[key] = tour_mean(pid[0], (d // 10000) * 10000)
    mu = tm_cache[key]
    if i == 0: return None, 0
    return (sum(s / n for _, s, n in v[:i]) + 10 * mu) / (i + 10), i
col = np.zeros(len(rec)); ok = np.zeros(len(rec), bool)
for j, x in enumerate(rec):
    r = x[0]
    a, na = sps(r[7], r[0]); b, nb = sps(r[8], r[0])
    if na >= 10 and nb >= 10:
        ok[j] = True
        col[j] = (a - b) * {'G': 1, 'H': 0, 'C': -1}.get(r[3], 0)
zb = wf_logit(F[:, LIVE], meta)
zt = wf_logit(np.c_[F[:, LIVE], col], meta)
d = nll(zt) - nll(zb)
tune, held = ok & (y >= 2012) & (y <= 2022), ok & (y >= 2023)
out = {'rows_ok': int(ok.sum()), 'tune': tclust(d[tune], tid[tune]), 'held': tclust(d[held], tid[held]),
       'seasons': {int(s): round(float(d[ok & (y == s)].mean() * 1e4), 2) for s in range(2012, 2027) if (ok & (y == s)).any()}}
out['held_better'] = sum(out['seasons'].get(s, 1) < 0 for s in range(2023, 2027))
out['pass'] = bool(out['held']['t'] <= -2 and out['tune']['d1e4'] < 0 and out['held_better'] >= 3)
print(json.dumps(out, indent=1)); save('t11_results', out)
