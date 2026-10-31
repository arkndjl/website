#!/usr/bin/env python3
"""NBA player props paper test (Oct 31 2026, Noah: "NBA/NHL player props in the same way we did NFL ones"): do
nba_players' projections, as they stand before the injury report, beat the books' opening prop lines and prices?

    python3 scripts/props_archive.py nba          # the opens: ESPN BET Jan 2024 on, DraftKings after (once)
    python3 scripts/nba_props_research.py         # -> data/nba_props_research.json, data/nba_props_fit.json (numpy)

Lines: the opening main over/under and both sides' opening prices of points, rebounds, assists and the combos (PRA,
points + rebounds, points + assists, assists + rebounds). A prop is void if he doesn't play, and so is a row here.

Projections: nba_players.collect() walked with no injury report (what's known when props open: who missed the last
games, not tonight's report) and the opening spread for the game script; each season's coefficients fit on the seasons
before it, the inputs those nba_players --fit chose. P(over): the negative binomial at the projection with the spread
(a mu + b mu^2) and logistic shape correction fit per stat on 2021-23 (no prop seasons).

Rule, pre-registered like NFL's: for each player's game, the prop and side with the highest P (one bet per player a
game: his props are near-duplicates), bet if P >= p*, p* in .54-.64 picked on 2024 (tune, Jan-Jun 2024), scored on
2025 and 2026 (held out) at the archived opening prices. Pass = held-out ROI > 0 with t >= 2, games as clusters, at the
book's own prices. -110 and the no-vig price less 1.5% (Novig's asks run ~1.5% inside) as checks.

Result (Oct 31 2026): fails. Held out 2025-26 at the book's prices, full projections: -2.5% (t -2.4, 7,568 bets) against
the closes, +0.1% against the opens; no-vig less 1.5% +1.4% (t 1.3) against the closes. The live Novig snapshots of Oct
21-30 2026 lose too. At an assumed -110 the same bets show +4 to +12%: the books charge more on the sides this model
likes, so a flat -110 grade (as NFL's, which had no archived prices) overstates.
"""
import gzip
import json
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_players as P  # noqa: E402
import props_model as M  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nba_props_research.json')
FIT = os.path.join(ROOT, 'data', 'nba_props_fit.json')
OPENS = os.path.join(HERE, 'data', 'props', 'nba_opens.json.gz')
ROWS = os.path.join(HERE, '.cache', 'nba_props_rows_{}.pkl')
SHAPE, TUNE, HELD = (2021, 2022, 2023), (2024,), (2025, 2026)
COMBO = {'pts': ('pts',), 'reb': ('reb',), 'ast': ('ast',), 'pra': ('pts', 'reb', 'ast'), 'pr': ('pts', 'reb'),
         'pa': ('pts', 'ast'), 'ar': ('ast', 'reb')}


def build_rows(ver):
    """every played row since 2020 with its walk-forward projection by stat. ver 'wed': no injury report and the
    opening spread (what's known when props open); 'full': the official report before tip and the closing line (the
    live build, against the closing props)"""
    fn = ROWS.format(ver)
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    import nba_games as N
    import nba_games_fit as NF
    lh, li = N.load_hist, NF.load_inj

    def opens():
        g, nm = lh()
        for x in g:
            if x.get('Lo') is not None:
                x['L'] = x['Lo']
        return g, nm
    if ver == 'wed':
        N.load_hist = opens
        NF.load_inj = lambda: {}
    elif not os.path.exists(N.INJ_HIST):
        sys.exit('full needs scripts/.cache/nba/inj_hist.json (python3 scripts/nba_inj_hist.py 2020 2026)')
    P.PCAL = None
    P.PCAL = P.measure_pcal(P.collect())
    rows = [r for r in P.collect() if r['y'] and r['nv']]
    F = json.load(open(P.FIT))
    S = np.array([r['S'] for r in rows])
    fitm = np.array([r['mS'] >= 10 and not r['po'] for r in rows])
    out = {'S': S, 'g': np.array([r['g'] for r in rows]), 'p': np.array([r['p'] for r in rows]),
           'po': np.array([r['po'] for r in rows])}
    for i, s in enumerate(('min',) + P.PSTATS):
        feats = F['stats'][s]['feats']
        A = np.array([[r['fx'][s][f] for f in feats] for r in rows])
        y = np.array([r['y'][i] for r in rows])
        pred = np.full(len(rows), np.nan)
        for yr in sorted(set(S)):
            tr = (S < yr) & fitm
            if tr.sum() < 1000:
                continue
            c = np.linalg.lstsq(A[tr], y[tr], rcond=None)[0]
            pred[S == yr] = A[S == yr] @ c
        out['mu_' + s], out['y_' + s] = np.maximum(pred, 0.05), y
        out['nv_' + s] = np.array([r['nv'][i] for r in rows])
    N.load_hist, NF.load_inj = lh, li
    pickle.dump(out, open(fn, 'wb'))
    return out


