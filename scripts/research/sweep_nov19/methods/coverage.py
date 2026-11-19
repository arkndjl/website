# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Held-out coverage of the site's 80% ranges, current band against the conformal band (PREREG.md M7).

    python3 scripts/research/sweep_nov19/methods/coverage.py [--write]    # --write: data/coverage_scorecard.json

Walk forward: each scored season's band is calibrated on out-of-fold residuals of seasons strictly before it
(3Y targets: seasons whose three-season outcome was complete by then). Pass per board: coverage within 3 points of
80% overall and in every group with 100+ scored rows, and no wider than the current band where there is one.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)
import conformal as CF  # noqa: E402

OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))
TOL = 0.03


def verdict(c, cur=None):
    ok = abs(c['cover'] - .8) <= TOL and all(abs(g['cover'] - .8) <= TOL for g in c['groups'].values() if g['n'] >= 100)
    if cur is not None:
        ok = ok and c['width'] <= cur['width'] + 1e-9
    return bool(ok)


def walk_signed(f, y, S, grp, lag, first_cal=3):
    """signed-residual conformal, season by season; lag: seasons between a row and its finished outcome"""
    lo, hi = np.full(len(y), np.nan), np.full(len(y), np.nan)
    seasons = sorted(set(S.tolist()))
    for s in seasons:
        cal = S <= s - lag
        if len(set(S[cal].tolist())) < first_cal:
            continue
        te = S == s
        lo[te], hi[te] = CF.signed((y - f)[cal], grp[cal], f[te], grp[te])
    ok = ~np.isnan(lo)
    return lo, hi, ok


def cbb_fv():
    import fv_dist_fit as FD
    rows = FD.cbb_rows()
    fit = json.load(open(os.path.join(ROOT, 'data', 'fv_dist.json')))['cbb']
    FD.HINGES = tuple(fit['hinges'])
    _, extra = FD.cbb_terms()
    terms = [t for t in extra if t[0] in fit['kept']]
    S = np.array([r['season'] for r in rows]); y = np.array([r['y'] for r in rows]); x = np.array([r['x'] for r in rows])
    grp = np.where(x < 35, '<35', np.where(x < 45, '35-44', '45+'))
    k = np.array([FD.bin_of(v) for v in y])
    X, Z = FD.loc_x(x), FD.scale_z(rows, terms)

    def bands(tr, te):
        m = FD.Model(X.shape[1], Z.shape[1]).fit(X[tr], Z[tr], k[tr])
        P = m.predict(X[te], Z[te])
        fl = FD.floor_share(y[tr])
        return np.array([FD.quantile(p, .1, fl) for p in P]), np.array([FD.quantile(p, .9, fl) for p in P])
    lo0, hi0, lo1, hi1 = (np.full(len(y), np.nan) for _ in range(4))
    for s in sorted(set(S.tolist())):
        past = S < s
        ps = sorted(set(S[past].tolist()))
        if len(ps) < 3:
            continue
        te = S == s
        lo0[te], hi0[te] = bands(past, te)
        cl, ch = np.full(len(y), np.nan), np.full(len(y), np.nan)
        for c in ps:                                  # calibration bands out of fold: one earlier class left out at a time
            cl[S == c], ch[S == c] = bands(past & (S != c), S == c)
        lo1[te], hi1[te] = CF.band(cl[past], ch[past], y[past], grp[past], lo0[te], hi0[te], grp[te])
    ok = ~np.isnan(lo0)
    cur, new = CF.coverage(lo0[ok], hi0[ok], y[ok], grp[ok]), CF.coverage(np.maximum(lo1[ok], 20), hi1[ok], y[ok], grp[ok])
    return {'label': 'CBB FV range', 'outcome': 'realised FV, boards 2010-16', 'scored': sorted(set(S[ok].tolist())), 'top': '45+',
            'current': cur, 'conformal': new, 'currentPass': verdict(cur), 'pass': verdict(new, cur)}


