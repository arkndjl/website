"""Functional forms for the QB top-end lift, each held out by draft class, predictions capped at 80 (the outcome max)."""
import runpy, numpy as np, io, contextlib
with contextlib.redirect_stdout(io.StringIO()): G = runpy.run_path('/mnt/project-files/fv/qb-topend-nov01/qb_topend.py')
R = G['R']
FORMS = {'hinge': lambda x, K: max(0, x - K), 'ramp5': lambda x, K: min(1, max(0, (x - K) / 5)), 'ramp10': lambda x, K: min(1, max(0, (x - K) / 10))}
def run(S, f, K):
    e0, e1, bs, per, cl = [], [], [], [], []
    for c in sorted({r['cls'] for r in S}):
        tr = [r for r in S if r['cls'] != c]; te = [r for r in S if r['cls'] == c]
        h = np.array([f(r['fvx'], K) for r in tr]); y = np.array([r['out'] - r['fvx'] for r in tr])
        b = float(h @ y / (h @ h)) if h @ h > 0 else 0.0; bs.append(b)
        a0 = [(r['out'] - r['fvx']) ** 2 for r in te]; a1 = [(r['out'] - min(80, r['fvx'] + b * f(r['fvx'], K))) ** 2 for r in te]
        e0 += a0; e1 += a1
        if any(f(r['fvx'], K) > 0 for r in te): per.append(sum(a1) - sum(a0))
    d = np.array(e1) - np.array(e0); t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))
    return np.mean(e0), np.mean(e1), t, sum(p < 0 for p in per), len(per), np.mean(bs), min(bs), max(bs)
print('form    K  subset  MSE base->cand  t(<0 better)  classes better  b mean [min,max]')
for name, f in FORMS.items():
    for K in (50, 55, 60):
        for sub in ('all', 'final'):
            for pos in ('QB', 'non-QB'):
                S = [r for r in R if (r['g'] == 'QB') == (pos == 'QB') and (sub == 'all' or r['final'])]
                m0, m1, t, w, n, b, lo, hi = run(S, f, K)
                print(f"{name:7s} {K} {pos:6s} {sub:5s} {m0:6.2f}->{m1:6.2f} t{t:+.2f} {w}/{n} b{b:+.2f} [{lo:+.2f},{hi:+.2f}]")
