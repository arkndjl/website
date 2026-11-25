#!/usr/bin/env python3
"""T-D1 (prereg.md): rPA as the per-match mean of match-level rPA, shrunk k_m matches toward 0 -> tennis_rpa_mean.json
    python3 tennis_rpa_mean.py pass full ; python3 tennis_rpa_mean.py pass half ; python3 tennis_rpa_mean.py score
Round-1 passes.py with one more snapshot field (rpa_m); pickles in scripts/.cache/tennis/audit_nov24/port/."""
import json, os, pickle, statistics, sys
HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.abspath(os.path.join(HERE, '..', '..', 'tennis'))
sys.path.insert(0, R1)
import passes as PS  # noqa: E402
M = PS.M
OUT = os.path.join(PS.OUT, 'port')
KM_FILE = os.path.join(OUT, 'k_m.json')


def k_m():
    if os.path.exists(KM_FILE): return json.load(open(KM_FILE))['k_m']
    rows, _ = PS.load_rows()
    n = [r[10][0] + r[11][0] for r in rows if r[10] and r[11] and r[10][0] and r[11][0]]
    med = statistics.median(n); k = 300 / med
    os.makedirs(OUT, exist_ok=True); json.dump({'median_points': med, 'k_m': k}, open(KM_FILE, 'w'))
    return k


def run_pass(mode):
    K = k_m()
    snap0 = PS.snapshot

    def snapshot(m, e538, ss, year, P):
        out = snap0(m, e538, ss, year, P)
        import datetime as dt
        day = (dt.date(year, 12, 31) - M.DAY0).days
        for p, o in out.items():
            q = [x for x in m.pq.get(p, []) if x[0] >= day - 364 and x[2]]
            o['rpa_m'] = 100 * sum(x[1] / x[2] for x in q) / (len(q) + K) if q else None
            o['rpa_k'] = 100 * sum(x[1] for x in q) / (sum(x[2] for x in q) + 300) if q else None
        return out
    PS.snapshot = snapshot
    PS.OUT = OUT
    PS.run(mode)


def score():
    import numpy as np
    sys.argv = sys.argv[:1]
    import score as SC
    SC.NEED = SC.NEED + ('rpa_m',)
    SC.CAND = {'T-D1 rPA per-match mean': ('rpa_k', 'rpa_m', 'describe_held')}
    full = pickle.load(open(os.path.join(OUT, 'full.pkl'), 'rb')); half = pickle.load(open(os.path.join(OUT, 'half.pkl'), 'rb'))
    rk = SC.year_end_ranks(); SC.add_ranks(full['snaps'], rk); SC.add_ranks(half['snaps'], rk)
    dho, keys = SC.build(half['snaps'], half['matches'], 0, 5)
    din, _ = SC.build(full['snaps'], full['matches'], 0, 10)
    dpr, _ = SC.build(full['snaps'], full['matches'], 1, 10)
    res = SC.cand_test(dho, keys, 'rpa_k', 'rpa_m', True)
    res['player_r'] = {'base': SC.player_r(full['snaps'], 'rpa_k')['r'], 'cand': SC.player_r(full['snaps'], 'rpa_m')['r']}
    res['k_m'] = k_m()
    res['describe_in'] = {k: SC.summary(SC.score(din, keys.index(k), False))['r2'] for k in ('rpa_k', 'rpa_m')}
    res['predict'] = {k: SC.summary(SC.score(dpr, keys.index(k), True))['r2'] for k in ('rpa_k', 'rpa_m')}
    nb = int(res['seasons_better'].split('/')[0])
    res['pass'] = bool(res['p1'] < .05 and nb >= 9 and res['player_r']['cand'] >= res['player_r']['base'] - .01)
    print(res)
    json.dump(res, open(os.path.join(HERE, 'tennis_rpa_mean.json'), 'w'), indent=1)


if __name__ == '__main__':
    if sys.argv[1] == 'pass': run_pass(sys.argv[2])
    else: score()
