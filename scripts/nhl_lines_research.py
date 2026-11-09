#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Line inputs on the NHL game model (Nov 2 2026): walk-forward, add-one on top of the shipped inputs.

    python3 scripts/nhl_lines_research.py      # -> data/nhl_lines_research.json (numpy; shifts cached by nhl_lines.py --pull)

Candidates (home minus away, every value known before puck drop):
    cont    line continuity: share of the team's last game's 5v5 trio and pair time from units that had already
            played 20+ minutes together this season before that game (forwards and defence averaged)
    chem    chemistry: last game's 5v5 trio / pair time-weighted log(1 + minutes together before it), this season plus
            last season's minutes at half weight
    blend   line blender: share of the last game's top two trios (by 5v5 time) that weren't among the game before's
            top three
    onoff   last game's skaters' 5v5 on/off from LAST season only (on-ice minus off-ice xGF/60 plus off-ice minus
            on-ice xGA/60, in his games, shrunk by k minutes), times his 5v5 minutes a game / 60; newcomers 0
    wowy    the same with each teammate's xG differential with him against without him (pair time weighted), in place
            of on/off
    ppu     power-play units: the team's recent power-play skaters (5v4 seconds, decayed .8 a game) at last season's
            5v4 on-ice xGF/60 (shrunk 120 min to the league), against the opponent's penalty-kill skaters' 5v4 xGA/60
            the same way; (pp home + pk-allowed away) - (pp away + pk-allowed home)
Gates as nhl_games.fit(): tune 2017-23 every game and 2021-23 lined, t >= 1.5 (positive = helps) and held 2024-26
not against (t > -1). The on/off k is picked on tune only.
"""
import json
import math
import os
import sys
from collections import defaultdict

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nhl_games as G  # noqa: E402
import nhl_lines as L  # noqa: E402

SEASONS = range(2016, 2027)
KS = (300, 600, 1200)         # on/off shrink, minutes


def prior_tables(rows):
    """a finished season's per-player 5v5 on/off, WOWY and special-teams rates"""
    on = defaultdict(lambda: np.zeros(3))         # pid -> [s, xgf, xga] on ice
    team_in = defaultdict(lambda: np.zeros(3))    # pid -> team totals [s, xgf, xga] in his games
    gp = defaultdict(int)
    pair = defaultdict(lambda: np.zeros(3))
    pp = defaultdict(lambda: np.zeros(2)); pk = defaultdict(lambda: np.zeros(2))
    for g in rows:
        if not g['xg']:
            continue
        for t, r in g['t'].items():
            tot = np.array([r['tot'][0], r['tot'][3], r['tot'][4]], float)
            for p, v in r['P'].items():
                on[p] += (v[0], v[3], v[4]); team_in[p] += tot; gp[p] += 1
            for k, v in r['W'].items():
                pair[k] += (v[0], v[3], v[4])
            for p, v in r['pp'].items():
                pp[p] += v
            for p, v in r['pk'].items():
                pk[p] += v
    lg_pp = sum(v[1] for v in pp.values()) / max(1, sum(v[0] for v in pp.values())) * 3600     # a unit's xGF/60 (both sums count each skater)
    lg_pk = sum(v[1] for v in pk.values()) / max(1, sum(v[0] for v in pk.values())) * 3600
    return {'on': on, 'team': team_in, 'gp': gp, 'pair': pair, 'pp': pp, 'pk': pk, 'lgpp': lg_pp, 'lgpk': lg_pk}


def onoff_values(T, k):
    out = {}
    for p, (s, xf, xa) in T['on'].items():
        ts, tf, ta = T['team'][p]
        off = ts - s
        if s < 600 or off < 600:
            continue
        rel = (xf / s - (tf - xf) / off) * 3600 + ((ta - xa) / off - xa / s) * 3600
        m = s / 60
        out[p] = rel * m / (m + k) * (m / T['gp'][p]) / 60
    return out


def wowy_values(T, k):
    """for each skater: TOI-weighted mean over teammates of (teammate's xG differential/60 with him - without him)"""
    acc = defaultdict(lambda: [0.0, 0.0])
    for key, (s, xf, xa) in T['pair'].items():
        if s < 300:
            continue
        a, b = key.split('-')
        for p, q in ((a, b), (b, a)):
            qs, qf, qa = T['on'][q]
            ws = qs - s
            if ws < 300:
                continue
            d = ((xf - xa) / s - ((qf - xf) - (qa - xa)) / ws) * 3600
            acc[p][0] += d * s; acc[p][1] += s
    out = {}
    for p, (num, den) in acc.items():
        s = T['on'][p][0]
        m = s / 60
        out[p] = num / den * m / (m + k) * (m / T['gp'][p]) / 60
    return out


def st_rates(T, kmin=120):
    pp = {p: (v[1] + T['lgpp'] / 3600 * kmin * 60) / (v[0] + kmin * 60) * 3600 for p, v in T['pp'].items()}
    pk = {p: (v[1] + T['lgpk'] / 3600 * kmin * 60) / (v[0] + kmin * 60) * 3600 for p, v in T['pk'].items()}
    return pp, pk


