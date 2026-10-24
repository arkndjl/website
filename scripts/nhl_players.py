#!/usr/bin/env python3
"""NHL player value for the NHL ARKBOARD: HPM (goals per 60 over an average player) and WAR (wins over replacement),
every skater and goalie since 2008-09, from MoneyPuck's season summaries.

    python3 scripts/nhl_players.py --fit     # fit the component weights to team results, out of sample (numpy)
    python3 scripts/nhl_players.py           # write static/data/nhl-war/<season>.json and data/nhl_war.json

Skater components, each in goals per 60 of the player's ice time, centred on the league:
    evf, eva   5-on-5 on-ice expected goals for and against a 60, relative to his team with him off the ice, scaled by
               his 5-on-5 share of his ice time (eva signed so positive = fewer allowed)
    g, ixg     goals and individual expected goals a 60 (finishing is the gap between the two)
    a1, a2     primary and secondary assists a 60
    pp, pk     power-play on-ice xG for and penalty-kill on-ice xG against, each against the league's rate, scaled by
               his share of ice time in that state
    pen        penalties drawn minus taken a 60
The weights are fit so that last season's rates (shrunk toward a newcomer's level by ice time) times this season's ice
time predict each team's goal differential a game this season, every season held out in turn (ridge, the penalty chosen
by the same held-out error). Goalies: goals saved above expected a 60 (MoneyPuck xG against minus goals), shrunk.
HPM = the weighted sum, shrunk by ice time. WAR = (HPM - replacement) x TOI / 60 / goals a win, where replacement is the
HPM of the skaters outside each team's top 13 forwards and 7 defencemen by ice time (call-ups, freely available), and
goals a win comes from team points against goal differential.
"""
import csv
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nhl_data as D

ROOT = os.path.dirname(HERE)
MPD = os.path.join(D.CACHE, 'mp')
FIT = os.path.join(ROOT, 'data', 'nhl_war_fit.json')
IDX = os.path.join(ROOT, 'data', 'nhl_war.json')
OUTD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
FIRST, COMPS = 2009, ['evf', 'eva', 'g', 'ixg', 'a1', 'a2', 'pp', 'pk', 'pen']


def mp_file(kind, S, fresh=False):
    """MoneyPuck's regular-season summary for season S (file year S - 1)"""
    fn = os.path.join(MPD, f'{kind}_{S - 1}.csv')
    if fresh or not os.path.exists(fn) or (S >= D.current_season() and (dt.datetime.now().timestamp() - os.path.getmtime(fn)) > 6 * 3600):
        b = D.get(f'{D.MP}/seasonSummary/{S - 1}/regular/{kind}.csv', raw=True)
        if b:
            os.makedirs(MPD, exist_ok=True)
            open(fn, 'wb').write(b)
    if not os.path.exists(fn):
        return []
    return list(csv.DictReader(open(fn)))


def bios():
    fn = os.path.join(MPD, 'allPlayersLookup.csv')
    if not os.path.exists(fn) or dt.datetime.now().timestamp() - os.path.getmtime(fn) > 7 * 86400:
        b = D.get(f'{D.MP}/playerBios/allPlayersLookup.csv', raw=True)
        if b:
            os.makedirs(MPD, exist_ok=True)
            open(fn, 'wb').write(b)
    out = {}
    for r in csv.DictReader(open(fn)):
        out[r['playerId']] = r
    return out


def f(r, k):
    try:
        return float(r.get(k) or 0)
    except ValueError:
        return 0.0


