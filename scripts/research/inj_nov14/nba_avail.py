#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""J3 (NBA play chance) and J4 (report trajectory) of PREREG.md.

    python3 scripts/research/inj_nov14/nba_prev_reports.py     # once: the day-before reports (J4)
    python3 scripts/research/inj_nov14/nba_avail.py            # writes data/inj_nov14_nba.json
"""
import json
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import harness as H             # noqa: E402
import nba_games as N           # noqa: E402
from logit_ridge import fit_ridge, predict, pick_lambda, logloss   # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'inj_nov14_nba.json')
PREV = os.path.join(N.ROOT, 'scripts', '.cache', 'nba', 'prev_reports.json')
ROWS = os.path.join(N.ROOT, 'scripts', '.cache', 'nba', 'inj_nov14_rows.pkl')
TUNE, HELD = (2020, 2021, 2022), (2023, 2024, 2025, 2026)
LISTED = ('Questionable', 'Doubtful', 'Probable')


def build():
    F = json.load(open(os.path.join(N.ROOT, 'data', 'nba_games_fit.json')))
    games, names = N.load_hist()
    inj = N.load_inj()
    try:
        prev = json.load(open(PREV))
    except OSError:
        prev = {}
    params = {**F['params'], 'b2b': {'P': {}, 'M': {}}}
    m = N.Model(names, F['P'], inj=inj, **params)
    rows = []
    gp = defaultdict(lambda: [0, 0])            # (S, pid) -> [played, club games while on it]
    club = defaultdict(lambda: [0.0, 0.0])      # (S, team, status) -> [played, n]
    rec = defaultdict(lambda: [0, 0])           # (S, team) -> [wins, games]
    last = {}                                   # pid -> (status, played) at his club's previous game
    match = defaultdict(lambda: [0, 0])         # season -> [report names matched to a rostered player, names]
    for g in games:
        m.feats(g)
        S = g['S']
        if g.get('fin') and g.get('pl') and S >= 2020 and g.get('t', 2) == 2 or (g.get('fin') and g.get('pl') and S >= 2020):
            rep = inj.get(g['id'])
            pv = prev.get(g['id']) if g['id'] in prev else None
            pvk = {N.norm(k): v for k, v in pv.items()} if pv else pv
            if rep is not None:
                keys = set()
                for t in (g['h'], g['a']):
                    keys |= {N.norm(names.get(p, '')) for p in m.members[t]}
                match[S][0] += sum(1 for k in rep if k in keys); match[S][1] += len(rep)
            for t in (g['h'], g['a']):
                if t not in g['pl']:
                    continue
                mins = {p: mn for p, mn in g['pl'][t]}
                tip = N.tipdt(g)
                lt = m.last.get(t)
                days = 3 if not lt else max(0, min(5, (N.gday(tip) - N.gday(lt[0])).days))
                w_, n_ = rec[(S, t)]
                for p in m.roster(t):
                    w, n = m.role[p]
                    R = w / n if n else 0
                    if R < 8:
                        continue
                    key = N.norm(names.get(p, ''))
                    st = rep.get(key) if rep is not None else None
                    age = m.ages.get(p, 0)
                    pl = float(mins.get(p, 0) > 0)
                    if rep is not None:
                        a, c = gp[(S, p)], club[(S, t, st or 'none')]
                        rows.append({'S': S, 'day': str(N.gday(tip)), 'gid': g['id'], 'p': p, 't': t, 'st': st or 'none', 'bk': N.bucket(m.streak[p]),
                                     'n2': t in m.night2, 'R': R, 'age': age, 'grp': N.b2b_group(age, R), 'home': float(t == g['h'] and not g.get('n')),
                                     'days': days, 'club': (c[0], c[1]), 'own': (a[0], a[1]), 'last': last.get(p, ('first', 1.0)),
                                     'gnum': n_, 'wsh': (w_ / n_ if n_ >= 55 else 0.0), 'late': float(n_ >= 55), 'po': float(g.get('t', 2) == 3),
                                     'prev': (None if pvk is None else pvk.get(key, 'none')), 'played': pl})
                        c[0] += pl; c[1] += 1
                    gp[(S, p)][0] += pl; gp[(S, p)][1] += 1
                    last[p] = (st or ('none' if rep is not None else 'norep'), pl)
            if g.get('t', 2) == 2:
                hw = g['hs'] > g['as']
                rec[(S, g['h'])][0] += hw; rec[(S, g['h'])][1] += 1
                rec[(S, g['a'])][0] += (not hw); rec[(S, g['a'])][1] += 1
        m.update(g)
    pickle.dump((rows, dict(match)), open(ROWS, 'wb'))
    return rows, dict(match)


def cat(vals, mask, minn=30, other='other'):
    """one-hot of the levels with minn+ tune rows; the first (most common) level is the reference"""
    from collections import Counter
    c = Counter(v for v, k in zip(vals, mask) if k)
    lv = [v for v, n in c.most_common() if n >= minn]
    ref, lv = lv[0], lv[1:]
    M = np.array([[float(v == x) for x in lv] for v in vals])
    return M, [str(x) for x in lv], ref


def main():
    if os.path.exists(ROWS) and '--rebuild' not in sys.argv:
        R, match = pickle.load(open(ROWS, 'rb'))
    else:
        R, match = build()
    print('rows', len(R), 'report names matched to a rostered player by season', {s: round(a / max(b, 1), 3) for s, (a, b) in sorted(match.items())}, flush=True)
    S = np.array([r['S'] for r in R]); y = np.array([r['played'] for r in R]); w = np.array([r['R'] for r in R])
    A, B = np.isin(S, TUNE), np.isin(S, HELD)
    DAY = np.array([r['day'] for r in R])
    st = np.array([r['st'] for r in R]); bk = np.array([r['bk'] for r in R])
    # base: the live rule refit on tune
    tab = {}
    for s_ in set(st):
        k = A & (st == s_)
        if k.sum():
            tab[s_ + 'all'] = float((w[k] * y[k]).sum() / w[k].sum())
        for b_ in range(5):
            k2 = k & (bk == b_)
            if k2.sum() >= 30:
                tab[s_ + str(b_)] = float((w[k2] * y[k2]).sum() / w[k2].sum())
    n2 = np.array([r['n2'] for r in R]); grp = np.array([r['grp'] for r in R])
    mult = {}
    for g_ in set(grp):
        k = A & (st == 'none') & (bk == 0) & (grp == g_)
        a, b = k & n2, k & ~n2
        if a.sum() >= 150:
            mult[g_] = float((w[a] * y[a]).sum() / w[a].sum()) / float((w[b] * y[b]).sum() / w[b].sum())
    p0 = np.array([tab.get(s_ + str(b_), tab.get(s_ + 'all', 0.9)) for s_, b_ in zip(st, bk)])
    k = n2 & (st == 'none') & (bk == 0)
    p0[k] = np.minimum(1.0, p0[k] * np.array([mult.get(g_, 1.0) for g_ in grp[k]]))
    # candidate
    rate = {s_: tab[s_ + 'all'] for s_ in set(st) if s_ + 'all' in tab}
    cols, names = [], []
    M, lv, ref = cat([f'{a}|{b}' for a, b in zip(st, bk)], A); cols.append(M); names += ['cell=' + x for x in lv]
    M, lv, _ = cat([(r['grp'] if r['n2'] else 'no') for r in R], A); cols.append(M); names += ['n2=' + x for x in lv]
    M, lv, _ = cat([f"{r['last'][0]}|{int(r['last'][1])}" for r in R], A); cols.append(M); names += ['last=' + x for x in lv]
    age = np.array([r['age'] for r in R], float)
    num = np.column_stack([w, np.where(age > 0, age, 27.0), (age <= 0).astype(float), [r['home'] for r in R], [r['days'] for r in R],
                           [(r['club'][0] + 20 * rate.get(r['st'], .9)) / (r['club'][1] + 20) - rate.get(r['st'], .9) for r in R],
                           [(r['own'][0] + 8.5) / (r['own'][1] + 10) for r in R], [r['gnum'] / 82 for r in R], [r['wsh'] for r in R], [r['late'] for r in R]])
    names += ['role minutes', 'age', 'age unknown', 'home', 'days since last', 'club share at status', 'own play share', 'season progress', 'win share late', 'late']
    X = np.column_stack(cols + [num])
    lam = pick_lambda(X[A], y[A], S[A], w[A])
    b, mu, sd = fit_ridge(X[A], y[A], lam, w[A])
    p1 = predict(X, b, mu, sd)
    wn = w / w.mean()

    def cmp(pa, pb, k):
        r = H.paired(wn[k] * logloss(pa[k], y[k]), wn[k] * logloss(pb[k], y[k]), cluster=DAY[k])
        return {'n': int(k.sum()), 'base': round(float((wn[k] * logloss(pb[k], y[k])).sum() / wn[k].sum()), 4),
                'cand': round(float((wn[k] * logloss(pa[k], y[k])).sum() / wn[k].sum()), 4), 't': round(r['t'], 2), 'p': r['p'], 'G': r['G']}
    res = {'J3': {'lambda': lam, 'tune': cmp(p1, p0, A), 'held': cmp(p1, p0, B),
                  'heldByStatus': {s_: cmp(p1, p0, B & (st == s_)) for s_ in sorted(set(st)) if (B & (st == s_)).sum() > 200},
                  'heldBySeason': {int(s_): cmp(p1, p0, S == s_)['t'] for s_ in HELD},
                  'coef': {n: round(float(v), 3) for n, v in zip(['const'] + names, b)}, 'baseTable': {k_: round(v, 3) for k_, v in sorted(tab.items())}, 'n2mult': mult}}
    listed = np.isin(st, LISTED)
    kq = np.where(B & (st == 'Questionable'))[0]; o = kq[np.argsort(p1[kq])]
    res['J3']['calibHeldQ'] = [{'p': round(float(np.average(p1[c], weights=w[c])), 3), 'played': round(float(np.average(y[c], weights=w[c])), 3), 'n': int(len(c))} for c in np.array_split(o, 8)]
    groups = {'n2': ('n2=',), 'last': ('last=',), 'role': ('role minutes',), 'age': ('age',), 'home': ('home',), 'days': ('days since',),
              'club': ('club share',), 'own': ('own play',), 'season': ('season progress', 'win share', 'late')}
    drop = {}
    for g_, pre in groups.items():
        keep = [i for i, n in enumerate(names) if not any(n.startswith(q) for q in pre)]
        b2, mu2, sd2 = fit_ridge(X[A][:, keep], y[A], lam, w[A])
        p2 = predict(X[:, keep], b2, mu2, sd2)
        drop[g_] = {'all': cmp(p1, p2, B)['t'], 'listed': cmp(p1, p2, B & listed)['t']}
    res['J3']['dropOneHeldT'] = drop
    bF, muF, sdF = fit_ridge(X[A | B], y[A | B], lam, w[A | B])
    res['J3']['full'] = {'names': ['const'] + names, 'b': [float(v) for v in bF], 'mu': [float(v) for v in muF], 'sd': [float(v) for v in sdF], 'rate': rate, 'cellRef': ref}
    print(json.dumps({k_: v for k_, v in res['J3'].items() if k_ not in ('full', 'coef', 'baseTable')}, indent=1), flush=True)
    print(res['J3']['coef'])

    # J4: listed players, the day-before report
    has = np.array([r['prev'] is not None for r in R])
    L = listed & has
    pv = [f"{r['st']}|{r['prev']}" for r in R]
    M, lv, ref4 = cat(pv, A & L)
    lg = np.log(np.clip(p1, .005, .995) / (1 - np.clip(p1, .005, .995)))
    stM = np.column_stack([(st == 'Doubtful').astype(float), (st == 'Probable').astype(float)])
    Xb = np.column_stack([lg, stM]); Xc = np.column_stack([lg, stM, M])
    lam4 = pick_lambda(Xc[A & L], y[A & L], S[A & L], w[A & L])
    bb, mb, sb = fit_ridge(Xb[A & L], y[A & L], lam4, w[A & L]); pb = predict(Xb, bb, mb, sb)
    bc, mc, sc = fit_ridge(Xc[A & L], y[A & L], lam4, w[A & L]); pc = predict(Xc, bc, mc, sc)
    res['J4'] = {'lambda': lam4, 'rows': {'tune': int((A & L).sum()), 'held': int((B & L).sum()), 'listedNoPrevReport': int((listed & ~has & (A | B)).sum())},
                 'registered_vsJ3': {'tune': cmp(pc, p1, A & L), 'held': cmp(pc, p1, B & L)},
                 'strict_vsJ3RefitOnListed': {'tune': cmp(pc, pb, A & L), 'held': cmp(pc, pb, B & L)},
                 'heldBySeason': {int(s_): cmp(pc, p1, L & (S == s_))['t'] for s_ in HELD},
                 'coef': {n: round(float(v), 3) for n, v in zip(['const', 'logit J3', 'Doubtful', 'Probable'] + ['traj=' + x for x in lv], bc)}, 'ref': ref4}
    cells = {}
    for x in sorted(set(pv)):
        k = B & L & (np.array(pv) == x)
        if k.sum() >= 50:
            cells[x] = {'n': int(k.sum()), 'played': round(float(np.average(y[k], weights=w[k])), 3), 'J3': round(float(np.average(p1[k], weights=w[k])), 3), 'J4': round(float(np.average(pc[k], weights=w[k])), 3)}
    res['J4']['heldCells'] = cells
    bF4, mF4, sF4 = fit_ridge(Xc[(A | B) & L], y[(A | B) & L], lam4, w[(A | B) & L])
    res['J4']['full'] = {'names': ['const', 'logit J3', 'Doubtful', 'Probable'] + ['traj=' + x for x in lv], 'b': [float(v) for v in bF4], 'mu': [float(v) for v in mF4], 'sd': [float(v) for v in sF4], 'ref': ref4}
    print(json.dumps({k_: v for k_, v in res['J4'].items() if k_ != 'full'}, indent=1))
    # what live would read if both pass: J4 for listed players with a day-before report, J3 for the rest (descriptive)
    comp = np.where(L, pc, p1)
    res['composite_vsLive'] = {'tune': cmp(comp, p0, A), 'held': cmp(comp, p0, B),
                               'heldByStatus': {s_: cmp(comp, p0, B & (st == s_)) for s_ in sorted(set(st)) if (B & (st == s_)).sum() > 200}}
    kq = np.where(B & (st == 'Questionable'))[0]; o = kq[np.argsort(comp[kq])]
    res['composite_vsLive']['calibHeldQ'] = [{'p': round(float(np.average(comp[c], weights=w[c])), 3), 'played': round(float(np.average(y[c], weights=w[c])), 3), 'n': int(len(c))} for c in np.array_split(o, 8)]
    print(json.dumps(res['composite_vsLive'], indent=0))
    res['nameMatch'] = {int(s): round(a / max(b_, 1), 3) for s, (a, b_) in sorted(match.items())}
    json.dump({'prereg': 'scripts/research/inj_nov14/PREREG.md', **res}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
