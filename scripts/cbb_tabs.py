#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball production tabs (Nov 3 2026): the CBB page's equivalents of the CFB stats, WAR, breakout, top
performer, draft board, portal, returning and team talent views. Display only: every number is a season line, a
game line or an existing model output (FV, xBPM, NBA%, the mocks); nothing here feeds the FV model.

    python3 scripts/cbb_tabs.py            # daily: this season from static/data/cbb-all.json + the game logs cache
    python3 scripts/cbb_tabs.py --freeze   # once: 2025-26 (Barttorvik season file + game logs) -> scripts/data/cbb_tabs_2026.json.gz

Outputs
    static/data/cbb/{stats,war,breakouts,top,draft,portal}.json   player tables, drawn by layouts/shortcodes/rookies.html (src=)
    data/cbb_teamtabs.json                                          team tables (returning, talent), drawn by teamunits.html (feed=)

Definitions
    WAR    wins over a replacement player = (BPM - R) x minutes / 40 x 68 / 100 x wins a point.
           R = -2.0: the minutes-weighted BPM of the 9th man in team minutes, 2025-26 (-2.0; 8th -1.2, 10th -2.9).
           wins a point = fit on 2016-17 to 2025-26 team-seasons (FIT_YEARS): wins = a x games + b x team sum of
           (BPM - R) x minutes / 40 x .68 (b .0143, a .40, r .86; set by --freeze and kept in the frozen file). The
           textbook N'(0) / game sd (.0347 at sd 11.5) is the slope at an even game; real seasons bend (conference
           schedules pair strong with strong, win odds flatten at the ends), so the fit slope is what sums to wins.
           Barttorvik BPM is per 100 possessions over an average D-I player, and a team's minutes-weighted BPM x 5
           tracks its net rating, so a player's share of the margin is BPM x his share of the 200 minutes.
           Pace is a flat 68 possessions a 40, not the team's: a faster game's margin swings more, so a point a 100
           possessions buys about the same wins at any pace. Nov 3 2026 (scripts/cbb_war_research_nov03.py): flat beat
           team possessions on held-out team wins in 9 of 10 seasons (t 2.9), and the 10-season slope beat the
           2025-26-only fit (.0124) in 7 of 9 held-out seasons (t 3.4); 2025-26 had the lowest slope of the ten.
    WAA    the same over an average player (R = 0).
    Stat+  100 + 25 z, z = BPM against the minutes-weighted mean and sd of his position (G, F, C) in 2025-26 among
           players with 10%+ of team minutes (the CFB board's Stat+ scale). This season's lines use this season's own
           norms (same pool, LIVE_MIN players a position or the 2025-26 norms): early-season BPM spreads wider (sd
           4.4-5.5 through 8 games against 3.5-4.4 a full season), and its own norms cut the error against the
           full-season Stat+ by about a third (10 of 10 seasons, scripts/cbb_war_research_nov03.py).
    Next   next season's WAR at 31 games (scripts/cbb_next.py; fit by scripts/cbb_next_research.py): 2025-26 rows from
           the 2025-26 line (scripts/data/cbb_next_2027.json), this season's from the line to date on the in-season grid.
    Game Score   Hollinger: PTS + .4 FGM - .7 FGA - .4 (FTA - FTM) + .7 ORB + .3 DRB + STL + .7 AST + .7 BLK - .4 PF - TOV.
"""
import datetime as dt
import gzip
import json
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cbb_data as D
import cbb_next as NXT

SEASON, LAST = 2027, 2026
SD = os.path.join(ROOT, 'static', 'data')
OUT = os.path.join(SD, 'cbb')
TEAM_OUT = os.path.join(ROOT, 'data', 'cbb_teamtabs.json')
FROZEN = os.path.join(HERE, 'data', f'cbb_tabs_{LAST}.json.gz')
PRIOR = os.path.join(HERE, 'cbb_prior.json.gz')
REPL = -2.0
PACE = 68.0        # possessions a 40 for every team (not the team's own pace: see WAR above)
WPP = 1.0          # wins a point of margin: fit in freeze() and read from the frozen file
FIT_YEARS = range(2017, LAST + 1)   # team-seasons the wins-a-point slope is fit on (Barttorvik season files + game logs)
LIVE_MIN = 40      # 10%+ minute players a position before this season's Stat+ uses its own norms
POSMAP = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}
POWER = {'ACC', 'B10', 'B12', 'SEC', 'BE'}
GCOLS = ['date', 'dtext', 'opstyle', 'quality', 'win1', 'opp', 'muid', 'win2', 'min', 'ortg', 'usg', 'efg', 'ts', 'orb', 'drb', 'ast',
         'to', 'dunkm', 'dunka', 'rimm', 'rima', 'midm', 'mida', 'twopm', 'twopa', 'tpm', 'tpa', 'ftm', 'fta', 'bpm_rd', 'obpm', 'dbpm',
         'bpm_net', 'pts', 'orb_n', 'drb_n', 'ast_n', 'tov', 'stl_n', 'blk_n', 'stl', 'blk', 'pf', 'poss', 'gbpm', 'sbpm', 'loc', 'team',
         'name', 'inches', 'cls', 'pid', 'year']
GC = {k: i for i, k in enumerate(GCOLS)}
SOPT = [[0, 'any'], [20, '20'], [40, '40'], [100, '100'], [200, '200'], [400, '400'], [600, '600']]
BOPT = [[0, 'any'], [20, '20'], [40, '40'], [100, '100'], [200, '200'], [400, '400']]
MON = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')


def r1(x, d=1):
    return None if x is None else round(x, d)


def col(k, l, t, f='1', num=1, lo=0):
    c = {'k': k, 'l': l, 't': t, 'f': f, 'ph': 0, 'num': num}
    if lo: c['lo'] = 1
    return c


def mdef(opts, minutes):
    """the largest minutes-floor option at or under a target"""
    return max([o[0] for o in opts if o[0] <= minutes], default=0)


def label(s):
    return f'{s - 1}-{str(s)[2:]}'


def war(bpm, minutes, repl=REPL):
    if bpm is None or not minutes: return None
    return (bpm - repl) * minutes / 40 * PACE / 100 * WPP


def fit_wpp(years=FIT_YEARS):
    """wins a point: least squares of team wins on games and the team's summed (BPM - R) x minutes x .68 (20+ games),
    pooled over the team-seasons of every year with a Barttorvik season file and game logs"""
    import numpy as np
    A, w, used = [], [], []
    for y in years:
        games = load_games(y)
        if not games: continue
        X = defaultdict(float)
        for l in D.load_bt(y):
            if l['gp'] and l['mp'] and l['bpm'] is not None:
                X[l['team']] += (l['bpm'] - REPL) * l['mp'] * l['gp'] / 40 * PACE / 100   # points over replacement
        rec, seen = defaultdict(lambda: [0, 0]), set()
        for g in games:
            k = (g[GC['team']], g[GC['muid']])
            if k in seen: continue
            seen.add(k); rec[k[0]][0] += g[GC['win1']]; rec[k[0]][1] += 1
        ts = [t for t in rec if t in X and rec[t][1] >= 20]
        A += [[rec[t][1], X[t]] for t in ts]; w += [rec[t][0] for t in ts]; used.append(y)
    A, w = np.array(A, float), np.array(w, float)
    c = np.linalg.lstsq(A, w, rcond=None)[0]
    r = float(np.corrcoef(A @ c, w)[0, 1])
    return {'wpp': round(float(c[1]), 5), 'a': round(float(c[0]), 3), 'r': round(r, 3), 'teams': len(w), 'years': [min(used), max(used)]}


def game_score(g):
    fgm, fga = g[GC['twopm']] + g[GC['tpm']], g[GC['twopa']] + g[GC['tpa']]
    return (g[GC['pts']] + .4 * fgm - .7 * fga - .4 * (g[GC['fta']] - g[GC['ftm']]) + .7 * g[GC['orb_n']] + .3 * g[GC['drb_n']]
            + g[GC['stl_n']] + .7 * g[GC['ast_n']] + .7 * g[GC['blk_n']] - .4 * g[GC['pf']] - g[GC['tov']])


def load_games(year):
    p = os.path.join(D.CACHE, 'games', f'{year}.json.gz')
    if not os.path.exists(p):
        return []
    try:
        return [g for g in json.load(gzip.open(p)) if g[GC['year']] == year]
    except Exception as e:
        print('game logs unreadable:', e)
        return []


def team_tempo(games):
    """possessions a 40 minutes by team: the mean of its games' possessions, overtime scaled back to 40"""
    seen = {}
    for g in games:
        k = (g[GC['team']], g[GC['muid']])
        if k not in seen and g[GC['poss']]:
            seen[k] = g[GC['poss']]
    by = defaultdict(list)
    for (t, _), p in seen.items():
        by[t].append(p)
    return {t: sum(v) / len(v) for t, v in by.items()}


# ---------------------------------------------------------------- the board and its preseason prior
def board():
    d = json.load(open(os.path.join(SD, 'cbb-all.json')))
    return [dict(zip(d['cols'], r)) for r in d['rows']]


def prior():
    """the frozen preseason board (scripts/cbb_prior.json.gz, cbb_live.py): preseason FV, rank and xBPM by (name,
    team), each row's Barttorvik pid, and Barttorvik team name -> board team / logo / conference"""
    d = json.load(gzip.open(PRIOR))
    rows = [dict(zip(d['cols'], r)) for r in d['rows']]
    pre, pid, bt = {}, {}, {}
    for r, c in zip(rows, d['careers']):
        pre[(r['name'], r['team'])] = r
        if c.get('pid'): pid[(r['name'], r['team'])] = str(c['pid'])
        if c.get('bt'): bt[c['bt']] = (r['team'], r['logo'], r['conf'])
    return pre, pid, bt


# ---------------------------------------------------------------- 2025-26, frozen once
def pos_norms(lines, key='role'):
    """Stat+ scale: minutes-weighted mean and sd of BPM by position among 10%+ minute players (key 'role': Barttorvik
    role mapped by POSMAP; 'pos': already G/F/C)"""
    out = {}
    for p in 'GFC':
        xs = [(l['bpm'], l['mp'] * l['gp']) for l in lines if (POSMAP.get(l['role']) if key == 'role' else l['pos']) == p
              and (l['min_per'] or 0) >= 10 and l['bpm'] is not None]
        w = sum(m for _, m in xs)
        mu = sum(b * m for b, m in xs) / w
        sd = (sum(m * (b - mu) ** 2 for b, m in xs) / w) ** .5
        out[p] = (round(mu, 3), round(sd, 3))
    return out


def stat_line(L):
    """a Barttorvik season row -> the stats-tab numbers"""
    mins = (L['mp'] or 0) * (L['gp'] or 0)
    return {'gp': int(L['gp'] or 0), 'mp': round(mins), 'mpg': r1(L['mp']), 'pts': r1(L['pts_g']), 'reb': r1(L['treb_g']), 'ast_g': r1(L['ast_g']),
            'bpm': r1(L['bpm']), 'obpm': r1(L['obpm']), 'dbpm': r1(L['dbpm']), 'ortg': r1(L['ortg']), 'usg': r1(L['usg']), 'ts': r1(L['ts']),
            'tp': r1((L['tp'] or 0) * 100) if L['tpa'] else None, 'tpa': int(L['tpa'] or 0), 'ft': r1((L['ft'] or 0) * 100) if L['fta'] else None,
            'astp': r1(L['ast']), 'to': r1(L['to']), 'stl': r1(L['stl']), 'blk': r1(L['blk']), 'orb': r1(L['orb']), 'ftr': r1(L['ftr']),
            'war': r1(war(L['bpm'], mins), 2), 'waa': r1(war(L['bpm'], mins, 0), 2)}


def freeze():
    lines = [l for l in D.load_bt(LAST) if l['gp'] and l['mp'] and l['bpm'] is not None]
    prev = {str(l['pid']): l for l in D.load_bt(LAST - 1) if l['gp'] and l['mp'] and l['bpm'] is not None}
    games = load_games(LAST)
    if not games:
        sys.exit(f'no {LAST} game logs in {D.CACHE}/games: fetch https://barttorvik.com/{LAST}_all_advgames.json.gz there first')
    tempo = team_tempo(games)
    norms = pos_norms(lines)
    global WPP
    fit = fit_wpp()
    WPP = fit['wpp']
    out = []
    for L in lines:
        s = stat_line(L)
        P = prev.get(str(L['pid']))
        p = None
        if P:
            pm = (P['mp'] or 0) * (P['gp'] or 0)
            p = {'team': P['team'], 'gp': int(P['gp'] or 0), 'mpg': r1(P['mp']), 'bpm': r1(P['bpm']), 'usg': r1(P['usg']), 'mp': round(pm),
                 'war': r1(war(P['bpm'], pm), 2)}
        out.append({'pid': str(L['pid']), 'n': L['name'], 'bt': L['team'], 'conf': L['conf'], 'yr': L['yr'], 'role': L['role'],
                    'pos': POSMAP.get(L['role'], 'F'), 'ht': L['ht'], 'dob': L['dob'], 'min_per': r1(L['min_per']), 's': s, 'prev': p})
    top = sorted(games, key=lambda g: -game_score(g))[:400]
    tg = [{'n': g[GC['name']], 'bt': g[GC['team']], 'pid': str(g[GC['pid']]), 'opp': g[GC['opp']], 'date': g[GC['date']], 'loc': g[GC['loc']],
           'win': g[GC['win1']], **gline(g)} for g in top]
    os.makedirs(os.path.dirname(FROZEN), exist_ok=True)
    with gzip.open(FROZEN, 'wt') as fh:
        json.dump({'season': LAST, 'asof': now(), 'norms': norms, 'wfit': fit, 'tempo': {k: round(v, 2) for k, v in tempo.items()}, 'lines': out, 'top': tg},
                  fh, separators=(',', ':'))
    print(f'{FROZEN}: {len(out)} lines, {len(tg)} top games, Stat+ norms {norms}, WAR fit {fit}')


def gline(g):
    return {'gs': round(game_score(g), 1), 'pts': int(g[GC['pts']]), 'reb': int(g[GC['orb_n']] + g[GC['drb_n']]), 'ast': int(g[GC['ast_n']]),
            'stl': int(g[GC['stl_n']]), 'blk': int(g[GC['blk_n']]), 'min': r1(g[GC['min']]),
            'gbpm': r1(g[GC['gbpm']]), 'fg': f"{int(g[GC['twopm']] + g[GC['tpm']])}-{int(g[GC['twopa']] + g[GC['tpa']])}",
            'tp3': f"{int(g[GC['tpm']])}-{int(g[GC['tpa']])}"}


# ---------------------------------------------------------------- daily build
def main():
    if '--freeze' in sys.argv:
        return freeze()
    F = json.load(gzip.open(FROZEN))
    norms = F['norms']
    global WPP
    WPP = F['wfit']['wpp']
    wf = F['wfit']
    B = board()
    pre, pidof, bt = prior()
    by_pid = {}
    for r in B:
        p = pidof.get((r['name'], r['team']))
        if p: by_pid[p] = r
    games = load_games(SEASON)
    tg = defaultdict(set)
    for g in games: tg[g[GC['team']]].add(g[GC['muid']])
    gnow = statistics.median([len(v) for v in tg.values()]) if tg else 0     # median team games so far
    # next season's WAR (scripts/cbb_next.py): last season's rows from the 2025-26 line, this season's from the line to date
    nx_last = json.load(open(os.path.join(HERE, 'data', f'cbb_next_{SEASON}.json')))['war']
    nx_now = NXT.live(games, json.load(gzip.open(PRIOR)), SEASON, GC)
    t2e = {k: v[0] for k, v in bt.items()}
    e2t = {v[0]: k for k, v in bt.items()}
    asof = now()

    def esp(btname):
        return bt.get(btname, (btname, None, None))

    def splus(bpm, pos, N=None):
        if bpm is None: return None
        N = N or norms
        mu, sd = N.get(pos) or N['F']
        return round(100 + 25 * (bpm - mu) / sd)

    def age(r):
        return r.get('age') if r.get('age') is not None else r.get('ageEst')

    def spos(r, L=None):
        """the Stat+ position: Barttorvik's role (this line's, else last season's on the board), as the 2025-26 norms and
        the FV driver read it; a newcomer with no role is a C at 6'10" and up (84% of 2025-26 players that tall had a C
        or PF/C role), else his roster position. ESPN's roster labels made 227 qualified centers against 598 on roles"""
        p = POSMAP.get((L or {}).get('role')) or POSMAP.get(r.get('role'))
        if p: return p
        return 'C' if (r.get('mht') or 0) >= 82 else r.get('pos')

    # this season's lines from the board ('now', cbb_live.py)
    cur = []
    for r in B:
        L = r.get('now')
        if not L or not L.get('gp'): continue
        mins = (L['mpg'] or 0) * L['gp']
        cur.append((r, L, mins))
    # this season's Stat+ norms: its own 10%+ minute players by position (team games so far), once LIVE_MIN a position
    pool = [{'pos': spos(r, L), 'bpm': L['bpm'], 'mp': mins / L['gp'], 'gp': L['gp'], 'role': None,
             'min_per': 100 * mins / (40 * (len(tg.get(e2t.get(r['team'], r['team']), ())) or L['gp']))}
            for r, L, mins in cur if L.get('bpm') is not None and spos(r, L) in ('G', 'F', 'C')]
    live_n = {p: sum(1 for l in pool if l['pos'] == p and l['min_per'] >= 10) for p in 'GFC'}
    norms_now = pos_norms(pool, key='pos') if min(live_n.values()) >= LIVE_MIN else None

    # ---- stats
    def srow(n, tm, pos, ag, sub, ph, lo, s, fv=None, N=None, sp=None):
        return {'n': n, 'tm': tm, 'pos': pos, 'age': ag, 'sub': sub or '', 'ph': ph, 'lo': lo, 'fv': fv, 'splus': splus(s['bpm'], sp or pos, N), **s}

    now_rows = []
    for r, L, mins in cur:
        s = {'gp': L['gp'], 'mp': round(mins), 'mpg': L['mpg'], 'pts': L.get('ppg'), 'reb': L.get('rpg'), 'ast_g': L.get('apg'), 'bpm': L['bpm'],
             'obpm': L['obpm'], 'dbpm': L['dbpm'], 'ortg': L['ortg'], 'usg': L['usg'], 'ts': L.get('ts'), 'tp': L['tp'] if L.get('tpa') else None,
             'tpa': L.get('tpa'), 'ft': L.get('ft'), 'astp': L.get('ast'), 'to': L.get('to'), 'stl': L.get('stl'), 'blk': L.get('blk'),
             'orb': L.get('orb'), 'ftr': L.get('ftr'), 'war': r1(war(L['bpm'], mins), 2), 'waa': r1(war(L['bpm'], mins, 0), 2),
             'nx': r1(nx_now.get((r['name'], r['team'])), 2)}
        now_rows.append(srow(r['name'], r['team'], r['pos'], age(r), r['conf'], r.get('photo'), r.get('logo'), s, r['fv'], norms_now, spos(r, L)))
    last_rows = []
    for l in F['lines']:
        r = by_pid.get(l['pid'])
        tm, lo, cf = esp(l['bt'])
        last_rows.append(srow(l['n'], tm, r['pos'] if r else l['pos'], None, l['conf'], r.get('photo') if r else None, lo, {**l['s'], 'nx': nx_last.get(l['pid'])}, r['fv'] if r else None))
    stat_cols = [col('splus', 'Stat+', 'Stat+ = 100 + 25 z; z = BPM against his position\'s (G, F, C) minutes-weighted mean and sd that season (2025-26 until this season has 40 a position), players with 10%+ of team minutes', '0'),
                 col('pts', 'PTS', 'points a game'), col('reb', 'REB', 'rebounds a game'), col('ast_g', 'AST', 'assists a game'),
                 col('bpm', 'BPM', 'Barttorvik box plus-minus: points a 100 possessions over an average D-I player', 's1'),
                 col('obpm', 'OBPM', 'offensive BPM', 's1'), col('dbpm', 'DBPM', 'defensive BPM', 's1'),
                 col('ortg', 'ORtg', 'offensive rating: points produced a 100 possessions used'), col('usg', 'USG%', 'share of team possessions used on the floor'),
                 col('ts', 'TS%', 'true shooting %'), col('tp', '3P%', 'three-point %'), col('tpa', '3PA', 'three-point attempts', 'i'),
                 col('ft', 'FT%', 'free throw %'), col('astp', 'AST%', 'assist rate: share of teammates\' field goals he assisted on the floor'),
                 col('to', 'TO%', 'turnover rate: turnovers a 100 plays', '1', 1, 1), col('stl', 'STL%', 'steal rate: share of opponent possessions'),
                 col('blk', 'BLK%', 'block rate: share of opponent two-point attempts'), col('orb', 'ORB%', 'offensive rebound rate'),
                 col('ftr', 'FTR', 'free throw rate: FTA a 100 FGA'), col('gp', 'G', 'games', 'i'), col('mpg', 'MPG', 'minutes a game'),
                 col('fv', 'FV', 'FV now (the board\'s grade)', 'i')]
    write('stats', {
        'title': 'stats', 'key': 'splus', 'def': '',
        'views': [['splus', 'Stat+', 'Stat+'], ['pts', 'PTS', 'points a game'], ['reb', 'REB', 'rebounds a game'], ['ast_g', 'AST', 'assists a game'],
                  ['bpm', 'BPM', 'box plus-minus'], ['ts', 'TS%', 'true shooting %'], ['tp', '3P%', 'three-point %'], ['stl', 'STL%', 'steal rate'],
                  ['blk', 'BLK%', 'block rate'], ['ortg', 'ORtg', 'offensive rating']],
        'cols': stat_cols, 'pos': ['G', 'F', 'C'],
        'min': {'k': 'mp', 'l': 'min ≥', 'def': 0, 'opts': SOPT},
        'seasons': [{'s': SEASON, 'l': label(SEASON), 'rows': now_rows, 'mdef': mdef(SOPT, 20 * gnow)},
                    {'s': LAST, 'l': label(LAST), 'rows': last_rows, 'mdef': 400}]})

    # ---- WAR leaders
    wcols = [col('war', 'WAR', f"wins over a replacement player: (BPM + {-REPL:.0f}) x minutes / 40 x {PACE / 100:.2f} x {WPP:.4f} wins a point; the slope that makes team WAR + {wf['a']} x games track wins ({wf['teams']:,} team-seasons {label(wf['years'][0])} to {label(wf['years'][1])}, r {wf['r']}); replacement = the 9th man's BPM", 's2'),
             col('waa', 'WAA', 'wins over an average D-I player: BPM x the same minutes and pace', 's2'),
             col('bpm', 'BPM', 'Barttorvik box plus-minus', 's1'), col('splus', 'Stat+', 'BPM against his position, 100 + 25 z', '0'),
             col('nx', 'Next', "next season's WAR at 31 games, if he plays D-I: from this line (to date: by share of games played), the 3-year BPM, minutes share, class, age, seasons, recruit rank, usage and height", 's2'),
             col('mpg', 'MPG', 'minutes a game'), col('gp', 'G', 'games', 'i'), col('fv', 'FV', 'FV now', 'i')]
    WK = ('n', 'tm', 'pos', 'age', 'sub', 'ph', 'lo', 'war', 'waa', 'nx', 'bpm', 'splus', 'mpg', 'gp', 'fv', 'mp')
    slim = lambda rows: [{k: r.get(k) for k in WK} for r in rows]
    write('war', {
        'title': 'WAR leaders', 'key': 'war', 'def': '',
        'views': [['war', 'WAR', 'wins over replacement'], ['waa', 'WAA', 'wins over average'], ['nx', 'Next', "next season's WAR"], ['bpm', 'BPM', 'box plus-minus']],
        'cols': wcols, 'pos': ['G', 'F', 'C'],
        'min': {'k': 'mp', 'l': 'min ≥', 'def': 0, 'opts': [[0, 'any'], [100, '100'], [300, '300'], [600, '600']]},
        'seasons': [{'s': SEASON, 'l': label(SEASON), 'rows': slim(now_rows)}, {'s': LAST, 'l': label(LAST), 'rows': slim(last_rows), 'mdef': 100}]})

    # ---- breakouts: 1st and 2nd year players playing above their preseason projection
    brk = []
    for r, L, mins in cur:
        if r.get('cls') not in ('Fr', 'So'): continue
        P = pre.get((r['name'], r['team'])) or {}
        last = r.get('last') if r.get('cls') == 'So' else None
        xb0 = r.get('xb0') if r.get('xb0') is not None else P.get('xbpm')   # preseason xBPM under today's model
        brk.append({'n': r['name'], 'tm': r['team'], 'pos': r['pos'], 'age': age(r), 'sub': r['cls'], 'ph': r.get('photo'), 'lo': r.get('logo'),
                    'xup': r1(r['xbpm'] - xb0) if xb0 is not None and r.get('xbpm') is not None else None,
                    'over': r1(L['bpm'] - xb0) if xb0 is not None else None, 'bpm': L['bpm'], 'xb0': xb0,
                    'minup': r1(L['mpg'] - last['mpg']) if last else None, 'usgup': r1(L['usg'] - last['usg']) if last else None,
                    'fvup': r['fv'] - P['fv'] if P.get('fv') is not None else None, 'fv': r['fv'], 'mp': round(mins),
                    'pre': P.get('ovr'), 'preL': f"#{P['ovr']}" if P.get('ovr') else ''})
    brk_last = []
    for l in F['lines']:
        p = l.get('prev')
        if l['yr'] != 'So' or not p or not p['mp']: continue
        r = by_pid.get(l['pid'])
        tm, lo, cf = esp(l['bt'])
        s = l['s']
        brk_last.append({'n': l['n'], 'tm': tm, 'pos': r['pos'] if r else l['pos'], 'age': None, 'sub': ('from ' + p['team'] if p['team'] != l['bt'] else 'So'),
                         'ph': r.get('photo') if r else None, 'lo': lo, 'xup': None, 'over': None, 'bpm': s['bpm'], 'xb0': None,
                         'bup': r1(s['bpm'] - p['bpm']), 'minup': r1(s['mpg'] - p['mpg']), 'usgup': r1(s['usg'] - p['usg']),
                         'warup': r1(s['war'] - p['war'], 2), 'fvup': None, 'fv': r['fv'] if r else None, 'mp': s['mp'], 'pre': None, 'preL': ''})
    write('breakouts', {
        'title': 'breakouts', 'key': 'xup', 'def': '',
        'views': [['xup', 'xBPM up', 'live xBPM minus preseason xBPM'], ['over', 'BPM over x', 'BPM minus preseason xBPM'],
                  ['minup', 'MPG up', 'minutes a game over last season'], ['usgup', 'USG up', 'usage over last season'], ['fvup', 'FV up', 'FV now minus preseason FV'],
                  ['warup', 'WAR up', 'WAR over the season before (2025-26)'], ['bup', 'BPM up', 'BPM over the season before (2025-26)']],
        'cols': [col('xup', 'xBPM up', 'projected BPM now (this season blended in by minutes) minus the preseason projection', 's1'),
                 col('over', 'BPM over x', 'BPM to date minus the preseason xBPM', 's1'), col('bpm', 'BPM', 'BPM this season', 's1'),
                 col('xb0', 'xBPM pre', 'preseason projected BPM', 's1'), col('minup', 'MPG up', 'minutes a game over last season (2nd-years)', 's1'),
                 col('usgup', 'USG up', 'usage % over last season (2nd-years)', 's1'), col('warup', 'WAR up', 'WAR over the season before', 's2'),
                 col('bup', 'BPM up', 'BPM over the season before', 's1'), col('fvup', 'FV up', 'FV now minus preseason FV', 's0'),
                 col('fv', 'FV', 'FV now', 'i'), col('mp', 'Min', 'minutes played', 'i')],
        'pre': {'l': 'Pre', 't': 'preseason board rank (FV)'}, 'pos': ['G', 'F', 'C'],
        'min': {'k': 'mp', 'l': 'min ≥', 'def': 0, 'opts': BOPT},
        'seasons': [{'s': SEASON, 'l': label(SEASON), 'rows': brk, 'mdef': mdef(BOPT, 20 * gnow)},
                    {'s': LAST, 'l': label(LAST) + ' (2nd-years)', 'rows': brk_last, 'mdef': 200}]})

    # ---- top performers: best single games by Game Score, a week at a time
    def trow(g, n, btn, pid, opp, date, loc, win, line):
        r = by_pid.get(pid)
        tm, lo, cf = esp(btn)
        d = dt.date(int(date[:4]), int(date[4:6]), int(date[6:]))
        where = 'vs' if loc in ('H', 'N') else 'at'
        return {'n': n, 'tm': tm, 'pos': r['pos'] if r else '', 'age': None, 'ph': r.get('photo') if r else None, 'lo': lo,
                'sub': f"{'W' if win else 'L'} {where} {esp(opp)[0]} · {MON[d.month - 1].lower()} {d.day}", **line}
    weeks = defaultdict(list)
    for g in games:
        d = g[GC['date']]
        day = dt.date(int(d[:4]), int(d[4:6]), int(d[6:]))
        weeks[day - dt.timedelta(days=day.weekday())].append(g)
    wk = []
    for w0 in sorted(weeks, reverse=True):
        gs = sorted(weeks[w0], key=lambda g: -game_score(g))[:150]
        rows = [trow(g, g[GC['name']], g[GC['team']], str(g[GC['pid']]), g[GC['opp']], g[GC['date']], g[GC['loc']], g[GC['win1']], gline(g)) for g in gs]
        wk.append({'s': w0.isoformat(), 'l': f"week of {MON[w0.month - 1].lower()} {w0.day}", 'games': len({g[GC['muid']] for g in weeks[w0]}), 'rows': rows})
    season_best = sorted(games, key=lambda g: -game_score(g))[:150]
    seasons = wk + ([{'s': SEASON, 'l': label(SEASON) + ' season', 'rows': [trow(g, g[GC['name']], g[GC['team']], str(g[GC['pid']]), g[GC['opp']], g[GC['date']], g[GC['loc']], g[GC['win1']], gline(g)) for g in season_best]}] if len(wk) > 1 else [])
    seasons.append({'s': LAST, 'l': label(LAST) + ' season', 'rows': [trow(None, t['n'], t['bt'], t['pid'], t['opp'], t['date'], t['loc'], t['win'],
                                                                           {k: t[k] for k in ('gs', 'pts', 'reb', 'ast', 'stl', 'blk', 'min', 'gbpm', 'fg', 'tp3')}) for t in F['top'][:150]]})
    write('top', {
        'title': 'top performers', 'key': 'gs', 'def': '',
        'views': [['gs', 'GmSc', 'Game Score'], ['pts', 'PTS', 'points'], ['reb', 'REB', 'rebounds'], ['ast', 'AST', 'assists'], ['gbpm', 'gBPM', 'game BPM']],
        'cols': [col('gs', 'GmSc', 'Game Score (Hollinger): PTS + .4 FGM - .7 FGA - .4 (FTA - FTM) + .7 ORB + .3 DRB + STL + .7 AST + .7 BLK - .4 PF - TOV'),
                 col('pts', 'PTS', 'points', 'i'), col('reb', 'REB', 'rebounds', 'i'), col('ast', 'AST', 'assists', 'i'), col('stl', 'STL', 'steals', 'i'),
                 col('blk', 'BLK', 'blocks', 'i'), col('fg', 'FG', 'field goals made-attempted', 's', 0), col('tp3', '3P', 'threes made-attempted', 's', 0),
                 col('min', 'Min', 'minutes', '0'), col('gbpm', 'gBPM', 'Barttorvik game BPM', 's1')],
        'pos': ['G', 'F', 'C'], 'seasons': seasons})

    # ---- draft board: the 2027 draft's prospects, predictive mock order
    M = json.load(open(os.path.join(ROOT, 'data', 'cbb_mock.json')))
    fvby = {(r['name'], r['team']): r for r in B}
    drows = []
    for m in M['mocks']['pred']:
        r = fvby.get((m['name'], m['school'])) or {}
        sim = m.get('sim') or {}
        drows.append({'n': m['name'], 'tm': m['school'], 'pos': m.get('pos') or '', 'age': m.get('age'), 'ph': m.get('photo') or r.get('photo'), 'lo': m.get('logo'),
                      'sub': m.get('cls') or '', 'slot': m['pick'], 'cons': m.get('cons'), 'dec': r1((m.get('declare') or 0) * 100, 0), 'fv': m.get('fv'),
                      'nbaP': r1(r['nbaP'] * 100, 0) if r.get('nbaP') is not None else None, 'xbpm': r.get('xbpm'),
                      'rng': f"{sim['lo']}-{sim['hi']}" if sim.get('lo') else '', 'conv': (m.get('slots') or {}).get('conv'), 'pre': m.get('cons'), 'preL': f"#{m['cons']}" if m.get('cons') else ''})
    for s in M.get('staying') or []:
        r = fvby.get((s['name'], s['school'])) or {}
        drows.append({'n': s['name'], 'tm': s['school'], 'pos': r.get('pos') or '', 'age': age(r) if r else None, 'ph': r.get('photo'), 'lo': r.get('logo'),
                      'sub': (s.get('cls') or '') + ' · stays', 'slot': None, 'cons': s.get('cons'), 'dec': r1((s.get('declare') or 0) * 100, 0), 'fv': r.get('fv'),
                      'nbaP': r1(r['nbaP'] * 100, 0) if r.get('nbaP') is not None else None, 'xbpm': r.get('xbpm'), 'rng': '', 'conv': None,
                      'pre': s.get('cons'), 'preL': f"#{s['cons']}" if s.get('cons') else ''})
    write('draft', {
        'title': 'draft board', 'key': 'slot', 'def': '',
        'views': [['slot', 'Mock', 'predictive mock pick'], ['cons', 'Cons', 'consensus rank across the boards'], ['fv', 'FV', 'FV'], ['dec', 'Declare%', 'chance he enters the 2027 draft']],
        'cols': [col('slot', 'Mock', 'predictive mock pick (consensus + model, Tankathon order)', 'i', 1, 1), col('cons', 'Cons', f"median rank on {M['boards']} 2027 boards", 'i', 1, 1),
                 col('rng', '80%', '80% range of his pick across 2,000 simulated drafts', 's', 0), col('conv', 'Conv', 'conviction mock pick', 'i', 1, 1),
                 col('dec', 'Declare%', 'chance he enters the 2027 draft (declare model)', 'p'), col('fv', 'FV', 'FV now', 'i'),
                 col('nbaP', 'NBA%', 'chance of an NBA career', 'p'), col('xbpm', 'xBPM', 'projected BPM this season', 's1')],
        'pos': ['G', 'F', 'C'],
        'seasons': [{'s': SEASON, 'l': '2027 draft', 'rows': drows}]})

    # ---- portal: D-I transfers into this season, last season's production against their new grade
    last_by = {l['pid']: l for l in F['lines']}
    prow = []
    for r in B:
        L = r.get('last')
        if not L or not L.get('team') or t2e.get(L['team'], L['team']) == r['team'] or L.get('season') != label(LAST): continue
        l = last_by.get(pidof.get((r['name'], r['team'])))
        s = l['s'] if l else None
        fc, tc = L.get('conf'), r.get('conf')
        move = 'up' if tc in POWER and fc not in POWER else 'down' if fc in POWER and tc not in POWER else 'across'
        prow.append({'n': r['name'], 'tm': r['team'], 'pos': r['pos'], 'age': age(r), 'ph': r.get('photo'), 'lo': r.get('logo'), 'div': move,
                     'sub': f"from {t2e.get(L['team'], L['team'])}" + (f" ({fc})" if fc else ''),
                     'war': s['war'] if s else r1(war(L['bpm'], L['gp'] * L['mpg']), 2), 'bpm': L['bpm'], 'mpg': L['mpg'], 'ppg': L.get('ppg'),
                     'splus': splus(L['bpm'], spos(r, L)), 'fv': r['fv'], 'xbpm': r.get('xbpm'), 'bnow': (r.get('now') or {}).get('bpm')})
    write('portal', {
        'title': 'portal', 'key': 'war', 'def': '',
        'views': [['war', 'WAR', 'WAR last season'], ['fv', 'FV', 'FV now'], ['xbpm', 'xBPM', 'projected BPM this season'], ['bpm', 'BPM', 'BPM last season']],
        'cols': [col('war', 'WAR', 'wins over replacement last season (2025-26) at his old school', 's2'), col('bpm', 'BPM', 'BPM last season', 's1'),
                 col('splus', 'Stat+', 'last season\'s BPM against his position, 100 + 25 z', '0'), col('ppg', 'PTS', 'points a game last season'),
                 col('mpg', 'MPG', 'minutes a game last season'), col('xbpm', 'xBPM', 'projected BPM at the new school', 's1'),
                 col('bnow', 'BPM now', 'BPM this season', 's1'), col('fv', 'FV', 'FV now', 'i')],
        'divs': ['up', 'across', 'down'], 'pos': ['G', 'F', 'C'],
        'seasons': [{'s': SEASON, 'l': label(SEASON), 'rows': prow}]})

    teams(B, F, by_pid, pidof, bt, t2e, asof)


def teams(B, F, by_pid, pidof, bt, t2e, asof):
    """returning production and roster talent, one row a team"""
    G = json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))
    power = {p['t']: p for p in G['power']}
    roster = defaultdict(list)
    for r in B:
        roster[r['team']].append(r)
    last_team = defaultdict(list)
    for l in F['lines']:
        last_team[t2e.get(l['bt'], l['bt'])].append(l)
    ret_rows, tal_rows = [], []
    for team, rs in roster.items():
        P = power.get(team)
        if not P: continue
        base = {'id': (P.get('logo') or '').rsplit('/', 1)[-1].split('.')[0], 't': team, 'ab': team, 'lg': P.get('logo'), 'cf': P.get('conf')}
        here = {pidof.get((r['name'], r['team'])) for r in rs}
        ls = last_team.get(team, [])
        tot_min = sum(l['s']['mp'] for l in ls) or 1
        tot_war = sum(l['s']['war'] or 0 for l in ls)
        back = [l for l in ls if l['pid'] in here]
        rmin = sum(l['s']['mp'] for l in back)
        rwar = sum(l['s']['war'] or 0 for l in back)
        tin = [r for r in rs if r.get('last') and r['last'].get('team') and t2e.get(r['last']['team'], r['last']['team']) != team and r['last'].get('season') == label(LAST)]
        last_by = {l['pid']: l for l in F['lines']}
        inwar = 0.0
        for r in tin:
            l = last_by.get(pidof.get((r['name'], r['team'])))
            inwar += (l['s']['war'] or 0) if l else 0
        fr = [r for r in rs if r.get('cls') == 'Fr' and r.get('new')]
        ret_rows.append({**base, 'rmin': round(100 * rmin / tot_min, 1), 'rwar': round(rwar, 1), 'lwar': round(tot_war - rwar, 1), 'inwar': round(inwar, 1),
                         'net': round(rwar + inwar - tot_war, 1), 'ntr': len(tin), 'nfr': len(fr), 'frfv': max([r['fv'] for r in fr], default=None)})
        fvs = sorted([r['fv'] for r in rs if r.get('fv') is not None], reverse=True)
        top8 = fvs[:8]
        tal_rows.append({**base, 'tal': round(sum(top8) / len(top8), 1) if top8 else None, 'top': fvs[0] if fvs else None,
                         'n45': sum(1 for f in fvs if f >= 45), 'xnba': round(sum((r.get('nbaP') or 0) for r in rs), 1),
                         'xb': round(sum(sorted([r.get('xbpm') or -5 for r in rs], reverse=True)[:8]) / 8, 1),
                         'ark': P.get('rating'), 'rk': P.get('rk')})
    # TvE: ARK rank minus talent rank (+ = rated above the talent)
    for k in ('tal',):
        order = sorted(tal_rows, key=lambda r: -(r[k] or 0))
        for i, r in enumerate(order, 1): r['trk'] = i
    for r in tal_rows:
        r['tve'] = r['trk'] - r['rk'] if r.get('rk') else None
        r['up'] = 1
    for r in ret_rows:
        r['up'] = 1 if r['rmin'] >= 50 else 0
    ret_rows.sort(key=lambda r: -r['rmin'])
    tal_rows.sort(key=lambda r: -(r['tal'] or 0))
    for r in tal_rows: r.pop('trk', None); r.pop('rk', None)
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'sport': 'cbb', 'season': SEASON, 'label': label(SEASON), 'src': 'Barttorvik',
           'views': {
               'returning': {'plain': 1, 'about': 'Returning: last season\'s (2025-26) minutes and WAR still on the roster, by Barttorvik player id; transfers in = incoming D-I transfers\' WAR at their old schools. WAR = wins over a replacement player (BPM + 2) x minutes x .68 x wins a point; see the WAR leaders tab.',
                             'cols': [{'k': 'rmin', 'h': 'Ret Min%', 't': 'share of last season\'s minutes returning', 'f': '.1f', 'key': 1},
                                      {'k': 'rwar', 'h': 'Ret WAR', 't': 'last season\'s WAR returning', 'f': '.1f'},
                                      {'k': 'lwar', 'h': 'Lost WAR', 't': 'last season\'s WAR gone (graduated, pro, transferred out)', 'f': '.1f'},
                                      {'k': 'inwar', 'h': 'In WAR', 't': 'incoming D-I transfers\' WAR last season at their old schools', 'f': '.1f'},
                                      {'k': 'net', 'h': 'Net', 't': 'Ret WAR + In WAR - last season\'s WAR: production gained or lost before freshmen', 'f': '+.1f'},
                                      {'k': 'ntr', 'h': 'Trans', 't': 'incoming D-I transfers', 'f': '.0f', 'x': 1},
                                      {'k': 'nfr', 'h': 'Fr', 't': 'true freshmen on the roster', 'f': '.0f', 'x': 1},
                                      {'k': 'frfv', 'h': 'Top Fr FV', 't': 'highest FV among the freshmen', 'f': '.0f', 'x': 1}],
                             'sort': 'rmin', 'rows': ret_rows},
               'talent': {'plain': 1, 'about': 'Talent: mean FV of the eight highest-graded players. xNBA = sum of NBA% on the roster (expected NBA players). xBPM 8 = mean projected BPM of the top eight. TvE = talent rank minus ARK Ranking rank (+ = rated above the talent).',
                          'cols': [{'k': 'tal', 'h': 'Talent', 't': 'mean FV of the eight highest-graded players', 'f': '.1f', 'key': 1},
                                   {'k': 'top', 'h': 'Top FV', 't': 'highest FV on the roster', 'f': '.0f'},
                                   {'k': 'n45', 'h': 'FV 45+', 't': 'players graded FV 45 or better (NBA rotation and up)', 'f': '.0f'},
                                   {'k': 'xnba', 'h': 'xNBA', 't': 'sum of NBA% on the roster: expected NBA players', 'f': '.1f'},
                                   {'k': 'xb', 'h': 'xBPM 8', 't': 'mean projected BPM of the top eight by xBPM', 'f': '+.1f', 'x': 1},
                                   {'k': 'ark', 'h': 'ARK', 't': 'ARK Ranking rating: points a game better than an average D-I team', 'f': '+.1f'},
                                   {'k': 'tve', 'h': 'TvE', 't': 'talent rank minus ARK Ranking rank: + = playing above the roster\'s grades', 'f': '+.0f'}],
                          'sort': 'tal', 'rows': tal_rows}}}
    json.dump(out, open(TEAM_OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print(f'{TEAM_OUT}: {len(ret_rows)} teams')


def clean(x):
    if isinstance(x, float) and x != x: return None
    if isinstance(x, dict): return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list): return [clean(v) for v in x]
    return x


def write(name, d):
    os.makedirs(OUT, exist_ok=True)
    d = clean({'sport': 'cbb', 'asof': now(), **d})
    p = os.path.join(OUT, f'{name}.json')
    json.dump(d, open(p, 'w'), separators=(',', ':'), allow_nan=False)
    print(f'{p}: ' + ', '.join(f"{s['l']} {len(s['rows'])}" for s in d['seasons']))


if __name__ == '__main__':
    main()
