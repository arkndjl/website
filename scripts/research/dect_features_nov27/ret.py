#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""DECT in Ret% (prereg.md R1-R4): on the DECT history rows themselves (hist.py), so the base and the candidate read the
same board. CFB: the last fall PFF board 105-200 days out, 2022-25 drafts, players with eligibility left. CBB: the
ranked board rows 2022-26.

    python3 scripts/research/dect_features_nov27/ret.py      # -> results_ret.json here

Base: CFB ln xPick, age, 2024+ (era), by class group (Sr. / under), as the live declare model. CBB: ln rank, age, 2024+.
Gate: leave one draft out, t <= -2 on log loss and the term wins 6 of 8 cells (CFB) / 4 of 5 drafts (CBB); then it has to
hold walking forward (each draft from the drafts before it) with t <= -2.
"""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hist  # noqa: E402

OUT = os.path.join(HERE, 'results_ret.json')


def logit(X, y, l2=1.0, it=50):
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p)
        H = (X * W[:, None]).T @ X + l2 * np.eye(len(b)); H[0, 0] -= l2
        g = X.T @ (y - p) - l2 * b; g[0] += l2 * b[0]
        b += np.linalg.solve(H, g)
    return b


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6); return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def tstat(d): return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


def run(rows, ycol, base, cands, groups, cell, gate):
    """rows: dicts; base(r) -> list; cands: name -> f(r) -> list; groups(r) -> fit group key; cell(r) -> test cell"""
    years = sorted({r['year'] for r in rows})
    y = np.array([r[ycol] for r in rows], float)
    def pred(fx, wf):
        p = np.full(len(rows), np.nan)
        for yr in years:
            for g in sorted({groups(r) for r in rows}):
                te = [i for i, r in enumerate(rows) if r['year'] == yr and groups(r) == g]
                tr = [i for i, r in enumerate(rows) if (r['year'] < yr if wf else r['year'] != yr) and groups(r) == g]
                if not te or len(tr) < 30: continue
                X = lambda ix: np.array([[1.0] + fx(rows[i]) for i in ix], float)
                Xa = X(tr); mu = Xa[:, 1:].mean(0); sd = Xa[:, 1:].std(0); sd[sd == 0] = 1
                Z = lambda M: np.c_[M[:, :1], (M[:, 1:] - mu) / sd]
                b = logit(Z(Xa), y[tr]); p[te] = 1 / (1 + np.exp(-Z(X(te)) @ b))
        return p
    out = {'n': len(rows), 'rate': round(float(y.mean()), 3), 'terms': {}}
    for wf in (False, True):
        p0 = pred(base, wf); ok = ~np.isnan(p0); L0 = ll(p0, y)
        out['base' + ('WF' if wf else '')] = round(float(L0[ok].mean()), 4)
        for k, f in cands.items():
            p1 = pred(lambda r: base(r) + f(r), wf); L1 = ll(p1, y); d = (L1 - L0)[ok]
            C = np.array([cell(r) for r in rows])[ok]; cs = sorted(set(C))
            res = {'d': round(float(d.mean()), 5), 't': round(tstat(d), 2), 'won': int(sum(d[C == c].mean() < 0 for c in cs)), 'of': len(cs)}
            res['pass'] = bool(res['t'] <= -2 and (wf or res['won'] >= gate))
            out['terms'].setdefault(k, {})['walkForward' if wf else 'lodo'] = res
    for k, v in out['terms'].items(): v['pass'] = bool(v['lodo']['pass'] and v['walkForward']['pass'])
    return out


def asinh(x): return math.asinh(x / 0.25)


def main():
    h = hist.load()
    C = [dict(r, year=r['draft'], ret=1 - r['declared']) for r in h['cfb'] if r.get('ce') is not None]
    am = float(np.mean([r['ageD'] for r in C]))
    base = lambda r: [r['lx'], r['ageD'] - am, float(r['draft'] >= 2024)]
    cands = {'R1 ce': lambda r: [asinh(r['ce'])], 'R2 ce_rel': lambda r: [r['ce'] / max(r['vd'], 0.05)],
             'R3 college': lambda r: [float(r['ce'] > 0 and not r['even'])], 'R4 declare': lambda r: [float(r['ce'] <= 0 and not r['even'])]}
    out = {'cfb': run(C, 'ret', base, cands, lambda r: r['cls'] == 'Sr.', lambda r: f"{r['draft']}{r['cls'] == 'Sr.'}", 6)}
    print('cfb', json.dumps(out['cfb']))
    B = [dict(r, ret=1 - r['left']) for r in h['cbb'] if r.get('ce') is not None]
    am = float(np.mean([r['age'] for r in B]))
    base = lambda r: [r['lx'], r['age'] - am, float(r['year'] >= 2024)]
    out['cbb'] = run(B, 'ret', base, cands, lambda r: 0, lambda r: r['year'], 4)
    print('cbb', json.dumps(out['cbb']))
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
