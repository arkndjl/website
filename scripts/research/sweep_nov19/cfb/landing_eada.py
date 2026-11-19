# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 11: federal EADA football expenses against donor money + private flag in a landing-choice proxy
(pre-registered in prereg.md). argv: moves.json (transfer_cycles.py), then the two EADA football pickles (FY before
the 2024 window, FY before the 2025 window)."""
import json, math, os, re, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
L = {k: [v[0], v[1] or 0.0, v[2] or 0.0] for k, v in json.load(open(os.path.join(ROOT, 'data/cfb_transfer_fit.json')))['landing']['schools'].items()}
LOC = json.load(open(os.path.join(ROOT, 'scripts/geo/team_loc.json')))
T = {str(t['tid']): t for t in json.load(open(os.path.join(ROOT, 'data/cfb_teams.json')))['teams']}
moves = json.load(open(sys.argv[1]))
def nk(s):
    s = s.replace('&', 'and').replace('é', 'e').replace("'", '')
    s = re.sub(r'\b(The|University|of|at|Main Campus|College|Campus Immersion)\b', ' ', s)
    return re.sub(r'[^a-z]', '', s.lower())
ALIAS = {'Ole Miss': 'Mississippi', 'Pitt': 'Pittsburgh', 'UConn': 'Connecticut', 'USC': 'Southern California', 'LSU': 'Louisiana State', 'BYU': 'Brigham Young', 'SMU': 'Southern Methodist',
         'TCU': 'Texas Christian', 'UCF': 'Central Florida', 'UNLV': 'Nevada Las Vegas', 'UTEP': 'Texas El Paso', 'UTSA': 'Texas San Antonio', 'FIU': 'Florida International', 'NC State': 'North Carolina State',
         'UAB': 'Alabama Birmingham', 'USF': 'South Florida', 'UL Monroe': 'Louisiana Monroe', 'App State': 'Appalachian State', 'Miami (OH)': 'Miami Oxford', 'Texas A&M': 'Texas A and M', 'UCLA': 'California Los Angeles',
         'Penn State': 'Pennsylvania State', 'Virginia Tech': 'Virginia Polytechnic', 'Georgia Tech': 'Georgia Institute', 'Fresno State': 'California State Fresno', 'Southern Miss': 'Southern Mississippi',
         'Louisiana': 'Louisiana Lafayette', 'Nevada': 'Nevada Reno', 'California': 'California Berkeley', 'Navy': 'United States Naval Academy', 'Army': 'United States Military Academy', 'Air Force': 'United States Air Force Academy',
         "Hawai'i": 'Hawaii', 'Sacramento State': 'California State Sacramento', 'Middle Tennessee': 'Middle Tennessee State', 'Massachusetts': 'Massachusetts Amherst'}
PRIVATE = {'Notre Dame', 'USC', 'Stanford', 'Miami', 'Vanderbilt', 'TCU', 'Baylor', 'SMU', 'Duke', 'Wake Forest', 'Northwestern', 'Boston College', 'Syracuse', 'Rice', 'Tulane', 'Tulsa', 'BYU', 'Liberty',
           'Army', 'Navy', 'Air Force'}
def expenses(pkl):
    fb = pd.read_pickle(pkl); out, E = {}, {}
    for r in fb.itertuples(): E.setdefault(r.state_cd, []).append((nk(r.institution_name), float(r.EXP_MEN) if r.EXP_MEN == r.EXP_MEN else None))
    for tid, t in T.items():
        st = (LOC.get(tid) or [0, 0, None])[2]; k = nk(ALIAS.get(t['team'], t['team']))
        c = [(n, v) for n, v in E.get(st, []) if n == k] or sorted([(n, v) for n, v in E.get(st, []) if n.startswith(k)], key=lambda x: len(x[0]))[:1]
        if c and c[0][1]: out[tid] = math.log(c[0][1])
    return out
EX = {2024: expenses(sys.argv[2]), 2025: expenses(sys.argv[3])}
SCH = [t for t in T if t in L and L[t][0] in ('P4', 'G5') and t in LOC]
def hav(a, b, c, d):
    p = math.pi / 180; x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(x))
def design(S, money):
    ex = EX[S]; lev = {t: L[t][0] for t in SCH}
    med = {l: float(np.median([ex[t] for t in SCH if t in ex and lev[t] == l])) for l in ('P4', 'G5')}
    ev = np.array([ex.get(t, med[lev[t]]) for t in SCH]); ez = (ev - ev.mean()) / ev.std()
    Xs, ys, cl = [], [], []
    for m in moves:
        if m['S'] != S or m['from'] not in SCH or m['to'] not in SCH or m['from'] == m['to']: continue
        rows = []
        for j, t in enumerate(SCH):
            o, d = lev[m['from']], lev[t]
            base = [1.0 if (d == 'P4' and o == 'P4') else 0.0, 1.0 if (d == 'P4' and o == 'G5') else 0.0, 1.0 if (d == 'G5' and o == 'G5') else 0.0,
                    L[t][1], L[t][1] * L[m['from']][1], math.log(1 + hav(m['lat'], m['lon'], LOC[t][0], LOC[t][1])), 1.0 if m['st'] == LOC[t][2] else 0.0]
            mon = [L[t][2], 1.0 if T[t]['team'] in PRIVATE else 0.0] if money == 'don' else [ez[j], 0.0 if t in ex else 1.0]
            rows.append(base + mon + [-30.0 if t == m['from'] else 0.0])
        Xs.append(rows); ys.append(SCH.index(m['to'])); cl.append(m['from'])
    return np.array(Xs), np.array(ys), np.array(cl)
def fit(X, y, lam=1.0):
    k = X.shape[2] - 1; b = np.zeros(k)
    for _ in range(60):
        u = X[:, :, :k] @ b + X[:, :, k]; u -= u.max(1, keepdims=True); p = np.exp(u); p /= p.sum(1, keepdims=True)
        xb = (p[:, :, None] * X[:, :, :k]).sum(1)
        g = (X[np.arange(len(y)), y, :k] - xb).sum(0) - lam * b
        H = -(np.einsum('nj,njk,njl->kl', p, X[:, :, :k], X[:, :, :k]) - xb.T @ xb) - lam * np.eye(k)
        b -= np.linalg.solve(H, g)
    return b
def ll(X, y, b):
    k = len(b); u = X[:, :, :k] @ b + X[:, :, k]; u -= u.max(1, keepdims=True); lp = u - np.log(np.exp(u).sum(1, keepdims=True))
    return lp[np.arange(len(y)), y]
D = {(S, m): design(S, m) for S in (2024, 2025) for m in ('don', 'eada')}
out = {'schools': len(SCH), 'eadaMatched': {S: sum(1 for t in SCH if t in EX[S]) for S in EX}, 'folds': {}}
for tr, te in ((2024, 2025), (2025, 2024)):
    l = {}
    for m in ('don', 'eada'):
        b = fit(*D[(tr, m)][:2]); l[m] = ll(D[(te, m)][0], D[(te, m)][1], b)
        if m == 'eada': coef = [round(float(x), 3) for x in b[-2:]]
    d = l['eada'] - l['don']; c = D[(te, 'don')][2]; ks = sorted(set(c)); mm = np.array([d[c == x].sum() for x in ks])
    out['folds'][f'{tr}->{te}'] = {'n': len(d), 'llDon': round(float(l['don'].mean()), 4), 'llEada': round(float(l['eada'].mean()), 4), 'diff': round(float(d.mean()), 5),
                                  't': round(float(mm.mean() / (mm.std(ddof=1) / math.sqrt(len(ks)))), 2), 'clusters': len(ks), 'eadaCoef': coef}
print(json.dumps(out, indent=1))
