"""Crowd size in the CBB game model (Nov 18 2026, Noah: "have we tested crowd size as a team/game input?").

The shipped model already has hatt (Oct 29, scripts/cbb_edge_research.py): home x the home team's trailing crowd,
log(attendance / 1000 + 1), this season's earlier home games with last season's mean worth ATT_K games. This file
tests what that left out, on the shipped model (cbb_games_fit.json params and inputs, hatt in):

    margin  fill      + home x trailing share of capacity (next to hatt)
            fillsw      fill in place of hatt
            rawsw       home x trailing crowd in thousands (linear) in place of hatt
            raw       + the linear crowd next to hatt
    total   thatt     + home crowd (hatt's column) on the total
            tfill     + home fill share on the total

Capacity: ESPN's venue records carry no capacity for college basketball, so a team's capacity is its largest home
crowd over the three seasons before (2021 left out) and this season's earlier home games; fill = trailing crowd /
capacity, capped at 1. Everything is known before tip.

House bar (judge() in cbb_edge_research): walk-forward fit, tune 2016-20, held 2021-26; the change in prediction vs the
closing-line residual (tune t >= 1.5, held slope > 0, held squared-error gain t <= -1.5, clustered by day), model MAE no
worse in either block, Holm over the six. Writes data/cbb_crowd_research.json.

    python3 scripts/cbb_crowd_research.py
"""
import json
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C
import cbb_edge_research as E
import harness as H

OUT = os.path.join(C.ROOT, 'data', 'cbb_crowd_research.json')
PK = os.path.join(C.HERE, '.cache', 'crowd', 'walk.pkl')


def crowd_feats(games):
    """game id -> (log crowd as hatt, crowd in thousands, fill share), each the home side's trailing value shrunk to
    last season's mean with ATT_K games; None at a neutral site"""
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    means = {}          # season -> team -> (mean log, mean k, mean fill)
    hist_max = defaultdict(dict)    # season -> team -> max crowd that season
    out = {}
    for s in sorted(by_s):
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
        cur = defaultdict(list)
        smax = defaultdict(float)
        prev = means.get(s - 1, {})
        day_buf, day = [], None

        def cap(t):
            c = max([hist_max[y].get(t, 0.0) for y in range(s - 3, s) if y not in C.EMPTY] + [smax[t]])
            return c if c >= 500 else None

        def flush():
            for g in day_buf:
                a = g.get('att')
                if g['neutral'] or a is None or g.get('hs') is None or not (a > 0 or g['season'] in C.EMPTY):
                    continue
                a = float(a)
                t = g['home']
                smax[t] = max(smax[t], a) if s not in C.EMPTY else smax[t]
                c = cap(t)
                cur[t].append((np.log(a / 1000 + 1), a / 1000, min(1.0, a / c) if c else None))
            day_buf.clear()
        for g in gs:
            d = C.et_date(g['date'])
            if d != day:
                flush()
                day = d
            day_buf.append(g)
            if g['neutral']:
                out[g['id']] = None
                continue
            t = g['home']
            v = cur[t]
            pm = prev.get(t)
            vals = []
            for j in range(3):
                xs = [r[j] for r in v if r[j] is not None]
                p = pm[j] if pm and pm[j] is not None else None
                den = len(xs) + (C.ATT_K if p is not None else 0)
                vals.append((sum(xs) + (C.ATT_K * p if p is not None else 0.0)) / den if den else None)
            out[g['id']] = tuple(vals)
        flush()
        means[s] = {}
        for t, v in cur.items():
            m = []
            for j in range(3):
                xs = [r[j] for r in v if r[j] is not None]
                m.append(float(np.mean(xs)) if xs else None)
            means[s][t] = tuple(m)
        hist_max[s] = dict(smax)
    return out


