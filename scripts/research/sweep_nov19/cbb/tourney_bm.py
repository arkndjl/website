#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 2: Bracket Matrix final consensus stacked on the committee model (seed line, at-large bid).
Pre-registered in impl/cbb/prereg.md. The game walk reads the ESPN-built point-in-time logs (scripts/cbb_box_hist.py).

    OMP_NUM_THREADS=1 python3 scripts/research/sweep_nov19/cbb/tourney_bm.py DIR_WITH_MATRIX_PAGES
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import names as NM
import cbb_games as C
import cbb_box_hist as BH
C.BTLOG = BH.PIT
import cbb_tourney as T
import bracket_matrix as BM

OUT = os.environ.get('OUT', '/mnt/project-files/research-sweep-nov19/impl/cbb/tourney_bm_results.json')
TUNE, HELD = [2015, 2016, 2017, 2018, 2019], [2021, 2022, 2023, 2024, 2025, 2026]
SIGS = (0.5, 0.7, 0.8, 0.9, 1.0, 1.2)


def ct(d, g):
    s = defaultdict(float)
    for x, k in zip(d, g): s[k] += x
    v = np.array(list(s.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))


def seed_ll(rs, pred, sig, s):
    """T.fit_seeds' scoring: log loss of each team's real line under the simulated S-curve"""
    al = {r['t'] for r in rs if not r['auto']}
    cnt = defaultdict(lambda: np.zeros(16))
    g = np.random.default_rng(s)
    for _ in range(400):
        z = {r['t']: -pred[r['t']] + sig * g.normal() for r in rs}
        _, seed = T.bracket_slots(z, al)
        for t, line in seed.items(): cnt[t][line - 1] += 1
    out, hit = [], []
    for r in rs:
        p = (cnt[r['t']] + 0.05) / (cnt[r['t']].sum() + 0.8)
        out.append(-math.log(p[r['seed'] - 1])); hit.append(float(np.argmax(p) + 1 == r['seed']))
    return np.array(out), np.array(hit)


def attach(R, d):
    games = C.load_hist()
    nm = {}
    for g in games:
        nm[g['home']] = g['hn']; nm[g['away']] = g['an']
    miss = []
    for s in sorted({r['s'] for r in R}):
        p = os.path.join(d, f'matrix_{s}.html')
        if not os.path.exists(p): continue
        rows = BM.parse(p)
        rs = [r for r in R if r['s'] == s]
        left = list(rs)
        for x in rows:
            pool = [r for r in left if (x['seed'] is None or r['seed'] == x['seed'])]
            hit = [r for r in pool if NM.same_team(nm.get(r['t'], ''), x['team'])]
            if len(hit) != 1:
                k = NM.team_key(x['team'])
                hit = [r for r in pool if NM.team_key(nm.get(r['t'], '')) == k]
            if len(hit) == 1:
                hit[0]['bm'] = x['avg']; hit[0]['share'] = x['share']; left.remove(hit[0])
            else:
                miss.append((s, x['team'], x['seed']))
        for r in rs:
            r.setdefault('bm', None); r.setdefault('share', 0.0)
    return miss


