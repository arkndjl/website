#!/usr/bin/env python3
"""Season-sim backtest of the committee-memory forms, from every CFP release but the last, 2017-25 (not 2020).
Tune 2017-21 (memory coefficients fit there), held out 2022-25. Truth = 12-team rule on the final release."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import cfb_cfp as C, bracket as B
from cfb_cfp_seeds import seeds_of
import fit as F

def main(N=2000):
    pairs, (games, info, wfr, rels) = F.build()
    fitc = json.load(open(C.OUT)); cols = [C.FEATS_ALL.index(f) for f in fitc['feats']]; beta = np.array(fitc['betaTune'])
    tune = [p for p in pairs if p['S'] in C.TUNE]
    th_new = {wl: F.fit([p for p in tune if p['wl'] == wl], beta, cols, ['lin', 'base', 'dwab']) for wl in range(1, 6)}
    th_lin = {wl: F.fit([p for p in tune if p['wl'] == wl], beta, cols, ['lin']) for wl in range(1, 6)}
    g_old = {11: 1.0, 13: 3.25}          # the live form: tune gamma keyed by release label, linear between, held at ends
    def gamma_old(lab):
        ks = sorted(g_old)
        if lab <= ks[0]: return g_old[ks[0]]
        if lab >= ks[-1]: return g_old[ks[-1]]
        return g_old[ks[0]] + (lab - ks[0]) / (ks[1] - ks[0]) * (g_old[ks[1]] - g_old[ks[0]])
    print('theta new', {k: np.round(v, 3).tolist() for k, v in th_new.items()}, flush=True)
    rng = np.random.default_rng(20261125)
    rows = []
    for p in pairs:
        S, fr = p['S'], p['fr']; fbs, conf, ccg, reg = info[S]
        rel = next(r for r in rels[S] if r['week'] == p['label'])
        D0 = C.pday(rel['date'])
        wk = max(g['week'] for g in reg if C.pday(g['startDate']) < D0)
        teams = fr['teams']; T = len(teams); ix = {t: i for i, t in enumerate(teams)}
        Dr = C.sim_draws(S, wk, fr, info, wfr, rng, N)
        Fe, champ = Dr['feats'], Dr['champ']; strn = Fe['rating']
        # wab at the release: games before it, same strength draws and bubble
        bub = -np.sort(-strn, axis=1)[:, 11]
        fcs_r = -25.0
        wab_r = np.zeros((N, T))
        for g in reg:
            if C.pday(g['startDate']) >= D0 or g['week'] > wk: continue
            h, a = ix.get(str(g['homeId']), -1), ix.get(str(g['awayId']), -1)
            hw = 1.0 if g['homePoints'] > g['awayPoints'] else 0.0; site = 0 if g['neutralSite'] else 2.5
            sh = strn[:, h] if h >= 0 else fcs_r; sa = strn[:, a] if a >= 0 else fcs_r
            if h >= 0: wab_r[:, h] += hw - np.vectorize(C.phi)((bub - sa + site) / C.GSD)
            if a >= 0: wab_r[:, a] += (1 - hw) - np.vectorize(C.phi)((bub - sh - site) / C.GSD)
        base = sum(beta[k] * Fe[C.FEATS_ALL[c]] for k, c in enumerate(cols))
        lin = F.mem_lin(p['rk'])[None, :]
        wl = min(5, max(1, p['wl']))
        gum = rng.gumbel(size=(N, T))
        a, c, d = th_new[wl]
        scores = {'nomem': base, 'live': base + gamma_old(int(p['label'])) * lin, 'linwl': base + th_lin[wl][0] * lin,
                  'new': c * base + a * lin + d * (Fe['wab'] - wab_r)}
        truth = seeds_of(list(fr['order']) + [i for i in range(T) if i not in fr['order']], np.array([t in fr['champs'] for t in teams]))
        tset = set(truth); yin = np.array([1.0 if i in tset else 0.0 for i in range(T)])
        out = {'S': S, 'wl': p['wl'], 'part': 'tune' if S in C.TUNE else 'hold'}
        for nm, sc in scores.items():
            z = sc + gum
            tal = B.Tally({'cfp': 12}, ['in']); pin = np.zeros(T)
            for n in range(N):
                sd = seeds_of(list(np.argsort(-z[n])), champ[n].astype(bool)); tal.season(); tal.seeds('cfp', sd); pin[sd] += 1
            pin /= N
            proj, _, sdd = tal.project(); pj = [r['t'] for r in proj['cfp']]
            cl = np.clip(pin, 1 / (N + 1), 1 - 1 / (N + 1))
            out[nm] = {'exact': sum(int(pj[k] == truth[k]) for k in range(12)), 'field': sum(i in tset for i in pj),
                       'seedLL': [-math.log(max(sdd['cfp'].get(i, [0] * 12)[k], 1 / (N + 1))) for k, i in enumerate(truth)],
                       'fieldLL': (-(yin * np.log(cl) + (1 - yin) * np.log(1 - cl))).tolist()}
        # committee today: ranking that release, top-ranked per conference = champion
        ranked = [ix[x['id']] for x in sorted(rel['ranks'], key=lambda x: x['rk']) if x['id'] in ix]
        seen, mask = set(), np.zeros(T, bool)
        for i in ranked:
            cc = conf.get(teams[i])
            if cc and 'Independent' not in cc and cc not in seen: seen.add(cc); mask[i] = True
        bs = seeds_of(ranked + [i for i in range(T) if i not in ranked], mask)
        out['today'] = {'exact': sum(int(bs[k] == truth[k]) for k in range(12)), 'field': sum(i in tset for i in bs)}
        rows.append(out)
        print(S, p['wl'], {k: (v['exact'], v['field']) for k, v in out.items() if isinstance(v, dict)}, flush=True)
    json.dump({'theta': {k: v.tolist() for k, v in th_new.items()}, 'thetaLin': {k: v.tolist() for k, v in th_lin.items()}, 'rows': rows},
              open(os.path.join(HERE, 'sim.json'), 'w'))

if __name__ == '__main__':
    main()
