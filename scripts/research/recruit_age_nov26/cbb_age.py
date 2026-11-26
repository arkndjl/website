#!/usr/bin/env python3
"""CBB recruit age for the class (prereg.md families A, B). python3 cbb_age.py"""
import csv, json, math, os, sys, datetime as dt
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.argv.append('--offline')
import cbb_recruit_fit as R
import names as N

def dobs():
    first = {}
    for r in csv.DictReader(open(os.path.join(R.KIT, 'kit', 'college_seasons_nba.csv'))):
        if not r['rec_class'] or not r['on3rk']: continue
        k = (int(r['rec_class']), int(float(r['on3rk']))); y = int(r['year'])
        if k not in first or y < first[k][0]: first[k] = (y, r['name'], r['dob'] or None)
    kit = {}
    for (c, rk), (y, nm, d) in first.items(): kit[(c, rk)] = kit[(c, N.key(nm))] = (nm, d)
    return kit

def agec(dob, c):
    y, m, d = int(dob[:4]), int(dob[5:7]), int(dob[8:10])
    exact = (m, d) != (10, 15)
    b = dt.date(y, m, d) if exact else dt.date(y, 7, 1)
    return (dt.date(c, 9, 1) - b).days / 365.25, exact

def main():
    H = R.history(); smap = R.slug_map(H); teams = H['teams']
    for r in H['recruits']:
        if (r.get('x') or {}).get('hs'): R.HS_BY[r['cls']][r['x']['hs']] += 1
    rows = [r for r in H['recruits'] if r['cls'] in R.TRAIN + R.FORWARD]
    kit = dobs()
    for r in rows:
        r['ts'] = float(r['rfv'] - 20)
        k = kit.get((r['cls'], r['rk']))
        if k and not N.same(k[0], r['name']): k = None
        k = k or kit.get((r['cls'], N.key(r['name'])))
        r['_a'] = agec(k[1], r['cls']) if k and k[1] else None
    F, ref = R.frame(rows, smap, teams)
    cls = np.array([r['cls'] for r in rows]); ts = np.array([r['ts'] for r in rows])
    known = np.array([r['_a'] is not None for r in rows]); exact = np.array([bool(r['_a'] and r['_a'][1]) for r in rows])
    a = np.array([r['_a'][0] if r['_a'] else np.nan for r in rows])
    tr = np.isin(cls, R.TRAIN)
    m = float(np.nanmean(a[tr]))
    print('rows', len(rows), 'known', known.sum(), 'exact', exact.sum(), 'mean agec', round(m, 3), 'sd', round(float(np.nanstd(a[tr])), 3),
          'quintiles', np.round(np.nanquantile(a[tr & exact], [.1, .2, .5, .8, .9]), 2))
    print('known by outcome: NBA', round(known[ts > 0].mean(), 3), 'not', round(known[ts == 0].mean(), 3),
          '| exact: NBA', round(exact[ts > 0].mean(), 3), 'not', round(exact[ts == 0].mean(), 3))
    for f, x, k in zip(F, a, known):
        f['agec'] = float(x) if k else m
        f['young'] = (1.0 if x <= 17.9 else 0.0) if k else None
        f['ao'] = max(0.0, x - 18.4) if k else None
        f['ay'] = max(0.0, 18.4 - x) if k else None
    for c in ('young', 'ao', 'ay'):
        mu = float(np.mean([f[c] for f, t in zip(F, tr) if t and f[c] is not None]))
        for f in F:
            if f[c] is None: f[c] = mu
    # raw rates
    bins = []
    for lo, hi in ((0, 17.9), (17.9, 18.2), (18.2, 18.6), (18.6, 19.0), (19.0, 30)):
        s = tr & exact & (a > lo) & (a <= hi)
        print(f'  agec {lo}-{hi}: n {s.sum()}, mean rank {np.mean([rows[i]["rk"] or 400 for i in np.where(s)[0]]):.0f}, NBA {np.mean(ts[s] > 0):.3f}, FV {20 + ts[s].mean():.1f}')
        bins.append({'lo': lo, 'hi': hi, 'n': int(s.sum()), 'rank': round(float(np.mean([rows[i]["rk"] or 400 for i in np.where(s)[0]]))), 'nba': round(float(np.mean(ts[s] > 0)), 3), 'fv': round(20 + float(ts[s].mean()), 1)})
    out = {'bins': bins, 'median': round(float(np.nanmedian(a[tr & exact])), 2), 'n_exact': int((tr & exact).sum())}
    def run(tag, cp, cv_, base=(['lrk', 'old'], ['lrk']), mask=None, part='p'):
        res = {}
        for name, sel, folds in (('train', tr, R.TRAIN), ('fwd', ~tr, R.FORWARD)):
            if name == 'fwd':
                # forward: fit on train, score 2017-18
                mk = tr if mask is None else tr & mask
                Ft = [F[i] for i in np.where(mk)[0]]
                te = ~tr if mask is None else ~tr & mask
                Fe = [F[i] for i in np.where(te)[0]]
                L = []
                for cpx, cvx in (base, (cp, cv_)):
                    M = R.Hurdle(cpx, cvx).fit(Ft, ts[mk]); p, mu = M.parts(Fe)
                    y = (ts[te] > 0).astype(float); p = np.clip(p, 1e-6, 1 - 1e-6)
                    L.append(-(y * np.log(p) + (1 - y) * np.log(1 - p)) if part == 'p' else np.where(y > 0, (np.log(np.where(y > 0, ts[te], 1)) - mu) ** 2, 0))
                d = L[1] - L[0]; n = len(d) if part == 'p' else int((ts[te] > 0).sum())
                dd = d if part == 'p' else d[ts[te] > 0]
                res['fwd'] = {'gain': round(float(-dd.mean()), 5), 't': round(float(-dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2), 'n': n}
                continue
            mk = sel if mask is None else sel & mask
            Fs = [F[i] for i in np.where(mk)[0]]; t_, c_ = ts[mk], cls[mk]
            y = (t_ > 0).astype(float); pos = t_ > 0; lts = np.log(np.where(pos, t_, 1))
            L = []
            for cpx, cvx in (base, (cp, cv_)):
                P, MU, _ = R.cv(Fs, t_, c_, cpx, cvx, folds); P = np.clip(P, 1e-6, 1 - 1e-6)
                L.append(-(y * np.log(P) + (1 - y) * np.log(1 - P)) if part == 'p' else np.where(pos, (lts - MU) ** 2, 0.0))
            d, t, w = R.paired(L[1], L[0], c_, folds)
            res['train'] = {'gain': round(-d, 5), 't': round(-t, 2), 'classes': w, 'n': int(mk.sum())}
        out[tag] = res
        print(tag, res)
    run('A0 old vs rank only', ['lrk', 'old'], ['lrk'], base=(['lrk'], ['lrk']))
    run('A1 swap old -> agec', ['lrk', 'agec'], ['lrk'])
    run('A2 add agec', ['lrk', 'old', 'agec'], ['lrk'])
    run('A3 add young', ['lrk', 'old', 'young'], ['lrk'])
    run('A4 hinges for old', ['lrk', 'ao', 'ay'], ['lrk'])
    run('A1k swap, known only', ['lrk', 'agec'], ['lrk'], mask=known)
    run('A2k add, known only', ['lrk', 'old', 'agec'], ['lrk'], mask=known)
    run('A3k young, known only', ['lrk', 'old', 'young'], ['lrk'], mask=known)
    run('A1e swap, exact only', ['lrk', 'agec'], ['lrk'], mask=exact)
    run('A2e add, exact only', ['lrk', 'old', 'agec'], ['lrk'], mask=exact)
    run('A0e agec vs rank, exact only', ['lrk', 'agec'], ['lrk'], base=(['lrk'], ['lrk']), mask=exact)
    run('B1 value + agec', ['lrk', 'old'], ['lrk', 'agec'], part='v')
    run('B2 value + old', ['lrk', 'old'], ['lrk', 'old'], part='v')
    run('B1e value + agec, exact', ['lrk', 'old'], ['lrk', 'agec'], part='v', mask=exact)
    # coefficient of agec in the full-train swap fit
    M = R.Hurdle(['lrk', 'agec'], ['lrk', 'agec']).fit([F[i] for i in np.where(tr)[0]], ts[tr])
    print('coef per SD: P', np.round(M.bp, 3), 'sd agec', np.round(M.sp, 3), 'value', np.round(M.bv, 3))
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cbb_age.json'), 'w'), indent=1)

main()
