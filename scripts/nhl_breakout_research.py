# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL Potential Breakout research: ice-time scaling and breakout signals, leave-one-season-out (scripts/breakout_lib.py).

    python3 scripts/nhl_breakout_research.py   # -> data/nhl_breakout_fit.json

History: NHL stats API skater reports 2009-10 on (scripts/nhl_breakout.py pull, cached in scripts/.cache/nhl/bo) and
the site's WAR (static/data/nhl-war/<season>.json). Skaters only.

A. Ice-time scaling, three relations (scripts/nhl_breakout.py TARGETS): even-strength points a 60 against even-strength
   minutes a game, power-play points a 60 against power-play minutes a game, power-play minutes against total minutes.
   Pairs of consecutive seasons over the sample floors, weight = next season's sample minutes (capped). Next season's
   value on this season's (shrunk by sample) + age + workload + D, then + the workload change (dU), then + dU x traits
   a block at a time. Held-out error on all pairs and on the pairs whose workload rose (the case the tab projects).
   Selection check: the same workload change instrumented by what the player did not choose (minutes vacated at his
   position and on the power play by team-mates who left, a change of team), two-stage least squares.
B. Breakout odds. Rows: 200+ minutes this season (per 82 team games). Breakout = next season 900+ minutes and WAR a
   1,000 minutes 1.0+ over his best to date (the highest WAR a 1,000 minutes, shrunk to replacement by ice time with
   k 600 minutes, of this season and the six before), so a star's rebound is not a breakout.
   Baseline logistic: shrunk WAR rate, gap to his best, ln minutes, D. Candidates one at a time, Holm, then the
   passers together. Calibration is on the held-out predictions."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nhl_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'nhl_breakout_fit.json')
Y0 = 2010
LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1)
DEFN = ('next season 900+ minutes (per 82 team games) and WAR a 1,000 minutes 1.0+ over his best to date: the highest '
        'WAR a 1,000 minutes, shrunk to replacement by ice time (k 600 minutes), of this season and the six before.')


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