def fit_shapes(R):
    m = np.isin(R['S'], SHAPE) & ~np.isnan(R['mu_pts']) & (R['po'] == 0)
    return {st: M.fit_shape(sum(R['mu_' + c] for c in COMBO[st])[m], sum(R['y_' + c] for c in COMBO[st])[m],
                            sum(R['nv_' + c] for c in COMBO[st])[m]) for st in COMBO}


def prop_rows(R, sh, O, target):
    """graded props for one version of the projections against the opens or the closes (the last pregame line)"""
    ix = {(g, p): i for i, (g, p) in enumerate(zip(R['g'], R['p']))}
    props, miss = [], defaultdict(int)
    for gid, g in O.items():
        for a, st, L, oO, oU, cL, cO, cU, *_ in g['props']:
            if st not in COMBO:
                continue
            if target == 'close':
                L, oO, oU = cL, cO, cU
            i = ix.get((gid, a))
            if i is None:
                miss['row'] += 1
                continue
            if np.isnan(R['mu_pts'][i]):
                miss['mu'] += 1
                continue
            if oO is None or oU is None or not (-250 <= oO <= 250 and -250 <= oU <= 250) or abs(oO) < 100 or abs(oU) < 100:
                miss['price'] += 1
                continue
            mu = float(sum(R['mu_' + c][i] for c in COMBO[st]))
            y = float(sum(R['y_' + c][i] for c in COMBO[st]))
            props.append({'S': int(R['S'][i]), 'g': gid, 'a': a, 'st': st, 'L': L, 'oO': oO, 'oU': oU, 'y': y,
                          'mu': mu, 'P': M.p_over(sh[st], mu, L), 'q': M.no_vig(oO, oU), 'b': g['b'], 'k': g['k'],
                          'po': int(R['po'][i])})
    return props, dict(miss)


KEYS = ('pstar', 'held', 'heldBySeason', 'heldBySide', 'heldAllProps', 'calib', 'verdict')


def main():
    O = json.load(gzip.open(OPENS, 'rt'))
    out, fits = {}, {}
    for ver in ('wed', 'full'):
        R = build_rows(ver)
        sh = fit_shapes(R)
        fits[ver] = sh
        for target in ('open', 'close'):
            props, miss = prop_rows(R, sh, O, target)
            res = M.evaluate(props, TUNE, HELD, tuple(COMBO))
            res['missing'] = miss
            out[f'{ver} v {target}'] = res
            print(ver, target, len(props), json.dumps({k: res[k] for k in KEYS}), flush=True)
            print('  by stat alone', {st: (v['held'].get('roi'), v['held'].get('t'), v['held'].get('n'))
                                      for st, v in res['byStatAlone'].items()}, flush=True)
    # the live rule: the live build's projections (full) against the line it sees (between open and close; the close
    # is the harder bar, as the book has had the day's news)
    live = out['full v close']
    with open(OUT, 'w') as f:
        json.dump({'shape': fits, 'tests': out}, f, indent=1)
    with open(FIT, 'w') as f:
        json.dump({'registered': '2026-10-31', 'pstar': live['pstar'], 'c': live['calib']['c'], 'shape': fits['full'],
                   'verdict': live['verdict']}, f, separators=(',', ':'))
    return out


if __name__ == '__main__':
    main()
