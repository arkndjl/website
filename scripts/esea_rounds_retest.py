#!/usr/bin/env python3
"""Re-test of the 1NT round models (totals o/u and round spread) on the S53-S59 ESEA NA league pull.

    python3 scripts/esea_rounds_retest.py [path to esea_matches json.gz]   # default research/esea_matches.json.gz
                                                                           # writes data/esea_rounds_retest.json

Every map with a score (Bo1 and each Bo3 map, regular season and playoffs). Walk-forward round-share Elo
(K 96, updated per match) gives the map win chance. Tuned on S53-S56, held out on S57-S59.
  tau        the logit sd of the per-round chance, by log score of the total, per season (drift check)
  gap        totals with the relo gap, shrunk by c in log-odds (c tuned), vs no gap
  team       totals with tau scaled by each team's walk-forward rms round-share gap (shrunk by K maps)
  div        totals with a per-division tau
  spread     margin log score and cover at the iid line: mixture vs coin-flip rounds
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esea_research import Elo  # noqa: E402
import esea_totals_research as T  # noqa: E402
import esea_spread_research as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'esea_rounds_retest.json')
TAUS = [0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8]
TUNE, HELD = {53, 54, 55, 56}, {57, 58, 59}
DIV_RANK = {'Intermediate': 0, 'Main': 1, 'Advanced': 2}


def rows_of(path):
    d = json.load(gzip.open(path))
    ms = sorted((m for m in d['matches'] if m.get('at') and m.get('winner') in ('faction1', 'faction2')), key=lambda m: m['at'])
    relo = Elo(K=96, carry=0.0, margin=True, div_gap=0)
    rows = []
    for m in ms:
        rf = ra = 0
        for mp in m.get('maps') or []:
            if mp.get('s1') is not None and mp.get('s2') is not None:
                rf += mp['s1']
                ra += mp['s2']
        m['y'] = 1 if m['winner'] == 'faction1' else 0
        m['share'] = rf / (rf + ra) if rf + ra else None
        m['div_r'] = DIV_RANK.get((m.get('div') or 'Main').split()[0], 1)
        p = relo.predict(m)
        for mp in m.get('maps') or []:
            if mp.get('s1') is None or mp.get('s2') is None or mp['s1'] + mp['s2'] < 13:
                continue
            rows.append({'season': m['season'], 'at': m['at'], 'p': p, 'div': (m.get('div') or '?').split()[0], 'bo': m.get('bo'),
                         't1': m['f1']['id'], 't2': m['f2']['id'], 'total': mp['s1'] + mp['s2'], 'margin': mp['s1'] - mp['s2'],
                         'share': mp['s1'] / (mp['s1'] + mp['s2'])})
        relo.update(m)
    return rows


def mean_ls(rs, f):
    return sum(f(r) for r in rs) / len(rs)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'research', 'esea_matches.json.gz')
    rows = rows_of(path)
    tune = [r for r in rows if r['season'] in TUNE]
    held = [r for r in rows if r['season'] in HELD]
    res = {'maps': len(rows), 'tune_maps': len(tune), 'held_maps': len(held)}
    for r in rows:
        r['ls0'] = {t: T.logscore(T.dist_c(0.5, t), r['total']) for t in TAUS}
    # tau by season: does the league's streakiness drift?
    res['tau_by_season'] = {}
    for s in sorted({r['season'] for r in rows}):
        rs = [r for r in rows if r['season'] == s]
        t = min(TAUS, key=lambda t: sum(r['ls0'][t] for r in rs))
        res['tau_by_season'][s] = {'n': len(rs), 'tau': t, 'over_20_5': round(sum(r['total'] > 20.5 for r in rs) / len(rs), 3),
                                   'ot': round(sum(r['total'] > 24 for r in rs) / len(rs), 3)}
    tau = min(TAUS, key=lambda t: sum(r['ls0'][t] for r in tune))
    res['tau_tune'] = tau
    # held-out calibration at the tuned tau, and at the live .55
    for tt in (tau, 0.55):
        res[f'held_calibration_tau_{tt}'] = [{'line': L, 'pred': round(T.over(T.dist_c(0.5, tt), L), 3),
                                              'actual': round(sum(r['total'] > L for r in held) / len(held), 3)} for L in (18.5, 20.5, 22.5, 24.5)]
    base = [r['ls0'][tau] for r in held]

    # strength gap, shrunk by c in log-odds (c tuned)
    C = [0.0, 0.25, 0.5, 0.75, 1.0]
    ps = lambda p, c: T.ex(c * T.lg(min(.97, max(.03, p))))
    c = min(C, key=lambda c: sum(T.logscore(T.dist_c(ps(r['p'], c), tau), r['total']) for r in tune))
    res['gap'] = {'c_tune': c, 'full_c1_vs_nogap': T.tstat([T.logscore(T.dist_c(r['p'], tau), r['total']) - b for r, b in zip(held, base)]),
                  'tuned_vs_nogap': T.tstat([T.logscore(T.dist_c(ps(r['p'], c), tau), r['total']) - b for r, b in zip(held, base)])}
    # per-division tau
    dt = {}
    for dv in {r['div'] for r in tune}:
        rs = [r for r in tune if r['div'] == dv]
        dt[dv] = min(TAUS, key=lambda t: sum(r['ls0'][t] for r in rs)) if len(rs) >= 200 else tau
    res['div'] = {'tau': dt, 'vs_pooled': T.tstat([r['ls0'][dt.get(r['div'], tau)] - b for r, b in zip(held, base)])}
    # team spread, walk-forward across seasons: tau x (pair rms round-share gap / league rms), K-map shrink
    for K in (8, 20):
        sh, allv = defaultdict(list), []
        tl, ob = [], []
        pend, cur = [], None
        for r in rows:
            if r['at'] != cur:
                for x in pend:
                    sh[x['t1']].append(x['share'])
                    sh[x['t2']].append(1 - x['share'])
                    allv.append((x['share'] - .5) ** 2)
                pend, cur = [], r['at']
            pend.append(r)
            if r['season'] not in HELD:
                continue
            asd = math.sqrt(sum(allv[-20000:]) / len(allv[-20000:]))

            def tsd(t):
                v = sh.get(t, [])[-60:]
                return math.sqrt((sum((x - .5) ** 2 for x in v) + K * asd ** 2) / (len(v) + K))
            k = (tsd(r['t1']) + tsd(r['t2'])) / 2 / asd
            tt = min(TAUS, key=lambda t: abs(t - tau * k))
            tl.append(r['ls0'][tt] - r['ls0'][tau])
            ob.append(T.blog(T.over(T.dist_c(0.5, tt), 20.5), r['total'] > 20.5) - T.blog(T.over(T.dist_c(0.5, tau), 20.5), r['total'] > 20.5))
        res[f'team_K{K}'] = {'ls': T.tstat(tl), 'over_20_5': T.tstat(ob)}
    # spread: mixture vs coin-flip rounds on the held-out seasons
    ls_i, ls_m, cl_i, cl_m, own_i, own_m = [], [], [], [], [], []
    for r in held:
        di, dm = S.dist(r['p'], 0.0), S.dist(r['p'], tau)
        side, L, _ = S.line_of(di)
        y = r['margin'] * side > L
        ls_i.append(S.logscore(di, r['margin']))
        ls_m.append(S.logscore(dm, r['margin']))
        cl_i.append(T.blog(S.cover(di, side, L), y))
        cl_m.append(T.blog(S.cover(dm, side, L), y))
        s2, L2, _ = S.line_of(dm)
        own_i.append(y)
        own_m.append(r['margin'] * s2 > L2)
    res['spread'] = {'ls_mix_vs_iid': T.tstat([a - b for a, b in zip(ls_m, ls_i)]), 'cover_mix_vs_iid': T.tstat([a - b for a, b in zip(cl_m, cl_i)]),
                     'own_cover_iid': round(sum(own_i) / len(own_i), 3), 'own_cover_mix': round(sum(own_m) / len(own_m), 3)}
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
