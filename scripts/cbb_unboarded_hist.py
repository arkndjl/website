#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""D-I careers of last season's players the preseason board left off (Nov 19 2026) -> scripts/data/cbb_unboarded_hist.json.gz.

    python3 scripts/cbb_unboarded_hist.py          # Barttorvik season files (not reachable from Actions: run here, commit)
    python3 scripts/cbb_unboarded_hist.py --test   # last season: such players' BPM against both preseason grades

The preseason board is frozen in October. A player it left off who then plays (a senior granted another year after
the board was built, 35 of the 58 unboarded players on Nov 18 2026) was graded by scripts/cbb_live.py unboarded() as
a newcomer with no history. This file keeps the careers (the columns the model reads, cbb_live.KEEP) of every player
in last season's Barttorvik file who is not on the board, so unboarded() grades him as the returner he is: the
board's own returner model on his last seasons, then this season's line by minutes, as every boarded returner.
Test (--test): players listed Sr in 2024-25 who played again in 2025-26 (n 391), 2025-26 BPM (minutes-weighted) against the
preseason xBPM as a newcomer and as a returner: RMSE 4.26 -> 2.70 (t -6.8).
"""
import gzip, json, os, sys
import numpy as np
import cbb_data as D
import cbb_fit as F
import cbb_live as L

OUT = os.path.join(D.HERE, 'data', 'cbb_unboarded_hist.json.gz')
BACK = 5   # seasons kept


def careers(last, back=BACK):
    """pid -> career (seasons oldest first) from Barttorvik's files for the `back` seasons ending `last`, players in `last`"""
    by = {}
    for y in range(last - back + 1, last + 1):
        for r in D.load_bt(y):
            if r.get('pid') and (r.get('mp') or 0) * (r.get('gp') or 0) > 0:
                by.setdefault(str(r['pid']).split('.')[0], []).append(r)
    out = {}
    for pid, rs in by.items():
        rs.sort(key=lambda r: r['year'])
        if rs[-1]['year'] != last: continue
        dob = next((r['dob'] for r in reversed(rs) if r.get('dob') and len(r['dob']) == 10), None)
        out[pid] = {'pid': pid, 'name': rs[-1]['name'], 'key': rs[-1]['key'], 'dob': dob, 'rec': None, 'seasons': [{k: r.get(k) for k in L.KEEP} for r in rs]}
    return out


def build():
    prior = json.load(gzip.open(L.PRIOR))
    on = {str(m['pid']).split('.')[0] for m in prior['careers'] if m.get('pid')}
    C = {p: c for p, c in careers(L.SEASON - 1).items() if p not in on}
    with gzip.open(OUT, 'wt') as fh:
        json.dump({'season': L.SEASON, 'keep': L.KEEP, 'players': {p: {'name': c['name'], 'key': c['key'], 'dob': c['dob'], 'seasons': L.pack(c['seasons'])}
                                                                    for p, c in sorted(C.items())}}, fh, separators=(',', ':'))
    print('wrote', OUT, len(C), 'players off the board with a', L.SEASON - 1, 'line')


def test():
    """last season (2025-26 board season): Sr in 2024-25 with a 2025-26 line. A: preseason xBPM as a newcomer (what
    unboarded() read); B: as a returner on his career. Target: his 2025-26 BPM, minutes-weighted."""
    S = L.SEASON - 1
    fit = json.load(open(F.OUT))
    now = {str(r['pid']).split('.')[0]: r for r in D.load_bt(S) if (r.get('mp') or 0) * (r.get('gp') or 0) > 0 and r.get('bpm') is not None}
    C = careers(S - 1)
    A, B, y, w = [], [], [], []
    for pid, c in C.items():
        r = now.get(pid)
        if not r or c['seasons'][-1]['yr'] != 'Sr': continue
        srow = {'year': S, 'team': r['team'], 'conf': r['conf'], 'yr': 'Sr', 'hti': r['hti'], 'rec': None, 'role': r.get('role')}
        fa = F.features({'pid': pid, 'name': c['name'], 'dob': c['dob'], 'rec': None, 'seasons': [srow]}, 0)
        fb = F.features(dict(c, seasons=c['seasons'] + [srow]), len(c['seasons']))
        A.append(L.xbpm_of(fa, fit)); B.append(L.xbpm_of(fb, fit)); y.append(r['bpm']); w.append(r['mp'] * r['gp'])
    A, B, y, w = map(np.array, (A, B, y, w))
    rm = lambda p, m=None: float(np.sqrt((w * (p - y) ** 2)[m].sum() / w[m].sum())) if m is not None else float(np.sqrt((w * (p - y) ** 2).sum() / w.sum()))
    d = w * ((B - y) ** 2 - (A - y) ** 2)
    big = w >= 400
    res = {'n': int(len(y)), 'rmseNewcomer': round(rm(A), 3), 'rmseReturner': round(rm(B), 3), 't': round(float(d.mean() / d.std() * np.sqrt(len(d))), 2),
           'n400': int(big.sum()), 'rmseNewcomer400': round(rm(A, big), 3), 'rmseReturner400': round(rm(B, big), 3),
           'meanA': round(float(np.average(A, weights=w)), 2), 'meanB': round(float(np.average(B, weights=w)), 2), 'meanBPM': round(float(np.average(y, weights=w)), 2)}
    print(json.dumps(res, indent=1))
    return res


if __name__ == '__main__':
    test() if '--test' in sys.argv else build()
