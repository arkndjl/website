#!/usr/bin/env python3
"""Does self-created scoring add to the CBB board's FV model? (research, Oct 30 2026)

    python3 scripts/cbb_careers_kit.py && python3 scripts/cbb_selfcreate.py
    python3 scripts/cbb_selfcreate_fv.py          # -> data/cbb_selfcreate_fv.json

Returner boards 2015-21 (play-by-play covers the 2014-20 seasons before them), outcome = the common-horizon FV (best
3 of the first six NBA seasons, cbb_fit.horizon_fv). Base = the shipped returner ladder (data/cbb_fit.json, fit on
the 2009-16 boards). A candidate enters as an offset model: logit of each rung = shipped logit + b x z(candidate),
b fit leaving one board year out (one b for every rung, and a per-rung version). Scored as cbb_fit selects: rung
deviance / null, each rung equal; player-clustered t; and the top of each board (realized FV of the top 50 by E[FV]).
2015-16 boards are inside the shipped fit's training years, so 2017-21 (base fully out of sample) is reported apart.
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D.ROOT, 'data', 'cbb_selfcreate_fv.json')
YEARS = range(2015, 2022)


def cand(sc, mpt, ft):
    """candidate values from last season's counts"""
    m = max(mpt, 1.0)
    sh = lambda v, mu, n0: (v + mu * n0) / (m + n0) * 40     # per 40, shrunk to mu (a 40) with n0 minutes
    ua = sc['rim_u'] + sc['mid_u'] + sc['tp_u']
    a = sc['rim_a'] + sc['mid_a'] + sc['tp_a']
    out = {
        'ua40': sh(ua, 1.8 / 40, 300),
        'uarim40': sh(sc['rim_u'], 0.7 / 40, 300),
        'uamid40': sh(sc['mid_u'], 0.6 / 40, 300),
        'uatp40': sh(sc['tp_u'], 0.3 / 40, 300),
        'uashr': (ua + 0.45 * 20) / (ua + a + 20),
        'arim40': sh(sc['rim_a'], 1.2 / 40, 300),
        'put40': sh(sc['rim_p'] + sc['mid_p'], 0.3 / 40, 300),
        'uatpshr': (sc['tp_u'] + 0.1 * 10) / (sc['tp_u'] + sc['tp_a'] + 10),
    }
    return out


CANDS = ['ua40', 'uarim40', 'uamid40', 'uatp40', 'uashr', 'arim40', 'put40', 'uatpshr']


def logit(p): p = np.clip(p, 1e-6, 1 - 1e-6); return np.log(p / (1 - p))


def offset_fit(L, z, y, rows_on, per_rung, lam=1.0):
    """b (one or per rung) for logit = L + b z, Newton with a ridge; per_rung 'r0': the P(NBA) rung only"""
    if per_rung == 'r0':
        b = offset_fit(L[:, :1], z, y, rows_on[:1], False, lam)
        return np.array([b[0], 0.0, 0.0, 0.0])
    J = L.shape[1]
    b = np.zeros(J if per_rung else 1)
    for _ in range(25):
        g = np.zeros_like(b); h = np.zeros_like(b) + lam
        for j in range(J):
            on = rows_on[j]
            bj = b[j] if per_rung else b[0]
            p = 1 / (1 + np.exp(-(L[on, j] + bj * z[on])))
            o = (y[on] >= F.LADDER[j]).astype(float)
            q = j if per_rung else 0
            g[q] += ((o - p) * z[on]).sum(); h[q] += (p * (1 - p) * z[on] ** 2).sum()
        g -= lam * b
        b = b + g / h
    return b


def score(C, y, null):
    """per-row deviance share (rows x rungs) as cbb_fv_drivers.row_dev, from conditional rung probabilities C"""
    out = np.zeros((len(y), len(F.LADDER)))
    for j, t in enumerate(F.LADDER):
        on = y >= (F.LADDER[j - 1] if j else -1)
        c = np.clip(C[on, j], 1e-6, 1 - 1e-6); o = (y[on] >= t).astype(float)
        out[on, j] = -(o * np.log(c) + (1 - o) * np.log(1 - c)) / (null[j] * len(F.LADDER))
    return out


