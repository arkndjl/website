# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L6: UEFA top speed (standardised within competition-season, minutes and position) as a term in the one-year GAR
projection. Prereg: /mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/sweep_nov19/soccer/l6_speed.py <uefa dir>
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCR)
import names as N
import soccer_data as D
import soccer_players as SP
import soccer_proj_research as PR

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')


def uefa_z(dr, y):
    """birth date -> [(name, z, top speed, minutes)] for seasonYear y"""
    best = {}
    for c in (1, 14):
        fn = os.path.join(dr, f'uefa_{c}_{y}.json')
        if not os.path.exists(fn):
            continue
        rs = []
        for x in json.load(open(fn)):
            try:
                sp, mn = float(x['st']['top_speed']), float(x['st']['minutes_played_official'])
            except (KeyError, TypeError, ValueError):
                continue
            if sp >= 20 and mn >= 45 and x.get('dob'):
                rs.append((x, sp, mn))
        by = defaultdict(list)
        for r in rs:
            by[r[0].get('pos')].append(r)
        for pos, v in by.items():
            if len(v) < 20:
                continue
            a = np.array([[1.0, math.log(m)] for _, _, m in v]); s = np.array([sp for _, sp, _ in v])
            b = np.linalg.lstsq(a, s, rcond=None)[0]
            res = s - a @ b
            sd = res.std() or 1.0
            for (x, sp, mn), e in zip(v, res):
                k = (x['dob'], N.key(x['n']))
                if k not in best or mn > best[k][3]:
                    best[k] = (x['n'], float(e / sd), sp, mn)
    out = defaultdict(list)
    for (dob, _), v in best.items():
        out[dob].append(v)
    return out


def main():
    SF = PR.season_files()
    dob = SP.proj_dobs()
    nm = {}
    for r in D.load(SP.ROWS):
        nm[r['p']] = r['n']
    form = json.load(open(SP.PROJ_FIT))['1y']['form']
    cols = SP.PROJ_COLS
    ix = [cols.index(c) for c in ('one', 'g0', 'p1', 'lm0', 'a', 'a2', 'am')]
    if form == 'agepos':
        ix += [cols.index(c) for c in ('d', 'm', 'fw', 'ad', 'am_', 'af')]
    X, Z, Y, SS, PID = [], [], [], [], []
    cover = {}
    for S in range(2016, 2026):
        U = uefa_z(sys.argv[1], S)
        cur, nxt = SF[S], SF.get(S + 1, {})
        fl = PR.full_f(S)
        n = 0
        for p, (mn, g, pos, lg) in cur.items():
            if p not in nxt or p not in dob or lg not in fl:
                continue
            hit = [u for u in U.get(dob[p][:10], []) if N.same(u[0], nm.get(p, ''))]
            if len(hit) != 1:
                continue
            x1, x2 = SF.get(S - 1, {}).get(p), SF.get(S - 2, {}).get(p)
            pr = [(x1 or [0, 0.0])[0], (x1 or [0, 0.0])[1], (x2 or [0, 0.0])[0], (x2 or [0, 0.0])[1]]
            age = SP.age_on(S, dob[p])
            x = SP.proj_x(mn, g, pos, age, pr, max(fl[lg], 0.05))
            X.append([x[i] for i in ix]); Z.append([hit[0][1], hit[0][1] * (age - SP.PROJ_A0)])
            Y.append(nxt[p][1]); SS.append(S + 1); PID.append(p)
            n += 1
        cover[S] = n
    X, Z, Y, SS = np.array(X, float), np.array(Z), np.array(Y), np.array(SS)
    XC = np.c_[X, Z]
    tune = SS <= 2022

    def lo(Xm):
        p = np.zeros(int(tune.sum()))
        st = SS[tune]
        for s in np.unique(st):
            tr = st != s
            p[~tr] = Xm[tune][~tr] @ np.linalg.lstsq(Xm[tune][tr], Y[tune][tr], rcond=None)[0]
        return p

    def tpl(d, pid):
        g = defaultdict(list)
        for x, k in zip(d, pid):
            g[k].append(x)
        v = np.array([np.mean(x) for x in g.values()])
        return round(float(np.mean(d)), 5), round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2), len(v)
    dt_ = np.abs(Y[tune] - lo(XC)) - np.abs(Y[tune] - lo(X))
    b0 = np.linalg.lstsq(X[tune], Y[tune], rcond=None)[0]
    b1 = np.linalg.lstsq(XC[tune], Y[tune], rcond=None)[0]
    dh = np.abs(Y[~tune] - XC[~tune] @ b1) - np.abs(Y[~tune] - X[~tune] @ b0)
    pid = np.array(PID)
    m, t, n = tpl(dt_, pid[tune])
    res = {'form': form, 'rowsBySeason': cover, 'tune': {'n': int(tune.sum()), 'd': m, 't': t, 'players': n}}
    m, t, n = tpl(dh, pid[~tune])
    by = {int(s): round(float(dh[SS[~tune] == s].mean()), 5) for s in np.unique(SS[~tune])}
    res['held'] = {'n': int((~tune).sum()), 'd': m, 't': t, 'players': n, 'bySeason': by, 'seasonsBetter': sum(1 for v in by.values() if v < 0),
                   'maeBase': round(float(np.abs(Y[~tune] - X[~tune] @ b0).mean()), 4), 'w': [round(float(x), 4) for x in b1[-2:]]}
    json.dump(res, open(os.path.join(OUT, 'l6.json'), 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
