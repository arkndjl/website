#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Coach loyalty, recruit leans (prereg.md R1-R4): coach terms on top of the live LIST model, walk-forward by class,
NIL-era classes 2022-26 scored.

    python3 scripts/research/coach_loyalty_nov27/recruits.py [cfb|cbb]   # -> results_recruits_<sport>.json here
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as N  # noqa: E402
import recruit_commit_fit as C  # noqa: E402

NEW = ['newhc', 'hc_ten', 'hc_from', 'late']
SCORED = range(2022, 2027)


POSW = {'running back', 'defensive end', 'quarterback', 'cornerback', 'linebacker', 'offensive line', 'offensive tackle', 'wide receiver', 'safety', 'tight end',
        'defensive tackle', 'defensive back', 'int', 'interim', 'center', 'guard', 'fullback', 'halfback', 'defensive line', 'tbd', 'vacant'}


def ck(n):
    """coach name key: the disambiguator ("(American football)") off, position words and placeholders dropped"""
    import re
    k = N.key(re.sub(r'\s*\(.*?\)', '', n or ''))
    return None if (not k or k in POSW or len(k.split()) < 2) else k


def keys(v):
    return [k for k in (ck(n) for n in v or []) if k]


def clean(staff):
    """staff: {season: {tid: {'hc': [names], 'oc': [...], 'dc': [...]}}} -> the season-start head coach by continuity
    (the name also there the season before, else the one there the season after, else the first listed)"""
    out = defaultdict(dict)
    ys = sorted(staff)
    for y in ys:
        for t, v in staff[y].items():
            hc = keys(v.get('hc'))
            if not hc: continue
            prev = keys((staff.get(y - 1, {}).get(t) or {}).get('hc'))
            nxt = keys((staff.get(y + 1, {}).get(t) or {}).get('hc'))
            pick = next((n for n in hc if n in prev), None) or next((n for n in hc if n in nxt), None) or hc[0]
            out[y][t] = {'hc': pick, 'co': set(keys((v.get('oc') or []) + (v.get('dc') or [])))}
    return out


def cfb_staff():
    """FBS 2014-25 from the all-time coach file, then every FBS/FCS team 2021-26 from the season infoboxes"""
    d = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'coach_alltime_src.json.gz')))['cfb']
    camp = json.load(open(os.path.join(ROOT, 'scripts', 'geo', 'recruit_campus.json')))['cfb']
    alias = {'appalachianstate': 'appstate', 'louisianamonroe': 'ulmonroe', 'miamiohio': 'miamioh', 'middletennesseestate': 'middletennessee',
             'samhoustonstate': 'samhouston', 'southernmississippi': 'southernmiss'}
    ck = {}
    for t, v in camp.items():
        if v and v.get('name'): ck.setdefault(N.team_key(v['name']), t)
    staff = defaultdict(dict)
    for r in d['rows']:
        if r['y'] < 2013: continue
        k = N.team_key(d['teams'][r['t']]); tid = ck.get(k) or ck.get(alias.get(k))
        if tid: staff[r['y']][tid] = {'hc': [c[0] for c in r['cs'] if len(c[0].split()) >= 2], 'oc': r.get('oc') or [], 'dc': r.get('dc') or []}
    f = os.path.join(ROOT, 'scripts', 'data', 'cfb_staff_hist.json')
    if os.path.exists(f):
        for y, T in json.load(open(f)).items():
            for t, v in T.items(): staff[int(y)][t] = v
    return clean(staff)


def cbb_staff():
    import cbb_market_fit as M
    TS, _ = M.team_seasons(); raw, _ = M.coaches()
    out = defaultdict(dict)
    for y, T in raw.items():
        for t, v in T.items():
            i = (TS.get((y, t)) or TS.get((y - 1, t)) or TS.get((y + 1, t)) or {}).get('id')
            if i: out[y][str(i)] = {'hc': v['coach'], 'co': set()}
    return out


