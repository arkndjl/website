#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research: does the NBA board's projected XPM (3Y) set the basketball FV cut points better than realized careers alone?

    python3 scripts/cbb_careers_kit.py              # scripts/.cache/cbb/careers.json
    python3 scripts/cbb_scale_proj_research.py      # prints the test, writes project files fv/xpm-scale-nov16/results.json

Pre-registered in project files fv/xpm-scale-nov16/prereg.md. Live cuts (cbb_fit.xpm_scale): FV t starts at the peak
XPM reached by as many 2008-16 college careers as reached role tier t. Candidates add later classes whose peak is
realized seasons plus three future seasons at the player's 3Y projection (static/data/nba-proj.json p3, bbref id).
Leave one mature class out; score rarity (careers at the cut or better vs careers at the role tier or better) and
per-career tier agreement on the held-out class."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
from cbb_link import TIERS

ROOT = D.ROOT
MATURE = list(range(2008, 2017))
TS = [t for t, _, _ in TIERS if t != F.FLOOR]
OUT = os.environ.get('XS_OUT', '/mnt/project-files/fv/xpm-scale-nov16/results.json')


def proj_map():
    p = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-proj.json')))
    return {x['id']: x['p3'] for x in p['players'] if x.get('p3') is not None}


def peak(c, P, use_proj):
    n = c['nba']
    if n['games'] < 1: return None
    xs = [x for _, x in n.get('xs', [])]
    if use_proj and n.get('bref') in P: xs += [P[n['bref']]] * 3
    if not xs: return n['peakXpm']
    v = sorted(xs, reverse=True) + [-2.5] * 3
    return round(sum(v[:3]) / 3, 2)


def cuts(mature, extra, P, use_proj):
    """the cut for tier t: order statistic at rank = per-class role rate (mature classes) x classes in the pool"""
    rate = {t: sum(1 for c in mature if c['nba']['fv'] >= t) / len({c['last'] for c in mature}) for t in TS}
    ncls = len({c['last'] for c in mature}) + len({c['last'] for c in extra})
    vals = sorted([c['nba']['peakXpm'] for c in mature if c['nba']['games'] >= 1 and c['nba']['peakXpm'] is not None] +
                  [x for x in (peak(c, P, use_proj) for c in extra) if x is not None], reverse=True)
    out = {}
    for t in TS:
        k = rate[t] * ncls                      # fractional rank: interpolate between neighbours
        i = max(1.0, min(k, len(vals)))
        lo = int(math.floor(i)); hi = min(lo + 1, len(vals)); w = i - lo
        out[t] = round(vals[lo - 1] * (1 - w) + vals[hi - 1] * w, 3)
    # keep the cuts monotone
    for a, b in zip(TS[1:], TS[:-1]):
        if out[a] >= out[b]: out[a] = out[b] - 0.01
    return out


def fv_of(x, thr):
    if x is None: return float(F.FLOOR)
    ts = sorted(thr)
    return float(np.interp(x, [thr[t] for t in ts], ts)) if x >= thr[min(ts)] else 20.0 + 10.0 * max(0.0, 1 - (thr[30] - x) / 2)


def tier(y):
    return max([t for t in [20] + TS if y >= t - 1e-9] or [20])


def score(held, thr):
    R = 0.0; per = []
    nb = [c for c in held if c['nba']['games'] >= 1 and c['nba']['peakXpm'] is not None]
    for t in TS:
        if t < 35: continue
        R += (sum(1 for c in nb if c['nba']['peakXpm'] >= thr[t]) - sum(1 for c in held if c['nba']['fv'] >= t)) ** 2
    for c in nb:
        per.append(abs(tier(fv_of(c['nba']['peakXpm'], thr)) - c['nba']['fv']))
    return R, per


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    P = proj_map()
    by = defaultdict(list)
    for c in careers: by[c['last']].append(c)
    live = F.xpm_scale(careers)
    cand = {'A': ([], False), 'S0': (range(2017, 2021), False), 'S1': (range(2017, 2021), True), 'S2': (range(2017, 2023), True)}
    full = {k: cuts([c for y in MATURE for c in by[y]], [c for y in ex for c in by[y]], P, pr) for k, (ex, pr) in cand.items()}
    print('live cuts      ', live)
    for k, v in full.items(): print(f'{k:3} full-pool cuts', v)
    res = {k: {'R': [], 'T': []} for k in cand}
    for h in MATURE:
        tr = [c for y in MATURE if y != h for c in by[y]]
        for k, (ex, pr) in cand.items():
            thr = cuts(tr, [c for y in ex for c in by[y]], P, pr)
            R, per = score(by[h], thr)
            res[k]['R'].append(R); res[k]['T'].append(per)
    out = {'live': live, 'full': full, 'folds': MATURE, 'tests': {}}
    a = res['A']
    for k in cand:
        r = res[k]
        Ta = np.concatenate([np.array(x) for x in a['T']]); Tk = np.concatenate([np.array(x) for x in r['T']])
        d = Tk - Ta
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() > 0 else 0.0
        wins = sum(1 for x, y in zip(r['R'], a['R']) if x < y); ties = sum(1 for x, y in zip(r['R'], a['R']) if x == y)
        out['tests'][k] = {'R_total': round(sum(r['R']), 1), 'R_by_class': r['R'], 'R_wins': wins, 'R_ties': ties,
                           'T_mean': round(float(Tk.mean()), 3), 'T_t_vs_A': round(t, 2), 'n_careers': int(len(Tk))}
        print(f"{k:3} R {sum(r['R']):7.1f} by class {r['R']}  wins {wins}/9 (ties {ties})  T {Tk.mean():.3f}  t vs A {t:+.2f}")
    s = out['tests']['S1']; A = out['tests']['A']
    out['pass'] = bool(s['R_total'] < A['R_total'] and s['R_wins'] >= 6 and s['T_t_vs_A'] <= -2)
    print('S1 passes' if out['pass'] else 'S1 fails')
    # how today's NBA board 3Y sits on the live cuts (display check)
    p3 = np.array(list(P.values()))
    out['board3y_counts'] = {t: int((p3 >= live[t]).sum()) for t in TS}
    print('NBA board players at or above each live cut on 3Y:', out['board3y_counts'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
