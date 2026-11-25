#!/usr/bin/env python3
"""Holm over the football port batch + (c) NFL coverage check. Needs cfb_port.json, cfb_neutral.json, nfl_neutral_0/1.json.
    python3 combine.py -> results.json"""
import json, math, os
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
L = lambda f: json.load(open(os.path.join(HERE, f)))
cfb, cn, n0, n1 = L('cfb_port.json'), L('cfb_neutral.json'), L('nfl_neutral_0.json'), L('nfl_neutral_1.json')


def paired(e0, e1):
    d = [b - a for k in e0 for a, b in zip(e0[k], e1[k])]
    t = float(np.mean(d) / (np.std(d, ddof=1) / math.sqrt(len(d))))
    return dict(t=round(t, 2), p=round(.5 * math.erfc(-t / math.sqrt(2)), 4), seasonsBetter=f"{sum(sum(e1[k]) < sum(e0[k]) for k in e0)}/{len(e0)}", n=len(d))


T = {}
T['a CFB XV per side'] = dict(target='describe held out', before=cfb['a_xv_per_side']['base'], after=cfb['a_xv_per_side']['cand'], **{k: cfb['a_xv_per_side'][k] for k in ('t', 'p', 'seasonsBetter', 'n')})
for k, lab in (('b_pxr_form', 'b CFB pXR form (cWAR)'), ('d_g5_weight', 'd CFB G5 level weight')):
    c = cfb[k]; T[lab] = dict(target='predict team held out', before=c['base'], after=c['cand'], playerR=[c['baseR'], c['candR']],
                             playerRwithinPos=[c['baseRwithin'], c['candRwithin']], **{x: c[x] for x in ('t', 'p', 'seasonsBetter', 'n')})
T['e1 NFL neutral EPA -> pXR/60'] = dict(target='predict team held out', before=n0['metrics']['pwar']['predict']['teamHeldR2'], after=n1['metrics']['pwar']['predict']['teamHeldR2'],
                                         playerR=[n0['metrics']['pwar']['playerVsBoard'], n1['metrics']['pwar']['playerVsBoard']],
                                         **paired(n0['metrics']['pwar']['err'], n1['metrics']['pwar']['err']),
                                         beside={m: [n0['metrics'][m]['predict']['teamHeldR2'], n1['metrics'][m]['predict']['teamHeldR2'], paired(n0['metrics'][m]['err'], n1['metrics'][m]['err'])['t']] for m in ('pxp', 'xv')})
T['e2 CFB neutral EPA -> pSV/60'] = dict(target='predict team (QB block) held out', before=cn['base']['predictOOS'], after=cn['cand']['predictOOS'],
                                         playerR=[cn['base']['playerR'], cn['cand']['playerR']], **{x: cn[x] for x in ('t', 'p', 'seasonsBetter', 'n')})
order = sorted(T, key=lambda k: T[k]['p']); m = len(order); stop = False
for i, k in enumerate(order):
    c = T[k]; c['holmAlpha'] = round(.05 / (m - i), 4)
    a, b = map(int, c['seasonsBetter'].split('/'))
    guard = 'playerR' not in c or c['playerR'][1] >= c['playerR'][0] - .01
    sig = (not stop) and c['p'] <= c['holmAlpha']
    c['holmSig'] = bool(sig); c['pass'] = bool(sig and a * 3 >= b * 2 and guard); c['playerGuard'] = bool(guard)
    stop = stop or not sig
# (c) NFL coverage: shares of WAR rows a team side (17-game scale) vs 11
cov = {}
for y in range(2016, 2026):
    d = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'nfl', f'audit_{y}_full.json')))
    s = defaultdict(float)
    for r in d['rows']: s[(r['t'], r['side'])] += r['sh']
    v = [s[(t, side)] / (d['teams'][t]['g'] / 17) for t in d['teams'] for side in (0, 1)]
    cov[y] = dict(min=round(min(v), 3), mean=round(float(np.mean(v)), 3), under=sum(x < 10.95 for x in v))
out = {'tests': T, 'nflCoverage': cov,
       'c': ('void as a change: NFL WAR is over replacement, so time no WAR row covers already counts at replacement (0); '
             'the coverage check found a data bug instead: 2020 snap counts list two spots (C/G, G/T, G/C, WR/R, FB/D, DE/L, DT/D), '
             'nfl_war.group_of maps none of them, so ~60 player-team seasons (3.1%% of 2020 scrimmage snaps; BAL offense 7.5 of 11 '
             'slots) have no AV, WAR or XV row. Other seasons (2016-26): only K/P/LS unmapped (by design). Fix: map a two-spot label '
             'by its first spot. Team sides below 10.95 slots: %d (16 in 2020, TEN 2025 D 10.92)') % sum(c['under'] for c in cov.values()),
       'g5Diag': json.load(open(os.path.join(HERE, 'cfb_g5_diag.json'))),
       'f': 'skipped: pXR = pXP + an age-free sub-position constant, so the player-level age fit that failed Nov 11 is unchanged'}
for k in T: print(k, {x: T[k][x] for x in ('before', 'after', 't', 'p', 'seasonsBetter', 'holmAlpha', 'pass')}, T[k].get('playerR'))
print(out['c'])
json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
