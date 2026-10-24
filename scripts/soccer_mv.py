#!/usr/bin/env python3
"""Soccer players' estimated market value (xMV) for the Player value tab: what a big-five player should be worth on
Transfermarkt from what he has done, next to the value Transfermarkt shows and the gap between them.

    python3 scripts/soccer_mv.py --link   # Understat player -> Transfermarkt player (needs the dump), frozen
    python3 scripts/soccer_mv.py --fit    # snapshots 2015-26, fit + leave-one-season-out backtest, all seasons written
    python3 scripts/soccer_mv.py          # this season (live): Transfermarkt profiles, xMV at the fitted weights

xMV is a log-linear fit of Transfermarkt's value on the day of the snapshot, from inputs known that day only: GAR
(scripts/soccer_players.py) this season to date and the last two seasons, minutes, age, position, league and the
club's strength. No market input goes in (no past value, fee or contract), so the gap is the market's premium or
discount on the production. One fit per snapshot of the season (Sep 15, Oct 24, Jan 15, Apr 1, Jul 1); the live
page uses the nearest. The value shown is the mean: the log prediction maps to the average value of players with that
held-out prediction (a rising calibration, so the market's ceiling at the top and its floor at the bottom are kept).

Data: the Transfermarkt dump (dcaribou/transfermarkt-datasets, scripts/.cache/soccer_prospects/dump: valuations to Jul
2026, appearances for the club match), Transfermarkt's public API for this season's values and birth dates
(tmapi-alpha, cached in scripts/.cache/soccer_prospects/tm/players.json.gz with the soccer prospects board).
"""
import datetime as dt
import gzip
import json
import math
import os
import sys
from collections import defaultdict, Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as NM
import soccer_data as D
import soccer_players as SP

ROOT = os.path.dirname(HERE)
DUMPD = os.path.join(HERE, '.cache', 'soccer_prospects', 'dump')
TMC = os.path.join(HERE, '.cache', 'soccer_prospects', 'tm')
LINK = os.path.join(HERE, 'data', 'soccer_mv_link.json.gz')
FIT = os.path.join(ROOT, 'data', 'soccer_mv_fit.json')
SNAP = os.path.join(HERE, '.cache', 'soccer', 'mv_snaps.json.gz')
HIST = os.path.join(HERE, 'data', 'soccer_mv_hist.json.gz')
TMLG = {'eng.1': 'GB1', 'esp.1': 'ES1', 'ger.1': 'L1', 'ita.1': 'IT1', 'fra.1': 'FR1'}
SNAPS = [(9, 15), (10, 24), (1, 15), (4, 1), (7, 1)]      # month, day; Jul 1 = the season just finished
FIRST, LAST = 2015, 2026


def rd(name):
    import pandas as pd
    return pd.read_csv(os.path.join(DUMPD, name + '.csv.gz'))


def snapdate(S, md):
    """the snapshot day of season S (S = end year): Sep/Oct in S-1, Jan-Jul in S"""
    m, d = md
    return dt.date(S - 1 if m >= 8 else S, m, d)


