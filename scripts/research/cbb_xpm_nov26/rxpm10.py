#!/usr/bin/env python3
"""rXPM round 3 amendment 5: H = BPM's within-team split on GBPM's team totals. python3 rxpm10.py -> rxpm10.json"""
import json, math, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gl, rxpm7 as R7
from rxpm4 import paired, YEARS, COL
from rxpm5 import loso_slope_sse, r2
HCA, B = pickle.load(open(os.path.join(gl.GB, 'built.pkl'), 'rb'))
RW = R7.RW


def hvals(y):
    st = B[y]['st']; nb = defaultdict(float); ng = defaultdict(float); den = defaultdict(float)
    for k, q in st.items():
        if q['bpm'] is None: continue
        nb[k[1]] += q['bpm'] * q['min']; ng[k[1]] += q['gbpm'] * q['min']; den[k[1]] += q['min']
    return {k: {'bpm': q['bpm'], 'gbpm': q['gbpm'], 'h': q['bpm'] + (ng[k[1]] - nb[k[1]]) / den[k[1]], 'e': q['min'], 'name': q['name'], 'rot': q['rot']}
            for k, q in st.items() if q['bpm'] is not None}


FV = {y: hvals(y) for y in YEARS}
out = {}
# (i) who sat out: H = BPM on these designs
out['who sat out: H (= BPM) vs GBPM'] = {}
for k in RW:
    sb, sg = {}, {}
    for y in YEARS:
        tr = [s for s in YEARS if s != y]; yy = np.concatenate([RW[k][s][:, 0] for s in tr])
        for c, S in (('bpm', sb), ('gbpm', sg)):
            x = np.concatenate([RW[k][s][:, COL[c]] for s in tr]); b = float(x @ yy / (x @ x)); S[y] = float(((RW[k][y][:, 0] - b * RW[k][y][:, COL[c]]) ** 2).sum())
    tot = sum(float((RW[k][y][:, 0] ** 2).sum()) for y in YEARS); t, p, n = paired([sg[y] - sb[y] for y in YEARS])
    out['who sat out: H (= BPM) vs GBPM'][k] = {'R2': {'GBPM': round(1 - sum(sg.values()) / tot, 5), 'H': round(1 - sum(sb.values()) / tot, 5)}, 't': t, 'p': round(p, 5), 'seasonsBetter': n, 'of': 19,
                                              'bySeason': {y: [round(1 - sg[y] / float((RW[k][y][:, 0] ** 2).sum()), 5), round(1 - sb[y] / float((RW[k][y][:, 0] ** 2).sum()), 5)] for y in YEARS}}
    print(k, {a: b for a, b in out['who sat out: H (= BPM) vs GBPM'][k].items() if a != 'bySeason'}, flush=True)
# C
C = {}
for tgt in ('em', 'wab_g', 'wp'):
    C[tgt] = {}; sse = {}
    for m in ('bpm', 'gbpm', 'h'):
        rows = {}
        for y in YEARS:
            num = defaultdict(float); den = defaultdict(float)
            for (pid, t), v in FV[y].items(): num[t] += v[m] * v['e']; den[t] += v['e']
            ts = [t for t in num if t in B[y]['tr']]; x = np.array([5 * num[t] / den[t] for t in ts]); yy = np.array([B[y]['tr'][t][tgt] for t in ts]); rows[y] = (x - x.mean(), yy - yy.mean())
        L = loso_slope_sse(rows); C[tgt][m] = r2(L); sse[m] = {y: L[y][0] for y in L}
        C[tgt][m + ' bySeason'] = {y: round(1 - L[y][0] / L[y][1], 4) for y in L}
    for b in ('bpm', 'gbpm'):
        t, p, n = paired([sse[b][y] - sse['h'][y] for y in YEARS]); C[tgt]['h vs ' + b] = {'t': t, 'seasonsBetter': n}
out['C'] = C; print('C', {t: {k: v for k, v in e.items() if 'bySeason' not in k} for t, e in C.items()}, flush=True)
# G
sd = {}
for m in ('bpm', 'gbpm', 'h'):
    x = np.array([v[m] for y in YEARS for v in FV[y].values() if v['e'] >= 300]); w = np.array([v['e'] for y in YEARS for v in FV[y].values() if v['e'] >= 300])
    mu = np.average(x, weights=w); sd[m] = round(float(math.sqrt(np.average((x - mu) ** 2, weights=w))), 3)
