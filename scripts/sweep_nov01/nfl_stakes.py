"""NFL late-season stakes (Nov 1 2026 sweep): teams with nothing left to play for rest starters who aren't on the
injury report. Standings from scripts/data/games_wf/nfl.json.gz before each game, weeks 15 on, regular season:
  out    can't reach the conference's 7th place (wins + games left < its wins; 6th before 2020)
  in     clinched a place (conservative: more wins than any team 8th or lower could reach)
  lock1  clinched the conference's top seed (more wins than any other conference team could reach)
  late_in  in, week 17 on (the last week before 2021, 18 after)
x = flag(away) - flag(home); walk-forward slope on result - model and result - close; tune 2015-20, held 2021-25."""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H
AFC = set('BAL BUF CIN CLE DEN HOU IND JAX KC LV OAK LAC SD MIA NE NYJ PIT TEN'.split())
rows = [r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts/data/games_wf/nfl.json.gz'))) if r.get('res') is not None and not r.get('po')]
rows.sort(key=lambda r: (r['date'], r['id']))
allg = defaultdict(int)
for r in rows:
    allg[(r['S'], r['home'])] += 1; allg[(r['S'], r['away'])] += 1
W = defaultdict(float); G = defaultdict(int)
FL = defaultdict(list); pend = []; cur = None

def flags(S, t, wk):
    conf = [u for (s, u) in allg if s == S and (u in AFC) == (t in AFC)]
    full = 17 if S >= 2021 else 16
    rem = {u: full - G[(S, u)] for u in conf}
    order = sorted(conf, key=lambda u: -W[(S, u)])
    cut = 7 if S >= 2020 else 6
    wcut = W[(S, order[cut - 1])]
    out = int(wk >= 15 and W[(S, t)] + rem[t] < wcut)
    below = order[cut:]
    inn = int(wk >= 15 and t in order[:cut] and W[(S, t)] > max(W[(S, u)] + rem[u] for u in below if u != t))
    lock1 = int(wk >= 15 and W[(S, t)] > max(W[(S, u)] + rem[u] for u in conf if u != t))
    last = full + 1
    return {'out': out, 'in': inn, 'lock1': lock1, 'late_in': int(inn and wk >= last - 1), 'any': int(out or inn)}

for r in rows:
    if r['date'][:10] != cur:
        for (S, h, a, res) in pend:
            G[(S, h)] += 1; G[(S, a)] += 1
            if res > 0: W[(S, h)] += 1
            elif res < 0: W[(S, a)] += 1
            else: W[(S, h)] += .5; W[(S, a)] += .5
        pend = []; cur = r['date'][:10]
    fh, fa = flags(r['S'], r['home'], r['wk']), flags(r['S'], r['away'], r['wk'])
    for k in fh:
        FL[k].append(fa[k] - fh[k])
    pend.append((r['S'], r['home'], r['away'], r['res']))
S = np.array([r['S'] for r in rows]); days = np.array([r['date'][:10] for r in rows])
y = np.array([r['res'] for r in rows], float)
m = np.array([r['m'] for r in rows], float); L = np.array([r['L'] if r.get('L') is not None else np.nan for r in rows], float)

def walk(x, e):
    pred = np.full(len(e), np.nan)
    for s in sorted(set(S))[1:]:
        tr = (S < s) & ~np.isnan(e); te = S == s
        pred[te] = (x[tr] @ e[tr]) / max(x[tr] @ x[tr], 1e-9) * x[te]
    return pred

def score(x, e, lo, hi):
    p = walk(x, e)
    mk = (S >= lo) & (S <= hi) & ~np.isnan(e) & ~np.isnan(p) & (x != 0)
    r = H.paired((e[mk] - p[mk]) ** 2, e[mk] ** 2, cluster=days[mk])
    return {'t': round(r['t'], 2), 'd': round(float(r['d']), 3), 'n': int(r['n'])}
out = {}
for k, v in FL.items():
    x = np.array(v, float)
    o = {'flagged': int((x != 0).sum()),
         'mean_res_minus_model_x': round(float(np.mean(((y - m) * x)[x != 0])), 2),
         'mean_res_minus_close_x': round(float(np.nanmean(((y - L) * x)[x != 0])), 2)}
    for lab, b in (('vs_model', m), ('vs_close', L)):
        o[lab] = {'tune': score(x, y - b, 2016, 2020), 'held': score(x, y - b, 2021, 2025)}
    out[k] = o
    print(k, json.dumps(o), flush=True)
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nfl_stakes.json'), 'w'), indent=1)
