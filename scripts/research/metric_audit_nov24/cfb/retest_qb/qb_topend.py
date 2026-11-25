"""QB-only top-end stretch of CFB FV (Noah, Nov 1 2026). Held out by draft class on the 2014-25 all-time rebuild.
Candidate: fvx' = fvx + b*max(0, fvx-K) for QBs (b fit on the other classes). Outcome = NFL AV/season on the FV scale."""
import sys, json, numpy as np
sys.path.insert(0, '/home/user/website/scripts')
import fv_alltime as A
rows = []
src = json.load(A.gzip.open(A.CFB_ROWS))
d = A.cfb(A.CFB_ROWS)  # recompute box recal via same code: re-run its internals
# replicate rows with box recal (cfb() only returns listed peaks); rebuild quickly
R = []
for r in src:
    draft = r['draft'] or r['last'] + 1
    if r['av'] is None or draft > A.CFB_MATURE: continue
    R.append(dict(g=r['g'], s=r['s'], fvx=r['fvx'], fm=r['fm'], final=r['final'], cls=draft, out=A.fv_from_av(r['av']), name=r['name'], pick=r['pick']))
bf = {k == 'last': np.array(v) for k, v in d['boxfit'].items()}
for r in R:
    if r['s'] < 2019:
        r['fvx'] = max(20.0, 20 + float(np.dot(bf[r['final']], [r['fvx'] - 20, max(0, r['fvx'] - 40)])))
def run(S, K, label):
    cls = sorted({r['cls'] for r in S})
    e0, e1, bs, per = [], [], [], []
    for c in cls:
        tr = [r for r in S if r['cls'] != c]; te = [r for r in S if r['cls'] == c]
        h = np.array([max(0, r['fvx'] - K) for r in tr]); y = np.array([r['out'] - r['fvx'] for r in tr])
        b = float(h @ y / (h @ h)) if h @ h > 0 else 0.0
        bs.append(b)
        a0 = [(r['out'] - r['fvx']) ** 2 for r in te]
        a1 = [(r['out'] - r['fvx'] - b * max(0, r['fvx'] - K)) ** 2 for r in te]
        e0 += a0; e1 += a1
        if any(r['fvx'] > K for r in te): per.append(np.mean(a1) - np.mean(a0))
    dd = np.array(e1) - np.array(e0)
    t = dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd))) if dd.std() > 0 else 0
    top = [r for r in S if r['fvx'] > K]
    gap = np.mean([r['out'] - r['fvx'] for r in top]) if top else float('nan')
    print(f"{label:22s} K{K} n{len(S)} above{len(top)} gap{gap:+.1f} b[{min(bs):+.2f},{np.mean(bs):+.2f},{max(bs):+.2f}] "
          f"MSE {np.mean(e0):.1f}->{np.mean(e1):.1f} t{t:+.2f} classes better {sum(p < 0 for p in per)}/{len(per)}")
for K in (55, 60, 65):
    for pos in ('QB', 'non-QB'):
        for sub in ('all', 'final', 'pfn'):
            S = [r for r in R if (r['g'] == 'QB') == (pos == 'QB') and (sub == 'all' or (sub == 'final' and r['final']) or (sub == 'pfn' and r['s'] >= 2019))]
            run(S, K, f"{pos} {sub}")
print('\nQB above 60 (final seasons):')
for r in sorted([r for r in R if r['g'] == 'QB' and r['fvx'] > 60], key=lambda r: -r['fvx']):
    print(f"  {r['name']:22s} {r['s']} fin{int(r['final'])} fm{r['fm']:.1f} fvx{r['fvx']:.1f} out{r['out']:.1f} pick{r['pick']}")
print('\nQB final seasons by band (player = final season), gap = out - fvx:')
F = [r for r in R if r['g'] == 'QB' and r['final']]
for lo, hi in ((40, 45), (45, 50), (50, 55), (55, 60), (60, 99)):
    T = [r for r in F if lo <= r['fvx'] < hi]
    if T:
        g = np.array([r['out'] - r['fvx'] for r in T])
        print(f"  {lo}-{hi} n{len(T)} given{np.mean([r['fvx'] for r in T]):.1f} became{np.mean([r['out'] for r in T]):.1f} gap{g.mean():+.1f} se{g.std(ddof=1)/np.sqrt(len(g)) if len(g)>1 else 0:.1f}")
for r in sorted([r for r in F if 52 <= r['fvx'] < 60], key=lambda r: -r['fvx']):
    print(f"  {r['name']:22s} {r['s']} fvx{r['fvx']:.1f} out{r['out']:.1f} pick{r['pick']}")
