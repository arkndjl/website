#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT: who is priced. The page cannot know the five who play; it predicts them. This scores the same ratings
under each way of pricing a side (scripts/esea_standin_research.py FIVES) on rows where both sides have a history.

    python3 scripts/esea_five_research.py    # research/esea_matches.json.gz -> data/esea_five_research.json (~2 min)
    python3 scripts/esea_five_research.py --parity   # the page's JS port against this file

E1 expected five vs the page rule, E2 sharp vs expected: one-term logistic on the RWA gap (saved settings), fit
S54-S57, scored S58-S59, paired differences summed by match day. Player Elo and RWA + FACEIT level are reported
beside it. Also the share of matches where the page rule misses a player."""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esea_standin_research as SR  # noqa: E402
import esea_rwa_research as R  # noqa: E402

OUT = os.path.join(SR.ROOT, 'data', 'esea_five_research.json')


def pnorm(t):
    return 0.5 * math.erfc(-t / math.sqrt(2))


def holm(ps):
    """{name: one-sided p} -> {name: adjusted p}"""
    order = sorted(ps, key=ps.get)
    out, run = {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (len(order) - i) * ps[k]))
        out[k] = run
    return out


def parity(n=400):
    """the JS port (scripts/esea_five.mjs, used by the page) against this file on the last n archive matches"""
    import subprocess
    d, ms = SR.load()
    SR.predicted_fives(ms)
    gp, mdl = SR.run_pelo(ms, five='sharp', **R.PELO)
    js = json.loads(subprocess.check_output(['node', os.path.join(SR.ROOT, 'scripts', 'esea_five.mjs'), '--parity', str(n)]))
    bad, seen = 0, 0
    for m in ms[-n:]:
        j = js['matches'].get(m['id'])
        if j is None:
            bad += 1
            continue
        if not m['pf_ok']:
            continue
        seen += 1
        for k in ('live', 'expected', 'sharp'):
            for si in (0, 1):
                a, b = m['pf'][k][si], j[k][si]
                if [q for q, _ in a] != [q for q, _ in b] or any(abs(x[1] - y[1]) > 1e-9 for x, y in zip(a, b)):
                    bad += 1
        if abs(gp[m['id']] - j['gap']) > 1e-9:
            bad += 1
    es = sum(mdl.r.values())
    if abs(es - js['eloSum']) > 1e-6 * max(1, len(mdl.r)):
        bad += 1
    print(f'esea five parity: {seen} matches with both histories, {len(mdl.r)} players, {bad} mismatches')
    return bad


def main():
    if '--parity' in sys.argv:
        raise SystemExit(1 if parity() else 0)
    d, ms = SR.load()
    SR.predicted_fives(ms)
    fit = json.load(open(R.OUT))
    M = R.Maps(ms)
    cuts = R.weekly(ms)
    tune_g = (M.gseason >= 53) & (M.gseason <= R.TUNE[1])
    av = R.ark_values(M, tune_g)
    p = fit['params']
    feats = {}
    for five in SR.FIVES:
        feats[five] = {'rwa': R.rwa_gaps(ms, M, av, p, cuts, five), 'pelo': SR.run_pelo(ms, five=five, **R.PELO)[0],
                       'lv': {m['id']: m['pflv'][five] for m in ms}}
    ok = [m for m in ms if m['pf_ok'] and m['season'] > SR.BURN and all(m['id'] in feats[f]['rwa'] for f in SR.FIVES)]
    day = {m['id']: int(m['at'] // SR.DAY) for m in ms}
    res = {'asof': d.get('asof'), 'rows': {'tune': sum(R.TUNE[0] <= m['season'] <= R.TUNE[1] for m in ok), 'held': sum(m['season'] >= R.HELD[0] for m in ok)},
           'params': p}
    held = [m for m in ok if m['season'] >= R.HELD[0]]
    miss = [len(set(m['five1'][:5]) - {q for q, _ in m['pf']['live'][0]}) + len(set(m['five2'][:5]) - {q for q, _ in m['pf']['live'][1]}) for m in held]
    res['live_rule_miss'] = {'share_matches': round(sum(x > 0 for x in miss) / len(miss), 3), 'players_per_match': round(sum(miss) / len(miss), 2)}
    L = {}
    for name, cols in (('rwa', ['rwa']), ('pelo', ['pelo']), ('rwa+lv', ['rwa', 'lv'])):
        L[name] = {}
        for five in SR.FIVES:
            rows = [{'id': m['id'], 'y': m['y'], 'season': m['season'], **{c: feats[five][c][m['id']] for c in cols}} for m in ok
                    if all(feats[f]['lv'][m['id']] is not None for f in SR.FIVES) or 'lv' not in cols]
            b, hl = SR.split_fit(rows, cols, R.TUNE, R.HELD)
            _, tl = SR.split_fit(rows, cols, R.TUNE, R.TUNE)
            L[name][five] = {'coef': [round(x, 3) for x in b], 'held': hl, 'tune': tl}
    out = {}
    for name in L:
        o = {five: {'coef': L[name][five]['coef'], 'n': len(L[name][five]['held']),
                    'held_ll': round(sum(L[name][five]['held'].values()) / len(L[name][five]['held']), 4),
                    'tune_ll': round(sum(L[name][five]['tune'].values()) / len(L[name][five]['tune']), 4)} for five in SR.FIVES}
        for a, b in (('live', 'actual'), ('expected', 'live'), ('sharp', 'expected'), ('expected', 'actual')):
            o[f'{a}_vs_{b}'] = {'held': SR.day_t(L[name][a]['held'], L[name][b]['held'], day), 'tune': SR.day_t(L[name][a]['tune'], L[name][b]['tune'], day)}
        out[name] = o
    res['models'] = out
    e1, e2 = out['rwa']['expected_vs_live'], out['rwa']['sharp_vs_expected']
    res['E1'] = {'held': e1['held'], 'tune': e1['tune'], 'p': round(pnorm(e1['held']['t']), 5)}
    res['E2'] = {'held': e2['held'], 'tune': e2['tune'], 'p': round(pnorm(e2['held']['t']), 5)}
    res['note'] = 'Holm over the ESEA family (E1, E2, E3) is applied in scripts/esea_veto_research.py once E3 is scored'
    json.dump(res, open(OUT, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
