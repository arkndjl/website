#!/usr/bin/env python3
"""NFL WAR leaderboards for the NFL ARKBOARD (data/nfl_war.json), and the AV model behind them (data/nfl_war_fit.json).

    python3 scripts/nfl_war.py          # this season's board from nflverse (stdlib only; run by the cfb board job)
    python3 scripts/nfl_war.py --fit    # refit the AV model on PFR's AV (numpy) and write data/nfl_war_fit.json
    python3 scripts/nfl_war.py --calibrate  # refit the WAR scale on 2021-25 team seasons: data/nfl_war_calib.json

NFL WAR = (AV - NFL_REPL[group] x snap share) x NWAR_PER_AV (scripts/cfb_av.mjs). NWAR_PER_AV is wins per team AV
(least squares, 2021-25 team seasons, tested leaving out each season). NFL_REPL[group] is the AV a replacement player
at the position earns in a full season of snaps: the AV rate of the position's part-timers (5-35% of snaps, the
freely available players), scaled together so a team of replacements (its snap shares at the mean) wins REPL_WINS
of 17. Team WAR then sums to wins - REPL_WINS. One line for every position (6.2) left DBs and TEs at about zero
and RBs high, against what teams pay (veteran contracts signed after a 2021-25 season, cap %: see market in
data/nfl_war_calib.json); the AV rate of a starter differs by position (RB 16 a full season, DB 7). Snap share is the player's snaps over his team's plays on his side across
a 17-game season, so mid-season it is the share so far and replacement accrues as he plays.

AV: Pro Football Reference's Approximate Value (Drinen) is the target, but PFR can't be scraped, so the board
rebuilds it from nflverse's play stats (stats_player_week), PFR snap counts (snap_counts) and scores (nfldata
games.csv), the way Drinen builds it: each team gets an offense pool (100 at league-average scoring over 17 games)
and a defense pool (100 at league-average points allowed), and players split the pools by role and production.

    offense pool  100/17 x points for / league points a game
    defense pool  100/17 x (2 x games - points against / league points a game)
    player AV     sum over features of b[group][f] x share_f x pool, shares of the team's totals that season:
                  snaps (offense or defense), yards (rush, receive, pass, of the team's rush + pass yards), passing
                  TDs, sacks, tackles, tackles for loss, plays on the ball (INT + passes defended + forced fumbles)

The b's are fit (non-negative least squares) to PFR's own AV: nflverse's draft picks carry each player's
weighted career AV (w_av: best season 100%, next 95%, ...), which PFR updates in season, so each drafted player
from 2016-25 is one equation over his seasons (2016-2025, ordered by predicted AV, refit until the order holds).
Tested on the 2024-25 draft classes after fitting on 2016-23 (the 2025 class alone is a one-season test).
PFR posts AV only after a season (2026 rookies all read 0 in October), so this season's AV is the model's. Groups: QB, RB, WR, TE, OL, DL, LB, DB;
the board shows DE and pass-rushing OLBs (sacks + QB hits a snap) as EDGE, DT/NT as DL, ILB/MLB and 4-3 OLBs as LB,
by the roster's depth-chart spot.
Kickers, punters and long snappers aren't graded (PFR gives them little AV too).
"""
import csv
import json
import math
import os
import sys
import urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
FIT = os.path.join(ROOT, 'data', 'nfl_war_fit.json')
OUT = os.path.join(ROOT, 'data', 'nfl_war.json')            # season, week, counts: read by Hugo
PLAYERS = os.path.join(ROOT, 'static', 'data', 'nfl-war.json')  # every player: fetched by the page
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'

# keep in step with scripts/cfb_av.mjs
NFL_REPL_AV = 6.2   # the mean line (by FV, no position)
NFL_REPL = {'QB': 7.9, 'RB': 9.0, 'WR': 4.95, 'TE': 2.6, 'OL': 6.7, 'DL': 7.4, 'LB': 6.9, 'DB': 5.1}
CONTRACTS = f'{REL}/contracts/historical_contracts.csv.gz'
NWAR_PER_AV = 0.091
REPL_WINS = 3
CALIB = os.path.join(ROOT, 'data', 'nfl_war_calib.json')