def nba_3y():
    import nba_proj3y_research as R
    import nba_proj3y_star_research as SR
    rows = [r for r in SR.add_history(R.load()) if r['S'] <= 2023 and r['y3y'] is not None]
    n, proj, prior, age, lm, M = R.inputs(rows, 1, np.random.default_rng(0))
    g = lambda k: np.array([r[k] for r in rows], float)  # noqa: E731
    d1 = (g('x1') + 2) * g('m1') / (g('m1') + 1000); d2 = (g('x2') + 2) * g('m2') / (g('m2') + 1000)
    Xb = SR.design('H4', proj, prior, age, lm, d1, d2, np.log1p(g('mp') + g('m1') + g('m2')))
    S, y = g('S').astype(int), g('y3y')
    f = np.zeros(len(y))
    for c in sorted(set(S.tolist())):
        tr, te = np.abs(S - c) > 3, S == c
        f[te] = Xb[te] @ np.linalg.lstsq(Xb[tr], y[tr], rcond=None)[0]
    grp = np.where(proj < 0, '<0', np.where(proj < 2, '0-2', '2+'))
    lo, hi, ok = walk_signed(f, y, S, grp, 3)
    new = CF.coverage(lo[ok], hi[ok], y[ok], grp[ok])
    return {'label': 'NBA 3Y XPM (shrunk target)', 'outcome': 'XPM over the next three seasons, shrunk to -2', 'scored': sorted(set(S[ok].tolist())),
            'top': '2+', 'current': None, 'conformal': new, 'pass': verdict(new)}


def nhl_3y():
    import nhl_proj_research as R
    from hurdle import logit_fit
    files = R.load()
    allr = R.rows(files, 2025)
    rs = [r for r in allr if r['grp'] != 'G' and r['n3'] and r['S'] <= 2023]
    A = R.arr(rs)
    ix = lambda S_, pid: files.get(S_, {}).get('_ix', {}).get(pid)  # noqa: E731
    stay = np.array([float(any(ix(r['S'] + k, r['id']) for k in (1, 2, 3))) for r in rs])
    share = np.array([((ix(r['S'], r['id']) or {}).get('gp') or 0) / R.games(r['S']) for r in rs])
    a = A['age'] - 27
    Xb, Xl = R.X('bfull', A, ['F', 'D']), np.column_stack([np.ones(len(a)), A['pw'], a, a * a, A['lt'], share])
    S, y = A['S'].astype(int), A['y3']
    f = np.zeros(len(y))
    for c in sorted(set(S.tolist())):
        tr, te = S != c, S == c
        trs = tr & (stay > 0)
        f[te] = logit_fit(Xl[tr], stay[tr])(Xl[te]) * (Xb[te] @ np.linalg.lstsq(Xb[trs], y[trs], rcond=None)[0])
    grp = np.where(A['pw'] < .5, '<0.5', np.where(A['pw'] < 2, '0.5-2', '2+'))
    lo, hi, ok = walk_signed(f, y, S, grp, 3)
    new = CF.coverage(lo[ok], hi[ok], y[ok], grp[ok])
    # the constants the live column would use: residual quantiles by group on every finished season
    q = {str(k): [round(CF._q_lo((y - f)[grp == k], .1), 2), round(CF._q_hi((y - f)[grp == k], .9), 2)] for k in np.unique(grp)}
    return {'label': 'NHL 3Y WAR, skaters', 'outcome': 'WAR over the next three seasons', 'scored': sorted(set(S[ok].tolist())), 'top': '2+',
            'current': None, 'conformal': new, 'pass': verdict(new), 'q': q}


def main():
    out = {'level': 0.8, 'tolerance': TOL, 'boards': {}}
    for name, fn in (('cbb_fv', cbb_fv), ('nba_3y', nba_3y), ('nhl_3y', nhl_3y)):
        if len(sys.argv) > 1 and not sys.argv[1].startswith('--') and name not in sys.argv[1:]:
            continue
        r = fn()
        out['boards'][name] = r
        print(name, json.dumps(r), flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, 'coverage.json'), 'w'), indent=1)
    if '--write' in sys.argv:
        json.dump(out, open(os.path.join(ROOT, 'data', 'coverage_scorecard.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
