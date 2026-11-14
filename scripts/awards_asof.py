# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""As-of backtest of the in-season award layer (scripts/awards.py) and its temperature by season share.

    python3 scripts/awards_asof.py nhl nba nfl     # rebuild the as-of races (cached), score, write data/awards_temp.json
    python3 scripts/awards_asof.py --score         # score the cached races again

For each past season and shown award the candidates' to-date lines and team records are rebuilt at 25 / 50 / 75% of
the season and run through the live layer's own race functions (awards.nhl_races / nba_races / nfl_races: same draws,
same simulation count, same prune), with voter coefficients refit leaving that season out. Scored: log loss of the
eventual winner, every probability floored at FLOOR.

To-date inputs
- NFL: nflverse weekly player stats summed to the checkpoint week; rookies from nflverse players (rookie_season).
- NHL skaters: stats API skater summary with gameDate<=; goalies: the game archive's goalie lines (GSAx = xGA - GA).
- NBA: archived box lines (scripts/nba_pbox_hist.json.gz; 2012-13..2017-18 pulled into the cache) summed to date.
- WAR (NHL) and XPM (NBA) are season files and cannot be rebuilt by date. Variant 'box' (the test): the to-date
  value predicted from to-date box stats by a ridge fit on the other seasons' full-season lines, the predictive rate
  = that estimate shrunk to last season's published value by minutes. Variant 'end' (a bound: it leaks the rest of
  the season, so it can only understate the temperature): the season-end published rate x to-date minutes.
- Team finish: record to date, games left x win rate shrunk to .500 (PRIOR_G games).

