#!/usr/bin/env python3
"""Team unit ratings for the teams group of every ARKBOARD sport page (Noah, Nov 2 2026: "team offense, defense sections
for each sport as well as stuff like power play and penalty kill for NHL"; "formation analysis for CFB/NFL").

    python3 scripts/team_units.py nfl|cfb|nba|cbb|nhl|soccer      # -> data/units_<sport>.json

Display only: none of this feeds a game model or a pick. Every headline rating ("Adj") is opponent-adjusted and shrunk
the same way, by one ridge fit a sport and metric on game-level rows (one row per team per game per side):

    rate(game) = mu + b x home + O[offense] + D[defense] + e,  weighted by exposure (plays, possessions, minutes)
    penalty k_o x sum O^2 + k_d x sum D^2

so a team's offense is its rate against an average defense on a neutral field, held toward the league by k exposure
units. k = the exposure at which a season-to-date rate is half signal: split-half reliability of the raw rate on the
last full season (odd vs even games, r = E_half / (E_half + k), so k = E_half (1 - r) / r), the recipe of the team
badges (scripts/team_badges.py) and the special teams rating (scripts/st_teams.py). Early in a season the league
mean dominates; by midseason the team's own rate does.

Other columns are this season's raw rates (style, usage, situational rates) with their counts; split EPA columns are
shrunk toward the league's split mean with the same k.

Sources and views (data/units_<sport>.json 'views', one tab each in the teams group; shortcode teamunits.html):
  nfl     nflverse pbp (k from 2023-25 split halves): offense, defense (EPA a play, dropback / run EPA, success rate,
          PROE, red zone TD%, 3rd down, sacks, turnovers), formations + fronts (FTN charting: shotgun / under center /
          pistol, motion, play action, RPO, screens, no-huddle, blitz rate, rushers, box count, EPA splits)
  cfb     ESPN pbp, an EP model of our own (bins of down x distance x yards to goal, value = net drive points: own drive
          minus the other side's next drive in the half; a play's EPA = next snap's EP - this one's, the drive's last
          snap takes the drive's result, so a drive sums to its net). Garbage time out (Connelly: 38+ in Q2, 28+ Q3,
          22+ Q4). formations: shotgun and no-huddle from the play text (team-consistent home and away), tempo
  nhl     MoneyPuck game logs (k from the three seasons before): 5-on-5 score/venue adjusted xG, 5-on-4 for the power
          play and 4-on-5 for the kill (opponent = the unit faced); PP% / PK% from the NHL stats API
  nba     ESPN box scores (four factors, possessions), rating fit k from scripts/nba_games_hist.json.gz (2024-26)
  cbb     Barttorvik team results + team slice (AdjO/AdjD, four factors), ARK O / D from data/cbb_games.json
  soccer  FotMob match xG (non-penalty, open play, set piece), 18 leagues, ridge a league; k by method of moments on
          this season (within-team match variance / between-team variance), the median over leagues

Reliability at build (Nov 2 2026): NFL offense EPA k 236 plays (r .60), defense 902 (r .29); CFB 239 / 255 plays
(r .62 / .60); NHL 5-on-5 xGF 11 hours (r .76), xGA 17 (r .71), power play 5.5 (r .44), penalty kill 55 (r .10: shot
quality against on the kill barely repeats, so its Adj sits near the league); NBA 1,399 / 1,201 possessions
(r .78 / .75); soccer npxG 4.9 / 10.4 matches, set pieces 17 / 28.
"""
import collections
import csv
import datetime
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fl(x, d=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except (TypeError, ValueError):
        return d


def rnd(x, n=3):
    return None if x is None or not math.isfinite(x) else round(float(x), n)


# ------------------------------------------------------------------ engine
def ridge(obs, ko, kd, home=True):
    """obs: [{'o', 'd', 'h' (+1 offense at home, -1 away, 0 neutral), 'v' (sum), 'e' (exposure)}].
    Returns mu, O {team: effect}, D {team: effect}, b (home), all in rate units (v per e)."""
    obs = [x for x in obs if x['e'] > 0]
    if not obs:
        return 0.0, {}, {}, 0.0
    T = sorted({x['o'] for x in obs} | {x['d'] for x in obs})
    ix = {t: i for i, t in enumerate(T)}
    n = len(T)
    P = 2 + 2 * n
    A = np.zeros((P, P)); y = np.zeros(P)
    for x in obs:
        r = np.zeros(P); r[0] = 1; r[1] = x['h'] if home else 0
        r[2 + ix[x['o']]] = 1; r[2 + n + ix[x['d']]] = 1
        w = x['e']; v = x['v'] / x['e']
        A += w * np.outer(r, r); y += w * v * r
    for i in range(n):
        A[2 + i, 2 + i] += ko; A[2 + n + i, 2 + n + i] += kd
    A[1, 1] += 1e-6
    s = np.linalg.solve(A, y)
    return float(s[0]), {t: float(s[2 + ix[t]]) for t in T}, {t: float(s[2 + n + ix[t]]) for t in T}, float(s[1])


def split_k(obs, side, kmin=1.0):
    """k from split-half reliability of raw team rates: games alternate into two halves in date order"""
    by = collections.defaultdict(list)
    for x in obs:
        if x['e'] > 0:
            by[x[side]].append(x)
    a, b, eh = [], [], []
    for t, xs in by.items():
        xs.sort(key=lambda x: x.get('date', ''))
        h1, h2 = xs[0::2], xs[1::2]
        e1, e2 = sum(x['e'] for x in h1), sum(x['e'] for x in h2)
        if e1 <= 0 or e2 <= 0 or len(xs) < 6:
            continue
        a.append(sum(x['v'] for x in h1) / e1); b.append(sum(x['v'] for x in h2) / e2); eh.append((e1 + e2) / 2)
    if len(a) < 8:
        return None, None
    r = float(np.corrcoef(a, b)[0, 1])
    r = min(0.95, max(0.05, r))
    E = float(np.mean(eh))
    return max(kmin, E * (1 - r) / r), r


def fit_metric(cur, prev, home=True, kdef=None):
    """ratings for one metric: k from last season's split halves (both sides), fit on this season.
    Returns {'mu', 'O', 'D', 'ko', 'kd', 'ro', 'rd'}"""
    # prev: last season's rows, or a list of seasons' (k is then the median of the seasons' k, r their mean)
    seasons = prev if (prev and isinstance(prev[0], list)) else ([prev] if prev else [])

    def pooled(side):
        ks = [x for x in (split_k(p_, side) for p_ in seasons) if x[0] is not None]
        if not ks:
            return None, None
        return float(np.median([x[0] for x in ks])), float(np.mean([x[1] for x in ks]))
    ko, ro = pooled('o')
    kd, rd = pooled('d')
    ko = ko or kdef or 100.0
    kd = kd or kdef or 100.0
    mu, O, D, b = ridge(cur, ko, kd, home)
    return {'mu': mu, 'O': O, 'D': D, 'b': b, 'ko': ko, 'kd': kd, 'ro': ro, 'rd': rd}


def shrink(v, n, mean, k):
    return None if n <= 0 and k <= 0 else (v + mean * k) / (n + k)


def pct_rank(vals, hi=True):
    """percentile (0-100) of each value among the list, best = 100"""
    xs = sorted(v for v in vals if v is not None)
    out = []
    for v in vals:
        if v is None:
            out.append(None); continue
        below = sum(1 for z in xs if (z < v if hi else z > v))
        out.append(round(100 * below / max(1, len(xs) - 1)))
    return out


def save(sport, obj):
    p = os.path.join(ROOT, 'data', f'units_{sport}.json')
    old = None
    if os.path.exists(p):
        try:
            old = json.load(open(p))
        except ValueError:
            old = None
    if old and {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in obj.items() if k != 'asof'}:
        print(sport, 'unchanged'); return
    with open(p, 'w') as f:
        json.dump(obj, f, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', p, os.path.getsize(p), 'bytes')


def col(k, h, t, f='+.2f', x=False, lo=False, key=False):
    """a table column: key k in the rows, header h, tooltip t, format f, x = hidden on phones, lo = lower is better"""
    c = {'k': k, 'h': h, 't': t, 'f': f}
    if x:
        c['x'] = 1
    if lo:
        c['lo'] = 1
    if key:
        c['key'] = 1
    return c


def finish_view(rows, cols, sort, lo=False, plain=False, group=False):
    """sort rows by the key column (best first). plain: a style column (usage), not coloured better/worse"""
    rows.sort(key=lambda r: (r.get(sort) is None, (r.get(sort) or 0) * (1 if lo else -1)))
    if not plain:      # 'up': the key is better than its league's mean (soccer: the team's own league)
        grp = collections.defaultdict(list)
        for r in rows:
            if r.get(sort) is not None:
                grp[r.get('cf') if group else 0].append(r[sort])
        for r in rows:
            if r.get(sort) is not None:
                m = sum(grp[r.get('cf') if group else 0]) / len(grp[r.get('cf') if group else 0])
                r['up'] = 1 if ((r[sort] <= m) if lo else (r[sort] >= m)) else 0
    v = {'cols': cols, 'sort': sort, 'rows': rows}
    if plain:
        v['plain'] = 1
    return v


# ------------------------------------------------------------------ NFL
NFL_FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}


def nfl_rows(season, fresh=False):
    import nfl_war as W
    p = W.get(f'play_by_play_{season}.csv.gz', f'{W.REL}/pbp/play_by_play_{season}.csv.gz', fresh=fresh)
    out = []
    with gzip.open(p, 'rt', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r['season_type'] != 'REG':
                continue
            out.append(r)
    return out


def season_now_nfl():
    d = datetime.date.today()
    return d.year if d.month >= 8 else d.year - 1


def nfl_ftn(season, fresh=False):
    import nfl_war as W
    try:
        p = W.get(f'ftn_charting_{season}.csv', f'{W.REL}/ftn_charting/ftn_charting_{season}.csv', fresh=fresh)
    except Exception as e:  # noqa: BLE001
        print('ftn charting unavailable', season, e)
        return {}
    out = {}
    with open(p, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            out[(r['nflverse_game_id'], r['nflverse_play_id'])] = r
    return out


def nfl_obs(rows):
    """game-level rows per metric from nflverse pbp: offense side o, defense side d"""
    M = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))   # metric -> (gid,o) -> [v, e]
    meta = {}
    T = lambda t: NFL_FR.get(t, t)
    for r in rows:
        pt = r['play_type']
        if pt not in ('run', 'pass'):
            continue
        epa, wp = fl(r['epa']), fl(r['wp'])
        if epa is None or wp is None:
            continue
        o, d = T(r['posteam']), T(r['defteam'])
        if not o or not d:
            continue
        g = r['game_id']
        meta[(g, o)] = (d, 1 if o == T(r['home_team']) else -1, r['game_date'])
        if not (0.05 <= wp <= 0.95):
            continue
        succ = fl(r['success'], 0.0)
        M['epa'][(g, o)][0] += epa; M['epa'][(g, o)][1] += 1
        M['sr'][(g, o)][0] += succ; M['sr'][(g, o)][1] += 1
        k = 'pass' if pt == 'pass' else 'rush'
        M[k][(g, o)][0] += epa; M[k][(g, o)][1] += 1
    obs = {}
    for m, D in M.items():
        obs[m] = [{'o': o, 'd': meta[(g, o)][0], 'h': meta[(g, o)][1], 'date': meta[(g, o)][2], 'v': v, 'e': e}
                  for (g, o), (v, e) in D.items()]
    return obs


def nfl(fresh=True):
    S = season_now_nfl()
    cur = nfl_rows(S, fresh=fresh)
    oc, ops = nfl_obs(cur), [nfl_obs(nfl_rows(S - i)) for i in (1, 2, 3)]
    R = {m: fit_metric(oc[m], [op[m] for op in ops]) for m in ('epa', 'sr', 'pass', 'rush')}
    T = lambda t: NFL_FR.get(t, t)
    # raw counts this season
    C = collections.defaultdict(collections.Counter)
    games = collections.defaultdict(set)
    drives = {}
    week = 0
    for r in cur:
        pt = r['play_type']
        o, d = T(r['posteam']), T(r['defteam'])
        if not o or not d:
            continue
        g = r['game_id']; week = max(week, int(r['week'] or 0))
        if pt in ('run', 'pass'):
            games[o].add(g); games[d].add(g)
            y = fl(r['yards_gained'], 0.0)
            ex = (pt == 'pass' and y >= 20) or (pt == 'run' and y >= 10)
            for side, t in (('o', o), ('d', d)):
                c = C[t]
                c[side + 'plays'] += 1; c[side + 'yds'] += y; c[side + 'ex'] += ex
                if pt == 'pass':
                    c[side + 'db'] += 1; c[side + 'sack'] += r['sack'] == '1'
                xp = fl(r['xpass'])
                if xp is not None and fl(r['wp'], 0.5) >= 0.1 and fl(r['wp'], 0.5) <= 0.9 and r['down'] in ('1', '2'):
                    c[side + 'xpn'] += 1; c[side + 'xp'] += xp; c[side + 'pp'] += pt == 'pass'
                if r['interception'] == '1' or r['fumble_lost'] == '1':
                    c[side + 'to'] += 1
        if r['down'] == '3' and (r['third_down_converted'] == '1' or r['third_down_failed'] == '1'):
            for side, t in (('o', o), ('d', d)):
                C[t][side + '3a'] += 1; C[t][side + '3c'] += r['third_down_converted'] == '1'
        if r['fixed_drive'] and pt in ('run', 'pass'):
            key = (g, r['fixed_drive'], o)
            yl = fl(r['yardline_100'], 100)
            dv = drives.setdefault(key, {'o': o, 'd': d, 'min': 100, 'res': r['fixed_drive_result']})
            dv['min'] = min(dv['min'], yl)
    for dv in drives.values():
        if dv['min'] <= 20:
            for side, t in (('o', dv['o']), ('d', dv['d'])):
                C[t][side + 'rz'] += 1; C[t][side + 'rztd'] += dv['res'] == 'Touchdown'
    teams = sorted(t for t in games if t)
    off, dfn = [], []
    q = lambda a, b: (a / b) if b else None
    for t in teams:
        c = C[t]; g = len(games[t])
        e, s_, pa, ru = R['epa'], R['sr'], R['pass'], R['rush']
        off.append({'t': t, 'ab': t, 'g': g,
                    'adj': rnd(e['mu'] + e['O'].get(t, 0)), 'pass': rnd(pa['mu'] + pa['O'].get(t, 0)),
                    'rush': rnd(ru['mu'] + ru['O'].get(t, 0)), 'sr': rnd(100 * (s_['mu'] + s_['O'].get(t, 0)), 1),
                    'ypp': rnd(q(c['oyds'], c['oplays']), 2), 'ex': rnd(100 * q(c['oex'], c['oplays']), 1),
                    'proe': rnd(100 * (q(c['opp'], c['oxpn']) - q(c['oxp'], c['oxpn'])), 1) if c['oxpn'] else None,
                    'rz': rnd(100 * q(c['orztd'], c['orz']), 1) if c['orz'] else None, 'rzn': c['orz'],
                    'd3': rnd(100 * q(c['o3c'], c['o3a']), 1) if c['o3a'] else None,
                    'sk': rnd(100 * q(c['osack'], c['odb']), 1) if c['odb'] else None,
                    'to': rnd(q(c['oto'], g), 2), 'plays': c['oplays']})
        dfn.append({'t': t, 'ab': t, 'g': g,
                    'adj': rnd(e['mu'] + e['D'].get(t, 0)), 'pass': rnd(pa['mu'] + pa['D'].get(t, 0)),
                    'rush': rnd(ru['mu'] + ru['D'].get(t, 0)), 'sr': rnd(100 * (s_['mu'] + s_['D'].get(t, 0)), 1),
                    'ypp': rnd(q(c['dyds'], c['dplays']), 2), 'ex': rnd(100 * q(c['dex'], c['dplays']), 1),
                    'rz': rnd(100 * q(c['drztd'], c['drz']), 1) if c['drz'] else None, 'rzn': c['drz'],
                    'd3': rnd(100 * q(c['d3c'], c['d3a']), 1) if c['d3a'] else None,
                    'sk': rnd(100 * q(c['dsack'], c['ddb']), 1) if c['ddb'] else None,
                    'to': rnd(q(c['dto'], g), 2), 'plays': c['dplays']})
    k = R['epa']
    oc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"EPA a play, opponent-adjusted and shrunk: against an average defense on a neutral field, held toward the league by {k['ko']:.0f} plays (split-half r {k['ro'] or 0:.2f}); win chance 5-95% only; the rank", '+.3f', key=True),
           col('pass', 'Pass', 'EPA a dropback (passes, sacks, scrambles), adjusted the same way', '+.3f'),
           col('rush', 'Rush', 'EPA a designed run, adjusted the same way', '+.3f'),
           col('sr', 'SR%', 'success rate, adjusted: plays with positive EPA', '.1f'),
           col('ypp', 'Y/P', 'yards a play, raw', '.2f', x=True),
           col('ex', 'Expl%', 'explosive plays: passes of 20+ yards, runs of 10+, share of plays', '.1f', x=True),
           col('proe', 'PROE', 'pass rate over expected on 1st and 2nd down, win chance 10-90% (nflverse xpass), points of rate', '+.1f', x=True),
           col('rz', 'RZ TD%', 'red zone: drives that reached the 20 and ended in a touchdown', '.1f', x=True),
           col('d3', '3D%', 'third down conversion rate', '.1f', x=True),
           col('sk', 'Sack%', 'sacks taken a dropback', '.1f', x=True, lo=True),
           col('to', 'TO/G', 'giveaways a game (interceptions, fumbles lost)', '.2f', x=True, lo=True)]
    dc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"EPA a play allowed, opponent-adjusted and shrunk: against an average offense on a neutral field, held toward the league by {k['kd']:.0f} plays (split-half r {k['rd'] or 0:.2f}); lower is better; the rank", '+.3f', lo=True, key=True),
           col('pass', 'Pass', 'EPA a dropback allowed, adjusted', '+.3f', lo=True),
           col('rush', 'Rush', 'EPA a designed run allowed, adjusted', '+.3f', lo=True),
           col('sr', 'SR%', 'success rate allowed, adjusted', '.1f', lo=True),
           col('ypp', 'Y/P', 'yards a play allowed, raw', '.2f', x=True, lo=True),
           col('ex', 'Expl%', 'explosive plays allowed, share of plays', '.1f', x=True, lo=True),
           col('rz', 'RZ TD%', 'red zone touchdowns allowed: drives that reached the 20 and ended in a touchdown', '.1f', x=True, lo=True),
           col('d3', '3D%', 'third down conversions allowed', '.1f', x=True, lo=True),
           col('sk', 'Sack%', 'sacks a dropback', '.1f', x=True),
           col('to', 'TA/G', 'takeaways a game', '.2f', x=True)]
    views = {'offense': finish_view(off, oc_, 'adj'), 'defense': finish_view(dfn, dc_, 'adj', lo=True)}
    form = nfl_formations(S, cur, R, fresh)
    if form:
        views.update(form)
    out = {'asof': now(), 'sport': 'nfl', 'season': S, 'week': week,
           'src': 'nflverse play-by-play' + (' · FTN charting' if form else ''),
           'k': {m: {'o': rnd(R[m]['ko'], 1), 'd': rnd(R[m]['kd'], 1), 'ro': rnd(R[m]['ro']), 'rd': rnd(R[m]['rd'])} for m in R},
           'home': rnd(R['epa']['b'], 3), 'views': views}
    save('nfl', out)


