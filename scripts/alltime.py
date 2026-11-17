#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""All-time team-season and player rankings for every ARKBOARD sport (data/alltime.json, shortcode alltime.html).

    python3 scripts/alltime_pull.py all     # pages and files (cache scripts/.cache/alltime, ~40 min the first time)
    python3 scripts/alltime.py              # build data/alltime.json (and the snapshot scripts/data/alltime_src.json.gz)
    python3 scripts/alltime.py --snap       # rebuild from the snapshot only (no cache needed)

Era adjustment (every sport, teams and players): a season's value is set against the spread of that league in that era.
  Teams    Rtg+ / Off+ / Def+ = 100 + 25 z, z = (rating - season mean) / SD, SD pooled over the season and the two either
           side (team ratings demeaned by season). 100 = an average team that season, 125 = one SD better. Same scale as Stat+.
           Ratings: CFB ridge SRS on capped margin + offense / defense on capped points (scripts/coach_alltime_pull.py, jhowell
           scores 1900-); NFL the same ridge on every NFL / AFL / AAFC game (FiveThirtyEight 1920-98, nflverse 1999-); CBB
           Sports Reference SRS / OSRS / DSRS 1950-; NBA SRS + ORtg / DRtg against the league (Basketball Reference 1947-;
           ORtg / DRtg from 1952); NHL SRS + goals for / against a game against the league (Hockey Reference 1918-);
           soccer big-five clubs, goals a match vs the big-five average (scripts/soccer_* ratings, ESPN 2005-);
           CS2 Valve VRS points (peak a calendar year, 2024-).
  Players  peak = best season, career = sum of seasons, each season's value measured against replacement in its league:
           NBA VORP (Basketball Reference; before 1974 from WS / 48 and minutes at the 1974-85 fit), per 82 games;
           NHL point shares (Hockey Reference), per 82 games; CBB Barttorvik BPM x minutes share over replacement (2008-);
           tennis Elo (own fit on the Sackmann archive 1968-), peak and career weeks above the top-20 line;
           soccer GAR seasons where the site has them; CS2 HLTV-style rating where the site has it.
  Era check (about in each table): decade share of the top 100 against the decade's share of team-seasons; KL divergence
  of the adjusted list vs the raw one (lower = no era favoured).
