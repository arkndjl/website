"""Does anything beat a uniform draw for which NBA team gives an undrafted rookie his first NBA games?
Outcome: udfa_first.json (first_team.py). Per draft year y (2010-2025) and team: picks it made in draft y, its
second-round picks, and its undrafted-rookie debuts in the three drafts before (habit). Conditional logit over the
30 teams, held out by draft year (leave one draft out). Nov 26 2026."""
import json, os, math, collections
import numpy as np
R = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(R, '..', '..', '..')
BB = {'BRK': 'BKN', 'NJN': 'BKN', 'CHO': 'CHA', 'GSW': 'GS', 'NOP': 'NO', 'NOH': 'NO', 'NYK': 'NY', 'PHO': 'PHX',
      'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH'}
t_ = lambda t: BB.get(t, t)
first = {int(y): [t_(r[2].split('/')[0]) for r in v] for y, v in json.load(open(os.path.join(R, 'udfa_first.json'))).items()}
D = json.load(open(os.path.join(ROOT, 'scripts', 'nba_draft.json')))
TEAMS = sorted({t_(t) for rows in D.values() for *_, t in rows})
assert len(TEAMS) == 30, TEAMS
def feats(y):
    rows = D.get(str(y), [])
    npk = collections.Counter(t_(t) for _, _, _, t in rows)
    n2 = collections.Counter(t_(t) for pk, _, _, t in rows if pk > 30)
    hab = collections.Counter(t for z in (y - 1, y - 2, y - 3) for t in first.get(z, []))
    nh = sum(len(first.get(z, [])) for z in range(y - HW, y)) or 1
    return {t: [npk[t], n2[t], hab[t] * 30 / nh] for t in TEAMS}
import sys
HW = int(sys.argv[1]) if len(sys.argv) > 1 else 3
YEARS = [y for y in range(2010, 2026) if first.get(y)]
F = {y: feats(y) for y in YEARS}
obs = [(y, t) for y in YEARS for t in first[y] if t in TEAMS]
def ll(b, data, cols):
    s = 0.0
    for y, t in data:
        z = np.array([sum(b[i] * F[y][u][c] for i, c in enumerate(cols)) for u in TEAMS])
        z -= z.max(); s += z[TEAMS.index(t)] - math.log(np.exp(z).sum())
    return s
def fit(data, cols):
    b = np.zeros(len(cols))
    for _ in range(60):          # Newton on the conditional logit
        g = np.zeros(len(cols)); H = np.zeros((len(cols), len(cols)))
        for y, t in data:
            X = np.array([[F[y][u][c] for c in cols] for u in TEAMS]); z = X @ b; p = np.exp(z - z.max()); p /= p.sum()
            m = p @ X; g += X[TEAMS.index(t)] - m; H -= (X * p[:, None]).T @ X - np.outer(m, m)
        b = b - np.linalg.solve(H - 1e-6 * np.eye(len(cols)), g)
    return b
res = {'n': len(obs), 'years': [YEARS[0], YEARS[-1]], 'uniformLL': -math.log(30), 'models': {}}
for name, cols in {'picks': [0], 'R2 picks': [1], 'habit': [2], 'picks+habit': [0, 2], 'all': [0, 1, 2]}.items():
    per = []
    for y in YEARS:
        tr = [o for o in obs if o[0] != y]; te = [o for o in obs if o[0] == y]
        b = fit(tr, cols)
        per.append((y, len(te), ll(b, te, cols) / len(te)))
    tot = sum(n * v for _, n, v in per) / sum(n for _, n, v in per)
    d = np.array([v + math.log(30) for _, n, v in per]); w = np.array([n for _, n, _ in per])
    # per-draft gain over uniform: t across drafts (weighted)
    mu = (d * w).sum() / w.sum(); se = math.sqrt(((d - mu) ** 2 * w).sum() / w.sum() / (len(d) - 1))
    res['models'][name] = {'b': [round(x, 3) for x in fit(obs, cols)], 'heldLL': round(tot, 4), 'gain': round(tot + math.log(30), 4),
                           't': round(mu / se, 2), 'won': int((d > 0).sum()), 'of': len(d)}
    print(name, res['models'][name])
print('uniform', round(-math.log(30), 4), 'n', len(obs))
json.dump(res, open(os.path.join(R, f'team_test_hw{HW}.json'), 'w'), indent=1)
