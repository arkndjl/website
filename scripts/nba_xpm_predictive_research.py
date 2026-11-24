#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""XPM vs other player metrics, describe and predict (Nov 24 2026, XPM stabilization post). LumaHoops Table 4 style.

Describe: season-n value x season-n share of team minutes (x5) -> team season-n net rating, R2.
Predict:  season-n value x season-(n+1) share of team minutes (x5) -> team season-(n+1) net rating, R2. Players with
          no season-n value take the metric's mean for players under 500 MP that season. Raw values, no refit.
Pairs: 2013-14 -> 14-15 .. 2025-26, skipping 2019-20 and 2020-21 (the paper's nine pairs). RAPM (gabriel1200) ends
2022-23, so a common window 2014-23 (five pairs) is also scored. 90% intervals: 2,000 resamples of season pairs.
Inputs outside the repo (project files): cbb/xpm/players.csv + teams.csv (bbref minutes, on-court, on/off, team net),
nba-metrics/raw (LEBRON, RAPM), nba-metrics/hapm-nov18/hapm_bbref.csv (HAPM 1/3 = one season). XPM files from the repo.
LEBRON/HAPM history were fit with later seasons available (look-ahead in priors/weights); XPM/BPM/DPM have none.
rXPM = the team-adjusted blend (txpm, Nov 24 2026); pXPM is built on the box blend (xpm).
-> data/nba_xpm_predictive_research.json"""
import csv, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..')
PF = sys.argv[1] if len(sys.argv) > 1 else '/mnt/project-files'

P = pd.read_csv(f'{PF}/cbb/xpm/players.csv', low_memory=False, usecols=['year', 'pid', 'tm', 'mp', 'plus_minus_on', 'plus_minus_net'])
P = P[~P.tm.astype(str).str.match(r'^\dTM$|^TOT$')].copy()
for c in ('mp', 'plus_minus_on', 'plus_minus_net'): P[c] = pd.to_numeric(P[c], errors='coerce')
P['mp'] = P.mp.fillna(0)
T = pd.read_csv(f'{PF}/cbb/xpm/teams.csv')
T['net'] = pd.to_numeric(T.net_rtg.astype(str).str.replace('+', '', regex=False), errors='coerce')
NET = {(r.year, r.tm): r.net for r in T.itertuples()}
TMP = P.groupby(['year', 'tm']).mp.sum().to_dict()

V = {}                                                    # metric -> {(year, pid): (value, mp)}
def put(m, y, pid, v, mp):
    if v is not None and v == v: V.setdefault(m, {})[(y, pid)] = (float(v), float(mp or 0))
for y in range(2010, 2027):
    fn = os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{y}.json')
    if not os.path.exists(fn): continue
    for p in json.load(open(fn))['players']:
        if p.get('pr'): continue
        for m, k in (('rXPM', 'txpm'), ('pXPM', 'sxpm'), ('BPM', 'bpm'), ('DPM', 'dpm')): put(m, y, p['id'], p.get(k), p['mp'])
tot = P.groupby(['year', 'pid']).mp.sum().to_dict()
g = P.dropna(subset=['plus_minus_on']).assign(w1=lambda d: d.plus_minus_on * d.mp, w2=lambda d: d.plus_minus_net * d.mp)
for (y, pid), d in g.groupby(['year', 'pid']):
    if d.mp.sum() > 0:
        put('on-court +/-', y, pid, d.w1.sum() / d.mp.sum(), d.mp.sum()); put('on/off', y, pid, d.w2.sum() / d.mp.sum(), d.mp.sum())
n2b = json.load(open(f'{PF}/nba-metrics/nba2bbref.json'))
for r in json.load(open(f'{PF}/nba-metrics/raw/load_lebron.json')):
    b = n2b.get(str(r.get('nba_id'))); 
    if b: put('LEBRON', int(r['year']), b, r.get('LEBRON'), r.get('Minutes'))
for r in csv.DictReader(open(f'{PF}/nba-metrics/raw/rapm_gab.csv')):
    b = n2b.get(str(r['playerId']))
    if b and r.get('RAPM'): put('RAPM (1-yr)', int(r['season'][:4]) + 1, b, float(r['RAPM']), tot.get((int(r['season'][:4]) + 1, b), 0))
for r in csv.DictReader(open(f'{PF}/nba-metrics/hapm-nov18/hapm_bbref.csv')):
    if r['version'] == '1/3' and r['net']: put('HAPM (1-yr)', int(r['year']), r['pid'], float(r['net']), tot.get((int(r['year']), r['pid']), 0))

PAIRS = [n for n in range(2014, 2026) if n not in (2020, 2021) and n + 1 not in (2020, 2021)]


def team_rows(m, n, nxt):
    vals = V[m]; fill = np.mean([v for (y, _), (v, mp) in vals.items() if y == n and mp < 500] or [0])
    yy = n + 1 if nxt else n
    rows = {}
    for r in P[P.year == yy].itertuples():
        v = vals.get((n, r.pid)); v = v[0] if v else fill
        rows.setdefault(r.tm, 0.0); rows[r.tm] += v * 5 * r.mp / TMP[(yy, r.tm)]
    return [(n, rows[t], NET[(yy, t)]) for t in rows if (yy, t) in NET]


def r2(rows): a = np.array([r[1:] for r in rows]); return float(np.corrcoef(a.T)[0, 1] ** 2)


def score(m, pairs, rng):
    D = {n: team_rows(m, n, False) for n in pairs}; Q = {n: team_rows(m, n, True) for n in pairs}
    out = {'describe': round(r2(sum(D.values(), [])), 3), 'predict': round(r2(sum(Q.values(), [])), 3)}
    bs = [r2(sum((Q[n] for n in rng.choice(pairs, len(pairs))), [])) for _ in range(2000)]
    out['predict90'] = [round(float(np.percentile(bs, 5)), 3), round(float(np.percentile(bs, 95)), 3)]
    return out


def main():
    res = {'pairs': PAIRS, 'all': {}, 'common': {}}
    for m in V:
        pr = [n for n in PAIRS if any(y == n for y, _ in V[m])]
        if len(pr) < len(PAIRS) and m != 'RAPM (1-yr)': pr = [n for n in pr]
        res['all'][m] = score(m, pr, np.random.default_rng(0)) | {'pairs': len(pr)}
    common = [n for n in PAIRS if n <= 2023 and all(any(y == n for y, _ in V[m]) for m in V)]
    res['commonPairs'] = common
    for m in V: res['common'][m] = score(m, common, np.random.default_rng(0))
    rng = np.random.default_rng(1); picks = [rng.choice(PAIRS, len(PAIRS)) for _ in range(2000)]
    Q = {m: {n: team_rows(m, n, True) for n in PAIRS if any(y == n for y, _ in V[m])} for m in V}
    base = [r2(sum((Q['rXPM'][n] for n in pk), [])) for pk in picks]
    for m in V:                                            # paired vs rXPM on the same resampled pairs (all-window metrics)
        if len(Q[m]) < len(PAIRS): continue
        d = np.array([r2(sum((Q[m][n] for n in pk), [])) for pk in picks]) - np.array(base)
        res['all'][m]['vsXPM'] = {'diff': round(float(np.median(d)), 3), 'p_better': round(float((d > 0).mean()), 3)}
    json.dump(res, open(os.path.join(ROOT, 'data', 'nba_xpm_predictive_research.json'), 'w'), indent=1)
    for k in ('all', 'common'):
        print(k, res.get('commonPairs') if k == 'common' else PAIRS)
        for m, v in sorted(res[k].items(), key=lambda t: -t[1]['predict']): print(f'  {m:14s}', v)


if __name__ == '__main__':
    main()