# ---------------------------------------------------------------- link
def link():
    """Understat player id -> Transfermarkt player id, through each club-season's league appearances in the dump: a
    club is the Transfermarkt club in that league-season sharing the most names; a player is the one name match in
    that club (shared matcher, scripts/names.py)"""
    import pandas as pd
    rows = D.load(SP.ROWS)
    ap = rd('appearances')[['player_id', 'player_club_id', 'date', 'competition_id', 'minutes_played']]
    ap = ap[ap.competition_id.isin(TMLG.values())]
    ap['date'] = pd.to_datetime(ap.date)
    ap['S'] = ap.date.dt.year + (ap.date.dt.month >= 7).astype(int)
    pl = rd('players')[['player_id', 'name', 'date_of_birth', 'position']].set_index('player_id')
    tm = ap.groupby(['competition_id', 'S', 'player_club_id', 'player_id']).minutes_played.sum().reset_index()
    tm['name'] = tm.player_id.map(pl.name)
    roster = defaultdict(list)
    for r in tm.itertuples():
        roster[(r.competition_id, r.S, r.player_club_id)].append({'id': int(r.player_id), 'name': r.name, 'min': r.minutes_played})
    us = defaultdict(list)
    for r in rows:
        us[(r['lg'], r['S'], r['tid'])].append(r)
    out, club, miss = {}, {}, Counter()
    for (lg, S, tid), rs in us.items():
        cands = [(k, v) for k, v in roster.items() if k[0] == TMLG[lg] and k[1] == S]
        keys = {NM.key(r['n']) for r in rs}
        best = max(cands, key=lambda kv: sum(NM.key(x['name'] or '') in keys for x in kv[1]), default=None)
        if not best:
            continue
        club[f'{lg}|{S}|{tid}'] = int(best[0][2])
        M = NM.Matcher(best[1], name='name', team=None, pos=None)
        for r in rs:
            if r['p'] in out:
                continue
            row, how = M.find(r['n'], cross_team='variant')
            if row is None:
                # one roster player whose name words hold all of his, or his all of theirs (Mario / Mario Gaspar,
                # Son Heung-Min / Heung-min Son), or with his surname, and league minutes within a third
                a = set(NM.key(r['n']).replace('-', ' ').split())
                c = []
                for x in best[1]:
                    b = set(NM.key(x['name'] or '').replace('-', ' ').split())
                    if a and b and (a <= b or b <= a or NM.key(r['n']).split()[-1] == NM.key(x['name'] or '').split()[-1]) and abs(x['min'] - r['min']) <= max(270, r['min'] / 3):
                        c.append(x)
                if len(c) == 1:
                    row = c[0]
            if row is None:
                miss[lg] += r['min']
                continue
            out[r['p']] = row['id']
    tot = Counter()
    for r in rows:
        tot[r['lg']] += r['min']
    got = Counter()
    for r in rows:
        if r['p'] in out:
            got[r['lg']] += r['min']
    print({lg: round(got[lg] / tot[lg], 3) for lg in tot}, len(out), 'linked')
    dob = {str(i): (str(pl.date_of_birth.get(i))[:10] if isinstance(pl.date_of_birth.get(i), str) else None) for i in set(out.values())}
    with gzip.open(LINK, 'wt') as f:
        json.dump({'note': 'Understat player id -> Transfermarkt player id (scripts/soccer_mv.py --link)', 'p': out,
                   'club': club, 'dob': dob}, f, separators=(',', ':'))


# ---------------------------------------------------------------- snapshots
def gar_rows(rows, F):
    """GAR on each row at the fitted weights (soccer_players.write)"""
    SP.prep(rows, F['shrink'])
    for r in rows:
        r['gar'] = (SP.value(r, F) - F['repl'][r['pos']]) * r['min'] / 90
    return rows


def team_form(S, before=None):
    """(league, Understat team id) -> [matches, goal difference, xG difference] before the day (whole season if None)"""
    out = {}
    for lg in D.BIG5:
        d = D.us_league(lg, S)
        for tid, t in ((d or {}).get('teams') or {}).items():
            h = [x for x in t['history'] if not before or (x.get('date') or '') < before]
            out[(lg, tid)] = [len(h), sum(int(x['scored']) - int(x['missed']) for x in h), sum(x['xG'] - x['xGA'] for x in h)]
    return out


def player_rows(S, md, F, full):
    """one row per player in season S at snapshot md (or the whole season): inputs known that day"""
    day = snapdate(S, md).isoformat()
    cur = gar_rows(SP.build_rows(S, S, before=day) if md != (7, 1) else [dict(r) for r in full.get(S, [])], F)
    tf, tf1 = team_form(S, day), team_form(S - 1)
    prev = {}
    for k in (1, 2):
        agg = defaultdict(lambda: [0.0, 0])
        for r in full.get(S - k, []):
            agg[r['p']][0] += r['gar']; agg[r['p']][1] += r['min']
        prev[k] = agg
    by = defaultdict(list)
    for r in cur:
        by[r['p']].append(r)
    out = []
    for p, rs in by.items():
        m = sum(r['min'] for r in rs)
        if m < 90:
            continue
        r = max(rs, key=lambda r: r['min'])
        n, gd, xgd = tf.get((r['lg'], r['tid']), [0, 0, 0.0])
        n1, gd1, xgd1 = tf1.get((r['lg'], r['tid']), [0, 0, 0.0])
        out.append({'p': p, 'n': r['n'], 'lg': r['lg'], 'tid': r['tid'], 'team': r['team'], 'pos': r['pos'],
                    'S': S, 'day': day, 'min': m, 'tmp': n, 'gar': sum(x['gar'] for x in rs),
                    'gar1': prev[1][p][0] if p in prev[1] else 0.0, 'min1': prev[1][p][1] if p in prev[1] else 0,
                    'gar2': prev[2][p][0] if p in prev[2] else 0.0, 'min2': prev[2][p][1] if p in prev[2] else 0,
                    'tgd': gd / n if n else 0.0, 'txgd': xgd / n if n else 0.0,
                    'tgd1': gd1 / n1 if n1 else None, 'txgd1': xgd1 / n1 if n1 else None})
    return out


