"""Tonight's starting XI value (upper bound: the XI is known ~1 h before kickoff) and last match's XI, each minus the
team's usual XI this season, on top of the shipped soccer model and vs the close. Values = prior-season GAR/90 on
the big-five scale (soccer_players fit), newcomers at their position's replacement level."""
import gzip, json, glob, os, sys, math
from collections import defaultdict
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import soccer_players as SP
import harness as H
F = json.load(open(ROOT + '/data/soccer_war_fit.json'))
rows = json.load(gzip.open(SP.ROWS))
SP.prep(rows, F['shrink'])
LS = SP.league_strength()
val = {}
for r in rows:
    v = SP.value(r, F) + SP.lg_adj(r, F, LS)
    w = r['min'] / (r['min'] + 900)            # extra shrink toward replacement for thin seasons
    val[(r['p'], r['S'])] = w * v + (1 - w) * F['repl'][r['pos']]
POS = SP.POS
hist = json.load(gzip.open(ROOT + '/scripts/soccer_games_hist.json.gz'))
us2espn = {r['us']: r for r in hist if r.get('us')}
wf = {r['id']: r for r in json.load(gzip.open(ROOT + '/scripts/data/games_wf/soccer.json.gz'))}
# each Understat match: per side XI value
mt = []
for f in glob.glob(ROOT + '/scripts/.cache/soccer/usm/*/*.json.gz'):
    mid = os.path.basename(f).split('.')[0]
    e = us2espn.get(mid)
    if not e or e['id'] not in wf: continue
    d = json.load(gzip.open(f)); S = wf[e['id']]['S']
    xi = {}
    for s in ('h', 'a'):
        st = [p for p in d['ro'][s] if p['position'] != 'Sub']
        if len(st) < 10: break
        xi[s] = sum(val.get((p['player_id'], S - 1), F['repl'][POS.get(p['position'], 'M') if p['position'] != 'GK' else 'GK']) for p in st)
    if len(xi) == 2: mt.append((e['day'], e['id'], S, e['h'], e['a'], xi['h'], xi['a']))
mt.sort()
hist_t = defaultdict(list)   # (team, S) -> earlier XI values
X = {}
for day, eid, S, h, a, vh, va in mt:
    def dev(t, v, last=False):
        L = hist_t[(t, S)]
        if len(L) < 3: return None
        mu = np.mean(L)
        return (L[-1] - mu) if last else (v - mu)
    th, ta, lh, la = dev(h, vh), dev(a, va), dev(h, vh, True), dev(a, va, True)
    if None not in (th, ta): X[eid] = (th - ta, lh - la)
    hist_t[(h, S)].append(vh); hist_t[(a, S)].append(va)
print('matches with XI', len(mt), 'with feature', len(X), flush=True)
ids = [i for i in X if wf[i].get('hs') is not None]
Y = np.array([wf[i]['S'] for i in ids]); days = np.array([wf[i]['day'] for i in ids])
o = np.array([0 if wf[i]['hs'] > wf[i]['as'] else 1 if wf[i]['hs'] == wf[i]['as'] else 2 for i in ids])
Pm = np.array([wf[i]['p'] for i in ids]); Pc = np.array([wf[i]['c'] if wf[i].get('c') else [np.nan] * 3 for i in ids])
Xa = np.array([X[i] for i in ids])
def tilt(P, x, b):
    q = P * np.exp(np.c_[b * x, np.zeros_like(x), -b * x]); return q / q.sum(1, keepdims=True)
def nll(P): return -np.log(P[np.arange(len(P)), o[:len(P)]] if len(P) == len(o) else P)
def ll_rows(P, idx): return -np.log(P[idx, o[idx]])
grid = np.linspace(-1, 3, 81)
def test(P, col, years):
    new, old, cl = [], [], []
    for yr in years:
        tr = (Y < yr) & ~np.isnan(P[:, 0]); te = (Y == yr) & ~np.isnan(P[:, 0])
        if tr.sum() < 1500 or te.sum() == 0: continue
        trI = np.where(tr)[0]
        b = min(grid, key=lambda b: ll_rows(tilt(P[trI], Xa[trI, col], b), np.arange(len(trI))).mean() if False else -np.log(tilt(P[trI], Xa[trI, col], b)[np.arange(len(trI)), o[trI]]).mean())
        teI = np.where(te)[0]
        new += list(-np.log(tilt(P[teI], Xa[teI, col], b)[np.arange(len(teI)), o[teI]])); old += list(-np.log(P[teI, o[teI]])); cl += list(days[teI])
    r = H.paired(new, old, cluster=np.array(cl))
    trI = np.where(~np.isnan(P[:, 0]))[0]
    ball = min(grid, key=lambda b: -np.log(tilt(P[trI], Xa[trI, col], b)[np.arange(len(trI)), o[trI]]).mean())
    return dict(t=round(r['t'], 2), dLL_e4=round(float(r['d']) * 1e4, 2), n=r['n'], b_all=round(float(ball), 3))
out = {'sd_tonight': float(Xa[:, 0].std()), 'sd_last': float(Xa[:, 1].std())}
for col, nm in ((0, 'tonight XI'), (1, 'last XI')):
    out[nm] = {'tune': test(Pm, col, range(2018, 2023)), 'held': test(Pm, col, range(2023, 2028)),
               'close_tune': test(Pc, col, range(2018, 2023)), 'close_held': test(Pc, col, range(2023, 2028))}
    print(nm, out[nm], flush=True)
json.dump(out, open(os.path.join(ROOT, 'data', 'sweep_oct31', 'soccer_xi.json'), 'w'), indent=1)