Temperature: p_i' ~ p_i ^ (1 / T), T = 1 + a x (1 - season share); a from GRID, leave one season out. A sport
passes when the per-season mean log-loss change has t <= -2 (Holm over the sports run at .05) and the full-sample a
has the same sign; data/awards_temp.json then carries its a (the smaller of the box and end fits where both exist)
and scripts/awards.py applies it. numpy."""
import collections, csv, gzip, json, math, os, random, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import awards as AW
import awards_engine as E
import names as NM
from awards_research import t_sf, holm
from awards_nflverse import nfl_weekly, nfl_games, nfl_totals, nfl_records, rookies

ROOT = AW.ROOT
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'awards', 'asof')
OUT = os.path.join(ROOT, 'data', 'awards_temp.json')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
SHARES = (.25, .5, .75)
GRID = [x / 4 for x in range(-2, 21)]
FLOOR = 1e-3
PRIOR_G = {'nba': 12, 'nhl': 20, 'nfl': 6}
SEED = 20261114


def get(url, tries=4, raw=False):
    for a in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=120).read()
            return r if raw else json.loads(r)
        except Exception as e:
            print(url[:90], e, flush=True); time.sleep(5 * (a + 1))
    return None


def ridge(X, y, w=None, l2=1.0):
    import numpy as np
    X, y = np.array(X, float), np.array(y, float)
    w = np.ones(len(y)) if w is None else np.array(w, float)
    A = (X * w[:, None]).T @ X + l2 * np.eye(X.shape[1])
    return np.linalg.solve(A, (X * w[:, None]).T @ y)


def loso_specs(races, cols, depth):
    """{season: voter spec fit on the other seasons}"""
    out = {}
    rr = [(s, [[r[c] for c in cols] for r in pool], o) for s, pool, o in races]
    for s, _, _ in races:
        b, mu, sd = E.fit([(X, o) for t, X, o in rr if t != s and o], depth=depth)
        out[s] = {'cols': cols, 'b': b, 'mu': mu, 'sd': sd, 'test': {'pass': True}}
    return out


def shrunk_left(w, g, G, sport):
    k = PRIOR_G[sport]
    return w + max(G - g, 0) * (w + .5 * k) / (g + k)


def row(sp, s, aw, ci, var, pool, p, win_id):
    ids = [c['id'] for c in pool]
    return {'sp': sp, 's': s, 'aw': aw, 'cp': ci, 'var': var, 'p': [round(v, 6) for v in p],
            'w': ids.index(win_id) if win_id in ids else None,
            'top': [(pool[i]['n'], round(p[i], 3)) for i in sorted(range(len(p)), key=lambda i: -p[i])[:3]]}


# ---------------------------------------------------------------- NHL

def nhl_checkpoints():
    G = [g for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nhl_games_hist.json.gz')))
         if g['po'] == 0 and g.get('final') and g['S'] <= 2026]
    days = collections.defaultdict(list)
    for g in G: days[g['S']].append(g['day'])
    cp = {S: [sorted(d)[int(len(d) * f) - 1] for f in SHARES] + [max(d)] for S, d in days.items()}
    return G, cp


def nhl_skaters(S, i, day):
    fn = os.path.join(CACHE, f'sk_{S}_{i}.json')
    if os.path.exists(fn): return json.load(open(fn))
    q = f'seasonId={S - 1}{S} and gameTypeId=2 and gameDate<="{day} 23:59:59"'
    r = get('https://api.nhle.com/stats/rest/en/skater/summary?limit=-1&cayenneExp=' + urllib.parse.quote(q))
    os.makedirs(CACHE, exist_ok=True)
    json.dump(r['data'], open(fn, 'w'))
    time.sleep(1)
    return r['data']


SK_X = lambda r: [r['gp'], r['toi'], r['g'], r['a'], r['pp'], r['sh'], r['pm'], r['ev']]
HR2 = {'PHX': 'UTA', 'ARI': 'UTA', 'ATL': 'WPG'}


def nhl_lines(G, S, i, day):
    """to-date lines: {id: line} skaters (stats API) and goalies (game archive), and team points / games"""
    out = {}
    for x in nhl_skaters(S, i, day):
        gp = x['gamesPlayed'] or 0
        if not gp: continue
        tm = x['teamAbbrevs'].split(',')[-1].strip()
        out[str(x['playerId'])] = {'id': str(x['playerId']), 'n': x['skaterFullName'], 'tm': HR2.get(tm, tm),
                                   'grp': 'D' if x['positionCode'] == 'D' else 'F', 'gp': gp,
                                   'toi': (x['timeOnIcePerGame'] or 0) * gp / 60, 'g': x['goals'] or 0, 'a': x['assists'] or 0,
                                   'pts': x['points'] or 0, 'pp': x['ppPoints'] or 0, 'sh': x['shots'] or 0,
                                   'pm': x['plusMinus'] or 0, 'ev': x['evPoints'] or 0, 'gsax': 0.0}
    teams = collections.defaultdict(lambda: [0, 0])
    for g in G:
        if g['S'] != S or g['day'] > day: continue
        hw = g['hs'] > g['as']
        for sd, won in (('h', hw), ('a', not hw)):
            t = teams[g[sd]]
            t[0] += 2 if won else (1 if g.get('per', 3) > 3 else 0); t[1] += 1
            for gid, n, st, toi, sa, ga in g['gl'][sd]:
                r = out.setdefault(str(gid), {'id': str(gid), 'n': n, 'tm': g[sd], 'grp': 'G', 'gp': 0, 'toi': 0.0, 'g': 0,
                                              'pts': 0, 'gsax': 0.0})
                r['gp'] += 1; r['toi'] += toi / 60; r['tm'] = g[sd]
                r['gsax'] += (g.get('gx', {}).get(sd, {}).get(str(gid), ga)) - ga
    return out, dict(teams)


def nhl_build(sims):
    import numpy as np
    import awards_nhl as A
    G, CP = nhl_checkpoints()
    R = A.seasons_data()
    specs = {aw: loso_specs(R[aw], cols, 3) for aw, cols in (('hart', A.HART_COLS), ('norris', A.NORRIS_COLS),
                                                             ('vezina', A.VEZINA_COLS), ('calder', A.CALDER_COLS))}
    byS = {aw: {s: (pool, o) for s, pool, o in R[aw]} for aw in R}
    seasons = [S for S in sorted(CP) if S >= 2011]
    full = {S: nhl_lines(G, S, 3, CP[S][3])[0] for S in seasons}
    war = {S: {r['id']: r for r in A.war(S)} for S in range(2009, 2027)}
    # stand-in fits: WAR and gd from box totals, by group, on the other seasons
    def standin(S):
        fit = {}
        for grp in 'FDG':
            X, yw, yd = [], [], []
            for T in seasons:
                if T == S: continue
                for i, r in full[T].items():
                    w = war[T].get(i)
                    if not w or r['grp'] != grp: continue
                    X.append(SK_X(r) if grp != 'G' else [r['gp'], r['toi'], r['gsax']])
                    yw.append(w.get('war') or 0); yd.append(w.get('gd') or 0)
            fit[grp] = (ridge(X, yw), ridge(X, yd))
        return fit
    hist = {}
    for r in A.war(2009): hist.setdefault(NM.key(r['n']), []).append(r.get('gp') or 0)
    for r in A.war(2010): hist.setdefault(NM.key(r['n']), []).append(r.get('gp') or 0)
    rows = []
    for S in seasons:
        fitS = standin(S)
        Gs = max(collections.Counter([g['h'] for g in G if g['S'] == S] + [g['a'] for g in G if g['S'] == S]).values())
        Gs = min(Gs, 82)
        if S == 2020: Gs = 70
        last = war[S - 1]
        for ci, share in enumerate(SHARES):
            L, T = nhl_lines(G, S, ci, CP[S][ci])
            teams = {}
            for t, (pts, gp) in T.items():
                left = max(Gs - gp, 0)
                xp = 2 * shrunk_left(pts / 2, gp, Gs, 'nhl')
                teams[t] = (pts, gp * 2, xp, math.sqrt(left * 1.0 + (left * .25 * .2) ** 2), 2 * Gs)
            for var in ('box', 'end'):
                cands, rates = [], collections.defaultdict(list)
                for i, r in L.items():
                    if r['tm'] not in teams: continue
                    w = war[S].get(i, {})
                    if var == 'box':
                        x = np.array(SK_X(r) if r['grp'] != 'G' else [r['gp'], r['toi'], r['gsax']], float)
                        wv, gd = float(x @ fitS[r['grp']][0]), float(x @ fitS[r['grp']][1])
                    else:
                        k = r['toi'] / max(w.get('toi') or 0, r['toi'], 1)
                        wv, gd = (w.get('war') or 0) * k, (w.get('gd') or 0) * k
                    q = last.get(i, {})
                    k_ = NM.key(r['n'])
                    past = hist.get(k_, [])
                    rookie = (not any(g > 25 for g in past)) and sum(g > 6 for g in past[-2:]) < 2 and (w.get('age') or 30) < 26
                    c = {'id': i, 'n': r['n'], 'tm': r['tm'], 'grp': r['grp'], 'gp': r['gp'], 'tg': teams[r['tm']][1] / 2,
                         'toi': r['toi'], 'war': wv, 'gd': gd, 'pts': r['pts'], 'g': r['g'], 'gsax': r['gsax'],
                         'ppg0': (q.get('pts') or 0) / q['gp'] if q.get('gp') else None,
                         'gpg0': (q.get('g') or 0) / q['gp'] if q.get('gp') else None,
                         'gsx0': (q.get('gsax') or 0) / max(q.get('toi') or 1, 1) * 60 if q.get('gp') else None,
                         'rookie': rookie, 'key': k_,
                         'pr0': (q.get('pwar') or 0) / q['toi'] if (q.get('toi') or 0) >= 200 else None,
                         'wend': (w.get('pwar') or 0) / w['toi'] if w.get('toi') else 0.0}
                    if r['toi'] >= 100: rates[r['grp']].append(wv / r['toi'])
                    cands.append(c)
                mean = {g: sum(v) / len(v) for g, v in rates.items()}
                for c in cands:
                    if var == 'box':
                        pr = c['pr0'] if c['pr0'] is not None else mean.get(c['grp'], 0)
                        c['pwar'] = (c['war'] + 1000 * pr) / (c['toi'] + 1000) * c['toi']
                    else:
                        c['pwar'] = c['wend'] * c['toi']
                prevS = {}
                for aw in ('hart', 'norris', 'vezina'):
                    prevS[aw] = {NM.key(r['n']): r['prev_' + aw] for r in byS[aw][S][0] if r['prev_' + aw]} if S in byS[aw] else {}
                fit = {aw: specs[aw][S] for aw in specs if S in specs[aw] and byS[aw][S][1]}
                fit['_prev'] = prevS
                rng = random.Random(SEED + S * 10 + ci)
                for aw, pool, p, _, _ in AW.nhl_races(fit, rng, cands, teams, G=Gs, sims=sims):
                    fpool, o = byS[aw][S]
                    rows.append(row('nhl', S, aw, ci, var, pool, p, fpool[o[0]]['id']))
                    print('nhl', S, aw, share, var, rows[-1]['top'], 'winner', fpool[o[0]]['n'],
                          None if rows[-1]['w'] is None else round(p[rows[-1]['w']], 3), flush=True)
        for r in A.war(S): hist.setdefault(NM.key(r['n']), []).append(r.get('gp') or 0)
    return rows


# ---------------------------------------------------------------- NBA

NBA_END = {2020: '2020-03-12'}                       # 2019-20: the awards were voted on the games before the stoppage
BOX_K = ('pts', 'reb', 'ast', 'fg3', 'stl', 'blk', 'tov', 'fga', 'fta')


def nba_boxes():
    P = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_pbox_hist.json.gz')))
    G = [g for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
         if g['t'] == 2 and g.get('fin') and 2013 <= g['S'] <= 2026 and g['tip'][:10] <= NBA_END.get(g['S'], '9')]
    fn = os.path.join(CACHE, 'nba_pbox_1318.json.gz')
    old = json.load(gzip.open(fn)) if os.path.exists(fn) else {}
    todo = [g['id'] for g in G if g['S'] <= 2018 and g['id'] not in old]
    if todo:
        import nba_players as NP
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(6) as ex:
            for gid, b in zip(todo, ex.map(NP.pbox, todo)):
                if b: old[gid] = b
        os.makedirs(CACHE, exist_ok=True)
        json.dump(old, gzip.open(fn, 'wt'), separators=(',', ':'))
    P.update(old)
    return G, P


def nba_lines(G, P, S, day):
    """to-date lines by ESPN id and team records (wins, games, margin). ESPN holds no player lines for about one
    game in eight of 2012-13..2017-18 (every Chicago and New Orleans game: their players are missing those seasons, so
    a winner from them scores the floor in both arms): a player's games and minutes are scaled up by his team's games
    over its games with lines (his rates a game stay as archived)"""
    L, T, B = {}, collections.defaultdict(lambda: [0, 0, 0.0]), collections.Counter()
    for g in G:
        if g['S'] != S or g['tip'][:10] > day: continue
        for sd, o in (('h', 'a'), ('a', 'h')):
            t = T[g[sd]]
            t[0] += g[sd + 's'] > g[o + 's']; t[1] += 1; t[2] += g[sd + 's'] - g[o + 's']
        b = P.get(g['id'])
        if not b: continue
        B[g['h']] += 1; B[g['a']] += 1
        for tm, pl in b.items():
            for x in pl:
                if x[4] <= 0: continue
                r = L.setdefault(x[0], {'eid': x[0], 'n': x[1], 'tm': tm, 'g': 0, 'mp': 0.0, 'tbox': 0, **{k: 0.0 for k in BOX_K}})
                r['g'] += 1; r['mp'] += x[4]; r['tm'] = tm
                for k, v in zip(BOX_K, (x[5], x[6], x[7], x[8], x[9], x[10], x[11], x[12], x[13])): r[k] += v
    for r in L.values():
        k = T[r['tm']][1] / B[r['tm']] if B.get(r['tm']) else 1.0
        if k > 1:
            r['g'] = min(r['g'] * k, T[r['tm']][1]); r['mp'] *= k
            for x in BOX_K: r[x] *= k
    return L, {t: tuple(v) for t, v in T.items()}


def nba_x(r, T):
    m = max(r['mp'], 1)
    w, g, mar = T.get(r['tm'], (0, 1, 0.0))
    return [1.0] + [r[k] / m * 36 for k in BOX_K] + [r['mp'] / max(r['g'], 1), mar / max(g, 1)]


def nba_build(sims):
    import numpy as np
    import awards_nba as A
    import nba_xpm as XP
    G, P = nba_boxes()
    R = A.seasons_data()
    specs = {aw: loso_specs(R[aw], cols, 3) for aw, cols in (('mvp', A.MVP_COLS), ('dpoy', A.DPOY_COLS), ('roy', A.ROY_COLS))}
    byS = {aw: {s: (pool, o) for s, pool, o in R[aw]} for aw in R}
    seasons = sorted({g['S'] for g in G})
    days = {S: sorted(g['tip'][:10] for g in G if g['S'] == S) for S in seasons}
    conf = {p['t']: p.get('cname') for p in AW.jload(os.path.join(ROOT, 'data', 'nba_games.json'), {}).get('power', [])}
    xpm = {S: A.xpm(S) for S in range(2010, 2027)}
    # ESPN id -> bbref id by name inside the season
    idmap, full = {}, {}
    for S in seasons:
        L, T = nba_lines(G, P, S, days[S][-1])
        full[S] = (L, T)
        pool = list(xpm[S].values())
        m = NM.Matcher(pool, name='n', team=None, pos=None)
        for e, r in L.items():
            hit, _ = m.find(r['n'])
            if hit is not None: idmap[(S, e)] = hit['id']
    def standin(S):
        X, y, yd, w = [], [], [], []
        for T_ in seasons:
            if T_ == S: continue
            L, T = full[T_]
            for e, r in L.items():
                x = xpm[T_].get(idmap.get((T_, e)))
                if not x or r['mp'] < 300 or x.get('xpm') is None: continue
                X.append(nba_x(r, T)); y.append(x['xpm']); yd.append(x['dxpm']); w.append(r['mp'])
        return ridge(X, y, w), ridge(X, yd, w)
    rows = []
    for S in seasons:
        bx, bd = standin(S)
        Lf, Tf = full[S]
        Gs = min(82, int(sorted(v[1] for v in Tf.values())[len(Tf) // 2]))
        pri = XP.shrink_prior(S)
        pg0 = A.per_game(S - 1)
        seen = set()
        for s in range(2010, S): seen |= set(xpm[s])
        for ci, share in enumerate(SHARES):
            day = days[S][int(len(days[S]) * share) - 1]
            L, T = nba_lines(G, P, S, day)
            teams = {}
            for t, (w, g, _) in T.items():
                xw = shrunk_left(w, g, Gs, 'nba')
                teams[t] = (w, g, xw, AW.team_sd(max(Gs - g, 0), xw / Gs, 3, .030), Gs)
            for var in ('box', 'end'):
                cands = []
                for e, r in L.items():
                    pid = idmap.get((S, e))
                    x = xpm[S].get(pid)
                    if not x or r['tm'] not in teams or not r['g']: continue
                    if var == 'box':
                        v = np.array(nba_x(r, T))
                        xv, dv = float(v @ bx), float(v @ bd)
                    else:
                        xv, dv = x['xpm'], x['dxpm']
                    sh = XP.shrink({'id': pid, 'mp': r['mp'], 'xpm': xv, 'oxpm': xv - dv, 'dxpm': dv}, max(teams[r['tm']][1], 1), pri)
                    q = pg0.get(pid, {})
                    cands.append({'id': pid, 'n': x['n'], 'tm': r['tm'], 'g': r['g'], 'tg': teams[r['tm']][1], 'mp': r['mp'],
                                  'xpm': xv, 'dxpm': dv, 'sx': sh['sxpm'], 'sdx': sh['sdxpm'],
                                  'ppg': r['pts'] / r['g'], 'ppg0': q.get('pts_per_g'), 'rpg': r['reb'] / r['g'],
                                  'rpg0': q.get('trb_per_g'), 'st': (r['stl'] + r['blk']) / r['g'],
                                  'st0': (q.get('stl_per_g', 0) + q.get('blk_per_g', 0)) if q else None,
                                  'mpg': r['mp'] / r['g'], 'pos': x.get('pos', ''), 'rookie': pid not in seen})
                prevS = {aw: {r['id']: r['prev_' + aw] for r in byS[aw][S][0] if r['prev_' + aw]} for aw in ('mvp', 'dpoy')}
                fit = {aw: specs[aw][S] for aw in specs if S in specs[aw] and byS[aw][S][1]}
                fit['_prev'] = prevS
                rng = random.Random(SEED + S * 10 + ci)
                for aw, pool, p, _, _ in AW.nba_races(fit, rng, cands, teams, conf, G=Gs, min_g=65 if S >= 2024 else 0, sims=sims):
                    fpool, o = byS[aw][S]
                    rows.append(row('nba', S, aw, ci, var, pool, p, fpool[o[0]]['id']))
                    print('nba', S, aw, share, var, rows[-1]['top'], 'winner', fpool[o[0]]['n'],
                          None if rows[-1]['w'] is None else round(p[rows[-1]['w']], 3), flush=True)
    return rows


# ---------------------------------------------------------------- NFL

def nfl_season_pools(first=2005, last=2025):
    """season-end pools and AP winners from nflverse (voter refits and the new races)"""
    import awards_football as F
    RK = rookies()
    rook = {k: v[0] for k, v in RK.items()}
    GM = nfl_games()
    out = {}
    for S in range(first, last + 1):
        W = nfl_weekly(S)
        wk = max(w for w, *_ in GM[S])
        tot = nfl_totals(W, wk, rook, S)
        T = nfl_records(GM[S], wk)
        for r in tot.values():
            r['wp'] = T[r['tid']][0] / max(T[r['tid']][1], 1)
            r['r1'] = 1.0 if RK.get(r['id'], (0, None))[1] == 1 else 0.0
        out[S] = (W, tot, GM[S], rook)
    return out


def nfl_voter_races(pools):
    import awards_football as F
    Wn = {a: F.nfl_winners(a) for a in ('mvp', 'opoy', 'oroy')}
    races = {a: [] for a in Wn}
    mvps = dict(F.PRE_MVP)
    for S in sorted(pools):
        rows = list(pools[S][1].values())
        for r in rows: r['prev_mvp'] = mvps.get(NM.key(r['n']), 0)
        off = [r for r in rows if r['off'] and r['yds'] >= 400]
        for a, pool in (('mvp', off), ('opoy', off), ('oroy', [r for r in off if r['rookie']])):
            o = F._order(pool, Wn[a].get(S, [])[:1])
            if not o or o[0] is None:
                print('nfl', S, a, 'winner outside pool', Wn[a].get(S)); races[a].append((S, pool, [])); continue
            races[a].append((S, pool, o[:1]))
        for n in Wn['mvp'].get(S, [])[:1]: mvps[NM.key(n)] = mvps.get(NM.key(n), 0) + 1
    return races


def nfl_build(sims):
    import awards_football as F
    pools = nfl_season_pools()
    R = nfl_voter_races(pools)
    specs = {a: loso_specs(R[a], F.NFL_COLS[a], 1) for a in R}
    byS = {a: {s: (pool, o) for s, pool, o in R[a]} for a in R}
    rows = []
    for S in sorted(pools):
        W, tot, GM, rook = pools[S]
        Gs = 17 if S >= 2021 else 16
        nG = len(GM); cum = collections.Counter(w for w, *_ in GM)
        for ci, share in enumerate(SHARES):
            acc, wk = 0, 0
            for w in sorted(cum):
                acc += cum[w]; wk = w
                if acc >= share * nG: break
            T = nfl_records(GM, wk)
            teams = {}
            for t, (w, g) in T.items():
                xw = shrunk_left(w, g, Gs, 'nfl')
                teams[t] = (w, g, xw, AW.team_sd(max(Gs - g, 0), xw / Gs, 3, .03), Gs)
            cands = []
            for r in nfl_totals(W, wk, rook, S).values():
                if r['tid'] not in teams: continue
                f = dict(r)
                f['prev_mvp'] = next((x['prev_mvp'] for x in byS['mvp'][S][0] if x['id'] == r['id']), 0)
                cands.append({'id': r['id'], 'n': r['n'], 'tid': r['tid'], 'tm': r['tid'], 'pos': r['pos'], 'f': f})
            cands = [c for c in cands if c['f']['off']]
            fit = {a: specs[a][S] for a in specs if byS[a][S][1]}
            rng = random.Random(SEED + S * 10 + ci)
            for aw, pool, p, _, _ in AW.nfl_races(fit, rng, cands, teams, sims=sims):
                fpool, o = byS[aw][S]
                rows.append(row('nfl', S, aw, ci, 'box', pool, p, fpool[o[0]]['id']))
                print('nfl', S, aw, share, 'wk', wk, rows[-1]['top'], 'winner', fpool[o[0]]['n'],
                      None if rows[-1]['w'] is None else round(p[rows[-1]['w']], 3), flush=True)
    return rows


# ---------------------------------------------------------------- temperature and scores

def temper(p, T):
    """p_i ^ (1 / T), renormalised (stdlib; scripts/awards.py holds the same lines)"""
    q = [max(v, 1e-300) ** (1 / T) for v in p]
    t = sum(q)
    return [v / t for v in q]


def pw(r, a):
    """floored P(winner) of a row under temperature slope a"""
    if r['w'] is None: return FLOOR
    p = r['p'] if a == 0 else temper(r['p'], 1 + a * (1 - SHARES[r['cp']]))
    return max(p[r['w']], FLOOR)


def best_a(rows):
    return min(GRID, key=lambda a: sum(-math.log(pw(r, a)) for r in rows))


def score(rows, sport, var='box'):
    R = [r for r in rows if r['sp'] == sport and r['var'] == var]
    if not R: return None
    seasons = sorted({r['s'] for r in R})
    d, folds = [], {}
    for s in seasons:
        a = best_a([r for r in R if r['s'] != s])
        folds[s] = a
        own = [r for r in R if r['s'] == s]
        d.append(sum(math.log(pw(r, 0)) - math.log(pw(r, a)) for r in own) / len(own))
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    a_all = best_a(R)
    ll = lambda a: sum(-math.log(pw(r, a)) for r in R) / len(R)
    rel = []
    for ci in range(3):
        for tag, a in (('now', 0.0), ('temp', None)):
            fp, hit, k = 0.0, 0, 0
            for r in R:
                if r['cp'] != ci: continue
                aa = folds[r['s']] if a is None else a
                p = r['p'] if aa == 0 else temper(r['p'], 1 + aa * (1 - SHARES[ci]))
                top = max(range(len(p)), key=p.__getitem__)
                fp += p[top]; hit += int(top == r['w']); k += 1
            rel.append({'share': SHARES[ci], 'arm': tag, 'n': k, 'fav': round(fp / k, 3), 'hit': round(hit / k, 3)})
    return {'sport': sport, 'var': var, 'seasons': n, 'rows': len(R), 'no_pool': sum(r['w'] is None for r in R),
            'll_now': round(ll(0), 4), 'll_temp_loso': round(sum(-math.log(pw(r, folds[r['s']])) for r in R) / len(R), 4),
            'd': round(m, 4), 't': round(t, 2), 'p': round(t_sf(-t, n - 1), 5), 'a_all': a_all,
            'd_insample': round(ll(a_all) - ll(0), 4), 'folds': sorted(set(folds.values())),
            'wins': sum(x < 0 for x in d), 'rel': rel}


def report(rows):
    sports = sorted({r['sp'] for r in rows})
    res = {sp: score(rows, sp) for sp in sports}
    bound = {sp: score(rows, sp, 'end') for sp in sports}
    ok = holm([res[sp]['p'] for sp in sports])
    out = {}
    for sp, k in zip(sports, ok):
        r, b = res[sp], bound[sp]
        r['pass'] = bool(k and r['t'] <= -2 and r['d_insample'] < 0 and r['a_all'] > 0 and (b is None or b['d'] <= 0))
        r['bound'] = b
        a = min(r['a_all'], b['a_all']) if b else r['a_all']
        out[sp] = {'a': a if r['pass'] else 0.0, 'test': r}
        print(f"{sp}: rows {r['rows']} seasons {r['seasons']} log loss {r['ll_now']} -> {r['ll_temp_loso']} d {r['d']:+.4f} "
              f"t {r['t']} p {r['p']} a {r['a_all']} folds {r['folds']} wins {r['wins']}/{r['seasons']} "
              f"{'PASS' if r['pass'] else 'fail'}" + (f" | bound: d {b['d']:+.4f} t {b['t']} a {b['a_all']}" if b else ''))
        for x in r['rel']: print('   ', x)
    return out


BUILD = {'nhl': nhl_build, 'nba': nba_build, 'nfl': nfl_build}


def main(argv):
    fn = lambda sp: os.path.join(CACHE, f'rows_{sp}.json')
    sims = AW.SIMS
    for a in argv:
        if a.startswith('--sims='): sims = int(a[7:])
    for sp in [a for a in argv if a in BUILD]:
        os.makedirs(CACHE, exist_ok=True)
        json.dump(BUILD[sp](sims), open(fn(sp), 'w'))
    rows = [r for sp in BUILD for r in (AW.jload(fn(sp), []) or [])]
    if '--noscore' in argv or not rows: return
    out = report(rows)
    if '--write' in argv:
        json.dump(out, open(OUT, 'w'), indent=1, sort_keys=True)
        print('wrote', OUT)


if __name__ == '__main__':
    main(sys.argv[1:])
