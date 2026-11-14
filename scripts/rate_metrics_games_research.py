#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL game model, pre-registered (Nov 14 2026; part of the rate-metric batch, Holm in data/rate_metrics_research.json):

  G3  lineup value rv priced by a Marcel GAR a 60 (last three seasons 1 / .8 / .6, shrunk toward the F / D mean by
      20 / 80 hours of ice time, as a rate over the group's average) instead of projected HPM. Season S's games read
      seasons up to S-1 only. Same kept inputs (data/nhl_games_fit.json feats), walk-forward log loss on win, t
      clustered by day; tune 2021-23, held 2024-26 (negative = the GAR form is better).

    python3 scripts/rate_metrics_games_research.py   -> data/rate_metrics_games_research.json
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nhl_games as G
import harness as H

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'rate_metrics_games_research.json')
WTS, KH = (1, .8, .6), {'F': 20, 'D': 80}


def season_file(S):
    try:
        d = json.load(open(os.path.join(G.WARD, f'{S}.json')))
    except OSError:
        return None
    return {p['id']: p for p in d['players'] if p.get('grp') in ('F', 'D') and p.get('toi')}


def marcel_rates(S):
    """{id: GAR a 60 over the group's average} from seasons S, S-1, S-2 (the files only)"""
    fs = [season_file(S - j) for j in range(3)]
    if fs[0] is None:
        return None
    acc = {}
    for s in range(2009, S + 1):
        f = season_file(s)
        for p in (f or {}).values():
            a = acc.setdefault(p['grp'], [0.0, 0.0]); a[0] += p['gar']; a[1] += p['toi'] / 60
    mu = {g: a[0] / a[1] for g, a in acc.items()}
    out = {}
    for i, p in fs[0].items():
        g = p['grp']; num, den = KH[g] * mu[g], KH[g]
        for w, f in zip(WTS, fs):
            q = (f or {}).get(i)
            if q and q['grp'] == g:
                num += w * q['gar']; den += w * q['toi'] / 60
        out[i] = num / den
    avg = {}
    for g in ('F', 'D'):
        ps = [p for p in fs[0].values() if p['grp'] == g]
        avg[g] = sum(out[p['id']] * p['toi'] for p in ps) / sum(p['toi'] for p in ps)
    return {i: v - avg[fs[0][i]['grp']] for i, v in out.items()}


def main():
    hist = G.load_hist()
    P = json.load(open(G.FIT))['params']
    feats = json.load(open(G.FIT))['feats']
    _, base, _ = G.walk(hist, P, moves=G.hist_moves(hist))
    orig = G._war

    def alt(S):
        if S not in G._LV:
            w = orig(S)
            if w is None:
                return None
            ps, repl, avg = w
            r = marcel_rates(S - 1) or {}
            G._LV[S] = ({i: dict(p, hpm=r.get(i, p['hpm'])) for i, p in ps.items()}, repl, avg)
        return G._LV[S]
    G._LV.clear(); G._war = alt
    _, rows2, _ = G.walk(hist, P, moves=G.hist_moves(hist))
    G._war = orig
    S, y, m, tot, pc, tc, day = G.arrays(base)
    ok = np.ones(len(y), bool)
    lb = H.logloss(G.walk_logit(G.design(base, feats), y, S, G.SCORE_FROM + 1, ok), y)
    la = H.logloss(G.walk_logit(G.design(rows2, feats), y, S, G.SCORE_FROM + 1, ok), y)
    out = {}
    for lab, msk in (('tune', (S >= G.TUNE[0]) & (S <= G.TUNE[1])), ('held', S >= G.HOLD_FROM)):
        r = H.paired(la[msk], lb[msk], day[msk])
        out[lab] = {'d_x1000': round(r['d'] * 1000, 3), 't': round(r['t'], 2), 'n': int(msk.sum())}
    lined = ~np.isnan(pc)
    out['corr_rv'] = round(float(np.corrcoef([f['rv'] for _, f in base], [f['rv'] for _, f in rows2])[0, 1]), 3)
    print(json.dumps(out), flush=True)
    json.dump({'G3_nhl_rv_gar60': out}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
