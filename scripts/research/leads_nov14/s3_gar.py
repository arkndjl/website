# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""S3-ii: game-state npxG and xA as GAR input rates, judged as the GAR fit is (last season's rates at this season's
minutes -> team goal difference a match, ridge, leave-one-season-out). Prereg:
/mnt/project-files/leads-nov14/soccer/prereg.md.

    python3 scripts/research/leads_nov14/s3_gar.py
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import soccer_data as D
import soccer_players as SP
import gsxg

OUT = os.environ.get('LEADS_OUT', '/home/user/scratch-soccer')
PKL = os.path.join(OUT, 'gar_cuts.pkl')
WS = (0.0, 0.5)
LAST = 2026                      # 2025-26, the last finished season (2026-27 is not read)


def cuts():
    """(league, season, team id, player id) -> {w: [npxG removed, xA removed]}"""
    if os.path.exists(PKL):
        return pickle.load(open(PKL, 'rb'))
    out = defaultdict(lambda: {w: [0.0, 0.0] for w in WS})
    n = bad = 0
    for S in range(SP.FIRST, LAST + 1):
        for lg in D.BIG5:
            d = D.us_league(lg, S)
            for mt in (d or {}).get('matches', []):
                if not mt['res']:
                    continue
                m = D.us_match(mt['id'])
                if not m:
                    continue
                n += 1
                st = gsxg.states(m, mt['hg'], mt['ag'])
                if st is None:
                    bad += 1
                    continue
                for s in 'ha':
                    tid = mt['hid'] if s == 'h' else mt['aid']
                    name = defaultdict(list)
                    for r in m['ro'][s]:
                        if str(r['player_id']) not in name[r['player']]:
                            name[r['player']].append(str(r['player_id']))
                    for x, q in st[s]:
                        if x[3] == 'OwnGoal' or not q:
                            continue
                        for w in WS:
                            cut = (1 - gsxg.wt(q, w)) * gsxg.f(x[1])
                            if x[4] != 'Penalty':
                                out[(lg, S, tid, str(x[2]))][w][0] += cut
                            a = name.get(x[5]) if x[5] else None
                            if a and len(a) == 1:
                                out[(lg, S, tid, a[0])][w][1] += cut
    print('matches', n, 'kept raw', bad, flush=True)
    out = dict(out)
    pickle.dump(out, open(PKL, 'wb'))
    return out


def tstat(d, keys):
    g = defaultdict(float)
    for x, k in zip(d, keys):
        g[k] += x
    m = sum(d) / len(d)
    gs = defaultdict(float)
    for x, k in zip(d, keys):
        gs[k] += x - m
    se = math.sqrt(sum(v * v for v in gs.values())) / len(d)
    return m, m / se, len(g)


def main():
    F = json.load(open(SP.FIT))
    rows = [r for r in D.load(SP.ROWS) if r['S'] <= LAST]
    ts = {k: v for k, v in SP.team_seasons(SP.FIRST, LAST).items()}
    LS, TMV = SP.league_strength(), SP.tm_values()
    C = cuts()
    feats, lam = F['feats'], F['lambda']
    pri = dict(priors=SP.PRIORS, LS=LS, TMV=TMV)

    def mats(w):
        rs = [dict(r) for r in rows]
        tot = [0.0, 0.0, 0.0, 0.0]
        for r in rs:
            c = C.get((r['lg'], r['S'], str(r['tid']), str(r['p'])))
            tot[0] += r['x'] - r['pen']; tot[2] += r['xA']
            if w is not None and c:
                r['x'] -= c[w][0]; r['xA'] -= c[w][1]
                tot[1] += c[w][0]; tot[3] += c[w][1]
        SP.prep(rs, F['shrink'])
        ks, X, y = SP.design(rs, ts, feats, **pri)
        return ks, X, y, tot
    ks, X0, y, _ = mats(None)
    e0, p0 = SP.loso(ks, X0, y, lam)
    var = float(np.mean(y ** 2))
    res = {'teamSeasons': len(ks), 'baseMse': round(e0, 5), 'baseR2': round(1 - e0 / var, 4), 'fitR2': F.get('r2Held'), 'w': {}}
    Xw = {}
    S = np.array([k[1] for k in ks])
    for w in WS:
        k2, X, y2, tot = mats(w)
        assert k2 == ks
        Xw[w] = X
        e, p = SP.loso(ks, X, y, lam)
        d = (y - p) ** 2 - (y - p0) ** 2
        m, t, g = tstat(list(d), list(S))
        res['w'][str(w)] = {'mse': round(e, 5), 'r2': round(1 - e / var, 4), 'd': round(m, 6), 't': round(t, 2),
                            'npxgCut': round(tot[1] / tot[0], 4), 'xaCut': round(tot[3] / tot[2], 4),
                            'seasonsBetter': int(sum(1 for s in np.unique(S) if d[S == s].mean() < 0)), 'seasons': g}
    # nested: w chosen inside the other seasons
    pn = np.zeros(len(y))
    picks = {}
    for s in np.unique(S):
        tr = S != s
        inner = {}
        for w in WS:
            kk = [k for k, f_ in zip(ks, tr) if f_]
            inner[w] = SP.loso(kk, Xw[w][tr], y[tr], lam)[0]
        w = min(WS, key=lambda w: inner[w])
        picks[int(s)] = w
        pn[S == s] = Xw[w][S == s] @ SP.ridge(Xw[w][tr], y[tr], lam)
    d = (y - pn) ** 2 - (y - p0) ** 2
    m, t, g = tstat(list(d), list(S))
    res['nested'] = {'picks': picks, 'mse': round(float(np.mean((y - pn) ** 2)), 5), 'd': round(m, 6), 't': round(t, 2),
                     'clusters': g, 'seasonsBetter': int(sum(1 for s in np.unique(S) if d[S == s].mean() < 0)),
                     'bySeason': {int(s): round(float(d[S == s].mean()), 5) for s in np.unique(S)}}
    json.dump(res, open(os.path.join(OUT, 's3_gar.json'), 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
