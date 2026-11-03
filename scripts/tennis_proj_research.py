#!/usr/bin/env python3
"""Research + fit (Nov 3 2026): a forward projection for the tennis ARK Ranking (scripts/tennis_model.py): each
player's Elo and ARK 12 / 24 / 36 months ahead.

    python3 scripts/tennis_proj_research.py [--refresh]    # numpy; writes data/tennis_proj_fit.json

Needs scripts/.cache/tennis/hist.json.gz + players.json.gz (python3 scripts/tennis_data.py, or rebuilt from the
/mnt/project-files/tennis export). The snapshots are cached in scripts/.cache/tennis/proj_snaps.pkl.

Snapshots: the end of every quarter 2006-25 (Mar / Jun / Sep / Dec), one pass with the live parameters
(data/tennis_fit.json), each tour's board universe (15+ matches, one in the last 183 days), each row read the way
build() reads it: overall Elo, ARK (the blend's win chance against the average top-50 player by Elo over the last-52-week
tour-level surface mix; games rating against 0, like the live build), age from the bios, career matches (every level),
matches in the last 52 weeks, the official rank on the player's last match before the snapshot (unranked = none).
Target: the same player's logit ARK (and Elo over the tour's top-50 mean, since the Elo pool's level drifts) h = 12 / 24
/ 36 months later; rows = the top 300 by ARK at the snapshot (the page shows 200) still on the board h months on
(survivors only). Nothing after the snapshot enters a row.
Forms, fit per tour, leave one snapshot YEAR out (all four quarters of a year held out together), 6 tried (round 1, 5
forms on every active player and raw Elo, is in ROUND1 below):
    flat    the current rating held flat (Elo, or logit ARK)
    flatCA  flat + the live match model's age term CA x (age - 26) / 5 (logit; for Elo converted at the blend's
            logit-per-Elo slope k, fit on the snapshots)
    elo     c0 + c1 x (regression to the mean only)
    age     elo + (age - 26) / 5 + ((age - 26) / 5) ** 2
    proj    age + ln(1 + matches last 52 weeks) + ln(1 + career matches) + ln(rank) + unranked
    projX   proj + x (age - 26) / 5
Scores: held-out RMSE, paired t of squared error vs the baseline with PLAYERS as units (a player's rows averaged),
years won, held-out calibration slope (target on prediction). Kept: the simplest form that beats the best of flat /
flatCA with t <= -2, wins most years and slope .8-1.2; a richer form replaces it only if it beats it the same way
and has the lower RMSE.
Results (Nov 3 2026), logit ARK RMSE flatCA -> proj, t by player, years won:
    ATP 12 mo .477 -> .462 (t -18.8, 15/19), 24 mo .598 -> .567 (-14.4, 18/18), 36 mo .700 -> .645 (-11.7, 17/17)
    WTA 12 mo .509 -> .500 (t -16.0, 11/19), 24 mo .645 -> .629 (-7.3, 12/18), 36 mo .741 -> .717 (-3.6, 15/17)
    Elo (over top-50 mean) 12 mo ATP 90.6 -> 84.9 (t -15.8, 14/19), WTA flat 98.2 -> 94.6 (-13.6, 15/19); slopes .99-1.0
    age alone barely beats elo (regression to the mean) at 12 mo (ATP t -.1, WTA +3.4: fails); volume + rank carry it
    (proj vs age t -11.2 ATP, -5.3 WTA). projX: RMSE no better, years 10/19: not kept. Kept: proj, every tour / horizon.
"""
import gzip
import json
import math
import os
import pickle
import sys
from collections import defaultdict, deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tennis_model as TM  # noqa: E402

CACHE = os.path.join(HERE, '.cache', 'tennis')
PK = os.path.join(CACHE, 'proj_snaps.pkl')
OUT = os.path.join(ROOT, 'data', 'tennis_proj_fit.json')
HS = (12, 24, 36)
FORMS = ('flat', 'flatCA', 'elo', 'age', 'proj')
Y0, Y1 = 2006, 2025


