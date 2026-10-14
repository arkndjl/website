"""Consensus weight backtest for CONS_W (scripts/fetch_cfb.mjs).

FV blends the model grade toward the grade the consensus rank implies (80 - 8.7 ln(rank / 2.7)) by CONS_W. The only
in-season or preseason board with history and per-player ranks is PFF's: its 2022 board (last updated Nov 29, 2021)
and its 2023 board (May 3, 2022); PFN's consensus page has no archive and gives no board dates, and 2024 on come back
empty. Run by hand after scripts/cfb_statplus_backtest.mjs (it reuses that script's cached PFN lines and nflverse
picks): python3 scripts/cfb_consensus_backtest.py -> data/cfb_consensus_backtest.json (needs numpy, pandas).
  universe   players on either board with a PFN line in the season before the draft (QB, RB, WR, TE, EDGE, DT, LB);
             players drafted in a later class dropped
  outcome    weighted NFL AV a season through 2025 (undrafted 0), and ln pick (undrafted 290)
  model      FV's production blend (5/4/3 by snaps, K 3000), the only part of today's model with that history
  test       the board's share of the best two-predictor blend (standardized), fitted on one draft and scored on the
             other, and pooled. The history model is production alone, weaker than today's (On3, badges, QBR, age), so
             the share is converted to today's model with the two-predictor formula, b ~ r_y - r_xy r_other, at the
             model-consensus correlation on the current board, over a range of model validity
  CONS_W     the weight that gives the board that share of FV's spread on the current board
"""
import json, math, os, re, subprocess, tempfile
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'statplus')
W = tempfile.mkdtemp()
BOARDS = [(2022, 2021), (2023, 2022)]
for draft, _ in BOARDS:
    subprocess.run(['curl', '-sS', '-A', 'Mozilla/5.0', '-o', os.path.join(W, f'pff{draft}.json'), f'https://www.pff.com/api/college/big_board?season={draft}&version=1'], check=True)
nm = lambda s: re.sub(r'\s+', ' ', re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', re.sub(r'[^a-z ]', '', str(s or '').lower()))).strip()
cons_fv = lambda r: 80 - 8.7 * np.log(r / 2.7)
dp = pd.read_csv(os.path.join(CACHE, 'draft_picks.csv'), low_memory=False)
dp['k'] = dp.pfr_player_name.map(nm)
prod = {}
for g in ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB']:
    rows = [r for r in json.load(open(os.path.join(CACHE, f'pfn_{g}.json'))) if r['division'] == 'FBS']
    cz = {}
    for r in rows: cz.setdefault(r['season'], []).append(r['score'])
    cz = {s: (np.mean(x), np.std(x)) for s, x in cz.items()}
    for r in rows:
        r['z'] = (r['score'] - cz[r['season']][0]) / cz[r['season']][1]
        r['v'] = r['snapsQ'] if isinstance(r.get('snapsQ'), (int, float)) else (r.get('gp') or r.get('gamesQ') or 0) * 50
        prod.setdefault(nm(r['name']), {})[r['season']] = r
def marcel(b, last):
    num = den = 0
    for k, w in enumerate((5, 4, 3)):
        x = b.get(last - k)
        if x: num += w * x['v'] * x['z']; den += w * x['v']
    return num / (den + 3000) if last in b else None
rows, dates = [], {}
for draft, last in BOARDS:
    d = json.load(open(os.path.join(W, f'pff{draft}.json')))
    dates[draft] = d.get('last_updated_at')
    for p in (x for x in d['players'] if x.get('pff_rank')):
        n = nm(p['name']); mine = dp[dp.k == n]; pk = mine[mine.season == draft]
        if pk.empty and (mine.season > draft).any(): continue
        pr = marcel(prod[n], last) if n in prod else None
        if pr is None: continue
        rows.append(dict(name=p['name'], draft=draft, rank=p['pff_rank'], prod=pr,
                         av=float(pk.w_av.fillna(0).iloc[0]) / (2025 - draft + 1) if len(pk) else 0.0, lp=-math.log(float(pk.pick.iloc[0]) if len(pk) else 290.0)))
e = pd.DataFrame(rows)
zs = lambda x: (x - x.mean()) / x.std(ddof=0)
e['zc'], e['zp'] = zs(cons_fv(e['rank'])), zs(e['prod'])
r = lambda a, b: float(np.corrcoef(a, b)[0, 1])
share = lambda rc, rm, rcm: (rc - rcm * rm) / ((rc - rcm * rm) + (rm - rcm * rc))
res = {'_readme': __doc__.strip().split('\n\n')[0] + ' See the script header for the method.', 'boardDates': dates, 'n': {str(k): int(v) for k, v in e.groupby('draft').size().items()}, 'outcomes': {}}
for y in ('av', 'lp'):
    o = {'r': {'board': round(r(e.zc, e[y]), 3), 'production': round(r(e.zp, e[y]), 3), 'boardProduction': round(r(e.zc, e.zp), 3)},
         'pooledShare': round(share(r(e.zc, e[y]), r(e.zp, e[y]), r(e.zc, e.zp)), 2), 'crossFit': {}}
    for tr, te in ((2022, 2023), (2023, 2022)):
        A, B = e[e.draft == tr], e[e.draft == te]
        X = np.c_[np.ones(len(A)), A.zp, A.zc]; b = np.linalg.lstsq(X, A[y].values, rcond=None)[0]
        o['crossFit'][f'{tr}->{te}'] = {'boardShare': round(float(b[2] / (b[1] + b[2])), 2), 'oosR': round(r(np.c_[np.ones(len(B)), B.zp, B.zc] @ b, B[y]), 3),
                                        'boardOnlyR': round(r(B.zc, B[y]), 3), 'productionOnlyR': round(r(B.zp, B[y]), 3)}
    res['outcomes'][y] = o
# today's board: model FV vs consensus-implied FV among consensus-ranked prospects
cur = [p for p in json.load(open(os.path.join(ROOT, 'data', 'cfb.json')))['players'] if p.get('fvModel') is not None and p.get('cons') is not None]
fm, cf = np.array([p['fvModel'] for p in cur]), np.array([cons_fv(p['cons']) for p in cur])
sm, sc, rcm = fm.std(), cf.std(), r(fm, cf)
cons_w = lambda s: s * sm / (sc * (1 - s) + s * sm)   # CONS_W whose share of the blend's spread is s
rc = res['outcomes']['av']['r']['board']
res['today'] = {'n': len(cur), 'sdModel': round(float(sm), 2), 'sdCons': round(float(sc), 2), 'rModelCons': round(rcm, 3),
                'currentShare': round(float(0.35 * sc / ((1 - 0.35) * sm + 0.35 * sc)), 2),
                'byModelValidity': {str(rm): {'share': round(share(rc, rm, rcm), 2), 'consW': round(float(cons_w(share(rc, rm, rcm))), 2)} for rm in (0.40, 0.45, 0.50, 0.55, 0.60)}}
json.dump(res, open(os.path.join(ROOT, 'data', 'cfb_consensus_backtest.json'), 'w'), indent=1)
print(json.dumps(res, indent=1))
