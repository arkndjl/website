# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family CB: six additions to the CBB commitment LIST model (scripts/recruit_commit_fit.py), walk-forward by class."""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import names as N                 # noqa: E402
import recruit_commit_fit as M    # noqa: E402

OUT = '/mnt/project-files/recruits/cbb-nov16'
KIT = '/mnt/project-files/cbb/kit/college_seasons_nba.csv'
ALIAS = {'UL Monroe': 'Louisiana Monroe', 'Texas A&M-Corpus Christi': 'Texas A&M Corpus Chris', 'Grambling': 'Grambling St.', 'Kansas City': 'UMKC',
         'St. Francis Brooklyn': 'St. Francis NY', 'IU Indianapolis': 'IUPUI', 'Pennsylvania': 'Penn', 'SE Louisiana': 'Southeastern Louisiana',
         'UT Martin': 'Tennessee Martin', 'LSU New Orleans': 'New Orleans', 'App State': 'Appalachian St.', 'NE Illinois': 'Northeastern Illinois',
         'UAlbany': 'Albany', 'Loyola Maryland': 'Loyola MD', 'Nicholls': 'Nicholls St.', 'Sam Houston': 'Sam Houston St.', 'McNeese': 'McNeese St.',
         'South Carolina Upstate': 'USC Upstate', 'Omaha': 'Nebraska Omaha', 'UIC': 'Illinois Chicago'}
GROUP = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'W', 'Wing F': 'W', 'Stretch 4': 'B', 'PF/C': 'B', 'C': 'B'}
RPOS = {'PG': 'G', 'SG': 'G', 'SF': 'W', 'PF': 'B', 'C': 'B'}
BASE = ['pull', 'tier', 'gxt', 'gap', 'ld', 'inst']
NEW = ['str', 'str_g', 'picks', 'picks_g', 'open', 'local']
TESTS = {'K1': ['str'], 'K2': ['str', 'str_g'], 'K3': ['picks', 'picks_g'], 'K4': ['open'], 'K5': ['local']}


