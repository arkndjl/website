#!/usr/bin/env python3
"""Rebuild scripts/.cache/cbb/careers.json (what cbb_link.py writes) from the research kit in /mnt/project-files/cbb/kit,
for a container where 247 Sports refuses the pull: Barttorvik seasons joined to NBA careers, On3/247 grades, DPM.
The rebuild reproduces data/cbb_fit.json (drivers, cuts, shrink) exactly.  python3 scripts/cbb_careers_kit.py"""

import csv, json, os, sys, glob
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
from cbb_link import tier
K = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit')
car = {}
with open(f'{K}/college_seasons_nba.csv', newline='', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        s = {k: (r[k] if k in D.BT_TEXT else D.num(r[k])) for k in D.BT_COLS if k in r and k not in ('home', 'num')}
        for k in D.BT_COLS:
            if k not in s and k not in ('home', 'num'): s[k] = None
        s['year'] = int(r['year']); s['hti'] = D.num(r['hti']); s['dob'] = r['dob'] or None
        c = car.setdefault(r['pid'], {'pid': r['pid'], 'name': r['name'], 'seasons': [], 'row': r})
        c['seasons'].append(s); c['name'] = r['name']; c['row'] = r
nba = defaultdict(list)
for s in json.load(open(f'{K}/bbref_nba_seasons.json')): nba[s['bref']].append(s)
by_ns = {}
for b, ss in nba.items():
    for x in ss: by_ns[(D.norm(x['name']), x['year'])] = b
dpm = defaultdict(list)
for p in glob.glob(f'{K}/dpm/*.json'):
    for x in json.load(open(p)):
        b = by_ns.get((D.norm(x['name']), x['season']))
        if b: dpm[b].append(x)
SEASON_G = {2012: 66, 2020: 72, 2021: 72}   # cbb_link's shortened seasons
import cbb_link
SEASON_G = getattr(cbb_link, 'SEASON_G', SEASON_G)
out = []
for c in car.values():
    c['seasons'].sort(key=lambda s: s['year']); r = c['row']
    b = r['nba_bref'] or None
    ss = nba.get(b, []) if b else []
    o = {'bref': b, 'draft': int(float(r['nba_draft'])) if r['nba_draft'] else None, 'pick': int(float(r['nba_pick'])) if r['nba_pick'] else None,
         'allnba': int(float(r['allnba'] or 0)), 'allstar': int(float(r['allstar'] or 0)), 'games': sum(s['g'] for s in ss), 'starts': 0, 'rot': 0, 'nba_seasons': len(ss)}
    vals = []
    for s in ss:
        G = SEASON_G.get(s['year'], 82)
        if s['gs'] >= 0.5 * G: o['starts'] += 1
        if s['mp'] >= 1000 * G / 82: o['rot'] += 1
        if s['bpm'] is not None: vals.append((s['mp'] * s['bpm'] + 500 * -2.0) / (s['mp'] + 500))
    vals.sort(reverse=True); vals += [-2.5] * 3
    o['peak'] = round(sum(vals[:3]) / 3, 2) if ss else None
    dv = sorted(((x['min'] * x['dpm'] + 500 * -2.0) / (x['min'] + 500) for x in dpm.get(b, [])), reverse=True) + [-2.5] * 3
    o['peakDpm'] = round(sum(dv[:3]) / 3, 2) if b and dpm.get(b) else None
    dy_ = {x['season']: x['dpm'] for x in dpm.get(b, [])}
    xv = sorted(((s['mp'] * (0.5 * s['bpm'] + 0.5 * dy_[s['year']] if s['year'] in dy_ else s['bpm']) + 500 * -2.0) / (s['mp'] + 500)
                 for s in ss if s['bpm'] is not None), reverse=True) + [-2.5] * 3
    o['peakXpm'] = round(sum(xv[:3]) / 3, 2) if ss else None
    o['fv'], o['role'] = tier(o)
    rec = None
    if any(r[k] for k in ('on3', 'on3rk', 'r247', 'rk247')):
        rec = {k: D.num(r[k]) for k in ('on3', 'on3rk', 'r247', 'rk247') if r[k]}
        for k in ('on3rk', 'rk247'):
            if k in rec: rec[k] = int(rec[k])
        if r['rec_class']: rec['cls'] = int(float(r['rec_class']))
    dob = next((s['dob'] for s in reversed(c['seasons']) if s['dob']), None)
    out.append({'pid': c['pid'], 'name': c['name'], 'first': c['seasons'][0]['year'], 'last': c['seasons'][-1]['year'], 'dob': dob, 'nba': o, 'rec': rec, 'seasons': c['seasons']})
os.makedirs(D.CACHE, exist_ok=True)
json.dump(out, open(os.path.join(D.CACHE, 'careers.json'), 'w'))
print(len(out), 'careers;', sum(1 for c in out if c['nba']['games']), 'NBA;', sum(1 for c in out if c['rec']), 'with grades')
