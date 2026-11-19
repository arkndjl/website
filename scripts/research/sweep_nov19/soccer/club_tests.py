# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Club game model tests on one walk-forward record of the live model: L7 market draw lean, L9 referee lean on
totals, L11 manager effect (table + new-club term). Prereg:
/mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/sweep_nov19/soccer/club_tests.py rec          # the record (no scores)
    python3 scripts/research/sweep_nov19/soccer/club_tests.py l7|l9|l11 [held]
"""
import csv
import datetime as dt
import gzip
import json
import math
import os
import pickle
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCR)
import soccer_data as D
import soccer_games as G

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')
DUMP = os.path.join(SCR, '.cache', 'soccer_prospects', 'dump')
END = '2026-06-30'
OU_LGS = ('eng.1', 'esp.1', 'ger.1', 'ita.1', 'fra.1', 'eng.2', 'esp.2', 'ger.2', 'ita.2', 'fra.2', 'ned.1', 'por.1',
          'bel.1', 'tur.1', 'gre.1', 'sco.1')
TT = np.add.outer(np.arange(G.GMAX), np.arange(G.GMAX))


def day_add(d, k):
    return (dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat()


def tm_games():
    """(day, TM home id, TM away id) -> (referee, home manager, away manager), league matches"""
    out = {}
    with gzip.open(os.path.join(DUMP, 'games.csv.gz'), 'rt') as fh:
        for r in csv.DictReader(fh):
            if r['date'] <= END and r.get('competition_type') == 'domestic_league':
                out[(r['date'][:10], r['home_club_id'], r['away_club_id'])] = (r.get('referee') or '', r.get('home_club_manager_name') or '',
                                                                          r.get('away_club_manager_name') or '')
    return out


def record():
    fn = os.path.join(OUT, 'club_rec.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    rows = [r for r in G.add_inj(G.add_mv(G.add_market(D.load(G.HIST)))) if r['day'] <= END]
    P = G.params()
    e2t = D.load(G.MVF)['espn2tm']
    TG = tm_games()
    lgs = {r['lg'] for r in rows if r['lg'] not in D.EURO and r['lg'] not in D.CUPS}
    recs = []

    def score(r, S, lh, la, R):
        if r['st'] != 'FT':
            return
        mu = R.total(r, lh, la)
        rec = {'id': r['id'], 'S': S, 'day': r['day'], 'lg': r['lg'], 'h': r['h'], 'a': r['a'], 'lh': lh, 'la': la, 'mu': mu,
               'hs': r['hs'], 'as': r['as'], 'c': G.close_probs(r), 'ou': G.ou_close(r)}
        th, ta = e2t.get(r['h']), e2t.get(r['a'])
        if th and ta:
            for k in (0, -1, 1):
                g = TG.get((day_add(r['day'], k), str(th), str(ta)))
                if g:
                    rec['ref'], rec['mh'], rec['ma'] = g
                    break
        recs.append(rec)
    G.run(rows, P, score, totals=True, scored=lgs)
    pickle.dump(recs, open(fn, 'wb'))
    return recs


def bll(p, y):
    p = min(1 - 1e-6, max(1e-6, p))
    return -math.log(p if y else 1 - p)


def rep(d, recs):
    by = defaultdict(float)
    for x, r in zip(d, recs):
        by[r['S']] += x
    return {'n': len(d), 'd': round(sum(d) / len(d), 6), 't': G.cl_t(d, [r['day'] for r in recs]),
            'seasons': f"{sum(v < 0 for v in by.values())}/{len(by)}"}


# ---------------------------------------------------------------- L7
def lean_z(recs, rho):
    fn = os.path.join(OUT, 'l7_z.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    z = {}
    for r in recs:
        if r['lg'] not in OU_LGS or not r['c'] or r['ou'] is None:
            continue
        pw, pd, pl = r['c']
        mu = G.mu_of(min(0.95, max(0.05, r['ou'])))
        tgt = math.log(pw / pl)
        lo, hi = 0.03, 0.97
        for _ in range(22):
            s = (lo + hi) / 2
            w, d_, l_ = G.wdl(mu * s, mu * (1 - s), rho)
            if math.log(w / l_) < tgt:
                lo = s
            else:
                hi = s
        z[r['id']] = math.log(pd / d_)
    pickle.dump(z, open(fn, 'wb'))
    return z


def l7_run(recs, z, rho, kb, kt, g, lo, hi):
    b = defaultdict(float); tau = defaultdict(float); nb = Counter()
    d, used, pdn, pdo, yd = [], [], [], [], []
    for r in recs:
        if r['id'] not in z:
            continue
        pred = b[r['lg']] + tau[r['h']] + tau[r['a']]
        if lo <= r['S'] <= hi and nb[r['lg']] >= 50:
            pw, pd, pl = G.wdl(r['lh'], r['la'], rho)
            pd2 = pd * math.exp(g * pred)
            s = (1 - pd2) / (pw + pl)
            y = 0 if r['hs'] > r['as'] else 1 if r['hs'] == r['as'] else 2
            d.append(-math.log((pw * s, pd2, pl * s)[y]) + math.log((pw, pd, pl)[y]))
            used.append(r); pdn.append(pd2); pdo.append(pd); yd.append(y == 1)
        e = z[r['id']] - pred
        b[r['lg']] += kb * e
        tau[r['h']] += kt * e; tau[r['a']] += kt * e
        nb[r['lg']] += 1
    out = rep(d, used)
    out['slopeBase'] = round(float(np.polyfit(pdo, np.array(yd, float), 1)[0]), 3)
    out['slopeCand'] = round(float(np.polyfit(pdn, np.array(yd, float), 1)[0]), 3)
    out['drawPred'] = [round(float(np.mean(pdo)), 4), round(float(np.mean(pdn)), 4), round(float(np.mean(yd)), 4)]
    return out


def l7(held):
    recs = record()
    rho = G.params()['rho']
    z = lean_z(recs, rho)
    fn = os.path.join(OUT, 'l7.json')
    res = json.load(open(fn)) if os.path.exists(fn) else {'rows': len(z), 'meanZ': round(sum(z.values()) / len(z), 4), 'tune': {}}
    if not held:
        for kb in (.02, .06):
            for kt in (0, .03):
                for g in (.5, 1):
                    res['tune'][f'{kb}_{kt}_{g}'] = l7_run(recs, z, rho, kb, kt, g, 2021, 2023)
                    print(kb, kt, g, res['tune'][f'{kb}_{kt}_{g}'], flush=True)
    else:
        best = min(res['tune'], key=lambda k: res['tune'][k]['d'])
        kb, kt, g = (float(x) for x in best.split('_'))
        res['held'] = dict(kb=kb, kt=kt, g=g, **l7_run(recs, z, rho, kb, kt, g, 2024, 2026))
        print(res['held'])
    json.dump(res, open(fn, 'w'), indent=1)


# ---------------------------------------------------------------- L9 referee
_C = {}


def o25(lh, la, rho):
    k = (round(lh, 3), round(la, 3))
    v = _C.get(k)
    if v is None:
        v = _C[k] = float(G.score_matrix(k[0], k[1], rho)[TT > 2.5].sum())
    return v


def l9_run(recs, rho, n0, c, lo, hi):
    acc = defaultdict(lambda: [0.0, 0])
    d, used = [], []
    for r in recs:
        if r['mu'] is None or not r.get('ref'):
            continue
        k = r['mu'] / (r['lh'] + r['la'])
        p = min(.98, max(.02, o25(r['lh'] * k, r['la'] * k, rho)))
        y = int(r['hs'] + r['as'] > 2)
        a = acc[r['ref']]
        if lo <= r['S'] <= hi:
            lean = a[0] / (a[1] + n0)
            p2 = 1 / (1 + math.exp(-(math.log(p / (1 - p)) + 4 * c * lean)))
            d.append(bll(p2, y) - bll(p, y)); used.append(r)
        a[0] += y - p; a[1] += 1
    return rep(d, used)


def l9(held):
    recs = record()
    rho = G.params()['rho']
    fn = os.path.join(OUT, 'l9.json')
    tot = sum(1 for r in recs if r['mu'] is not None)
    res = json.load(open(fn)) if os.path.exists(fn) else {'totalsRows': tot, 'withRef': sum(1 for r in recs if r['mu'] is not None and r.get('ref')),
                                                           'refs': len({r.get('ref') for r in recs if r.get('ref')}), 'tune': {}}
    if not held:
        for n0 in (20, 60):
            for c in (.5, 1):
                res['tune'][f'{n0}_{c}'] = l9_run(recs, rho, n0, c, 2020, 2022)
                print(n0, c, res['tune'][f'{n0}_{c}'], flush=True)
    else:
        best = min(res['tune'], key=lambda k: res['tune'][k]['d'])
        n0, c = (float(x) for x in best.split('_'))
        res['held'] = dict(n0=n0, c=c, **l9_run(recs, rho, n0, c, 2023, 2026))
        print(res['held'])
    json.dump(res, open(fn, 'w'), indent=1)


# ---------------------------------------------------------------- L11 managers
def l11_run(recs, rho, beta, lo, hi, table=False):
    tot = defaultdict(lambda: [0.0, 0])                   # manager -> residual sum, matches
    at = defaultdict(lambda: [0.0, 0])                    # (manager, club) -> the same at that club
    clubs = defaultdict(list)
    d, used = [], []
    for r in recs:
        mh, ma = r.get('mh'), r.get('ma')
        if not mh or not ma:
            continue
        res = (r['hs'] - r['as']) - (r['lh'] - r['la'])
        new = False
        e = {}
        for m, t in ((mh, r['h']), (ma, r['a'])):
            first = t not in clubs[m]
            if first:
                clubs[m].append(t)
            n_here = at[(m, t)][1]
            early = n_here < 10 and len(clubs[m]) > 1 and clubs[m][-1] == t
            s_o, n_o = tot[m][0] - at[(m, t)][0], tot[m][1] - at[(m, t)][1]
            e[m] = s_o / (n_o + 40) if n_o > 0 else 0.0
            new = new or early
        if new and lo <= r['S'] <= hi and beta is not None:
            x = beta * (e[mh] - e[ma]) / 2
            pw, pd, pl = G.wdl(r['lh'], r['la'], rho)
            qw, qd, ql = G.wdl(r['lh'] * math.exp(x), r['la'] * math.exp(-x), rho)
            y = 0 if r['hs'] > r['as'] else 1 if r['hs'] == r['as'] else 2
            d.append(-math.log((qw, qd, ql)[y]) + math.log((pw, pd, pl)[y])); used.append(r)
        for m, t, sg in ((mh, r['h'], 1), (ma, r['a'], -1)):
            tot[m][0] += sg * res; tot[m][1] += 1
            at[(m, t)][0] += sg * res; at[(m, t)][1] += 1
    if table:
        last = {}
        for r in recs:
            for m, t in ((r.get('mh'), r['h']), (r.get('ma'), r['a'])):
                if m:
                    last[m] = (r['day'], t, r['lg'])
        return [{'n': m, 'eff': round(v[0] / (v[1] + 40), 3), 'raw': round(v[0] / v[1], 3), 'mp': v[1], 'clubs': len(clubs[m]),
                 'last': last[m][0], 'club': last[m][1], 'lg': last[m][2]} for m, v in tot.items() if v[1] >= 60]
    return rep(d, used) if d else {'n': 0}


def l11(held):
    recs = record()
    rho = G.params()['rho']
    fn = os.path.join(OUT, 'l11.json')
    res = json.load(open(fn)) if os.path.exists(fn) else {'withManagers': sum(1 for r in recs if r.get('mh') and r.get('ma')), 'tune': {}}
    if not held:
        for beta in (.25, .5, 1):
            res['tune'][str(beta)] = l11_run(recs, rho, beta, 2014, 2022)
            print(beta, res['tune'][str(beta)], flush=True)
    else:
        beta = float(min(res['tune'], key=lambda k: res['tune'][k]['d']))
        res['held'] = dict(beta=beta, **l11_run(recs, rho, beta, 2023, 2026))
        print(res['held'])
    json.dump(res, open(fn, 'w'), indent=1)
    if 'table' in sys.argv:
        tb = sorted(l11_run(recs, rho, None, 0, 0, table=True), key=lambda x: -x['eff'])
        json.dump(tb, open(os.path.join(OUT, 'managers.json'), 'w'))
        print(len(tb), tb[:5], tb[-3:])


if __name__ == '__main__':
    held = 'held' in sys.argv
    {'rec': record, 'l7': lambda: l7(held), 'l9': lambda: l9(held), 'l11': lambda: l11(held)}[sys.argv[1]]()