"""
import gzip, json, math, os, sys, csv, re, glob
from collections import defaultdict, Counter
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
CACHE = os.path.join(HERE, '.cache', 'alltime')
OUT = os.path.join(ROOT, 'data', 'alltime.json')
SNAP = os.path.join(HERE, 'data', 'alltime_src.json.gz')
TOP, PER_DEC = 250, 25           # list: the top TOP plus the top PER_DEC of every decade
WIN = 2                          # SD pooled over the season +- WIN
CAP = 35


def plus(z): return round(100 + 25 * z, 1)


def era_z(rows, keys, group=lambda r: r['y']):
    """adds z<key> to rows: (value - season mean) / SD pooled over seasons +- WIN"""
    by = defaultdict(list)
    for r in rows: by[group(r)].append(r)
    for k in keys:
        mu = {s: float(np.mean([r[k] for r in L if r.get(k) is not None] or [0])) for s, L in by.items()}
        dev = {s: [r[k] - mu[s] for r in L if r.get(k) is not None] for s, L in by.items()}
        for s, L in by.items():
            pool = [d for t in range(s - WIN, s + WIN + 1) for d in dev.get(t, [])]
            sd = float(np.sqrt(np.mean(np.square(pool)))) if len(pool) > 3 else None
            for r in L:
                r['z' + k] = (r[k] - mu[s]) / sd if (sd and r.get(k) is not None) else None


def era_check(rows, zk, rk, n=100):
    """KL(top-n decade share || all team-season decade share), adjusted (z) vs raw"""
    base = Counter(r['y'] // 10 * 10 for r in rows); tot = sum(base.values())
    def kl(key):
        top = sorted([r for r in rows if r.get(key) is not None], key=lambda r: -r[key])[:n]
        c = Counter(r['y'] // 10 * 10 for r in top)
        return sum((c[d] / n) * math.log((c[d] / n) / (base[d] / tot)) for d in c)
    return round(kl(zk), 3), round(kl(rk), 3)


def pick(rows, key, top=TOP, per=PER_DEC):
    R = sorted([r for r in rows if r.get(key) is not None], key=lambda r: -r[key])
    keep = set(id(r) for r in R[:top])
    per_d = Counter()
    for r in R:
        d = r['y'] // 10 * 10
        if per_d[d] < per: keep.add(id(r)); per_d[d] += 1
    return [r for r in R if id(r) in keep]


# ---------------------------------------------------------------- ridge ratings from scores (NFL)
def ridge(G, cap=CAP, lam=2.0):
    """G: dicts a, b, pa, pb, h (+1 a home, -1 b home, 0 neutral). -> {team: (rating, off, def, games)}"""
    teams = sorted({g['a'] for g in G} | {g['b'] for g in G}); ix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    X = np.zeros((len(G), n + 1)); ym = np.zeros(len(G)); Xo = np.zeros((2 * len(G), 2 * n + 1)); yo = np.zeros(2 * len(G))
    for r, g in enumerate(G):
        X[r, ix[g['a']]] = 1; X[r, ix[g['b']]] = -1; X[r, n] = g['h']; ym[r] = max(-cap, min(cap, g['pa'] - g['pb']))
        for q, (t, u, pts, hh) in enumerate([(g['a'], g['b'], g['pa'], g['h']), (g['b'], g['a'], g['pb'], -g['h'])]):
            Xo[2 * r + q, ix[t]] = 1; Xo[2 * r + q, n + ix[u]] = -1; Xo[2 * r + q, 2 * n] = hh / 2; yo[2 * r + q] = pts
    l1 = np.full(n + 1, lam); l1[n] = .01
    beta = np.linalg.solve(X.T @ X + np.diag(l1), X.T @ ym)
    yo2 = np.minimum(yo, yo.mean() + cap); l2 = np.full(2 * n + 1, lam); l2[2 * n] = .01
    bo = np.linalg.solve(Xo.T @ Xo + np.diag(l2), Xo.T @ (yo2 - yo2.mean()))
    cnt = Counter([g['a'] for g in G] + [g['b'] for g in G])
    return {t: (float(beta[ix[t]]), float(bo[ix[t]]), float(bo[n + ix[t]]), cnt[t]) for t in teams}


NFL_LG = {'AAFC': {'BBA', 'BCL', 'BDA', 'CRA', 'LDA', 'MSA', 'NAA'}}
AFL_TEAMS = {'BUF', 'DEN', 'KC', 'LAC', 'NE', 'NYJ', 'OAK', 'TEN', 'MIA', 'CIN'}


def nfl_rows():
    from alltime_names import nfl_name
    by = defaultdict(list); wl = defaultdict(lambda: [0, 0, 0])
    for r in csv.DictReader(open(os.path.join(CACHE, 'nfl', '538.csv'))):
        y = int(r['season'])
        if y >= 1999: continue
        a, b, pa, pb = r['team1'], r['team2'], int(r['score1']), int(r['score2'])
        by[y].append(dict(a=a, b=b, pa=pa, pb=pb, h=0 if r['neutral'] == '1' else 1))
        if r['playoff'] in ('0', ''):
            wl[(a, y)][0 if pa > pb else 1 if pa < pb else 2] += 1; wl[(b, y)][0 if pb > pa else 1 if pb < pa else 2] += 1
    for r in csv.DictReader(open(os.path.join(CACHE, 'nfl', 'games.csv'))):
        if not r['home_score']: continue
        y = int(r['season']); a, b, pa, pb = r['home_team'], r['away_team'], int(r['home_score']), int(r['away_score'])
        by[y].append(dict(a=a, b=b, pa=pa, pb=pb, h=0 if r['location'] == 'Neutral' else 1))
        if r['game_type'] == 'REG':
            wl[(a, y)][0 if pa > pb else 1 if pa < pb else 2] += 1; wl[(b, y)][0 if pb > pa else 1 if pb < pa else 2] += 1
    out = []
    last = max(by)
    for y, G in sorted(by.items()):
        if y == last and len(G) < 200: continue       # season in progress
        R = ridge(G)
        for t, (rt, o, d, n) in R.items():
            if n < 6: continue
            lg = 'AAFC' if t in NFL_LG['AAFC'] else ('AFL' if 1960 <= y <= 1969 and t in AFL_TEAMS else None)
            out.append(dict(t=nfl_name(t, y), y=y, r=rt, o=o, d=d, wl=wl[(t, y)], lg=lg))
    return out


def cfb_rows():
    d = json.load(gzip.open(os.path.join(HERE, 'data', 'coach_alltime_src.json.gz')))['cfb']
    nm = d['teams']
    return [dict(t=nm.get(r['t'], r['t']), y=r['y'], r=r['r'], o=r['o'], d=r['d'], wl=r['wl'], lg=None, nt=r.get('nt') or 0)
            for r in d['rows']]


def team_lists(rows, keys=('r', 'o', 'd')):
    era_z(rows, [k for k in keys if any(r.get(k) is not None for r in rows)])
    for r in rows:
        for k in keys:
            if r.get('z' + k) is not None: r['p' + k] = plus(r['z' + k])
    out = {}
    names = {'r': 'teams', 'o': 'offense', 'd': 'defense'}
    for k in keys:
        if not any(r.get('p' + k) is not None for r in rows): continue
        L = pick(rows, 'p' + k)
        out[names[k]] = [{**{f: r.get(f) for f in ('t', 'y', 'wl', 'lg', 'nt')}, 'pr': r.get('pr'), 'po': r.get('po'), 'pd': r.get('pd'),
                          'raw': round(r[k], 2)} for r in L]
        out[names[k] + '_check'] = era_check(rows, 'z' + k, k)
    out['n'] = len(rows); out['from'] = min(r['y'] for r in rows); out['to'] = max(r['y'] for r in rows)
    return out


# ---------------------------------------------------------------- players
def player_lists(seasons, key_v, minv=None, per=None):
    """seasons: dicts id, n, y, v (value, era-adjusted already), (+ tm, pos). -> peak (best season) and career (sum)"""
    peak = sorted([s for s in seasons if s['v'] is not None], key=lambda s: -s['v'])
    best = {}
    for s in peak:
        if s['id'] not in best: best[s['id']] = s
    P = list(best.values())
    car = defaultdict(lambda: dict(v=0.0, n=0))
    for s in seasons:
        if s['v'] is None: continue
        c = car[s['id']]; c['v'] += max(0.0, s['v']) if s.get('pos_only') else s['v']; c['n'] += 1
        c['y0'] = min(c.get('y0', 9999), s['y']); c['y1'] = max(c.get('y1', 0), s['y'])
        c['nm'] = s['n']; c['tm'] = c.get('tms', Counter()); c.setdefault('tms', Counter())[s.get('tm') or ''] += max(1.0, s.get('w', 1))
        c['pos'] = s.get('pos'); c['est'] = c.get('est', False) or bool(s.get('est'))
        c['bestv'] = max(c.get('bestv', -99), s['v'])
    C = sorted(car.items(), key=lambda kv: -kv[1]['v'])
    def prow(s):
        return dict(n=s['n'], y=s['y'], tm=s.get('tm'), pos=s.get('pos'), v=round(s['v'], 2), raw=s.get('raw'), est=s.get('est') or None)
    def crow(pid, c):
        return dict(n=c['nm'], y0=c['y0'], y1=c['y1'], tm=c['tms'].most_common(1)[0][0], pos=c['pos'], v=round(c['v'], 1), s=c['n'],
                    pk=round(c['bestv'], 2), est=c['est'] or None)
    for p in P: p['y'] = p['y']
    peaks = pick([dict(p) for p in P], 'v')
    cars = [crow(pid, c) for pid, c in C[:TOP]]
    return dict(peak=[prow(s) for s in peaks], career=cars, peak_check=era_check(P, 'v', 'v0' if P and 'v0' in P[0] else 'v'),
                n=len(seasons), from_=min(s['y'] for s in seasons), to=max(s['y'] for s in seasons))


def tennis_players(tour):
    """Elo on every tour-level singles match (FiveThirtyEight K = 250 / (matches + 5)^.4, Slams x1.1), 1968 on.
    season value = year-end Elo over that year's 20th best year-end Elo (players with 20+ matches), in SDs of the
    year's top 100; peak = best year-end-or-in-season Elo as the same z; career = sum of positive season values"""
    import csv as _csv
    ORD = {'Q1': 0, 'Q2': 1, 'Q3': 2, 'R128': 3, 'R64': 4, 'R32': 5, 'R16': 6, 'RR': 6, 'QF': 7, 'SF': 8, 'BR': 8, 'F': 9}
    M = []
    for f in sorted(glob.glob(os.path.join(CACHE, 'tennis', f'{tour}_[12]*.csv'))):
        for r in _csv.DictReader(open(f, encoding='utf-8', errors='replace')):
            if not r['winner_id'] or not r['loser_id'] or 'W/O' in (r.get('score') or '') or r.get('tourney_level') in ('O',): continue
            M.append((r['tourney_date'], ORD.get(r['round'], 5), r['winner_id'], r['loser_id'], r['tourney_level'] == 'G', r['winner_name'], r['loser_name']))
    M.sort(key=lambda m: (m[0], m[1]))
    E, N, name = defaultdict(lambda: 1500.0), Counter(), {}
    yr_peak, yr_end, yr_n = {}, {}, Counter()
    for d, _, w, l, g, wn, ln in M:
        y = int(d[:4]); name[w] = wn; name[l] = ln
        ew, el = E[w], E[l]; pw = 1 / (1 + 10 ** ((el - ew) / 400))
        kw = 250 / (N[w] + 5) ** .4 * (1.1 if g else 1); kl = 250 / (N[l] + 5) ** .4 * (1.1 if g else 1)
        E[w] = ew + kw * (1 - pw); E[l] = el - kl * (1 - pw); N[w] += 1; N[l] += 1
        for p in (w, l):
            yr_n[(p, y)] += 1; yr_end[(p, y)] = E[p]
            if N[p] >= 40: yr_peak[(p, y)] = max(yr_peak.get((p, y), 0), E[p])
    by = defaultdict(list)
    for (p, y), n in yr_n.items():
        if n >= 20: by[y].append(yr_end[(p, y)])
    out = []
    for (p, y), e in yr_end.items():
        L = sorted(by.get(y, []), reverse=True)
        if len(L) < 50 or yr_n[(p, y)] < 20: continue
        top = L[:100]; sd = float(np.std(top)); line = L[19]
        pk = yr_peak.get((p, y))
        out.append(dict(id=p, n=name[p], y=y, v=(pk - line) / sd if pk else None, cv=max(0.0, (e - line) / sd), raw=round(pk) if pk else None))
    return out


