#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB WAR replacement level from freely available players, tested out of sample.

    (needs scripts/.cache/cbb/bt/adv<y>.csv and scripts/.cache/cbb/teams/t<y>.csv = barttorvik.com/<y>_team_results.csv,
     2008-26, and the driver backtest's research_seasons.csv for NBA outcomes and recruit ranks)
    python3 scripts/cbb_repl_research.py [research_seasons.csv]   # -> data/cbb_repl_research.json

Pool F(y): rotation players in y (team top 8 by minutes, gp >= 10) who were in no D-I team's top 8 in y-1 and were never
a top-100 recruit. Line = median BPM of F, seasons out of fold.
P1 (gate): season WAR -> realized FV (hurdle on [1, WAR]), held-out draft class 2010-19, MSE paired t <= -2, 6+ of 10.
S1 (guard): next-season wins = a x games + b x returning value(R) + c x newcomer minutes, held-out season, t < +2.
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np    # noqa: E402
import cbb_data as D  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_repl_research.json')
CSV = sys.argv[1] if len(sys.argv) > 1 else '/mnt/project-files/cbb/backtest/research_seasons.csv'
YEARS = range(2008, 2027)
K = 0.68 * 0.01432 / 40   # WAR a (BPM - R) minute
OLD = -2.0


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)


def load():
    S = {}
    for y in YEARS:
        L = [l for l in D.load_bt(y) if l['gp'] and l['mp'] and l['bpm'] is not None]
        for l in L:
            l['min'] = l['mp'] * l['gp']
        by = defaultdict(list)
        for l in L:
            by[l['team']].append(l)
        rot = set()
        for t, ls in by.items():
            for l in sorted(ls, key=lambda l: -l['min'])[:8]:
                rot.add((l['pid'], t))
        rec = {}
        with open(os.path.join(D.CACHE, 'teams', f't{y}.csv'), newline='') as f:
            for r in csv.DictReader(f):
                w, lo = (int(x) for x in r['record'].split('-'))
                rec[r['team']] = (w, w + lo)
        S[y] = {'L': L, 'rot': rot, 'rotp': {p for p, _ in rot}, 'pids': {l['pid'] for l in L}, 'rec': rec}
    return S


def ranks(path):
    top, out = set(), {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            p = r['pid']
            num = lambda k: float(r[k]) if r[k] not in ('', None) else None
            rec, o3, s247 = num('rec'), num('on3rk'), num('rk247')
            if (rec is not None and rec >= 80.2) or (o3 is not None and o3 <= 100) or (s247 is not None and s247 <= 100):
                top.add(p)
            out[(p, int(r['year']))] = r
    return top, out


def pool(S, top, y, bench_only=False, rank_filter=True):
    prev = S[y - 1]
    out = []
    for l in S[y]['L']:
        if l['gp'] < 10 or (l['pid'], l['team']) not in S[y]['rot']:
            continue
        if l['pid'] in prev['rotp']:
            continue
        if bench_only and l['pid'] not in prev['pids']:
            continue
        if rank_filter and l['pid'] in top:
            continue
        out.append((l['bpm'], l['min']))
    return out


def med(xs):
    return float(np.median([b for b, _ in xs]))


def wmed(xs):
    xs = sorted(xs); h = sum(m for _, m in xs) / 2; c = 0
    for b, m in xs:
        c += m
        if c >= h:
            return b


def fit_logit(x, y, iters=50):
    X = np.column_stack([np.ones(len(x)), x]); w = np.zeros(2)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (y - p); H = (X * (p * (1 - p))[:, None]).T @ X + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, g); w += step
        if np.abs(step).max() < 1e-10:
            break
    return w


def hurdle(xtr, ytr, xte):
    nb = ytr > 20
    wl = fit_logit(xtr, nb.astype(float))
    A = np.column_stack([np.ones(nb.sum()), xtr[nb]]); c = np.linalg.lstsq(A, ytr[nb], rcond=None)[0]
    p = 1 / (1 + np.exp(-(wl[0] + wl[1] * xte))); mu = c[0] + c[1] * xte
    return 20 + p * (mu - 20), p