def main():
    F = json.load(open(C.FIT))
    P = dict(F['params'])
    for k in ('cv', 'lw3', 'xcar', 'thl', 'ldft', 'aplmix', 'aplo', 'apld'):
        P.setdefault(k, C.DEFAULT[k])
    feats, tfeats = list(F['feats']), list(F.get('tfeats') or C.TFEATS)
    games, btname, d1s, tprior, avs = C.load_all()
    print('loaded', len(games), flush=True)
    if os.path.exists(PK):
        rows = pickle.load(open(PK, 'rb'))
    else:
        _, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
        os.makedirs(os.path.dirname(PK), exist_ok=True)
        pickle.dump(rows, open(PK, 'wb'))
    cf = crowd_feats(games)
    # candidate columns into each row (home only, centred on the tune-block home mean)
    tr = [(g, x) for g, x, _ in rows if C.SCORE0 <= g['season'] <= C.TUNE_END and not g['neutral'] and cf.get(g['id'])]
    mus = [float(np.mean([cf[g['id']][j] for g, _ in tr if cf[g['id']][j] is not None])) for j in range(3)]
    rep, nfill, nh = 0.0, 0, 0
    for g, x, tx in rows:
        v = cf.get(g['id'])
        if g['neutral'] or not v:
            x['c_log'] = x['c_k'] = x['c_fill'] = 0.0
        else:
            nh += 1
            nfill += v[2] is not None
            x['c_log'], x['c_k'], x['c_fill'] = [(z - m) if z is not None else 0.0 for z, m in zip(v, mus)]
            if v[0] is not None:
                rep = max(rep, abs(v[0] - C.ATT_MID - x['hatt']))
        tx['c_hatt'], tx['c_fill'] = x['hatt'], x['c_fill']
    print('hatt replica max diff', rep, 'fill covered', nfill / max(nh, 1), 'means', mus, flush=True)

    D, Xm0, y, TX0, ty, S, line, tline, d1 = C.matrices(rows, feats, tfeats)
    pm0 = C.walk_pred(Xm0, y, S, d1)
    pt0 = C.walk_pred(TX0, ty, S, d1)
    g_ = [r[0] for r in D]
    day = np.array([g['date'][:10] for g in g_])
    hc = [day, np.array([f"{g['home']}-{g['season']}" for g in g_])]
    tune = (S >= C.SCORE0) & (S <= C.TUNE_END) & d1
    held = (S > C.TUNE_END) & d1
    hm = np.array([not g['neutral'] for g in g_])
    fl = np.array([r[1]['c_fill'] for r in D]); lg = np.array([r[1]['c_log'] for r in D])
    res = {'base': {'feats': feats, 'tfeats': tfeats, 'games': [int(tune.sum()), int(held.sum())],
                    'mae': [E.r4(np.abs(pm0 - y)[tune].mean()), E.r4(np.abs(pm0 - y)[held].mean())],
                    'tmae': [E.r4(np.abs(pt0 - ty)[tune].mean()), E.r4(np.abs(pt0 - ty)[held].mean())]},
           'hattReplica': E.r4(rep), 'fillCovered': E.r4(nfill / max(nh, 1)),
           'means': {'log': E.r4(mus[0]), 'k': E.r4(mus[1]), 'fill': E.r4(mus[2])},
           'fillSd': E.r4(float(fl[hm & tune].std())), 'corrFillLog': E.r4(float(np.corrcoef(fl[hm], lg[hm])[0, 1])),
           'tests': {}}
    print('base', res['base'], flush=True)
    T = res['tests']
    sw = lambda c: [c if f == 'hatt' else f for f in feats]
    for k, fs in (('fill', feats + ['c_fill']), ('fillsw', sw('c_fill')), ('rawsw', sw('c_k')), ('raw', feats + ['c_k'])):
        _, Xm, _, _, _, _, _, _, _ = C.matrices(rows, fs, tfeats)
        T[k + ':margin'] = E.judge(C.walk_pred(Xm, y, S, d1), pm0, y, line, S, day, d1, hc)
        print(k, T[k + ':margin'], flush=True)
    for k, c in (('thatt', 'c_hatt'), ('tfill', 'c_fill')):
        _, _, _, TX, _, _, _, _, _ = C.matrices(rows, feats, tfeats + [c])
        T[k + ':total'] = E.judge(C.walk_pred(TX, ty, S, d1), pt0, ty, tline, S, day, d1, hc)
        print(k, T[k + ':total'], flush=True)
    ks = list(T)
    p = [H.p_of_z(T[k]['z']) if T[k].get('z') else 0.5 for k in ks]
    m = len(p)
    hq, run = [0.0] * m, 0.0
    for r, i in enumerate(np.argsort(p)):
        run = max(run, min(1.0, (m - r) * p[i]))
        hq[i] = run
    for k, q in zip(ks, hq):
        T[k]['holm'] = round(float(q), 3)
        T[k]['pass'] = bool(T[k].get('split') and q <= 0.10 and T[k].get('modelOk'))
        print(f"{k:14} tune {T[k]['tune']} held {T[k]['held']} se {T[k]['seHeld']} holm {T[k]['holm']} "
              f"mae {T[k]['mae_tune'][1:]} {T[k]['mae_held'][1:]} {'PASS' if T[k]['pass'] else ''}", flush=True)
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
