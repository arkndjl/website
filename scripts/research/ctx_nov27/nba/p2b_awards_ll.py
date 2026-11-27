"""P2 guard: winner log loss of the as-of award races (scripts/awards_asof.py nba_build, in-repo boxes 2019-2026, 'box'
arm, same seeds) with the games-left rate on the Nov 4 shrink (live) and on the pXPM form.  -> p2b_awards_ll.json"""
import json, math, os, sys
import numpy as np
import common as C
import awards_asof as AA, awards as AW, awards_nba as A
import p2_awards_rate as P2
X = C.X
AA.NBA_FIRST, AA.VARS = 2019, ('box',)
SIMS = int(next((a[7:] for a in sys.argv if a.startswith('--sims=')), 2000))
LIVE, PRI0 = X.shrink, X.shrink_prior
cur = {}


def prior(S):
    cur['S'] = S; return PRI0(S)


def pshrink(p, games, pri=None):
    v, d = P2.pform(p['id'], cur['S'], p['mp'], p['oxpm'], p['dxpm'], games, True)
    p['sxpm'], p['sdxpm'] = v, d
    return p


X.shrink_prior = prior
a = AA.nba_build(SIMS)
X.shrink = pshrink
b = AA.nba_build(SIMS)
X.shrink = LIVE
key = lambda r: (r['s'], r['aw'], r['cp'])
B = {key(r): r for r in b}
la, lb, ss, aw = [], [], [], []
for r in a:
    q = B[key(r)]; la.append(-math.log(AA.pw(r, 0))); lb.append(-math.log(AA.pw(q, 0))); ss.append(r['s']); aw.append(r['aw'])
la, lb, ss, aw = np.array(la), np.array(lb), np.array(ss), np.array(aw)
res = {'sims': SIMS, 'rows': len(la), 'll': [round(float(la.mean()), 4), round(float(lb.mean()), 4)], 't': round(C.tstat(la - lb), 2),
       'seasons': f"{sum(lb[ss == s].mean() < la[ss == s].mean() for s in set(ss))}/{len(set(ss))}",
       'by award': {k: [round(float(la[aw == k].mean()), 4), round(float(lb[aw == k].mean()), 4)] for k in sorted(set(aw))}}
print(json.dumps(res)); json.dump(res, open(os.path.join(C.HERE, 'p2b_awards_ll.json'), 'w'), indent=1)
