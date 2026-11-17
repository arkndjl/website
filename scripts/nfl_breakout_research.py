#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL Potential Breakout research: workload scaling and breakout signals, leave-one-season-out (scripts/breakout_lib.py).

    python3 scripts/nfl_breakout_research.py      # -> data/nfl_breakout_fit.json (numpy; nflverse weekly files 2010 on)

Workload and efficiency: scripts/nfl_breakout.py (WR/TE target share and yards a target; RB share of the team's
carries + targets and scrimmage yards an opportunity). QB, OL and defense are not scaled.

A. Workload scaling, one fit a position. Rows: season pairs (both seasons with a real sample) and half pairs (a
   season's weeks 1-9 against weeks 10 on: a teammate's injury or a trade moves the share with no off-season between),
   weight = the smaller opportunity count, block = the season of the outcome. Next efficiency on this one's (shrunk by
   sample) + age + share + last season's, then + the share change (dU), then + dU x context blocks. Held-out error on
   all rows and on the rows whose share rose 3+ points (the case the tab projects).
B. Breakout odds. Rows: WR/TE/RB with 4+ games and 15+ opportunities. Breakout = next season 8+ games at a fantasy
   starter's PPR points a game (RB/WR 12, TE 9) and 4+ over this season's shrunk to a depth player's by 4 games.
   Baseline logistic: shrunk PPR/G, ln opportunities, position, share. Candidates one at a time, then the passers."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import nfl_breakout as B  # noqa: E402

DATA0 = 2004                                        # first season loaded (career history for the early rows)
Y0, Y1 = 2010, 2025                                 # seasons with a known next season: Y0..Y1-1
ROSE = 3.0
LAMS = (1e-4, 1e-3, 1e-2, 3e-2, 0.1, 0.3)


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


def pairs(P, pos):
    R = []
    m = B.MINN[pos]
    for (pid, y), a in P.items():
        if a['pos'] != pos or y < Y0:
            continue
        hist = B.history(P, pid, y)
        b = P.get((pid, y + 1))
        if b and b['pos'] == pos and a['n'] >= m and b['n'] >= m:
            R.append((a, b, hist, 0.0, y + 1))
        g1 = [g for g in a['games'] if g['wk'] <= 9]
        g2 = [g for g in a['games'] if g['wk'] > 9]
        if len(g1) >= 3 and len(g2) >= 3:
            h1, h2 = B.part(a, g1), B.part(a, g2)
            if h1['n'] >= 0.6 * m and h2['n'] >= 0.6 * m:
                R.append((h1, h2, hist, 1.0, y))
    return R


