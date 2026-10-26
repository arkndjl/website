#!/usr/bin/env python3
"""1NT round-spread research (Oct 26 2026): should the preview's round spread treat rounds as coin flips?

    python3 scripts/esea_spread_research.py   # reads research/esea_matches.json.gz and data/esea.json history;
                                               # writes data/esea_spread_research.json

The spread is the round differential of a Bo1 map. Candidates, both matched to the same map win chance p:
  iid   one per-round chance q for the whole map (the page's spread() until Oct 26)
  mix   q varies map to map, logit(q) = logit(q0) + tau z (esea_totals_research.py), tau fitted on the
        training days
Strength input p: walk-forward round-share Elo on all 1,719 S58-S59 maps, and the page's own FACEIT elo
(600 scale) on S59 maps (data/esea.json git history). Leave-one-match-day-out. Scoring: log score of the
exact margin (OT margins are 1-4, scored exactly), and log loss on cover at the line the iid model would hang
(the live line until now), plus how often each model's own favourite covers its own line.
"""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esea_research import Elo, load, snapshots  # noqa: E402
from esea_totals_research import GH, blog, ex, lg, tstat  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'esea_spread_research.json')


def race_margin(q):
    """distribution of the map's round margin (f1 - f2) for per-round chance q; OT wins are +-2..4"""
    g = {(0, 0): 1.0}
    out = defaultdict(float)
    ot = 0.0
    for t in range(24):
        ng = defaultdict(float)
        for (a, b), p in g.items():
            for na, nb, pr in ((a + 1, b, p * q), (a, b + 1, p * (1 - q))):
                if na == 13:
                    out[13 - nb] += pr
                elif nb == 13:
                    out[na - 13] += pr
                elif na == 12 and nb == 12:
                    ot += pr
                else:
                    ng[(na, nb)] += pr
        g = ng
    # MR3: first to 4 of 6, 3-3 repeats; the final margin is the last period's (4-j)
    per = defaultdict(float)
    h = {(0, 0): 1.0}
    for _ in range(6):
        nh = defaultdict(float)
        for (a, b), p in h.items():
            for na, nb, pr in ((a + 1, b, p * q), (a, b + 1, p * (1 - q))):
                if na == 4:
                    per[4 - nb] += pr
                elif nb == 4:
                    per[na - 4] += pr
                else:
                    nh[(na, nb)] += pr
        h = nh
    tie = h.get((3, 3), 0.0)
    tot = sum(per.values())
    for m, p in per.items():
        out[m] += ot * p / tot   # geometric over repeated periods: same conditional margin
    return dict(out)


_rc = {}


def rm(q):
    k = round(min(.97, max(.03, q)), 4)
    if k not in _rc:
        _rc[k] = race_margin(k)
    return _rc[k]


def mix(q0, tau):
    out = defaultdict(float)
    for z, w in GH:
        for m, p in rm(ex(lg(q0) + tau * z)).items():
            out[m] += w * p
    return out


def win(d):
    return sum(p for m, p in d.items() if m > 0)


_dc = {}


def dist(p, tau):
    """margin distribution (f1 side) with map win chance p; cached on a .01 grid"""
    k = (round(min(.97, max(.03, p)), 2), tau)
    if k not in _dc:
        lo, hi = 0.03, 0.97
        for _ in range(24):
            m = (lo + hi) / 2
            (lo, hi) = (m, hi) if win(mix(m, tau)) < k[0] else (lo, m)
        _dc[k] = dict(mix((lo + hi) / 2, tau))
    return _dc[k]


def logscore(d, m):
    return -math.log(max(d.get(m, 0.0), 1e-6))


def line_of(d):
    """the page's rule: the half-point hook on the favourite's side where the cover is closest to 50%"""
    ed = sum(m * p for m, p in d.items())
    side = 1 if ed >= 0 else -1
    best = None
    for L in [x + 0.5 for x in range(14)]:
        c = sum(p for m, p in d.items() if m * side > L)
        if best is None or abs(c - .5) < abs(best[2] - .5):
            best = (side, L, c)
    return best


def cover(d, side, L):
    return sum(p for m, p in d.items() if m * side > L)


def evaluate(rows, key, taus):
    days = sorted({r['day'] for r in rows})
    for r in rows:
        r['_ls'] = {t: logscore(dist(r[key], t), r['margin']) for t in taus}
    res = {'iid': {'ls': [], 'cl': [], 'own': []}, 'mix': {'ls': [], 'cl': [], 'own': []}}
    chosen = []
    for dd in days:
        tr = [r for r in rows if r['day'] != dd]
        tau = min(taus[1:], key=lambda t: sum(r['_ls'][t] for r in tr))
        chosen.append(tau)
        for r in rows:
            if r['day'] != dd:
                continue
            di, dm = dist(r[key], 0.0), dist(r[key], tau)
            side, L, _ = line_of(di)   # the live (iid) line
            y = r['margin'] * side > L
            for name, d in (('iid', di), ('mix', dm)):
                res[name]['ls'].append(r['_ls'][0.0 if name == 'iid' else tau])
                res[name]['cl'].append(blog(cover(d, side, L), y))
                s2, L2, _ = line_of(d)
                res[name]['own'].append(r['margin'] * s2 > L2)
    n = len(res['iid']['ls'])
    out = {'n': n, 'tau_chosen': sorted(set(chosen))}
    for name in res:
        out[name] = {'logscore': round(sum(res[name]['ls']) / n, 4), 'cover_logloss_live_line': round(sum(res[name]['cl']) / n, 4),
                     'own_line_cover': round(sum(res[name]['own']) / n, 3)}
    out['mix_vs_iid'] = {m: tstat([a - b for a, b in zip(res['mix'][m], res['iid'][m])]) for m in ('ls', 'cl')}
    return out


def main():
    d, ms = load()
    relo = Elo(K=96, carry=0.0, margin=True, div_gap=0)
    rows = []
    for m in ms:
        p = relo.predict(m)
        relo.update(m)
        mp = (m.get('maps') or [None])[0]
        if not mp or mp.get('s1') is None or mp.get('s2') is None:
            continue
        rows.append({'id': m['id'], 'day': m['at'] // 86400, 'at': m['at'], 'season': m['season'], 'p': p,
                     't1': m['f1']['id'], 't2': m['f2']['id'], 'margin': mp['s1'] - mp['s2']})
    taus = [0.0, 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8]
    res = {'maps': len(rows)}
    res['relo_all'] = evaluate(rows, 'p', taus)
    snaps = snapshots()
    s59 = []
    for r in rows:
        if r['season'] != 59:
            continue
        prior = [s for s in snaps if s[0] < r['at'] - 60]
        if not prior:
            continue
        a, b = prior[-1][1].get(r['t1']), prior[-1][1].get(r['t2'])
        if a and b and a.get('elo') and b.get('elo'):
            s59.append({**r, 'pe': 1 / (1 + 10 ** (-(a['elo'] - b['elo']) / 600))})
    res['elo_s59'] = evaluate(s59, 'pe', taus)
    # what the change does to a typical line
    res['lines'] = []
    for p in (0.55, 0.6, 0.7, 0.8):
        li, lm = line_of(dist(p, 0.0)), line_of(dist(p, 0.55))
        res['lines'].append({'p': p, 'iid_line': li[1], 'iid_cover': round(li[2], 3), 'mix_line': lm[1], 'mix_cover': round(lm[2], 3),
                             'mix_cover_at_iid_line': round(cover(dist(p, 0.55), 1, li[1]), 3)})
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
