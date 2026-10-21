#!/usr/bin/env python3
"""Research: provisional values for NFL players the injury term can't price (no WAR to date), and the next man up.

    python3 scripts/nfl_inj_prov_research.py     # writes data/nfl_inj_prov_research.json (numpy; ~10 min warm)

The live injury term (nfl_games.injury_history) costs each listed non-QB at his WAR a game, last season at half weight
plus this season, shrunk toward replacement (0) with three games. A rookie or a player with no snaps yet is worth 0,
so a first-round rookie starter listed out costs nothing. Variants, each the same walk-forward refit as the live model
(train on every season before, score the season; 2017-20 picks, 2021-25 held out, paired per game):
    slot     players in their first two seasons shrink toward their draft slot's WAR a game (a + b ln(pick), fit on
             earlier seasons' first- and second-year players, games-weighted); undrafted at the fit's undrafted mean
    slot1    the same, rookies only
    nextK    each listed player's cost less K% of the value of the healthy teammate behind him (the same position
             group's best player by WAR a game below him who isn't listed), K 25/50/100
Kept by the fit's rule: paired t <= -1.5 on the selection seasons and the held-out seasons no worse.
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N
import nfl_war as W

OUT = os.path.join(N.ROOT, 'data', 'nfl_inj_prov_research.json')
RAW = os.path.join(N.CACHE, 'inj_raw_v1.json')


def draft():
    out = {}
    for r in N.rows(N.get('draft_picks.csv', f'{N.REL}/draft_picks/draft_picks.csv')):
        if r.get('gsis_id') and r.get('pick', '').isdigit():
            out[r['gsis_id']] = (int(r['season']), int(r['pick']))
    return out


def rookie_years(years):
    """gsis -> rookie season (roster files), for undrafted players"""
    out = {}
    for y in years:
        for r in N.rows(N.get(f'roster_{y}.csv', f'{N.REL}/rosters/roster_{y}.csv')):
            g = r.get('gsis_id')
            if not g:
                continue
            ry = r.get('rookie_year') or r.get('entry_year') or ''
            if ry.isdigit():
                out.setdefault(g, int(ry))
            elif r.get('years_exp') == '0':
                out.setdefault(g, y)
    return out


def positions(y):
    out = {}
    for r in N.rows(N.get(f'roster_{y}.csv', f'{N.REL}/rosters/roster_{y}.csv')):
        if r.get('gsis_id'):
            out[r['gsis_id']] = (N.team(r['team']), W.GROUP.get(r.get('position') or '') or W.GROUP.get(r.get('depth_chart_position') or ''))
    return out


def raw(games, years):
    """per game side: the report's non-QBs (gsis, status, played last game, prev [WAR, g], cur [WAR, g]) and the team's
    healthy players by group (gsis, prev, cur), all as of that week (no look-ahead)"""
    try:
        cache = json.load(open(RAW))
    except (OSError, ValueError):
        cache = {}
    for y in years:
        if str(y) in cache:
            continue
        maps = W.gsis_map(y)
        prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
        top = max([int(g['week']) for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')] + [1])
        led = {w: W.war_ledger(y, thru=w, maps=maps) for w in range(1, min(top + 1, 19) + 1)}
        pos = positions(y)
        rep = defaultdict(list)
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(N.team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status']))
        sg = [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]
        last_wk, out = {}, {}
        for g in sg:
            w = int(g['week'])
            row = []
            for side in ('home', 'away'):
                t = N.team(g[f'{side}_team'])
                pw = last_wk.get(t)
                L = led[min(w, 19, top + 1)]
                listed = []
                for gsis, stt in rep.get((t, w), []):
                    if pw is None or pw >= 18 or w > 18:
                        played = True
                    else:
                        played = led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    listed.append([gsis, stt, played, list(prev.get(gsis, (0.0, 0))), list(L.get(gsis, (0.0, 0))), pos.get(gsis, (t, None))[1]])
                on = {x[0] for x in listed}
                # the healthy depth: this season's players on the team (by roster file) with any value to date
                depth = defaultdict(list)
                for gsis, (tt, grp) in pos.items():
                    if tt == t and grp and gsis not in on and (gsis in L or gsis in prev):
                        depth[grp].append([gsis, list(prev.get(gsis, (0.0, 0))), list(L.get(gsis, (0.0, 0)))])
                row.append({'listed': listed, 'depth': depth})
                last_wk[t] = w
            out[g['game_id']] = row
        cache[str(y)] = out
        json.dump(cache, open(RAW, 'w'))
        print('raw', y, len(out), flush=True)
    return {int(y): v for y, v in cache.items() if int(y) in years}


def slot_curve(years_fit, drafted, ry, ledgers, exp_max):
    """WAR a game by draft slot for players in their first exp_max+1 seasons: a + b ln(pick) and the undrafted mean,
    games-weighted, from full seasons in years_fit"""
    xs, ys, ws, ux, uw = [], [], [], [], []
    for y in years_fit:
        for gsis, (war, g) in ledgers[y].items():
            if g <= 0:
                continue
            d = drafted.get(gsis)
            if d and 0 <= y - d[0] <= exp_max:
                xs.append(math.log(d[1])); ys.append(war / g); ws.append(g)
            elif not d and ry.get(gsis) is not None and 0 <= y - ry[gsis] <= exp_max:
                ux.append(war / g); uw.append(g)
    X = np.column_stack([np.ones(len(xs)), xs]); w = np.array(ws)
    b = np.linalg.solve(X.T @ (X * w[:, None]), X.T @ (np.array(ys) * w))
    return float(b[0]), float(b[1]), float(np.average(ux, weights=uw)) if uw else 0.0


def main():
    last = 2025
    F = json.load(open(N.FIT))
    params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    years = list(range(N.INJ_FIRST, last + 1))
    R = raw(games, years)
    drafted = draft()
    ry = rookie_years(range(N.INJ_FIRST - 6, last + 1))
    ledgers = {y: W.war_ledger(y, maps=W.gsis_map(y)) for y in range(N.INJ_FIRST - 4, last + 1)}
    curves = {}
    for y in years:
        fit_years = [z for z in range(N.INJ_FIRST - 4, y)]
        curves[(y, 0)] = slot_curve(fit_years, drafted, ry, ledgers, 0)
        curves[(y, 1)] = slot_curve(fit_years, drafted, ry, ledgers, 1)
    print('slot curves (a, b, undrafted)', {f'{y}/{e}': [round(v, 4) for v in c] for (y, e), c in curves.items() if y in (2016, 2021, 2025)})

    def prior(gsis, y, exp_max):
        d = drafted.get(gsis)
        a, b, u = curves[(y, exp_max)]
        if d and 0 <= y - d[0] <= exp_max:
            return a + b * math.log(d[1])
        if not d and ry.get(gsis) is not None and 0 <= y - ry[gsis] <= exp_max:
            return u
        return 0.0

    def value(prev, cur, p=0.0):
        return (0.5 * prev[0] + cur[0] + 3 * p) / (0.5 * prev[1] + cur[1] + 3)

    def cost(y, side, variant):
        c = 0.0
        exp_max = 1 if 'slot' in variant and 'slot1' not in variant else 0 if 'slot1' in variant else None
        share = {'next25': 0.25, 'next50': 0.5, 'next100': 1.0}.get(variant.split('+')[0], 0.0)
        for gsis, stt, played, pv, cv, grp in side['listed']:
            p = prior(gsis, y, exp_max) if exp_max is not None else 0.0
            v = max(value(pv, cv, p), 0.0)
            if variant.startswith('next') and grp:
                # the next man up: the best healthy teammate in the group by WAR a game whose own snaps leave room
                # (fewer games' worth of value than the listed player); he takes over the listed player's work, so the
                # loss is the listed player's value less what the backup does with it beyond his own current role
                behind = [value(b[1], b[2], prior(b[0], y, exp_max) if exp_max is not None else 0.0) for b in side['depth'].get(grp, [])]
                behind = [b for b in behind if b < v]
                if behind:
                    v = v - share * max(0.0, max(behind))
            c += (1 - N.play_prob(stt, played)) * v * N.PTS_PER_WIN
        return c

    variants = ['live', 'slot', 'slot1', 'next25', 'next50', 'next100', 'next50+slot']
    inj = {v: {} for v in variants}
    for y, gm in R.items():
        for gid, (h, a) in gm.items():
            for v in variants:
                inj[v][gid] = cost(y, a, 'live' if v == 'live' else v) - cost(y, h, 'live' if v == 'live' else v)
    _, data = N.walk(games, box, qbs, params)
    D = [(g, x) for g, x, _ in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    S = np.array([int(g['season']) for g, _ in D])
    y = np.array([N.num(g['result']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D])
    ok = ~np.isnan(line)
    A = (S >= 2017) & (S <= 2020) & ok; B = (S >= 2021) & ok
    base = [f for f in N.FEATS if f != 'inj']

    def wf(v):
        X = np.array([[x[f] for f in base] + [inj[v].get(g['game_id'], 0.0)] for g, x in D])
        pred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            pred[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        b = np.linalg.lstsq(X[S >= 2016], y[S >= 2016], rcond=None)[0]
        return np.abs(pred - y), float(b[-1])

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return {'d': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)}

    e0, c0 = wf('live')
    res = {'live': {'mae1720': round(float(e0[A].mean()), 4), 'mae2125': round(float(e0[B].mean()), 4), 'coef': round(c0, 3),
                    'line2125': round(float(np.abs(line[B] - y[B]).mean()), 4)},
           'curves': {str(y): [round(v, 4) for v in curves[(y, 1)]] for y in years}}
    for v in variants[1:]:
        e1, c1 = wf(v)
        r = {'mae1720': round(float(e1[A].mean()), 4), 'mae2125': round(float(e1[B].mean()), 4), 'coef': round(c1, 3),
             'd1720': cmp(e1, e0, A), 'd2125': cmp(e1, e0, B)}
        r['kept'] = r['d1720']['t'] <= -1.5 and r['d2125']['d'] <= 0
        res[v] = r
        print(v, r, flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
