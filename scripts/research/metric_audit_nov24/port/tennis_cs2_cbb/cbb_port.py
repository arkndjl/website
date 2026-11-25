#!/usr/bin/env python3
"""CBB port round (prereg.md B-P1, B-D1, B-C1) -> cbb_port.json. Barttorvik player game logs (all_advgames,
scripts/.cache/cbb/games/<y>.json.gz, 2017-2026: no 2026-27) on the round-1 harness (metric_audit_nov24/cbb/audit.py).
Game row: 0 date, 5 opponent, 8 minutes, 43 possessions a 100 minutes (fv_drivers weight), 44 game BPM, 46 site, 51 pid."""
import gzip, json, math, os, sys, zlib
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'cbb')))
import audit as A  # noqa: E402
GL = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '.cache', 'cbb', 'games'))
GY = list(range(2017, 2027))
LOGS = {}
for y in GY:
    rk = {r[1]: int(r[0]) for r in json.load(open(os.path.join(A.C, f'tr{y}.json')))}
    L = []
    for r in json.load(gzip.open(os.path.join(GL, f'{y}.json.gz'), 'rt')):
        try:
            mn, gb = float(r[8] or 0), r[44]
            if mn <= 0 or gb is None: continue
            L.append((str(r[51]), str(r[0]), mn, mn * float(r[43] or 0) / 100, float(gb), rk.get(r[5], 999), r[46], r[47]))
        except (TypeError, ValueError):
            continue
    LOGS[y] = L
    print(y, len(L), flush=True)
out = {}

# ---------------------------------------------------------------- B-P1 level weighting (predict)
PAIRS = [n for n in A.PAIRS if n in GY]


def wgbpm(y, lam):
    num, den = defaultdict(float), defaultdict(float)
    for pid, d, mn, w, gb, rk, site, t in LOGS[y]:
        f = w * (lam if rk > 200 else 1.0); num[pid] += f * gb; den[pid] += f
    return {pid: num[pid] / den[pid] for pid in num if den[pid] > 0}


# sanity: per-game GBPM mean vs the season csv's GBPM
g1 = wgbpm(2024, 1.0); pl = A.S[2024]['pl']
both = [p for p in g1 if p in pl and pl[p]['e'] > 200]
out['sanity_r_logGBPM_vs_csvGBPM_2024'] = round(float(np.corrcoef([g1[p] for p in both], [pl[p]['gbpm'] for p in both])[0, 1]), 4)
GRID = [1.0, .85, .7, .5]


def predict(vnf):
    per, pp = {}, {}
    for n in PAIRS: per[n], pp[n] = A.predict_rows(n, vnf(n), 'bpm')
    return per, pp, A.predict_score(per, pp, PAIRS)


G = {lam: predict(lambda n, lam=lam: wgbpm(n, lam)) for lam in GRID}
base = G[1.0][2]
per, pp, ch = {}, {}, {}
for n in PAIRS:
    oth = [m for m in PAIRS if m != n]
    best = max(GRID, key=lambda g: A.core.r2(*zip(*[r for m in oth for r in G[g][0][m]])))
    per[n], pp[n], ch[n] = G[best][0][n], G[best][1][n], best
sc = A.predict_score(per, pp, PAIRS)
d = [sc['byPair'][n] - base['byPair'][n] for n in PAIRS]
t, p = A.paired_t(d)
bpm = predict(lambda n: A.vals(n, 'bpm'))[2]
out['B-P1'] = {'target': 'next-season team adjEM R2', 'pairs': PAIRS, 'before': base['teamR2'], 'after': sc['teamR2'],
               'gridR2': {str(g): G[g][2]['teamR2'] for g in GRID}, 'chosen': {str(k): v for k, v in ch.items()},
               'pairsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': p, 'seasonBPM_sameYears': bpm['teamR2'],
               'playerR_vsBPM': [base['playerR_vsBPM'], sc['playerR_vsBPM']]}
print('B-P1', out['B-P1'], flush=True)