def features():
    """{game id: {candidate: home - away}}"""
    F = {}
    prev_T = None
    prev_tog = None
    for S in SEASONS:
        rows = L.summarize(S)
        print('season', S, len(rows), 'games', flush=True)
        vals = {}
        if prev_T is not None:
            for k in KS:
                vals[f'onoff{k}'] = onoff_values(prev_T, k)
                vals[f'wowy{k}'] = wowy_values(prev_T, k)
            ppr, pkr = st_rates(prev_T)
        tog = defaultdict(float)             # (team, unit) -> seconds together this season, before the game
        last, prev2 = {}, {}
        state = {}                            # team -> features from its last game
        ppw = defaultdict(lambda: defaultdict(float)); pkw = defaultdict(lambda: defaultdict(float))
        for g in rows:
            if g['po']:
                continue
            h, a = g['h'], g['a']
            if h in state and a in state:
                f = {k: state[h][k] - state[a][k] for k in state[h] if k in state[a]}
                if prev_T is not None:
                    def unit(w, r, lg):
                        tw = sum(w.values())
                        return sum(x * r.get(p, lg) for p, x in w.items()) / tw if tw else lg
                    pph, ppa = unit(ppw[h], ppr, prev_T['lgpp']), unit(ppw[a], ppr, prev_T['lgpp'])
                    pkh, pka = unit(pkw[h], pkr, prev_T['lgpk']), unit(pkw[a], pkr, prev_T['lgpk'])
                    f['ppu'] = (pph + pka) - (ppa + pkh)
                F[g['id']] = f
            for t in (h, a):
                r = g['t'].get(t)
                if not r:
                    continue
                st = {}
                for grp, need in (('F', 1200), ('D', 1200)):
                    units = r[grp]
                    tot = sum(v[0] for v in units.values())
                    if tot:
                        st['cont' + grp] = sum(v[0] for u, v in units.items() if tog[(t, u)] >= need) / tot
                        st['chem' + grp] = sum(v[0] * math.log1p((tog[(t, u)] + .5 * (prev_tog or {}).get((t, u), 0)) / 60)
                                               for u, v in units.items()) / tot
                st['cont'] = (st.get('contF', 0) + st.get('contD', 0)) / 2
                st['chem'] = (st.get('chemF', 0) + st.get('chemD', 0)) / 2
                top2 = sorted(r['F'], key=lambda u: -r['F'][u][0])[:2]
                if t in last:
                    top3 = sorted(last[t]['F'], key=lambda u: -last[t]['F'][u][0])[:3]
                    st['blend'] = sum(u not in top3 for u in top2) / max(1, len(top2))
                else:
                    st['blend'] = 0.0
                for k, v in vals.items():
                    st[k] = sum(v.get(p, 0.0) for p in r['P'])
                state[t] = st
                for grp in ('F', 'D'):
                    for u, v in r[grp].items():
                        tog[(t, u)] += v[0]
                for p in list(ppw[t]):
                    ppw[t][p] *= .8
                for p in list(pkw[t]):
                    pkw[t][p] *= .8
                for p, v in r['pp'].items():
                    ppw[t][p] += v[0]
                for p, v in r['pk'].items():
                    pkw[t][p] += v[0]
                prev2[t] = last.get(t)
                last[t] = r
        prev_T = prior_tables(rows)
        prev_tog = dict(tog)
    return F


def main():
    feats_by_game = features()
    hist = G.load_hist()
    fit = json.load(open(G.FIT))
    P, kept = fit['params'], fit['feats']
    _, rows, _ = G.walk(hist, P, moves=G.hist_moves(hist))
    names = sorted({k for v in feats_by_game.values() for k in v})
    cov = defaultdict(int)
    for g, f in rows:
        x = feats_by_game.get(g['id'], {})
        for k in names:
            f[k] = x.get(k, 0.0)
            cov[(g['S'], k)] += k in x
    nS = defaultdict(int)
    for g, f in rows:
        nS[g['S']] += 1
    base = [k for k in kept if k != 'mkt']
    out = {'kept': kept, 'coverage': {str(S): {k: round(cov[(S, k)] / nS[S], 3) for k in names} for S in sorted(nS) if S >= 2016}}
    print('coverage 2024', out['coverage'].get('2024'))
    ev_all = G.evidence(rows, base, names, lined_only=False, first=G.SCORE_FROM + 1, tune_s=(G.SCORE_FROM + 1, G.TUNE[1]))
    ev_lined = G.evidence(rows, kept, names)
    out['everyGame'] = ev_all
    out['lined'] = ev_lined
    # pick the on/off and WOWY shrink on tune only, then the gate on both splits
    pick = {}
    for fam in ('onoff', 'wowy'):
        k = max(KS, key=lambda k: ev_all[f'{fam}{k}']['tTune'])
        pick[fam] = f'{fam}{k}'
    out['picked'] = pick
    verdict = {}
    for k in ['cont', 'chem', 'blend', 'ppu', pick['onoff'], pick['wowy'], 'contF', 'contD']:
        if k not in ev_all:
            continue
        a, b = ev_all[k], ev_lined[k]
        verdict[k] = {'every': [a['tTune'], a['tHeld']], 'lined': [b['tTune'], b['tHeld']],
                      'pass': bool(G.passes(a) and G.passes(b))}
    out['verdict'] = verdict
    print(json.dumps(verdict, indent=1))
    with open(L.RES, 'w') as f:
        json.dump(out, f, indent=1, allow_nan=False)
    print('wrote', L.RES)


if __name__ == '__main__':
    main()
