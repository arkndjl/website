#!/usr/bin/env python3
"""Amendment check for N6 (written after N6 scored, see prereg.md Amendment 1): is the N6 gain positional value, or the
level of next season's skater ice time a game (penalty kill time, pulled goalies) leaking n+1 results through a rate
whose mean is no longer 0? (i) one constant for every skater (no positional information); (ii) N6 and base with each
team's n+1 skater ice time rescaled to 5 hours a game and goalie ice time to 1 hour a game (exposure as shares of a full lineup).
    python3 .../nhl_n6check.py -> nhl_n6check.json"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'nhl.py')).read().split('# ---------------- N4')[0]
exec(src)
from collections import defaultdict as dd
import numpy as np
RH = {}
for S in SEAS:
    rows = [dict(r, hpm=H[S][r['id']], S=S) for r in base[S]['rows']]; RH[S] = {}
    for pos, top in (('F', 13), ('D', 7), ('G', 2)):
        rest = P.depth_rest(rows, pos, top); tt = sum(r['toi'] for r in rest)
        RH[S][pos] = sum(r['hpm'] * r['toi'] for r in rest) / tt
V6 = {S: {pid: v - RH[S][base[S]['grp'][pid]] for pid, v in H[S].items()} for S in SEAS}
k = float(np.mean([-(.6 * RH[S]['F'] + .4 * RH[S]['D']) for S in SEAS]))
VC = {S: {pid: v + (k if base[S]['grp'][pid] != 'G' else 0.0) for pid, v in H[S].items()} for S in SEAS}
out = {}
def run(lab, V):
    per, pr = predict(V); a = pstats(per, pr); d = [core.r2(*zip(*per[n])) - bpair[n] for n in PAIRS]; t, p = onesided(d)
    out[lab] = dict(a, t=round(t, 2), pairsBetter=int(sum(x > 0 for x in d))); print(lab, out[lab], flush=True)
run('N6 (as scored)', V6); run('one constant for every skater (+%.3f)' % k, VC)
# (ii) rescale n+1 parts: skater hours per team = 5 x goalie hours
orig = {S: base[S]['parts'] for S in SEAS}
for S in SEAS:
    sk, gh = dd(float), dd(float)
    for pid, t, x in orig[S]: (gh if base[S]['pos'][pid] == 'G' else sk)[t] += x
    gp = {t: v[1] for t, v in base[S]['team'].items()}   # one hour a game: 5 skater hours, 1 goalie hour
    base[S]['parts'] = [(pid, t, x * (1 if base[S]['pos'][pid] == 'G' else 5) * gp.get(t, 0) / (gh[t] if base[S]['pos'][pid] == 'G' else sk[t])) for pid, t, x in orig[S]]
B2, R2_ = predict(H); bpair = {n: core.r2(*zip(*B2[n])) for n in PAIRS}; out['base, lineup-share exposure'] = pstats(B2, R2_)
print('base rescaled', out['base, lineup-share exposure'], flush=True)
run('N6, lineup-share exposure', V6); run('one constant, lineup-share exposure', VC)
json.dump(out, open(os.path.join(HERE, 'nhl_n6check.json'), 'w'), indent=1)