def tables():
    H = json.load(gzip.open(os.path.join(M.ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz'), 'rt'))
    espn = {k: v for k, v in json.load(open(os.path.join(M.CACHE, 'cbb-teams.json'))).items() if v}
    bart = set()
    for v in H['teams'].values(): bart |= set(v)
    bk = {N.team_key(x): x for x in bart}
    tmap = {k: (ALIAS.get(v['name']) if ALIAS.get(v['name']) in bart else bk.get(N.team_key(v['name']))) for k, v in espn.items()}
    last = {}; mins = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for r in csv.DictReader(open(KIT)):
        y = int(r['year'])
        if r['nba_draft'] and r['nba_pick'] and (r['pid'] not in last or y > last[r['pid']][0]): last[r['pid']] = (y, r['team'], int(float(r['nba_draft'])))
        g = GROUP.get(r['role'])
        if g and r['min_per']:
            mp = float(r['min_per'])
            for k in (g, 'all'):
                mins[(y, r['team'])][k][0] += mp
                if r['yr'] in ('Jr', 'Sr'): mins[(y, r['team'])][k][1] += mp
    picks = defaultdict(int)
    for _, team, dy in last.values(): picks[(dy, team)] += 1
    return H['teams'], tmap, picks, mins


TEAMS, TMAP, PICKS, MINS = tables()
_stats0 = M.school_stats


def school_stats(cls, y, loc): return _stats0(cls, y, loc) + (y,)


def feats(x, alts, st, loc):
    n, tier, bys, y = st
    F = []
    for t in alts:
        lat, lon, sst, _ = loc[t]
        mi = M.miles(x['home'], (lat, lon)); ld = math.log1p(mi / 100); tr = tier.get(t, -1.0)
        b = TMAP.get(t)
        s = TEAMS.get(str(y - 1), {}).get(b, 0.0) if b else 0.0
        pk = math.log1p(sum(PICKS.get((d, b), 0) for d in range(y - 5, y))) if b else 0.0
        m = MINS.get((y - 1, b)) if b else None
        g = RPOS.get(x['pos'])
        if m and g and m[g][0] > 0: op = m[g][1] / m[g][0]
        elif m and m['all'][0] > 0: op = m['all'][1] / m['all'][0]
        else: op = 0.5
        F.append([math.log1p(n.get(t, 0)), tr, x['g'] * tr, abs(x['g'] - tr), ld, float(sst == x['st']),
                  s, s * x['g'], pk, pk * x['g'], op, float(mi <= 50)])
    return np.array(F)


M.school_stats, M.feats, M.COLS = school_stats, feats, BASE + NEW


def fit_w(X, yv, cols, w, lam=M.LAM):
    """M.fit with a weight a recruit"""
    idx = [M.COLS.index(c) for c in cols]
    A = np.vstack([x[:, idx] for x in X]); mu, sd = A.mean(0), A.std(0) + 1e-9
    off = np.cumsum([0] + [len(x) for x in X]); Zs = (A - mu) / sd; ch = off[:-1] + yv; n = np.diff(off); b = np.zeros(len(idx))
    wr = np.repeat(w, n)
    def obj(b):
        u = Zs @ b; m = np.maximum.reduceat(u, off[:-1]); e = np.exp(u - np.repeat(m, n)); s = np.add.reduceat(e, off[:-1])
        return -(w * (u[ch] - m - np.log(s))).sum() + lam * b @ b, e / np.repeat(s, n)
    f0, p = obj(b)
    for _ in range(100):
        zb = np.add.reduceat(p[:, None] * Zs, off[:-1])
        gr = (w[:, None] * Zs[ch]).sum(0) - (w[:, None] * zb).sum(0) - 2 * lam * b
        Hm = ((wr * p)[:, None] * Zs).T @ Zs - (w[:, None] * zb).T @ zb + 2 * lam * np.eye(len(b))
        step, a = np.linalg.solve(Hm, gr), 1.0
        while a > 1e-6:
            f1, p1 = obj(b + a * step)
            if f1 <= f0 + 1e-10: break
            a /= 2
        b, f0, p = b + a * step, f1, p1
        if np.abs(a * step).max() < 1e-8: break
    return {'cols': cols, 'b': (b / sd).tolist(), 'mu': mu.tolist(), 'sd': sd.tolist(), 'b_std': b.tolist()}


def main():
    loc, cls = M.load('cbb')
    print('schools mapped', sum(1 for t in loc if TMAP.get(t)), 'of', len(loc))
    res = defaultdict(lambda: defaultdict(list)); start = M.YEARS['cbb'][0] + 3
    for y in M.HELD['cbb']:
        Xt, yt, mt = M.build('cbb', loc, cls, range(start, y), 'list', True)
        Xh, yh, _ = M.build('cbb', loc, cls, [y], 'list', False)
        if not len(yh): continue
        models = {'base': M.fit(Xt, yt, BASE)}
        for k, add in TESTS.items(): models[k] = M.fit(Xt, yt, BASE + add)
        w = np.array([0.5 ** ((y - 1 - m[0]) / 4) for m in mt]); models['K6'] = fit_w(Xt, yt, BASE, w * len(w) / w.sum())
        for k, m in models.items():
            ll, br, t1, t3 = M.score(m, Xh, yh)
            res[k]['ll'].append(ll); res[k]['t1'].append(t1); res[k]['yr'].append(np.full(len(ll), y))
        print(y, len(yh), {k: round(float(res[k]['ll'][-1].mean()), 4) for k in models}, flush=True)
    R = {k: {kk: np.concatenate(v) for kk, v in d.items()} for k, d in res.items()}
    out = {'n': int(len(R['base']['ll'])), 'base': {'ll': round(float(R['base']['ll'].mean()), 4), 'top1': round(float(R['base']['t1'].mean()), 4)}, 'tests': {}}
    for k in list(TESTS) + ['K6']:
        g = M.gate(R['base'], R[k]); g['top1'] = round(float(R[k]['t1'].mean()), 4); g['ll'] = round(float(R[k]['ll'].mean()), 4)
        out['tests'][k] = g; print(k, {a: (round(b, 5) if isinstance(b, float) else b) for a, b in g.items() if a != 'byClass'})
    Xa, ya, _ = M.build('cbb', loc, cls, range(start, max(M.HELD['cbb']) + 1), 'list', True)
    out['coef'] = {k: dict(zip(BASE + add, [round(v, 4) for v in M.fit(Xa, ya, BASE + add)['b_std']])) for k, add in TESTS.items()}
    json.dump(out, open(os.path.join(OUT, 'cb_tests.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