def scaling(P, pos):
    R = pairs(P, pos)
    S = np.array([r[4] for r in R], float)
    w = np.array([min(a['n'], b['n']) for a, b, *_ in R], float)
    du = np.array([b['u'] - a['u'] for a, b, *_ in R])
    half = np.array([r[3] for r in R])
    y = np.array([b['x'] for a, b, *_ in R])
    F = np.array([B.features(a, h, d, hf) for (a, b, h, hf, _), d in zip(R, du)])
    cols = B.columns()
    ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
    sets = {'base': B.BASE, 'dU': B.BASE + ['dU']}
    for blk, tr in B.BLOCKS.items():
        sets[blk] = B.BASE + ['dU'] + sum([['dU*' + t, t] for t in tr], [])
    sets['full'] = cols
    up = du >= ROSE
    masks = {'all': np.ones(len(y), bool), 'rose': up, 'rose, seasons': up & (half == 0), 'rose, halves': up & (half == 1)}

    def run(cs):
        X = F[:, ix(cs)]

        def fp(trn, te):
            b0, b = L.wls(X[trn], y[trn], w[trn], pick_lam(X[trn], y[trn], w[trn], S[trn]))
            return b0 + X[te] @ b
        pred = {}
        for s in sorted(set(S.tolist())):
            te = S == s
            pred[s] = (te, fp(~te, te))
        out = {}
        for k, m in masks.items():
            out[k] = {s: (float((w[te][m[te]] * (y[te][m[te]] - p[m[te]]) ** 2).sum()), float(w[te][m[te]].sum()) or 1e-9)
                      for s, (te, p) in pred.items()}
        return out
    res = {nm: run(cs) for nm, cs in sets.items()}
    tests = {'dU vs base (all)': L.compare(res['base']['all'], res['dU']['all']),
             'dU vs base (rose)': L.compare(res['base']['rose'], res['dU']['rose']),
             'full vs base (all)': L.compare(res['base']['all'], res['full']['all']),
             'full vs base (rose)': L.compare(res['base']['rose'], res['full']['rose']),
             'full vs dU (rose)': L.compare(res['dU']['rose'], res['full']['rose'])}
    for t in tests.values():
        t['pass'] = bool(t['t'] >= 2 and t['won'] * 2 > t['seasons'])
    blocks = {k: L.compare(res['dU']['rose'], res[k]['rose']) for k in B.BLOCKS}
    L.holm(blocks)
    for k in B.BLOCKS:
        blocks[k]['all rows'] = {q: L.compare(res['dU']['all'], res[k]['all'])[q] for q in ('gain', 't', 'won')}
    keep = [k for k in B.BLOCKS if blocks[k]['pass']]
    fin = B.BASE + ['dU'] + sum([sum([['dU*' + t, t] for t in B.BLOCKS[k]], []) for k in keep], [])
    if keep:
        rk = run(fin)
        for k in masks:
            tests[f'kept vs base ({k})'] = L.compare(res['base'][k], rk[k])
    X = F[:, ix(fin)]
    lam = pick_lam(X, y, w, S)
    b0, b = L.wls(X, y, w, lam)
    sp = du[half == 0]
    ib = ix(B.BASE)
    lb = pick_lam(F[:, ib], y, w, S)
    tb0, tb = L.wls(F[:, ib], y, w, lb)
    out = {'tier_fit': {'b0': round(float(tb0), 5), 'cols': B.BASE, 'b': [round(float(v), 7) for v in tb]},
           'causal': causal(P, pos), 'n': len(R), 'n_season': int((half == 0).sum()), 'n_half': int((half == 1).sum()), 'n_rose': int(up.sum()),
           'du99': round(float(np.percentile(sp, 99)), 1), 'tests': tests, 'blocks': blocks, 'keep': keep, 'lam': lam,
           'slope': {'dU': round(float(b[fin.index('dU')]), 4)},
           'fit': {'b0': round(float(b0), 5), 'cols': fin, 'b': [round(float(v), 7) for v in b]}}
    print(pos, 'rows', len(R), 'rose', int(up.sum()), 'du99', out['du99'], flush=True)
    for k, v in tests.items():
        print('  ', k, v, flush=True)
    for k, v in blocks.items():
        print('   block', k, v, flush=True)
    return out


