# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L4: exposure terms in the xMV log fit (national-team appearances, UEFA minutes, goals over xG), nested
leave-one-season-out as scripts/research/leads_nov14/s2_xmv.py. Prereg:
/mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/leads_nov14/s2_snaps.py            # snapshot rows first
    python3 scripts/research/sweep_nov19/soccer/l4_xmv.py
"""
import bisect
import csv
import datetime as dt
import gzip
import json
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCR)
import soccer_data as D
import soccer_intl as I
import soccer_mv as MV
import soccer_players as SP

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')
DUMP = os.path.join(SCR, '.cache', 'soccer_prospects', 'dump')
NEW = ['nt12', 'nt24', 'ntm', 'ue1', 'gx1', 'ax1']


def day_add(d, k):
    return (dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat()


def exposure():
    """player TM id -> sorted squad-page days, and the days that were World Cup / continental finals matches"""
    C = I.callups()
    rows = pickle.load(open(os.path.join(OUT, 'intl_rows_espn.pkl'), 'rb'))
    cat = {}
    for r in rows:
        cat[(r['day'], r['h'], r['a'])] = cat[(r['day'], r['a'], r['h'])] = r['cat']
    allp, maj = defaultdict(list), defaultdict(list)
    for t, v in C['sq'].items():
        for day, gid, opp, sq in v:
            c = cat.get((day, t, opp)) or cat.get((day_add(day, 1), t, opp)) or cat.get((day_add(day, -1), t, opp))
            for p in sq[0::2]:
                allp[p].append(day)
                if c in ('wc', 'cf'):
                    maj[p].append(day)
    for m in (allp, maj):
        for v in m.values():
            v.sort()
    return allp, maj


def uefa_minutes():
    """(player TM id, season S) -> Champions League + Europa League minutes in season S (Jul to Jun)"""
    out = defaultdict(float)
    with gzip.open(os.path.join(DUMP, 'appearances.csv.gz'), 'rt') as fh:
        for r in csv.DictReader(fh):
            if r['competition_id'] in ('CL', 'EL') and r['date'] <= '2026-06-30':
                y, m = int(r['date'][:4]), int(r['date'][5:7])
                out[(int(r['player_id']), y + 1 if m >= 7 else y)] += float(r['minutes_played'] or 0)
    return out


def count(v, lo, hi):
    return bisect.bisect_left(v, hi) - bisect.bisect_left(v, lo) if v else 0


def tstat(d, keys):
    m = float(np.mean(d))
    gs = defaultdict(float)
    for x, k in zip(d, keys):
        gs[k] += x - m
    se = math.sqrt(sum(v * v for v in gs.values())) / len(d)
    return round(m, 6), round(m / se, 2) if se else 0.0


def main():
    F = json.load(open(MV.FIT))
    rows = [r for r in D.load(os.path.join(OUT, 'mv_snaps_fringe.json.gz')) if r.get('dob') and r['S'] <= 2026]
    for r in rows:
        r['age'] = MV.age_of(r['day'], r['dob'])
    MV.levels(rows)
    rows = [r for r in rows if r.get('mv') and 15 <= r['age'] <= 42]
    allp, maj = exposure()
    UE = uefa_minutes()
    over = defaultdict(lambda: [0.0, 0.0])
    for r in D.load(SP.ROWS):
        e = over[(str(r['p']), r['S'])]
        e[0] += r['g'] - r['x']; e[1] += r['as'] - r['xA']
    for r in rows:
        tm = int(r['tm'])
        d = r['day']
        r['nt12'] = math.log1p(count(allp.get(tm), day_add(d, -365), d))
        r['nt24'] = math.log1p(count(allp.get(tm), day_add(d, -730), d))
        r['ntm'] = math.log1p(count(maj.get(tm), day_add(d, -730), d))
        r['ue1'] = UE.get((tm, r['S'] - 1), 0.0) / 900
        o = over.get((str(r['p']), r['S'] - 1), (0.0, 0.0))
        r['gx1'], r['ax1'] = o
    keep = F['feats']
    res = {'feats': keep, 'new': NEW, 'snap': {}}
    allrows = []
    for md in MV.SNAPS:
        rs = [r for r in rows if r['day'][5:] == MV.snapdate(2020, md).isoformat()[5:]]
        fs = [MV.feats(r) for r in rs]
        X0 = np.array([[1.0] + [f[k] for k in keep] for f in fs])
        XA = np.c_[X0, np.array([[r[k] for k in NEW] for r in rs])]
        XB = np.c_[X0, np.array([[r[k] for k in NEW if k != 'ue1'] for r in rs])]
        y = np.log([r['mv'] for r in rs])
        S = np.array([r['S'] for r in rs])

        def nested(X):
            out = np.zeros(len(y))
            seasons = np.unique(S)
            for s in seasons:
                tr = S != s
                p_s = X[~tr] @ MV.solve(X[tr], y[tr])
                pin = np.zeros(len(y))
                for t in seasons:
                    if t == s:
                        continue
                    tr2 = tr & (S != t)
                    pin[S == t] = X[S == t] @ MV.solve(X[tr2], y[tr2])
                knots = MV.calibration(pin[tr], y[tr]) + [MV.tail_slope(pin[tr], y[tr])]
                out[~tr] = MV.calibrate(p_s, knots)
            return out
        key = f'{md[0]:02d}-{md[1]:02d}'
        pb, pa, pB = nested(X0), nested(XA), nested(XB)
        res['snap'][key] = {'n': len(y), 'baseMse': round(float(np.mean((y - pb) ** 2)), 4), 'aMse': round(float(np.mean((y - pa) ** 2)), 4),
                            'bMse': round(float(np.mean((y - pB) ** 2)), 4),
                            'wA': {k: round(float(v), 4) for k, v in zip(NEW, MV.solve(XA, y)[-len(NEW):])}}
        for r, yy, a, b, c in zip(rs, y, pb, pa, pB):
            allrows.append((key, r, yy, a, b, c))
        print(key, res['snap'][key], flush=True)
    y = np.array([x[2] for x in allrows])
    S = np.array([x[1]['S'] for x in allrows])
    pb = np.array([x[3] for x in allrows])
    var = float(np.var(y))
    end = {(x[1]['S'], x[1]['p']): x[1]['mv'] for x in allrows if x[0] == '07-01'}
    gi = [i for i, x in enumerate(allrows) if x[0] == '10-24' and (x[1]['S'], x[1]['p']) in end]
    tgt = np.array([math.log(end[(allrows[i][1]['S'], allrows[i][1]['p'])] / allrows[i][1]['mv']) for i in gi])
    gS = S[gi]
    rng = np.random.default_rng(7)
    for lab, col in (('A', 4), ('B', 5)):
        pc = np.array([x[col] for x in allrows])
        d = (y - pc) ** 2 - (y - pb) ** 2
        m, t = tstat(list(d), list(S))
        per = {int(s): round(float(d[S == s].mean()), 5) for s in np.unique(S)}
        g0, g1 = (pb - y)[gi], (pc - y)[gi]
        s0, s1 = float(np.polyfit(g0, tgt, 1)[0]), float(np.polyfit(g1, tgt, 1)[0])
        boot = []
        seas = np.unique(gS)
        for _ in range(300):
            pick = rng.choice(seas, len(seas))
            ix = np.concatenate([np.where(gS == s)[0] for s in pick])
            boot.append(float(np.polyfit(g1[ix], tgt[ix], 1)[0]) - float(np.polyfit(g0[ix], tgt[ix], 1)[0]))
        res[lab] = {'n': len(y), 'baseMse': round(float(np.mean((y - pb) ** 2)), 5), 'candMse': round(float(np.mean((y - pc) ** 2)), 5),
                    'baseR2': round(1 - float(np.mean((y - pb) ** 2)) / var, 4), 'candR2': round(1 - float(np.mean((y - pc) ** 2)) / var, 4),
                    'd': m, 't': t, 'seasonsBetter': sum(1 for v in per.values() if v < 0), 'seasons': len(per), 'bySeason': per,
                    'gapSlopeBase': round(s0, 4), 'gapSlopeCand': round(s1, 4), 'gapSlopeDiffSe': round(float(np.std(boot)), 4), 'gapN': len(gi)}
    json.dump(res, open(os.path.join(OUT, 'l4_xmv.json'), 'w'), indent=1)
    print(json.dumps({k: res[k] for k in ('A', 'B')}, indent=1))


if __name__ == '__main__':
    main()
