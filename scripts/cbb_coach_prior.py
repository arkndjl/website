#!/usr/bin/env python3
"""The head coach's record against the preseason projection: the CBB game model's prior term 'cres' (Oct 30 2026).

    python3 scripts/cbb_coach_prior.py      # cres into scripts/data/cbb_team_prior.json (history + the coming season),
                                            # coach misses into scripts/data/cbb_coach_miss.json

Each team-season's miss = its final net rating minus the walk's preseason prior net (cbb_games, run without cres).
A coach's cres for season s = the sum of his misses before s, any school, over (seasons + 2): a coach whose teams beat
the roster projection year after year starts above it. Coaches by season from Sports Reference (cbb_roster coaches;
the main coach of each school-season); the coming season's coach from ESPN's roster feed, matched to a Sports Reference
id (last season's coach at the school, else the same name anywhere). First-time head coaches have no history (0).
Misses count from 2015 (2014's prior had no history behind it).

Research (scripts/cbb_oct30_research.py, data/cbb_oct30_research.json): margin MAE 2016-20 t -1.85, 2021-26 -.0046
(t -3.9), lined -.0026 (t -2.4); both portal halves (2021-23 t -2.8, 2024-26 t -2.7). Coefficient ~.6. The same at the
current school only (cres_s) passes neither tune nor lined held out; the program's own misses (pres) fail.
After a season ends, rerun this, then cbb_games.py --fit --keep-params.
"""
import json
import os
import sys
from collections import defaultdict

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C
import cbb_roster as R
import names as N

MISS = os.path.join(HERE, 'data', 'cbb_coach_miss.json')
K = 2.0          # shrink: seasons of zero miss added to each coach's record
RES0 = 2015


def misses():
    """(season, Barttorvik team) -> final net - preseason prior net, from the shipped walk without cres"""
    C.PRIOR_F = [k for k in C.PRIOR_F if k != 'cres']
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    W, _ = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
    out = {}
    for s in sorted(W.final):
        if s < RES0 or s not in d1s:
            continue
        p, _ = W.season_prior(s, sorted(d1s[s]))
        for t, v in p.items():
            b = btname.get(t)
            if b and t in W.final[s]:
                out[(s, b)] = W.final[s][t]['net'] - v['net']
    return out


def slug_name(slug):
    return N.key(' '.join(x for x in slug.split('-') if not x.isdigit()))


def main():
    miss = misses()
    tprior = json.load(open(C.TPRIOR))
    raw = R.coach_feats(R.load_coaches(), tprior, raw=True)
    hist = defaultdict(list)
    for s in sorted(raw):
        for t, v in raw[s].items():
            if (s, t) in miss:
                hist[v['coach']].append((s, t, round(miss[(s, t)], 3)))

    def cres(coach, s):
        h = [m for ss, _, m in hist.get(coach, []) if ss < s]
        return round(sum(h) / (len(h) + K), 3)
    n = 0
    for s in sorted(raw):
        T = tprior.get(str(s))
        if not T:
            continue
        for t, v in raw[s].items():
            if t in T:
                T[t]['cres'] = cres(v['coach'], s); n += 1
    live = C.LAST + 1
    last = max(raw)
    by_name = defaultdict(list)
    for s in sorted(raw):
        for t, v in raw[s].items():
            by_name[slug_name(v['coach'])].append((s, v['coach']))
    found = new = 0
    for t, c in R.espn_coaches().items():
        L = raw.get(live - 1, {}).get(t) if live - 1 <= last else None
        coach = L['coach'] if L and R.same_coach(c, L['coach']) else None
        if coach is None:
            cands = {cc for _, cc in by_name.get(N.key(f"{c.get('firstName', '')} {c.get('lastName', '')}"), [])}
            coach = max(cands, key=lambda cc: max(ss for ss, x in by_name[slug_name(cc)] if x == cc)) if cands else None
            new += 1
        if t in tprior.get(str(live), {}):
            tprior[str(live)][t]['cres'] = cres(coach, live) if coach else 0.0
            found += coach is not None
    with open(C.TPRIOR, 'w') as fh:
        json.dump(tprior, fh, separators=(',', ':'))
    with open(MISS, 'w') as fh:
        json.dump({c: v for c, v in sorted(hist.items())}, fh, separators=(',', ':'))
    print(f'cres on {n} history team-seasons; {live}: {found} coaches with a Sports Reference id ({new} not last season\'s)')


if __name__ == '__main__':
    main()
