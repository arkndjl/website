# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""OVR round 2 (Nov 28 2026, Noah: "look for any way we can improve the OVR model"). New ideas, each scored against the
live OVR form (the shipped inputs) through the same gate, leaving one season out:
  role     playing time a game this season (minutes or TOI a game): what coaches show they think of him
  trend    this season's rate minus last season's (0 and a flag when he has no last season)
  split    the defensive part of the rate on its own weight (NBA pD-XPM; NHL the defensive half of WAR), so offense and
           defense can carry forward at different rates
  ageP     age x rate: young players' good rates carry forward differently from veterans'
  hpm      (NHL) HPM over replacement beside pWAR
python3 scripts/research/ovr_nov28/round2.py [nba nhlF nhlD nhlG soccer] -> research/ovr_research.json 'round2'"""
import json, math, os, sys, itertools
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE)
import suite
from engine import Engine, passes

OUT = os.path.join(ROOT, 'research', 'ovr_research.json')


def games(sport):
    """(season, id) -> games, from the season files"""
    g = {}
    if sport == 'nba':
        import nba
        for s in range(2010, 2028):
            d = nba.season_file(s)
            if d:
                for p in d['players']: g[(s, p['id'])] = p.get('g')
    elif sport.startswith('nhl'):
        import nhl
        for s in range(2009, 2028):
            d = nhl.season_file(s)
            if d:
                for p in d['players']: g[(s, p['id'])] = p.get('gp') or p.get('g')
    return g


def load(sport):
    if sport == 'nba':
        import nba; return nba.rows(), dict(cap=2000, repl=lambda r: nba.REPL), 'nba'
    if sport.startswith('nhl'):
        import nhl; g = sport[3:]; return nhl.rows(g), dict(cap=3000 if g == 'G' else 1200, repl=lambda r: 0.0), sport
    import soccer; return soccer.rows(), dict(cap=3000, repl=lambda r: 0.0), 'soccer'


def go(sport):
    rows, kw, key = load(sport)
    R0 = json.load(open(OUT)); live = R0[key]['ship']
    G = games(sport)
    prev = {(r['s'], r['id']): r['P'] for r in rows}
    for r in rows:
        gp = G.get((r['s'], r['id'])) or r.get('games')
        r['_pg'] = r['n'] / gp if gp else None
        pp = prev.get((r['s'] - 1, r['id']))
        r['_tr'] = (r['P'] - pp) if pp is not None else 0.0; r['_hp'] = 1.0 if pp is not None else 0.0
    E = Engine(rows, kw['cap'], kw['repl'])
    R = E.rows
    B, consts = suite.builders(R, 27.0)
    pgs = sorted(r['_pg'] for r in R if r['_pg']); mpg = pgs[len(pgs) // 2] if pgs else 1.0
    ag = lambda r: (r['age'] or 27.0) - 27.0
    new = {'role': lambda r: [math.log((r['_pg'] or mpg) / mpg)],
           'trend': lambda r: [r['_tr'], r['_hp']],
           'ageP': lambda r: [ag(r) * r['P']]}
    if any(r.get('Pd') is not None for r in R): new['split'] = lambda r: [r['Pd'] if r.get('Pd') is not None else 0.0]
    if any(r.get('P0') is not None for r in R): new['hpm'] = lambda r: [r['P0'] if r.get('P0') is not None else 0.0]
    if not any(r['_pg'] for r in R): new.pop('role')
    B.update(new)
    base = E.score(lambda tr: suite.feats(B, live), 'live')
    out = {'live': live, 'tests': {}}
    res = {}
    for nm in new:
        res[nm] = E.score(lambda tr, nm=nm: suite.feats(B, live + [nm]), nm)
        c = Engine.compare(res[nm], base); c['pass'] = passes(c); out['tests'][nm] = c
    ok = [k for k, c in out['tests'].items() if c['pass']]
    best = None
    for m in range(1, len(ok) + 1):
        for sub in itertools.combinations(ok, m):
            v = E.score(lambda tr, sub=sub: suite.feats(B, live + list(sub)), 'combo'); c = Engine.compare(v, base)
            if passes(c) and (best is None or v['MSE'] < best[0]['MSE'] - 1e-9): best = (v, list(sub), c)
    if best: out['combo'] = dict(best[2], feats=best[1])
    out['ship'] = best[1] if best else []
    # the pooled fit of the live form plus what passed, for scripts/ovr.py (consts: the build's feature constants)
    allf = live + out['ship']
    out['beta'] = [round(b, 5) for b in suite.wls([[1.0] + suite.feats(B, allf)(r) for r in R], [r['Y'] for r in R], [E.w(r) for r in R])]
    out['feats'] = allf; out['consts'] = dict(consts, mpg=round(mpg, 3))
    return out


if __name__ == '__main__':
    A = json.load(open(OUT)); A.setdefault('round2', {})
    for sp in sys.argv[1:] or ['nba', 'nhlF', 'nhlD', 'nhlG', 'soccer']:
        A['round2'][sp] = go(sp)
        print(sp, json.dumps({k: (v.get('t'), v.get('tR'), v.get('tTeam'), v['pass']) for k, v in A['round2'][sp]['tests'].items()}), A['round2'][sp]['ship'], flush=True)
    json.dump(A, open(OUT, 'w'), indent=1)
