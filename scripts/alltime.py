#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""All-time team-season and player rankings for every ARKBOARD sport (data/alltime.json, shortcode alltime.html).

    python3 scripts/alltime_pull.py all     # pages and files (cache scripts/.cache/alltime, ~40 min the first time)
    python3 scripts/alltime.py              # build data/alltime.json (and the snapshot scripts/data/alltime_src.json.gz)
    python3 scripts/alltime.py --snap       # rebuild from the snapshot only (no cache needed)

Era adjustment (every sport, teams and players): a season's value is set against the spread of that league in that era.
  Teams    Rtg+ / Off+ / Def+ = 100 + 25 z, z = (rating - season mean) / s, s = the upper semi-deviation x sqrt 2 (spread(),
           Nov 23; the SD before), pooled over the season and the two either side (team ratings demeaned by season).
           100 = an average team that season, 125 = one s better. Same scale as Stat+.
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
  Era check (about in each table): decade share of the top 100 against the decade's share of rows; KL divergence
  of the adjusted list vs the raw one (lower = no era favoured) and the era-blind 95% line (null95); every list passes
  (Nov 23 2026). Players: each player's best season once.
"""
import gzip, json, math, os, sys, csv, re, glob
from collections import defaultdict, Counter
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
CACHE = os.path.join(HERE, '.cache', 'alltime')
OUT = os.environ.get('ALLTIME_OUT') or os.path.join(ROOT, 'data', 'alltime.json')
SNAP = os.path.join(HERE, 'data', 'alltime_src.json.gz')
TOP, PER_DEC = 250, 25           # list: the top TOP plus the top PER_DEC of every decade
WIN = 2                          # SD pooled over the season +- WIN
CAP = 35


def plus(z): return round(100 + 25 * z, 1)


def spread(dev, upper=True):
    """a season's scale from deviations about its mean. upper (team lists, Nov 23): the upper semi-deviation x sqrt 2,
    sqrt(2 mean(max(d, 0)^2)), which equals the SD for a normal season but is not stretched by a long bottom tail (a
    0-points-allowed floor in low-scoring eras, blowout losers, a wide spread of weak programs), so the best teams of
    each era are measured against how far good teams spread above average that era. upper=False: the SD (player pools,
    already cut to regulars, Nov 20)"""
    d = np.asarray(dev, float)
    if not len(d): return 0.0
    return float(np.sqrt(2 * np.mean(np.square(np.maximum(d, 0))))) if upper else float(np.sqrt(np.mean(np.square(d))))


def era_z(rows, keys, group=lambda r: r['y']):
    """adds z<key> to rows: (value - season mean) / SD pooled over seasons +- WIN"""
    by = defaultdict(list)
    for r in rows: by[group(r)].append(r)
    for k in keys:
        mu = {s: float(np.mean([r[k] for r in L if r.get(k) is not None] or [0])) for s, L in by.items()}
        dev = {s: [r[k] - mu[s] for r in L if r.get(k) is not None] for s, L in by.items()}
        for s, L in by.items():
            pool = [d for t in range(s - WIN, s + WIN + 1) for d in dev.get(t, [])]
            sd = spread(pool) if len(pool) > 3 else None
            for r in L:
                r['z' + k] = (r[k] - mu[s]) / sd if (sd and r.get(k) is not None) else None


def null95(base, n, sims=4000, seed=7):
    """95th percentile of the KL below when the top n are drawn era-blind (multinomial on the decades' shares of rows)"""
    ds = sorted(base); p = np.array([base[d] for d in ds], float); p /= p.sum()
    C = np.random.default_rng(seed).multinomial(n, p, sims) / n
    with np.errstate(divide='ignore', invalid='ignore'):
        k = np.where(C > 0, C * np.log(C / p), 0).sum(1)
    return float(np.quantile(k, .95))


def era_check(rows, zk, rk, n=100):
    """KL(top-n decade share || all-row decade share), adjusted (z) vs raw, and the era-blind 95% line (null95). Player
    rows (with an id) count each player's best season once, rows with an eb are binned by it instead of the decade, so one player's run of seasons (Gretzky's eight 1980s
    seasons) is not read as an era effect; pass = adjusted under the line (Nov 23)"""
    def best(key):
        R = sorted([r for r in rows if r.get(key) is not None], key=lambda r: -r[key])
        if not R or 'id' not in R[0]: return R
        seen, out = set(), []
        for r in R:
            if r['id'] not in seen: seen.add(r['id']); out.append(r)
        return out
    def kl(key):
        eb = lambda r: r['eb'] if 'eb' in r else r['y'] // 10 * 10     # era bin: the decade (hockey prospects: the draft class, 5 years)
        R = best(key); base = Counter(eb(r) for r in R); tot = sum(base.values())
        c = Counter(eb(r) for r in R[:n])
        return sum((c[d] / n) * math.log((c[d] / n) / (base[d] / tot)) for d in c), base
    a, base = kl(zk)
    return round(a, 3), round(kl(rk)[0], 3), round(null95(base, n), 3)


def pick(rows, key, top=TOP, per=PER_DEC):
    R = sorted([r for r in rows if r.get(key) is not None], key=lambda r: -r[key])
    keep = set(id(r) for r in R[:top])
    per_d = Counter()
    for r in R:
        d = r['y'] // 10 * 10
        if per_d[d] < per: keep.add(id(r)); per_d[d] += 1
    return [r for r in R if id(r) in keep]


def sv_hist(sp):
    """SV (season value) rows for past seasons (scripts/sv_history.py -> scripts/data/sv_hist.json.gz), [] when missing"""
    try:
        return json.load(gzip.open(os.path.join(HERE, 'data', 'sv_hist.json.gz'), 'rt')).get(sp) or []
    except (OSError, ValueError):
        return []


def pick_sv(rows, key='v'):
    """the peak list by the main key plus the top by SV (so a header sort by SV ranks the real SV leaders); rows without
    the main key last"""
    keep, out = set(), []
    for r in pick(rows, key) + pick(rows, 'sv') + pick(rows, 'svar'):
        if id(r) not in keep:
            keep.add(id(r)); out.append(r)
    return sorted(out, key=lambda r: (r.get(key) is None, -(r.get(key) or 0), -(r.get('sv') or 0)))


def svar(r, sp):
    """SVAR: the season's SV points over replacement in wins (NFL / 36 a win, on 17 games; CFB / 1 / .0189 = 52.9 a win)"""
    if r.get('tot') is None: return None
    return round(r['tot'] * 17 / (16 if r['y'] <= 2020 else 17) / 36, 2) if sp == 'nfl' else round(r['tot'] * 0.0189, 2)


SV_T = ('SV (season value): points over replacement a game that season, EPA a play (QB dropbacks + runs; runs + targets; '
        'defenders: credited EPA on negative plays) less the opponent\'s rate where it helped, replacement moved with that '
        "season's league EPA (era)")


def soccer_sv_attach(P, S):
    """SV (goals over replacement a 90) and SVAR (season total) on the soccer peak list, as played (scripts/soccer_sv.py);
    the list also takes the top seasons by SVAR, so a sort by SVAR ranks the real leaders"""
    if not any(x.get('svar') is not None for x in S): return
    k = lambda n, y, tm: (fixenc(n), y, tm)
    m = {k(x['n'], x['y'], x.get('tm')): x for x in S}
    have = {k(r['n'], r['y'], r.get('tm')) for r in P['peak']}
    for x in sorted((x for x in S if x.get('svar') is not None), key=lambda x: -x['svar'])[:TOP]:
        if k(x['n'], x['y'], x.get('tm')) not in have:
            P['peak'].append(dict(n=fixenc(x['n']), y=x['y'], tm=x.get('tm'), pos=x.get('pos'), v=None if x['v'] is None else round(x['v'], 2),
                                  raw=x.get('raw'), est=None, ph=x.get('ph'), ox=None, dx=None, u=None if x.get('v0') is None else round(x['v0'], 2)))
    for r in P['peak']:
        x = m.get(k(r['n'], r['y'], r.get('tm'))) or {}
        r['sv'], r['svar'] = x.get('sv'), x.get('svar')
    P['peak'].sort(key=lambda r: (r.get('v') is None, -(r.get('v') or 0)))
    P['sv'], P['svf'], P['svarf'] = True, '%+.2f', '%+.1f'
    P['svT'] = ("SV (season value): goals over replacement a 90 that season from that season alone (GAR's weights on its "
                "inputs with a one-season xG plus-minus, plus finishing and keeper saves shrunk by split-half reliability), as played; 2014-15 on")
    P['svarT'] = 'SVAR = SV x 90s played: the season total in goals, GAR scale, as played'


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
            out.append(dict(t=nfl_name(t, y), y=y, r=rt, o=o, d=d, wl=wl[(t, y)], lg=lg, c=t))
    return out


def cfb_rows():
    d = json.load(gzip.open(os.path.join(HERE, 'data', 'coach_alltime_src.json.gz')))['cfb']
    nm = d['teams']
    return [dict(t=nm.get(r['t'], r['t']), y=r['y'], r=r['r'], o=r['o'], d=r['d'], wl=r['wl'], lg=None, nt=r.get('nt') or 0, c=nm.get(r['t'], r['t']))
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
        out[names[k]] = [{**{f: r.get(f) for f in ('t', 'y', 'wl', 'lg', 'nt', 'c')}, 'pr': r.get('pr'), 'po': r.get('po'), 'pd': r.get('pd'),
                          'raw': round(r[k], 2)} for r in L]
        out[names[k] + '_check'] = era_check(rows, 'z' + k, k)
    out['n'] = len(rows); out['from'] = min(r['y'] for r in rows); out['to'] = max(r['y'] for r in rows)
    return out


# ---------------------------------------------------------------- players
def player_lists(seasons, key_v, minv=None, per=None, every=False):
    """seasons: dicts id, n, y, v (value, era-adjusted already), (+ tm, pos). -> peak and career (sum).
    every: the peak list ranks every player-season (a player can appear more than once); else his best season only"""
    peak = sorted([s for s in seasons if s['v'] is not None], key=lambda s: -s['v'])
    best = {}
    for s in peak:
        if s['id'] not in best: best[s['id']] = s
    P = peak if every else list(best.values())
    car = defaultdict(lambda: dict(v=0.0, n=0))
    for s in seasons:
        if s['v'] is None: continue
        c = car[s['id']]; c['v'] += max(0.0, s['v']) if s.get('pos_only') else s['v']; c['n'] += 1
        c['y0'] = min(c.get('y0', 9999), s['y']); c['y1'] = max(c.get('y1', 0), s['y'])
        c['nm'] = s['n']; c['tm'] = c.get('tms', Counter()); c.setdefault('tms', Counter())[s.get('tm') or ''] += max(1.0, s.get('w', 1))
        c['pos'] = s.get('pos'); c['est'] = c.get('est', False) or bool(s.get('est'))
        c['bestv'] = max(c.get('bestv', -99), s['v'])
        if s.get('ph') and s['y'] >= c.get('phy', 0): c['ph'], c['phy'] = s['ph'], s['y']
        if s.get('ox') is not None and s.get('mp'):
            c['om'] = c.get('om', 0) + s['ox'] * s['mp']; c['dm'] = c.get('dm', 0) + s['dx'] * s['mp']; c['xm'] = c.get('xm', 0) + s['mp']
    C = sorted(car.items(), key=lambda kv: -kv[1]['v'])
    def prow(s):
        return dict(n=s['n'], y=s['y'], tm=s.get('tm'), pos=s.get('pos'), v=round(s['v'], 2), raw=s.get('raw'), est=s.get('est') or None,
                    ph=s.get('ph'), ox=s.get('ox'), dx=s.get('dx'), u=None if s.get('v0') is None else round(s['v0'], 2))
    def crow(pid, c):
        return dict(n=c['nm'], y0=c['y0'], y1=c['y1'], tm=c['tms'].most_common(1)[0][0], pos=c['pos'], v=round(c['v'], 1), s=c['n'],
                    pk=round(c['bestv'], 2), est=c['est'] or None, ph=c.get('ph'),
                    ox=round(c['om'] / c['xm'], 1) if c.get('xm') else None, dx=round(c['dm'] / c['xm'], 1) if c.get('xm') else None)
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
    """site CBB WAR (scripts/cbb_tabs.py: (shrunk rXPM - REPL) x minutes / 40 x .68 x wins a point; rXPM shrunk GBPM_K
    minutes toward that season's minutes-weighted mean, Nov 24 2026 port round) on every Barttorvik season 2008-"""
    import cbb_data, cbb_tabs
    wpp = json.load(gzip.open(os.path.join(HERE, 'data', f'cbb_tabs_2026.json.gz')))['wfit']['wpp']
    C = cbb_data.BT_COLS; rows = []
    for f in sorted(glob.glob(os.path.join(CACHE, 'cbbp', '*.csv'))):
        for row in csv.reader(open(f, encoding='utf-8', errors='replace')):
            r = dict(zip(C, row))
            try: bpm, gp, mpg, y = float(r['bpm']), float(r['gp']), float(r['mp']), int(float(r['year']))
            except (ValueError, KeyError): continue
            try: gb = float(r['gbpm'])
            except (ValueError, KeyError): gb = bpm
            rows.append((r, bpm, gb, gp * mpg, y))
    num, den, sh = defaultdict(float), defaultdict(float), defaultdict(lambda: [0.0, 0.0])
    for r, bpm, gb, m, y in rows:
        num[y] += gb * m; den[y] += m; q = sh[(r['team'], y)]; q[0] += (gb - bpm) * m; q[1] += m
    out = []
    for r, bpm, gb, m, y in rows:
        q = sh[(r['team'], y)]     # rXPM (Nov 26 2026): BPM plus the team's minutes-weighted mean (GBPM - BPM), scripts/cbb_xpm.py
        x = cbb_tabs.wx({'xpm': bpm + (q[0] / q[1] if q[1] else 0.0)}, m, num[y] / den[y] if den[y] else None)
        war = (x - cbb_tabs.REPL) * m / 40 * .68 * wpp
        out.append(dict(id=r['pid'], n=r['name'], y=y, tm=r['team'], pos=None, v=war, raw=round(bpm, 1), w=m))
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


def nfl_era(S, starters=704, ref=10):
    """NFL season WAR in today's units (Nov 23): rosters grew (1,734 WAR rows in 2013, 2,055 in 2021) and the top thinned
    (mean of the top 50 .79 -> .73 a season), so each season's WAR is set against that season's starters at the position
    (the top k by WAR, k = the position's share of the season's rows x 704 = 32 teams x 22 starters):
    v = mu_ref + sd_ref x (WAR - season mean) / season SD, ref = the position's last `ref` seasons. Keeps v0 (on 17 games)"""
    by, n_y = defaultdict(list), Counter()
    for x in S: by[(x['y'], x.get('pos'))].append(x['v']); n_y[x['y']] += 1
    st = {}
    for k, v in by.items():
        t = np.array(sorted(v, reverse=True)[:max(5, int(starters * len(v) / n_y[k[0]]))])
        st[k] = (float(t.mean()), float(t.std()) or 1.0)
    ys = sorted(n_y)
    for x in S:
        k = (x['y'], x.get('pos')); R = [st[(y, k[1])] for y in ys[-ref:] if (y, k[1]) in st]
        x['v0'] = x['v']; x['v'] = float(np.mean([a for a, _ in R])) + float(np.mean([b for _, b in R])) * (x['v'] - st[k][0]) / st[k][1]
    return S


def nfl_wav():
    """draft picks: pfr id -> (name, drafted, last season, pos, team, weighted career AV)"""
    out = {}
    for r in csv.DictReader(open(os.path.join(CACHE, 'nfl', 'draft_picks.csv'))):
        if r['pfr_player_id'] and r['w_av']:
            out[r['pfr_player_id']] = [r['pfr_player_name'], int(r['season']), int(r['to'] or r['season']), r['position'], r['team'], float(r['w_av']), r['hof'] == 'TRUE']
    return out


def nfl_career(pk, wav, top=TOP):
    """career = the site's AV WAR summed over 2012 on, plus for seasons before 2012 c x weighted career AV x the share of
    his seasons played before 2012. c fit (through 0) on players drafted 2003-11 still playing after 2012: their 2012-on
    WAR against weighted career AV x the share of seasons from 2012 on"""
    last = max(s['y'] for s in pk)
    tot = defaultdict(lambda: dict(v=0.0, n=0, ys=[], tm=Counter()))
    for s in pk:
        t = tot[s['id']]; t['v'] += s['v']; t['n'] += 1; t['ys'].append(s['y']); t['tm'][s['tm']] += 1; t['nm'] = s['n']; t['pos'] = s['pos']
    pre = lambda w: max(0.0, min(1.0, (2012 - w[1]) / (w[2] - w[1] + 1)))
    pr = [(w[5] * (1 - pre(w)), tot[i]['v']) for i, w in wav.items() if 2003 <= w[1] < 2012 and w[2] >= 2013 and i in tot and pre(w) <= .7]
    a = np.array(pr); c = float((a[:, 0] @ a[:, 1]) / (a[:, 0] @ a[:, 0])); r = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
    rows = []
    for i, t in tot.items():
        w = wav.get(i); est = None; v = t['v']; y0 = min(t['ys'])
        if w and w[1] < 2012:
            y0 = w[1]; v += c * w[5] * pre(w); est = True
        rows.append(dict(n=t['nm'], y0=y0, y1=max(t['ys']), tm=t['tm'].most_common(1)[0][0], pos=t['pos'], v=round(v, 1), s=t['n'] + (2012 - w[1] if est else 0), est=est, hof=(w[6] if w else None) or None))
    for i, w in wav.items():
        if i not in tot and w[2] < 2012:
            rows.append(dict(n=w[0], y0=w[1], y1=w[2], tm=w[4], pos=w[3], v=round(c * w[5], 1), s=w[2] - w[1] + 1, est=True, hof=w[6] or None))
    rows.sort(key=lambda r: -r['v'])
    return rows[:top], dict(b=round(c, 4), r=round(r, 3), n=len(a))


NFL_REL = 'https://github.com/nflverse/nflverse-data/releases/download'


def nfl_qb_pull(last):
    """QB lines for the all-time QB lists: every QB regular season 1999-last (nflverse stats_player_reg) and drafted QBs'
    career passing (nflverse draft_picks, PFR totals). seasons: [name, y, team, att, cmp, yds, td, int, sk, sk yds, air
    yds, pass EPA, CPOE, rush EPA, carries, rush yds]; dp: [name, drafted, last season, att, cmp, yds, td, int, rush yds]"""
    from nfl_pbp import download
    D = os.path.join(CACHE, 'nfl'); os.makedirs(D, exist_ok=True)
    f = lambda x: float(x) if x not in (None, '', 'NA') else 0.0  # noqa: E731
    seasons = []
    for y in range(1999, last + 1):
        p = os.path.join(D, f'stats_player_reg_{y}.csv')
        if not os.path.exists(p): download(f'{NFL_REL}/stats_player/stats_player_reg_{y}.csv', p)
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if f(r['attempts']) < 1: continue   # any listed position: Taysom Hill is a TE in nflverse
            seasons.append([r['player_display_name'], y, r['recent_team']] + [f(r[k]) for k in (
                'attempts', 'completions', 'passing_yards', 'passing_tds', 'passing_interceptions', 'sacks_suffered', 'sack_yards_lost',
                'passing_air_yards', 'passing_epa', 'passing_cpoe', 'rushing_epa', 'carries', 'rushing_yards')])
    p = os.path.join(D, 'draft_picks.csv')
    if not os.path.exists(p): download(f'{NFL_REL}/draft_picks/draft_picks.csv', p)
    dp = [[r['pfr_player_name'], int(r['season']), int(r['to'] or r['season'])] + [f(r[k]) for k in ('pass_attempts', 'pass_completions', 'pass_yards', 'pass_tds', 'pass_ints', 'rush_yards')]
          for r in csv.DictReader(open(p, encoding='utf-8')) if f(r['pass_attempts']) > 0]
    return dict(seasons=seasons, dp=dp)


def nfl_qb_attach(P, Q):
    """QB columns on the all-time QB lists. peak: that season's line (EPA a dropback = pass EPA / (att + sacks), CPOE,
    ANY/A, sack %, aDOT, INT %, rush EPA, dropbacks). career: Cmp %, yards, TD, INT, AY/A, rush yards, from the nflverse
    seasons when the career starts 1999 or later, else PFR's career totals (draft_picks)"""
    import names as NM
    by_y = defaultdict(list)
    for s in Q['seasons']: by_y[s[1]].append(s)
    # ANY/A+ = 100 + 25 z against that season's QBs with 200+ attempts (ANY/A has climbed with the passing game)
    lg = {}
    for y, L in by_y.items():
        a = [(s[5] + 20 * s[6] - 45 * s[7] - s[9]) / (s[3] + s[8]) for s in L if s[3] >= 200]
        if len(a) > 5: m = sum(a) / len(a); lg[y] = (m, (sum((x - m) ** 2 for x in a) / len(a)) ** .5)
    for r in P['peak']:
        c = [s for s in by_y[r['y']] if NM.same(s[0], r['n'])]
        c.sort(key=lambda s: (s[2] != (r.get('tm') or '').split('/')[-1], -s[3]))
        if not c: continue
        _, _, _, att, cm, yd, td, it, sk, sky, ay, pe, cpoe, re_, car, ry = c[0]
        db = att + sk
        r['q'] = dict(epa=round(pe / db, 3), cpoe=round(cpoe, 1), anya=round((yd + 20 * td - 45 * it - sky) / db, 2), sk=round(100 * sk / db, 1),
                      adot=round(ay / att, 1), int=round(100 * it / att, 1), rush=round(re_, 1), db=int(db))
        if r['y'] in lg: r['q']['anyx'] = round(100 + 25 * (r['q']['anya'] - lg[r['y']][0]) / lg[r['y']][1])
    for r in P['career']:
        if r['y0'] >= 1999:
            c = [s for s in Q['seasons'] if r['y0'] <= s[1] <= r['y1'] and NM.same(s[0], r['n'])]
            if not c: continue
            att, cm, yd, td, it, ry = (sum(s[k] for s in c) for k in (3, 4, 5, 6, 7, 15))
        else:
            c = [d for d in Q['dp'] if NM.same(d[0], r['n']) and abs(d[1] - r['y0']) <= 1]
            if not c: continue
            _, _, _, att, cm, yd, td, it, ry = c[0]
        r['q'] = dict(cmp=round(100 * cm / att, 1), yds=int(yd), td=int(td), int=int(it), aya=round((yd + 20 * td - 45 * it) / att, 2), ry=int(ry))
    miss = [r['n'] for r in P['peak'] + P['career'] if 'q' not in r]
    if miss: print('nfl QB lines missing (left off the QB lists)', miss)
    P['peak'] = [r for r in P['peak'] if 'q' in r]; P['career'] = [r for r in P['career'] if 'q' in r]



def cfb_qb_pull(y0=2004, y1=2025, per=150, workers=8):
    """CFB QB seasons for the all-time QB lists: each FBS regular season's top `per` passers by yards (ESPN byathlete,
    one call a season), then each one's season line (ESPN core athletes/<id>/statistics; cached in CACHE/cfb_qb).
    -> [espn id, name, y, team id, school, games, att, cmp, yds, td, int, sacks, sack yds, adj QBR, rush att, rush yds, rush td]
    (college rush att / yds include sacks)"""
    import urllib.request, time
    from concurrent.futures import ThreadPoolExecutor
    D = os.path.join(CACHE, 'cfb_qb'); os.makedirs(D, exist_ok=True)
    def get(u, fn):
        p = os.path.join(D, fn)
        if os.path.exists(p): return json.load(open(p))
        for k in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as r: d = json.load(r)
                json.dump(d, open(p, 'w')); return d
            except Exception as e:  # noqa: BLE001
                if getattr(e, 'code', None) == 404: return {}
                time.sleep(2 * (k + 1))
        return {}
    who = []
    for y in range(y0, y1 + 1):
        d = get('https://site.web.api.espn.com/apis/common/v3/sports/football/college-football/statistics/byathlete?region=us&lang=en'
                f'&contentorigin=espn&isqualified=false&page=1&limit={per}&season={y}&seasontype=2&category=offense&sort=passing.passingYards:desc', f'lead_{y}.json')
        for a in d.get('athletes', []):
            x = a['athlete']; t = (x.get('teams') or [{}])[0]
            who.append((x['id'], x['displayName'], y, x.get('teamId') or t.get('id'), t.get('shortDisplayName') or x.get('teamShortName')))
    def line(w):
        aid, n, y, tid, sch = w
        d = get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/{y}/types/2/athletes/{aid}/statistics', f'{y}_{aid}.json')
        S = {}
        for c in (d.get('splits') or {}).get('categories', []):
            for st in c.get('stats', []): S[c['name'] + '.' + st['name']] = st.get('value')
        g = lambda k: float(S.get(k) or 0.0)  # noqa: E731
        if g('passing.passingAttempts') < 1: return None
        return [aid, n, y, tid, sch, int(g('general.gamesPlayed')), g('passing.passingAttempts'), g('passing.completions'), g('passing.passingYards'),
                g('passing.passingTouchdowns'), g('passing.interceptions'), g('passing.sacks'), abs(g('passing.sackYardsLost')),
                S.get('passing.adjQBR'), g('rushing.rushingAttempts'), g('rushing.rushingYards'), g('rushing.rushingTouchdowns')]
    with ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(line, who) if r]


def era_factor(dev, ref=10):
    """dev: {(season, group): [deviations from that season's baseline]} -> {(season, group): spread_ref / spread_season}, the
    spread (the SD about the baseline, as the player pools) pooled over the season +- WIN and ref = the mean over the group's last `ref` seasons:
    multiplies a season's over-baseline value into today's units (CFB QB / skill lists, Nov 23)"""
    out = {}
    for g in {k[1] for k in dev}:
        ys = sorted(y for y, h in dev if h == g)
        sp = {y: spread([d for t in range(y - WIN, y + WIN + 1) for d in dev.get((t, g), [])], upper=False) or 1.0 for y in ys}
        s0 = float(np.mean([sp[y] for y in ys[-ref:]]))
        for y in ys: out[(y, g)] = s0 / sp[y]
    return out


def cfb_qb_lists(rows, minq=150):
    """CFB all-time QB lists (peak seasons, careers), FBS regular seasons from 2004. Each season's plays = pass att + rush
    att (college counts sacks as runs, sack yards in rushing). TAY/P = (pass yds + 20 pass TD - 45 INT + rush yds + 20 rush
    TD) / plays. Yds+ = (TAY/P - that season's average TAY/P over QBs with minq+ attempts, play-weighted) x plays: adjusted
    yards over an average FBS QB, no opponent adjustment. TAY/P+ = 100 + 25 z within the season (QBs with minq+ attempts).
    peak = every season on its own by Yds+; career = Yds+ summed over the seasons in the pool (top 150 passers a season)."""
    import names as NM
    S = []
    for r in rows:
        aid, n, y, tid, sch, gp, att, cm, yd, td, it, sk, sky, qbr, ra, ry, rtd = r
        pl = att + ra
        S.append(dict(id=aid, n=n, y=y, tid=tid, tm=sch, g=gp, att=att, cm=cm, yd=yd, td=td, it=it, sk=sk, sky=sky, qbr=qbr, ra=ra, ry=ry, rtd=rtd,
                      pl=pl, tay=(yd + 20 * td - 45 * it + ry + 20 * rtd) / pl if pl else 0.0))
    by = defaultdict(list)
    for s in S:
        if s['att'] >= minq: by[s['y']].append(s)
    M = {y: sum(q['tay'] * q['pl'] for q in Q) / sum(q['pl'] for q in Q) for y, Q in by.items()}
    F = era_factor({(y, ''): [q['tay'] - M[y] for q in Q] for y, Q in by.items()})
    for s in S:
        Q = by[s['y']]; m = M[s['y']]
        sd = (sum((q['tay'] - m) ** 2 for q in Q) / len(Q)) ** .5
        s['v0'] = (s['tay'] - m) * s['pl']; s['v'] = s['v0'] * F[(s['y'], '')]; s['ix'] = 100 + 25 * (s['tay'] - m) / sd
    # era (Nov 20 2026): plays per qualified QB run flat 2004-25 (355-422 a season, no upward trend), so volume is not
    # rescaled; scaling to it mostly inflated 2020's short schedules. Nov 23: the rate over average is also put in today's
    # spread (era_factor: the season's upper semi-RMS of TAY/P about the average, pooled +- 2, vs the last 10 seasons).
    lo = lambda tid: f'/img/cfb/logos/{tid}.png' if tid and os.path.exists(os.path.join(IMG, 'cfb', 'logos', f'{tid}.png')) else (f'https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/{tid}.png&w=40&h=40' if tid else None)
    def q_of(L):
        att = sum(s['att'] for s in L); sk = sum(s['sk'] for s in L); yd = sum(s['yd'] for s in L); td = sum(s['td'] for s in L); it = sum(s['it'] for s in L)
        qa = [(s['qbr'], s['att']) for s in L if s['qbr'] is not None]
        return dict(cmp=round(100 * sum(s['cm'] for s in L) / att, 1), ya=round(yd / att, 1), anya=round((yd + 20 * td - 45 * it - sum(s['sky'] for s in L)) / (att + sk), 2),
                    yds=int(yd), td=int(td), int=int(it), qbr=round(sum(a * b for a, b in qa) / sum(b for _, b in qa), 1) if qa else None,
                    ry=int(sum(s['ry'] for s in L)), rtd=int(sum(s['rtd'] for s in L)), pl=int(sum(s['pl'] for s in L)))
    peak = []
    for s in S:
        if s['att'] < minq: continue
        peak.append(dict(id=s['id'], n=s['n'], y=s['y'], tm=s['tm'], lo=lo(s['tid']), pos='QB', v=round(s['v']), v0=s['v0'], raw=round(s['tay'], 2),
                         q=dict(q_of([s]), ix=round(s['ix'])), est=None, ph=None))
    svm = {(str(r['id']), r['y']): r for r in sv_hist('cfb') if r['g'] == 'QB'}
    for r in peak:
        m_ = svm.get((str(r['id']), r['y'])) or {}
        r['sv'], r['svar'] = m_.get('sv'), svar(m_, 'cfb') if m_ else None
    chk = era_check(peak, 'v', 'v0')
    pk = pick_sv([dict(r) for r in peak]) if svm else pick([dict(r) for r in peak], 'v')      # every player-season on its own
    for r in pk: r.pop('id', None); r.pop('v0', None)
    C = defaultdict(list)
    for s in S: C[s['id']].append(s)
    car = []
    for i, L in C.items():
        if sum(s['att'] for s in L) < 300: continue
        tms = Counter(s['tm'] for s in L for _ in range(int(s['pl']))); tm = tms.most_common(1)[0][0]
        car.append(dict(n=L[0]['n'], y0=min(s['y'] for s in L), y1=max(s['y'] for s in L), tm=tm, lo=lo(next(s['tid'] for s in L if s['tm'] == tm)),
                        pos='QB', v=round(sum(s['v'] for s in L)), s=len(L), pk=round(max(s['v'] for s in L)), est=None, ph=None, q=q_of(L)))
    car.sort(key=lambda r: -r['v'])
    return dict(peak=pk, career=car[:TOP], peak_check=chk, n=len(S), **{'from': min(s['y'] for s in S)}, to=max(s['y'] for s in S),
                pk=dict(l='Yds+', t='adjusted yards over an average FBS QB that season, in today\'s spread: (TAY/P - season average) x plays; TAY/P = (pass yds + 20 x pass TD - 45 x INT + rush yds + 20 x rush TD) / (attempts + rushes), sacks count as rushes. no opponent adjustment', f='%+.0f', rl='TAY/P', rt='total adjusted yards a play', rf='%.2f'),
                car=dict(l='Yds+', t='career Yds+: each season\'s adjusted yards over an average FBS QB, summed (seasons among the top 150 passers)', f='%+.0f', s=1, pl='Peak', pt='best season Yds+', pf='%+.0f'),
                src='ESPN', pos=True, tm=True, estT='', qb=True, ph=False,
                peak_about=f'FBS regular seasons {min(s["y"] for s in S)}-{max(s["y"] for s in S)}, QBs with {minq}+ attempts; the season average and SD over the same QBs; every player-season ranks on its own.',
                career_about='FBS regular seasons from 2004 (careers that started earlier count from 2004), 300+ attempts.')



SKILL_POS = {'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE'}
SKILL_K = {'RB': 100, 'WR': 200, 'TE': 40}       # the season's average starter: mean of the top K at the position


def cfb_skill_pull(y0=2004, y1=2025, rush=150, rec=450, workers=12):
    """CFB RB / WR / TE seasons for the all-time players lists: each FBS regular season's top `rush` rushers and top `rec`
    receivers by yards (ESPN byathlete, pages of 150), then each one's season line (ESPN core statistics; cached in
    CACHE/cfb_qb, shared with cfb_qb_pull). Position from ESPN (FB counts as RB); a player ESPN lists without one is an RB
    when he ran more than he caught, else a WR. QBs and defenders are left out.
    -> [espn id, name, y, team id, school, pos, games, carries, rush yds, rush TD, rec, rec yds, rec TD, fumbles lost]"""
    import urllib.request, time
    from concurrent.futures import ThreadPoolExecutor
    D = os.path.join(CACHE, 'cfb_qb'); os.makedirs(D, exist_ok=True)
    def get(u, fn):
        p = os.path.join(D, fn)
        if os.path.exists(p): return json.load(open(p))
        for k in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as r: d = json.load(r)
                json.dump(d, open(p, 'w')); return d
            except Exception as e:  # noqa: BLE001
                if getattr(e, 'code', None) == 404: return {}
                time.sleep(2 * (k + 1))
        return {}
    who = {}
    for y in range(y0, y1 + 1):
        for sort, n in (('rushing.rushingYards', rush), ('receiving.receivingYards', rec)):
            for pg in range(1, (n + 149) // 150 + 1):
                d = get('https://site.web.api.espn.com/apis/common/v3/sports/football/college-football/statistics/byathlete?region=us&lang=en'
                        f'&contentorigin=espn&isqualified=false&page={pg}&limit=150&season={y}&seasontype=2&category=offense&sort={sort}:desc',
                        f'lead_{y}_{sort.split(".")[0]}_{pg}.json')
                for a in d.get('athletes', []):
                    x = a['athlete']; t = (x.get('teams') or [{}])[0]
                    who.setdefault((x['id'], y), (x['id'], x['displayName'], y, x.get('teamId') or t.get('id'),
                                                  t.get('shortDisplayName') or x.get('teamShortName'), (x.get('position') or {}).get('abbreviation') or '-'))
    def line(w):
        aid, n, y, tid, sch, pos = w
        d = get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/{y}/types/2/athletes/{aid}/statistics', f'{y}_{aid}.json')
        S = {}
        for c in (d.get('splits') or {}).get('categories', []):
            for st in c.get('stats', []): S[c['name'] + '.' + st['name']] = st.get('value')
        g = lambda k: float(S.get(k) or 0.0)  # noqa: E731
        ra, rc = g('rushing.rushingAttempts'), g('receiving.receptions')
        if pos == '-': pos = 'RB' if ra > rc else 'WR'
        pos = SKILL_POS.get(pos)
        if not pos or ra + rc < 1: return None
        return [aid, n, y, tid, sch, pos, int(g('general.gamesPlayed')), ra, g('rushing.rushingYards'), g('rushing.rushingTouchdowns'),
                rc, g('receiving.receivingYards'), g('receiving.receivingTouchdowns'), g('general.fumblesLost')]
    with ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(line, list(who.values())) if r]


def cfb_skill_lists(rows, qbrows=()):
    """CFB all-time RB / WR / TE lists, FBS regular seasons from 2004. AY = rush yds + rec yds + 20 x (rush TD + rec TD)
    - 45 x fumbles lost. Yds+ = AY - the season's average starter at the position (mean AY of the top SKILL_K by AY: RB 100,
    WR 200, TE 40). No targets in ESPN's college history, so receivers are measured on volume, not per target.
    AY+ = 100 + 25 z against the same starters. peak = best season by Yds+; career = Yds+ summed over the seasons in the pool."""
    qb = {(r[0], r[2]) for r in qbrows if r[6] >= 50}      # a season with 50+ passes is a QB season (ESPN lists many QBs with no position)
    S = [dict(id=r[0], n=r[1], y=r[2], tid=r[3], tm=r[4], pos=r[5], g=r[6], ra=r[7], ry=r[8], rtd=r[9], rc=r[10], cy=r[11], ctd=r[12], fl=r[13]) for r in rows if (r[0], r[2]) not in qb]
    for s in S: s['ay'] = s['ry'] + s['cy'] + 20 * (s['rtd'] + s['ctd']) - 45 * s['fl']
    SVM = {(str(r['id']), r['y']): r for r in sv_hist('cfb') if r['g'] in ('RB', 'WR', 'TE')}
    base = {}
    by = defaultdict(list)
    for s in S: by[(s['y'], s['pos'])].append(s['ay'])
    for k, v in by.items():
        v = sorted(v, reverse=True)[:SKILL_K[k[1]]]; m = sum(v) / len(v)
        base[k] = (m, (sum((x - m) ** 2 for x in v) / len(v)) ** .5 or 1.0)
    top = defaultdict(list)
    for (y, pos), v in by.items(): top[(y, pos)] = [x - base[(y, pos)][0] for x in sorted(v, reverse=True)[:SKILL_K[pos]]]
    F = era_factor(top)      # Nov 23: Yds+ in today's spread of the position's starters (pooled +- 2, last 10 seasons)
    for s in S:
        m, sd = base[(s['y'], s['pos'])]; s['v0'] = s['ay'] - m; s['v'] = s['v0'] * F[(s['y'], s['pos'])]; s['ix'] = 100 + 25 * (s['ay'] - m) / sd
    lo = lambda tid: f'/img/cfb/logos/{tid}.png' if tid and os.path.exists(os.path.join(IMG, 'cfb', 'logos', f'{tid}.png')) else (f'https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/{tid}.png&w=40&h=40' if tid else None)
    def q_of(L):
        ra, ry, rc, cy = (sum(s[k] for s in L) for k in ('ra', 'ry', 'rc', 'cy'))
        return dict(ra=int(ra), ry=int(ry), ypc=round(ry / ra, 1) if ra >= 20 else None, rtd=int(sum(s['rtd'] for s in L)),
                    rc=int(rc), cy=int(cy), ypr=round(cy / rc, 1) if rc >= 10 else None, ctd=int(sum(s['ctd'] for s in L)), scr=int(ry + cy))
    P = []
    for s in S:    # every player-season on its own
        P.append(dict(n=s['n'], y=s['y'], tm=s['tm'], lo=lo(s['tid']), pos=s['pos'], v=round(s['v']), raw=round(s['ay']), est=None, ph=None, q=dict(q_of([s]), ix=round(s['ix'])),
                      sv=(SVM.get((str(s['id']), s['y'])) or {}).get('sv'), svar=svar(SVM[(str(s['id']), s['y'])], 'cfb') if (str(s['id']), s['y']) in SVM else None))
    chk = era_check([dict(id=s['id'], y=s['y'], v=s['v'], v0=s['v0']) for s in S], 'v', 'v0')
    pk = pick_sv([dict(r) for r in P]) if SVM else pick([dict(r) for r in P], 'v')
    C = defaultdict(list)
    for s in S: C[s['id']].append(s)
    car = []
    for i, L in C.items():
        tms = Counter(s['tm'] for s in L for _ in range(int(s['ra'] + s['rc']) or 1)); tm = tms.most_common(1)[0][0]
        pos = Counter(s['pos'] for s in L for _ in range(int(s['ra'] + s['rc']) or 1)).most_common(1)[0][0]
        car.append(dict(n=L[0]['n'], y0=min(s['y'] for s in L), y1=max(s['y'] for s in L), tm=tm, lo=lo(next(s['tid'] for s in L if s['tm'] == tm)),
                        pos=pos, v=round(sum(s['v'] for s in L)), s=len(L), pk=round(max(s['v'] for s in L)), est=None, ph=None, q=q_of(L)))
    car.sort(key=lambda r: -r['v'])
    return dict(peak=pk, career=car[:TOP], peak_check=chk, n=len(S), **{'from': min(s['y'] for s in S)}, to=max(s['y'] for s in S),
                pk=dict(l='Yds+', t='adjusted scrimmage yards over the season\'s average starter at the position, in today\'s spread: AY = rush + rec yds + 20 x TD - 45 x fumbles lost, minus the mean AY of that season\'s top RB 100 / WR 200 / TE 40. volume, not per target (no targets in the college history)', f='%+.0f', rl='AY', rt='adjusted scrimmage yards', rf='%.0f'),
                car=dict(l='Yds+', t='career Yds+: each season\'s adjusted yards over the average starter at his position, summed (seasons among the top 150 rushers / 450 receivers)', f='%+.0f', s=1, pl='Peak', pt='best season Yds+', pf='%+.0f'),
                src='ESPN', pos=True, tm=True, estT='', skill=True, ph=False,
                peak_about='FBS regular seasons 2004-25: RB, WR, TE (ESPN position; FB as RB); every player-season ranks on its own. QBs on their own lists; defense, OL and specialists left out (no usable per-player history).',
                career_about='FBS regular seasons from 2004 (careers that started earlier count from 2004).')


def soccer_teams():
    d = json.load(gzip.open(os.path.join(HERE, 'data', 'soccer_team_ratings.json.gz')))['seasons']
    nm = json.load(gzip.open(os.path.join(HERE, 'data', 'soccer_teams.json.gz')))
    BIG = {'eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1'}
    return [dict(t=(nm.get(c) or [c])[0], y=int(s), r=v[1], o=v[2], d=v[3], wl=None, lg=v[0], c=c) for s, L in d.items() for c, v in L.items() if v[0] in BIG]


def soccer_players():
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'static', 'data', 'soccer-war', '*.json'))):
        d = json.load(open(f))
        if d['season'] >= json.load(open(os.path.join(ROOT, 'data', 'soccer_war.json')))['current']: continue
        for p in d['players']:
            if p.get('gar') is not None: out.append(dict(id=p['p'], n=p['n'], y=d['season'], tm=p['team'], pos=p['pos'], v=p['gar'], raw=p.get('min'), w=p.get('min', 1), ph=p.get('ph'),
                                                         sv=p.get('sv'), svar=p.get('svar')))
    return out


