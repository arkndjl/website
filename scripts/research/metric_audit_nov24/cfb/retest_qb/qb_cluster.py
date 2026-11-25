"""Player-clustered t for the QB all-seasons variants (a player's seasons share one outcome)."""
import runpy, numpy as np, io, contextlib
with contextlib.redirect_stdout(io.StringIO()): G = runpy.run_path('/mnt/project-files/fv/qb-topend-nov01/qb_forms.py')
R, FORMS = G['R'], G['FORMS']
S = [r for r in R if r['g'] == 'QB']
for name, f in FORMS.items():
    for K in (50, 55, 60):
        d = {}
        for c in sorted({r['cls'] for r in S}):
            tr = [r for r in S if r['cls'] != c]
            h = np.array([f(r['fvx'], K) for r in tr]); y = np.array([r['out'] - r['fvx'] for r in tr]); b = float(h @ y / (h @ h))
            for r in S:
                if r['cls'] == c:
                    k = r['name'] + str(c); d[k] = d.get(k, 0) + (r['out'] - min(80, r['fvx'] + b * f(r['fvx'], K))) ** 2 - (r['out'] - r['fvx']) ** 2
        v = np.array(list(d.values())); print(f"{name:7s} K{K} players {len(v)} clustered t {v.mean() / (v.std(ddof=1) / np.sqrt(len(v))):+.2f}")