GROUP = {'QB': 'QB', 'RB': 'RB', 'HB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE',
         'OL': 'OL', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OT': 'OL', 'OG': 'OL',
         'DL': 'DL', 'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'LB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'OLB': 'LB',
         'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'DB': 'DB'}
FEATS = {'QB': ['snap', 'pass', 'ptd', 'rush'], 'RB': ['snap', 'rush', 'rec'], 'WR': ['snap', 'rec'],
         'TE': ['snap', 'rec'], 'OL': ['snap'],
         'DL': ['snap', 'sack', 'tkl', 'tfl', 'ball'], 'LB': ['snap', 'sack', 'tkl', 'tfl', 'ball'],
         'DB': ['snap', 'sack', 'tkl', 'tfl', 'ball']}
OFFENSE = {'QB', 'RB', 'WR', 'TE', 'OL'}
EDGE_RUSH = 1.5   # sacks + QB hits per 100 defensive snaps that makes a roster OLB an EDGE (3-4) and not a 4-3 SAM/WILL


def get(name, url, fresh=False):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if fresh or not os.path.exists(p):
        req = urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net arkboard'})
        with urllib.request.urlopen(req, timeout=120) as r, open(p + '.tmp', 'wb') as f:
            f.write(r.read())
        os.replace(p + '.tmp', p)
    return p


def rows(p):
    with open(p, newline='', encoding='utf-8') as f:
        yield from csv.DictReader(f)


def num(x):
    try:
        return float(x) if x not in (None, '', 'NA') else 0.0
    except ValueError:
        return 0.0


def season_data(y, fresh=False):
    """Per player-team season: snaps, play stats and pools. Keyed (pfr_id, team); stats rows joined by gsis id."""
    games = [g for g in rows(get('games.csv', GAMES, fresh)) if g['season'] == str(y) and g['game_type'] == 'REG'
             and g['home_score'] not in ('', 'NA')]
    team = defaultdict(lambda: {'g': 0, 'pf': 0.0, 'pa': 0.0})
    for g in games:
        h, a, hs, as_ = g['home_team'], g['away_team'], num(g['home_score']), num(g['away_score'])
        for t, pf, pa in ((h, hs, as_), (a, as_, hs)):
            team[t]['g'] += 1; team[t]['pf'] += pf; team[t]['pa'] += pa
    lg = sum(t['pf'] for t in team.values()) / max(1, sum(t['g'] for t in team.values()))
    for t in team.values():
        t['off'] = 100 / 17 * t['pf'] / lg
        t['def'] = 100 / 17 * (2 * t['g'] - t['pa'] / lg)
    played = {g['game_id'] for g in games}

    snaps = defaultdict(lambda: {'off': 0, 'def': 0, 'g': 0, 'pos': Counter(), 'name': ''})
    gmax = defaultdict(lambda: [0, 0])     # (game, team) -> most offense / defense snaps by one player = team plays
    for r in rows(get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv', fresh)):
        if r['game_type'] != 'REG' or r['game_id'] not in played:
            continue
        o, d = num(r['offense_snaps']), num(r['defense_snaps'])
        s = snaps[(r['pfr_player_id'], r['team'])]
        s['off'] += o; s['def'] += d; s['name'] = r['player']
        if o or d: s['g'] += 1
        s['pos'][r['position']] += 1
        m = gmax[(r['game_id'], r['team'])]
        m[0] = max(m[0], o); m[1] = max(m[1], d)
    plays = defaultdict(lambda: [0, 0])
    for (_, t), m in gmax.items():
        plays[t][0] += m[0]; plays[t][1] += m[1]

    stat = defaultdict(lambda: defaultdict(float))
    meta = {}
    tot = defaultdict(lambda: defaultdict(float))
    for r in rows(get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', fresh)):
        if r['season_type'] != 'REG' or r.get('game_id') not in played:
            continue
        k = (r['player_id'], r['team'])
        meta[r['player_id']] = (r['player_display_name'], r['position'], r.get('headshot_url', ''))
        v = {'pass': num(r['passing_yards']), 'ptd': num(r['passing_tds']), 'rush': num(r['rushing_yards']),
             'rec': num(r['receiving_yards']), 'sack': num(r['def_sacks']),
             'tkl': num(r['def_tackles_solo']) + num(r['def_tackle_assists']), 'tfl': num(r['def_tackles_for_loss']),
             'ball': num(r['def_interceptions']) + num(r['def_pass_defended']) + num(r['def_fumbles_forced']),
             'hit': num(r['def_qb_hits']), 'pint': num(r['passing_interceptions']), 'rtd': num(r['rushing_tds']),
             'retd': num(r['receiving_tds'])}
        for f, x in v.items():
            stat[k][f] += x
            tot[r['team']][f] += x
    for t in tot.values():
        t['yds'] = t['pass'] + t['rush']
    return {'team': team, 'snaps': snaps, 'plays': plays, 'stat': stat, 'tot': tot, 'meta': meta, 'lg': lg}


def features(sd, pfr, gsis, t, group):
    """{feature: share x pool} for one player-team season, and the snap line."""
    s, st, T, P, tm = sd['snaps'].get((pfr, t)), sd['stat'].get((gsis, t), {}), sd['tot'][t], sd['plays'][t], sd['team'].get(t)
    if not tm:
        return None
    off = group in OFFENSE
    pool = tm['off'] if off else tm['def']
    snapshare = ((s['off'] / P[0]) if off else (s['def'] / P[1])) if s and P[0] and P[1] else 0.0
    x = {}
    for f in FEATS[group]:
        if f == 'snap':
            v = snapshare
        elif f in ('pass', 'rush', 'rec'):
            v = max(0.0, st.get(f, 0.0)) / T['yds'] if T['yds'] > 0 else 0.0
        else:
            v = max(0.0, st.get(f, 0.0)) / T[f] if T[f] > 0 else 0.0
        x[f] = v * pool
    return x


def group_of(pos_counter, fallback):
    pos = pos_counter.most_common(1)[0][0] if pos_counter else fallback
    return GROUP.get(pos), pos


def display_pos(group, pos, dc, st, snaps):
    """Board position: the roster's depth-chart spot (dc) where it settles it, else the snap-count listing."""
    rush = (st.get('sack', 0) + st.get('hit', 0)) / max(1, snaps) * 100
    if group == 'DL':
        return 'DL' if dc in ('DT', 'NT') or (not dc and pos != 'DE') else 'EDGE'
    if group == 'LB':
        # OLB is a 3-4 edge or a 4-3 SAM/WILL: the pass rush rate tells them apart
        return 'EDGE' if dc == 'DE' or (dc == 'OLB' and (rush >= EDGE_RUSH or snaps < 100)) else 'LB'
    if group == 'DB':
        return 'CB' if (dc or pos) == 'CB' else 'S' if (dc or pos) in ('S', 'FS', 'SS') else 'CB' if dc == 'DB' else 'S'
    return group


def predict(b, group, x):
    return sum(b[group].get(f, 0.0) * v for f, v in x.items())


# ---------------------------------------------------------------- fit
def fit():
    import numpy as np

    def nnls(A, y, tol=1e-10):
        # Lawson-Hanson active set
        n = A.shape[1]
        P, w = np.zeros(n, bool), np.zeros(n)
        for _ in range(3 * n):
            g = A.T @ (y - A @ w)
            if P.all() or g[~P].max() <= tol:
                break
            P[np.argmax(np.where(P, -np.inf, g))] = True
            while True:
                z = np.zeros(n)
                z[P] = np.linalg.lstsq(A[:, P], y, rcond=None)[0]
                if (z[P] > 0).all():
                    w = z
                    break
                neg = P & (z <= 0)
                a = np.min(w[neg] / (w[neg] - z[neg]))
                w = w + a * (z - w)
                P &= w > tol
                w[~P] = 0
        return w

    picks = [r for r in rows(get('draft_picks.csv', f'{REL}/draft_picks/draft_picks.csv'))
             if 2016 <= int(r['season']) <= 2025 and r['pfr_player_id'] and r['w_av'] not in ('', 'NA')]
    years = range(2016, 2026)   # PFR posts AV after the season: 2026 rookies all show 0 in October
    SD = {y: season_data(y) for y in years}
    byp = {y: defaultdict(list) for y in years}
    for y in years:
        for (pid, t), s in SD[y]['snaps'].items():
            byp[y][pid].append((t, s))
    cols = [(g, f) for g in FEATS for f in FEATS[g]]
    ci = {c: i for i, c in enumerate(cols)}
    # each player's seasons as feature vectors
    players = []
    for p in picks:
        D, pfr, gsis = int(p['season']), p['pfr_player_id'], p['gsis_id']
        seasons = []
        for y in years:
            if y < D:
                continue
            sd = SD[y]
            v = np.zeros(len(cols))
            for t, s in byp[y].get(pfr, []):
                g, pos = group_of(s['pos'], p['position'])
                if not g:
                    continue
                x = features(sd, pfr, gsis, t, g)
                for f, val in (x or {}).items():
                    v[ci[(g, f)]] += val
            if v.any():
                seasons.append((y, v))
        players.append({'D': D, 'y': float(p['w_av']), 'seasons': seasons, 'name': p['pfr_player_name'], 'pos': p['position']})

    def design(ps, b):
        A, Y = [], []
        for p in ps:
            pred = sorted(p['seasons'], key=lambda s: -(s[1] @ b)) if b is not None else sorted(p['seasons'], key=lambda s: -s[1].sum())
            row = np.zeros(len(cols))
            for k, (_, v) in enumerate(pred):
                row += max(0.0, 1 - 0.05 * k) * v
            A.append(row); Y.append(p['y'])
        return np.array(A), np.array(Y)

    def train(ps):
        b = None
        for _ in range(6):
            A, Y = design(ps, b)
            b = nnls(A, Y)
        return b

    def score(ps, b):
        A, Y = design(ps, b)
        pr = A @ b
        r = float(np.corrcoef(pr, Y)[0, 1])
        return {'n': len(ps), 'r': round(r, 3), 'rmse': round(float(np.sqrt(np.mean((pr - Y) ** 2))), 2)}

    tr = [p for p in players if p['D'] <= 2023]
    te = [p for p in players if p['D'] >= 2024]
    b_tr = train(tr)
    test = {'train_2016_23': score(tr, b_tr), 'test_2024_25': score(te, b_tr)}
    # one season, one number: the 2025 class, whose w_av is its 2025 AV
    test['rookies_2025_one_season'] = score([p for p in players if p['D'] == 2025], b_tr)
    by = {}
    for g in FEATS:
        sub = [p for p in te if any(GROUP.get(p['pos'], p['pos']) == g for _ in [0])]
        if len(sub) >= 10:
            by[g] = score(sub, b_tr)
    test['test_by_group'] = by
    b = train(players)
    coef = {g: {f: round(float(b[ci[(g, f)]]), 4) for f in FEATS[g]} for g in FEATS}
    out = {'coef': coef, 'test': test, 'fit': score(players, b), 'edgeRush': EDGE_RUSH,
           'note': 'AV = sum of coef x share x team pool; NNLS on PFR weighted career AV (nflverse draft picks), drafted 2016-26'}
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- board
def build():
    with open(FIT) as f:
        b = json.load(f)['coef']
    games = list(rows(get('games.csv', GAMES, fresh=True)))
    done = [g for g in games if g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    y = max(int(g['season']) for g in done)
    week = max(int(g['week']) for g in done if int(g['season']) == y)
    sd = season_data(y, fresh=True)
    ros = {}
    for r in rows(get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv', fresh=True)):
        if r['pfr_id']:
            ros[r['pfr_id']] = r
    gsis_of = {pfr: r['gsis_id'] for pfr, r in ros.items()}
    agg = {}
    for (pfr, t), s in sd['snaps'].items():
        g, pos = group_of(s['pos'], '')
        if not g:
            continue
        gsis = gsis_of.get(pfr, '')
        x = features(sd, pfr, gsis, t, g)
        if x is None:
            continue
        av = predict(b, g, x)
        st = sd['stat'].get((gsis, t), {})
        snaps = s['off'] if g in OFFENSE else s['def']
        P = sd['plays'][t]
        share = snaps / (P[0] if g in OFFENSE else P[1]) * sd['team'][t]['g'] / 17 if P[0] and P[1] else 0.0
        a = agg.setdefault(pfr, {'name': s['name'], 'teams': [], 'g': 0, 'snaps': 0, 'av': 0.0, 'sh': 0.0, 'repl': 0.0, 'grp': Counter(), 'st': Counter(), 'pos': Counter()})
        a['teams'].append((snaps, t)); a['g'] += s['g']; a['snaps'] += snaps; a['av'] += av; a['sh'] += share
        a['repl'] += NFL_REPL[g] * share
        a['grp'][g] += snaps + 0.01; a['pos'][pos] += snaps + 0.01
        for k, v in st.items():
            a['st'][k] += v
    teamg = {t: v['g'] for t, v in sd['team'].items()}
    out = []
    for pfr, a in agg.items():
        if a['snaps'] <= 0:
            continue
        g = a['grp'].most_common(1)[0][0]
        team = max(a['teams'])[1]
        r = ros.get(pfr, {})
        pos = display_pos(g, a['pos'].most_common(1)[0][0], r.get('depth_chart_position', ''), a['st'], a['snaps'])
        tg = max(1, teamg.get(team, 1))
        av = a['av']
        # replacement accrues with the snaps played (share of a 17-game season's plays); below replacement is negative
        war = (av - a['repl']) * NWAR_PER_AV
        st = a['st']
        line = (f"{int(st['pass'])} pass yds, {int(st['ptd'])} TD, {int(st['pint'])} INT" if g == 'QB' else
                f"{int(st['rush'])} rush yds, {int(st['rec'])} rec yds" if g == 'RB' else
                f"{int(st['rec'])} rec yds, {int(st['retd'])} TD" if g in ('WR', 'TE') else
                '' if g == 'OL' else
                f"{st['sack']:g} sk, {int(st['tkl'])} tkl, {int(st['tfl'])} TFL, {int(st['ball'])} on ball")
        out.append({'n': a['name'], 'id': pfr, 't': team, 'tm': '/'.join(sorted({t for _, t in a['teams']})), 'pos': pos,
                    'g': a['g'], 'sn': int(a['snaps']), 'av': round(av, 2), 'war': round(war, 2),
                    'pace': round(war * 17 / tg, 2), 'sh': round(a['sh'], 3), 'line': line, 'age': age(r.get('birth_date'), y),
                    'exp': r.get('years_exp', ''), 'col': (r.get('college') or '').split(';')[0]})
    out = [p for p in out if p['sn'] >= 1]
    out.sort(key=lambda p: -p['war'])
    import datetime
    last = max(g['gameday'] for g in done if int(g['season']) == y)
    meta = {'season': y, 'week': week, 'last': last, 'n': len(out), 'replAv': NFL_REPL, 'warPerAv': round(NWAR_PER_AV, 4), 'replWins': REPL_WINS,
            'top': [{k: p[k] for k in ('n', 't', 'pos', 'war')} for p in out[:3]]}
    body = json.dumps({'season': y, 'week': week, 'last': last, 'players': out}, separators=(',', ':'))
    try:
        same = open(PLAYERS).read() == body
    except OSError:
        same = False
    if same:
        return print('nfl war: no change')
    meta['asof'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(PLAYERS, 'w') as f:
        f.write(body)
    with open(OUT, 'w') as f:
        json.dump(meta, f, indent=1)
    print(f'nfl war: {y} through week {week}, {len(out)} players; top: ' +
          ', '.join(f"{p['n']} {p['war']}" for p in out[:5]))


def age(bd, y):
    try:
        by, bm, bdd = map(int, bd.split('-'))
    except (AttributeError, ValueError):
        return None
    return y - by - ((9, 1) < (bm, bdd))   # age on Sept 1 of the season


# ---------------------------------------------------------------- WAR scale
def calibrate(years=range(2021, 2026)):
    """Wins per team AV and the replacement line, from team seasons on this model's AV (data/nfl_war_calib.json)."""
    with open(FIT) as f:
        b = json.load(f)['coef']
    games = [g for g in rows(get('games.csv', GAMES)) if g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    W = Counter()
    for g in games:
        y, hs, as_ = int(g['season']), float(g['home_score']), float(g['away_score'])
        for t, d in ((g['home_team'], hs - as_), (g['away_team'], as_ - hs)):
            W[(y, t)] += 1 if d > 0 else 0.5 if d == 0 else 0
    teams, players = [], []
    for y in years:
        sd = season_data(y)
        gsis_of = {r['pfr_id']: r['gsis_id'] for r in rows(get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv')) if r['pfr_id']}
        T = {}
        for (pfr, t), s in sd['snaps'].items():
            g, _ = group_of(s['pos'], '')
            if not g:
                continue
            x = features(sd, pfr, gsis_of.get(pfr, ''), t, g)
            if x is None:
                continue
            P = sd['plays'][t]
            share = ((s['off'] / P[0]) if g in OFFENSE else (s['def'] / P[1])) if P[0] and P[1] else 0.0
            av = predict(b, g, x)
            a = T.setdefault(t, [0.0, 0.0, 0.0]); a[0] += av; a[1] += share; a[2] += NFL_REPL[g] * share
            players.append((av, share, g, y, s['name']))
        teams += [{'y': y, 't': t, 'av': a[0], 'sh': a[1], 'repl': a[2], 'w': W[(y, t)] * 17 / sd['team'][t]['g']} for t, a in T.items()]
    mean = lambda xs: sum(xs) / len(xs)

    def slope(rs):
        mx, my = mean([r['av'] for r in rs]), mean([r['w'] for r in rs])
        return sum((r['av'] - mx) * (r['w'] - my) for r in rs) / sum((r['av'] - mx) ** 2 for r in rs)
    k = slope(teams)
    mav, msh, mw = mean([r['av'] for r in teams]), mean([r['sh'] for r in teams]), mean([r['w'] for r in teams])
    sx = math.sqrt(sum((r['av'] - mav) ** 2 for r in teams)); sy = math.sqrt(sum((r['w'] - mw) ** 2 for r in teams))
    r = sum((t['av'] - mav) * (t['w'] - mw) for t in teams) / (sx * sy)
    loso = {}
    for y in years:
        tr, te = [t for t in teams if t['y'] != y], [t for t in teams if t['y'] == y]
        ky = slope(tr); a = mean([t['w'] for t in tr]) - ky * mean([t['av'] for t in tr])
        loso[y] = {'k': round(ky, 4), 'rmseWins': round(math.sqrt(mean([(t['w'] - a - ky * t['av']) ** 2 for t in te])), 2)}
    # replacement: team WAR = k x (AV - R x share) sums to wins - REPL_WINS at the mean team
    R = (mav - (mw - REPL_WINS) / k) / msh
    # by position: the part-timers' AV a full season of snaps, scaled together to the same replacement team
    part = defaultdict(lambda: [0.0, 0.0]); shg = Counter()
    for av, sh, g, *_ in players:
        shg[g] += sh / len(teams)
        if 0.05 <= sh < 0.35:
            part[g][0] += av; part[g][1] += sh
    rate = {g: v[0] / v[1] for g, v in part.items()}
    c = (mav - (mw - REPL_WINS) / k) / sum(rate[g] * shg[g] for g in rate)
    used = (NWAR_PER_AV, NFL_REPL)
    war = [used[0] * (t['av'] - t['repl']) for t in teams]
    bins = {}
    for av, sh, *_ in players:
        bins.setdefault(min(14, int(av)), []).append(sh)
    out = {'years': [min(years), max(years)], 'teams': len(teams), 'meanTeamAv': round(mav, 1), 'meanShare': round(msh, 2),
           'meanWins': round(mw, 2), 'winsPerAv': round(k, 4), 'r': round(r, 3), 'leaveOneSeasonOut': loso,
           'replWins': REPL_WINS, 'replAvFullSeason': round(R, 2), 'replTeamAv': round(R * msh, 1),
           'partTimeRate': {g: round(v, 2) for g, v in rate.items()}, 'replByPos': {g: round(c * v, 2) for g, v in rate.items()},
           'used': {'warPerAv': used[0], 'replAv': used[1], 'meanTeamWar': round(mean(war), 2),
                    'teamWarVsWinsSlope': round(sum((w - mean(war)) * (t['w'] - mw) for w, t in zip(war, teams)) / sum((w - mean(war)) ** 2 for w in war), 3)},
           'shareByAv': {a: round(mean(v), 3) for a, v in sorted(bins.items())}}
    out['market'] = market(players, k)
    with open(CALIB, 'w') as f:
        json.dump(out, f, indent=1)
        f.write('\n')
    print(json.dumps(out, indent=1))


def market(players, k):
    """WAR against what teams pay: veteran contracts (3+ years after the draft) signed after a season, the player's
    rank by WAR that season against his rank by cap %, one replacement line for all against NFL_REPL."""
    import gzip, io, re
    norm = lambda n: re.sub(r'[^a-z]', '', re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', n.lower()))
    by = {}
    for av, sh, g, y, n in players:
        a = by.setdefault((norm(n), y), [0.0, 0.0, Counter()]); a[0] += av; a[1] += sh; a[2][g] += sh
    raw = urllib.request.urlopen(urllib.request.Request(CONTRACTS, headers={'User-Agent': 'arkboard'}), timeout=120).read()
    rowsm = []
    for c in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)), 'utf-8')):
        try:
            ys, cap = int(c['year_signed']), float(c['apy_cap_pct'])
        except ValueError:
            continue
        dy = c['draft_year']
        if dy not in ('', 'NA') and ys - int(dy) < 3:
            continue
        a = by.get((norm(c['player']), ys - 1))
        if a and a[1] >= 0.3:
            rowsm.append((a, cap))
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        for j, i in enumerate(o):
            r[i] = j / len(v)
        return r
    rc = rank([c for _, c in rowsm])
    res = {'contracts': len(rowsm)}
    for name, repl in (('oneLine', lambda a: NFL_REPL_AV * a[1]), ('byPosition', lambda a: sum(NFL_REPL[g] * s for g, s in a[2].items()))):
        rw = rank([(a[0] - repl(a)) * k for a, _ in rowsm])
        mr = sum(rw) / len(rw); mc = sum(rc) / len(rc)
        rho = sum((x - mr) * (y - mc) for x, y in zip(rw, rc)) / math.sqrt(sum((x - mr) ** 2 for x in rw) * sum((y - mc) ** 2 for y in rc))
        bias = defaultdict(list)
        for i, (a, _) in enumerate(rowsm):
            bias[a[2].most_common(1)[0][0]].append(rw[i] - rc[i])
        b = {g: round(sum(v) / len(v), 3) for g, v in sorted(bias.items())}
        res[name] = {'rankCorr': round(rho, 3), 'posBias': b, 'meanAbsBias': round(sum(abs(v) for v in b.values()) / len(b), 3)}
    return res


if __name__ == '__main__':
    calibrate() if '--calibrate' in sys.argv else fit() if '--fit' in sys.argv else build()
