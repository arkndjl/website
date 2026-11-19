# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 5: pre-draft team meetings in the mock's pick step (pre-registered in prereg.md).
argv: dir with WalterFootball m<Y>.html, dir with DraftTek dt_<Y>_<p>.html, nflverse draft_picks.csv."""
import csv, glob, html, json, math, os, re, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names
WF, DT, DP = sys.argv[1:4]
NFL = {'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN',
       'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GNB', 'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND',
       'Jacksonville Jaguars': 'JAX', 'Kansas City Chiefs': 'KAN', 'Las Vegas Raiders': 'LVR', 'Los Angeles Chargers': 'LAC', 'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
       'New England Patriots': 'NWE', 'New Orleans Saints': 'NOR', 'New York Giants': 'NYG', 'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SFO',
       'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TAM', 'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS'}
CANON = {'GB': 'GNB', 'KC': 'KAN', 'LV': 'LVR', 'LA': 'LAR', 'NE': 'NWE', 'NO': 'NOR', 'SF': 'SFO', 'TB': 'TAM'}
canon = lambda t: CANON.get(t, t)
def meetings(y):
    s = open(os.path.join(WF, f'm{y}.html'), encoding='latin1').read()
    t = html.unescape(re.sub(r'<[^>]+>', '\n', re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S)))
    lines = [x.strip() for x in t.split('\n') if x.strip()]
    start = max(i for i, x in enumerate(lines) if x == 'By College')
    M, team = {}, None
    for x in lines[start:]:
        if x in NFL: team = NFL[x]; continue
        m = re.match(r"^([^,]+?)[\^%#]*,\s*[^,]+,\s*.+\(([A-Z0-9, ]+)\)\s*$", x)
        if team and m:
            tags = {a.strip() for a in m.group(2).split(',')}
            M[(team, names.key(m.group(1)))] = 2 if tags & {'T30', 'PRI'} else 1
    return M
def board(y):
    out, seen = [], set()
    for f in sorted(glob.glob(os.path.join(DT, f'dt_{y}_*.html'))):
        s = re.sub(r'<!--.*?-->', '', open(f, encoding='latin1').read(), flags=re.S)
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
            td = [html.unescape(re.sub('<[^>]+>', '', t)).strip() for t in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
            if len(td) >= 8 and td[0].isdigit() and int(td[0]) not in seen:
                seen.add(int(td[0])); out.append({'rank': int(td[0]), 'k': names.key(td[2]), 'pos': td[4]})
    return sorted(out, key=lambda r: r['rank'])
GRP = lambda p: next((g for g, ps in {'QB': ['QB'], 'RB': ['RB', 'FB'], 'WR': ['WR'], 'TE': ['TE'], 'OL': ['OT', 'OG', 'OC', 'G', 'T', 'C', 'OL', 'IOL'], 'DL': ['DL', 'DT', 'DE', 'EDGE', 'DL1T', 'DL3T', 'DL5T', 'NT'],
                                       'LB': ['LB', 'OLB', 'ILB'], 'DB': ['CB', 'S', 'DB', 'FS', 'SS', 'CBN']}.items() if p.upper() in ps), 'X')
picks = defaultdict(list)
for r in csv.DictReader(open(DP)):
    if r['season'] in ('2023', '2024', '2025', '2026'): picks[int(r['season'])].append({'pick': int(r['pick']), 'round': int(r['round']), 'team': canon(r['team']), 'k': names.key(r['pfr_player_name']), 'grp': GRP(r['position'])})
data, info = {}, {}
for y in (2024, 2025, 2026):
    M, B = meetings(y), board(y)
    rank = {b['k']: b for b in B}
    rep = {(p['team'], p['grp']) for p in picks[y - 1] if p['round'] <= 2}
    gone, rows = set(), []
    nm = sum(1 for (t, k) in M if k in rank)
    for p in sorted(picks[y], key=lambda p: p['pick']):
        if p['pick'] > 100: break
        avail = [b for b in B if b['k'] not in gone][:40]
        real = rank.get(p['k']) or {'rank': 400, 'k': p['k'], 'pos': p['grp']}
        if real['k'] not in {b['k'] for b in avail}: avail.append(real)
        X = [[-math.log(b['rank']), 1.0 if (p['team'], GRP(b['pos'])) in rep else 0.0, 1.0 if M.get((p['team'], b['k'])) == 2 else 0.0, 1.0 if M.get((p['team'], b['k'])) == 1 else 0.0] for b in avail]
        rows.append((np.array(X), [b['k'] for b in avail].index(p['k']), p['team']))
        gone.add(p['k'])
    data[y] = rows
    info[y] = {'meetings': len(M), 'onBoard': nm, 'board': len(B), 'pickedHadT30': sum(1 for X, i, _ in rows if X[i, 2]), 'pickedHadOther': sum(1 for X, i, _ in rows if X[i, 3])}
def fit(rows, cols, lam=0.1):
    b = np.zeros(len(cols))
    for _ in range(80):
        g = -lam * b; H = -lam * np.eye(len(cols))
        for X, i, _ in rows:
            Z = X[:, cols]; u = Z @ b; u -= u.max(); p = np.exp(u); p /= p.sum(); m = p @ Z
            g += Z[i] - m; H -= (Z * p[:, None]).T @ Z - np.outer(m, m)
        b -= np.linalg.solve(H, g)
    return b
def ll(rows, cols, b):
    out = []
    for X, i, _ in rows:
        u = X[:, cols] @ b; u -= u.max(); out.append(u[i] - math.log(np.exp(u).sum()))
    return np.array(out)
out = {'info': info, 'folds': {}}
D, CL = [], []
for y in (2024, 2025, 2026):
    tr = [r for z in data if z != y for r in data[z]]
    b0, b1 = fit(tr, [0, 1]), fit(tr, [0, 1, 2, 3])
    d = ll(data[y], [0, 1, 2, 3], b1) - ll(data[y], [0, 1], b0)
    top0 = np.mean([int(np.argmax(X[:, [0, 1]] @ b0) == i) for X, i, _ in data[y]]); top1 = np.mean([int(np.argmax(X @ b1) == i) for X, i, _ in data[y]])
    out['folds'][y] = {'n': len(d), 'llBase': round(float(ll(data[y], [0, 1], b0).mean()), 4), 'gain': round(float(d.mean()), 4), 'top1Base': round(float(top0), 3), 'top1Meet': round(float(top1), 3), 'coef': [round(float(x), 3) for x in b1]}
    D += list(d); CL += [f'{y}|{t}' for _, _, t in data[y]]
D = np.array(D); CL = np.array(CL); ks = sorted(set(CL)); m = np.array([D[CL == k].sum() for k in ks])
out['pooled'] = {'n': len(D), 'gain': round(float(D.mean()), 4), 't': round(float(m.mean() / (m.std(ddof=1) / math.sqrt(len(ks)))), 2), 'clusters': len(ks)}
ball = fit([r for z in data for r in data[z]], [0, 1, 2, 3])
out['all'] = {'coef': [round(float(x), 3) for x in ball], 'names': ['-ln board rank', 'repeat position', 'T30 or PRI', 'other meeting only'],
              'perLogPick': {'t30': round(float(ball[2] / ball[0]), 2), 'other': round(float(ball[3] / ball[0]), 2)}}
print(json.dumps(out, indent=1))
if len(sys.argv) > 4: json.dump(out, open(sys.argv[4], 'w'), indent=1)