# ---------------------------------------------------------------- B-D1 displayed rate shrink (describe, split half)
KG = [0, 50, 100, 200, 400]


def halves(y):
    a = defaultdict(lambda: [0.0, 0.0]); b = defaultdict(lambda: [0.0, 0.0])
    for pid, d, mn, w, gb, rk, site, t in LOGS[y]:
        q = a if zlib.crc32(d.encode()) & 1 else b
        q[pid][0] += mn * gb; q[pid][1] += mn
    return a, b


SSE = {}
for y in GY:
    a, b = halves(y)
    m = sum(v[0] for v in a.values()) / sum(v[1] for v in a.values())
    ps = [p for p in a if p in b and a[p][1] > 0 and b[p][1] > 0]
    yb = np.array([b[p][0] / b[p][1] for p in ps]); wb = np.array([b[p][1] for p in ps])
    SSE[y] = {}
    for k in KG:
        xa = np.array([(a[p][0] + k * m) / (a[p][1] + k) for p in ps])
        SSE[y][k] = float(np.sum(wb * (yb - xa) ** 2) / wb.sum())
ch, dd = {}, []
for y in GY:
    oth = [s for s in GY if s != y]
    k = min(KG, key=lambda k: sum(SSE[s][k] for s in oth)); ch[y] = k
    dd.append(SSE[y][0] - SSE[y][k])            # positive = shrunk better
t, p = A.paired_t(dd)
out['B-D1'] = {'target': 'half-B GBPM, minutes-weighted MSE of the half-A rate', 'before': round(float(np.mean([SSE[y][0] for y in GY])), 3),
               'after': round(float(np.mean([SSE[y][ch[y]] for y in GY])), 3), 'chosen': {str(k): v for k, v in ch.items()},
               'byK': {str(k): round(float(np.mean([SSE[y][k] for y in GY])), 3) for k in KG}, 'seasonsBetter': int(sum(x > 0 for x in dd)), 't': t, 'p': p}
print('B-D1', out['B-D1'], flush=True)

# ---------------------------------------------------------------- B-C1 home-court player offsets: plausibility gate
xs, ys = [], []
for y in GY:
    g = defaultdict(list)
    for pid, d, mn, w, gb, rk, site, t in LOGS[y]:
        if site in ('H', 'A'): g[pid].append((d, site, mn, gb))
    for pid, L in g.items():
        L.sort(); s = [{'H': [0, 0], 'A': [0, 0]}, {'H': [0, 0], 'A': [0, 0]}]
        cnt = {'H': 0, 'A': 0}
        for d, site, mn, gb in L:
            q = s[cnt[site] % 2][site]; cnt[site] += 1; q[0] += mn * gb; q[1] += mn
        if all(s[i][z][1] >= 100 for i in (0, 1) for z in 'HA'):
            xs.append(s[0]['H'][0] / s[0]['H'][1] - s[0]['A'][0] / s[0]['A'][1]); ys.append(s[1]['H'][0] / s[1]['H'][1] - s[1]['A'][0] / s[1]['A'][1])
r = float(np.corrcoef(xs, ys)[0, 1])
out['B-C1'] = {'splitHalf_r_homeMinusAway': round(r, 4), 'players': len(xs), 'gate': .10, 'tested': bool(r >= .10),
               'meanHomeMinusAway': round(float(np.mean(xs + ys)), 3)}
print('B-C1', out['B-C1'], flush=True)

# Holm over the two tested candidates
c = [k for k in ('B-P1', 'B-D1')]
o = sorted(c, key=lambda k: out[k]['p']); stop = False
for i, k in enumerate(o):
    adj = min(1.0, out[k]['p'] * (len(o) - i)); out[k]['pHolm'] = round(adj, 4)
    out[k]['pass'] = bool(not stop and adj < .05 and out[k]['t'] > 0)
    if adj >= .05: stop = True
json.dump(out, open(os.path.join(HERE, 'cbb_port.json'), 'w'), indent=1)
