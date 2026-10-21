"""Game-script research for the NBA player projections (Oct 21 2026): blowout minutes, volume with the total, a full
simulation of each game's margin and total (prop chances as a mixture over the script) against the negative binomial,
and how teammates' misses correlate. Held out 2024-26, MAE and CRPS, games as clusters.

    python3 scripts/nba_players_script_research.py     # -> data/nba_players_script_research.json (needs the injury
                                                       #    history: python3 scripts/nba_inj_hist.py 2020 2026)
Result: the game-script mean terms ship through nba_players.py --fit; the simulation does not beat a refit NB.
"""
import sys, math, json
import numpy as np
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_players as NP
import nba_games as N
import harness as H

NP.PCAL = json.load(open(NP.FIT)).get('pcal')
rows = NP.collect()
G = {g['id']: g for g in N.load_hist()[0] if g['S'] >= 2020}
F = json.load(open(NP.FIT))
OUT = os.path.join(NP.ROOT, 'data', 'nba_players_script_research.json')
ST = ('min', 'pts', 'reb', 'ast')
SDM = NP.SDM   # margin sd around the close (measured below)

D = [r for r in rows if r['y'] and r['nv'] and r['mS'] >= 10 and not r['po']
     and G.get(r['g'], {}).get('L') is not None and G[r['g']].get('T')]
print('rows', len(D))
S = np.array([r['S'] for r in D])
gid = np.array([r['g'] for r in D])
tg = np.array([r['g'] + r['t'] for r in D])
mS = np.array([r['mS'] for r in D])
Lt = np.array([G[r['g']]['L'] * (1 if r['t'] == G[r['g']]['h'] else -1) for r in D], float)  # team's expected margin
T = np.array([G[r['g']]['T'] for r in D], float)
Ma = np.array([(G[r['g']]['hs'] - G[r['g']]['as']) * (1 if r['t'] == G[r['g']]['h'] else -1) for r in D], float)
Ta = np.array([G[r['g']]['hs'] + G[r['g']]['as'] for r in D], float)
res_m = Ma - Lt
print('margin sd vs close', res_m.std(), 'total sd', (Ta - T).std(), 'corr |M| resid', np.corrcoef(np.abs(Ma), Ta - T)[0, 1])


def eabs(mu, sd=SDM):
    z = mu / sd
    return sd * math.sqrt(2 / math.pi) * np.exp(-z * z / 2) + mu * (1 - 2 * np.vectorize(H._Phi)(-z))


EA = eabs(Lt)
EA0 = EA.mean()
Tlg = {}
for s_ in set(S):
    Tlg[s_] = T[S == s_].mean()
Trel = T / np.array([Tlg[s_] for s_ in S]) - 1
role = (mS - 24) / 12.0
Y = {s: np.array([r['y'][i] for r in D], float) for i, s in enumerate(ST)}
NV = {s: np.array([r['nv'][i] for r in D], float) for i, s in enumerate(ST)}
X = {s: {f: np.array([r['fx'][s][f] for r in D], float) for f in NP.FEATS} for s in ST}
for s in ST:
    b = X[s]['base']
    X[s]['bo'] = b * (EA - EA0) / 10
    X[s]['boR'] = b * (EA - EA0) / 10 * role
    X[s]['fav'] = b * Lt / 10
    X[s]['tot'] = b * Trel
tune, hold = np.isin(S, NP.TUNE), np.isin(S, NP.HOLD)


def wf(s, feats):
    A = np.column_stack([X[s][f] for f in feats])
    pred = np.full(len(S), np.nan)
    for yr in sorted(set(S)):
        tr, te = S < yr, S == yr
        if tr.sum() < 1000:
            continue
        pred[te] = A[te] @ np.linalg.lstsq(A[tr], Y[s][tr], rcond=None)[0]
    return pred


rep = {'n': len(D), 'sdM': float(res_m.std()), 'sdT': float((Ta - T).std()), 'stats': {}}
base_feats = {s: [f for f in F['stats'][s]['feats'] if f not in NP.SCRIPT] for s in ST}
P0, P1, FE = {}, {}, {}
for s in ST:
    feats = list(base_feats[s])
    p0 = wf(s, feats)
    P0[s] = p0
    cur = p0
    log = []
    cands = ([] if s == 'min' else ['gsm']) + ['bo', 'boR', 'fav'] + ([] if s == 'pts' else ['tot']) + ([] if s != 'min' else [])
    if s != 'pts' and 'imp' not in feats:
        cands.append('imp')
    for f in cands:
        new = wf(s, feats + [f])
        e0, e1 = (Y[s] - cur) ** 2, (Y[s] - new) ** 2
        rt = H.paired(e1[tune], e0[tune], cluster=gid[tune])
        rh = H.paired(e1[hold], e0[hold], cluster=gid[hold])
        keep = rt['t'] <= NP.SEL_T and rh['t'] <= 0
        log.append({'feat': f, 't_tune': round(rt['t'], 2), 't_hold': round(rh['t'], 2), 'keep': bool(keep)})
        print(s, f, round(rt['t'], 2), round(rh['t'], 2), keep, flush=True)
        if keep:
            feats.append(f); cur = new
    P1[s], FE[s] = cur, feats
    if s == 'min':
        gr = np.nan_to_num(P1['min'] / P0['min'] - 1)
        for s2 in ('pts', 'reb', 'ast'):
            X[s2]['gsm'] = X[s2]['base'] * gr
    rep['stats'][s] = {'feats': feats, 'select': log}
