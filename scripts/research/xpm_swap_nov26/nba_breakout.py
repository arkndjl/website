#!/usr/bin/env python3
"""Cross-sport analogue of the CBB breakout pass: NBA Potential Breakout (scripts/nba_breakout_research.py, leave one season
out, log loss by season) with a pXPM gap = pXPM (next-season XPM, static/data/nba-xpm sxpm; history and aging curve of
seasons <= y) - his shrunk BPM, added to the kept logistic. XPM starts 2009-10, so rows are the 2010-2025 seasons.
Also rXPM (team-adjusted, txpm) gap as the descriptive read.  -> nba_breakout.json"""
import json, os, sys
import numpy as np
import common as C
sys.path.insert(0, os.path.join(C.ROOT, 'scripts'))
import breakout_lib as L, nba_breakout as B, nba_breakout_research as R
P = R.seasons(R.SRC); V = R.vacated(P); fit = json.load(open(R.OUT))['breakout']; keep = fit['keep'] + fit.get('keep2', [])
XS = {}
for y in range(2010, 2026):
    XS[y] = {p['id']: p for p in json.load(open(os.path.join(C.ROOT, 'static', 'data', 'nba-xpm', f'{y}.json')))['players']}
S, yv, X, G = [], [], [], {'sxpm': [], 'txpm': [], 'sx0': []}
for (pid, y), a in P.items():
    if y < 2010 or y >= 2026 or a['mp'] < 300 or B.career_best(P, pid, y) >= B.BAR: continue
    x = XS[y].get(pid)
    if not x or x.get('sxpm') is None: continue
    b = P.get((pid, y + 1)); s0 = R.shr(a['bpm'], a['mp'])
    f = B.bo_feats(a, s0, V[(pid, y)], R.marcel(P, pid, y))
    X.append(f['base'] + sum([f[k] for k in keep], [])); S.append(y + 1)
    yv.append(1.0 if (b and b['mp'] >= 1000 and R.shr(b['bpm'], b['mp']) >= B.BAR) else 0.0)
    for k in G: G[k].append((x.get(k) if x.get(k) is not None else x['xpm']) - s0)
S, yv, X = np.array(S, float), np.array(yv), np.array(X)


def run(Z):
    def ll(p, te):
        p = np.clip(p, 1e-6, 1 - 1e-6); return (float(-(yv[te] * np.log(p) + (1 - yv[te]) * np.log(1 - p)).sum()), float(te.sum()))
    def fp(trn, te):
        b0, b = L.logit(Z[trn], yv[trn]); return L.sig(b0 + Z[te] @ b)
    return L.loso(S, fp, ll)
rb = run(X); out = {'n': len(yv), 'rate': round(float(yv.mean()), 4), 'keep': keep}
for k, lab in (('sxpm', 'pXPM gap added'), ('sx0', 'old shrunk XPM gap added'), ('txpm', 'rXPM gap added')):
    out[lab] = L.compare(rb, run(np.column_stack([X, G[k]]))); print(lab, out[lab], flush=True)
json.dump(out, open(os.path.join(C.HERE, 'nba_breakout.json'), 'w'), indent=1)