def snaps():
    """every snapshot row 2015-26 with Transfermarkt's value that day and the player's birth date"""
    import pandas as pd
    F = json.load(open(SP.FIT))
    rows = D.load(SP.ROWS)
    gar_rows(rows, F)
    full = defaultdict(list)
    for r in rows:
        full[r['S']].append(r)
    L = D.load(LINK)
    v = rd('player_valuations')[['player_id', 'date', 'market_value_in_eur']]
    v['date'] = pd.to_datetime(v.date)
    val = {pid: (g.date.values, g.market_value_in_eur.values) for pid, g in v.sort_values('date').groupby('player_id')}
    out = []
    for S in range(FIRST, LAST + 1):
        for md in SNAPS:
            day = np.datetime64(snapdate(S, md))
            for r in player_rows(S, md, F, full):
                tm = L['p'].get(r['p'])
                if tm is None:
                    continue
                r['tm'], r['dob'] = tm, L['dob'].get(str(tm))
                if tm in val:
                    d, x = val[tm]
                    i = np.searchsorted(d, day, side='right') - 1
                    if i >= 0 and (day - d[i]).astype('timedelta64[D]').astype(int) <= 400:
                        r['mv'] = float(x[i])
                out.append(r)
            print(S, md, len(out), flush=True)
    with gzip.open(SNAP, 'wt') as f:
        json.dump(out, f)


# ---------------------------------------------------------------- the model
CANDS = ['a1', 'a2', 'a3', 'g0', 'g1', 'g2', 'g0r', 'g1r', 'gg0', 'gg1', 'ag0', 'ag1', 's0', 's02', 'm1', 'm12', 'm2',
         'n1', 'as0', 'am1', 'tgd1', 'prom', 'tgd', 'txgd', 'lvl', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'GK', 'D', 'F']
NAMES = {'a1': 'age (26 = 0)', 'a2': 'age squared', 'a3': 'age cubed / 10', 'g0': 'GAR this season, per 38 team matches',
         'g1': 'GAR last season', 'g2': 'GAR two seasons ago', 'g0r': 'root of positive GAR this season (to date)',
         'g1r': 'root of positive GAR last season', 'gg0': 'positive GAR this season squared / 10',
         'gg1': 'positive GAR last season squared / 10', 'ag0': 'age x GAR this season', 'ag1': 'age x GAR last season',
         's0': "share of the team's minutes this season", 's02': 'that share squared',
         'm1': 'big-five minutes last season / 3420', 'm12': 'that squared', 'm2': 'minutes two seasons ago / 3420',
         'n1': 'not in the big five last season', 'as0': 'age x minutes share', 'am1': 'age x last-season minutes',
         'tgd1': "club's goal difference a match last season", 'prom': 'club promoted (no big-five season last year)',
         'tgd': "club's goal difference a match this season (to date)", 'txgd': "club's xG difference a match this season",
         'lvl': "the league's mean log value this snapshot (the market's price level)",
         'esp.1': 'La Liga', 'ger.1': 'Bundesliga', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1', 'GK': 'keeper', 'D': 'defender',
         'F': 'forward'}