P0['pra'] = P0['pts'] + P0['reb'] + P0['ast']
P1['pra'] = P1['pts'] + P1['reb'] + P1['ast']
Y['pra'] = Y['pts'] + Y['reb'] + Y['ast']
NV['pra'] = NV['pts'] + NV['reb'] + NV['ast']
for s in ST + ('pra',):
    ok = hold & ~np.isnan(P0[s])
    r = H.paired(np.abs(Y[s] - P1[s])[ok], np.abs(Y[s] - P0[s])[ok], cluster=gid[ok])
    rep['stats'].setdefault(s, {})['mae'] = {'new': round(float(np.abs(Y[s] - P1[s])[ok].mean()), 4),
                                            'cur': round(float(np.abs(Y[s] - P0[s])[ok].mean()), 4),
                                            'savg': round(float(np.abs(Y[s] - NV[s])[ok].mean()), 4), 't': round(r['t'], 2)}
    print('MAE', s, rep['stats'][s]['mae'], flush=True)

# ------------------------------------------------ realized script: how a player's line moves with the game's margin and total
# residual on the tuning seasons, regressed on b x (|M| - E|M|) (x role) and b x (Tact - T)/T
sc = {}
dA = (np.abs(Ma) - EA) / 10
dT = (Ta - T) / T
for s in ('pts', 'reb', 'ast'):
    b = X[s]['base']
    m = tune & ~np.isnan(P1[s])
    A = np.column_stack([b * dA, b * dA * role, b * dT])[m]
    c = np.linalg.lstsq(A, (Y[s] - P1[s])[m], rcond=None)[0]
    sc[s] = [float(x) for x in c]
    print('script', s, sc[s])
rep['script'] = sc


# ------------------------------------------------ distributions: CRPS of NB (current) vs sim mixture over margin/total draws
def nb_pmf(mu, var, K):
    """rows x K pmf"""
    mu = np.maximum(mu, 1e-3)
    var = np.maximum(var, mu * 1.0001)
    r = mu * mu / (var - mu)
    q = mu / var
    out = np.empty((len(mu), K))
    pm = np.exp(r * np.log(q))
    for x in range(K):
        out[:, x] = pm
        pm = pm * (x + r) / (x + 1) * (1 - q)
    return out


def crps(pmf, y):
    Fc = np.cumsum(pmf, axis=1)
    xs = np.arange(pmf.shape[1])
    ind = (xs[None, :] >= y[:, None]).astype(float)
    return ((Fc - ind) ** 2).sum(axis=1)


def var_fit(mu, y):
    ab = np.linalg.lstsq(np.column_stack([mu, mu * mu]), (y - mu) ** 2, rcond=None)[0]
    return ab


