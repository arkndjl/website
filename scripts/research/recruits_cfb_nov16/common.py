# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Shared rows and statistics for the CFB recruit tests: the 2011-19 history (H), the 2020-21 lockbox (L, drafted and
draft capital only), school-clustered t, Holm."""
import math, os, pickle, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'recruits_nov14'))
import cfb_recruit_fit as R          # noqa: E402
import cfb_recruit_retarget as T     # noqa: E402
import rh                            # noqa: E402

PKL = os.path.join(R.CACHE, 'hist_nov16.pkl')
LPKL = os.path.join(R.CACHE, 'lock_nov16.pkl')
USE = {'on': ['grade', 'rank', 'size', 'level', 'elo', 'on3', 'svc', 'tm'], 'fv': ['grade', 'elo']}


def hist():
    data, how, cap = pickle.load(open(PKL, 'rb'))
    tms = [t for t in (R.commit_timing(r) for r in data) if t]
    R.TM_MEAN = [round(float(np.mean([t[0] for t in tms])), 3), round(float(np.mean([t[1] for t in tms])), 3)]
    return rh.prep(data), cap


def lock(cap):
    """the 2020 and 2021 classes linked to the 2023-26 drafts; outcome = drafted, pick, capital (H's capital line)"""
    if os.path.exists(LPKL): return rh.prep(pickle.load(open(LPKL, 'rb')))
    import csv
    a, b = cap
    def nfl():
        pe = {x['gsis_id']: x['espn_id'] for x in csv.DictReader(open(os.path.join(T.SP, 'players.csv'))) if x['gsis_id']}
        rows = []
        for r in csv.DictReader(open(os.path.join(T.SP, 'draft_picks.csv'))):
            s = int(r['season'])
            if 2014 <= s <= 2026 and int(r['pick'] or 0) > 0:
                rows.append({'name': r['pfr_player_name'], 'team': r['college'], 'pos': r['position'], 'season': s, 'espn': pe.get(r['gsis_id']) or None,
                             'pick': int(r['pick']), 'av': 0.0, 'cap': max(0.0, a + b * math.log(int(r['pick'])))})
        return rows, cap
    seen = {str(r['id'] or ('rid', r['rid'])) for r in pickle.load(open(PKL, 'rb'))[0]}
    keep = T.nfl, T.CLASSES
    T.nfl, T.CLASSES = nfl, range(2020, 2022)
    try: data, how, _ = T.dataset()
    finally: T.nfl, T.CLASSES = keep
    data = [r for r in data if str(r['id'] or ('rid', r['rid'])) not in seen]
    print('lockbox rows', len(data), 'drafted', sum(r['drafted'] for r in data), dict(how))
    pickle.dump(data, open(LPKL, 'wb'))
    return rh.prep(data)


def t_cluster(d, g):
    """mean of d over its SE clustered by g"""
    d = np.asarray(d, float); u = {}
    for x, k in zip(d - d.mean(), g): u[k] = u.get(k, 0.0) + x
    se = math.sqrt(sum(v * v for v in u.values())) / len(d) * math.sqrt(len(u) / (len(u) - 1))
    return float(d.mean() / se) if se else 0.0


def p_one(t): return 0.5 * math.erfc(t / math.sqrt(2))


def holm(ps, alpha=0.05):
    """{name: p} -> {name: passes}"""
    o = sorted(ps, key=ps.get); out, ok = {}, True
    for i, k in enumerate(o):
        ok = ok and ps[k] <= alpha / (len(o) - i); out[k] = ok
    return out


def by_class(d, cls):
    return {int(c): float(np.mean(d[cls == c])) for c in sorted(set(cls))}
