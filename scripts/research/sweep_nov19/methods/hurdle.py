# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Career-exit hurdle in the 3Y projections (PREREG.md M10): P(still plays) x E[value | plays] + (1 - P) x exit value
against the live one-step form, and the "still in the league in 3 seasons" chance. -> out/hurdle.json

    python3 scripts/research/sweep_nov19/methods/hurdle.py [nba nhl nfl]
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H  # noqa: E402

OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))


def logit_fit(X, y, ridge=1e-3):
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    mu[0], sd[0] = 0, 1
    Z = (X - mu) / sd
    b = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-Z @ b))
        g = Z.T @ (y - p) - ridge * b
        Hm = (Z * (p * (1 - p))[:, None]).T @ Z + ridge * np.eye(len(b))
        st = np.linalg.solve(Hm, g)
        b += st
        if np.abs(st).max() < 1e-8:
            break
    return lambda Xn: 1 / (1 + np.exp(-((Xn - mu) / sd) @ b))


def run(name, Xb, Xl, y, stay, stay3, S, ids, exit_val, buf, age):
    """Xb: baseline design; Xl: hazard inputs; folds: season c held, train |S - c| > buf"""
    seasons = sorted(set(S.tolist()))
    base, hur, p_any, p3, p3age = (np.full(len(y), np.nan) for _ in range(5))
    Xa = np.column_stack([np.ones(len(y)), age, age ** 2])
    for c in seasons:
        tr, te = np.abs(S - c) > buf, S == c
        base[te] = Xb[te] @ np.linalg.lstsq(Xb[tr], y[tr], rcond=None)[0]
        f = logit_fit(Xl[tr], stay[tr])
        p_any[te] = f(Xl[te])
        trs = tr & (stay > 0)
        cond = Xb[te] @ np.linalg.lstsq(Xb[trs], y[trs], rcond=None)[0]
        hur[te] = p_any[te] * cond + (1 - p_any[te]) * exit_val
        p3[te] = logit_fit(Xl[tr], stay3[tr])(Xl[te])
        p3age[te] = logit_fit(Xa[tr], stay3[tr])(Xa[te])
    d = (hur - y) ** 2 - (base - y) ** 2
    ps = H.paired((hur - y) ** 2, (base - y) ** 2, S)
    pp = H.paired((hur - y) ** 2, (base - y) ** 2, ids)
    sm = [float(d[S == c].mean()) for c in seasons]
    half = len(seasons) // 2
    first, second = float(np.mean(sm[:half])), float(np.mean(sm[half:]))
    # the column's calibration: ten equal-count bins
    o = np.argsort(p3)
    bins = np.array_split(o, 10)
    cal = [[round(float(p3[b].mean()), 3), round(float(stay3[b].mean()), 3), len(b)] for b in bins]
    out = {'n': len(y), 'seasons': [int(seasons[0]), int(seasons[-1])], 'exitShare': round(float(1 - stay.mean()), 3),
           'rmse': {'base': round(float(np.sqrt(((base - y) ** 2).mean())), 4), 'hurdle': round(float(np.sqrt(((hur - y) ** 2).mean())), 4)},
           'd': round(float(d.mean()), 5), 'tSeason': round(ps['t'], 2), 'pSeason': round(ps['p'], 4), 'tPlayer': round(pp['t'], 2),
           'won': int(sum(v < 0 for v in sm)), 'of': len(seasons), 'firstHalf': round(first, 5), 'secondHalf': round(second, 5),
           'p3': {'brier': round(float(((p3 - stay3) ** 2).mean()), 4), 'brierAge': round(float(((p3age - stay3) ** 2).mean()), 4),
                  'base': round(float(stay3.mean()), 3), 'maxBinErr': round(max(abs(a - b) for a, b, _ in cal), 3), 'bins': cal}}
    out['pass'] = bool(ps['t'] <= -2 and out['won'] > len(seasons) / 2 and first < 0 and second < 0)
    out['p3']['pass'] = bool(out['p3']['maxBinErr'] <= .05 and out['p3']['brier'] < out['p3']['brierAge'])
    print(name, json.dumps({k: v for k, v in out.items() if k != 'p3'}), '\n   p3', json.dumps({k: v for k, v in out['p3'].items() if k != 'bins'}), flush=True)
    return out


def nba():
    import nba_proj3y_research as R
    import nba_proj3y_star_research as SR
    rows = SR.add_history(R.load())
    rows = [r for r in rows if r['S'] <= 2023 and r['y3y'] is not None]
    rng = np.random.default_rng(0)
    n, proj, prior, age, lm, M = R.inputs(rows, 1, rng)
    g = lambda k: np.array([r[k] for r in rows], float)
    d1 = (g('x1') + 2) * g('m1') / (g('m1') + 1000)
    d2 = (g('x2') + 2) * g('m2') / (g('m2') + 1000)
    m3 = g('mp') + g('m1') + g('m2')
    try:
        Xb = SR.design('H4', proj, prior, age, lm, d1, d2, np.log1p(m3))
        form = 'H4'
    except Exception as e:
        Xb, form = R.design('F4', proj, prior, age, lm), f'F4 ({e!r})'
    a = age - 27
    share = g('gp') / g('games')
    Xl = np.column_stack([np.ones(len(a)), proj, a, a * a, lm, share])
    stay = np.array([float(sum(r['fmp']) > 0) for r in rows])
    stay3 = np.array([float(r['fmp'][2] > 0) for r in rows])
    out = run('nba', Xb, Xl, g('y3y'), stay, stay3, g('S').astype(int), np.array([r['id'] for r in rows]), -2.0, 3, a)
    out['baseline'] = form
    return out


def nhl():
    import nhl_proj_research as R
    files = R.load()
    allr = R.rows(files, 2025)
    out = {}
    for part, grps in (('skaters', ['F', 'D']), ('goalies', ['G'])):
        rs = [r for r in allr if (r['grp'] == 'G') == (part == 'goalies') and r['n3'] and r['S'] <= 2023]
        A = R.arr(rs)
        Xb = R.X('bfull', A, grps)
        a = A['age'] - 27
        ix = lambda S, pid: files.get(S, {}).get('_ix', {}).get(pid)
        stay = np.array([float(any(ix(r['S'] + k, r['id']) for k in (1, 2, 3))) for r in rs])
        stay3 = np.array([float(bool(ix(r['S'] + 3, r['id']))) for r in rs])
        gp = np.array([(ix(r['S'], r['id']) or {}).get('gp') or 0 for r in rs], float)
        share = gp / np.array([R.games(r['S']) for r in rs], float)
        Xl = np.column_stack([np.ones(len(a)), A['pw'], a, a * a, A['lt'], share])
        out[part] = run('nhl ' + part, Xb, Xl, A['y3'], stay, stay3, A['S'].astype(int), np.array([r['key'] for r in rs]), 0.0, 0, a)
    # the sport's verdict: skaters and goalies pooled (one test in the family)
    return out


def main(args):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'hurdle.json')
    res = json.load(open(path)) if os.path.exists(path) else {}
    for sp in args or ['nba', 'nhl']:
        res[sp] = {'nba': nba, 'nhl': nhl}[sp]()
        json.dump(res, open(path, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1:])
