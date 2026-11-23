#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB FV driver test: next up breakout odds (BO%) as a returner FV driver (Noah, Nov 23 2026; research only unless it
passes). Pre-registration: /mnt/project-files/next-up/prereg-bo-fv-nov23.md.

    python3 scripts/cbb_careers_kit.py        # once: scripts/.cache/cbb/careers.json
    python3 scripts/cbb_fv_bo_research.py     # -> scripts/data/cbb_fv_bo_research.json

BO% for a returner's board season Y = the shipped next up logistic (data/cbb_breakout_fit.json: base + kept signals,
scripts/cbb_breakout.py bo_feats) on his season Y-1 line, fit leave-one-season-out with season Y's breakout labels held
out (college breakout labels only; the FV outcome is never seen). Pool as the next up tab: 10+ min%, 10+ games, not
yet at the bar. Candidates, each added alone to the shipped returner drivers (data/cbb_fit.json):
  bo      BO%; players outside the pool (already at the bar, or too small a line) missing -> the mean
  bo_cap  BO%, with players already at the bar set to 1 (they are there); too small a line missing
Gate = scripts/cbb_fv_sweep3.py's (cbb_fv_sweep2 cv + held): 2009-16 boards out of fold under three fold rules
(gain, 4/5 folds, player-clustered t >= 2 each), and fit 2009-16 -> held 2017-19 and forward 2020-23 boards on the
horizon outcome with deviance gain and top 10/25/50 not worse. Holm is moot: pass = all three gates, both reported."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_lib as L
import cbb_breakout as B
import cbb_breakout_research as R
import cbb_data as D
import cbb_fit as F
import cbb_fv_sweep2 as S2

OUT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_fv_bo_research.json')
CANDS = ['bo', 'bo_cap']


def bo_table():
    """{(pid, base year): BO%} held out by season, and the set of (pid, base year) already at the bar"""
    P, _ = R.load(R.SRC)
    C = R.context(P)
    bar = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_breakout_fit.json')))['breakout']['L']
    keep = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_breakout_fit.json')))['breakout']['keep']
    rows, at = [], set()
    for (pid, y), a in P.items():
        b = P.get((pid, y + 1))
        if y < R.Y0 or not b or a['m'] < R.ROW_M or a['gp'] < R.ROW_GP:
            continue
        hist = B.history(P, pid, y)
        if B.level(a, hist)[0] >= bar:
            at.add((str(pid), y))
            continue
        s0, cur = B.level(a, hist)
        f = B.bo_feats(a, s0, cur, B.marcel(hist, y), C[(pid, y)], 0.0)
        rows.append((str(pid), y, 1.0 if B.broke_out(b, bar) else 0.0, sum([f['base']] + [list(np.atleast_1d(f[k])) for k in keep], [])))
    X = np.array([r[3] for r in rows], float); yv = np.array([r[2] for r in rows]); S = np.array([r[1] + 1 for r in rows])
    p = np.zeros(len(rows))
    for s in sorted(set(S.tolist())):
        te = S == s
        b0, b = L.logit(X[~te], yv[~te])
        p[te] = L.sig(b0 + X[te] @ b)
    print('BO% rows', len(rows), 'rate', round(float(yv.mean()), 4), 'already at the bar', len(at), flush=True)
    return {(r[0], r[1]): float(q) for r, q in zip(rows, p)}, at


def main():
    BO, AT = bo_table()
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    F.set_context(careers)
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    M = fitj['models']['returner']; F.TOP_MEAN = M['topMean']
    rows, hr, hit = [], [], 0
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2009 <= s['year'] <= 2023) or i == 0: continue
            f = F.features(c, i)
            k = (str(c['pid']), s['year'] - 1)
            f['bo'] = BO.get(k)
            f['bo_cap'] = 1.0 if k in AT else BO.get(k)
            hit += f['bo'] is not None
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'], 'last': c['last'],
                 'cls': (c['last'] - 2009) % F.FOLDS, 'f': f}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] >= 2017 and c['nba']['fvh'] is not None: hr.append(r)
    seen = {r['pid'] for r in rows}
    hr = [r for r in hr if r['pid'] not in seen]
    print(f'returner rows: train {len(rows)}, held 2017-19 {sum(r["year"] <= 2019 for r in hr)}, fwd 2020-23 '
          f'{sum(r["year"] >= 2020 for r in hr)}; with BO% {hit}', flush=True)
    nba = np.array([r['y'] >= 30 for r in rows])
    info = {}
    for cnd in CANDS:
        v = np.array([r['f'].get(cnd) if r['f'].get(cnd) is not None else np.nan for r in rows], dtype=float)
        bp = np.array([r['f']['bpm'] for r in rows], float); ok = ~np.isnan(v) & ~np.isnan(bp)
        info[cnd] = {'sd': round(float(np.nanstd(v)), 4), 'mean_nba': round(float(np.nanmean(v[nba])), 4),
                     'mean_non': round(float(np.nanmean(v[~nba])), 4), 'r_bpm': round(float(np.corrcoef(v[ok], bp[ok])[0, 1]), 3),
                     'missing': int(np.isnan(v).sum())}
        print(' ', cnd, info[cnd], flush=True)
    res, cvc, hc = {}, {}, {}
    for cnd in CANDS:
        a = S2.cv(rows, M['kept'], M['lam'], cnd, cvc)
        b = S2.held(rows, hr, M['kept'], M['lam'], cnd, hc)
        cv_ok = all(x['gain'] > 0 and x['folds'] >= 4 and x['t'] >= 2 for x in a.values())
        top_ok = lambda h: h['gain'] > 0 and all(h[k][1] >= h[k][0] for k in ('top10', 'top25', 'top50'))
        res[cnd] = {'cv': a, **b, 'pass': bool(cv_ok and top_ok(b['held']) and top_ok(b['fwd']))}
        print(cnd, 'PASS' if res[cnd]['pass'] else 'fail', json.dumps(res[cnd]), flush=True)
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'kept': M['kept'], 'info': info, 'results': res},
              open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
