"""Team-game lines from nflverse play-by-play (stdlib): success rates, explosiveness, red zone, field position,
special teams EPA, 4th-down and pass-rate decisions over expected. One row per (game_id, offense team); the defense
side of a stat is the opponent's row. The raw files are shared with nfl_war.py (scripts/.cache/nfl/play_by_play_YYYY.csv.gz); the lines are cached per
season in scripts/.cache/nfl/pbp."""
import csv
import gzip
import json
import os
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'scripts', '.cache', 'nfl', 'pbp')
RAW = os.path.join(ROOT, 'scripts', '.cache', 'nfl', 'play_by_play_{y}.csv.gz')
URL = 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{y}.csv.gz'

FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'JAC': 'JAX', 'LAR': 'LA'}
def tm(t): return FR.get(t, t)
def f(x, d=None):
    try: return float(x)
    except (TypeError, ValueError): return d

KEYS = ['n', 's', 'e', 'ng', 'sg', 'eg', 'edn', 'eds', 'ede', 'tdn', 'tdc', 'rzn', 'rzs', 'xpe', 'big', 'run', 'stuff', 'lyd',
        'cpn', 'cps', 'pen', 'pes', 'drv', 'fps', 'rzt', 'rzp', 'stk', 'str', 'f4n', 'f4go', 'f4x', 'to', 'dpe', 'dpn']

def ybin(y): return min(int(y // 10), 9)
def tbin(t): return 0 if t <= 1 else 1 if t <= 2 else 2 if t <= 3 else 3 if t <= 5 else 4 if t <= 10 else 5

def agg(path):
    rd = csv.reader(gzip.open(path, 'rt'))
    h = next(rd); I = {k: i for i, k in enumerate(h)}
    G = defaultdict(lambda: dict.fromkeys(KEYS, 0.0))
    seen_drive = set()
    f4 = []   # (game, team, bin, go)
    for r in rd:
        g = r[I['game_id']]; pt = tm(r[I['posteam']]); dt = tm(r[I['defteam']])
        if not pt or pt == 'NA' or not dt or dt == 'NA':
            continue
        ptype = r[I['play_type']]; epa = f(r[I['epa']])
        A = G[(g, pt)]
        # drives: starting field position and red-zone trips, read once per drive
        dk = (g, r[I['fixed_drive']])
        if dk not in seen_drive and ptype not in ('kickoff', '') and r[I['fixed_drive']] not in ('', 'NA'):
            seen_drive.add(dk)
            s = r[I['drive_start_yard_line']].split()
            if len(s) == 2 and f(s[1]) is not None:
                yd = f(s[1]); fp = 50 if s[0] == 'MID' else (100 - yd if tm(s[0]) == pt else yd)
                A['drv'] += 1; A['fps'] += fp
            if r[I['drive_inside20']] == '1':
                A['rzt'] += 1
                res = r[I['fixed_drive_result']]
                A['rzp'] += 7 if res == 'Touchdown' else 3 if res == 'Field goal' else 0
        if epa is None:
            continue
        if ptype in ('kickoff', 'punt'):
            A['str'] += epa; G[(g, dt)]['str'] -= epa
            if ptype == 'punt' and r[I['down']] == '4':
                f4.append((g, pt, r, 0))
            continue
        if ptype in ('field_goal', 'extra_point'):
            A['stk'] += epa; G[(g, dt)]['stk'] -= epa
            if r[I['down']] == '4':
                f4.append((g, pt, r, 0))
            continue
        if ptype == 'punt':
            continue
        if ptype not in ('pass', 'run') or r[I['qb_kneel']] == '1' or r[I['qb_spike']] == '1' or r[I['two_point_attempt']] == '1':
            continue
        down = r[I['down']]
        if down == '4':
            f4.append((g, pt, r, 1))
        succ = 1.0 if r[I['success']] == '1' else 0.0
        yds = f(r[I['yards_gained']], 0.0); wp = f(r[I['wp']], 0.5); yl = f(r[I['yardline_100']], 50)
        A['n'] += 1; A['s'] += succ; A['e'] += epa
        if 0.1 <= wp <= 0.9:
            A['ng'] += 1; A['sg'] += succ; A['eg'] += epa
        if down in ('1', '2'):
            A['edn'] += 1; A['eds'] += succ; A['ede'] += epa
        if down == '3':
            A['tdn'] += 1; A['tdc'] += 1 if r[I['third_down_converted']] == '1' else 0
        if yl <= 20:
            A['rzn'] += 1; A['rzs'] += succ
        if succ:
            A['xpe'] += epa
        if yds >= 20:
            A['big'] += 1
        if r[I['interception']] == '1' or r[I['fumble_lost']] == '1':
            A['to'] += 1
        if r[I['rush']] == '1' and r[I['qb_scramble']] != '1':
            A['run'] += 1
            if yds <= 0: A['stuff'] += 1
            A['lyd'] += 1.2 * yds if yds <= 0 else (min(yds, 4) + 0.5 * max(0, min(yds, 10) - 4))
        c = f(r[I['cpoe']])
        if c is not None:
            A['cpn'] += 1; A['cps'] += c
        if r[I['qb_dropback']] == '1':
            A['dpn'] += 1; A['dpe'] += epa
        pe = f(r[I['pass_oe']])
        if pe is not None and down in ('1', '2', '3') and 0.1 <= wp <= 0.9:
            A['pen'] += 1; A['pes'] += pe
    # 4th downs: go rate over the season's league rate in the same bin (distance x field position, plus trailing late)
    L = defaultdict(lambda: [0, 0]); B = []
    for g, pt, r, go in f4:
        wp = f(r[I['wp']], 0.5); qtr = r[I['qtr']]
        if not 0.05 <= wp <= 0.95 or qtr == '5':
            continue
        late = 1 if (qtr == '4' and f(r[I['score_differential']], 0) <= -4) else 0
        b = (tbin(f(r[I['ydstogo']], 10)), ybin(f(r[I['yardline_100']], 50)), late)
        L[b][0] += 1; L[b][1] += go; B.append((g, pt, b, go))
    for g, pt, b, go in B:
        A = G[(g, pt)]; A['f4n'] += 1; A['f4go'] += go; A['f4x'] += L[b][1] / L[b][0]
    return G


def season(y, fresh=False):
    """{(game_id, team): line} for season y; fresh refetches the play-by-play (this season's, as games finish)."""
    os.makedirs(DIR, exist_ok=True)
    raw, out = RAW.format(y=y), os.path.join(DIR, f'tg_{y}.json')
    if fresh or not os.path.exists(out):
        if fresh or not os.path.exists(raw):
            req = urllib.request.Request(URL.format(y=y), headers={'User-Agent': 'arkndjl.net'})
            with urllib.request.urlopen(req, timeout=120) as r, open(raw + '.tmp', 'wb') as f:
                f.write(r.read())
            os.replace(raw + '.tmp', raw)
        G = agg(raw)
        with open(out, 'w') as f:
            json.dump({f'{g}|{t}': {k: round(v, 4) for k, v in a.items()} for (g, t), a in G.items()}, f)
    with open(out) as f:
        return {tuple(k.split('|')): v for k, v in json.load(f).items()}