def cs2_teams():
    c = json.load(gzip.open(os.path.join(HERE, 'data', 'cs2_history.json.gz')))['vrs']
    best = {}
    for d, L in c.items():
        y = int(d[:4])
        for rk, t, pts, *_ in L:
            k = (t, y)
            if rk > 50: continue
            if pts and (k not in best or pts > best[k]['r']): best[k] = dict(t=t, y=y, r=float(pts), wl=None, lg=None, d0=d, c=t)
    return [v for v in best.values()]


# ---------------------------------------------------------------- Sports Reference (NBA, NHL, CBB)
def _sr():
    import coach_alltime_pro as cap
    cap.CACHE = os.path.join(CACHE, 'sr')
    return cap


FACES_NBA = json.load(open(os.path.join(HERE, 'data', 'faces_nba.json')))


def _team(cell):
    m = re.search(r'/teams/([A-Z0-9]+)/', cell or '')
    return m.group(1) if m else None


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
                          wl=[int(w or 0), int(l or 0), 0], lg=None, c=_team(r.get('team'))))
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
                          ws48=cap.num(r.get('ws_per_48')), per=cap.num(r.get('per')), ws=cap.num(r.get('ws')),
                          ob=cap.num(r.get('obpm')), db=cap.num(r.get('dbpm'))))
    # before 1974 (no BPM): BPM from WS / 48 and PER, fit on 1974-85 players with 500+ minutes
    fit = [p for p in P if 1974 <= p['y'] <= 1985 and p['bpm'] is not None and p['ws48'] is not None and p['per'] is not None and (p['mp'] or 0) >= 500]
    X = np.array([[1, p['ws48'], p['per']] for p in fit]); b = np.linalg.lstsq(X, np.array([p['bpm'] for p in fit]), rcond=None)[0]
    r = float(np.corrcoef(X @ b, [p['bpm'] for p in fit])[0, 1])
    # VORX (scripts/nba_xpm.py): .030 x (XPM + 1.4) x MP / 48, per 82 games. The published XPM files (2009-10 on: DPM + BPM
    # blend) as they are; before them XPM = BPM (the XPM rule for a player with no DPM row), and before 1973-74 BPM from
    # WS / 48 and PER
    import nba_xpm
    pub = nba_published()
    S = []
    for p in P:
        if not p['mp'] or not p['gs']: continue
        if p['bpm'] is not None:
            x, est = p['bpm'], False
        elif p['ws48'] is not None and p['per'] is not None:
            x, est = b[0] + b[1] * p['ws48'] + b[2] * p['per'], True
        else: continue
        v = nba_xpm.VORX_K * (x - nba_xpm.VORX_REP) * p['mp'] / 48
        ox, dx = p['ob'], p['db']
        if (p['id'], p['y']) in pub:
            q = pub[(p['id'], p['y'])]; v, x = q[0], q[1] if q[1] is not None else x
            if q[2] is not None: ox, dx = q[2], q[3]
        S.append(dict(id=p['id'], n=p['n'], y=p['y'], tm=p['tm'], pos=(p['pos'] or '').split('-')[0], v=v * 82 / p['gs'], raw=round(x, 1), est=est,
                      ox=None if ox is None else round(ox, 1), dx=None if dx is None else round(dx, 1), mp=p['mp'], ph=FACES_NBA.get(p['id']),
                      reg=(p['g'] or 0) >= p['gs'] / 2 and (p['mp'] or 0) >= 12 * p['gs'], pub=(p['id'], p['y']) in pub))
    return T, S, dict(b=[round(float(x), 3) for x in b], r=round(r, 3), n=len(fit))