def feats(r):
    """the candidate inputs of one player row (age, lvl filled in)"""
    a, tm = r['age'] - 26, max(r['tmp'], 1)
    s0, m1 = r['min'] / (90 * tm), r['min1'] / 3420
    w = min(1, tm / 19)                                      # this season's GAR counts more as the season fills
    g0 = r['gar'] / tm * 38
    f = {'a1': a, 'a2': a * a, 'a3': a ** 3 / 10, 'g0': g0, 'g1': r['gar1'], 'g2': r['gar2'],
         'g0r': max(g0, 0) ** .5 * w, 'g1r': max(r['gar1'], 0) ** .5, 'gg0': max(g0, 0) ** 2 / 10 * w,
         'gg1': max(r['gar1'], 0) ** 2 / 10, 'ag0': a * g0, 'ag1': a * r['gar1'], 's0': s0, 's02': s0 * s0, 'm1': m1,
         'm12': m1 * m1, 'm2': r['min2'] / 3420, 'n1': float(r['min1'] == 0), 'as0': a * s0, 'am1': a * m1,
         'tgd1': r['tgd1'] if r['tgd1'] is not None else -0.6, 'prom': float(r['tgd1'] is None),
         'tgd': r['tgd'] * min(1, tm / 10), 'txgd': r['txgd'] * min(1, tm / 10), 'lvl': r['lvl']}
    for lg in ('esp.1', 'ger.1', 'ita.1', 'fra.1'):
        f[lg] = float(r['lg'] == lg)
    for p in ('GK', 'D', 'F'):
        f[p] = float(r['pos'] == p)
    return f


def age_of(day, dob):
    return (dt.date.fromisoformat(day[:10]) - dt.date.fromisoformat(dob[:10])).days / 365.25


def levels(rows):
    """lvl: the league's mean log value at the snapshot, leaving the player out"""
    tot = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r.get('mv'):
            t = tot[(r['lg'], r['day'])]; t[0] += math.log(r['mv']); t[1] += 1
    for r in rows:
        s, n = tot[(r['lg'], r['day'])]
        if r.get('mv') and n > 1:
            s, n = s - math.log(r['mv']), n - 1
        r['lvl'] = s / n if n else 13.5


LAM = 1.0


def solve(X, y, lam=LAM):
    A = X.T @ X + lam * np.eye(X.shape[1])
    A[0, 0] -= lam                                           # the constant is not shrunk
    return np.linalg.solve(A, X.T @ y)


def loso_pred(X, y, S):
    p = np.zeros(len(y))
    for s in np.unique(S):
        tr = S != s
        p[S == s] = X[S == s] @ solve(X[tr], y[tr])
    return p


def calibration(p, y, nbin=40):
    """the mean value (EUR, as log) at each held-out log prediction: quantile bins (the top 2% in finer ones), pooled
    adjacent violators so it rises, interpolated between bin centres and flat past the ends. A log fit is too convex
    at the top (the market's ceiling) and too low at the bottom; this keeps the mean right everywhere."""
    o = np.argsort(p)
    p, y = p[o], y[o]
    cuts = list(np.quantile(p, np.linspace(0, .98, nbin + 1))[:-1]) + list(np.quantile(p, [.98, .99, .995, .998])) + [p[-1] + 1e-9]
    xs, zs, ws = [], [], []
    for a, b in zip(cuts[:-1], cuts[1:]):
        m = (p >= a) & (p < b)
        if m.sum() >= 20:
            xs.append(float(p[m].mean())); zs.append(float(np.exp(y[m]).mean())); ws.append(int(m.sum()))
    blocks = []                                              # [x sum, value sum, weight] pooled
    for x, z, w in zip(xs, zs, ws):
        blocks.append([[x], z * w, w])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] > blocks[-1][1] / blocks[-1][2]:
            b = blocks.pop()
            blocks[-1][0] += b[0]; blocks[-1][1] += b[1]; blocks[-1][2] += b[2]
    kx, kz = [], []
    for xx, v, w in blocks:
        kx.append(round(float(np.mean(xx)), 4)); kz.append(round(math.log(v / w), 4))
    return [kx, kz]


def calibrate(lp, knots):
    return np.interp(lp, knots[0], knots[1])


