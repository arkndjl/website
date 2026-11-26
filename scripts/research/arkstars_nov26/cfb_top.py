# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFB top tier (prereg.md): family ELITE (E1 industry top end, E3 position) on the top-64 hit, and the 5-star+ line
by the even-odds rule. History rows from recruits_cfb_nov16/build.py (scripts/.cache/recruit/hist_nov16.pkl).

    python3 scripts/research/recruits_cfb_nov16/build.py && python3 scripts/research/arkstars_nov26/cfb_top.py
"""
import csv
import json
import math
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'recruits_cfb_nov16'))
from common import R, T, rh, USE, hist, t_cluster, p_one, holm   # noqa: E402
from top import loco, line_report, logit                          # noqa: E402

LPKL = os.path.join(R.CACHE, 'lock_nov26.pkl')
TRAIN = list(range(2011, 2022)); FWD = [2022]


def later(cap):
    """the 2020-22 classes linked to the drafts through 2026 (drafted, pick)"""
    if os.path.exists(LPKL): return rh.prep(pickle.load(open(LPKL, 'rb')))
    a, b = cap
    def nfl():
        pe = {x['gsis_id']: x['espn_id'] for x in csv.DictReader(open(os.path.join(T.SP, 'players.csv'))) if x['gsis_id']}
        rows = []
        for r in csv.DictReader(open(os.path.join(T.SP, 'draft_picks.csv'))):
            s = int(r['season'])
            if 2014 <= s <= 2026 and int(r['pick'] or 0) > 0:
                rows.append({'name': r['pfr_player_name'], 'team': r['college'], 'pos': r['position'], 'season': s, 'espn': pe.get(r['gsis_id']) or None,
                             'pick': int(r['pick']), 'av': 0.0, 'cap': max(0.0, a + b * math.log(int(r['pick'])))})
        return rows, cap
    seen = {str(r['id'] or ('rid', r['rid'])) for r in pickle.load(open(os.path.join(R.CACHE, 'hist_nov16.pkl'), 'rb'))[0]}
    keep = T.nfl, T.CLASSES
    T.nfl, T.CLASSES = nfl, range(2020, 2023)
    try: data, how, _ = T.dataset()
    finally: T.nfl, T.CLASSES = keep
    data = [r for r in data if str(r['id'] or ('rid', r['rid'])) not in seen]
    print('later rows', len(data), 'drafted', sum(r['drafted'] for r in data), dict(how))
    pickle.dump(data, open(LPKL, 'wb'))
    return rh.prep(data)


def top_rate(s, hit, cls, classes, n):
    num = den = 0
    for c in classes:
        i = np.where(cls == c)[0]; j = i[np.argsort(-s[i], kind='stable')[:n]]; num += hit[j].sum(); den += len(j)
    return round(float(num / den), 3)


def main():
    H, cap = hist(); L = later(cap); sz = R.size_norms(H)
    p0, f0 = rh.cv(H, USE['on'], USE['fv'], sz); sH = p0 * np.maximum(f0, R.FLOOR) + (1 - p0) * R.FLOOR
    ix = T.index_fit(H, USE, sz)
    pl = R.sig(ix['on']['b0'] + rh.X_of(L, USE['on'], sz) @ np.array(ix['on']['coef'])); fl = ix['fv']['b0'] + rh.X_of(L, USE['fv'], sz) @ np.array(ix['fv']['coef'])
    sL = pl * np.maximum(fl, R.FLOOR) + (1 - pl) * R.FLOOR
    A = H + L; s = np.r_[sH, sL]
    cls = np.array([r['year'] for r in A]); sch = np.array([r['tid'] for r in A]); pk = np.array([r['pick'] or 999 for r in A])
    hit = (pk <= 64).astype(float); h32 = (pk <= 32).astype(float); dr = np.array([float(r['drafted']) for r in A])
    ir = np.array([r.get('indRank') or 0 for r in A], float); ind = np.array([r.get('ind') or 0 for r in A], float)
    lir = np.where((ir > 0) & (ir <= 400), math.log(400) - np.log(np.maximum(ir, 1)), 0.0); hin = np.maximum(0.0, (ind - 95) / 5)
    qb = np.array([1.0 if r['g'] == 'QB' else 0.0 for r in A]); line = np.array([1.0 if r['g'] in ('OL', 'DL', 'EDGE') else 0.0 for r in A])
    pool = np.zeros(len(A), bool); five = np.zeros(len(A), bool); ship = np.zeros(len(A), bool)
    for c in sorted(set(cls)):
        i = np.where(cls == c)[0]; pool[i[np.argsort(-s[i], kind='stable')[:100]]] = True; pool[i[(ir[i] > 0) & (ir[i] <= 100)]] = True
        five[i] = s[i] >= np.quantile(s[i], .985); ship[i[np.argsort(-s[i], kind='stable')[:6]]] = True
    tr = np.isin(cls, TRAIN); m = pool & tr; mf = pool & ~tr
    out = {'n': int(m.sum()), 'hits': int(hit[m].sum()), 'perClass': {int(c): [int((pool & (cls == c)).sum()), int(hit[pool & (cls == c)].sum())] for c in sorted(set(cls))},
           'fwdDrafted': int(dr[cls == 2022].sum())}
    print(out, flush=True)
    X = {'E0': s[:, None], 'E1': np.c_[s, lir, hin], 'E3': np.c_[s, qb, line]}
    P, LL = {}, {}
    for k, x in X.items(): P[k], LL[k] = loco(x, hit, cls, pool, TRAIN, FWD)
    res = {}
    for k in ('E1', 'E3'):
        d = LL['E0'] - LL[k]; by = {int(c): float(d[m & (cls == c)].mean()) for c in TRAIN}; t = t_cluster(d[m], sch[m])
        _, raw = logit(X[k][m], hit[m])
        res[k] = {'ll0': round(float(LL['E0'][m].mean()), 5), 'll1': round(float(LL[k][m].mean()), 5), 'gain': round(float(d[m].mean()), 5), 'tSchool': round(t, 2), 'p': p_one(t),
                  'won': f'{sum(v > 0 for v in by.values())}/{len(by)}', 'byClass': {c: round(v, 5) for c, v in by.items()}, 'forward': round(float(d[mf].mean()), 5),
                  'coef': [round(float(x), 4) for x in raw],
                  'top3': [top_rate(P['E0'], hit, cls, TRAIN, 3), top_rate(P[k], hit, cls, TRAIN, 3)], 'top6': [top_rate(P['E0'], hit, cls, TRAIN, 6), top_rate(P[k], hit, cls, TRAIN, 6)],
                  'fwdTop6': [top_rate(P['E0'], hit, cls, FWD, 6), top_rate(P[k], hit, cls, FWD, 6)]}
    hp = holm({k: res[k]['p'] for k in res})
    for k in res:
        res[k]['holm'] = hp[k]; res[k]['pass'] = bool(hp[k] and int(res[k]['won'].split('/')[0]) >= 8 and res[k]['forward'] >= 0); print(k, res[k], flush=True)
    out.update(res)
    out['rates'] = {'QB': round(float(hit[m & (qb == 1)].mean()), 3), 'line': round(float(hit[m & (line == 1)].mean()), 3), 'other': round(float(hit[m & (qb == 0) & (line == 0)].mean()), 3),
                    'industryTop6': top_rate(-np.where(ir > 0, ir, 9999), hit, cls, TRAIN, 6), 'industryTop3': top_rate(-np.where(ir > 0, ir, 9999), hit, cls, TRAIN, 3)}
    win = 'E1' if res['E1']['pass'] else 'E0'
    if res['E3']['pass']: win = 'E3' if win == 'E0' else 'E1+E3'
    if win == 'E1+E3': X[win] = np.c_[s, lir, hin, qb, line]; P[win], LL[win] = loco(X[win], hit, cls, pool, TRAIN, FWD)
    out['score'] = win
    out['line'] = line_report(s, P[win], hit, cls, pool, TRAIN, FWD, ship, five, extra={'top32': h32, 'drafted': dr}, X=X[win])
    rk = np.zeros(len(A), int)
    for c in set(cls):
        i = np.where(cls == c)[0]; rk[i[np.argsort(-s[i], kind='stable')]] = np.arange(1, len(i) + 1)
    out['byPlace'] = {f'{a}-{b}': {'n': int((tr & (rk >= a) & (rk <= b)).sum()), 'top64': round(float(hit[tr & (rk >= a) & (rk <= b)].mean()), 3)}
                      for a, b in ((1, 1), (2, 3), (4, 6), (7, 10), (11, 15), (16, 20), (21, 30), (31, 40))}
    L_ = out['line']
    for k in ('new', 'shipped', 'plainUnderNew', 'plainUnderShipped', 'newByClass', 'lineScore', 'lineScoreCi90', 'calibration', 'forward', 'rule'): print(k, L_.get(k))
    print(out['byPlace'], out['rates'])
    json.dump(out, open(os.path.join(HERE, 'cfb_top.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
