# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Basketball award races added Nov 23 2026, same engine and gate as scripts/awards_more.py (held-out log P vs the
null, Holm at .05 over the sport's whole list incl. the earlier races' p-values in data/awards_fit.json, gain > 0, most
seasons won). Preregistered in scripts/research/awards_nov23/{nba,cbb}/prereg.md. Results merge into
data/awards_fit.json (more: true); scripts/awards.py runs the ones that pass.

    python3 scripts/awards_bball.py nba      # Sixth Man, Most Improved, All-Defensive, All-Rookie, Coach of the Year
    python3 scripts/awards_bball.py cbb      # Naismith, AP, DPOY, Freshman, Cousy / West / Erving / Malone / Abdul-Jabbar

NBA history: Basketball-Reference award, per-game, standings and preseason-odds pages (scripts/awards_nba.py). CBB:
the Barttorvik research table and Wikipedia's winner lists (scripts/awards_cbb.py). numpy."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from awards_more import test, gate
from awards_research import OUT

NBA_LABEL = {'smoy': 'Sixth Man', 'mip': 'MIP', 'alldef': 'All-Defensive', 'allrookie': 'All-Rookie', 'coy': 'COY'}


def nba(cur):
    import awards_nba as A
    R, prev_ad = A.more_races()
    coy_cols = A.COY_COLS
    have = sum(any(t['has_ou'] for t in p) for _, p, _ in R['coy'])
    if have < len(R['coy']) - 2:
        print('nba coy: preseason lines in', have, 'of', len(R['coy']), 'seasons; running without ovr')
        coy_cols = [c for c in coy_cols if c != 'ovr']
    spec = {'smoy': (A.SMOY_COLS, ['vorx'], 3, None), 'mip': (A.MIP_COLS, ['d_vorx'], 3, None),
            'alldef': (A.ALLDEF_COLS, ['dxpm'], None, A.ALLDEF_K), 'allrookie': (A.ALLROOK_COLS, ['vorx'], None, A.ALLROOK_K),
            'coy': (coy_cols, ['wp'], 3, None)}
    new = {}
    for aw, (cols, null, depth, k) in spec.items():
        r = test(R[aw], cols, null, depth or 1, k=k)
        new[aw] = dict(r, award=aw, label=NBA_LABEL[aw], more=True)
        if k: new[aw]['k'] = k
    cur['nba'].setdefault('_prev', {})['alldef'] = prev_ad
    return new


CBB_LABEL = {'naismith': 'Naismith', 'ap': 'AP POY', 'dpoy': 'DPOY', 'frosh': 'Freshman', 'cousy': 'Cousy',
             'west': 'West', 'erving': 'Erving', 'malone': 'Malone', 'kareem': 'Abdul-Jabbar'}


def cbb(cur):
    import awards_cbb as C
    R = C.more_races()
    new = {}
    for aw in CBB_LABEL:
        cols, null = C.MORE[aw][1], C.MORE[aw][2]
        r = test(R[aw], cols, null, 1)
        new[aw] = dict(r, award=aw, label=CBB_LABEL[aw], more=True)
    return new


def drivers(sport, new):
    """the driver tests that passed (scripts/research/awards_nov23/<sport>/drivers.json) on each race they joined"""
    fn = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'research', 'awards_nov23', sport, 'drivers.json')
    if not os.path.exists(fn): return
    D = json.load(open(fn))
    for t in D['tests']:
        if t['pass'] and t['award'] in new:
            new[t['award']].setdefault('drivers', {})[t['driver']] = {k: t[k] for k in ('gain', 't', 'p', 'wins', 'n')}
            new[t['award']]['drivers'][t['driver']]['holm_n'] = D['holm_n']


def main(argv):
    want = [a for a in argv if a in ('nba', 'cbb')] or ['nba', 'cbb']
    cur = json.load(open(OUT))
    for sp in want:
        new = (nba if sp == 'nba' else cbb)(cur)
        drivers(sp, new)
        gate(cur, sp, new)
        cur[sp].update(new)
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main(sys.argv[1:])
