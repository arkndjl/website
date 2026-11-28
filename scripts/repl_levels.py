# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Replacement levels for every stat that has one, dated and refit on a schedule (Noah, Nov 28 2026: recalibrate
replacement level constantly, by position). Writes data/repl_levels.json; process-refresh.yml runs it, and it refits at
most once a week (--force to refit now). Stdlib only.

What each sport reads, and how it was tested (scripts/research/repl_nov28/, Nov 28 2026):
  cbb   VORX lines by position (G, F, C on Barttorvik's role): the fixed level (-1.4, the 9th man's shrunk rXPM) moved
        by each position's offset in the 9th-12th men by team minutes (shrunk rXPM, minutes-weighted) over the last three
        finished seasons. Against one flat line, held out (leave one season out, 2012-26): same-season team W% t 6.15
        (14/15 seasons), with season fixed effects t 3.37; next season's W% on returning VORX t 4.31, fixed effects t 2.42.
        scripts/cbb_tabs.py, cbb_next.py and alltime.py read 'cbb'. A refit flat level failed same-season W% (t -2.8 to
        -5.2; ties under fixed effects), so the level stays -1.4 and is tracked here ('track').
  nba   one line, -1.4 (freely available players: 24+, under 250 MP the season before). Every position split failed
        (best: the CBB form, same-season W% t .59, next season -.2; freely available pools by position t -.26 to -3.4),
        and a refit level ties under fixed effects and loses pooled (t -2.3 to -4.9). Tracked here, not read.
  nhl / nfl / soccer / tennis / cs2: already fit by position (or tour) inside their own runs; copied here with dates so
        every line has one history (nhl F/D/G beyond each team's top 13/7/2, pooled over seasons, which beat the last
        three seasons on next season's line, scripts/research/repl_nov28/nhl.py: F RMSE .051 vs .060, D .085 vs .082, G .173 vs .178; nfl by sub-position,
        part-timers, data/nfl_war_pos.json; soccer GK/D/M/F, bottom-three sides' regulars; tennis ranked 101-150 Elo by
        tour; cs2 VRS 51-100 starters at the day).

  python3 scripts/repl_levels.py            # refit if the last fit is a week old
  python3 scripts/repl_levels.py --force    # refit now
  python3 scripts/repl_levels.py --history  # also rebuild the CBB lines of every past season (needs Barttorvik 2008-)
