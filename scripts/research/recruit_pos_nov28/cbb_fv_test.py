"""Does the projected college position help CBB recruit FV? Realized FV (cbb_recruit_hist rfv) on the recruit
model's own inputs (log rank, its square, old for the class), then + listed position, then + projected position
(out of fold: each class's projection comes from a position model fit without that class). OLS, held out by class."""
import gzip, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import mnl, cbb_pos as CP

d = json.load(gzip.open(os.path.join(CP.ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')))['recruits']
rows = [r for r in d if r.get('pos') in CP.FAM and r.get('rk') and r['cls'] <= 2022]   # FV needs three seasons to read
prow = CP.load()
hs = [r['ht'] for r in prow if r['ht']]; ws = [r['wt'] for r in prow if r['wt']]
CP.SZ.update(ht=float(np.mean(hs)), hs=float(np.std(hs)), wt=float(np.mean(ws)), ws=float(np.std(ws)),
             lr=float(np.mean([math.log(r['rk']) for r in prow if r['rk']])))
Xp = np.array([CP.feats(r['code'], r['ht'], r['wt'], r['rk']) for r in prow]); Yp = np.array([r['y'] for r in prow]); cp = np.array([r['c'] for r in prow])
cls = sorted({r['cls'] for r in rows})
proj = {}
for k in cls:      # the position model without class k (and without later classes: point in time would be stricter; see forward)
    B = mnl.fit(Xp[cp != k], Yp[cp != k], 1.0)
    for r in rows:
        if r['cls'] == k: proj[id(r)] = mnl.predict(np.array([CP.feats(r['pos'], r['ht'], r['wt'], r['rk'])]), B)[0]
y = np.array([float(r['rfv'] or 20) for r in rows]); c = np.array([r['cls'] for r in rows])
lr = np.array([math.log(r['rk']) for r in rows]); old = np.array([float(r.get('old') or 0) for r in rows])
base = np.c_[np.ones(len(rows)), lr, lr * lr, old]
lst = np.array([[1.0 if r['pos'] == p else 0.0 for p in CP.CODES[1:]] for r in rows])
pj = np.array([proj[id(r)] for r in rows])
ht = np.array([((r['ht'] or CP.SZ['ht']) - CP.SZ['ht']) / CP.SZ['hs'] for r in rows])
forms = {'base': base, 'listed': np.c_[base, lst], 'projected': np.c_[base, pj[:, 1:]],
         'projected x rank': np.c_[base, pj[:, 1:], pj[:, 1:] * lr[:, None]], 'height': np.c_[base, ht]}
err = {}
for nm, X in forms.items():
    e = np.zeros(len(y))
    for k in cls:
        tr = c != k
        b = np.linalg.solve(X[tr].T @ X[tr] + .5 * np.eye(X.shape[1]), X[tr].T @ y[tr]); e[~tr] = (y[~tr] - X[~tr] @ b) ** 2
    err[nm] = e; print(nm, 'MSE %.3f' % e.mean())
out = {}
for nm in forms:
    if nm == 'base': continue
    dl = [err['base'][c == k].mean() - err[nm][c == k].mean() for k in cls]
    t = np.mean(dl) / (np.std(dl, ddof=1) / math.sqrt(len(dl)))
    out[nm] = {'mse': [round(err['base'].mean(), 3), round(err[nm].mean(), 3)], 't': round(float(t), 2), 'wins': int(sum(x > 0 for x in dl)), 'classes': len(dl)}
    print(nm, out[nm])
dl = [err['listed'][c == k].mean() - err['projected'][c == k].mean() for k in cls]
out['projected_vs_listed'] = {'t': round(float(np.mean(dl) / (np.std(dl, ddof=1) / math.sqrt(len(dl)))), 2), 'wins': int(sum(x > 0 for x in dl))}
print('projected vs listed', out['projected_vs_listed'])
json.dump(out, open(os.path.join(HERE, 'cbb_fv_test.json'), 'w'), indent=1)
