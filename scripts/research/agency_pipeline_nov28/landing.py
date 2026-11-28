# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Do agency pipelines say where a transfer lands? (Nov 28 2026)

Sample: the 2026 CFB portal cycle (data/cfb_portal.json moves) joined to the agency ledger (data/agencies.json)
through the shared name matcher. Choice set: every school in the landing fit (data/cfb_transfer_fit.json).

  baseline  a conditional logit fit on the movers with no agency on file: the level step (from x to), program
            talent, talent x his old school's talent, and log(1 + the school's other intake that cycle)
  pipe      log(1 + the agency's other clients at the school BEFORE the window): a mover's old school, everyone
            else's school on the ledger. This is the agency-to-school flow and the agency share at the school.
  co        log(1 + the agency's other clients who moved TO the school the same cycle). Not point in time (the moves
            are simultaneous); reported as an upper bound only, never a candidate to ship.
  test      the baseline coefficients stay fixed; the agency coefficient is fit leaving each client mover out and
            scored on him (leave one out, ridge 1). Pass = mean log-likelihood gain > 0 with t >= 2.

The ledger is a Nov 2026 snapshot: most client pages carry no signing date, so an agency signed after his move
counts as if it were there before. That bias favours the agency terms, so a fail is a fail; a pass would still
need the forward check on the January 2027 window (ledger frozen before it opens).
python3 scripts/research/agency_pipeline_nov28/landing.py  ->  research/agency_pipeline.json

PRE-REGISTERED (Nov 28 2026): the January 2027 window. The ledger as it stands today is truly before that window.
    --freeze   writes scripts/data/ledger/agency_pipeline_2027.json: every client's agency and school today, the
               pipe coefficient fit on 2026 and this file's hash (done Nov 28 2026)
    --score    once data/cfb_portal.json holds the 2027 cycle: the frozen ledger and coefficient only, no refit.
               Pass = mean gain > 0 with t >= 2 over the client movers, then the same in CBB if 20+ client movers.
"""
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names  # noqa: E402

OUT = os.path.join(ROOT, 'research', 'agency_pipeline.json')
LV = {'P4': 2, 'G5': 1, 'FCS': 0}


def lid(logo):
    m = re.search(r'/(\d+)\.png', logo or '')
    return m.group(1) if m else None


def clogit(Xs, ys, off=None, lam=1.0, iters=60):
    k = Xs[0].shape[1]
    b = np.zeros(k)
    for _ in range(iters):
        g = -lam * b
        H = -lam * np.eye(k)
        for i, (X, y) in enumerate(zip(Xs, ys)):
            u = X @ b + (off[i] if off is not None else 0)
            p = np.exp(u - u.max())
            p /= p.sum()
            m = p @ X
            g += X[y] - m
            H -= (X * p[:, None]).T @ X - np.outer(m, m)
        step = np.linalg.solve(H, g)
        b -= step
        if np.abs(step).max() < 1e-8:
            break
    return b


def ll(X, y, b, off=0):
    u = X @ b + off
    u = u - u.max()
    return u[y] - math.log(np.exp(u).sum())


FROZEN = os.path.join(ROOT, 'scripts', 'data', 'ledger', 'agency_pipeline_2027.json')


def main(frozen=None):
    fit = json.load(open(os.path.join(ROOT, 'data', 'cfb_transfer_fit.json')))['landing']['schools']
    ids = list(fit)
    ix = {s: i for i, s in enumerate(ids)}
    lvl = np.array([LV[fit[s][0]] for s in ids])
    tal = np.array([fit[s][1] for s in ids])
    moves = [m for m in json.load(open(os.path.join(ROOT, 'data', 'cfb_portal.json')))['moves']
             if lid(m.get('toLogo')) in ix and lid(m.get('fromLogo'))]
    intake = Counter(lid(m['toLogo']) for m in moves)
    led = frozen['rows'] if frozen else [x for x in json.load(open(os.path.join(ROOT, 'data', 'agencies.json')))['rows']
                                         if x['sport'] == 'cfb' and not x['cls'] and x['agency'] not in ('Family', 'None')]
    bykey = defaultdict(list)
    for i, m in enumerate(moves):
        bykey[names.key(m['name'])].append(i)
    # ledger school -> ESPN id through the movers' logos (every FBS school appears in the cycle)
    sid = {}
    for m in moves:
        sid.setdefault(names.team_key(m['to']), lid(m['toLogo']))
        sid.setdefault(names.team_key(m['from']), lid(m['fromLogo']))
    client = {}   # move index -> agency
    pre = []      # (agency, school id before the window, move index or None)
    for x in led:
        hit = [i for i in bykey.get(names.key(x['player']), [])
               if names.same_team(moves[i]['to'], x['school'] or '') or names.same_team(moves[i]['from'], x['school'] or '')]
        if hit:
            client[hit[0]] = x['agency']
            pre.append((x['agency'], lid(moves[hit[0]]['fromLogo']), hit[0]))
        else:
            pre.append((x['agency'], sid.get(names.team_key(x['school'] or '')), None))

    def X_of(i):
        m = moves[i]
        f = lid(m['fromLogo'])
        fl = LV[fit[f][0]] if f in fit else 0
        ft = fit[f][1] if f in fit else -1.5
        cols = []
        for d in (2, 1):
            for o in (2, 1, 0):
                cols.append(((lvl == d) & (fl == o)).astype(float))
        n_in = np.array([intake[s] - (s == lid(m['toLogo'])) for s in ids], float)
        cols += [tal, tal * ft, np.log1p(n_in)]
        return np.column_stack(cols), ix[lid(m['toLogo'])]

    def agency_cols(i):
        ag = client[i]
        p = np.zeros(len(ids))
        c = np.zeros(len(ids))
        for a, s, j in pre:
            if a != ag or j == i:
                continue
            if s in ix:
                p[ix[s]] += 1
            if j is not None:
                c[ix[lid(moves[j]['toLogo'])]] += 1
        return np.log1p(p), np.log1p(c), p, c

    base = [i for i in range(len(moves)) if i not in client]
    Xb, yb = zip(*[X_of(i) for i in base])
    bb = clogit(list(Xb), list(yb))
    cl = sorted(client)
    rows = []
    for i in cl:
        X, y = X_of(i)
        lp, lc, p, c = agency_cols(i)
        rows.append((X @ bb, y, lp, lc, p, c))
    res = {'n_movers': len(moves), 'n_base': len(base), 'n_clients': len(cl),
           'agencies': Counter(client.values()).most_common()}
    if frozen:
        b = np.array([frozen['coef']])
        g = np.array([ll(r[2][:, None], r[1], b, r[0]) - ll(np.zeros((len(ids), 1)), r[1], np.zeros(1), r[0]) for r in rows])
        t = float(g.mean() / (g.std(ddof=1) / math.sqrt(len(g))))
        res['score'] = {'gain': round(float(g.mean()), 4), 't': round(t, 2), 'pass': bool(g.mean() > 0 and t >= 2)}
        print(json.dumps(res, indent=1))
        return res
    for name, k in (('pipe', 2), ('co', 3)):
        gains = []
        for h in range(len(rows)):
            tr = [r for j, r in enumerate(rows) if j != h]
            b = clogit([r[k][:, None] for r in tr], [r[1] for r in tr], off=[r[0] for r in tr])
            o, y = rows[h][0], rows[h][1]
            gains.append(ll(rows[h][k][:, None], y, b, o) - ll(np.zeros((len(ids), 1)), y, np.zeros(1), o))
        g = np.array(gains)
        bfull = clogit([r[k][:, None] for r in rows], [r[1] for r in rows], off=[r[0] for r in rows])
        # how often the school he picked held any of his agency's other clients, against the baseline's expected rate
        cnt = 4 if k == 2 else 5
        hit = sum(1 for r in rows if r[cnt][r[1]] > 0)
        exp_ = 0.0
        for r in rows:
            u = r[0] - r[0].max()
            pr = np.exp(u) / np.exp(u).sum()
            exp_ += pr[r[cnt] > 0].sum()
        res[name] = {'coef': round(float(bfull[0]), 3), 'gain': round(float(g.mean()), 4),
                     't': round(float(g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))), 2),
                     'picked_with_client': hit, 'expected': round(exp_, 1),
                     'pass': bool(g.mean() > 0 and g.mean() / (g.std(ddof=1) / math.sqrt(len(g))) >= 2)}
    base_ll = np.mean([ll(np.zeros((len(ids), 1)), r[1], np.zeros(1), r[0]) for r in rows])
    res['base_ll'] = round(float(base_ll), 3)
    res['uniform_ll'] = round(-math.log(len(ids)), 3)
    print(json.dumps(res, indent=1))
    return res


def sparse():
    """the samples too thin to fit: CBB client transfers and HS recruits with an agency on file"""
    led = json.load(open(os.path.join(ROOT, 'data', 'agencies.json')))['rows']
    p = json.load(open(os.path.join(ROOT, 'static', 'data', 'moves', 'cbb.json')))['p']
    cbb = [x for x in led if x['sport'] == 'cbb' and not x['cls']]
    tr = [x for x in cbb if any(e[1] == 'transfer' and e[0] >= '2025-12' for e in p.get(names.key(x['player']), []))]
    rec = [x for x in led if x['cls']]
    com = [x for x in rec if x['school'] and not re.search(r'\b(HS|Prep|Academy)\b|\(', x['school'])]
    return {'cbb_client_transfers': len(tr), 'cbb_agencies_among_them': len({x['agency'] for x in tr}),
            'recruits_on_ledger': len(rec), 'recruits_committed': len(com),
            'recruits_agency_dated_before_2026_11': sum(1 for x in com if x['source_date'] and x['source_date'] < '2026-11')}


if __name__ == '__main__':
    if '--freeze' in sys.argv:
        r = main()
        rows = [{k: x[k] for k in ('player', 'school', 'agency', 'source_date')}
                for x in json.load(open(os.path.join(ROOT, 'data', 'agencies.json')))['rows']
                if x['sport'] == 'cfb' and not x['cls'] and x['agency'] not in ('Family', 'None')]
        json.dump({'frozen': '2026-11-28', 'window': 'January 2027', 'coef': r['pipe']['coef'],
                   'pass': 'mean gain > 0 with t >= 2, frozen coefficient, no refit', 'rows': rows},
                  open(FROZEN, 'w'), indent=1)
        sys.exit(0)
    if '--score' in sys.argv:
        r = main(json.load(open(FROZEN)))
        key = 'cfb_landing_2027'
    else:
        r = main()
        key = 'cfb_landing'

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    old[key] = r
    old['sparse'] = sparse()
    json.dump(old, open(OUT, 'w'), indent=1)