# Gauss-Hermite nodes for margin residual and total residual (independent: corr checked above)
gx, gw = np.polynomial.hermite_e.hermegauss(9)
gw = gw / gw.sum()
sdM, sdT = float(res_m.std()), float((Ta - T).std())
K = {'pts': 80, 'reb': 40, 'ast': 30, 'pra': 120}
out = {}
for s in ('pts', 'reb', 'ast', 'pra'):
    parts = ('pts', 'reb', 'ast') if s == 'pra' else (s,)
    mu1 = P1[s]
    okT = tune & ~np.isnan(mu1) & (mu1 > 0)
    okH = hold & ~np.isnan(mu1) & (mu1 > 0)
    # current: NB with shipped var on the current mean
    Vc = F['var'][s]
    mu0 = P0[s]
    res = {}
    # conditional mean shift per node, and the conditional variance fit on tuning residuals after the realized shift
    def shift(dAx, dTx):
        tot = 0
        for p in parts:
            b = X[p]['base']
            c = sc[p]
            tot = tot + c[0] * b * dAx + c[1] * b * dAx * role + c[2] * b * dTx
        return tot
    real = shift(dA, dT)
    vab = var_fit((mu1 + real)[okT].clip(0.1), Y[s][okT])
    vnb = var_fit(mu1[okT], Y[s][okT])
    for nm, msk in (('tune', okT), ('hold', okH)):
        y = Y[s][msk]
        k = K[s]
        c_cur = crps(nb_pmf(mu0[msk], Vc[0] * mu0[msk] + Vc[1] * mu0[msk] ** 2, k), y)
        c_nb1 = crps(nb_pmf(mu1[msk], vnb[0] * mu1[msk] + vnb[1] * mu1[msk] ** 2, k), y)
        # sim: margin draw M = L + sdM z1, total draw = T + sdT z2
        mix = np.zeros((msk.sum(), k))
        Lm, Tm, EAm = Lt[msk], T[msk], EA[msk]
        for z1, w1 in zip(gx, gw):
            for z2, w2 in zip(gx, gw):
                dAx = (np.abs(Lm + sdM * z1) - EAm) / 10
                dTx = sdT * z2 / Tm
                sh = 0
                for p in parts:
                    b = X[p]['base'][msk]; c = sc[p]
                    sh = sh + c[0] * b * dAx + c[1] * b * dAx * role[msk] + c[2] * b * dTx
                mc = np.maximum(mu1[msk] + sh, 0.05)
                mix += w1 * w2 * nb_pmf(mc, vab[0] * mc + vab[1] * mc ** 2, k)
        c_sim = crps(mix, y)
        c_sav = crps(nb_pmf(NV[s][msk], Vc[0] * NV[s][msk] + Vc[1] * NV[s][msk] ** 2, k), y)
        r1 = H.paired(c_sim, c_cur, cluster=gid[msk]); r2 = H.paired(c_sim, c_nb1, cluster=gid[msk])
        res[nm] = {'cur': round(float(c_cur.mean()), 4), 'nbNew': round(float(c_nb1.mean()), 4), 'sim': round(float(c_sim.mean()), 4),
                   'savg': round(float(c_sav.mean()), 4), 't_sim_vs_cur': round(r1['t'], 2), 't_sim_vs_nbNew': round(r2['t'], 2)}
        # over/under calibration of the sim at a season-average line
        line = np.floor(NV[s][msk]) + 0.5
        idx = np.clip(np.floor(line).astype(int), 0, k - 1)
        pO_sim = 1 - np.cumsum(mix, axis=1)[np.arange(len(y)), idx]
        pO_nb = 1 - np.cumsum(nb_pmf(mu0[msk], Vc[0] * mu0[msk] + Vc[1] * mu0[msk] ** 2, k), axis=1)[np.arange(len(y)), idx]
        o = (y > line).astype(float)
        res[nm]['brier_sim'] = round(float(((pO_sim - o) ** 2).mean()), 5)
        res[nm]['brier_cur'] = round(float(((pO_nb - o) ** 2).mean()), 5)
        res[nm]['ll_sim'] = round(float(H.logloss(pO_sim, o).mean() if hasattr(H.logloss(pO_sim, o), 'mean') else H.logloss(pO_sim, o)), 5)
        res[nm]['ll_cur'] = round(float(H.logloss(pO_nb, o).mean() if hasattr(H.logloss(pO_nb, o), 'mean') else H.logloss(pO_nb, o)), 5)
        print(s, nm, res[nm], flush=True)
    res['var_sim'] = [float(x) for x in vab]
    res['var_nb'] = [float(x) for x in vnb]
    out[s] = res
rep['crps'] = out

# ------------------------------------------------ teammate correlation of PRA residuals (same team, same game)
from collections import defaultdict
for nm, msk in (('hold', hold),):
    e = (Y['pra'] - P1['pra'])
    e2 = e - np.nan_to_num(sum(sc[p][0] * X[p]['base'] * dA + sc[p][1] * X[p]['base'] * dA * role + sc[p][2] * X[p]['base'] * dT for p in ('pts', 'reb', 'ast')))
    by = defaultdict(list)
    idx = np.where(msk & ~np.isnan(e))[0]
    for i in idx:
        by[tg[i]].append(i)
    a1, a2, b1, b2, st1, st2 = [], [], [], [], [], []
    for k_, ii in by.items():
        for x in range(len(ii)):
            for y_ in range(x + 1, len(ii)):
                a1.append(e[ii[x]]); a2.append(e[ii[y_]]); b1.append(e2[ii[x]]); b2.append(e2[ii[y_]])
                st1.append(mS[ii[x]] >= 28 and mS[ii[y_]] >= 28)
    a1, a2, b1, b2, st1 = map(np.array, (a1, a2, b1, b2, st1))
    rho = {'all': float(np.corrcoef(a1, a2)[0, 1]), 'after_script': float(np.corrcoef(b1, b2)[0, 1]),
           'starters': float(np.corrcoef(a1[st1], a2[st1])[0, 1]), 'starters_after': float(np.corrcoef(b1[st1], b2[st1])[0, 1])}
    # opponents
    rep['teammates'] = rho
    print('teammate rho', rho)
def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None                                  # Hugo's JSON loader fails on bare NaN
    return x


json.dump(clean(rep), open(OUT, 'w'), indent=1)
