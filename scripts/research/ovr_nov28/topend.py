# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""OVR top end (Nov 28 2026, Noah: "are we sure stretching it at the top is the right move?"). The same rate put on 0-99 three
ways, each scored on what OVR is meant to track, leaving one season out (NBA 2011-25, NHL 2010-25):
  piece   the live mapping: replacement 60, median starter 75, mean of each season's best 97 (two slopes, cap 99, floor 20)
  lowline one slope through replacement 60 and the median starter 75, cap 99 (linear in value until the cap)
  topline one slope through replacement 60 and the season's best 97 (linear in value; the median starter lands lower)
  pct     the player's percentile among the season's qualified players x 99 (a pure rank)
Targets: next season's team result from the minutes-weighted mean grade (team R2), and each player's next-season value
((rate - replacement) x minutes) from his grade (Pearson r). Paired t over held-out seasons against piece.
python3 scripts/research/ovr_nov28/topend.py -> research/ovr_research.json 'topend'"""
import bisect, json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import team as T
from engine import wls, pearson, paired_t
import ovr as O

RES = os.path.join(ROOT, 'research', 'ovr_research.json')
K = json.load(open(os.path.join(ROOT, 'data', 'ovr_fit.json')))['anchors']


def maps(Kx, pool):
    r, s, t = Kx['r'], Kx['s'], Kx['t']; pool = sorted(pool)
    cl = lambda g: max(20.0, min(99.0, g))
    return {'piece': lambda z: O.grade(z, Kx),
            'lowline': lambda z: cl(60 + 15 * (z - r) / (s - r)),
            'topline': lambda z: cl(60 + 37 * (z - r) / (t - r)),
            'pct': lambda z: 99.0 * bisect.bisect_left(pool, z) / len(pool)}


def run(sport):
    S = T.nba_seasons() if sport == 'nba' else T.nhl_seasons(); nba = sport == 'nba'
    Kx = K['nba'] if nba else K['nhl']        # NHL z here is WAR a 60: put on a forward's full season (x 1129 / 60) to read the points
    sc = 1.0 if nba else K['nhl']['toi']['F'] / 60
    pool = [x['z'] * sc for _, tt in S for pl in tt.values() for x in pl if x['z'] is not None and x['w0'] and x['w0'] >= (500 if nba else 400)]
    M0 = maps(Kx, pool); M = {k: (lambda z, f=f: f(z * sc)) for k, f in M0.items()}
    tg = (lambda pl: sum(x['y'] for x in pl) / sum(x['w1'] for x in pl) * 5) if nba else (lambda pl: sum(x['y'] for x in pl))
    res = {k: {'team': [], 'val': []} for k in M}
    for s, teams in S:
        tr = [t2 for s2, t2 in S if s2 != s]
        nz = [x['y'] / x['w1'] * (1 if nba else 60) for tt in tr for pl in tt.values() for x in pl if x['z'] is None and x['w1']]
        nzv = st.mean(nz)
        for k, f in M.items():
            g = lambda x: f(x['z'] if x['z'] is not None else nzv)
            feat = lambda pl: sum(g(x) * x['w1'] for x in pl) / sum(x['w1'] for x in pl)
            X = [[1.0, feat(pl)] for tt in tr for pl in tt.values()]; y = [tg(pl) for tt in tr for pl in tt.values()]
            b = wls(X, y, [1.0] * len(y))
            res[k]['team'].append(pearson([b[0] + b[1] * feat(pl) for pl in teams.values()], [tg(pl) for pl in teams.values()]) ** 2)
            xs = [x for pl in teams.values() for x in pl if x['z'] is not None]
            repl = -1.4 if nba else 0.0
            res[k]['val'].append(pearson([f(x['z']) for x in xs], [(x['y'] / x['w1'] * (1 if nba else 60) - repl) * x['w1'] for x in xs]))
    out = {}
    for k, v in res.items():
        out[k] = {'team': round(st.mean(v['team']), 4), 'val': round(st.mean(v['val']), 4)}
        if k != 'piece':
            out[k]['tTeam'] = paired_t(v['team'], res['piece']['team']); out[k]['tVal'] = paired_t(v['val'], res['piece']['val'])
            out[k]['winsTeam'] = sum(1 for a, b in zip(v['team'], res['piece']['team']) if a > b); out[k]['of'] = len(v['team'])
    return out


if __name__ == '__main__':
    A = json.load(open(RES)); A['topend'] = {sp: run(sp) for sp in ('nba', 'nhl')}
    print(json.dumps(A['topend'], indent=1)); json.dump(A, open(RES, 'w'), indent=1)
