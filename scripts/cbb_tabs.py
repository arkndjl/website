#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball production tabs (Nov 3 2026): the CBB page's equivalents of the CFB stats, VORX, breakout, top
performer, draft board, portal, returning and team talent views. Display only: every number is a season line, a
game line or an existing model output (FV, xBPM, NBA%, the mocks); nothing here feeds the FV model.

    python3 scripts/cbb_tabs.py            # daily: this season from static/data/cbb-all.json + the game logs cache
    python3 scripts/cbb_tabs.py --freeze   # once: 2025-26 (Barttorvik season file + game logs) -> scripts/data/cbb_tabs_2026.json.gz

Outputs
    static/data/cbb/{stats,war,pxpm,breakouts,top,draft,portal}.json   player tables, drawn by layouts/shortcodes/rookies.html (src=)
                                                                    (draft: this draft, then each past draft at draft week, past_drafts)
    data/cbb_teamtabs.json                                          team tables (returning, talent), drawn by teamunits.html (feed=)

Definitions
    VORX   wins over a replacement player on XPM (rXPM) = (XPM - R) x minutes / 40 x 68 / 100 x wins a point. Called WAR
           until Nov 26 2026 (Noah: one name with the NBA's VORX, .030 x (XPM + 1.4) x MP / 48; same replacement, -1.4);
           the json keys stay war / waa / rwar / lwar / inwar. History of the input, oldest first:
           GBPM = Barttorvik's game BPM, the minutes-weighted mean of his games' BPM (the live line sums the game logs the
           same way; BPM when a line has none). Nov 24 2026 (scripts/research/metric_audit_nov24/cbb): GBPM in place of
           season BPM tracks team wins better held out (win% R2 .633 -> .658, 15/15 seasons; VORX form 14/14, t 28.7);
           season BPM stays the predictive input (next-season team R2 .643 against GBPM's .612), so Next is BPM based.
           Nov 24 2026 port round (scripts/research/metric_audit_nov24/port/tennis_cs2_cbb, pre-registered): GBPM is
           shrunk GBPM_K = 100 minutes toward the season's minutes-weighted mean GBPM, (GBPM x min + 100 x mean) / (min
           + 100). Half-A games' rate vs the same players' half-B GBPM: minutes-weighted MSE 16.2 -> 11.4 (10/10 seasons,
           t 8.5); VORX form held-out team wins RMSE 3.348 -> 3.331 (14/14, t 8.2). Season-only (no prior-season input).
           R = -1.6: the minutes-weighted shrunk GBPM of the 9th man in team minutes, 2025-26 (raw GBPM's was -2.3,
           BPM's -2.0).
           wins a point = fit on 2016-17 to 2025-26 team-seasons (FIT_YEARS): wins = a x games + b x team sum of
           (GBPM - R) x minutes / 40 x .68 (b .0186, a .38, r .87 on shrunk GBPM, Nov 24; raw GBPM .0160, .37; BPM .0143, .40; set by
           --freeze and kept in the frozen file). The
           textbook N'(0) / game sd (.0347 at sd 11.5) is the slope at an even game; real seasons bend (conference
           schedules pair strong with strong, win odds flatten at the ends), so the fit slope is what sums to wins.
           Barttorvik BPM is per 100 possessions over an average D-I player, and a team's minutes-weighted BPM x 5
           tracks its net rating, so a player's share of the margin is BPM x his share of the 200 minutes.
           Pace is a flat 68 possessions a 40, not the team's: a faster game's margin swings more, so a point a 100
           possessions buys about the same wins at any pace. Nov 3 2026 (scripts/cbb_war_research_nov03.py): flat beat
           team possessions on held-out team wins in 9 of 10 seasons (t 2.9), and the 10-season slope beat the
           2025-26-only fit (.0124) in 7 of 9 held-out seasons (t 3.4); 2025-26 had the lowest slope of the ten.
           Nov 26 2026 (scripts/research/cbb_xpm_nov26, rXPM round 3): the input is rXPM (scripts/cbb_xpm.py rxpm_lines), each
           side's BPM plus the team's minutes-weighted mean (GBPM - BPM): GBPM's team totals (same team win% R2, .676) with
           BPM's split inside the team (who-sat-out game margins: t 3.0 to 4.9 against GBPM; next-season team R2 .611 ->
           .624). Shrunk the same 100 minutes; R = -1.4, the 9th man's shrunk rXPM; wins a point refit by --freeze. This
           season's shift comes from the game logs (team mean game O/D BPM minus the team's lines' mean O/D BPM), saved in
           scripts/data/cbb_xpm_shift.json for a run with no game logs.
    WAA    the same over an average player (R = 0).
    Stat+  100 + 25 z, z = XPM (rXPM; BPM before Nov 26 2026, r .998) against the minutes-weighted mean and sd of his position (G, F, C) in 2025-26 among
           players with 10%+ of team minutes (the CFB board's Stat+ scale). This season's lines use this season's own
           norms (same pool, LIVE_MIN players a position or the 2025-26 norms): early-season BPM spreads wider (sd
           4.4-5.5 through 8 games against 3.5-4.4 a full season), and its own norms cut the error against the
           full-season Stat+ by about a third (10 of 10 seasons, scripts/cbb_war_research_nov03.py).
    Next   next season's VORX at 31 games (scripts/cbb_next.py; fit by scripts/cbb_next_research.py): 2025-26 rows from
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
import cbb_xpm as XP

SEASON, LAST = 2027, 2026
SD = os.path.join(ROOT, 'static', 'data')
OUT = os.path.join(SD, 'cbb')
TEAM_OUT = os.path.join(ROOT, 'data', 'cbb_teamtabs.json')
FROZEN = os.path.join(HERE, 'data', f'cbb_tabs_{LAST}.json.gz')
PRIOR = os.path.join(HERE, 'cbb_prior.json.gz')
SHIFT = os.path.join(HERE, 'data', 'cbb_xpm_shift.json')   # this season's team rXPM shifts, kept for runs with no game logs (--cols)
REPL = -1.4         # 9th man's shrunk rXPM, 2025-26 (VORX's input; see VORX above; GBPM's was -1.6)
GBPM_K = 100.0      # minutes of shrink toward the season's mean GBPM (VORX's input; see VORX above)
PACE = 68.0        # possessions a 40 for every team (not the team's own pace: see VORX above)
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


def wx(L, mins=None, mu=None):
    """VORX's box input: rXPM (XPM), else GBPM, else BPM (a line with neither); with mins and the season's mean mu, shrunk GBPM_K
    minutes toward mu (see VORX above)"""
    x = L.get('xpm') if L.get('xpm') is not None else L.get('gbpm') if L.get('gbpm') is not None else L.get('bpm')
    if x is None or mins is None or mu is None:
        return x
    return (x * mins + GBPM_K * mu) / (mins + GBPM_K)


def gmu(lines, mins_of=lambda l: (l.get('mp') or 0) * (l.get('gp') or 0)):
    """the minutes-weighted mean of wx over a season's lines (the shrink target)"""
    xs = [(wx(l), mins_of(l)) for l in lines if wx(l) is not None and mins_of(l)]
    w = sum(m for _, m in xs)
    return sum(x * m for x, m in xs) / w if w else None


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
        ls = XP.rxpm_lines(D.load_bt(y)); mu = gmu(ls)
        for l in ls:
            if l['gp'] and l['mp'] and wx(l) is not None:
                mins = l['mp'] * l['gp']
                X[l['team']] += (wx(l, mins, mu) - REPL) * mins / 40 * PACE / 100   # points over replacement
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


def load_shift():
    try:
        d = json.load(open(SHIFT))
        return {t: tuple(v) for t, v in d['teams'].items()} if d.get('season') == SEASON else {}
    except (OSError, ValueError, KeyError):
        return {}


def board_cols(B, pxof):
    """static/data/cbb-all.json gets two columns in place: xpm (this season's rXPM) and pxpm (the preseason pXPM,
    scripts/data/cbb_pxpm_<last>.json). cbb_live.py rewrites the file without them, so every run of it is followed by
    this (cbb-board.yml: the daily build; cbb-boards.yml: --cols)"""
    p = os.path.join(SD, 'cbb-all.json')
    d = json.load(open(p))
    if len(d['rows']) != len(B): return
    for k, f in (('xpm', lambda r: r1((r.get('now') or {}).get('xpm'))), ('pxpm', lambda r: r1((pxof(r) or [None])[0]))):
        if k not in d['cols']: d['cols'].append(k)
        i = d['cols'].index(k)
        for row, r in zip(d['rows'], B):
            row += [None] * (i + 1 - len(row)); row[i] = f(r)
    json.dump(d, open(p, 'w'), separators=(',', ':'))


# ---------------------------------------------------------------- 2025-26, frozen once
def pos_norms(lines, key='role'):
    """Stat+ scale: minutes-weighted mean and sd of BPM by position among 10%+ minute players (key 'role': Barttorvik
    role mapped by POSMAP; 'pos': already G/F/C)"""
    out = {}
    for p in 'GFC':
        xs = [(l['xpm'] if l.get('xpm') is not None else l['bpm'], l['mp'] * l['gp']) for l in lines
              if (POSMAP.get(l['role']) if key == 'role' else l['pos']) == p and (l['min_per'] or 0) >= 10 and l['bpm'] is not None]
        w = sum(m for _, m in xs)
        mu = sum(b * m for b, m in xs) / w
        sd = (sum(m * (b - mu) ** 2 for b, m in xs) / w) ** .5
        out[p] = (round(mu, 3), round(sd, 3))
    return out


def stat_line(L, mu=None):
    """a Barttorvik season row -> the stats-tab numbers (mu: the season's mean GBPM, VORX's shrink target)"""
    mins = (L['mp'] or 0) * (L['gp'] or 0)
    return {'gp': int(L['gp'] or 0), 'mp': round(mins), 'mpg': r1(L['mp']), 'pts': r1(L['pts_g']), 'reb': r1(L['treb_g']), 'ast_g': r1(L['ast_g']),
            'xpm': r1(L.get('xpm')), 'oxpm': r1(L.get('oxpm')), 'dxpm': r1(L.get('dxpm')), 'bpm': r1(L['bpm']), 'gbpm': r1(L.get('gbpm')), 'obpm': r1(L['obpm']), 'dbpm': r1(L['dbpm']), 'ortg': r1(L['ortg']), 'usg': r1(L['usg']), 'ts': r1(L['ts']),
            'tp': r1((L['tp'] or 0) * 100) if L['tpa'] else None, 'tpa': int(L['tpa'] or 0), 'ft': r1((L['ft'] or 0) * 100) if L['fta'] else None,
            'astp': r1(L['ast']), 'to': r1(L['to']), 'stl': r1(L['stl']), 'blk': r1(L['blk']), 'orb': r1(L['orb']), 'ftr': r1(L['ftr']),
            'war': r1(war(wx(L, mins, mu), mins), 2), 'waa': r1(war(wx(L, mins, mu), mins, 0), 2)}


def freeze():
    lines = [l for l in XP.rxpm_lines(D.load_bt(LAST)) if l['gp'] and l['mp'] and l['bpm'] is not None]
    prev = {str(l['pid']): l for l in XP.rxpm_lines(D.load_bt(LAST - 1)) if l['gp'] and l['mp'] and l['bpm'] is not None}
    games = load_games(LAST)
    if not games:
        sys.exit(f'no {LAST} game logs in {D.CACHE}/games: fetch https://barttorvik.com/{LAST}_all_advgames.json.gz there first')
    tempo = team_tempo(games)
    norms = pos_norms(lines)
    global WPP
    fit = fit_wpp()
    WPP = fit['wpp']
    mu_last, mu_prev = gmu(lines), gmu(list(prev.values()))
    out = []
    for L in lines:
        s = stat_line(L, mu_last)
        P = prev.get(str(L['pid']))
        p = None
        if P:
            pm = (P['mp'] or 0) * (P['gp'] or 0)
            p = {'team': P['team'], 'gp': int(P['gp'] or 0), 'mpg': r1(P['mp']), 'bpm': r1(P['bpm']), 'xpm': r1(P.get('xpm')), 'usg': r1(P['usg']), 'mp': round(pm),
                 'war': r1(war(wx(P, pm, mu_prev), pm), 2)}
        out.append({'pid': str(L['pid']), 'n': L['name'], 'bt': L['team'], 'conf': L['conf'], 'yr': L['yr'], 'role': L['role'],
                    'pos': POSMAP.get(L['role'], 'F'), 'ht': L['ht'], 'dob': L['dob'], 'min_per': r1(L['min_per']), 's': s, 'prev': p})
    top = sorted(games, key=lambda g: -game_score(g))[:400]
    tg = [{'n': g[GC['name']], 'bt': g[GC['team']], 'pid': str(g[GC['pid']]), 'opp': g[GC['opp']], 'date': g[GC['date']], 'loc': g[GC['loc']],
           'win': g[GC['win1']], **gline(g)} for g in top]
    os.makedirs(os.path.dirname(FROZEN), exist_ok=True)
    with gzip.open(FROZEN, 'wt') as fh:
        json.dump({'season': LAST, 'asof': now(), 'norms': norms, 'wfit': fit, 'mu': mu_last, 'tempo': {k: round(v, 2) for k, v in tempo.items()}, 'lines': out, 'top': tg},
                  fh, separators=(',', ':'))
    print(f'{FROZEN}: {len(out)} lines, {len(tg)} top games, Stat+ norms {norms}, VORX fit {fit}')


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
    # next season's VORX (scripts/cbb_next.py): last season's rows from the 2025-26 line, this season's from the line to date
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
    # this season's rXPM: each side's BPM plus the team's (game BPM - season BPM) minutes-weighted mean (scripts/cbb_xpm.py)
    ga, sa = defaultdict(lambda: [0.0, 0.0, 0.0]), defaultdict(lambda: [0.0, 0.0, 0.0])
    for g in games:
        m = g[GC['min']] or 0
        if m <= 0 or g[GC['obpm']] is None or g[GC['dbpm']] is None: continue
        q = ga[t2e.get(g[GC['team']], g[GC['team']])]; q[0] += m * g[GC['obpm']]; q[1] += m * g[GC['dbpm']]; q[2] += m
    for r, L, mins in cur:
        if L.get('obpm') is None or L.get('dbpm') is None or not mins: continue
        q = sa[r['team']]; q[0] += mins * L['obpm']; q[1] += mins * L['dbpm']; q[2] += mins
    shift = {t: (ga[t][0] / ga[t][2] - q[0] / q[2], ga[t][1] / ga[t][2] - q[1] / q[2]) for t, q in sa.items() if q[2] and ga.get(t) and ga[t][2]}
    if not shift:
        shift = load_shift()
    else:
        json.dump({'season': SEASON, 'asof': asof, 'teams': {t: [round(o, 3), round(d, 3)] for t, (o, d) in sorted(shift.items())}},
                  open(SHIFT, 'w'), separators=(',', ':'))
    for r, L, mins in cur:
        XP.rxpm_lines([L], team=lambda l: r['team'], shift=shift)
    PX = XP.frozen()
    pxof = lambda r: PX.get(pidof.get((r['name'], r['team'])) or '')
    board_cols(B, pxof)
    if '--cols' in sys.argv:
        return
    # this season's Stat+ norms: its own 10%+ minute players by position (team games so far), once LIVE_MIN a position
    pool = [{'pos': spos(r, L), 'bpm': L['bpm'], 'xpm': L.get('xpm'), 'mp': mins / L['gp'], 'gp': L['gp'], 'role': None,
             'min_per': 100 * mins / (40 * (len(tg.get(e2t.get(r['team'], r['team']), ())) or L['gp']))}
            for r, L, mins in cur if L.get('bpm') is not None and spos(r, L) in ('G', 'F', 'C')]
    live_n = {p: sum(1 for l in pool if l['pos'] == p and l['min_per'] >= 10) for p in 'GFC'}
    norms_now = pos_norms(pool, key='pos') if min(live_n.values()) >= LIVE_MIN else None

    # ---- stats
    def srow(n, tm, pos, ag, sub, ph, lo, s, fv=None, N=None, sp=None):
        return {'n': n, 'tm': tm, 'pos': pos, 'age': ag, 'sub': sub or '', 'ph': ph, 'lo': lo, 'fv': fv, 'splus': splus(s['xpm'] if s.get('xpm') is not None else s['bpm'], sp or pos, N), **s}

    mu_now = gmu([L for _, L, _ in cur], lambda l: (l.get('mpg') or 0) * (l.get('gp') or 0))
    now_rows = []
    for r, L, mins in cur:
        s = {'gp': L['gp'], 'mp': round(mins), 'mpg': L['mpg'], 'pts': L.get('ppg'), 'reb': L.get('rpg'), 'ast_g': L.get('apg'), 'bpm': L['bpm'],
             'xpm': r1(L.get('xpm')), 'oxpm': r1(L.get('oxpm')), 'dxpm': r1(L.get('dxpm')), 'obpm': L['obpm'], 'dbpm': L['dbpm'], 'ortg': L['ortg'], 'usg': L['usg'], 'ts': L.get('ts'), 'tp': L['tp'] if L.get('tpa') else None,
             'tpa': L.get('tpa'), 'ft': L.get('ft'), 'astp': L.get('ast'), 'to': L.get('to'), 'stl': L.get('stl'), 'blk': L.get('blk'),
             'orb': L.get('orb'), 'ftr': L.get('ftr'), 'war': r1(war(wx(L, mins, mu_now), mins), 2), 'waa': r1(war(wx(L, mins, mu_now), mins, 0), 2),
             'nx': r1(nx_now.get((r['name'], r['team'])), 2)}
        now_rows.append(srow(r['name'], r['team'], r['pos'], age(r), r['conf'], r.get('photo'), r.get('logo'), s, r['fv'], norms_now, spos(r, L)))
    last_rows = []
    for l in F['lines']:
        r = by_pid.get(l['pid'])
        tm, lo, cf = esp(l['bt'])
        last_rows.append(srow(l['n'], tm, r['pos'] if r else l['pos'], None, l['conf'], r.get('photo') if r else None, lo, {**l['s'], 'nx': nx_last.get(l['pid'])}, r['fv'] if r else None))
    XT = 'XPM (rXPM): box plus-minus on team totals that track wins; points a 100 possessions over an average D-I player'
    stat_cols = [col('xpm', 'XPM', XT, 's1'), col('oxpm', 'O-XPM', 'offensive XPM', 's1'), col('dxpm', 'D-XPM', 'defensive XPM', 's1'),
                 col('splus', 'Stat+', 'Stat+ = 100 + 25 z; z = XPM against his position\'s (G, F, C) minutes-weighted mean and sd that season (2025-26 until this season has 40 a position), players with 10%+ of team minutes', '0'),
                 col('pts', 'PTS', 'points a game'), col('reb', 'REB', 'rebounds a game'), col('ast_g', 'AST', 'assists a game'),
                 col('bpm', 'BPM', 'Barttorvik box plus-minus: points a 100 possessions over an average D-I player', 's1'),
                 col('ortg', 'ORtg', 'offensive rating: points produced a 100 possessions used'), col('usg', 'USG%', 'share of team possessions used on the floor'),
                 col('ts', 'TS%', 'true shooting %'), col('tp', '3P%', 'three-point %'), col('tpa', '3PA', 'three-point attempts', 'i'),
                 col('ft', 'FT%', 'free throw %'), col('astp', 'AST%', 'assist rate: share of teammates\' field goals he assisted on the floor'),
                 col('to', 'TO%', 'turnover rate: turnovers a 100 plays', '1', 1, 1), col('stl', 'STL%', 'steal rate: share of opponent possessions'),
                 col('blk', 'BLK%', 'block rate: share of opponent two-point attempts'), col('orb', 'ORB%', 'offensive rebound rate'),
                 col('ftr', 'FTR', 'free throw rate: FTA a 100 FGA'), col('gp', 'G', 'games', 'i'), col('mpg', 'MPG', 'minutes a game'),
                 col('fv', 'FV', 'FV now (the board\'s grade)', 'i')]
    write('stats', {
        'title': 'stats', 'key': 'xpm', 'def': '',
        'views': [['xpm', 'XPM', 'XPM'], ['oxpm', 'O-XPM', 'offensive XPM'], ['dxpm', 'D-XPM', 'defensive XPM'], ['splus', 'Stat+', 'Stat+'], ['pts', 'PTS', 'points a game'], ['reb', 'REB', 'rebounds a game'], ['ast_g', 'AST', 'assists a game'],
                  ['ts', 'TS%', 'true shooting %'], ['tp', '3P%', 'three-point %'], ['stl', 'STL%', 'steal rate'],
                  ['blk', 'BLK%', 'block rate'], ['ortg', 'ORtg', 'offensive rating']],
        'cols': stat_cols, 'pos': ['G', 'F', 'C'],
        'min': {'k': 'mp', 'l': 'min ≥', 'def': 0, 'opts': SOPT},
        'seasons': [{'s': SEASON, 'l': label(SEASON), 'rows': now_rows, 'mdef': mdef(SOPT, 20 * gnow)},
                    {'s': LAST, 'l': label(LAST), 'rows': last_rows, 'mdef': 400}]})

    # ---- VORX leaders
    wcols = [col('war', 'VORX', f"wins over a replacement player: (XPM + {-REPL:.1f}) x minutes / 40 x {PACE / 100:.2f} x {WPP:.4f} wins a point; the slope that makes team VORX + {wf['a']} x games track wins ({wf['teams']:,} team-seasons {label(wf['years'][0])} to {label(wf['years'][1])}, r {wf['r']}); XPM shrunk {GBPM_K:.0f} minutes toward the season's mean; replacement = the 9th man's XPM, so a team of replacement players wins {wf['a'] * 100:.1f}% of its games", 's2'),
             col('waa', 'WAA', 'wins over an average D-I player: XPM x the same minutes and pace', 's2'),
             col('xpm', 'XPM', XT, 's1'), col('oxpm', 'O-XPM', 'offensive XPM', 's1'), col('dxpm', 'D-XPM', 'defensive XPM', 's1'),
             col('splus', 'Stat+', 'XPM against his position, 100 + 25 z', '0'),
             col('nx', 'Next', "next season's VORX at 31 games, if he plays D-I: from this line (to date: by share of games played), his pXPM, minutes share, class, age, seasons, recruit rank, usage and height", 's2'),
             col('mpg', 'MPG', 'minutes a game'), col('gp', 'G', 'games', 'i'), col('fv', 'FV', 'FV now', 'i')]
    WK = ('n', 'tm', 'pos', 'age', 'sub', 'ph', 'lo', 'war', 'waa', 'nx', 'xpm', 'oxpm', 'dxpm', 'splus', 'mpg', 'gp', 'fv', 'mp')
    slim = lambda rows: [{k: r.get(k) for k in WK} for r in rows]
    write('war', {
        'title': 'VORX/XPM leaders', 'key': 'war', 'def': '',
        'views': [['war', 'VORX', 'wins over replacement'], ['waa', 'WAA', 'wins over average'], ['xpm', 'XPM', 'XPM'], ['oxpm', 'O-XPM', 'offensive XPM'], ['dxpm', 'D-XPM', 'defensive XPM'], ['nx', 'Next', "next season's VORX"]],
        'cols': wcols, 'pos': ['G', 'F', 'C'],
        'min': {'k': 'mp', 'l': 'min ≥', 'def': 0, 'opts': [[0, 'any'], [100, '100'], [300, '300'], [600, '600']]},
        'seasons': [{'s': SEASON, 'l': label(SEASON), 'rows': slim(now_rows)}, {'s': LAST, 'l': label(LAST), 'rows': slim(last_rows), 'mdef': 100}]})

    # ---- pXPM: the preseason projection of every player with a D-I season behind him
    PT = "pXPM: projected XPM this season from his last three seasons, minutes, class, box profile, team and recruit rating; fit to next-season BPM, frozen before the season"
    lastx = {l['pid']: l['s'].get('xpm') for l in F['lines']}
    prows = []
    for r in B:
        px = pxof(r)
        if not px: continue
        L = r.get('now') or {}
        m = (L.get('mpg') or 0) * (L.get('gp') or 0)
        prows.append({'n': r['name'], 'tm': r['team'], 'pos': r['pos'], 'age': age(r), 'sub': r.get('cls') or '', 'ph': r.get('photo'), 'lo': r.get('logo'),
                      'pxpm': r1(px[0]), 'opx': r1(px[1]), 'dpx': r1(px[2]), 'lxpm': lastx.get(pidof.get((r['name'], r['team']))),
                      'xpm': r1(L.get('xpm')) if m >= 50 else None, 'fv': r['fv'], 'mp': round(m)})
    write('pxpm', {
        'title': 'pXPM', 'key': 'pxpm', 'def': '',
        'views': [['pxpm', 'pXPM', 'projected XPM'], ['opx', 'O-pXPM', 'projected offensive XPM'], ['dpx', 'D-pXPM', 'projected defensive XPM']],
        'cols': [col('pxpm', 'pXPM', PT, 's1'), col('opx', 'O-pXPM', 'offensive pXPM', 's1'), col('dpx', 'D-pXPM', 'defensive pXPM', 's1'),
                 col('lxpm', 'XPM 25-26', 'XPM last season', 's1'), col('xpm', 'XPM now', 'XPM this season (50+ minutes)', 's1'), col('fv', 'FV', 'FV now', 'i')],
        'pos': ['G', 'F', 'C'], 'seasons': [{'s': SEASON, 'l': label(SEASON), 'rows': prows}]})

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
                    # against the preseason grade under today's model (cbb_live fv0), not the Oct 26 file's grade
                    'fvup': r['fv'] - (r['fv0'] if r.get('fv0') is not None else P['fv']) if (r.get('fv0') is not None or P.get('fv') is not None) else None,
                    'fv': r['fv'], 'mp': round(mins),
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
                  ['warup', 'VORX up', 'VORX over the season before (2025-26)'], ['bup', 'BPM up', 'BPM over the season before (2025-26)']],
        'cols': [col('xup', 'xBPM up', 'projected BPM now (this season blended in by minutes) minus the preseason projection', 's1'),
                 col('over', 'BPM over x', 'BPM to date minus the preseason xBPM', 's1'), col('bpm', 'BPM', 'BPM this season', 's1'),
                 col('xb0', 'xBPM pre', 'preseason projected BPM', 's1'), col('minup', 'MPG up', 'minutes a game over last season (2nd-years)', 's1'),
                 col('usgup', 'USG up', 'usage % over last season (2nd-years)', 's1'), col('warup', 'VORX up', 'VORX over the season before', 's2'),
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
                      'sub': m.get('cls') or '', 'slot': m['pick'], 'cons': m.get('cons'), 'ret': r1((1 - (m.get('declare') or 0)) * 100, 0), 'fv': m.get('fv'),
                      'nbaP': r1(r['nbaP'] * 100, 0) if r.get('nbaP') is not None else None, 'xbpm': r.get('xbpm'),
                      'rng': f"{sim['lo']}-{sim['hi']}" if sim.get('lo') else '', 'conv': (m.get('slots') or {}).get('conv')})
    for s in M.get('staying') or []:
        r = fvby.get((s['name'], s['school'])) or {}
        drows.append({'n': s['name'], 'tm': s['school'], 'pos': r.get('pos') or '', 'age': age(r) if r else None, 'ph': r.get('photo'), 'lo': r.get('logo'),
                      'sub': (s.get('cls') or '') + ' · stays', 'slot': None, 'cons': s.get('cons'), 'ret': r1((1 - (s.get('declare') or 0)) * 100, 0), 'fv': r.get('fv'),
                      'nbaP': r1(r['nbaP'] * 100, 0) if r.get('nbaP') is not None else None, 'xbpm': r.get('xbpm'), 'rng': '', 'conv': None})
    write('draft', {
        'title': 'draft board', 'key': 'slot',
        'def': 'past drafts: the board in draft week. FV = draft-day grade (scripts/cbb_draftday.py: season just played + the June boards; '
               'college exits 2009-16 graded by fits that held out his class, later exits by the fit on 2009-16), Cons = consensus of '
               'the ESPN and NBADraft.net final boards, Pick = actual NBA pick, Out = the career on the FV scale (drafts through 2020).',
        'views': [['slot', 'Mock', 'predictive mock pick'], ['cons', 'Cons', 'consensus rank across the boards'], ['fv', 'FV', 'FV'], ['ret', 'Ret%', 'chance he returns to school instead of entering the 2027 draft'],
                  ['out', 'Out', 'what he became: NBA career on the FV scale']],
        'cols': [col('slot', 'Mock', 'predictive mock pick (consensus + model, Tankathon order)', 'i', 1, 1),
                 col('cons', 'Cons', f"consensus rank: median on {M['boards']} 2027 boards; past drafts, ESPN and NBADraft.net final boards", 'i', 1, 1),
                 col('rng', '80%', '80% range of his pick across 2,000 simulated drafts', 's', 0), col('conv', 'Conv', 'conviction mock pick', 'i', 1, 1),
                 col('ret', 'Ret%', 'chance he returns to school instead of entering the 2027 draft (1 - declare model; seniors and internationals 0)', 'p'), col('fv', 'FV', 'FV now', 'i'),
                 col('nbaP', 'NBA%', 'chance of an NBA career', 'p'), col('xbpm', 'xBPM', 'projected BPM this season', 's1'),
                 col('out', 'Out', 'what he became: NBA career on the FV scale (drafts through 2020, six NBA seasons or more)', 'i'),
                 col('role', 'Career', 'NBA career: peak XPM and role', 's', 0)],
        'pre': {'l': 'Pick', 't': 'actual NBA pick (UDFA: undrafted)'},
        'pos': ['G', 'F', 'C'],
        'seasons': [{'s': SEASON, 'l': '2027 draft', 'rows': drows}] + past_drafts(esp)})

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
                     'pxpm': r1((pxof(r) or [None])[0]), 'xpm': s.get('xpm') if s else None, 'xnow': r1((r.get('now') or {}).get('xpm')),
                     'war': s['war'] if s else r1(war(wx(L, L['gp'] * L['mpg'], F.get('mu')), L['gp'] * L['mpg']), 2), 'bpm': L['bpm'], 'mpg': L['mpg'], 'ppg': L.get('ppg'),
                     'splus': splus(s['xpm'] if s and s.get('xpm') is not None else L['bpm'], spos(r, L)), 'fv': r['fv']})
    write('portal', {
        'title': 'portal', 'key': 'pxpm', 'def': '',
        'views': [['pxpm', 'pXPM', 'projected XPM at the new school'], ['war', 'VORX', 'VORX last season'], ['fv', 'FV', 'FV now'], ['xpm', 'XPM', 'XPM last season']],
        'cols': [col('pxpm', 'pXPM', PT, 's1'), col('war', 'VORX', 'wins over replacement last season (2025-26) at his old school', 's2'),
                 col('xpm', 'XPM', 'XPM last season', 's1'),
                 col('splus', 'Stat+', 'last season\'s XPM against his position, 100 + 25 z', '0'), col('ppg', 'PTS', 'points a game last season'),
                 col('mpg', 'MPG', 'minutes a game last season'),
                 col('xnow', 'XPM now', 'XPM this season', 's1'), col('fv', 'FV', 'FV now', 'i')],
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
               'returning': {'plain': 1, 'about': 'Returning: last season\'s (2025-26) minutes and VORX still on the roster, by Barttorvik player id; transfers in = incoming D-I transfers\' VORX at their old schools. VORX = wins over a replacement player (XPM + 1.4) x minutes x .68 x wins a point; see the VORX leaders tab.',
                             'cols': [{'k': 'rmin', 'h': 'Ret Min%', 't': 'share of last season\'s minutes returning', 'f': '.1f', 'key': 1},
                                      {'k': 'rwar', 'h': 'Ret VORX', 't': 'last season\'s VORX returning', 'f': '.1f'},
                                      {'k': 'lwar', 'h': 'Lost VORX', 't': 'last season\'s VORX gone (graduated, pro, transferred out)', 'f': '.1f'},
                                      {'k': 'inwar', 'h': 'In VORX', 't': 'incoming D-I transfers\' VORX last season at their old schools', 'f': '.1f'},
                                      {'k': 'net', 'h': 'Net', 't': 'Ret VORX + In VORX - last season\'s VORX: production gained or lost before freshmen', 'f': '+.1f'},
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


def past_drafts(esp):
    """each past draft (2009 on) at draft week, from the all-time list's draft-day grades (scripts/data/cbb_draftday.json.gz):
    the college players who left that season and the internationals drafted or on the final boards, if on a June
    board or picked. The grade only uses what was known in draft week; the player's own class never trains it."""
    import names as NM
    R = json.load(gzip.open(os.path.join(HERE, 'data', 'cbb_draftday.json.gz')))['rows']
    picks = {}
    for yr, lst in json.load(open(os.path.join(HERE, 'nba_draft.json'))).items():
        for pk, _, n, _ in lst: picks.setdefault((int(yr), NM.key(n)), pk)
    by = defaultdict(list)
    for r in R:
        s = r['draft'] if r['cls'] == 'Intl' else r['season']
        if not s or r['status'] == 'college': continue
        pk = r['pick'] if r.get('draft') == s and r.get('pick') else picks.get((s, NM.key(r['name'])))
        if pk is None and r.get('june') is None: continue
        tm, lo, _ = esp(r['team']) if r['cls'] != 'Intl' else (r['team'] or 'International', None, None)
        by[s].append({'n': r['name'], 'tm': tm, 'pos': r['pos'] or '', 'age': None, 'ph': None, 'lo': lo, 'sub': r['cls'],
                      'cons': r.get('june'), 'fv': r['fv'], 'out': r.get('out'), 'role': r.get('role') or None,
                      'pre': pk, 'preL': f'#{pk}' if pk else 'UDFA'})
    return [{'s': s, 'l': f'{s} draft', 'key': 'fv', 'rows': sorted(by[s], key=lambda r: (-r['fv'], r['cons'] or 999))}
            for s in sorted(by, reverse=True) if s < SEASON]


def write(name, d):
    os.makedirs(OUT, exist_ok=True)
    d = clean({'sport': 'cbb', 'asof': now(), **d})
    p = os.path.join(OUT, f'{name}.json')
    json.dump(d, open(p, 'w'), separators=(',', ':'), allow_nan=False)
    print(f'{p}: ' + ', '.join(f"{s['l']} {len(s['rows'])}" for s in d['seasons']))


if __name__ == '__main__':
    main()
