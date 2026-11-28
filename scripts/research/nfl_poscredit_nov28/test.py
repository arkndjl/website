# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL position credit (Nov 28 2026, Noah: "should OVR be balanced by position for football? it's entirely skill
position players at the top"). If the WAR board credits each position group correctly, a point of a group's projected
XP is worth a point of next season's team margin, the same for every group. Test, leaving one target season out
(targets 2017-25):
  X_g   sum over next season's roster in group g of this season's shrunk rate (rXP/60 shrunk to the group mean by snaps,
        K per group from data/nfl_rate_fit.json) x next season's snaps / 60, a game; newcomers at the group mean
  pooled  margin = a + b x sum_g X_g              (the board's assumption: one exchange rate for every group)
  split   margin = a + sum_g b_g X_g               (a slope per group)
  rb      margin = a + b x (sum_g X_g - X_RB) + c x X_RB   (RB on its own slope; added after split's RB slope came out
          negative, so it is a second look on the same seasons, not a pre-registered test)
split beats pooled on held-out squared error at paired t <= -2 -> the credit split is off, and the slopes say where.
python3 scripts/research/nfl_poscredit_nov28/test.py -> research/nfl_poscredit.json"""
import json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'ovr_nov28'))
from engine import wls, paired_t

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
FIT = json.load(open(os.path.join(ROOT, 'data', 'nfl_rate_fit.json')))
KG = FIT['model']['K']
G = sorted(KG)
D = {y: json.load(open(os.path.join(CACHE, f'poscredit_{y}.json'))) for y in range(2016, 2026)}


def rate(r): return r['pts'] / r['sn'] * 60 if r['sn'] else 0.0


def gmean(ys):
    a = {}
    for y in ys:
        for r in D[y]['rows']:
            s = a.setdefault(r['grp'], [0.0, 0.0]); s[0] += r['pts']; s[1] += r['sn']
    return {g: v[0] / v[1] * 60 for g, v in a.items()}


def team_x(y, m):
    """features for target season y + 1 from season y's rates"""
    prev = {r['id']: r for r in D[y]['rows']}
    X = {}
    for r in D[y + 1]['rows']:
        p = prev.get(r['id']); g = r['grp']
        if g not in KG: continue
        rt = (rate(p) * p['sn'] + m.get(g, 0) * KG[g]) / (p['sn'] + KG[g]) if p and p['grp'] == g else (
             (rate(p) * p['sn'] + m.get(p['grp'], 0) * KG.get(p['grp'], 1000)) / (p['sn'] + KG.get(p['grp'], 1000)) if p else m.get(g, 0))
        X.setdefault(r['tm'], {}).setdefault(g, 0.0)
        X[r['tm']][g] += rt * r['sn'] / 60 / 17
    return X


def rows(y, m):
    X = team_x(y, m); M = D[y + 1]['margin']
    return [([X[t].get(g, 0.0) for g in G], M[t]) for t in X if t in M]


def main():
    T = list(range(2016, 2025)); err = {'pooled': [], 'split': [], 'rb': []}
    iRB = G.index('RB')
    for ho in T:
        tr = [y for y in T if y != ho]
        m = gmean([y for y in tr if y <= ho] or tr)
        TR = [r for y in tr for r in rows(y, gmean([q for q in tr]))]
        TE = rows(ho, m)
        for k in err:
            f = (lambda x: [sum(x)]) if k == 'pooled' else (lambda x: [sum(x) - x[iRB], x[iRB]]) if k == 'rb' else (lambda x: x)
            b = wls([[1.0] + f(x) for x, _ in TR], [v for _, v in TR], [1.0] * len(TR), ridge=1e-3)
            err[k].append(st.mean((v - sum(bi * xi for bi, xi in zip(b, [1.0] + f(x)))) ** 2 for x, v in TE))
    m = gmean(T); ALL = [r for y in T for r in rows(y, m)]
    bs = wls([[1.0] + x for x, _ in ALL], [v for _, v in ALL], [1.0] * len(ALL), ridge=1e-3)
    bp = wls([[1.0, sum(x)] for x, _ in ALL], [v for _, v in ALL], [1.0] * len(ALL), ridge=1e-3)
    # standard errors of the split slopes by bootstrap over team-seasons
    import random; random.seed(7); boot = []
    for _ in range(300):
        S = [random.choice(ALL) for _ in ALL]
        boot.append(wls([[1.0] + x for x, _ in S], [v for _, v in S], [1.0] * len(S), ridge=1e-3)[1:])
    se = [st.pstdev([b[i] for b in boot]) for i in range(len(G))]
    sd = [st.pstdev([x[i] for x, _ in ALL]) for i in range(len(G))]
    out = {'targets': [2017, 2025], 'teamSeasons': len(ALL), 'mse': {k: round(st.mean(v), 3) for k, v in err.items()},
           'tSplit': paired_t(err['split'], err['pooled']), 'tRB': paired_t(err['rb'], err['pooled']), 'winsRB': sum(1 for a, b in zip(err['rb'], err['pooled']) if a < b), 'wins': sum(1 for a, b in zip(err['split'], err['pooled']) if a < b), 'of': len(T),
           'pooledSlope': round(bp[1], 3), 'slopes': {g: {'b': round(bs[i + 1], 2), 'se': round(se[i], 2), 'sdX': round(sd[i], 2)} for i, g in enumerate(G)}}
    return out


if __name__ == '__main__':
    o = main(); print(json.dumps(o, indent=1))
    json.dump(o, open(os.path.join(ROOT, 'research', 'nfl_poscredit.json'), 'w'), indent=1)