def nba_published():
    """{(bbref id, season): (VORX, XPM, O-XPM, D-XPM)} from the published XPM files (rXPM: team-adjusted), past seasons"""
    import nba_xpm
    pub = {}
    for f in glob.glob(os.path.join(ROOT, 'static', 'data', 'nba-xpm', '*.json')):
        d = json.load(open(f))
        if d['season'] >= nba_xpm.current_season(): continue
        for q in d['players']:
            if q.get('vorx') is not None: pub[(q['id'], d['season'])] = (q['vorx'], q.get('txpm', q.get('xpm')), q.get('toxpm', q.get('oxpm')), q.get('tdxpm', q.get('dxpm')))
    return pub


def nba_pub(src):
    """snapshot rows -> the published files' values (VORX per 82 games, as nba() writes them)"""
    pub = nba_published()
    gsn = defaultdict(int)
    for r in src['nbaT']: gsn[r['y']] = max(gsn[r['y']], sum(r['wl'][:2]))
    for x in src['nbaS']:
        q = pub.get((x['id'], x['y']))
        if not q or not gsn.get(x['y']): continue
        x['v'] = q[0] * 82 / gsn[x['y']]
        if q[1] is not None: x['raw'] = round(q[1], 1)
        if q[2] is not None: x['ox'], x['dx'] = round(q[2], 1), round(q[3], 1)


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
            rows.append(dict(t=nm, y=y, c=_team(r.get('team_name')), r=srs, gf=gf / gp, ga=ga / gp, sos=cap.num(r.get('sos')) or 0,
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
    return T, nhl_war(list(by.values()), {r['y']: max(x['wl'][0] + x['wl'][1] + x['wl'][2] for x in T if x['y'] == r['y']) for r in T})


NHL_FIT = {}


def nhl_war(PS, gs):
    """the site's NHL WAR (static/data/nhl-war, 2008-09 on) per 82 games; before it WAR from point shares per 82
    (least squares, skaters and goalies apart, fit on the seasons both have, joined by name key + season)"""
    import names as NM
    W = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'static', 'data', 'nhl-war', '*.json'))):
        d = json.load(open(f)); y = d['season']
        if y not in gs or y >= 2027: continue
        for q in d['players']:
            if q.get('war') is None: continue
            W.append(dict(id='nhl' + q['id'], n=q['n'], y=y, tm=q.get('tm'), pos='G' if q.get('grp') == 'G' or q.get('pos') == 'G' else (q.get('grp') or q.get('pos') or '')[:1],
                          v=q['war'] * 82 / gs[y], raw=q['war'], ph=q.get('ph'), reg=(q.get('gp') or 0) >= gs[y] / 2, k=NM.key(q['n'])))
    first = min(w['y'] for w in W)
    wk = {(w['k'], w['y'], w['pos'] == 'G'): w for w in W}
    fit = {}
    for g in (False, True):
        pr = [(p['v'], wk[(NM.key(p['n']), p['y'], g)]['v']) for p in PS if p['y'] >= first and (p['pos'] == 'G') == g and (NM.key(p['n']), p['y'], g) in wk]
        a = np.array(pr); X = np.column_stack([np.ones(len(a)), a[:, 0]]); c = np.linalg.lstsq(X, a[:, 1], rcond=None)[0]
        fit[g] = dict(a=float(c[0]), b=float(c[1]), r=round(float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), 3), n=len(a))
    out = [dict(w) for w in W]
    idmap = {}
    for p in PS:
        if p['y'] >= first: continue
        f_ = fit[p['pos'] == 'G']
        out.append(dict(p, v=f_['a'] + f_['b'] * p['v'], raw=None, est=True))
    # one id per player across the switch: the NHL id's name key + the latest Hockey Reference id with that key
    hr = {}
    for p in PS:
        if p['y'] >= first - 3: hr.setdefault((NM.key(p['n']), p['pos'] == 'G'), set()).add(p['id'])
    for o in out:
        if o['id'].startswith('nhl'):
            ids = hr.get((o.pop('k'), o['pos'] == 'G'))
            if ids and len(ids) == 1: o['id'] = next(iter(ids))
    NHL_FIT.update({('G' if g else 'S'): v for g, v in fit.items()}); NHL_FIT['first'] = first
    return out


