#!/usr/bin/env python3
"""Backtest: do player badges (scripts/cbb_badges.py) predict NBA value beyond the College Basketball ARKBOARD's FV?

    python3 scripts/cbb_link.py             # once: scripts/.cache/cbb/careers.json
    python3 scripts/cbb_badge_backtest.py   # -> data/cbb_badge_backtest.json

Universe: the board's training boards (preseason 2009-16, returners: a badge reads last season's line), careers that
ended by 2020, as scripts/cbb_fit.py builds them. Outcome: realized FV on peak XPM (the board's own target).
FV held fixed: the returner model's E[FV] out of fold (its kept drivers and penalties from data/cbb_fit.json, refit
with whole college classes held out, the board's nested outer folds).

Per badge (tier points 0-4, bronze 1 ... platinum 4, positional: the role family's returners with 300+ minutes):
  y-to-y r   last season vs the next one, back-to-back 300+ minute seasons 2008-26, each stat less its role-family
             season mean; k = n (1 - r) / r at the pairs' mean volume n. Under r .15 = noise, dropped.
  t          OLS FV ~ E[FV] + badge points, standard errors clustered by player (a player sits on several boards)
  oos        leave one board season out (8 folds): FV ~ E[FV] + badge fit on the other seasons, the gain in held-out
             R^2 over E[FV] alone, x100; seasons = how many of the 8 held-out seasons improve
  ladder     the badge added as a driver to the board's own hurdle ladder (class folds), the change in out-of-fold
             rung deviance x100 (positive = better) with its player-clustered paired t
Pass = t >= 2 (a badge is a good thing), oos > 0 and no loss on the held-out 2017-19 boards (forward: fit on 2009-16,
scored on the common-horizon FV, cbb_fit.horizon_fv). Passers are then fit jointly, strongest first, so two badges
measuring one thing don't both ship. The ladder gain decides whether a passer may also feed FV. Badges whose stat the
FV model already reads (assist, steal, block rate, rim FG%) can only add through the tier's shape (the top tail).

Results (Nov 1 2026; 23,106 returner rows, 12,119 players, 2009-16 boards; 6,307 held-out 2017-19 rows). Every badge
clears r .15 (3P% .39, FT% .49, rim FG% .30 are the noisy ones). t / oos x100 (seasons) / fwd x100:
  guards  Shooter -0.14 / -.03 (0/8)   FT Touch 1.02 / -.03   Playmaker* 1.20 / +.03 / fwd -.17   Ball Hawk* 1.09 / -.01
          Ball Security 0.64 / -.03    Finisher* -0.46 / -.07
  wings   Shooter -0.16 / -.01   FT Touch 1.65 / +.02 (6/8) / +.07   Playmaker* 0.47   Ball Hawk* -1.46   Rim Protector* -1.12
          Rebounder -0.60   Finisher* -1.41
  bigs    FT Touch 3.01 / +.66 (5/8) / +.39 (fwd t 1.86)  PASS     Shooter 2.42 / +.38 / +.15  PASS alone, t 1.55 next to FT
          Touch (one trait: touch) -> not shipped     Rebounder 2.61 / +.33 / -.28 (fails forward)   Finisher* 1.79
          Offensive Glass 1.05   Rim Protector* -1.62   Playmaker* -0.25
  (* the FV model already reads the stat linearly; these test only the tier's top tail, and none adds)
Shipped: bigs' FT Touch, display only. As a driver in the FV ladder it costs out-of-fold deviance (-.033, t -0.69), so
it doesn't feed FV. Twenty tests: one or two t >= 2 by chance alone is expected; FT Touch holds up held out too.
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
import cbb_badges as B

OUT = os.path.join(D.ROOT, 'data', 'cbb_badge_backtest.json')
MIN_R = 0.15


def yty(careers):
    """year-to-year r and k per stat part: role-family-season demeaned values, back-to-back 300+ minute seasons."""
    pairs = defaultdict(list)
    for c in careers:
        ss = c['seasons']
        for a, b in zip(ss, ss[1:]):
            if b['year'] != a['year'] + 1 or B.mpt(a) < B.MIN_MPT or B.mpt(b) < B.MIN_MPT: continue
            g = B.ROLES.get(a['role'], 'W')
            for p, (val, vol) in B.PARTS.items():
                va, vb = val(a), val(b)
                if va is None or vb is None: continue
                pairs[p].append((g, a['year'], va, vb, 0.5 * (vol(a) + vol(b))))
    out = {}
    for p, xs in pairs.items():
        ma, mb = defaultdict(list), defaultdict(list)
        for g, y, va, vb, _ in xs: ma[(g, y)].append(va); mb[(g, y)].append(vb)
        ma = {k: np.mean(v) for k, v in ma.items()}; mb = {k: np.mean(v) for k, v in mb.items()}
        A = np.array([va - ma[(g, y)] for g, y, va, vb, _ in xs]); Bv = np.array([vb - mb[(g, y)] for g, y, va, vb, _ in xs])
        r = float(np.corrcoef(A, Bv)[0, 1]); n = float(np.mean([x[4] for x in xs]))
        out[p] = {'pairs': len(xs), 'r': round(r, 3), 'n': round(n, 1), 'k': round(n * (1 - r) / r) if r > 0 else None}
    return out


def ols(X, y):
    A = np.column_stack([np.ones(len(y)), X])
    return np.linalg.lstsq(A, y, rcond=None)[0]


def clustered_t(X, y, cl):
    """OLS y ~ 1 + X, t of the last coefficient with cluster-robust (CR1) standard errors."""
    A = np.column_stack([np.ones(len(y)), X]); b = np.linalg.lstsq(A, y, rcond=None)[0]; e = y - A @ b
    Ai = np.linalg.inv(A.T @ A); M = np.zeros((A.shape[1],) * 2)
    for g in np.unique(cl):
        s = A[cl == g].T @ e[cl == g]; M += np.outer(s, s)
    G, n, k = len(np.unique(cl)), len(y), A.shape[1]
    V = Ai @ M @ Ai * G / (G - 1) * (n - 1) / (n - k)
    return b, b / np.sqrt(np.diag(V))


def paired_t(d, cl):
    s = defaultdict(float)
    for x, g in zip(d, cl): s[g] += x
    v = np.array(list(s.values())); G = len(v)
    return float(v.sum() / (math.sqrt(G / (G - 1) * ((v - v.mean()) ** 2).sum()) + 1e-12)) if G > 1 else 0.0


def ladder_oof(rows, X, lam):
    folds = np.array([r['cls'] for r in rows]); P = np.zeros((len(rows), len(F.LADDER)))
    idx = list(range(X.shape[1]))
    for k in np.unique(folds):
        tr, te = folds != k, folds == k
        m = F.fit([r for r, t in zip(rows, tr) if t], X[tr], idx, lam)
        P[te] = F.predict(m, X[te])[1]
    return P


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    fit = json.load(open(F.OUT))['models']['returner']
    kept, lam = fit['kept'], fit['lam']
    F.TOP_MEAN = round(float(np.mean([c['nba']['fvx'] for c in careers if c['last'] in F.SCALE_CLASSES and c['nba']['fvx'] >= 60])), 2)

    R = yty(careers)
    kk = {p: v['k'] for p, v in R.items()}
    print('year-to-year r, k:', {p: (v['r'], v['k']) for p, v in R.items()})

    F.horizon_fv(careers)
    rows, held = [], []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if i == 0: continue
            prev = c['seasons'][i - 1]
            r = {'pid': c['pid'], 'cls': (c['last'] - 2009) % F.FOLDS, 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'],
                 'f': None, 'line': prev, 'g': B.ROLES.get(prev['role'], 'W'), 'c': c, 'i': i}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] in F.HELD and c['nba']['fvh'] is not None: held.append(r)
    seen = {r['pid'] for r in rows}
    held = [r for r in held if r['pid'] not in seen]
    for r in rows + held: r['f'] = F.features(r['c'], r['i'])
    print(len(rows), 'returner board rows,', len(seen), 'players;', len(held), 'held-out 2017-19 rows')
    # badge tier points per row: within each board season and role family
    cands = sorted({k for ks in B.GROUPS.values() for k in ks})
    for key in cands:
        for r in rows: r[key] = 0.0
    by = defaultdict(list)
    for r in rows + held: by[(r['year'], r['g'])].append(r)
    for (yr, g), rs in by.items():
        for key in B.GROUPS[g]:
            for r, (t, pct) in zip(rs, B.tiers([x['line'] for x in rs], key, kk)):
                r[key] = float(B.PTS[t]) if t else 0.0

    y = np.array([r['y'] for r in rows]); pid = np.array([r['pid'] for r in rows]); yr = np.array([r['year'] for r in rows])
    X0 = F.matrix(rows, kept)
    P0 = ladder_oof(rows, X0, lam); E0 = F.expected(P0); D0 = F.row_dev(P0, y).sum(1) * 100
    print(f'base: corr(E, FV) {np.corrcoef(E0, y)[0, 1]:.3f}, deviance {D0.sum():.3f}')
    # forward: the fit on every training board grades the held-out 2017-19 boards (outcome: common-horizon FV)
    Eh = F.predict(F.fit(rows, X0, list(range(len(kept))), lam), F.matrix(held, kept))[2]
    yh = np.array([r['yh'] for r in held]); pidh = np.array([r['pid'] for r in held])

    def forward(g, bcols):
        it = [i for i, r in enumerate(rows) if r['g'] == g]; ih = [i for i, r in enumerate(held) if r['g'] == g]
        Xt = np.column_stack([E0[it]] + [[rows[i][k] for i in it] for k in bcols])
        Xh = np.column_stack([Eh[ih]] + [[held[i][k] for i in ih] for k in bcols])
        b1 = ols(Xt, y[it]); b0 = ols(Xt[:, :1], y[it])
        e1 = ((yh[ih] - b1[0] - Xh @ b1[1:]) ** 2).sum(); e0 = ((yh[ih] - b0[0] - b0[1] * Xh[:, 0]) ** 2).sum()
        sst = ((yh[ih] - yh[ih].mean()) ** 2).sum()
        _, th = clustered_t(Xh, yh[ih], pidh[ih])
        return round(float(100 * (e0 - e1) / sst), 3), round(float(th[-1]), 2), len(ih)

    def test(rs_ix, bcols):
        """bcols: list of badge keys; returns dict of numbers for the last one (and joint betas)."""
        ix = np.array(rs_ix)
        Xb = np.column_stack([[rows[i][k] for i in ix] for k in bcols])
        Xf = np.column_stack([E0[ix], Xb])
        b, t = clustered_t(Xf, y[ix], pid[ix])
        _, t2 = clustered_t(np.column_stack([E0[ix], E0[ix] ** 2, Xb]), y[ix], pid[ix])   # E[FV]'s curve held too
        test.t2 = float(t2[-1])
        sse0 = sse1 = sst = 0.0; wins = 0
        for s in np.unique(yr[ix]):
            tr, te = yr[ix] != s, yr[ix] == s
            b0 = ols(E0[ix][tr][:, None], y[ix][tr]); b1 = ols(Xf[tr], y[ix][tr])
            e0 = ((y[ix][te] - b0[0] - b0[1] * E0[ix][te]) ** 2).sum()
            e1 = ((y[ix][te] - b1[0] - Xf[te] @ b1[1:]) ** 2).sum()
            sse0 += e0; sse1 += e1; sst += ((y[ix][te] - y[ix][tr].mean()) ** 2).sum(); wins += e1 < e0
        return b, t, 100 * (sse0 - sse1) / sst, int(wins)

    allix = list(range(len(rows)))
    out = {'asof': __import__('datetime').date.today().isoformat(), 'method': 'see scripts/cbb_badge_backtest.py',
           'rows': len(rows), 'players': len(set(pid)), 'boards': '2009-2016', 'yty': R, 'groups': {}}
    passers = defaultdict(list)
    for g, keys in B.GROUPS.items():
        gix = [i for i in allix if rows[i]['g'] == g]
        res = {'n': len(gix), 'nba': int((y[gix] >= 30).sum()), 'badges': {}}
        for key in keys:
            name, parts, label, inmodel = B.CANDIDATES[key]
            rr = min(R[p]['r'] for p in parts)
            hold = sum(1 for i in gix if rows[i][key] > 0)
            d = {'name': name, 'stat': label, 'fvDriver': inmodel, 'r': rr, 'k': {p: R[p]['k'] for p in parts}, 'holders': hold}
            if rr < MIN_R:
                d['pass'] = False; d['note'] = 'year-to-year r under .15'; res['badges'][key] = d; continue
            b, t, gain, wins = test(gix, [key])
            # the board's own ladder with the badge as a driver (in this family only: 0 elsewhere)
            X1 = np.column_stack([X0, [rows[i][key] if rows[i]['g'] == g else 0.0 for i in allix]])
            P1 = ladder_oof(rows, X1, lam); D1 = F.row_dev(P1, y).sum(1) * 100
            lg = float(D0.sum() - D1.sum()); lt = paired_t(D0 - D1, pid)
            fg, ft_, nh = forward(g, [key])
            d.update({'beta': round(float(b[2]), 3), 't': round(float(t[2]), 2), 'tCurve': round(test.t2, 2), 'oosGain': round(gain, 3),
                      'seasons': f'{wins}/8', 'ladderGain': round(lg, 3), 'ladderT': round(lt, 2), 'fwdGain': fg, 'fwdT': ft_, 'fwdN': nh})
            d['pass'] = bool(t[2] >= 2 and gain > 0 and fg >= 0)   # and no worse on the held-out 2017-19 boards
            if d['pass']: passers[g].append((float(t[2]), key))
            res['badges'][key] = d
            print(f"{g} {name:16s} r {rr:.2f} holders {hold:5d} beta {b[2]:+.3f} t {t[2]:+.2f} (curve {test.t2:+.2f}) oos {gain:+.3f} ({wins}/8) "
                  f"ladder {lg:+.3f} (t {lt:+.2f}) fwd {fg:+.3f} (t {ft_:+.2f}, n {nh}){' PASS' if d['pass'] else ''}{' [FV driver]' if inmodel else ''}")
        # jointly: strongest first; the next one ships only if it still has t >= 2 and adds held-out R^2 next to those kept
        keep = []
        for _, key in sorted(passers[g], reverse=True):
            if not keep: keep.append(key); continue
            b, t, gain, _ = test(gix, keep + [key]); _, _, g0, _ = test(gix, keep)
            ok = t[-1] >= 2 and gain > g0
            res['badges'][key]['joint'] = {'with': list(keep), 't': round(float(t[-1]), 2), 'oosAdd': round(float(gain - g0), 3), 'kept': bool(ok)}
            print(g, key, 'next to', keep, res['badges'][key]['joint'])
            if ok: keep.append(key)
        passers[g] = keep
        if keep: res['ship'] = keep; res['shipFwd'] = dict(zip(('gain', 't', 'n'), forward(g, keep)))
        out['groups'][g] = res
    out['ship'] = {g: v for g, v in passers.items() if v}
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT, 'ship:', out['ship'])


if __name__ == '__main__':
    main()
