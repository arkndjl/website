#!/usr/bin/env python3
"""NFL personnel groupings for the NFL ARKBOARD's personnel tab (static/data/personnel/nfl.json), and the personnel
inputs tested on the game model and the receiving props (data/nfl_personnel_research.json).

    python3 scripts/nfl_personnel.py             # the tab: last season with participation data + this season's FTN
    python3 scripts/nfl_personnel.py --research  # game-model matchup terms and route share on the props (numpy)

Data (nflverse, free): play_by_play_<y> (EPA, success), pbp_participation_<y> (who was on the field, offense and
defense personnel; 2016-25 published, 2026 not yet: the release returns 404), ftn_charting_<y> (FTN's charting,
2022 on, current: motion, play action, shotgun, box count, blitzers), snap_counts_<y> (PFR snaps by player, current).

Offense personnel is backs then tight ends ("11" = 1 RB, 1 TE, 3 WR; fullbacks count as backs); six or more
linemen is "jumbo". Defense: base = 4 or fewer defensive backs, nickel = 5, dime = 6+. Plays: runs and dropbacks
(scrambles and sacks included), no kneels, spikes or two-point tries; regular season.
"""
import csv
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nfl_pbp as P  # noqa: E402
import nfl_war as W  # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'nfl', 'personnel')
OUT = os.path.join(ROOT, 'static', 'data', 'personnel', 'nfl.json')
RES = os.path.join(ROOT, 'data', 'nfl_personnel_research.json')
GROUPS = ['11', '12', '13', '21', '22', '10', 'jumbo', 'other']
DEFS = ['base', 'nickel', 'dime']
OLPOS = {'OL', 'C', 'G', 'T', 'OG', 'OT'}
DBPOS = {'DB', 'CB', 'S', 'FS', 'SS'}
csv.field_size_limit(1 << 24)


def team(t):
    return P.tm(t)


def off_group(s):
    """'1 RB, 1 TE, 3 WR' or the 2025 roster-position form -> '11', '12', ..., 'jumbo', 'other'; None if blank"""
    if not s:
        return None
    c = defaultdict(int)
    for n, pos in re.findall(r'(\d+) ([A-Z]+)', s):
        c[pos] += int(n)
    if not c:
        return None
    ol = sum(v for k, v in c.items() if k in OLPOS)
    if ol >= 6:
        return 'jumbo'
    b, te = c['RB'] + c['FB'] + c['HB'], c['TE']
    g = f'{b}{te}'
    return g if g in GROUPS else 'other'


def def_group(s):
    if not s:
        return None
    n = sum(int(k) for k, pos in re.findall(r'(\d+) ([A-Z]+)', s) if pos in DBPOS)
    if n == 0 and not re.search(r'\d', s):
        return None
    return 'base' if n <= 4 else 'nickel' if n == 5 else 'dime'


def part_file(y):
    return W.get(f'pbp_participation_{y}.csv', f'{W.REL}/pbp_participation/pbp_participation_{y}.csv')


def has_participation(y):
    try:
        part_file(y)
        return True
    except Exception:
        return False


def plays(y, fresh=False):
    """[game_id, week, off, def, offense group, defense group, epa, success, dropback, wp, [offense gsis ids]]
    for season y's regular-season runs and dropbacks; groups None without participation. Cached a season."""
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'plays_{y}.json.gz')
    if os.path.exists(fn) and not fresh:
        with gzip.open(fn, 'rt') as f:
            return json.load(f)
    part = {}
    try:
        with open(part_file(y), newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                part[(r['nflverse_game_id'], r['play_id'])] = (off_group(r['offense_personnel']),
                                                               def_group(r['defense_personnel']),
                                                               r['offense_players'])
    except Exception as e:
        print('participation', y, e, file=sys.stderr)
    P.season(y, fresh=fresh)          # makes sure the raw play-by-play is cached
    out = []
    with gzip.open(P.RAW.format(y=y), 'rt') as f:
        rd = csv.reader(f)
        h = next(rd)
        I = {k: i for i, k in enumerate(h)}
        for r in rd:
            if r[I['season_type']] != 'REG' or r[I['play_type']] not in ('pass', 'run'):
                continue
            if '1' in (r[I['qb_kneel']], r[I['qb_spike']], r[I['two_point_attempt']]):
                continue
            epa = P.f(r[I['epa']])
            if epa is None:
                continue
            gid = r[I['game_id']]
            pid = r[I['play_id']].split('.')[0]
            og, dg, ids = part.get((gid, pid), (None, None, ''))
            out.append([gid, int(r[I['week']]), team(r[I['posteam']]), team(r[I['defteam']]), og, dg, round(epa, 3),
                        int(r[I['success']] == '1'), int(r[I['qb_dropback']] == '1'), round(P.f(r[I['wp']], .5), 3),
                        ids.split(';') if ids else []])
    with gzip.open(fn + '.tmp', 'wt') as f:
        json.dump(out, f, separators=(',', ':'))
    os.replace(fn + '.tmp', fn)
    return out


# ---------------------------------------------------------------- the tab
NAMES = {'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
         'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns',
         'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
         'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars', 'KC': 'Kansas City Chiefs',
         'LA': 'Los Angeles Rams', 'LAC': 'Los Angeles Chargers', 'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
         'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
         'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks',
         'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'}
LOGO = {'LA': 'lar'}


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x, n)


