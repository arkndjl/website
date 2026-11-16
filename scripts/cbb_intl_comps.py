#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Historical comps for the internationals on the College Basketball ARKBOARD: each international's nearest draft-day
profiles among the 2009-20 internationals (277) on ESPN's or NBADraft.net's final boards (scripts/cbb_intl.py's training
rows, scripts/data/cbb_intl_draftday.json.gz), with what they did in the NBA. Display only, like the D-I comps
(scripts/cbb_comps.py): it does not move FV.

Profile, all as of the draft (point in time): June consensus board rank (log), the international model's E[FV] from
his draft-season inputs (board rank, league-adjusted production, minutes and level, age, size), out of fold, and position group. A live player enters with the June rank his current board rank predicts (the
model's 'draft board rank' input) and his E[FV]. Weights: rank 2, E[FV] 2, position .5; z-scored on the pool.
The mix is his 50 nearest; the three shown are his nearest who reached the NBA among his 120
nearest.

    python3 scripts/cbb_intl_comps.py --pool   # scripts/data/cbb_intl_comps_pool.json (needs the ESPN pick file)
    python3 scripts/cbb_intl_comps.py          # static/data/cbb-comps-intl.json from static/data/cbb-intl.json
"""
import csv, gzip, json, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFTDAY = os.path.join(ROOT, 'scripts', 'data', 'cbb_intl_draftday.json.gz')
PICKS = os.environ.get('CBB_PICKS', '/mnt/project-files/cbb/boards/espn_picks.csv')
POOL = os.path.join(ROOT, 'scripts', 'data', 'cbb_intl_comps_pool.json')
LIVE = os.path.join(ROOT, 'static', 'data', 'cbb-intl.json')
OUT = os.path.join(ROOT, 'static', 'data', 'cbb-comps-intl.json')
K, NEAR = 50, 120
W = {'lr': 2.0, 'e': 2.0, 'g': 0.5, 'f': 0.5, 'c': 0.5}
COLS = ['name', 'team', 'season', 'cls', 'fv', 'role', 'pick', 'draft']


def role_of(fv):
    return 'no NBA' if fv < 30 else 'bench' if fv < 40 else 'rotation' if fv < 50 else 'starter' if fv < 60 else 'All-Star'


def pos_group(p):
    p = (p or '').upper()
    return 'c' if p.startswith('C') else 'g' if p.endswith('G') or p == 'G' else 'f'


def vec(lr, e, pos):
    g = pos_group(pos)
    return [lr, e, 1.0 if g == 'g' else 0.0, 1.0 if g == 'f' else 0.0, 1.0 if g == 'c' else 0.0]


def build_pool():
    rows = json.load(gzip.open(DRAFTDAY))['rows']
    picks, byyear = {}, {}
    for r in csv.DictReader(open(PICKS)):
        if r.get('slot_pick'):
            picks[(N.key(r['name']), int(r['draft_year']))] = int(r['slot_pick']); byyear.setdefault(int(r['draft_year']), []).append(r)

    def pick_of(name, y):
        if (N.key(name), y) in picks: return picks[(N.key(name), y)]
        hits = [r for r in byyear.get(y, []) if N.same(name, r['name'])]   # a source's spelling (Beverly / Beverley)
        return int(hits[0]['slot_pick']) if len(hits) == 1 else None
    out = []
    for r in rows:
        if not r.get('oof'): continue   # 2021+ drafts: careers still open and E[FV] in sample
        y = int(r['year']); fv = round(float(r['y']), 1)
        out.append({'row': [r['name'], r['club'] if r['club'] and r['club'] != '0' else '', y, '', fv, role_of(fv), pick_of(r['name'], y), y],
                    'x': vec(-math.log(max(1.0, float(r['june']))), float(r['e']), r['pos'])})
    json.dump({'note': 'cbb_intl_comps.py --pool', 'cols': COLS, 'rows': out}, open(POOL, 'w'), separators=(',', ':'))
    print(f'pool: {len(out)} rows, {sum(1 for o in out if o["row"][4] >= 30)} reached the NBA, {sum(1 for o in out if o["row"][6])} drafted')


def live_rows():
    d = json.load(open(LIVE)); C = d['cols']
    for a in d['rows']:
        r = dict(zip(C, a))
        lr = next((p[2] for p in (r.get('parts') or []) if p and p[0] == 'draft board rank' and len(p) > 2), None)
        if lr is None and r.get('cons'): lr = -math.log(max(1.0, float(r['cons'])))
        if lr is None or r.get('e') is None: continue
        yield r['name'] + '|' + r['team'], vec(float(lr), float(r['e']), r.get('pos'))


def write():
    pool = json.load(open(POOL))
    X = np.array([p['x'] for p in pool['rows']], float)
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
    w = np.array([W[k] for k in ('lr', 'e', 'g', 'f', 'c')])
    Z = (X - mu) / sd * w
    fv = np.array([p['row'][4] for p in pool['rows']])
    players = {}
    for key, x in live_rows():
        z = (np.array(x) - mu) / sd * w
        dist = np.sqrt(((Z - z) ** 2).sum(1)); order = np.argsort(dist, kind='stable')
        seen, uniq = set(), []
        for i in order:   # a player is one comp (his nearest draft year)
            nk = N.key(pool['rows'][i]['row'][0])
            if nk in seen: continue
            seen.add(nk); uniq.append(int(i))
        mix = uniq[:K]; near = [i for i in uniq[:NEAR] if fv[i] >= 30][:3]
        players[key] = [[i, round(float(dist[i]), 2)] for i in near] + [[len(mix), round(float((fv[mix] >= 30).mean()), 3),
                                                                           round(float((fv[mix] >= 45).mean()), 3), round(float((fv[mix] >= 60).mean()), 3)]]
    json.dump({'cols': COLS, 'k': K, 'pool': [p['row'] for p in pool['rows']], 'players': players}, open(OUT, 'w'), separators=(',', ':'))
    print(f'{OUT}: {len(players)} players')


if __name__ == '__main__':
    build_pool() if '--pool' in sys.argv else write()
