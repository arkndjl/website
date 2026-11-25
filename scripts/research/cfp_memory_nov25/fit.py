#!/usr/bin/env python3
"""Committee memory: how the CFP committee's final ranking leans on its latest release (real inputs, no sim).
Pairs (release with wl releases left -> final), 2017-25 minus 2020. Tune 2017-21, hold 2022-25."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import cfb_cfp as C

def build():
    hist, polls, wf = C.load()
    games = {int(S): g for S, g in hist['games'].items()}
    by_id = {str(g['id']): g for S in games for g in games[S]}
    wfr = C.wf_rows(wf, by_id)
    info = {S: C.season_info(games[S], S) for S in games}
    rels = defaultdict(list)
    for r in polls['releases']:
        if r['poll'] == 'cfp' and r['S'] in games and r['S'] >= 2017 and r['S'] != 2020:
            rels[r['S']].append(r)
    pairs = []
    for S, rs in sorted(rels.items()):
        rs.sort(key=lambda r: r['date'])
        fr = C.release_rows(S, rs[-1], info[S], wfr, True)
        Dfin = C.pday(rs[-1]['date'])
        for k, rel in enumerate(rs[:-1]):
            wl = round((Dfin - C.pday(rel['date'])).days / 7)
            rr = C.release_rows(S, rel, info[S], wfr, False)
            assert rr['teams'] == fr['teams']
            rk = np.array([rr['rk'].get(t, 99) for t in fr['teams']], float)
            pairs.append({'S': S, 'wl': wl, 'label': rel['week'], 'fr': fr, 'Xr': rr['X'], 'rk': rk})
    return pairs, (games, info, wfr, rels)

def mem_lin(rk): return np.where(rk <= 25, (26 - rk) / 25, 0.0)
def mem_log(rk): return np.where(rk <= 25, np.log(26 / rk), 0.0)

def pl_ll(s, order):
    alive = np.ones(len(s), bool); out = 0.0
    for i in order:
        m = s[alive].max(); out += s[i] - m - math.log(np.exp(s[alive] - m).sum()); alive[i] = False
    return out

def design(p, beta, cols, kind):
    X = p['fr']['X']; base = X[:, cols] @ beta
    Xr = p['Xr']
    cols_out = {'base': base, 'lin': mem_lin(p['rk']), 'log': mem_log(p['rk']),
                'dL': X[:, 0] - Xr[:, 0], 'dwab': X[:, 3] - Xr[:, 3], 'drat': X[:, 2] - Xr[:, 2],
                'baseR': Xr[:, cols] @ beta, 'champ': X[:, 4],
                'sq': mem_lin(p['rk']) ** 2, 'unr': (p['rk'] > 25).astype(float)}
    return cols_out

MODELS = {  # free coefficients on the design columns; 'base' coefficient fixed 1 unless listed
    'none': [],
    'lin': ['lin'],                      # the live form
    'log': ['log'],
    'lin+log': ['lin', 'log'],
    'log+c': ['log', 'base'],
    'log+dL': ['log', 'dL'],
    'log+dL+dwab': ['log', 'dL', 'dwab'],
    'log+c+dL+dwab': ['log', 'base', 'dL', 'dwab'],
    'lin+log+c+dL': ['lin', 'log', 'base', 'dL'],
    'lin+dL': ['lin', 'dL'],
    'lin+c': ['lin', 'base'],
    'lin+c+dL': ['lin', 'base', 'dL'],
    'lin+c+dL+dwab': ['lin', 'base', 'dL', 'dwab'],
    'lin+c+dL+drat': ['lin', 'base', 'dL', 'drat'],
    'lin+c+dL+dwab+champ': ['lin', 'base', 'dL', 'dwab', 'champ'],
    'lin+c+dL+ch+top': ['lin', 'base', 'dL', 'champ', 'unr'],
    'sq+c+dL': ['sq', 'base', 'dL'],
    'lin+c+dwab': ['lin', 'base', 'dwab'],
    'lin+dwab': ['lin', 'dwab'],
    'lin+sq+c+dL': ['lin', 'sq', 'base', 'dL'],
}

def fit(pairs, beta, cols, free, ridge=0.01):
    D = [(design(p, beta, cols, None), p['fr']['order']) for p in pairs]
    k = len(free); th = np.array([1.0 if f == 'base' else 0.0 for f in free])
    def f_g_h(th):
        nll, g, H = 0.0, np.zeros(k), 2 * ridge * np.eye(k)
        for d, order in D:
            Z = np.stack([d[f] for f in free], 1) if k else np.zeros((len(d['base']), 0))
            off = d['base'] * (0 if 'base' in free else 1)
            s = off + Z @ th; alive = np.ones(len(s), bool)
            for i in order:
                Za = Z[alive]; m = s[alive].max(); e = np.exp(s[alive] - m); pr = e / e.sum(); mu = pr @ Za
                nll -= s[i] - m - math.log(e.sum()); g -= Z[i] - mu
                H += (Za * pr[:, None]).T @ Za - np.outer(mu, mu); alive[i] = False
        return nll + ridge * th @ th, g + 2 * ridge * th, H
    if not k: return th
    for _ in range(60):
        f, g, H = f_g_h(th); step = np.linalg.solve(H, g); t = 1.0
        while f_g_h(th - t * step)[0] > f and t > 1e-4: t /= 2
        th = th - t * step
        if np.abs(t * step).max() < 1e-7: break
    return th

def score(p, beta, cols, free, th):
    d = design(p, beta, cols, None)
    s = d['base'] * (0 if 'base' in free else 1) + sum(th[j] * d[f] for j, f in enumerate(free))
    return pl_ll(s, p['fr']['order'])

if __name__ == '__main__':
    pairs, _ = build()
    fitc = json.load(open(C.OUT)); cols = [C.FEATS_ALL.index(f) for f in fitc['feats']]; beta = np.array(fitc['betaTune'])
    print('pairs by wl', sorted({(p['wl'], sum(q['wl'] == p['wl'] for q in pairs)) for p in pairs}))
    res = {}
    for name, free in MODELS.items():
        row = {}
        for mode in ('perwl', 'pooled'):
            tot_h, tot_t, ths = 0.0, 0.0, {}
            per = defaultdict(float)
            for wl in sorted({p['wl'] for p in pairs}):
                tp = [p for p in pairs if p['S'] in C.TUNE and (p['wl'] == wl if mode == 'perwl' else True)]
                if mode == 'pooled' and 'log' in free:
                    pass
                th = fit(tp, beta, cols, free) if mode == 'perwl' else ths.get('all') if 'all' in ths else fit(tp, beta, cols, free)
                if mode == 'pooled': ths['all'] = th
                else: ths[wl] = th
                for p in pairs:
                    if p['wl'] != wl: continue
                    v = score(p, beta, cols, free, th)
                    if p['S'] in C.HOLD: tot_h += v; per[wl] += v
                    else: tot_t += v
            row[mode] = {'hold': round(tot_h, 1), 'tune': round(tot_t, 1), 'perwl': {k: round(v, 1) for k, v in per.items()},
                         'theta': {str(k): [round(float(x), 3) for x in v] for k, v in ths.items()}}
        res[name] = row
        print(name, free, 'perwl hold', row['perwl']['hold'], row['perwl']['perwl'], 'pooled hold', row['pooled']['hold'], flush=True)
        print('   theta', row['perwl']['theta'], flush=True)
    json.dump(res, open(os.path.join(HERE, 'fit.json'), 'w'), indent=1)
