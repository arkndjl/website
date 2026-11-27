"""Returning QB quality (preseason pSV form) in the CFB roster prior: prereg.md C1 / C2.
    python3 scripts/research/ctx_nov27/cfb/qb_prior.py      -> results.json (repo files only, ~1 min)"""
import gzip
import json
import math
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
LAM, HFA, SIGMA = 3.0, 2.5, 17.131
K, W = 650, (1.0, 0.7, 0.5)
FCS = 'FCS'

G = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'cfb.json.gz'), 'rt'))
G = [g for g in G if g.get('res') is not None and not (g['S'] == 2026 and g['wk'] >= 11)]       # lockbox
SV = [r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'sv_hist.json.gz'), 'rt'))['cfb'] if r['g'] == 'QB']
FE = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_roster_feats.json')))['feats']
TID = {t['team']: t['tid'] for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_rank.json')))['teams']}
NAME = {v: k for k, v in TID.items()}

by = defaultdict(list)
for g in G:
    by[g['S']].append(g)
SEASONS = sorted(by)
fbs = {S: {NAME[t] for t in FE.get(str(S), {}) if t in NAME} for S in SEASONS}


def side(S, t):
    return t if t in fbs[S] else FCS


def massey(S, games, prior=None, lam=0.0):
    teams = sorted({side(S, g[k]) for g in games for k in ('home', 'away')} | set(prior or {}))
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    A = np.zeros((n, n)); b = np.zeros(n)
    for g in games:
        h, a = ix[side(S, g['home'])], ix[side(S, g['away'])]
        if h == a:
            continue
        y = g['res'] - (0 if g['neutral'] else HFA)
        A[h, h] += 1; A[a, a] += 1; A[h, a] -= 1; A[a, h] -= 1
        b[h] += y; b[a] -= y
    if prior is None:
        A += np.eye(n) * 1e-3
    else:
        for t, i in ix.items():
            A[i, i] += lam; b[i] += lam * prior.get(t, -20.0)
    r = np.linalg.solve(A, b)
    if prior is None:
        r -= np.mean([r[ix[t]] for t in teams if t != FCS])
    return {t: float(r[ix[t]]) for t in teams}


FIN = {S: massey(S, by[S]) for S in SEASONS}

# ---- preseason QB quality ------------------------------------------------------------------------------------
qrow = defaultdict(dict)            # id -> season -> (tot, pl)   (a QB with two teams in a season: summed)
tq = defaultdict(lambda: defaultdict(list))
for r in SV:
    a = qrow[r['id']].get(r['y'], (0.0, 0))
    qrow[r['id']][r['y']] = (a[0] + r['tot'], a[1] + r['pl'])
    tq[r['y']][r['t']].append(r)


def psv_pre(qid, S):
    rows = [r for r in SV if r['y'] == S - 1]
    m = sum(r['tot'] for r in rows) / max(1, sum(r['pl'] for r in rows))
    P = n = 0.0
    for i, w in enumerate(W, 1):
        t, p = qrow[qid].get(S - i, (0.0, 0))
        P += w * t; n += w * p
    return (P + K * m) / (n + K) * 60


X = {}
for S in SEASONS:
    f = FE.get(str(S))
    if not f or S - 1 not in FIN:
        continue
    vals = [v['qbRet'] for v in f.values()]
    lo, hi = min(vals), max(vals)
    raw = {}
    for tid, v in f.items():
        t = NAME.get(tid)
        if not t:
            continue
        L = tq[S - 1].get(t)
        raw[t] = psv_pre(max(L, key=lambda r: r['pl'])['id'], S) if L else None
    have = [v for v in raw.values() if v is not None]
    mu, sd = np.mean(have), np.std(have)
    X[S] = {}
    for tid, v in f.items():
        t = NAME.get(tid)
        if not t:
            continue
        s = (v['qbRet'] - lo) / (hi - lo)
        zq = 0.0 if raw[t] is None else (raw[t] - mu) / sd
        X[S][t] = {'last': FIN[S - 1].get(t, FIN[S - 1].get(FCS, -20.0)), 'tal247': v['tal247'], 'offRet': v['offRet'], 'qbRet': v['qbRet'],
                   'offIn': v['offIn'], 'qbQ': s * zq, 'y': FIN[S].get(t)}

BASE = ['last', 'tal247', 'offRet', 'qbRet', 'offIn']
SPECS = {'base': BASE, 'C1 add qbQ': BASE + ['qbQ'], 'C2 swap qbRet -> qbQ': ['last', 'tal247', 'offRet', 'qbQ', 'offIn']}
XS = sorted(X)
HOLD = [S for S in XS if len([s for s in XS if s < S]) >= 3]


def fit(keys, S):
    rows = [(x, x['y']) for s in XS if s < S for x in X[s].values() if x['y'] is not None]
    A = np.array([[1.0] + [x[k] for k in keys] for x, _ in rows]); y = np.array([v for _, v in rows])
    return np.linalg.solve(A.T @ A + np.eye(A.shape[1]) * 1.0, A.T @ y)


def walk(keys):
    out, wts = {}, {}
    for S in HOLD:
        w = fit(keys, S); wts[S] = [round(float(v), 3) for v in w]
        prior = {t: float(w[0] + sum(w[i + 1] * x[k] for i, k in enumerate(keys))) for t, x in X[S].items()}
        prior[FCS] = FIN[S - 1].get(FCS, -20.0)
        for wk in sorted({g['wk'] for g in by[S]}):
            R = massey(S, [g for g in by[S] if g['wk'] < wk], prior, LAM)
            for g in by[S]:
                if g['wk'] != wk or g['fcs'] or g['home'] not in fbs[S] or g['away'] not in fbs[S]:
                    continue
                out[g['id']] = (S, g['wk'], R[g['home']] - R[g['away']] + (0 if g['neutral'] else HFA), g['res'])
    return out, wts


phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))


