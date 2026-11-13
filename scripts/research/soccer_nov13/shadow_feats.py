#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-match features and the close's own lean for every big-five league match of the walk-forward record:
    t = 1/2 log(market goals home / away) - 1/2 log(model goals home / away)
the amount (log goals, each way) the closing price sits from the game model. Written to a pickle for shadow.py."""
import math
import os
import pickle
import sys
from collections import defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine as E
import soccer_data as D
import soccer_games as G

OUT = os.environ.get('SHADOW_PKL', os.path.join(HERE, 'shadow_rows.pkl'))


def collect(rows, P):
    recs = []
    hist = defaultdict(lambda: {'mres': deque(maxlen=6), 'gres': deque(maxlen=6), 'xres': deque(maxlen=6)})
    pend = {}
    MV = D.load(G.MVF)
    cps, sq, e2t = MV['cp'], MV['sq'], MV['espn2tm']

    def mv_at(t, day, back=0):
        tm = e2t.get(t)
        i = len(cps) - 1
        while i >= 0 and cps[i] > day:
            i -= 1
        i -= back
        return sq[cps[i]].get(tm) if tm is not None and i >= 0 else None

    def side(R, r, t, st):
        h = hist[t]
        L = R.lg.get(t)
        m, x = R.sub['m'], R.sub['x']
        f = {}
        for k, nm in (('mres', 'm'), ('gres', 'g'), ('xres', 'x')):
            v = list(h[k])
            f[nm + '1'] = v[-1] if v else 0.0
            f[nm + '3'] = sum(v[-3:]) / 3 if v else 0.0
            f[nm + '6'] = sum(v) / 6 if v else 0.0
        f['xm'] = (x['a'][t] + x['d'][t] - m['a'][t] - m['d'][t]) if t in x['has'] and t in m['has'] else 0.0
        f['gm'] = (R.a[t] + R.d[t] - m['a'][t] - m['d'][t]) if t in m['has'] else 0.0
        S = D.season_of(r['day'], r['lg'])
        f['new'] = float(R.home_lg.get((t, S - 1)) != r['lg'])
        f['early'] = max(0.0, 1 - R.n[t] / 6)
        a, b = mv_at(t, r['day']), mv_at(t, r['day'], 1)
        f['dmv'] = (a - b) if a is not None and b is not None else 0.0
        g = R.gap(t, G.lday(r))
        f['r3'] = float(g <= 3)
        f['r8'] = float(8 <= g <= 20)
        if st:
            lf = st['left']
            f['any3'] = st['any'] * float(lf <= 3)
            f['any6'] = st['any'] * float(4 <= lf <= 6)
            f['champ'] = st['champ'] * float(lf <= 6)
            f['down'] = st['down'] * float(lf <= 6)
        else:
            f['any3'] = f['any6'] = f['champ'] = f['down'] = 0.0
        return f

    def stakes(R, r):
        lg = r['lg']
        S = D.season_of(r['day'], lg)
        T = R.tab.get((lg, S))
        sch = R.sched.get((lg, S))
        if not T or not sch or len(T) < len(sch) or r['h'] not in T or r['a'] not in T:
            return None
        N = len(sch)
        order = sorted(T, key=lambda t: -T[t][0])
        pts = [T[t][0] for t in order]
        out = []
        for t in (r['h'], r['a']):
            p, g = T[t][0], sch[t] - T[t][1]
            rk = order.index(t) + 1
            live = {}
            for nm, b in (('title', 1), ('top4', 4), ('top6', 6), ('drop', N - 3)):
                if rk <= b:
                    live[nm] = int(pts[b] + 3 * (sch[order[b]] - T[order[b]][1]) >= p)
                else:
                    live[nm] = int(p + 3 * g >= pts[b - 1])
            out.append({'left': g, 'any': int(any(live.values())), 'champ': int(rk == 1 and not live['title']),
                        'down': int(rk > N - 3 and not live['drop'])})
        return out

    def score(r, S, lh, la, R):
        if r['lg'] not in D.BIG5 or r['st'] != 'FT':
            return
        st = stakes(R, r)
        fh = side(R, r, r['h'], st[0] if st else None)
        fa = side(R, r, r['a'], st[1] if st else None)
        X = {k: fh[k] - fa[k] for k in fh}
        X['mvz'] = r.get('mvz', 0.0)
        X['mvz_early'] = r.get('mvz', 0.0) * max(0.0, 1 - min(R.n[r['h']], R.n[r['a']]) / 6)
        X['avz'] = r.get('avz', 0.0)
        c = G.close_probs(r)
        t = None
        if r.get('mh') is not None and c:
            t = 0.5 * math.log(r['mh'] / r['ma']) - 0.5 * math.log(lh / la)
        recs.append({'id': r['id'], 'S': S, 'day': r['day'], 'lg': r['lg'], 'lh': lh, 'la': la, 't': t, 'c': c,
                     'res': G.res90(r), 'hs': r['hs'], 'as': r['as'], 'X': X})
        pend[r['id']] = (lh, la, t)

    def keep(r, R):
        v = pend.pop(r['id'], None)
        if v is None:
            return
        lh, la, t = v
        gr = ((min(r['hs'], 6) - lh) - (min(r['as'], 6) - la)) / 2
        for tm, sg in ((r['h'], 1), (r['a'], -1)):
            h = hist[tm]
            if t is not None:
                h['mres'].append(sg * t)
            h['gres'].append(sg * gr)
            if r.get('hx') is not None:
                h['xres'].append(sg * ((r['hx'] - lh) - (r['ax'] - la)) / 2)
    G.run(rows, P, score, keep)
    return recs


if __name__ == '__main__':
    rows = E.load_rows()
    P = G.params()
    recs = collect(rows, P)
    pickle.dump(recs, open(OUT, 'wb'))
    print(len(recs), sum(r['t'] is not None for r in recs))
