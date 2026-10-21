#!/usr/bin/env python3
"""Research: the NFL injury term with the starter's backup priced in (Noah, Oct 21: better backup grades should price an
injury better). Follows scripts/nfl_inj_prov_research.py, which found that netting a backup's WAR a game failed: a
backup's WAR a game is his part-time role's, not what he does in the starter's snaps.

    python3 scripts/nfl_backup_research.py     # writes data/nfl_backup_research.json (numpy; ~15 min warm)

Who replaces him: the weekly depth chart (nflverse depth_charts; 2025's daily ESPN snapshots, the last one 4+ days
before the game): the next player at the listed player's slot on the chart before the game week, skipping teammates
also listed out or doubtful. What the backup is worth there: his WAR a snap (last season at half weight plus this
season to date) shrunk with k snaps toward a provisional rate: his position group's backup rate (players under 300
snaps a season, earlier seasons), moved by draft slot for first- and second-year players (a + b ln(pick), earlier
seasons) - so a backup with no snaps yet has a value. Times the starter's snaps a game. The listed player's cost is
his WAR a game less that, at his chance to miss (the live play chances). Variants k = 100, 300, 1000 snaps; 'net0'
the same with the backup floored at replacement. Same walk-forward refit as the live model; kept at paired t <= -1.5
on 2017-20 and 2021-25 no worse.
"""
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N
import nfl_war as W
from nfl_inj_prov_research import draft, rookie_years

OUT = os.path.join(N.ROOT, 'data', 'nfl_backup_research.json')
RAW = os.path.join(N.CACHE, 'inj_backup_raw_v1.json')
OFF = {'QB', 'RB', 'WR', 'TE', 'OL'}


def ledger(y, thru=None, maps=None):
    """{gsis: [WAR, games, snaps, group]} for season y before week thru, on the board's formula (nfl_war.war_ledger
    plus snaps and group)"""
    b = json.load(open(W.FIT))['coef']
    by_pfr, by_name = maps or W.gsis_map(y)
    sd = W.season_data(y, False, thru)
    out = {}
    for (pfr, t), s in sd['snaps'].items():
        gsis = by_pfr.get(pfr) or by_name.get((s['name'].lower(), t))
        g, _ = W.group_of(s['pos'], '')
        if not gsis or not g:
            continue
        x = W.features(sd, pfr, gsis, t, g)
        if x is None:
            continue
        P = sd['plays'][t]
        share = ((s['off'] / P[0]) if g in W.OFFENSE else (s['def'] / P[1])) * sd['team'][t]['g'] / 17 if P[0] and P[1] else 0.0
        a = out.setdefault(gsis, [0.0, 0, 0, g])
        a[0] += (W.predict(b, g, x) - W.NFL_REPL[g] * share) * W.NWAR_PER_AV
        a[1] += s['g']
        a[2] += s['off'] if g in OFF else s['def']
    return out


def charts(y, games):
    """(team, week) -> {gsis: (slot, depth)} from the chart before that week's game (the week before; week 1's own)"""
    rows = N.rows(N.get(f'depth_charts_{y}.csv', f'{N.REL}/depth_charts/depth_charts_{y}.csv'))
    out = {}
    if y < 2025:
        wk = defaultdict(dict)
        for r in rows:
            if r.get('game_type') != 'REG' or not r.get('gsis_id') or not r.get('week', '').isdigit():
                continue
            k = (N.team(r['club_code']), int(r['week']))
            slot = (r.get('formation'), r.get('depth_position') or r.get('position'))
            d = int(r['depth_team']) if r.get('depth_team', '').isdigit() else 9
            if r['gsis_id'] not in wk[k] or d < wk[k][r['gsis_id']][1]:
                wk[k][r['gsis_id']] = (slot, d)
        for (t, w) in list(wk):
            out[(t, w + 1)] = wk[(t, w)]
        for (t, w), v in wk.items():
            out.setdefault((t, w), v)
        return out
    snaps = defaultdict(lambda: defaultdict(dict))        # team -> dt -> {gsis: (slot, rank)}
    for r in rows:
        if r.get('gsis_id') and r.get('pos_rank', '').isdigit():
            slot = (r.get('pos_grp'), r.get('pos_abb'))
            cur = snaps[N.team(r['team'])][r['dt'][:10]].get(r['gsis_id'])
            if not cur or int(r['pos_rank']) < cur[1]:
                snaps[N.team(r['team'])][r['dt'][:10]][r['gsis_id']] = (slot, int(r['pos_rank']))
    for g in games:
        if int(g['season']) != y:
            continue
        cut = (date.fromisoformat(g['gameday']) - timedelta(days=4)).isoformat()
        for side in ('home', 'away'):
            t = N.team(g[f'{side}_team'])
            ds = [d for d in snaps.get(t, {}) if d <= cut] or sorted(snaps.get(t, {}))[:1]
            if ds:
                out[(t, int(g['week']))] = snaps[t][max(ds)]
    return out


