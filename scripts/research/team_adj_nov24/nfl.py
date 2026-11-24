#!/usr/bin/env python3
"""NFL two-way WAR (board blend .6 AV WAR + .4 XV) with the team adjustment, per side as BPM: offense players shift so
the offense's summed value tracks points scored a game, defense players so it tracks points allowed (centred within
season). Exposure = season snap share (sh, of a 17-game season); rate = WAR / sh, predictor shrunk sh / (sh + .2) as
scripts/nfl_war_research_nov03.py. XV weights for pair n are fit without seasons n and n+1 (point in time).
Pairs 2018-19 ... 2024-25 (nflverse, scripts/nfl_xv.py --prep). Also AV WAR alone and XV alone."""
import json, os, sys
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import core, nfl_xv as X, nfl_war as W

S = X.load(); X.zscore(S); ys = sorted(S); _, value, _ = W.sub_lines()


def xv(y, excl):
    w = X.fit_w(S, [v for v in ys if v not in excl], 20)
    wd = {f'{g}.{part}': float(v) for (g, part), v in zip(X.COLS, w)}
    qm = X.q_means({k: S[k] for k in S if k not in excl}, wd)
    return X.xv_of(S, y, wd, value, qm)


def season(y, xvs, mix):
    d = S[y]; parts, num, den, grp, team, nm, cg = [], defaultdict(float), defaultdict(float), {}, {}, {}, {}
    for p, x in zip(d['players'], xvs):
        if p['sh'] <= 0: continue
        side = 'O' if p['g'] in X.OFF else 'D'; t = f"{p['t']}|{side}"
        v = mix * p['war'] + (1 - mix) * x
        parts.append((p['pfr'], t, p['sh'])); num[p['pfr']] += v; den[p['pfr']] += p['sh']; grp[p['pfr']] = p['sub']
    for t, tm in d['teams'].items():
        team[f'{t}|O'] = (tm['pf'], tm['g']); team[f'{t}|D'] = (-tm['pa'], tm['g'])
        nm[f'{t}|O'] = nm[f'{t}|D'] = t
    return {'parts': parts, 'val': {k: num[k] / den[k] for k in num}, 'team': team, 'grp': grp, 'net': nm}


out = {}
pairs = [y for y in ys if y + 1 in S]
for nmx, mix in (('WAR (board: .6 AV + .4 XV)', .6), ('AV WAR', 1.0), ('XV', 0.0)):
    PD = {n: (season(n, xv(n, (n, n + 1)), mix), season(n + 1, xv(n + 1, (n, n + 1)), mix)) for n in pairs}
    D = {y: season(y, xv(y, (y,)), mix) for y in ys}            # same-season describe / slope: XV without its own season
    out[nmx] = core.run(D, pairs, .25, .4, nmx, pk=.2, PD=PD)
json.dump(out, open(os.path.join(HERE, 'nfl.json'), 'w'), indent=1)
