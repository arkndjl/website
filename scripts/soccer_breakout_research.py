# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer Potential Breakout research: workload scaling and breakout signals, leave-one-season-out
(scripts/breakout_lib.py).

    python3 scripts/soccer_breakout_research.py     # -> data/soccer_breakout_fit.json

History: static/data/soccer-war/<season>.json (Understat big five since 2014-15, scripts/soccer_players.py); the
season in progress is never a target. A player's stints in one season are pooled.

A. Workload scaling. Workload = shot involvement share (SI%: shots + key passes per 100 team shots while on the pitch),
   efficiency = (npxG + xA) per shot involvement. Pairs of seasons (900+ minutes and 15+ involvements both), outfield,
   weight = the smaller involvement count. Next-season efficiency on this season's (shrunk by involvements) + age +
   SI%; then each context block's traits (levels, all pairs); then the SI% change (dU); then dU x each block against
   the block's traits + dU, on the pairs whose SI% changed UP+ points either way.
B. Breakout odds. Rows: outfield, 450+ minutes this season, in the big five next season. Breakout = next season
   1500+ minutes at or over the quality bar LEVEL (GAR a 90 shrunk to replacement by minutes, k 600; about the 76th
   percentile of outfield 1500+ minute seasons) for the first time: a player with any season to date at the bar is
   out of the rows. Baseline logistic: shrunk GAR a 90,
   ln minutes, best to date minus this season. Candidates one at a time, then the passers together."""
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import soccer_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'soccer_breakout_fit.json')
UP, UP2 = 5.0, 10.0
LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1)


def data():
    SS = B.seasons()
    P, T, squad, meta = {}, {}, {}, {}
    for s in SS:
        Ps, T[s], meta[s] = B.load(s)
        sq = defaultdict(set)
        for p, o in Ps.items():
            P[(p, s)] = o
            for t in o['teams']:
                sq[t].add(p)
        squad[s] = sq
    last = SS[-1] if (meta[SS[-1]].get('asof') or '')[5:7] in ('06', '07') else SS[-2]
    return P, T, squad, last


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


# ---------- A. workload scaling ----------
def scaling(P, T, last):
    """two questions per context block, each against a baseline that already holds everything kept before it:
    levels (does the trait move next-season efficiency at all; all pairs) and scaling (does dU x trait add to the
    trait + dU; the pairs whose workload changed UP+ points either way, so the test set is not picked on a rise)"""
    R = []
    for (p, s), a in P.items():
        b = P.get((p, s + 1))
        if s + 1 > last or not b or a['pos'] == 'GK' or min(a['min'], b['min']) < B.MIN_PAIR or min(a['inv'], b['inv']) < 15:
            continue
        R.append((p, s, a, b, B.team_sh(T[s], b['team'], b['lg']) - a['tsh']))
    S = np.array([s + 1 for _, s, *_ in R], float)
    w = np.array([min(a['inv'], b['inv']) for _, _, a, b, _ in R], float)
    du = np.array([b['U'] - a['U'] for _, _, a, b, _ in R])
    out = {}
    for tgt in B.TARGETS:
        y = np.array([b[tgt] for _, _, a, b, _ in R]) * 100
        F = np.array([B.features(tgt, a, B.history(P, p, s), dT, d) for (p, s, a, b, dT), d in zip(R, du)])
        cols = B.columns(tgt)
        masks = {'all': np.ones(len(y), bool), 'chg': np.abs(du) >= UP, 'up': du >= UP, 'up2': du >= UP2}

        def run(cs):
            X = F[:, [cols.index(c) for c in dict.fromkeys(cs)]]
            store = {}

            def fp(trn, te):
                b0, b = L.wls(X[trn], y[trn], w[trn], pick_lam(X[trn], y[trn], w[trn], S[trn]))
                store[float(S[te][0])] = b0 + X[te] @ b
                return None
            L.loso(S, fp, lambda p, te: (0.0, 1.0))
            res = {}
            for key, m in masks.items():
                res[key] = {}
                for s, p in store.items():
                    te = S == s
                    mm = m[te]
                    res[key][s] = (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
            return res
        r0 = run(B.BASE)
        lev = {k: L.compare(r0['all'], run(B.BASE + tr)['all']) for k, tr in B.BLOCKS.items()}
        L.holm(lev)
        klev = [k for k in B.BLOCKS if lev[k]['pass']]
        BL = B.BASE + sum([B.BLOCKS[k] for k in klev], [])
        rl, rd = run(BL), run(BL + ['dU'])
        inter, ires = {}, {}
        for k, tr in B.BLOCKS.items():
            ires[k] = run(BL + tr + ['dU'] + ['dU*' + t for t in tr])
            inter[k] = L.compare(run(BL + tr + ['dU'])['chg'], ires[k]['chg'])
            inter[k]['rose'] = {q: L.compare(run(BL + tr + ['dU'])['up'], ires[k]['up'])[q] for q in ('t', 'won')}
        L.holm(inter)
        keep = [k for k in B.BLOCKS if inter[k]['pass']]
        fin = list(dict.fromkeys(BL + ['dU'] + sum([B.BLOCKS[k] + ['dU*' + t for t in B.BLOCKS[k]] for k in keep], [])))
        rf, ra = run(fin), run(cols)
        cmp = {'levels vs base (all)': L.compare(r0['all'], rl['all']),
               'dU vs levels (all)': L.compare(rl['all'], rd['all']),
               'dU vs levels (changed)': L.compare(rl['chg'], rd['chg']),
               'dU vs levels (rose)': L.compare(rl['up'], rd['up']),
               'kept vs base (all)': L.compare(r0['all'], rf['all']),
               'kept vs base (changed)': L.compare(r0['chg'], rf['chg']),
               'kept vs base (rose)': L.compare(r0['up'], rf['up']),
               'kept vs base (rose 2x)': L.compare(r0['up2'], rf['up2']),
               'kept vs levels + dU (changed)': L.compare(rd['chg'], rf['chg']),
               'kept vs levels + dU (rose)': L.compare(rd['up'], rf['up']),
               'every block vs kept (changed)': L.compare(rf['chg'], ra['chg'])}
        X = F[:, [cols.index(c) for c in fin]]
        lam = pick_lam(X, y, w, S)
        b0, b = L.wls(X, y, w, lam)
        out[tgt] = {'n': len(R), 'n_changed': int(masks['chg'].sum()), 'n_rose': int(masks['up'].sum()),
                    'n_rose2x': int(masks['up2'].sum()), 'changed': UP, 'rose2x': UP2, 'unit': 'efficiency x 100',
                    'tests': cmp, 'levels': lev, 'blocks': inter, 'keep_levels': klev, 'keep': keep, 'lam': lam,
                    'fit': {'b0': round(b0 / 100, 7), 'cols': fin, 'b': [round(float(v) / 100, 9) for v in b]}}
        print(tgt, 'pairs', len(R), 'changed', out[tgt]['n_changed'], 'rose', out[tgt]['n_rose'], out[tgt]['n_rose2x'], flush=True)
        for k, v in cmp.items():
            print('  ', k, v, flush=True)
        for k, v in lev.items():
            print('   level', k, v, flush=True)
        for k, v in inter.items():
            print('   dU x', k, v, flush=True)
        print('   fit', dict(zip(fin, (b / 100).round(5))), flush=True)
    return out, du


# ---------- B. breakout odds ----------
def breakout(P, T, squad, last):
    R, C = [], B.careers(P)
    reg = [B.shr(o['g90'], o['min']) for (p, s), o in P.items() if s <= last and o['pos'] != 'GK' and o['min'] >= B.MIN_NEXT]
    pct = round(float((np.array(reg) < B.LEVEL).mean()) * 100, 1)
    for (p, s), a in P.items():
        b = P.get((p, s + 1))
        if s + 1 > last or not b or a['pos'] == 'GK' or a['min'] < B.MIN_BASE or a['inv'] < 5:
            continue
        ref = max(v for q, v in C[p] if q <= s)
        if ref >= B.LEVEL:
            continue
        s0, f = B.bo_row(a, B.history(P, p, s), T[s], b['team'], squad[s + 1][b['team']], ref)
        R.append((s, f, 1.0 if (b['min'] >= B.MIN_NEXT and B.shr(b['g90'], b['min']) >= B.LEVEL) else 0.0))
    S = np.array([s + 1 for s, _, _ in R], float)
    y = np.array([h for _, _, h in R])
    base = np.array([f['base'] for _, f, _ in R])
    cands = {k: np.array([f[k] for _, f, _ in R]) for k in B.BO_CANDS}

    def run(X, keep_p=None):
        def fp(trn, te):
            b0, b = L.logit(X[trn], y[trn])
            p = L.sig(b0 + X[te] @ b)
            if keep_p is not None:
                keep_p[te] = p
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
    ph = np.zeros(len(y))
    final = L.compare(rb, run(X, ph))
    b0, b = L.logit(X, y)
    cal = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (ph >= lo) & (ph < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ph[m].mean()), 3), round(float(y[m].mean()), 3)])
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y), flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    print(' held-out calibration', cal, flush=True)
    return {'def': f'first season at the bar: next season {B.MIN_NEXT}+ minutes and GAR a 90 of {B.LEVEL}+ (shrunk to '
                   f'replacement by minutes, k {B.K_SHR:.0f}; the {pct:.0f}th percentile of outfield {B.MIN_NEXT}+ minute '
                   f'seasons), no season to date at the bar; outfield, {B.MIN_BASE}+ minutes, in the big '
                   f'five next season',
            'level': B.LEVEL, 'level_pct': pct, 'n': len(y), 'rate': round(float(y.mean()), 4), 'tests': res, 'keep': keep, 'final': final,
            'calib_heldout': cal, 'fit': {'b0': round(b0, 5), 'b': [round(float(v), 6) for v in b],
                                          'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


def main():
    P, T, squad, last = data()
    A, du = scaling(P, T, last)
    Bo = breakout(P, T, squad, last)
    U = np.array([o['U'] for o in P.values() if o['min'] >= 1500 and o['pos'] != 'GK'])
    json.dump({'source': f'static/data/soccer-war 2015-{last} (Understat big five)',
               'workload': 'SI% = shots + key passes per 100 team shots while on the pitch; efficiency = '
                           '(npxG + xA) per shot involvement',
               'scaling': A, 'breakout': Bo, 'dU_p99': round(float(np.percentile(du, 99)), 2),
               'U_pct': {str(q): round(float(np.percentile(U, q)), 1) for q in (50, 75, 90, 95, 99)},
               'tiers': [{'k': 20, 'lab': 'SI 20'}, {'k': 30, 'lab': 'SI 30'}, {'k': 40, 'lab': 'SI 40'}],
               'k_shrink': B.K_SHR, 'level': B.LEVEL}, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
