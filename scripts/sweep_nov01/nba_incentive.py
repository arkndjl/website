"""NBA late-season incentive (Nov 1 2026 sweep; team idea 7's NBA half, never run). Flags from the standings before
each regular-season game (scripts/data/games_wf/nba.json.gz W-L, play-in games and the playoffs left out):
  out   the team can no longer reach the last post-season place in its conference (10th from 2020-21, 8th before):
        its wins + games left < the current holder's wins
  tank  50+ games played and bottom five in the league by win%
  low   out or tank
x = flag(away) - flag(home) on the margin; flag(home) + flag(away) on the total. Walk-forward slope fit on earlier
seasons (no intercept) on result - model (vs model) and result - close line (vs close); tune 2016-21, held 2022-26,
t clustered by day. Bar: tune t <= -1.5 and held t <= 0."""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H
EAST = set('ATL BKN BOS CHA CHI CLE DET IND MIA MIL NY ORL PHI TOR WSH'.split())

rows = json.load(gzip.open(os.path.join(ROOT, 'scripts/data/games_wf/nba.json.gz')))
rows = [r for r in rows if r.get('res') is not None and not r.get('po')]
rows.sort(key=lambda r: r['date'])
total_g = defaultdict(int)
for r in rows:
    total_g[(r['S'], r['home'])] += 1; total_g[(r['S'], r['away'])] += 1
W = defaultdict(int); G = defaultdict(int)
F = {k: [] for k in ('out', 'tank', 'low')}; FT = {k: [] for k in F}
cur_day = None; pend = []

def flags(S, t):
    g = G[(S, t)]; full = 82 if S not in (2020, 2021) else max(total_g[(S, t)], 72)
    conf = [u for u in {k[1] for k in G if k[0] == S} if (u in EAST) == (t in EAST)]
    cut = 10 if S >= 2021 else 8
    ws = sorted((W[(S, u)] for u in conf), reverse=True)
    wcut = ws[cut - 1] if len(ws) >= cut else 0
    out = int(g >= 40 and W[(S, t)] + (full - g) < wcut)
    allt = [u for u in {k[1] for k in G if k[0] == S}]
    pct = sorted(allt, key=lambda u: W[(S, u)] / max(G[(S, u)], 1))
    tank = int(g >= 50 and t in pct[:5])
    return {'out': out, 'tank': tank, 'low': int(out or tank)}

for r in rows:
    if r['date'][:10] != cur_day:
        for (S, h, a, res) in pend:
            G[(S, h)] += 1; G[(S, a)] += 1
            W[(S, h if res > 0 else a)] += 1
        pend = []; cur_day = r['date'][:10]
    fh, fa = flags(r['S'], r['home']), flags(r['S'], r['away'])
    for k in F:
        F[k].append(fa[k] - fh[k]); FT[k].append(fh[k] + fa[k])
    pend.append((r['S'], r['home'], r['away'], r['res']))

S = np.array([r['S'] for r in rows]); days = np.array([r['date'][:10] for r in rows])
y = np.array([r['res'] for r in rows], float)
tot = np.array([r['tot'] if r.get('tot') is not None else np.nan for r in rows], float)
base = {'m': np.array([r['m'] for r in rows], float), 'L': np.array([r['L'] if r.get('L') is not None else np.nan for r in rows], float),
        'tm': np.array([r.get('tm') if r.get('tm') is not None else np.nan for r in rows], float),
        'T': np.array([r.get('T') if r.get('T') is not None else np.nan for r in rows], float)}

def walk(x, e):
    pred = np.full(len(e), np.nan)
    for s in sorted(set(S))[1:]:
        tr = (S < s) & ~np.isnan(e); te = S == s
        pred[te] = (x[tr] @ e[tr]) / max(x[tr] @ x[tr], 1e-9) * x[te]
    return pred

def score(x, e, seasons):
    p = walk(x, e)
    mk = np.isin(S, seasons) & ~np.isnan(e) & ~np.isnan(p) & (x != 0)
    r = H.paired((e[mk] - p[mk]) ** 2, e[mk] ** 2, cluster=days[mk])
    return {'t': round(r['t'], 2), 'd': round(float(r['d']), 4), 'n': int(r['n'])}

TUNE, HELD = list(range(2016, 2022)), list(range(2022, 2027))
out = {}
for k in F:
    x = np.array(F[k], float); xt = np.array(FT[k], float)
    raw = {'flagged_games': int((x != 0).sum()), 'mean_res_minus_close_per_flag': round(float(np.nanmean(((y - base['L']) * x)[x != 0])), 2)}
    o = {'raw': raw}
    for lab, b, ee, xx in (('margin_vs_model', 'm', y, x), ('margin_vs_close', 'L', y, x), ('total_vs_model', 'tm', tot, xt), ('total_vs_close', 'T', tot, xt)):
        e = ee - base[b]
        o[lab] = {'tune': score(xx, e, TUNE), 'held': score(xx, e, HELD)}
    out[k] = o
    print(k, json.dumps(o), flush=True)
os.makedirs(os.path.join(ROOT, 'data', 'sweep_nov01'), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nba_incentive.json'), 'w'), indent=1)