"""
import datetime as dt
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
OUT = os.path.join(ROOT, 'data', 'repl_levels.json')
CBB_LEVEL, NBA_LEVEL = -1.4, -1.4
POSMAP = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}
SHRINK_K = 100.0          # cbb_tabs GBPM_K: VORX's input is rXPM shrunk 100 minutes toward the season's mean
WINDOW = 3                # finished seasons in the position offsets (trailing 3 passed; the expanding mean passed too)
CBB_SEASON = 2027         # the season in progress (cbb_tabs SEASON); a bump in data/seasons/cbb.json


def r2(x): return None if x is None else round(x, 2)


def load():
    try: return json.load(open(OUT))
    except (OSError, ValueError): return {}


# ---------------------------------------------------------------- CBB
def cbb_bench(year):
    """season `year`: {pool: (sum x m, sum m)} for the 9th-12th men by team minutes, flat and by position; x = rXPM
    (BPM + the team's minutes-weighted mean GBPM - BPM per side, scripts/cbb_xpm.py) shrunk SHRINK_K toward the mean"""
    import cbb_data as D
    ls = [l for l in D.load_bt(year) if (l.get('gp') or 0) and (l.get('mp') or 0) and l.get('obpm') is not None and l.get('dbpm') is not None]
    if len(ls) < 2000: return None
    sh = defaultdict(lambda: [0.0, 0.0, 0.0])
    for l in ls:
        l['m'] = l['gp'] * l['mp']
        if all(l.get(k) is not None for k in ('ogbpm', 'dgbpm')):
            q = sh[l['team']]; q[0] += l['m'] * (l['ogbpm'] - l['obpm']); q[1] += l['m'] * (l['dgbpm'] - l['dbpm']); q[2] += l['m']
    for l in ls:
        q = sh.get(l['team']); o, d = (q[0] / q[2], q[1] / q[2]) if q and q[2] else (0.0, 0.0)
        l['x'] = l['obpm'] + o + l['dbpm'] + d
    w = sum(l['m'] for l in ls); mu = sum(l['x'] * l['m'] for l in ls) / w
    by = defaultdict(list)
    for l in ls:
        l['sx'] = (l['x'] * l['m'] + SHRINK_K * mu) / (l['m'] + SHRINK_K); by[l['team']].append(l)
    acc = defaultdict(lambda: [0.0, 0.0])
    for g in by.values():
        g.sort(key=lambda l: -l['m'])
        for l in g[8:12]:
            for k in ('all', POSMAP.get(l['role'], 'F')):
                acc[k][0] += l['sx'] * l['m']; acc[k][1] += l['m']
    return {k: [round(a, 1), round(b, 1)] for k, (a, b) in acc.items()}


def cbb_lines(pools, target):
    """the VORX lines of season `target` from the WINDOW finished seasons before it: CBB_LEVEL + (position mean - flat mean)"""
    ys = [y for y in sorted(pools) if y < target and pools[y] and all(k in pools[y] for k in ('G', 'F', 'C'))][-WINDOW:]
    if len(ys) < WINDOW: return None
    def m(k): return sum(pools[y][k][0] for y in ys) / sum(pools[y][k][1] for y in ys)
    flat = m('all')
    return {'from': [ys[0], ys[-1]], 'G': r2(CBB_LEVEL + m('G') - flat), 'F': r2(CBB_LEVEL + m('F') - flat), 'C': r2(CBB_LEVEL + m('C') - flat),
            'pool': r2(flat)}


# ---------------------------------------------------------------- NBA (tracked)
def nba_track():
    """freely available players' minutes-weighted rXPM (24+, under 250 MP the season before), by season and position"""
    d = os.path.join(ROOT, 'static', 'data', 'nba-xpm'); S = {}
    for f in sorted(os.listdir(d)):
        if f[:4].isdigit() and f.endswith('.json'):
            S[int(f[:4])] = {p['id']: p for p in json.load(open(os.path.join(d, f)))['players'] if not p.get('pr') and p.get('xpm') is not None}
    G3 = {'PG': 'G', 'SG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'C'}
    by = {}
    for y, ps in S.items():
        a = defaultdict(lambda: [0.0, 0.0])
        for pid, p in ps.items():
            prev = S.get(y - 1, {}).get(pid)
            if y - 1 not in S or (p.get('age') or 0) < 24 or (prev['mp'] if prev else 0) >= 250 or not p['mp']: continue
            x = p['txpm'] if p.get('txpm') is not None else p['xpm']
            for k in ('all', G3.get(str(p['pos']).split('-')[0], 'F')):
                a[k][0] += x * p['mp']; a[k][1] += p['mp']
        if a: by[y] = {k: r2(s / m) for k, (s, m) in a.items()}
    done = [y for y in sorted(by) if y < max(by)]
    return {'line': NBA_LEVEL, 'bySeason': by, 'last3': r2(sum(by[y]['all'] for y in done[-3:]) / 3) if len(done) >= 3 else None}


# ---------------------------------------------------------------- other sports (their own fits)
def other():
    def j(p):
        try: return json.load(open(os.path.join(ROOT, 'data', p)))
        except (OSError, ValueError): return {}
    nhl, nfl, soc, ten, cs2 = j('nhl_war_fit.json'), j('nfl_war_pos.json'), j('soccer_war_fit.json'), j('tennis_fit.json'), j('cs2_value.json')
    return {'nhl': {'lines': (nhl.get('desc') or {}).get('repl'), 'unit': 'goals a 60 over replacement, beyond each team\'s top 13 F / 7 D / 2 G'},
            'nfl': {'lines': nfl.get('line'), 'asof': nfl.get('asof'), 'unit': 'AV a full season of snaps, part-timers (5-35% of snaps)'},
            'soccer': {'lines': soc.get('repl'), 'asof': soc.get('asof'), 'unit': 'goals a 90, the bottom three sides\' regulars'},
            'tennis': {'lines': {k[5:].lower(): v for k, v in (ten.get('params') or {}).items() if k.startswith('REPL_')}, 'unit': 'Elo, ranked 101-150'},
            'cs2': {'lines': {'all': cs2.get('repl')}, 'asof': cs2.get('asof'), 'unit': 'rating, VRS 51-100 starters'}}


def main():
    old = load(); today = dt.date.today()
    if old.get('asof') and '--force' not in sys.argv and '--history' not in sys.argv:
        if (today - dt.date.fromisoformat(old['asof'][:10])).days < 7:
            print('repl_levels: refit', old['asof'], '(weekly)'); return
    pools = {int(k): v for k, v in ((old.get('cbb') or {}).get('pools') or {}).items()}
    want = range(2008, CBB_SEASON) if '--history' in sys.argv else range(CBB_SEASON - WINDOW, CBB_SEASON)
    for y in want:
        if y in pools and y < CBB_SEASON - 1 and '--history' not in sys.argv: continue   # a finished season's pool is kept
        try:
            p = cbb_bench(y)
            if p: pools[y] = p
        except Exception as e:                       # Barttorvik refuses a runner now and then: keep the last pool
            print('cbb pool', y, e)
    seasons = dict((old.get('cbb') or {}).get('bySeason') or {})
    for t in range(min(pools) + WINDOW, CBB_SEASON + 1) if pools else []:
        L = cbb_lines(pools, t)
        if L: seasons[str(t)] = L
    cur = seasons.get(str(CBB_SEASON)) or (old.get('cbb') or {}).get('lines')
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'cbb': {'level': CBB_LEVEL, 'season': CBB_SEASON, 'lines': {k: cur[k] for k in 'GFC'} if cur else {'G': CBB_LEVEL, 'F': CBB_LEVEL, 'C': CBB_LEVEL},
                   'from': cur.get('from') if cur else None, 'pool': cur.get('pool') if cur else None,
                   'bySeason': dict(sorted(seasons.items())), 'pools': {str(k): pools[k] for k in sorted(pools)},
                   'how': 'level -1.4 + position offset of the 9th-12th men (shrunk rXPM), last 3 finished seasons'},
           'nba': nba_track(), **other()}
    # dated, change-only history of every sport's lines
    hist = list(old.get('history') or [])
    snap = {s: (out[s]['lines'] if s != 'nba' else {'all': out['nba']['line']}) for s in ('cbb', 'nba', 'nhl', 'nfl', 'soccer', 'tennis', 'cs2')}
    if not hist or hist[-1]['lines'] != snap:
        hist.append({'d': out['asof'][:10], 'lines': snap})
    out['history'] = hist
    json.dump(out, open(OUT, 'w'), indent=1)
    print('repl_levels:', json.dumps(snap))


def cbb_line(pos, season=None):
    """the CBB VORX replacement line for a position (G, F, C) in a season (default: this one); -1.4 without the file"""
    c = _CACHE.get('f')
    if c is None:
        c = _CACHE['f'] = load().get('cbb') or {}
    bs = c.get('bySeason') or {}
    if season and bs and str(season) not in bs and int(season) < min(int(k) for k in bs):
        season = min(int(k) for k in bs)        # before Barttorvik's roles (2013): the first lines there are
    L = bs.get(str(season)) if season else None
    L = L or c.get('lines') or {}
    return L.get(pos if pos in ('G', 'F', 'C') else 'F', CBB_LEVEL)


_CACHE = {}

if __name__ == '__main__':
    main()