def raw(games, years):
    try:
        cache = json.load(open(RAW))
    except (OSError, ValueError):
        cache = {}
    for y in years:
        if str(y) in cache:
            continue
        maps = W.gsis_map(y)
        prev = ledger(y - 1, maps=W.gsis_map(y - 1))
        top = max([int(g['week']) for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')] + [1])
        led = {w: ledger(y, thru=w, maps=maps) for w in range(1, min(top + 1, 19) + 1)}
        ch = charts(y, games)
        rep = defaultdict(list)
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(N.team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status']))
        last_wk, out = {}, {}
        for g in [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]:
            w = int(g['week'])
            row = []
            for side in ('home', 'away'):
                t = N.team(g[f'{side}_team'])
                pw = last_wk.get(t)
                L = led[min(w, 19, top + 1)]
                C = ch.get((t, w), {})
                outs = {gs for gs, st in rep.get((t, w), []) if st in ('Out', 'Doubtful')}
                listed = []
                for gsis, stt in rep.get((t, w), []):
                    played = True if pw is None or pw >= 18 or w > 18 else led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    bk = None
                    if gsis in C:
                        slot, d = C[gsis]
                        behind = sorted((dd, gs) for gs, (sl, dd) in C.items() if sl == slot and dd > d and gs not in outs)
                        bk = behind[0][1] if behind else None
                    pv, cv = prev.get(gsis), L.get(gsis)
                    grp = (cv or pv or [None, None, None, None])[3]
                    bp, bc = (prev.get(bk), L.get(bk)) if bk else (None, None)
                    listed.append([gsis, stt, played, pv[:3] if pv else [0.0, 0, 0], cv[:3] if cv else [0.0, 0, 0], grp, bk,
                                   bp[:3] if bp else [0.0, 0, 0], bc[:3] if bc else [0.0, 0, 0]])
                row.append(listed)
                last_wk[t] = w
            out[g['game_id']] = row
        cache[str(y)] = out
        json.dump(cache, open(RAW, 'w'))
        print('raw', y, len(out), flush=True)
    return {int(y): v for y, v in cache.items() if int(y) in years}


def main():
    last = 2025
    F = json.load(open(N.FIT))
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    years = list(range(N.INJ_FIRST, last + 1))
    R = raw(games, years)
    drafted, ry = draft(), rookie_years(range(N.INJ_FIRST - 6, last + 1))
    full = {y: ledger(y) for y in range(N.INJ_FIRST - 4, last + 1)}

    # provisional rate a snap: the group's backup rate (under 300 snaps), and draft slot for years 1-2, from seasons before y
    prov = {}
    for y in years:
        acc = defaultdict(lambda: [0.0, 0.0])
        xs, ys, ws, gs = [], [], [], []
        for z in range(N.INJ_FIRST - 4, y):
            for gsis, (war, g, sn, grp) in full[z].items():
                if 0 < sn < 300:
                    acc[grp][0] += war; acc[grp][1] += sn
                d = drafted.get(gsis)
                if sn >= 50 and d and 0 <= z - d[0] <= 1:
                    xs.append(math.log(d[1])); ys.append(war / sn); ws.append(sn); gs.append(grp)
        base = {k: v[0] / v[1] for k, v in acc.items() if v[1]}
        # slot slope on the rate over the group's backup rate
        r = np.array(ys) - np.array([base.get(k, 0.0) for k in gs]); x = np.array(xs); w = np.array(ws)
        X = np.column_stack([np.ones(len(x)), x])
        a, b = np.linalg.solve(X.T @ (X * w[:, None]), X.T @ (r * w))
        prov[y] = (base, float(a), float(b))
    print('provisional rates', {y: {k: round(v * 1000, 3) for k, v in prov[y][0].items()} for y in (2016, 2025)},
          {y: [round(prov[y][1] * 1000, 3), round(prov[y][2] * 1000, 3)] for y in (2016, 2025)}, '(WAR per 1000 snaps)')

    def prior_rate(gsis, grp, y):
        base, a, b = prov[y]
        p = base.get(grp, 0.0)
        d = drafted.get(gsis)
        if d and 0 <= y - d[0] <= 1:
            p += a + b * math.log(d[1])
        return p

    def cost(y, side, k, floor0):
        c = 0.0
        for gsis, stt, played, pv, cv, grp, bk, bp, bc in side:
            v = max((0.5 * pv[0] + cv[0]) / (0.5 * pv[1] + cv[1] + 3), 0.0)
            if k and bk and grp:
                spg = (0.5 * pv[2] + cv[2]) / max(1e-9, 0.5 * pv[1] + cv[1])      # the starter's snaps a game
                rate = (0.5 * bp[0] + bc[0] + k * prior_rate(bk, grp, y)) / (0.5 * bp[2] + bc[2] + k)
                vb = rate * spg
                v = v - (max(vb, 0.0) if floor0 else vb)
                v = max(v, 0.0) if floor0 else v
            c += (1 - N.play_prob(stt, played)) * v * N.PTS_PER_WIN
        return c

    variants = {'live': (0, True), 'k100': (100, False), 'k300': (300, False), 'k1000': (1000, False), 'k300net0': (300, True)}
    inj = {v: {} for v in variants}
    found = [0, 0]
    for y, gm in R.items():
        for gid, (h, a) in gm.items():
            for x in h + a:
                found[0] += 1; found[1] += x[6] is not None
            for v, (k, f0) in variants.items():
                inj[v][gid] = cost(y, a, k, f0) - cost(y, h, k, f0)
    print('listed players with a depth-chart backup:', found[1], 'of', found[0])
    _, data = N.walk(games, box, qbs, F['params'])
    D = [(g, x) for g, x, _ in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    S = np.array([int(g['season']) for g, _ in D])
    yv = np.array([N.num(g['result']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D])
    ok = ~np.isnan(line)
    A = (S >= 2017) & (S <= 2020) & ok; B = (S >= 2021) & ok
    base = [f for f in N.FEATS if f != 'inj']

    def wf(v):
        X = np.array([[x[f] for f in base] + [inj[v].get(g['game_id'], 0.0)] for g, x in D])
        pred = np.full(len(yv), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            pred[te] = X[te] @ np.linalg.lstsq(X[tr], yv[tr], rcond=None)[0]
        return np.abs(pred - yv), float(np.linalg.lstsq(X[S >= 2016], yv[S >= 2016], rcond=None)[0][-1])

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return {'d': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(k.sum()))), 2)}

    e0, c0 = wf('live')
    res = {'live': {'mae1720': round(float(e0[A].mean()), 4), 'mae2125': round(float(e0[B].mean()), 4), 'coef': round(c0, 3)},
           'backupFound': found}
    for v in list(variants)[1:]:
        e1, c1 = wf(v)
        r = {'mae1720': round(float(e1[A].mean()), 4), 'mae2125': round(float(e1[B].mean()), 4), 'coef': round(c1, 3),
             'd1720': cmp(e1, e0, A), 'd2125': cmp(e1, e0, B)}
        r['kept'] = r['d1720']['t'] <= -1.5 and r['d2125']['d'] <= 0
        res[v] = r
        print(v, r, flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
