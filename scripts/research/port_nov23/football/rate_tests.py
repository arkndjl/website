#!/usr/bin/env python3
"""N4 (rookie aXP/60) and N5 (SV -> pXP/60 prior) from prereg.md, on nfl_rate_research's board replays."""
import csv, datetime, gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nfl_rate_research as RR
import nfl_rate as R
import nfl_market as MK
D = RR.load()
out = {}
# ---------------- N4
born, rook = {}, {}
for r in csv.DictReader(open(os.path.join(ROOT, 'scripts/.cache/nfl/players.csv'), encoding='utf-8')):
    if r.get('pfr_id'):
        born[r['pfr_id']] = r['birth_date']
        try:
            rook[r['pfr_id']] = int(r['rookie_season'] or r['draft_year'])
        except ValueError:
            pass
K = json.load(open(os.path.join(ROOT, 'data/nfl_rate_fit.json')))['model']['K']
def age(pid, y):
    try:
        b = datetime.date.fromisoformat(born[pid][:10])
    except (KeyError, ValueError):
        return None
    return (datetime.date(y, 9, 1) - b).days / 365.25
R4 = []
for y in range(2016, 2023):
    for pid, r in D[y].items():
        if rook.get(pid) != y or r['sn'] < 1:
            continue
        a = age(pid, y)
        fut = [D[z][pid] for z in (y + 1, y + 2, y + 3) if pid in D.get(z, {})]
        sn = sum(f['sn'] for f in fut)
        if a is None or sn < 100:
            continue
        R4.append({'y': y, 'pid': pid, 'r': r, 'age': a, 't': sum(f['pts'] for f in fut) / sn * 60, 'w': min(sn, 2000)})
classes = sorted({x['y'] for x in R4})
e0, e1, cls = [], [], []
for c in classes:
    tr = [x for x in R4 if x['y'] != c]
    m, _, _ = RR.means(D, [y for y in range(2016, 2026) if y != c])
    base = lambda x: (x['r']['pts'] * 60 + K[x['r']['grp']] * m.get(x['r']['sub'], 0.0)) / (x['r']['sn'] + K[x['r']['grp']])
    A = np.array([x['age'] - 22 for x in tr]); Y = np.array([x['t'] - base(x) for x in tr]); Wt = np.array([x['w'] for x in tr])
    k = float((Wt * A * (Y - np.average(Y, weights=Wt))).sum() / (Wt * A * A).sum())
    # through the base: residual on (age-22) with an intercept left in base? prereg: pXP + k (age-22), no intercept
    k = float((Wt * A * Y).sum() / (Wt * A * A).sum())
    for x in R4:
        if x['y'] == c:
            b = base(x); e0.append((x['w'], (b - x['t']) ** 2)); e1.append((x['w'], (b + k * (x['age'] - 22) - x['t']) ** 2)); cls.append((c, k))
d = np.array([b[1] - a[1] for a, b in zip(e0, e1)]); w = np.array([a[0] for a in e0])
mu = (w * d).sum() / w.sum(); var = (w * (d - mu) ** 2).sum() / w.sum(); neff = w.sum() ** 2 / (w * w).sum()
byc = {}
for (c, k), a, b in zip(cls, e0, e1):
    byc.setdefault(c, [0, 0, 0, k]); byc[c][0] += a[0] * a[1]; byc[c][1] += b[0] * b[1]; byc[c][2] += a[0]
out['N4'] = {'n': len(R4), 'wmseBase': float((w * np.array([a[1] for a in e0])).sum() / w.sum()),
             'wmseAge': float((w * np.array([b[1] for b in e1])).sum() / w.sum()), 't': float(mu / math.sqrt(var / neff)),
             'classesBetter': sum(1 for v in byc.values() if v[1] < v[0]), 'k': {c: round(v[3], 4) for c, v in byc.items()}}
print(out['N4'])
# ---------------- N5
SV = {}
for r in json.load(gzip.open(os.path.join(ROOT, 'scripts/data/sv_hist.json.gz')))['nfl']:
    if r.get('pfr'):
        SV[(r['pfr'], r['y'])] = r['tot'] / (r['pl'] + 200)
targets = RR.YEARS[:-1]
E0, E1, byS = [], [], {}
for ty in targets:
    tr = [y for y in targets if y != ty]
    m, b, xb = RR.means(D, tr); mq = RR.mslopes(D, tr, m)
    Kt = RR.fit_k(D, tr, 'marcelM', m, b, xb, mq=mq)
    num, den = defaultdict(float), defaultdict(float)
    for y, pid, t, sn in RR.pairs(D, tr):
        v = SV.get((pid, y), 0.0); g = D[y][pid]['grp']
        res = t - RR.pred(D, y, pid, 'marcelM', Kt, m, b, xb, mq=mq)
        num[g] += sn * v * res; den[g] += sn * v * v
    bg = {g: num[g] / den[g] if den[g] else 0.0 for g in num}
    s0 = s1 = ws = 0.0
    for y, pid, t, sn in RR.pairs(D, [ty]):
        p = RR.pred(D, y, pid, 'marcelM', Kt, m, b, xb, mq=mq); g = D[y][pid]['grp']
        p1 = p + bg.get(g, 0.0) * SV.get((pid, y), 0.0)
        E0.append((sn, (p - t) ** 2)); E1.append((sn, (p1 - t) ** 2)); s0 += sn * (p - t) ** 2; s1 += sn * (p1 - t) ** 2; ws += sn
    byS[ty + 1] = {'base': s0 / ws, 'sv': s1 / ws, 'b': {g: round(v, 3) for g, v in bg.items()}}
    print(ty + 1, byS[ty + 1], flush=True)
d = np.array([b[1] - a[1] for a, b in zip(E0, E1)]); w = np.array([a[0] for a in E0])
mu = (w * d).sum() / w.sum(); var = (w * (d - mu) ** 2).sum() / w.sum(); neff = w.sum() ** 2 / (w * w).sum()
out['N5'] = {'n': len(E0), 'wmseBase': float((w * np.array([a[1] for a in E0])).sum() / w.sum()),
             'wmseSV': float((w * np.array([b[1] for b in E1])).sum() / w.sum()), 't': float(mu / math.sqrt(var / neff)),
             'seasonsBetter': sum(1 for v in byS.values() if v['sv'] < v['base']), 'by': byS}
json.dump(out, open(os.path.join(os.path.dirname(__file__), 'res_rate.json'), 'w'), indent=1)
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != 'by'} for k, v in out.items()}, indent=1))