def nfl_formations(S, cur, R, fresh):
    ftn = nfl_ftn(S, fresh=fresh)
    if not ftn:
        return None
    T = lambda t: NFL_FR.get(t, t)
    C = collections.defaultdict(collections.Counter)
    V = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0]))   # team -> split -> [epa, n]
    L = collections.defaultdict(lambda: [0.0, 0])
    k_o, k_d = R['epa']['ko'], R['epa']['kd']
    for r in cur:
        pt = r['play_type']
        if pt not in ('run', 'pass'):
            continue
        f = ftn.get((r['game_id'], r['play_id']))
        epa, wp = fl(r['epa']), fl(r['wp'])
        if not f or epa is None:
            continue
        o, d = T(r['posteam']), T(r['defteam'])
        ql = f['qb_location']
        if ql not in ('S', 'U', 'P'):
            continue
        db = pt == 'pass'
        tf = lambda k: f.get(k) == 'TRUE'
        c, cd = C[o], C[d]
        c['n'] += 1; c['qS'] += ql == 'S'; c['qU'] += ql == 'U'; c['qP'] += ql == 'P'
        c['mo'] += tf('is_motion'); c['nh'] += tf('is_no_huddle'); c['rpo'] += tf('is_rpo')
        if db:
            c['db'] += 1; c['pa'] += tf('is_play_action'); c['scr'] += tf('is_screen_pass')
            nb, nr = fl(f['n_blitzers'], 0), fl(f['n_pass_rushers'], 0)
            if nr > 0:      # FTN leaves rushers at 0 on plays it didn't chart
                cd['ddb'] += 1; cd['bl'] += nb > 0; cd['rush'] += nr
        else:
            bx = fl(f['n_defense_box'], 0)
            if bx > 0:
                cd['run'] += 1; cd['box'] += bx; cd['light'] += bx <= 6; cd['heavy'] += bx >= 8
        if wp is None or not (0.05 <= wp <= 0.95):
            continue
        splits = [('sg' if ql in ('S', 'P') else 'uc', o, 'o')]
        if db:
            splits.append(('pa' if tf('is_play_action') else 'npa', o, 'o'))
            if fl(f['n_pass_rushers'], 0) > 0:
                splits.append(('bl' if fl(f['n_blitzers'], 0) > 0 else 'nbl', d, 'd'))
        for sp, t, side in splits:
            V[t][sp][0] += epa; V[t][sp][1] += 1; L[sp][0] += epa; L[sp][1] += 1
    if not C:
        return None
    q = lambda a, b: rnd(100 * a / b, 1) if b else None
    lm = {sp: (v / n if n else 0.0) for sp, (v, n) in L.items()}
    sh = lambda t, sp, k: rnd(shrink(V[t][sp][0], V[t][sp][1], lm.get(sp, 0), k), 3) if V[t][sp][1] else None
    off, dfn = [], []
    for t in sorted(C):
        c = C[t]
        if not c['n']:
            continue
        adj = rnd(R['epa']['mu'] + R['epa']['O'].get(t, 0))
        off.append({'t': t, 'ab': t, 'adj': adj, 'sg': q(c['qS'], c['n']), 'uc': q(c['qU'], c['n']), 'pis': q(c['qP'], c['n']),
                    'mo': q(c['mo'], c['n']), 'pa': q(c['pa'], c['db']), 'rpo': q(c['rpo'], c['n']), 'scr': q(c['scr'], c['db']),
                    'nh': q(c['nh'], c['n']), 'esg': sh(t, 'sg', k_o), 'euc': sh(t, 'uc', k_o), 'epa_pa': sh(t, 'pa', k_o),
                    'enpa': sh(t, 'npa', k_o), 'plays': c['n']})
    for t in sorted(C):
        c = C[t]
        if not c['ddb']:
            continue
        dfn.append({'t': t, 'ab': t, 'adj': rnd(R['epa']['mu'] + R['epa']['D'].get(t, 0)), 'bl': q(c['bl'], c['ddb']),
                    'rush': rnd(c['rush'] / c['ddb'], 2) if c['ddb'] else None, 'box': rnd(c['box'] / c['run'], 2) if c['run'] else None,
                    'light': q(c['light'], c['run']), 'heavy': q(c['heavy'], c['run']),
                    'ebl': sh(t, 'bl', k_d), 'enbl': sh(t, 'nbl', k_d), 'db': c['ddb']})
    oc_ = [col('adj', 'Adj', 'offense EPA a play, opponent-adjusted and shrunk (offense tab), for context', '+.3f'),
           col('sg', 'SG%', 'shotgun snaps, share of plays', '.1f', key=True),
           col('uc', 'UC%', 'under center snaps', '.1f'),
           col('pis', 'Pistol%', 'pistol snaps', '.1f', x=True),
           col('mo', 'Motion%', 'plays with pre-snap motion', '.1f'),
           col('pa', 'PA%', 'play action, share of dropbacks', '.1f'),
           col('rpo', 'RPO%', 'run-pass options, share of plays', '.1f', x=True),
           col('scr', 'Screen%', 'screen passes, share of dropbacks', '.1f', x=True),
           col('nh', 'NH%', 'no-huddle snaps', '.1f', x=True),
           col('esg', 'EPA SG', f'EPA a play from shotgun or pistol, shrunk toward the league by {k_o:.0f} plays', '+.3f', x=True),
           col('euc', 'EPA UC', 'EPA a play from under center, shrunk the same', '+.3f', x=True),
           col('epa_pa', 'EPA PA', 'EPA a play action dropback, shrunk', '+.3f', x=True),
           col('enpa', 'EPA no PA', 'EPA a dropback without play action, shrunk', '+.3f', x=True)]
    dc_ = [col('adj', 'Adj', 'defense EPA a play allowed, opponent-adjusted and shrunk (defense tab), for context', '+.3f', lo=True),
           col('bl', 'Blitz%', 'dropbacks with at least one blitzer (FTN)', '.1f', key=True),
           col('rush', 'Rushers', 'pass rushers a dropback', '.2f'),
           col('box', 'Box', 'defenders in the box on runs', '.2f'),
           col('light', 'Light%', 'runs against a light box (6 or fewer)', '.1f', x=True),
           col('heavy', 'Heavy%', 'runs against a stacked box (8 or more)', '.1f', x=True),
           col('ebl', 'EPA blitz', f'EPA a dropback allowed when blitzing, shrunk toward the league by {k_d:.0f} plays', '+.3f', x=True, lo=True),
           col('enbl', 'EPA no blitz', 'EPA a dropback allowed without a blitz, shrunk', '+.3f', x=True, lo=True)]
    return {'formations': finish_view(off, oc_, 'sg', plain=True), 'fronts': finish_view(dfn, dc_, 'bl', plain=True)}


