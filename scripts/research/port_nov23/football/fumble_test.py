#!/usr/bin/env python3
"""N3 (prereg.md): fumble-neutral offense EPA in the NFL game model's walk-forward (nfl_games.fit's run())."""
import copy, json, os, sys
from collections import defaultdict
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H
import nfl_games as N

DR, PR, DS, PS = 3.80, 0.418, 3.30, 0.528
last = 2025
games, box, qbs = N.load(last)
N.index_qbs(qbs, games); N.load_qb_teams(last)
inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
# fumble-neutral box: same plays, EPA moved by the player-week fumble counts
adj = defaultdict(float)
for y in range(N.FIRST, last + 1):
    for r in N.rows(os.path.join(N.CACHE, f'stats_player_week_{y}.csv')):
        if r.get('game_id'):
            adj[(r['game_id'], N.team(r['team']))] += (DR * (N.num(r['rushing_fumbles_lost']) - PR * N.num(r['rushing_fumbles']))
                                                     + DS * (N.num(r['sack_fumbles_lost']) - PS * N.num(r['sack_fumbles'])))
box_fn = defaultdict(lambda: {'epa': 0.0, 'plays': 0.0})
for k, v in box.items():
    box_fn[k] = dict(v); box_fn[k]['epa'] = v['epa'] + adj.get(k, 0.0)
print('mean adj a game', round(float(np.mean(list(adj.values()))), 4), 'sd', round(float(np.std(list(adj.values()))), 3))
params = json.load(open(N.FIT))['params']
played = lambda g: g['home_score'] not in ('', 'NA')

def frame(bx):
    _, data = N.walk(games, bx, qbs, params)
    out = {}
    for g, x, tx in data:
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1]); x['ir'] = r[5] - r[4]
        if played(g) and int(g['season']) >= 2012:
            out[g['game_id']] = (g, x, tx)
    return out
A, B = frame(box), frame(box_fn)
ids = list(A)
S = np.array([int(A[i][0]['season']) for i in ids]); wk = np.array([f"{A[i][0]['season']}-{A[i][0]['week']}" for i in ids])
y = np.array([N.num(A[i][0]['result']) for i in ids]); ty = np.array([N.num(A[i][0]['total']) for i in ids])

def wf(X, yy):
    p = np.full(len(yy), np.nan)
    for s in range(2015, last + 1):
        tr, te = S < s, S == s
        b = np.linalg.lstsq(X[tr], yy[tr], rcond=None)[0]; p[te] = X[te] @ b
    return p
Xm = lambda fs, src: np.array([[src[i][1][f] for f in fs] for i in ids])
Xt = lambda fs, src: np.array([[src[i][2][f] for f in fs] for i in ids])
base = wf(Xm(N.FEATS, A), y)
raw_epa = wf(np.column_stack([Xm(N.FEATS, A), [A[i][1]['epa'] for i in ids]]), y)
fn_epa = wf(np.column_stack([Xm(N.FEATS, A), [B[i][1]['epa'] for i in ids]]), y)
tbase = wf(Xt(N.TFEATS, A), ty)
tfn = wf(Xt(N.TFEATS, B), ty)
out = {}
for lab, k in (('tune', (S >= 2015) & (S <= 2020)), ('held', S >= 2021)):
    e = lambda p, yy: np.abs(p[k] - yy[k])
    out[lab] = {'N3a': H.paired(e(fn_epa, y), e(base, y), cluster=wk[k]),
                'N3a_rawEpaRef': H.paired(e(raw_epa, y), e(base, y), cluster=wk[k]),
                'N3a_fnVsRaw': H.paired(e(fn_epa, y), e(raw_epa, y), cluster=wk[k]),
                'N3b': H.paired(e(tfn, ty), e(tbase, ty), cluster=wk[k]),
                'maeBase': float(np.mean(e(base, y))), 'maeFn': float(np.mean(e(fn_epa, y))),
                'tmaeBase': float(np.mean(e(tbase, ty))), 'tmaeFn': float(np.mean(e(tfn, ty)))}
out['ryoy'] = 'see notes'
json.dump(out, open(os.path.join(os.path.dirname(__file__), 'res_fumble.json'), 'w'), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