def cbb_players():
    """site CBB WAR (scripts/cbb_tabs.py: (BPM + 2) x minutes / 40 x .68 x wins a point) on every Barttorvik season 2008-"""
    import cbb_data
    wpp = json.load(gzip.open(os.path.join(HERE, 'data', f'cbb_tabs_2026.json.gz')))['wfit']['wpp']
    C = cbb_data.BT_COLS; out = []
    for f in sorted(glob.glob(os.path.join(CACHE, 'cbbp', '*.csv'))):
        for row in csv.reader(open(f, encoding='utf-8', errors='replace')):
            r = dict(zip(C, row))
            try: bpm, gp, mpg, y = float(r['bpm']), float(r['gp']), float(r['mp']), int(float(r['year']))
            except (ValueError, KeyError): continue
            war = (bpm + 2.0) * gp * mpg / 40 * .68 * wpp
            out.append(dict(id=r['pid'], n=r['name'], y=y, tm=r['team'], pos=None, v=war, raw=round(bpm, 1), w=gp * mpg))
    return out


def nfl_players():
    """peak: site AV WAR (scripts/nfl_war.py board, no special teams) a season 2012-; career: PFR weighted career AV
    (nflverse draft_picks, drafted 1980-)"""
    import nfl_war, io, contextlib
    peak = []
    last = max(int(r['season']) for r in csv.DictReader(open(os.path.join(CACHE, 'nfl', 'games.csv'))) if r['home_score'] and r['game_type'] == 'REG')
    for y in range(2012, last):
        with contextlib.redirect_stdout(io.StringIO()):
            rows, _, _ = nfl_war.board(y, st=False)
        for r in rows:
            if r.get('wav') is not None: peak.append(dict(id=r['id'], n=r['n'], y=y, tm=r.get('tm') or r.get('t'), pos=r.get('pos'), v=r['wav'], raw=r.get('av')))
    car = []
    dp = os.path.join(CACHE, 'nfl', 'draft_picks.csv')
    for r in csv.DictReader(open(dp)):
        if r['w_av']: car.append(dict(n=r['pfr_player_name'], y0=int(r['season']), y1=int(r['to'] or r['season']), tm=r['team'], pos=r['position'],
                                      v=float(r['w_av']), s=int(float(r['seasons_started'] or 0)), hof=r['hof'] == 'TRUE', ap=int(float(r['allpro'] or 0))))
    car.sort(key=lambda c: -c['v'])
    return peak, car[:TOP]


