#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Rest days on UTC dates in the game models other than NBA (Nov 2 2026 follow-up to rest_research.py, where nba_games
read rest off UTC dates and missed 38% of its back-to-backs). Research script; results in data/rest_dates_research.json.

Audit (code read Nov 2 2026; no model change needed):
  NHL     rest / b2b from the NHL API's gameDate and the schedule's local date (not UTC); today = UTC-5. Clean.
  CBB     rest from cbb_games.et_date = UTC-8 (was UTC-5 until #665, Nov 1: 10 pm Pacific tips fell on the next day,
          so a West-coast team's next-night game read as two days off). Fixed before this pass.
  soccer  rest bands (r45) from soccer_games.lday (US Eastern for MLS night kickoffs, #683). Fixed before this pass.
  NFL     nflverse home_rest / away_rest (computed from local game dates). Clean.
  CFB     rest = hours between kickoffs / 24, clamped 4-14 (no calendar day). Clean.
  tennis  history days are the event's start + round offsets; live reads ESPN UTC dates, rest enters as log(days),
          and the events are worldwide. No US-date fix applies.
  close_model.py (NBA b2b cell) already used UTC-6.
So the only game-model term whose dates moved is CBB rest (UTC-5 -> UTC-8), already in the refit wf file. This re-scores
the near miss rest_research.py left open, b2bd (played the day before, home minus away), on the corrected dates:
  rest from the full D-I schedule (scripts/data/cbb_games_hist.json.gz) on et_date days, the model's own definition;
  y = margin, base = the walk-forward model (scripts/data/games_wf/cbb.json.gz 'm', which already holds linear rest).
  fixed:  b fit on 2016-20 (y - m on b2bd), applied to 2021-26: held MAE paired t clustered by game day
  walk:   each season 2017-26 from y ~ m + b2bd on the seasons before it (MAE vs y ~ m), 2017-20 tune / 2021-26 held
Pass (rest_research rule): tune t <= -1.5 and held t <= -1.5 in the expected direction.
Result (Nov 2 2026): FAIL, unchanged by the date fix. b tune -.98, held -1.95; MAE tune t -0.24, held t -2.62; walk
2017-20 t -0.22 (2/4), 2021-26 t -2.41 (5/6). On the old UTC-5 days: tune t -0.02, held t -2.36 (b2b games 2,232 vs 2,216).

    python3 scripts/rest_dates_research.py      # -> data/rest_dates_research.json
"""
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H                                     # noqa: E402
from cbb_games import et_date                           # noqa: E402

OUT = os.path.join(ROOT, 'data', 'rest_dates_research.json')
TUNE, HELD = range(2016, 2021), range(2021, 2027)


def rest_map(utc_shift=None):
    """{(game id, team id): days since that team's last game this season (model: 1-7, 7 for openers)}"""
    rows = json.load(gzip.open(os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')))
    day = (lambda r: et_date(r['date'])) if utc_shift is None else \
        (lambda r: (datetime.fromisoformat(r['date'].replace('Z', '+00:00')) - __import__('datetime').timedelta(hours=utc_shift)).strftime('%Y-%m-%d'))
    rows = sorted(rows, key=lambda r: (r['date'], r['id']))
    out, last = {}, {}
    for r in rows:
        d = datetime.strptime(day(r), '%Y-%m-%d').toordinal()
        for t in (r['home'], r['away']):
            p = last.get(t)
            out[(str(r['id']), t)] = max(1, min(7, d - p[0])) if p and p[1] == r['season'] else 7
        if r.get('hs') is not None:
            for t in (r['home'], r['away']):
                last[t] = (d, r['season'])
    return out, {str(r['id']): (r['home'], r['away']) for r in rows}


def run(utc_shift=None):
    rm, ids = rest_map(utc_shift)
    G = [g for g in json.load(gzip.open(os.path.join(HERE, 'data', 'games_wf', 'cbb.json.gz')))
         if g.get('res') is not None and g.get('m') is not None and str(g['id']) in ids]
    hid = [ids[str(g['id'])] for g in G]
    rh = np.array([rm.get((str(g['id']), h), 7) for g, (h, a) in zip(G, hid)], float)
    ra = np.array([rm.get((str(g['id']), a), 7) for g, (h, a) in zip(G, hid)], float)
    x = (rh == 1).astype(float) - (ra == 1).astype(float)
    y = np.array([g['res'] for g in G], float); m = np.array([g['m'] for g in G], float)
    S = np.array([g['S'] for g in G]); day = np.array([g['date'][:10] for g in G])
    tu, he = np.isin(S, TUNE), np.isin(S, HELD)
    r = y - m
    b = float((x[tu] @ r[tu]) / (x[tu] @ x[tu]))
    se_tu = H.paired(np.abs(r[tu] - b * x[tu]), np.abs(r[tu]), day[tu])
    se_he = H.paired(np.abs(r[he] - b * x[he]), np.abs(r[he]), day[he])
    # slope of the held residual on the flag, clustered by day
    bh = float((x[he] @ r[he]) / (x[he] @ x[he]))
    rep = {'games': int(len(G)), 'b2bShare': round(float(((rh == 1) | (ra == 1)).mean()), 4),
           'b2bTeamGames': {'tune': int(((rh == 1).sum(where=tu) + (ra == 1).sum(where=tu))), 'held': int(((rh == 1).sum(where=he) + (ra == 1).sum(where=he)))},
           'fixed': {'bTune': round(b, 3), 'bHeld': round(bh, 3),
                     'tuneMAE': {'d': round(se_tu['d'], 5), 't': round(se_tu['t'], 2)},
                     'heldMAE': {'d': round(se_he['d'], 5), 't': round(se_he['t'], 2)}}}
    # walk: y ~ m + x by the seasons before
    pw = np.full(len(y), np.nan); p0 = np.full(len(y), np.nan); coefs = {}
    for s in range(2017, 2027):
        tr, te = S < s, S == s
        A = np.c_[np.ones(tr.sum()), m[tr], x[tr]]; c = np.linalg.lstsq(A, y[tr], rcond=None)[0]
        A0 = np.c_[np.ones(tr.sum()), m[tr]]; c0 = np.linalg.lstsq(A0, y[tr], rcond=None)[0]
        pw[te] = np.c_[np.ones(te.sum()), m[te], x[te]] @ c; p0[te] = np.c_[np.ones(te.sum()), m[te]] @ c0
        coefs[str(s)] = round(float(c[2]), 3)
    wk = {}
    for nm, k in (('tune', np.isin(S, range(2017, 2021))), ('held', he)):
        pr = H.paired(np.abs(y[k] - pw[k]), np.abs(y[k] - p0[k]), day[k])
        won = sum(1 for s in set(S[k]) if np.abs(y[k & (S == s)] - pw[k & (S == s)]).mean() < np.abs(y[k & (S == s)] - p0[k & (S == s)]).mean())
        wk[nm] = {'d': round(pr['d'], 5), 't': round(pr['t'], 2), 'seasonsWon': f'{won}/{len(set(S[k]))}'}
    rep['walk'] = dict(wk, b2bdCoef=coefs)
    return rep


def main():
    rep = {'about': __doc__.split('\n\n')[0], 'cbb_b2bd_et8': run(), 'cbb_b2bd_et5_old': run(5)}
    v = rep['cbb_b2bd_et8']
    rep['verdict'] = 'PASS' if v['fixed']['tuneMAE']['t'] <= -1.5 and v['fixed']['heldMAE']['t'] <= -1.5 else 'FAIL'
    print(json.dumps(rep, indent=1))
    json.dump(rep, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
