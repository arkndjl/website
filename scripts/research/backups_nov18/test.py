"""Backtest (prereg.md): ESPN roster backups graded on NFL outcomes (B) vs the shipped board-copy fit (A).
    python3 scripts/research/backups_nov18/test.py      # needs rows.json.gz from build.py
"""
import gzip, json, math, os, re, sys
from collections import Counter, defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import fv_dist as F
from cfb_all import read_cfb_all

POSS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S']
D = json.load(gzip.open(os.path.join(HERE, 'rows.json.gz'), 'rt'))
rows = [r for r in D['rows'] if r['g'] in POSS]
CL = sorted({r['year'] for r in rows})


def cz(pos, fv, years=1):
    return {'pos_QB': +(pos == 'QB'), 'pos_TE': +(pos == 'TE'), 'pos_LB': +(pos == 'LB'), 'pos_RB': +(pos == 'RB'), 'pos_EDGE': +(pos == 'EDGE'),
            'pos_DL': +(pos == 'DL'), 'under': +(years <= 2.5), 'early': 1, 'walkon': 0, 'lowsnap': 0, 'cons': 0, 'level': (fv - 45) / 10}


# ---- A: the shipped backup grade, read back off the live board's backups (exact: fvs steps are linear in the drivers)
A_ = read_cfb_all(); c = A_['cols']; L = [dict(zip(c, r)) for r in A_['rows']]
bk = [r for r in L if r.get('src') == 'espn' and r.get('fvs') and r['pos'] in POSS]
inch = lambda h: (lambda m: int(m[1]) * 12 + int(m[2]) if m else None)(re.match(r'(\d+)-(\d+)', h or ''))
base = defaultdict(Counter); acfr = Counter(); X = []; y = []; frt = defaultdict(list)
for r in bk:
    s = dict((k, v) for k, v in r['fvs'])
    base[(r['pos'], r['div'])][s['b']] += 1
    rep = r.get('report') or {}; t = ' '.join(rep.get('plus', []) + rep.get('minus', []))
    m = re.search(r'247 composite ([\d.]+)(?:, #(\d+) nationally)?', json.dumps(r['report']))
    if r['cls'] == 'Fr' and 'older' not in t: acfr[s.get('ac', 0.0)] += 1
    if m: X.append([(float(m[1]) - .85) * 10, 1, 6 - math.log(int(m[2])) if m[2] else 0]); y.append(s.get('pd', 0.0))
    if inch(r['ht']) and r['wt']: frt[(r['pos'], inch(r['ht']), r['wt'])].append(s.get('fr', 0.0))
W = np.linalg.lstsq(np.array(X), np.array(y), rcond=None)[0]
res = np.array(y) - np.array(X) @ W
print('A pedigree weights (rating x10, has, 6-ln rank):', W.round(3), 'resid sd', res.std().round(4), 'rows', len(y))
B0 = {k: v.most_common(1)[0][0] for k, v in base.items()}; AC = acfr.most_common(1)[0][0]
frm = {k: float(np.mean(v)) for k, v in frt.items()}
print('A base by position (FBS):', {p: B0.get((p, 'FBS')) for p in POSS}, 'freshman class step', AC)


def frA(p, h, w):
    if not h or not w: return 0.0
    if (p, h, w) in frm: return frm[(p, h, w)]
    near = [(abs(k[1] - h) * 10 + abs(k[2] - w), v) for k, v in frm.items() if k[0] == p and abs(k[1] - h) <= 1 and abs(k[2] - w) <= 10]
    return min(near)[1] if near else 0.0


def gradeA(r):
    div = 'FCS' if r['level'] == 'FCS' else 'FBS'
    pd = (W @ [((r['comp'] - .85) * 10), 1, 6 - math.log(r['cRank']) if r.get('cRank') else 0]) if r.get('comp') is not None else 0.0
    return max(20.0, min(80.0, B0[(r['g'], div)] + AC + pd + frA(r['g'], r['ht'], r['wt'])))


gA = np.array([gradeA(r) for r in rows])
mA = np.array([F.at_mean('cfb', g, cz(r['g'], g)) for g, r in zip(gA, rows)])
yv = np.array([r['rfv'] for r in rows])

# ---- B: hurdle on NFL outcomes, leave one class out
norm = {}
for p in POSS:
    hs = [r['ht'] for r in rows if r['g'] == p and r['ht']]; ws = [r['wt'] for r in rows if r['g'] == p and r['wt']]
    bm = [703 * r['wt'] / r['ht'] ** 2 for r in rows if r['g'] == p and r['ht'] and r['wt']]
    norm[p] = [(np.mean(v), np.std(v)) for v in (hs, ws, bm)]
cl3 = lambda v: max(-3.0, min(3.0, v))


def feats(g, ht, wt, comp, crank, level, nm=None):
    n = (nm or norm)[g]
    hz = cl3((ht - n[0][0]) / n[0][1]) if ht else 0.0; wz = cl3((wt - n[1][0]) / n[1][1]) if wt else 0.0
    bz = cl3((703 * wt / ht ** 2 - n[2][0]) / n[2][1]) if ht and wt else 0.0
    has = comp is not None
    return [*(float(g == p) for p in POSS), hz, wz, bz, (comp - .85) * 10 if has else 0.0, float(has),
            6 - math.log(crank) if has and crank else 0.0, float(level == 'FCS'), float(level == 'G5')]


NP = len(POSS)
Xall = np.array([feats(r['g'], r['ht'], r['wt'], r.get('comp'), r.get('cRank'), r['level']) for r in rows])
on = np.array([r['drafted'] for r in rows], float)