def cbb_teams():
    cap = _sr(); T = []
    for y in range(1950, 2027):
        h = cap.get(f'https://www.sports-reference.com/cbb/seasons/men/{y}-ratings.html', False)
        if not h: continue
        for r in next(iter(cap.tables(h).values()), []) if False else cap.tables(h).get('ratings', []):
            nm = cap.text(r.get('school_name')); srs = cap.num(r.get('srs'))
            if not nm or srs is None: continue
            w, l = cap.num(r.get('wins')), cap.num(r.get('losses'))
            T.append(dict(t=nm, y=y, r=srs, o=cap.num(r.get('srs_off')), d=cap.num(r.get('srs_def')), c=nm,
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
        sd[y] = spread(pool, upper=False)
    R = [y for y in reg if ref[0] <= y <= ref[1]]
    m0 = float(np.mean([mu[y] for y in R])); s0 = float(np.mean([sd[y] for y in R]))
    for s in S:
        if s['y'] in mu: s['v'] = m0 + s0 * (s['v0'] - mu[s['y']]) / sd[s['y']]
    return dict(mu=round(m0, 3), sd=round(s0, 3))


def era_scale(S, rate, vol, value, reg, grp=lambda s: '', ref=10, vq=.9):
    """Era adjustment, every sport (Noah Nov 20): a season's rate against that season's league, its volume against
    that season's volume, both put in the units of the last `ref` seasons, then the sport's own value formula.
      rate'  = mu_ref + sd_ref x (rate - season mean) / season SD   (regulars; SD pooled over the season +- WIN)
      vol'   = vol x q_ref / season q                                (q = the vq quantile of the regulars' volume)
      v      = value(rate', vol')
    grp splits the pool (NHL skaters / goalies). vol None: rate only. Keeps v0 (as played).
    -> {group: dict(mu, sd, q)} for the reference seasons and the per-season terms"""
    out = {}
    for g in sorted({grp(x) for x in S}):
        G = [x for x in S if grp(x) == g]
        R = defaultdict(list); V = defaultdict(list)
        for x in G:
            if reg(x) and rate(x) is not None:
                R[x['y']].append(rate(x))
                if vol: V[x['y']].append(vol(x))
        mu = {y: float(np.mean(L)) for y, L in R.items() if len(L) >= 5}
        sd = {}
        for y in mu:
            pool = [v - mu[t] for t in range(y - WIN, y + WIN + 1) if t in mu for v in R[t]]
            sd[y] = spread(pool, upper=False) or 1.0
        q = {y: float(np.quantile(V[y], vq)) for y in mu} if vol else {}
        ys = sorted(mu)[-ref:]
        m0 = float(np.mean([mu[y] for y in ys])); s0 = float(np.mean([sd[y] for y in ys]))
        q0 = float(np.mean([q[y] for y in ys])) if vol else None
        for x in G:
            x.setdefault('v0', x['v'])
            r = rate(x)
            if x['y'] not in mu or r is None: x['v'] = None; continue
            r2 = m0 + s0 * (r - mu[x['y']]) / sd[x['y']]
            x['v'] = value(r2, vol(x) * q0 / q[x['y']]) if vol else r2
        out[g or 'all'] = dict(mu=round(m0, 3), sd=round(s0, 3), q=None if q0 is None else round(q0, 1), ref=[ys[0], ys[-1]],
                               by={y: [round(mu[y], 3), round(sd[y], 3), round(q[y], 1) if vol else None] for y in sorted(mu)})
    return out


def era_drift(rows, n=25):
    """top-n seasons as played (v0) vs era-adjusted (v): who left, who came in, mean season, decade counts"""
    a = sorted([r for r in rows if r.get('v0') is not None], key=lambda r: -r['v0'])[:n]
    b = sorted([r for r in rows if r.get('v') is not None], key=lambda r: -r['v'])[:n]
    k = lambda r: (r['id'], r['y'])
    ka, kb = {k(r) for r in a}, {k(r) for r in b}
    dec = lambda L: dict(sorted(Counter(r['y'] // 10 * 10 for r in L).items()))
    return dict(out=[(fixenc(r['n']), r['y']) for r in a if k(r) not in kb], inn=[(fixenc(r['n']), r['y']) for r in b if k(r) not in ka],
                y_raw=round(float(np.mean([r['y'] for r in a])), 1), y_adj=round(float(np.mean([r['y'] for r in b])), 1),
                dec_raw=dec(a), dec_adj=dec(b), kept=len(ka & kb))


def cs2_players():
    """CS2 player-seasons (calendar years, bo3.gg per-map lines 2024-, scripts/cs2_players.py): that year's RWA (round win %
    added per round, opponents credited at their year-end ratings, the board's S/A-tier lift) over the year's replacement
    level (median of players with 1,000+ rounds), and rounds played. Built from the repo's per-map files, not the snapshot"""
    import datetime as dt, cs2_players as CP, cs2_bo3
    fitj = json.loads(CP.FIT.read_text()); p = fitj['params']; a = p['a']
    M = CP.Maps()
    c = CP.contributions(M, np.array([fitj['beta'][k] for k in CP.STATS]), np.array(fitj['mline']), p.get('pm', 0.0))
    bo3 = cs2_bo3.Bo3(); tname = {}
    for r in sorted(bo3.mt.values(), key=lambda r: r[1]): tname[r[2]], tname[r[3]] = r[4], r[5]
    pdir = CP.load_pdir(); today = dt.date.today().toordinal() + 1; out = []
    y0, y1 = dt.date.fromordinal(int(M.d.min())).year, dt.date.fromordinal(int(M.d.max())).year
    for y in range(y0, y1 + 1):
        T0, T1 = dt.date(y, 1, 1).toordinal(), min(dt.date(y + 1, 1, 1).toordinal(), today)
        th, _ = CP.ratings(M, c, T1, p)
        lift = p.get('ssg', 0.0) * CP.sa_share(M, T1) if p.get('ssg') else 0.0
        rt, rd = CP.window_stats(M, c, th, T0, T1, p)
        rt = rt + lift
        act = rd >= 1000
        if act.sum() < 20: continue
        repl = float(np.median(rt[act]))
        m = (M.d >= T0) & (M.d < T1); tm = defaultdict(Counter)
        for i in np.where(m)[0]: tm[M.p[i]][int(M.team[i])] += M.R[i]
        for i in np.where(rd >= 200)[0]:
            pid = int(M.pids[i]); d = pdir.get(str(pid)) or [None] * 6
            t = tname.get(tm[i].most_common(1)[0][0], '') if tm[i] else ''
            out.append(dict(id=pid, n=M.nick.get(pid) or d[1] or str(pid), y=y, tm=t, pos=None, rate=float(a / 2 * (rt[i] - repl)), w=float(rd[i]),
                            v=float(a / 2 * (rt[i] - repl) * rd[i] / 100), raw=round(float(a / 2 * (rt[i] - repl)), 2), reg=bool(act[i]), ph=d[5],
                            ytd=T1 < dt.date(y + 1, 1, 1).toordinal()))
    return out


def hockey_prospect_seasons():
    """Drafted skaters' pre-NHL seasons (NHL draft classes 2008-, scripts/data/hockey_rows.json.gz): draft year -1, draft
    year and each later season outside the NHL, at 20+ games. NHLe = points per 82 NHL games at the league's fitted
    factor (scripts/hockey_nhle.py), on a log scale (log(NHLe + 5): junior scoring is right-skewed). Age = on Dec 31 of the season"""
    import datetime as dt
    R = json.load(gzip.open(os.path.join(HERE, 'data', 'hockey_rows.json.gz'))); out = []
    for r in R:
        if r.get('G') or not r.get('birth'): continue
        b = dt.date.fromisoformat(r['birth']); pos = 'D' if r.get('D') else 'F'
        L = [(r['year'] - 1, r.get('dm1')), (r['year'], r.get('d0'))] + [(r['year'] + int(k), q) for k, q in (r.get('post') or {}).items()]
        for y, q in L:
            if not q or q.get('lg') == 'NHL' or not q.get('gp') or q['gp'] < 20 or q.get('nhle') is None: continue
            age = int((dt.date(y - 1, 12, 31) - b).days / 365.25)
            if age > 21: continue
            out.append(dict(id=r['id'], n=r['name'], y=y, tm=q['lg'], pos=pos, age=max(age, 16), rate=math.log(max(q['nhle'], 0) + 5), w=q['gp'], v=q['nhle'],
                            raw=round(q['nhle'], 1), reg=True, pick=r.get('pick'), dy=r['year'], eb=2008 + (r['year'] - 2008) // 5 * 5))
    # eb (Nov 23): the era check bins prospects by draft class (2008-12, 13-17, ...): the 2007-09 seasons hold only the first
    # classes' youngest seasons, so a season-decade bin reads cohort coverage as era
    return out


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


# ---------------------------------------------------------------- logos
IMG = os.path.join(ROOT, 'static', 'img')
FR = {'nba': {'NJN': 'BRK', 'NYN': 'BRK', 'NOH': 'NOP', 'NOK': 'NOP', 'SEA': 'OKC', 'VAN': 'MEM', 'CHH': 'CHO', 'CHA': 'CHO', 'WSB': 'WAS',
              'CAP': 'WAS', 'BAL': 'WAS', 'CHZ': 'WAS', 'CHP': 'WAS', 'KCK': 'SAC', 'KCO': 'SAC', 'CIN': 'SAC', 'ROC': 'SAC', 'SDC': 'LAC',
              'BUF': 'LAC', 'NOJ': 'UTA', 'SDR': 'HOU', 'SFW': 'GSW', 'PHW': 'GSW', 'SYR': 'PHI', 'STL': 'ATL', 'MLH': 'ATL', 'TRI': 'ATL',
              'MNL': 'LAL', 'FTW': 'DET', 'NJA': 'BRK'},
      'nhl': {'PHX': 'UTA', 'ARI': 'UTA', 'QUE': 'COL', 'HAR': 'CAR', 'MNS': 'DAL', 'ATF': 'CGY', 'KCS': 'NJD', 'CLR': 'NJD', 'ATL': 'WPG',
              'MDA': 'ANA', 'CBH': 'CHI', 'DTC': 'DET', 'DTF': 'DET', 'TRS': 'TOR', 'TRA': 'TOR', 'WIN': 'UTA', 'TBL': 'TBL', 'VEG': 'VGK',
              'LA': 'LAK', 'NJ': 'NJD', 'SJ': 'SJS', 'TB': 'TBL', 'CLB': 'CBJ', 'MON': 'MTL', 'WAS': 'WSH', 'AFM': 'WPG'},
      'nfl': {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA', 'WSH': 'WAS', 'SFO': 'SF', 'TAM': 'TB', 'SDG': 'LAC', 'GNB': 'GB', 'KAN': 'KC',
              'NWE': 'NE', 'NOR': 'NO', 'RAI': 'LV', 'RAM': 'LA', 'PHO': 'ARI', 'CRD': 'ARI', 'CLT': 'IND', 'HTX': 'HOU', 'OTI': 'TEN',
              'RAV': 'BAL', 'LVR': 'LV', 'LAC': 'LAC', 'BOS': 'NE', 'STL': 'LA'}}
ESPN = {}


def espn_map(sp):
    """school name key -> ESPN logo url (CFB: /img/cfb/logos/<id>.png when the site has it)"""
    if sp in ESPN: return ESPN[sp]
    import names as NM, subprocess
    f = os.path.join(CACHE, f'espn_{sp}.json')
    if not os.path.exists(f):
        path = 'football/college-football' if sp == 'cfb' else 'basketball/mens-college-basketball'
        subprocess.run(['curl', '-s', '-m', '60', '-o', f, f'https://site.api.espn.com/apis/site/v2/sports/{path}/teams?limit=2000'])
    out = {}
    for t in json.load(open(f))['sports'][0]['leagues'][0]['teams']:
        t = t['team']; i = t['id']
        u = f'/img/cfb/logos/{i}.png' if sp == 'cfb' and os.path.exists(os.path.join(IMG, 'cfb', 'logos', f'{i}.png')) else \
            f'https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/{i}.png&w=40&h=40'
        for n in (t.get('location'), t.get('shortDisplayName'), t.get('displayName'), t.get('nickname')):
            if n: out.setdefault(NM.team_key(n), u)
    ESPN[sp] = out
    return out


def logo(sp, c):
    if not c: return None
    if sp in ('nba', 'nhl', 'nfl'):
        k = FR[sp].get(c, c).lower()
        for x in (k, {'gsw': 'gs', 'pho': 'phx', 'sas': 'sa', 'nop': 'no'}.get(k, k)):
            if os.path.exists(os.path.join(IMG, sp, f'{x}.png')): return f'/img/{sp}/{x}.png'
        return None
    if sp == 'soccer':
        return f'/img/soccer/{c}.png' if os.path.exists(os.path.join(IMG, 'soccer', f'{c}.png')) else None
    if sp == 'cs2':
        k = re.sub(r'[^a-z0-9]', '', c.lower())
        return f'/img/cs2/{k}.png' if os.path.exists(os.path.join(IMG, 'cs2', f'{k}.png')) else None
    if sp in ('cfb', 'cbb'):
        import names as NM
        return espn_map(sp).get(NM.team_key(c))
    return None


def face(sp, ph):
    if not ph: return None
    if sp == 'nba': return f'https://a.espncdn.com/combiner/i?img=/i/headshots/nba/players/full/{ph}.png&w=96&h=70&scale=crop'
    if sp == 'nhl':
        ph = str(ph)
        if ph.startswith('e'): ph = ph[1:]
        return f'https://a.espncdn.com/combiner/i?img=/i/headshots/nhl/players/full/{ph}.png&w=96&h=70&scale=crop' if ph.isdigit() else None
    if sp == 'soccer': return f'https://img.a.transfermarkt.technology/portrait/medium/{ph}'
    if sp == 'cs2': return ph if str(ph).startswith('https://') else None
    return None


def teams_out(sp, rows, keys=('r', 'o', 'd')):
    for r in rows: r['t'] = fixenc(r['t'])
    T = team_lists(rows, keys)
    for k in ('teams', 'offense', 'defense'):
        for r in T.get(k, []): r['lo'] = logo(sp, r.pop('c', None))
    T['units'] = dict(zip(['teams', 'offense', 'defense'], UNITS[sp])); T['src'] = SRC[sp]
    T['wl'] = any(r.get('wl') for r in rows); T['lg'] = any(r.get('lg') for r in rows)
    return T


def players_out(seasons, pk, car, src, pos=True, tm=True, est=None, career=None, abouts=('', ''), every=False):
    P = player_lists(seasons, 'v', every=every)
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
        if '--qb' in sys.argv:   # add the all-time QB lines to the snapshot (no other pull needed)
            src['nflqb'] = nfl_qb_pull(max(s['y'] for s in src['nflpk']))
            src['cfbqb'] = cfb_qb_pull()
            src['cfbsk'] = cfb_skill_pull()
            json.dump(src, gzip.open(SNAP, 'wt'), separators=(',', ':'))
        src['soccerS'] = soccer_players()      # local season files: SV / SVAR (scripts/soccer_sv.py) without a re-pull
        nba_pub(src)                   # the published XPM files (rXPM, VORX on rXPM) over the snapshot's 2010-26 rows
    else:
        nT, nS, nfit = nba(); hT, hS = nhl()
        nflpk, nflcar = nfl_players()
        src = dict(nhlfit=NHL_FIT, nflwav=nfl_wav(), cfb=cfb_rows(), nfl=nfl_rows(), nflch=nfl_champs(), cbb=cbb_teams(), nbaT=nT, nbaS=nS, nbafit=nfit, nhlT=hT, nhlS=hS,
                   soccerT=soccer_teams(), cs2T=cs2_teams(), cbbS=cbb_players(), nflpk=nflpk, nflcar=nflcar, soccerS=soccer_players(), nflqb=nfl_qb_pull(max(s['y'] for s in nflpk)), cfbqb=cfb_qb_pull(), cfbsk=cfb_skill_pull(),
                   atp=tennis_players('atp'), wta=tennis_players('wta'))
        rnd = lambda x: round(x, 3) if isinstance(x, float) else [rnd(v) for v in x] if isinstance(x, list) else {k: rnd(v) for k, v in x.items()} if isinstance(x, dict) else x
        json.dump(rnd(src), gzip.open(SNAP, 'wt'), separators=(',', ':'))
    ch = {int(k): v for k, v in src['nflch'].items()}
    for r in src['nfl']: r['nt'] = 1 if ch.get(r['y']) == r['t'] else 0
    for r in src['nbaT'] + src['nhlT']: r['nt'] = 0
    res['cfb'] = {'teams': teams_out('cfb', src['cfb'])}
    if src.get('cfbqb'): res['cfb']['qbs'] = cfb_qb_lists(src['cfbqb'])
    if src.get('cfbsk'): res['cfb']['players'] = cfb_skill_lists(src['cfbsk'], src.get('cfbqb') or ())
    for g_, t_ in (('qbs', 'CFB 2014 on (cfbfastR play-by-play), FBS games'), ('players', 'CFB 2014 on: RBs on runs; WR, TE and RB targets 2025 on (target ids)')):
        P_ = res['cfb'].get(g_)
        if P_ and any(r.get('sv') is not None for r in P_['peak']):
            P_['sv'], P_['svT'] = True, SV_T + '; ' + t_
            P_['svarT'] = 'SVAR = SV points over replacement that season, in wins: points x .0189 (FBS: win % rises .0189 a point of margin a game, 12 games)'
    res['nfl'] = {'teams': teams_out('nfl', src['nfl'])}
    res['cbb'] = {'teams': teams_out('cbb', src['cbb'])}
    res['nba'] = {'teams': teams_out('nba', src['nbaT'])}
    res['nhl'] = {'teams': teams_out('nhl', src['nhlT'])}
    res['soccer'] = {'teams': teams_out('soccer', src['soccerT'])}
    # CS2: each snapshot's top 50 are the pool
    res['cs2'] = {'teams': teams_out('cs2', src['cs2T'], keys=('r',))}
    nf = src['nbafit']
    # era adjustment (era_scale): NBA XPM vs the season's regulars + minutes per 82 vs the season's 90th pct load;
    # NHL WAR per 82 vs the season, skaters and goalies apart (no minutes before 2008-09); CBB BPM + minutes; soccer GAR/90 + minutes
    import nba_xpm
    gsn = defaultdict(int)
    for r in src['nbaT']: gsn[r['y']] = max(gsn[r['y']], sum(r['wl'][:2]))
    for x in src['nbaS']: x['m82'] = x['mp'] * 82 / gsn[x['y']] if gsn.get(x['y']) else None
    ERA = {}
    ERA['nba'] = era_scale([x for x in src['nbaS'] if x['m82']], lambda x: x['raw'], lambda x: x['m82'],
                           lambda r, m: nba_xpm.VORX_K * (r - nba_xpm.VORX_REP) * m / 48, reg=lambda x: x.get('reg'))
    ERA['nhl'] = era_scale(src['nhlS'], lambda x: x['v'], None, None, reg=lambda x: x.get('reg'), grp=lambda x: 'G' if x.get('pos') == 'G' else 'S')
    wpp = json.load(gzip.open(os.path.join(HERE, 'data', 'cbb_tabs_2026.json.gz')))['wfit']['wpp']
    ERA['cbb'] = era_scale(src['cbbS'], lambda x: x['raw'], lambda x: x['w'], lambda r, m: (r + 2.0) * m / 40 * .68 * wpp, reg=lambda x: x['w'] >= 400)
    ERA['soccer'] = era_scale(src['soccerS'], lambda x: x['v'] / x['raw'] * 90 if x.get('raw') else None, lambda x: x['raw'] or 0,
                              lambda r, m: r * m / 90, reg=lambda x: (x.get('raw') or 0) >= 900)
    cs = cs2_players()
    ERA['cs2'] = era_scale(cs, lambda x: x['rate'], lambda x: x['w'], lambda r, m: r * m / 100, reg=lambda x: x['reg'])
    hk = hockey_prospect_seasons()
    ERA['hkp'] = era_scale(hk, lambda x: x['rate'], None, None, reg=lambda x: x['reg'], grp=lambda x: f"{x['pos']}{x['age']}")
    for x in hk:   # NHLe+ = 100 + 25 SD against prospects of his age and position that season; adj NHLe kept for the column
        if x['v'] is None: continue
        e = ERA['hkp'][f"{x['pos']}{x['age']}"]; mu, sd = e['by'][x['y']][:2]
        x['adj'] = round(math.exp(x['v']) - 5, 1); x['v'] = 100 + 25 * (x['rate'] - mu) / sd
    nba_nom = [x for x in src['nbaS'] if not x['m82']]
    for x in nba_nom: x['v'] = None
    hf = src['nhlfit']
    res['nba']['players'] = players_out(src['nbaS'], dict(l='VORX', t='wins over replacement on XPM: .030 x (XPM + 1.4) x MP / 48, per 82 games, in today\'s units', f='%.1f', rl='XPM', rt='XPM (DPM + BPM blend from 2009-10; BPM alone before)', rf='%.1f'),
                                        dict(l='VORX', t='career VORX, each season per 82 games in today\'s units', f='%.0f', s=1, pl='Peak', pt='best season VORX per 82'),
                                        'Basketball Reference + databallr', est=f'before 1973-74 (no BPM): XPM from WS/48 and PER, fit on 1974-85 (r {nf["r"]:.2f})',
                                        abouts=('Regular season. XPM = DPM + BPM blend from 2009-10, BPM alone 1973-74 to 2008-09.', 'Regular season, 1951-52 on (minutes).'))
    res['nba']['players']['fit_r'] = nf['r']
    res['nhl']['players'] = players_out(src['nhlS'], dict(l='WAR', t='NHL WAR (2008-09 on), per 82 games, in today\'s units', f='%.1f', rl='Raw', rt='NHL WAR as played', rf='%.1f'),
                                        dict(l='WAR', t='career WAR, each season per 82 games in today\'s units', f='%.0f', s=1, pl='Peak', pt='best season WAR per 82'),
                                        'MoneyPuck + Hockey Reference', est=f"before {hf['first'] - 1}-{str(hf['first'])[2:]}: WAR from point shares (skaters r {hf['S']['r']:.2f}, goalies r {hf['G']['r']:.2f} on the seasons both have)",
                                        abouts=(f"NHL WAR from {hf['first'] - 1}-{str(hf['first'])[2:]}; earlier seasons est from point shares.", ''))
    res['nhl']['players']['fit'] = hf
    res['cbb']['players'] = players_out(src['cbbS'], dict(l='WAR', t='wins over a replacement player: (BPM + 2) x minutes / 40 x .68 x wins a point (CBB WAR)', f='%.1f', rl='BPM', rt='Barttorvik box plus-minus', rf='%.1f'),
                                        dict(l='WAR', t='career WAR, D-I seasons 2007-08 on', f='%.1f', s=1, pl='Peak', pt='best season WAR'),
                                        'Barttorvik', pos=False)
    car, nfit = nfl_career(src['nflpk'], src['nflwav'])
    res['nfl']['players'] = players_out(src['nflpk'], dict(l='WAR', t='NFL WAR (AV WAR, no special teams), 2012 on (snap counts)', f='%.2f', rl='AV', rt='approximate value, rebuilt from nflverse', rf='%.1f'),
                                        dict(l='WAR', t='career NFL WAR: seasons 2012 on, earlier seasons est from weighted career AV', f='%.1f', s=1, pl='', pt=''),
                                        'nflverse + Pro Football Reference', career=car, est=f"seasons before 2012: weighted career AV x pre-2012 share of his seasons x {nfit['b']:.3f} (fit on 2003-11 draftees' 2012-on WAR, r {nfit['r']:.2f})",
                                        abouts=('Seasons 2012 on.', 'NFL WAR 2012 on; earlier careers est from weighted career AV (drafted players 1980 on).'))
    res['nfl']['players']['fit'] = nfit
    # QBs and everyone else, each its own all-time list (QB lists add the QB columns: nfl_qb_attach). Era: WAR is measured
    # against each season's own replacement lines and a team's WAR sums to its wins - 3, so the league total is fixed by the
    # schedule, not by pass volume; seasons are put on 17 games (2012-20 played 16: x 17 / 16). Peak lists rank every
    # player-season on its own (a player can appear more than once).
    for s_ in src['nflpk']: s_['v17'] = s_['v'] * 17 / (16 if s_['y'] <= 2020 else 17)
    if src.get('nflqb'):
        pk17 = nfl_era([dict(s_, v=s_['v17']) for s_ in src['nflpk']])
        allc, nfit = nfl_career(pk17, src['nflwav'], top=None)
        base = res['nfl']['players']
        pkm = dict(base['pk'], t="NFL WAR (AV WAR, no special teams), 2012 on (snap counts), on 17 games (2012-20 x 17 / 16), in today's units (vs the season's starters at the position)")
        SVN = sv_hist('nfl')
        for g, keep in (('qbs', lambda p: p == 'QB'), ('players', lambda p: p != 'QB')):
            S_ = [s_ for s_ in pk17 if keep(s_.get('pos'))]
            P = players_out(S_, pkm, base['car'], base['src'],
                            career=[r for r in allc if keep(r.get('pos'))][:TOP], est=base['estT'],
                            abouts=('WAR seasons 2012 on, on 17 games; every player-season ranks on its own. SV seasons 1999 on (defenders 2013 on): the list holds the top by WAR and the top by SV.', base['career_about']))
            # SV (scripts/sv_history.py) by pfr id + season; seasons with SV and no WAR row (1999-2012, before snap counts)
            # join the list with WAR blank, so a sort by SV covers every season the play-by-play reaches
            svr = [r for r in SVN if (r['g'] == 'QB') == (g == 'qbs')]
            svm = {(r['pfr'], r['y']): r for r in svr if r.get('pfr')}
            for x in S_:
                m_ = svm.pop((x.get('id'), x['y']), None)
                x['sv'], x['svar'] = (m_['sv'], svar(m_, 'nfl')) if m_ else (None, None)
            extra = [dict(n=r['n'], y=r['y'], tm=r.get('t'), pos=r['g'], v=None, raw=None, sv=r['sv'], svar=svar(r, 'nfl'))
                     for r in svm.values() if r.get('n')]
            P['peak'] = [dict(n=fixenc(x['n']), y=x['y'], tm=x.get('tm'), pos=x.get('pos'), v=None if x['v'] is None else round(x['v'], 2), raw=x.get('raw'),
                              sv=x.get('sv'), svar=x.get('svar'), est=None, ph=None, ox=None, dx=None,
                              u=None if x.get('v0') is None else round(x['v0'], 2))
                         for x in (pick_sv([dict(x) for x in S_ + extra]) if SVN else pick([dict(x) for x in S_], 'v'))]
            if SVN:
                P['sv'], P['svT'] = True, SV_T + '; NFL 1999 on (defenders 2013 on, snap counts); WAR 2012 on'
                P['svarT'] = 'SVAR = SV points over replacement that season, in wins: points / 36 a win (the game model), on 17 games (1999-2020 x 17 / 16)'
                P['from'] = min(P['from'], min(r['y'] for r in svr))
            P['fit'] = nfit
            res['nfl'][g] = P
        nfl_qb_attach(res['nfl']['qbs'], src['nflqb'])
        res['nfl']['qbs']['qb'] = True
    res['soccer']['players'] = players_out(src['soccerS'], dict(l='GAR', t='goals above replacement (soccer GAR), big-five leagues', f='%.1f', rl='Min', rt='minutes', rf='%.0f'),
                                           dict(l='GAR', t='career GAR, big-five seasons 2014-15 on', f='%.0f', s=1, pl='Peak', pt='best season GAR'), 'ESPN + FotMob',
                                           abouts=('Big-five league seasons 2014-15 on.', ''))
    for sp_, k_ in (('nba', 'nbaS'), ('nhl', 'nhlS'), ('cbb', 'cbbS'), ('soccer', 'soccerS')):
        old_ = res[sp_]['players']
        P_ = players_out(src[k_], old_['pk'], old_['car'], old_['src'], pos=old_['pos'], est=old_['estT'], abouts=(old_['peak_about'], old_['career_about']), every=True)
        for kk in old_:
            if kk not in P_: P_[kk] = old_[kk]
        P_['era'] = ERA[sp_]; P_['drift'] = era_drift(src[k_]); P_['u'] = True
        res[sp_]['players'] = P_
    soccer_sv_attach(res['soccer']['players'], src['soccerS'])
    res['cs2']['players'] = players_out(cs, dict(l='RAR', t="rounds won over a replacement player: RWA over replacement x rounds / 100, in today's units (RWA vs that year's players, rounds vs that year's load)", f='%.1f', rl='RWA', rt="round win % added per round over that year's replacement level", rf='%+.2f'),
                                        dict(l='RAR', t='career RAR, each year in today\'s units', f='%.0f', s=1, pl='Peak', pt='best year RAR'),
                                        'bo3.gg', pos=False, abouts=('Calendar years, 2024 on; current year to date.', ''), every=True)
    res['cs2']['players'].update(era=ERA['cs2'], drift=era_drift(cs), u=True)
    res['hkp'] = {'players': players_out([x for x in hk if x['v'] is not None], dict(l='NHLe+', t="NHLe against drafted prospects of his age and position that season: 100 = average, +25 = one SD", f='%.0f', rl='NHLe', rt='points per 82 NHL games at the league factor, as played', rf='%.1f'),
                                         dict(l='NHLe+', t='sum of seasons over 100, in SDs', f='%.0f', s=1, pl='Peak', pt='best season NHLe+'),
                                         'NHL + HockeyTech + Elite leagues', abouts=('Drafted skaters (2008 on), seasons outside the NHL at 20+ games, ages 16-21 (on Dec 31).', ''), every=True)}
    for r in res['hkp']['players']['peak']:
        q = next((x for x in hk if x['n'] == r['n'] and x['y'] == r['y'] and x['tm'] == r['tm']), None)
        if q: r['u'] = q['adj']; r['age'] = q['age']
    res['hkp']['players'].update(era=ERA['hkp'], u=True, ul='Adj', ut="NHLe in today's units for his age and position (season mean and SD set to the last 10 seasons')")
    res['hkp']['players'].update(tmL='Lg', age=True, career=[])
    def _e(sp, k='all'):
        e = ERA[sp][k]; return f"{e['ref'][0]}-{e['ref'][1]}"
    ET = {'nba': f"Era: XPM against that season's regulars (mean, SD), minutes per 82 against that season's 90th pct load, both in {_e('nba')} units; BPM is per 100 possessions, so pace is already out.",
          'nhl': f"Era: WAR per 82 against that season's regulars (mean, SD), skaters and goalies apart, in {_e('nhl', 'S')} units.",
          'cbb': f"Era: BPM against that season's regulars (400+ min), minutes against that season's 90th pct, in {_e('cbb')} units.",
          'soccer': f"Era: GAR per 90 against that season's regulars (900+ min), minutes against that season's 90th pct, in {_e('soccer')} units.",
          'cs2': f"Era: RWA against that year's regulars (1,000+ rounds), rounds against that year's 90th pct, in {_e('cs2')} units.",
          'hkp': 'Era: log NHLe against drafted skaters of the same age and position that season (SD pooled +- 2 seasons).'}
    for sp_, t_ in ET.items(): res[sp_]['players']['eraT'] = t_
    for t in ('atp', 'wta'):
        S = src[t]
        pk = players_out([dict(s, v=100 + 25 * s['v']) for s in S if s['v'] is not None],
                         dict(l='Elo+', t="peak Elo that year against the year's #20 (100) in SDs of the year's top 100 (x25)", f='%.0f', rl='Elo', rt='peak Elo that year', rf='%.0f'),
                         {}, 'Sackmann archive', pos=False, tm=False, every=True)
        drift = era_drift([dict(s, v=s['v'], v0=s['raw']) for s in S if s['v'] is not None])
        cr = players_out([dict(s, v=s['cv']) for s in S], {}, dict(l='Career', t="sum of year-end Elo over the year's #20, in SDs of the year's top 100", f='%.1f', s=1, pl='', pt=''),
                         'Sackmann archive', pos=False, tm=False)
        pk['career'] = cr['career']; pk['car'] = cr['car']
        pk['peak_about'] = 'Tour-level singles; peak counts after 40 matches.'; pk['career_about'] = 'Years with 20+ tour-level matches.'
        pk['drift'] = drift; pk['eraT'] = "Era: Elo against that year's #20, in SDs of that year's top 100."
        res[t] = {'players': pk}
    snm = {}
    import names as NM
    for r in src['soccerT']: snm[NM.team_key(fixenc(r['t']))] = r.get('c')
    for sp, g in (('nba', 'players'), ('nhl', 'players'), ('cbb', 'players'), ('nfl', 'players'), ('nfl', 'qbs'), ('soccer', 'players'), ('cs2', 'players')):
        P = res[sp].get(g)
        if not P: continue
        for L in (P['peak'], P['career']):
            for r in L:
                tm = (r.get('tm') or '').split('/')[-1]
                if sp == 'soccer':
                    k = NM.team_key({'RasenBallsport Leipzig': 'RB Leipzig', 'Inter': 'Internazionale'}.get(tm, tm))
                    c = snm.get(k) or next((v for kk, v in snm.items() if kk.startswith(k) or k.startswith(kk)), None)
                    r['lo'] = logo(sp, c)
                else: r['lo'] = logo(sp, tm)
                r['ph'] = face(sp, r.get('ph'))
        P['ph'] = any(r.get('ph') for r in P['peak'] + P['career'])
    res['nba']['players']['od'] = True
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
