"""Median vs mean for the consensus board (fetchConsensus in scripts/fetch_cfb.mjs).

No archive keeps per-analyst boards with NFL outcomes, so this tests the aggregators on today's boards: hold one
board out, combine the other eight, and score how well each combination predicts the held-out board (Spearman, on
the prospects that board ranks in its top 60), averaged over the nine boards; 1000 bootstrap draws over prospects
give the median's margin. A board that leaves a prospect off counts at its depth + 10 (PFN's convention). With
scripts/cfb_statplus_backtest.mjs's cache present it also checks which order tracks this season's PFN production,
holding last season's fixed. Usage: python3 scripts/cfb_consensus_median.py -> data/cfb_consensus_median.json
"""
import json, os, re, subprocess
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
get = lambda u: subprocess.run(['curl', '-sSL', '-A', UA, u], capture_output=True, check=True).stdout.decode('utf8', 'replace')
nm = lambda s: re.sub(r'\s+', ' ', re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', re.sub(r'[^a-z ]', '', str(s or '').lower()))).strip()
dec = json.JSONDecoder()
html = get('https://www.profootballnetwork.com/nfl-draft-hq/industry-consensus-big-board')
s = ''.join(json.loads(m) for m in re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html))
ranks = {}
for m in re.finditer(r'\{"id":"', s):
    try: d, _ = dec.raw_decode(s, m.start())
    except ValueError: continue
    if d.get('avgRank') is not None and d.get('name'): ranks[nm(d['name'])] = dict(d.get('analystRanks') or {})
page = get('https://www.tankathon.com/nfl/big_board')
i = page.find('id="big-board"'); j = page.find('class="mock-rows"', page.find('class="mock-rows"', i) + 20)
tk = []
for n in re.findall(r'class="mock-row-name">([^<]+)</div><div class="mock-row-school-position">', page[i:j if j > i else None]):
    n = nm(n.replace('&#39;', "'"))
    if n not in [x for x in tk]: tk.append(n)
for k, n in enumerate(tk): ranks.setdefault(n, {})['Tankathon'] = k + 1
season = int(re.search(r'(20\d\d) NFL Draft', html).group(1)) if re.search(r'(20\d\d) NFL Draft', html) else 2027
pff = json.loads(get(f'https://www.pff.com/api/college/big_board?season={season}&version=1'))
for p in pff.get('players', []):
    if p.get('pff_rank'): ranks.setdefault(nm(p['name']), {})['PFF'] = p['pff_rank']
boards = sorted({k for v in ranks.values() for k in v})
depth = {b: max(v[b] for v in ranks.values() if b in v) for b in boards}
spear = lambda a, b: float(pd.Series(a).rank().corr(pd.Series(b).rank()))
imp = lambda rs, bs: [rs.get(b, depth[b] + 10) for b in bs]
HOW = {'mean': lambda rs, bs: np.mean(imp(rs, bs)), 'median': lambda rs, bs: np.median(imp(rs, bs)),
       'median of boards that rank him': lambda rs, bs: np.median([rs[b] for b in bs if b in rs]),
       'trimmed mean': lambda rs, bs: np.mean(sorted(imp(rs, bs))[1:-1])}
TOP = 60
held, cache = {h: {} for h in HOW}, {}
for b in boards:
    others = [x for x in boards if x != b]
    pl = [n for n, rs in ranks.items() if b in rs and rs[b] <= TOP and sum(x in rs for x in others) >= 2]
    y = np.array([ranks[n][b] for n in pl])
    for h, f in HOW.items():
        x = np.array([f(ranks[n], others) for n in pl]); held[h][b] = round(spear(x, y), 3)
        cache[(h, b)] = (x, y)
rng = np.random.default_rng(7); gaps = []
for _ in range(1000):
    g = []
    for b in boards:
        (md, y), (mn, _) = cache[('median', b)], cache[('mean', b)]
        i = rng.integers(0, len(y), len(y)); g.append(spear(md[i], y[i]) - spear(mn[i], y[i]))
    gaps.append(np.mean(g))
out = {'_readme': __doc__.strip().split('\n\n')[0] + ' See the script header for the method.', 'boards': boards, 'depth': depth,
       'heldOut': {h: {'mean': round(float(np.mean(list(v.values()))), 3), 'byBoard': v} for h, v in held.items()},
       'medianMinusMean': {'gap': round(float(np.mean(gaps)), 3), 'p5p95': [round(float(x), 3) for x in np.percentile(gaps, [5, 95])], 'shareAhead': round(float(np.mean(np.array(gaps) > 0)), 3)}}
sp = os.path.join(ROOT, 'scripts', '.cache', 'statplus')
if os.path.exists(os.path.join(sp, 'pfn_QB.json')):
    z = {}
    for g in ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB']:
        rows = [r for r in json.load(open(os.path.join(sp, f'pfn_{g}.json'))) if r['division'] == 'FBS']
        for sn in (season - 2, season - 1):
            xs = [r for r in rows if r['season'] == sn]; mu, sd = np.mean([r['score'] for r in xs]), np.std([r['score'] for r in xs])
            for r in xs: z.setdefault(nm(r['name']), {})[sn] = (r['score'] - mu) / sd
    pl = [n for n in ranks if n in z and len(z[n]) == 2 and len(ranks[n]) >= 3]
    out['tracksThisSeason'] = {}
    for h in ('mean', 'median'):
        a = np.array([(np.log(HOW[h](ranks[n], boards)), z[n][season - 1], z[n][season - 2]) for n in pl])
        X = np.c_[np.ones(len(a)), a[:, 1], a[:, 2]]; b = np.linalg.lstsq(X, a[:, 0], rcond=None)[0]
        r = a[:, 0] - X @ b; se = np.sqrt(np.diag(r @ r / (len(a) - 3) * np.linalg.inv(X.T @ X)))
        out['tracksThisSeason'][h] = {'n': len(a), 'thisSeasonT': round(float(b[1] / se[1]), 2), 'lastSeasonT': round(float(b[2] / se[2]), 2)}
json.dump(out, open(os.path.join(ROOT, 'data', 'cfb_consensus_median.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