def snaps():
    with gzip.open(os.path.join(CACHE, 'hist.json.gz'), 'rt') as fh:
        rows = json.load(fh)['rows']
    with gzip.open(os.path.join(CACHE, 'players.json.gz'), 'rt') as fh:
        players = json.load(fh)
    P = dict(TM.DEFAULT, **json.load(open(TM.FIT)).get('params', {}))
    m = TM.Model(P)
    m.set_bios(players)
    dates = [y * 10000 + md for y in range(Y0, Y1 + 1) for md in (331, 630, 930, 1231)]
    out = []
    mixq = deque()                      # (date, tour, surface) of tour-level main-draw matches
    days = defaultdict(deque)           # pid -> match dates (last 52 weeks)
    lrank = {}                          # pid -> official rank at the last match
    di = 0

    def snap(d):
        day = (TM.ymd(d) - TM.DAY0).days
        lo = d - 10000
        while mixq and mixq[0][0] < lo:
            mixq.popleft()
        for tour in ('atp', 'wta'):
            act = [p for p, x in m.last.items() if p[0] == tour[0] and day - x <= 183 and m.nm.get(p, 0) >= 15]
            if len(act) < 60:
                continue
            c = {s: 0 for s in TM.SURFS}
            for _, t_, s in mixq:
                if t_ == tour: c[s] += 1
            tt = sum(c.values()) or 1
            mix = {s: c[s] / tt for s in TM.SURFS}
            top = sorted(act, key=lambda p: -m.elo[p][0])[:50]
            ref = 'REF' + tour
            m.elo[ref] = [sum(m.elo[p][0] for p in top) / 50, 999, {s: [sum(m.elo[p][2][s][0] for p in top) / 50, 999] for s in TM.SURFS}]
            m.pt[ref] = [sum(m._pt(p, day)[0] for p in top) / 50, 0.0, sum(m._pt(p, day)[2] for p in top) / 50, 0.0, day]
            for p in act:
                ark = sum(mix[s] * m.predict(p, ref, tour, s, day, 3, match=False)[0] for s in TM.SURFS)
                q = days[p]
                while q and q[0] < lo:
                    q.popleft()
                age = (day - m.born[p]) / 365.25 if p in m.born else None
                out.append((p, tour, d, m.elo[p][0], ark, m.elo[ref][0], age, m.nm.get(p, 0), len(q), lrank.get(p)))
            for d_ in (m.elo, m.pt, m.gr):
                d_.pop(ref, None)

    for r in rows:
        while di < len(dates) and r[0] > dates[di]:
            snap(dates[di])
            di += 1
        if di >= len(dates):
            break
        if r[2] in TM.TOUR_LV and not r[4].startswith('Q'):
            mixq.append((r[0], r[1], r[3]))
        for p, rk in ((r[7], r[12]), (r[8], r[13])):
            days[p].append(r[0])
            lrank[p] = int(rk) if rk else None
        m.update(r)
    while di < len(dates) and rows[-1][0] > dates[di]:
        snap(dates[di])
        di += 1
    return out


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def addm(d, mo):
    y, md = divmod(d, 10000)
    return (y + mo // 12) * 10000 + md



def design(form, A):
    one = np.ones(len(A['x']))
    a = (A['age'] - 26) / 5
    base = [A['x'], a, a ** 2]
    vol = [np.log1p(A['n52']), np.log1p(A['nm']), A['lrk'], A['unr']]
    c = {'elo': [A['x']], 'age': base, 'proj': base + vol, 'projX': base + vol + [A['x'] * a]}[form]
    return np.column_stack([one] + c)


def evaluate(A, y, k_ca, forms):
    """held-out predictions per form (leave one snapshot year out)"""
    yr = A['d'] // 10000
    pr = {'flat': A['x'].copy(), 'flatCA': A['x'] + k_ca * (A['age'] - 26) / 5}
    for f in forms:
        if f in pr:
            continue
        p = np.zeros(len(y))
        X = design(f, A)
        for Y in np.unique(yr):
            te = yr == Y
            b = np.linalg.lstsq(X[~te], y[~te], rcond=None)[0]
            p[te] = X[te] @ b
        pr[f] = p
    return pr, yr


def paired(e1, e0, pid):
    """t of mean(e1 - e0) with players as units"""
    g = defaultdict(list)
    for v, p in zip(e1 - e0, pid):
        g[p].append(v)
    d = np.array([np.mean(v) for v in g.values()])
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), len(d)


