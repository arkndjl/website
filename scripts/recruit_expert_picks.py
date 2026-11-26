# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""On3/Rivals expert picks for the uncommitted recruits of the live classes (scripts/data/recruit_on3_live.json.gz,
pulled daily by the recruit leans workflow) -> data/recruit_expert_picks.json, read by the CFB and CBB class tabs and
drawn on the recruit GFX card.
Each expert counts once, at his latest pick. Out: {sport: {class: {site row name: [school, k, n, espn id]}}}: the
school most experts pick (ties: higher summed confidence, then the more recent pick), k experts on it of n with a pick.
247 Crystal Balls are not here: 247 serves no feed a bot may read (see scripts/research/recruit_experts_nov19/)."""
import gzip, json, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402
from recruit_on3_join import LIVEP, slug_map, CACHE, TEAMS  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'recruit_expert_picks.json')


def leader(picks, smap, nm):
    last = {}
    for p in picks or []:
        d, org, ex, conf = p[0], p[1], p[2], p[3]
        if not org or org not in smap: continue
        if ex not in last or (d or '') >= (last[ex][0] or ''): last[ex] = (d, org, conf or 50)
    if not last: return None
    by = defaultdict(lambda: [0, 0, ''])
    for d, org, conf in last.values():
        b = by[smap[org]]; b[0] += 1; b[1] += conf; b[2] = max(b[2], d or '')
    t, (k, _, _) = max(by.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[1][2]))
    return [nm.get(t, t), k, len(last), t]


def site_rows(sp):
    """{year: [(name, state)]}: the rows the class tabs show (CFB future lists, CBB classes)"""
    f = os.path.join(ROOT, 'data', f'{sp}_recruits.json')
    if not os.path.exists(f): return {}
    d = json.load(open(f)); out = defaultdict(list)
    for g in (([{'year': d.get('next'), 'list': d.get('class', [])}] + d.get('future', [])) if sp == 'cfb' else d.get('classes', [])):
        for r in g.get('list', []):
            out[str(g['year'])].append((r['name'], (r.get('home') or '').split(', ')[-1]))
    return out


def main():
    if not os.path.exists(LIVEP): print('no', LIVEP); return
    live = json.load(gzip.open(LIVEP, 'rt')); out = {}
    for sp, years in live.items():
        smap = slug_map(sp)
        tj = json.load(open(os.path.join(CACHE, f'espn_teams_{TEAMS[sp]}.json')))
        nm = {str(t['team']['id']): t['team']['location'] for t in tj['sports'][0]['leagues'][0]['teams']}
        rows = site_rows(sp)
        for y, recs in years.items():
            got = [(r, leader(r.get('picks'), smap, nm)) for r in recs]
            got = [(r, L) for r, L in got if L]
            by = defaultdict(list)
            for r, L in got: by[names.key(r['name'])].append((r, L))
            for name, st in rows.get(y, []):
                cand = [c for c in by.get(names.key(name), []) if not st or not c[0].get('state') or c[0]['state'] == st]
                if not cand: cand = [c for c in got if (not st or c[0].get('state') == st) and names.same(c[0]['name'], name)]
                if len(cand) == 1: out.setdefault(sp, {}).setdefault(y, {})[name] = cand[0][1]
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), sort_keys=True)
    print('wrote', OUT, {sp: {y: len(v) for y, v in d.items()} for sp, d in out.items()})


if __name__ == '__main__':
    main()
