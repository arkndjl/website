#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Defender on-field RAPM as a last-season XV part (PREREG.md lead 9): X1 pressure for EDGE/DT, X2 dropback EPA for DB.

    python3 def_rapm_test.py --extract <dir of part_<y>.csv>     # dropbacks with the defenders on the field (cache)
    python3 def_rapm_test.py --test <out json>

Ridge per season of each dropback's outcome (pressure; minus EPA) on the defenders on the field, the offence as a
nuisance column; each season's rating shrunk toward decay x the rating through the season before. lambda and decay
are picked on 2017-20 by how well the rating through S-1 lines up with season S's own rating. The part a player
carries in season S is the rating through S-1 only."""
import csv
import gzip
import json
import math
import os
import pickle
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import nfl_war as W   # noqa: E402
import nfl_xv as X    # noqa: E402
from madden_xv_test import residuals, tclus, xvs   # noqa: E402

YEARS = list(range(2016, 2026))
PLAYS = os.path.join(W.CACHE, 'defplays_rapm_{}.pkl')
GRID = [(1000, 0.0), (1000, 0.5), (3000, 0.0), (3000, 0.5)]
K_PART = 300


def extract(D):
    for y in YEARS:
        part = {}
        with open(os.path.join(D, f'part_{y}.csv'), newline='') as f:
            for r in csv.DictReader(f):
                if r['defense_players']:
                    part[(r['nflverse_game_id'], r['play_id'])] = (r['defense_players'], r['was_pressure'])
        out = []
        src = W.get(f'play_by_play_{y}.csv.gz', f'{W.REL}/pbp/play_by_play_{y}.csv.gz')
        with gzip.open(src, 'rt', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['season_type'] != 'REG' or r['epa'] in ('', 'NA') or r['qb_dropback'] != '1':
                    continue
                p = part.get((r['game_id'], r['play_id']))
                if not p:
                    continue
                d = [g for g in p[0].split(';') if g]
                if 9 <= len(d) <= 12:
                    out.append((r['posteam'], d, 1.0 if p[1] == 'TRUE' else 0.0, float(r['epa']), p[1] in ('TRUE', 'FALSE')))
        with open(PLAYS.format(y), 'wb') as f:
            pickle.dump(out, f)
        print(y, len(out), 'dropbacks', sum(1 for p in out if p[4]), 'with a pressure flag', flush=True)


def season(P, prior, lam, target, lam_n=300.0):
    if target == 'pr':
        P = [p for p in P if p[4]]
        yv = np.array([p[2] for p in P])
    else:
        yv = -np.array([max(-4.0, min(4.0, p[3])) for p in P])
    yv = yv - yv.mean()
    ids, nus = {}, {}
    for p in P:
        for g in p[1]:
            ids.setdefault(g, len(ids))
        nus.setdefault(p[0], len(nus))
    nd = len(ids); n = nd + len(nus)
    M = np.zeros((n, n)); b = np.zeros(n)
    for p, v in zip(P, yv):
        c = [ids[g] for g in p[1]] + [nd + nus[p[0]]]
        M[np.ix_(c, c)] += 1; b[c] += v
    pv = np.zeros(n)
    for g, j in ids.items():
        pv[j] = prior.get(g, 0.0)
    reg = np.full(n, lam_n); reg[:nd] = lam
    beta = np.linalg.solve(M + np.diag(reg), b + reg * pv)
    return {g: float(beta[j]) for g, j in ids.items()}, Counter(g for p in P for g in p[1])


def chain(PL, target, lam, decay):
    """{season: (rating through that season, on-field counts that season)}; and each season's own rating (no prior)"""
    out, own, prev = {}, {}, {}
    for y in YEARS:
        r, cnt = season(PL[y], {g: decay * v for g, v in prev.items()}, lam, target)
        out[y] = (r, cnt)
        own[y] = r if decay == 0 else season(PL[y], {}, lam, target)[0]
        prev = r
    return out, own


