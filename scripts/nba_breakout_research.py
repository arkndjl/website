# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA Potential Breakout research: usage scaling and breakout signals, leave-one-season-out (scripts/breakout_lib.py).

    python3 scripts/nba_breakout_research.py [laker_history.json]   # -> data/nba_breakout_fit.json

History: nbarapm.com LAKER_history regular-season rows 1990-2026 (bbref box rates: usage %, TS+, TOV %, BPM, ...),
project files nba-metrics/raw/load_LAKER_history.json. Traded players' stints are pooled by minutes.

A. Usage scaling. Pairs of seasons (400+ MP both), weight = the smaller MP. Next-season TS+ (and TOV %) on this
   season's (shrunk by MP) + age + usage, then + the usage change (dU), then + dU x traits. Held-out error on all pairs
   and on the pairs whose usage rose 3+ points (the case the tab projects).
B. Breakout odds. Rows: 300+ MP this season. Breakout = next season 1000+ MP and BPM 2+ over his established level:
   the higher of this season's BPM shrunk to -2 by MP (k 600) and his 3-season Marcel (a healthy star's bounce-back
   is not a breakout). Baseline logistic: shrunk BPM, ln MP. Candidates one at a time, then the passers
   together."""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nba_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = '/mnt/project-files/nba-metrics/raw/load_LAKER_history.json'
OUT = os.path.join(ROOT, 'data', 'nba_breakout_fit.json')
Y0 = 1990
RATE = ('usage_pct', 'ts_plus', 'tov_pct', 'ast_pct', 'ftr_plus', 'threepar_plus', 'fg3_plus', 'ft_plus', 'bpm',
        'obpm', 'dbpm', 'points_per_100', 'orb_pct', 'drb_pct', 'c_pct', 'pf_pct', 'pg_pct', 'sg_pct', 'fg2_plus')
K_SHR = 600.0
BPM_REP = -2.0


def seasons(src):
    rows = [r for r in json.load(open(src)) if r['season_type'] == 'RS' and r['year'] >= Y0 - 3]
    by = defaultdict(list)
    for r in rows:
        if r['minutes'] and r['minutes'] > 0:
            by[(r['player_id'], r['year'])].append(r)
    P = {}
    for (pid, y), rs in by.items():
        mp = sum(r['minutes'] for r in rs)
        o = {'pid': pid, 'y': y, 'n': rs[0]['player_name'], 'age': rs[0]['age'], 'mp': mp,
             'fr': max(rs, key=lambda r: r['minutes'])['franchise']}
        for k in RATE:
            v = [(float(r[k]), r['minutes']) for r in rs if isinstance(r.get(k), (int, float))]
            o[k] = sum(a * b for a, b in v) / sum(b for _, b in v) if v else 0.0
        P[(pid, y)] = o
    return P


def shr(bpm, mp):
    return (bpm * mp + BPM_REP * K_SHR) / (mp + K_SHR)


def vacated(P):
    """share of a franchise's usage-minutes this season from players not on it next season (the max-MP team)"""
    tot, gone = defaultdict(float), defaultdict(float)
    for (pid, y), o in P.items():
        um = o['usage_pct'] * o['mp']
        tot[(o['fr'], y)] += um
        nx = P.get((pid, y + 1))
        if nx is None or nx['fr'] != o['fr']:
            gone[(o['fr'], y)] += um
    V = {}
    for (pid, y), o in P.items():
        k = (o['fr'], y)
        nx = P.get((pid, y + 1))
        own = o['usage_pct'] * o['mp'] if (nx is None or nx['fr'] != o['fr']) else 0.0
        V[(pid, y)] = (gone[k] - own) / tot[k] if tot[k] else 0.0
    return V


def marcel(P, pid, y):
    num = den = 0.0
    for lag, w in ((0, 5), (1, 4), (2, 3)):
        o = P.get((pid, y - lag))
        if o:
            num += w * o['bpm'] * o['mp']
            den += w * o['mp']
    return (num + BPM_REP * 1000) / (den + 1000)


