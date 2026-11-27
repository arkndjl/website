#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Draft pay against college pay as a Return% driver (see prereg.md).

    python3 scripts/research/ret_pay_nov27/pay.py     # -> data/return_pay.json (read by scripts/library_glossary.py)
"""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE)); ROOT = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import return_drivers as R
CD = R.CD
CE = R.load('ce', 'cfb_declare_econ.py')
bt = R.load('bt', 'cfb_draft_pct_backtest.py')

# first-year cash in $M, 2026 dollars, at anchor picks (linear in ln pick between)
NFL_Y1 = [(1, 33.4), (2, 31.0), (5, 24.4), (10, 15.6), (16, 11.2), (24, 8.7), (32, 7.5), (33, 5.4), (48, 3.7), (64, 2.7),
          (65, 2.4), (100, 1.95), (140, 1.6), (180, 1.05), (220, .77), (257, .64)]
NFL_Y1_UD = .38
NBA_Y1 = [(1, 14.7), (2, 13.2), (3, 11.9), (5, 9.7), (10, 6.5), (14, 5.2), (20, 4.0), (25, 3.4), (30, 3.1), (31, 2.0), (45, 1.2), (60, .7)]
NBA_Y1_UD = .25
CAP = {'nfl': {2022: 208.2, 2023: 224.8, 2024: 255.4, 2025: 279.2, 2026: 301.2},
       'nba': {2022: 123.7, 2023: 136.0, 2024: 140.6, 2025: 154.6, 2026: 165.0}}     # the season after the draft
NILM = {2022: 1.14, 2023: 1.17, 2024: 2.26, 2025: 2.6, 2026: 2.8}                    # $B, the season he would return for
Z = np.linspace(-3, 3, 61); W = np.exp(-Z ** 2 / 2); W /= W.sum()


def curve(tab, ud, last, sd):
    lp = np.log([p for p, _ in tab]); v = np.array([x for _, x in tab])
    def f(l):
        s = l + sd * Z
        return np.where(s <= math.log(last), np.interp(s, lp, v), ud)      # $M at each point of the pick spread
    return f


NFL1 = curve(NFL_Y1, NFL_Y1_UD, 257, CE.SD); NFL4 = curve(CE.SCALE, CE.UDFA, 257, CE.SD)
NBA1 = curve(NBA_Y1, NBA_Y1_UD, 60, .7); NBA4 = curve(R.NBA_SCALE, R.NBA_UNDRAFTED, 60, .7)


def terms(r, lx, y1, y4, nil_now, lg, yr):
    """nil_now: college pay in $M at today's level"""
    kp = CAP[lg][yr] / CAP[lg][2026]; kn = NILM[yr] / NILM[2026]
    a, b = y1(lx), y4(lx)
    r['econ4'] = math.log(float(W @ b)) - math.log(nil_now)
    r['econ1'] = math.log(float(W @ a)) - math.log(nil_now)
    r['econ1p'] = math.log(float(W @ a) * kp) - math.log(nil_now * kn)
    r['gap'] = math.asinh((float(W @ a) * kp - nil_now * kn) / .25)
    r['pstay'] = float(W @ (nil_now * kn > a * kp))
    r['idx'] = math.log(kn / kp)


CANDS = ['econ4', 'econ1', 'econ1p', 'gap', 'pstay', 'idx']
P4 = {'SEC', 'Big Ten', 'Big 12', 'ACC'}


def cfb_ynil_shape():
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cfb-all.json'))); c = {k: i for i, k in enumerate(d['cols'])}
    X, y = [], []
    for r in d['rows']:
        if r[c['consRk']] and r[c['ynil']] and (r[c['conf']] in P4 or r[c['team']] == 'Notre Dame'):
            X.append([1, bt.lnPick(r[c['consRk']]), r[c['pos']] == 'QB']); y.append(math.log(r[c['ynil']]))
    b = np.linalg.lstsq(np.array(X, float), np.array(y), rcond=None)[0]
    return {'a': float(b[0]), 'b': float(b[1]), 'qb': float(b[2]), 'g5': CE.NIL['g5'], 'fcs': CE.NIL['fcs'], 'n': len(y)}