def fit():
    """per snapshot: ridge on log value, the inputs chosen by leave-one-season-out error pooled over the snapshots
    (an input stays only if dropping it raises the error), then the gap test: does the held-out gap (xMV over the
    value) forecast the value's next move?"""
    rows = [r for r in D.load(SNAP) if r.get('dob')]
    for r in rows:
        r['age'] = age_of(r['day'], r['dob'])
    levels(rows)
    rows = [r for r in rows if r.get('mv') and 15 <= r['age'] <= 42]
    by = {md: [r for r in rows if r['day'][5:] == snapdate(2020, md).isoformat()[5:]] for md in SNAPS}
    mats = {}
    for md, rs in by.items():
        F = [feats(r) for r in rs]
        mats[md] = (np.array([[1.0] + [f[k] for k in CANDS] for f in F]), np.log([r['mv'] for r in rs]),
                    np.array([r['S'] for r in rs]))

    def err(keep):
        idx = [0] + [1 + CANDS.index(k) for k in keep]
        e = 0.0
        for X, y, S in mats.values():
            e += np.mean((y - loso_pred(X[:, idx], y, S)) ** 2)
        return e / len(mats)
    keep = list(CANDS)
    best = err(keep)
    base = err([])
    evidence = {}
    while True:
        trial = {k: err([x for x in keep if x != k]) for k in keep}
        k, e = min(trial.items(), key=lambda kv: kv[1])
        if e > best:
            break
        keep.remove(k); evidence[k] = {'dMse': round(best - e, 5), 'dropped': True}; best = e
        print('drop', k, round(e, 4), flush=True)
    for k in keep:
        evidence[k] = {'dMse': round(trial[k] - best, 5)}
    idx = [0] + [1 + CANDS.index(k) for k in keep]
    models, test, hist = {}, {}, defaultdict(dict)
    for md, rs in by.items():
        X, y, S = mats[md]
        X = X[:, idx]
        p = loso_pred(X, y, S)
        e = y - p
        b = solve(X, y)
        key = f'{md[0]:02d}-{md[1]:02d}'
        per = {}
        for s in np.unique(S):
            m = S == s
            per[int(s)] = round(float(1 - np.mean(e[m] ** 2) / np.var(y[m])), 3)
        models[key] = {'coef': dict(zip(['const'] + keep, [round(float(x), 5) for x in b])), 'var': round(float(np.var(e)), 4),
                       'n': int(len(y)), 'heldR2': round(float(1 - np.mean(e ** 2) / np.var(y)), 3),
                       'heldMAE': round(float(np.mean(np.abs(e))), 3), 'baseR2': None, 'bySeason': per}
        knots = calibration(p, y)
        pc = calibrate(p, knots)
        ec = y - pc
        models[key].update({'knots': knots, 'heldR2cal': round(float(1 - np.mean(ec ** 2) / np.var(y)), 3),
                            'sumRatio': round(float(np.exp(y).sum() / np.exp(pc).sum()), 3)})
        for r, pp in zip(rs, pc):
            r['_p'] = float(pp)
            r['_x'] = math.exp(pp)
        if md == (7, 1):
            for r in rs:
                hist[r['S']][r['p']] = [round(r['_x'] / 1e5) / 10, round(r['mv'] / 1e5) / 10]
    # age, league and position alone (no production), for scale
    simple = ['a1', 'a2', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'GK', 'D', 'F', 'lvl']
    sidx = [0] + [1 + CANDS.index(k) for k in simple]
    for md in by:
        X, y, S = mats[md]
        e = y - loso_pred(X[:, sidx], y, S)
        models[f'{md[0]:02d}-{md[1]:02d}']['baseR2'] = round(float(1 - np.mean(e ** 2) / np.var(y)), 3)
    # the gap test: gap = held-out log(xMV / value) at a snapshot; move = log(value at the season's end / value now)
    end = {(r['S'], r['p']): r['mv'] for r in by[(7, 1)]}
    for md in SNAPS[:-1] + [(7, 1)]:
        xs, ys, ss = [], [], []
        for r in by[md]:
            nxt = end.get((r['S'] + 1, r['p'])) if md == (7, 1) else end.get((r['S'], r['p']))
            if nxt:
                xs.append(r['_p'] - math.log(r['mv'])); ys.append(math.log(nxt / r['mv'])); ss.append(r['S'])
        xs, ys, ss = np.array(xs), np.array(ys), np.array(ss)
        X = np.c_[np.ones(len(xs)), xs]
        b = np.linalg.lstsq(X, ys, rcond=None)[0]
        slopes = []
        for s in np.unique(ss):
            m = ss == s
            if m.sum() > 50:
                slopes.append(np.linalg.lstsq(X[m], ys[m], rcond=None)[0][1])
        sl = np.array(slopes)
        q = np.quantile(xs, [.2, .8])
        test[f'{md[0]:02d}-{md[1]:02d}'] = {
            'n': int(len(xs)), 'slope': round(float(b[1]), 3),
            'seasonSlopes': [round(float(x), 3) for x in sl], 'tSeasons': round(float(sl.mean() / (sl.std(ddof=1) / len(sl) ** .5)), 1),
            'positive': f'{int((sl > 0).sum())}/{len(sl)}',
            'moveTopFifth': round(float(np.mean(ys[xs >= q[1]])), 3), 'moveBottomFifth': round(float(np.mean(ys[xs <= q[0]])), 3),
            'moveAll': round(float(np.mean(ys)), 3),
            'to': 'next season end' if md == (7, 1) else 'this season end'}
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'seasons': [FIRST, LAST],
           'lambda': LAM, 'feats': keep, 'names': {k: NAMES[k] for k in CANDS}, 'evidence': evidence,
           'pooledHeldMse': round(best, 4), 'models': models, 'gapTest': test}
    print(json.dumps({k: v for k, v in out.items() if k not in ('names',)}, indent=1))
    json.dump(out, open(FIT, 'w'), indent=1, allow_nan=False)
    with gzip.open(HIST, 'wt') as f:
        json.dump({'note': 'season -> Understat player id -> [held-out xMV, Transfermarkt value] at Jul 1, EUR m',
                   'h': {str(k): v for k, v in hist.items()}}, f, separators=(',', ':'))


