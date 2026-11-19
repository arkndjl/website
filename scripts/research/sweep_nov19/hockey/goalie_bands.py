# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Goalie next-season GSAx per shot: danger bands + rebound control vs the pooled Marcel (pre-registered H6).

usage: goalie_bands.py <dir with g<startYear>.csv MoneyPuck goalie season files> <out.json>
"""
import csv, itertools, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H  # noqa: E402

WTS = (1.0, 0.5, 0.25)
BANDS = ('low', 'medium', 'high')
GRID = list(itertools.product((1500, 4000), (500, 1500), (150, 500), (1500, 4000)))


def load(d):
    S = {}
    for y in range(2008, 2026):
        rows = {}
        for r in csv.DictReader(open(os.path.join(d, 'g%d.csv' % y), encoding='utf8')):
            if r['situation'] != 'all':
                continue
            f = lambda k: float(r[k] or 0)
            g = {'shots': f('ongoal'), 'gsax': f('xGoals') - f('goals'), 'reb': f('xRebounds') - f('rebounds')}
            for b in BANDS:
                g['s_' + b] = f(b + 'DangerShots'); g['d_' + b] = f(b + 'DangerxGoals') - f(b + 'DangerGoals')
            rows[r['playerId']] = g
        # centre each rate on the season's shot-weighted league mean
        tot = {k: sum(g[k] for g in rows.values()) for k in next(iter(rows.values()))}
        for g in rows.values():
            g['gsax_c'] = g['gsax'] - g['shots'] * tot['gsax'] / tot['shots']
            g['reb_c'] = g['reb'] - g['shots'] * tot['reb'] / tot['shots']
            for b in BANDS:
                g['d_%s_c' % b] = g['d_' + b] - g['s_' + b] * tot['d_' + b] / tot['s_' + b]
        S[y] = (rows, {b: tot['s_' + b] / sum(tot['s_' + c] for c in BANDS) for b in BANDS})
    return S


def marcel(S, pid, y, num, den, k):
    a = b = 0.0
    for j, w in enumerate(WTS):
        g = S.get(y - j, ({},))[0].get(pid)
        if g:
            a += w * g[num]; b += w * g[den]
    return a / (b + k)


def main(d, out):
    S = load(d)
    fit = json.load(open(os.path.join(ROOT, 'data', 'nhl_war_fit.json')))
    K0 = fit['KG'] / 3600 * 30
    pairs = []
    for y in range(2008, 2025):
        for pid, g in S[y][0].items():
            n = S[y + 1][0].get(pid)
            if n and g['shots'] >= 600 and n['shots'] >= 600:
                pairs.append((y + 1, pid, n['gsax_c'] / n['shots'], n['shots']))
    T = np.array([p[0] for p in pairs]); y = np.array([p[2] for p in pairs]); w = np.array([p[3] for p in pairs])
    base = np.array([marcel(S, p[1], p[0] - 1, 'gsax_c', 'shots', K0) for p in pairs])
    cand = {}
    for ks in GRID:
        cols = [np.array([marcel(S, p[1], p[0] - 1, 'd_%s_c' % b, 's_' + b, k) * S[p[0] - 1][1][b] for p in pairs])
                for b, k in zip(BANDS, ks[:3])]
        cols.append(np.array([marcel(S, p[1], p[0] - 1, 'reb_c', 'shots', ks[3]) for p in pairs]))
        cand[ks] = np.column_stack(cols)

    def ols(X, yy, ww):
        X1 = np.column_stack([np.ones(len(X)), X]); W = ww[:, None]
        return np.linalg.lstsq(X1.T @ (W * X1), X1.T @ (ww * yy), rcond=None)[0]

    def run(folds):
        pb = np.full(len(y), np.nan); pc = np.full(len(y), np.nan); chosen = {}
        for name, tr, te in folds:
            b = ols(base[tr][:, None], y[tr], w[tr]); pb[te] = b[0] + b[1] * base[te]
            best = None
            for ks, X in cand.items():
                bb = ols(X[tr], y[tr], w[tr])
                mse = float(np.sum(w[tr] * (y[tr] - bb[0] - X[tr] @ bb[1:]) ** 2))
                if best is None or mse < best[0]:
                    best = (mse, ks, bb)
            pc[te] = best[2][0] + cand[best[1]][te] @ best[2][1:]; chosen[name] = list(best[1])
        ok = ~np.isnan(pb)
        wn = w[ok] / w[ok].mean()
        eb = wn * np.abs(pb[ok] - y[ok]); ec = wn * np.abs(pc[ok] - y[ok])
        pr = H.paired(ec, eb, T[ok])
        seas = sorted(set(T[ok]))
        won = sum(1 for s in seas if ec[T[ok] == s].mean() < eb[T[ok] == s].mean())
        return {'n': int(ok.sum()), 'maeBase': float(eb.mean()), 'maeCand': float(ec.mean()), 'd': float(pr['d'].mean()) if hasattr(pr['d'], 'mean') else pr['d'],
                't': round(pr['t'], 2), 'p': pr['p'], 'seasonsBetter': '%d/%d' % (won, len(seas)), 'K': chosen}
    seasons = sorted(set(T))
    loso = run([(int(s), T != s, T == s) for s in seasons])
    tsplit = run([('<=2019', T <= 2019, T >= 2020)])
    res = {'pairs': len(pairs), 'K0': K0, 'loso': loso, 'time': tsplit,
           'repeatR': float(np.corrcoef(base, y)[0, 1])}
    json.dump(res, open(out, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
