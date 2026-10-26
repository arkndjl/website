#!/usr/bin/env python3
"""1NT total-rounds over/under research (Oct 26 2026): what sets the line on an ESEA NA Bo1 map.

    python3 scripts/esea_totals_research.py   # reads research/esea_matches.json.gz; writes data/esea_totals_research.json

A map is a race to 13 (MR12); 12-12 goes to MR3 overtime (first to 4 of 6, 3-3 repeats), so the total is
13 + the loser's rounds, or 24 + 4..6 per overtime. Candidates for the distribution of the total:
  naive    the league's empirical distribution of totals (training days only); line = its median hook
  iid      rounds as coin flips at one per-round chance q, q matched to the map win chance (the page's race())
  mix      q varies map to map: logit(q) = logit(q0) + tau z, z ~ N(0, 1) (economy streaks, form, side
           swings); tau fitted on the training days, q0 matched so the mixture keeps the map win chance
  mix+map  mix with a per-map tau (shrunk to the pooled tau)
  mix+team mix with each team's own spread of round share (shrunk), averaged over the two teams
The map win chance is walk-forward round-share Elo (esea_research.py 'relo', K 96, carry 0), predicted
from earlier matches only; a no-gap variant (p = .5 for every map) shows what the strength gap adds.
Scoring: leave-one-match-day-out. Log score of the exact total (OT totals pooled per overtime count),
binary log loss on over at the league's common hook (20.5), MAE of the expected total, and how often the
model's own line goes over (should be ~50%). Paired t vs naive per map.
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esea_research import Elo, load, snapshots  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'esea_totals_research.json')
# 9-point Gauss-Hermite (probabilists'), nodes and weights for z ~ N(0, 1)
_x = [-4.512745863, -3.205429002, -2.076847979, -1.023255664, 0.0, 1.023255664, 2.076847979, 3.205429002, 4.512745863]
_w = [2.234584e-05, 2.789141e-03, 4.991640e-02, 2.440975e-01, 4.063492e-01, 2.440975e-01, 4.991640e-02, 2.789141e-03, 2.234584e-05]
GH = list(zip(_x, _w))
COMMON = 20.5


def race(q):
    """distribution of (total rounds) and the map win chance for per-round chance q; OT totals keyed 24+6k+j"""
    g = defaultdict(float)
    g[(0, 0)] = 1.0
    tot = defaultdict(float)
    win = 0.0
    for t in range(24):
        for a in range(t + 1):
            b = t - a
            p = g.pop((a, b), 0.0)
            if not p:
                continue
            for na, nb, pr in ((a + 1, b, p * q), (a, b + 1, p * (1 - q))):
                if na == 13:
                    tot[13 + nb] += pr
                    win += pr
                elif nb == 13:
                    tot[13 + na] += pr
                elif na == 12 and nb == 12:
                    g[('ot',)] += pr
                else:
                    g[(na, nb)] += pr
    # overtime periods: first to 4 of 6; per period P(win 4-j), P(lose j-4), P(3-3)
    per = defaultdict(float)
    h = {(0, 0): 1.0}
    for t in range(6):
        nh = defaultdict(float)
        for (a, b), p in h.items():
            for na, nb, pr in ((a + 1, b, p * q), (a, b + 1, p * (1 - q))):
                if na == 4:
                    per[('w', nb)] += pr
                elif nb == 4:
                    per[('l', na)] += pr
                else:
                    nh[(na, nb)] += pr
        h = nh
    tie = h.get((3, 3), 0.0)
    carry = g.get(('ot',), 0.0)
    for k in range(8):
        if carry < 1e-12:
            break
        for (s, j), p in per.items():
            tot[24 + 6 * k + 4 + j] += carry * p
            if s == 'w':
                win += carry * p
        carry *= tie
    return dict(tot), win


_cache = {}


def race_c(q):
    k = round(q, 4)
    if k not in _cache:
        _cache[k] = race(k)
    return _cache[k]


lg = lambda p: math.log(p / (1 - p))
ex = lambda x: 1 / (1 + math.exp(-x))


def mix(q0, tau):
    tot, win = defaultdict(float), 0.0
    for z, w in GH:
        q = ex(lg(q0) + tau * z)
        d, pw = race_c(min(.97, max(.03, q)))
        win += w * pw
        for k, v in d.items():
            tot[k] += w * v
    return tot, win


def dist_for(p, tau):
    """total distribution with map win chance p and dispersion tau: bisect q0"""
    lo, hi = 0.05, 0.95
    for _ in range(22):
        m = (lo + hi) / 2
        (lo, hi) = (m, hi) if mix(m, tau)[1] < p else (lo, m)
    return mix((lo + hi) / 2, tau)[0]


_dc = {}


def dist_c(p, tau):
    # symmetric in p <-> 1-p; cache on a .01 grid of the favourite's chance
    k = (round(max(p, 1 - p), 2), round(tau, 3))
    if k not in _dc:
        _dc[k] = dist_for(k[0], k[1])
    return _dc[k]


def bucket(t):
    return t if t <= 24 else 24 + 6 * ((t - 25) // 6 + 1)   # every total of the k-th overtime in one cell


def logscore(dist, t):
    """log score of the realised total; OT totals scored on their overtime cell (rare, noisy)"""
    b = bucket(t)
    p = sum(v for k, v in dist.items() if bucket(k) == b)
    return -math.log(max(p, 1e-6))


def over(dist, L):
    return sum(v for k, v in dist.items() if k > L)


def line_of(dist):
    """the half-point hook closest to a 50/50 over"""
    best = None
    for L in [x + 0.5 for x in range(13, 30)]:
        o = over(dist, L)
        if best is None or abs(o - .5) < abs(best[1] - .5):
            best = (L, o)
    return best


def mean(dist):
    return sum(k * v for k, v in dist.items())


def blog(p, y):
    p = min(1 - 1e-4, max(1e-4, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def tstat(d):
    n = len(d)
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) or 1e-9
    return {'n': n, 'diff': round(mu, 4), 't': round(mu / (sd / math.sqrt(n)), 2)}


def elo_check(rows, ms, tau):
    """S59: the page's own strength input, FACEIT team elo (top-5 mean, 600-point scale) as it stood before each
    match (data/esea.json git history), against relo and against no gap, at the pooled tau"""
    snaps = snapshots()
    at = {m['id']: m['at'] for m in ms}
    out = []
    for r in rows:
        if r['season'] != 59:
            continue
        prior = [s for s in snaps if s[0] < at[r['id']] - 60]
        if not prior:
            continue
        S = prior[-1][1]
        a, b = S.get(r['t1']), S.get(r['t2'])
        if not a or not b or not a.get('elo') or not b.get('elo'):
            continue
        pe = 1 / (1 + 10 ** (-(a['elo'] - b['elo']) / 600))
        out.append((r, pe))
    if len(out) < 20:
        return {'n': len(out)}
    res = {'n': len(out), 'mean_fav_elo_p': round(sum(max(p, 1 - p) for _, p in out) / len(out), 3)}
    sc = {}
    for name, f in (('nogap', lambda r, pe: dist_c(0.5, tau)), ('relo', lambda r, pe: dist_c(r['p'], tau)), ('elo', lambda r, pe: dist_c(pe, tau)),
                    ('elo_half', lambda r, pe: dist_c(ex(0.5 * lg(pe)), tau))):
        ls = [logscore(f(r, pe), r['total']) for r, pe in out]
        bl = [blog(over(f(r, pe), COMMON), r['total'] > COMMON) for r, pe in out]
        ae = [abs(mean(f(r, pe)) - r['total']) for r, pe in out]
        sc[name] = {'ls': ls, 'bl': bl, 'ae': ae}
        res[name] = {'logscore': round(sum(ls) / len(ls), 4), 'over_logloss_20_5': round(sum(bl) / len(bl), 4), 'mae': round(sum(ae) / len(ae), 3)}
    for name in ('relo', 'elo', 'elo_half'):
        res[name]['vs_nogap'] = {m: tstat([x - y for x, y in zip(sc[name][m], sc['nogap'][m])]) for m in ('ls', 'bl', 'ae')}
    # do bigger elo gaps play shorter? observed mean total by elo favourite bucket
    bk = defaultdict(list)
    for r, pe in out:
        bk[min(0.8, round(max(pe, 1 - pe) * 10) / 10)].append(r['total'])
    res['observed_by_elo_p'] = [{'p': k, 'n': len(v), 'mean': round(sum(v) / len(v), 2), 'model_mean': round(mean(dist_c(k, tau)), 2)} for k, v in sorted(bk.items())]
    return res


def main():
    d, ms = load()
    # walk-forward round-share Elo win chance before each match
    relo = Elo(K=96, carry=0.0, margin=True, div_gap=0)
    rows = []
    for m in ms:
        p = relo.predict(m)
        relo.update(m)
        mp = (m.get('maps') or [None])[0]
        if not mp or mp.get('s1') is None or mp.get('s2') is None:
            continue
        rows.append({'id': m['id'], 'day': m['at'] // 86400, 'p': p, 'map': mp['map'], 'season': m['season'], 'div': m['div'],
                     't1': m['f1']['id'], 't2': m['f2']['id'], 'total': mp['s1'] + mp['s2'],
                     'share': mp['s1'] / (mp['s1'] + mp['s2'])})
    days = sorted({r['day'] for r in rows})
    print('maps', len(rows), 'days', len(days))
    TAUS = [0.0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 1.0]
    for r in rows:
        r['ls0'] = {t: logscore(dist_c(0.5, t), r['total']) for t in TAUS}     # no strength gap
        r['lsr'] = {t: logscore(dist_c(r['p'], t), r['total']) for t in TAUS}  # relo gap
    keys = list(range(13, 25)) + [28, 29, 30, 34, 35, 36, 40, 41, 42, 46, 47, 48]

    def emp(tr):
        cnt = defaultdict(float)
        for r in tr:
            cnt[r['total']] += 1
        Z = len(tr) + 0.5 * len(keys)
        return {k: (cnt[k] + 0.5) / Z for k in keys}
    preds = defaultdict(dict)
    chosen = defaultdict(list)
    for dd in days:
        tr = [r for r in rows if r['day'] != dd]
        te = [r for r in rows if r['day'] == dd]
        nd = emp(tr)
        tau = min(TAUS, key=lambda t: sum(r['ls0'][t] for r in tr))
        taur = min(TAUS, key=lambda t: sum(r['lsr'][t] for r in tr))
        chosen['mix'].append(tau)
        chosen['mix_relo'].append(taur)
        pool = {t: sum(r['ls0'][t] for r in tr) / len(tr) for t in TAUS}
        # team spread: each team's rms round-share gap from .5 on the training days, shrunk to the league's by
        # 8 maps; tau scaled by (pair mean / league), snapped to the grid
        sh = defaultdict(list)
        for r in tr:
            sh[r['t1']].append(r['share'])
            sh[r['t2']].append(1 - r['share'])
        allsd = math.sqrt(sum((r['share'] - .5) ** 2 for r in tr) / len(tr))

        def tsd(t):
            v = sh.get(t, [])
            return math.sqrt((sum((x - .5) ** 2 for x in v) + 8 * allsd ** 2) / (len(v) + 8))
        for r in te:
            preds['naive'][r['id']] = nd
            sub = [x for x in tr if x['map'] == r['map']]
            e, n = emp(sub), len(sub)
            preds['naive_map'][r['id']] = {k: (n * e[k] + 100 * nd[k]) / (n + 100) for k in keys}   # map's own totals, shrunk by 100 maps
            preds['iid'][r['id']] = dist_c(0.5, 0.0)
            preds['mix'][r['id']] = dist_c(0.5, tau)
            preds['mix_relo'][r['id']] = dist_c(r['p'], taur)
            # per-map tau with the pooled score as a prior worth 60 maps
            tm = min(TAUS, key=lambda t: sum(x['ls0'][t] for x in sub) + 60 * pool[t])
            preds['mix_map'][r['id']] = dist_c(0.5, tm)
            k = (tsd(r['t1']) + tsd(r['t2'])) / 2 / allsd
            preds['mix_team'][r['id']] = dist_c(0.5, min(TAUS, key=lambda t: abs(t - tau * k)))
    res = {'maps': len(rows), 'days': len(days), 'seasons': sorted({r['season'] for r in rows}),
           'league': {'mean_total': round(sum(r['total'] for r in rows) / len(rows), 2),
                      'ot_rate': round(sum(r['total'] > 24 for r in rows) / len(rows), 3),
                      'over_20_5': round(sum(r['total'] > 20.5 for r in rows) / len(rows), 3),
                      'iid_ot_at_even': round(sum(v for k, v in race(0.5)[0].items() if k > 24), 3)},
           'tau_chosen': {k: sorted(set(v)) for k, v in chosen.items()}, 'models': {}}
    cache = {}
    for name, pr in preds.items():
        c = {'ls': [], 'bl': [], 'ae': []}
        hits = []
        for r in rows:
            dist = pr[r['id']]
            c['ls'].append(logscore(dist, r['total']))
            c['bl'].append(blog(over(dist, COMMON), r['total'] > COMMON))
            c['ae'].append(abs(mean(dist) - r['total']))
            hits.append(r['total'] > line_of(dist)[0])
        cache[name] = c
        res['models'][name] = {'logscore': round(sum(c['ls']) / len(rows), 4), 'over_logloss_20_5': round(sum(c['bl']) / len(rows), 4),
                               'mae': round(sum(c['ae']) / len(rows), 3), 'own_line_over': round(sum(hits) / len(hits), 3)}
    for name in preds:
        for ref in ('naive', 'mix'):
            if name != ref:
                res['models'][name][f'vs_{ref}'] = {m: tstat([a - b for a, b in zip(cache[name][m], cache[ref][m])]) for m in ('ls', 'bl', 'ae')}
    tau_all = min(TAUS, key=lambda t: sum(r['ls0'][t] for r in rows))
    res['tau'] = tau_all
    res['elo_s59'] = elo_check(rows, ms, tau_all)
    # calibration of the shipped model (held-out days) at every hook
    res['calibration_mix'] = [{'line': L, 'pred_over': round(sum(over(preds['mix'][r['id']], L) for r in rows) / len(rows), 3),
                               'actual_over': round(sum(r['total'] > L for r in rows) / len(rows), 3)} for L in (17.5, 18.5, 19.5, 20.5, 21.5, 22.5, 23.5, 24.5)]
    # what a strength gap would do to the line (shown for reference; the gap carries no weight live)
    res['line_by_p'] = []
    for p in (0.5, 0.6, 0.7, 0.8, 0.9):
        dist = dist_c(p, tau_all)
        L, o = line_of(dist)
        res['line_by_p'].append({'p': p, 'mean': round(mean(dist), 2), 'line': L, 'over': round(o, 3), 'ot': round(sum(v for k, v in dist.items() if k > 24), 3)})
    obs = defaultdict(list)
    for r in rows:
        obs[min(0.75, round(max(r['p'], 1 - r['p']) * 20) / 20)].append(r['total'])
    res['observed_by_relo_p'] = [{'p': k, 'n': len(v), 'mean': round(sum(v) / len(v), 2), 'ot': round(sum(x > 24 for x in v) / len(v), 3)} for k, v in sorted(obs.items())]
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
