#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFP committee memory: the final ranking as a move from the committee's latest release.

    python3 scripts/cfb_cfp_memory.py      # -> data/cfb_cfp_memory.json (~1 min)

scripts/cfb_model.mjs simulate() reads it. Rerun each January with scripts/cfb_cfp.py (it needs that fit's beta).

Pairs: every CFP release but the last of 2017-25 (not 2020) against that season's final release, keyed by wl = weeks
from the release to the final (1-5; 2026's Week 13 release on Nov 24 = 2, like 2025's Week 14 on Nov 25: the release
labels shift between seasons, the calendar does not). Final ranking, Plackett-Luce over every FBS team:
    s = c x (b . x_final) + a x (26 - rank) / 25 + d x (wab_final - wab_release)
b . x_final = the season committee model (scripts/cfb_cfp.py: losses, wins, rating, wins above bubble, champion, P4),
rank = the release's rank (unranked 0), wab = wins above a bubble team; a, c, d fit per wl. The old form (c 1, d 0, a
by the release label) and the shapes tried (log rank, rank squared, new losses, rating change, champion, unranked
flag) are in scripts/research/cfp_memory_nov25 (fit.py); the shape was chosen on 2017-21 by likelihood.

Tests, fit 2017-21 and scored 2022-25:
  real inputs: the final release's log likelihood given the real results (20 release-final pairs)
  season sim: from each release the rest of the season simulated as in cfb_cfp.sim_draws (2,000 finishes), the
              12-team rule (five best-ranked champions), seeds by rank; log loss of each real seed under the sim's seed
              odds, P(in the field) log loss over every FBS team, exact seeds of the projected bracket (most expected
              exact seeds), against the old form and the committee's own ranking that week."""
import json
import math
import os
from collections import defaultdict

import numpy as np

import cfb_cfp as C
import bracket as B

OUT = os.path.join(C.ROOT, 'data', 'cfb_cfp_memory.json')
WLS = range(1, 6)
FREE = ['lin', 'base', 'dwab']
OLD_G = {11: 1.0, 13: 3.25}      # the old form's tune gamma by release label (data/cfb_cfp_seeds.json 'gamma', label = week + 1)


def seeds_of(order, mask):
    f = set(C.pick12(order, mask))
    return [i for i in order if i in f][:12]


def mem_lin(rk):
    return np.where(rk <= 25, (26 - rk) / 25, 0.0)


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
        for rel in rs[:-1]:
            rr = C.release_rows(S, rel, info[S], wfr, False)
            pairs.append({'S': S, 'wl': round((Dfin - C.pday(rel['date'])).days / 7), 'rel': rel, 'fr': fr, 'Xr': rr['X'],
                          'rk': np.array([rr['rk'].get(t, 99) for t in fr['teams']], float)})
    return pairs, games, info, wfr


def design(p, beta, cols):
    X, Xr = p['fr']['X'], p['Xr']
    return {'base': X[:, cols] @ beta, 'lin': mem_lin(p['rk']), 'dwab': X[:, 3] - Xr[:, 3]}


def pl_ll(s, order):
    alive = np.ones(len(s), bool); out = 0.0
    for i in order:
        m = s[alive].max(); out += s[i] - m - math.log(np.exp(s[alive] - m).sum()); alive[i] = False
    return out


def scores(d, free, th):
    return d['base'] * (0 if 'base' in free else 1) + sum(th[j] * d[f] for j, f in enumerate(free))


