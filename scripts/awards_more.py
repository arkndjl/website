# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Award races added after the first build, same engine and same gate (scripts/awards_research.py): the voter model
must beat the null on held-out seasons, Holm at .05 over the sport's whole list (the earlier races' p-values in
data/awards_fit.json plus the new ones), gain > 0 and most seasons won. Results are merged into data/awards_fit.json
under the sport; scripts/awards.py runs the ones that pass.

    python3 scripts/awards_more.py            # every race below
    python3 scripts/awards_more.py droy       # some

droy    NFL Defensive Rookie of the Year: rookie defenders from nflverse weekly defensive stats (the ESPN leader lists
        hold a handful a season), winner only
allnba  All-NBA: the 15 named, a top-k race (the exploded logit down the 15 slots), scored on the held-out
        log-likelihood of the 15
ballon  Ballon d'Or: big-five-league players by GAR with club and national-team honours (scripts/awards_soccer.py)
numpy."""
import json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import awards_engine as E
import names as NM
from awards_research import t_sf, holm, summarise, OUT, L2

DROY_COLS = ['sacks', 'dint', 'tfl', 'pd', 'ff', 'tackles', 'dtd', 'wp', 'r1']
DROY_NULL = ['sacks', 'dint']
ALLNBA_COLS = ['vorx', 'xpm', 'ppg', 'rpg', 'apg', 'wp', 'gfrac', 'prev_allnba']
ALLNBA_NULL = ['vorx']
ALLNBA_K = 15


def droy_pool(rows):
    return [r for r in rows if r['rookie'] and r['def'] and (r['tackles'] >= 20 or r['sacks'] >= 3 or r['dint'] >= 2)]


def droy_races():
    import awards_asof as B
    import awards_football as F
    W = F.nfl_winners('droy')
    races = []
    for S, (_, tot, _, _) in sorted(B.nfl_season_pools().items()):
        pool = droy_pool(tot.values())
        o = F._order(pool, W.get(S, [])[:1])
        if not o or o[0] is None:
            print('nfl', S, 'droy winner outside pool', W.get(S)); races.append((S, pool, [])); continue
        races.append((S, pool, o[:1]))
    return races


def allnba_named(season):
    """bbref ids of the 15 named, first team first, by voting points inside a team"""
    import awards_nba as A
    h = A.fetch(f'nba_awards_{season}.html', f'https://www.basketball-reference.com/awards/awards_{season}.html')
    rows = [(int((r.get('all_nba_team') or '9')[0]), -A.f(r.get('points_won')), r['_id'])
            for r in A.table(h, 'leading_all_nba') if r.get('_id') and (r.get('all_nba_team') or '')[:1] in '123' and r.get('all_nba_team')]
    return [i for _, _, i in sorted(rows)]


def allnba_races():
    import awards_nba as A
    R = A.seasons_data()['mvp']
    prev, races = {}, []
    for s, pool, _ in R:
        named = allnba_named(s)
        for r in pool: r['prev_allnba'] = prev.get(r['id'], 0)
        ids = [r['id'] for r in pool]
        miss = [i for i in named if i not in ids]
        if miss: print('nba', s, 'all-nba named outside pool', miss)
        races.append((s, pool, [ids.index(i) for i in named if i in ids]))
        for i in named: prev[i] = prev.get(i, 0) + 1
    return races, prev


def test(races, cols, null, depth, k=None):
    S = [s for s, _, _ in races]
    rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
    if k:
        full, base = E.loso_k(rr(cols), S, k, l2=L2), E.loso_k(rr(null), S, k, l2=L2)
    else:
        full, base = E.loso(rr(cols), S, l2=L2, depth=depth), E.loso(rr(null), S, l2=L2, depth=depth)
    pr = E.paired(full, base)
    b, mu, sd = E.fit([x for x in rr(cols) if x[1]], l2=L2, depth=k or depth)
    used = [s for (s, _, o) in races if o]
    return {'cols': cols, 'null': null, 'depth': k or depth, 'b': [round(v, 5) for v in b], 'mu': [round(v, 5) for v in mu],
            'sd': [round(v, 5) for v in sd], 'seasons': [min(used), max(used)],
            'test': {'model': summarise(full), 'null': summarise(base), 'gain': pr['gain'], 't': pr['t'],
                     'p': round(t_sf(pr['t'], pr['n'] - 1), 4), 'wins': pr['wins'],
                     'by': [{'s': x['season'], 'pw': round(x['pw'], 3), 'pw0': round(y['pw'], 3), 'hit': x['hit']}
                            for x, y in zip(full, base)]}}


def gate(cur, sport, new):
    """Holm over the sport's earlier races and the new ones; sets test.pass on the new"""
    old = [(a, v['test']['p']) for a, v in cur.get(sport, {}).items() if a != '_prev' and a not in new and 'test' in v]
    keys = [a for a, _ in old] + list(new)
    ok = holm([p for _, p in old] + [new[a]['test']['p'] for a in new])
    for a, k in zip(keys, ok):
        if a not in new: continue
        t = new[a]['test']
        t['pass'] = bool(k and t['gain'] > 0 and t['wins'] * 2 > t['model']['n'])
        t['holm_n'] = len(keys)
        print(f"{sport} {new[a]['label']:10s} held-out {t['model']['ll']:.3f} vs null {t['null']['ll']:.3f} gain {t['gain']:+.3f} "
              f"t {t['t']} p {t['p']} wins {t['wins']}/{t['model']['n']} hit {t['model']['hit']} vs {t['null']['hit']} "
              f"(Holm over {len(keys)})  {'PASS' if t['pass'] else 'fail'}", flush=True)


def main(argv):
    want = [a for a in argv if not a.startswith('-')] or ['droy', 'allnba', 'ballon']
    cur = json.load(open(OUT))
    nfl, nba = {}, {}
    if 'droy' in want:
        r = test(droy_races(), DROY_COLS, DROY_NULL, 1)
        nfl['droy'] = dict(r, award='droy', label='DROY', more=True)
    if 'allnba' in want:
        races, prev = allnba_races()
        r = test(races, ALLNBA_COLS, ALLNBA_NULL, ALLNBA_K, k=ALLNBA_K)
        nba['allnba'] = dict(r, award='allnba', label='All-NBA', k=ALLNBA_K, more=True)
        cur['nba'].setdefault('_prev', {})['allnba'] = prev
    soc = {}
    if 'ballon' in want:
        import awards_soccer as SO
        races, prev = SO.races()
        r = test(races, SO.COLS, SO.NULL, 3)
        soc['ballon'] = dict(r, award='ballon', label="Ballon d'Or", more=True)
        cur.setdefault('soccer', {})['_prev'] = {'ballon': prev}
    for sport, new in (('nfl', nfl), ('nba', nba), ('soccer', soc)):
        if not new: continue
        gate(cur, sport, new)
        cur[sport].update(new)
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main(sys.argv[1:])
