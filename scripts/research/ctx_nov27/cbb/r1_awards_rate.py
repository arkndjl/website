#!/usr/bin/env python3
"""R1 (prereg.md, round 2): the CBB awards draw's rest-of-season rate. Prior = last season's BPM (now) against his
preseason pXPM board form (candidate), K 300. Barttorvik game logs (BTLOG dir: <year>.json.gz, {year}_all_advgames).
 -> r1.json"""
import csv, gzip, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, HERE)
import cbb_xpm_hist as XH
from h1_builder import tstat, KIT
BTLOG = os.environ.get('BTLOG', '/tmp/claude-0/btlog')
KS = [300, 450, 600, 900, 1200]; CPS = [5, 10, 15, 20]
H = XH.load()
GP = {}
for r in csv.DictReader(open(KIT, newline='')):
    try: GP[(str(int(float(r['pid']))), int(r['year']))] = max(GP.get((str(int(float(r['pid']))), int(r['year'])), 0), float(r['gp'] or 0))
    except ValueError: pass


def season(y):
    """rows: (cp, m0, bpm0, mr, bpm_rest, last bpm, px2)"""
    T = defaultdict(lambda: defaultdict(dict))
    for g in json.load(gzip.open(os.path.join(BTLOG, f'{y}.json.gz'))):
        mn, gb = g[8], g[44]
        if not mn or gb is None: continue
        T[g[47]][g[0]][str(int(g[51]))] = (float(mn), float(gb))
    out = []
    for t, G in T.items():
        ds = sorted(G)
        for cp in CPS:
            if len(ds) < cp + 5: continue
            a = defaultdict(lambda: [0.0, 0.0, 0]); b = defaultdict(lambda: [0.0, 0.0])
            for d in ds[:cp]:
                for p, (mn, gb) in G[d].items(): a[p][0] += mn; a[p][1] += mn * gb; a[p][2] += 1
            for d in ds[cp:]:
                for p, (mn, gb) in G[d].items(): b[p][0] += mn; b[p][1] += mn * gb
            for p, (m0, s0, gp) in a.items():
                q = H.get((p, y - 1))
                if gp < .6 * cp or m0 / gp < 20 or b[p][0] < 50 or not q or GP.get((p, y - 1), 0) < 8: continue
                out.append((cp, m0, s0 / m0, b[p][0], b[p][1] / b[p][0], q['bpm'], q['px2']))
    return np.array(out)


def mse(A, prior, K, top=False):
    m = (A[:, 2] * A[:, 1] + prior * K) / (A[:, 1] + K); w = A[:, 3]; e = w * (m - A[:, 4]) ** 2
    if top:
        keep = np.zeros(len(A), bool)
        for cp in CPS:
            i = np.flatnonzero(A[:, 0] == cp); keep[i[np.argsort(-A[i, 2])[:100]]] = True
        return float(e[keep].sum() / w[keep].sum())
    return float(e.sum() / w.sum())


res, S = [], {}
for y in range(2017, 2027):
    A = season(y); S[y] = A
    r = {'season': y, 'n': len(A), 'now': mse(A, A[:, 5], 300), 'cand': mse(A, A[:, 6], 300), 'top_now': mse(A, A[:, 5], 300, True), 'top_cand': mse(A, A[:, 6], 300, True),
         'grid_now': {k: mse(A, A[:, 5], k) for k in KS}, 'grid_cand': {k: mse(A, A[:, 6], k) for k in KS}, 'no_prior': mse(A, A[:, 2], 0)}
    res.append(r); print(y, len(A), round(r['now'], 3), round(r['cand'], 3), round(r['top_now'], 3), round(r['top_cand'], 3), flush=True)
# secondary: K picked on earlier seasons
wf = []
for i, r in enumerate(res):
    if i == 0: continue
    k = min(KS, key=lambda k: sum(q['grid_cand'][k] for q in res[:i])); wf.append((r['season'], k, r['grid_cand'][k]))
d = np.array([r['now'] - r['cand'] for r in res]); dt = np.array([r['top_now'] - r['top_cand'] for r in res])
d2 = np.array([res[i + 1]['now'] - w[2] for i, w in enumerate(wf)])
out = {'seasons': res, 'mse_now': round(float(np.mean([r['now'] for r in res])), 4), 'mse_cand': round(float(np.mean([r['cand'] for r in res])), 4),
       'mse_no_prior': round(float(np.mean([r['no_prior'] for r in res])), 4), 't': round(tstat(d), 2), 'k': int((d > 0).sum()), 'n': len(d),
       'top_now': round(float(np.mean([r['top_now'] for r in res])), 4), 'top_cand': round(float(np.mean([r['top_cand'] for r in res])), 4), 'top_t': round(tstat(dt), 2), 'top_k': int((dt > 0).sum()),
       'grid_now': {k: round(float(np.mean([r['grid_now'][k] for r in res])), 4) for k in KS}, 'grid_cand': {k: round(float(np.mean([r['grid_cand'][k] for r in res])), 4) for k in KS},
       'walk_K': [(s, k) for s, k, _ in wf], 'walk_K_mse': round(float(np.mean([w[2] for w in wf])), 4), 'walk_K_t_vs_now': round(tstat(d2), 2), 'walk_K_k': int((d2 > 0).sum())}
print({k: v for k, v in out.items() if k != 'seasons'})
json.dump(out, open(os.path.join(HERE, 'r1.json'), 'w'), indent=1)
# the shipped form (K 600, the walk's pick every season): the top-100 guard
g6 = np.array([mse(S[y], S[y][:, 5], 300, True) - mse(S[y], S[y][:, 6], 600, True) for y in S])
out['top_cand_K600'] = round(float(np.mean([mse(S[y], S[y][:, 6], 600, True) for y in S])), 4); out['top_K600_t'] = round(tstat(g6), 2); out['top_K600_k'] = int((g6 > 0).sum())
print(out['top_cand_K600'], out['top_K600_t'], out['top_K600_k'])
json.dump(out, open(os.path.join(HERE, 'r1.json'), 'w'), indent=1)