# ---------------------------------------------------------------- live
TMAPI = 'https://tmapi-alpha.transfermarkt.technology'
PROF = os.path.join(TMC, 'players.json.gz')
SQUADS = os.path.join(HERE, '.cache', 'soccer', 'tm_squads.json.gz')
CUR = os.path.join(HERE, 'data', 'soccer_mv_cur.json.gz')


def tm(path):
    return D.get(TMAPI + path, tries=3, headers={'Accept': 'application/json'})


def profiles(ids, days=7):
    """Transfermarkt player profiles (name, birth date, value now), shared with the soccer prospects board's cache;
    refreshed after `days`"""
    import concurrent.futures as cf
    have = D.load(PROF) if os.path.exists(PROF) else {}
    today = dt.date.today().isoformat()
    lim = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    todo = [str(i) for i in ids if str(i) not in have or have[str(i)].get('_got', '') < lim]
    with cf.ThreadPoolExecutor(10) as ex:
        for i, r in zip(todo, ex.map(lambda i: tm(f'/player/{i}'), todo)):
            if r and r.get('data'):
                d = r['data']
                keep = {k: d.get(k) for k in ('name', 'lifeDates', 'attributes', 'marketValueDetails')}
                keep['_got'] = today
                have[i] = keep
    if todo:
        D.save(PROF, have)
    print('profiles', len(todo), 'fetched of', len(ids), flush=True)
    return have


def squads(clubs, season):
    """Transfermarkt squad ids of each club this season (a day's cache)"""
    import concurrent.futures as cf
    have = D.load(SQUADS) if os.path.exists(SQUADS) else {}
    if have.get('_day') != dt.date.today().isoformat() or have.get('_season') != season:
        have = {'_day': dt.date.today().isoformat(), '_season': season}
    todo = [c for c in clubs if str(c) not in have]
    with cf.ThreadPoolExecutor(8) as ex:
        for c, r in zip(todo, ex.map(lambda c: tm(f'/club/{c}/squad?season={season}'), todo)):
            if r and r.get('data'):
                have[str(c)] = [int(x['playerId']) for x in r['data'].get('squad') or []]
    D.save(SQUADS, have)
    return {int(k): v for k, v in have.items() if not k.startswith('_')}


def mv_now(d):
    return (((d or {}).get('marketValueDetails') or {}).get('current') or {}).get('value')


