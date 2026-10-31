"""Shared pieces of the NBA and NHL player props tests (scripts/nba_props_research.py, scripts/nhl_props.py): the
chance of an over from a projection (negative binomial with a fitted spread and a logistic shape correction), and the
pre-registered one-bet-a-player rule scored at the archived opening prices.

A prop row: {S season, g game, a athlete, st stat, L line, oO, oU (open American), y result, mu projection, P P(over),
q the market's no-vig P(over)}.
"""
import math
from collections import defaultdict

import nba_players as NP

try:                                    # the tests need numpy; the paper books' chance (p_over) is stdlib
    import numpy as np
    import harness as H
except ImportError:
    np = H = None

PSTAR = (.54, .56, .58, .60, .62, .64)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def no_vig(oO, oU):
    a, b = 1 / dec(oO), 1 / dec(oU)
    return a / (a + b)


def var_of(v, mu):
    return max(mu * 1.0001, v[0] * mu + v[1] * mu * mu)


def fit_shape(mu, y, nv, every=2):
    """{'var': [a, b], 'recal': [4]} for one stat: variance a mu + b mu^2 on the residuals, then a logistic on
    logit(NB chance), log mu and their product at prop-like lines (the half point at his average and 1-2 off mu)"""
    k = mu > 0.05
    mu, y, nv = mu[k], y[k], nv[k]
    ab = np.linalg.lstsq(np.column_stack([mu, mu ** 2]), (y - mu) ** 2, rcond=None)[0]
    v = [float(ab[0]), float(ab[1])]
    sub = np.arange(len(mu))[::every]
    offs = (-2, -1, 0, 1, 2) if mu.mean() > 8 else (-1, 0, 1)
    X, Y = [], []
    for L in [np.floor(nv[sub]) + .5] + [np.maximum(.5, np.floor(mu[sub]) + .5 + o) for o in offs]:
        p = np.array([NP.nb_over(a, var_of(v, a), l) for a, l in zip(mu[sub], L)])
        lg = np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
        lm = np.log(mu[sub])
        X.append(np.column_stack([np.ones(len(sub)), lg, lm, lg * lm]))
        Y.append((y[sub] > L).astype(float))
    X, Y = np.concatenate(X), np.concatenate(Y)
    w = np.zeros(4)
    for _ in range(25):
        pz = 1 / (1 + np.exp(-X @ w))
        w += np.linalg.solve((X * (pz * (1 - pz))[:, None]).T @ X + 1e-6 * np.eye(4), X.T @ (Y - pz))
    return {'var': [round(x, 5) for x in v], 'recal': [round(float(x), 5) for x in w]}


def p_over(sh, mu, L):
    p = NP.nb_over(mu, var_of(sh['var'], mu), L)
    w = sh.get('recal')
    if not w or mu <= 0:
        return p
    lg, lm = NP._logit(p), math.log(mu)
    return 1 / (1 + math.exp(-(w[0] + w[1] * lg + w[2] * lm + w[3] * lg * lm)))


def bets(props, ps, seasons, stat=None, one=True, stats=None):
    """the rule: per player a game (one) or per prop, the side with the highest P, if P >= ps.
    (game, profit a unit at the book's price, at -110, at no-vig less 1.5%, side, prop, P, at -113: Novig's median
    prop ask, Oct 29 2026)"""
    best = {}
    for x in props:
        if x['S'] not in seasons or (stat and x['st'] != stat) or (stats and x['st'] not in stats) or x['y'] == x['L']:
            continue
        for side, p in (('o', x['P']), ('u', 1 - x['P'])):
            if p >= ps:
                k = (x['g'], x['a']) if one else (x['g'], x['a'], x['st'])
                if k not in best or p > best[k][0]:
                    best[k] = (p, side, x)
    out = []
    for p, side, x in best.values():
        win = (x['y'] > x['L']) if side == 'o' else (x['y'] < x['L'])
        pr = x['oO'] if side == 'o' else x['oU']
        q = x['q'] if side == 'o' else 1 - x['q']
        nov = 1 / min(.99, q + .015) - 1
        out.append((x['g'], dec(pr) - 1 if win else -1.0, 100 / 110 if win else -1.0, nov if win else -1.0, side, x, p,
                    100 / 113 if win else -1.0))
    return out


