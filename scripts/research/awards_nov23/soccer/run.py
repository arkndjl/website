# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer awards research, Nov 23 2026 (pre-registration: prereg.md beside this file).

    python3 scripts/research/awards_nov23/soccer/run.py races     # new races: test, Holm over soccer's list, merge into data/awards_fit.json
    python3 scripts/research/awards_nov23/soccer/run.py drivers   # driver add-ons (report only)

Results -> results.json beside this file. numpy."""
import json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
import awards_engine as E
import awards_soccer_more as M
from awards_research import t_sf, holm, OUT, L2
from awards_more import test, gate

RES = os.path.join(HERE, 'results.json')


def save(key, val):
    cur = json.load(open(RES)) if os.path.exists(RES) else {}
    cur[key] = val
    json.dump(cur, open(RES, 'w'), indent=1, sort_keys=True)


def cols_of(a):
    return {'goldenboy': M.YOUNG_COLS, 'kopa': M.KOPA_COLS, 'yashin': M.YASHIN_COLS}.get(a, M.LEAGUE_COLS)


def races_cmd():
    R, prev = M.races()
    cur = json.load(open(OUT))
    new = {}
    for a, races in R.items():
        lab, _, lg, depth = M.AWARDS[a]
        n = sum(1 for _, _, o in races if o)
        print(a, 'seasons with the winner in the pool', n, 'of', len(races), flush=True)
        if n < 6: print(a, 'too few seasons, not tested'); continue
        new[a] = dict(test([r for r in races if r[2]], cols_of(a), M.NULL, depth), award=a, label=lab, more=True, lg=lg)
        new[a]['test']['out_of_pool'] = len(races) - n
    gate(cur, 'soccer', new)
    cur['soccer'].update(new)
    # Golden Boot per league: a stat title with no to-date scorer archive to test a projection on, so conviction only
    for lg, nm in M.LEAGUES.items():
        cur['soccer']['boot_' + lg.split('.')[0]] = {'award': 'boot_' + lg.split('.')[0], 'label': f'{nm} Golden Boot',
                                                    'stat': True, 'more': True, 'null': ['g'], 'test': {'pass': False}}
    pv = cur['soccer'].setdefault('_prev', {})
    for a in new: pv[a] = prev.get(a, {})
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    save('races', {a: {'cols': v['cols'], 'null': v['null'], 'test': {k: x for k, x in v['test'].items() if k != 'by'}}
                   for a, v in new.items()})
    print('wrote', OUT)


DRIVERS = {a: ['age', 'ucl'] for a in ('pl_pots', 'pfa', 'laliga', 'seriea', 'vdv', 'ligue1')}


def drivers_cmd():
    R, _ = M.races()
    res, ps, keys = {}, [], []
    for a, ds in DRIVERS.items():
        races = [(s, [dict(r, age=r.get('age') or 26.0) for r in p], o) for s, p, o in R[a] if o]
        S = [s for s, _, _ in races]
        rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
        cols = cols_of(a)
        base = E.loso(rr(cols), S, l2=L2, depth=1)
        for d in ds:
            full = E.loso(rr(cols + [d]), S, l2=L2, depth=1)
            pr = E.paired(full, base)
            p = t_sf(pr['t'], pr['n'] - 1)
            res[f'{a}:{d}'] = {'gain': pr['gain'], 't': pr['t'], 'p': round(p, 4), 'wins': pr['wins'], 'n': pr['n'],
                               'hit': sum(x['hit'] for x in full), 'hit0': sum(x['hit'] for x in base)}
            ps.append(p); keys.append(f'{a}:{d}')
    ok = holm(ps)
    for k, o in zip(keys, ok):
        r = res[k]
        r['pass'] = bool(o and r['gain'] > 0 and r['wins'] * 2 > r['n'])
        print(f"{k:16s} gain {r['gain']:+.3f} t {r['t']:5.2f} p {r['p']:.4f} wins {r['wins']}/{r['n']} hit {r['hit']} vs {r['hit0']} "
              f"(Holm over {len(keys)})  {'PASS' if r['pass'] else 'fail'}", flush=True)
    save('drivers', res)


if __name__ == '__main__':
    {'races': races_cmd, 'drivers': drivers_cmd}[sys.argv[1] if len(sys.argv) > 1 else 'races']()