def coach_terms(st, s, t, lst):
    """st cleaned staff; s the season whose coach is in place when the class signs"""
    a, b, c = st.get(s, {}).get(t), st.get(s - 1, {}).get(t), st.get(s + 1, {}).get(t)
    if not a: return [0.0, 0.0, 0.0, 0.0]
    hc = a['hc']
    ten = 1
    while st.get(s - ten, {}).get(t, {}).get('hc') == hc: ten += 1
    new = float(bool(b) and b['hc'] != hc)
    frm = 0.0
    if new:
        for k in lst:
            p = st.get(s - 1, {}).get(k)
            if k != t and p and (p['hc'] == hc or hc in p['co']): frm = 1.0
    return [new, math.log1p(min(ten, 10)) - 1.4, frm, float(bool(c) and c['hc'] != hc)]


def main(sp):
    st = cfb_staff() if sp == 'cfb' else cbb_staff()
    print(sp, 'staff seasons', {y: len(v) for y, v in sorted(st.items())}, flush=True)
    off = -1 if sp == 'cfb' else 0
    base_feats = C.feats
    YEAR = {}

    def feats(x, alts, s_, loc):
        F = base_feats(x, alts, s_, loc)
        y = YEAR[id(x)]
        return np.c_[F, np.array([coach_terms(st, y + off, t, x['list']) for t in alts])]
    C.feats = feats
    C.COLS = C.COLS + NEW
    loc, cls = C.load(sp)
    for y, rows in cls.items():
        for x in rows: YEAR[id(x)] = y
    spec = json.load(open(C.OUT))[sp]['list']
    kept = spec['kept'] + [c for c in C.EXTRA.get(sp, {}).get('list', []) if c not in spec['kept']]
    dec = C.DECAY.get(sp, {}).get('list')
    start = C.YEARS[sp][0] + 3
    specs = {'base': kept, 'R1 newhc': kept + ['newhc'], 'R2 hc_ten': kept + ['hc_ten'], 'R3 hc_from_list': kept + ['hc_from'], 'R4 late': kept + ['late'],
             'R1+R3': kept + ['newhc', 'hc_from']}
    res = {k: defaultdict(list) for k in specs}; coef = defaultdict(list); expo = defaultdict(list)
    for y in SCORED:
        Xt, yt, mt = C.build(sp, loc, cls, range(start, y), 'list', True); Xh, yh, _ = C.build(sp, loc, cls, [y], 'list', False)
        w = [dec ** (y - 1 - m[0]) for m in mt] if dec else None
        for k, cols in specs.items():
            m = C.fit(Xt, yt, cols, w=w); ll, br, t1, t3 = C.score(m, Xh, yh)
            for key, v in (('ll', ll), ('br', br), ('t1', t1), ('t3', t3)): res[k][key].append(v)
            res[k]['yr'].append(np.full(len(ll), y))
            if k != 'base': coef[k].append([round(float(v), 3) for v in m['b'][len(kept):]])
        for j, nm in enumerate(NEW):
            i = len(C.COLS) - len(NEW) + j
            has = [F[:, i].max() > 0 if nm != 'hc_ten' else True for F in Xh]
            took = [F[c, i] > 0 for F, c in zip(Xh, yh)]
            share = [F[:, i].mean() if nm != 'hc_ten' else 0 for F in Xh]
            expo[nm].append([int(y), int(np.sum(has)), int(np.sum(np.array(took) & np.array(has))), round(float(np.sum(share)), 1)])
        print(sp, y, len(yh), {k: round(float(np.mean(res[k]['ll'][-1])), 4) for k in res}, flush=True)
    res = {k: {kk: np.concatenate(v) for kk, v in d.items()} for k, d in res.items()}
    out = {'base': C.summ(res['base']), 'cols': kept, 'exposure': {k: v for k, v in expo.items()},
           'exposureNote': 'per class: [class, recruits with the flag on a listed school, of them chose a flagged school, expected by listed share]'}
    for k in specs:
        if k == 'base': continue
        g = C.gate(res['base'], res[k]); g['with'] = C.summ(res[k]); g['coef'] = coef[k]; out[k] = g
        print(k, {a: (round(b, 5) if isinstance(b, float) else b) for a, b in g.items() if a not in ('with',)}, flush=True)
    json.dump(out, open(os.path.join(HERE, f'results_recruits_{sp}.json'), 'w'), indent=1)


if __name__ == '__main__':
    for sp in ([a for a in sys.argv[1:] if a in ('cfb', 'cbb')] or ['cbb', 'cfb']): main(sp)
