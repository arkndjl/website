# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""S1: the value of the squad actually called up (Transfermarkt matchday squads of the nation's earlier matches)
against the top-23-by-citizenship squad term of the national-team model. Prereg:
/mnt/project-files/leads-nov14/soccer/prereg.md.

    python3 scripts/research/leads_nov14/s1_intl.py data      # join + coverage, no scores
    python3 scripts/research/leads_nov14/s1_intl.py tune      # choose (sq_c, sq_r) on 2000-15
    python3 scripts/research/leads_nov14/s1_intl.py held      # one pass on 2016 to Jul 2026
"""
import bisect
import datetime as dt
import glob
import json
import math
import os
import pickle
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_intl as I

OUT = os.environ.get('LEADS_OUT', '/home/user/scratch-soccer')
TMC = os.path.join(I.CACHE, 'tm')
PKL = os.path.join(OUT, 'intl_rows.pkl')
HELD_END = '2026-07-31'
WINDOW, STALE, MINP, TOPN = 12, 400, 14, 18
GC = [0, .04, .08, .12, .16, .20, .24, .28, .32]
GR = [0, .04, .08, .13, .17]


def day_add(d, k):
    return (dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat()


def tm_data():
    clubs = {}
    for p in glob.glob(os.path.join(TMC, 'club', '*.json')):
        c = json.load(open(p))
        if c.get('nat') and c.get('main') == c.get('id'):
            clubs[c['id']] = c['name']
    games = {}
    for p in glob.glob(os.path.join(TMC, 'fx', '*.json')):
        for g in json.load(open(p)):
            if g.get('fin') and g.get('id') and g['h'] in clubs and g['a'] in clubs and g.get('d'):
                games[g['id']] = g
    return clubs, games


def name_map(clubs, games, rows):
    """Transfermarkt national team id -> the history's name: the same name where it exists, else by votes over
    matches sharing the day (+-1), the score and an already-named opponent"""
    names = {r['h'] for r in rows} | {r['a'] for r in rows}
    mp = {i: I.tm_to_mj(n) for i, n in clubs.items() if I.tm_to_mj(n) in names}
    idx = defaultdict(list)
    for r in rows:
        if r['day'] >= '2003-12-01':
            idx[r['day']].append(r)
    for _ in range(2):
        votes = defaultdict(Counter)
        for g in games.values():
            if g.get('hs') is None or (g['h'] in mp) == (g['a'] in mp):
                continue
            known, new, flip = (g['h'], g['a'], False) if g['h'] in mp else (g['a'], g['h'], True)
            for k in (-1, 0, 1):
                for r in idx.get(day_add(g['d'], k), []):
                    for a, b, hs, as_ in ((r['h'], r['a'], r['hs'], r['as']), (r['a'], r['h'], r['as'], r['hs'])):
                        if a == mp[known] and {hs, as_} == {g['hs'], g['as']}:
                            votes[new][b] += 1
        for i, v in votes.items():
            (n, c), = v.most_common(1)
            if c >= 2 and n not in mp.values():
                mp[i] = n
    return mp


def squads(mp):
    """nation -> sorted [(day, game id, {player: value}, opponent)] over its Transfermarkt matches with a squad list"""
    out = defaultdict(list)
    for p in glob.glob(os.path.join(TMC, 'g', '*.json')):
        g = json.load(open(p))
        if not g or not g.get('d'):
            continue
        for s, o in (('h', 'a'), ('a', 'h')):
            t = mp.get((g[s] or {}).get('id'))
            sq = {x[0]: x[1] for x in (g[s].get('xi') or []) + (g[s].get('sub') or []) if x[0]}
            if t and len(sq) >= 11:
                out[t].append((g['d'], g['id'], sq, mp.get((g[o] or {}).get('id'))))
    for v in out.values():
        v.sort(key=lambda x: (x[0], x[1]))
    return out


def q_of(sq):
    v = sorted((x for x in sq.values() if x), reverse=True)
    if len(v) < MINP:
        return None
    return math.log1p(sum(v[:TOPN]) / 1e6)


def attach(rows, SQ):
    days = {t: [x[0] for x in v] for t, v in SQ.items()}
    for r in rows:
        for s, o in (('h', 'a'), ('a', 'h')):
            v = SQ.get(r[s])
            if not v:
                continue
            d = days[r[s]]
            # the match's own page: same opponent within a day
            own = None
            lo = bisect.bisect_left(d, day_add(r['day'], -1))
            for i in range(lo, min(len(v), lo + 6)):
                if v[i][0] <= day_add(r['day'], 1) and v[i][3] == r[o]:
                    own = i
                    break
            if own is not None:
                r['qo' + s] = q_of(v[own][2])
            end = own if own is not None else bisect.bisect_left(d, r['day'])      # strictly earlier matches
            end = min(end, bisect.bisect_left(d, r['day']))
            pre = {}
            i = end - 1
            w0 = day_add(r['day'], -WINDOW)
            while i >= 0 and v[i][0] >= w0:
                for p, x in v[i][2].items():
                    pre.setdefault(p, x)                                         # latest page first
                i -= 1
            src = 'w'
            if not pre and end - 1 >= 0 and v[end - 1][0] >= day_add(r['day'], -STALE):
                pre, src = dict(v[end - 1][2]), 'p'
            q = q_of(pre) if pre else None
            if q is not None:
                r['qc' + s], r['qs' + s] = q, src
    return rows


def load_rows():
    if os.path.exists(PKL):
        return pickle.load(open(PKL, 'rb'))
    rows, _, _ = I.load()
    rows = [r for r in rows if r['day'] <= HELD_END]
    I.attach_sq(rows)
    clubs, games = tm_data()
    mp = name_map(clubs, games, rows)
    SQ = squads(mp)
    attach(rows, SQ)
    print('nations named', len(mp), 'of', len(clubs), '| with squads', len(SQ), flush=True)
    pickle.dump(rows, open(PKL, 'wb'))
    return rows


def variant(rows, P, sc_, sr_, key='qc'):
    out = []
    for r in rows:
        a, b = r.get(key + 'h'), r.get(key + 'a')
        if a is not None and b is not None and 'qh' in r:
            r = dict(r, qh=(sc_ * a + sr_ * r['qh']) / P['sq'], qa=(sc_ * b + sr_ * r['qa']) / P['sq'])
        out.append(r)
    return out


def per_match(rows, P, lo, hi):
    _, sc = I.run(rows, P, lo, hi, keep=True)
    return {(x[0]['day'], x[0]['h'], x[0]['a']): -math.log(max(x[1 + I.outcome(x[0])], 1e-9)) for x in sc}


def tday(d, keys):
    g = defaultdict(float)
    m = sum(d) / len(d)
    for x, k in zip(d, keys):
        g[k] += x - m
    se = math.sqrt(sum(v * v for v in g.values())) / len(d)
    return m, (m / se if se else 0.0)


def paired(a, b, only=None):
    ks = [k for k in sorted(a) if only is None or k in only]
    d = [b[k] - a[k] for k in ks]
    m, t = tday(d, [k[0] for k in ks])
    return {'n': len(ks), 'base': round(sum(a[k] for k in ks) / len(ks), 5), 'cand': round(sum(b[k] for k in ks) / len(ks), 5),
            'd': round(m, 6), 't': round(t, 2)}


def main():
    rows = load_rows()
    P = I.params()
    fn = os.path.join(OUT, 's1_intl.json')
    both = {(r['day'], r['h'], r['a']) for r in rows if r.get('qch') is not None and r.get('qca') is not None and 'qh' in r}
    orc = {(r['day'], r['h'], r['a']) for r in rows if r.get('qoh') is not None and r.get('qoa') is not None and 'qh' in r}
    if sys.argv[1] == 'data':
        by = defaultdict(lambda: [0, 0, 0, 0])
        for r in rows:
            if r['day'] >= '2000-01-01':
                e = by[r['day'][:4]]
                k = (r['day'], r['h'], r['a'])
                e[0] += 1; e[1] += k in both; e[2] += k in orc
                e[3] += r.get('qsh') == 'w' and r.get('qsa') == 'w'
        for y, e in sorted(by.items()):
            print(y, e)
        return
    if sys.argv[1] == 'tune':
        base = per_match(rows, P, *I.TUNE)
        res = {'P_sq': P['sq'], 'grid': {}, 'oracleGrid': {}}
        for key, lab in (('qc', 'grid'), ('qo', 'oracleGrid')):
            for c in GC:
                for rr in GR:
                    ll = per_match(variant(rows, P, c, rr, key), P, *I.TUNE)
                    res[lab][f'{c},{rr}'] = round(sum(ll.values()) / len(ll), 6)
                print(lab, c, [res[lab][f'{c},{rr}'] for rr in GR], flush=True)
        res['base'] = round(sum(base.values()) / len(base), 6)
        for key, lab, sub in (('qc', 'pick', both), ('qo', 'oraclePick', orc)):
            g = res['grid' if key == 'qc' else 'oracleGrid']
            c, rr = map(float, min(g, key=g.get).split(','))
            ll = per_match(variant(rows, P, c, rr, key), P, *I.TUNE)
            res[lab] = {'sq_c': c, 'sq_r': rr, 'all': paired(base, ll), 'differ': paired(base, ll, sub)}
        json.dump(res, open(fn, 'w'), indent=1)
        print(json.dumps({k: v for k, v in res.items() if 'rid' not in k}, indent=1))
    else:
        res = json.load(open(fn))
        assert 'held' not in res, 'held is scored once'
        base = per_match(rows, P, I.HOLD, HELD_END)
        for key, lab, out, sub in (('qc', 'pick', 'held', both), ('qo', 'oraclePick', 'heldOracle', orc)):
            c, rr = res[lab]['sq_c'], res[lab]['sq_r']
            ll = per_match(variant(rows, P, c, rr, key), P, I.HOLD, HELD_END)
            res[out] = {'all': paired(base, ll), 'differ': paired(base, ll, sub)}
        json.dump(res, open(fn, 'w'), indent=1)
        print(json.dumps({k: v for k, v in res.items() if 'rid' not in k}, indent=1))


if __name__ == '__main__':
    main()
