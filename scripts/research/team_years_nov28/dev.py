#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""prereg.md, player development (CBB): class means against a ridge curve on class, age, level and role.
    python3 scripts/research/team_years_nov28/dev.py   -> results_dev.json here, data/team_years_dev.json (the curve)"""
import json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE)); ROOT = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, HERE)
import team_years as CH  # noqa: E402
from test import paired_t, REP  # noqa: E402

ORIG = {1: [2022, 2023, 2024, 2025], 2: [2022, 2023, 2024]}


def val(r): return (r['px'] if r.get('px') is not None else (r.get('bpm') or REP))


def fit_curve(tr):
    """tr: [(row, row a season on)] -> the live form {'b': raw coefficients, 'ageMean'}"""
    ages = defaultdict(list)
    for r, _ in tr:
        if r.get('age'): ages[CH.CLS[r['yr']]].append(r['age'])
    am = {c: float(np.mean(v)) for c, v in ages.items()}
    F = lambda r: [1.0 * (CH.CLS[r['yr']] == 1), 1.0 * (CH.CLS[r['yr']] == 2), 1.0 * (CH.CLS[r['yr']] == 3),
                   (r['age'] - am.get(CH.CLS[r['yr']], 0)) if r.get('age') else 0.0, val(r), (r.get('min_per') or 0) / 100]
    X = np.array([F(r) for r, _ in tr]); yv = np.array([val(n) - val(r) for r, n in tr])
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1; Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    b = np.linalg.solve(Z.T @ Z + 5.0 * np.diag([0] + [1] * X.shape[1]), Z.T @ yv)
    return {'b': [float(b[0] - (b[1:] * mu / sd).sum())] + [float(x) for x in b[1:] / sd], 'ageMean': {str(c): v for c, v in am.items()}}


def main():
    import cbb_market_fit as M
    by = M.player_rows(write=False)
    agem = {}
    def feats(r):
        c = CH.CLS[r['yr']]; a = (r.get('age') or 0) - agem.get(c, 0) if r.get('age') else 0.0
        return [1.0 * (c == 1), 1.0 * (c == 2), 1.0 * (c == 3), a, val(r), (r.get('min_per') or 0) / 100]
    out = {'k': {}}
    for k, origins in ORIG.items():
        def pairs(y):
            nxt = {r['pid']: r for r in by.get(y + k, [])}
            return [(r, nxt[r['pid']]) for r in by.get(y, []) if CH.CLS.get(r.get('yr')) and r['pid'] in nxt]
        E0, E1, CL, folds = [], [], [], {}
        for y in origins:
            tr = [p for yy in range(y - 4, y - k + 1) for p in pairs(yy)]   # targets known by season y
            te = pairs(y)
            ages = defaultdict(list)
            for r, _ in tr:
                if r.get('age'): ages[CH.CLS[r['yr']]].append(r['age'])
            agem.clear(); agem.update({c: float(np.mean(v)) for c, v in ages.items()})
            dc = defaultdict(list)
            for r, n in tr: dc[CH.CLS[r['yr']]].append(val(n) - val(r))
            mdev = {c: float(np.mean(v)) for c, v in dc.items()}
            X = np.array([feats(r) for r, _ in tr]); yv = np.array([val(n) - val(r) for r, n in tr])
            mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1; Z = np.c_[np.ones(len(X)), (X - mu) / sd]
            b = np.linalg.solve(Z.T @ Z + 5.0 * np.diag([0] + [1] * X.shape[1]), Z.T @ yv)
            Xt = np.array([feats(r) for r, _ in te]); Zt = np.c_[np.ones(len(Xt)), (Xt - mu) / sd]
            tgt = np.array([val(n) for _, n in te]); v0 = np.array([val(r) for r, _ in te])
            p0 = v0 + np.array([mdev.get(CH.CLS[r['yr']], 0.0) for r, _ in te]); p1 = v0 + Zt @ b
            e0, e1 = (tgt - p0) ** 2, (tgt - p1) ** 2
            E0 += list(e0); E1 += list(e1); CL += [r['team'] + str(y) for r, _ in te]
            folds[str(y)] = {'n': len(te), 'mse0': round(float(e0.mean()), 3), 'mse1': round(float(e1.mean()), 3)}
        E0, E1 = np.array(E0), np.array(E1)
        t = paired_t(E0 - E1, CL); won = sum(f['mse1'] < f['mse0'] for f in folds.values())
        res = {'mse0': round(float(E0.mean()), 3), 'mse1': round(float(E1.mean()), 3), 't': round(t, 2), 'won': won, 'of': len(origins), 'folds': folds}
        res['pass'] = bool(t >= 2 and won >= len(origins) - 1)
        out['k'][str(k)] = res
        print('dev k', k, {x: res[x] for x in ('mse0', 'mse1', 't', 'won', 'of', 'pass')}, flush=True)
    # the live curve: fit on the three latest origins with k = 1 targets
    tr = [(r, n) for yy in (2023, 2024, 2025) for r, n in [(r, {x['pid']: x for x in by.get(yy + 1, [])}.get(r['pid'])) for r in by.get(yy, []) if CH.CLS.get(r.get('yr'))] if n]
    ages = defaultdict(list)
    for r, _ in tr:
        if r.get('age'): ages[CH.CLS[r['yr']]].append(r['age'])
    agem.clear(); agem.update({c: float(np.mean(v)) for c, v in ages.items()})
    X = np.array([feats(r) for r, _ in tr]); yv = np.array([val(n) - val(r) for r, n in tr])
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1; Z = np.c_[np.ones(len(X)), (X - mu) / sd]
    b = np.linalg.solve(Z.T @ Z + 5.0 * np.diag([0] + [1] * X.shape[1]), Z.T @ yv)
    raw = [float(b[0] - (b[1:] * mu / sd).sum())] + [float(x) for x in b[1:] / sd]
    out['live'] = {'cols': ['const', 'fr', 'so', 'jr', 'age_rel', 'value', 'min'], 'b': [round(x, 4) for x in raw], 'ageMean': {str(c): round(v, 2) for c, v in agem.items()}, 'n': len(tr)}
    json.dump(out, open(os.path.join(HERE, 'results_dev.json'), 'w'), indent=1)
    json.dump({'cbb': dict(out['live'], test={k: {x: v[x] for x in ('mse0', 'mse1', 't', 'won', 'of', 'pass')} for k, v in out['k'].items()})},
              open(os.path.join(ROOT, 'data', 'team_years_dev.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
