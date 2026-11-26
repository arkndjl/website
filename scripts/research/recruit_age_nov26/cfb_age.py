#!/usr/bin/env python3
"""CFB recruit age for the class (prereg.md, CFB). On3 industry top 400 of the 2011-19 classes (on3_age_pull.mjs football 8
2011..2019) joined to nflverse players.csv (birth date, draft) by name and a rookie season 3-6 years after the class.
    python3 cfb_age.py <on3 json> <nflverse dir>"""
import csv, json, math, os, sys, datetime as dt
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import names as N
TODAY = dt.date(2026, 11, 26)

def logit(X, y, lam=1.0):
    X = np.c_[np.ones(len(X)), X]; b = np.zeros(X.shape[1]); pen = np.r_[0, np.full(X.shape[1] - 1, lam)]
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ b)); d = np.linalg.solve(X.T @ (X * (p * (1 - p))[:, None]) + np.diag(pen), X.T @ (y - p) - pen * b)
        b += d
        if abs(d).max() < 1e-9: break
    return b

def ols(X, y, lam=1.0):
    X = np.c_[np.ones(len(X)), X]; pen = np.r_[0, np.full(X.shape[1] - 1, lam)]
    return np.linalg.solve(X.T @ X + np.diag(pen), X.T @ y)

def cvtest(X0, X1, y, cls, kind):
    L = [np.zeros(len(y)), np.zeros(len(y))]
    for c in sorted(set(cls)):
        tr, te = cls != c, cls == c
        for i, X in enumerate((X0, X1)):
            m, s = X[tr].mean(0), X[tr].std(0) + 1e-9
            Z, Zt = (X[tr] - m) / s, (X[te] - m) / s
            if kind == 'logit':
                b = logit(Z, y[tr]); p = np.clip(1 / (1 + np.exp(-(b[0] + Zt @ b[1:]))), 1e-6, 1 - 1e-6)
                L[i][te] = -(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p))
            else:
                b = ols(Z, y[tr]); L[i][te] = (y[te] - b[0] - Zt @ b[1:]) ** 2
    d = np.array([np.mean(L[0][cls == c] - L[1][cls == c]) for c in sorted(set(cls))])
    return {'gain': round(float(d.mean()), 5), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'classes': f'{int((d > 0).sum())}/{len(d)}', 'n': len(y)}

on3 = json.load(open(sys.argv[1])); nd = sys.argv[2]
by = defaultdict(list)
for p in csv.DictReader(open(os.path.join(nd, 'players.csv'))):
    if p['birth_date'] and p['rookie_season']: by[N.key(p['display_name'])].append(p)
rows = []
for y, L in on3.items():
    c = int(y)
    for r in L:
        if not r['rk'] or r['rk'] > 400 or (r['age'] is not None and not 20 <= r['age'] <= 40): r = dict(r, age=None) if r['rk'] and r['rk'] <= 400 else None
        if not r: continue
        cand = [p for p in by.get(N.key(r['name']), []) if c + 3 <= int(p['rookie_season']) <= c + 6]
        p = cand[0] if len(cand) == 1 else None
        row = {'cls': c, 'lrk': -math.log(r['rk']), 'cons': r['cons'] or 80, 'nfl': 0, 'drafted': 0, 'lpick': None, 'agec': None, 'old': None}
        if p:
            b = dt.date.fromisoformat(p['birth_date'][:10])
            row.update(nfl=1, drafted=1 if p['draft_pick'] else 0, lpick=-math.log(int(float(p['draft_pick']))) if p['draft_pick'] else -math.log(300),
                       agec=(dt.date(c, 9, 1) - b).days / 365.25)
            a = (TODAY - b).days // 365.25
            row['old'] = 1.0 if a - (TODAY.year - (c - 1)) >= 18 else 0.0
        elif r['age'] is not None:
            row['old'] = 1.0 if r['age'] - (TODAY.year - (c - 1)) >= 18 else 0.0
        rows.append(row)
A = lambda k, R=rows: np.array([r[k] for r in R], float)
print('rows', len(rows), 'NFL entry', int(A('nfl').sum()), 'drafted', int(A('drafted').sum()), 'age known', sum(r['old'] is not None for r in rows),
      '| known: drafted', round(np.mean([r['old'] is not None for r in rows if r['drafted']]), 3), 'undrafted', round(np.mean([r['old'] is not None for r in rows if not r['drafted']]), 3))
out = {}
E_ = [r for r in rows if r['nfl']]
a = A('agec', E_)
out['median'] = round(float(np.median(a)), 2); out['n'] = len(a); out['rows'] = len(rows)
print('NFL entrants: agec mean', round(a.mean(), 2), 'sd', round(a.std(), 2))
for lo, hi in ((0, 18.0), (18.0, 18.4), (18.4, 18.8), (18.8, 19.2), (19.2, 30)):
    s = (a > lo) & (a <= hi)
    print(f'  agec {lo}-{hi}: n {s.sum()}, mean rank {np.exp(-A("lrk", E_)[s]).mean():.0f}, drafted {A("drafted", E_)[s].mean():.3f}, top-64 {(A("lpick", E_)[s] >= -math.log(64)).mean():.3f}')
    out.setdefault('bins', []).append({'lo': lo, 'hi': hi, 'n': int(s.sum()), 'rank': round(float(np.exp(-A("lrk", E_)[s]).mean())), 'drafted': round(float(A("drafted", E_)[s].mean()), 3), 'top64': round(float((A("lpick", E_)[s] >= -math.log(64)).mean()), 3)})
X0 = np.c_[A('lrk', E_), A('cons', E_)]; cl = A('cls', E_)
out['given NFL entry: drafted + agec'] = cvtest(X0, np.c_[X0, a], A('drafted', E_), cl, 'logit')
out['given NFL entry: log pick + agec'] = cvtest(X0, np.c_[X0, a], A('lpick', E_), cl, 'ols')
out['given NFL entry: top-64 + agec'] = cvtest(X0, np.c_[X0, a], (A('lpick', E_) >= -math.log(64)).astype(float), cl, 'logit')
out['given NFL entry: drafted + old'] = cvtest(X0, np.c_[X0, A('old', E_)], A('drafted', E_), cl, 'logit')
K = [r for r in rows if r['old'] is not None]
X0 = np.c_[A('lrk', K), A('cons', K)]
out['age known (On3 or NFL): drafted + old'] = cvtest(X0, np.c_[X0, A('old', K)], A('drafted', K), A('cls', K), 'logit')
print('  known rows: old share', round(A('old', K).mean(), 3), 'drafted if old', round(A('drafted', K)[A('old', K) > 0].mean(), 3), 'if not', round(A('drafted', K)[A('old', K) == 0].mean(), 3))
for k, v in out.items():
    if k != 'bins': print(k, v)
json.dump(out, open(os.path.join(HERE, 'cfb_age.json'), 'w'), indent=1)
