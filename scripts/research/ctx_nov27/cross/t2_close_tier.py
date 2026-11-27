#!/usr/bin/env python3
"""T2 (prereg.md): close predictor tier cells, today's conference map vs the game's own season. Read-only: writes
results_t2.json beside this file.

    python3 scripts/research/ctx_nov27/cross/t2_close_tier.py"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import close_model as CM     # noqa: E402
import units as DU           # noqa: E402


def clustered(vals):
    by = {}
    for s, v in vals:
        by[s] = by.get(s, 0.0) + v
    k, tot = len(by), sum(by.values())
    m = tot / k
    sd = math.sqrt(sum((a - m) ** 2 for a in by.values()) / (k - 1))
    return tot, (m / (sd / math.sqrt(k)) if sd else None)


def rows_for(sport, then):
    keep, CM.TIER_THEN = CM.TIER_THEN, ({sport} if then else set())
    rows = CM.load(sport)
    CM.TIER_THEN = keep
    return rows


def run(sport, mk, cap, old_rows, new_rows):
    S = CM.SPEC[sport]
    arms = {}
    new_tier = {str(g['id']): g['_tier'] for g in new_rows}
    for lab, rows in (('old', old_rows), ('new', new_rows)):
        rs = CM.market_rows(sport, mk, rows, cap)
        tcuts = {}
        for ss in {r['S'] for r in rs}:
            tt = sorted(r['o'] for r in rs if r['S'] == ss)
            tcuts[ss] = (tt[len(tt) // 3], tt[2 * len(tt) // 3]) if mk == 'total' else None
        for r in rs:
            r['cells'] = CM.cells(sport, mk, r['g'], tcuts[r['S']])
            r['serve'] = {**r['cells'], 'tier': new_tier[str(r['g']['id'])]}      # what the live board would read
        tune = [r for r in rs if r['S'] in S['tune']]
        oMean = sum(r['o'] for r in tune) / len(tune)
        ytune = [r['c'] - r['o'] for r in tune]
        best = None
        for knot in CM.KNOTS:
            for lam in CM.LAMS:
                p = CM.oof(sport, mk, tune, S['tune'], knot, lam, oMean)
                sse = sum((a - b) ** 2 for a, b in zip(ytune, p))
                if best is None or sse < best[0]:
                    best = (sse, knot, lam)
        _, knot, lam = best
        out = {}
        for hs in S['held']:
            past = [r for r in rs if r['S'] < hs]
            sp = CM.fit_spec(sport, mk, past, knot, lam, oMean)
            for r in rs:
                if r['S'] == hs:
                    q = {**r, 'cells': r['serve']}
                    mv = CM.predict(sport, mk, q, sp)
                    side, e = CM.e_ret(sport, mk, q, mv)
                    out[str(r['g']['id'])] = (r, mv, side, e)
        arms[lab] = {'knot': knot, 'lam': lam, 'out': out}
    ids = sorted(set(arms['old']['out']) & set(arms['new']['out']))
    d, bets = [], {'old': [], 'new': []}
    res = {'n': len(ids), 'spec': {k: (arms[k]['knot'], arms[k]['lam']) for k in arms}}
    for lab in arms:
        se = 0.0
        for i in ids:
            r, mv, side, e = arms[lab]['out'][i]
            se += (r['c'] - r['o'] - mv) ** 2
            if e is not None and e > 0:
                bets[lab].append((DU.et_day(r['date']), CM.realized(sport, mk, r, side)['clvRet']))
        res[lab] = {'sse': round(se, 1)}
        if len(bets[lab]) > 2:
            tot, t = clustered(bets[lab])
            v = [b[1] for b in bets[lab]]
            mu = sum(v) / len(v)
            res[lab].update({'bets': len(v), 'clvRet': round(mu, 4), 'se': round(math.sqrt(sum((a - mu) ** 2 for a in v) / (len(v) - 1) / len(v)), 4), 't': round(t, 2) if t else None})
    for i in ids:
        r, mo = arms['old']['out'][i][:2]
        mn = arms['new']['out'][i][1]
        y = r['c'] - r['o']
        d.append((DU.et_day(r['date']), (y - mn) ** 2 - (y - mo) ** 2))
    tot, t = clustered(d)
    res['dSse'] = round(tot, 2)
    res['t'] = None if t is None else round(t, 2)
    return res


def main():
    caps = {s: (v.get('cap') or [None, None]) for s, v in json.load(open(CM.GP_FIT))['sports'].items()}
    out = {}
    for sport in ('cfb', 'cbb'):
        old_rows, new_rows = rows_for(sport, False), rows_for(sport, True)
        ot = {str(g['id']): g['_tier'] for g in old_rows}
        diff = sum(1 for g in new_rows if ot[str(g['id'])] != g['_tier'])
        out[sport] = {'rows': len(new_rows), 'tierDiffers': diff, 'markets': {}}
        ok = True
        for mk in ('spread', 'total'):
            m = run(sport, mk, caps[sport][0 if mk == 'spread' else 1], old_rows, new_rows)
            out[sport]['markets'][mk] = m
            g_ok = ('clvRet' not in m['new'] or 'clvRet' not in m['old'] or m['new']['clvRet'] >= m['old']['clvRet'] - m['old']['se'])
            ok = ok and m['dSse'] <= 0 and g_ok
            print(sport, mk, 'tier differs', diff, '/', len(new_rows), json.dumps(m))
        out[sport]['pass'] = ok
        print(sport, 'PASS' if ok else 'FAIL')
    json.dump(out, open(os.path.join(HERE, 'results_t2.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