# ------------------------------------------------------------------ CFB
CFB_PLAY = {'Rush', 'Pass Reception', 'Pass Incompletion', 'Sack', 'Rushing Touchdown', 'Passing Touchdown',
            'Pass Interception Return', 'Interception', 'Interception Return Touchdown', 'Fumble Recovery (Own)',
            'Fumble Recovery (Opponent)', 'Fumble', 'Fumble Return Touchdown', 'Safety', 'Pass Interception'}
CFB_PASS = {'Pass Reception', 'Pass Incompletion', 'Sack', 'Passing Touchdown', 'Pass Interception Return',
            'Interception', 'Interception Return Touchdown', 'Pass Interception'}


def cfb_season_now():
    d = datetime.date.today()
    return d.year if d.month >= 7 else d.year - 1


def cfb_games(S):
    import cfb_espn_hist as EH
    P = os.path.join(EH.DIR, '..', 'espn_pbp')
    gp = os.path.join(EH.DIR, f'games{S}.json')
    out = []
    if not os.path.exists(gp):
        return out
    for g in json.load(open(gp)):
        p = os.path.join(P, f"{g['id']}.json.gz")
        if g.get('done') and os.path.exists(p):
            d = json.load(gzip.open(p, 'rt'))
            d['id'] = str(g['id']); d['w'] = g.get('w', 0)
            out.append(d)
    return out


def _clock(c):
    try:
        m, s_ = str(c).split(':')
        return int(m) * 60 + int(s_)
    except (ValueError, AttributeError):
        return None


def cfb_plays(games):
    """scrimmage plays with their drive's net points (own points minus the other side's next drive in the half)"""
    plays = []
    for d in games:
        ha = {t.get('ha'): str(t.get('id')) for t in d.get('teams') or []}
        if 'home' not in ha or 'away' not in ha:
            continue
        drs = d['drives']
        own = []
        for dr in drs:
            res = (dr.get('res') or '').upper()
            if res in ('TD',):
                pts = 7
            elif res == 'FG':
                pts = 3
            elif 'TD' in res:            # INT TD, FUMBLE TD, PUNT TD, ...: the other side scored
                pts = -7
            elif 'SAFETY' in res:
                pts = -2
            else:
                pts = 0
            own.append(pts)
        for i, dr in enumerate(drs):
            tm = str(dr.get('tm')); q = dr.get('sq') or 0
            if q >= 5 or not tm:
                continue
            half = 1 if q <= 2 else 2
            nxt = 0
            if own[i] >= 0:
                for j in range(i + 1, len(drs)):
                    qj = drs[j].get('sq') or 0
                    if (1 if qj <= 2 else 2) != half or qj >= 5:
                        break
                    if str(drs[j].get('tm')) != tm:
                        nxt = own[j]; break
            net = own[i] - nxt
            pl = []
            for p in dr['plays']:
                t = p.get('t') or ''
                if t not in CFB_PLAY or p.get('pen') or str(p.get('st')) != tm or p.get('dn') not in (1, 2, 3, 4):
                    continue
                yl, ds = p.get('yl'), p.get('ds')
                if not yl or not (1 <= yl <= 99) or ds is None:
                    continue
                x = (p.get('x') or '').lower()
                isp = t in CFB_PASS or (t.startswith('Fumble') and (' pass' in x or 'sacked' in x))
                opp = ha['away'] if tm == ha['home'] else ha['home']
                hs, as_ = p.get('hs') or 0, p.get('as') or 0
                mar = abs(hs - as_)
                garbage = (q == 2 and mar > 38) or (q == 3 and mar > 28) or (q == 4 and mar > 22)
                y = p.get('y') or 0
                td = 'touchdown' in t.lower() and not t.startswith(('Interception', 'Fumble Return'))
                dn = int(p['dn'])
                succ = td or (y >= (0.5 * ds if dn == 1 else 0.7 * ds if dn == 2 else ds))
                pl.append({'g': d['id'], 'o': tm, 'd': opp, 'h': 0 if d.get('neutral') else (1 if tm == ha['home'] else -1),
                           'dn': dn, 'ds': int(ds), 'yl': int(yl), 'pass': isp, 'y': y, 'succ': bool(succ), 'garb': garbage,
                           'q': q, 'c': _clock(p.get('c')), 'sg': 'shotgun' in x, 'nh': 'no huddle' in x, 'td': td,
                           'to': bool(p.get('to')), 'date': (d.get('date') or '')[:10], 'net': net, 'dr': (d['id'], i)})
            plays.extend(pl)
    return plays


