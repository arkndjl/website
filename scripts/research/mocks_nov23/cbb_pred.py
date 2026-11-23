"""F3 (prereg.md): new drivers for the CBB/NBA predictive mock (scripts/cbb_mock.py pred_order), leave one draft out.
Universes: ESPN final boards 2017-26 and the first No Ceilings board 2022-26 (the cbb_mock pools, make_pool).
ln slot = a + b ln consensus rank (+ c driver), each held-out draft re-ranked by it; loss = |ln slot - ln real slot|
(undrafted 75), as backtest_pred scores. Needs scripts/.cache/cbb/careers.json (scripts/cbb_careers_kit.py) and
/mnt/project-files/cbb (boards, frame).

    python3 scripts/research/mocks_nov23/cbb_pred.py   -> scripts/research/mocks_nov23/cbb_pred.json"""
import collections, json, math, os
import numpy as np
from common import OUT, paired, holm
import cbb_data as D
import cbb_mock as M
import cbb_boards as CB
import names as N
import cbb_feats as CF

UND = M.UND


def pools():
    past = M.past_boards(); slots = M.espn_slots()
    es = collections.defaultdict(list)
    for r in M.read_csv('espn'): es[int(r['draft_year'])].append(r)
    ndn = collections.defaultdict(list)
    for r in M.read_csv('nbadraftnet'):
        if r['board_date'] == 'final' and r['rank']: ndn[int(r['draft_year'])].append(r)
    nc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in M.read_csv('noceilings'): nc[int(r['draft_year'])][r['board_date']].append(r)
    fin, first = {}, {}
    for y in range(2017, 2027):
        rows = [(r['name'], r['school'], r['pos'], int(r['rank'])) for r in es.get(y, []) if r['rank']]
        pl = M.make_pool([rows], past.get(y, []), slots, y)
        nm = N.Matcher([{'name': r['name'], 'team': r['school'], 'rk': int(r['rank'])} for r in ndn.get(y, [])], name='name', team='team', pos=None, sport='basketball')
        dn = 1.5 * max([int(r['rank']) for r in ndn.get(y, [])] or [100])
        mv = None
        if y in nc:
            dates = sorted(nc[y]); f0 = dates[0]
            late = [d for d in dates if CB.days_to_draft(d, y) >= 45]
            if late and late[-1] != f0:
                m0 = N.Matcher([{'name': r['name'], 'team': r['school'], 'rk': int(r['rank'])} for r in nc[y][f0]], name='name', team='team', pos=None, sport='basketball')
                m1 = N.Matcher([{'name': r['name'], 'team': r['school'], 'rk': int(r['rank'])} for r in nc[y][late[-1]]], name='name', team='team', pos=None, sport='basketball')
                d0 = 1.5 * max(int(r['rank']) for r in nc[y][f0]); d1 = 1.5 * max(int(r['rank']) for r in nc[y][late[-1]])
                mv = (m0, m1, d0, d1)
        for p in pl:
            p['year'] = y
            CF.attach(p, y, final_season=True)
            if p['ranks']:
                r = nm.find(p['name'], p['school'])[0]
                p['disp'] = abs(math.log(p['ranks'][0]) - math.log(r['rk'] if r else dn))
            else: p['disp'] = 0.0
            if mv and p['ranks']:
                a = mv[0].find(p['name'], p['school'])[0]; b = mv[1].find(p['name'], p['school'])[0]
                p['move'] = math.log(a['rk'] if a else mv[2]) - math.log(b['rk'] if b else mv[3])
            else: p['move'] = 0.0
        fin[y] = pl
    for y in range(2022, 2027):
        f0 = min(nc[y])
        rows = [(r['name'], r['school'], r['pos'], int(r['rank'])) for r in nc[y][f0]]
        pl = M.make_pool([rows], past.get(y, []), slots, y)
        for p in pl:
            p['year'] = y
            CF.attach(p, y, final_season=False)
        first[y] = pl
    return fin, first


def lodo(P, extra):
    """P: {year: pool}; returns per-row loss list and the year of each row, in a fixed order"""
    yrs = sorted(P)
    X = lambda p: [1.0, math.log(p['cons'])] + [p.get(k) or 0.0 for k in extra]
    Y = lambda p: math.log(min(p['actual'], UND))
    loss, grp = [], []
    for t in yrs:
        tr = [p for y in yrs if y != t for p in P[y]]
        b = np.linalg.lstsq(np.array([X(p) for p in tr]), np.array([Y(p) for p in tr]), rcond=None)[0]
        te = P[t]
        s = [float(np.dot(X(p), b)) for p in te]
        order = sorted(range(len(te)), key=lambda i: (s[i], te[i]['cons']))
        slot = [0] * len(te)
        for j, i in enumerate(order, 1): slot[i] = j
        loss += [abs(math.log(min(sl, UND)) - math.log(p['actual'])) for p, sl in zip(te, slot)]; grp += [t] * len(te)
    return np.array(loss), grp


def main():
    fin, first = pools()
    cover = {u: {k: int(sum(1 for y in P for p in P[y] if p.get(k))) for k in CF.KEYS + ['disp', 'move']} | {'n': sum(len(P[y]) for y in P)}
             for u, P in (('final', fin), ('first', first))}
    tests = []
    for uni, P, drivers in (('final', fin, ['aa', 'poy', 'cpoy', 'age_c', 'disp', 'move', 'trend', 'hm', 'comb']),
                            ('first', first, ['age_c', 'trend', 'hm', 'aa_prev'])):
        l0, g = lodo(P, [])
        for d in drivers:
            l1, _ = lodo(P, [d])
            allp = [p for y in P for p in P[y]]
            b = np.linalg.lstsq(np.array([[1.0, math.log(p['cons']), p.get(d) or 0.0] for p in allp]),
                                np.array([math.log(min(p['actual'], UND)) for p in allp]), rcond=None)[0]
            res = paired(l0, l1, g)
            res.update({'model': 'F3', 'universe': uni, 'driver': d, 'coef': round(float(b[-1]), 4), 'n': len(l0),
                        'err': [round(float(l0.mean()), 4), round(float(l1.mean()), 4)]})
            tests.append(res)
    holm(tests)
    json.dump({'_readme': 'prereg.md F3: CBB predictive mock drivers; loss |ln slot - ln real| (undrafted 75), LODO; coef = ln slot per unit.',
               'coverage': cover, 'tests': tests}, open(os.path.join(OUT, 'cbb_pred.json'), 'w'), indent=1)
    print(json.dumps(cover))
    for t in tests:
        print(f"{t['universe']:6} {t['driver']:8} coef {t['coef']:+.3f} gain {t['gain']:+.5f} t {t['t']:+.2f} p {t['p']:.4f} won {t['won']}/{t['of']} err {t['err']} pass {t['pass']}")


if __name__ == '__main__':
    main()