def topq(C, y, yr, N=50):
    P = np.cumprod(C, axis=1)
    e = F.expected(P)
    return float(np.mean([y[i] for b in sorted(set(yr)) for i in np.where(yr == b)[0][np.argsort(-e[yr == b])[:N]]])), e


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    sc = json.load(open(os.path.join(D.CACHE, 'selfcreate.json')))['rows']
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    fit = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    m = fit['models']['returner']
    F.TOP_MEAN = m['topMean']
    rows = []
    for c in careers:
        if c['nba'].get('fvh') is None:
            continue
        for i, s in enumerate(c['seasons']):
            if s['year'] not in YEARS or i == 0:
                continue
            p = c['seasons'][i - 1]
            if p['year'] != s['year'] - 1:
                continue
            k = f"{c['pid']}|{p['year']}"
            mpt = (p['mp'] or 0) * (p['gp'] or 0)
            if k not in sc or mpt < 100:
                continue
            f = F.features(c, i)
            f.update(cand(sc[k], mpt, f.get('ft')))
            rows.append({'pid': c['pid'], 'year': s['year'], 'y': c['nba']['fvh'], 'f': f})
    print(len(rows), 'rows;', sum(r['y'] >= 30 for r in rows), 'NBA', flush=True)
    y = np.array([r['y'] for r in rows]); yr = np.array([r['year'] for r in rows]); pid = [r['pid'] for r in rows]
    X = np.array([[r['f'].get(k) if r['f'].get(k) is not None else np.nan for k in m['kept']] for r in rows], float)
    Z = np.clip(np.nan_to_num((X - np.array(m['mean'])) / np.array(m['sd'])), -4, 4)
    A = np.hstack([np.ones((len(Z), 1)), Z])
    L = np.column_stack([A @ np.array(w) for w in m['w']])
    C0 = 1 / (1 + np.exp(-L))
    on = [y >= (F.LADDER[j - 1] if j else -1) for j in range(len(F.LADDER))]
    null = []
    for j, t in enumerate(F.LADDER):
        o = (y[on[j]] >= t).astype(float); mu = o.mean()
        null.append(-(o * np.log(mu) + (1 - o) * np.log(1 - mu)).sum())
    d0 = score(C0, y, null)
    top0, e0 = topq(C0, y, yr)
    held = yr >= 2017
    # how well does the shipped core already read these boards (corr of E[FV] with the outcome in each board's top 300)
    base = {'rows': len(rows), 'top50': round(top0, 3), 'top50Held': round(topq(C0[held], y[held], yr[held])[0], 3)}
    print('base', base, flush=True)
    res = []
    # usage as a yardstick (it passed this rung before and failed the top), and each candidate net of usage
    U = np.array([[r['f'].get('usg') or 20.0, 1.0] for r in rows])
    for r in rows:
        r['f']['usg_'] = r['f'].get('usg') or 20.0
    for cn in CANDS:
        x = np.array([r['f'][cn] for r in rows])
        bu = np.linalg.lstsq(U, x, rcond=None)[0]
        for r, v in zip(rows, x - U @ bu):
            r['f'][cn + '_nu'] = float(v)
    for cn in ['usg_'] + CANDS + [c + '_nu' for c in CANDS]:
        x = np.array([r['f'][cn] for r in rows])
        for per in (False, True, 'r0'):
            C1 = np.zeros_like(C0)
            bs = {}
            for b in YEARS:
                tr, te = yr != b, yr == b
                mu, sd = x[tr].mean(), x[tr].std()
                z = (x - mu) / sd
                trn = [o & tr for o in on]
                bb = offset_fit(L, z, y, trn, per)
                bs[b] = [round(float(v), 3) for v in bb]
                for j in range(len(F.LADDER)):
                    C1[te, j] = 1 / (1 + np.exp(-(L[te, j] + (bb[j] if per else bb[0]) * z[te])))
            d1 = score(C1, y, null)
            diff = (d0 - d1).sum(1)
            out = {'cand': cn, 'perRung': per, 'coefByYear': bs}
            for nm, k in (('all', np.ones(len(y), bool)), ('held', held)):
                cl = defaultdict(float)
                for p_, v in zip(np.array(pid)[k], diff[k]): cl[p_] += v
                v = np.array(list(cl.values()))
                yrs = [float(diff[k & (yr == b)].sum()) for b in YEARS if (k & (yr == b)).any()]
                out[nm] = {'gain': round(float(diff[k].sum() * 100), 3), 't': round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2),
                           'years': f"{sum(1 for q in yrs if q > 0)}/{len(yrs)}", 'rungs': [round(float(q * 100), 3) for q in (d0 - d1)[k].sum(0)],
                           'top50': round(topq(C1[k], y[k], yr[k])[0], 3),
                           'top50Years': f"{sum(1 for b in YEARS if (k & (yr == b)).any() and topq(C1[k & (yr == b)], y[k & (yr == b)], yr[k & (yr == b)])[0] > topq(C0[k & (yr == b)], y[k & (yr == b)], yr[k & (yr == b)])[0])}/{len({b for b in yr[k]})}",
                           'top150': round(topq(C1[k], y[k], yr[k], 150)[0] - topq(C0[k], y[k], yr[k], 150)[0], 3),
                           'auc': round(F.auc(np.cumprod(C1[k], 1)[:, 0], y[k] >= 30) - F.auc(np.cumprod(C0[k], 1)[:, 0], y[k] >= 30), 4)}
            print(json.dumps(out), flush=True)
            res.append(out)
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'base': base, 'results': res}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
