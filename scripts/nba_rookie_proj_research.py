#!/usr/bin/env python3
"""Research + fit (Nov 3 2026): a rookie projection for the NBA rookie board, XPM + age + rookie minutes.

    python3 scripts/nba_rookie_proj_research.py     # writes data/nba_rookie_proj_fit.json (numpy)

Lead from scripts/nba_rookie_age_research.py: adding log(1 + MP) to XPM + age cut held-out RMSE .942 -> .876 on the
next three seasons' XPM. Same rookies (1,222, classes 2010-23) and target (fx: seasons +1..+3 minutes-weighted XPM,
shrunk to -2 with 1,000 MP).

Live use guard. During a season the board has only part of the minutes, so
    minutes enter as MP82 = MP x 82 / team games played (full-season pace, so lockout years and a partial season sit
    on the same scale), and
    the fit is done per share of the season f (team games / 82). A partial season is simulated from the full one:
    MP_f = MP x f; raw XPM_f = XPM + N(0, s2 (1 / MP_f - 1 / MP)), s2 797 = newcomers' per-minute noise
    (data/nba_proj_fit.json); then shrunk the board's way (role mean -1 + .5 ln(1 + MP82 / 100), MP / (MP + 300));
    log MP82 gets N(0, .25 sqrt((1 - f) / f)) for role changes (an assumption: no partial-season minutes on file).
    20 draws per rookie. Coefficients per f on a grid, linear in between (the board reads f from the season file).
Forms per f, leave one class out: raw (x), age (x + age), proj (x + age + log1p(MP82)).
Kept: proj beats age on held-out RMSE with paired t <= -2 at every f, and held-out calibration slope .8-1.2.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_rookie_age_research as AR

OUT = os.path.join(AR.ROOT, 'data', 'nba_rookie_proj_fit.json')
FS = [0.1, 0.2, 0.35, 0.5, 0.75, 1.0]
S2, K, A0, DRAWS = 797.0, 300.0, 21, 20


def board_x(raw, mp, mp82):
    mu = -1 + 0.5 * np.log1p(mp82 / 100)
    return mu + (raw - mu) * mp / (mp + K)


def X(form, x, age, lm):
    c = {'raw': [x], 'age': [x, age - A0], 'proj': [x, age - A0, lm]}[form]
    return np.column_stack([np.ones_like(x)] + c)


def main():
    rows = AR.load()
    S = np.array([r[0] for r in rows], float)
    sx = np.array([r[1] for r in rows], float)
    age = np.array([r[2] for r in rows], float)
    mp = np.array([r[3] for r in rows], float)
    fx = np.array([r[4] for r in rows], float)
    raw = np.array([r[7] for r in rows], float)
    gm = np.array([r[8] for r in rows], float)
    mp82 = mp * 82 / gm
    chk = board_x(raw, mp, mp82)
    rng = np.random.default_rng(20261103)
    classes = sorted(set(S.astype(int)))
    out = {'n': len(rows), 'classes': [int(classes[0]), int(classes[-1])], 'A0': A0, 'boardCheckMAE': round(float(np.abs(chk - sx).mean()), 3),
           'grid': [], 'note': 'pred = c0 + c1 XPM + c2 (age - 21) + c3 ln(1 + MP82); interpolate on f = min(1, team games / 82)'}
    for f in FS:
        if f < 1:
            n = DRAWS
            Sd, ad, fd = (np.repeat(v, n) for v in (S, age, fx))
            mpf = np.maximum(np.repeat(mp, n) * f, 1.0)
            rawf = np.repeat(raw, n) + rng.normal(0, 1, len(mpf)) * np.sqrt(S2 * np.maximum(1 / mpf - 1 / np.maximum(np.repeat(mp, n), 1), 0))
            lm = np.log1p(np.repeat(mp82, n)) + rng.normal(0, 0.25 * math.sqrt((1 - f) / f), len(mpf))
            m82 = np.expm1(np.maximum(lm, 0))
            xd = board_x(rawf, mpf, m82)
            lm = np.log1p(m82)
        else:
            Sd, ad, fd, xd, lm = S, age, fx, sx, np.log1p(mp82)
        pr = {}
        for form in ('raw', 'age', 'proj'):
            p = np.zeros_like(fd)
            for c in classes:
                tr, te = Sd != c, Sd == c
                b = np.linalg.lstsq(X(form, xd[tr], ad[tr], lm[tr]), fd[tr], rcond=None)[0]
                p[te] = X(form, xd[te], ad[te], lm[te]) @ b
            pr[form] = p
        e = {k: (v - fd) ** 2 for k, v in pr.items()}
        # paired t by player (draws averaged per player, so n = rookies, not draws)
        n0 = len(rows)
        dp = (e['proj'] - e['age']).reshape(n0, -1).mean(1)
        t = float(dp.mean() / (dp.std(ddof=1) / math.sqrt(n0)))
        slope = float(np.polyfit(pr['proj'], fd, 1)[0])
        rho = [AR.spearman(pr['proj'][Sd == c], fd[Sd == c]) for c in classes]
        rhoA = [AR.spearman(pr['age'][Sd == c], fd[Sd == c]) for c in classes]
        b = np.linalg.lstsq(X('proj', xd, ad, lm), fd, rcond=None)[0]
        out['grid'].append({'f': f, 'c': [round(float(v), 4) for v in b],
                            'rmse': {k: round(float(np.sqrt(v.mean())), 4) for k, v in e.items()}, 'tProjVsAge': round(t, 2),
                            'slope': round(slope, 3), 'rho': round(float(np.mean(rho)), 4), 'rhoAge': round(float(np.mean(rhoA)), 4),
                            'rhoClassesWon': int(sum(a > b_ for a, b_ in zip(rho, rhoA)))})
    out['kept'] = all(g['tProjVsAge'] <= -2 and g['rmse']['proj'] < g['rmse']['age'] and 0.8 <= g['slope'] <= 1.2 for g in out['grid'])
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
