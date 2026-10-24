#!/usr/bin/env python3
"""Round-2 research harness (Oct 24 2026): do KenPom roster-structure fields (last season's height by position,
experience, bench minutes, points by position) improve the CBB preseason prior?  Prior-level test: walk-forward ridge
of the season's final KenPom AdjEM on the shipped PRIOR_F terms (scripts/data/cbb_team_prior.json, last = last season's
AdjEM) with and without a candidate.  Same ridge (5.0 on everything but the intercept) as cbb_games.Walk.prior_coef.
    python3 -I scripts/cbb_kenpom_structure_backtest.py KAGGLE_DIR
KAGGLE_DIR = unzip of kaggle.com/api/v1/datasets/download/jonathanpilafas/2024-march-madness-statistical-analysis"""
import csv, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
KD = sys.argv[1]
tp = json.load(open(os.path.join(HERE, 'data', 'cbb_team_prior.json')))


def rd(f):
    return list(csv.DictReader(open(os.path.join(KD, f))))


SUM = {(int(r['Season']), r['TeamName']): r for r in rd('INT _ KenPom _ Summary.csv')}
HT = {(int(r['Season']), r['TeamName']): r for r in rd('INT _ KenPom _ Height.csv')}
alias = {'N.C. State': 'NC State', 'Detroit Mercy': 'Detroit', 'Saint Francis': 'St. Francis PA', 'IU Indy': 'IUPUI',
         'Houston Christian': 'Houston Baptist', 'East Texas A&M': 'Texas A&M Commerce'}


def kp(d, y, t):
    return d.get((y, t)) or d.get((y, alias.get(t, t)))


PF = ['one', 'last', 'retmin', 'tr', 'trmin', 'fvtop', 'agew', 'tenure', 'rret', 'fvfrm']
LASTF = ['Experience', 'Bench', 'AvgHeight', 'EffectiveHeight', 'CenterHeight', 'PFHeight', 'SFHeight', 'SGHeight', 'PGHeight',
         'CenterPts', 'PFPts', 'SFPts', 'SGPts', 'PGPts']


def fl(r, k):
    try:
        return float(r[k])
    except Exception:
        return None


rows = []   # (season, team, base feats dict, cand dict, target)
for s in range(2015, 2027):
    for t, f in tp[str(s)].items():
        a, b = kp(SUM, s, t), kp(SUM, s - 1, t)
        if not a:
            continue
        ln = float(b['AdjEM']) if b else -8.0
        d = {k: f.get(k, 0.0) for k in PF}
        d['one'] = 1.0
        d['last'] = ln
        h = kp(HT, s - 1, t)
        c = {k: (fl(h, k) if h else None) for k in LASTF}
        rows.append((s, t, d, c, float(a['AdjEM'])))
print('rows', len(rows), 'with last height', sum(r[3]['Experience'] is not None for r in rows))
mu = {k: np.mean([r[3][k] for r in rows if r[3][k] is not None]) for k in LASTF}
sd = {k: np.std([r[3][k] for r in rows if r[3][k] is not None]) for k in LASTF}


def z(r, k):
    v = r[3][k]
    return 0.0 if v is None else (v - mu[k]) / sd[k]


CAND = {}
for k in LASTF:
    CAND[k] = [lambda r, k=k: z(r, k)]
CAND['EffHt+Exp'] = [lambda r: z(r, 'EffectiveHeight'), lambda r: z(r, 'Experience')]
CAND['Exp*retmin'] = [lambda r: z(r, 'Experience') * r[2]['retmin']]
CAND['Bench*retmin'] = [lambda r: z(r, 'Bench') * r[2]['retmin']]
CAND['EffHt*retmin'] = [lambda r: z(r, 'EffectiveHeight') * r[2]['retmin']]
CAND['posht5'] = [lambda r, k=k: z(r, k + 'Height') for k in ['Center', 'PF', 'SF', 'SG', 'PG']]
CAND['pospts5'] = [lambda r, k=k: z(r, k + 'Pts') for k in ['Center', 'PF', 'SF', 'SG', 'PG']]
SEV = ['Experience', 'Bench', 'EffectiveHeight', 'CenterHeight', 'PGHeight', 'CenterPts', 'PGPts']
CAND['all_struct'] = [lambda r, k=k: z(r, k) for k in SEV]
CAND['all_struct*retmin'] = [lambda r, k=k: z(r, k) * r[2]['retmin'] for k in SEV]


CAND['EffHt+Bench*retmin'] = [lambda r: z(r, 'EffectiveHeight'), lambda r: z(r, 'Bench') * r[2]['retmin']]
CAND['EffHt*ret+Bench*ret'] = [lambda r: z(r, 'EffectiveHeight') * r[2]['retmin'], lambda r: z(r, 'Bench') * r[2]['retmin']]


def walk(extra, first=2017):
    err = {}
    for s in range(first, 2027):
        tr = [r for r in rows if r[0] < s]
        te = [r for r in rows if r[0] == s]

        def X(rs):
            return np.array([[r[2][k] for k in PF] + [fn(r) for fn in extra] for r in rs])
        A = X(tr)
        y = np.array([r[4] for r in tr])
        P = np.diag([0.0] + [5.0] * (A.shape[1] - 1))
        c = np.linalg.solve(A.T @ A + P, A.T @ y)
        err[s] = np.array([r[4] for r in te]) - X(te) @ c
    return err


def tt(d):
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


def cat(e, ss):
    return np.concatenate([e[s] for s in ss])


def rm(a):
    return math.sqrt((a ** 2).mean())


base = walk([])
TUNE, HELD = range(2017, 2021), range(2021, 2027)
print('base RMSE tune(2017-20) %.3f held(2021-26) %.3f' % (rm(cat(base, TUNE)), rm(cat(base, HELD))))
print('%-20s %7s %7s | %7s %7s | folds better (of 10) | per-season dRMSE 2017..2026' % ('cand', 'tuneRM', 'dTune', 'heldRM', 'dHeld'))
for name, ex in CAND.items():
    e = walk(ex)
    out = []
    for ss in (TUNE, HELD):
        a, b = cat(e, ss), cat(base, ss)
        out += [rm(a), rm(a) - rm(b), tt(a ** 2 - b ** 2)]
    wins = sum(rm(e[s]) < rm(base[s]) for s in range(2017, 2027))
    per = ' '.join('%+.2f' % (rm(e[s]) - rm(base[s])) for s in range(2017, 2027))
    print('%-20s %7.3f %+7.3f t%+5.1f | %7.3f %+7.3f t%+5.1f | %d | %s' % ((name,) + tuple(out) + (wins, per)))
