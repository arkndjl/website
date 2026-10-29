"""per (game, offense): scrimmage plays, neutral seconds a play, no-huddle share, drives; stream and drop the raw file"""
import csv, gzip, io, json, os, subprocess, sys
from collections import defaultdict
from core import OUT
URL = 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{y}.csv.gz'
FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'JAC': 'JAX', 'LAR': 'LA'}
out = {}
for y in range(int(sys.argv[1]), int(sys.argv[2]) + 1):
    p = OUT + f'pbp{y}.csv.gz'
    subprocess.run(['curl', '-sSL', '-m', '600', URL.format(y=y), '-o', p], check=True)
    rd = csv.reader(gzip.open(p, 'rt'))
    h = next(rd); I = {k: i for i, k in enumerate(h)}
    G = defaultdict(lambda: [0, 0.0, 0, 0, 0, set()])   # plays, neutral secs sum, neutral n, no-huddle, scrimmage n, drives
    prev = None
    def f(x):
        try: return float(x)
        except ValueError: return None
    for r in rd:
        pt = FR.get(r[I['posteam']], r[I['posteam']])
        if not pt or pt == 'NA':
            continue
        if r[I['play_type']] not in ('pass', 'run'):
            if r[I['play_type']] not in ('no_play',):
                prev = None
            continue
        g = r[I['game_id']]
        k = (g, pt)
        A = G[k]
        A[0] += 1
        A[3] += r[I['no_huddle']] == '1'
        A[5].add(r[I['drive']])
        gs = f(r[I['game_seconds_remaining']]); wp = f(r[I['wp']]); hs = f(r[I['half_seconds_remaining']])
        key = (g, pt, r[I['drive']])
        if prev and prev[0] == key and gs is not None and prev[1] is not None and wp is not None and 0.2 <= wp <= 0.8 and hs and hs > 120:
            dt = prev[1] - gs
            if 3 <= dt <= 60:
                A[1] += dt; A[2] += 1
        prev = (key, gs)
    for (g, t), A in G.items():
        out.setdefault(g, {})[t] = [A[0], A[1] / A[2] if A[2] else None, A[3] / A[0] if A[0] else 0, len(A[5])]
    os.remove(p)
    print(y, len(out), flush=True)
json.dump(out, open(OUT + f'nfl_pace_{sys.argv[1]}.json', 'w'))