def scaling(P, last):
    out = {}
    for tgt, T in B.TARGETS.items():
        R = []
        for (pid, y), a in P.items():
            b = P.get((pid, y + 1))
            if y < Y0 or y >= last or not b:
                continue
            if a[T['n']] < T['minn'][0] * a['gmax'] / 82 or b[T['n']] < T['minn'][1] * b['gmax'] / 82:
                continue
            R.append((pid, y, a, b))
        S = np.array([y + 1 for _, y, _, _ in R], float)
        w = np.array([min(b[T['n']], 4 * T['k']) for _, _, a, b in R], float)
        du = np.array([b[T['u']] - a[T['u']] for _, _, a, b in R])
        y = np.array([b[T['x']] for _, _, a, b in R])
        F = np.array([B.features(tgt, a, B.history(P, pid, yy), d) for (pid, yy, a, b), d in zip(R, du)])
        cols = B.columns(tgt)
        ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
        sets = {'base': B.BASE, 'dU': B.BASE + ['dU']}
        for blk, traits in B.BLOCKS.items():
            sets[blk] = B.BASE + ['dU'] + sum([['dU*' + t, t] for t in traits], [])
        sets['full'] = cols
        up, up2 = du >= T['rose'], du >= 2 * T['rose']
        masks = {'all': np.ones(len(y), bool), 'up': up, 'up2': up2}

        def run(cs):
            X = F[:, ix(cs)]

            def fp(trn, te):
                lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
                b0, b = L.wls(X[trn], y[trn], w[trn], lam)
                return b0 + X[te] @ b
            r = {}
            for key, m in masks.items():
                def e(p, te, m=m):
                    mm = m[te]
                    return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
                r[key] = L.loso(S, fp, e)
            return r
        res = {nm: run(cs) for nm, cs in sets.items()}
        rl = f"rose {T['rose']}+"
        cmp = {'dU vs base (all)': L.compare(res['base']['all'], res['dU']['all']),
               f'dU vs base ({rl})': L.compare(res['base']['up'], res['dU']['up']),
               'full vs base (all)': L.compare(res['base']['all'], res['full']['all']),
               f'full vs dU ({rl})': L.compare(res['dU']['up'], res['full']['up']),
               f"full vs dU (rose {2 * T['rose']}+)": L.compare(res['dU']['up2'], res['full']['up2'])}
        blocks = {k: L.compare(res['dU']['up'], res[k]['up']) for k in B.BLOCKS}
        blocks_all = {k: L.compare(res['dU']['all'], res[k]['all']) for k in B.BLOCKS}
        L.holm(blocks)
        keep = [k for k in B.BLOCKS if blocks[k]['pass']]
        fin = B.BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in B.BLOCKS[k]], []) for k in keep], [])
        rk = run(fin)
        cmp['kept vs base (all)'] = L.compare(res['base']['all'], rk['all'])
        cmp[f'kept vs base ({rl})'] = L.compare(res['base']['up'], rk['up'])
        cmp[f'kept vs dU ({rl})'] = L.compare(res['dU']['up'], rk['up'])
        X = F[:, ix(fin)]
        lam = pick_lam(X, y, w, S)
        b0, b = L.wls(X, y, w, lam)
        out[tgt] = {'n': len(R), 'n_up': int(up.sum()), 'n_up2': int(up2.sum()), 'rose': T['rose'],
                    'du_q99': round(float(np.quantile(du, .99)), 2), 'tests': cmp, 'blocks': blocks,
                    'blocks_all_pairs': blocks_all, 'keep': keep, 'lam': lam,
                    'fit': {'b0': round(float(b0), 5), 'cols': fin, 'b': [round(float(v), 7) for v in b]}}
        print(tgt, 'n', len(R), 'up', int(up.sum()), flush=True)
        for k, v in cmp.items():
            print('  ', k, v, flush=True)
        for k, v in blocks.items():
            print('   block', k, v, flush=True)
    return out


def instrumented(P, last):
    """workload change coefficient: least squares against two-stage least squares (instruments: vacated position
    minutes share, vacated power-play minutes share, changed team)"""
    by = {}
    for (pid, y), o in P.items():
        by.setdefault(y, {})[pid] = o
    out = {}
    for tgt, T in B.TARGETS.items():
        X, Z, du, Y, w = [], [], [], [], []
        for y in range(Y0, last):
            V = B.vacated(by[y], by[y + 1])
            for pid, a in by[y].items():
                b = by[y + 1].get(pid)
                if (not b or not a['tm'] or not b['tm'] or a[T['n']] < T['minn'][0] * a['gmax'] / 82
                        or b[T['n']] < T['minn'][1] * b['gmax'] / 82):
                    continue
                X.append(B.features(tgt, a, B.history(P, pid, y), 0.0)[:len(B.BASE)])
                Z.append([V[pid][0], V[pid][1], 1.0 if a['tm'] != b['tm'] else 0.0])
                du.append(b[T['u']] - a[T['u']])
                Y.append(b[T['x']])
                w.append(min(b[T['n']], 4 * T['k']))
        X, Z, du, Y, w = np.array(X), np.array(Z), np.array(du), np.array(Y), np.sqrt(np.array(w))
        A = np.column_stack([np.ones(len(X)), X])
        AZ = np.column_stack([A, Z])
        ols = lambda M, v: np.linalg.lstsq(M * w[:, None], v * w, rcond=None)[0]  # noqa: E731
        b1, b0 = ols(AZ, du), ols(A, du)
        r1, r0 = (du - AZ @ b1) * w, (du - A @ b0) * w
        F = ((r0 @ r0 - r1 @ r1) / 3) / (r1 @ r1 / (len(du) - AZ.shape[1]))
        dh = AZ @ b1
        b2, bo = ols(np.column_stack([A, dh]), Y), ols(np.column_stack([A, du]), Y)
        res = (Y - np.column_stack([A, du]) @ b2) * w
        M = np.column_stack([A, dh]) * w[:, None]
        se = float(np.sqrt((res @ res / (len(Y) - M.shape[1])) * np.linalg.inv(M.T @ M)[-1, -1]))
        out[tgt] = {'n': len(Y), 'first_stage_F': round(float(F), 1), 'ols': round(float(bo[-1]), 4),
                    'iv': round(float(b2[-1]), 4), 'iv_se': round(se, 4)}
        print('instrumented', tgt, out[tgt], flush=True)
    return out


