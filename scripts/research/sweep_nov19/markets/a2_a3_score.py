# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""A2 (NBA availability floor of an active candidate) and A3 (CFB temperature / pace per game played): scores from
the as-of rows written by scripts/awards_asof.py.
    python3 a2_a3_score.py a2 <rows dir> <out.json>
    python3 a2_a3_score.py a3 <rows dir> <out.json>"""
import collections, json, math, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
FLOOR = 1e-3


def nll(r): return -math.log(max(r['p'][r['w']], FLOOR) if r['w'] is not None else FLOOR)


def tstat(d):
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0
    return m, (m / (sd / math.sqrt(n)) if sd > 0 else 0.0)


def by_season(base, cand, seasons, awards):
    out = {}
    for s in seasons:
        d = [nll(cand[k]) - nll(base[k]) for k in base if k[0] == s and k[1] in awards and k in cand]
        if d: out[s] = sum(d) / len(d)
    return out


def a2(rdir, outfn):
    ld = lambda tag: {(r['s'], r['aw'], r['cp']): r for r in json.load(open(os.path.join(rdir, f'rows_nba{tag}.json'))) if r['var'] == 'box'}
    base = ld('')
    grid = {a: ld(f'_av{a}') for a in ('0.80', '0.85', '0.90', '0.95')}
    AW = ('mvp', 'dpoy')
    tune_s, held_s = range(2019, 2024), range(2024, 2027)
    tune = {a: sum(nll(c[k]) - nll(base[k]) for k in base if k[0] in tune_s and k[1] in AW) for a, c in grid.items()}
    A = min(tune, key=tune.get)
    n_tune = sum(1 for k in base if k[0] in tune_s and k[1] in AW)
    hs = by_season(base, grid[A], held_s, AW)
    m, t = tstat(list(hs.values()))
    rows = [(k, round(nll(base[k]), 3), round(nll(grid[A][k]), 3)) for k in sorted(base) if k[0] in held_s and k[1] in AW]
    out = {'A': float(A), 'tune_d_by_A': {a: round(v / n_tune, 4) for a, v in tune.items()}, 'tune_rows': n_tune,
           'held_rows': len(rows), 'held_by_season': {s: round(v, 4) for s, v in hs.items()}, 'held_d': round(m, 4), 'held_t': round(t, 2),
           'held_ll_base': round(sum(r[1] for r in rows) / len(rows), 4), 'held_ll_cand': round(sum(r[2] for r in rows) / len(rows), 4),
           'rows': [(list(k), a, b) for k, a, b in rows]}
    out['pass'] = bool(t <= -2 and tune[A] < 0 and sum(v < 0 for v in hs.values()) >= 2)
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, indent=1))
    for r in out['rows']: print(r)
    json.dump(out, open(outfn, 'w'), indent=1)


def a3(rdir, outfn):
    import awards_asof as AS
    from awards_research import t_sf
    base = json.load(open(os.path.join(rdir, 'rows_cfb.json')))
    out = {}
    sc = AS.score(base, 'cfb')
    sc['pass_raw'] = bool(sc['t'] <= -2 and sc['d_insample'] < 0 and sc['a_all'] > 0 and sc['wins'] > sc['seasons'] / 2)
    out['A3a'] = sc
    print('A3a', {k: v for k, v in sc.items() if k != 'rel'}); [print('   ', x) for x in sc['rel']]
    byaw = collections.defaultdict(list)
    for r in base: byaw[r['aw']].append(nll(r))
    out['ll_by_award'] = {a: (len(v), round(sum(v) / len(v), 4)) for a, v in byaw.items()}
    print(out['ll_by_award'])
    fn = os.path.join(rdir, 'rows_cfb_pacegp.json')
    if os.path.exists(fn):
        b = {(r['s'], r['aw'], r['cp']): r for r in base}
        c = {(r['s'], r['aw'], r['cp']): r for r in json.load(open(fn))}
        seasons = sorted({k[0] for k in b})
        hs = by_season(b, c, seasons, ('heisman', 'maxwell', 'camp', 'obrien'))
        m, t = tstat(list(hs.values()))
        n = len(hs)
        out['A3b'] = {'seasons': n, 'rows': len([k for k in b if k in c]), 'd': round(m, 4), 't': round(t, 2), 'p': round(t_sf(-t, n - 1), 5),
                      'better': sum(v < 0 for v in hs.values()),
                      'll_base': round(sum(nll(b[k]) for k in b if k in c) / len(c), 4), 'll_cand': round(sum(nll(c[k]) for k in c if k in b) / len(c), 4)}
        out['A3b']['pass_raw'] = bool(t <= -2 and out['A3b']['better'] > n / 2)
        print('A3b', out['A3b'])
    json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    {'a2': a2, 'a3': a3}[sys.argv[1]](sys.argv[2], sys.argv[3])
