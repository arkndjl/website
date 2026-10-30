#!/usr/bin/env python3
"""Does the school add to the CBB board's FV? A program development effect (research, Oct 30 2026).

    python3 scripts/cbb_careers_kit.py && python3 scripts/cbb_program_fv.py     # -> data/cbb_program_fv.json

Each program's past players' realized FV minus the shipped model's E[FV] (data/cbb_fit.json core ladders), one row
per player (his last board at the school), summed and shrunk: sum / (n + k). Built from the 2009-16 boards only
(careers done by 2020), then tested forward on the 2017-21 boards (common-horizon outcome) as an offset on every
rung (logit = shipped logit + b x z), b fit leaving one board year out. Also by whole college classes inside
2009-16 (the effect from the other classes) as a stability check. Newcomers and returners both.
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
from cbb_selfcreate_fv import offset_fit, score, topq

OUT = os.path.join(D.ROOT, 'data', 'cbb_program_fv.json')


def model_L(m, fs):
    X = np.array([[f.get(k) if f.get(k) is not None else np.nan for k in m['kept']] for f in fs], float)
    Z = np.clip(np.nan_to_num((X - np.array(m['mean'])) / np.array(m['sd'])), -4, 4)
    A = np.hstack([np.ones((len(Z), 1)), Z])
    return np.column_stack([A @ np.array(w) for w in m['w']])


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    rows = []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if s['year'] < 2009 or s['year'] > 2021:
                continue
            f = F.features(c, i)
            rows.append({'pid': c['pid'], 'year': s['year'], 'team': s['team'], 'last': c['last'], 'new': f['newcomer'],
                         'y': c['nba']['fvx'], 'yh': c['nba'].get('fvh'), 'f': f})
    for grp in ('newcomer', 'returner'):
        m = fit['models'][grp]
        F.TOP_MEAN = m['topMean']
        ix = [i for i, r in enumerate(rows) if r['new'] == (grp == 'newcomer')]
        L = model_L(m, [rows[i]['f'] for i in ix])
        E = F.expected(np.cumprod(1 / (1 + np.exp(-L)), axis=1))
        for i, l, e in zip(ix, L, E):
            rows[i]['L'] = l; rows[i]['E'] = float(e)
    # program residuals from the training boards: a player's last board at each school
    train = [r for r in rows if r['year'] in F.TRAIN and r['last'] <= 2020]
    lastb = {}
    for r in train:
        k = (r['pid'], r['team'])
        if k not in lastb or r['year'] > lastb[k]['year']:
            lastb[k] = r
    res = []
    for kk in (5.0, 15.0, 40.0):
        prog = defaultdict(lambda: [0.0, 0])
        for r in lastb.values():
            p = prog[r['team']]; p[0] += r['y'] - r['E']; p[1] += 1
        held = [r for r in rows if 2017 <= r['year'] <= 2021 and r['yh'] is not None and r['last'] > 2016]
        for grp in ('newcomer', 'returner', 'all'):
            H = [r for r in held if grp == 'all' or r['new'] == (grp == 'newcomer')]
            y = np.array([r['yh'] for r in H]); yr = np.array([r['year'] for r in H]); pid = np.array([r['pid'] for r in H])
            L = np.array([r['L'] for r in H])
            x = np.array([prog[r['team']][0] / (prog[r['team']][1] + kk) for r in H])
            on = [y >= (F.LADDER[j - 1] if j else -1) for j in range(len(F.LADDER))]
            null = []
            for j, t in enumerate(F.LADDER):
                o = (y[on[j]] >= t).astype(float); mu = o.mean()
                null.append(-(o * np.log(mu) + (1 - o) * np.log(1 - mu)).sum())
            C0 = 1 / (1 + np.exp(-L)); d0 = score(C0, y, null)
            for per in (False, True):
                C1 = np.zeros_like(C0); bs = {}
                for b in range(2017, 2022):
                    tr, te = yr != b, yr == b
                    z = (x - x[tr].mean()) / (x[tr].std() or 1)
                    bb = offset_fit(L, z, y, [o & tr for o in on], per)
                    bs[b] = [round(float(v), 3) for v in bb]
                    for j in range(len(F.LADDER)):
                        C1[te, j] = 1 / (1 + np.exp(-(L[te, j] + (bb[j] if per else bb[0]) * z[te])))
                diff = (d0 - score(C1, y, null)).sum(1)
                cl = defaultdict(float)
                for p_, v in zip(pid, diff): cl[p_] += v
                v = np.array(list(cl.values()))
                yrs = [float(diff[yr == b].sum()) for b in range(2017, 2022)]
                out = {'k': kk, 'grp': grp, 'perRung': per, 'n': len(H), 'gain': round(float(diff.sum() * 100), 3),
                       't': round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2), 'years': f"{sum(q > 0 for q in yrs)}/5",
                       'rungs': [round(float(q * 100), 3) for q in (d0 - score(C1, y, null)).sum(0)],
                       'top50': round(topq(C1, y, yr)[0] - topq(C0, y, yr)[0], 3), 'top150': round(topq(C1, y, yr, 150)[0] - topq(C0, y, yr, 150)[0], 3),
                       'coef': bs[2021]}
                print(json.dumps(out), flush=True)
                res.append(out)
    top = sorted(((v[0] / (v[1] + 15), t, v[1]) for t, v in prog.items()), reverse=True)
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'results': res,
               'programs': {'top': [(t, round(a, 2), n) for a, t, n in top[:15]], 'bottom': [(t, round(a, 2), n) for a, t, n in top[-15:]]}},
              open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
