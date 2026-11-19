#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 1a: the ESPN-built point-in-time season line against the frozen Barttorvik line, through the board's FV model.
Pre-registered in impl/cbb/prereg.md. Needs scripts/.cache/cbb/careers.json and scripts/cbb_box_hist.py builds.

    python3 scripts/research/sweep_nov19/cbb/parity.py
"""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import names as NM
import cbb_data as D
import cbb_fit as F
import cbb_live as L
import cbb_role as ROLE
import cbb_box_hist as BH

OUT = os.environ.get('OUT', '/mnt/project-files/research-sweep-nov19/impl/cbb/parity_results.json')
FIT = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
RECON = json.load(open(L.LIVE_FIT))['recon']
C = L.C


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    res = {}
    for Y in range(2014, 2027):
        try:
            logs = json.load(gzip.open(os.path.join(BH.PIT, f'{Y}.json.gz')))
        except OSError:
            continue
        by_team, tdates = defaultdict(lambda: defaultdict(list)), defaultdict(set)
        for r in logs:
            by_team[r[C['team']]][r[C['pid']]].append(r); tdates[r[C['team']]].add(r[C['date']])
        match = {t: NM.Matcher([{'pid': p, 'name': rs[0][C['name']]} for p, rs in v.items()], team=None, pos=None, sport='basketball') for t, v in by_team.items()}
        fb, fe, keep, bp = [], [], [], []
        n_all = 0
        allrows = []
        for c in careers:
            ss = [s for s in c['seasons'] if s['year'] <= Y]
            if not ss or ss[-1]['year'] != Y: continue
            s = ss[-1]
            if (s.get('mp') or 0) * (s.get('gp') or 0) < 200 or s.get('bpm') is None: continue
            cc = dict(c, seasons=ss)
            nb = L.next_career(cc, {k: s.get(k) for k in L.KEEP})
            f0 = F.features(nb, len(nb['seasons']) - 1)
            n_all += 1
            m = match.get(s['team'])
            hit, _ = m.find(c['name']) if m else (None, None)
            f1 = None
            if hit:
                rs = sorted(by_team[s['team']][hit['pid']], key=lambda g: g[C['date']])
                a = L.summed(rs, len(tdates[s['team']]))
                if a['mp'] * a['gp'] > 0:
                    ln = L.line(a, RECON, {'team': s['team'], 'conf': s.get('conf'), 'yr': s.get('yr'), 'hti': s.get('hti'), 'rec': s.get('rec'), 'year': Y})
                    ln['role'] = ROLE.predict(ln, s.get('hti')) or s.get('role')
                    ne = L.next_career(cc, ln)
                    f1 = F.features(ne, len(ne['seasons']) - 1)
                    bp.append((s['bpm'], ln['bpm'], s['mp'] * s['gp'], a['mp'] * a['gp']))
            allrows.append((c['pid'], f0, f1))
        e0 = L.score_many([r[1] for r in allrows], FIT)[0]
        ix = [i for i, r in enumerate(allrows) if r[2] is not None]
        e1 = np.full(len(allrows), -np.inf)
        e1[ix] = L.score_many([allrows[i][2] for i in ix], FIT)[0]
        top0 = set(np.argsort(-e0)[:50].tolist()); top1 = set(np.argsort(-e1)[:50].tolist())
        bp = np.array(bp)
        res[Y] = {'rows': n_all, 'matched': len(ix), 'share': round(len(ix) / max(1, n_all), 3), 'spearman': round(F.spearman(e0[ix], e1[ix]), 4),
                  'pearson': round(float(np.corrcoef(e0[ix], e1[ix])[0, 1]), 4), 'top50': len(top0 & top1),
                  'top50_matched_only': len(set(np.argsort(-np.where(e1 > -np.inf, e0, -np.inf))[:50].tolist()) & top1),
                  'bpm_r': round(float(np.corrcoef(bp[:, 0], bp[:, 1])[0, 1]), 4), 'bpm_rmse': round(float(np.sqrt(((bp[:, 0] - bp[:, 1]) ** 2).mean())), 3),
                  'min_ratio': round(float(bp[:, 3].sum() / bp[:, 2].sum()), 3), 'mean_abs_dE': round(float(np.abs(e0[ix] - e1[ix]).mean()), 3)}
        print(Y, res[Y], flush=True)
    sp = [v['spearman'] for v in res.values()]; tp = [v['top50'] for v in res.values()]
    out = {'bySeason': res, 'median_spearman': round(float(np.median(sp)), 4), 'mean_top50': round(float(np.mean(tp)), 2)}
    out['pass'] = bool(out['median_spearman'] >= 0.98 and out['mean_top50'] >= 45)
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'bySeason'}))


if __name__ == '__main__':
    main()
