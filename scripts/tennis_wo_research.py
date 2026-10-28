#!/usr/bin/env python3
"""Injury signal in the tennis match model (Oct 2026): a player who gave a walkover (withdrew before a match, W/O in
the archive) in the last N days, A minus B, beside the live blend inputs. Walk-forward: each season's weights fit on
the WIN seasons before it (the live scheme), log loss tune 2012-22 and held out 2023+, t clustered by tournament.

    python3 scripts/tennis_wo_research.py      # needs scripts/tennis_data.py's build cache -> data/tennis_wo_research.json"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tennis_data as T
import tennis_model as M

OUT = os.path.join(M.ROOT, 'data', 'tennis_wo_research.json')


def walkovers():
    """player id (model form) -> sorted day numbers he gave a walkover (Sackmann archive, every level)"""
    wo = defaultdict(list)
    for tour, f in T.sack_files():
        p = os.path.join(T.SACK_DIR, f + '.csv')
        if not os.path.exists(p):
            continue
        for r in T.read_csv(p):
            sc = (r.get('score') or '').upper()
            d, l = T._int(r.get('tourney_date')), T._int(r.get('loser_id'))
            if 'W/O' in sc and d and l:
                wo[f'{tour[0]}{l}'].append(M.dnum(d, (r.get('round') or '').strip()))
    return {k: sorted(v) for k, v in wo.items()}


def fitlog(F, y):
    X = np.vstack([F, -F]); Y = np.r_[y, 1 - y]
    w = np.zeros(F.shape[1]); w[0] = 1.0
    for _ in range(30):
        p = 1 / (1 + np.exp(-(X @ w)))
        H = (X * (p * (1 - p))[:, None]).T @ X
        w = w + np.linalg.solve(H + 1e-3 * np.eye(len(w)), X.T @ (Y - p) - 1e-3 * w)
    return w


def main():
    rows, _, _ = T.load()
    P = json.load(open(M.FIT))['params']
    wo = walkovers()
    print(sum(len(v) for v in wo.values()), 'walkovers', flush=True)
    _, rec = M.run(rows, P, score=lambda r: M.scored(r, 2012 - M.WIN, 2100))
    base = np.array([M.feats(x) for x in rec])
    yr = np.array([x[0][0] // 10000 for x in rec])
    ev = [x[0][6] for x in rec]
    res = {'n': len(rec), 'walkovers': sum(len(v) for v in wo.values()), 'tests': []}

    def recent(p, day, n):
        return any(0 < day - d <= n for d in wo.get(p, ()))
    for n in (14, 30, 60):
        cw = np.array([float(recent(x[0][7], M.dnum(x[0][0], x[0][4]), n)) - float(recent(x[0][8], M.dnum(x[0][0], x[0][4]), n))
                       for x in rec])
        F1 = np.c_[base, cw]
        ll0, ll1 = np.zeros(len(rec)), np.zeros(len(rec))
        for y in range(2012, yr.max() + 1):
            tr = (yr >= y - M.WIN) & (yr < y)
            te = yr == y
            for F, out in ((base, ll0), (F1, ll1)):
                w = fitlog(F[tr], np.ones(tr.sum()))
                out[te] = np.log1p(np.exp(-(F[te] @ w)))
        t = {'days': n, 'withSignal': int((cw != 0).sum()), 'heldWithSignal': int(((cw != 0) & (yr >= 2023)).sum())}
        for nm, lo, hi in (('tune', 2012, 2022), ('held', 2023, 2100)):
            m = (yr >= lo) & (yr <= hi)
            d = ll1[m] - ll0[m]
            g = defaultdict(float)
            for di, k in zip(d - d.mean(), [e for e, mm in zip(ev, m) if mm]):
                g[k] += di
            se = math.sqrt(sum(v * v for v in g.values())) / len(d)
            t[nm] = {'n': int(m.sum()), 'dLLx1e4': round(float(d.mean()) * 1e4, 2), 't': round(float(d.mean() / se), 2)}
        w = fitlog(F1[yr >= 2012], np.ones((yr >= 2012).sum()))
        t['weight'] = round(float(w[-1]), 3)
        mk = (cw != 0) & (yr >= 2012)
        # gave-walkover side's win rate vs the base model's chance for him
        pb = 1 / (1 + np.exp(-(base[mk] @ fitlog(base[yr >= 2012], np.ones((yr >= 2012).sum())))))
        side = cw[mk] > 0
        won = np.where(side, 1.0, 0.0)                       # rows are winner-side: cw>0 means the walkover giver won
        pw = np.where(side, pb, 1 - pb)
        t['woSide'] = {'n': int(mk.sum()), 'won': round(float(won.mean()), 3), 'chance': round(float(pw.mean()), 3)}
        res['tests'].append(t)
        print(json.dumps(t), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