X = [(v['h'], v['bpm'], v['gbpm']) for y in YEARS for v in FV[y].values() if v['e'] >= 300]
out['G'] = {'sd': sd, 'r(H,BPM)': round(float(np.corrcoef([a for a, _, _ in X], [b for _, b, _ in X])[0, 1]), 4), 'r(H,GBPM)': round(float(np.corrcoef([a for a, _, _ in X], [c for _, _, c in X])[0, 1]), 4),
            'mean |H - BPM|': round(float(np.mean([abs(a - b) for a, b, _ in X])), 3)}
print('G', out['G'], flush=True)
# N
sys.path.insert(0, os.path.join(gl.ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb'))
import audit as A
def vals(n, m):
    num = defaultdict(float); den = defaultdict(float)
    for (pid, t), v in FV[n].items(): num[pid] += v[m] * v['e']; den[pid] += v['e']
    return {pid: num[pid] / den[pid] for pid in num if pid in A.S[n]['pl']}
sc = {m: A.predict(lambda n: vals(n, m))[2] for m in ('bpm', 'gbpm', 'h')}
# player r against the next season's own metric and against next-season H
def own_r(m):
    xs, ys, ws = [], [], []
    for n in A.PAIRS:
        a, b = vals(n, m), vals(n + 1, m)
        for pid, v in b.items():
            e = A.S[n + 1]['pl'][pid]['e']
            if pid in a and e >= A.MINN: xs.append(a[pid]); ys.append(v); ws.append(e)
    return round(A.core.wcorr(xs, ys, ws), 4)
N = {m: {'teamR2': sc[m]['teamR2'], 'playerR_vsNextBPM': sc[m]['playerR_vsBPM'], 'playerR_vsOwnNext': own_r(m), 'byPair': sc[m]['byPair']} for m in sc}
for b in ('bpm', 'gbpm'):
    t, p, n = paired([sc['h']['byPair'][k] - sc[b]['byPair'][k] for k in A.PAIRS]); N['h vs ' + b] = {'t': t, 'pairsBetter': n, 'of': 14}
out['N'] = N; print('N', {k: {a: b for a, b in v.items() if a != 'byPair'} for k, v in N.items()}, flush=True)
# B: odd-game values -> even-game mean adjusted margin (and reverse)
def test_b():
    M = ('gb', 'bl', 'h'); rows = {m: {} for m in M}
    for y in YEARS:
        st, tg = B[y]['st'], B[y]['tg']; acc = {m: ([], []) for m in M}
        for H in (0, 1):
            am = defaultdict(list); ao = defaultdict(list)
            for (d, t), r in tg.items(): (am if r['odd'] == (H == 0) else ao)[t].append(r['a'])
            num = defaultdict(float); den = defaultdict(float)
            for k, q in st.items():
                h = q['h'][H]
                if h['e'] > 0: num[k[1]] += h['gb'] / h['e'] * h['min']; den[k[1]] += h['min']
            V = {}
            for k, q in st.items():
                h = q['h'][H]; t = k[1]
                if h['e'] <= 0 or t not in am: continue
                g = h['gb'] / h['e']; V[k] = {'gb': g, 'bl': g + (np.mean(am[t]) - 5 * num[t] / den[t]) / 5, 'e': h['e']}
                # H from one half: BPM-like deviations (= the same game-BPM deviations; the shift is one number a team) + the half's GBPM team mean = odd-game GBPM
                V[k]['h'] = V[k]['bl'] - (np.mean(am[t]) - 5 * num[t] / den[t]) / 5
            fill = {m: float(np.mean([v[m] for v in V.values() if v['e'] < 150])) for m in M}
            n2 = {m: defaultdict(float) for m in M}; d2 = defaultdict(float)
            for k, q in st.items():
                mn = q['h'][1 - H]['min']
                if mn <= 0: continue
                d2[k[1]] += mn
                for m in M: n2[m][k[1]] += mn * (V[k][m] if k in V else fill[m])
            ts = [t for t in d2 if len(ao[t]) >= 5]
            for m in M:
                x = np.array([5 * n2[m][t] / d2[t] for t in ts]); yy = np.array([np.mean(ao[t]) for t in ts]); acc[m][0].append(x - x.mean()); acc[m][1].append(yy - yy.mean())
        for m in M: rows[m][y] = (np.concatenate(acc[m][0]), np.concatenate(acc[m][1]))
    L = {m: loso_slope_sse(rows[m]) for m in M}
    return {m: r2(L[m]) for m in M}
out['B'] = test_b(); out['B note'] = 'within one half the game log gives one within-team split (game BPM), so H from a half is odd-game GBPM: equal by construction'
print('B', out['B'], flush=True)
json.dump(out, open(os.path.join(HERE, 'rxpm10.json'), 'w'), indent=1)