def predict(rows, F, day):
    """xMV (EUR) at the snapshot model nearest the day of the season"""
    doy = lambda d: (d - dt.date(d.year if d.month >= 7 else d.year - 1, 7, 1)).days
    t = doy(dt.date.fromisoformat(day))
    key = min(F['models'], key=lambda k: abs(doy(snapdate(2020, (int(k[:2]), int(k[3:])))) - t))
    m = F['models'][key]
    for r in rows:
        f = feats(r)
        lp = m['coef']['const'] + sum(m['coef'][k] * f[k] for k in F['feats'])
        r['xmv'] = math.exp(float(calibrate(lp, m['knots'])))
    return key


def current():
    """this season: every player on the Player value tab gets xMV, Transfermarkt's value now and the gap"""
    F = json.load(open(FIT))
    S = D.current_season()
    day = dt.date.today().isoformat()
    fn = os.path.join(SP.SDIR, f'{S}.json')
    J = json.load(open(fn))
    prev = {}
    for k in (1, 2):
        agg = defaultdict(lambda: [0.0, 0])
        try:
            for o in json.load(open(os.path.join(SP.SDIR, f'{S - k}.json')))['players']:
                agg[o['p']][0] += o['gar']; agg[o['p']][1] += o['min']
        except OSError:
            pass
        prev[k] = agg
    tid = {}
    for lg in D.BIG5:
        for t, x in ((D.us_league(lg, S) or {}).get('teams') or {}).items():
            tid[(lg, x['title'])] = t
    tf, tf1 = team_form(S, day), team_form(S - 1)
    L = D.load(LINK)
    link = dict(L['p'])
    club = {}
    for k, c in sorted(L['club'].items(), key=lambda kv: int(kv[0].split('|')[1])):
        lg, _, t = k.split('|')
        club[(lg, t)] = c                                   # the club's latest Transfermarkt id
    # players new to the big five: the one name match in his club's Transfermarkt squad
    old = D.load(CUR) if os.path.exists(CUR) else {}
    for p, i in (old.get('link') or {}).items():
        link.setdefault(p, i)
    need = [o for o in J['players'] if o['p'] not in link]
    # promoted clubs new to the big five since 2015: the Transfermarkt club in the league's fixtures whose squad
    # shares the most names with the Understat team
    for lg in D.BIG5:
        miss = {o['team'] for o in need if o['lg'] == lg and (lg, tid.get((lg, o['team']))) not in club}
        if not miss:
            continue
        fx = tm(f'/competition/{TMLG[lg]}/fixtures?season={S - 1}') or {}
        ids = {int(g[side]['clubId']) for f in ((fx.get('data') or {}).get('fixtures') or []) for g in f.get('games') or []
               for side in ('homeClub', 'awayClub') if (g.get(side) or {}).get('clubId')}
        free = sorted(ids - {c for (l, _), c in club.items() if l == lg and c in ids and
                             any(tid.get((lg, o['team'])) == _ for o in J['players'] if o['lg'] == lg)})
        sq0 = squads(free, S - 1)
        pr0 = profiles(sorted({i for c in sq0.values() for i in c}))
        for team in miss:
            keys = {NM.key(o['n']) for o in J['players'] if o['lg'] == lg and o['team'] == team}
            score = {c: sum(NM.key((pr0.get(str(i)) or {}).get('name') or '') in keys for i in v) for c, v in sq0.items()}
            c = max(score, key=score.get, default=None)
            if c is not None and score[c] >= 5:
                club[(lg, tid.get((lg, team)))] = c
    clubs = sorted({club[(o['lg'], tid.get((o['lg'], o['team'])))] for o in need if (o['lg'], tid.get((o['lg'], o['team']))) in club})
    sq = squads(clubs, S - 1) if clubs else {}
    prof = profiles(sorted({i for c in sq.values() for i in c} | {link[o['p']] for o in J['players'] if o['p'] in link}))
    new = {}
    for o in need:
        c = club.get((o['lg'], tid.get((o['lg'], o['team']))))
        ros = [{'id': i, 'name': (prof.get(str(i)) or {}).get('name')} for i in sq.get(c, [])]
        row, _ = NM.Matcher([x for x in ros if x['name']], name='name', team=None, pos=None).find(o['n'], cross_team='variant')
        if row is None:
            a = set(NM.key(o['n']).replace('-', ' ').split())
            c2 = [x for x in ros if x['name'] and a and (a <= set(NM.key(x['name']).replace('-', ' ').split()) or
                                                         set(NM.key(x['name']).replace('-', ' ').split()) <= a)]
            row = c2[0] if len(c2) == 1 else None
        if row:
            link[o['p']] = row['id']; new[o['p']] = row['id']
    rows = []
    for o in J['players']:
        i = link.get(o['p'])
        d = prof.get(str(i)) if i else None
        dob = ((d or {}).get('lifeDates') or {}).get('dateOfBirth') or (L['dob'].get(str(i)) if i else None)
        t = tid.get((o['lg'], o['team']))
        n, gd, xgd = tf.get((o['lg'], t), [0, 0, 0.0])
        n1, gd1, xgd1 = tf1.get((o['lg'], t), [0, 0, 0.0])
        if not dob or not n:
            continue
        r = {'p': o['p'], 'lg': o['lg'], 'pos': o['pos'], 'day': day, 'age': age_of(day, dob), 'min': o['min'], 'tmp': n,
             'gar': o['gar'], 'gar1': prev[1][o['p']][0] if o['p'] in prev[1] else 0.0,
             'min1': prev[1][o['p']][1] if o['p'] in prev[1] else 0, 'gar2': prev[2][o['p']][0] if o['p'] in prev[2] else 0.0,
             'min2': prev[2][o['p']][1] if o['p'] in prev[2] else 0, 'tgd': gd / n, 'txgd': xgd / n,
             'tgd1': gd1 / n1 if n1 else None, 'txgd1': None, 'mv': mv_now(d), 'tm': i}
        rows.append(r)
    levels(rows)
    key = predict(rows, F, day)
    cur = {r['p']: [round(r['xmv'] / 1e5) / 10, round(r['mv'] / 1e5) / 10 if r['mv'] else None, int(r['tm'])] for r in rows}
    D.save(CUR, {'season': S, 'asof': day, 'model': key, 'link': {**(old.get('link') or {}), **new}, 'v': cur})
    attach(S, J['players'])
    J['mv'] = mv_meta(F, key)
    open(fn, 'w').write(json.dumps(J, separators=(',', ':'), allow_nan=False))
    print(S, key, len(rows), 'valued of', len(J['players']), '| new links', len(new), flush=True)