# ---------- A. usage scaling ----------
def scaling(P, HT):
    """contextual usage scaling: next-season rate on this season's + dU + dU x context blocks (scripts/nba_breakout.py
    builds the same columns for the live board), ridge strength picked inside each training fold"""
    R = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if y < Y0 or not b or a['mp'] < 400 or b['mp'] < 400:
            continue
        R.append((pid, y, a, b))
    S = np.array([y + 1 for _, y, _, _ in R], float)
    w = np.array([min(a['mp'], b['mp']) for _, _, a, b in R], float)
    du = np.array([b['usage_pct'] - a['usage_pct'] for _, _, a, b in R])
    out = {}
    for tgt in B.TARGETS:
        y = np.array([b[tgt] for _, _, a, b in R])
        F = np.array([B.features(tgt, a, B.history(P, pid, yy), HT.get(pid), d)
                      for (pid, yy, a, b), d in zip(R, du)])
        cols = B.columns(tgt)
        ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
        base_c = B.BASE
        sets = {'base': base_c, 'dU': base_c + ['dU']}
        for blk, traits in B.BLOCKS.items():
            sets[blk] = base_c + ['dU'] + sum([['dU*' + t, t] for t in traits], [])
        sets['full'] = cols
        up3, up6 = du >= 3, du >= 6
        res = {k: {} for k in ('all', 'up3', 'up6')}
        for nm, cs in sets.items():
            X = F[:, ix(cs)]

            def fp(trn, te, X=X):
                lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
                b0, b = L.wls(X[trn], y[trn], w[trn], lam)
                return b0 + X[te] @ b
            preds = {}

            def err_m(m):
                def e(p, te):
                    mm = m[te]
                    return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
                return e
            for key, m in (('all', np.ones(len(y), bool)), ('up3', up3), ('up6', up6)):
                res[key][nm] = L.loso(S, fp, err_m(m))
        cmp = {'dU vs base (all)': L.compare(res['all']['base'], res['all']['dU']),
               'dU vs base (rose 3+)': L.compare(res['up3']['base'], res['up3']['dU']),
               'full vs base (all)': L.compare(res['all']['base'], res['all']['full']),
               'full vs base (rose 3+)': L.compare(res['up3']['base'], res['up3']['full']),
               'full vs base (rose 6+)': L.compare(res['up6']['base'], res['up6']['full']),
               'full vs dU (rose 3+)': L.compare(res['up3']['dU'], res['up3']['full'])}
        blocks = {k: L.compare(res['up3']['dU'], res['up3'][k]) for k in B.BLOCKS}
        L.holm(blocks)
        keep = [k for k in B.BLOCKS if blocks[k]['pass']]
        fin = base_c + ['dU'] + sum([sum([['dU*' + t, t] for t in B.BLOCKS[k]], []) for k in keep], [])
        X = F[:, ix(fin)]

        def fpf(trn, te):
            lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
            b0, b = L.wls(X[trn], y[trn], w[trn], lam)
            return b0 + X[te] @ b

        def e_all(p, te):
            return (float((w[te] * (y[te] - p) ** 2).sum()), float(w[te].sum()))

        def e_up(p, te):
            mm = up3[te]
            return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
        cmp['kept vs base (all)'] = L.compare(res['all']['base'], L.loso(S, fpf, e_all))
        cmp['kept vs base (rose 3+)'] = L.compare(res['up3']['base'], L.loso(S, fpf, e_up))
        lam = pick_lam(X, y, w, S)
        b0, b = L.wls(X, y, w, lam)
        out[tgt] = {'n': len(R), 'n_up3': int(up3.sum()), 'n_up6': int(up6.sum()), 'tests': cmp, 'blocks': blocks,
                    'keep': keep, 'lam': lam, 'fit': {'b0': round(b0, 5), 'cols': fin,
                                                       'b': [round(float(v), 7) for v in b]}}
        print(tgt, flush=True)
        for k, v in cmp.items():
            print('  ', k, v, flush=True)
        for k, v in blocks.items():
            print('   block', k, v, flush=True)
    return out


LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1)


def pick_lam(X, y, w, S):
    """ridge strength from an inner split of the training seasons (every third season held out)"""
    u = sorted(set(S.tolist()))
    hold = np.isin(S, u[1::3])
    best, bl = None, LAMS[0]
    for lam in LAMS:
        b0, b = L.wls(X[~hold], y[~hold], w[~hold], lam)
        e = float((w[hold] * (y[hold] - b0 - X[hold] @ b) ** 2).sum())
        if best is None or e < best:
            best, bl = e, lam
    return bl


# ---------- B. breakout odds ----------
def breakout(P, V):
    R = []
    for (pid, y), a in P.items():
        if y < Y0 or y >= 2026 or a['mp'] < 300:
            continue
        b = P.get((pid, y + 1))
        s0 = shr(a['bpm'], a['mp'])
        mar = marcel(P, pid, y)
        hit = 1.0 if (b and b['mp'] >= 1000 and b['bpm'] >= max(s0, mar) + 2) else 0.0
        R.append((a, s0, hit, V[(pid, y)], mar))
    S = np.array([a['y'] + 1 for a, *_ in R], float)
    y = np.array([h for _, _, h, _, _ in R])
    rows = [B.bo_feats(a, s0, v, m) for a, s0, _, v, m in R]
    base = np.array([r['base'] for r in rows])
    cands = {k: np.array([r[k] for r in rows]) for k in B.BO_CANDS}

    def run(X):
        def fp(trn, te):
            b0, b = L.logit(X[trn], y[trn])
            return L.sig(b0 + X[te] @ b)

        def err(p, te):
            p = np.clip(p, 1e-6, 1 - 1e-6)
            return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))
        return L.loso(S, fp, err)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, X]))) for k, X in cands.items()}
    L.holm(res)
    keep = [k for k in cands if res[k]['pass']]
    X = np.column_stack([base] + [cands[k] for k in keep])
    final = L.compare(rb, run(X))
    b0, b = L.logit(X, y)
    p = L.sig(b0 + X @ b)
    cal = []
    for lo, hi in ((0, .05), (.05, .1), (.1, .2), (.2, .35), (.35, 1)):
        m = (p >= lo) & (p < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(p[m].mean()), 3), round(float(y[m].mean()), 3)])
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y), flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    return {'n': len(y), 'rate': round(float(y.mean()), 4), 'tests': res, 'keep': keep, 'final': final,
            'calib': cal, 'fit': {'b0': round(b0, 5), 'b': [round(float(v), 6) for v in b],
                                  'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    P = seasons(src)
    V = vacated(P)
    HT = json.load(open(os.path.join(ROOT, 'scripts', 'nba_htwt.json')))
    A = scaling(P, HT)
    B = breakout(P, V)
    # league constant: points per 100 = 2 x TS+/100 x (1 - TOV%) x USG x K (K = league TS x plays per 100, by season)
    K = {}
    for y in range(2020, 2027):
        v = [o['points_per_100'] / (2 * o['ts_plus'] / 100 * (1 - o['tov_pct'] / 100) * o['usage_pct'] / 100)
             for o in P.values() if o['y'] == y and o['mp'] > 500 and o['usage_pct'] > 0]
        K[y] = round(float(np.median(v)), 3)
    json.dump({'source': 'LAKER_history RS 1990-2026', 'scaling': A, 'breakout': B, 'K': K,
               'k_shrink': K_SHR, 'bpm_rep': BPM_REP}, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