def soccer_teams():
    d = json.load(gzip.open(os.path.join(HERE, 'data', 'soccer_team_ratings.json.gz')))['seasons']
    nm = json.load(gzip.open(os.path.join(HERE, 'data', 'soccer_teams.json.gz')))
    BIG = {'eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1'}
    return [dict(t=(nm.get(c) or [c])[0], y=int(s), r=v[1], o=v[2], d=v[3], wl=None, lg=v[0]) for s, L in d.items() for c, v in L.items() if v[0] in BIG]


def soccer_players():
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'static', 'data', 'soccer-war', '*.json'))):
        d = json.load(open(f))
        if d['season'] >= json.load(open(os.path.join(ROOT, 'data', 'soccer_war.json')))['current']: continue
        for p in d['players']:
            if p.get('gar') is not None: out.append(dict(id=p['p'], n=p['n'], y=d['season'], tm=p['team'], pos=p['pos'], v=p['gar'], raw=p.get('min'), w=p.get('min', 1)))
    return out


def cs2_teams():
    c = json.load(gzip.open(os.path.join(HERE, 'data', 'cs2_history.json.gz')))['vrs']
    best = {}
    for d, L in c.items():
        y = int(d[:4])
        for rk, t, pts, *_ in L:
            k = (t, y)
            if rk > 50: continue
            if pts and (k not in best or pts > best[k]['r']): best[k] = dict(t=t, y=y, r=float(pts), wl=None, lg=None, d0=d)
    return [v for v in best.values()]


