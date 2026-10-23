#!/usr/bin/env python3
"""Injury underpricing (Oct 23 2026): PR #349 found the closing line weights each game model's injury term at about
half what results do (NFL inj .60 vs 1.36, CBB .29 vs .48, NBA lin .41 vs .52). This turns that into bets three ways,
each held out against the close:

  1. residual: results minus the close on the injury term, by season (what the close leaves on the table)
  2. at the close, on results: (a) the injury part alone, e = a x term, a fit on the seasons before; (b) the model's
     gap with the injury term reweighted, E = c1 x gap + c2 x term (both fit on the seasons before); bet |E| >= X,
     X picked on the tuning seasons, then validation and test (the NFL rule framework: no opening lines)
  3. at the open, by the close (CLV): the open-to-close move on the term, and gap picks split by whether the injury
     part sides with them. This one ships, as the games_picks.py 'inj' segment family (fit_segments decides it)

    python3 scripts/close_target_research.py --build nfl nba cbb    # the designs (scripts/.cache/ct)
    python3 scripts/games_wf/cbb_wf.py                              # CBB rows carry 'ij' (the term's points)
    python3 scripts/injury_edge_research.py                         # data/injury_edge.json

NBA's lineup term carries the tip-time injury report, so its open numbers (part 3) are an upper bound and NBA gets no
segment; the close-based parts (1, 2) are fair for NBA because the report comes out before the close.
"""
import collections
import gzip
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import clv as C

CACHE = os.path.join(HERE, '.cache', 'ct')
TERM = {'nfl': 'inj', 'nba': 'lin', 'cbb': 'inj'}
# tuning / validation / test seasons for the close-based rules: the game models' held-out split (HELD in games_picks),
# its first two seasons validate and the rest test; tuning starts once the term has a season before it to fit on
SPLIT = {'nfl': ((2017, 2020), (2021, 2022), (2023, 2030)), 'nba': ((2017, 2021), (2022, 2023), (2024, 2030)),
         'cbb': ((2018, 2020), (2021, 2022), (2023, 2030))}
GRID = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
MIN_N, KEEP_T = 40, 1.65


def dec(o):
    return 1 + o / 100 if o > 0 else 1 + 100 / -o


def slope_t(x, r, day):
    """OLS slope of r on x (with an intercept) and its t, clustered by game day"""
    X = np.column_stack([np.ones(len(x)), x])
    b = np.linalg.lstsq(X, r, rcond=None)[0]
    e = r - X @ b
    XtX = np.linalg.inv(X.T @ X)
    M = np.zeros((2, 2))
    idx = collections.defaultdict(list)
    for i, d in enumerate(day):
        idx[d].append(i)
    for v in idx.values():
        s = X[v].T @ e[v]
        M += np.outer(s, s)
    V = XtX @ M @ XtX
    return round(float(b[1]), 3), round(float(b[1] / np.sqrt(V[1, 1])), 2), len(x)


def load(sp):
    z = np.load(os.path.join(CACHE, sp + '.npz'))
    keys = list(z['keys'])
    W = {str(r['id']): r for r in json.load(gzip.open(os.path.join(HERE, 'data', 'games_wf', sp + '.json.gz')))}
    x = z['X'][:, keys.index(TERM[sp])]
    rows = []
    for i, g in enumerate(z['gid']):
        r = W.get(str(g))
        if r and r.get('L') is not None and r.get('res') is not None:
            rows.append((r, float(x[i]), str(z['day'][i])))
    return rows


def record(sig, rows, X_, msk):
    """flat-stake results at the close for |sig| >= X_ on the masked rows, at the board's prices (-110 when none)"""
    prof = []
    for (r, _, _), s, m in zip(rows, sig, msk):
        if not m or np.isnan(s) or abs(s) < X_:
            continue
        side = 'home' if s > 0 else 'away'
        d = (r['res'] - r['L']) * (1 if s > 0 else -1)
        o = (r.get('oH') if side == 'home' else r.get('oA')) or -110
        prof.append(0.0 if d == 0 else (dec(o) - 1 if d > 0 else -1.0))
    n = len(prof)
    if n < 2:
        return {'n': n, 'roi': None, 't': None}
    p = np.array(prof)
    return {'n': n, 'roi': round(float(p.mean()), 4), 't': round(float(p.mean() / (p.std(ddof=1) / np.sqrt(n))), 2)}


def close_rules(sp, rows):
    S = np.array([r['S'] for r, _, _ in rows])
    x = np.array([v for _, v, _ in rows])
    y = np.array([r['res'] for r, _, _ in rows], float)
    L = np.array([r['L'] for r, _, _ in rows], float)
    g = np.array([r['m'] for r, _, _ in rows], float) - L
    ok = np.abs(g) < 4 * g.std()
    first = S[x != 0].min()
    e = np.full(len(y), np.nan)
    E = np.full(len(y), np.nan)
    for s in range(first + 1, S.max() + 1):
        tr, te = ok & (S < s) & (S >= first), ok & (S == s)
        if tr.sum() < 300 or not te.any():
            continue
        a = (x[tr] @ (y - L)[tr]) / (x[tr] @ x[tr])
        c = np.linalg.lstsq(np.column_stack([g[tr], x[tr]]), (y - L)[tr], rcond=None)[0]
        e[te], E[te] = a * x[te], c[0] * g[te] + c[1] * x[te]
    (t0, t1), (v0, v1), (h0, h1) = SPLIT[sp]
    out = {}
    for name, sig in (('injuryOnly', e), ('gapPlusInjury', E)):
        tu, va, he = ((S >= a_) & (S <= b_) for a_, b_ in ((t0, t1), (v0, v1), (h0, h1)))
        grid = [{'x': X_, **record(sig, rows, X_, tu)} for X_ in GRID]
        ok_ = [q for q in grid if q['n'] >= MIN_N and (q['roi'] or 0) > 0 and (q['t'] or 0) >= 1]
        best = max(ok_, key=lambda q: q['roi'])['x'] if ok_ else None
        m = {'sd': round(float(np.nanstd(sig)), 3), 'grid': grid, 'x': best, 'on': False}
        if best is None:
            m['why'] = 'no cut beat the vig on the tuning seasons'
        else:
            vr, hr = record(sig, rows, best, va), record(sig, rows, best, he)
            m.update({'val': vr, 'test': hr})
            m['on'] = vr['n'] >= 30 and (vr['roi'] or 0) > 0 and (vr['t'] or 0) >= KEEP_T and hr['n'] >= 30 and (hr['roi'] or 0) > 0
            m['why'] = None if m['on'] else 'lost on the validation or test seasons'
        out[name] = m
    return out


