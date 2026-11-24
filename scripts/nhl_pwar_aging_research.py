#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Cross-sport port of the Nov 24 2026 pXPM change (scripts/nba_pxpm_research.py): does an aging term help NHL pWAR?
pWAR's HPM already has the other two pieces (Marcel weights over three seasons, an ice-time shrink toward a learned
target that sits below average for short histories). The new piece is the aging curve.

Candidate: skater HPM_S + a x cv_grp(age + 1), cv = next-season change in descriptive goals above average a 60
((go + gd) / TOI x 60) by age, F and D apart, quadratic in age (20-38 clipped), harmonic-mean ice-time weights,
fit only on season pairs ending <= S (point in time). Goalies unchanged.
Tests (season S -> S+1, S 2011-25; rates and shares, so short seasons stay in):
  team    sum over S+1 skaters + goalies of value x S+1 share of team ice time (5 skaters / 1 goalie) -> team S+1 goals
          above average a game (sum of go + gd / games), R2 pooled.
  player  next-season goals above average a 60, skaters with 300+ minutes next season, weighted by them, RMSE after a
          per-fold linear calibration (HPM is a projected rate on its own scale).
a picked leave one season out on the other seasons (grid 0 .. 2), per target. Pass: team R2 up on held-out
predictions with season-paired t >= 2 (squared-error gain) and player RMSE down (t <= -2).
Caveat: the season files' HPM uses the stored pWAR weights (fit on all seasons); both arms share it.
-> data/nhl_pwar_aging_research.json"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..')
SRC = os.path.join(ROOT, 'static', 'data', 'nhl-war')
F = {}
for fn in sorted(os.listdir(SRC)):
    if fn.endswith('.json'):
        d = json.load(open(os.path.join(SRC, fn)))
        F[d['season']] = d
LAST = max(F) - 1                                         # last complete season
SEAS = [S for S in range(2011, LAST) if S + 1 in F and S in F]
GRID = [0, .25, .5, .75, 1.0, 1.25, 1.5, 2.0]


def gaa(p):
    return (p.get('go') or 0) + (p.get('gd') or 0)


def curve(S):
    """grp -> age -> expected change, pairs (s-1, s) with s <= S"""
    out = {}
    for grp in ('F', 'D'):
        xs, ds, ws = [], [], []
        for s in range(min(F) + 1, S + 1):
            A = {p['id']: p for p in F[s - 1]['players'] if p['grp'] == grp and p['toi'] >= 100}
            for p in F[s]['players']:
                q = A.get(p['id'])
                if not q or p['grp'] != grp or p['toi'] < 100 or not q.get('age'): continue
                xs.append(min(max(q['age'] + 1, 20), 38) - 27)
                ds.append(gaa(p) / p['toi'] * 60 - gaa(q) / q['toi'] * 60)
                ws.append(2 / (1 / q['toi'] + 1 / p['toi']))
        x, d, w = map(np.array, (xs, ds, ws))
        A = np.column_stack([np.ones_like(x), x, x * x]) * np.sqrt(w)[:, None]
        c = np.linalg.lstsq(A, d * np.sqrt(w), rcond=None)[0]
        out[grp] = lambda ag, c=c: float(c[0] + c[1] * (min(max(ag, 20), 38) - 27) + c[2] * (min(max(ag, 20), 38) - 27) ** 2)
    return out


CV = {S: curve(S) for S in SEAS}


def values(S, a):
    out = {}
    for p in F[S]['players']:
        v = p.get('hpm')
        if v is None: continue
        if a and p['grp'] in ('F', 'D') and p.get('age'): v += a * CV[S][p['grp']](p['age'] + 1)
        out[p['id']] = v
    return out


def team_rows(vals, S):
    nx = F[S + 1]['players']
    low = [vals[p['id']] for p in F[S]['players'] if p['id'] in vals and p['toi'] < 300 and p['grp'] != 'G']
    fs = float(np.mean(low)) if low else 0.0
    lowg = [vals[p['id']] for p in F[S]['players'] if p['id'] in vals and p['toi'] < 300 and p['grp'] == 'G']
    fg = float(np.mean(lowg)) if lowg else 0.0
    tt, tg, X, Y, G = {}, {}, {}, {}, {}
    for p in nx:
        (tg if p['grp'] == 'G' else tt)[p['tm']] = (tg if p['grp'] == 'G' else tt).get(p['tm'], 0) + p['toi']
        Y[p['tm']] = Y.get(p['tm'], 0) + gaa(p); G[p['tm']] = max(G.get(p['tm'], 0), p['gp'])
    for p in nx:
        g = p['grp'] == 'G'; v = vals.get(p['id'], fg if g else fs)
        X[p['tm']] = X.get(p['tm'], 0) + v * (1 if g else 5) * p['toi'] / (tg if g else tt)[p['tm']]
    return [(X[t], Y[t] / max(G[t], 1)) for t in X if t in tt and t in tg]


