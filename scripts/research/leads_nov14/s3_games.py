# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""S3-i: game-state xG as the club game model's xG input. Prereg: /mnt/project-files/leads-nov14/soccer/prereg.md.

    python3 scripts/research/leads_nov14/s3_games.py tune     # choose w, retune wx / kx (2013-22)
    python3 scripts/research/leads_nov14/s3_games.py held     # one pass on 2023-26 with the stored choice
"""
import json
import math
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import soccer_data as D
import soccer_games as G
import gsxg

OUT = os.environ.get('LEADS_OUT', '/home/user/scratch-soccer')
PKL = os.path.join(OUT, 'games_rows.pkl')
HELD = (2023, 2026)


def load_rows():
    if os.path.exists(PKL):
        return pickle.load(open(PKL, 'rb'))
    rows = G.add_inj(G.add_mv(G.add_market(D.load(G.HIST))))
    n = bad = 0
    for r in rows:
        if r.get('us') and r.get('hx') is not None:
            m = D.us_match(r['us'])
            n += 1
            if not m:
                bad += 1
                continue
            raw = gsxg.team_xg(m, 1.0)
            for w in (0.0, 0.5):
                x = gsxg.team_xg(m, w, r['hs'] if r['st'] == 'FT' else None, r['as'] if r['st'] == 'FT' else None)
                if x is None:
                    bad += 1
                    break
                r[f'gs{w}'] = [r['hx'] * x[0] / raw[0] if raw[0] > 0 else r['hx'], r['ax'] * x[1] / raw[1] if raw[1] > 0 else r['ax']]
    print('understat rows', n, 'kept raw', bad, flush=True)
    pickle.dump(rows, open(PKL, 'wb'))
    return rows


def swap(rows, w):
    out = []
    for r in rows:
        g = r.get(f'gs{w}') if w is not None else None
        if g:
            r = dict(r, hx=g[0], ax=g[1])
        out.append(r)
    return out


def per_match(rows, P, lo, hi):
    ll = {}

    def score(r, S, lh, la, R):
        if lo <= S <= hi:
            pw, pd, pl = G.wdl(lh, la, P['rho'])
            ll[r['id']] = (-math.log(max((pl, pd, pw)[G.res90(r) + 1], 1e-9)), r['day'], r['lg'])
    G.run(rows, P, score, et=True)
    return ll


def paired(a, b):
    ids = sorted(a)
    d = [b[i][0] - a[i][0] for i in ids]
    return {'n': len(d), 'base': round(sum(a[i][0] for i in ids) / len(d), 5), 'cand': round(sum(b[i][0] for i in ids) / len(d), 5),
            'd': round(sum(d) / len(d), 6), 't': G.cl_t(d, [a[i][1] for i in ids])}


def main():
    rows = load_rows()
    P = G.params()
    fn = os.path.join(OUT, 's3_games.json')
    if sys.argv[1] == 'tune':
        base = per_match(rows, P, *G.TUNE)
        res = {'base': round(sum(v[0] for v in base.values()) / len(base), 5), 'w': {}}
        for w in (0.0, 0.5):
            c = per_match(swap(rows, w), P, *G.TUNE)
            res['w'][str(w)] = paired(base, c)
            print(w, res['w'][str(w)], flush=True)
        w = min((0.0, 0.5), key=lambda w: res['w'][str(w)]['cand'])
        rw = swap(rows, w)
        Q, best = G.tune(rw, dict(P), ['wx', 'kx'])
        res.update({'pick': w, 'wx': Q['wx'], 'kx': Q['kx'], 'tuned': paired(base, per_match(rw, Q, *G.TUNE)),
                    'b5': None})
        big = {i: v for i, v in base.items() if v[2] in D.BIG5}
        c = per_match(rw, Q, *G.TUNE)
        res['b5'] = paired(big, {i: c[i] for i in big})
        json.dump(res, open(fn, 'w'), indent=1)
        print(json.dumps(res, indent=1))
    else:
        res = json.load(open(fn))
        assert 'held' not in res, 'held is scored once'
        Q = dict(P, wx=res['wx'], kx=res['kx'])
        base = per_match(rows, P, *HELD)
        c = per_match(swap(rows, res['pick']), Q, *HELD)
        res['held'] = paired(base, c)
        big = {i: v for i, v in base.items() if v[2] in D.BIG5}
        res['heldB5'] = paired(big, {i: c[i] for i in big})
        json.dump(res, open(fn, 'w'), indent=1)
        print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
