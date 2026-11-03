#!/usr/bin/env python3
"""Per board row (Barttorvik pid, board season) projected NBA position for other threads' frame tests, class-out:
each row's model is refit without the player's own draft class (last college season), on the live features
(scripts/cbb_nbapos.py), from his college seasons before the board season.  -> /mnt/project-files/cbb/nbapos/proj_pos.csv"""
import csv, gzip, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_nbapos as NP, cbb_data as D
careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
fit = json.load(open(NP.OUT)); N = fit['norms']
est = defaultdict(list)
for r in json.load(gzip.open(NP.EST, 'rt')): est[r['bref']].append(r)
lab = []
for c in careers:
    b = c['nba'].get('bref'); end = c['seasons'][-1]['year']
    if not b or b not in est: continue
    ss = sorted((r for r in est[b] if r['year'] > end), key=lambda r: r['year'])[:NP.NBA_SEASONS]; mp = sum(r['mp'] for r in ss)
    if mp < NP.MIN_NBA_MP: continue
    y = np.array([sum(r['mp'] * r['pct'][k] for r in ss) / mp for k in range(5)]); y /= y.sum()
    seas = [s for s in c['seasons'] if (s['mp'] or 0) * (s['gp'] or 0) >= NP.MIN_COL_MPT and s['hti']]
    if seas: lab.append((end, y, [NP.season_feats(s) for s in seas]))
models = {}
for k in sorted({e for e, _, _ in lab}) + ['all']:
    R, Y, W = [], [], []
    for e, y, fs in lab:
        if e == k: continue
        for f in fs: R.append(f); Y.append(y); W.append(1 / len(fs))
    X = NP.design(R); mu, sd = X.mean(0), X.std(0) + 1e-9
    models[k] = (NP.fit_mnl((X - mu) / sd, np.array(Y), np.array(W), NP.LAM), mu, sd)
mix = lambda p, key: float(p @ np.array(N[key]['mean'])) if key in N else None
out = '/mnt/project-files/cbb/nbapos/proj_pos.csv'
with open(out, 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['pid', 'year', 'name', 'p_PG', 'p_SG', 'p_SF', 'p_PF', 'p_C', 'epos', 'ht_listed', 'ht_norm_listed', 'ht_np', 'ht_npz',
                'ht_norm_combine', 'wt_norm_combine', 'bmi_norm_combine', 'wing_norm_combine', 'nba_label_known'])
    n = 0
    for c in careers:
        B, mu, sd = models.get(c['last'], models['all'])
        for i, s in enumerate(c['seasons']):
            if i == 0: continue
            f = NP.pooled(c['seasons'][:i]); f['ht'] = s['hti'] or f['ht']
            p = NP.softmax(np.hstack([np.ones((1, 1)), (NP.design([f]) - mu) / sd]) @ B)[0]
            hn = mix(p, 'htListed'); np_ = f['ht'] - hn
            w.writerow([c['pid'], s['year'], c['name']] + [round(float(v), 4) for v in p] + [round(float(p @ np.arange(1, 6)), 3), f['ht'], round(hn, 2),
                       round(np_, 2), round(np_ / N['htListed']['pooledSd'], 3)] + [round(mix(p, k), 2) if mix(p, k) is not None else '' for k in
                       ('htCombine', 'wtCombine', 'bmiCombine', 'wingCombine')] + [1 if c['nba'].get('bref') in est else 0])
            n += 1
print(n, 'rows ->', out, '| pooled within-position sd:', {k: v['pooledSd'] for k, v in N.items()})