def mv_meta(F, key):
    m = F['models'][key]
    g = F['gapTest'].get(key) or {}
    return {'model': key, 'heldR2': m['heldR2'], 'baseR2': m['baseR2'], 'gapSlope': g.get('slope'),
            'gapPos': g.get('positive')}


def attach(S, players):
    """xmv / mv (EUR m) on a season file's players: held-out end-of-season values for past seasons, today's for this
    one (called by soccer_players.write too, so a rebuild keeps them)"""
    try:
        if S == D.current_season():
            src = (D.load(CUR) or {}).get('v') or {}
        else:
            src = (D.load(HIST)['h']).get(str(S)) or {}
    except OSError:
        return
    for o in players:
        v = src.get(o['p'])
        if v:
            o['xmv'], o['mv'] = v[0], v[1]
            if v[1] is not None:
                o['gap'] = round(v[0] - v[1], 1)


def meta(S):
    """the season file's 'mv' block: which snapshot model and its backtest"""
    try:
        F = json.load(open(FIT))
        key = (D.load(CUR).get('model') or '10-24') if S == D.current_season() else '07-01'
        return mv_meta(F, key)
    except (OSError, KeyError):
        return None


def write_hist():
    """past season files: the held-out Jul 1 xMV next to Transfermarkt's Jul 1 value"""
    F = json.load(open(FIT))
    for S in range(FIRST, LAST + 1):
        fn = os.path.join(SP.SDIR, f'{S}.json')
        if not os.path.exists(fn):
            continue
        J = json.load(open(fn))
        attach(S, J['players'])
        J['mv'] = mv_meta(F, '07-01')
        open(fn, 'w').write(json.dumps(J, separators=(',', ':'), allow_nan=False))


if __name__ == '__main__':
    if '--link' in sys.argv:
        link()
    elif '--snaps' in sys.argv:
        snaps()
    elif '--fit' in sys.argv:
        fit()
        write_hist()
    else:
        current()