def fit(pairs, beta, cols, free, ridge=0.01):
    """Plackett-Luce MLE of the free coefficients (Newton with halving)"""
    D = [(design(p, beta, cols), p['fr']['order']) for p in pairs]
    k = len(free)

    def fgh(th):
        nll, g, H = 0.0, np.zeros(k), 2 * ridge * np.eye(k)
        for d, order in D:
            Z = np.stack([d[f] for f in free], 1); s = scores(d, free, th); alive = np.ones(len(s), bool)
            for i in order:
                Za = Z[alive]; m = s[alive].max(); e = np.exp(s[alive] - m); pr = e / e.sum(); mu = pr @ Za
                nll -= s[i] - m - math.log(e.sum()); g -= Z[i] - mu
                H += (Za * pr[:, None]).T @ Za - np.outer(mu, mu); alive[i] = False
        return nll + ridge * th @ th, g + 2 * ridge * th, H
    th = np.array([1.0 if f == 'base' else 0.0 for f in free])
    for _ in range(60):
        f, g, H = fgh(th); step = np.linalg.solve(H, g); t = 1.0
        while fgh(th - t * step)[0] > f and t > 1e-4:
            t /= 2
        th = th - t * step
        if np.abs(t * step).max() < 1e-7:
            break
    return th


def gamma_old(label):
    ks = sorted(OLD_G)
    if label <= ks[0]:
        return OLD_G[ks[0]]
    if label >= ks[-1]:
        return OLD_G[ks[-1]]
    return OLD_G[ks[0]] + (label - ks[0]) / (ks[1] - ks[0]) * (OLD_G[ks[1]] - OLD_G[ks[0]])


def tstat(x):
    x = np.asarray(x, float)
    return round(float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))), 2) if len(x) > 1 and x.std() > 0 else 0.0


def sim_test(pairs, info, wfr, beta, cols, th, N=2000):
    rng = np.random.default_rng(20261125)
    rows = []
    phi_v = np.vectorize(C.phi)
    for p in pairs:
        S, fr, rel = p['S'], p['fr'], p['rel']; fbs, conf, ccg, reg = info[S]
        D0 = C.pday(rel['date'])
        wk = max(g['week'] for g in reg if C.pday(g['startDate']) < D0)
        teams = fr['teams']; T = len(teams); ix = {t: i for i, t in enumerate(teams)}
        Dr = C.sim_draws(S, wk, fr, info, wfr, rng, N)
        Fe, champ = Dr['feats'], Dr['champ']; strn = Fe['rating']
        bub = -np.sort(-strn, axis=1)[:, 11]
        wab_r = np.zeros((N, T))   # wins above bubble at the release: games before it, the same draws
        for g in reg:
            if C.pday(g['startDate']) >= D0:
                continue
            h, a = ix.get(str(g['homeId']), -1), ix.get(str(g['awayId']), -1)
            hw = 1.0 if g['homePoints'] > g['awayPoints'] else 0.0; site = 0 if g['neutralSite'] else 2.5
            sh = strn[:, h] if h >= 0 else -25.0; sa = strn[:, a] if a >= 0 else -25.0
            if h >= 0:
                wab_r[:, h] += hw - phi_v((bub - sa + site) / C.GSD)
            if a >= 0:
                wab_r[:, a] += (1 - hw) - phi_v((bub - sh - site) / C.GSD)
        base = sum(beta[k] * Fe[C.FEATS_ALL[c]] for k, c in enumerate(cols))
        lin = mem_lin(p['rk'])[None, :]
        a, c, d = th[min(5, max(1, p['wl']))]
        sc = {'old': base + gamma_old(int(p['rel']['week'])) * lin, 'new': c * base + a * lin + d * (Fe['wab'] - wab_r)}
        truth = seeds_of(list(fr['order']) + [i for i in range(T) if i not in fr['order']], np.array([t in fr['champs'] for t in teams]))
        tset = set(truth); yin = np.array([1.0 if i in tset else 0.0 for i in range(T)])
        gum = rng.gumbel(size=(N, T))
        out = {'S': S, 'wl': p['wl'], 'part': 'tune' if S in C.TUNE else 'hold'}
        for nm, s in sc.items():
            z = s + gum; tal = B.Tally({'cfp': 12}, ['in']); pin = np.zeros(T)
            for n in range(N):
                sd = seeds_of(list(np.argsort(-z[n])), champ[n].astype(bool)); tal.season(); tal.seeds('cfp', sd); pin[sd] += 1
            pin /= N
            proj, _, sdd = tal.project(); pj = [r['t'] for r in proj['cfp']]
            cl = np.clip(pin, 1 / (N + 1), 1 - 1 / (N + 1))
            out[nm] = {'exact': sum(int(pj[k] == truth[k]) for k in range(12)),
                       'seedLL': [-math.log(max(sdd['cfp'].get(i, [0] * 12)[k], 1 / (N + 1))) for k, i in enumerate(truth)],
                       'fieldLL': float((-(yin * np.log(cl) + (1 - yin) * np.log(1 - cl))).mean())}
        ranked = [ix[x['id']] for x in sorted(rel['ranks'], key=lambda x: x['rk']) if x['id'] in ix]
        seen, mask = set(), np.zeros(T, bool)
        for i in ranked:
            cc = conf.get(teams[i])
            if cc and 'Independent' not in cc and cc not in seen:
                seen.add(cc); mask[i] = True
        bs = seeds_of(ranked + [i for i in range(T) if i not in ranked], mask)
        out['today'] = {'exact': sum(int(bs[k] == truth[k]) for k in range(12))}
        rows.append(out)
        print(S, p['wl'], {k: v['exact'] for k, v in out.items() if isinstance(v, dict)}, flush=True)
    res = {}
    for part in ('tune', 'hold'):
        rr = [r for r in rows if r['part'] == part]
        res[part] = {'pairs': len(rr),
                     'seedLL': {m: round(float(np.mean([v for r in rr for v in r[m]['seedLL']])), 3) for m in ('old', 'new')},
                     'tSeedLL': tstat([a - b for r in rr for a, b in zip(r['old']['seedLL'], r['new']['seedLL'])]),
                     'fieldLL': {m: round(float(np.mean([r[m]['fieldLL'] for r in rr])), 4) for m in ('old', 'new')},
                     'tFieldLL': tstat([r['old']['fieldLL'] - r['new']['fieldLL'] for r in rr]),
                     'exact': {m: round(float(np.mean([r[m]['exact'] for r in rr])), 2) for m in ('old', 'new', 'today')}}
    return res