# ---------------------------------------------------------------- Sports Reference (NBA, NHL, CBB)
def _sr():
    import coach_alltime_pro as cap
    cap.CACHE = os.path.join(CACHE, 'sr')
    return cap


def _pid(cell):
    m = re.search(r'/players/[a-z]/([a-z0-9]+)\.html', cell or '')
    return m.group(1) if m else None


def nba():
    cap = _sr(); T, P = [], []
    for y in range(1947, 2027):
        lg = 'BAA' if y <= 1949 else 'NBA'
        h = cap.get(f'{cap.BB}/leagues/{lg}_{y}.html', False)
        if not h: continue
        tb = cap.tables(h); at = tb.get('advanced-team', [])
        avg = next((r for r in at if 'League Average' in cap.text(r.get('team'))), None)
        if not avg: continue
        lo, ld = cap.num(avg.get('off_rtg')), cap.num(avg.get('def_rtg'))
        gs = 0
        for r in at:
            nm = cap.text(r.get('team')).rstrip('*').strip(); srs = cap.num(r.get('srs'))
            if srs is None or 'League Average' in nm: continue
            w, l = cap.num(r.get('wins')), cap.num(r.get('losses')); gs = max(gs, (w or 0) + (l or 0))
            o, d = cap.num(r.get('off_rtg')), cap.num(r.get('def_rtg'))
            T.append(dict(t=nm, y=y, r=srs, o=(o - lo) if (o and lo and y >= 1952) else None, d=(ld - d) if (d and ld and y >= 1952) else None,
                          wl=[int(w or 0), int(l or 0), 0], lg=None, nt='*' in cap.text(r.get('team')) and 0))
        a = cap.get(f'{cap.BB}/leagues/{lg}_{y}_advanced.html', False)
        if not a: continue
        seen = set()
        for r in cap.tables(a).get('advanced', []):
            pid = _pid(r.get('name_display') or r.get('player'))
            if not pid or pid in seen: continue
            seen.add(pid)
            mp, g = cap.num(r.get('mp')), cap.num(r.get('games') or r.get('g'))
            P.append(dict(id=pid, n=cap.text(r.get('name_display') or r.get('player')).rstrip('*'), y=y, tm=cap.text(r.get('team_name_abbr') or r.get('team_id')),
                          pos=cap.text(r.get('pos')), mp=mp, g=g, gs=gs, vorp=cap.num(r.get('vorp')), bpm=cap.num(r.get('bpm')),
                          ws48=cap.num(r.get('ws_per_48')), per=cap.num(r.get('per')), ws=cap.num(r.get('ws'))))
    # before 1974 (no BPM): BPM from WS / 48 and PER, fit on 1974-85 players with 500+ minutes
    fit = [p for p in P if 1974 <= p['y'] <= 1985 and p['bpm'] is not None and p['ws48'] is not None and p['per'] is not None and (p['mp'] or 0) >= 500]
    X = np.array([[1, p['ws48'], p['per']] for p in fit]); b = np.linalg.lstsq(X, np.array([p['bpm'] for p in fit]), rcond=None)[0]
    r = float(np.corrcoef(X @ b, [p['bpm'] for p in fit])[0, 1])
    S = []
    for p in P:
        if not p['mp'] or not p['gs']: continue
        if p['vorp'] is not None and p['bpm'] is not None:
            v, est = p['vorp'] * 82 / p['gs'], False
        elif p['ws48'] is not None and p['per'] is not None:
            v, est = (b[0] + b[1] * p['ws48'] + b[2] * p['per'] + 2) * p['mp'] / (240 * p['gs']), True
        else: continue
        S.append(dict(id=p['id'], n=p['n'], y=p['y'], tm=p['tm'], pos=(p['pos'] or '').split('-')[0], v=v, raw=p['bpm'] if p['bpm'] is not None else None, est=est,
                      reg=(p['g'] or 0) >= p['gs'] / 2 and (p['mp'] or 0) >= 12 * p['gs']))
    return T, S, dict(b=[round(float(x), 3) for x in b], r=round(r, 3), n=len(fit))


