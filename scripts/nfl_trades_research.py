#!/usr/bin/env python3
"""In-season moves (trades, waiver claims, signings off other teams) in the NFL game model (Nov 1 2026).

    python3 scripts/nfl_trades_research.py     # numpy; writes data/nfl_trades_research.json

Noah (Nov 1 2026): "make all of our pro sports models account for trades. Ex. Colts traded a lot of players this
week, game model should reflect the lost players and the new starters."

The live model's team ratings (Elo, EPA, the market rating from earlier closes) learn a roster only from games it
has played. The offseason roster prior (scripts/nfl_roster.py) prices the summer's moves once, at week 1, and the QB
term reads a new starter. Nothing prices a mid-season trade: the old team's ratings keep the departed player until
games without him wash him out, and the new team's ratings don't have him at all.

The term: for each team before each game, from nflverse weekly rosters (the team a player is on that week, known
before kickoff) and PFR snap counts (who played for whom):
    departures  players who took snaps for the team earlier this season and are on another club's roster now, each at
                his WAR a game (nfl_games.player_value: last season at half weight plus this season to date, the
                injury term's value) x the share of the team's games he played for it (what the ratings carry)
    arrivals    players on the team's roster this week who took snaps for another club earlier this season, at his WAR
                a game x the share of his clubs' games he played (his availability)
    moves       arrivals - departures, each x 0.5 ** (the team's games since the move / hl), in points (x 36)
QBs are left out (the QB term has the starter). Variants: values floored at 0 (as the injury term), arrivals or
departures alone, and a rating-weighted version (each departed player's weight in the EPA ratings' memory).

The bar (the project's): tune on 2015-20 walk-forward and keep at paired t <= -1.5 on the games it moves (and not
worse on all games), 2021-25 not worse. Both as a refit input and at fixed shares outside the fit (the offseason
prior's way: c x the term on top of the base walk-forward). Variants: direct (straight from one club's roster to the
other's week to week: trades and claims, not a cut and a later signing), regulars (played half his club's games).

Results (Nov 1 2026): nothing passes. ~1,000 games a period carry a move, the term's sd is .15-.40 points. Refit,
the weight runs negative for departures in every variant; fixed shares are all within +-.002 MAE of the base, best
arrivals/direct/hl4/c.25 t -1.1 tune, 0.0 held; both sides at the injury weight (c 1, hl 2, direct) t -0.3 / +0.5.
Result minus the close on the term: t -1.4 to +0.5, signs flip by period. Not in the margin (nfl_trades.TRADES c 0);
the cards list the moves. Retest after 2026-27 (each season adds ~70 direct moves).
"""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N   # noqa: E402
import nfl_war as W     # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nfl_trades_research.json')
FIRST = 2014


def main():
    import numpy as np
    import nfl_trades as T
    last = 2025
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, params)
    D = []
    for g, x, _ in data:
        s = int(g['season'])
        if g['home_score'] in ('', 'NA') or s < 2012:
            continue
        x = dict(x)
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D.append((g, x))
    terms = {}
    for y in range(FIRST, last + 1):
        terms[y] = T.season_terms(y, [g for g, _ in D if int(g['season']) == y])
        n = sum(1 for v in terms[y].values() for z in v if z[2] == 0 and z[3])
        print('season', y, 'moves', n, flush=True)
    S = np.array([int(g['season']) for g, _ in D])
    y = np.array([N.num(g['result']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D]); ok = ~np.isnan(line)
    XB = np.array([[x[f] for f in N.FEATS] for _, x in D])

    def feat(hl, kind='both', floor=False, direct=False, share=0.0):
        v = np.zeros(len(D))
        for i, (g, _) in enumerate(D):
            s = int(g['season'])
            if s not in terms:
                continue
            h, a = N.team(g['home_team']), N.team(g['away_team'])
            v[i] = (T.points(terms[s].get((g['game_id'], h), []), hl, kind, floor, direct, share)
                    - T.points(terms[s].get((g['game_id'], a), []), hl, kind, floor, direct, share))
        return v

    def wf(X, first=2015):
        pred = np.full(len(y), np.nan)
        for s in range(first, last + 1):
            tr, te = (S < s) & (S >= 2012), S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        b = np.linalg.lstsq(X[S >= 2012], y[S >= 2012], rcond=None)[0]
        return np.abs(pred - y), pred, b

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        if k.sum() < 3:
            return [0.0, 0.0, int(k.sum())]
        return [round(float(d.mean()), 4), round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()) + 1e-12)), 2), int(k.sum())]

    e0, p0, _ = wf(XB)
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok
    f_any = feat(0) != 0
    res = {'base': {'1520': round(float(e0[A].mean()), 4), '2125': round(float(e0[B].mean()), 4)},
           'line': {'1520': round(float(np.abs(line[A] - y[A]).mean()), 4), '2125': round(float(np.abs(line[B] - y[B]).mean()), 4)},
           'gamesWithMoves': {'1520': int((A & f_any).sum()), '2125': int((B & f_any).sum())}}
    print(res, flush=True)
    cand, fixed = {}, {}
    VARS = [(kind, floor, direct, share) for kind in ('both', 'arr', 'dep') for floor in (False, True)
            for direct, share in ((False, 0.0), (True, 0.0), (True, 0.5))]
    for kind, floor, direct, share in VARS:
        for hl in (1, 2, 4, 8, 0):
            f = feat(hl, kind, floor, direct, share)
            mv = f != 0
            blocks = {'all1520': A, 'all2125': B, 'mv1520': A & mv, 'mv2125': B & mv,
                      'big1520': A & (np.abs(f) >= 0.5), 'big2125': B & (np.abs(f) >= 0.5)}
            e1, _, b = wf(np.column_stack([XB, f]))
            key = f'{kind}{"/floor" if floor else ""}{"/direct" if direct else ""}{f"/share{share}" if share else ""}/hl{hl or "flat"}'
            cand[key] = {'coef': round(float(b[-1]), 3), 'sd': round(float(f[mv].std()) if mv.any() else 0.0, 3),
                         **{k: cmp(e1, e0, m) for k, m in blocks.items()}}
            print('refit', key, cand[key], flush=True)
            for c in (0.25, 0.5, 0.75, 1.0, 1.36):
                e1 = np.abs(p0 + c * f - y)
                fixed[f'{key}/c{c}'] = {k: cmp(e1, e0, m) for k, m in blocks.items()}
            # does the close miss it? (result - close on the term, games with a move)
            k = mv & ok & (S >= 2015)
            if k.sum() > 30:
                r_ = y[k] - line[k]
                for lab, kk in (('1520', S[k] <= 2020), ('2125', S[k] >= 2021)):
                    xx, yy = f[k][kk], r_[kk]
                    if len(xx) > 10 and xx.std() > 0:
                        bb = float(np.dot(xx - xx.mean(), yy - yy.mean()) / np.dot(xx - xx.mean(), xx - xx.mean()))
                        se = float(np.sqrt(np.sum((yy - yy.mean() - bb * (xx - xx.mean())) ** 2) / (len(xx) - 2) / np.sum((xx - xx.mean()) ** 2)))
                        cand[key][f'vsClose{lab}'] = [round(bb, 3), round(bb / se, 2), int(len(xx))]
    res['refit'] = cand
    res['fixed'] = fixed
    for k_, v in fixed.items():
        print('fixed', k_, v, flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