def main():
    pairs, games, info, wfr = build()
    cf = json.load(open(C.OUT)); cols = [C.FEATS_ALL.index(f) for f in cf['feats']]
    beta_t, beta_a = np.array(cf['betaTune']), np.array(cf['beta'])
    tune = [p for p in pairs if p['S'] in C.TUNE]; hold = [p for p in pairs if p['S'] in C.HOLD]
    th = {wl: fit([p for p in tune if p['wl'] == wl], beta_t, cols, FREE) for wl in WLS}
    ll = {'new': [], 'old': [], 'none': []}
    for p in hold:
        d = design(p, beta_t, cols); o = p['fr']['order']
        ll['new'].append(pl_ll(scores(d, FREE, th[p['wl']]), o))
        ll['old'].append(pl_ll(d['base'] + gamma_old(int(p['rel']['week'])) * d['lin'], o))
        ll['none'].append(pl_ll(d['base'], o))
    real = {'pairs': len(hold), **{k: round(sum(v), 1) for k, v in ll.items()},
            'tVsOld': tstat(np.array(ll['new']) - np.array(ll['old'])),
            'betterThanOld': int(sum(a > b for a, b in zip(ll['new'], ll['old'])))}
    print('real inputs, held out', real, flush=True)
    sim = sim_test(pairs, info, wfr, beta_t, cols, th)
    print(json.dumps(sim, indent=1), flush=True)
    live = {wl: fit([p for p in pairs if p['wl'] == wl], beta_a, cols, FREE) for wl in WLS}
    r4 = lambda v: [round(float(x), 4) for x in v]
    out = {'note': 'CFP committee memory: final ranking from the latest release (scripts/cfb_cfp_memory.py)',
           'form': 's = c x (b . x) + a x (26 - rank) / 25 + d x (wab - wab at release)', 'keys': ['a', 'c', 'd'],
           'byWeeksLeft': {str(k): r4(v) for k, v in live.items()}, 'tune': {str(k): r4(v) for k, v in th.items()},
           'realInputs': real, 'sim': sim}
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