def nhl():
    cap = _sr(); T, S = [], []
    for y in range(1918, 2027):
        if y == 2005: continue
        h = cap.get(f'{cap.HR}/leagues/NHL_{y}.html', False)
        if not h: continue
        tb = cap.tables(h); st = tb.get('stats', [])
        gs = 0; rows = []
        for r in st:
            nm = cap.text(r.get('team_name')).rstrip('*').strip(); srs = cap.num(r.get('srs'))
            gp = cap.num(r.get('games')); gf, ga = cap.num(r.get('goals')), cap.num(r.get('goals_against') or r.get('opp_goals'))
            if srs is None or not gp or 'League Average' in nm or gf is None: continue
            gs = max(gs, gp)
            rows.append(dict(t=nm, y=y, r=srs, gf=gf / gp, ga=ga / gp, sos=cap.num(r.get('sos')) or 0,
                             wl=[int(cap.num(r.get('wins')) or 0), int(cap.num(r.get('losses')) or 0), int((cap.num(r.get('ties')) or 0) + (cap.num(r.get('losses_ot')) or 0))]))
        if not rows: continue
        mf = float(np.mean([r['gf'] for r in rows]))
        for r in rows:
            r['o'] = r['gf'] - mf + r['sos'] / 2; r['d'] = mf - r['ga'] + r['sos'] / 2; r['lg'] = None
            T.append(r)
        for kind in ('skaters', 'goalies'):
            a = cap.get(f'{cap.HR}/leagues/NHL_{y}_{"skaters-misc" if kind == "skaters" else kind}.html', False)
            if not a: continue
            seen = set()
            tbl = cap.tables(a)
            for r in tbl.get('player_stats', []) or tbl.get('stats', []) or next(iter(tbl.values()), []):
                pid = _pid(r.get('name_display') or r.get('player'))
                if not pid or (pid, kind) in seen: continue
                seen.add((pid, kind))
                ps = cap.num(r.get('ps') if kind == 'skaters' else (r.get('gps') or r.get('ps')))
                if ps is None: continue
                g = cap.num(r.get('games') or r.get('goalie_games')) or 0
                S.append(dict(id=pid, n=cap.text(r.get('name_display') or r.get('player')).rstrip('*'), y=y, tm=cap.text(r.get('team_name_abbr') or r.get('team_id')),
                              pos='G' if kind == 'goalies' else (cap.text(r.get('pos')) or '')[:1].replace('L', 'F').replace('R', 'F').replace('C', 'F').replace('W', 'F'),
                              v=ps * 82 / gs, raw=ps, reg=g >= gs / 2))
    # a goalie with skater rows too: keep both seasons' sum as one season
    by = {}
    for s in S:
        k = (s['id'], s['y'])
        if k in by: by[k]['v'] += s['v']; by[k]['raw'] += s['raw']; by[k]['reg'] = by[k]['reg'] or s['reg']
        else: by[k] = s
    return T, list(by.values())


def cbb_teams():
    cap = _sr(); T = []
    for y in range(1950, 2027):
        h = cap.get(f'https://www.sports-reference.com/cbb/seasons/men/{y}-ratings.html', False)
        if not h: continue
        for r in next(iter(cap.tables(h).values()), []) if False else cap.tables(h).get('ratings', []):
            nm = cap.text(r.get('school_name')); srs = cap.num(r.get('srs'))
            if not nm or srs is None: continue
            w, l = cap.num(r.get('wins')), cap.num(r.get('losses'))
            T.append(dict(t=nm, y=y, r=srs, o=cap.num(r.get('srs_off')), d=cap.num(r.get('srs_def')),
                          wl=[int(w or 0), int(l or 0), 0], lg=None))
    return T


def player_era(S, ref=(2012, 2026)):
    """season value in today's units: (v - season mean) / season SD among regulars (pooled +- WIN), times the SD and plus the
    mean of the reference seasons. Keeps v0 (as played, per 82)"""
    reg = defaultdict(list)
    for s in S:
        s['v0'] = s['v']
        if s.get('reg'): reg[s['y']].append(s['v'])
    mu = {y: float(np.mean(L)) for y, L in reg.items()}
    sd = {}
    for y in reg:
        pool = [v - mu[t] for t in range(y - WIN, y + WIN + 1) for v in reg.get(t, [])]
        sd[y] = float(np.sqrt(np.mean(np.square(pool))))
    R = [y for y in reg if ref[0] <= y <= ref[1]]
    m0 = float(np.mean([mu[y] for y in R])); s0 = float(np.mean([sd[y] for y in R]))
    for s in S:
        if s['y'] in mu: s['v'] = m0 + s0 * (s['v0'] - mu[s['y']]) / sd[s['y']]
    return dict(mu=round(m0, 3), sd=round(s0, 3))


def fixenc(x):
    try: return x.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return x


def nfl_champs():
    """season -> champion code: winner of the season's last playoff game (FiveThirtyEight playoff flag; nflverse SB)"""
    from alltime_names import nfl_name
    ch = {}
    for r in csv.DictReader(open(os.path.join(CACHE, 'nfl', '538.csv'))):
        y = int(r['season'])
        if y < 1999 and r['playoff'] not in ('0', ''):
            w = r['team1'] if int(r['score1']) > int(r['score2']) else r['team2']
            if r['date'] >= ch.get(y, ('', ''))[0]: ch[y] = (r['date'], nfl_name(w, y))
    for r in csv.DictReader(open(os.path.join(CACHE, 'nfl', 'games.csv'))):
        if r['game_type'] == 'SB' and r['home_score']:
            y = int(r['season']); w = r['home_team'] if int(r['home_score']) > int(r['away_score']) else r['away_team']
            ch[y] = ('', nfl_name(w, y))
    return {y: v[1] for y, v in ch.items()}


