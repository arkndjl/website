#!/usr/bin/env python3
"""Do the player projections help the NBA game model? (Noah, Oct 21 2026: player projections "feeding into the game
models (if it improves them)"). Research only; results to data/nba_players_research.json.

    python3 scripts/nba_players_research.py

Two non-circular tests (no market number inside the player lines; the game model's own market term stays as it is):
    plin   the lineup term with each player's minutes from the player model (role minutes, plus the minutes teammates on
           the report free up, shared by role) instead of role minutes x P(play) scaled to 240; in place of lin, and
           on top of it
    ppts   the total: the sum of the players' projected points (x P(play)), fit without the market-total input, as a
           totals input on top of the game model's own
Walk-forward like nba_games_fit (each season fit on the ones before), the game model's fitted params; tune 2021-23,
held out 2024-26 (the player box scores start in 2019). Keep only at paired t <= -1.5 on tuning abs error and lower
held-out error. The minutes and points coefficients are fit on 2021-23 only, so held out is clean.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N  # noqa: E402
import nba_games_fit as GF  # noqa: E402
import nba_players as NP  # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nba_players_research.json')
TUNE, HOLD = (2021, 2022, 2023), (2024, 2025, 2026)


def coefs():
    """minutes and points coefficients fit on the tuning seasons only (points without the market total)"""
    rows = NP.collect()
    D = [r for r in rows if r['y'] and r['nv'] and r['mS'] >= 10 and not r['po'] and r['S'] in TUNE]
    out = {}
    for s, i, feats in (('min', 0, ['base', 'long', 'savg', 'fill', 'eS', 'eB', 'eL']),
                        ('pts', 1, ['base', 'long', 'savg', 'fill', 'pace', 'opp'])):
        A = np.array([[r['fx'][s][f] for f in feats] for r in D])
        y = np.array([r['y'][i] for r in D])
        out[s] = (feats, np.linalg.lstsq(A, y, rcond=None)[0])
    return out


def walk(C):
    import gzip
    games, names = N.load_hist()
    with gzip.open(NP.PHIST, 'rt') as f:
        box = json.load(f)
    F = json.load(open(N.FIT))
    m = N.Model(names, F['P'], inj=GF.load_inj(), **F['params'])
    R = NP.Rates()
    seas = {}
    out = []
    for g in games:
        x, tx = m.feats(g)
        if g['S'] != R.season:
            R.new_season(g['S'])
        if g['S'] >= 2021 and g.get('fin'):
            V, P = {}, {}
            for t in (g['h'], g['a']):
                V[t], P[t] = 0.0, 0.0
            rows = NP.game_rows(m, R, g)
            exp = {g['h']: [], g['a']: []}
            for pid, t, pr, mS, fx in rows:
                cur, prv = seas.get((g['S'], pid)), seas.get((g['S'] - 1, pid))
                NP.add_savg(fx, cur, prv)
                mm = max(0.0, sum(c * fx['min'][f] for f, c in zip(*C['min'])))
                pp = max(0.0, sum(c * fx['pts'][f] for f, c in zip(*C['pts'])))
                exp[t].append((pid, mm * pr, pp * pr))
            for t, lst in exp.items():
                tot = sum(e for _, e, _ in lst)
                sc = 240.0 / tot if tot > 240 else 1.0
                V[t] = sum(m.v(p) * e * sc for p, e, _ in lst) / 48 + (N.REPL * (240 - tot) / 48 if tot < 240 else 0.0)
                P[t] = sum(pp for _, _, pp in lst)
            Bh, Ba = m.rate(m.base, g['h'], 1.0), m.rate(m.base, g['a'], 1.0)
            x = dict(x)
            x['plin'] = (V[g['h']] - Bh) - (V[g['a']] - Ba)
            tx = dict(tx)
            tx['ppts'] = P[g['h']] + P[g['a']]
            out.append((g, x, tx))
        b = box.get(g['id'])
        if b and g.get('fin'):
            R.update(b, (g['h'], g['a']))
            for t in b:
                for r in b[t]:
                    a = seas.setdefault((g['S'], r[0]), [0, 0.0, 0.0, 0.0, 0.0])
                    a[0] += 1; a[1] += r[4]; a[2] += r[5]; a[3] += r[6]; a[4] += r[7]
        m.update(g)
    return out, F


def wf(A, y, S):
    pred = np.full(len(y), np.nan)
    for s in sorted(set(S)):
        tr, te = S < s, S == s
        if tr.sum() >= 500:
            pred[te] = A[te] @ np.linalg.lstsq(A[tr], y[tr], rcond=None)[0]
    return pred


def main():
    C = coefs()
    data, F = walk(C)
    S = np.array([g['S'] for g, _, _ in data])
    y = np.array([g['hs'] - g['as'] for g, _, _ in data], float)
    ty = np.array([g['hs'] + g['as'] for g, _, _ in data], float)
    feats = F['feats']
    res = {'margin': {}, 'total': {}}
    # 2021-22 is the first season with a walk-forward fit inside this window: score 2022-23 tune, 2024-26 held out
    tune, hold = np.isin(S, (2022, 2023)), np.isin(S, HOLD)

    def score(p0, p1, yy):
        e0, e1 = np.abs(yy - p0), np.abs(yy - p1)
        out = {}
        for nm, msk in (('tune', tune), ('hold', hold)):
            d = e1[msk] - e0[msk]
            out[nm] = {'mae0': round(float(e0[msk].mean()), 4), 'mae1': round(float(e1[msk].mean()), 4),
                       't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)}
        out['keep'] = out['tune']['t'] <= -1.5 and out['hold']['mae1'] < out['hold']['mae0']
        return out

    X = lambda fs: np.column_stack([[x[f] for _, x, _ in data] for f in fs])
    base = wf(X(feats), y, S)
    for nm, fs in (('plin for lin', [f if f != 'lin' else 'plin' for f in feats]), ('plin on top', feats + ['plin'])):
        res['margin'][nm] = score(base, wf(X(fs), y, S), y)
        print(nm, res['margin'][nm], flush=True)
    TX = lambda fs: np.column_stack([[tx[f] for _, _, tx in data] for f in fs])
    tb = wf(TX(N.TFEATS), ty, S)
    res['total']['ppts on top'] = score(tb, wf(TX(N.TFEATS + ['ppts']), ty, S), ty)
    res['total']['ppts for pts'] = score(tb, wf(TX([f if f != 'pts' else 'ppts' for f in N.TFEATS]), ty, S), ty)
    print(res['total'], flush=True)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
