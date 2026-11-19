# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The NHL exit hurdle on the live season-share grid (PREREG.md M10 shipping check) and its fit file.

    python3 scripts/research/sweep_nov19/methods/hurdle_nhl_grid.py [--write]   # --write: data/nhl_exit_fit.json

Partial seasons are simulated exactly as scripts/nhl_proj_research.py partial() (same noise model, draws and seed
rule); at each share f the hurdle (stay chance x bfull refit on stayers) is scored against bfull, leave one season out.
Needs the MoneyPuck summaries in scripts/.cache/nhl/mp (nhl_players.mp_file pulls them).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import nhl_proj_research as R  # noqa: E402
from hurdle import logit_fit  # noqa: E402

OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))
FITF = os.path.join(ROOT, 'data', 'nhl_exit_fit.json')


def sim(rs, grps, fitd, HT, rng, f):
    G = grps == ['G']
    wts, K, gpw = fitd['wts'], fitd['KG'] if G else fitd['K'], fitd['goalsPerWin']
    ns = R.noise(rs, HT)
    C1 = np.array([[ns['hh'], ns['hw']], [ns['hw'], ns['ww']]])
    n = 1 if f == 1 else R.DRAWS
    A = {k: [] for k in ('S', 'age', 'pw', 'pm', 'r', 'lt', 'grp', 'share', 'stay', 'stay3', 'y', 'key')}
    for r in rs:
        cur = HT[r['S']].get(r['key'])
        if not cur:
            continue
        hist = [HT.get(r['S'] - j, {}).get(r['key']) for j in range(len(wts))]
        den0 = sum(w * h[1] for w, h in zip(wts, hist) if h)
        num0 = sum(w * h[1] * h[0] for w, h in zip(wts, hist) if h)
        pl = fitd['w'].get('gpl' if G else 'pl', 0) + (fitd['w'].get('pD', 0) if r['grp'] == 'D' else 0)
        h = cur[1] / 3600
        if f < 1:
            E = rng.multivariate_normal([0, 0], C1 * (1 / (h * f) - 1 / h), n)
            Z = rng.normal(0, R.TSD * math.sqrt((1 - f) / f), n)
        else:
            E, Z = np.zeros((1, 2)), np.zeros(1)
        tf = cur[1] * f
        raw0 = (num0 + pl * K) / (den0 + K)
        for (eh, ew), z in zip(E, Z):
            den = den0 - (1 - f) * cur[1]
            num = num0 - cur[1] * cur[0] + tf * (cur[0] + eh)
            hpm = r['hpm'] + (num + pl * K) / (den + K) - raw0
            toi82 = r['toi82'] * math.exp(z)
            pnum = r['pmnum'] - r['war'] + (r['wh'] + ew) * tf / 3600
            pden = r['pmden'] - r['toi'] + tf / 60
            A['S'].append(r['S']); A['age'].append(r['age']); A['grp'].append(r['grp'])
            A['pw'].append((hpm - r['repl']) * toi82 / 60 / gpw)
            A['pm'].append((pnum + R.KP * R.MU[r['grp']]) / (pden + R.KP) * toi82)
            A['r'].append(hpm - r['repl']); A['lt'].append(math.log1p(toi82 / 100))
            A['share'].append(r['share']); A['stay'].append(r['stay']); A['stay3'].append(r['stay3']); A['y'].append(r['y3']); A['key'].append(r['key'])
    return {k: np.array(v) if k in ('grp', 'key') else np.array(v, float) for k, v in A.items()}, n


def haz_x(A):
    a = A['age'] - R.A0
    return np.column_stack([np.ones(len(a)), A['pw'], a, a * a, A['lt'], A['share']])