def score(bb, col=1):
    if len(bb) < 3:
        return {'n': len(bb)}
    pnl = np.array([b[col] for b in bb])
    pr = H.paired(pnl, np.zeros(len(pnl)), np.array([b[0] for b in bb]))
    return {'n': len(bb), 'games': pr['G'], 'hit': round(float(np.mean([b[1] > 0 for b in bb])), 4),
            'roi': round(float(pnl.mean()), 4), 't': round(pr['t'], 2),
            'over': round(float(np.mean([b[4] == 'o' for b in bb])), 3)}


def evaluate(props, tune, held, stats, pstar=PSTAR):
    """the pre-registered test: p* by ROI at the book's open on tune (100+ bets), scored held out; diagnostics"""
    res = {'n': len(props), 'book': defaultdict(int)}
    for x in props:
        res['book'][f"{x['S']} {x['b']}"] += 1
    res['tune'] = {str(ps): score(bets(props, ps, tune, stats=stats)) for ps in pstar}
    best = max(pstar, key=lambda ps: res['tune'][str(ps)].get('roi', -9) if res['tune'][str(ps)]['n'] >= 100 else -9)
    res['pstar'] = best
    hb = bets(props, best, held, stats=stats)
    res['held'] = {'book': score(hb, 1), '-110': score(hb, 2), '-113': score(hb, 7), 'novig': score(hb, 3)}
    res['heldBySeason'] = {str(s): score(bets(props, best, (s,), stats=stats)) for s in held}
    res['heldByStat'] = {st: score([b for b in hb if b[5]['st'] == st]) for st in stats}
    res['heldBySide'] = {sd: score([b for b in hb if b[4] == sd]) for sd in 'ou'}
    res['heldAllProps'] = score(bets(props, best, held, one=False, stats=stats))
    res['allP'] = {str(ps): {str(s): score(bets(props, ps, (s,), stats=stats)) for s in tuple(tune) + tuple(held)}
                   for ps in pstar}
    # each stat on its own at p* (all of its props, one a player): which markets carry it
    res['byStatAlone'] = {st: {'tune': score(bets(props, best, tune, stat=st)), 'held': score(bets(props, best, held, stat=st))}
                          for st in stats}
    res['diag'] = {}
    for nm, ss in (('tune', tune), ('held', held)):
        xs = [x for x in props if x['S'] in ss and x['y'] != x['L'] and x['st'] in stats]
        if len(xs) < 50:
            continue
        lq = np.array([math.log(x['q'] / (1 - x['q'])) for x in xs])
        lp = np.array([NP._logit(x['P']) for x in xs])
        yy = np.array([float(x['y'] > x['L']) for x in xs])
        X = np.column_stack([np.ones(len(xs)), lq, lp])
        w = np.zeros(3)
        for _ in range(25):
            pz = 1 / (1 + np.exp(-X @ w))
            w += np.linalg.solve((X * (pz * (1 - pz))[:, None]).T @ X + 1e-9 * np.eye(3), X.T @ (yy - pz))
        pq = 1 / (1 + np.exp(-lq))
        br = H.paired((1 / (1 + np.exp(-lp)) - yy) ** 2, (pq - yy) ** 2, np.array([x['g'] for x in xs]))
        res['diag'][nm] = {'n': len(xs), 'overRate': round(float(yy.mean()), 4), 'mktOver': round(float(pq.mean()), 4),
                           'modelOver': round(float(np.mean([x['P'] for x in xs])), 4),
                           'blend': [round(float(v), 3) for v in w], 'brierVsMkt': round(br['d'], 5), 't': round(br['t'], 2),
                           'meanMuMinusLine': round(float(np.mean([x['mu'] - x['L'] for x in xs])), 3)}
    # stakes: chance = .5 + c (P - .5) through (.5, .5), fit on the tune season's bets
    tb = bets(props, best, tune, stats=stats)
    tp = np.array([b[6] for b in tb]); ty = np.array([float(b[1] > 0) for b in tb])
    c = float(((tp - .5) * (ty - .5)).sum() / ((tp - .5) ** 2).sum()) if len(tb) else 0.0
    res['calib'] = {'c': round(c, 3), 'tuneHit': round(float(ty.mean()), 4) if len(tb) else None,
                    'tuneP': round(float(tp.mean()), 4) if len(tb) else None,
                    'heldHit': res['held']['book'].get('hit'), 'heldP': round(float(np.mean([b[6] for b in hb])), 4) if hb else None}
    Hb = res['held']['book']
    res['verdict'] = 'pass' if Hb.get('n', 0) >= 100 and Hb['roi'] > 0 and Hb['t'] >= 2 else 'fail'
    res['book'] = dict(res['book'])
    return res