def main():
    S = load()
    top, meta = ranks(CSV)
    res = {'prereg_sha256': '5d15d80e7f2c3dd0189f6f467e1fd2087d1e2e71e3e42f2561cfe26726f77f41'}

    # ---- the line
    F = {y: pool(S, top, y) for y in YEARS if y > YEARS[0]}
    line_all = med([r for y in F for r in F[y]])
    res['line'] = {'pooled': round(line_all, 3), 'live': round(line_all * 2) / 2, 'n': sum(len(v) for v in F.values()),
                   'bySeason': {y: [round(med(F[y]), 2), len(F[y])] for y in F},
                   'variants': {'benchOnly': round(med([r for y in F for r in pool(S, top, y, bench_only=True)]), 2),
                                'noRankFilter': round(med([r for y in F for r in pool(S, top, y, rank_filter=False)]), 2),
                                'minutesWeighted': round(wmed([r for y in F for r in F[y]]), 2)}}
    # 9th man and slot medians, for reference
    slots = defaultdict(list)
    for y in range(2017, 2027):
        by = defaultdict(list)
        for l in S[y]['L']:
            by[l['team']].append(l)
        for ls in by.values():
            for i, l in enumerate(sorted(ls, key=lambda l: -l['min'])[:15]):
                slots[i + 1].append(l['bpm'])
    res['slotMedianBpm2017_26'] = {i: round(float(np.median(v)), 2) for i, v in sorted(slots.items())}

    def fold_line(excl):
        return med([r for y in F if y not in excl for r in F[y]])

    # replacement team win% at each line: same-season wins = a x games + b x points over R, 2017-26
    def repl_fit(R):
        A, w = [], []
        for y in range(2017, 2027):
            X = defaultdict(float)
            for l in S[y]['L']:
                X[l['team']] += (l['bpm'] - R) * l['min'] / 40 * 0.68
            for t, (wi, g) in S[y]['rec'].items():
                if t in X and g >= 20:
                    A.append([g, X[t]]); w.append(wi)
        c = np.linalg.lstsq(np.array(A, float), np.array(w, float), rcond=None)[0]
        return {'a': round(float(c[0]), 4), 'wpp': round(float(c[1]), 5), 'teams': len(w)}
    unmatched = sorted({l['team'] for y in YEARS for l in S[y]['L']} - {t for y in YEARS for t in S[y]['rec']})
    res['teamsUnmatched'] = unmatched[:20]
    res['replTeam'] = {str(R): repl_fit(R) for R in (OLD, res['line']['live'], -3.0, -4.0, -5.0, -6.0)}

    # ---- P1: season WAR -> realized FV, held-out draft class
    rows = []
    for y in YEARS:
        for l in S[y]['L']:
            m = meta.get((l['pid'], y))
            if not m or l['gp'] < 10 or (l['min_per'] or 0) < 10:
                continue
            c = int(float(m['career_last']))
            rows.append((c, l['pid'], l['bpm'], l['min'], float(m['fv']), float(m['nba']), float(m['nba_games'] or 0)))
    R_ = np.array(rows, dtype=object)

    def p1(classes, use_rows):
        cls = np.array([r[0] for r in use_rows]); bpm = np.array([r[2] for r in use_rows], float)
        mn = np.array([r[3] for r in use_rows], float); fv = np.array([r[4] for r in use_rows], float)
        nba = np.array([r[5] for r in use_rows], float); ng = np.array([r[6] for r in use_rows], float)
        keep = np.isin(cls, classes); cls, bpm, mn, fv, nba, ng = cls[keep], bpm[keep], mn[keep], fv[keep], nba[keep], ng[keep]
        per = {}
        for c in classes:
            R1 = fold_line(set(range(c - 4, c + 1)))
            te, tr = cls == c, cls != c
            out = {'line': round(R1, 3), 'n': int(te.sum())}
            for name, R in (('old', OLD), ('new', R1)):
                x = (bpm - R) * mn * K
                e, p = hurdle(x[tr], fv[tr], x[te])
                pc = np.clip(p, 1e-9, 1 - 1e-9)
                A = np.column_stack([np.ones(tr.sum()), x[tr]]); g = np.linalg.lstsq(A, ng[tr], rcond=None)[0]
                out[name] = {'mse': float(np.mean((fv[te] - e) ** 2)),
                             'logloss': float(-np.mean(nba[te] * np.log(pc) + (1 - nba[te]) * np.log(1 - pc))),
                             'gamesRmse': float(np.sqrt(np.mean((ng[te] - g[0] - g[1] * x[te]) ** 2)))}
            per[c] = out
        summ = {}
        for k in ('mse', 'logloss', 'gamesRmse'):
            d = [per[c]['new'][k] - per[c]['old'][k] for c in classes]
            summ[k] = {'old': round(float(np.mean([per[c]['old'][k] for c in classes])), 5),
                       'new': round(float(np.mean([per[c]['new'][k] for c in classes])), 5),
                       'd': [round(x, 5) for x in d], 't': tstat(d), 'better': sum(x < 0 for x in d), 'classes': len(d)}
        return {'byClass': {c: {'line': v['line'], 'n': v['n'], 'mseOld': round(v['old']['mse'], 4), 'mseNew': round(v['new']['mse'], 4)} for c, v in per.items()},
                **summ}

    res['P1'] = p1(list(range(2010, 2020)), rows)
    res['P1']['pass'] = bool(res['P1']['mse']['t'] <= -2 and res['P1']['mse']['better'] >= 6)
    res['P1_2010_21'] = p1(list(range(2010, 2022)), rows)

    # career WAR: sum of a player's seasons (first season 2009+ or a 2008 freshman season), classes 2011-19
    first = {}
    for y in YEARS:
        for l in S[y]['L']:
            first.setdefault(l['pid'], (y, l['yr']))
    car = defaultdict(lambda: [0.0, 0.0, None])
    for (c, pid, b, mn, fv, nba, ng) in rows:
        fy, fyr = first[pid]
        if fy >= 2009 or fyr == 'Fr':
            a = car[(c, pid)]; a[0] += b * mn; a[1] += mn; a[2] = (fv, nba, ng)
    crow = [(c, pid, a[0] / a[1], a[1], *a[2]) for (c, pid), a in car.items() if a[1] > 0]
    res['P1career'] = p1(list(range(2011, 2020)), crow)

    # ---- S1: next-season wins with newcomer control
    tg = list(range(2010, 2027))

    def srows(y, R, newc=True):
        prev = {l['pid']: l['bpm'] for l in S[y - 1]['L']}
        V, N = defaultdict(float), defaultdict(float)
        for l in S[y]['L']:
            b = prev.get(l['pid'])
            if b is None:
                N[l['team']] += l['min'] / 40 * 0.68
            else:
                V[l['team']] += (b - R) * l['min'] / 40 * 0.68
        teams = {l['team'] for l in S[y]['L']}
        return [(g, V[t], N[t], w) if newc else (g, V[t], w) for t, (w, g) in S[y]['rec'].items() if t in teams and g >= 15]

    def s1(newc):
        d, sse = [], {'old': 0.0, 'new': 0.0}
        for y in tg:
            R1 = fold_line({y - 1, y})
            e = {}
            for name, R in (('old', OLD), ('new', R1)):
                tr = [r for k in tg if k != y for r in srows(k, R, newc)]; te = srows(y, R, newc)
                A = np.array([r[:-1] for r in tr], float); c = np.linalg.lstsq(A, np.array([r[-1] for r in tr], float), rcond=None)[0]
                At = np.array([r[:-1] for r in te], float)
                e[name] = float(np.sum((np.array([r[-1] for r in te]) - At @ c) ** 2))
                sse[name] += e[name]
            d.append(e['new'] - e['old'])
        return {'sseOld': round(sse['old'], 1), 'sseNew': round(sse['new'], 1), 'd': [round(x, 2) for x in d], 't': tstat(d),
                'better': sum(x < 0 for x in d), 'seasons': len(d)}
    res['S1'] = s1(True)
    res['S1']['notWorse'] = bool(res['S1']['t'] < 2)
    res['S1_nov03design'] = s1(False)
    res['decision'] = 'ship' if res['P1']['pass'] and res['S1']['notWorse'] else 'no ship'
    json.dump(res, open(OUT, 'w'), indent=1)
    print(json.dumps({k: res[k] for k in ('line', 'replTeam', 'teamsUnmatched', 'decision')}, indent=1))
    for k in ('P1', 'P1_2010_21', 'P1career'):
        print(k, {m: {q: res[k][m][q] for q in ('old', 'new', 't', 'better', 'classes')} for m in ('mse', 'logloss', 'gamesRmse')})
    for k in ('S1', 'S1_nov03design'):
        print(k, {q: res[k][q] for q in ('sseOld', 'sseNew', 't', 'better', 'seasons')})


if __name__ == '__main__':
    main()
