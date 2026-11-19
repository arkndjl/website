#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Join Polymarket tennis moneyline events to history rows (same tour, same pair through scripts/names.py, event
start inside the tournament's window) -> <PM_CACHE>/tennis_join.pkl: [{ev, tok, t0, vol, ri (row index), flip
(True when the token's player is the row's loser)}]."""
import pickle, datetime as dt
from tcommon import *
import pm


def moneyline(e):
    for m in e['m']:
        if m['smt'] == 'moneyline' and m['t0'] and m['tok']:
            o = json.loads(m['o'])
            if len(o) == 2: return m, o
    return None, None


def build():
    out_p = os.path.join(pm.CACHE, 'tennis_join.pkl')
    if os.path.exists(out_p): return pickle.load(open(out_p, 'rb'))
    rows, players, tn = load_rows()
    R = Resolver(players, rows, 20240101)
    idx = {}
    for i, r in enumerate(rows):
        if r[0] >= 20250901: idx.setdefault(frozenset((r[7], r[8])), []).append(i)
    out, miss = [], {'name': 0, 'row': 0, 'ml': 0}
    for tour in ('atp', 'wta'):
        for line in open(os.path.join(pm.CACHE, f'list_{tour}.jsonl')):
            e = json.loads(line)
            m, o = moneyline(e)
            if not m: miss['ml'] += 1; continue
            a, b = R.pid(o[0], tour), R.pid(o[1], tour)
            if not a or not b: miss['name'] += 1; continue
            t0 = pm.ts(m['t0'])
            od = t0.date().toordinal()
            c = [i for i in idx.get(frozenset((a, b)), []) if -3 <= od - dord(rows[i][0]) <= 16]
            if not c: miss['row'] += 1; continue
            i = min(c, key=lambda i: abs((t0.date() - M.DAY0).days - M.dnum(rows[i][0], rows[i][4], rows[i][2], rows[i][6])))
            out.append({'ev': e['id'], 'tok': json.loads(m['tok'])[0], 't0': t0.timestamp(), 'vol': e['vol'] or 0, 'ri': i,
                        'flip': rows[i][7] != a, 'tour': tour, 'res': m['res'], 'lg': e['lg']})
    print('joined', len(out), 'missed', miss)
    pickle.dump(out, open(out_p, 'wb'))
    return out


if __name__ == '__main__':
    import collections
    J = build()
    rows, players, tn = load_rows()
    c = collections.Counter((rows[j['ri']][2], M.is_qual(rows[j['ri']][4])) for j in J)
    print(sorted(c.items(), key=lambda x: -x[1]))
    # result agreement (winner's token should have resolved to 1)
    ok = bad = 0
    for j in J:
        try: res = json.loads(j['res'])
        except Exception: continue
        if res[0] in ('1', '0'):
            if (res[0] == '1') != j['flip']: ok += 1
            else: bad += 1
    print('winner agrees', ok, 'disagrees', bad)