UNITS = {
    'cfb': ('points a game vs an average major-college team, neutral field (ridge SRS on margin capped at 35)',
            'points scored a game over average, schedule-adjusted', 'points allowed a game under average, schedule-adjusted'),
    'nfl': ('points a game vs an average team, neutral field (ridge SRS on margin capped at 35)', 'points scored a game over average, schedule-adjusted',
            'points allowed a game under average, schedule-adjusted'),
    'cbb': ('Sports Reference SRS: points a game vs an average D-I team', 'OSRS: offensive points a game over average, schedule-adjusted', 'DSRS: points prevented a game, schedule-adjusted'),
    'nba': ('Basketball Reference SRS: points a game vs an average team', 'ORtg over the league: points a 100 possessions', 'DRtg under the league: points a 100 possessions'),
    'nhl': ('Hockey Reference SRS: goals a game vs an average team', 'goals for a game over the league + half the SOS', 'goals against a game under the league + half the SOS'),
    'soccer': ('goals a match vs the big-five average club, neutral ground (season end)', 'attack: goals scored a match over the big-five average', 'defence: goals conceded a match under the big-five average'),
    'cs2': ('Valve VRS points, best snapshot of the year',),
}
SRC = {'cfb': 'jhowell.net scores', 'nfl': 'FiveThirtyEight + nflverse scores', 'cbb': 'Sports Reference', 'nba': 'Basketball Reference',
       'nhl': 'Hockey Reference', 'soccer': 'ESPN', 'cs2': 'Valve VRS'}


def teams_out(sp, rows, keys=('r', 'o', 'd')):
    for r in rows: r['t'] = fixenc(r['t'])
    T = team_lists(rows, keys)
    T['units'] = dict(zip(['teams', 'offense', 'defense'], UNITS[sp])); T['src'] = SRC[sp]
    T['wl'] = any(r.get('wl') for r in rows); T['lg'] = any(r.get('lg') for r in rows)
    return T


def players_out(seasons, pk, car, src, pos=True, tm=True, est=None, career=None, abouts=('', '')):
    P = player_lists(seasons, 'v')
    if career is not None: P['career'] = career
    for L in (P['peak'], P['career']):
        for r in L: r['n'] = fixenc(r['n'])
    P.update(pk=pk, car=car, src=src, pos=pos, tm=tm, estT=est or '', peak_about=abouts[0], career_about=abouts[1])
    P['from'] = P.pop('from_')
    return P


