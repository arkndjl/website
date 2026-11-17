# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College football Potential Breakout research: workload scaling and breakout signals, leave-one-season-out
(scripts/breakout_lib.py).

    python3 scripts/cfb_breakout_research.py [--offline]   # -> data/cfb_breakout_fit.json

History: PFN impact rankings, FBS, 2019 on, at QB, RB, WR, TE, EDGE, DT and LB (OL, CB and S start in 2024: two pairs,
not enough seasons to hold out). Past seasons list PFN's qualifiers only, so the pairs are regulars and near-regulars;
snap counts exist for the front seven only, so workload is opportunities a game (scripts/cfb_breakout.py).

A. Workload scaling, offense and defense fit apart. Pairs of seasons, weight = the smaller reliability. Next-season
   efficiency z on this season's (shrunk by volume) + class + workload, then + the change in ln workload (dU), then
   + dU x context blocks. Held-out error on all pairs and on the pairs whose workload rose 25%+ (the case the tab
   projects).
B. Breakout odds. Rows: every base season 2019-2025. Breakout = next season a regular (T_REG a game, half the
   season's games) with a score z JUMP over his established level (the higher of this season's z shrunk to
   replacement and his 3-season Marcel). Baseline logistic: shrunk z, ln workload games, position. Candidates one at
   a time, then the passers together."""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L  # noqa: E402
import cfb_breakout as B  # noqa: E402

OUT = B.FIT
LAMS = (1e-3, 1e-2, 3e-2, 0.1, 0.3)
RISE = math.log(1.25)
TIER_PCT = (50, 80, 95)


def pick_lam(X, y, w, S):
    """ridge strength from an inner split of the training seasons (every other season held out)"""
    u = sorted(set(S.tolist()))
    hold = np.isin(S, u[1::2])
    best, bl = None, LAMS[0]
    for lam in LAMS:
        b0, b = L.wls(X[~hold], y[~hold], w[~hold], lam)
        e = float((w[hold] * (y[hold] - b0 - X[hold] @ b) ** 2).sum())
        if best is None or e < best:
            best, bl = e, lam
    return bl


def scaling(P, side):
    pos = B.OFF if side == 'off' else tuple(g for g in B.POS if g not in B.OFF)
    R = []
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if not b or a['g'] not in pos or b['g'] != a['g']:
            continue
        R.append((pid, y, a, b))
    S = np.array([y + 1 for _, y, _, _ in R], float)
    w = np.array([min(a['rel'], b['rel']) for _, _, a, b in R])
    du = np.array([math.log(b['u'] / a['u']) for _, _, a, b in R])
    y = np.array([b['ez'] for _, _, a, b in R])
    cols = B.columns(side)
    F = np.array([B.scale_feats(a, B.history(P, pid, yy), d, side) for (pid, yy, a, b), d in zip(R, du)])
    ix = lambda names: [cols.index(c) for c in names]  # noqa: E731
    base_c = B.BASE + B.DUMS[side]

    def blk_cols(k):
        out = []
        for t in B.block_traits(k, side):
            out.append('dU*' + t)
            if t not in base_c and t not in out:
                out.append(t)
        return out
    sets = {'base': base_c, 'dU': base_c + ['dU']}
    for k in B.BLOCKS:
        sets[k] = base_c + ['dU'] + blk_cols(k)
    sets['full'] = cols
    up = du >= RISE
    masks = {'all': np.ones(len(y), bool), 'up': up}

    def run(cs):
        X = F[:, ix(cs)]

        def fp(trn, te):
            lam = pick_lam(X[trn], y[trn], w[trn], S[trn])
            b0, b = L.wls(X[trn], y[trn], w[trn], lam)
            return b0 + X[te] @ b
        out = {}
        for key, m in masks.items():
            def e(p, te, m=m):
                mm = m[te]
                return (float((w[te][mm] * (y[te][mm] - p[mm]) ** 2).sum()), float(w[te][mm].sum()) or 1e-9)
            out[key] = L.loso(S, fp, e)
        return out
    res = {nm: run(cs) for nm, cs in sets.items()}
    cmp = {'dU vs base (all)': L.compare(res['base']['all'], res['dU']['all']),
           'dU vs base (rose 25%+)': L.compare(res['base']['up'], res['dU']['up']),
           'full vs base (rose 25%+)': L.compare(res['base']['up'], res['full']['up']),
           'full vs dU (rose 25%+)': L.compare(res['dU']['up'], res['full']['up'])}
    blocks = {k: L.compare(res['dU']['up'], res[k]['up']) for k in B.BLOCKS}
    L.holm(blocks)
    keep = [k for k in B.BLOCKS if blocks[k]['pass']]
    fin = base_c + ['dU'] + sum([blk_cols(k) for k in keep], [])
    rk = run(fin)
    cmp['kept vs base (all)'] = L.compare(res['base']['all'], rk['all'])
    cmp['kept vs base (rose 25%+)'] = L.compare(res['base']['up'], rk['up'])
    cmp['kept vs dU (rose 25%+)'] = L.compare(res['dU']['up'], rk['up'])
    X = F[:, ix(fin)]
    lam = pick_lam(X, y, w, S)
    b0, b = L.wls(X, y, w, lam)
    # ship the tiers when the fitted model beats the no-workload baseline out of sample on the risers
    t = cmp['kept vs base (rose 25%+)']
    ship = bool(t['t'] >= 2 and t['won'] * 2 > t['seasons'])
    print(side, 'pairs', len(R), 'rose', int(up.sum()), flush=True)
    for k, v in cmp.items():
        print('  ', k, v, flush=True)
    for k, v in blocks.items():
        print('   block', k, v, flush=True)
    return {'n': len(R), 'n_up': int(up.sum()), 'tests': cmp, 'blocks': blocks, 'keep': keep, 'lam': lam,
            'ship': ship, 'du99': round(float(np.quantile(du, 0.99)), 3), 'du01': round(float(np.quantile(du, 0.01)), 3),
            'fit': {'b0': round(float(b0), 5), 'cols': fin, 'b': [round(float(v), 6) for v in b]}}


def breakout(P, N):
    left = lambda o: 0.0 if (o['id'], o['y'] + 1) in P and P[(o['id'], o['y'] + 1)]['tm'] == o['tm'] else 1.0  # noqa: E731
    V = B.vacated(P, left)
    last = max(y for _, y in P)
    R = []
    for (pid, y), a in P.items():
        if y >= last:
            continue
        b = P.get((pid, y + 1))
        hist = B.history(P, pid, y)
        s0, mar = B.shr(a['vz'], a['v']), B.marcel(hist, y)
        hit = 0.0
        if b:
            n = N[f"{b['g']}|{y + 1}"]
            if b['u'] >= B.T_REG[b['g']] and b['gp'] >= 0.5 * n['gmax'] and b['vz'] >= max(s0, mar) + B.JUMP:
                hit = 1.0
        R.append((a, s0, hit, V[(pid, y)], mar))
    S = np.array([a['y'] + 1 for a, *_ in R], float)
    y = np.array([r[2] for r in R])
    rows = [B.bo_feats(a, s0, v, m) for a, s0, _, v, m in R]
    base = np.array([r['base'] for r in rows])
    cands = {k: np.array([r[k] for r in rows]) for k in B.BO_CANDS}

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
    keep = [k for k in cands if res[k]['pass']]
    X = np.column_stack([base] + [cands[k] for k in keep])
    final = L.compare(rb, run(X))
    # held-out calibration: every row scored by the fit that never saw its season
    ph = np.zeros(len(y))
    for s in sorted(set(S.tolist())):
        te = S == s
        b0, b = L.logit(X[~te], y[~te])
        ph[te] = L.sig(b0 + X[te] @ b)
    cal = []
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (ph >= lo) & (ph < hi)
        if m.sum():
            cal.append([lo, hi, int(m.sum()), round(float(ph[m].mean()), 3), round(float(y[m].mean()), 3)])
    b0, b = L.logit(X, y)
    by_pos = {g: [int(sum(1 for r in R if r[0]['g'] == g)), round(float(np.mean([r[2] for r in R if r[0]['g'] == g])), 4)]
              for g in B.POS}
    by_season = {int(s): round(float(y[S == s].mean()), 4) for s in sorted(set(S.tolist()))}
    print('breakout rate', round(float(y.mean()), 4), 'n', len(y), by_pos, by_season, flush=True)
    for k, v in res.items():
        print(' ', k, v, flush=True)
    print(' final', keep, final, flush=True)
    print(' calib (held out)', cal, flush=True)
    u0_min = {g: round(float(np.quantile([r[0]['u0'] for r in R if r[0]['g'] == g], 0.01)), 3) for g in B.POS}
    return {'n': len(y), 'rate': round(float(y.mean()), 4), 'u0_min': u0_min, 'by_pos': by_pos, 'by_season': by_season, 'tests': res,
            'keep': keep, 'final': final, 'calib_heldout': cal,
            'fit': {'b0': round(float(b0), 5), 'b': [round(float(v), 6) for v in b],
                    'mu': [round(float(v), 5) for v in X.mean(axis=0)]}}


def main():
    P = B.load('--offline' in sys.argv)
    N = B.season_norms(P)
    last = max(y for _, y in P)
    hist = {k: o for k, o in P.items() if k[1] < last}
    SD = B.sd_from(hist, N)
    P = B.standardize(P, N, SD)
    B.add_context(P)
    size = {}
    for g in B.POS:
        seen, hs, bs = set(), [], []
        for o in P.values():
            if o['g'] == g and o['_ht'] and o['id'] not in seen:
                seen.add(o['id'])
                hs.append(o['_ht'])
                bs.append(703.0 * o['_wt'] / o['_ht'] ** 2)
        size[g] = {'ht': [round(float(np.mean(hs)), 3), round(float(np.std(hs)), 3)],
                   'bmi': [round(float(np.mean(bs)), 3), round(float(np.std(bs)), 3)], 'n': len(hs)}
    for o in P.values():
        B.set_context(o, o['yrs'] if o['hasyrs'] else None, None if o['unr'] else o['stars'], o['_ht'], o['_wt'], size)
    cov = {k: round(float(np.mean([o[k] for o in P.values()])), 3) for k in ('hasyrs', 'hasfr')}
    cov['stars'] = round(float(np.mean([1 - o['unr'] for o in P.values()])), 3)
    print('player-seasons', len(P), 'coverage', cov, flush=True)
    A = {side: scaling(P, side) for side in ('off', 'def')}
    BO = breakout(P, N)
    tiers = {'pct': list(TIER_PCT), 'u': {}}
    for g in B.POS:
        us = sorted(o['u'] for o in P.values() if o['g'] == g and o['y'] < last and o['u'] >= B.T_REG[g]
                    and o['gp'] >= 0.5 * N[f"{g}|{o['y']}"]['gmax'])
        tiers['u'][g] = {str(p): round(float(np.quantile(us, p / 100)), 2) for p in TIER_PCT}
    f, so = BO['final'], A['off']
    kt = so['tests']['kept vs base (rose 25%+)']
    about = (f"breakout: next season a regular with a PFN score z {B.JUMP}+ over his established level (higher of this "
             f"season's z shrunk to replacement and 3-season Marcel); base {last}; odds = logistic on shrunk z, workload, "
             f"position + {', '.join(BO['keep']) or 'nothing else'} (each passes leave-one-season-out 2019-{last}; final "
             f"t {f['t']}, {f['won']}/{f['seasons']} seasons). OPP/G = attempts (QB), carries + catches (RB), targets "
             f"(WR, TE), snaps (EDGE, DT, LB) a game; seniors and workloads below the fit's range left out. ")
    if so['ship']:
        about += (f"tiers = the position's P50 / P80 / P95 workload among regulars: next-season yards per opportunity "
                  f"at that workload from players whose workload changed ({', '.join(so['keep']) or 'workload change only'}"
                  f"; held out t {kt['t']}, {kt['won']}/{kt['seasons']} seasons on workloads up 25%+); offense only; "
                  f"dim = a jump beyond the 99th percentile")
    else:
        about += (f"no workload tiers: the change in workload did not predict next-season efficiency out of sample "
                  f"(t {kt['t']}, {kt['won']}/{kt['seasons']} seasons on workloads up 25%+)")
    json.dump({'source': f'PFN impact rankings, FBS 2019-{last}', 'definition': {
                   'breakout': 'next season: T_REG opportunities a game and half the season\'s games, score z >= max(shrunk z, Marcel) + JUMP',
                   'jump': B.JUMP, 'rep': B.REP, 'k_shrink_games': B.K_SHR, 't_reg': B.T_REG, 'min_opp': B.MIN_OPP},
               'coverage': cov, 'scaling': A, 'breakout': BO, 'tiers': tiers, 'size': size,
               'norms': {k: {a: round(b, 5) for a, b in v.items()} for k, v in N.items()},
               'sd': {g: {a: round(b, 5) for a, b in v.items()} for g, v in SD.items()}, 'about': about},
              open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
