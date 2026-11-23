#!/usr/bin/env python3
"""C1 (prereg.md): CFB predictive season value pSV a play, Marcel shrink vs raw, leave one target season out."""
import gzip, json, math, os
from collections import defaultdict
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
rows = [r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts/data/sv_hist.json.gz')))['cfb'] if r['g'] in ('QB', 'RB') and r['pl'] > 0]
D = defaultdict(dict)
for r in rows:
    D[r['y']][r['id']] = r
YS = sorted(D); KS = (50, 100, 200, 300, 450, 650, 900, 1300, 1800, 2600, 3600); W = (1, .7, .5)
rate = lambda r: r['tot'] / r['pl']
def pairs(ys):
    for y in ys:
        for pid, r in D[y].items():
            n = D.get(y + 1, {}).get(pid)
            if n and n['pl'] >= 100 and n['g'] == r['g']:
                yield y, pid, rate(n), n['pl']
def means(ys):
    a = defaultdict(lambda: [0.0, 0.0])
    for y in ys:
        for r in D[y].values():
            a[r['g']][0] += r['tot']; a[r['g']][1] += r['pl']
    return {g: v[0] / v[1] for g, v in a.items()}
def pred(y, pid, form, K, m):
    r = D[y][pid]; g = r['g']
    if form == 'raw':
        return rate(r)
    P = S = 0.0
    for i, w in enumerate(W if form == 'marcel' else (1,)):
        h = D.get(y - i, {}).get(pid)
        if h and h['g'] == g:
            P += w * h['tot']; S += w * h['pl']
    return (P + K[g] * m[g]) / (S + K[g])
def sse(ys, form, K, m, g=None):
    s = w = 0.0
    for y, pid, t, n in pairs(ys):
        if g and D[y][pid]['g'] != g:
            continue
        e = pred(y, pid, form, K, m) - t; s += n * e * e; w += n
    return s / w
targets = [y for y in YS if y + 1 in D and y >= 2015]   # targets y+1 = 2016-25
err = {f: [] for f in ('raw', 'shrink1', 'marcel')}; by = {f: {} for f in err}; chosen = {}
for ty in targets:
    tr = [y for y in targets if y != ty]
    m = means(tr)
    for f in err:
        K = {'QB': 0, 'RB': 0}
        if f != 'raw':
            for g in K:
                K[g] = min(KS, key=lambda k: sse(tr, f, {**K, g: k}, m, g))
        chosen.setdefault(ty, {})[f] = K
        s = w = 0.0
        for y, pid, t, n in pairs([ty]):
            e = pred(y, pid, f, K, m) - t; err[f].append((n, e * e, pred(y, pid, f, K, m), t)); s += n * e * e; w += n
        by[f][ty + 1] = s / w
def paired(f, g):
    d = [(a[0], a[1] - b[1]) for a, b in zip(err[f], err[g])]
    Wt = sum(x for x, _ in d); mu = sum(x * v for x, v in d) / Wt
    var = sum(x * (v - mu) ** 2 for x, v in d) / Wt; neff = Wt ** 2 / sum(x * x for x, _ in d)
    return round(mu / math.sqrt(var / neff), 2), sum(1 for y in by[f] if by[f][y] < by[g][y])
P = err['marcel']; Wt = sum(p[0] for p in P)
mx = sum(p[0] * p[2] for p in P) / Wt; my = sum(p[0] * p[3] for p in P) / Wt
slope = sum(p[0] * (p[2] - mx) * (p[3] - my) for p in P) / sum(p[0] * (p[2] - mx) ** 2 for p in P)
# year-to-year r of the raw rate (100+ plays both seasons)
xy = [(rate(D[y][pid]), t) for y, pid, t, n in pairs(targets) if D[y][pid]['pl'] >= 100]
def corr(xy):
    n = len(xy); ax = sum(x for x, _ in xy) / n; ay = sum(y for _, y in xy) / n
    sxy = sum((x - ax) * (y - ay) for x, y in xy); sx = math.sqrt(sum((x - ax) ** 2 for x, _ in xy)); sy = math.sqrt(sum((y - ay) ** 2 for _, y in xy))
    return sxy / sx / sy
xyM = []
for ty in targets:
    m = means([y for y in targets if y != ty])
    xyM += [(pred(y, pid, 'marcel', chosen[ty]['marcel'], m), t) for y, pid, t, n in pairs([ty]) if D[y][pid]['pl'] >= 100]
out = {'n': len(err['raw']), 'wmse': {f: round(sum(a * b for a, b, *_ in e) / sum(a for a, *_ in e), 6) for f, e in err.items()},
       'marcelVsRaw': paired('marcel', 'raw'), 'shrink1VsRaw': paired('shrink1', 'raw'), 'marcelVsShrink1': paired('marcel', 'shrink1'),
       'slope': round(slope, 3), 'yoyRaw': round(corr(xy), 3), 'rMarcelNext': round(corr(xyM), 3),
       'K': chosen[targets[-1]], 'by': {f: {str(k): round(v, 6) for k, v in b.items()} for f, b in by.items()}}
json.dump(out, open(os.path.join(os.path.dirname(__file__), 'res_cfb_psv.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