def main():
    import datetime as dt
    snap = '--snap' in sys.argv
    res = {'asof': dt.date.today().isoformat(), 'top': TOP, 'perDec': PER_DEC}
    if snap:
        src = json.load(gzip.open(SNAP))
    else:
        nT, nS, nfit = nba(); hT, hS = nhl()
        nflpk, nflcar = nfl_players()
        src = dict(cfb=cfb_rows(), nfl=nfl_rows(), nflch=nfl_champs(), cbb=cbb_teams(), nbaT=nT, nbaS=nS, nbafit=nfit, nhlT=hT, nhlS=hS,
                   soccerT=soccer_teams(), cs2T=cs2_teams(), cbbS=cbb_players(), nflpk=nflpk, nflcar=nflcar, soccerS=soccer_players(),
                   atp=tennis_players('atp'), wta=tennis_players('wta'))
        rnd = lambda x: round(x, 3) if isinstance(x, float) else [rnd(v) for v in x] if isinstance(x, list) else {k: rnd(v) for k, v in x.items()} if isinstance(x, dict) else x
        json.dump(rnd(src), gzip.open(SNAP, 'wt'), separators=(',', ':'))
    ch = {int(k): v for k, v in src['nflch'].items()}
    for r in src['nfl']: r['nt'] = 1 if ch.get(r['y']) == r['t'] else 0
    for r in src['nbaT'] + src['nhlT']: r['nt'] = 0
    res['cfb'] = {'teams': teams_out('cfb', src['cfb'])}
    res['nfl'] = {'teams': teams_out('nfl', src['nfl'])}
    res['cbb'] = {'teams': teams_out('cbb', src['cbb'])}
    res['nba'] = {'teams': teams_out('nba', src['nbaT'])}
    res['nhl'] = {'teams': teams_out('nhl', src['nhlT'])}
    res['soccer'] = {'teams': teams_out('soccer', src['soccerT'])}
    # CS2: each snapshot's top 50 are the pool
    res['cs2'] = {'teams': teams_out('cs2', src['cs2T'], keys=('r',))}
    nf = src['nbafit']
    for k in ('nbaS', 'nhlS'): player_era(src[k])
    res['nba']['players'] = players_out(src['nbaS'], dict(l='VORP', t='value over replacement player (Basketball Reference), per 82 games', f='%.1f', rl='BPM', rt='box plus-minus', rf='%.1f'),
                                        dict(l='VORP', t='career VORP, each season per 82 games', f='%.0f', s=1, pl='Peak', pt='best season VORP per 82'),
                                        'Basketball Reference', est=f'before 1973-74 (no BPM): BPM from WS/48 and PER, fit on 1974-85 (r {nf["r"]:.2f})',
                                        abouts=('Regular season. VORP = (BPM + 2) x share of team minutes, per 82 games.', 'Regular season, 1951-52 on (minutes).'))
    res['nba']['players']['fit_r'] = nf['r']
    res['nhl']['players'] = players_out(src['nhlS'], dict(l='PS', t='point shares (Hockey Reference: standings points created), per 82 games', f='%.1f', rl='Raw', rt='point shares, as played', rf='%.1f'),
                                        dict(l='PS', t='career point shares, each season per 82 games', f='%.0f', s=1, pl='Peak', pt='best season PS per 82'),
                                        'Hockey Reference', abouts=('Skaters OPS + DPS, goalies GPS.', ''))
    res['cbb']['players'] = players_out(src['cbbS'], dict(l='WAR', t='wins over a replacement player: (BPM + 2) x minutes / 40 x .68 x wins a point (CBB WAR)', f='%.1f', rl='BPM', rt='Barttorvik box plus-minus', rf='%.1f'),
                                        dict(l='WAR', t='career WAR, D-I seasons 2007-08 on', f='%.1f', s=1, pl='Peak', pt='best season WAR'),
                                        'Barttorvik', pos=False)
    car = [dict(c, est=None) for c in src['nflcar']]
    res['nfl']['players'] = players_out(src['nflpk'], dict(l='WAR', t='NFL WAR from rebuilt AV (AV WAR, no special teams), 2012 on (snap counts)', f='%.2f', rl='AV', rt='approximate value, rebuilt from nflverse', rf='%.1f'),
                                        dict(l='wAV', t="Pro Football Reference weighted career AV (best season 100%, next 95%, ...): players drafted 1980 on", f='%.0f', s=1, pl='', pt=''),
                                        'nflverse + Pro Football Reference', career=car, abouts=('Seasons 2012 on.', 'Drafted players 1980 on (undrafted players are not in the file).'))
    res['soccer']['players'] = players_out(src['soccerS'], dict(l='GAR', t='goals above replacement (soccer GAR), big-five leagues', f='%.1f', rl='Min', rt='minutes', rf='%.0f'),
                                           dict(l='GAR', t='career GAR, big-five seasons 2014-15 on', f='%.0f', s=1, pl='Peak', pt='best season GAR'), 'ESPN + FotMob',
                                           abouts=('Big-five league seasons 2014-15 on.', ''))
    for t in ('atp', 'wta'):
        S = src[t]
        pk = players_out([dict(s, v=100 + 25 * s['v']) for s in S if s['v'] is not None],
                         dict(l='Elo+', t="peak Elo that year against the year's #20 (100) in SDs of the year's top 100 (x25)", f='%.0f', rl='Elo', rt='peak Elo that year', rf='%.0f'),
                         {}, 'Sackmann archive', pos=False, tm=False)
        cr = players_out([dict(s, v=s['cv']) for s in S], {}, dict(l='Career', t="sum of year-end Elo over the year's #20, in SDs of the year's top 100", f='%.1f', s=1, pl='', pt=''),
                         'Sackmann archive', pos=False, tm=False)
        pk['career'] = cr['career']; pk['car'] = cr['car']
        pk['peak_about'] = 'Tour-level singles; peak counts after 40 matches.'; pk['career_about'] = 'Years with 20+ tour-level matches.'
        res[t] = {'players': pk}
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
    for s in ('cfb', 'nfl', 'cbb', 'nba', 'nhl', 'soccer', 'cs2', 'atp', 'wta'):
        v = res[s]; T = v.get('teams')
        if T:
            print(s, T['n'], T['from'], T['to'], {k: T[k] for k in T if k.endswith('_check')})
            for k in ('teams', 'offense', 'defense'):
                if k in T: print('  ', k, [(r['t'], r['y'], r['p' + ('r' if k == 'teams' else k[0])]) for r in T[k][:6]])
        P = v.get('players')
        if P:
            print('  peak', [(r['n'], r['y'], r['v']) for r in P['peak'][:6]]); print('  career', [(r['n'], r['v']) for r in P['career'][:6]])
    print('bytes', os.path.getsize(OUT))


if __name__ == '__main__':
    main()