def main():
    files = R.load()
    allr = R.rows(files, 2025)
    ix = lambda S, pid: files.get(S, {}).get('_ix', {}).get(pid)
    for r in allr:
        r['stay'] = float(any(ix(r['S'] + k, r['id']) for k in (1, 2, 3)))
        r['stay3'] = float(bool(ix(r['S'] + 3, r['id'])))
        r['share'] = ((ix(r['S'], r['id']) or {}).get('gp') or 0) / R.games(r['S'])
    fitd = json.load(open(os.path.join(ROOT, 'data', 'nhl_war_fit.json')))
    HT = R.h1_tables(fitd)
    rng = np.random.default_rng(20261119)
    out = {'A0': R.A0, 'form': 'bfull', 'haz': ['1', 'pw', 'age-27', '(age-27)^2', 'ln(1+TOI82/100)', 'share of team games'],
           'note': 'p3 = stay x X(bfull) . cc; stay = logistic(((x - mu) / sd) . b); il = the chance he plays in season S+3 (same inputs, b3)'}
    ok_all = True
    for part, grps in (('skaters', ['F', 'D']), ('goalies', ['G'])):
        rs = [r for r in allr if (r['grp'] == 'G') == (part == 'goalies') and r['n3'] and r['S'] <= 2023]
        grid = []
        for f in R.FS:
            A, n = sim(rs, grps, fitd, HT, rng, f)
            S, y = A['S'], A['y']
            Xb, Xl = R.X('bfull', A, grps), haz_x(A)
            base, hur, p3 = (np.zeros(len(y)) for _ in range(3))
            for s in sorted(set(S)):
                tr, te = S != s, S == s
                base[te] = Xb[te] @ np.linalg.lstsq(Xb[tr], y[tr], rcond=None)[0]
                trs = tr & (A['stay'] > 0)
                hur[te] = logit_fit(Xl[tr], A['stay'][tr])(Xl[te]) * (Xb[te] @ np.linalg.lstsq(Xb[trs], y[trs], rcond=None)[0])
                p3[te] = logit_fit(Xl[tr], A['stay3'][tr])(Xl[te])
            d = ((hur - y) ** 2 - (base - y) ** 2).reshape(-1, n).mean(1)
            S1 = S.reshape(-1, n)[:, 0]
            ps = H.paired(d, 0 * d, S1)
            sm = [d[S1 == s].mean() for s in sorted(set(S1))]
            o = np.argsort(p3)
            cal = max(abs(p3[b].mean() - A['stay3'][b].mean()) for b in np.array_split(o, 10))
            # full-sample coefficients for the live column
            def lcoef(yv):
                mu, sd = Xl.mean(0), Xl.std(0)
                sd[sd == 0] = 1; mu[0], sd[0] = 0, 1
                Z = (Xl - mu) / sd
                b = np.zeros(Z.shape[1])
                for _ in range(50):
                    p = 1 / (1 + np.exp(-Z @ b))
                    st = np.linalg.solve((Z * (p * (1 - p))[:, None]).T @ Z + 1e-3 * np.eye(len(b)), Z.T @ (yv - p) - 1e-3 * b)
                    b += st
                    if np.abs(st).max() < 1e-8:
                        break
                return {'mu': [round(float(v), 5) for v in mu], 'sd': [round(float(v), 5) for v in sd], 'b': [round(float(v), 5) for v in b]}
            st = A['stay'] > 0
            g = {'f': f, 'cc': [round(float(v), 5) for v in np.linalg.lstsq(Xb[st], y[st], rcond=None)[0]], 'stay': lcoef(A['stay']), 'il': lcoef(A['stay3']),
                 'rmse': [round(float(np.sqrt(((base - y) ** 2).mean())), 4), round(float(np.sqrt(((hur - y) ** 2).mean())), 4)],
                 't': round(ps['t'], 2), 'won': int(sum(v < 0 for v in sm)), 'seasons': len(sm), 'ilMaxBinErr': round(float(cal), 3)}
            grid.append(g)
            print(part, json.dumps({k: g[k] for k in ('f', 'rmse', 't', 'won', 'seasons', 'ilMaxBinErr')}), flush=True)
        passed = all(g['t'] <= -2 and g['won'] > g['seasons'] / 2 for g in grid)
        il_ok = all(g['ilMaxBinErr'] <= .05 for g in grid)
        out[part] = {'grps': grps, 'grid': grid, 'kept': bool(passed), 'il': bool(il_ok), 'n': len(rs)}
        ok_all &= passed
        print(part, 'hurdle kept' if passed else 'hurdle NOT kept', '| in-league column', 'kept' if il_ok else 'not kept', flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, 'hurdle_nhl_grid.json'), 'w'), indent=1)
    if '--write' in sys.argv:
        json.dump(out, open(FITF, 'w'), separators=(',', ':'))
        print('wrote', FITF)


if __name__ == '__main__':
    main()
