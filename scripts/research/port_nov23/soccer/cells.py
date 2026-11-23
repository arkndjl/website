#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer port pass Nov 23 2026: game-model cells C1-C6 (prereg.md here). Rows dated 2026-07-01 or later are dropped
(lockbox). Tune S 2013-22, held S 2023-26 one pass.

    SOCCER_ROWS_PKL=<pkl> python3 scripts/research/port_nov23/soccer/cells.py tune
    SOCCER_ROWS_PKL=<pkl> python3 scripts/research/port_nov23/soccer/cells.py held
"""
import bisect
import datetime as dt
import gzip
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, 'research', 'soccer_nov13'))
import soccer_data as D            # noqa: E402
import soccer_games as G           # noqa: E402
import soccer_tm_injuries as TI    # noqa: E402
import engine                      # noqa: E402

LOCK = '2026-07-01'
OUT = os.path.join(HERE, 'results.json')


# ------------------------------------------------------------ features
def usm(r):
    p = os.path.join(D.CACHE, 'usm', str(r['us'])[-2:], f"{r['us']}.json.gz")
    if not os.path.exists(p):
        return None
    try:
        return json.load(gzip.open(p))
    except (OSError, ValueError):
        return None


def skellam_table():
    """T[lead][minute] = home expected points share (win + draw / 2) with the minutes left at 1.35 a side a 90"""
    T = {}
    for m in range(0, 91):
        mu = 1.35 * (90 - m) / 90
        pm = [math.exp(-mu) * mu ** k / math.factorial(k) for k in range(12)]
        for L in range(-8, 9):
            w = dr = 0.0
            for i in range(12):
                for j in range(12):
                    f = L + i - j
                    q = pm[i] * pm[j]
                    if f > 0:
                        w += q
                    elif f == 0:
                        dr += q
            T[(L, m)] = w + dr / 2
    return T


def features(rows):
    link = dict(D.load(TI.LINK)['p'])
    seq = defaultdict(list)       # club -> [(day, {pid: minutes}, comp, {pid: started as GK})]
    played = sorted([r for r in rows if r.get('us') and r.get('hs') is not None], key=lambda r: r['day'])
    T = skellam_table()
    ctl_ok = ctl_bad = 0
    for r in played:
        m = usm(r)
        if not m:
            continue
        for s, t in (('h', r['h']), ('a', r['a'])):
            ro = m['ro'][s]
            seq[t].append((r['day'], {str(x['player_id']): int(x['time'] or 0) for x in ro}, TI.TMC[r['lg']],
                           {str(x['player_id']) for x in ro if x.get('position') == 'GK'}))
        # control from the shot list
        if r['st'] == 'FT':
            ev = []
            for s, sg in (('h', 1), ('a', -1)):
                for x in m.get('sh', {}).get(s) or []:
                    if x[3] == 'Goal':
                        ev.append((int(x[0]), sg))
                    elif x[3] == 'OwnGoal':
                        ev.append((int(x[0]), -sg))
            gh = sum(1 for _, g in ev if g > 0); ga = sum(1 for _, g in ev if g < 0)
            if gh == r['hs'] and ga == r['as']:
                ev.sort()
                L, i, acc = 0, 0, 0.0
                for mi in range(1, 91):
                    while i < len(ev) and ev[i][0] < mi:
                        L += ev[i][1]; i += 1
                    acc += T[(max(-8, min(8, L)), mi)]
                r['ctl'] = acc / 90
                ctl_ok += 1
            else:
                ctl_bad += 1
    print('control rows', ctl_ok, 'skipped', ctl_bad, flush=True)
    days = {t: [x[0] for x in L] for t, L in seq.items()}
    sp = {}

    def spl(p):
        if p not in sp:
            f = os.path.join(TI.CDIR, f'{link[p]}.json.gz') if p in link else None
            sp[p] = (D.load(f) or []) if f and os.path.exists(f) else []
        return sp[p]
    v = TI.value_table()
    vs = value_table('sv'); vp = value_table('pg90')

    def window(t, day):
        L = seq.get(t)
        if not L:
            return None, -1
        i = bisect.bisect_left(days[t], day) - 1
        if i < TI.HEALTHY or (dt.date.fromisoformat(day) - dt.date.fromisoformat(L[i][0])).days > TI.STALE:
            return None, i
        return L[max(0, i - TI.LAST_N + 1):i + 1], i

    def club(t, day, comp):
        """(C3 deficit, C2 returners, C4 keeper out)"""
        w, i = window(t, day)
        if not w:
            return 0.0, 0.0, 0, 0.0, 0.0
        S = D.season_of(day)
        L = seq[t]
        d3 = 0.0
        dsv = dpg = 0.0
        fcut = (dt.date.fromisoformat(day) - dt.timedelta(days=TI.FRESH)).isoformat()
        for p in set().union(*[x[1] for x in w]):
            o = TI.out_on(spl(p), day, comp)
            if not o:
                continue
            if any(s[0] >= fcut for s in o):
                ms = [x[1].get(p, 0) for x in w if not TI.out_on(spl(p), x[0], x[2])]
                if len(ms) >= TI.HEALTHY:
                    u = (sum(ms) / len(ms)) / 90
                    dsv += vs(S - 1, p) * u; dpg += vp(S - 1, p) * u
            st = min(s[0] for s in o)
            # club matches since the spell began, before this one
            k = i + 1 - bisect.bisect_left(days[t], st)
            if k >= 3:
                continue
            ms = [x[1].get(p, 0) for x in w if not TI.out_on(spl(p), x[0], x[2])]
            if len(ms) >= TI.HEALTHY:
                d3 += v(S - 1, p) * (sum(ms) / len(ms)) / 90
        # returners: anyone on the club's last 40 line-ups
        ret = 0.0
        cut = (dt.date.fromisoformat(day) - dt.timedelta(days=21)).isoformat()
        cand = set().union(*[x[1] for x in L[max(0, i - 39):i + 1]])
        for p in cand:
            s_ = spl(p)
            if not s_ or TI.out_on(s_, day, comp):
                continue
            for s in s_:
                if s[1] and cut <= s[1] < day and s[0] < day and (dt.date.fromisoformat(s[1]) - dt.date.fromisoformat(s[0])).days >= 28:
                    j = bisect.bisect_left(days[t], s[0]) - 1
                    pre = [x[1].get(p, 0) for x in L[max(0, j - 9):j + 1] if not TI.out_on(s_, x[0], x[2])]
                    if len(pre) >= 3 and j >= 0:
                        ret += v(S - 1, p) * (sum(pre) / len(pre)) / 90
                    break
        # regular keeper
        gm = defaultdict(int); gs = defaultdict(int)
        for x in w:
            for p in x[3]:
                gm[p] += x[1].get(p, 0); gs[p] += 1
        gk = 0
        if gm:
            p = max(gm, key=gm.get)
            if gs[p] >= 6 and TI.out_on(spl(p), day, comp):
                gk = 1
        return d3, ret, gk, dsv, dpg
    for r in rows:
        if r['lg'] not in TI.TMC or r.get('hs') is None:
            continue
        c = TI.TMC[r['lg']]
        h3, hr, hg, hs_, hp = club(r['h'], r['day'], c)
        a3, ar, ag, as_, ap = club(r['a'], r['day'], c)
        r['avzsv'] = round((as_ - hs_) / 2, 4)
        r['avzpg'] = round((ap - hp) / 2, 4)
        r['avz3'] = round((a3 - h3) / 2, 4)
        r['rtz'] = round((hr - ar) / 2, 4)
        r['gkh'], r['gka'] = hg, ag
    return rows


def value_table(field):
    """TI.value_table with another per-90 field of the season files (same fringe shift, same V0)"""
    gv = {}
    try:
        F = json.load(open(os.path.join(os.path.dirname(TI.WARD), '..', '..', 'data', 'soccer_war_fit.json')))
        dl = {k: F['repl'][k] - F['replFringe'][k] for k in F['repl']} if F.get('replFringe') else {}
    except (OSError, KeyError, ValueError):
        dl = {}

    def v(S, p):
        if S not in gv:
            try:
                rows = [(x['gar'] + dl.get(x['pos'], 0.0) * x['min'] / 90, x) for x in json.load(open(os.path.join(TI.WARD, f'{S}.json')))['players']]
                gv[S] = {x['p']: x[field] + dl.get(x['pos'], 0.0) for _, x in sorted(rows, key=lambda t: -t[0]) if x.get(field) is not None}
            except (OSError, KeyError, ValueError):
                gv[S] = {}
        return gv[S].get(p, TI.V0)
    return v


# ------------------------------------------------------------ engine
class R3(G.Ratings):
    def __init__(self, P):
        super().__init__(P)
        self.c = defaultdict(float)
        self.cn = defaultdict(int)
        self.hc = 0.0

    def lambdas(self, r):
        lh, la = super().lambdas(r)
        P = self.P
        x, y = math.log(lh), math.log(la)
        e1 = P.get('e1', 0.0)
        if e1 and r['lg'] not in D.EURO and r['lg'] not in D.CUPS and min(self.n[r['h']], self.n[r['a']]) < 4:
            m, g = (x + y) / 2, (x - y) / 2
            x, y = m + g * (1 + e1), m - g * (1 + e1)
        if P.get('rt'):
            x += P['rt'] * r.get('rtz', 0.0); y -= P['rt'] * r.get('rtz', 0.0)
        if P.get('kg'):
            x += P['kg'] * r.get('gka', 0); y += P['kg'] * r.get('gkh', 0)
        if P.get('wc') and self.cn[r['h']] >= 10 and self.cn[r['a']] >= 10:
            g = P['wc'] * (self.c[r['h']] - self.c[r['a']])
            x += g; y -= g
        return G.ex(x), G.ex(y)

    def update(self, r):
        super().update(r)
        if self.P.get('kc') and r.get('ctl') is not None:
            h, a = r['h'], r['a']
            e = r['ctl'] - (0.5 + self.c[h] - self.c[a] + self.hc)
            self.c[h] += self.P['kc'] * e; self.c[a] -= self.P['kc'] * e
            self.hc += 0.002 * e
            self.cn[h] += 1; self.cn[a] += 1


def walk(rows, P, lo, hi):
    """per scored match (day, lg, ll) for S in [lo, hi]"""
    out = []
    R = R3(P)
    R.set_membership(rows)
    G.add_r90(rows)
    rho = P['rho']
    for r in rows:
        if r.get('hs') is None:
            continue
        R.prep(r)
        if r['lg'] in G.SCORED and (r['st'] == 'FT' or r.get('r90') is not None):
            S = D.season_of(r['day'], r['lg'])
            if lo <= S <= hi:
                lh, la = R.lambdas(r)
                pw, pd, pl = G.wdl(lh, la, rho)
                y = (pl, pd, pw)[G.res90(r) + 1]
                out.append((r['day'], r['lg'], S, -math.log(max(y, 1e-9))))
        R.update(r)
    return out


def compare(base, tr):
    d = [b[3] - a[3] for a, b in zip(base, tr)]
    days = [a[0] for a in base]
    n = len(d)
    m = sum(d) / n
    t = G.cl_t(d, days)
    parts = {}
    for name, f in (('big5', lambda x: x[1] in D.BIG5), ('uefa', lambda x: x[1] in D.EURO)):
        dd = [di for di, a in zip(d, base) if f(a)]
        kk = [a[0] for a, di in zip(base, d) if f(a)]
        parts[name] = {'n': len(dd), 'd': round(sum(dd) / max(1, len(dd)), 6), 't': G.cl_t(dd, kk)}
    seas = defaultdict(list)
    for di, a in zip(d, base):
        seas[a[2]].append(di)
    won = sum(1 for v in seas.values() if sum(v) < 0)
    return {'n': n, 'base': round(sum(a[3] for a in base) / n, 6), 'd': round(m, 6), 't': t, 'parts': parts,
            'seasons_better': f'{won}/{len(seas)}'}


GRID = {
    'C1': [{'e1': e} for e in (-0.15, -0.10, -0.05, 0.05, 0.10, 0.15)],
    'C2': [{'rt': x} for x in (0.1, 0.2, 0.35, 0.5)],
    'C3': [{'av': x, '_avz3': 1} for x in (0.25, 0.35, 0.5)],
    'C4': [{'kg': x} for x in (0.03, 0.06, 0.10, 0.15)],
    'C7': [{'av': x, '_avz': 'avzsv'} for x in (0.25, 0.35, 0.5)],
    'C8': [{'av': x, '_avz': 'avzpg'} for x in (0.25, 0.35, 0.5)],
    'C6': [{'kc': kc, 'wc': wc} for kc in (0.02, 0.05) for wc in (0.1, 0.2, 0.4)],
}


def with_rows(rows, q):
    if q.get('_avz3'):
        return [dict(r, avz=r['avz3']) if 'avz3' in r else r for r in rows]
    if q.get('_avz'):
        return [dict(r, avz=r[q['_avz']]) if q['_avz'] in r else r for r in rows]
    return rows


def main(mode):
    rows = [r for r in engine.load_rows() if r['day'] < LOCK]
    rows = features(rows)
    P = G.params()
    try:
        res = json.load(open(OUT))
    except (OSError, ValueError):
        res = {}
    lo, hi = (2013, 2022) if mode == 'tune' else (2023, 2026)
    base = walk(rows, P, lo, hi)
    print(mode, 'base', len(base), round(sum(x[3] for x in base) / len(base), 6), flush=True)
    for c, grid in GRID.items():
        if mode == 'tune':
            out = []
            for q in grid:
                Q = dict(P, **{k: v for k, v in q.items() if not k.startswith('_')})
                cmp_ = compare(base, walk(with_rows(rows, q), Q, lo, hi))
                out.append({'q': q, **cmp_})
                print(c, q, cmp_['d'], cmp_['t'], flush=True)
            best = min(out, key=lambda x: x['d'])
            res.setdefault(c, {})['tune'] = out
            res[c]['pick'] = best['q'] if best['d'] < 0 else None
        else:
            q = res.get(c, {}).get('pick')
            if not q:
                print(c, 'failed at tune, no held run')
                continue
            Q = dict(P, **{k: v for k, v in q.items() if not k.startswith('_')})
            cmp_ = compare(base, walk(with_rows(rows, q), Q, lo, hi))
            res[c]['held'] = cmp_
            print(c, q, cmp_, flush=True)
    if mode == 'held':
        # Holm over the cells taken to held
        ps = sorted(((0.5 * math.erfc(-res[c]['held']['t'] / math.sqrt(2)), c) for c in res
                     if 'held' in res[c] and res[c]['held']['t'] is not None), key=lambda x: x[0])
        k = len(ps)
        alive = True
        for i, (p, c) in enumerate(ps):
            ok = alive and p <= 0.05 / (k - i)
            alive = ok
            res[c]['holm'] = {'p': round(p, 5), 'alpha': round(0.05 / (k - i), 5), 'pass': bool(ok)}
    res['_meta'] = {'prereg_sha256': open(os.path.join(HERE, 'prereg.sha256')).read().split()[0], 'lock': LOCK}
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'tune')
