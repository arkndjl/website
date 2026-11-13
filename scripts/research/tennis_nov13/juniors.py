#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Family P (prereg-fv.md): junior Grand Slam singles champions as a prospect FV input."""
import sys, os, re, json, math, pickle, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import numpy as np, pandas as pd
from scipy import stats
import tennis_prospects as T
import names
HERE = os.path.dirname(os.path.abspath(__file__))
SLAM = [(1, 31), (6, 10), (7, 14), (9, 12)]

def champions(path):
    """[(year, slam index, name, IOC)] from the list's wikitext"""
    w = json.load(open(path))['parse']['wikitext']['*']
    out = []
    for row in re.split(r'\n\|-', w):
        m = re.match(r'\s*\n?\|\s*(\d{4})\s*\|\|(.*)', row.strip(), re.S)
        if not m: continue
        y = int(m.group(1))
        cells = re.split(r'\|\|', m.group(2))
        for i, c in enumerate(cells[:4]):
            f = re.search(r'\{\{flagicon\|([A-Za-z]{3})[^}]*\}\}', c)
            n = re.search(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', c)
            nm = (n.group(2) or n.group(1)) if n else re.sub(r'\{\{[^}]*\}\}', '', c).strip(" '\n")
            nm = re.sub(r'\s*\(.*?\)', '', nm).strip()
            if nm and f and 'not played' not in c and 'n/a' not in c: out.append((y, i, nm, f.group(1).upper()))
    return out

def match(ch, P):
    """champion -> pid: name key + born 13-19 years before the title"""
    idx = {}
    for pid, r in P.iterrows():
        k = names.key(f"{r['first']} {r['last']}")
        idx.setdefault(k, []).append((pid, r.dobd))
        k2 = names.key(f"{r['last']} {r['first']}")
        idx.setdefault(k2, []).append((pid, r.dobd))
    out, miss = [], []
    for y, i, nm, ioc in ch:
        d = pd.Timestamp(y, *SLAM[i])
        c = [(pid, dob) for pid, dob in idx.get(names.key(nm), []) if pd.notna(dob) and 13 <= (d - dob).days / 365.25 < 19.6]
        c = list({p for p, _ in c})
        if len(c) == 1: out.append((c[0], d))
        else: miss.append((y, i, nm, ioc, len(c)))
    return out, miss

if __name__ == '__main__':
    rows = pickle.load(open(T.ROWS, 'rb')); B = T.base()
    fit = json.load(open(T.FIT))
    snap = '%02d-%02d' % T.SEL_SNAP
    res = {}
    for tour, f in (('atp', '/tmp/wiki_boys.json'), ('wta', '/tmp/wiki_girls.json')):
        ch = champions(f)
        got, miss = match(ch, B[tour]['P'])
        print(tour, 'champion slots', len(ch), 'matched', len(got), 'unmatched', len(miss), [m for m in miss if 1993 <= m[0] <= 2016][:12])
        first = {}
        for pid, d in got: first[pid] = min(d, first.get(pid, d))
        X, F, y, pos, by = T.snap_rows(rows, tour, snap)
        D = pd.to_datetime([T.snapdate(s, T.SEL_SNAP) for s in X.season.values]) if hasattr(T, 'snapdate') else None
        jg = np.array([1.0 if (p in first and first[p] <= d - pd.Timedelta(days=7)) else 0.0 for p, d in zip(X.pid.values, D)])
        F = F.assign(jgs=jg)
        kept = fit[tour]['kept']
        season = X.season.values
        print(tour, 'rows', len(F), 'jgs rows', int(jg.sum()), 'players', len(set(X.pid.values[jg > 0])), 'mean FV of jgs rows', round(float(y[jg > 0].mean()), 1), 'others', round(float(y[jg == 0].mean()), 1))
        p0 = T.loso(F, y, pos, by, kept)[2]; p1 = T.loso(F, y, pos, by, kept + ['jgs'])[2]
        g = T.fold_mse(p0, y, by) - T.fold_mse(p1, y, by)
        t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))
        t50 = lambda p, yy=y, ss=season: float(pd.Series(yy[np.argsort(-p)]).groupby(ss[np.argsort(-p)]).head(50).mean())
        tr, te = by <= T.FWD, by > T.FWD
        fw = []
        for cols in (kept, kept + ['jgs']):
            bl, bo = T.hurdle(F, y, pos, cols, tr); pp, mu = T.hpred(F[te], cols, bl, bo); fw.append((1 - pp) * 20 + pp * mu)
        yt, st = y[te], season[te]
        bl, bo = T.hurdle(F, y, pos, kept + ['jgs'], np.ones(len(y), bool))
        res[tour] = dict(n=len(F), jgs_rows=int(jg.sum()), mse=[round(float(np.mean((p0 - y) ** 2)), 3), round(float(np.mean((p1 - y) ** 2)), 3)],
                         gain=round(float(g.mean()), 4), t=round(float(t), 2), p1=float(stats.t.sf(t, len(g) - 1)), wins=int((g > 0).sum()), of=len(g),
                         top50=[round(t50(p0), 2), round(t50(p1), 2)],
                         fwd=[round(float(np.mean((fw[0] - yt) ** 2)), 3), round(float(np.mean((fw[1] - yt) ** 2)), 3)],
                         fwd_top50=[round(t50(fw[0], yt, st), 2), round(t50(fw[1], yt, st), 2)],
                         coef_logit=round(float(bl[-1]), 3), coef_mu=round(float(bo[-1]), 2),
                         jgs_resid=round(float((y - p0)[jg > 0].mean()), 2))
        print(tour, res[tour], flush=True)
    ps = sorted((res[t]['p1'], t) for t in res)
    for i, (p, t) in enumerate(ps):
        res[t]['holm_p'] = round(min(1.0, (2 - i) * p), 4)
        r = res[t]
        r['pass'] = bool(r['t'] >= 2 and r['wins'] >= 13 and r['holm_p'] < .05 and r['top50'][1] >= r['top50'][0] and r['fwd'][1] <= r['fwd'][0] and r['fwd_top50'][1] >= r['fwd_top50'][0])
        print(t, 'holm', r['holm_p'], 'PASS' if r['pass'] else 'fail')
    json.dump(res, open(os.path.join(HERE, 'p_results.json'), 'w'), indent=1)
