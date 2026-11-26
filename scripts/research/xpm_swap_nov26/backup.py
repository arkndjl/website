#!/usr/bin/env python3
"""Depth chart / backup watch grade (scripts/backup_watch.py cbb_grade: BPM this season and last at half weight, by minutes,
shrunk to replacement). Candidate: last season's line carries pXPM (board form, point in time) in place of its BPM; nothing
is fit. Test: at season share f of each team's games (Barttorvik game logs 2015-26), the grade against the same player's
minutes-weighted game BPM over the rest of the season (100+ minutes left), squared error weighted by those minutes.  -> backup.json"""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import backup_watch as BW, cbb_roster as R, cbb_next_research as NR
f = R.f; by = R.load_seasons(); LOG = os.path.join(C.ROOT, 'scripts', '.cache', 'cbb', 'advgames'); GL = NR.GL
K, REPL, W = BW.CBB_K, BW.CBB_REPL, BW.CBB_W


def grade(now, last):
    num = den = 0.0
    for (rate, m), w in zip((now, last), W):
        if rate is None or not m: continue
        num += w * m * rate; den += w * m
    return (num + K * REPL) / (den + K)
out = {}
for fr in (0.0, 0.15, 0.3, 0.5):
    d, ws, ss = [], [], []
    for s in range(2015, 2027):
        if s - 1 not in by: continue
        games = [g for g in json.load(gzip.open(os.path.join(LOG, f'{s}.json.gz'))) if g[-1] == s]
        tg = defaultdict(set)
        for g in games: tg[g[GL['team']]].add((g[GL['date']], g[GL['muid']]))
        cut = {t: {m for _, m in sorted(L)[:int(np.ceil(fr * len(L)))]} for t, L in tg.items()}
        a = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for g in games:
            m = g[GL['min']]
            if not m or g[GL['gbpm']] is None: continue
            q = a[str(g[GL['pid']])]; i = 0 if g[GL['muid']] in cut[g[GL['team']]] else 2
            q[i] += m; q[i + 1] += m * g[GL['gbpm']]
        for pid, q in a.items():
            p = by[s - 1].get(pid)
            if q[2] < 100 or p is None or f(p.get('bpm')) is None: continue
            lm = C.get(pid, s - 1, 'e', 0) or 0; px = C.get(pid, s - 1, 'px2')
            if not lm or px is None: continue
            now = (q[1] / q[0], q[0]) if q[0] else (None, 0); y = q[3] / q[2]
            ga, gb = grade(now, (f(p['bpm']), lm)), grade(now, (px, lm))
            d.append((ga - y) ** 2 - (gb - y) ** 2); ws.append(q[2]); ss.append(s)
    d, ws, ss = np.array(d), np.array(ws), np.array(ss); wd = d * ws / ws.mean()
    out[str(fr)] = {'n': len(d), 't': round(C.tstat(wd), 2), 'seasons': f"{int(sum(wd[ss == s].mean() > 0 for s in set(ss)))}/{len(set(ss))}", 'mse_gain': round(float(wd.mean()), 3)}
    print(fr, out[str(fr)], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'backup.json'), 'w'), indent=1)