def cfb_ep(plays):
    """EP of a snap (down x distance x yards to goal) = mean net drive points from that state; thin bins borrow"""
    db = lambda ds: 0 if ds <= 3 else 1 if ds <= 6 else 2 if ds <= 10 else 3
    yb = lambda yl: min(19, (yl - 1) // 5)
    A, B, C = (collections.defaultdict(lambda: [0, 0.0]) for _ in range(3))
    for p in plays:
        k = (p['dn'], db(p['ds']), yb(p['yl']))
        for D, kk in ((A, k), (B, (p['dn'], yb(p['yl']))), (C, yb(p['yl']))):
            D[kk][0] += 1; D[kk][1] += p['net']

    def ep(p):
        k = (p['dn'], db(p['ds']), yb(p['yl']))
        n, v = A[k]; n2, v2 = B[(k[0], k[2])]; n3, v3 = C[k[2]]
        b2 = v2 / n2 if n2 else (v3 / n3 if n3 else 0.0)
        w = min(1.0, n / 40)
        return w * (v / n if n else 0) + (1 - w) * b2
    return ep


def cfb_epa(plays, ep):
    by = collections.defaultdict(list)
    for p in plays:
        by[p['dr']].append(p)
    for dr, ps in by.items():
        for i, p in enumerate(ps):
            p['ep'] = ep(p)
        for i, p in enumerate(ps):
            p['epa'] = (ps[i + 1]['ep'] if i + 1 < len(ps) else p['net']) - p['ep']
    return plays


def cfb_obs(plays):
    M = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
    meta = {}
    for p in plays:
        meta[(p['g'], p['o'])] = (p['d'], p['h'], p['date'])
        if p['garb']:
            continue
        key = (p['g'], p['o'])
        M['epa'][key][0] += p['epa']; M['epa'][key][1] += 1
        M['sr'][key][0] += p['succ']; M['sr'][key][1] += 1
        k = 'pass' if p['pass'] else 'rush'
        M[k][key][0] += p['epa']; M[k][key][1] += 1
    return {m: [{'o': o, 'd': meta[(g, o)][0], 'h': meta[(g, o)][1], 'date': meta[(g, o)][2], 'v': v, 'e': e}
                for (g, o), (v, e) in D.items()] for m, D in M.items()}


def cfb():
    S = cfb_season_now()
    gc, gp = cfb_games(S), cfb_games(S - 1)
    pc, pp = cfb_plays(gc), cfb_plays(gp)
    ep = cfb_ep(pc + pp)
    cfb_epa(pc, ep); cfb_epa(pp, ep)
    oc, op = cfb_obs(pc), cfb_obs(pp)
    R = {m: fit_metric(oc[m], op[m]) for m in ('epa', 'sr', 'pass', 'rush')}
    rk = json.load(open(os.path.join(ROOT, 'data', 'cfb_rank.json')))
    info = {str(t['tid']): t for t in rk['teams']}
    week = max((d.get('w') or 0) for d in gc) if gc else 0
    C = collections.defaultdict(collections.Counter)
    games = collections.defaultdict(set)
    tempo = collections.defaultdict(list)
    V = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0]))
    L = collections.defaultdict(lambda: [0.0, 0])
    prev = None
    for p in pc:
        o, d = p['o'], p['d']
        games[o].add(p['g']); games[d].add(p['g'])
        y = p['y']; ex = (p['pass'] and y >= 20) or (not p['pass'] and y >= 10)
        for side, t in (('o', o), ('d', d)):
            c = C[t]
            c[side + 'plays'] += 1; c[side + 'yds'] += y; c[side + 'ex'] += ex
            if p['dn'] == 3:
                c[side + '3a'] += 1; c[side + '3c'] += (y >= p['ds']) or p['td']
            if p['to']:
                c[side + 'to'] += 1
        C[o]['sg'] += p['sg']; C[o]['nh'] += p['nh']
        if not p['garb']:
            sp = 'sg' if p['sg'] else 'uc'
            V[o][sp][0] += p['epa']; V[o][sp][1] += 1; L[sp][0] += p['epa']; L[sp][1] += 1
        if prev and prev['dr'] == p['dr'] and prev['q'] == p['q'] and prev['c'] is not None and p['c'] is not None:
            gap = prev['c'] - p['c']
            if 0 < gap <= 60:
                tempo[o].append(gap)
        prev = p
    # drives: points a drive, red zone trips
    drv = {}
    for p in pc:
        dv = drv.setdefault(p['dr'], {'o': p['o'], 'd': p['d'], 'min': 100, 'net': p['net'], 'td': False, 'g': p['g']})
        dv['min'] = min(dv['min'], p['yl']); dv['td'] = dv['td'] or p['td']
    for d in gc:
        for i, dr in enumerate(d['drives']):
            dv = drv.get((d['id'], i))
            if not dv:
                continue
            res = (dr.get('res') or '').upper()
            pts = 7 if res == 'TD' else 3 if res == 'FG' else 0
            for side, t in (('o', dv['o']), ('d', dv['d'])):
                C[t][side + 'drv'] += 1; C[t][side + 'pts'] += pts
                if dv['min'] <= 20:
                    C[t][side + 'rz'] += 1; C[t][side + 'rztd'] += res == 'TD'
    q = lambda a, b: (a / b) if b else None
    lm = {sp: (v / n if n else 0.0) for sp, (v, n) in L.items()}
    k_o = R['epa']['ko']
    off, dfn, form = [], [], []
    for tid, t in info.items():
        if tid not in games:
            continue
        c = C[tid]; g = len(games[tid])
        e, s_, pa, ru = R['epa'], R['sr'], R['pass'], R['rush']
        base = {'id': tid, 't': t['team'], 'ab': t.get('abbr'), 'lg': t.get('logo'), 'cf': t.get('conf'), 'g': g}
        off.append({**base, 'adj': rnd(e['mu'] + e['O'].get(tid, 0)), 'pass': rnd(pa['mu'] + pa['O'].get(tid, 0)),
                    'rush': rnd(ru['mu'] + ru['O'].get(tid, 0)), 'sr': rnd(100 * (s_['mu'] + s_['O'].get(tid, 0)), 1),
                    'ypp': rnd(q(c['oyds'], c['oplays']), 2), 'ex': rnd(100 * (q(c['oex'], c['oplays']) or 0), 1),
                    'ppd': rnd(q(c['opts'], c['odrv']), 2), 'rz': rnd(100 * q(c['orztd'], c['orz']), 1) if c['orz'] else None,
                    'rzn': c['orz'], 'd3': rnd(100 * q(c['o3c'], c['o3a']), 1) if c['o3a'] else None,
                    'to': rnd(q(c['oto'], g), 2), 'ppg': rnd(q(c['oplays'], g), 1)})
        dfn.append({**base, 'adj': rnd(e['mu'] + e['D'].get(tid, 0)), 'pass': rnd(pa['mu'] + pa['D'].get(tid, 0)),
                    'rush': rnd(ru['mu'] + ru['D'].get(tid, 0)), 'sr': rnd(100 * (s_['mu'] + s_['D'].get(tid, 0)), 1),
                    'ypp': rnd(q(c['dyds'], c['dplays']), 2), 'ex': rnd(100 * (q(c['dex'], c['dplays']) or 0), 1),
                    'ppd': rnd(q(c['dpts'], c['ddrv']), 2), 'rz': rnd(100 * q(c['drztd'], c['drz']), 1) if c['drz'] else None,
                    'rzn': c['drz'], 'd3': rnd(100 * q(c['d3c'], c['d3a']), 1) if c['d3a'] else None,
                    'to': rnd(q(c['dto'], g), 2)})
        tp = sorted(tempo.get(tid) or [])
        sh = lambda sp: rnd(shrink(V[tid][sp][0], V[tid][sp][1], lm.get(sp, 0), k_o), 3) if V[tid][sp][1] else None
        form.append({**base, 'adj': off[-1]['adj'], 'sg': rnd(100 * (q(c['sg'], c['oplays']) or 0), 1),
                     'nh': rnd(100 * (q(c['nh'], c['oplays']) or 0), 1), 'ppg': off[-1]['ppg'],
                     'tempo': rnd(tp[len(tp) // 2], 0) if tp else None, 'esg': sh('sg'), 'euc': sh('uc')})
    k = R['epa']
    oc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"EPA a play, opponent-adjusted and shrunk: against an average FBS defense on a neutral field, held toward the league by {k['ko']:.0f} plays (split-half r {k['ro'] or 0:.2f}); garbage time left out; the rank", '+.3f', key=True),
           col('pass', 'Pass', 'EPA a dropback (passes, sacks), adjusted the same way', '+.3f'),
           col('rush', 'Rush', 'EPA a run, adjusted the same way', '+.3f'),
           col('sr', 'SR%', 'success rate, adjusted: 50% of the distance on 1st down, 70% on 2nd, all of it on 3rd and 4th', '.1f'),
           col('ypp', 'Y/P', 'yards a play, raw', '.2f', x=True),
           col('ex', 'Expl%', 'explosive plays: passes of 20+ yards, runs of 10+, share of plays', '.1f', x=True),
           col('ppd', 'Pts/Dr', 'points a drive (TD 7, FG 3), raw', '.2f', x=True),
           col('rz', 'RZ TD%', 'red zone: drives that reached the 20 and ended in a touchdown', '.1f', x=True),
           col('d3', '3D%', 'third down conversion rate', '.1f', x=True),
           col('to', 'TO/G', 'giveaways a game', '.2f', x=True, lo=True)]
    dc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"EPA a play allowed, opponent-adjusted and shrunk: against an average FBS offense on a neutral field, held toward the league by {k['kd']:.0f} plays (split-half r {k['rd'] or 0:.2f}); lower is better; the rank", '+.3f', lo=True, key=True),
           col('pass', 'Pass', 'EPA a dropback allowed, adjusted', '+.3f', lo=True),
           col('rush', 'Rush', 'EPA a run allowed, adjusted', '+.3f', lo=True),
           col('sr', 'SR%', 'success rate allowed, adjusted', '.1f', lo=True),
           col('ypp', 'Y/P', 'yards a play allowed, raw', '.2f', x=True, lo=True),
           col('ex', 'Expl%', 'explosive plays allowed', '.1f', x=True, lo=True),
           col('ppd', 'Pts/Dr', 'points a drive allowed', '.2f', x=True, lo=True),
           col('rz', 'RZ TD%', 'red zone touchdowns allowed', '.1f', x=True, lo=True),
           col('d3', '3D%', 'third down conversions allowed', '.1f', x=True, lo=True),
           col('to', 'TA/G', 'takeaways a game', '.2f', x=True)]
    fc_ = [col('adj', 'Adj', 'offense EPA a play, opponent-adjusted and shrunk (offense tab), for context', '+.3f'),
           col('sg', 'SG%', 'snaps from shotgun or pistol (the play text says shotgun), share of plays', '.1f', key=True),
           col('nh', 'NH%', 'no-huddle snaps', '.1f'),
           col('ppg', 'Plays/G', 'offensive plays a game', '.1f'),
           col('tempo', 'Sec/Play', 'median seconds of game clock between snaps within a drive', '.0f', lo=True),
           col('esg', 'EPA SG', f'EPA a play from shotgun, shrunk toward the league by {k_o:.0f} plays', '+.3f', x=True),
           col('euc', 'EPA UC', 'EPA a play from under center, shrunk the same', '+.3f', x=True)]
    out = {'asof': now(), 'sport': 'cfb', 'season': S, 'week': week, 'src': 'ESPN play-by-play',
           'k': {m: {'o': rnd(R[m]['ko'], 1), 'd': rnd(R[m]['kd'], 1), 'ro': rnd(R[m]['ro']), 'rd': rnd(R[m]['rd'])} for m in R},
           'home': rnd(R['epa']['b'], 3),
           'views': {'offense': finish_view(off, oc_, 'adj'), 'defense': finish_view(dfn, dc_, 'adj', lo=True),
                     'formations': finish_view(form, fc_, 'sg', plain=True)}}
    save('cfb', out)