def skaters(S):
    """one row a skater-season: ice time, team, position, raw component rates (per 60, uncentred)"""
    by = defaultdict(dict)
    for r in mp_file('skaters', S):
        by[r['playerId']][r['situation']] = r
    out = []
    for pid, s in by.items():
        al, e5, pp, pk = s.get('all'), s.get('5on5'), s.get('5on4'), s.get('4on5')
        if not al:
            continue
        toi = f(al, 'icetime')
        if toi < 60:
            continue
        h = toi / 3600
        row = {'id': pid, 'n': al['name'], 'tm': D.team(al['team']), 'pos': 'D' if al['position'] == 'D' else 'F',
               'p': al['position'], 'gp': int(f(al, 'games_played')), 'toi': toi,
               'g': f(al, 'I_F_goals') / h, 'ixg': f(al, 'I_F_xGoals') / h, 'a1': f(al, 'I_F_primaryAssists') / h,
               'a2': f(al, 'I_F_secondaryAssists') / h, 'pen': (f(al, 'penaltiesDrawn') - f(al, 'penalties')) / h,
               'pts': f(al, 'I_F_points'), 'goals': f(al, 'I_F_goals')}
        if e5 and f(e5, 'icetime') > 0 and f(e5, 'timeOnBench') > 0:
            i5, b5 = f(e5, 'icetime') / 3600, f(e5, 'timeOnBench') / 3600
            sh = f(e5, 'icetime') / toi
            row['evf'] = (f(e5, 'OnIce_F_xGoals') / i5 - f(e5, 'OffIce_F_xGoals') / b5) * sh
            row['eva'] = -(f(e5, 'OnIce_A_xGoals') / i5 - f(e5, 'OffIce_A_xGoals') / b5) * sh
        else:
            row['evf'] = row['eva'] = 0.0
        row['_pp'] = (f(pp, 'OnIce_F_xGoals'), f(pp, 'icetime')) if pp else (0, 0)
        row['_pk'] = (f(pk, 'OnIce_A_xGoals'), f(pk, 'icetime')) if pk else (0, 0)
        out.append(row)
    # power play and penalty kill against the league's rate in that state
    ppx = sum(r['_pp'][0] for r in out); ppt = sum(r['_pp'][1] for r in out)
    pkx = sum(r['_pk'][0] for r in out); pkt = sum(r['_pk'][1] for r in out)
    lpp, lpk = ppx / ppt * 3600 if ppt else 0, pkx / pkt * 3600 if pkt else 0
    for r in out:
        x, t = r.pop('_pp'); r['pp'] = (x / t * 3600 - lpp) * t / r['toi'] if t > 0 else 0.0
        x, t = r.pop('_pk'); r['pk'] = -(x / t * 3600 - lpk) * t / r['toi'] if t > 0 else 0.0
    # centre the individual rates on the league (ice-time weighted)
    tt = sum(r['toi'] for r in out)
    for k in ('g', 'ixg', 'a1', 'a2', 'pen'):
        m = sum(r[k] * r['toi'] for r in out) / tt
        for r in out:
            r[k] -= m
    return out


def goalies(S):
    out = []
    for r in mp_file('goalies', S):
        if r['situation'] != 'all':
            continue
        toi = f(r, 'icetime')
        if toi < 60:
            continue
        out.append({'id': r['playerId'], 'n': r['name'], 'tm': D.team(r['team']), 'pos': 'G', 'p': 'G',
                    'gp': int(f(r, 'games_played')), 'toi': toi, 'xga': f(r, 'xGoals'), 'ga': f(r, 'goals'),
                    'gsax60': (f(r, 'xGoals') - f(r, 'goals')) / (toi / 3600)})
    return out


def team_results(S):
    """team goal differential a game and points a game, regular season (NHL stats API game list)"""
    gd, gp, pts = defaultdict(float), defaultdict(int), defaultdict(float)
    for g in D.games(S):
        if g['type'] != 2 or not g['final']:
            continue
        h, a, hs, as_ = g['h'], g['a'], g['hs'], g['as']
        ot = (g['per'] or 3) > 3
        so = (g['per'] or 3) >= 5
        # a shootout winner is credited a goal in the final score; take it out of the differential
        if so:
            if hs > as_:
                hs -= 1
            else:
                as_ -= 1
        gd[h] += hs - as_; gd[a] += as_ - hs; gp[h] += 1; gp[a] += 1
        w, l = (g['h'], g['a']) if g['hs'] > g['as'] else (g['a'], g['h'])
        pts[w] += 2
        if ot:
            pts[l] += 1
    return {t: (gd[t] / gp[t], pts[t] / gp[t], gp[t]) for t in gp}


def shrink(rate, toi, k, prior=0.0):
    """per-60 rate shrunk toward prior with k seconds of pseudo ice time"""
    return (rate * toi + prior * k) / (toi + k)