def main():
    P, rows, margin = T.prepare()
    R = T.sel_rows(P)
    miss = attach(R, sys.argv[1])
    F = json.load(open(T.FIT))
    seed_f, sel_f, sig0 = F['seeding']['feats'], F['selection']['feats'], F['seeding']['sigma']
    seasons = sorted({r['s'] for r in R})
    out = {'unmatched_matrix_rows': miss, 'seed_feats': seed_f, 'sel_feats': sel_f, 'sigma_shipped': sig0}
    # ---------------- seeds
    fld = [r for r in R if r['bid']]
    for s in seasons:                         # the shipped committee line, held out by season
        tr = [r for r in fld if r['s'] != s]
        M = T.moments(tr, seed_f)
        X = np.array([[1.0] + [(r[f] - M[f][0]) / M[f][1] for f in seed_f] for r in tr])
        b = np.linalg.lstsq(X, np.array([r['seed'] for r in tr], float), rcond=None)[0]
        for r in fld:
            if r['s'] == s: r['line'] = float(b[0] + sum(b[j + 1] * (r[f] - M[f][0]) / M[f][1] for j, f in enumerate(seed_f)))
    out['field_with_matrix'] = round(float(np.mean([r['bm'] is not None for r in fld])), 3)
    base = {s: seed_ll([r for r in fld if r['s'] == s], {r['t']: r['line'] for r in fld if r['s'] == s}, sig0, s) for s in seasons}

    def stack(train):
        tr = [r for r in fld if r['s'] in train]
        X = np.array([[1.0, r['line'], r['bm'] if r['bm'] is not None else r['line']] for r in tr])
        b = np.linalg.lstsq(X, np.array([r['seed'] for r in tr], float), rcond=None)[0]
        pr = lambda r: float(b[0] + b[1] * r['line'] + b[2] * (r['bm'] if r['bm'] is not None else r['line']))
        best = None
        for sig in SIGS:
            m = np.mean(np.concatenate([seed_ll([r for r in tr if r['s'] == s], {r['t']: pr(r) for r in tr if r['s'] == s}, sig, s)[0] for s in train]))
            if best is None or m < best[0]: best = (m, sig)
        return b, best[1], pr
    b, sig, pr = stack(TUNE)
    d, g, per = [], [], {}
    for s in HELD:
        rs = [r for r in fld if r['s'] == s]
        l1, h1 = seed_ll(rs, {r['t']: pr(r) for r in rs}, sig, s)
        l0, h0 = base[s]
        d += list(l1 - l0); g += [s] * len(rs)
        per[s] = [round(float(l0.mean()), 4), round(float(l1.mean()), 4), round(float(h0.mean()), 3), round(float(h1.mean()), 3)]
    lo = []
    for s in TUNE:
        b2, sig2, pr2 = stack([x for x in TUNE if x != s])
        rs = [r for r in fld if r['s'] == s]
        lo.append(round(float(seed_ll(rs, {r['t']: pr2(r) for r in rs}, sig2, s)[0].mean() - base[s][0].mean()), 4))
    out['seed'] = {'b': [round(float(x), 4) for x in b], 'sigma': sig, 'held_bySeason_ll0_ll1_exact0_exact1': per, 'held_d': round(float(np.mean(d)), 4),
                   'held_t_season': round(ct(d, g), 2), 'held_better': int(sum(per[s][1] < per[s][0] for s in HELD)), 'tune_loso_d': lo, 'n': len(d)}
    out['seed']['pass'] = bool(out['seed']['held_t_season'] <= -2 and out['seed']['held_better'] >= 4 and sum(lo) < 0)
    print(json.dumps(out['seed']), flush=True)
    # ---------------- at-large
    cand = [r for r in R if not r['auto']]
    for s in seasons:
        tr = [r for r in cand if r['s'] != s]
        M = T.moments(tr, sel_f)
        bb = T.logit_fit(np.array([[(r[f] - M[f][0]) / M[f][1] for f in sel_f] for r in tr]), np.array([r['bid'] for r in tr]))
        for r in cand:
            if r['s'] == s: r['sc'] = float(bb[0] + sum(bb[j + 1] * (r[f] - M[f][0]) / M[f][1] for j, f in enumerate(sel_f)))

    def bid_ll(rs, sc, s):
        k = int(sum(r['bid'] for r in rs))
        p = T.topk_p(np.array(sc), k, np.ones(len(rs), bool), np.random.default_rng(s))
        return np.array(T.ll(p, [r['bid'] for r in rs]))

    def bstack(train):
        tr = [r for r in cand if r['s'] in train]
        bb = T.logit_fit(np.array([[r['sc'], r['share']] for r in tr]), np.array([r['bid'] for r in tr]))
        return bb
    bb = bstack(TUNE)
    d, g, per = [], [], {}
    for s in HELD:
        rs = [r for r in cand if r['s'] == s]
        l0 = bid_ll(rs, [r['sc'] for r in rs], s); l1 = bid_ll(rs, [bb[0] + bb[1] * r['sc'] + bb[2] * r['share'] for r in rs], s)
        d += list(l1 - l0); g += [s] * len(rs); per[s] = [round(float(l0.mean()), 4), round(float(l1.mean()), 4)]
    lo = []
    for s in TUNE:
        b2 = bstack([x for x in TUNE if x != s])
        rs = [r for r in cand if r['s'] == s]
        lo.append(round(float(bid_ll(rs, [b2[0] + b2[1] * r['sc'] + b2[2] * r['share'] for r in rs], s).mean() - bid_ll(rs, [r['sc'] for r in rs], s).mean()), 4))
    out['bid'] = {'b': [round(float(x), 4) for x in bb], 'held_bySeason_ll0_ll1': per, 'held_d': round(float(np.mean(d)), 4), 'held_t_season': round(ct(d, g), 2),
                  'held_better': int(sum(per[s][1] < per[s][0] for s in HELD)), 'tune_loso_d': lo, 'n': len(d)}
    out['bid']['pass'] = bool(out['bid']['held_t_season'] <= -2 and out['bid']['held_better'] >= 4 and sum(lo) < 0)
    print(json.dumps(out['bid']), flush=True)
    json.dump(out, open(OUT, 'w'), indent=1)
    print('unmatched', miss)


if __name__ == '__main__':
    main()