# ------------------------------------------------------------------ NHL
def nhl_mp(season_mp):
    """MoneyPuck team game logs for regular seasons in season_mp (start years): {season: [row]} with the columns used"""
    import nhl_data as D
    os.makedirs(D.CACHE, exist_ok=True)
    D.moneypuck_teams()          # refreshes the raw file when stale
    raw = os.path.join(D.CACHE, 'all_teams.csv')
    keep = ('iceTime', 'xGoalsFor', 'xGoalsAgainst', 'scoreVenueAdjustedxGoalsFor', 'scoreVenueAdjustedxGoalsAgainst',
            'goalsFor', 'goalsAgainst', 'shotAttemptsFor', 'shotAttemptsAgainst', 'highDangerxGoalsFor',
            'highDangerxGoalsAgainst', 'penaltiesFor', 'penaltiesAgainst')
    out = collections.defaultdict(list)
    with open(raw) as f:
        for r in csv.DictReader(f):
            if r['situation'] not in ('all', '5on5', '5on4', '4on5'):
                continue
            s = int(r['season'])
            if s not in season_mp or str(r['gameId'])[4:6] != '02':
                continue
            row = {k: fl(r.get(k), 0.0) for k in keep}
            row.update({'t': D.team(r['playerTeam']), 'opp': D.team(r['opposingTeam']), 'gid': r['gameId'],
                        'date': r['gameDate'], 'sit': r['situation'], 'home': r['home_or_away'] == 'HOME'})
            out[s].append(row)
    return out


def nhl_obs(rows, sit, key, against=False):
    """per-60 rows: offense = the team (or its opponent for 'against' keys), exposure in hours of ice time"""
    obs = []
    for r in rows:
        if r['sit'] != sit or r['iceTime'] <= 0:
            continue
        obs.append({'o': r['t'], 'd': r['opp'], 'h': 0, 'date': r['date'], 'v': r[key], 'e': r['iceTime'] / 3600})
    return obs


def nhl_api(path, sid):
    u = f'https://api.nhle.com/stats/rest/en/team/{path}?cayenneExp=seasonId={sid}%20and%20gameTypeId=2'
    req = urllib.request.Request(u, headers={'User-Agent': UA})
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60)).get('data') or []
        except Exception:  # noqa: BLE001
            time.sleep(3 * (i + 1))
    return []


def nhl():
    import nhl_data as D
    d = datetime.date.today()
    S = d.year if d.month >= 9 else d.year - 1           # MoneyPuck season = start year
    mp = nhl_mp({S, S - 1, S - 2, S - 3})
    cur, prevs = mp[S], [mp[S - 1], mp[S - 2], mp[S - 3]]
    R = {}
    for name, sit, key in (('ev_xgf', '5on5', 'scoreVenueAdjustedxGoalsFor'), ('pp_xgf', '5on4', 'xGoalsFor'),
                           ('ev_cf', '5on5', 'shotAttemptsFor')):
        R[name] = fit_metric(nhl_obs(cur, sit, key), [nhl_obs(p_, sit, key) for p_ in prevs], home=False)
    sid = f'{S}{S + 1}'

    api = {}
    for path in ('summary', 'powerplay', 'penaltykill'):
        for x in nhl_api(path, sid):
            t = D.TEAM_ID.get(x.get('teamId'))
            if t:
                api.setdefault(t, {}).update(x)
    agg = collections.defaultdict(lambda: collections.defaultdict(float))
    gp = collections.defaultdict(set)
    for r in cur:
        a = agg[(r['t'], r['sit'])]
        for k, v in r.items():
            if isinstance(v, float):
                a[k] += v
        gp[r['t']].add(r['gid'])
    teams = sorted(gp)
    per60 = lambda t, sit, k: rnd(agg[(t, sit)][k] / (agg[(t, sit)]['iceTime'] / 3600), 2) if agg[(t, sit)]['iceTime'] else None
    pg = lambda t, sit, k: rnd(agg[(t, sit)][k] / len(gp[t]), 2) if gp[t] else None
    lg = lambda t: f'/img/nhl/{t.lower()}.png'
    off, dfn, pp, pk = [], [], [], []
    for t in teams:
        g = len(gp[t]); A = api.get(t, {})
        e, cf, ppx = R['ev_xgf'], R['ev_cf'], R['pp_xgf']
        base = {'t': t, 'ab': t, 'lg': lg(t), 'g': g}
        off.append({**base, 'adj': rnd(e['mu'] + e['O'].get(t, 0), 2), 'xgf': per60(t, '5on5', 'xGoalsFor'),
                    'gf': per60(t, '5on5', 'goalsFor'), 'cf': rnd(cf['mu'] + cf['O'].get(t, 0), 1),
                    'hd': per60(t, '5on5', 'highDangerxGoalsFor'), 'fin': rnd((agg[(t, '5on5')]['goalsFor'] - agg[(t, '5on5')]['xGoalsFor']) / g, 2),
                    'gpg': pg(t, 'all', 'goalsFor'), 'xpg': pg(t, 'all', 'xGoalsFor')})
        dfn.append({**base, 'adj': rnd(e['mu'] + e['D'].get(t, 0), 2), 'xga': per60(t, '5on5', 'xGoalsAgainst'),
                    'ga': per60(t, '5on5', 'goalsAgainst'), 'ca': rnd(cf['mu'] + cf['D'].get(t, 0), 1),
                    'hd': per60(t, '5on5', 'highDangerxGoalsAgainst'),
                    'gsax': rnd((agg[(t, 'all')]['xGoalsAgainst'] - agg[(t, 'all')]['goalsAgainst']) / g, 2),
                    'gapg': pg(t, 'all', 'goalsAgainst'), 'xapg': pg(t, 'all', 'xGoalsAgainst')})
        pp.append({**base, 'adj': rnd(ppx['mu'] + ppx['O'].get(t, 0), 2), 'pct': rnd(100 * A['powerPlayPct'], 1) if A.get('powerPlayPct') is not None else None,
                   'opp': rnd(A.get('ppOpportunitiesPerGame'), 2), 'toi': rnd(agg[(t, '5on4')]['iceTime'] / 60 / g, 1),
                   'xgf': per60(t, '5on4', 'xGoalsFor'), 'gf': per60(t, '5on4', 'goalsFor'),
                   'cf': per60(t, '5on4', 'shotAttemptsFor'), 'ppg': A.get('powerPlayGoalsFor'), 'sha': A.get('shGoalsAgainst')})
        pk.append({**base, 'adj': rnd(ppx['mu'] + ppx['D'].get(t, 0), 2), 'pct': rnd(100 * A['penaltyKillPct'], 1) if A.get('penaltyKillPct') is not None else None,
                   'tsh': rnd((A.get('timesShorthanded') or 0) / g, 2) if A.get('timesShorthanded') is not None else None,
                   'toi': rnd(agg[(t, '4on5')]['iceTime'] / 60 / g, 1), 'xga': per60(t, '4on5', 'xGoalsAgainst'),
                   'ga': per60(t, '4on5', 'goalsAgainst'), 'ca': per60(t, '4on5', 'shotAttemptsAgainst'),
                   'shg': A.get('shGoalsFor')})
    k, kp = R['ev_xgf'], R['pp_xgf']
    hrs = lambda x: f'{x * 60:.0f} minutes'
    oc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"5-on-5 expected goals for a 60 minutes (score and venue adjusted), opponent-adjusted and shrunk: against an average defence, held toward the league by {hrs(k['ko'])} (split-half r {k['ro'] or 0:.2f}); the rank", '.2f', key=True),
           col('xgf', 'xGF/60', '5-on-5 expected goals for a 60, raw', '.2f'),
           col('gf', 'GF/60', '5-on-5 goals for a 60', '.2f'),
           col('cf', 'CF/60', '5-on-5 shot attempts for a 60, opponent-adjusted and shrunk', '.1f', x=True),
           col('hd', 'HDxGF', '5-on-5 high-danger expected goals for a 60', '.2f', x=True),
           col('fin', 'Fin/G', '5-on-5 goals minus expected goals a game (finishing)', '+.2f', x=True),
           col('gpg', 'GF/G', 'goals a game, all situations', '.2f', x=True),
           col('xpg', 'xGF/G', 'expected goals a game, all situations', '.2f', x=True)]
    dc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"5-on-5 expected goals against a 60 (score and venue adjusted), opponent-adjusted and shrunk: against an average attack, held toward the league by {hrs(k['kd'])} (split-half r {k['rd'] or 0:.2f}); lower is better; the rank", '.2f', lo=True, key=True),
           col('xga', 'xGA/60', '5-on-5 expected goals against a 60, raw', '.2f', lo=True),
           col('ga', 'GA/60', '5-on-5 goals against a 60', '.2f', lo=True),
           col('ca', 'CA/60', '5-on-5 shot attempts against a 60, opponent-adjusted and shrunk', '.1f', x=True, lo=True),
           col('hd', 'HDxGA', '5-on-5 high-danger expected goals against a 60', '.2f', x=True, lo=True),
           col('gsax', 'GSAx/G', 'goals saved above expected a game, all situations (goaltending)', '+.2f', x=True),
           col('gapg', 'GA/G', 'goals against a game, all situations', '.2f', x=True, lo=True),
           col('xapg', 'xGA/G', 'expected goals against a game, all situations', '.2f', x=True, lo=True)]
    pc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"5-on-4 expected goals for a 60, opponent-adjusted (the penalty kills faced) and shrunk toward the league by {hrs(kp['ko'])} (split-half r {kp['ro'] or 0:.2f}); the rank", '.2f', key=True),
           col('pct', 'PP%', 'power play goals a power play opportunity (NHL)', '.1f'),
           col('opp', 'Opp/G', 'power play opportunities a game (penalties drawn)', '.2f'),
           col('toi', 'TOI/G', '5-on-4 minutes a game', '.1f', x=True),
           col('xgf', 'xGF/60', '5-on-4 expected goals for a 60, raw', '.2f', x=True),
           col('gf', 'GF/60', '5-on-4 goals for a 60', '.2f', x=True),
           col('cf', 'CF/60', '5-on-4 shot attempts for a 60', '.1f', x=True),
           col('ppg', 'PPG', 'power play goals', '.0f', x=True),
           col('sha', 'SHGA', 'shorthanded goals allowed on the power play', '.0f', x=True, lo=True)]
    kc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"4-on-5 expected goals against a 60, opponent-adjusted (the power plays faced) and shrunk toward the league by {hrs(kp['kd'])} (split-half r {kp['rd'] or 0:.2f}); lower is better; the rank", '.2f', lo=True, key=True),
           col('pct', 'PK%', 'power plays killed without a goal (NHL)', '.1f'),
           col('tsh', 'TSH/G', 'times shorthanded a game (penalties taken)', '.2f', lo=True),
           col('toi', 'TOI/G', '4-on-5 minutes a game', '.1f', x=True, lo=True),
           col('xga', 'xGA/60', '4-on-5 expected goals against a 60, raw', '.2f', x=True, lo=True),
           col('ga', 'GA/60', '4-on-5 goals against a 60', '.2f', x=True, lo=True),
           col('ca', 'CA/60', '4-on-5 shot attempts against a 60', '.1f', x=True, lo=True),
           col('shg', 'SHG', 'shorthanded goals scored', '.0f', x=True)]
    out = {'asof': now(), 'sport': 'nhl', 'season': S + 1, 'label': f'{S}-{str(S + 1)[2:]}', 'src': 'MoneyPuck · NHL',
           'k': {m: {'o': rnd(R[m]['ko'], 2), 'd': rnd(R[m]['kd'], 2), 'ro': rnd(R[m]['ro']), 'rd': rnd(R[m]['rd'])} for m in R},
           'views': {'offense': finish_view(off, oc_, 'adj'), 'defense': finish_view(dfn, dc_, 'adj', lo=True),
                     'power play': finish_view(pp, pc_, 'adj'), 'penalty kill': finish_view(pk, kc_, 'adj', lo=True)}}
    save('nhl', out)


