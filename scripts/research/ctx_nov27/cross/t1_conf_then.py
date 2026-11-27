#!/usr/bin/env python3
"""T1 (prereg.md): pick-rule segment labels, today's conference map vs the game's own season. Read-only: writes
results_t1.json beside this file, nothing in data/. No live 2026-27 record is read.

    python3 scripts/research/ctx_nov27/cross/t1_conf_then.py"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import games_picks as G      # noqa: E402
import units as DU           # noqa: E402

FAMS = ('tier', 'game', 'conf')
EVAL = {'cfb': lambda S: S >= 2021, 'cbb': lambda S: S == 2026}


def tune_rules(tp, key, mk):
    """fit_segments' tuning step: per family value the X with the best shrunk tuning clvRet (25+ picks, > 0)"""
    rules = {}
    for fam in FAMS:
        vals = sorted({e[key][fam] for e in tp if fam in e[key]})
        best = {}
        for x in G.RULE_GRID[mk]:
            px = [e['clvRet'] for e in tp if e['gap'] >= x]
            if len(px) < G.SEG_MIN_TUNE:
                continue
            mu = sum(px) / len(px)
            st = {}
            for v in vals:
                xs = [e['clvRet'] for e in tp if e['gap'] >= x and e[key].get(fam) == v]
                if len(xs) >= 5:
                    m_ = sum(xs) / len(xs)
                    st[v] = (m_, sum((a - m_) ** 2 for a in xs) / max(1, len(xs) - 1), len(xs))
            if len(st) < 2:
                continue
            ms = [a[0] for a in st.values()]
            mm = sum(ms) / len(ms)
            tau2 = max(0.0, sum((a - mm) ** 2 for a in ms) / (len(ms) - 1) - sum(a[1] / a[2] for a in st.values()) / len(st))
            for v, (m_, s2, n) in st.items():
                B = tau2 / (tau2 + s2 / n) if tau2 + s2 / n > 0 else 0.0
                sh = mu + B * (m_ - mu)
                if n >= G.SEG_MIN_TUNE and sh > 0 and (v not in best or sh > best[v][1]):
                    best[v] = (x, sh)
        for v, (x, sh) in best.items():
            rules[(fam, v)] = x
    return rules


def clustered(vals):
    """(sum, mean per row, t) of rows [(slate, value)], t on slate sums"""
    by = {}
    for s, v in vals:
        by[s] = by.get(s, 0.0) + v
    n, k = len(vals), len(by)
    tot = sum(by.values())
    if k < 2 or not n:
        return tot, None, None
    m = tot / k
    sd = math.sqrt(sum((a - m) ** 2 for a in by.values()) / (k - 1))
    return tot, tot / n, (m / (sd / math.sqrt(k)) if sd else None)


def main():
    F = json.load(open(G.FIT))['sports']
    out = {}
    for sport in ('cfb', 'cbb'):
        rows = [r for r in G.load_wf(sport) if r.get('res') is not None]
        tune = set(G.RULE_TUNE[sport])
        caps = F.get(sport, {}).get('cap') or [None, None]
        res = {'markets': {}}
        pool = {'old': [], 'new': [], 'd': []}
        for mk in ('spread', 'total'):
            rs = [r for r in rows if (r.get('Lo') if mk == 'spread' else r.get('To')) is not None]
            allp = G.rule_bets(sport, rs, mk, G.RULE_GRID[mk][0], True, caps[0] if mk == 'spread' else caps[1])
            for lab, flag in (('old', set()), ('new', {'cfb', 'cbb'})):
                G.CONF_THEN = flag
                for e in allp:
                    sg = G.seg_of(sport, e['g'], mk, e['side'], e['line'])
                    e[lab] = {f: sg[f] for f in FAMS if f in sg}
            G.CONF_THEN = {'cbb'}
            tp = [e for e in allp if e['S'] in tune]
            ep = [e for e in allp if e['S'] not in tune and EVAL[sport](e['S'])]
            diff = sum(1 for e in allp if e['old'] != e['new'])
            R = {lab: tune_rules(tp, lab, mk) for lab in ('old', 'new')}
            m = {'picksAtMinX': len(allp), 'labelsDiffer': diff, 'evalN': len(ep),
                 'rules': {lab: {f'{k[0]}={k[1]}': x for k, x in sorted(R[lab].items())} for lab in R}}
            sel = {}
            for lab in ('old', 'new'):
                # serve labels are as-it-stood, whatever labels the rule was tuned on
                sel[lab] = [e for e in ep if any(e['new'].get(f) == v and e['gap'] >= x for (f, v), x in R[lab].items())]
                tot, mu, t = clustered([(DU.et_day(e['g']['date']), e['clvRet']) for e in sel[lab]])
                m[lab] = {'n': len(sel[lab]), 'sum': round(tot, 3), 'clvRet': None if mu is None else round(mu, 4), 't': None if t is None else round(t, 2)}
                pool[lab] += [(DU.et_day(e['g']['date']), e['clvRet']) for e in sel[lab]]
            io, inn = {id(e) for e in sel['old']}, {id(e) for e in sel['new']}
            d = [(DU.et_day(e['g']['date']), e['clvRet'] * ((id(e) in inn) - (id(e) in io))) for e in ep if (id(e) in io) != (id(e) in inn)]
            tot, mu, t = clustered(d)
            m['diff'] = {'n': len(d), 'sum': round(tot, 3), 't': None if t is None else round(t, 2)}
            pool['d'] += d
            res['markets'][mk] = m
        for lab in ('old', 'new'):
            tot, mu, t = clustered(pool[lab])
            res[lab] = {'n': len(pool[lab]), 'sum': round(tot, 3), 'clvRet': None if mu is None else round(mu, 4), 't': None if t is None else round(t, 2)}
        tot, mu, t = clustered(pool['d'])
        res['diff'] = {'n': len(pool['d']), 'sum': round(tot, 3), 't': None if t is None else round(t, 2)}
        res['pass'] = bool(tot >= 0 and (res['new']['clvRet'] or 0) > 0)
        out[sport] = res
        print(sport, 'old', res['old'], 'new', res['new'], 'diff', res['diff'], 'PASS' if res['pass'] else 'FAIL')
        for mk, m in res['markets'].items():
            print('  ', mk, 'labels differ', m['labelsDiffer'], '/', m['picksAtMinX'], 'old', m['old'], 'new', m['new'], 'diff', m['diff'])
    with open(os.path.join(HERE, 'results_t1.json'), 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