def ll(p, res):
    if res == 0:
        return None
    q = min(max(phi(p / SIGMA), 1e-6), 1 - 1e-6)
    return -math.log(q if res > 0 else 1 - q)


P = {k: walk(v) for k, v in SPECS.items()}
base = P['base'][0]
ids = sorted(base)
res = {'seasons': {'priorFitFrom': XS[0], 'held': HOLD}, 'n': len(ids), 'specs': {}}
ps = []
for k in SPECS:
    pr, wts = P[k]
    mae = float(np.mean([abs(pr[i][2] - pr[i][3]) for i in ids]))
    L = [ll(pr[i][2], pr[i][3]) for i in ids]
    o = {'mae': round(mae, 4), 'logLoss': round(float(np.mean([v for v in L if v is not None])), 4), 'w2026': wts[HOLD[-1]]}
    o['maeWk1to4'] = round(float(np.mean([abs(pr[i][2] - pr[i][3]) for i in ids if pr[i][1] <= 4])), 4)
    if k != 'base':
        d = np.array([abs(pr[i][2] - pr[i][3]) - abs(base[i][2] - base[i][3]) for i in ids])
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
        dl = np.array([a - b for a, b in zip(L, [ll(base[i][2], base[i][3]) for i in ids]) if a is not None])
        bs = {S: float(np.mean([d[j] for j, i in enumerate(ids) if pr[i][0] == S])) for S in HOLD}
        de = np.array([d[j] for j, i in enumerate(ids) if pr[i][1] <= 4])
        o.update(dMae=round(float(d.mean()), 4), t=round(t, 2), p=round(phi(t), 4), dLogLoss=round(float(dl.mean()), 5),
                 tLogLoss=round(float(dl.mean() / (dl.std(ddof=1) / math.sqrt(len(dl)))), 2),
                 seasonsBetter=f"{sum(v < 0 for v in bs.values())}/{len(bs)}", bySeason={str(S): round(v, 4) for S, v in bs.items()},
                 tWk1to4=round(float(de.mean() / (de.std(ddof=1) / math.sqrt(len(de)))), 2))
        ps.append((o['p'], k))
    res['specs'][k] = o
for j, (p, k) in enumerate(sorted(ps)):
    o = res['specs'][k]
    o['pHolm'] = round(min(1.0, p * (len(ps) - j)), 4)
    o['pass'] = bool(o['pHolm'] < .05 and int(o['seasonsBetter'].split('/')[0]) >= 4 and o['dLogLoss'] <= 0)
json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
print(json.dumps(res, indent=1))