def causal(P, pos):
    """The share's own effect on efficiency: two-stage least squares with the work teammates left behind as the
    instrument for the share change. Halves: same-group teammates' weeks 1-9 work a game that is gone in weeks 10 on;
    seasons: same-group teammates not on the team next season. Both sides are residualized on the rate model's
    inputs. SE: season-block jackknife."""
    team = {}
    for (pid, y), o in P.items():
        team.setdefault((o['tm0'], y), []).append(o)
    rb = pos == 'RB'
    op = (lambda g: g['tg'] + g['ca']) if rb else (lambda g: g['tg'])
    same = lambda q: (q['pos'] == 'RB') == rb  # noqa: E731
    R = []
    for (pid, y), a in P.items():
        if a['pos'] != pos or y < Y0 or len({g['tm'] for g in a['games']}) > 1:
            continue
        tm, m = a['tm0'], B.MINN[pos]
        mates = [q for q in team[(tm, y)] if q is not a and same(q)]
        g1 = [g for g in a['games'] if g['wk'] <= 9]
        g2 = [g for g in a['games'] if g['wk'] > 9]
        if len(g1) >= 3 and len(g2) >= 3:
            h1, h2 = B.part(a, g1), B.part(a, g2)
            if h1['n'] >= 0.6 * m and h2['n'] >= 0.6 * m:
                wks = max(g['wk'] for q in team[(tm, y)] for g in q['games']) - 10      # team games after week 9
                z = sum(max(0.0, sum(op(g) for g in q['games'] if g['wk'] <= 9 and g['tm'] == tm) / 9.0
                            - sum(op(g) for g in q['games'] if g['wk'] > 9 and g['tm'] == tm) / max(1, wks))
                        for q in mates) / h1['vol']
                R.append((y, h1, h2, 100 * z, 1.0))
        b = P.get((pid, y + 1))
        if b and b['pos'] == pos and b['tm0'] == tm and a['n'] >= m and b['n'] >= m:
            gone = sum(q['n'] / max(q['g'], 8) for q in mates
                       if (P.get((q['pid'], y + 1)) or {}).get('tm0') != tm)
            R.append((y + 1, a, b, 100 * gone / a['vol'], 0.0))
    S = np.array([r[0] for r in R], float)
    w = np.array([min(a['n'], b['n']) for _, a, b, *_ in R], float)
    X0 = np.array([[a['x'], a['x'] * a['n'] / (a['n'] + B.KREL[pos]), a['n'] / (a['n'] + B.KREL[pos]), a['u'], a['age'],
                    hf, hf * a['x']] for _, a, b, z, hf in R])

    def resid(v):
        b0, b = L.wls(X0, v, w, 1e-4)
        return v - b0 - X0 @ b
    ry = resid(np.array([b['x'] for _, a, b, *_ in R]))
    rd = resid(np.array([b['u'] - a['u'] for _, a, b, *_ in R]))
    rz = resid(np.array([r[3] for r in R]))
    half = np.array([r[4] for r in R])

    def est(m):
        iv = (w[m] * rz[m] * ry[m]).sum() / (w[m] * rz[m] * rd[m]).sum()
        jk = np.array([(w[k] * rz[k] * ry[k]).sum() / (w[k] * rz[k] * rd[k]).sum()
                       for k in (m & (S != s) for s in sorted(set(S[m].tolist())))])
        se = float(np.sqrt((len(jk) - 1) / len(jk) * ((jk - jk.mean()) ** 2).sum()))
        return {'n': int(m.sum()), 'ols': round(float((w[m] * rd[m] * ry[m]).sum() / (w[m] * rd[m] ** 2).sum()), 4),
                'first_stage': round(float((w[m] * rz[m] * rd[m]).sum() / (w[m] * rz[m] ** 2).sum()), 3),
                'iv': round(float(iv), 4), 'se': round(se, 4), 't': round(float(iv / se), 2)}
    out = est(np.ones(len(R), bool))
    out['halves'], out['seasons'] = est(half == 1), est(half == 0)
    print(pos, 'causal', out, flush=True)
    return out


def xtd_fit(P):
    out = {}
    for pos in B.POS:
        R = [o for (pid, y), o in P.items() if o['pos'] == pos and Y0 <= y <= Y1]
        X = np.array([[o['tg'], o['wy'], o['ca'], o['ry']] for o in R])
        t = np.array([o['wtd'] + o['rtd'] for o in R])
        out[pos] = [round(float(v), 6) for v in np.linalg.lstsq(X, t, rcond=None)[0]]
    return out


