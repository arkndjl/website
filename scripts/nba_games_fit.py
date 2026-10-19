"""The NBA game model's backtest and fit (python3 scripts/nba_games.py --fit; numpy). Writes data/nba_games_fit.json.

Walk-forward: each season 2015-2026 is scored by weights fit on the seasons before it. The rating memory and market
steps are tuned on 2015-21 error only; 2022-26 is the held-out report. Inputs beyond the core (Elo, efficiency,
market, home) enter by forward selection: the candidate that most cuts 2015-21 absolute error, if the paired t is
<= -1.5 and 2022-26 error also falls. Play chances by status are measured on the reports (2019-20 on) and, for the
seasons before them, on games missed in a row, minutes-weighted.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N

CORE = ['elo', 'eff', 'mkt', 'home']
CANDS = ['lin', 'rest', 'b2b', 'roster', 'trav', 'tz', 'alt', 'n4', 'b2bRoad', 'po', 'early', 'eloPo']


def load_inj():
    try:
        raw = json.load(open(N.INJ_HIST))
    except (OSError, ValueError):
        return {}
    return {gid: {N.norm(k): v for k, v in rep.items()} for gid, rep in raw.items()}


def measure_P(games, names, inj, params):
    """minutes-weighted share of rotation players who played, by status (or none / no report) and missed streak"""
    acc = {}
    m = N.Model(names, {}, inj=inj, **params)
    for g in games:
        m.feats(g)
        if g['S'] >= N.SCORE_FROM - 1 and g.get('pl'):
            rep = inj.get(g['id'])
            for t in (g['h'], g['a']):
                if t not in g['pl']:
                    continue
                played = {p for p, mn in g['pl'][t] if mn > 0}
                for p in m.roster(t):
                    w, n = m.role[p]
                    R = w / n if n else 0
                    if R < 8:
                        continue                        # rotation players only
                    st = rep.get(N.norm(names.get(p, ''))) if rep is not None else None
                    key = (st if st else ('none' if rep is not None else 'norep'))
                    for k in (key + str(N.bucket(m.streak[p])), key + 'all'):
                        a = acc.setdefault(k, [0.0, 0.0, 0])
                        a[0] += R * (p in played); a[1] += R; a[2] += 1
        m.update(g)
    return {k: round(v[0] / v[1], 3) for k, v in acc.items() if v[2] >= 30}, {k: v[2] for k, v in acc.items()}


def design(games, names, P, params, inj, feats):
    _, data = N.walk(games, names, P, params, inj=inj)
    D = [(g, x, tx) for g, x, tx in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    X = {f: np.array([x[f] for _, x, _ in D]) for f in set(feats) | set(CANDS) | set(N.FEATS)}
    TX = np.array([[tx[f] for f in N.TFEATS] for _, _, tx in D])
    y = np.array([g['hs'] - g['as'] for g, _, _ in D], float)
    ty = np.array([g['hs'] + g['as'] for g, _, _ in D], float)
    S = np.array([g['S'] for g, _, _ in D])
    line = np.array([g['L'] if g.get('L') is not None else np.nan for g, _, _ in D])
    tline = np.array([g['T'] if g.get('T') else np.nan for g, _, _ in D])
    return D, X, TX, y, ty, S, line, tline


def wf(Xm, y, S, lo=N.SCORE_FROM):
    pred = np.full(len(y), np.nan)
    for s in range(lo, int(S.max()) + 1):
        tr, te = S < s, S == s
        if te.any():
            pred[te] = Xm[te] @ np.linalg.lstsq(Xm[tr], y[tr], rcond=None)[0]
    return pred


def mat(X, feats):
    return np.column_stack([X[f] for f in feats])


def paired_t(a, b):
    d = a - b
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def fit():
    games, names = N.load_hist()
    inj = load_inj()
    base = {'hl': 20.0, 'carry': 0.5, 'elo_k': 20.0, 'mk': 0.1, 'mrev': 0.5, 'tk': 0.2, 'rhl': 10.0, 'hca': 2.4}
    P, Pn = measure_P(games, names, inj, base)
    print('P', json.dumps(P))
    tune = lambda S: (S >= N.SCORE_FROM) & (S < N.HOLD_FROM)
    hold = lambda S: S >= N.HOLD_FROM

    # 1. rating memory and market steps, on 2015-21 error with every base input in
    grid = []
    feats0 = CORE + ['lin', 'rest', 'b2b']
    cands = []
    for hl in (12, 20, 30):
        for carry in (0.3, 0.5, 0.7):
            cands.append({**base, 'hl': float(hl), 'carry': carry})
    for mk in (0.05, 0.15, 0.25):
        cands.append({**base, 'mk': mk})
    for mrev in (0.3, 0.7):
        cands.append({**base, 'mrev': mrev})
    for rhl in (5.0, 20.0):
        cands.append({**base, 'rhl': rhl})
    for k in (15.0, 25.0):
        cands.append({**base, 'elo_k': k})
    for n0, rook in ((300.0, -2.0), (1200.0, -2.0), (600.0, -1.0), (600.0, -3.0)):
        cands.append({**base, 'n0': n0, 'rook': rook})
    seen = set()
    for p in cands:
        key = json.dumps(p, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        D, X, TX, y, ty, S, line, tline = design(games, names, P, p, inj, feats0)
        pr = wf(mat(X, feats0), y, S)
        k = tune(S)
        grid.append((float(np.mean(np.abs(pr[k] - y[k]))), p))
        print('grid', round(grid[-1][0], 4), {kk: v for kk, v in p.items() if base.get(kk) != v}, flush=True)
    grid.sort(key=lambda z: z[0])
    # each sweep's winner, combined, when it beat the base settings
    e_base = [e for e, p in grid if p == base][0]
    best, won = dict(base), {}
    for e, p in grid:
        diff = tuple(sorted(kk for kk, v in p.items() if base.get(kk) != v))
        grp = ('hl', 'carry') if set(diff) & {'hl', 'carry'} else ('n0', 'rook') if set(diff) & {'n0', 'rook'} else diff
        if diff and e < e_base and grp not in won:
            won[grp] = e
            best.update({kk: p[kk] for kk in grp})
    print('best', best, flush=True)

    # 2. forward selection of inputs on the tuned walk
    D, X, TX, y, ty, S, line, tline = design(games, names, P, best, inj, feats0)
    k1, k2 = tune(S), hold(S)
    feats = list(CORE)
    cur = wf(mat(X, feats), y, S)
    steps = []
    pool = list(CANDS)
    while pool:
        trial = []
        for c in pool:
            pr = wf(mat(X, feats + [c]), y, S)
            t1 = paired_t(np.abs(pr[k1] - y[k1]), np.abs(cur[k1] - y[k1]))
            d2 = float(np.mean(np.abs(pr[k2] - y[k2])) - np.mean(np.abs(cur[k2] - y[k2])))
            t2 = paired_t(np.abs(pr[k2] - y[k2]), np.abs(cur[k2] - y[k2]))
            trial.append((t1, c, d2, t2, pr))
        trial.sort(key=lambda z: z[0])
        rec = [{'input': c, 't2015_21': round(t1, 2), 'd2022_26': round(d2, 4), 't2022_26': round(t2, 2)} for t1, c, d2, t2, _ in trial]
        steps.append({'with': list(feats), 'tried': rec})
        t1, c, d2, t2, pr = trial[0]
        print('step', feats, rec[:4], flush=True)
        if t1 <= -1.5 and d2 < 0:
            feats.append(c); pool.remove(c); cur = pr
        else:
            break
    pred = cur
    Xm = mat(X, feats)

    # 3. totals
    tpred = wf(TX, ty, S)

    # 4. win probability: sd from residuals vs the sd that best fits wins (2015-21), scored on 2022-26
    ok = ~np.isnan(pred)
    res_sd = float(np.std((pred - y)[ok & k1]))
    win = (y > 0).astype(float)

    def ll(sd, k):
        p = np.clip(np.array([N.phi(m / sd) for m in pred[k]]), 1e-6, 1 - 1e-6)
        return float(-np.mean(win[k] * np.log(p) + (1 - win[k]) * np.log(1 - p)))
    sds = [(ll(s, k1 & ok), s) for s in np.arange(9.0, 16.01, 0.25)]
    win_sd = float(min(sds)[1])
    calib = []
    pk = np.array([N.phi(m / win_sd) if not np.isnan(m) else np.nan for m in pred])
    for lo in np.arange(0.5, 1.0, 0.05):
        fav = np.where(pk >= 0.5, pk, 1 - pk); fw = np.where(pk >= 0.5, win, 1 - win)
        b = k2 & ok & (fav >= lo) & (fav < lo + 0.05)
        if b.sum():
            calib.append({'bin': round(float(lo), 2), 'n': int(b.sum()), 'model': round(float(fav[b].mean()), 3), 'won': round(float(fw[b].mean()), 3)})

    # 5. against the closing line, by block
    mlH = np.array([g.get('mlH') or np.nan for g, _, _ in D], float); mlA = np.array([g.get('mlA') or np.nan for g, _, _ in D], float)

    def imp(o):
        return np.where(o < 0, -o / (-o + 100), 100 / (o + 100))

    def block(k):
        k = k & ok & ~np.isnan(line)
        e = pred[k] - line[k]; r = y[k] - line[k]
        out = {'games': int(k.sum()), 'maeModel': round(float(np.mean(np.abs(pred[k] - y[k]))), 3),
               'maeLine': round(float(np.mean(np.abs(line[k] - y[k]))), 3),
               'tVsLine': round(paired_t(np.abs(pred[k] - y[k]), np.abs(line[k] - y[k])), 2),
               'rModelVsLine': round(float(np.corrcoef(pred[k], line[k])[0, 1]), 3),
               'edgeSlope': round(float(np.polyfit(e, r, 1)[0]), 3)}
        for th in (1, 2, 3, 4):
            pick = (np.abs(e) >= th) & (r != 0)
            n = int(pick.sum())
            out[f'ats{th}'] = {'n': n, 'pct': round(float((np.sign(e[pick]) == np.sign(r[pick])).mean()), 3) if n else None}
        km = k & ~np.isnan(mlH) & ~np.isnan(mlA)
        ph = imp(mlH[km]); pa = imp(mlA[km]); pm = ph / (ph + pa)
        pmod = np.clip(np.array([N.phi(m / win_sd) for m in pred[km]]), 1e-6, 1 - 1e-6)
        w = win[km]
        out['logLossModel'] = round(float(-np.mean(w * np.log(pmod) + (1 - w) * np.log(1 - pmod))), 4)
        out['logLossMarket'] = round(float(-np.mean(w * np.log(pm) + (1 - w) * np.log(1 - pm))), 4)
        out['mlGames'] = int(km.sum())
        kt = k & ~np.isnan(tline)
        out['totalMaeModel'] = round(float(np.mean(np.abs(tpred[kt] - ty[kt]))), 3)
        out['totalMaeLine'] = round(float(np.mean(np.abs(tline[kt] - ty[kt]))), 3)
        return out

    test = {'2015-21 (tuning)': block(k1), '2022-26 (held out)': block(k2), 'all 2015-26': block(S >= N.SCORE_FROM)}
    by_season = {int(s): block(S == s) for s in range(N.SCORE_FROM, int(S.max()) + 1)}
    # what each kept input is worth: held-out error with it dropped
    drop = {}
    for f in feats:
        if f in CORE and f != 'mkt':
            continue
        pr = wf(mat(X, [x for x in feats if x != f]), y, S)
        drop[f] = {'mae2015_21': round(float(np.mean(np.abs(pr[k1] - y[k1]))), 4), 'mae2022_26': round(float(np.mean(np.abs(pr[k2] - y[k2]))), 4),
                   't2022_26': round(paired_t(np.abs(pred[k2] - y[k2]), np.abs(pr[k2] - y[k2])), 2)}

    b = np.linalg.lstsq(Xm, y, rcond=None)[0]
    r = y - Xm @ b; s2 = r @ r / (len(y) - len(b)); cov = s2 * np.linalg.inv(Xm.T @ Xm)
    tb = np.linalg.lstsq(TX, ty, rcond=None)[0]
    out = {'params': best, 'feats': feats, 'coef': {f: round(float(v), 4) for f, v in zip(feats, b)},
           't': {f: round(float(v / math.sqrt(cov[i, i])), 1) for i, (f, v) in enumerate(zip(feats, b))},
           'tcoef': {f: round(float(v), 4) for f, v in zip(N.TFEATS, tb)},
           'sd': round(win_sd, 2), 'resSd': round(res_sd, 2), 'tsd': round(float(np.nanstd(tpred - ty)), 2),
           'P': P, 'Pn': Pn, 'test': test, 'bySeason': by_season, 'calib': calib, 'drop': drop, 'select': steps,
           'grid': [[round(e, 4), {kk: v for kk, v in p.items() if base.get(kk) != v}] for e, p in grid]}
    with open(N.FIT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ('grid', 'select', 'bySeason', 'Pn')}, indent=1))
    # the walk-forward predictions, for the picks backtest
    rows = []
    for (g, _, _), m, tm in zip(D, pred, tpred):
        if not np.isnan(m) and g.get('L') is not None:
            rows.append({'id': g['id'], 'S': int(g['S']), 'm': round(float(m), 2), 'L': g['L'], 'Lo': g.get('Lo'), 'res': g['hs'] - g['as'],
                         'mlH': g.get('mlH'), 'mlA': g.get('mlA'), 'oH': g.get('oH'), 'oA': g.get('oA'),
                         'tip': g['tip'], 'h': g['h'], 'a': g['a'], 'po': 1 if g['t'] == 3 else 0,
                         'tm': None if np.isnan(tm) else round(float(tm), 2), 'T': g.get('T'), 'tot': g['hs'] + g['as']})
    with open(os.path.join(N.ROOT, 'scripts', '.cache', 'nba', 'wf_preds.json'), 'w') as f:
        json.dump(rows, f)
    return out