def breakout(P, last):
    by = {}
    for (pid, y), o in P.items():
        by.setdefault(y, {})[pid] = o
    R = []
    for y in range(Y0, last):
        V = B.vacated(by[y], by[y + 1])
        for pid, a in by[y].items():
            if a['war'] is None or a['tmin'] < B.ROW_MIN * a['gmax'] / 82:
                continue
            b = by[y + 1].get(pid)
            hit = 1.0 if (b and b['war'] is not None and b['tmin'] >= B.ROLE_MIN * b['gmax'] / 82
                          and B.rate(b) >= B.best(a, B.history(P, pid, y)) + B.J_WAR) else 0.0
            R.append((a, hit, B.bo_feats(a, B.history(P, pid, y), V[pid])))
    S = np.array([a['y'] + 1 for a, _, _ in R], float)
    y = np.array([h for _, h, _ in R])
    base = np.array([f['base'] for _, _, f in R])
    cands = {k: np.array([f[k] for _, _, f in R]) for k in B.BO_CANDS}

    def run(X, keep_pred=None):
        def fp(trn, te):
            b0, b = L.logit(X[trn], y[trn])
            p = L.sig(b0 + X[te] @ b)
            if keep_pred is not None:
                keep_pred[te] = p
            return p

        def err(p, te):
            p = np.clip(p, 1e-6, 1 - 1e-6)
            return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))
        return L.loso(S, fp, err)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, X]))) for k, X in cands.items()}
    L.holm(res)
    keep = [k for k in cands if res[k]['pass']]
    X = np.column_stack([base] + [cands[k] for k in keep])
    ho = np.zeros(len(y))
    final = L.compare(rb, run(X, ho))
    b0, b = L.logit(X, y)
    cal = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (ho >= lo) & (ho < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ho[m].mean()), 3), round(float(y[m].mean()), 3)])
    d = np.array([a['d'] for a, _, _ in R])
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y), 'F', round(float(y[d == 0].mean()), 4), 'D',
          round(float(y[d == 1].mean()), 4), flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    print(' calib (held out)', cal, flush=True)
    return {'n': len(y), 'rate': round(float(y.mean()), 4), 'tests': res, 'keep': keep, 'final': final,
            'calib_held_out': cal, 'width': {k: int(cands[k].shape[1]) for k in keep},
            'fit': {'b0': round(float(b0), 5), 'b': [round(float(v), 6) for v in b],
                    'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


def main():
    cur = B.D.current_season()
    last = cur - 1          # the last finished season
    P = {}
    for S in range(Y0, cur):
        for pid, o in B.season(S).items():
            P[(pid, S)] = o
        print(S, sum(1 for k in P if k[1] == S), flush=True)
    A = scaling(P, last)
    IV = instrumented(P, last)
    Bo = breakout(P, last)
    json.dump({'source': f'NHL stats API skater reports + site WAR, {Y0 - 1}-{Y0 % 100:02d} to {last - 1}-{last % 100}',
               'workload': 'ice time a game by state (even strength, power play); goalies not modelled',
               'definition': DEFN, 'scaling': A, 'scaling_instrumented': IV, 'breakout': Bo, 'k_shrink': B.K_SHR, 'jump': B.J_WAR,
               'role_min': B.ROLE_MIN}, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
