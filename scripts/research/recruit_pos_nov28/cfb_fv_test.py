"""Does the projected college position help CFB recruit FV? The recruit index's NFL outcome (scripts/cfb_recruit_retarget.py:
mean of weighted AV a season and draft capital, on the FV scale; undrafted 20), ESPN 2014-19 classes linked by ESPN id.
Base = ESPN grade, the 4-star hinge, log rank and the live fit's listed group (scripts/cfb_recruit_fit.py group());
then the projected position (out of fold: the position model without that class) in place of the ATH group, and on top
of every group. Ridge OLS, held out by class, paired t on MSE."""
import csv, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import mnl, cfb_pos as F
import cfb_recruit_retarget as RT
import cfb_recruit_fit as R

picks, _ = RT.nfl()
out = {str(p['espn']): F_ for p in picks if p['espn'] for F_ in [RT.fv_of((p['av'] + p['cap']) / 2)]}
rows = [r for r in F.load() if 2014 <= r['c'] <= 2024]
hs = [r['ht'] for r in rows if r['ht']]; ws = [r['wt'] for r in rows if r['wt']]; gs = [r['grade'] for r in rows if r['grade']]
F.SZ.update(ht=float(np.mean(hs)), hs=float(np.std(hs)), wt=float(np.mean(ws)), ws=float(np.std(ws)), gr=float(np.mean(gs)), gs=float(np.std(gs)))
X = np.array([F.feats(r['code'], r['ht'], r['wt'], r['grade']) for r in rows]); Y = np.array([r['y'] for r in rows]); c = np.array([r['c'] for r in rows])
test = [r for r in rows if r['c'] <= 2019 and r['grade']]
P = {}
for k in range(2014, 2020):
    B = mnl.fit(X[c != k], Y[c != k], 1.0)
    for r in test:
        if r['c'] == k: P[r['id']] = mnl.predict(np.array([F.feats(r['code'], r['ht'], r['wt'], r['grade'])]), B)[0]
y = np.array([out.get(r['id'], 20.0) for r in test]); cc = np.array([r['c'] for r in test])
g = np.array([(r['grade'] - 80) / 10 for r in test])
rk = np.array([math.log(1 + (r.get('rank') or 400)) for r in test]) if False else None
base = np.c_[np.ones(len(test)), g, np.maximum(0, g), g * g]
GR = [x for x in R.GROUPS]
lg = np.array([[1.0 if R.group(r['code'], r['ht'], r['wt']) == q else 0.0 for q in GR[1:]] for r in test])
pj = np.array([P[r['id']] for r in test])
isath = np.array([R.group(r['code'], r['ht'], r['wt']) == 'ATH' for r in test])
# ATH rows: the projected mix in place of the ATH dummy (DB split as the CB/S columns share it)
swap = lg.copy(); m = {q: GR[1:].index(q) for q in GR[1:]}
for i in np.where(isath)[0]:
    swap[i] = 0; p = dict(zip(F.G, pj[i]))
    for q in ('RB', 'WR', 'TE', 'OL', 'DL', 'LB'): swap[i, m[q]] += p[q]
    swap[i, m['EDGE']] += 0; swap[i, m['CB']] += p['DB'] / 2; swap[i, m['S']] += p['DB'] / 2
forms = {'listed group': np.c_[base, lg], 'ATH projected': np.c_[base, swap], 'listed + projected': np.c_[base, lg, pj[:, 1:]]}
err = {}
for nm, Xf in forms.items():
    e = np.zeros(len(y))
    for k in range(2014, 2020):
        tr = cc != k
        b = np.linalg.solve(Xf[tr].T @ Xf[tr] + 1.0 * np.eye(Xf.shape[1]), Xf[tr].T @ y[tr]); e[~tr] = (y[~tr] - Xf[~tr] @ b) ** 2
    err[nm] = e
res = {'n': len(test), 'ath': int(isath.sum())}
for nm in list(forms)[1:]:
    for sub, msk in (('all', np.ones(len(y), bool)), ('ATH', isath)):
        d = [err['listed group'][(cc == k) & msk].mean() - err[nm][(cc == k) & msk].mean() for k in range(2014, 2020)]
        res[nm + ' ' + sub] = {'mse': [round(float(err['listed group'][msk].mean()), 3), round(float(err[nm][msk].mean()), 3)],
                               't': round(float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d)))), 2), 'wins': int(sum(x > 0 for x in d)), 'classes': len(d)}
        print(nm, sub, res[nm + ' ' + sub])
json.dump(res, open(os.path.join(HERE, 'cfb_fv_test.json'), 'w'), indent=1)