def fit():
    import numpy as np
    seasons = list(range(FIRST, D.current_season()))
    sk = {S: skaters(S) for S in seasons}
    gk = {S: goalies(S) for S in seasons}
    res = {S: team_results(S) for S in seasons}
    print('seasons', len(seasons), flush=True)

    def design(K, KG):
        """team-season rows: sum over this season's skaters of (TOI this season) x (last season's shrunk component
        rates), per game; goalies likewise on GSAx a 60"""
        X, y, w, keys = [], [], [], []
        for S in seasons[1:]:
            prev = {r['id']: r for r in sk[S - 1]}
            prevg = {r['id']: r for r in gk[S - 1]}
            agg = defaultdict(lambda: np.zeros(len(COMPS) + 1))
            for r in sk[S]:
                p = prev.get(r['id'])
                v = np.array([shrink(p[c], p['toi'], K) if p else 0.0 for c in COMPS] + [0.0])
                agg[r['tm']] += v * r['toi'] / 3600
            for r in gk[S]:
                p = prevg.get(r['id'])
                agg[r['tm']][-1] += (shrink(p['gsax60'], p['toi'], KG) if p else 0.0) * r['toi'] / 3600
            for t, v in agg.items():
                if t not in res[S]:
                    continue
                gdpg, ppg, gp = res[S][t]
                X.append(v / gp); y.append(gdpg); keys.append((S, t))
        return np.array(X), np.array(y), keys

    best = None
    for K in (3600 * 5, 3600 * 10, 3600 * 20):
        for KG in (3600 * 10, 3600 * 25, 3600 * 50):
            X, y, keys = design(K, KG)
            S_ = np.array([k[0] for k in keys])
            for lam in (0.1, 1.0, 10.0):
                pred = np.zeros(len(y))
                for s in sorted(set(S_)):
                    tr, te = S_ != s, S_ == s
                    A = np.column_stack([X[tr], np.ones(tr.sum())])
                    R = lam * np.eye(A.shape[1]); R[-1, -1] = 0
                    b = np.linalg.solve(A.T @ A + R, A.T @ y[tr])
                    pred[te] = np.column_stack([X[te], np.ones(te.sum())]) @ b
                mse = float(((pred - y) ** 2).mean())
                if best is None or mse < best[0]:
                    best = (mse, K, KG, lam)
    mse, K, KG, lam = best
    X, y, keys = design(K, KG)
    S_ = np.array([k[0] for k in keys])
    base = float(((y - y.mean()) ** 2).mean())

    def loso(cols):
        pred = np.zeros(len(y))
        for s in sorted(set(S_)):
            tr, te = S_ != s, S_ == s
            A = np.column_stack([X[tr][:, cols], np.ones(tr.sum())])
            R = lam * np.eye(A.shape[1]); R[-1, -1] = 0
            b = np.linalg.solve(A.T @ A + R, A.T @ y[tr])
            pred[te] = np.column_stack([X[te][:, cols], np.ones(te.sum())]) @ b
        return pred
    allc = list(range(len(COMPS) + 1))
    full = loso(allc)
    e_full = (full - y) ** 2
    ev = {}
    names = COMPS + ['gsax']
    for j, nm in enumerate(names):
        p = loso([c for c in allc if c != j])
        d = (p - y) ** 2 - e_full
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
        ev[nm] = {'dMse': round(float(d.mean()), 5), 't': round(t, 2)}
        print(nm, ev[nm], flush=True)
    # forward selection from the core (on-ice xG both ways, goalies): add the component that lowers held-out error
    # most while its paired t is 1.5 or more; drop-one alone would throw out both of a correlated pair (goals, assists)
    keep = [names.index(c) for c in ('evf', 'eva', 'gsax')]
    steps = []
    while True:
        cur = (loso(keep) - y) ** 2
        cand = []
        for j in allc:
            if j in keep:
                continue
            d = (loso(keep + [j]) - y) ** 2 - cur
            t = float(-d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
            cand.append((t, j, float(d.mean())))
        if not cand:
            break
        t, j, dm = max(cand)
        if t < 1.5:
            break
        keep.append(j); steps.append({'add': names[j], 't': round(t, 2), 'dMse': round(dm, 5)})
        print('add', names[j], round(t, 2), flush=True)
    A = np.column_stack([X[:, keep], np.ones(len(y))])
    R = lam * np.eye(A.shape[1]); R[-1, -1] = 0
    b = np.linalg.solve(A.T @ A + R, A.T @ y)
    w = {names[j]: round(float(bj), 4) for j, bj in zip(keep, b[:-1])}
    pk = loso(keep)
    r2 = 1 - float(((pk - y) ** 2).mean()) / base
    # baselines for the page: last season's points alone, on-ice xG alone
    pts_only = loso([names.index('g'), names.index('a1'), names.index('a2')])
    xg_only = loso([names.index('evf'), names.index('eva')])
    # goals a win: team points a game against goal differential a game
    gd = np.array([res[k[0]][k[1]][0] for k in keys]); ppg = np.array([res[k[0]][k[1]][1] for k in keys])
    slope = float(np.polyfit(gd, ppg, 1)[0])            # points a game per goal a game
    gpw = 2 / slope                                     # a win = 2 points
    out = {'updated': dt.date.today().isoformat(), 'K': K, 'KG': KG, 'lam': lam, 'w': w, 'evidence': ev, 'steps': steps,
           'teamSeasons': len(y), 'r2': round(r2, 3), 'r2Points': round(1 - float(((pts_only - y) ** 2).mean()) / base, 3),
           'r2OnIceXg': round(1 - float(((xg_only - y) ** 2).mean()) / base, 3), 'goalsPerWin': round(gpw, 2)}
    print(out, flush=True)
    json.dump(out, open(FIT, 'w'), indent=1)


def rate(r, fitd):
    """HPM: the weighted components, shrunk by ice time (skaters); GSAx a 60 shrunk (goalies)"""
    w = fitd['w']
    if r['pos'] == 'G':
        return shrink(r['gsax60'], r['toi'], fitd['KG']) * w.get('gsax', 1.0), 0.0, 0.0
    o = sum(w.get(c, 0) * r[c] for c in ('evf', 'g', 'ixg', 'a1', 'a2', 'pp', 'pen'))
    d = sum(w.get(c, 0) * r[c] for c in ('eva', 'pk'))
    k = fitd['K']
    return shrink(o + d, r['toi'], k), shrink(o, r['toi'], k), shrink(d, r['toi'], k)


def season_table(S, fitd, bio):
    sk, gk = skaters(S), goalies(S)
    rows = sk + gk
    for r in rows:
        r['hpm'], r['o'], r['d'] = rate(r, fitd)
    # replacement: skaters outside each team's top 13 forwards / 7 defencemen by ice time; goalies outside the top 2
    repl = {}
    for pos, top in (('F', 13), ('D', 7), ('G', 2)):
        by = defaultdict(list)
        for r in rows:
            if r['pos'] == pos:
                by[r['tm']].append(r)
        rest = [r for t in by for r in sorted(by[t], key=lambda r: -r['toi'])[top:]]
        tt = sum(r['toi'] for r in rest)
        repl[pos] = sum(r['hpm'] * r['toi'] for r in rest) / tt if tt else 0.0
    gpw = fitd['goalsPerWin']
    out = []
    for r in rows:
        b = bio.get(r['id'], {})
        age = None
        if b.get('birthDate'):
            try:
                bd = dt.date.fromisoformat(b['birthDate'][:10])
                ref = dt.date(S - 1, 9, 15)
                age = ref.year - bd.year - ((ref.month, ref.day) < (bd.month, bd.day))
            except ValueError:
                pass
        war = (r['hpm'] - repl[r['pos']]) * r['toi'] / 3600 / gpw
        out.append({'id': r['id'], 'n': r['n'], 'tm': r['tm'], 'pos': r['p'], 'grp': r['pos'], 'age': age, 'gp': r['gp'],
                    'toi': round(r['toi'] / 60), 'hpm': round(r['hpm'], 3), 'o': round(r['o'], 3), 'd': round(r['d'], 3),
                    'war': round(war, 2), 'pts': int(r.get('pts', 0)) if r['pos'] != 'G' else None,
                    'g': int(r.get('goals', 0)) if r['pos'] != 'G' else None,
                    'gsax': round(r['xga'] - r['ga'], 1) if r['pos'] == 'G' else None})
    out.sort(key=lambda r: -r['war'])
    return out, repl


def build(seasons=None):
    fitd = json.load(open(FIT))
    bio = bios()
    cur = D.current_season()
    seasons = seasons or list(range(FIRST, cur + 1))
    os.makedirs(OUTD, exist_ok=True)
    try:
        idx = json.load(open(IDX))
    except (OSError, ValueError):
        idx = {'seasons': []}
    have = {s['season']: s for s in idx.get('seasons', [])}
    for S in seasons:
        rows, repl = season_table(S, fitd, bio)
        if not rows:
            continue
        asof = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
        gmax = max(r['gp'] for r in rows)
        json.dump({'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'asof': asof, 'n': len(rows), 'games': gmax,
                   'repl': {k: round(v, 3) for k, v in repl.items()}, 'players': rows},
                  open(os.path.join(OUTD, f'{S}.json'), 'w'), separators=(',', ':'))
        have[S] = {'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'n': len(rows), 'games': gmax, 'asof': asof}
        print(S, len(rows), 'top', rows[0]['n'], rows[0]['war'], flush=True)
    idx = {'current': max(have), 'seasons': sorted(have.values(), key=lambda s: -s['season']), 'w': fitd['w'],
           'goalsPerWin': fitd['goalsPerWin'], 'r2': fitd['r2'], 'r2Points': fitd['r2Points'], 'r2OnIceXg': fitd['r2OnIceXg'],
           'teamSeasons': fitd['teamSeasons']}
    json.dump(idx, open(IDX, 'w'), indent=1)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    elif '--current' in sys.argv:
        build([D.current_season()])
    else:
        build()
