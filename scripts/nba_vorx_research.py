"""VORX on the box blend (xpm) vs on rXPM (txpm, team-adjusted). Team VORX share = sum of value x 5 x MP / team MP;
target team W% same season and next season (minutes of the next season's roster, as nba_pxpm_research team test).
Writes data/nba_vorx_research.json. Nov 24 2026: ships txpm (same-season R2 up, next season a tie)."""
import sys, json, numpy as np
sys.argv = sys.argv[:1]; sys.path.insert(0, 'scripts')
import nba_pxpm_research as R

W = {(r.year, r.tm): r.wins / (r.wins + r.losses) for r in R.T.itertuples()}
YRS = [n for n in range(2011, 2026) if n not in (2020, 2021)]


def rows(key, n, nxt):
    vals = {pid: p[key] for pid, p in R.S[n]['p'].items() if p.get(key) is not None}
    fill = float(np.mean([v for pid, v in vals.items() if R.S[n]['p'][pid]['mp'] < 500])); yy = n + 1 if nxt else n
    X = {}
    for r in R.P[R.P.year == yy].itertuples():
        X[r.tm] = X.get(r.tm, 0) + vals.get(r.pid, fill) * 5 * r.mp / R.TMP[(yy, r.tm)]
    return {t: (X[t], W[(yy, t)]) for t in X if (yy, t) in W}


def r2(a): return float(np.corrcoef(a[:, 0], a[:, 1])[0, 1] ** 2)


out = {}
for key, lab in (('xpm', 'XPM box blend'), ('txpm', 'rXPM')):
    o = {}
    for nxt in (False, True):
        ps = [n for n in YRS if not nxt or n + 1 not in (2020, 2021)]
        D = {n: rows(key, n, nxt) for n in ps}
        e = []
        for h in ps:
            tr = np.array([v for n in ps if n != h for v in D[n].values()]); b, a = np.polyfit(tr[:, 0], tr[:, 1], 1)
            te = np.array(list(D[h].values())); e += list(te[:, 1] - (a + b * te[:, 0]))
        allv = np.array([v for n in ps for v in D[n].values()])
        o['next' if nxt else 'same'] = {'r2': round(r2(allv), 4), 'winsRmse': round(float(np.sqrt(np.mean(np.square(e)))) * 82, 3),
                                        'slope': round(float(np.polyfit(allv[:, 0], allv[:, 1], 1)[0]), 4), 'n': len(allv)}
        o['per_' + ('next' if nxt else 'same')] = {n: r2(np.array(list(D[n].values()))) for n in ps}
    out[lab] = o
test = {}
for k in ('same', 'next'):
    d = np.array([out['rXPM']['per_' + k][n] - out['XPM box blend']['per_' + k][n] for n in out['rXPM']['per_' + k]])
    test[k] = {'mean': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2),
               'better': int((d > 0).sum()), 'of': len(d)}
for o in out.values(): o.pop('per_same'); o.pop('per_next')
res = {'metrics': out, 'test': test, 'ship': 'txpm' if test['same']['t'] > 2 and test['next']['t'] > -2 else 'xpm'}
json.dump(res, open('data/nba_vorx_research.json', 'w'), indent=1); print(json.dumps(res, indent=1))
