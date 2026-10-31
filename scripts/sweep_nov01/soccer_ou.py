"""Soccer market rating from the closing 1X2 AND the closing over/under 2.5 (Nov 1 2026 sweep).
add_market() solves each earlier match's (lambda_h, lambda_a) from the 1X2 alone, which pins the goal gap but only
weakly the total. Here the O/U 2.5 close (Pinnacle -> Betfair -> average) joins the solve at weight w:
argmin (W-pw)^2 + (L-pl)^2 + w (O-po)^2. Walk-forward log loss on the shipped params (tune 2013-22, held 2023+)."""
import math, os, sys, json, time
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import soccer_games as G
import soccer_data as D
ROOT = os.path.dirname(HERE)

def ou_probs(r):
    for k in ('ouc', 'oubc', 'ouac'):
        p = G.novig(r.get(k))
        if p:
            return p[0]
    return None

def grid(rho):
    ls = np.arange(0.15, 4.01, 0.05)
    out = []
    for lh in ls:
        for la in ls:
            pw, pd, pl = G.wdl(lh, la, rho)
            ph, pa = G.pois(lh), G.pois(la)
            # P(total <= 2) with the Dixon-Coles low-score corrections
            u = sum(ph[i] * pa[j] for i in range(3) for j in range(3) if i + j <= 2)
            u += ph[0] * pa[0] * (-lh * la * rho) + ph[1] * pa[0] * (la * rho) + ph[0] * pa[1] * (lh * rho) + ph[1] * pa[1] * (-rho)
            out.append((lh, la, pw, pl, 1 - u))
    return np.array(out)

def add_market_ou(rows, w, rho=-0.04):
    g = grid(rho)
    gh, ga, W, L, O = g.T
    for r in rows:
        if r.get('hst') is not None and r.get('ast') is not None:
            r['hsg'], r['asg'] = 0.3 * r['hst'], 0.3 * r['ast']
    for src, (oh, oa) in ((G.close_probs, ('mh', 'ma')), (lambda r: G.novig(r.get('nc')), ('nh', 'na'))):
        todo = [(r, p, ou_probs(r) if oh == 'mh' else None) for r in rows if r.get(oh) is None for p in [src(r)] if p]
        for i in range(0, len(todo), 2000):
            ch = todo[i:i + 2000]
            pw = np.array([p[0] for _, p, _ in ch])[:, None]; pl = np.array([p[2] for _, p, _ in ch])[:, None]
            po = np.array([o if o is not None else np.nan for _, _, o in ch])[:, None]
            d = (W[None, :] - pw) ** 2 + (L[None, :] - pl) ** 2
            has = ~np.isnan(po[:, 0])
            d[has] += w * (O[None, :] - po[has]) ** 2
            k = np.argmin(d, axis=1)
            for (r, _, _), kk in zip(ch, k):
                r[oh], r[oa] = round(float(gh[kk]), 3), round(float(ga[kk]), 3)
    return rows

if __name__ == '__main__':
    P = G.params()
    base = D.load(G.HIST)
    out = {}
    for w in [float(x) for x in (sys.argv[1:] or ['0', '1', '4'])]:
        t0 = time.time()
        rows = G.add_inj(G.add_mv(add_market_ou([dict(r) for r in base], w)))
        a, ga, na = G.evaluate(rows, P)
        b, gb, nb = G.evaluate(rows, P, lo=G.HOLD_FROM, hi=2100)
        out[w] = dict(tune=a, hold=b, tuneBy=ga, holdBy=gb, n=[na, nb])
        print(w, round(a, 5), round(b, 5), ga, gb, round(time.time() - t0), flush=True)
    json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'soccer_ou_grid.json'), 'w'), indent=1)