def cbb_ynil_shape():
    import csv
    m = json.load(open(os.path.join(ROOT, 'data', 'cbb_market.json')))['nil']; B = {}
    with open(os.path.join(CD.BOARDS, 'all_boards.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['draft_year'] == '2027': k = R.N.key(r['name']); B[k] = min(B.get(k, 999), int(r['rank']))
    X, y = [], []
    for p in m:
        if not p.get('y'): continue
        X.append([1, math.log(min(B.get(R.N.key(p['name']), 100), 100)), int(p.get('conf') in R.HM)]); y.append(math.log(p['y']))
    b = np.linalg.lstsq(np.array(X, float), np.array(y), rcond=None)[0]
    return {'a': float(b[0]), 'b': float(b[1]), 'hm': float(b[2]), 'n': len(y)}


def cmp(L, Lref, C, gate):
    d = L - Lref; cells = sorted(set(C))
    c = {'logLoss': round(float(L.mean()), 4), 'vsLive': round(float(d.mean()), 4), 't': round(R.tstat(d), 2),
         'won': int(sum(d[C == k].mean() < 0 for k in cells)), 'of': len(cells)}
    c['pass'] = bool(c['vsLive'] < 0 and c['t'] <= -2 and c['won'] >= gate); return c


def cfb(out):
    fall, _ = R.cfb_rows(); S = cfb_ynil_shape()
    fall = [r for r in fall if r['draft'] >= 2022]; drafts = sorted({r['draft'] for r in fall})
    for r in fall:
        nil = 1e-6 * math.exp(S['a'] + S['b'] * r['lx'] + S['qb'] * r['qb'] + (S['fcs'] if r['fcs'] else 0 if r['p4'] else S['g5']))
        terms(r, r['lx'], NFL1, NFL4, nil, 'nfl', r['draft'])
    mu = {k: float(np.mean([r[k] for r in fall])) for k in CANDS}; sd = {k: float(np.std([r[k] for r in fall])) or 1.0 for k in CANDS}
    def lodo(fx):
        L, C = [], []
        for d in drafts:
            for g in ('sr', 'under'):
                tr = [r for r in fall if r['draft'] != d and r['grp'] == g]; te = [r for r in fall if r['draft'] == d and r['grp'] == g]
                b = R.logit([[1] + fx(r) for r in tr], [r['declared'] for r in tr], 1.0)
                L += list(R.ll(1 / (1 + np.exp(-np.array([[1] + fx(r) for r in te], float) @ b)), np.array([r['declared'] for r in te], float)))
                C += [f'{d}{g}'] * len(te)
        return np.array(L), np.array(C)
    z = lambda r, k: (r[k] - mu[k]) / sd[k]
    Llive, C = lodo(lambda r: [r['lx'], r['agez'], r['era']])
    o = {'n': len(fall), 'returned': int(sum(1 - r['declared'] for r in fall)), 'drafts': drafts, 'ynilShape': {k: round(v, 3) for k, v in S.items()},
         'live': round(float(Llive.mean()), 4), 'onTop': {}, 'swap': {}}
    for k in CANDS:
        o['onTop'][k] = cmp(lodo(lambda r: [r['lx'], r['agez'], r['era'], z(r, k)])[0], Llive, C, 6); print('cfb +', k, o['onTop'][k])
    for k in ('econ1p', 'gap', 'pstay', 'idx'):      # in place of the 2024 flag
        o['swap'][k] = cmp(lodo(lambda r: [r['lx'], r['agez'], z(r, k)])[0], Llive, C, 6); print('cfb swap', k, o['swap'][k])
    o['moneyOnly'] = cmp(lodo(lambda r: [z(r, 'econ1p'), r['agez']])[0], Llive, C, 6); print('cfb money only', o['moneyOnly'])
    # how much of each term the board rank already holds
    o['r2OnRank'] = {k: round(float(np.corrcoef([r['lx'] for r in fall], [r[k] for r in fall])[0, 1] ** 2), 3) for k in CANDS if k != 'idx'}
    out['cfb'] = o


def cbb(out):
    rows = sorted(CD.rows_from_kit(), key=lambda r: r['year'])
    conf = {}
    import csv
    with open(os.path.join(CD.KIT, 'college_seasons_nba.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f): conf[(r['pid'], int(r['year']))] = r['conf']
    S = cbb_ynil_shape()
    for r in rows:
        r['hm'] = float(conf.get((r['pid'], r['year'])) in R.HM); r['e24'] = float(r['year'] >= 2024)
        lr = math.log(min(r['nb'], 100)) if r['nb'] else math.log(100); yr = min(max(r['year'], 2022), 2026)
        terms(r, lr, NBA1, NBA4, 1e-6 * math.exp(S['a'] + S['b'] * lr + S['hm'] * r['hm']), 'nba', yr)
        if r['year'] < 2022: r['idx'] = None
    i0 = min(r['idx'] for r in rows if r['idx'] is not None) - math.log(8)          # before NIL: far below the first NIL season
    for r in rows:
        if r['idx'] is None: r['idx'] = i0
    T = ['bpm', 'rank', 'e24'] + CANDS
    mu = {k: float(np.mean([r[k] for r in rows])) for k in T}; sd = {k: float(np.std([r[k] for r in rows])) or 1.0 for k in T}
    sig = lambda z: 1 / (1 + np.exp(-z)); HOLD = CD.HOLD
    def design(rs, e24=True, extra=()):
        return np.array([[1, r['cls'] == 'So', r['cls'] == 'Jr', r['year'] >= 2022, r['year'] == 2021] + ([r['year'] >= 2024] if e24 else []) +
                         [(r[k] - mu[k]) / sd[k] for k in ('bpm', 'rank') + tuple(extra)] for r in rs], float)
    def walk(years, **kw):
        Zs = []
        for y in years:
            tr = [r for r in rows if r['year'] < y]; ts = [r for r in rows if r['year'] == y]
            Zs += list(design(ts, **kw) @ CD.logit(design(tr, **kw), np.array([r['left'] for r in tr], float)))
        return np.array(Zs)
    te = [r for r in rows if r['year'] in HOLD]; yte = np.array([r['left'] for r in te], float); yrs = np.array([r['year'] for r in te])
    Lship = R.ll(sig(walk(HOLD)), yte)
    A = {'nHeld': len(te), 'shipped': round(float(Lship.mean()), 4),
         'idxOnTop': cmp(R.ll(sig(walk(HOLD, extra=('idx',))), yte), Lship, yrs, 3),
         'idxSwap': cmp(R.ll(sig(walk(HOLD, e24=False, extra=('idx',))), yte), Lship, yrs, 3)}
    print('cbb A', A)
    BY = sorted({r['year'] for r in rows if r['nb']}); sub = [r for r in rows if r['year'] in BY]
    ys = np.array([r['left'] for r in sub], float); yy = np.array([r['year'] for r in sub]); rk = np.array([r['nb'] is not None for r in sub])
    zA = walk(BY)
    def stageB(extra, board=True, wf=False):
        X = np.column_stack([np.ones(len(sub)), zA] + ([[r['board'] for r in sub]] if board else []) + [rk] + [[(r[k] - mu[k]) / sd[k] for r in sub] for k in extra])
        p = np.full(len(sub), np.nan)
        for y in BY:
            m = yy == y; tr = (yy < y) if wf else ~m       # wf: only the drafts before it (point in time for a term that moves by year)
            if tr.any(): p[m] = sig(X[m] @ CD.logit(X[tr], ys[tr], l2=0.1))
        return p
    def pair(extra, ref, gate, **kw):
        p, q = stageB(extra, **kw), stageB(ref, **kw); ok = rk & ~np.isnan(p)
        return cmp(R.ll(p, ys)[ok], R.ll(q, ys)[ok], yy[ok], gate)
    pB = stageB([]); LB = R.ll(pB, ys)
    B = {'ranked': int(rk.sum()), 'returned': int((1 - ys[rk]).sum()), 'drafts': BY, 'ynilShape': {k: round(v, 3) for k, v in S.items()},
         'shippedRanked': round(float(LB[rk].mean()), 4), 'onTop': {}, 'besideStep': {}, 'walkForward': {}}
    for k in CANDS:
        B['onTop'][k] = pair([k], [], 4); print('cbb B +', k, B['onTop'][k])
    B['onTop']['step'] = pair(['e24'], [], 4)                                   # a 2024+ step in the board stage, no dollars
    for k in ('econ1p', 'gap', 'pstay'):
        B['besideStep'][k] = pair(['e24', k], ['e24'], 4)                       # is it more than the year level?
        B['walkForward'][k] = pair([k], [], 3, wf=True)
    B['walkForward']['step'] = pair(['e24'], [], 3, wf=True)
    print('cbb B beside step', B['besideStep']); print('cbb B walk forward', B['walkForward'])
    B['moneyOnly'] = cmp(R.ll(stageB(['econ1p'], board=False), ys)[rk], LB[rk], yy[rk], 4)
    sr = [r for r, m in zip(sub, rk) if m]
    B['r2OnRank'] = {k: round(float(np.corrcoef([r['board'] for r in sr], [r[k] for r in sr])[0, 1] ** 2), 3) for k in CANDS if k != 'idx'}
    nb = np.array([r['nb'] or 0 for r in sub])
    B['bands'] = [{'picks': f'{lo}-{hi}', 'era': lab, 'n': int(m.sum()), 'left': round(float(ys[m].mean()), 3), 'model': round(float(pB[m].mean()), 3)}
                  for lo, hi in ((1, 14), (15, 30), (31, 60)) for lab, e in (('2022-23', yy <= 2023), ('2025-26', yy >= 2025))
                  for m in [rk & e & (nb >= lo) & (nb <= hi)]]
    print(B['bands'])
    out['cbb'] = {'stageA': A, 'stageB': B}


def main():
    out = {'_readme': __doc__.split('\n\n')[1].strip(), 'nilMarket': NILM, 'cap': CAP}
    cbb(out); cfb(out)
    json.dump(out, open(os.path.join(ROOT, 'data', 'return_pay.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