# ------------------------------------------------------------------ NBA
def nba_box(gid):
    """ESPN team box for one final game, cached for good: {team: {fgm, fga, tpm, tpa, ftm, fta, orb, drb, tov, pts, paint, fb}}"""
    import nba_espn as E
    p = os.path.join(HERE, '.cache', 'units', 'nba', f'{gid}.json')
    if os.path.exists(p):
        return json.load(open(p))
    j = E.get(f'{E.SITE}/summary?event={gid}')
    if not j or 'boxscore' not in j:
        return None
    out = {}
    for t in j['boxscore'].get('teams', []):
        ab = E.team(t['team']['abbreviation'])
        st = {x['name']: x.get('displayValue') for x in t.get('statistics', [])}
        sp = lambda k: [fl(v, 0.0) for v in (st.get(k) or '0-0').split('-')][:2]
        fgm, fga = sp('fieldGoalsMade-fieldGoalsAttempted'); tpm, tpa = sp('threePointFieldGoalsMade-threePointFieldGoalsAttempted')
        ftm, fta = sp('freeThrowsMade-freeThrowsAttempted')
        out[ab] = {'fgm': fgm, 'fga': fga, 'tpm': tpm, 'tpa': tpa, 'ftm': ftm, 'fta': fta,
                   'orb': fl(st.get('offensiveRebounds'), 0.0), 'drb': fl(st.get('defensiveRebounds'), 0.0),
                   'tov': fl(st.get('totalTurnovers', st.get('turnovers')), 0.0), 'paint': fl(st.get('pointsInPaint')),
                   'fb': fl(st.get('fastBreakPoints'))}
    if len(out) != 2 or any(v['fga'] <= 0 for v in out.values()):
        return None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, 'w'))
    return out


def nba():
    import nba_espn as E
    from concurrent.futures import ThreadPoolExecutor
    today = datetime.date.today()
    S = today.year + 1 if today.month >= 9 else today.year
    d0 = datetime.date(S - 1, 10, 1)
    days = [d0 + datetime.timedelta(days=i) for i in range((today - d0).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        sb = list(ex.map(E.day, days))
    gs = [g for day in sb for g in day if g['season'] == S and g['type'] == 2 and g['final']]
    with ThreadPoolExecutor(8) as ex:
        boxes = list(ex.map(lambda g: nba_box(g['id']), gs))
    hist = json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz'), 'rt'))['games']

    def rows_hist(SS):
        o = []
        for g in hist:
            if g['S'] != SS or g.get('t') != 2 or not g.get('fin') or not g.get('poss'):
                continue
            e = g['poss'] / 100
            nh = 0 if g.get('n') else 1
            o.append({'o': g['h'], 'd': g['a'], 'h': nh, 'date': g['tip'], 'v': g['hs'], 'e': e})
            o.append({'o': g['a'], 'd': g['h'], 'h': -nh, 'date': g['tip'], 'v': g['as'], 'e': e})
        return o
    cur, C, G = [], collections.defaultdict(collections.Counter), collections.defaultdict(int)
    for g, b in zip(gs, boxes):
        if not b or g['h'] not in b or g['a'] not in b:
            continue
        H, A = b[g['h']], b[g['a']]
        poss = lambda x, y: x['fga'] - x['orb'] / max(1.0, x['orb'] + y['drb']) * (x['fga'] - x['fgm']) * 1.07 + x['tov'] + 0.4 * x['fta']
        P = (poss(H, A) + poss(A, H)) / 2         # Basketball-Reference's possession estimate, both sides averaged
        nh = 0 if g['neutral'] else 1
        cur.append({'o': g['h'], 'd': g['a'], 'h': nh, 'date': g['tip'], 'v': g['hs'], 'e': P / 100})
        cur.append({'o': g['a'], 'd': g['h'], 'h': -nh, 'date': g['tip'], 'v': g['as'], 'e': P / 100})
        for t, x, y, pts, pa in ((g['h'], H, A, g['hs'], g['as']), (g['a'], A, H, g['as'], g['hs'])):
            c = C[t]; G[t] += 1
            for side, u, w, pp in (('o', x, y, pts), ('d', y, x, pa)):
                for k in ('fgm', 'fga', 'tpm', 'tpa', 'ftm', 'fta', 'orb', 'tov'):
                    c[side + k] += u[k]
                c[side + 'oppdrb'] += w['drb']; c[side + 'pts'] += pp; c[side + 'poss'] += P
                c[side + 'paint'] += u['paint'] or 0; c[side + 'fb'] += u['fb'] or 0
    R = fit_metric(cur, [rows_hist(S - i) for i in (1, 2, 3)])
    q = lambda a, b: (a / b) if b else None
    off, dfn = [], []
    for t in sorted(G):
        c = C[t]; g = G[t]
        ff = {}
        for side in ('o', 'd'):
            ff[side] = {'efg': rnd(100 * q(c[side + 'fgm'] + 0.5 * c[side + 'tpm'], c[side + 'fga']), 1),
                        'tov': rnd(100 * q(c[side + 'tov'], c[side + 'poss']), 1),
                        'orb': rnd(100 * q(c[side + 'orb'], c[side + 'orb'] + c[side + 'oppdrb']), 1),
                        'ftr': rnd(100 * q(c[side + 'ftm'], c[side + 'fga']), 1),
                        'tpr': rnd(100 * q(c[side + 'tpa'], c[side + 'fga']), 1),
                        'raw': rnd(100 * q(c[side + 'pts'], c[side + 'poss']), 1),
                        'paint': rnd(q(c[side + 'paint'], g), 1), 'fb': rnd(q(c[side + 'fb'], g), 1)}
        pace = rnd(q(c['oposs'], g), 1)
        base = {'t': t, 'ab': t, 'lg': f'/img/nba/{t.lower()}.png', 'g': g}
        off.append({**base, 'adj': rnd(R['mu'] + R['O'].get(t, 0), 1), **ff['o'], 'pace': pace})
        dfn.append({**base, 'adj': rnd(R['mu'] + R['D'].get(t, 0), 1), **ff['d'], 'pace': pace})
    fx = lambda side: [
        col('raw', 'Rtg', f"points {'scored' if side == 'o' else 'allowed'} a 100 possessions, raw", '.1f', lo=side == 'd'),
        col('efg', 'eFG%', 'effective field goal % (a three counts 1.5)' + ('' if side == 'o' else ' allowed'), '.1f', lo=side == 'd'),
        col('tov', 'TOV%', 'turnovers a 100 possessions' + (', forced' if side == 'd' else ''), '.1f', lo=side == 'o'),
        col('orb', 'ORB%', 'offensive rebound rate' + (' allowed (lower is better)' if side == 'd' else ''), '.1f', lo=side == 'd'),
        col('ftr', 'FT/FGA', 'free throws made a field goal attempt' + (' allowed' if side == 'd' else ''), '.1f', lo=side == 'd'),
        col('tpr', '3PA%', 'share of field goal attempts from three' + (' allowed' if side == 'd' else ''), '.1f', x=True),
        col('paint', 'Paint', 'points in the paint a game' + (' allowed' if side == 'd' else ''), '.1f', x=True, lo=side == 'd'),
        col('fb', 'Fast', 'fast break points a game' + (' allowed' if side == 'd' else ''), '.1f', x=True, lo=side == 'd'),
        col('pace', 'Pace', 'possessions a game', '.1f', x=True)]
    oc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"points a 100 possessions, opponent-adjusted and shrunk: against an average defense on a neutral floor, held toward the league by {R['ko'] * 100:.0f} possessions (split-half r {R['ro'] or 0:.2f}); the rank", '.1f', key=True)] + fx('o')
    dc_ = [col('g', 'G', 'games', '.0f', x=True),
           col('adj', 'Adj', f"points allowed a 100 possessions, opponent-adjusted and shrunk: against an average offense, held toward the league by {R['kd'] * 100:.0f} possessions (split-half r {R['rd'] or 0:.2f}); lower is better; the rank", '.1f', lo=True, key=True)] + fx('d')
    out = {'asof': now(), 'sport': 'nba', 'season': S, 'label': f'{S - 1}-{str(S)[2:]}', 'src': 'ESPN box scores',
           'k': {'rtg': {'o': rnd(R['ko'] * 100, 0), 'd': rnd(R['kd'] * 100, 0), 'ro': rnd(R['ro']), 'rd': rnd(R['rd'])}},
           'home': rnd(R['b'], 2), 'views': {'offense': finish_view(off, oc_, 'adj'), 'defense': finish_view(dfn, dc_, 'adj', lo=True)}}
    save('nba', out)


