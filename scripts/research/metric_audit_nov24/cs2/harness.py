#!/usr/bin/env python3
"""CS2 metric audit (Nov 24 2026): every player metric on one harness (prereg.md). -> harness.json
    python3 scripts/research/metric_audit_nov24/cs2/harness.py   (~5 min)"""
import json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
from common import P

M = C.load(); p = C.SHIP; n = len(M.pids)
MO = C.months('2024-07', C.LAST)
PUB = list(M.pub)


def values(mo, excl_half=None):
    """month-n values (month window) and board forms, as of the end of month mo. excl_half: leave that hash half of
    the month's maps out of everything (weights, ratings, windows)."""
    Ta, Tb = C.T0(mo), C.T1(mo)
    gmo = (M.gd >= Ta) & (M.gd < Tb); rmo = (M.d >= Ta) & (M.d < Tb)
    eg = er = None
    if excl_half is not None:
        eg = gmo & (M.half == excl_half); er = rmo & (M.half[M.g] == excl_half)
    beta, ml, _ = C.weights(M, Tb, eg)
    c5 = P.contributions(M, beta, ml, p['pm']); c0 = P.contributions(M, beta, ml, 0.0)
    th, _ = C.ratings_ex(M, c5, Tb, p, er)
    lift = p['ssg'] * C.sa_share_ex(M, Tb, er)
    opp = (th - lift)[M.p][M.five[M.g, 1 - M.side]].mean(1) + lift[M.p][M.five[M.g, 1 - M.side]].mean(1)
    win = rmo if er is None else rmo & ~er
    yr = (M.d >= Tb - 365) & (M.d < Tb)
    if er is not None: yr = yr & ~er
    out, rr = {}, None
    v, rr = C.wmean(M, c5 + p['opp'] * opp, win); out['season RWA'] = v + lift
    v, _ = C.wmean(M, c0 + p['opp'] * opp, win); out['box RWA (pm 0)'] = v + lift
    out['RWA rating'] = th
    board = {'RWA rating': th}
    for k in PUB:
        out[k], _ = C.wmean(M, M.pub[k], win)
        board[k], _ = C.wmean(M, M.pub[k], yr, lo=300)
    board['season RWA'] = out['season RWA']; board['box RWA (pm 0)'] = out['box RWA (pm 0)']
    return out, board, rr


METRICS = ['RWA rating', 'season RWA', 'box RWA (pm 0)'] + PUB
desc_in, desc_ho = defaultdict(dict), defaultdict(dict)   # metric -> month -> (x, y)
V, B, RR = {}, {}, {}
for mo in MO:
    Ta, Tb = C.T0(mo), C.T1(mo)
    gi = np.where((M.gd >= Ta) & (M.gd < Tb))[0]
    V[mo], B[mo], RR[mo] = values(mo)
    for k in METRICS: desc_in[k][mo] = C.mapxy(M, V[mo][k], gi)
    hx = defaultdict(lambda: ([], []))
    for h in (0, 1):
        vh, _, _ = values(mo, excl_half=h)
        gh = gi[M.half[gi] == h]
        for k in METRICS:
            x, y = C.mapxy(M, vh[k], gh); hx[k][0].append(x); hx[k][1].append(y)
    for k in METRICS: desc_ho[k][mo] = (np.concatenate(hx[k][0]), np.concatenate(hx[k][1]))
    print(mo, len(gi), {k: round(C.r2(*desc_ho[k][mo]), 3) for k in ('season RWA', 'RWA rating', 'bo3.gg rating')}, flush=True)

pairs = MO[:-1]
pred_m, pred_b, pr_own, pr_val = defaultdict(dict), defaultdict(dict), defaultdict(dict), defaultdict(dict)
FAM = {'RWA rating': 'season RWA'}
for mo, mo1 in zip(MO[:-1], MO[1:]):
    gi = np.where((M.gd >= C.T0(mo1)) & (M.gd < C.T1(mo1)))[0]
    r0, r1 = RR[mo], RR[mo1]; ok = (r0 >= 100) & (r1 >= 100)
    for k in METRICS:
        pred_m[k][mo] = C.mapxy(M, V[mo][k], gi)
        pred_b[k][mo] = C.mapxy(M, B[mo][k], gi)
        pr_own[k][mo] = (B[mo][k][ok], V[mo1][FAM.get(k, k)][ok], r1[ok])
        pr_val[k][mo] = (B[mo][k][ok], V[mo1]['box RWA (pm 0)'][ok], r1[ok])

rng = np.random.default_rng(0)


def pooled(d, keys):
    x = np.concatenate([d[m][0] for m in keys]); y = np.concatenate([d[m][1] for m in keys]); return C.r2(x, y)


def pooled_r(d, keys):
    return C.wcorr(*[np.concatenate([d[m][j] for m in keys]) for j in range(3)])


def ci(f, d, keys, B_=1000):
    ks = list(keys); s = [f(d, list(rng.choice(ks, len(ks)))) for _ in range(B_)]
    return [round(float(np.percentile(s, 5)), 3), round(float(np.percentile(s, 95)), 3)]


res = {'months': MO, 'pairs': pairs, 'nMapsDescribe': int(sum(len(desc_in['season RWA'][m][0]) for m in MO)),
       'nMapsPredict': int(sum(len(pred_b['season RWA'][m][0]) for m in pairs)), 'metrics': {}}
for k in METRICS:
    res['metrics'][k] = {
        'describeIn': round(pooled(desc_in[k], MO), 4), 'describeInCI': ci(pooled, desc_in[k], MO),
        'describeHeld': round(pooled(desc_ho[k], MO), 4), 'describeHeldCI': ci(pooled, desc_ho[k], MO),
        'predictTeamMonth': round(pooled(pred_m[k], pairs), 4),
        'predictTeamBoard': round(pooled(pred_b[k], pairs), 4), 'predictTeamBoardCI': ci(pooled, pred_b[k], pairs),
        'playerROwn': round(pooled_r(pr_own[k], pairs), 4), 'playerROwnCI': ci(pooled_r, pr_own[k], pairs),
        'playerRValue': round(pooled_r(pr_val[k], pairs), 4), 'playerRValueCI': ci(pooled_r, pr_val[k], pairs),
        'nPlayerPairs': int(sum(len(pr_own[k][m][0]) for m in pairs)),
        'describeHeldByMonth': {m: round(C.r2(*desc_ho[k][m]), 4) for m in MO},
        'predictBoardByMonth': {m: round(C.r2(*pred_b[k][m]), 4) for m in pairs}}
    print(k, {a: b for a, b in res['metrics'][k].items() if 'ByMonth' not in a}, flush=True)


# paired month-level comparisons against our own metric for each target (t by month on the month R2)
def bym(d, keys): return np.array([C.r2(*d[m]) for m in keys])


cmp = {}
for k in METRICS:
    cmp[k] = {'describeHeld_vs_seasonRWA_t': round(C.tby(bym(desc_ho[k], MO) - bym(desc_ho['season RWA'], MO)), 2),
              'predictBoard_vs_RWArating_t': round(C.tby(bym(pred_b[k], pairs) - bym(pred_b['RWA rating'], pairs)), 2)}
res['vsOurs'] = cmp
print(json.dumps(cmp, indent=0))
Path(__file__).with_name('harness.json').write_text(json.dumps(res, indent=1))
