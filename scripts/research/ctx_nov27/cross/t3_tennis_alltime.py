#!/usr/bin/env python3
"""T3 (prereg.md): tennis all-time season value, year-end Elo margin vs season-only SV (wins over what a replacement
player would win against the same opponents that year). Needs scripts/.cache/alltime/tennis (alltime_pull.py tennis).

    python3 scripts/research/ctx_nov27/cross/t3_tennis_alltime.py"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import alltime as AT         # noqa: E402

out = {}
for tour in ('atp', 'wta'):
    S = AT.tennis_players(tour)
    res = {'rows': len(S)}
    for lab, pk, cv in (('elo', 'ev', 'ecv'), ('sv', 'v', 'cv')):
        P = [dict(s, v=s[pk]) for s in S if s.get(pk) is not None]
        a, raw, line = AT.era_check(P, 'v', 'v')
        # careers: a player's summed value, binned by the decade of his best season
        car = {}
        for s in S:
            c = car.setdefault(s['id'], {'id': s['id'], 'n': s['n'], 'v': 0.0, 'b': -9, 'y': s['y']})
            c['v'] += s.get(cv) or 0.0
            if (s.get(pk) or -9) > c['b']:
                c['b'], c['y'] = s.get(pk) or -9, s['y']
        ca, _, cline = AT.era_check(list(car.values()), 'v', 'v')
        top = sorted(P, key=lambda r: -r['v'])[:10]
        ctop = sorted(car.values(), key=lambda r: -r['v'])[:10]
        res[lab] = {'peakKL': a, 'peakLine': line, 'peakPass': a <= line, 'careerKL': ca, 'careerLine': cline, 'careerPass': ca <= cline,
                    'peakDecades': dict(sorted(Counter(r['y'] // 10 * 10 for r in sorted(P, key=lambda r: -r['v'])[:100]).items())),
                    'top': [(r['n'], r['y'], round(r['v'], 2)) for r in top], 'careers': [(r['n'], round(r['v'], 1)) for r in ctop]}
        print(tour, lab, {k: v for k, v in res[lab].items() if k not in ('top', 'careers')})
        print('   ', res[lab]['top'][:6])
        print('   ', res[lab]['careers'][:8])
    out[tour] = res
json.dump(out, open(os.path.join(HERE, 'results_t3.json'), 'w'), indent=1)