def logit(X, y, lam=30.0, it=60):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1; Z = (X - mu) / sd
    A = np.c_[np.ones(len(Z)), Z]; b = np.zeros(A.shape[1]); b[0] = math.log(y.mean() / (1 - y.mean()))
    P = np.eye(A.shape[1]) * lam; P[0, 0] = 0
    for _ in range(it):
        q = 1 / (1 + np.exp(-np.clip(A @ b, -30, 30))); st = np.linalg.solve(A.T @ (A * (q * (1 - q) + 1e-9)[:, None]) + P, A.T @ (q - y) + P @ b)
        b -= np.clip(st, -1, 1)
        if np.abs(st).max() < 1e-8: break
    return lambda Xn: 1 / (1 + np.exp(-np.clip(np.c_[np.ones(len(Xn)), (Xn - mu) / sd] @ b, -30, 30)))


def ridge(X, y, lam=30.0):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1; Z = (X - mu) / sd
    A = np.c_[np.ones(len(Z)), Z]; P = np.eye(A.shape[1]) * lam; P[0, 0] = 0
    b = np.linalg.solve(A.T @ A + P, A.T @ y)
    return lambda Xn: np.c_[np.ones(len(Xn)), (Xn - mu) / sd] @ b


import cfb_backup_fit as BF


def fitB(idx):
    m = BF.fit([rows[i] for i in idx], norm)
    return lambda Xn: BF.predict(m, Xn)


cls = np.array([r['year'] for r in rows]); mB = np.zeros(len(rows))
for y0 in CL:
    te = np.where(cls == y0)[0]; tr = np.where(cls != y0)[0]
    mB[te] = fitB(tr)(Xall[te])

# ---- primary: per-class paired MSE
gain = []
for y0 in CL:
    j = cls == y0; gain.append(np.mean((mA[j] - yv[j]) ** 2) - np.mean((mB[j] - yv[j]) ** 2))
g = np.array(gain); t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))
out = {'n': len(rows), 'mseA': round(float(np.mean((mA - yv) ** 2)), 2), 'mseB': round(float(np.mean((mB - yv) ** 2)), 2),
       'perClassGain': [round(float(x), 2) for x in g], 't': round(float(t), 2), 'won': f'{int((g > 0).sum())}/{len(g)}'}
out['pass'] = bool(t >= 2 and (g > 0).sum() >= 6)
print(json.dumps(out))

# ---- secondary: calibration
def band(r):
    if r.get('comp') is None: return 'unrated'
    k = r['cRank'] or 9999
    return next(b for lo, hi, b in ((1, 6, '1-6'), (7, 41, '7-41'), (42, 143, '42-143'), (144, 400, '144-400'), (401, 1e9, '401+')) if lo <= k <= hi)
cal = defaultdict(list)
for i, r in enumerate(rows):
    cal['band ' + band(r)].append(i); cal['pos ' + r['g']].append(i)
    if r['g'] == 'QB': cal['QB ' + band(r)].append(i)
tab = {}
for k, ix in cal.items():
    ix = np.array(ix); tab[k] = {'n': len(ix), 'real': round(float(yv[ix].mean()), 1), 'A': round(float(mA[ix].mean()), 1), 'B': round(float(mB[ix].mean()), 1),
                                 'mseA': round(float(np.mean((mA[ix] - yv[ix]) ** 2)), 1), 'mseB': round(float(np.mean((mB[ix] - yv[ix]) ** 2)), 1)}
for k in sorted(tab): print(k.ljust(16), tab[k])
json.dump({'primary': out, 'calibration': tab, 'A': {'pedigree': W.round(4).tolist(), 'base': {f'{a}|{b}': v for (a, b), v in B0.items()}, 'frStep': AC}},
          open(os.path.join(HERE, 'results.json'), 'w'), indent=1)

# A with a neutral frame step (A's frame reads college listings; the signees carry high school ones, lighter, which
# pulls A's frame points down): the same test, reported beside the primary
gA0 = np.array([gradeA(r) - frA(r['g'], r['ht'], r['wt']) for r in rows])
mA0 = np.array([F.at_mean('cfb', g, cz(r['g'], g)) for g, r in zip(gA0, rows)])
g0 = np.array([np.mean((mA0[cls == y0] - yv[cls == y0]) ** 2) - np.mean((mB[cls == y0] - yv[cls == y0]) ** 2) for y0 in CL])
print('A frame-neutral: mse', round(float(np.mean((mA0 - yv) ** 2)), 2), 'B', out['mseB'], 't', round(float(g0.mean() / (g0.std(ddof=1) / math.sqrt(len(g0)))), 2), f'{int((g0 > 0).sum())}/9')
for k in ('pos QB', 'band 42-143', 'band 7-41', 'band 1-6', 'band 401+'):
    ix = np.array(cal[k]); print(' ', k, 'real', round(float(yv[ix].mean()), 1), 'A0', round(float(mA0[ix].mean()), 1), 'B', round(float(mB[ix].mean()), 1))
mA = mA0
# top of the class (added after the primary was read, for the ship note only)
for lo, hi in ((1, 1), (1, 3), (4, 10), (11, 25), (26, 60)):
    ix = np.array([i for i, r in enumerate(rows) if r.get('comp') is not None and r.get('cRank') and lo <= r['cRank'] <= hi])
    print(f'rank {lo}-{hi}', len(ix), 'real', round(float(yv[ix].mean()), 1), 'A', round(float(mA[ix].mean()), 1), 'B', round(float(mB[ix].mean()), 1))
