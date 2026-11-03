#!/usr/bin/env python3
"""CBB WAR / Stat+ staple audit (Nov 3 2026), out of sample across 2017-26 Barttorvik seasons.

    (needs scripts/.cache/cbb/bt/adv<y>.csv and scripts/.cache/cbb/games/<y>.json.gz, 2017-26)
    python3 scripts/cbb_war_research_nov03.py   # -> data/cbb_war_research_nov03.json

WAR = (BPM - R) x min / 40 x team poss a 40 / 100 x WPP; WPP .01243 and the intercept a .407 x games were fit on
2025-26 alone (scripts/cbb_tabs.py fit_wpp), R = -2.

Pre-registered (written before any run):
  C1  wins a point: team wins = a x games + b x team points over replacement, (a, b) fit on the other seasons (pooled)
      against (a, b) fixed at the 2025-26 fit (.407, .01243); held-out team-season wins SSE, seasons 2017-25 (2026 is the
      fixed fit's own season), paired t over seasons.
  C2  replacement level R on NEXT-season team wins: team value = sum over season-y players of (BPM(y-1) - R) x min(y)
      / 40 x poss(y) / 100, players with no D-I line in y-1 at R (0); wins = a x games + b x value, (a, b) fit on the other
      target seasons; R* picked on the other seasons (nested, grid 0 .. -6) against R -2; paired t over 2018-26.
  C3  pace: the same-season C1 fit with team possessions against a flat 68 (is poss x per-100 BPM right, or does pace
      wash out of wins?); paired t over 2017-26, LOSO (a, b) both ways.
  C4  Stat+ norms: G/F/C minutes-weighted BPM sd by season (descriptive); live Stat+ through each team's 8th game:
      norms from the season's own partial pool against the fixed full-season norms, scored by squared error against
      the full-season Stat+ (game-log BPM), paired t over seasons.
Pass: Holm over C1-C4 at .05, ahead in most seasons.
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np    # noqa: E402
import cbb_data as D  # noqa: E402
import cbb_tabs as T  # noqa: E402
from nfl_war_research_nov03 import tstat, pval   # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'data', 'cbb_war_research_nov03.json')
YEARS = list(range(2017, 2027))
GC = T.GC
POS = T.POSMAP


def season(y):
    G = [g for g in json.load(gzip.open(os.path.join(D.CACHE, 'games', f'{y}.json.gz'))) if g[GC['year']] == y]
    rec, seen, poss, mins = defaultdict(lambda: [0, 0]), {}, {}, defaultdict(float)
    for g in G:
        k = (g[GC['team']], g[GC['muid']])
        mins[k] += g[GC['min']] or 0
        if k in seen:
            continue
        seen[k] = 1; rec[k[0]][0] += g[GC['win1']]; rec[k[0]][1] += 1
        if g[GC['poss']]:
            poss[k] = g[GC['poss']]
    tempo, tempo40 = defaultdict(list), defaultdict(list)
    for k, p in poss.items():
        tempo[k[0]].append(p)
        tempo40[k[0]].append(p * 200 / mins[k] if mins[k] > 150 else p)   # overtime scaled back to 40 minutes
    L = [l for l in D.load_bt(y) if l['gp'] and l['mp'] and l['bpm'] is not None]
    return {'G': G, 'rec': dict(rec), 'tempo': {t: sum(v) / len(v) for t, v in tempo.items()},
            'tempo40': {t: sum(v) / len(v) for t, v in tempo40.items()}, 'L': L}


def fit_ab(rows):
    A = np.array([[r[1], r[2]] for r in rows]); w = np.array([r[3] for r in rows], float)
    return np.linalg.lstsq(A, w, rcond=None)[0]


def sse_of(rows, ab):
    return float(sum((r[3] - ab[0] * r[1] - ab[1] * r[2]) ** 2 for r in rows))


def main():
    S = {y: season(y) for y in YEARS}
    res = {'years': [YEARS[0], YEARS[-1]]}

    def team_rows(y, R=-2.0, pace='tempo'):
        s = S[y]; X = defaultdict(float)
        for l in s['L']:
            tp = s[pace].get(l['team'], 68.0) if pace else 68.0
            X[l['team']] += (l['bpm'] - R) * l['mp'] * l['gp'] / 40 * tp / 100
        return [(y, s['rec'][t][1], X[t], s['rec'][t][0]) for t in s['rec'] if t in X and s['rec'][t][1] >= 20]

    # ---- C1: wins a point, pooled other seasons vs the 2025-26 fit
    rows = {y: team_rows(y) for y in YEARS}
    per = {y: [round(float(v), 5) for v in fit_ab(rows[y])] for y in YEARS}
    fixed = (0.407, 0.01243)
    d1 = []
    for y in YEARS[:-1]:
        ab = fit_ab([r for k in YEARS if k != y for r in rows[k]])
        d1.append(sse_of(rows[y], fixed) - sse_of(rows[y], ab))
    allab = fit_ab([r for y in YEARS for r in rows[y]])
    res['C1'] = {'bySeason': per, 'pooled': [round(float(v), 5) for v in allab], 'fixed': fixed,
                 'dSse': [round(x, 1) for x in d1], 't': tstat(d1), 'better': sum(x > 0 for x in d1), 'seasons': len(d1),
                 'teams': sum(len(rows[y]) for y in YEARS)}

    # ---- C2: replacement level on next-season wins
    RS = [0.0, -1.0, -2.0, -3.0, -4.0, -5.0, -6.0]
    tg = YEARS[1:]
    prevb = {y: {str(l['pid']): l['bpm'] for l in S[y - 1]['L']} for y in tg}
    nrows = {R: {} for R in RS}
    for y in tg:
        s = S[y]
        for R in RS:
            X = defaultdict(float)
            for l in s['L']:
                b = prevb[y].get(str(l['pid']))
                if b is None:
                    continue
                X[l['team']] += (b - R) * l['mp'] * l['gp'] / 40 * s['tempo'].get(l['team'], 68.0) / 100
            nrows[R][y] = [(y, s['rec'][t][1], X[t], s['rec'][t][0]) for t in s['rec'] if s['rec'][t][1] >= 20 and t in {l['team'] for l in s['L']}]
    sse2 = {R: {} for R in RS}
    for R in RS:
        for y in tg:
            ab = fit_ab([r for k in tg if k != y for r in nrows[R][k]])
            sse2[R][y] = sse_of(nrows[R][y], ab)
    pick, d2 = {}, []
    for y in tg:
        R_ = min(RS, key=lambda R: sum(v for k, v in sse2[R].items() if k != y))
        pick[y] = R_; d2.append(sse2[-2.0][y] - sse2[R_][y])
    res['C2'] = {'sseByR': {str(R): round(sum(sse2[R].values()), 1) for R in RS}, 'nestedPick': pick, 'dSse': [round(x, 1) for x in d2],
                 't': tstat(d2), 'better': sum(x > 0 for x in d2), 'seasons': len(d2)}

    # ---- C3: pace (team poss vs flat 68; and overtime-scaled poss, the docstring's definition)
    out3 = {}
    for name, pace in (('flat68', None), ('ot40', 'tempo40')):
        rws = {y: team_rows(y, pace=pace) for y in YEARS}
        d3 = []
        for y in YEARS:
            ab0 = fit_ab([r for k in YEARS if k != y for r in rows[k]]); ab1 = fit_ab([r for k in YEARS if k != y for r in rws[k]])
            d3.append(sse_of(rows[y], ab0) - sse_of(rws[y], ab1))
        out3[name] = {'dSse': [round(x, 2) for x in d3], 't': tstat(d3), 'better': sum(x > 0 for x in d3), 'seasons': len(d3)}
    res['C3'] = out3['flat68']; res['C3ot'] = out3['ot40']

    # ---- C4: Stat+ norms
    def norms(xs):   # xs: (pos, bpm, minutes)
        out = {}
        for p in 'GFC':
            v = [(b, m) for q, b, m in xs if q == p]
            w = sum(m for _, m in v); mu = sum(b * m for b, m in v) / w
            out[p] = (mu, math.sqrt(sum(m * (b - mu) ** 2 for b, m in v) / w))
        return out
    sd_by = {}
    d4 = []
    fixedN = None
    for y in YEARS:
        L = S[y]['L']
        role = {str(l['pid']): POS.get(l['role'], 'F') for l in L}
        sd_by[y] = {p: [round(a, 2), round(b, 2)] for p, (a, b) in norms([(POS.get(l['role'], 'F'), l['bpm'], l['mp'] * l['gp']) for l in L if (l['min_per'] or 0) >= 10]).items()}
    fixedN = {p: tuple(v) for p, v in sd_by[2026].items()}
    part = {}
    for y in YEARS:
        G = sorted(S[y]['G'], key=lambda g: g[GC['date']])
        role = {str(l['pid']): POS.get(l['role'], 'F') for l in S[y]['L']}
        tgames = defaultdict(list)
        for g in G:
            k = (g[GC['team']], g[GC['muid']])
            if k[1] not in tgames[k[0]]:
                tgames[k[0]].append(k[1])
        early = {t: set(v[:8]) for t, v in tgames.items()}
        acc = {'full': defaultdict(lambda: [0.0, 0.0]), 'early': defaultdict(lambda: [0.0, 0.0])}
        tmin = {'full': defaultdict(float), 'early': defaultdict(float)}
        for g in G:
            pid, t, m, b = str(g[GC['pid']]), g[GC['team']], g[GC['min']] or 0, g[GC['gbpm']]
            if b is None or pid not in role:
                continue
            for w in ('full', 'early') if g[GC['muid']] in early[t] else ('full',):
                a = acc[w][(pid, t)]; a[0] += b * m; a[1] += m; tmin[w][t] += m
        val = {}
        for w in acc:
            val[w] = {k: (v[0] / v[1], v[1], role[k[0]]) for k, v in acc[w].items() if v[1] > 0 and v[1] / max(1, tmin[w][k[1]]) * 5 >= 0.10}
        fN = norms([(q, b, m) for b, m, q in val['full'].values()])
        eN = norms([(q, b, m) for b, m, q in val['early'].values()])
        sp = lambda b, q, N: 100 + 25 * (b - N[q][0]) / N[q][1]
        e_fix, e_own = 0.0, 0.0
        for k, (b, m, q) in val['early'].items():
            if k not in val['full']:
                continue
            tgt = sp(val['full'][k][0], q, fN)
            e_fix += (sp(b, q, fN) - tgt) ** 2; e_own += (sp(b, q, eN) - tgt) ** 2
        part[y] = {'sdFull': {p: round(fN[p][1], 2) for p in 'GFC'}, 'sdEarly8': {p: round(eN[p][1], 2) for p in 'GFC'},
                   'mseFixed': round(e_fix / len(val['early']), 1), 'mseOwn': round(e_own / len(val['early']), 1)}
        d4.append(e_fix / len(val['early']) - e_own / len(val['early']))
    res['C4'] = {'seasonNorms': sd_by, 'early8': part, 't': tstat(d4), 'better': sum(x > 0 for x in d4), 'seasons': len(d4)}

    # after the batch: what ships (flat pace + slope pooled on the other seasons) against the old WAR (team pace, the
    # 2025-26 fit), held-out wins; and why C2's R -4 does not ship: newcomers' own BPM and returners' year-on gain
    flat = {y: team_rows(y, pace=None) for y in YEARS}
    ds = [sse_of(rows[y], fixed) - sse_of(flat[y], fit_ab([r for k in YEARS if k != y for r in flat[k]])) for y in YEARS[:-1]]
    res['shipped'] = {'dSse': [round(x, 1) for x in ds], 't': round(tstat(ds), 2), 'better': sum(x > 0 for x in ds), 'seasons': len(ds),
                      'fit': [round(float(v), 5) for v in fit_ab([r for y in YEARS for r in flat[y]])]}
    diag = {}
    for y in tg:
        nb = nm = rd = rm = 0.0
        prev = {str(l['pid']): l['bpm'] for l in S[y - 1]['L']}
        for l in S[y]['L']:
            m = l['mp'] * l['gp']; b = prev.get(str(l['pid']))
            if b is None:
                nb += l['bpm'] * m; nm += m
            else:
                rd += (l['bpm'] - b) * m; rm += m
        diag[y] = {'newcomerBpm': round(nb / nm, 2), 'newcomerMin': round(nm / (nm + rm), 2), 'returnerGain': round(rd / rm, 2)}
    res['C2diag'] = diag
    res['decision'] = {'C1': 'ship (pooled 2017-26 slope)', 'C3': 'ship (flat 68)', 'C4': 'ship (live Stat+ on own norms)',
                       'C2': 'no ship: R -4 = newcomer BPM (-1.3) less returners\' year-on gain (+1.1) and noise in last season\'s BPM, not a replacement level'}

    ps = {k: pval(res[k]['t'], res[k]['seasons'] - 1) for k in ('C1', 'C2', 'C3', 'C4')}
    order = sorted(ps, key=lambda k: ps[k] if ps[k] is not None else 1)
    holm, ok = {}, True
    for i, k in enumerate(order):
        thr = 0.05 / (len(order) - i)
        passed = ok and ps[k] is not None and ps[k] < thr and res[k]['t'] > 0 and res[k]['better'] > res[k]['seasons'] / 2
        ok = ok and passed
        holm[k] = {'p': None if ps[k] is None else round(ps[k], 4), 'thr': round(thr, 4), 'pass': passed}
    res['holm'] = holm
    for k in ('C1', 'C2', 'C3', 'C3ot', 'C4'):
        if res[k]['t'] is not None:
            res[k]['t'] = round(res[k]['t'], 2)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1, default=str)
        f.write('\n')
    print(json.dumps(res, indent=1, default=str))


if __name__ == '__main__':
    main()
