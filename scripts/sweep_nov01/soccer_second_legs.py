"""Soccer two-legged ties: does the first leg's score move the second leg beyond the model? (Nov 1 2026 sweep)
UEFA cups and their qualifiers (hist 'leg' 1/2 + 'ser'). For each second leg, agg = first-leg goals of the
second leg's home side minus its opponent's. Terms on the walk-forward model's expected goals (wf 'l'):
  lin   log lam_h -= c * clip(agg, -3, 3), log lam_a += c * clip(agg, -3, 3)   (the leader sits back)
  dead  |agg| >= 3: both lam x exp(d)                                              (a decided tie)
c, d fit on second legs 2010-22 by log loss (grid), scored on 2023+ (held), paired by match. No closes in these
competitions in football-data, so this is against the model only."""
import gzip, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import soccer_games as G
import harness as H
ROOT = os.path.dirname(HERE)
hist = json.load(gzip.open(G.HIST))
wf = {r['id']: r for r in json.load(gzip.open(G.WF))}
P = G.params(); rho = P['rho']
first = {}
for r in hist:
    if r.get('leg') == 1 and r.get('hs') is not None:
        first[(r['lg'], r.get('ser'), r['h'], r['a'])] = r
legs = []
for r in hist:
    if r.get('leg') == 2 and r.get('hs') is not None and r['id'] in wf and 'l' in wf[r['id']]:
        f = first.get((r['lg'], r.get('ser'), r['a'], r['h']))
        if f and f['day'] < r['day']:
            agg = f['as'] - f['hs']            # leg-2 home side was away in leg 1
            legs.append((r, wf[r['id']], agg))
print('second legs', len(legs))
S = np.array([w['S'] for _, w, _ in legs]); day = np.array([r['day'] for r, _, _ in legs])
y = np.array([0 if r['hs'] > r['as'] else 1 if r['hs'] == r['as'] else 2 for r, _, _ in legs])
agg = np.array([a for _, _, a in legs], float)

def ll(c, d):
    out = np.empty(len(legs))
    for i, (r, w, a) in enumerate(legs):
        lh, la = w['l']
        ca = max(-3, min(3, a))
        lh = lh * math.exp(-c * ca + (d if abs(a) >= 3 else 0)); la = la * math.exp(c * ca + (d if abs(a) >= 3 else 0))
        p = G.wdl(lh, la, rho)
        out[i] = -math.log(max(p[y[i]], 1e-9))
    return out

base = ll(0, 0)
tune = S <= 2022; held = S >= 2023
best = None
for c in (-0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2):
    for d in (-0.2, -0.1, 0, 0.1):
        l = ll(c, d)
        v = l[tune].mean()
        if best is None or v < best[0]:
            best = (v, c, d, l)
v, c, d, l = best
out = {'n': {'tune': int(tune.sum()), 'held': int(held.sum())}, 'c': c, 'd': d,
       'raw': {f'agg{k}': {'n': int((np.clip(agg, -2, 2) == k).sum()),
                           'gd_res_minus_model': round(float(np.mean([(r['hs'] - r['as']) - (w['l'][0] - w['l'][1]) for (r, w, a) in legs if max(-2, min(2, a)) == k])), 3)}
               for k in (-2, -1, 0, 1, 2)}}
for lab, m in (('tune', tune), ('held', held)):
    rr = H.paired(l[m], base[m], cluster=day[m])
    out[lab] = {'ll_new': round(float(l[m].mean()), 5), 'll_old': round(float(base[m].mean()), 5), 't': round(rr['t'], 2)}
# lin alone and dead alone at their own tune best
for nm, grid in (('lin_only', [(c_, 0) for c_ in (-0.1, -0.05, 0.05, 0.1, 0.15, 0.2)]), ('dead_only', [(0, d_) for d_ in (-0.2, -0.1, 0.1)])):
    bb = min(grid, key=lambda g: ll(*g)[tune].mean())
    l2 = ll(*bb)
    out[nm] = {'param': bb, 'tune_t': round(H.paired(l2[tune], base[tune], cluster=day[tune])['t'], 2),
               'held_t': round(H.paired(l2[held], base[held], cluster=day[held])['t'], 2)}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'soccer_second_legs.json'), 'w'), indent=1)
