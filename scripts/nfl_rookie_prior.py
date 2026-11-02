#!/usr/bin/env python3
"""Rookie WAR-rate prior from draft slot (breakouts tab, Noah Nov 2 2026) -> data/nfl_rookie_prior.json.

    python3 scripts/nfl_rookie_prior.py      # fit + leave-one-season-out test (stdlib)

A rookie has no NFL history, so the projections' WAR rate prior (scripts/player_pctl.py) puts him at his group's
newcomer mean. Here: rate a snap = a[g] + b[g] x ln(pick), undrafted at pick UDFA, one line per group (QB RB WR TE OL DL
LB DB), weighted least squares on rookie seasons 2016-25 (the season's WAR / snaps from the board's whole-season rows, scripts/nfl_war.py board(),
weight 1 / (V0 + phi / snaps), V0 and phi the newcomer spread and noise from data/pctl_fit_nfl.json).
Rookie: drafted that season (nflverse draft_picks), or undrafted with no snaps the three seasons before.
Test: each season held out in turn, the weighted squared error of the season's rate against the draft line and
against the group mean (the current prior); t from the paired per-season differences. Ships if t <= -2 overall.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nfl_rookie_prior.json')
UDFA = 300
GROUPS = ('QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB')
YEARS = range(2016, 2026)


def seasons():
    """{season: {pfr id: {'e': snaps, 'grp', 'x': {'war'}}}} from the board's whole-season rows, 2013-25 (cached)"""
    import nfl_war as W
    fn = os.path.join(HERE, '.cache', 'nfl', 'rookie_prior_seasons.json')
    if os.path.exists(fn):
        return {int(k): v for k, v in json.load(open(fn)).items()}
    H = {}
    for y in range(YEARS[0] - 3, YEARS[-1] + 1):
        out, _, _ = W.board(y)
        H[y] = {p['id']: {'e': p['sn'], 'grp': p['_g'], 'x': {'war': p['_war']}} for p in out}
        print('season', y, len(H[y]), flush=True)
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    json.dump(H, open(fn, 'w'))
    return H


def data():
    import nfl_war as W
    import player_pctl as P
    H = seasons()
    fit = json.load(open(P.FIT.format('nfl')))['rates']['war']
    pick = {}
    for r in W.rows(W.get('draft_picks.csv', W.REL + '/draft_picks/draft_picks.csv')):
        if r['pfr_player_id'] and r['pick'].isdigit():
            pick[r['pfr_player_id']] = (int(r['season']), int(r['pick']))
    rows = []
    for y in YEARS:
        for pid, h in H.get(y, {}).items():
            e, war, g = h['e'], h['x'].get('war'), h['grp']
            if not e or e <= 0 or war is None or g not in GROUPS:
                continue
            if pid in pick:
                if pick[pid][0] != y:
                    continue
                pk = pick[pid][1]
            elif any(pid in H.get(s, {}) for s in (y - 1, y - 2, y - 3)):
                continue
            else:
                pk = UDFA
            V0, phi = fit['var'].get(g + ':n') or fit['var']['all:n']
            if phi <= 0:
                phi = fit['var']['all:n'][1]
            rows.append({'y': y, 'g': g, 'pk': pk, 'r': war / e, 'w': 1 / (V0 + phi / e), 'mu': fit['mu'].get(g + ':n', 0.0)})
    return rows


def wls(rs):
    sw = sum(r['w'] for r in rs); sx = sum(r['w'] * math.log(r['pk']) for r in rs); sy = sum(r['w'] * r['r'] for r in rs)
    sxx = sum(r['w'] * math.log(r['pk']) ** 2 for r in rs); sxy = sum(r['w'] * math.log(r['pk']) * r['r'] for r in rs)
    d = sw * sxx - sx * sx
    b = (sw * sxy - sx * sy) / d if d else 0.0
    return (sy - b * sx) / sw, b


def main():
    rows = data()
    per = []   # per held-out season: (sum w e_draft^2, sum w e_mean^2, n)
    by_g = {g: [0.0, 0.0, 0] for g in GROUPS}
    for y in YEARS:
        tr = [r for r in rows if r['y'] != y]
        co = {g: wls([r for r in tr if r['g'] == g]) for g in GROUPS}
        te = [r for r in rows if r['y'] == y]
        sd = sm = 0.0
        for r in te:
            a, b = co[r['g']]
            ed = r['w'] * (r['r'] - (a + b * math.log(r['pk']))) ** 2
            em = r['w'] * (r['r'] - r['mu']) ** 2
            sd += ed; sm += em
            by_g[r['g']][0] += ed; by_g[r['g']][1] += em; by_g[r['g']][2] += 1
        per.append((y, sd, sm, len(te)))
    diffs = [(sd - sm) / n for _, sd, sm, n in per]
    m = sum(diffs) / len(diffs)
    s = math.sqrt(sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1))
    t = m / (s / math.sqrt(len(diffs)))
    tot_d = sum(p[1] for p in per); tot_m = sum(p[2] for p in per)
    co = {g: wls([r for r in rows if r['g'] == g]) for g in GROUPS}
    out = {'udfa': UDFA, 'years': [YEARS[0], YEARS[-1]], 'n': len(rows),
           'coef': {g: [round(a, 7), round(b, 8)] for g, (a, b) in co.items()},
           'test': {'t': round(t, 2), 'err_ratio': round(tot_d / tot_m, 4),
                    'seasons': [{'y': y, 'draft': round(sd, 1), 'mean': round(sm, 1), 'n': n} for y, sd, sm, n in per],
                    'groups': {g: {'ratio': round(v[0] / v[1], 3) if v[1] else None, 'n': v[2]} for g, v in by_g.items()}},
           'ship': t <= -2}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: out[k] for k in ('n', 'coef', 'ship')}), json.dumps(out['test']['groups']), 't', out['test']['t'], 'ratio', out['test']['err_ratio'])


if __name__ == '__main__':
    main()
