import json, math, numpy as np, fit as F, cfb_cfp as C
pairs, _ = F.build()
fc = json.load(open(C.OUT)); cols = [C.FEATS_ALL.index(f) for f in fc['feats']]; beta = np.array(fc['betaTune'])
tune = [p for p in pairs if p['S'] in C.TUNE]
th = {wl: F.fit([p for p in tune if p['wl'] == wl], beta, cols, ['lin', 'base', 'dwab']) for wl in range(1, 6)}
thl = {wl: F.fit([p for p in tune if p['wl'] == wl], beta, cols, ['lin']) for wl in range(1, 6)}
g_old = {11: 1.0, 13: 3.25}
def gold(l): return g_old[11] if l <= 11 else g_old[13] if l >= 13 else 2.125
out = {'new': [], 'linwl': [], 'live': [], 'none': []}
for p in pairs:
    if p['S'] not in C.HOLD: continue
    out['new'].append(F.score(p, beta, cols, ['lin', 'base', 'dwab'], th[p['wl']]))
    out['linwl'].append(F.score(p, beta, cols, ['lin'], thl[p['wl']]))
    out['live'].append(F.score(p, beta, cols, ['lin'], np.array([gold(int(p['label']))])))
    out['none'].append(F.score(p, beta, cols, [], np.array([])))
for k, v in out.items():
    d = np.array(out['new']) - np.array(v)
    print(k, round(sum(v), 1), 'new-minus t', round(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))), 2) if d.std() > 0 else '-', 'better pairs', int((d > 0).sum()), '/', len(d))
json.dump({'theta': {k: [round(float(x), 4) for x in v] for k, v in th.items()}}, open('theta.json', 'w'))
