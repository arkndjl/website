#!/usr/bin/env python3
"""NHL player value for the NHL ARKBOARD: HPM (goals per 60 over an average player) and WAR (wins over replacement),
every skater and goalie since 2008-09, from MoneyPuck's season summaries.

    python3 scripts/nhl_players.py --fit     # fit pWAR's weights to team results out of sample, WAR's levels (numpy)
    python3 scripts/nhl_players.py           # write static/data/nhl-war/<season>.json and data/nhl_war.json

Skater components, each in goals per 60 of the player's ice time, centred on the league:
    evf, eva   5-on-5 on-ice expected goals for and against a 60, relative to his team with him off the ice, scaled by
               his 5-on-5 share of his ice time (eva signed so positive = fewer allowed)
    g, ixg     goals and individual expected goals a 60 (finishing is the gap between the two)
    a1, a2     primary and secondary assists a 60
    pp, pk     power-play on-ice xG for and penalty-kill on-ice xG against, each against the league's rate, scaled by
               his share of ice time in that state
    pen        penalties drawn minus taken a 60
Two values a season:
WAR (descriptive, what happened): goals over replacement at goal value, / goals a win. Skaters: evf and eva at 1 (a
    player's own on-ice xG effect against his teammates'), power-play / penalty-kill on-ice xG split among the 5 or 4
    skaters, finishing (goals - xG) at 1, penalties drawn - taken at the league's net power-play goals a penalty, and an
    even share a minute of the team's xG for and against not credited to anyone. Goalies: GSAx at 1. It adds up to each
    team's goal differential the same season (R2 .975, slope 1.00 over 554 team-seasons). Replacement: the descriptive
    rate of the players outside each team's top 13 forwards / 7 defencemen / 2 goalies by ice time, pooled over seasons.
pWAR (projected, what it is worth going forward): HPM = the weighted components over this season and the two before
    (Marcel weights, tuned), shrunk by ice time toward a learned target (newcomers and short histories sit below
    average, not at it), centred on the average skater / goalie. The weights are fit so that the seasons before predict
    each team's goal differential a game (players weighted by their share of the team's ice time), every season held
    out in turn (ridge, the penalty, shrink and Marcel weights chosen by the same held-out error). Oct 25 2026: R2 .23 ->
    .38 over 524 team-seasons, paired t 4.95, 15 of 17 seasons (nested tuning: t 4.6, 14/17). Age curve, a usage-tier
    target and a rookie prior from draft slot + NHLe all failed (t -.2, .1, 1.8).
    pWAR = (HPM - replacement) x TOI / 60 / goals a win, replacement as above on HPM; goals a win from team points
    against goal differential.
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
               'pts': f(al, 'I_F_points'), 'goals': f(al, 'I_F_goals'),
               'fin': (f(al, 'I_F_goals') - f(al, 'I_F_xGoals')) / h}
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
    if not out:
        return out
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


def teams(S):
    """MoneyPuck team totals, all situations: expected goals for and against, games"""
    out = {}
    for r in mp_file('teams', S):
        if r['situation'] == 'all':
            out[D.team(r['team'])] = {'xgf': f(r, 'xGoalsFor'), 'xga': f(r, 'xGoalsAgainst'), 'gp': f(r, 'games_played')}
    return out


def pen_value(S):
    """net power-play goals (5-on-4 for minus against) a penalty taken, league-wide"""
    net = sum(f(r, 'goalsFor') - f(r, 'goalsAgainst') for r in mp_file('teams', S) if r['situation'] == '5on4')
    pens = sum(f(r, 'penalties') for r in mp_file('skaters', S) if r['situation'] == 'all')
    return net / pens if pens else None


def describe(S, sk, gk, pv):
    """descriptive goals a 60 over an average player, at goal value (adds to each team's goal differential):
    skaters: 5-on-5 on-ice xG for and against relative to teammates (evf, eva, at 1), power-play and penalty-kill
    on-ice xG split among the 5 or 4 skaters, finishing (goals - xG, at 1), penalties drawn - taken at the league's net
    power-play goals a penalty, and an even share a minute of the team's xG for and against not credited to anyone;
    goalies: GSAx a 60, at 1. Sets r['dr'] (the rate), r['do'], r['dd'] (offense, defense parts)"""
    tm = teams(S)
    H = sum(r['toi'] for r in sk) / 3600
    lf = sum(r['fin'] * r['toi'] for r in sk) / 3600 / H if H else 0.0
    L = sum(t['xgf'] for t in tm.values()) / max(1, sum(t['gp'] for t in tm.values()))
    for r in sk:
        r['do'] = r['evf'] + r['pp'] / 5 + r['pen'] * pv + r['fin'] - lf
        r['dd'] = r['eva'] + r['pk'] / 4
    by = defaultdict(list)
    for r in sk:
        by[r['tm']].append(r)
    for t, rs in by.items():
        T = tm.get(t)
        h = sum(r['toi'] for r in rs) / 3600
        if not T or not h:
            continue
        ot = (T['xgf'] - L * T['gp'] - sum(r['toi'] / 3600 * (r['do'] - r['fin'] + lf) for r in rs)) / h
        dt_ = (L * T['gp'] - T['xga'] - sum(r['toi'] / 3600 * r['dd'] for r in rs)) / h
        for r in rs:
            r['do'] += ot
            r['dd'] += dt_
    G = sum(r['toi'] for r in gk) / 3600
    lg = sum(r['gsax60'] * r['toi'] for r in gk) / 3600 / G if G else 0.0
    for r in sk:
        r['dr'] = r['do'] + r['dd']
    for r in gk:
        r['do'], r['dd'] = 0.0, r['gsax60'] - lg
        r['dr'] = r['dd']


def depth_rest(rows, pos, top):
    """the players outside each team's top `top` at a position by ice time"""
    by = defaultdict(list)
    for r in rows:
        if r['pos'] == pos:
            by[(r.get('S'), r['tm'])].append(r)
    return [r for k in by for r in sorted(by[k], key=lambda r: -r['toi'])[top:]]


def fit_desc():
    """descriptive WAR: the league's net power-play goals a penalty by season, replacement levels (pooled over every
    season) and how well the descriptive values add up to each team's goal differential the same season"""
    import numpy as np
    seasons = list(range(FIRST, D.current_season()))
    pv, rows, ys, ps = {}, [], [], []
    for S in seasons:
        sk, gk, res = skaters(S), goalies(S), team_results(S)
        pv[S] = round(pen_value(S), 4)
        describe(S, sk, gk, pv[S])
        tot = defaultdict(float)
        for r in sk + gk:
            r['S'] = S
            tot[r['tm']] += r['dr'] * r['toi'] / 3600
        for t, (gd, ppg, gp) in res.items():
            if t in tot:
                ys.append(gd); ps.append(tot[t] / gp)
        rows += sk + gk
    ys, ps = np.array(ys), np.array(ps)
    r2 = 1 - float(((ys - ps) ** 2).sum() / ((ys - ys.mean()) ** 2).sum())
    slope = float(np.polyfit(ps, ys, 1)[0])
    repl = {}
    for pos, top in (('F', 13), ('D', 7), ('G', 2)):
        rest = depth_rest(rows, pos, top)
        repl[pos] = round(sum(r['dr'] * r['toi'] for r in rest) / sum(r['toi'] for r in rest), 4)
    out = {'penValue': pv, 'repl': repl, 'r2Same': round(r2, 3), 'slope': round(slope, 3), 'teamSeasons': len(ys)}
    print('desc', out, flush=True)
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


WTS = [(1,), (1, .5, .25), (1, .7, .5), (1, .8, .6)]          # Marcel weights: last season, the one before, ...
PRIORS = ['pl', 'pD', 'gpl']                                     # the shrink target: level, defence, goalies


def marcel(hist, k, keys):
    """weighted per-60 rates over the seasons in hist [(weight, row or None)], shrunk toward 0 with k seconds of
    pseudo ice time; and the shrink share k / (weighted ice time + k), which carries the learned shrink target"""
    hist = [(w, p) for w, p in hist if p]
    wt = sum(w * p['toi'] for w, p in hist)
    return {c: sum(w * p['toi'] * p[c] for w, p in hist) / (wt + k) for c in keys}, k / (wt + k)


def history(pid, idx, S, wts):
    """a player's rows in the seasons before S, most recent first, with their Marcel weights"""
    return [(w, idx.get(S - 1 - j, {}).get(pid)) for j, w in enumerate(wts)]


def fit():
    import numpy as np
    seasons = list(range(FIRST - 1, D.current_season()))
    sk = {S: skaters(S) for S in seasons}
    gk = {S: goalies(S) for S in seasons}
    six = {S: {r['id']: r for r in sk[S]} for S in seasons}
    gix = {S: {r['id']: r for r in gk[S]} for S in seasons}
    res = {S: team_results(S) for S in seasons}
    names = COMPS + ['gsax'] + PRIORS
    print('seasons', len(seasons), flush=True)

    def design(K, KG, wts, norm=True, prior=True):
        """team-season rows: sum over this season's players of (ice time this season) x (projected rates from the
        seasons before: Marcel-weighted, shrunk toward a learned target by the shrink share), per game. norm: ice time
        as a share of the team's (5 skaters, 1 goalie a game), so time short-handed, in overtime or with the goalie
        pulled (trailing teams) doesn't leak this season's result into the inputs"""
        X, y, keys = [], [], []
        for S in range(FIRST + 1, D.current_season()):
            tt, tg = defaultdict(float), defaultdict(float)
            for r in sk[S]:
                tt[r['tm']] += r['toi']
            for r in gk[S]:
                tg[r['tm']] += r['toi']
            agg = defaultdict(lambda: np.zeros(len(names)))
            for r in sk[S]:
                if r['tm'] not in res[S]:
                    continue
                m, sh = marcel(history(r['id'], six, S, wts), K, COMPS)
                v = np.array([m[c] for c in COMPS] + [0.0] + ([sh, sh * (r['pos'] == 'D'), 0.0] if prior else [0.0] * 3))
                h = r['toi'] / tt[r['tm']] * 5 * res[S][r['tm']][2] if norm else r['toi'] / 3600
                agg[r['tm']] += v * h
            for r in gk[S]:
                if r['tm'] not in res[S]:
                    continue
                m, sh = marcel(history(r['id'], gix, S, wts), KG, ['gsax60'])
                h = r['toi'] / tg[r['tm']] * res[S][r['tm']][2] if norm else r['toi'] / 3600
                agg[r['tm']][len(COMPS)] += m['gsax60'] * h
                if prior:
                    agg[r['tm']][-1] += sh * h
            for t, v in agg.items():
                gdpg, ppg, gp = res[S][t]
                X.append(v / gp); y.append(gdpg); keys.append((S, t))
        return np.array(X), np.array(y), keys

    def loso_of(X, y, S_, cols, lam):
        pred = np.zeros(len(y))
        for s in sorted(set(S_)):
            tr, te = S_ != s, S_ == s
            A = np.column_stack([X[tr][:, cols], np.ones(tr.sum())])
            R = lam * np.eye(A.shape[1]); R[-1, -1] = 0
            b = np.linalg.solve(A.T @ A + R, A.T @ y[tr])
            pred[te] = np.column_stack([X[te][:, cols], np.ones(te.sum())]) @ b
        return pred

    allc = list(range(len(names)))
    best = None
    for wts in WTS:
        for K in (3600 * 5, 3600 * 10, 3600 * 20, 3600 * 40):
            for KG in (3600 * 50, 3600 * 100, 3600 * 200, 3600 * 400, 3600 * 800):
                X, y, keys = design(K, KG, wts)
                S_ = np.array([k[0] for k in keys])
                for lam in (0.3, 1.0, 3.0, 10.0):
                    mse = float(((loso_of(X, y, S_, allc, lam) - y) ** 2).mean())
                    if best is None or mse < best[0]:
                        best = (mse, K, KG, wts, lam)
    mse, K, KG, wts, lam = best
    X, y, keys = design(K, KG, wts)
    S_ = np.array([k[0] for k in keys])
    base = float(((y - y.mean()) ** 2).mean())
    loso = lambda cols: loso_of(X, y, S_, cols, lam)
    full = loso(allc)
    e_full = (full - y) ** 2
    ev = {}
    for j, nm in enumerate(names):
        p = loso([c for c in allc if c != j])
        d = (p - y) ** 2 - e_full
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
        ev[nm] = {'dMse': round(float(d.mean()), 5), 't': round(t, 2)}
        print(nm, ev[nm], flush=True)
    # forward selection from the core (on-ice xG both ways, goalies, the shrink target): add the component that lowers
    # held-out error most while its paired t is 1.5 or more; drop-one alone would throw out both of a correlated pair
    keep = [names.index(c) for c in ('evf', 'eva', 'gsax', 'pl', 'pD', 'gpl')]
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
    # the gate: against the Oct 24 projection (last season only, shrunk to league average, raw ice time), paired by
    # team-season and by season
    Xo, _, _ = design(18000, 36000, (1,), norm=False, prior=False)
    po = loso_of(Xo, y, S_, [names.index(c) for c in ('evf', 'eva', 'gsax', 'a1', 'pk', 'ixg')], 10.0)
    d = (po - y) ** 2 - (pk - y) ** 2
    won = sum(1 for s in set(S_) if d[S_ == s].sum() > 0)
    gate = {'r2Old': round(1 - float(((po - y) ** 2).mean()) / base, 3), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
            'seasonsWon': won, 'seasons': len(set(S_))}
    print('gate', gate, flush=True)
    # baselines for the page: last season's points alone, on-ice xG alone
    pts_only = loso([names.index('g'), names.index('a1'), names.index('a2')])
    xg_only = loso([names.index('evf'), names.index('eva')])
    # goals a win: team points a game against goal differential a game
    gd = np.array([res[k[0]][k[1]][0] for k in keys]); ppg = np.array([res[k[0]][k[1]][1] for k in keys])
    slope = float(np.polyfit(gd, ppg, 1)[0])            # points a game per goal a game
    gpw = 2 / slope                                     # a win = 2 points
    out = {'updated': dt.date.today().isoformat(), 'K': K, 'KG': KG, 'wts': list(wts), 'lam': lam, 'w': w, 'evidence': ev,
           'steps': steps, 'teamSeasons': len(y), 'r2': round(r2, 3), 'gate': gate,
           'r2Points': round(1 - float(((pts_only - y) ** 2).mean()) / base, 3),
           'r2OnIceXg': round(1 - float(((xg_only - y) ** 2).mean()) / base, 3), 'goalsPerWin': round(gpw, 2),
           'desc': fit_desc()}
    print(out, flush=True)
    json.dump(out, open(FIT, 'w'), indent=1)


def rate(r, hist, fitd):
    """HPM, projected goals a 60 over an average player (before centring): the Marcel rates of this season and the
    ones before, weighted, plus the shrink target's share; offense and defense parts of the components"""
    w = fitd['w']
    if r['pos'] == 'G':
        m, sh = marcel(hist, fitd['KG'], ['gsax60'])
        return m['gsax60'] * w.get('gsax', 1.0) + w.get('gpl', 0) * sh, 0.0, 0.0
    m, sh = marcel(hist, fitd['K'], COMPS)
    o = sum(w.get(c, 0) * m[c] for c in ('evf', 'g', 'ixg', 'a1', 'a2', 'pp', 'pen'))
    d = sum(w.get(c, 0) * m[c] for c in ('eva', 'pk'))
    return o + d + (w.get('pl', 0) + w.get('pD', 0) * (r['pos'] == 'D')) * sh, o, d


def season_table(S, fitd, bio):
    sk, gk = skaters(S), goalies(S)
    rows = sk + gk
    wts = fitd.get('wts', [1])
    six = {S - j: {r['id']: r for r in (sk if j == 0 else skaters(S - j))} for j in range(len(wts))}
    gix = {S - j: {r['id']: r for r in (gk if j == 0 else goalies(S - j))} for j in range(len(wts))}
    for r in rows:
        r['hpm'], r['o'], r['d'] = rate(r, history(r['id'], gix if r['pos'] == 'G' else six, S + 1, wts), fitd)
    # centre HPM on the average skater / goalie, ice-time weighted
    for grp in (sk, gk):
        tt = sum(r['toi'] for r in grp)
        m = sum(r['hpm'] * r['toi'] for r in grp) / tt if tt else 0.0
        for r in grp:
            r['hpm'] -= m
    de = fitd['desc']
    pv = de['penValue'].get(str(S)) or de['penValue'][max(de['penValue'], key=int)]
    describe(S, sk, gk, pv)
    # pWAR's replacement (repl, HPM): skaters outside each team's top 13 forwards / 7 defencemen by ice time; goalies
    # outside the top 2. WAR's replacement: the same players' descriptive rate, pooled over every season
    repl = {}
    for pos, top in (('F', 13), ('D', 7), ('G', 2)):
        rest = depth_rest(rows, pos, top)
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
        h = r['toi'] / 3600
        war = (r['dr'] - de['repl'][r['pos']]) * h / gpw
        pwar = (r['hpm'] - repl[r['pos']]) * h / gpw
        out.append({'id': r['id'], 'n': r['n'], 'tm': r['tm'], 'pos': r['p'], 'grp': r['pos'], 'age': age, 'gp': r['gp'],
                    'toi': round(r['toi'] / 60), 'war': round(war, 2), 'gar': round((r['dr'] - de['repl'][r['pos']]) * h, 1),
                    'go': round(r['do'] * h, 1), 'gd': round(r['dd'] * h, 1),
                    'pwar': round(pwar, 2), 'hpm': round(r['hpm'], 3), 'o': round(r['o'], 3), 'd': round(r['d'], 3),
                    'pts': int(r.get('pts', 0)) if r['pos'] != 'G' else None,
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
                   'repl': {k: round(v, 3) for k, v in repl.items()}, 'replWar': fitd['desc']['repl'], 'players': rows},
                  open(os.path.join(OUTD, f'{S}.json'), 'w'), separators=(',', ':'))
        have[S] = {'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'n': len(rows), 'games': gmax, 'asof': asof}
        print(S, len(rows), 'top', rows[0]['n'], rows[0]['war'], flush=True)
    idx = {'current': max(have), 'seasons': sorted(have.values(), key=lambda s: -s['season']), 'w': fitd['w'],
           'goalsPerWin': fitd['goalsPerWin'], 'r2': fitd['r2'], 'r2Points': fitd['r2Points'], 'r2OnIceXg': fitd['r2OnIceXg'],
           'teamSeasons': fitd['teamSeasons'], 'r2Same': fitd['desc']['r2Same'], 'repl': fitd['desc']['repl']}
    json.dump(idx, open(IDX, 'w'), indent=1)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    elif '--current' in sys.argv:
        build([D.current_season()])
    else:
        build()
