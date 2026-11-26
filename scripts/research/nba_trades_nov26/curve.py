"""NBA pick value curve from draft-night pick-for-pick deals (deals.py), held out by draft.
v(pick) = exp(-a (pick - 1)^b); a future first = F1, a future second = F2, cash = Cc (in #1-pick units).
Fit: least squares on ln(value one side gets / value the other gets) over two-team pure-pick deals.
Baselines: the NFL Massey-Thaler curve the CFB/NFL mock uses (a .148, b .698, futures at .48 of a mid-round pick)."""
import json, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse as PA
D = [d for d in json.load(open(os.path.join(PA.C, 'deals.json')))
     if all(sd['cur'] or sd['f1'] or sd['f2'] or sd['cash'] for sd in d['sides'].values())]
FORM = os.environ.get('FORM', 'power')


def v(p, a, b, form=None):
    if (form or FORM) == 'power': return ((p + a) / (1 + a)) ** -b     # a = offset, b = decay
    return math.exp(-a * (p - 1) ** b)


def val(side, th):
    a, b, F1, F2, Cc = th[:5]
    form = th[5] if len(th) > 5 else FORM
    return sum(v(p, a, b, form) for p in side['cur']) + side['f1'] * F1 + side['f2'] * F2 + (Cc if side['cash'] else 0)


def resid(d, th):
    A, B = d['sides'].values()
    va, vb = val(A, th), val(B, th)
    if va <= 0 or vb <= 0: return None
    return math.log(va / vb)


def loss(x, deals, fix=None):
    th = unpack(x, fix)
    r = [resid(d, th) for d in deals]
    return sum(z * z for z in r if z is not None) + 50 * sum(z is None for z in r)


def unpack(x, fix=None):
    a, b = (math.exp(x[0]), math.exp(x[1])) if fix is None else fix
    k = 0 if fix else 2
    return (a, b, math.exp(x[k]), math.exp(x[k + 1]), math.exp(x[k + 2]), FORM if fix is None else 'mt')


def nelder(f, x0, it=4000, step=0.3):
    n = len(x0); X = [np.array(x0, float)] + [np.array(x0, float) + step * np.eye(n)[i] for i in range(n)]
    F = [f(x) for x in X]
    for _ in range(it):
        o = np.argsort(F); X = [X[i] for i in o]; F = [F[i] for i in o]
        if F[-1] - F[0] < 1e-10: break
        c = np.mean(X[:-1], axis=0); xr = c + (c - X[-1]); fr = f(xr)
        if fr < F[0]:
            xe = c + 2 * (c - X[-1]); fe = f(xe)
            X[-1], F[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < F[-2]: X[-1], F[-1] = xr, fr
        else:
            xc = c + 0.5 * (X[-1] - c); fc = f(xc)
            if fc < F[-1]: X[-1], F[-1] = xc, fc
            else:
                X = [X[0]] + [X[0] + 0.5 * (x - X[0]) for x in X[1:]]; F = [F[0]] + [f(x) for x in X[1:]]
    return X[int(np.argmin(F))]


def fit(deals, fix=None):
    x0 = (([math.log(2), math.log(1.2)] if FORM == 'power' else [math.log(.15), math.log(.7)]) if fix is None else []) + [math.log(.3), math.log(.03), math.log(.02)]
    best = None
    for st in (0.3, 0.8):
        x = nelder(lambda z: loss(z, deals, fix), x0, step=st)
        x = nelder(lambda z: loss(z, deals, fix), x, step=0.1)
        L = loss(x, deals, fix)
        if best is None or L < best[0]: best = (L, x)
    return unpack(best[1], fix)


MT = (0.148, 0.698)
MT_FULL = MT + (0.48 * math.exp(-.148 * 14.5 ** .698), 0.48 * math.exp(-.148 * 44.5 ** .698), math.exp(-.148 * 54 ** .698), 'mt')

if __name__ == '__main__':
    yrs = sorted({d['y'] for d in D})
    full = fit(D)
    print('full fit a %.3f b %.3f F1 %.3f F2 %.4f cash %.4f' % full[:5])
    print('n', len(D), FORM, 'v(1,3,5,10,14,20,30,31,45,60):', [round(v(p, full[0], full[1]), 3) for p in (1, 3, 5, 10, 14, 20, 30, 31, 45, 60)])
    E = {'nba': [], 'mt_fixed': [], 'mt_refit_futures': []}
    per = []
    for y in yrs:
        tr = [d for d in D if d['y'] != y]; te = [d for d in D if d['y'] == y]
        th = fit(tr); thm = fit(tr, MT)
        e = [abs(resid(d, th)) for d in te]; m = [abs(resid(d, MT_FULL)) for d in te]; mr = [abs(resid(d, thm)) for d in te]
        E['nba'] += e; E['mt_fixed'] += m; E['mt_refit_futures'] += mr
        per.append((y, len(te), np.mean(e), np.mean(m), np.mean(mr)))
    for p in per: print('%d n%2d  nba %.3f  MT %.3f  MT+refit futures %.3f' % p)
    dn = np.array(E['nba']) - np.array(E['mt_fixed']); dr = np.array(E['nba']) - np.array(E['mt_refit_futures'])
    def cl(dif):   # t clustered by draft
        g = {}
        i = 0
        for y in yrs:
            n = sum(1 for d in D if d['y'] == y); g[y] = dif[i:i + n].sum(); i += n
        v = np.array(list(g.values())); return dif.mean() / (np.sqrt(len(v)) * v.std(ddof=1) / len(dif)) if len(v) > 1 else 0
    out = dict(n=len(D), drafts=[yrs[0], yrs[-1]], fit=dict(zip(['a', 'b', 'F1', 'F2', 'cash'], [round(x, 4) for x in full[:5]])),
               held=dict(nba=round(float(np.mean(E['nba'])), 3), mt=round(float(np.mean(E['mt_fixed'])), 3), mtRefit=round(float(np.mean(E['mt_refit_futures'])), 3),
                         tVsMt=round(float(cl(dn)), 2), tVsMtRefit=round(float(cl(dr)), 2),
                         draftsBetter=int(sum(p[2] < p[3] for p in per)), draftsBetterRefit=int(sum(p[2] < p[4] for p in per)), of=len(per)))
    print(json.dumps(out, indent=1))
    json.dump(out, open(os.path.join(PA.C, 'curve.json'), 'w'))


def subset_check():
    yrs = sorted({d['y'] for d in D})
    sw = lambda d: all(s['cur'] for s in d['sides'].values())
    e, m = [], []
    for y in yrs:
        th = fit([d for d in D if d['y'] != y])
        for d in D:
            if d['y'] == y and sw(d): e.append(abs(resid(d, th))); m.append(abs(resid(d, MT_FULL)))
    e, m = np.array(e), np.array(m)
    dd = e - m
    print('pick-for-pick swaps n', len(e), 'nba %.3f MT %.3f  t %.2f  better in %d' % (e.mean(), m.mean(), dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd))), (dd < 0).sum()))
    return dict(n=len(e), nba=round(float(e.mean()), 3), mt=round(float(m.mean()), 3), t=round(float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2))


if __name__ == '__main__' and os.environ.get('SUB'):
    subset_check()