def block(R, tgt, kslope, CA, forms, pairs):
    A = {'pid': np.array([s[0] for s, _ in R]), 'd': np.array([s[2] for s, _ in R]),
         'age': np.array([s[6] for s, _ in R], float), 'nm': np.array([s[7] for s, _ in R], float),
         'n52': np.array([s[8] for s, _ in R], float),
         'lrk': np.array([math.log(s[9]) if s[9] else math.log(1500) for s, _ in R]),
         'unr': np.array([0.0 if s[9] else 1.0 for s, _ in R])}
    if tgt == 'elo':           # Elo over the tour's top-50 mean at each date (the Elo pool's level drifts)
        A['x'] = np.array([s[3] - s[5] for s, _ in R])
        y = np.array([t[3] - t[5] for _, t in R])
        k_ca = CA / kslope
    else:
        A['x'] = np.array([logit(s[4]) for s, _ in R])
        y = np.array([logit(t[4]) for _, t in R])
        k_ca = CA
    pr, yr = evaluate(A, y, k_ca, forms)
    e = {f: (pr[f] - y) ** 2 for f in forms}
    o = {'rmse': {f: round(float(np.sqrt(e[f].mean())), 4) for f in forms}}
    base = min(('flat', 'flatCA'), key=lambda f: e[f].mean())
    o['baseline'] = base
    o['vs'] = {}
    for f, g in pairs:
        g = base if g == 'base' else g
        t, npl = paired(e[f], e[g], A['pid'])
        yrs = [int(np.mean(e[f][yr == Y]) < np.mean(e[g][yr == Y])) for Y in np.unique(yr)]
        o['vs'][f'{f}-{g}'] = {'t': round(t, 2), 'yearsWon': [sum(yrs), len(yrs)], 'players': npl}
    o['slope'] = {f: round(float(np.polyfit(pr[f], y, 1)[0]), 3) for f in forms}
    for f in forms:
        if f not in ('flat', 'flatCA'):
            o.setdefault('c', {})[f] = [round(float(v), 5) for v in np.linalg.lstsq(design(f, A), y, rcond=None)[0]]
    return o


