#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball Potential Breakout research: usage scaling, breakout signals and the NBA-translation test,
all held out (scripts/breakout_lib.py).

    python3 scripts/cbb_breakout_research.py [research_seasons.csv]
        -> data/cbb_breakout_fit.json, scripts/data/cbb_breakout_base.json.gz (last season's lines for the live build)

History: Barttorvik D-I player seasons 2010-2026 (shot-location and role columns start in 2010), the project files'
cbb/backtest/research_seasons.csv. Pairs = the same Barttorvik pid in consecutive seasons, transfers included.

A. Usage scaling. Pairs with 20%+ of team minutes and 10+ games both seasons, weight = the smaller min%. Next-season
   TS% (and TO%) on this season's (shrunk by min%) + age + usage, then + the usage change (dU), then + dU x traits by
   block. Held-out error on all pairs and on the pairs whose usage rose 3+ points (the case the tab projects).
B. Breakout odds. Rows: 10%+ of minutes and 10+ games this season and a D-I line next season (the live board only
   lists players on a roster). Breakout = next season 40%+ of team minutes and BPM 3+ over his best season so far
   (each season's BPM shrunk to -2 by min%, k 10; a comeback to an old level doesn't count). Baseline logistic: that
   best shrunk BPM, ln min%. Candidates one at a time, then the passers together.
   The usage-scaling candidate uses a scaling fit that never saw the held-out season.
C. NBA translation. Does projected TS% at 28 usage (and the +6 usage TS% change) add to the board's baseline drivers
   for reaching the NBA and peak BPM given NBA? Hurdle, leave one draft class out (the backtest README's framework)."""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import cbb_breakout as B  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = '/mnt/project-files/cbb/backtest/research_seasons.csv'
OUT = os.path.join(ROOT, 'data', 'cbb_breakout_fit.json')
Y0 = 2010
PAIR_M, PAIR_GP = 20.0, 10.0
ROW_M, ROW_GP = 10.0, 10.0
LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1)


def load(src):
    raw = list(csv.DictReader(open(src)))
    P = {}
    for r in raw:
        o = B.line(r)
        if abs(o['bpm']) < 40:
            P[(o['pid'], o['y'])] = o
    return P, raw


def context(P):
    """per (pid, y) with a line next season: his team's level, his next team's level / vacated / arriving usage (all
    measured this season, so known before the next one), top-100 freshmen arriving, transfer flag"""
    by_y = defaultdict(list)
    for (pid, y), o in P.items():
        by_y[y].append(o)
    C = {}
    for y, ls in by_y.items():
        nxt = {o['pid']: P[(o['pid'], y + 1)]['team'] for o in ls if (o['pid'], y + 1) in P}
        T = B.team_tables(ls, nxt)
        tops = defaultdict(int)
        for o in by_y.get(y + 1, []):
            if o['cls'] == 1 and (o['pid'], y) not in P and o['rg_lrk'] >= -math.log(100):
                tops[o['team']] += 1
        for o in ls:
            nt = nxt.get(o['pid'])
            if not nt:
                continue
            here, there = T.get(o['team'], B.NO_TEAM), T.get(nt, B.NO_TEAM)
            C[(o['pid'], y)] = {'vac': there['vac'], 'inc': there['inc'], 'top': float(tops.get(nt, 0)),
                                'lvl': here['lvl'], 'nlvl': there['lvl'], 'xfer': 1.0 if nt != o['team'] else 0.0}
    return C


def pick_lam(X, y, w, S):
    """ridge strength from an inner split of the training seasons (every third season held out)"""
    u = sorted(set(S.tolist()))
    hold = np.isin(S, u[1::3])
    best, bl = None, LAMS[0]
    for lam in LAMS:
        b0, b = L.wls(X[~hold], y[~hold], w[~hold], lam)
        e = float((w[hold] * (y[hold] - b0 - X[hold] @ b) ** 2).sum())
        if best is None or e < best:
            best, bl = e, lam
    return bl


# ---------- A. usage scaling ----------
def scaling(P, C):
    R = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if y < Y0 or not b or min(a['m'], b['m']) < PAIR_M or min(a['gp'], b['gp']) < PAIR_GP:
            continue
        R.append((pid, y, a, b))
    S = np.array([y + 1 for _, y, _, _ in R], float)
    w = np.array([min(a['m'], b['m']) for _, _, a, b in R], float)
    du = np.array([b['usg'] - a['usg'] for _, _, a, b in R])
    cols = B.columns()
    out, folds = {}, {}
    for tgt in B.TARGETS:
        y = np.array([b[tgt] for _, _, a, b in R])
        F = []
        for (pid, yy, a, b), d in zip(R, du):
            c = C[(pid, yy)]
            v = B.features(tgt, a, B.history(P, pid, yy), (c['lvl'], c['nlvl'], c['xfer']), d)
            F.append([v[k] for k in cols])
        F = np.array(F)
        ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
        base_c = B.BASE
        sets = {'base': base_c, 'dU': base_c + ['dU']}
        for blk, traits in B.BLOCKS.items():
            sets[blk] = base_c + ['dU'] + sum([['dU*' + t, t] for t in traits], [])
            # the same block without its dU interactions: what the traits add as plain predictors of next season
            sets[blk + ' (traits only)'] = base_c + ['dU'] + list(traits)
        sets['full'] = cols
        up3, up6 = du >= 3, du >= 6
        res = {k: {} for k in ('all', 'up3', 'up6')}

        def run(cs):
            X = F[:, ix(cs)]

            def fp(trn, te):
                lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
                b0, b = L.wls(X[trn], y[trn], w[trn], lam)
                return b0 + X[te] @ b
            r = {}
            for key, m in (('all', np.ones(len(y), bool)), ('up3', up3), ('up6', up6)):
                def e(p, te, m=m):
                    mm = m[te]
                    return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
                r[key] = L.loso(S, fp, e)
            return r
        for nm, cs in sets.items():
            r = run(cs)
            for key in res:
                res[key][nm] = r[key]
        cmp = {'dU vs base (all)': L.compare(res['all']['base'], res['all']['dU']),
               'dU vs base (rose 3+)': L.compare(res['up3']['base'], res['up3']['dU']),
               'full vs base (all)': L.compare(res['all']['base'], res['all']['full']),
               'full vs base (rose 3+)': L.compare(res['up3']['base'], res['up3']['full']),
               'full vs base (rose 6+)': L.compare(res['up6']['base'], res['up6']['full']),
               'full vs dU (rose 3+)': L.compare(res['up3']['dU'], res['up3']['full'])}
        blocks = {k: L.compare(res['up3']['dU'], res['up3'][k]) for k in B.BLOCKS}
        L.holm(blocks)
        # how much of each block is the dU interaction itself (block vs its traits-only version)
        inter = {k: L.compare(res['up3'][k + ' (traits only)'], res['up3'][k]) for k in B.BLOCKS}
        keep = [k for k in B.BLOCKS if blocks[k]['pass']]
        fin = base_c + ['dU'] + sum([sum([['dU*' + t, t] for t in B.BLOCKS[k]], []) for k in keep], [])
        r = run(fin)
        cmp['kept vs base (all)'] = L.compare(res['all']['base'], r['all'])
        cmp['kept vs base (rose 3+)'] = L.compare(res['up3']['base'], r['up3'])
        cmp['kept vs base (rose 6+)'] = L.compare(res['up6']['base'], r['up6'])
        X = F[:, ix(fin)]
        lam = pick_lam(X, y, w, S)
        b0, b = L.wls(X, y, w, lam)
        # the same kept columns refit without each season, for the breakout test's scaling candidate
        folds[tgt] = {}
        for s in sorted(set(S.tolist())):
            m = S != s
            f0, fb = L.wls(X[m], y[m], w[m], lam)
            folds[tgt][int(s)] = (f0, fb, fin)
        out[tgt] = {'n': len(R), 'n_up3': int(up3.sum()), 'n_up6': int(up6.sum()), 'tests': cmp, 'blocks': blocks,
                    'interaction_only': inter, 'keep': keep, 'lam': lam,
                    'fit': {'b0': round(b0, 5), 'cols': fin, 'b': [round(float(v), 7) for v in b]}}
        print(tgt, 'pairs', len(R), 'rose 3+', int(up3.sum()), flush=True)
        for k, v in cmp.items():
            print('  ', k, v, flush=True)
        for k, v in blocks.items():
            print('   block', k, v, '| interaction only t', inter[k]['t'], inter[k]['won'], flush=True)
    q = np.percentile(du, [1, 50, 99])
    return out, folds, float(q[2])


# ---------- B. breakout odds ----------
def breakout(P, C, sfit, folds):
    R = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if y < Y0 or not b or a['m'] < ROW_M or a['gp'] < ROW_GP:
            continue
        R.append((pid, y, a, b))
    S = np.array([y + 1 for _, y, _, _ in R], float)
    yv, rows, X6, X0 = [], [], [], []
    f0, fb, fin = folds['ts'][int(S[0])]
    for pid, y, a, b in R:
        hist = B.history(P, pid, y)
        s0, cur = B.level(a, hist)
        yv.append(1.0 if (b['m'] >= B.ROLE_M and b['bpm'] >= s0 + B.JUMP) else 0.0)
        c = C[(pid, y)]
        lv = (c['lvl'], c['nlvl'], c['xfer'])
        v6, v0 = B.features('ts', a, hist, lv, 6.0), B.features('ts', a, hist, lv, 0.0)
        X6.append([v6[k] for k in fin])
        X0.append([v0[k] for k in fin])
        rows.append(B.bo_feats(a, s0, cur, B.marcel(hist, y), c, 0.0))
    y = np.array(yv)
    D6 = np.array(X6) - np.array(X0)
    lowu = np.array([max(0.0, 20 - a['usg']) / 10 for _, _, a, _ in R])
    base = np.array([r['base'] for r in rows])
    cands = {k: np.array([r[k] for r in rows]) for k in B.BO_CANDS}
    full = sfit['ts']['fit']
    sc_full = D6 @ np.array(full['b'])
    cands['usage scaling'] = np.column_stack([sc_full, sc_full * lowu])

    def scal_fold(s):
        sc = D6 @ folds['ts'][int(s)][1]
        return np.column_stack([sc, sc * lowu])

    def run(names):
        def fp(trn, te):
            s = S[te][0]
            X = np.column_stack([base] + [scal_fold(s) if k == 'usage scaling' else cands[k] for k in names])
            b0, b = L.logit(X[trn], y[trn])
            return L.sig(b0 + X[te] @ b)

        def err(p, te):
            p = np.clip(p, 1e-6, 1 - 1e-6)
            return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))
        return L.loso(S, fp, err)
    rb = run([])
    res = {k: L.compare(rb, run([k])) for k in B.BO_CANDS}
    L.holm(res)
    keep = [k for k in B.BO_CANDS if res[k]['pass']]
    final = L.compare(rb, run(keep))
    # each kept signal's gain on top of the others
    marg = {}
    if len(keep) > 1:
        rk = run(keep)
        for k in keep:
            marg[k] = L.compare(run([j for j in keep if j != k]), rk)
    X = np.column_stack([base] + [cands[k] for k in keep])
    b0, b = L.logit(X, y)
    # calibration on held-out predictions
    ph = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        Xs = np.column_stack([base] + [scal_fold(s) if k == 'usage scaling' else cands[k] for k in keep])
        c0, cb = L.logit(Xs[~te], y[~te])
        ph[te] = L.sig(c0 + Xs[te] @ cb)
    cal = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .2), (.2, .35), (.35, 1)):
        m = (ph >= lo) & (ph < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ph[m].mean()), 3), round(float(y[m].mean()), 3)])
    top = ph >= np.quantile(ph, 0.9)
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y), flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    for k, v in marg.items():
        print('  on top of the rest:', k, v['t'], v['won'], flush=True)
    print(' held-out calibration', cal, 'top-decile hit rate', round(float(y[top].mean()), 3), flush=True)
    return {'definition': f'next season {B.ROLE_M:.0f}%+ of team minutes and BPM {B.JUMP:.0f}+ over his best season so far '
                          f'(each shrunk to {B.BPM_REP:.0f} by min%, k {B.K_SHR:.0f}), among players with a D-I line next season',
            'n': len(y), 'rate': round(float(y.mean()), 4), 'tests': res, 'keep': keep, 'final': final,
            'marginal': marg, 'calib_heldout': cal, 'top_decile_rate': round(float(y[top].mean()), 3),
            'fit': {'b0': round(b0, 5), 'b': [round(float(v), 6) for v in b],
                    'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


# ---------- C. NBA translation ----------
NBA_BASE = ['rgrade', 'unranked', 'usg', 'hgt_role', 'bpm', 'bpm3', 'age', 'dporpag', 'guard', 'ast', 'seasons', 'cls',
            'young_for_class', 'bpm_trend', 'min_per']
NBA_REC = ['rg_lrk', 'unranked2', 'prpg', 'stl', 'age2', 'age_x_bpm', 'dprpg']


def nba_test(P, C, raw, sfit):
    """hurdle (ridge logistic P(NBA), ridge peak BPM given NBA) on standardized drivers winsorized at 4 SD, leave one
    draft class out (final college season, <=2010 and >=2019 pooled); t = player-clustered paired t of the row errors"""
    def fl(v):
        try:
            v = float(v)
            return v if v == v else np.nan
        except (TypeError, ValueError):
            return np.nan
    rows = [r for r in raw if Y0 <= int(r['year']) <= 2018 and fl(r['gp']) >= 10 and fl(r['min_per']) >= 10
            and abs(fl(r['bpm'])) < 40 and (r['pid'], int(r['year'])) in P]
    fold = np.array([min(max(int(float(r['career_last'])), Y0), 2019) for r in rows])
    pid = np.array([r['pid'] for r in rows])
    nba = np.array([fl(r['nba']) for r in rows])
    pk = np.array([fl(r['peak_bpm']) for r in rows])
    hi, sl, ts0 = [], [], []
    for r in rows:
        a = P[(r['pid'], int(r['year']))]
        hist = B.history(P, a['pid'], a['y'])
        c = C.get((a['pid'], a['y']))
        lv = (c['lvl'], c['lvl'], 0.0) if c else (B.NO_TEAM['lvl'], B.NO_TEAM['lvl'], 0.0)
        p0 = B.predict(sfit, 'ts', a, hist, lv, 0.0)
        hi.append(B.predict(sfit, 'ts', a, hist, lv, 28.0 - a['usg']))
        sl.append(B.predict(sfit, 'ts', a, hist, lv, 6.0) - p0)
        ts0.append(a['ts'])
    extra = {'TS% at 28 usage': np.array(hi)[:, None], '+6 usage TS% change': np.array(sl)[:, None],
             'both': np.column_stack([hi, sl]), 'raw TS% (reference)': np.array(ts0)[:, None]}

    def mat(names):
        return np.array([[fl(r[k]) for k in names] for r in rows])

    def std(a, b):
        med = np.nanmedian(a, 0)
        a, b = np.where(np.isnan(a), med, a), np.where(np.isnan(b), med, b)
        mu, sd = a.mean(0), a.std(0)
        sd[sd == 0] = 1
        return np.clip((a - mu) / sd, -4, 4), np.clip((b - mu) / sd, -4, 4)

    def oos(X):
        p, mu = np.zeros(len(rows)), np.zeros(len(rows))
        for f in np.unique(fold):
            tr, te = fold != f, fold == f
            a, b = std(X[tr], X[te])
            n = tr.sum()
            b0, bb = L.logit(a, nba[tr], lam=1.0 / n)
            p[te] = L.sig(b0 + b @ bb)
            has = (nba[tr] == 1) & ~np.isnan(pk[tr])
            c0, cb = L.wls(a[has], pk[tr][has], np.ones(has.sum()), lam=1.0 / has.sum())
            mu[te] = c0 + b @ cb
        pc = np.clip(p, 1e-9, 1 - 1e-9)
        ll = -(nba * np.log(pc) + (1 - nba) * np.log(1 - pc))
        cond = (nba == 1) & ~np.isnan(pk)
        yv = np.where(np.isnan(pk), -2.5, pk)
        E = -2.5 + p * (mu - (-2.5))
        return {'hurdle': ll, 'cond': np.where(cond, (mu - yv) ** 2, np.nan), 'all': (E - yv) ** 2}

    def cmp(a, b):
        o = {}
        for k in ('hurdle', 'cond', 'all'):
            ok = ~np.isnan(a[k])
            d = (a[k] - b[k])[ok]
            g, cnt = defaultdict(float), defaultdict(int)
            for v, q in zip(d, pid[ok]):
                g[q] += v
                cnt[q] += 1
            m = d.mean()
            se = math.sqrt(sum((g[q] - cnt[q] * m) ** 2 for q in g)) / len(d)
            fs = np.unique(fold[ok])
            won = sum(a[k][ok & (fold == f)].mean() > b[k][ok & (fold == f)].mean() for f in fs)
            gain = m if k == 'hurdle' else math.sqrt(a[k][ok].mean()) - math.sqrt(b[k][ok].mean())
            o[k] = {'gain': round(float(gain), 5), 't': round(float(m / se), 2) if se else 0.0, 'won': int(won),
                    'folds': len(fs)}
        return o
    out = {'n': len(rows), 'nba_rows': int(nba.sum()), 'players': len(set(pid.tolist())),
           'bar': 't >= 2 and 8+ of 10 held-out classes', 'tests': {}}
    for nm, cols in (('board baseline', NBA_BASE), ('recommended set', NBA_BASE + NBA_REC)):
        Xb = mat(cols)
        rb = oos(Xb)
        for k, e in extra.items():
            out['tests'][f'{k} | {nm}'] = cmp(rb, oos(np.column_stack([Xb, e])))
            print('  nba', k, '|', nm, out['tests'][f'{k} | {nm}'], flush=True)
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    P, raw = load(src)
    C = context(P)
    A, folds, dmax = scaling(P, C)
    BO = breakout(P, C, A, folds)
    NB = nba_test(P, C, raw, A)
    # points a 40 = K x usage share x 2 TS x (1 - TO share); K from last season's lines
    k = [o['pts40'] / (o['usg'] / 100 * 2 * o['ts'] / 100 * (1 - o['to'] / 100)) for o in P.values()
         if o['y'] == B.BASE_YEAR and o['m'] >= 40 and o['usg'] > 5 and o['ts'] > 20]
    K = round(float(np.median(k)), 3)
    json.dump({'source': f'Barttorvik D-I player seasons {Y0}-{B.BASE_YEAR}', 'workload': 'usage % (min% as role)',
               'scaling': A, 'breakout': BO, 'nba_translation': NB, 'K': K, 'dU_p99': round(dmax, 1),
               'min_m': ROW_M, 'min_gp': ROW_GP, 'k_shrink': B.K_SHR, 'bpm_rep': B.BPM_REP},
              open(OUT, 'w'), indent=1)
    # last season's lines (and those players' earlier seasons) for the live build
    pids = {pid for (pid, y) in P if y == B.BASE_YEAR}
    lines = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in o.items()}
             for (pid, y), o in P.items() if pid in pids and y >= B.BASE_YEAR - 4]
    with gzip.open(B.BASEF, 'wt') as f:
        json.dump({'season': B.BASE_YEAR, 'lines': lines}, f, separators=(',', ':'))
    print('K', K, 'dU p99', dmax, 'wrote', OUT, B.BASEF, len(lines))


if __name__ == '__main__':
    main()