def open_side(sp, rows):
    """open-to-close move on the term, and the CLV of gap picks at the open split by the injury part"""
    op = [(r, v, d) for r, v, d in rows if r.get('Lo') is not None and not C.bad_open(sp, 'spread', r['Lo'], r['L'])]
    if not op:
        return None
    x = np.array([v for _, v, _ in op])
    day = [d for _, _, d in op]
    mv = np.array([r['L'] - r['Lo'] for r, _, _ in op])
    out = {'move': dict(zip(('slope', 't', 'n'), slope_t(x, mv, day))), 'split': []}
    for X_ in (3, 4, 4.5, 5, 6):
        for lab in ('with', 'against', 'none'):
            cr = []
            for r, _, _ in op:
                gap = r['m'] - r['Lo']
                if abs(gap) < X_:
                    continue
                ij = r.get('ij')
                if ij is None:
                    continue
                ij = ij if gap > 0 else -ij
                v = 'none' if abs(ij) < 0.5 else 'with' if ij > 0 else 'against'
                if v == lab:
                    cr.append(C.judge({}, sp, 'spread', 'home' if gap > 0 else 'away', r['Lo'], -110, r['L']).get('clvRet') or 0.0)
            if len(cr) > 5:
                c = np.array(cr)
                out['split'].append({'x': X_, 'inj': lab, 'n': len(c), 'clvRet': round(float(c.mean()), 4),
                                     't': round(float(c.mean() / (c.std(ddof=1) / np.sqrt(len(c)))), 2)})
    return out


def main():
    res = {'asof': str(np.datetime64('today')), 'term': TERM, 'split': SPLIT, 'sports': {}}
    for sp in ('nfl', 'nba', 'cbb'):
        rows = load(sp)
        S = np.array([r['S'] for r, _, _ in rows])
        x = np.array([v for _, v, _ in rows])
        resid = np.array([r['res'] - r['L'] for r, _, _ in rows], float)
        day = [d for _, _, d in rows]
        held = S >= SPLIT[sp][1][0]
        R = {'residual': {'held': dict(zip(('slope', 't', 'n'), slope_t(x[held], resid[held], [d for d, h in zip(day, held) if h]))),
                          'bySeason': {int(s): dict(zip(('slope', 't', 'n'), slope_t(x[S == s], resid[S == s], [d for d, k in zip(day, S == s) if k])))
                                       for s in np.unique(S) if x[S == s].std() > 0}},
             'termSd': round(float(x.std()), 3)}
        R.update(close_rules(sp, rows))
        if sp != 'nfl':
            # NBA lacks the 'ij' row field (no segment, see above): its split reads the cache term at the model's weight
            if sp == 'nba':
                for r, v, _ in rows:
                    r['ij'] = 0.52 * v
            R['open'] = open_side(sp, rows)
            if sp == 'nba':
                R['open']['note'] = 'upper bound: the lineup term carries the tip-time injury report, which the open did not have'
        res['sports'][sp] = R
        print(sp, 'residual held', R['residual']['held'], 'injuryOnly', R['injuryOnly'].get('x'), R['injuryOnly'].get('test'), R['injuryOnly'].get('why'),
              '| gapPlusInjury', R['gapPlusInjury'].get('x'), R['gapPlusInjury'].get('val'), R['gapPlusInjury'].get('test'), R['gapPlusInjury'].get('why'))
        if R.get('open'):
            print('   open move', R['open']['move'], [q for q in R['open']['split'] if q['x'] == 4.5])
    # Benjamini-Hochberg (q .10) over every close-based rule that reached validation, on its validation t
    import math
    cands = [(sp, k) for sp, R in res['sports'].items() for k in ('injuryOnly', 'gapPlusInjury') if R[k].get('val')]
    ps = [1 - 0.5 * (1 + math.erf((res['sports'][sp][k]['val']['t'] or 0) / math.sqrt(2))) for sp, k in cands]
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    top = max([r for r, i in enumerate(order, 1) if ps[i] <= 0.10 * r / len(ps)] or [0])
    keep = set(order[:top])
    for i, (sp, k) in enumerate(cands):
        m = res['sports'][sp][k]
        m['p'] = round(ps[i], 4)
        if m['on'] and i not in keep:
            m['on'], m['why'] = False, f'passed validation and test but not the Benjamini-Hochberg cut (q .10 over {len(cands)})'
        print(sp, k, 'p', m['p'], 'on' if m['on'] else 'off', m['why'] or '')
    res['bhOver'] = len(cands)
    with open(os.path.join(ROOT, 'data', 'injury_edge.json'), 'w') as f:
        json.dump(res, f, indent=1)


if __name__ == '__main__':
    main()