def main():
    if os.path.exists(PK) and '--refresh' not in sys.argv:
        S = pickle.load(open(PK, 'rb'))
    else:
        S = snaps()
        pickle.dump(S, open(PK, 'wb'))
    print('snapshot rows', len(S), flush=True)
    P = json.load(open(TM.FIT))['params']
    CA = P['CA']
    by = {(s[0], s[2]): s for s in S}
    res = {'snapshots': f'quarter ends {Y0}-{Y1}', 'n': len(S), 'CA': round(CA, 4), 'note': __doc__.split('Forms')[0].strip(),
           'round1': ROUND1, 'tours': {}}
    forms = ('flat', 'flatCA', 'elo', 'age', 'proj', 'projX')
    pairs = (('elo', 'base'), ('age', 'base'), ('proj', 'base'), ('projX', 'base'), ('age', 'elo'), ('proj', 'age'), ('projX', 'proj'))
    for tour in ('atp', 'wta'):
        St = [s for s in S if s[1] == tour]
        ex = np.array([s[3] - s[5] for s in St])
        lx = np.array([logit(s[4]) for s in St])
        kslope = float(np.polyfit(ex, lx, 1)[0])
        rk = {}
        for d in sorted(set(s[2] for s in St)):
            ss = sorted([s for s in St if s[2] == d], key=lambda s: -s[4])
            rk.update({(s[0], d): i + 1 for i, s in enumerate(ss)})
        res['tours'][tour] = {'logitArkPerElo': round(kslope, 5), 'h': {}}
        for h in HS:
            # the board universe: top 300 by ARK at the snapshot (the page shows 200), still on the board h months on
            R = [(s, by.get((s[0], addm(s[2], h)))) for s in St if s[6] is not None and rk[(s[0], s[2])] <= TOPN]
            R = [(s, t) for s, t in R if t is not None]
            out = {'n': len(R), 'players': len({s[0] for s, _ in R}), 'years': [min(s[2] for s, _ in R) // 10000, max(s[2] for s, _ in R) // 10000]}
            for tgt in ('elo', 'ark'):
                o = block(R, tgt, kslope, CA, forms, pairs)
                out[tgt] = o
                print(tour, h, tgt, o['rmse'], o['baseline'], {k: (v['t'], v['yearsWon']) for k, v in o['vs'].items()}, o['slope'], flush=True)
            res['tours'][tour]['h'][str(h)] = out
    # kept: per tour and horizon, the ARK target (the board's headline); the simplest of elo / age / proj / projX that
    # beats the baseline with t <= -2 and most years won, a richer one only if it also beats the simpler one so (and RMSE)
    res['keep'] = {}
    for tour, tv in res['tours'].items():
        for h, o in tv['h'].items():
            for tgt in ('ark', 'elo'):
                v = o[tgt]['vs']
                ok = lambda k: v[k]['t'] <= -2 and v[k]['yearsWon'][0] * 2 > v[k]['yearsWon'][1]
                kept = None
                for f, step in (('elo', None), ('age', 'age-elo'), ('proj', 'proj-age'), ('projX', 'projX-proj')):
                    if ok(f'{f}-{o[tgt]["baseline"]}') and 0.8 <= o[tgt]['slope'][f] <= 1.2 and (kept is None or (ok(step) and o[tgt]["rmse"][f] < o[tgt]["rmse"][kept])):
                        kept = f
                res['keep'].setdefault(tour, {}).setdefault(h, {})[tgt] = kept
    print(json.dumps(res['keep']))
    json.dump(res, open(OUT, 'w'), indent=1, allow_nan=False)


TOPN = 300
# round 1 (Nov 3, same snapshots): every active player on the board (not only the top 300), Elo on its own scale (not
# over the top-50 mean), forms flat / flatCA / elo / age / proj. The pooled line mis-fits the tails: fitted forms won
# RMSE but lost the player-unit paired t to flatCA (ATP Elo 12m proj t +5.2; WTA ARK 12m proj vs flat +3.1); ATP ARK
# passed (proj vs flatCA t -11.5, 18/19 years). Replaced by the board-universe / relative-Elo round below.
ROUND1 = {'universe': 'every active player', 'atp': {'ark12': {'rmse': {'flat': .5611, 'flatCA': .5501, 'proj': .5395}, 'tProjVsFlatCA': -11.51, 'years': '18/19'},
                                                     'elo12': {'rmse': {'flat': 98.83, 'flatCA': 95.31, 'proj': 93.05}, 'tProjVsFlatCA': 5.22, 'years': '19/19'}},
          'wta': {'ark12': {'rmse': {'flat': .5162, 'flatCA': .5173, 'proj': .5115}, 'tProjVsFlat': 3.12, 'years': '16/19'},
                  'elo12': {'rmse': {'flat': 99.17, 'flatCA': 96.14, 'proj': 95.30}, 'tProjVsFlatCA': 7.99, 'years': '18/19'}}}


if __name__ == '__main__':
    main()
