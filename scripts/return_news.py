#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Reported returns as a Return% input, both sports: once a draft-eligible prospect is reported back in school
("announces return for 2025", "withdraws from the NBA draft"), or out ("declares for the NFL draft"), is the report
a better read than the declare model, and by how much?

    python3 scripts/return_news.py     # after scripts/return_drivers.py (its held-out per-row odds); -> data/return_drivers.json "news"

Pools: the rows scripts/return_drivers.py scores held out (CFB: each draft's fall PFF board prospects, odds from
leave one draft out; CBB: Barttorvik prospects in the board years, stage A + board, leave one draft out). Reports:
Google News search RSS headlines (scripts/college_returns.py: gnews, Index, reading, about), dated inside the
decision window before the deadline: CFB Nov 20 - Jan 15 (the NFL's early-entry deadline), CBB Mar 15 - May 28
(the NCAA withdrawal date). A headline counts for a player only through the clause that names him.
Lock: a reported return sets P(declare) to the report rate among the other cycles' reported returners (Laplace);
a reported declaration likewise. Test: per-row paired log loss on the reported players against the model's own
held-out odds, t, and cycles won. Gate: t <= -2 and 2 of 3 cycles.
"""
import datetime as dt, json, math, os, re, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names
import college_returns as CR

PRED = os.path.join(HERE, '.cache', 'return_preds.json')
CACHE = os.path.join(HERE, '.cache', 'return_news')
OUT = os.path.join(ROOT, 'data', 'return_drivers.json')
os.makedirs(CACHE, exist_ok=True)

WINDOW = {'cfb': lambda y: (dt.date(y - 1, 11, 20), dt.date(y, 1, 16)), 'cbb': lambda y: (dt.date(y, 3, 15), dt.date(y, 5, 29))}
CYCLES = {'cfb': (2023, 2024, 2025), 'cbb': (2024, 2025, 2026)}
Q = {
    'cfb': ['("return for {y}" OR "returning for {y}" OR "back for {y}" OR "return in {y}") football',
            '("announces return" OR "will return to" OR "decides to return" OR "decision to return" OR "returning to school") football',
            '("forgo" OR "forgoes" OR "bypass" OR "bypasses" OR "skip" OR "skips" OR "passes on" OR "return to school") "NFL draft"',
            '("declares for" OR "will enter" OR "enters" OR "entering") "NFL draft" college football'],
    'cbb': ['("return for" OR "returning for" OR "back for" OR "return to") "{s}" basketball',
            '("withdraws from" OR "withdrawing from" OR "pulls out of" OR "pulls name out of" OR "return to school" OR "returning to school") "NBA draft"',
            '("announces return" OR "will return to" OR "decides to return" OR "decision to return" OR "staying at") basketball',
            '("declares for" OR "will enter" OR "enters" OR "staying in" OR "keep his name in" OR "remain in") "NBA draft"'],
}
# draft-specific return wording college_returns.reading doesn't read
DRAFT_RET = re.compile(r"\b(forgo(es|ing)?|bypass(es|ing)?|skip(s|ping)?|pass(es|ing)? on|withdraw(s|ing|n)?( his name)? from|pull(s|ing|ed)? (out of|(his )?name (out of|from))|"
                       r"turn(s|ing|ed)? down)\b[\w .'-]{0,25}\b(nfl|nba) draft\b|\breturn(s|ing)? to school\b|\bwithdraws?\b|\bwill return to\b", re.I)
SPEC = re.compile(r"\?|\bcould\b|\bmight\b|\bmay\b|\bwould\b|\bif\b|\bwhether\b|\bexpected\b|\bconsider|\bweigh|\bundecided\b|"
                  r"\brumou?r|\bchances?\b|\breasons?\b|\bshould\b|\bpredict|\bmock\b|\bwatch\b|\btracker\b|\bodds\b|\bwho\b|\btop \d+\b|\bplayers\b", re.I)


def read(t, sport, target):
    """'return', 'out' or None for one clause"""
    if SPEC.search(t): return None
    if DRAFT_RET.search(t): return 'return'
    k, _ = CR.reading(t, target, sport)
    return k


def headlines(sport, y):
    f = os.path.join(CACHE, f'{sport}_{y}.json')
    if os.path.exists(f): return json.load(open(f))
    d0, end = WINDOW[sport](y); items = []
    season = f'{y}-{(y + 1) % 100:02d}'
    qs = [q.format(y=y, s=season) for q in Q[sport]]
    while d0 < end:
        d1 = min(d0 + dt.timedelta(days=5), end)
        for q in qs:
            try: items += CR.gnews(q + f' after:{d0} before:{d1}')
            except RuntimeError as e: print(e)
            time.sleep(0.5)
        d0 = d1
    json.dump(items, open(f, 'w'))
    return items


def reports(sport, y, pool):
    """newest in-window report per pool row (index into pool) -> (kind, date, title)"""
    d0, end = WINDOW[sport](y)
    ix = CR.Index([{**r, '_teams': [r['team']], 'fv': -(r.get('nb') or r.get('rank') or 999)} for r in pool])
    target = y if sport == 'cfb' else y + 1
    got = {}
    for it in headlines(sport, y):
        if not (str(d0) <= it['date'][:10] < str(end)): continue
        t = it['title']
        if CR.PRO[sport].search(t) and not re.search(r'\bdraft\b', t, re.I): continue
        for r in ix.find(t):
            last = names.key(r['name']).split()[-1]
            kinds = {read(c, sport, target) for c in CR.CLAUSE.split(t) if last in names.key(c).split()}
            kinds.discard(None)
            if len(kinds) != 1: continue
            k = kinds.pop(); i = r['_i']
            if i not in got or it['date'] > got[i][1]: got[i] = (k, it['date'], t[:160])
    return got


def ll(p, y): p = min(max(p, 1e-4), 1 - 1e-4); return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def main():
    P = json.load(open(PRED)); res = {}
    for sport in ('cfb', 'cbb'):
        rows = P[sport]
        for i, r in enumerate(rows): r['_i'] = i
        rep = {}
        for y in CYCLES[sport]:
            pool = [r for r in rows if r['year'] == y]
            if not pool: continue
            got = reports(sport, y, pool)
            for i, v in got.items(): rep[i] = v
            print(sport, y, 'pool', len(pool), 'reports', len(got), {k: sum(1 for v in got.values() if v[0] == k) for k in ('return', 'out')})
        S = {'cycles': list(CYCLES[sport]), 'kinds': {}}
        for kind in ('return', 'out'):
            R = [(rows[i], v) for i, v in rep.items() if v[0] == kind]
            if not R: S['kinds'][kind] = {'n': 0}; continue
            Lm, Ll, cyc = [], [], []
            for r, v in R:
                oth = [x['y'] for x, w in R if x['year'] != r['year']]
                q = (sum(oth) + 0.5) / (len(oth) + 1) if oth else 0.5
                Lm.append(ll(r['p'], r['y'])); Ll.append(ll(q, r['y'])); cyc.append(r['year'])
            d = np.array(Ll) - np.array(Lm); cyc = np.array(cyc)
            ys = [r['y'] for r, _ in R]
            lead = [(dt.date.fromisoformat(v[1][:10]) - WINDOW[sport](r['year'])[1]).days for r, v in R]
            S['kinds'][kind] = {'n': len(R), 'declared': round(float(np.mean(ys)), 3), 'model': round(float(np.mean([r['p'] for r, _ in R])), 3),
                                'lockRate': round((sum(ys) + 0.5) / (len(ys) + 1), 3),
                                'logLossModel': round(float(np.mean(Lm)), 4), 'logLossLock': round(float(np.mean(Ll)), 4),
                                't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2) if len(d) > 2 and d.std() > 0 else 0.0,
                                'cyclesWon': int(sum(d[cyc == c].mean() < 0 for c in set(cyc))), 'cycles': len(set(cyc)),
                                'daysBeforeDeadline': int(np.median(lead)),
                                'breakers': [{'name': r['name'], 'team': r['team'], 'year': r['year'], 'title': v[2]} for r, v in R if r['y'] != (kind == 'out')][:12]}
            k = S['kinds'][kind]; k['pass'] = bool(k['t'] <= -2 and k['cyclesWon'] >= 2)
            print(sport, kind, {a: b for a, b in k.items() if a != 'breakers'})
        res[sport] = S
    out = json.load(open(OUT)); out['news'] = res
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