# ------------------------------------------------------------------ CBB
BT_FIX = {'Miami': 'Miami FL', 'UConn': 'Connecticut', 'Ole Miss': 'Mississippi', 'UIC': 'Illinois Chicago',
          'McNeese': 'McNeese St.', 'Seattle U': 'Seattle', 'App State': 'Appalachian St.', 'San José State': 'San Jose St.',
          'Pennsylvania': 'Penn', 'Florida International': 'FIU', 'Texas A&M-Corpus Christi': 'Texas A&M Corpus Chris',
          'Kansas City': 'UMKC', 'Sam Houston': 'Sam Houston St.', 'American University': 'American', 'Grambling': 'Grambling St.',
          'UL Monroe': 'Louisiana Monroe', 'Omaha': 'Nebraska Omaha', 'LSU New Orleans': 'New Orleans', 'California Baptist': 'Cal Baptist',
          'South Carolina Upstate': 'USC Upstate', 'Nicholls': 'Nicholls St.', 'UAlbany': 'Albany', 'Queens University': 'Queens',
          'SE Louisiana': 'Southeastern Louisiana', 'UT Martin': 'Tennessee Martin', 'Long Island University': 'LIU',
          'IU Indianapolis': 'IU Indy', 'Loyola Maryland': 'Loyola MD'}


def bt_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=90))
        except Exception:  # noqa: BLE001
            time.sleep(3 * (i + 1))
    return None


def cbb():
    today = datetime.date.today()
    S = today.year + 1 if today.month >= 9 else today.year
    res = bt_get(f'https://barttorvik.com/{S}_team_results.json') or []
    sl = bt_get(f'https://barttorvik.com/teamslicejson.php?year={S}&json=1&type=R') or []
    if not res:
        print('no Barttorvik team results'); return
    norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower().replace('state', 'st').replace('saint', 'st'))
    TR = {norm(r[1]): r for r in res}
    SL = {norm(r[0]): r for r in sl}
    power = json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']
    off, dfn = [], []
    for p in power:
        k = norm(BT_FIX.get(p['t'], p['t']))
        r = TR.get(k)
        if not r:
            continue
        x = SL.get(k)
        g = int(x[6]) if x else 0
        f_ = (lambda i: rnd(fl(x[i]), 1)) if (x and g > 0) else (lambda i: None)
        base = {'id': p['id'], 't': p['t'], 'ab': p['t'], 'lg': p.get('logo'), 'cf': p.get('conf'), 'g': g}
        off.append({**base, 'adj': rnd(fl(r[4]), 1), 'ark': p.get('off'), 'efg': f_(7), 'tov': f_(11), 'orb': f_(13),
                    'ftr': f_(9), 'p2': f_(16), 'p3': f_(18), 'tpr': f_(24), 'ast': f_(22), 'tempo': rnd(fl(r[44]), 1)})
        dfn.append({**base, 'adj': rnd(fl(r[6]), 1), 'ark': p.get('def'), 'efg': f_(8), 'tov': f_(12), 'orb': f_(14),
                    'ftr': f_(10), 'p2': f_(17), 'p3': f_(19), 'tpr': f_(25), 'blk': f_(20), 'tempo': rnd(fl(r[44]), 1)})
    oc_ = [col('g', 'G', 'games played', '.0f', x=True),
           col('adj', 'AdjO', "Barttorvik adjusted offensive efficiency: points a 100 possessions against an average D-I defense (blends in a preseason projection early in the season); the rank", '.1f', key=True),
           col('ark', 'ARK O', 'the ARK Ranking offense rating (points a 100 possessions)', '.1f'),
           col('efg', 'eFG%', 'effective field goal %', '.1f'),
           col('tov', 'TOV%', 'turnover rate', '.1f', lo=True),
           col('orb', 'ORB%', 'offensive rebound rate', '.1f'),
           col('ftr', 'FTR', 'free throw rate (FTA a FGA)', '.1f'),
           col('p2', '2P%', 'two-point %', '.1f', x=True), col('p3', '3P%', 'three-point %', '.1f', x=True),
           col('tpr', '3PA%', 'share of attempts from three', '.1f', x=True), col('ast', 'Ast%', 'assisted field goals', '.1f', x=True),
           col('tempo', 'Tempo', 'adjusted possessions a 40 minutes', '.1f', x=True)]
    dc_ = [col('g', 'G', 'games played', '.0f', x=True),
           col('adj', 'AdjD', "Barttorvik adjusted defensive efficiency: points allowed a 100 possessions against an average D-I offense; lower is better; the rank", '.1f', lo=True, key=True),
           col('ark', 'ARK D', 'the ARK Ranking defense rating (points allowed a 100 possessions)', '.1f', lo=True),
           col('efg', 'eFG%', 'effective field goal % allowed', '.1f', lo=True),
           col('tov', 'TOV%', 'turnover rate forced', '.1f'),
           col('orb', 'ORB%', 'offensive rebound rate allowed', '.1f', lo=True),
           col('ftr', 'FTR', 'free throw rate allowed', '.1f', lo=True),
           col('p2', '2P%', 'two-point % allowed', '.1f', x=True, lo=True), col('p3', '3P%', 'three-point % allowed', '.1f', x=True, lo=True),
           col('tpr', '3PA%', 'share of opponent attempts from three', '.1f', x=True), col('blk', 'Blk%', 'block rate', '.1f', x=True),
           col('tempo', 'Tempo', 'adjusted possessions a 40 minutes', '.1f', x=True)]
    out = {'asof': now(), 'sport': 'cbb', 'season': S, 'label': f'{S - 1}-{str(S)[2:]}', 'src': 'Barttorvik',
           'views': {'offense': finish_view(off, oc_, 'adj'), 'defense': finish_view(dfn, dc_, 'adj', lo=True)}}
    save('cbb', out)


def mom_k(obs, side):
    """k (exposure units) by method of moments on one season: within-team noise / between-team variance"""
    by = collections.defaultdict(list)
    for x in obs:
        if x['e'] > 0:
            by[x[side]].append(x)
    means, ns, ss = [], [], []
    for xs in by.values():
        E = sum(x['e'] for x in xs)
        if len(xs) < 3:
            continue
        m = sum(x['v'] for x in xs) / E
        ss.append(sum(x['e'] * (x['v'] / x['e'] - m) ** 2 for x in xs) / (len(xs) - 1))
        means.append(m); ns.append(E)
    if len(means) < 8:
        return None
    s2 = float(np.mean(ss))
    tau2 = float(np.var(means, ddof=1)) - s2 * float(np.mean([1 / n for n in ns]))
    return s2 / tau2 if tau2 > 0 else None


