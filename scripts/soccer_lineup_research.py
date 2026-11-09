# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer lineup continuity as a game-model term (big five, Understat league rosters 2015-16 on).

Per side, from Understat starters (position != 'Sub'):
  chg     starters changed from the team's previous league XI this season (0-11; lineup-time info, ~1 h pre-kickoff)
  settled mean share of the team's earlier league matches this season that tonight's starters started (lineup-time)
  habit   team's mean changes per match so far this season (pre-lineup info; a rotation habit)
  pairs   share of tonight's 55 starter pairs that had started together in 3+ earlier league matches (lineup-time)
  pairs_pre, settled_pre  the same on the team's previous XI (pre-lineup: what a model run a day out can know)
Each enters as a home-minus-away tilt on the shipped walk-forward probabilities (scripts/data/games_wf/soccer.json.gz),
b chosen on earlier seasons only (expanding by season), tune seasons 2018-22, held out 2023+; paired log-loss t
clustered by match day. Also scored as a tilt on the close (does the market already price it?).
Result (Nov 2 2026): pairs passes on the model (tune t -1.62, held -2.14) and settled nearly (-1.39 / -1.97), but both
need the announced XI; the close already prices them (held +1.77 / -0.21), and the pre-lineup versions fail (pairs_pre
+1.34 / +0.08, settled_pre +1.02 / +0.11). The live model runs before lineups and soccer has no picks: not shipped.
Writes data/soccer_lineup_research.json."""
import gzip, json, glob, os, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H

hist = json.load(gzip.open(ROOT + '/scripts/soccer_games_hist.json.gz'))
us2espn = {r['us']: r for r in hist if r.get('us')}
wf = {r['id']: r for r in json.load(gzip.open(ROOT + '/scripts/data/games_wf/soccer.json.gz'))}

mt = []
for f in glob.glob(ROOT + '/scripts/.cache/soccer/usm/*/*.json.gz'):
    mid = os.path.basename(f).split('.')[0]
    e = us2espn.get(mid)
    if not e:
        continue
    d = json.load(gzip.open(f))
    xi = {}
    for s in ('h', 'a'):
        st = [p['player_id'] for p in d['ro'][s] if p['position'] != 'Sub']
        if len(st) < 10:
            break
        xi[s] = st
    if len(xi) == 2:
        S = wf[e['id']]['S'] if e['id'] in wf else None
        mt.append((e['day'], e.get('t') or '', e['id'], S, e['h'], e['a'], xi['h'], xi['a']))
mt.sort()

last = {}                       # (team, S) -> previous XI
starts = defaultdict(lambda: defaultdict(int))   # (team, S) -> player -> starts
pairc = defaultdict(lambda: defaultdict(int))    # (team, S) -> frozenset pair -> starts together
nm = defaultdict(int)
chgs = defaultdict(list)
X = {}
for day, _, eid, S, h, a, xh, xa in mt:
    if S is None:
        continue
    f = {}
    for side, t, xi in (('h', h, xh), ('a', a, xa)):
        k = (t, S)
        n = nm[k]
        if n >= 3:
            chg = len(set(xi) - set(last[k]))
            settled = float(np.mean([starts[k][p] / n for p in xi]))
            habit = float(np.mean(chgs[k]))
            prs = [(xi[i], xi[j]) for i in range(len(xi)) for j in range(i + 1, len(xi))]
            pairs = float(np.mean([pairc[k][frozenset(pr)] >= 3 for pr in prs]))
            L = last[k]
            prl = [(L[i], L[j]) for i in range(len(L)) for j in range(i + 1, len(L))]
            pairs_pre = float(np.mean([pairc[k][frozenset(pr)] >= 3 for pr in prl]))
            settled_pre = float(np.mean([starts[k][p] / n for p in L]))
            f[side] = (chg, settled, habit, pairs, pairs_pre, settled_pre)
    if len(f) == 2:
        X[eid] = tuple(f['h'][i] - f['a'][i] for i in range(6))
    for t, xi in ((h, xh), (a, xa)):
        k = (t, S)
        if k in last:
            chgs[k].append(len(set(xi) - set(last[k])))
        last[k] = xi
        nm[k] += 1
        for p in xi:
            starts[k][p] += 1
        for i in range(len(xi)):
            for j in range(i + 1, len(xi)):
                pairc[k][frozenset((xi[i], xi[j]))] += 1
NAMES = ['chg', 'settled', 'habit', 'pairs', 'pairs_pre', 'settled_pre']
print('matches', len(mt), 'with features', len(X), flush=True)
ids = [i for i in X if i in wf and wf[i].get('hs') is not None]
Y = np.array([wf[i]['S'] for i in ids]); days = np.array([wf[i]['day'] for i in ids])
o = np.array([0 if wf[i]['hs'] > wf[i]['as'] else 1 if wf[i]['hs'] == wf[i]['as'] else 2 for i in ids])
Pm = np.array([wf[i]['p'] for i in ids])
# close (Shin no-vig) from the hist rows: Pinnacle -> Betfair -> average
sys.path.insert(0, ROOT + '/scripts')
import soccer_games as G
byid = {r['id']: r for r in hist}
Pc = np.array([G.close_probs(byid[i]) if G.close_probs(byid[i]) is not None else [np.nan] * 3 for i in ids], float)
Xa = np.array([X[i] for i in ids], float)
Xa = (Xa - Xa.mean(0)) / Xa.std(0)


def tilt(P, x, b):
    q = P * np.exp(np.c_[b * x, np.zeros_like(x), -b * x])
    return q / q.sum(1, keepdims=True)


def ll(P, I, x, b):
    return -np.log(tilt(P[I], x, b)[np.arange(len(I)), o[I]])


grid = np.linspace(-0.3, 0.3, 61)


def test(P, col, years):
    new, old, cl, bs = [], [], [], []
    for yr in years:
        tr = np.where((Y < yr) & ~np.isnan(P[:, 0]))[0]
        te = np.where((Y == yr) & ~np.isnan(P[:, 0]))[0]
        if len(tr) < 1500 or len(te) == 0:
            continue
        b = min(grid, key=lambda b: ll(P, tr, Xa[tr, col], b).mean())
        bs.append(round(float(b), 3))
        new += list(ll(P, te, Xa[te, col], b)); old += list(ll(P, te, Xa[te, col], 0)); cl += list(days[te])
    r = H.paired(new, old, cluster=np.array(cl))
    return dict(t=round(r['t'], 2), dLL_e4=round(float(r['d']) * 1e4, 2), n=r['n'], b_by_year=bs)


out = {'n': len(ids), 'sd': dict(zip(NAMES, [round(float(s), 3) for s in np.array([X[i] for i in ids], float).std(0)])),
       'note': __doc__.split('\n')[0]}
# raw: does the model already explain it? slope of (result - model) on feature
for col, nm_ in enumerate(NAMES):
    out[nm_] = {'tune': test(Pm, col, range(2018, 2023)), 'held': test(Pm, col, range(2023, 2028)),
                'close_tune': test(Pc, col, range(2018, 2023)), 'close_held': test(Pc, col, range(2023, 2028))}
    print(nm_, out[nm_], flush=True)
json.dump(out, open(os.path.join(ROOT, 'data', 'soccer_lineup_research.json'), 'w'), indent=1)