def pl_rows(vals, S):
    return [(vals[p['id']], gaa(p) / p['toi'] * 60, p['toi']) for p in F[S + 1]['players']
            if p['grp'] != 'G' and p['toi'] >= 300 and p['id'] in vals]


def r2(rows):
    a = np.array(rows); return float(np.corrcoef(a[:, 0], a[:, 1])[0, 1] ** 2)


def cal_sse(train, test):
    a, b = np.array(train), np.array(test)
    A = np.column_stack([np.ones(len(a)), a[:, 0]]) * np.sqrt(a[:, 2])[:, None]
    c = np.linalg.lstsq(A, a[:, 1] * np.sqrt(a[:, 2]), rcond=None)[0]
    e = b[:, 1] - c[0] - c[1] * b[:, 0]
    return float((b[:, 2] * e * e).sum()), float(b[:, 2].sum())


def team_sse(train, test):
    a, b = np.array(train), np.array(test)
    c = np.polyfit(a[:, 0], a[:, 1], 1); e = b[:, 1] - np.polyval(c, b[:, 0])
    return float((e * e).sum())


def main():
    T = {a: {S: team_rows(values(S, a), S) for S in SEAS} for a in GRID}
    L = {a: {S: pl_rows(values(S, a), S) for S in SEAS} for a in GRID}
    res = {'seasons': SEAS, 'grid': GRID, 'full': {a: {'team': round(r2(sum(T[a].values(), [])), 4)} for a in GRID}}
    print({a: v['team'] for a, v in res['full'].items()})
    # team: held-out squared error of a calibrated line fit on the other seasons
    pick_t, pick_p, et, e0, pt, p0 = {}, {}, [], [], [], []
    for h in SEAS:
        tr = [S for S in SEAS if S != h]
        sse = lambda a: sum(team_sse(sum((T[a][S] for S in tr if S != s), []), T[a][s]) for s in tr)
        at = min(GRID, key=sse); pick_t[h] = at
        trn = lambda a: sum((T[a][S] for S in tr), [])
        et.append(team_sse(trn(at), T[at][h])); e0.append(team_sse(trn(0), T[0][h]))
        psse = lambda a: sum(cal_sse(sum((L[a][S] for S in tr if S != s), []), L[a][s])[0] for s in tr)
        ap = min(GRID, key=psse); pick_p[h] = ap
        trl = lambda a: sum((L[a][S] for S in tr), [])
        s1, w1 = cal_sse(trl(ap), L[ap][h]); s0, _ = cal_sse(trl(0), L[0][h])
        pt.append(math.sqrt(s1 / w1)); p0.append(math.sqrt(s0 / w1))
        print(h, 'team a', at, round(et[-1] - e0[-1], 4), 'player a', ap, round(pt[-1] - p0[-1], 4), flush=True)
    dt = np.array(e0) - np.array(et); dp = np.array(pt) - np.array(p0)
    tstat = lambda d: float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() > 0 else 0.0
    res['team'] = {'picks': pick_t, 'sseGain': round(float(dt.sum()), 4), 't': round(tstat(dt), 2), 'better': int((dt > 0).sum()), 'of': len(dt)}
    res['player'] = {'picks': pick_p, 'rmse': round(float(np.mean(pt)), 4), 'rmse0': round(float(np.mean(p0)), 4),
                     't': round(tstat(dp), 2), 'better': int((dp < 0).sum()), 'of': len(dp)}
    res['pass'] = res['team']['t'] >= 2 and res['player']['t'] <= -2
    print(json.dumps({k: res[k] for k in ('team', 'player', 'pass')}, indent=1))
    json.dump(res, open(os.path.join(ROOT, 'data', 'nhl_pwar_aging_research.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
