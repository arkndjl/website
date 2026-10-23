#!/usr/bin/env python3
"""Barttorvik T-Rank stacked into the college basketball game model (team model idea 9, Oct 23 2026).

    python3 scripts/close_target_research.py --build cbb     # the shipped design (scripts/.cache/ct/cbb.npz)
    python3 scripts/public_ratings.py --cbb                  # T-Rank time machine, one file a day
    python3 scripts/public_ratings_cbb.py                    # writes data/public_ratings_cbb.json

ESPN BPI: its own forecast margin for each game (scripts/public_ratings.py --cbb-bpi), used only where the forecast
was last written before the tip, with a has-forecast indicator (0 margin otherwise).
Each game reads T-Rank as of the end of the day before it (Eastern date; the time machine file for day D counts D's
games). Columns: the T-Rank neutral margin (adjusted efficiencies crossed against the day's average, times the
two teams' tempo), and the same margin fading over each team's first 10 games (T-Rank's preseason prior against
ours). Margin weights walk forward (each season from the ones before it), D-I games, scored on absolute error:
tune 2016-20, held out 2021-26, paired with clustered errors (game day, home team-season). The ship bar is the
project's: tune t <= -1.5 and held out no worse.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import cbb_games as C  # noqa: E402
import public_ratings as PR  # noqa: E402

TUNE, HELD = (2016, 2020), 2021


def trank_margin(R, hb, ab):
    """neutral-court T-Rank margin, home minus away, points; None when a side is unrated"""
    if not R or hb not in R or ab not in R:
        return None, None
    oe = np.mean([v[0] for v in R.values()])
    tav = np.mean([v[4] for v in R.values() if v[4]]) if any(v[4] for v in R.values()) else 68.0
    h, a = R[hb], R[ab]
    poss = (h[4] or tav) * (a[4] or tav) / tav
    m = (h[0] * a[1] / oe - a[0] * h[1] / oe) * poss / 100
    return m, min(h[3], a[3])


def columns():
    z = np.load(os.path.join(HERE, '.cache', 'ct', 'cbb.npz'))
    games = C.load_hist()
    btname = C.bt_map(games)
    by = {str(g.get('id', '')): g for g in games}
    bpi = PR.bpi_load()
    cache, col, fade, ok, bm, bok = {}, [], [], [], [], []
    for gid in z['gid']:
        g = by[gid]
        # ESPN BPI's own forecast margin for the home side, only when it was last written before the tip
        b = bpi.get(gid)
        good = bool(b and b[1] is not None and b[0] and b[0][:16] <= g['date'][:16])
        bm.append(float(b[1]) if good else 0.0)
        bok.append(good)
        d = C.et_date(g['date'])
        if d not in cache:
            cache[d] = PR.trank_at(d)
        m, ng = trank_margin(cache[d], btname.get(g['home']), btname.get(g['away']))
        ok.append(m is not None)
        col.append(m or 0.0)
        fade.append((m or 0.0) * max(0.0, 1 - (ng or 0) / 10))
    return z, np.array(col), np.array(fade), np.array(ok), np.array(bm), np.array(bok)


def main():
    z, tm, tf, has, bm, bok = columns()
    X, y, S, L, d1 = z['X'], z['y'], z['S'], z['line'], z['d1']
    feats = list(z['feats'])
    cl = [z['day'], z['team']]
    base = H.walk_ols(X, y, S, TUNE[0], train=d1)
    ok = ~np.isnan(base) & d1
    tune, held = H.season_masks(S, TUNE, HELD, ok)
    lined = ~np.isnan(L)
    lb = H.ae(base, y)
    side = lambda a, m: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in H.paired(a[m], lb[m], [c[m] for c in cl]).items() if k in ('d', 't', 'n', 'G')}
    out = {'asof': str(np.datetime64('today')), 'feats': feats, 'coverage': {int(s): round(float(has[(S == s) & d1].mean()), 3) for s in np.unique(S)},
           'coverageBpi': {int(s): round(float(bok[(S == s) & d1].mean()), 3) for s in np.unique(S)},
           'base': {'tuneMae': round(float(lb[tune].mean()), 4), 'heldMae': round(float(lb[held].mean()), 4),
                    'heldMaeLined': round(float(lb[held & lined].mean()), 4), 'closeHeldMae': round(float(H.ae(L, y)[held & lined].mean()), 4)},
           'cands': {}}
    cands = {'trank': [tm], 'trankFade': [tf], 'trank+fade': [tm, tf], 'bpi': [bm, bok.astype(float)], 'bpi+trank': [bm, bok.astype(float), tm]}
    for k, cols in cands.items():
        Xc = np.column_stack([X] + cols)
        pr = H.walk_ols(Xc, y, S, TUNE[0], train=d1)
        la = H.ae(pr, y)
        w = H.fit_ols(Xc[d1 & (S <= 2025)], y[d1 & (S <= 2025)])
        out['cands'][k] = {'tune': side(la, tune), 'held': side(la, held), 'heldLined': side(la, held & lined),
                           'tuneMae': round(float(la[tune].mean()), 4), 'heldMae': round(float(la[held].mean()), 4),
                           'heldMaeLined': round(float(la[held & lined].mean()), 4),
                           'weights': {f: round(float(v), 4) for f, v in zip(feats + [f'c{i}' for i in range(len(cols))], w)}}
        print(k, json.dumps(out['cands'][k]), flush=True)
    with open(os.path.join(ROOT, 'data', 'public_ratings_cbb.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