def ranks(rows, key, high=True):
    """1 = best within the list; ties share"""
    vals = sorted((r[key] for r in rows if r.get(key) is not None), reverse=high)
    for r in rows:
        r[key + 'R'] = None if r.get(key) is None else 1 + vals.index(r[key])


def personnel_table(y):
    """per team: offense usage, EPA a play and success by grouping; defense base / nickel / dime rates and EPA allowed
    by the offense grouping it faced; league rates"""
    ps = [p for p in plays(y) if p[4] is not None]
    off = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0, 0]))     # team -> group -> [n, epa, success, dropbacks]
    dfn = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0]))        # team -> def group -> [n, epa allowed, success]
    dvs = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0]))        # team -> offense group faced -> [n, epa, success]
    lg = defaultdict(lambda: [0, 0.0, 0, 0])
    lgd = defaultdict(lambda: [0, 0.0, 0])
    weeks = set()
    for gid, wk, o, d, og, dg, epa, s, db, wp, ids in ps:
        weeks.add(wk)
        for a, b in ((off[o][og], lg[og]), (off[o]['all'], lg['all'])):
            a[0] += 1; a[1] += epa; a[2] += s; a[3] += db
            b[0] += 1; b[1] += epa; b[2] += s; b[3] += db
        if dg:
            for a in (dfn[d][dg], dfn[d]['all'], lgd[dg]):
                a[0] += 1; a[1] += epa; a[2] += s
        for a in (dvs[d][og], dvs[d]['all']):
            a[0] += 1; a[1] += epa; a[2] += s
    teams = []
    for t in sorted(off):
        tot = off[t]['all'][0]
        O = {}
        for g in GROUPS:
            n, e, s, db = off[t][g]
            O[g] = {'n': n, 'pct': _r(n / tot, 4) if tot else None, 'epa': _r(e / n) if n >= 20 else None,
                    'sr': _r(s / n) if n >= 20 else None, 'pass': _r(db / n) if n >= 20 else None}
        dt_ = dfn[t]['all'][0]
        Dd = {}
        for g in DEFS:
            n, e, s = dfn[t][g]
            Dd[g] = {'n': n, 'pct': _r(n / dt_, 4) if dt_ else None, 'epa': _r(e / n) if n >= 20 else None,
                     'sr': _r(s / n) if n >= 20 else None}
        V = {}
        for g in GROUPS:
            n, e, s = dvs[t][g]
            V[g] = {'n': n, 'epa': _r(e / n) if n >= 20 else None, 'sr': _r(s / n) if n >= 20 else None}
        a = off[t]['all']; da = dvs[t]['all']
        teams.append({'t': t, 'n': NAMES.get(t, t), 'logo': f"/img/nfl/{LOGO.get(t, t.lower())}.png", 'plays': tot,
                      'epa': _r(a[1] / a[0]), 'sr': _r(a[2] / a[0]), 'depa': _r(da[1] / da[0]), 'dsr': _r(da[2] / da[0]),
                      'heavy': _r(sum(off[t][g][0] for g in ('12', '13', '21', '22', 'jumbo')) / tot, 4),
                      'p11': O['11']['pct'], 'base': Dd['base']['pct'], 'nickel': Dd['nickel']['pct'], 'dime': Dd['dime']['pct'],
                      'off': O, 'def': Dd, 'vs': V})
    for k, hi in (('epa', True), ('sr', True), ('depa', False), ('dsr', False), ('heavy', True), ('p11', True),
                  ('base', True), ('nickel', True), ('dime', True)):
        ranks(teams, k, hi)
    for g in GROUPS:                      # per-group ranks: usage and EPA (offense), EPA allowed against it (defense)
        for k, side, hi in (('pct', 'off', True), ('epa', 'off', True), ('epa', 'vs', False)):
            vals = sorted((T[side][g][k] for T in teams if T[side][g].get(k) is not None), reverse=hi)
            for T in teams:
                v = T[side][g].get(k)
                T[side][g][k + 'R'] = None if v is None else 1 + vals.index(v)
    for g in DEFS:
        for k, hi in (('pct', True), ('epa', False)):
            vals = sorted((T['def'][g][k] for T in teams if T['def'][g].get(k) is not None), reverse=hi)
            for T in teams:
                v = T['def'][g].get(k)
                T['def'][g][k + 'R'] = None if v is None else 1 + vals.index(v)
    L = {g: {'pct': _r(lg[g][0] / lg['all'][0], 4), 'epa': _r(lg[g][1] / lg[g][0]) if lg[g][0] else None,
             'sr': _r(lg[g][2] / lg[g][0]) if lg[g][0] else None} for g in GROUPS}
    LD = {g: {'pct': _r(lgd[g][0] / sum(lgd[x][0] for x in DEFS), 4), 'epa': _r(lgd[g][1] / lgd[g][0]) if lgd[g][0] else None}
          for g in DEFS}
    return {'season': y, 'weeks': max(weeks) if weeks else 0, 'teams': teams, 'league': L, 'leagueDef': LD}