def breakout(P, fit):
    R = []
    rooms = {y: B.room(P, y) for y in range(Y0, Y1)}
    for (pid, y), a in P.items():
        if not (Y0 <= y < Y1) or a['g'] < B.BO_MIN_G or a['n'] < B.BO_MIN_N or not B.eligible(P, a):
            continue
        b = P.get((pid, y + 1))
        hit = 1.0 if (b and b['g'] >= B.G_NEXT and b['ppg'] >= B.LINE[a['pos']] and b['ppg'] >= B.shr(a) + B.JUMP) else 0.0
        old, vac = rooms[y]
        R.append((a, hit, B.bo_feats(fit, a, B.history(P, pid, y), old[pid], vac[pid])))
    S = np.array([a['y'] + 1 for a, *_ in R], float)
    y = np.array([h for _, h, _ in R])
    base = np.array([f['base'] for *_, f in R])
    cands = {k: np.array([f[k] for *_, f in R]) for k in B.BO_CANDS}
    pos = np.array([a['pos'] for a, *_ in R])

    def run(X):
        def fp(trn, te):
            b0, b = L.logit(X[trn], y[trn])
            return L.sig(b0 + X[te] @ b)

        def err(p, te):
            p = np.clip(p, 1e-6, 1 - 1e-6)
            return (float(-(y[te] * np.log(p) + (1 - y[te]) * np.log(1 - p)).sum()), float(te.sum()))
        return L.loso(S, fp, err)
    rb = run(base)
    res = {k: L.compare(rb, run(np.column_stack([base, X]))) for k, X in cands.items()}
    L.holm(res)
    keep = [k for k in cands if res[k]['pass'] and k not in B.LIVE_OFF]
    X = np.column_stack([base] + [cands[k] for k in keep])
    final = L.compare(rb, run(X))
    # held-out predictions for calibration
    ph = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        b0, b = L.logit(X[~te], y[~te])
        ph[te] = L.sig(b0 + X[te] @ b)
    cal = []
    for lo, hi in ((0, .03), (.03, .07), (.07, .15), (.15, .3), (.3, 1)):
        m = (ph >= lo) & (ph < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ph[m].mean()), 3), round(float(y[m].mean()), 3)])
    b0, b = L.logit(X, y)
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y),
          {p: round(float(y[pos == p].mean()), 3) for p in B.POS}, flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    print(' calib (held out)', cal, flush=True)
    return {'definition': f"next season {B.G_NEXT}+ games, PPR points a game >= the starter line (RB/WR 12, TE 9) and >= "
                          f"this season's PPR/G shrunk to a depth player's (RB/WR 4, TE 2.5) by {B.K_SHR:g} games + {B.JUMP:g}; never at the line before",
            'rows': f'WR/TE/RB, {B.BO_MIN_G}+ games, {B.BO_MIN_N}+ opportunities, under the starter line this season '
                    f'(shrunk) and in every {B.G_NEXT}+ game season of the eight before', 'seasons': f'{Y0 + 1}-{Y1}',
            'n': len(y), 'rate': round(float(y.mean()), 4),
            'rate_pos': {p: round(float(y[pos == p].mean()), 4) for p in B.POS}, 'tests': res, 'keep': keep,
            'research_only': [k for k in B.LIVE_OFF if res[k]['pass']], 'final': final, 'calib_held_out': cal,
            'fit': {'b0': round(float(b0), 5), 'b': [round(float(v), 6) for v in b],
                    'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


def main():
    info, pfr = B.load_players()
    P = B.load(DATA0, Y1, info, pfr)
    fit = {'source': f'nflverse stats_player_week {DATA0}-{Y1} + snap_counts 2013-{Y1}, REG; rows {Y0} on',
           'workload': 'WR/TE: targets / team targets in games played; RB: (carries + targets) / team (carries + targets)',
           'efficiency': 'WR/TE receiving yards a target; RB scrimmage yards a carry or target',
           'not_scaled': 'QB, OL, defense', 'xtd': xtd_fit(P)}
    fit['scaling'] = {pos: scaling(P, pos) for pos in B.POS}
    # the share's own effect ships where the pooled estimate clears t 2 and Holm across the three positions; the
    # slope used is the halves' (the strong instrument: first stage 3-10x the seasons'), the smaller of the two
    order = sorted(B.POS, key=lambda p: -abs(fit['scaling'][p]['causal']['t']))
    alive = True
    for i, p in enumerate(order):
        c = fit['scaling'][p]['causal']
        c['p'] = round(math.erfc(abs(c['t']) / math.sqrt(2)) / 2, 4)
        alive = alive and abs(c['t']) >= 2 and c['p'] <= 0.05 / (len(order) - i)
        c['pass'] = bool(alive)
        c['use'] = c['halves']['iv'] if alive else 0.0
        print(p, 'causal slope used', c['use'], 'pooled t', c['t'], 'p', c['p'])
    fit['breakout'] = breakout(P, fit)
    json.dump(fit, open(B.FIT, 'w'), indent=1)
    print('wrote', B.FIT)


if __name__ == '__main__':
    main()
