#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""J1 (questionable play chance) and J2 (return timeline) of PREREG.md.

    python3 scripts/research/inj_nov14/nfl_avail.py        # writes data/inj_nov14_nfl.json (and the fitted tables)
"""
import csv
import datetime as dt
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import harness as H             # noqa: E402
import nfl_games as N           # noqa: E402
import nfl_inj_hazard as HZ     # noqa: E402
from logit_ridge import fit_ridge, predict, pick_lambda, logloss   # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'inj_nov14_nfl.json')
TUNE, HELD = range(2016, 2021), range(2021, 2026)
POSG = {'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'OT': 'OL', 'OG': 'OL', 'WR': 'WRTE', 'TE': 'WRTE', 'RB': 'RB', 'FB': 'RB',
        'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB',
        'CB': 'DB', 'S': 'DB', 'SS': 'DB', 'FS': 'DB', 'DB': 'DB', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
PRAC = ('dnp', 'limited', 'full', 'none')
MPART = 40.0


def season(y, games):
    """everything one season's tests read"""
    pfr = {r['gsis_id']: r['pfr_id'] for r in N.rows(N.get('players.csv', f'{N.REL}/players/players.csv')) if r.get('pfr_id')}
    snaps, pct = {}, {}
    tweeks = defaultdict(set)
    for r in N.rows(N.get(f'snap_counts_{y}.csv', f'{N.REL}/snap_counts/snap_counts_{y}.csv')):
        if r['game_type'] != 'REG':
            continue
        w = int(r['week'])
        tweeks[N.team(r['team'])].add(w)
        if int(float(r['offense_snaps'] or 0)) + int(float(r['defense_snaps'] or 0)) + int(float(r['st_snaps'] or 0)) > 0:
            snaps[(w, r['pfr_player_id'])] = True
            pct[(w, r['pfr_player_id'])] = max(float(r['offense_pct'] or 0), float(r['defense_pct'] or 0))
    day = {}
    for g in games:
        if int(g['season']) == y and g['game_type'] == 'REG':
            for s in ('home', 'away'):
                day[(N.team(g[f'{s}_team']), int(g['week']))] = dt.date.fromisoformat(g['gameday'])
    inj = [r for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')) if r.get('game_type', 'REG') == 'REG']
    return pfr, snaps, pct, tweeks, day, inj


def j1_rows(games):
    rows = []
    for y in list(TUNE) + list(HELD):
        pfr, snaps, pct, tweeks, day, inj = season(y, games)
        listed = defaultdict(dict)
        for r in inj:
            if r['report_status']:
                listed[(N.team(r['team']), int(r['week']))][r['gsis_id']] = r['report_status']
        nq = {k: sum(1 for s in v.values() if s == 'Questionable') for k, v in listed.items()}
        tq = defaultdict(lambda: [0, 0])      # (team, week) -> [played, listed] questionables, for the club's earlier share
        tmp = []
        for r in inj:
            if r['report_status'] != 'Questionable' or r['position'] == 'QB':
                continue
            p = pfr.get(r['gsis_id']); w = int(r['week']); t = N.team(r['team'])
            if not p or (t, w) not in day:
                continue
            prior = sorted(x for x in tweeks.get(t, ()) if x < w)
            pw = prior[-1] if prior else None
            miss = 0
            for x in reversed(prior):
                if snaps.get((x, p)):
                    break
                miss += 1
            if not any(snaps.get((x, p)) for x in prior):
                miss = min(miss, 1) if prior else 0     # no game yet this season: not a known absence run
                if prior and miss:
                    miss = 1
            recent = pw is None or bool(snaps.get((pw, p)))
            lw = listed.get((t, pw), {}).get(r['gsis_id']) if pw else None
            last = ('none' if not lw else ('qplay' if snaps.get((pw, p)) else 'qsat') if lw == 'Questionable' else 'dout')
            lastp = [pct[(x, p)] for x in reversed(prior) if (x, p) in pct][:4]
            played = float(bool(snaps.get((w, p))))
            tq[(t, w)][0] += played; tq[(t, w)][1] += 1
            tmp.append({'y': y, 'w': w, 't': t, 'played': played, 'prac': N.practice_of(r['practice_status']) or 'none',
                        'recent': recent, 'pos': POSG.get(r['position'], 'other'), 'part': HZ.part_of(r['report_primary_injury']),
                        'last': last, 'miss': min(miss, 2), 'short': float(pw is not None and (day[(t, w)] - day[(t, pw)]).days <= 5),
                        'share': float(np.mean(lastp)) if lastp else 0.0, 'noshare': float(not lastp), 'nq': nq[(t, w)]})
        for r in tmp:
            a = [0.0, 0.0]
            for (t, w), v in tq.items():
                if t == r['t'] and w < r['w']:
                    a[0] += v[0]; a[1] += v[1]
            r['club'] = a
        rows += tmp
        print('j1', y, len(tmp), flush=True)
    return rows


def j1(games):
    R = j1_rows(games)
    S = np.array([r['y'] for r in R]); y = np.array([r['played'] for r in R])
    A, B = S <= 2020, S >= 2021
    lg = float(y[A].mean())
    cell = [f"{r['prac']}|{r['recent']}" for r in R]
    tab = {}
    for c in set(cell):
        k = np.array([x == c for x in cell]) & A
        tab[c] = float(y[k].mean()) if k.sum() >= 30 else None
    flat = {True: float(y[A & np.array([r['recent'] for r in R])].mean()), False: float(y[A & ~np.array([r['recent'] for r in R])].mean())}
    p0 = np.array([tab[c] if tab[c] is not None else flat[r['recent']] for c, r in zip(cell, R)])

    def onehot(key, drop):
        lv = sorted({r[key] if not callable(key) else key(r) for r in R} - {drop})
        return [[float((r[key] if not callable(key) else key(r)) == v) for v in lv] for r in R], [f'{key if not callable(key) else "cell"}={v}' for v in lv]
    cols, names = [], []
    for key, drop in ((lambda r: f"{r['prac']}|{r['recent']}", 'limited|True'), ('pos', 'DB'), ('part', 'other'), ('last', 'none'), ('miss', 0)):
        m, n = onehot(key, drop)
        cols.append(np.array(m)); names += n
    club = np.array([(r['club'][0] + 20 * lg) / (r['club'][1] + 20) - lg for r in R])
    num = np.column_stack([club, [r['short'] for r in R], [r['share'] for r in R], [r['noshare'] for r in R], [r['nq'] for r in R]])
    names += ['club share', 'short week', 'snap share', 'no snaps yet', 'club Q count']
    X = np.column_stack(cols + [num])
    lam = pick_lambda(X[A], y[A], S[A])
    b, mu, sd = fit_ridge(X[A], y[A], lam)
    p1 = predict(X, b, mu, sd)
    WK = np.array([f"{r['y']}-{r['w']}" for r in R])
    res = {'n': {'tune': int(A.sum()), 'held': int(B.sum())}, 'lambda': lam, 'playRate': {'tune': round(lg, 4), 'held': round(float(y[B].mean()), 4)}}
    for nm, k in (('tune', A), ('held', B)):
        l1, l0 = logloss(p1[k], y[k]), logloss(p0[k], y[k])
        r = H.paired(l1, l0, cluster=WK[k])
        b1, b0 = (np.clip(p1[k], .005, .995) - y[k]) ** 2, (np.clip(p0[k], .005, .995) - y[k]) ** 2
        rb = H.paired(b1, b0, cluster=WK[k])
        res[nm] = {'llBase': round(float(l0.mean()), 4), 'llCand': round(float(l1.mean()), 4), 't': round(r['t'], 2), 'p': r['p'], 'G': r['G'],
                   'brierBase': round(float(b0.mean()), 4), 'brierCand': round(float(b1.mean()), 4), 'tBrier': round(rb['t'], 2)}
    res['bySeasonHeld'] = {int(s): round(float((logloss(p1, y) - logloss(p0, y))[S == s].mean()), 4) for s in HELD}
    # calibration of the candidate on held, by decile
    k = np.where(B)[0]; o = k[np.argsort(p1[k])]
    res['calibHeld'] = [{'p': round(float(p1[c].mean()), 3), 'played': round(float(y[c].mean()), 3), 'n': int(len(c))} for c in np.array_split(o, 10)]
    res['coef'] = {n: round(float(v), 3) for n, v in zip(['const'] + names, b)}
    # drop-one groups on held (descriptive)
    groups = {'pos': 'pos=', 'part': 'part=', 'last': 'last=', 'miss': 'miss=', 'club': 'club share', 'short': 'short week',
              'snap': ('snap share', 'no snaps yet'), 'nq': 'club Q count'}
    drop = {}
    for g, pre in groups.items():
        pre = pre if isinstance(pre, tuple) else (pre,)
        keep = [i for i, n in enumerate(names) if not any(n.startswith(q) for q in pre)]
        b2, mu2, sd2 = fit_ridge(X[A][:, keep], y[A], lam)
        p2 = predict(X[:, keep], b2, mu2, sd2)
        r = H.paired(logloss(p1[B], y[B]), logloss(p2[B], y[B]), cluster=WK[B])
        drop[g] = {'dLL': round(r['d'], 5), 't': round(r['t'], 2)}
    res['dropOneHeld'] = drop
    # the model refit on every season through 2025 (what live would read)
    lamF = lam
    bF, muF, sdF = fit_ridge(X, y, lamF)
    res['full'] = {'names': ['const'] + names, 'b': [float(v) for v in bF], 'mu': [float(v) for v in muF], 'sd': [float(v) for v in sdF], 'league': lg}
    return res


def j2_rows(games):
    """[(y, w, status, streak bucket / weeks-on-list bucket, practice, [miss_j...])]"""
    out = []
    for y in list(TUNE) + list(HELD):
        sch = HZ.schedule(games, y)
        ros = {}
        for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
            if r.get('game_type', 'REG') == 'REG' and r['gsis_id'] and r['week'] not in ('', 'NA'):
                ros[(int(r['week']), r['gsis_id'])] = (N.team(r['team']), r['status'])
        rep = {}
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            if r.get('game_type', 'REG') == 'REG' and r['report_status'] in ('Questionable', 'Doubtful', 'Out'):
                rep[(N.team(r['team']), int(r['week']), r['gsis_id'])] = (r['report_status'], N.practice_of(r['practice_status']) or 'none')

        def follow(t, w, gsis):
            o = []
            for x in [x for x in sch.get(t, []) if x > w][:4]:
                tt, st = ros.get((x, gsis), (None, None))
                if tt != t or st not in ('ACT', 'INA', 'RES', 'PUP'):
                    break
                o.append(0 if st == 'ACT' else 1)
            return o

        def streak(t, w, gsis):
            n = 0
            for x in reversed([x for x in sch.get(t, []) if x < w]):
                tt, st = ros.get((x, gsis), (None, None))
                if tt != t or st == 'ACT' or st not in ('INA', 'RES', 'PUP'):
                    break
                n += 1
            return n
        n0 = len(out)
        for (t, w, gsis), (st, prac) in rep.items():
            o = follow(t, w, gsis)
            if o:
                s = streak(t, w, gsis)
                out.append((y, w, st, '0' if s == 0 else '1' if s == 1 else '2-3' if s <= 3 else '4+', prac, o, 0))
        first = min(w for w, _ in ros) if ros else 1
        for (w, gsis), (t, st) in ros.items():
            if st not in ('RES', 'PUP') or w not in sch.get(t, []) or (t, w, gsis) in rep:
                continue
            n, x = 0, w - 1
            while (x, gsis) in ros and ros[(x, gsis)][0] == t and ros[(x, gsis)][1] in ('RES', 'PUP'):
                n += 1; x -= 1
            pre = x < first                       # on the list back to the season's first week
            was = ros.get((x, gsis))
            o = follow(t, w, gsis)
            if not o:
                continue
            b = 'pre' if pre else '0' if n == 0 else '1-3' if n <= 3 else '4-7' if n <= 7 else '8+'
            move = n == 0 and not pre and was is not None and was[0] == t and was[1] in ('ACT', 'INA')
            out.append((y, w, 'Reserve', b, 'none', o, int(move)))
        print('j2', y, len(out) - n0, flush=True)
    return out


def j2(games):
    E = j2_rows(games)
    tune = [e for e in E if e[0] <= 2020]; held = [e for e in E if e[0] >= 2021]

    def curves(rows, key):
        c = defaultdict(lambda: np.zeros((2, 4)))
        for e in rows:
            k = key(e)
            if k is None:
                continue
            o = e[5]
            c[k][0, :len(o)] += o; c[k][1, :len(o)] += 1
        return c
    # base: the live table. Q/D/Out by status on every listing; Reserve from the week of the move only
    cb = curves([e for e in tune if e[2] != 'Reserve' or e[6]], lambda e: e[2])
    base = {k: (v[0] + 0.5) / (v[1] + 1) for k, v in cb.items()}
    # candidate: status -> status x elapsed -> status x elapsed x practice, each shrunk to its parent
    c0 = curves(tune, lambda e: e[2]); c1 = curves(tune, lambda e: (e[2], e[3])); c2 = curves(tune, lambda e: (e[2], e[3], e[4]) if e[2] != 'Reserve' else None)
    L0 = {k: (v[0] + 0.5) / (v[1] + 1) for k, v in c0.items()}
    L1 = {k: (v[0] + MPART * L0[k[0]]) / (v[1] + MPART) for k, v in c1.items()}
    L2 = {k: (v[0] + MPART * L1[k[:2]]) / (v[1] + MPART) for k, v in c2.items()}

    def cand(e):
        return L2.get((e[2], e[3], e[4]), L1.get((e[2], e[3]), L0[e[2]]))

    def score(rows):
        a, b, cl, st, jj = [], [], [], [], []
        for e in rows:
            pc, pb = cand(e), base[e[2]]
            for j, m in enumerate(e[5]):
                a.append(logloss(np.array([pc[j]]), np.array([m]))[0]); b.append(logloss(np.array([pb[j]]), np.array([m]))[0])
                cl.append(f'{e[0]}-{e[1]}'); st.append(e[2]); jj.append(j + 1)
        return np.array(a), np.array(b), np.array(cl), np.array(st), np.array(jj)
    res = {'n': {'tune': len(tune), 'held': len(held)}}
    for nm, rows in (('tune', tune), ('held', held)):
        a, b, cl, st, jj = score(rows)
        r = H.paired(a, b, cluster=cl)
        res[nm] = {'llBase': round(float(b.mean()), 4), 'llCand': round(float(a.mean()), 4), 't': round(r['t'], 2), 'p': r['p'], 'G': r['G'],
                   'byStatus': {s: {'n': int((st == s).sum()), 'base': round(float(b[st == s].mean()), 4), 'cand': round(float(a[st == s].mean()), 4),
                                    't': round(H.paired(a[st == s], b[st == s], cluster=cl[st == s])['t'], 2)} for s in sorted(set(st))},
                   'byGame': {int(j): round(float((a - b)[jj == j].mean()), 4) for j in (1, 2, 3, 4)}}
    # the table on every season (what live would read), with counts
    f0 = curves(E, lambda e: e[2]); f1 = curves(E, lambda e: (e[2], e[3])); f2 = curves(E, lambda e: (e[2], e[3], e[4]) if e[2] != 'Reserve' else None)
    F0 = {k: (v[0] + 0.5) / (v[1] + 1) for k, v in f0.items()}
    F1 = {k: (v[0] + MPART * F0[k[0]]) / (v[1] + MPART) for k, v in f1.items()}
    F2 = {k: (v[0] + MPART * F1[k[:2]]) / (v[1] + MPART) for k, v in f2.items()}
    res['table'] = {'status': {k: [round(float(x), 4) for x in v] for k, v in F0.items()},
                    'elapsed': {'|'.join(k): {'p': [round(float(x), 4) for x in v], 'n': int(f1[k][1, 0])} for k, v in sorted(F1.items())},
                    'practice': {'|'.join(k): {'p': [round(float(x), 4) for x in v], 'n': int(f2[k][1, 0])} for k, v in sorted(F2.items())}}
    return res


if __name__ == '__main__':
    games, _, _ = N.load(2025)
    out = {'prereg': 'scripts/research/inj_nov14/PREREG.md'}
    if len(sys.argv) < 2 or 'j1' in sys.argv:
        out['J1'] = j1(games)
        print(json.dumps({k: v for k, v in out['J1'].items() if k not in ('full', 'coef', 'calibHeld')}, indent=1))
        print(out['J1']['coef'])
    if len(sys.argv) < 2 or 'j2' in sys.argv:
        out['J2'] = j2(games)
        print(json.dumps({k: v for k, v in out['J2'].items() if k != 'table'}, indent=1))
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    old.update(out)
    json.dump(old, open(OUT, 'w'), indent=1)
