"""home country + indoor terms on top of the shipped tennis blend (walk-forward weights, WIN seasons), held 2023+,
t clustered by tournament; and vs the feed's no-vig close (2025+)."""
import gzip, csv, json, os, sys, math, shutil
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tennis_data as T
from tn_country import country, indoor
os.makedirs(T.CACHE, exist_ok=True)
if not os.path.exists(T.HIST):
    def num(x, f=int):
        return f(x) if x not in ('', None) else None
    rows, tn = [], {}
    for r in csv.reader(gzip.open('/mnt/project-files/tennis/matches.csv.gz', 'rt')):
        if r[0] == 'd': continue
        ws = [num(x) for x in r[11:20]]; ls = [num(x) for x in r[20:29]]
        rows.append([int(r[0]), r[1], r[2], r[3], r[4], int(r[5]), r[6], r[7], r[8], r[9],
                     ws if any(v is not None for v in ws) else None, ls if any(v is not None for v in ls) else None,
                     num(r[29]), num(r[30]), num(r[31], float), num(r[32], float)])
        tn[r[6]] = r[10]
    json.dump({'rows': rows, 'tn': tn}, gzip.open(T.HIST, 'wt'))
    shutil.copy('/mnt/project-files/tennis/players.json.gz', T.PLAYERS)
import tennis_model as M
rows, players, tn = T.load()
P = json.load(open(ROOT + '/data/tennis_fit.json'))['params']
_, rec = M.run(rows, P, score=lambda r: M.scored(r, 2012 - M.WIN, 2100))
pw = M.wf_probs(rec, P)
nat = {k: (v.get('nat') or '') for k, v in players.items()}
# player indoor share of results: track running indoor-minus-outdoor Elo residual per player (shrunk)
from collections import defaultdict
res = defaultdict(lambda: [0.0, 0, 0.0, 0])   # pid -> [indoor resid sum, n, outdoor resid sum, n]
X, y, P0, G, Y, C = [], [], [], [], [], []
for x, p in zip(rec, pw):
    r = x[0]; name = tn.get(r[6], ''); cc = country(name); ind = indoor(r[1], name)
    w, l = r[7], r[8]
    hw = 1.0 if cc and nat.get(w) == cc else 0.0; hl = 1.0 if cc and nat.get(l) == cc else 0.0
    def dev(pid, k=30):
        a = res[pid]
        if a[1] == 0 or a[3] == 0: return 0.0
        ne = a[1] * a[3] / (a[1] + a[3])
        return (a[0] / a[1] - a[2] / a[3]) * ne / (ne + k)
    iw = (dev(w) - dev(l)) if ind else -(dev(w) - dev(l)) * 0.0
    yr = r[0] // 10000
    if yr >= 2012:
        X.append([hw - hl, iw]); P0.append(p); G.append(r[6]); Y.append(yr)
        C.append(r[14] if r[14] and 0 < r[14] < 1 else None)
    e = 1 - p   # winner's residual
    for pid, s in ((w, e), (l, -e)):
        a = res[pid]
        if ind: a[0] += s; a[1] += 1
        else: a[2] += s; a[3] += 1
X = np.array(X); P0 = np.array(P0); Y = np.array(Y); G = np.array(G)
z0 = np.log(P0 / (1 - P0))
def fit(idx, cols, base):
    F = X[idx][:, cols]; Z = base[idx]
    Xf = np.vstack([F, -F]); off = np.r_[Z, -Z]; yy = np.r_[np.ones(len(F)), np.zeros(len(F))]
    b = np.zeros(len(cols))
    for _ in range(25):
        p = 1 / (1 + np.exp(-(off + Xf @ b)))
        H = (Xf * (p * (1 - p))[:, None]).T @ Xf + 1e-3 * np.eye(len(cols))
        b += np.linalg.solve(H, Xf.T @ (yy - p))
    return b
import harness as HH
def test(cols, base, years, label):
    # walk-forward: b from all earlier years in 2012+
    nl, ol, gg = [], [], []
    for yr in years:
        tr = (Y < yr) & ~np.isnan(base); te = (Y == yr) & ~np.isnan(base)
        if tr.sum() < 2000 or te.sum() == 0: continue
        b = fit(tr, cols, base)
        z = base[te] + X[te][:, cols] @ b
        nl += list(np.log1p(np.exp(-z))); ol += list(np.log1p(np.exp(-base[te]))); gg += list(G[te])
    r = HH.paired(nl, ol, cluster=np.array(gg))
    out = dict(t=round(r['t'], 2), d=round(float(r['d']) * 1e4, 2), n=r['n'], b=[round(float(v), 3) for v in fit(~np.isnan(base), cols, base)])
    print(label, out, flush=True); return out
out = {'share_home': float((X[:, 0] != 0).mean())}
for cols, nm in (([0], 'home'), ([1], 'indoor dev'), ([0, 1], 'both')):
    out[nm] = {'tune': test(cols, z0, range(2014, 2023), nm + ' tune'), 'held': test(cols, z0, range(2023, 2027), nm + ' held')}
cz = np.array([math.log(c / (1 - c)) if c else np.nan for c in C])
out['home vs close'] = test([0], cz, range(2026, 2027), 'home vs close 2026 (fit 2025)')
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_oct31', 'tennis_home.json'), 'w'), indent=1)
