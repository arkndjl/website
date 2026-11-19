# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""National-team research harness (never soccer_intl.py --fit): L3 shots process rating, L3b penalty-discounted
goals, L8 squad make-up covariates, shootouts check. Prereg:
/mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/sweep_nov19/soccer/intl_tests.py l8|l3b|l3|so  [held]
"""
import bisect
import csv
import datetime as dt
import gzip
import json
import math
import os
import pickle
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
import soccer_intl as I

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')
DUMP = os.path.join(os.path.dirname(I.HERE), 'scripts', '.cache', 'soccer_prospects', 'dump')
if not os.path.isdir(DUMP):
    DUMP = os.path.join(I.HERE, '.cache', 'soccer_prospects', 'dump')
END = '2026-07-31'


def base_rows():
    fn = os.path.join(OUT, 'intl_rows_cu.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    rows = pickle.load(open(os.path.join(OUT, 'intl_rows_espn.pkl'), 'rb'))
    rows = [r for r in rows if r['day'] <= END]
    I.attach_sq(rows)
    I.attach_cu(rows)
    pickle.dump(rows, open(fn, 'wb'))
    return rows


def run(rows, P, lo, hi, extra=None, upd=None, R=None, hook=None):
    """soccer_intl.run with a per-row log-rate shift (extra: row -> x, home up / away down), an update row
    (upd: row -> row used for the rating update) and a hook(R, r) -> (dlh, dla) log shifts from a second rating"""
    R = R or I.Ratings(P)
    rho = P['rho']
    out = {}
    for r in rows:
        h, a = r['h'], r['a']
        R._decay(h, r['day']); R._decay(a, r['day'])
        lh, la = R.rates(h, a, r['neu'], r.get('qh'), r.get('qa'), r.get('ch'), r.get('ca'))
        lh0, la0 = lh, la
        if extra:
            x = extra(r)
            if x:
                lh, la = lh * math.exp(x), la * math.exp(-x)
        flag = True
        if hook:
            s = hook(R, r)
            if s:
                lh, la = lh * math.exp(s[0]), la * math.exp(s[1])
            else:
                flag = False
        if lo <= r['day'] <= hi and R.n[h] >= 5 and R.n[a] >= 5:
            p = I.wdl(lh, la, rho)[I.outcome(r)]
            out[(r['day'], h, a)] = (-math.log(max(p, 1e-9)), flag, lh, la)
        R.update(upd(r) if upd else r, lh0 if hook else lh, la0 if hook else la)
        if hook and hasattr(R, 'post'):
            R.post(r)
    return out


def tday(d, keys):
    m = sum(d) / len(d)
    g = defaultdict(float)
    for x, k in zip(d, keys):
        g[k] += x - m
    se = math.sqrt(sum(v * v for v in g.values())) / len(d)
    return m, (m / se if se else 0.0)


def paired(a, b, only=None):
    ks = [k for k in sorted(a) if k in b and (only is None or k in only)]
    if not ks:
        return {'n': 0}
    d = [b[k][0] - a[k][0] for k in ks]
    m, t = tday(d, [k[0] for k in ks])
    yrs = defaultdict(list)
    for x, k in zip(d, ks):
        yrs[k[0][:4]].append(x)
    return {'n': len(ks), 'base': round(sum(a[k][0] for k in ks) / len(ks), 5), 'cand': round(sum(b[k][0] for k in ks) / len(ks), 5),
            'd': round(m, 6), 't': round(t, 2), 'yearsBetter': sum(1 for v in yrs.values() if sum(v) < 0), 'years': len(yrs)}


# ---------------------------------------------------------------- L8
def squad_ids(C, team, day, opp):
    v = C['sq'].get(team)
    if not v:
        return None, 0
    d = C['days'][team]
    end = bisect.bisect_left(d, day)
    lo = bisect.bisect_left(d, I._day(day, -1))
    for i in range(lo, min(len(v), lo + 6)):
        if v[i][0] <= I._day(day, 1) and v[i][2] == opp:
            end = min(end, i)
            break
    pre = set()
    w0 = I._day(day, -I.CU_WINDOW)
    i = end - 1
    while i >= 0 and d[i] >= w0:
        pre.update(v[i][3][0::2])
        i -= 1
    if not pre:
        i = end - 1
        while i >= 0 and not v[i][3]:
            i -= 1
        if i >= 0 and d[i] >= I._day(day, -I.CU_STALE):
            pre = set(v[i][3][0::2])
    return pre, end


def l8_covs(rows):
    fn = os.path.join(OUT, 'l8_covs.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    C = I.callups()
    dob = {}
    with gzip.open(os.path.join(DUMP, 'players.csv.gz'), 'rt') as fh:
        for r in csv.DictReader(fh):
            if r.get('date_of_birth'):
                dob[int(r['player_id'])] = r['date_of_birth'][:10]
    app = defaultdict(list)
    with gzip.open(os.path.join(DUMP, 'appearances.csv.gz'), 'rt') as fh:
        for r in csv.DictReader(fh):
            if r['date'] <= END:
                app[int(r['player_id'])].append((r['date'], r['player_club_id'], r['competition_id'] == 'CL'))
    for v in app.values():
        v.sort()
    appd = {p: [x[0] for x in v] for p, v in app.items()}
    # caps: per nation, player -> sorted page indexes he is on
    on = {}
    for t, v in C['sq'].items():
        m = defaultdict(list)
        for i, pg in enumerate(v):
            for p in pg[3][0::2]:
                m[p].append(i)
        on[t] = m
    out = {}
    for r in rows:
        if r.get('ch') is None or r.get('ca') is None:
            continue
        e = {}
        for s, o in (('h', 'a'), ('a', 'h')):
            ids, end = squad_ids(C, r[s], r['day'], r[o])
            if not ids:
                e = None
                break
            ages = [(dt.date.fromisoformat(r['day']) - dt.date.fromisoformat(dob[p])).days / 365.25 for p in ids if p in dob]
            clubs, cl, fit = Counter(), 0, 0
            d200, d365, d30 = I._day(r['day'], -200), I._day(r['day'], -365), I._day(r['day'], -30)
            for p in ids:
                ds = appd.get(p)
                if not ds:
                    continue
                j = bisect.bisect_left(ds, r['day']) - 1
                if j < 0:
                    continue
                if ds[j] >= d200:
                    clubs[app[p][j][1]] += 1
                if ds[j] >= d30:
                    fit += 1
                k = j
                while k >= 0 and ds[k] >= d365:
                    if app[p][k][2]:
                        cl += 1
                        break
                    k -= 1
            caps = [bisect.bisect_left(on[r[s]].get(p, []), end) for p in ids]
            n = len(ids)
            ma = sum(ages) / len(ages) if len(ages) >= 11 else None
            e[s] = {'age': ma, 'age2': abs(ma - 27.5) if ma is not None else None, 'coh': max(clubs.values()) if clubs else 0,
                    'cl': cl, 'caps': sum(math.log1p(c) for c in caps) / n, 'fit': fit / n}
        if e:
            out[(r['day'], r['h'], r['a'])] = {k: (e['h'][k] - e['a'][k]) if e['h'][k] is not None and e['a'][k] is not None else 0.0
                                               for k in e['h']}
    pickle.dump(out, open(fn, 'wb'))
    return out


TESTS = {'age': ('age', 'age2'), 'coh': ('coh',), 'cl': ('cl',), 'caps': ('caps',), 'fit': ('fit',)}
GRID = (-.06, -.03, .03, .06)


def l8(held):
    rows = base_rows()
    P = I.params()
    cov = l8_covs(rows)
    tk = [k for k in cov if '2005-01-01' <= k[0] <= '2015-12-31']
    sd = {}
    for c in ('age', 'age2', 'coh', 'cl', 'caps', 'fit'):
        v = [cov[k][c] for k in tk]
        m = sum(v) / len(v)
        sd[c] = (m, math.sqrt(sum((x - m) ** 2 for x in v) / len(v)) or 1.0)
    fn = os.path.join(OUT, 'l8.json')
    res = json.load(open(fn)) if os.path.exists(fn) else {'n': len(cov), 'sd': sd, 'tune': {}}

    def extra_of(betas):
        def ex(r):
            c = cov.get((r['day'], r['h'], r['a']))
            if not c:
                return 0.0
            return sum(b * (c[k] - sd[k][0] * 0) / sd[k][1] for k, b in betas.items()) / 2
        return ex
    if not held:
        b0 = run(rows, P, '2005-01-01', '2015-12-31')
        only = set(tk)
        for name, cs in TESTS.items():
            best = None
            combos = [dict(zip(cs, (b,))) for b in GRID] if len(cs) == 1 else [{cs[0]: a, cs[1]: b} for a in GRID for b in GRID]
            for bt in combos:
                r_ = paired(b0, run(rows, P, '2005-01-01', '2015-12-31', extra=extra_of(bt)), only)
                if best is None or r_['d'] < best[1]['d']:
                    best = (bt, r_)
            res['tune'][name] = {'beta': best[0], **best[1]}
            print(name, res['tune'][name], flush=True)
    else:
        b0 = run(rows, P, '2016-01-01', END)
        only = {k for k in cov if k[0] >= '2016-01-01'}
        res['held'] = {}
        for name in TESTS:
            bt = res['tune'][name]['beta']
            res['held'][name] = dict(beta=bt, **paired(b0, run(rows, P, '2016-01-01', END, extra=extra_of(bt)), only))
            print(name, res['held'][name], flush=True)
    json.dump(res, open(fn, 'w'), indent=1)


# ---------------------------------------------------------------- L3b
def pens():
    p = os.path.join(I.CACHE, 'goalscorers.csv')
    if not os.path.exists(p):
        open(p, 'wb').write(I._get(f'{I.MJ}/goalscorers.csv'))
    out = defaultdict(Counter)
    for r in csv.DictReader(open(p, encoding='utf-8')):
        if r['date'] <= END and r.get('penalty', '').upper() == 'TRUE':
            out[(r['date'], r['home_team'], r['away_team'])][r['team']] += 1
    return out


def l3b(held):
    rows = base_rows()
    P = I.params()
    PN = pens()
    fn = os.path.join(OUT, 'l3b.json')
    res = json.load(open(fn)) if os.path.exists(fn) else {'penMatches': len(PN), 'tune': {}}

    def upd_of(phi):
        def u(r):
            c = PN.get((r['day'], r['h'], r['a']))
            if not c or r['day'] < '2000-01-01' or r.get('et'):
                return r
            return dict(r, hs=max(0.0, r['hs'] - phi * c.get(r['h'], 0)), **{'as': max(0.0, r['as'] - phi * c.get(r['a'], 0))})
        return u
    lo, hi = ('2016-01-01', END) if held else ('2000-01-01', '2015-12-31')
    b0 = run(rows, P, lo, hi)
    if not held:
        for phi in (.5, 1.0):
            res['tune'][str(phi)] = paired(b0, run(rows, P, lo, hi, upd=upd_of(phi)))
            print(phi, res['tune'][str(phi)], flush=True)
    else:
        phi = min(res['tune'], key=lambda k: res['tune'][k]['d'])
        res['held'] = dict(phi=float(phi), **paired(b0, run(rows, P, lo, hi, upd=upd_of(float(phi)))))
        print(res['held'])
    json.dump(res, open(fn, 'w'), indent=1)


# ---------------------------------------------------------------- L3
def stats():
    out = {}
    for ln in open(os.path.join(OUT, 'intl_stats.jsonl')):
        x = json.loads(ln)
        st = x.get('st') or {}
        h, a = st.get('home') or {}, st.get('away') or {}
        try:
            sh, sa = int(h['shotsOnTarget']), int(a['shotsOnTarget'])
            th, ta = int(h['totalShots']), int(a['totalShots'])
        except (KeyError, ValueError, TypeError):
            continue
        if th + ta >= 4:
            out[(x['day'], x['h'], x['a'])] = (sh, sa, x['lg'])
    return out


class SR:
    """the second (shots on target) attack/defence pair beside soccer_intl.Ratings"""

    def __init__(self, P, ST, wx, kx):
        self.P, self.ST, self.wx, self.kx = P, ST, wx, kx
        self.xa = defaultdict(float); self.xd = defaultdict(float); self.n = Counter()
        self.g = 30.0; self.s = 100.0          # running goals and shots on target: c starts at .30

    def hook(self, R, r):
        h, a = r['h'], r['a']
        if self.n[h] < 5 or self.n[a] < 5:
            return None
        dh = (self.xa[h] - self.xd[a]) - (R.a[h] - R.d[a])
        da = (self.xa[a] - self.xd[h]) - (R.a[a] - R.d[h])
        return self.wx * dh, self.wx * da

    def post(self, R, r):
        st = self.ST.get((r['day'], r['h'], r['a']))
        if not st:
            return
        P = self.P
        h, a = r['h'], r['a']
        c = self.g / self.s
        hh = 0 if r['neu'] else R.H / 2
        lh = math.exp(R.m + hh + self.xa[h] - self.xd[a])
        la = math.exp(R.m - hh + self.xa[a] - self.xd[h])
        k = self.kx * P['k'] * P['w' + r['cat']]
        eh, ea = min(c * st[0], P['cap']) - lh, min(c * st[1], P['cap']) - la
        self.xa[h] += k * eh; self.xd[a] -= k * eh * P['kd']
        self.xa[a] += k * ea; self.xd[h] -= k * ea * P['kd']
        gh, ga = I.res90(r)
        self.g += gh + ga; self.s += st[0] + st[1]
        self.n[h] += 1; self.n[a] += 1


def run_sr(rows, P, lo, hi, ST, wx, kx):
    R = I.Ratings(P)
    S = SR(P, ST, wx, kx)
    R.post = lambda r: S.post(R, r)
    return run(rows, P, lo, hi, R=R, hook=S.hook)


def l3(held):
    rows = base_rows()
    P = I.params()
    ST = stats()
    fn = os.path.join(OUT, 'l3.json')
    res = json.load(open(fn)) if os.path.exists(fn) else {'statMatches': len(ST), 'byLg': dict(Counter(v[2] for v in ST.values())), 'tune': {}}
    lo, hi = ('2016-01-01', END) if held else ('2012-01-01', '2015-12-31')
    b0 = run(rows, P, lo, hi)
    if not held:
        for wx in (.15, .3, .5):
            for kx in (1, 2):
                c = run_sr(rows, P, lo, hi, ST, wx, kx)
                only = {k for k, v in c.items() if v[1]}
                res['tune'][f'{wx}_{kx}'] = paired(b0, c, only)
                print(wx, kx, res['tune'][f'{wx}_{kx}'], flush=True)
    else:
        best = min(res['tune'], key=lambda k: res['tune'][k]['d'])
        wx, kx = (float(x) for x in best.split('_'))
        c = run_sr(rows, P, lo, hi, ST, wx, kx)
        only = {k for k, v in c.items() if v[1]}
        res['held'] = dict(wx=wx, kx=kx, **paired(b0, c, only))
        res['heldStatOwn'] = paired(b0, c, {k for k in only if k in ST})
        cat = {(r['day'], r['h'], r['a']): r['cat'] for r in rows}
        res['heldByCat'] = {ct: paired(b0, c, {k for k in only if cat.get(k) == ct}) for ct in ('wc', 'cf', 'q', 'nl', 'f', 'o')}
        res['heldCoverage'] = {'scored': len(b0), 'blend': len(only)}
        print(json.dumps({k: res[k] for k in ('held', 'heldStatOwn', 'heldByCat', 'heldCoverage')}, indent=1))
    json.dump(res, open(fn, 'w'), indent=1)


# ---------------------------------------------------------------- shootouts
def shootouts():
    rows = base_rows()
    P = I.params()
    b = run(rows, P, '2005-01-01', END)
    xs, ys = [], []
    for r in rows:
        k = (r['day'], r['h'], r['a'])
        if r.get('so') and k in b:
            xs.append(math.log(b[k][2] / b[k][3]) - (0 if r['neu'] else 0))
            ys.append(1.0 if r['so'] == r['h'] else 0.0)
    b0 = b1 = 0.0
    for _ in range(50):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(b0 + b1 * x)))
            g0 += y - p; g1 += (y - p) * x
            w = p * (1 - p)
            h00 += w; h01 += w * x; h11 += w * x * x
        det = h00 * h11 - h01 * h01
        b0 += (h11 * g0 - h01 * g1) / det
        b1 += (h00 * g1 - h01 * g0) / det
    se1 = math.sqrt(h00 / det)
    fav = sum(1 for x, y in zip(xs, ys) if (x > 0) == (y > .5)) / len(xs)
    res = {'n': len(xs), 'slope': round(b1, 4), 'se': round(se1, 4), 'z': round(b1 / se1, 2), 'intercept': round(b0, 4),
           'favouriteWins': round(fav, 4), 'homeListedWins': round(sum(ys) / len(ys), 4)}
    json.dump(res, open(os.path.join(OUT, 'shootouts.json'), 'w'), indent=1)
    print(res)


if __name__ == '__main__':
    held = 'held' in sys.argv
    {'l8': lambda: l8(held), 'l3b': lambda: l3b(held), 'l3': lambda: l3(held), 'so': shootouts}[sys.argv[1]]()