def ftn_table(y):
    """this season's FTN charting by team: offense (motion, play action, shotgun, no huddle, RPO, screen; EPA with
    and without motion and play action) and defense (box count, blitz rate, pass rushers)"""
    try:
        fn = W.get(f'ftn_charting_{y}.csv', f'{W.REL}/ftn_charting/ftn_charting_{y}.csv', fresh=True)
    except Exception as e:
        print('ftn', y, e, file=sys.stderr)
        return None
    ftn = {}
    with open(fn, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            ftn[(r['nflverse_game_id'], r['nflverse_play_id'].split('.')[0])] = r
    P.season(y, fresh=True)
    O = defaultdict(lambda: defaultdict(float))
    Df = defaultdict(lambda: defaultdict(float))
    weeks = set()
    with gzip.open(P.RAW.format(y=y), 'rt') as f:
        rd = csv.reader(f)
        h = next(rd)
        I = {k: i for i, k in enumerate(h)}
        for r in rd:
            if r[I['season_type']] != 'REG' or r[I['play_type']] not in ('pass', 'run'):
                continue
            if '1' in (r[I['qb_kneel']], r[I['qb_spike']], r[I['two_point_attempt']]):
                continue
            epa = P.f(r[I['epa']])
            x = ftn.get((r[I['game_id']], r[I['play_id']].split('.')[0]))
            if epa is None or not x:
                continue
            weeks.add(int(r[I['week']]))
            o, d = team(r[I['posteam']]), team(r[I['defteam']])
            T = lambda k: x.get(k) == 'TRUE'
            db = r[I['qb_dropback']] == '1'
            A = O[o]
            A['n'] += 1; A['epa'] += epa
            for k, c in (('mo', 'is_motion'), ('pa', 'is_play_action'), ('nh', 'is_no_huddle'), ('rpo', 'is_rpo'),
                         ('scr', 'is_screen_pass')):
                if T(c):
                    A[k] += 1; A[k + 'E'] += epa
            A['sg'] += x.get('qb_location') in ('S', 'P')
            A['db'] += db
            if db:
                A['pa_db'] += T('is_play_action')
            B = Df[d]
            B['n'] += 1; B['epa'] += epa
            box = P.f(x.get('n_defense_box'))
            if box:
                B['box'] += box; B['boxn'] += 1
            if db:
                B['db'] += 1
                nb = P.f(x.get('n_blitzers'), 0) or 0
                B['bl'] += nb > 0
                B['rush'] += P.f(x.get('n_pass_rushers'), 0) or 0
                if nb > 0:
                    B['blE'] += epa; B['bln'] += 1
                else:
                    B['nbE'] += epa; B['nbn'] += 1
    teams = []
    for t in sorted(O):
        A, B = O[t], Df[t]
        n = A['n'] or 1
        row = {'t': t, 'n': NAMES.get(t, t), 'logo': f"/img/nfl/{LOGO.get(t, t.lower())}.png", 'plays': int(A['n']),
               'mo': _r(A['mo'] / n), 'pa': _r(A['pa_db'] / A['db']) if A['db'] else None, 'sg': _r(A['sg'] / n),
               'nh': _r(A['nh'] / n), 'rpo': _r(A['rpo'] / n),
               'moE': _r(A['moE'] / A['mo']) if A['mo'] >= 20 else None,
               'nomoE': _r((A['epa'] - A['moE']) / (n - A['mo'])) if n - A['mo'] >= 20 else None,
               'box': _r(B['box'] / B['boxn'], 2) if B['boxn'] else None,
               'blitz': _r(B['bl'] / B['db']) if B['db'] else None,
               'rush': _r(B['rush'] / B['db'], 2) if B['db'] else None,
               'blE': _r(B['blE'] / B['bln']) if B['bln'] >= 20 else None,
               'nbE': _r(B['nbE'] / B['nbn']) if B['nbn'] >= 20 else None}
        teams.append(row)
    for k, hi in (('mo', True), ('pa', True), ('sg', True), ('nh', True), ('rpo', True), ('moE', True), ('box', True),
                  ('blitz', True), ('rush', True), ('blE', False), ('nbE', False)):
        ranks(teams, k, hi)
    return {'season': y, 'weeks': max(weeks) if weeks else 0, 'teams': teams}


def snap_personnel(y):
    """this season's average personnel from PFR snap counts: RBs/FBs, TEs and WRs on the field a play (team snaps by
    position over offensive plays); the snap counts carry no per-play groupings"""
    try:
        fn = W.get(f'snap_counts_{y}.csv', f'{W.REL}/snap_counts/snap_counts_{y}.csv', fresh=True)
    except Exception as e:
        print('snaps', y, e, file=sys.stderr)
        return None
    pos = defaultdict(lambda: defaultdict(float))
    plays_ = defaultdict(dict)
    with open(fn, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r.get('game_type') not in ('REG', None):
                continue
            t = team(r['team'])
            o = W.num(r['offense_snaps'])
            plays_[t][r['game_id']] = max(plays_[t].get(r['game_id'], 0), o)     # the QB / linemen who played every snap
            p = r['position']
            k = 'b' if p in ('RB', 'FB', 'HB') else 'te' if p == 'TE' else 'wr' if p == 'WR' else None
            if k:
                pos[t][k] += o
    out = {}
    for t, v in pos.items():
        n = sum(plays_[t].values())
        if n:
            out[t] = {k: _r(v[k] / n, 2) for k in ('b', 'te', 'wr')}
    return out


def build():
    cur = int(os.environ.get('NFL_SEASON') or (dt.date.today().year if dt.date.today().month >= 8 else dt.date.today().year - 1))
    y = cur
    while y > 2016 and not has_participation(y):
        y -= 1
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'current': cur,
           'personnel': personnel_table(y), 'groups': GROUPS, 'defs': DEFS}
    out['personnelNote'] = (f'{y} season: nflverse has not published {cur} participation data yet'
                            if y != cur else f'{y} season')
    f = ftn_table(cur)
    if f and f['teams']:
        out['ftn'] = f
    s = snap_personnel(cur)
    if s:
        out['snaps'] = {'season': cur, 'teams': s}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'), allow_nan=False)
    os.replace(tmp, OUT)
    print('wrote', OUT, os.path.getsize(OUT), 'bytes; personnel', y, '; ftn', bool(f), '; snaps', bool(s))


if __name__ == '__main__':
    if '--research' in sys.argv:
        import nfl_personnel_research as R
        R.main()
    else:
        build()
