#!/usr/bin/env python3
"""Research (Oct 30 2026): squad age next to squad market value in the soccer game model, after the NHL age line
(PR #583).

    python3 scripts/soccer_aging_research.py     # pandas + numpy; needs the Transfermarkt dump
                                                 # (scripts/.cache/soccer_prospects/dump); writes data/soccer_aging_research.json

The one player-value input is the top-18 squad market value (Transfermarkt, log, frozen checkpoints Jul 25 / Sep 2 /
Feb 3). A market value already carries age, but it prices resale as well as today's level: a young squad's value
holds potential it hasn't played to yet, so at equal value an older squad may be stronger now. Rebuilt from the dump
the same way as the checkpoints (each player's last club event before the date, his latest valuation in the 18 months
before, the club's top 18 by value; log value r .94-.99 with the frozen file from 2014 on), with each top 18's
value-weighted mean age and plain mean age. Input: half the home-minus-away age gap in years (like mvz), its weight
ag picked on 2013-22 by grid; the live model's other settings unchanged. Log loss on big-five and UEFA matches,
2013-22 (tuning) and 2023+ (held out), paired t by match; seasons better. Kept: tuning t <= -1.5, held out no worse.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D   # noqa: E402
import soccer_games as G  # noqa: E402

OUT = os.path.join(G.ROOT, 'data', 'soccer_aging_research.json')
DUMPD = os.path.join(HERE, '.cache', 'soccer_prospects', 'dump')


def squad_ages(cps):
    import pandas as pd
    rd = lambda n, c: pd.read_csv(os.path.join(DUMPD, n + '.csv.gz'), usecols=c)
    pl = rd('players', ['player_id', 'date_of_birth'])
    pl['dob'] = pd.to_datetime(pl['date_of_birth'], errors='coerce')
    v = rd('player_valuations', ['player_id', 'date', 'market_value_in_eur'])
    v['date'] = pd.to_datetime(v['date']); v = v.sort_values('date')
    ap = rd('appearances', ['player_id', 'player_club_id', 'date']).rename(columns={'player_club_id': 'club'})
    tr = rd('transfers', ['player_id', 'transfer_date', 'to_club_id']).rename(columns={'transfer_date': 'date', 'to_club_id': 'club'})
    ev = pd.concat([ap, tr]); ev['date'] = pd.to_datetime(ev['date'], errors='coerce'); ev = ev.dropna().sort_values('date')
    out = {}
    for cp in cps:
        d = pd.Timestamp(cp)
        c = ev[ev['date'] <= d].groupby('player_id').tail(1)[['player_id', 'club']]
        vv = v[(v['date'] <= d) & (v['date'] >= d - pd.Timedelta(days=550))].groupby('player_id').tail(1)
        m = c.merge(vv[['player_id', 'market_value_in_eur']], on='player_id').merge(pl[['player_id', 'dob']], on='player_id')
        m['age'] = (d - m['dob']).dt.days / 365.25
        m = m.dropna(subset=['age']).sort_values('market_value_in_eur', ascending=False).groupby('club').head(18)
        res = {}
        for club, x in m.groupby('club'):
            w = x['market_value_in_eur'].values.astype(float); a = x['age'].values
            if len(x) >= 11 and w.sum() > 0:
                res[str(int(club))] = (float(np.average(a, weights=w)), float(a.mean()))
        out[cp] = res
    return out


def main():
    rows = G.add_inj(G.add_mv(G.add_market(D.load(G.HIST))))
    T = D.load(G.MVF)
    cps, e2t = T['cp'], T['espn2tm']
    A = squad_ages(cps)
    mu = {k: float(np.mean([v[k] for c in A.values() for v in c.values()])) for k in (0, 1)}

    def at(t, day, k):
        tm = e2t.get(t)
        i = len(cps) - 1
        while i >= 0 and cps[i] > day:
            i -= 1
        if tm is None or i < 0:
            return None
        v = A[cps[i]].get(str(tm))
        return v[k] if v else None
    cover = 0
    for r in rows:
        for k, nm in ((0, 'agw'), (1, 'agm')):
            a, b = at(r['h'], r['day'], k), at(r['a'], r['day'], k)
            r[nm] = (a - b) / 2 if a is not None and b is not None else 0.0
        cover += r['agw'] != 0.0 and r['lg'] in G.SCORED and D.season_of(r['day'], r['lg']) >= G.SCORE_FROM
    P = G.params()
    mv0 = {id(r): r.get('mvz', 0.0) for r in rows}

    def per_match(ag, key):
        c = ag / P['mv'] if P['mv'] else 0.0
        for r in rows:
            r['mvz'] = mv0[id(r)] + c * r.get(key, 0.0)
        out = []

        def score(r, S, lh, la, R):
            pw, pd, pl = G.wdl(lh, la, P['rho'])
            y = pw if r['hs'] > r['as'] else pd if r['hs'] == r['as'] else pl
            out.append((S, -math.log(max(y, 1e-9))))
        G.run(rows, P, score)
        return np.array(out)
    base = per_match(0.0, 'agw')
    S = base[:, 0]
    tune, hold = (S >= G.TUNE[0]) & (S <= G.TUNE[1]), S >= G.HOLD_FROM

    def pt(a, b):
        d = a - b
        return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    nsc = sum(1 for r in rows if r.get('hs') is not None and r['lg'] in G.SCORED and D.season_of(r['day'], r['lg']) >= G.SCORE_FROM)
    res = {'coverageScored': round(cover / nsc, 3), 'meanAge': {'valueWeighted': round(mu[0], 2), 'plain': round(mu[1], 2)},
           'live': {'tune': round(float(base[tune, 1].mean()), 5), 'hold': round(float(base[hold, 1].mean()), 5)}, 'variants': []}
    print(res, flush=True)
    for key in ('agw', 'agm'):
        grid = {}
        for ag in (-0.04, -0.02, -0.01, 0.01, 0.02, 0.04):
            L = per_match(ag, key)
            grid[ag] = float(L[tune, 1].mean())
            print(' ', key, ag, round(grid[ag], 5), flush=True)
        ag = min(grid, key=grid.get)
        L = per_match(ag, key)
        r = {'label': key, 'ag': ag, 'grid': {str(k): round(v, 5) for k, v in grid.items()}}
        for nm, k in (('tune', tune), ('hold', hold)):
            r[nm] = {'n': int(k.sum()), 'dLL1e4': round(float((L[k, 1] - base[k, 1]).mean()) * 1e4, 2), 't': round(pt(L[k, 1], base[k, 1]), 2),
                     'seasons': f"{sum((L[k & (S == s), 1] - base[k & (S == s), 1]).mean() < 0 for s in sorted(set(S[k])))}/{len(set(S[k]))}"}
        r['kept'] = r['tune']['t'] <= -1.5 and r['hold']['dLL1e4'] <= 0
        print(json.dumps(r), flush=True)
        res['variants'].append(r)
    with open(OUT, 'w') as fh:
        json.dump(res, fh, indent=1)


if __name__ == '__main__':
    main()
