# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The NBA exit hurdle on the live season-share grid (PREREG.md M10, wired Nov 19 2026) and its coefficients.

    python3 scripts/research/sweep_nov19/methods/hurdle_nba_grid.py [--write]   # --write: data/nba_proj3y_fit.json 'exit'

3Y = stay x (XPM given he plays, the live 'cp' form) + (1 - stay) x WASH (-2, the replacement value the shrunk target
uses). stay = the chance he plays in S+1..S+3: logistic on [1, XPM (proj), age - 27, (age - 27)^2, ln(1 + minutes per 82),
share of team games played], the M10 hazard. Same simulated partial seasons, draws and seed as
scripts/nba_proj3y_play_research.py; leave one season out with seasons within 3 dropped, S 2012-23.

Scored at every share f on two targets, squared error, season clusters:
    exit    minutes-weighted XPM over the window if he played, else -2      (the column's own definition)
    shrunk  the M10 target (y3y: pooled with 1,000 minutes of -2)
against the live column alone (cp) and, on the shrunk target, against the shrunk-target form (the M10 baseline).
Kept when the hurdle beats cp on the exit target at every f (t <= -2). Run after nba_proj3y_play_research.py --write
and before scripts/gleague.py --fit.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import nba_proj3y_research as R  # noqa: E402
import nba_proj3y_star_research as SR  # noqa: E402
from nba_proj3y_play_research import wfit  # noqa: E402
from hurdle import logit_fit  # noqa: E402

OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))
BUF, LAST = 3, 2023


def lcoef(Xl, yv):
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


def main():
    rows = [r for r in SR.add_history(R.load()) if r['S'] <= LAST and r['y3y'] is not None]
    rng = np.random.default_rng(20261103)
    grid, ok = [], True
    for f in R.FS:
        SR.inputs_with_mp(rows, f, rng)
        n, proj, prior, age, lm, M = R.inputs(rows, f, rng)
        rep = lambda k: np.repeat(np.array([r[k] for r in rows], float), n)  # noqa: E731
        S = rep('S').astype(int)
        d1 = (rep('x1') + 2) * rep('m1') / (rep('m1') + 1000)
        d2 = (rep('x2') + 2) * rep('m2') / (rep('m2') + 1000)
        X = SR.design('H4', proj, prior, age, lm, d1, d2, np.log1p(SR.MPF[0] + rep('m1') + rep('m2')))
        a = age - R.A0
        Xl = np.column_stack([np.ones(len(a)), proj, a, a * a, lm, rep('gp') / rep('games')])
        FM = np.repeat(np.array([r['fmp'] for r in rows], float), n, axis=0)
        FX = np.repeat(np.array([r['fx'] for r in rows], float), n, axis=0)
        w3 = FM.sum(1)
        stay = (w3 > 0).astype(float)
        act = np.where(w3 > 0, (FX * FM).sum(1) / np.maximum(w3, 1e-9), R.WASH)
        y3y = rep('y3y')
        cp, hur, old, ps = (np.zeros(len(S)) for _ in range(4))
        for c in sorted(set(S)):
            tr, te = np.abs(S - c) > BUF, S == c
            tw = tr & (w3 > 0)
            cp[te] = X[te] @ wfit(X[tw], act[tw], w3[tw])
            ps[te] = logit_fit(Xl[tr], stay[tr])(Xl[te])
            old[te] = X[te] @ np.linalg.lstsq(X[tr], y3y[tr], rcond=None)[0]
        hur = ps * cp + (1 - ps) * R.WASH
        S1 = S.reshape(-1, n)[:, 0]
        def cmp(p, q, y):
            d = ((p - y) ** 2 - (q - y) ** 2).reshape(-1, n).mean(1)
            t = H.paired(d, 0 * d, S1)
            sm = [d[S1 == s].mean() for s in sorted(set(S1))]
            return {'rmse': [round(float(np.sqrt(((p - y) ** 2).mean())), 4), round(float(np.sqrt(((q - y) ** 2).mean())), 4)],
                    't': round(float(t['t'] if isinstance(t, dict) else t), 2), 'won': int(sum(v < 0 for v in sm)), 'of': len(sm)}
        res = {'exit_vs_cp': cmp(hur, cp, act), 'shrunk_vs_cp': cmp(hur, cp, y3y), 'shrunk_vs_old': cmp(hur, old, y3y)}
        o = np.argsort(ps)
        res['stayCal'] = round(float(max(abs(ps[b].mean() - stay[b].mean()) for b in np.array_split(o, 10))), 3)
        res['n'] = len(rows); res['exitShare'] = round(float(1 - stay.mean()), 3)
        ok = ok and res['exit_vs_cp']['t'] <= -2
        grid.append({'f': f, 'res': res, 'stay': lcoef(Xl, stay)})
        print(f, json.dumps(res), flush=True)
    print('kept', ok)
    json.dump({'kept': ok, 'grid': [{'f': g['f'], **g['res']} for g in grid]}, open(os.path.join(OUT, 'hurdle_nba_grid.json'), 'w'), indent=1)
    if '--write' in sys.argv:
        fit = json.load(open(R.OUT))
        assert all('cp' in g for g in fit['grid']), 'run nba_proj3y_play_research.py --write first'
        fit['exit'] = {'kept': ok, 'wash': R.WASH, 'haz': ['1', 'XPM (proj)', 'age-27', '(age-27)^2', 'ln(1+M)', 'share of team games'],
                       'note': '3Y = stay x cp + (1 - stay) x wash; stay = logistic(((x - mu) / sd) . b), the chance he plays in S+1..S+3',
                       'res': {str(g['f']): g['res'] for g in grid}}
        for g, gg in zip(fit['grid'], grid):
            assert g['f'] == gg['f']
            if ok: g['stay'] = gg['stay']
            else: g.pop('stay', None)
        json.dump(fit, open(R.OUT, 'w'), indent=1)
        print('wrote', R.OUT)


if __name__ == '__main__':
    main()
