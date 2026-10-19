#!/usr/bin/env python3
"""Research on the NBA game model (scripts/nba_games.py): totals, Elo, the win-probability sd, the market blend.

    python3 scripts/nba_games_research.py      # writes data/nba_games_research.json (numpy; ~5 min)

Same walk-forward as the fit (scripts/nba_games_fit.py): each season 2015-26 is scored by weights fit on the seasons
before it, with the live model's settings and inputs. A change is kept only if it cuts 2015-21 error at paired
per-game t <= -1.5 and 2022-26 (held out) does not get worse.
    totals   the possession model split into league level, pace and efficiency, pace as a product, home court
    margin   the efficiency term split into offense and defense, or with pace as a product
    elo      K and the offseason carry, and a points Elo stepped on margin minus expected margin
    sd       win probability sd by games played (stage of season), on log loss
    blend    w x model + (1 - w) x close, margin and win probability (report only)
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_games_fit as Fit

OUT = os.path.join(N.ROOT, 'data', 'nba_games_research.json')
TX0 = ['pts', 'tmkt', 'po', 'one']


def design(games, names, P, params, inj):
    _, data = N.walk(games, names, P, params, inj=inj)
    D = [(g, x, tx) for g, x, tx in data if g.get('fin') and g['S'] >= N.FIRST + 1]
    X = {f: np.array([x[f] for _, x, _ in D], float) for f in D[0][1]}
    TX = {f: np.array([tx[f] for _, _, tx in D], float) for f in D[0][2]}
    y = np.array([g['hs'] - g['as'] for g, _, _ in D], float)
    ty = np.array([g['hs'] + g['as'] for g, _, _ in D], float)
    S = np.array([g['S'] for g, _, _ in D])
    line = np.array([g['L'] if g.get('L') is not None else np.nan for g, _, _ in D])
    tline = np.array([g['T'] if g.get('T') else np.nan for g, _, _ in D])
    return D, X, TX, y, ty, S, line, tline


def mat(X, feats):
    return np.column_stack([X[f] for f in feats])


def r4(v):
    return round(float(v), 4)


def compare(pr, base, y, k1, k2):
    """paired per-game abs error, candidate minus base: 2015-21 t, 2022-26 change and t"""
    a1, b1 = np.abs(pr[k1] - y[k1]), np.abs(base[k1] - y[k1])
    a2, b2 = np.abs(pr[k2] - y[k2]), np.abs(base[k2] - y[k2])
    return {'mae2015_21': r4(a1.mean()), 'd2015_21': r4(a1.mean() - b1.mean()), 't2015_21': round(Fit.paired_t(a1, b1), 2),
            'mae2022_26': r4(a2.mean()), 'd2022_26': r4(a2.mean() - b2.mean()), 't2022_26': round(Fit.paired_t(a2, b2), 2)}


def passes(c):
    return c['t2015_21'] <= -1.5 and c['d2022_26'] <= 0


def ll_vec(p, w):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(w * np.log(p) + (1 - w) * np.log(1 - p))


def Phi(z):
    from math import erf
    return 0.5 * (1 + np.vectorize(erf)(z / math.sqrt(2)))


def main():
    games, names = N.load_hist()
    inj = Fit.load_inj()
    F = json.load(open(N.FIT))
    P, feats, sd0 = F['P'], F['feats'], F['sd']
    params = {k: v for k, v in F['params'].items() if k != 'thl'}      # the base: totals on the margin's ratings
    res = {'base': {'params': params, 'feats': feats, 'tfeats': TX0}}
    D, X, TX, y, ty, S, line, tline = design(games, names, P, params, inj)
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM)
    k2 = S >= N.HOLD_FROM
    kl1, kl2 = k1 & ~np.isnan(line), k2 & ~np.isnan(line)
    pred = Fit.wf(mat(X, feats), y, S)
    res['base']['mae'] = {'2015_21': r4(np.mean(np.abs(pred[k1] - y[k1]))), '2022_26': r4(np.mean(np.abs(pred[k2] - y[k2])))}
    print('base', res['base']['mae'], flush=True)

    # ---- 1. totals. The total's pace and efficiency ratings on their own half-life (thl), tuned on 2015-21; then
    # the possession model's pieces, each with the market total in the same regression
    tbase = Fit.wf(mat(TX, TX0), ty, S)
    tot = {'base': {'mae2015_21': r4(np.mean(np.abs(tbase[k1] - ty[k1]))), 'mae2022_26': r4(np.mean(np.abs(tbase[k2] - ty[k2])))}}
    thl = {}
    for hl in (2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 14.0, 30.0):
        _, _, TXh, _, _, _, _, _ = design(games, names, P, {**params, 'thl': hl}, inj)
        pr = Fit.wf(mat(TXh, TX0), ty, S)
        thl[hl] = (TXh, pr, compare(pr, tbase, ty, k1, k2))
        print('total thl', hl, thl[hl][2], flush=True)
    tot['total ratings half-life'] = {f'{hl:g}': {**c, 'pass': passes(c)} for hl, (_, _, c) in thl.items()}
    best_thl = min(thl, key=lambda hl: float(np.mean(np.abs(thl[hl][1][k1] - ty[k1]))))
    tot['best half-life (2015-21)'] = best_thl
    TXb, tb_pred, _ = thl[best_thl]
    variants = {
        'pace x eff, no market total': ['pts', 'po', 'one'],
        'market total only': ['tmkt', 'po', 'one'],
        'split: league, pace, eff': ['tlg', 'tpace', 'teff', 'tmkt', 'po', 'one'],
        'split: pace, eff (no league term)': ['tpace', 'teff', 'tmkt', 'po', 'one'],
        'pace as a product': ['ptsM', 'tmkt', 'po', 'one'],
        'pace as a product and a sum': ['ptsM', 'pts', 'tmkt', 'po', 'one'],
        '+ home': ['pts', 'tmkt', 'po', 'thome', 'one'],
    }
    tot['vs the tuned half-life'] = {}
    for nm, fs in variants.items():
        pr = Fit.wf(mat(TXb, fs), ty, S)
        c = compare(pr, tb_pred, ty, k1, k2)
        tot['vs the tuned half-life'][nm] = {'feats': fs, **c, 'pass': passes(c)}
        print('total', nm, c, flush=True)
    kt2 = k2 & ~np.isnan(tline)
    tot['close 2022_26'] = r4(np.mean(np.abs(tline[kt2] - ty[kt2])))
    tot['model 2022_26 (games with a close)'] = {'base': r4(np.mean(np.abs(tbase[kt2] - ty[kt2]))),
                                                 'tuned half-life': r4(np.mean(np.abs(tb_pred[kt2] - ty[kt2])))}
    res['totals'] = tot

    # ---- 1b. margin: efficiency split into offense and defense, pace as a product
    mar = {}
    for nm, swap in (('eff -> effO + effD', ['effO', 'effD']), ('eff -> effM (pace as a product)', ['effM'])):
        fs = [f for f in feats if f != 'eff'] + swap
        pr = Fit.wf(mat(X, fs), y, S)
        mar[nm] = {'feats': fs, **compare(pr, pred, y, k1, k2)}
        mar[nm]['pass'] = passes(mar[nm])
        print('margin', nm, mar[nm], flush=True)
    # 'early' (Elo weighted up in a team's first 20 games) was tested with games played read from the last four days'
    # tips (never above 3); retested on the real count
    pr = Fit.wf(mat(X, feats + ['early']), y, S)
    mar['+ early (games played fixed)'] = {**compare(pr, pred, y, k1, k2)}
    mar['+ early (games played fixed)']['pass'] = passes(mar['+ early (games played fixed)'])
    print('margin early', mar['+ early (games played fixed)'], flush=True)
    res['margin'] = mar

    # ---- 2. Elo: K and offseason carry (538's margin multiplier with its autocorrelation term is already in);
    # a points Elo stepped on margin minus expected margin
    elo = {'note': "538's multiplier (MOV+3)^0.8 / (7.5 + 0.006 x winner's Elo edge) is already in the update"}
    eh = lambda XX: Fit.wf(mat(XX, ['elo', 'home']), y, S)
    elo_alone0 = eh(X)
    elo['base alone (elo + home)'] = {'mae2015_21': r4(np.mean(np.abs(elo_alone0[k1] - y[k1]))), 'mae2022_26': r4(np.mean(np.abs(elo_alone0[k2] - y[k2])))}
    grid = []
    for K in (10.0, 15.0, 20.0, 25.0, 30.0):
        for keep in (0.5, 0.75, 0.9):
            if K == params['elo_k'] and keep == 0.75:
                continue
            _, Xe, _, _, _, _, _, _ = design(games, names, P, {**params, 'elo_k': K, 'elo_keep': keep}, inj)
            alone = compare(eh(Xe), elo_alone0, y, k1, k2)
            full = compare(Fit.wf(mat(Xe, feats), y, S), pred, y, k1, k2)
            grid.append({'K': K, 'keep': keep, 'alone': alone, 'model': full, 'pass': passes(full)})
            print('elo', K, keep, alone['d2015_21'], full, flush=True)
    elo['grid'] = grid
    pe = []
    for pk in (0.02, 0.04, 0.06):
        for keep in (0.5, 0.75):
            _, Xp, _, _, _, _, _, _ = design(games, names, P, {**params, 'pk': pk, 'pkeep': keep}, inj)
            alone = compare(Fit.wf(mat(Xp, ['pelo', 'home']), y, S), elo_alone0, y, k1, k2)
            add = compare(Fit.wf(mat(Xp, feats + ['pelo']), y, S), pred, y, k1, k2)
            rep = compare(Fit.wf(mat(Xp, [f if f != 'elo' else 'pelo' for f in feats]), y, S), pred, y, k1, k2)
            pe.append({'k': pk, 'keep': keep, 'alone vs Elo alone': alone, 'added': add, 'replacing elo': rep,
                       'pass': passes(add) or passes(rep)})
            print('pelo', pk, keep, alone['d2015_21'], add, rep, flush=True)
    elo['points Elo'] = pe
    res['elo'] = elo

    # ---- 3. win probability sd by stage of the season: sd = s0 x (1 + c x max(0, 1 - gp/40)), playoffs their own
    gp = X['gpn']                                                      # the fewer games played of the two teams
    win = (y > 0).astype(float)
    ok = ~np.isnan(pred)
    k1o, k2o = k1 & ok, k2 & ok

    def probs(s0, c, half):
        sdv = s0 * (1 + c * np.clip(1 - gp / half, 0, 1))
        return Phi(pred / sdv)
    base_p = probs(sd0, 0.0, 40)
    sdres = {'sd': sd0, 'base logloss 2015_21': r4(ll_vec(base_p[k1o], win[k1o]).mean()),
             'base logloss 2022_26': r4(ll_vec(base_p[k2o], win[k2o]).mean())}
    best = None
    for half in (10, 20, 40, 60):
        for c in (-0.1, -0.05, 0.05, 0.1, 0.15, 0.2, 0.3):
            for s0 in np.arange(sd0 - 0.75, sd0 + 0.76, 0.25):
                l1 = ll_vec(probs(s0, c, half)[k1o], win[k1o]).mean()
                if best is None or l1 < best[0]:
                    best = (l1, float(s0), c, half)
    l1, s0, c, half = best
    pb = probs(s0, c, half)
    d1, d2 = ll_vec(pb[k1o], win[k1o]) - ll_vec(base_p[k1o], win[k1o]), ll_vec(pb[k2o], win[k2o]) - ll_vec(base_p[k2o], win[k2o])
    sdres['best on 2015_21'] = {'sd0': round(s0, 2), 'c': c, 'games': half, 'logloss 2015_21': r4(l1),
                                'logloss 2022_26': r4(ll_vec(pb[k2o], win[k2o]).mean()),
                                't2015_21': round(float(d1.mean() / (d1.std(ddof=1) / math.sqrt(len(d1)))), 2),
                                't2022_26': round(float(d2.mean() / (d2.std(ddof=1) / math.sqrt(len(d2)))), 2)}
    sdres['best on 2015_21']['pass'] = sdres['best on 2015_21']['t2015_21'] <= -1.5 and float(d2.mean()) <= 0
    # by stage, the sd each bin of games played wants (2015-26 regular season)
    stage = []
    for lo, hi in ((0, 10), (10, 20), (20, 40), (40, 60), (60, 83)):
        b = ok & (gp >= lo) & (gp < hi) & (S >= N.SCORE_FROM)
        fits = [(ll_vec(Phi(pred[b] / s), win[b]).mean(), s) for s in np.arange(9.0, 15.01, 0.25)]
        stage.append({'games played': f'{lo}-{hi - 1}', 'n': int(b.sum()), 'sd': float(min(fits)[1]),
                      'resSd': round(float(np.std(pred[b] - y[b])), 2)})
    sdres['by stage'] = stage
    print('sd', sdres, flush=True)
    res['sd'] = sdres

    # ---- 5. market blend (report only): w x model + (1 - w) x close
    mlH = np.array([g.get('mlH') or np.nan for g, _, _ in D], float)
    mlA = np.array([g.get('mlA') or np.nan for g, _, _ in D], float)
    imp = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
    km = ~np.isnan(mlH) & ~np.isnan(mlA) & ok
    pm = np.full(len(y), np.nan)
    pm[km] = imp(mlH[km]) / (imp(mlH[km]) + imp(mlA[km]))
    pmod = Phi(np.nan_to_num(pred) / sd0)
    ws = np.round(np.arange(0, 1.001, 0.01), 2)
    blend = {}
    for nm, kk in (('2015_21', kl1 & ok), ('2022_26', kl2 & ok)):
        e = [(float(np.mean(np.abs(w * pred[kk] + (1 - w) * line[kk] - y[kk]))), w) for w in ws]
        kp = kk & km
        l = [(float(ll_vec(w * pmod[kp] + (1 - w) * pm[kp], win[kp]).mean()), w) for w in ws]
        blend[nm] = {'maeByW': {str(w): r4(v) for v, w in e if round(w * 100) % 10 == 0},
                     'loglossByW': {str(w): r4(v) for v, w in l if round(w * 100) % 10 == 0},
                     'bestMaeW': float(min(e)[1]), 'bestLoglossW': float(min(l)[1])}
    wm, wl = blend['2015_21']['bestMaeW'], blend['2015_21']['bestLoglossW']
    for tag, w_m, w_l in (('w tuned on 2015_21', wm, wl), ('w best on 2022_26', blend['2022_26']['bestMaeW'], blend['2022_26']['bestLoglossW'])):
        kk = kl2 & ok
        a = np.abs(w_m * pred[kk] + (1 - w_m) * line[kk] - y[kk]); b = np.abs(line[kk] - y[kk])
        kp = kk & km
        la = ll_vec(w_l * pmod[kp] + (1 - w_l) * pm[kp], win[kp]); lb = ll_vec(pm[kp], win[kp])
        tt = lambda u, v: round(Fit.paired_t(u, v), 2) if np.any(u != v) else None
        blend[tag] = {'wMae': w_m, 'mae': r4(a.mean()), 'maeClose': r4(b.mean()), 'tMae': tt(a, b),
                      'wLogloss': w_l, 'logloss': r4(la.mean()), 'loglossClose': r4(lb.mean()), 'tLogloss': tt(la, lb),
                      'games': int(kk.sum()), 'mlGames': int(kp.sum())}
    print('blend', {k: v for k, v in blend.items() if k.startswith('w ')}, flush=True)
    res['blend'] = blend

    json.dump(res, open(OUT, 'w'), indent=1)
    return res


if __name__ == '__main__':
    main()
