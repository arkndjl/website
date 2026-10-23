#!/usr/bin/env python3
"""Research: players back from a lost season (Haliburton 2026-27, Lillard, Irving, Tatum) in the NBA priors.

    python3 scripts/nba_returners_research.py           # player level -> data/nba_returners_research.json (numpy)
    python3 scripts/nba_returners_research.py --games   # game level (walk-forward, as nba_roster_research.py)

The game model's prior for a player (nba_games.values) is last season's XPM plus the season before at half weight,
minutes-weighted and shrunk toward -1 with 600 minutes. A player who missed last season keeps only the older season
at half weight, so a +4.7 Haliburton enters 2026-27 at +2.8, and two lost seasons make anyone a newcomer.

Returner: under RL minutes last season (1,000 shipped; RL=300/500/800 env to compare) and 1,000+ in one of the three seasons before. Variants of his prior:
    base     the live prior
    shift    his last two healthy seasons (RL+ minutes, up to four back) stand in for last season and the one before;
             last season's few minutes count at full weight on top
    +age     plus the aging curve (nba_games.aging_curve, fit on earlier pairs) summed over each year since his last
             healthy season
    +disc    plus a return discount: the minutes-weighted mean residual of returners in earlier seasons only
Scored on the return season's XPM, weighted by its minutes; 2013-21 for selection, 2022-26 held out. Minutes:
return-season minutes a game against the last healthy season's, next to every other player's change at the same
minutes (the game model carries a player's role minutes over a lost season unchanged).
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N

OUT = os.path.join(N.ROOT, 'data', 'nba_returners_research.json')
RL, HEALTHY = int(os.environ.get("RL", 1000)), 1000


def xfile(S):
    fn = os.path.join(N.XPM, f'{S}.json')
    if not os.path.exists(fn):
        return {}
    return {p['id']: p for p in json.load(open(fn))['players'] if p.get('xpm') is not None and not p.get('pr')}


def prior(F, pid, S, n0=600.0, rook=-1.0, w2=0.5, mode='base', cv=None):
    a, b = F[S - 1].get(pid), F[S - 2].get(pid)
    if mode == 'base':
        rows = [(a, 1.0), (b, w2)]
        gap = 0
    else:
        hist = [F[S - k].get(pid) for k in range(1, 5)]
        good = [(k, h) for k, h in enumerate(hist, 1) if h and h['mp'] >= RL]
        rows = [(a, 1.0)] if a and a['mp'] < RL else []
        rows += [(h, w) for (k, h), w in zip(good[:2], (1.0, w2))]
        gap = good[0][0] - 1 if good else 0
    num, den = rook * n0, n0
    for r, w in rows:
        if r:
            num += r['xpm'] * r['mp'] * w; den += r['mp'] * w
    v = num / den
    if cv and gap and rows:
        h = [r for r, _ in rows if r and r['mp'] >= RL][0]
        if h.get('age'):
            v += sum(cv(h['age'] + j) for j in range(1, gap + 1)) * (den - n0) / den
    return v


def returners(F, S):
    out = []
    for pid, p in F[S].items():
        a = F[S - 1].get(pid)
        if (a and a['mp'] >= RL) or p['mp'] < 100:
            continue
        if not any(F[S - k].get(pid, {}).get('mp', 0) >= HEALTHY for k in (2, 3, 4)):
            continue
        out.append(pid)
    return out


def run():
    F = {S: xfile(S) for S in range(2006, 2028)}
    rows = []
    for S in range(2013, 2027):
        cv = N.aging_curve(S)
        for pid in returners(F, S):
            p = F[S][pid]
            hist = [F[S - k].get(pid) for k in range(1, 5)]
            last = next(h for h in hist[1:] if h and h['mp'] >= RL)
            gap = next(k for k, h in enumerate(hist, 1) if h and h['mp'] >= RL) - 1
            rows.append({'S': S, 'id': pid, 'n': p['n'], 'age': p.get('age'), 'gap': gap, 'y': p['xpm'], 'mp': p['mp'],
                         'g': p['g'], 'mpg0': last['mp'] / max(1, last['g']), 'mpg': p['mp'] / max(1, p['g']),
                         'pre': last['xpm'], 'base': prior(F, pid, S), 'shift': prior(F, pid, S, mode='shift'),
                         'age_': prior(F, pid, S, mode='shift', cv=cv)})
    S = np.array([r['S'] for r in rows]); y = np.array([r['y'] for r in rows]); w = np.array([r['mp'] for r in rows], float)
    k1, k2 = S <= 2021, S >= 2022
    res = {'n': {'2013_21': int(k1.sum()), '2022_26': int(k2.sum())}, 'variants': {}}
    # the discount, walk-forward: each season's from returners in earlier seasons only (2013-14 use 2013-14 pooled)
    for v in ('base', 'shift', 'age_'):
        x = np.array([r[v] for r in rows])
        for disc in (False, True):
            pr = x.copy()
            if disc:
                for s in np.unique(S):
                    k = S < s if (S < s).sum() >= 15 else S <= 2014
                    pr[S == s] += np.average(y[k] - x[k], weights=w[k])
            lab = v.rstrip('_').replace('age', 'shift+age') + ('+disc' if disc else '')
            e = pr - y
            r = {}
            for nm, k in (('2013_21', k1), ('2022_26', k2)):
                r[nm] = {'mae': round(float(np.average(np.abs(e[k]), weights=w[k])), 3),
                         'rmse': round(float(np.sqrt(np.average(e[k] ** 2, weights=w[k]))), 3),
                         'bias': round(float(np.average(e[k], weights=w[k])), 3)}
            res['variants'][lab] = r
            if lab == 'shift+age+disc':
                for r_, p_ in zip(rows, pr):
                    r_['pred'] = round(float(p_), 2)
    for v in ('shift', 'age_'):
        x = np.array([r[v] for r in rows])
        res['disc_' + v.rstrip('_')] = {nm: round(float(np.average(y[k] - x[k], weights=w[k])), 3) for nm, k in
                                        (('2013_21', k1), ('2022_26', k2), ('all', k1 | k2))}
        g = np.array([r['gap'] for r in rows])
        res['disc_' + v.rstrip('_') + '_byGap'] = {str(G): [round(float(np.average(y[g == G] - x[g == G], weights=w[g == G])), 3), int((g == G).sum())]
                                                   for G in (1, 2, 3) if (g == G).sum()}
    # minutes: returners' minutes a game vs their last healthy season, against all players at the same minutes
    m0 = np.array([r['mpg0'] for r in rows]); m1 = np.array([r['mpg'] for r in rows]); gw = np.array([r['g'] for r in rows], float)
    allc = []
    for s in range(2013, 2027):
        for pid, p in F[s].items():
            q = F[s - 1].get(pid)
            if q and q['mp'] >= RL and p['mp'] >= 100:
                allc.append((q['mp'] / q['g'], p['mp'] / p['g'], p['g']))
    A = np.array(allc)
    band = lambda lo, hi, a, b, g: (round(float(np.average(b[(a >= lo) & (a < hi)] - a[(a >= lo) & (a < hi)], weights=g[(a >= lo) & (a < hi)])), 2), int(((a >= lo) & (a < hi)).sum()))
    res['minutes'] = {f'{lo}-{hi}': {'returners': band(lo, hi, m0, m1, gw), 'everyone': band(lo, hi, A[:, 0], A[:, 1], A[:, 2])}
                      for lo, hi in ((0, 20), (20, 28), (28, 33), (33, 48))}
    res['games'] = {'returnersGamesShare': round(float(gw.sum() / len(rows)), 1)}
    res['rows'] = sorted(rows, key=lambda r: (-r['S'], -r['mp']))
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != 'rows'}, indent=1))
    for r in res['rows'][:25]:
        print(r['S'], r['n'], r['gap'], 'pre', r['pre'], 'base', round(r['base'], 2), 'new', r.get('pred'), 'actual', r['y'], r['mp'])


def games():
    """game level: the live model against ret (the returner prior) and ret + retm (role minutes x retm at the
    rollover), walk-forward refit of the margin coefficients as in nba_roster_research.py, scored on all games and on
    games where a returner changes either lineup's value (|roster| moves .05+). Kept: paired t <= -1.5 on 2015-21 and
    2022-26 no worse"""
    import nba_games_fit as Fit
    F = json.load(open(N.FIT))
    G, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']

    def design(params):
        _, data = N.walk(G, names, P, params, inj=inj)
        D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x in D], float) for f in D[0][1]}
        return X, np.array([g['hs'] - g['as'] for g, _ in D], float), np.array([g['S'] for g, _ in D]), \
            np.array([g['L'] if g.get('L') is not None else np.nan for g, _ in D])
    X0, y, S, line = design(base)
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    ok = ~np.isnan(line)
    out = []
    # minutes factor, pre-registered from the player study: returners played .80 (2013-21) of their last healthy
    # season's minutes a game, everyone else about .95, so x.85
    V = (('ret 500', {'ret': 500}), ('ret 1000', {'ret': 1000}), ('ret 500 + retm .85', {'ret': 500, 'retm': 0.85}),
         ('retm .85 only', {'retm': 0.85}), ('ret 1000 + retm .85', {'ret': 1000, 'retm': 0.85}))
    if '--only' in sys.argv:                            # rerun some variants: --only 4 (indices into V)
        V = [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    for lab, extra in V:
        X, _, _, _ = design({**base, **extra})
        pr = Fit.wf(Fit.mat(X, feats), y, S)
        aff = np.abs(X['roster'] - X0['roster']) + np.abs(X['lin'] - X0['lin']) > 0.05
        r = {'label': lab}
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            for sub, kk in (('all', k), ('returnerGames', k & aff)):
                e, e0 = np.abs(pr[kk] - y[kk]), np.abs(ref[kk] - y[kk])
                r[f'{sub}{nm}'] = {'n': int(kk.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4),
                                   't': round(Fit.paired_t(e, e0), 2),
                                   'maeLine': round(float(np.abs(line[kk & ok] - y[kk & ok]).mean()), 4),
                                   'maeModelLined': round(float(np.abs(pr[kk & ok] - y[kk & ok]).mean()), 4),
                                   'maeLiveLined': round(float(np.abs(ref[kk & ok] - y[kk & ok]).mean()), 4)}
        r['kept'] = r['all2015_21']['t'] <= -1.5 and r['all2022_26']['d'] <= 0
        r['keptReturnerGames'] = r['returnerGames2015_21']['t'] <= -1.5 and r['returnerGames2022_26']['d'] <= 0 and r['all2022_26']['d'] <= 0.001
        print(json.dumps(r), flush=True)
        out.append(r)
    if '--only' in sys.argv:
        out = [r for r in json.load(open(OUT.replace('.json', '_games.json'))) if r['label'] not in {o['label'] for o in out}] + out
    with open(OUT.replace('.json', '_games.json'), 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    games() if '--games' in sys.argv else run()