# ------------------------------------------------------------------ soccer
SOC_FM = {'eng.1': 47, 'esp.1': 87, 'ger.1': 54, 'ita.1': 55, 'fra.1': 53}
SOC_NAME = {'eng.1': 'Premier League', 'esp.1': 'La Liga', 'ger.1': 'Bundesliga', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1',
            'eng.2': 'Championship', 'ger.2': '2. Bundesliga', 'por.1': 'Primeira Liga', 'ned.1': 'Eredivisie',
            'bel.1': 'Pro League', 'sco.1': 'Scottish Prem', 'tur.1': 'Super Lig', 'aut.1': 'Austria', 'sui.1': 'Swiss SL',
            'den.1': 'Superliga', 'nor.1': 'Eliteserien', 'swe.1': 'Allsvenskan', 'usa.1': 'MLS'}


def soc_matches(lg, fid, S):
    import soccer_data as D
    cal = lg in D.CAL
    S = D.current_season() if not cal else datetime.date.today().year
    sea = str(S) if cal else f'{S - 1}%2F{S}'
    d = D.get(f'{D.FM}?id={fid}&season={sea}', tries=2)
    if not d:
        return S, []
    ms = [{'id': m['id'], 'status': {'utcTime': (m.get('status') or {}).get('utcTime'), 'scoreStr': (m.get('status') or {}).get('scoreStr')},
           'home': {'id': m['home']['id'], 'name': m['home'].get('name')}, 'away': {'id': m['away']['id'], 'name': m['away'].get('name')}}
          for m in (d.get('fixtures') or {}).get('allMatches') or []
          if (m.get('status') or {}).get('finished') and not (m.get('status') or {}).get('cancelled')]
    return S, ms


def soccer(budget=900):
    import soccer_data as D
    from concurrent.futures import ThreadPoolExecutor
    leagues = {**SOC_FM, **D.FMX_LG}
    t0 = time.time()
    att, dfn, setp = [], [], []

    per_lg = {}
    for lg, fid in leagues.items():
        S, ms = soc_matches(lg, fid, None)
        if not ms:
            continue

        def one(m):
            have = os.path.exists(os.path.join(D.CACHE, 'fmx', f'{m["id"]}.json'))
            if not have and time.time() - t0 > budget:
                return None
            return D.fm_match_stats(lg, S, m)
        with ThreadPoolExecutor(8) as ex:
            got = [o for o in ex.map(one, ms) if o and o.get('st', {}).get('expected_goals')]
        rows = []
        for o in got:
            st = o['st']
            try:
                hs, as_ = [int(x) for x in o['sc'].split(' - ')]
            except (ValueError, AttributeError):
                continue
            g2 = lambda k, i: fl((st.get(k) or [None, None])[i])
            rows.append({'h': o['h'], 'a': o['a'], 'hn': o['hn'], 'an': o['an'], 'hs': hs, 'as': as_, 'date': (o.get('t') or '')[:10],
                         **{f'{k}{i}': g2(key, j) for k, key in (('xg', 'expected_goals'), ('np', 'expected_goals_non_penalty'),
                                                                 ('op', 'expected_goals_open_play'), ('sp', 'expected_goals_set_play'),
                                                                 ('sh', 'total_shots'), ('bc', 'big_chance')) for i, j in (('h', 0), ('a', 1))}})
        if len(rows) < 20:
            continue
        per_lg[lg] = rows
        print(lg, len(rows), 'matches with xG', flush=True)
    # one k across leagues a metric (method of moments, this season), ridge a league
    def obs(rows, k):
        o = []
        for r in rows:
            for side, opp, s1, s2 in (('h', 'a', 1, 'h'), ('a', 'h', -1, 'a')):
                v = r.get(f'{k}{s2}')
                if v is None:
                    continue
                o.append({'o': r[side], 'd': r[opp], 'h': s1, 'date': r['date'], 'v': v, 'e': 1.0})
        return o
    K = {}
    for m in ('np', 'sp'):
        ks_o = [mom_k(obs(rows, m), 'o') for rows in per_lg.values()]
        ks_d = [mom_k(obs(rows, m), 'd') for rows in per_lg.values()]
        ko = float(np.median([k for k in ks_o if k])) if any(ks_o) else 10.0
        kd = float(np.median([k for k in ks_d if k])) if any(ks_d) else 10.0
        K[m] = (ko, kd)
    for lg, rows in per_lg.items():
        R = {m: ridge(obs(rows, m), *K[m]) for m in ('np', 'sp')}
        T = collections.defaultdict(collections.Counter); name = {}
        for r in rows:
            for side, opp in (('h', 'a'), ('a', 'h')):
                t = r[side]; name[t] = r[side + 'n']; c = T[t]
                c['g'] += 1
                for k in ('xg', 'np', 'op', 'sp', 'sh', 'bc'):
                    c[k + 'f'] += r.get(f'{k}{side}') or 0; c[k + 'a'] += r.get(f'{k}{opp}') or 0
        for r in rows:
            T[r['h']]['goals'] += r['hs']; T[r['h']]['ga'] += r['as']
            T[r['a']]['goals'] += r['as']; T[r['a']]['ga'] += r['hs']
        for t, c in T.items():
            g = c['g']; q = lambda k: rnd(c[k] / g, 2)
            base = {'id': t, 't': name[t], 'ab': name[t], 'lg': f'https://images.fotmob.com/image_resources/logo/teamlogo/{t}_small.png',
                    'cf': SOC_NAME.get(lg, lg), 'g': g}
            mu, O, Dd, _ = R['np']; mus, Os, Ds, _ = R['sp']
            att.append({**base, 'adj': rnd(mu + O.get(t, 0), 2), 'xg': q('xgf'), 'gpg': q('goals'), 'op': q('opf'), 'sp': q('spf'),
                        'sh': rnd(c['shf'] / g, 1), 'bc': q('bcf'), 'fin': rnd((c['goals'] - c['xgf']) / g, 2)})
            dfn.append({**base, 'adj': rnd(mu + Dd.get(t, 0), 2), 'xg': q('xga'), 'gpg': q('ga'), 'op': q('opa'), 'sp': q('spa'),
                        'sh': rnd(c['sha'] / g, 1), 'bc': q('bca'), 'gk': rnd((c['xga'] - c['ga']) / g, 2)})
            spf, spa = mus + Os.get(t, 0), mus + Ds.get(t, 0)
            setp.append({**base, 'adj': rnd(spf - spa, 2), 'spf': rnd(spf, 2), 'spa': rnd(spa, 2), 'rf': q('spf'), 'ra': q('spa'),
                         'shf': rnd(100 * c['spf'] / c['xgf'], 1) if c['xgf'] else None,
                         'sha': rnd(100 * c['spa'] / c['xga'], 1) if c['xga'] else None})
    if not att:
        print('no soccer xG'); return
    ko, kd = K['np']
    ac_ = [col('g', 'G', 'matches', '.0f', x=True),
           col('adj', 'Adj', f'non-penalty xG a match, opponent-adjusted (within the league) and shrunk: against an average defence on a neutral pitch, held toward the league by {ko:.0f} matches; the rank', '.2f', key=True),
           col('xg', 'xG', 'expected goals a match, raw (penalties in)', '.2f'),
           col('gpg', 'GF', 'goals a match', '.2f'),
           col('op', 'Open', 'open-play xG a match', '.2f', x=True),
           col('sp', 'Set', 'set-piece xG a match', '.2f', x=True),
           col('sh', 'Shots', 'shots a match', '.1f', x=True),
           col('bc', 'BC', 'big chances a match', '.2f', x=True),
           col('fin', 'G-xG', 'goals minus xG a match (finishing)', '+.2f', x=True)]
    dc_ = [col('g', 'G', 'matches', '.0f', x=True),
           col('adj', 'Adj', f'non-penalty xG allowed a match, opponent-adjusted and shrunk toward the league by {kd:.0f} matches; lower is better; the rank', '.2f', lo=True, key=True),
           col('xg', 'xGA', 'expected goals against a match, raw', '.2f', lo=True),
           col('gpg', 'GA', 'goals against a match', '.2f', lo=True),
           col('op', 'Open', 'open-play xG allowed a match', '.2f', x=True, lo=True),
           col('sp', 'Set', 'set-piece xG allowed a match', '.2f', x=True, lo=True),
           col('sh', 'Shots', 'shots against a match', '.1f', x=True, lo=True),
           col('bc', 'BC', 'big chances against a match', '.2f', x=True, lo=True),
           col('gk', 'xGA-GA', 'xG against minus goals against a match (goalkeeping and luck)', '+.2f', x=True)]
    sko, skd = K['sp']
    sc_ = [col('g', 'G', 'matches', '.0f', x=True),
           col('adj', 'Net', f'set-piece xG for minus against a match, both opponent-adjusted and shrunk (attack by {sko:.0f} matches, defence by {skd:.0f}); the rank', '+.2f', key=True),
           col('spf', 'For', 'set-piece xG a match, adjusted', '.2f'),
           col('spa', 'Agst', 'set-piece xG allowed a match, adjusted', '.2f', lo=True),
           col('rf', 'For raw', 'set-piece xG a match, raw', '.2f', x=True),
           col('ra', 'Agst raw', 'set-piece xG allowed a match, raw', '.2f', x=True, lo=True),
           col('shf', 'Share', 'set pieces as a share of the team\'s xG', '.1f', x=True),
           col('sha', 'Share A', 'set pieces as a share of xG allowed', '.1f', x=True)]
    out = {'asof': now(), 'sport': 'soccer', 'season': D.current_season(), 'label': f'{D.current_season() - 1}-{str(D.current_season())[2:]}', 'src': 'FotMob', 'leagues': sorted({r['cf'] for r in att}),
           'k': {'np': [rnd(ko, 1), rnd(kd, 1)], 'sp': [rnd(sko, 1), rnd(skd, 1)]},
           'views': {'attack': finish_view(att, ac_, 'adj', group=True), 'defence': finish_view(dfn, dc_, 'adj', lo=True, group=True),
                     'set pieces': finish_view(setp, sc_, 'adj', group=True)}}
    save('soccer', out)


if __name__ == '__main__':
    sp = sys.argv[1]
    {'nfl': nfl, 'cfb': cfb, 'nhl': nhl, 'nba': nba, 'cbb': cbb, 'soccer': soccer}[sp]()
