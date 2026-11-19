# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 5, wiring (Noah, Nov 19 2026: add the meetings to the mock): the size of the meetings term in the mock's own
units. Same rows as meetings.py (prereg.md lead 5): real picks 1-100 of the 2024-26 drafts, choice set = the 40 best
left on the DraftTek final board plus the real pick.

    python3 scripts/research/sweep_nov19/cfb/meetings_weight.py <WF dir> <DraftTek dir> <draft_picks.csv> [out.json]

The modal mock takes the best utility, so the term is sized as an argmax: utility = -ln board rank - REPEAT x repeat
position + w x (T30 or private visit) + w x R x (other meeting only), R = .804 / 1.378 (the logit fit's ratio, fixed).
w from the grid below, picked on two drafts by the top-1 hit rate (ties: the smaller w), scored on the third:
top-1 hits and the mean |ln(rank taken / rank mocked)|, against w = 0. Pass = pooled hit gain t >= 2 by draft-team and
all three drafts no worse. The shipped MEET_LN is the grid point picked on all three drafts.
"""
import importlib.util, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv
out_f = argv[4] if len(argv) > 4 else None
sys.argv = argv[:4]
spec = importlib.util.spec_from_file_location('meet', os.path.join(HERE, 'meetings.py'))
import io, contextlib
M = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(M)
GRID = [0, .1, .2, .3, .45, .6, .8, 1.0, 1.25, 1.5, 2.0, 3.0]
R, REPEAT = .804 / 1.378, 0.35


def score(rows, w):
    hit, miss = [], []
    for X, i, _ in rows:
        u = X[:, 0] - REPEAT * X[:, 1] + w * X[:, 2] + w * R * X[:, 3]
        j = int(np.argmax(u))
        hit.append(float(j == i)); miss.append(abs(X[i, 0] - X[j, 0]))
    return np.array(hit), np.array(miss)


def pick(rows):
    best = max(GRID, key=lambda w: (round(score(rows, w)[0].mean(), 6), -w))
    return best


res = {'grid': GRID, 'ratio': round(R, 3), 'folds': {}}
D, DM, CL = [], [], []
for y in M.data:
    tr = [r for z in M.data if z != y for r in M.data[z]]
    w = pick(tr)
    h1, m1 = score(M.data[y], w); h0, m0 = score(M.data[y], 0)
    res['folds'][y] = {'w': w, 'n': len(h1), 'hit0': round(float(h0.mean()), 4), 'hit': round(float(h1.mean()), 4), 'miss0': round(float(m0.mean()), 4), 'miss': round(float(m1.mean()), 4)}
    D += list(h1 - h0); DM += list(m1 - m0); CL += [f'{y}|{t}' for _, _, t in M.data[y]]
D, DM, CL = np.array(D), np.array(DM), np.array(CL)
ks = sorted(set(CL))
def t(d):
    m = np.array([d[CL == k].sum() for k in ks])
    return round(float(m.mean() / (m.std(ddof=1) / math.sqrt(len(ks)))), 2) if m.std() > 0 else 0.0
allr = [r for z in M.data for r in M.data[z]]
res['pooled'] = {'n': len(D), 'hitGain': round(float(D.mean()), 4), 'tHit': t(D), 'missGain': round(float(DM.mean()), 4), 'tMiss': t(DM), 'clusters': len(ks)}
res['curve'] = {str(w): [round(float(score(allr, w)[0].mean()), 4), round(float(score(allr, w)[1].mean()), 4)] for w in GRID}
res['w'] = pick(allr)
res['pass'] = bool(res['pooled']['tHit'] >= 2 and all(f['hit'] >= f['hit0'] for f in res['folds'].values()))
print(json.dumps(res, indent=1))
if out_f: json.dump(res, open(out_f, 'w'), indent=1)
