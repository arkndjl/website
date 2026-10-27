#!/usr/bin/env python3
"""Novig vs DraftKings as the closing reference, scored on finished games (Oct 27 2026).

Joins each game's last pregame row in scripts/data/odds_novig/ (scripts/novig.py) with its last pregame row and final in
scripts/data/odds_dense/ (scripts/odds_snap.py, DraftKings through ESPN), on the ESPN id. Per sport: games, moneyline
log loss of each no-vig close (paired, Novig minus DraftKings, clustered by day via harness.paired), spread and total
MAE of each closing number, and median holds.

    python3 scripts/novig_compare.py            # -> data/novig_compare.json
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def rows(d, sport):
    out = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.startswith(sport + '-') and fn.endswith('.jsonl'):
                out += [json.loads(x) for x in open(os.path.join(d, fn)) if x.strip()]
    return out


def closes(rs, key):
    """{espn id: last pregame row with the row's fields carried forward}, {espn id: final}"""
    cur, fin = {}, {}
    for r in sorted(rs, key=lambda r: r['t']):
        gid = r.get(key)
        if gid is None:
            continue
        if 'fin' in r:
            fin[gid] = r['fin']
            continue
        if r['t'] >= r.get('k', '9'):
            continue
        cur[gid] = {**cur.get(gid, {}), **{k: v for k, v in r.items() if v is not None}}
    return cur, fin


def nv_ml(r):
    a, b = r.get('mlH'), r.get('mlA')
    if a is None or b is None:
        return None, None
    p = [100 / (o + 100) if o > 0 else -o / (-o + 100) for o in (a, b)]
    return p[0] / sum(p), sum(p) - 1


def score(sport):
    import harness
    dk, fin = closes(rows(os.path.join(HERE, 'data', 'odds_dense'), sport), 'id')
    nv, _ = closes(rows(os.path.join(HERE, 'data', 'odds_novig'), sport), 'id')
    ll_d, ll_n, sp, tt, hd, hn, day = [], [], [], [], [], [], []
    for gid, n in nv.items():
        d, f = dk.get(gid), fin.get(gid)
        if not d or not f:
            continue
        margin, total = f[0] - f[1], f[0] + f[1]
        pd, hdk = nv_ml(d)
        if pd is not None and n.get('pH') is not None and margin != 0:
            y = 1.0 if margin > 0 else 0.0
            ll = lambda p: -(y * math.log(p) + (1 - y) * math.log(1 - p))
            ll_d.append(ll(min(max(pd, 1e-4), 1 - 1e-4)))
            ll_n.append(ll(min(max(n['pH'], 1e-4), 1 - 1e-4)))
            day.append(n['k'][:10])
            hd.append(hdk)
            hn.append(n.get('hML'))
        if d.get('L') is not None and n.get('L') is not None:
            sp.append((abs(margin - d['L']), abs(margin - n['L'])))
        if d.get('T') is not None and n.get('T') is not None:
            tt.append((abs(total - d['T']), abs(total - n['T'])))
    med = lambda v: None if not v else sorted(v)[len(v) // 2]
    out = {'games': len(ll_d), 'llDK': None, 'llNovig': None}
    if ll_d:
        out.update(llDK=round(sum(ll_d) / len(ll_d), 4), llNovig=round(sum(ll_n) / len(ll_n), 4),
                   holdDK=med([h for h in hd if h is not None]), holdNovig=med([h for h in hn if h is not None]))
        if len(ll_d) >= 20:
            pr = harness.paired(ll_n, ll_d, cluster=day)
            out['llT'] = round(pr['t'], 2)
    for name, v in (('spread', sp), ('total', tt)):
        if v:
            out[name] = {'n': len(v), 'maeDK': round(sum(a for a, _ in v) / len(v), 3), 'maeNovig': round(sum(b for _, b in v) / len(v), 3)}
    return out


if __name__ == '__main__':
    res = {s: score(s) for s in ('cfb', 'nfl', 'cbb', 'nba')}
    json.dump(res, open(os.path.join(ROOT, 'data', 'novig_compare.json'), 'w'), indent=1)
    print(json.dumps(res, indent=1))
