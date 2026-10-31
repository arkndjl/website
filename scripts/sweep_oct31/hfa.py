"""Team-specific home advantage (EB-shrunk) and persistent team model bias, on every games_wf file.
x_hfa = d_H + d_A, d_T = (mean resid at home - mean resid away)/2 shrunk by k games (all earlier games, any season).
x_bias = b_H - b_A, b_T = shrunk mean team-perspective resid over earlier seasons (long memory).
walk-forward: b fit by OLS (no intercept) on all earlier seasons; k chosen on tune; held reported with tune's k."""
import gzip, json, os, sys, math
from collections import defaultdict
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H

def load(s):
    rows = json.load(gzip.open(f'{ROOT}/scripts/data/games_wf/{s}.json.gz'))
    out = []
    for r in rows:
        if s in ('nhl', 'soccer'):
            if r.get('hs') is None: continue
            hs, as_ = r['hs'], r['as']
            if s == 'nhl':
                y = 1.0 if hs > as_ else 0.0; m = r['p']; c = (r.get('c') or {}).get('p')
            else:
                y = (hs > as_) - (hs < as_); m = r['p'][0] - r['p'][2]
                c = (r['c'][0] - r['c'][2]) if r.get('c') else None
            out.append(dict(S=r['S'], day=r['day'], h=r['h'], a=r['a'], neu=0, y=y, m=m, c=c))
        else:
            if r.get('res') is None or r.get('m') is None: continue
            out.append(dict(S=r['S'], day=r['date'][:10], h=r['home'], a=r['away'], neu=r.get('neutral', 0) or 0,
                            y=r['res'], m=r['m'], c=r.get('L')))
    out.sort(key=lambda r: r['day'])
    return out

def feats(rows, k, kind):
    hs = defaultdict(lambda: [0.0, 0]); as_ = defaultdict(lambda: [0.0, 0]); bs = defaultdict(lambda: [0.0, 0])
    xs = []; pend = []; cur = None
    for r in rows:
        if r['day'] != cur:
            for (h, a, e, neu, S) in pend:
                bs[(h, S)][0] += e; bs[(h, S)][1] += 1; bs[(a, S)][0] -= e; bs[(a, S)][1] += 1
                if not neu:
                    hs[h][0] += e; hs[h][1] += 1; as_[a][0] -= e; as_[a][1] += 1
            pend = []; cur = r['day']
        if kind == 'hfa':
            def d(t):
                (sh, nh), (sa, na) = hs[t], as_[t]
                if nh == 0 or na == 0: return 0.0
                neff = nh * na / (nh + na)
                return (sh / nh - sa / na) / 2 * neff / (neff + k)
            x = 0.0 if r['neu'] else d(r['h']) + d(r['a'])
        else:  # long-memory team bias from earlier seasons, decayed by season age
            def b(t):
                s = n = 0.0
                for back in range(1, 4):
                    v = bs.get((t, r['S'] - back))
                    if v: s += v[0] * .7 ** (back - 1); n += v[1] * .7 ** (back - 1)
                return s / (n + k) if n else 0.0
            x = b(r['h']) - b(r['a'])
        xs.append(x)
        pend.append((r['h'], r['a'], r['y'] - r['m'], r['neu'], r['S']))
    return np.array(xs)

def walk(rows, x, base):  # base: 'm' or 'c'
    S = np.array([r['S'] for r in rows]); y = np.array([r['y'] for r in rows], float)
    b0 = np.array([r[base] if r[base] is not None else np.nan for r in rows], float)
    e = y - b0; pred = np.full(len(rows), np.nan)
    for s in sorted(set(S))[1:]:
        tr = (S < s) & ~np.isnan(e); te = S == s
        bb = (x[tr] @ e[tr]) / max(x[tr] @ x[tr], 1e-9)
        pred[te] = bb * x[te]
    return S, e, pred

def score(rows, x, base, seasons):
    S, e, p = walk(rows, x, base)
    days = np.array([r['day'] for r in rows])
    mk = np.isin(S, seasons) & ~np.isnan(e) & ~np.isnan(p)
    r = H.paired((e[mk] - p[mk]) ** 2, e[mk] ** 2, cluster=days[mk])
    return round(r['t'], 2), round(float(r['d']), 5), int(r['n'])

SPORTS = {'nba': ([2016, 2017, 2018, 2019, 2020], [20, 50, 100, 200, 400]),
          'nfl': ([2016, 2017, 2018, 2019, 2020], [10, 20, 40, 80, 160]),
          'cbb': ([2017, 2018, 2019, 2020], [10, 20, 40, 80, 160]),
          'cfb': ([2018, 2019, 2020, 2021], [5, 10, 20, 40, 80]),
          'nhl': ([2018, 2019, 2020, 2021, 2022, 2023], [20, 50, 100, 200, 400]),
          'soccer': ([2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022], [10, 20, 40, 80, 160])}
out = {}
for s, (tune, ks) in SPORTS.items():
    rows = load(s); allS = sorted(set(r['S'] for r in rows)); held = [q for q in allS if q > max(tune)]
    for kind in ('hfa', 'bias'):
        best = None
        for k in ks:
            x = feats(rows, k, kind); t = score(rows, x, 'm', tune)
            if best is None or t[0] < best[1][0]: best = (k, t, x)
        k, tt, x = best
        res = dict(k=k, tune=tt, held=score(rows, x, 'm', held), tune_close=score(rows, x, 'c', tune),
                   held_close=score(rows, x, 'c', held))
        out[f'{s}:{kind}'] = res
        print(s, kind, res, flush=True)
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_oct31', 'hfa.json'), 'w'), indent=1)
