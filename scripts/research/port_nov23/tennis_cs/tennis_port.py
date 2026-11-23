#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Port pass Nov 23 (prereg.md T1-T5, SV): tennis match-model terms against the live walk-forward blend.
    python3 scripts/research/port_nov23/tennis_cs/tennis_port.py   -> tennis_results.json beside this file
Reuses scripts/research/tennis_nov13 (base.py cached pass, mtests.py wf_logit / compare); lockbox cut 20261110."""
import os, sys, re, json, math
from collections import deque, defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'tennis_nov13'))
from mtests import *  # noqa: F401,F403  (base: M, load_rows, base_rec, live_P; arrays, wf_logit, compare)
import numpy as np
OUTD = os.path.dirname(os.path.abspath(__file__))

TB = re.compile(r'^(7-6|6-7|13-12|12-13)')


def tb_sets(score):
    """(tiebreak sets won, lost) from the match winner's side"""
    w = l = 0
    for s in (score or '').split():
        m = TB.match(s)
        if not m: continue
        a, b = map(int, m.group(1).split('-'))
        if a > b: w += 1
        else: l += 1
    return w, l


def bp_luck(mine, theirs):
    """(luck points, break points) for the player with stats `mine` against `theirs` in one match"""
    if not mine or not theirs or not mine[0] or not theirs[0]: return None
    if any(v is None for v in mine[:7] + theirs[:7]): return None
    spw = (mine[2] + mine[3]) / mine[0]
    spo = (theirs[2] + theirs[3]) / theirs[0]
    sv = mine[5] - mine[6] * spw
    rt = (theirs[6] - theirs[5]) - theirs[6] * (1 - spo)
    return sv + rt, mine[6] + theirs[6]


def features(rows):
    """key -> dict of T1-T5 inputs (winner first) for every scored row, read before the row; also SV rows"""
    tbq, bpq = defaultdict(deque), defaultdict(deque)
    last = {}            # pid -> (day, tid, rd, won)
    out = {}
    M.mark_two_week(rows)
    for r in rows:
        day = M.dnum(r[0], r[4], r[2], r[6])
        w, l = r[7], r[8]
        if M.scored(r, 2012 - M.WIN, 2100):
            f = {}
            for side, p in (('w', w), ('l', l)):
                q = tbq[p]
                while q and q[0][0] < day - 364: q.popleft()
                tw = sum(x[1] for x in q); tl = sum(x[2] for x in q)
                f['tb' + side] = (tw - tl) / (tw + tl + 10)
                q = bpq[p]
                while q and q[0][0] < day - 364: q.popleft()
                f['bp' + side] = sum(x[1] for x in q) / (sum(x[2] for x in q) + 50)
                ls = last.get(p)
                f['tt' + side] = 1.0 if ls and ls[2] == 'F' and ls[3] and ls[1] != r[6] else 0.0
                f['gap' + side] = day - ls[0] if ls else None
            out[(r[0], r[6], w, l, r[4])] = f
        tw, tl = tb_sets(r[9])
        if tw + tl:
            tbq[w].append((day, tw, tl)); tbq[l].append((day, tl, tw))
        a = bp_luck(r[10], r[11]); b = bp_luck(r[11], r[10])
        if a and b:
            bpq[w].append((day, a[0], a[1])); bpq[l].append((day, b[0], b[1]))
        last[w] = (day, r[6], r[4], True); last[l] = (day, r[6], r[4], False)
    return out


def main():
    rows, players, tn = load_rows()
    P = live_P()
    rec = base_rec(rows)
    Fb, mb = arrays(rec)
    zb = wf_logit(Fb, mb)
    feat = features(rows)
    miss = sum(1 for k in mb['key'] if k not in feat)
    print('rec', len(rec), 'missing features', miss)
    Z = {k: feat.get(k) for k in mb['key']}

    def g(k):
        return Z[k] or {}

    def col(fn):
        return np.array([fn(g(k), x) for k, x in zip(mb['key'], rec)], float)
    le = np.array([M.logit(x[1]) for x in rec])
    cands = {
        'T1_TBL': col(lambda f, x: f.get('tbw', 0) - f.get('tbl', 0)),
        'T2_BPL': col(lambda f, x: f.get('bpw', 0) - f.get('bpl', 0)),
        'T3_TTL': col(lambda f, x: f.get('ttw', 0) - f.get('ttl', 0)),
        'T4_EAR': np.array([1.0 if (x[0][0] // 100) % 100 == 1 else 0.0 for x in rec]) * le,
        'T5_RET': np.array([1.0 if any((g(k).get(s) or 0) >= 180 for s in ('gapw', 'gapl')) else 0.0
                            for k in mb['key']]) * le,
    }
    res = {}
    for nm, c in cands.items():
        F = np.column_stack([Fb, c])
        zt = wf_logit(F, mb)
        o = compare(zb, mb, zt, mb, nm)
        o['flagged'] = int((c != 0).sum())
        # last walk-forward weight of the new column (2026 fit) for the sign
        res[nm] = o
        print(nm, o['tune'], o['held'], o['held_better'], o['flagged'])
    json.dump(res, open(os.path.join(OUTD, "tennis_results.json"), 'w'), indent=1)


if __name__ == '__main__':
    main()