def pick(PL, target):
    best = None
    res = {}
    for lam, decay in GRID:
        ch, own = chain(PL, target, lam, decay)
        xs, ys = [], []
        for y in (2017, 2018, 2019, 2020):
            a, ca = ch[y - 1]; b = own[y]; cb = ch[y][1]
            for g, v in a.items():
                if g in b and ca[g] >= 200 and cb[g] >= 200:
                    xs.append(v); ys.append(b[g])
        r = float(np.corrcoef(xs, ys)[0, 1])
        res[f'{lam}/{decay}'] = round(r, 4)
        if best is None or r > best[0]:
            best = (r, lam, decay, ch)
    return best, res


def test(out_path):
    PL = {y: pickle.load(open(PLAYS.format(y), 'rb')) for y in YEARS}
    S = X.load(); X.zscore(S)
    _, value, _ = W.sub_lines()
    lam = json.load(open(X.OUT)).get('lambda', 20)
    base, r0, _ = xvs(S, lam, value)
    out = {'teamRLive': round(r0, 4)}
    live_parts = {g: list(v) for g, v in X.PARTS.items()}
    for name, target, groups in (('X1 EDGE/DT pressure', 'pr', ('EDGE', 'DT')), ('X2 DB dropback EPA', 'epa', ('DB',))):
        (rr, rl, rd, ch), grid = pick(PL, target)
        for g, v in live_parts.items():
            X.PARTS[g] = list(v) + (['rapm'] if g in groups else [])
        X.COLS[:] = [(g, part) for g in X.GROUPS for part in X.PARTS[g]]
        have = 0
        for y, d in S.items():
            rat, cnt = ch.get(y - 1, ({}, {}))
            by = defaultdict(list)
            for p in d['players']:
                if X.GROUP_OF[p['sub']] in groups and p.get('gsis') in rat and cnt[p['gsis']] >= 100:
                    by[p['sub']].append(rat[p['gsis']])
            st = {s: (np.mean(v), np.std(v) or 1.0) for s, v in by.items() if len(v) >= 8}
            for p in d['players']:
                if X.GROUP_OF[p['sub']] not in groups:
                    continue
                g = p.get('gsis')
                if g in rat and p['sub'] in st and cnt[g] >= 100:
                    z = max(-3.0, min(3.0, (rat[g] - st[p['sub']][0]) / st[p['sub']][1]))
                    p['z']['rapm'] = z * cnt[g] / (cnt[g] + K_PART); have += 1
                else:
                    p['z']['rapm'] = 0.0
        cand, r1, w1 = xvs(S, lam, value)
        res = {'grid': grid, 'lambda': rl, 'decay': rd, 'stabilityR': round(rr, 4), 'playerSeasonsWithPart': have,
               'teamR': round(r1, 4), 'weights': {k: v for k, v in w1.items() if k.endswith('.rapm')}}
        for lab, ys in (('2018-25', range(2018, 2026)), ('2018-21', range(2018, 2022)), ('2022-25', range(2022, 2026))):
            Sy = {y: S[y] for y in ys if y in S}
            e0, cl, c0, t0 = residuals(Sy, base)
            e1, _, c1, t1 = residuals(Sy, cand)
            d = e0 - e1
            res[lab] = {'games': len(d), 'liveT': round(t0, 2), 'candT': round(t1, 2), 'sseGain': round(float(d.sum()), 1), 'tPaired': round(float(tclus(d, cl)), 2)}
        out[name] = res
        print(name, json.dumps(res), flush=True)
        for p in (p for d in S.values() for p in d['players']):
            p['z'].pop('rapm', None)
    json.dump(out, open(out_path, 'w'), indent=1)


if __name__ == '__main__':
    if '--extract' in sys.argv:
        extract(sys.argv[2])
    else:
        test(sys.argv[2])
