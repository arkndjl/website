#!/usr/bin/env python3
"""Nightly exposure cap test (Nov 1 2026). Research harness, nothing live reads it.

The opening night of the CBB season sent 61 bets at once (104% of the bankroll on Nov 2-3 ET). Each pick is staked
at full Kelly on its own calibrated edge with a 5% per-bet cap, and nothing caps the total on one night. This asks
whether a cap on a slate's total stake (an ET day; football a week) costs or adds growth.

  python3 scripts/exposure_cap_research.py        # table + data/exposure_cap_research.json

Picks: walk-forward on every season with opening lines, the markets live now with an open history (CBB spread and
total, NBA total, CFB total), as scripts/pick_recal.py builds them: each test season's calibration is fit on the
seasons before it, scaled by units.TIMING (0.5), every pick with a calibrated return > 0 at Novig -103, stake 1x Kelly
capped at 5% (units.BOOK_CAP). All markets' picks on one date share a slate.

Policy: cap C on the slate's total; a slate past C has every stake scaled by C / total.
Score: expected log growth of the joint slate (Monte Carlo, outcomes from the close's chances with the edge over a
fair coin x TRUE), with positively correlated outcomes inside a slate (Gaussian copula rho: 0, the measured ~0.04, and
0.10 as a stress for a slate-wide error such as the CBB totals level); realized log growth on the results; P(a 25% / 50%
drawdown inside a season) from simulated seasons.
"""
import json
import math
import os
import sys

import numpy as np
from statistics import NormalDist

ND = NormalDist()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pick_recal as R  # noqa: E402
import units as U  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), 'data', 'exposure_cap_research.json')
MARKETS = [('cbb', 'spread'), ('cbb', 'total'), ('nba', 'total'), ('cfb', 'total')]
CAPS = [10, 15, 20, 25, 30, 40, 50, 75, 100, None]
O = -103
B = R.dec(O) - 1


def build():
    """test picks with their stake (fraction of bankroll) and slate"""
    out = []
    for sport, mk in MARKETS:
        P = R.picks(sport, mk)
        ss = sorted({q['S'] for q in P})
        for T in ss[1:]:
            fit = [q for q in P if q['S'] < T]
            test = [q for q in P if q['S'] == T]
            if len(fit) < 100 or not test:
                continue
            cal = R.scaled(R.calib(fit), U.TIMING)
            f = R.stakes(test, cal, {'rule': 'edge0', 'lam': 1.0, 'cap': U.BOOK_CAP}, O)
            for q, s in zip(test, f):
                if s > 0:
                    out.append({**q, 's': s, 'mk': f'{sport} {mk}', 'season': f"{'bb' if sport != 'cfb' else 'fb'}{T}"})
    return out


def slates(P):
    sl = {}
    for q in P:
        sl.setdefault(q['slate'], []).append(q)
    return [sl[k] for k in sorted(sl)]


def run(S, cap, true, rho, draws, rng):
    """(expected log growth per slate summed, realized, mean exposure, P dd25, P dd50, worst simulated night)"""
    ge = gr = 0.0
    seasons = {}
    worst = []
    for v in S:
        s = np.array([q['s'] for q in v])
        tot = s.sum()
        if cap is not None and tot > cap / 100:
            s = s * (cap / 100) / tot
        d = np.array([q['d'] for q in v]) * true
        p = np.array([q['p'] for q in v])
        w = (1 - p + d) / 2
        z = rng.standard_normal((draws, 1)) * math.sqrt(rho) + rng.standard_normal((draws, len(v))) * math.sqrt(1 - rho)
        tw = np.array([ND.inv_cdf(min(max(a, 1e-9), 1 - 1e-9)) for a in w])
        tp = np.array([ND.inv_cdf(min(max(a, 1e-9), 1 - 1e-9)) for a in w + p])
        x = np.where(z < tw, B, np.where(z < tp, 0.0, -1.0)) @ s
        lg = np.log(np.maximum(1e-9, 1 + x))
        ge += lg.mean()
        worst.append(x.min())
        r = np.array([B if q['r'] > 0 else (-1.0 if q['r'] < 0 else 0.0) for q in v])
        gr += math.log(max(1e-9, 1 + float(r @ s)))
        seasons.setdefault(v[0]['season'], []).append(lg)
    # drawdowns: each draw index is one simulated path through the season's slates
    d25 = d50 = n = 0
    for lgs in seasons.values():
        M = np.cumsum(np.stack(lgs, axis=1), axis=1)
        pk = np.maximum.accumulate(np.maximum(M, 0), axis=1)
        dd = 1 - np.exp(M - pk)
        mdd = dd.max(axis=1)
        d25 += (mdd >= 0.25).sum()
        d50 += (mdd >= 0.5).sum()
        n += len(mdd)
    return ge, gr, d25 / n, d50 / n, float(np.percentile(worst, 1))


def main():
    P = build()
    S = slates(P)
    tot = np.array([sum(q['s'] for q in v) for v in S])
    nseas = len({q['season'] for q in P})
    print(f'{len(P)} picks on {len(S)} slates, {nseas} market-seasons; slate exposure median {np.median(tot)*100:.1f}%, '
          f'p90 {np.percentile(tot, 90)*100:.1f}%, p99 {np.percentile(tot, 99)*100:.1f}%, max {tot.max()*100:.1f}%; '
          f'past 50%: {(tot > .5).mean()*100:.1f}% of slates, past 100%: {(tot > 1).mean()*100:.1f}%')
    yrs = len({q['season'] for q in P if q['season'].startswith('bb')})
    out = {'picks': len(P), 'slates': len(S), 'exposure': {'median': float(np.median(tot)), 'p90': float(np.percentile(tot, 90)),
           'p99': float(np.percentile(tot, 99)), 'max': float(tot.max()), 'over50': float((tot > .5).mean()), 'over100': float((tot > 1).mean())},
           'rows': []}
    for true in (1.0, 0.5):
        for rho in (0.0, 0.04, 0.10):
            print(f'\n== true edge x{true}, within-night correlation {rho}; growth = total log growth over the test seasons')
            for cap in CAPS:
                rng = np.random.default_rng(7)
                ge, gr, a, b, w = run(S, cap, true, rho, 300, rng)
                lab = 'none' if cap is None else f'{cap}%'
                print(f'cap {lab:>5}: expected {ge*100:7.1f}%  realized {gr*100:7.1f}%  P(dd25) {a:.2f}  P(dd50) {b:.2f}  1% worst night {w*100:6.1f}%')
                out['rows'].append({'true': true, 'rho': rho, 'cap': cap, 'ge': round(ge * 100, 1), 'gr': round(gr * 100, 1),
                                    'dd25': round(a, 3), 'dd50': round(b, 3), 'worstNight1pct': round(w * 100, 1)})
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
