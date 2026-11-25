#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Tennis metric audit (Nov 24 2026): score every metric on the shared harness (prereg.md) -> results.json.
Needs passes.py full + half first, and the Sackmann ranking files untarred into scripts/.cache/tennis/audit_nov24/sack."""
import glob, json, math, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from passes import OUT, RANKD  # noqa: E402

MET = ['ark', 'elo', 'elo538', 'pts', 'ppa', 'rpa', 'war', 'sv', 'war_rate', 'wins', 'wl', 'winpct', 'gwp',
       'spw', 'rpw', 'dr', 'rank', 'rankpts', 'ark_pa', 'rpa_k', 'pipe_war']      # last three: after the shipped changes
CAND = {'D1 SV-L': ('sv', 'sv_l', 'describe_held'), 'D2 rPA-K': ('rpa', 'rpa_k', 'describe_held'),
        'P1 ARK-PA': ('ark', 'ark_pa', 'predict'), 'P2 WAR-L': ('war', 'pipe_war', 'predict')}   # pipe_war = tennis_model Model.war as shipped (level weights)
NEED = ('rpa', 'spw', 'rpw', 'dr')
LEAK = {'rank', 'rankpts'}            # need the held half: no held-out describe
Y0, Y1 = 2011, 2025
LN2 = math.log(2)
rng = np.random.default_rng(24)


def year_end_ranks():
    out = {}
    for tour in ('atp', 'wta'):
        best = {}
        for f in sorted(glob.glob(os.path.join(RANKD, tour, f'{tour}_rankings_*.csv'))):
            if not any(k in f for k in ('00s', '10s', '20s', 'current')): continue
            with open(f) as fh:
                next(fh)
                for line in fh:
                    x = line.rstrip('\n').split(',')
                    d = int(x[0]); y = d // 10000
                    if y < 2009: continue
                    k = (y, tour[0] + x[2])
                    if k not in best or best[k][0] < d or (best[k][0] == d and best[k][1] > int(x[1])):
                        best[k] = (d, int(x[1]), int(x[3] or 0) if x[3] else 0)
        # keep only the year's last ranking date
        last = defaultdict(int)
        for (y, _), v in best.items(): last[y] = max(last[y], v[0])
        for (y, p), v in best.items():
            if v[0] == last[y]: out[(y, p)] = (v[1], v[2])
    return out


def add_ranks(snaps, rk):
    for y, s in snaps.items():
        for p, o in s.items():
            r, pt = rk.get((y, p), (3000, 0))
            o['rank'] = -math.log(r); o['rankpts'] = math.log1p(pt)


def pool(s, minm):
    return {p: o for p, o in s.items() if o['m'] >= minm and all(o.get(k) is not None for k in NEED)}


def build(snaps, matches, lag, minm):
    """per season y (the season of the outcome): list of (tid, {metric: x winner - x loser})"""
    pools = {y: pool(s, minm) for y, s in snaps.items()}
    by = defaultdict(list)
    keys = MET + [c[1] for c in CAND.values()]
    for y, tour, tid, w, l in matches:
        ys = y - lag
        if not (Y0 <= ys <= Y1): continue
        P = pools.get(ys, {})
        if w in P and l in P:
            a, b = P[w], P[l]
            by[y].append((tid, np.array([a[k] - b[k] for k in keys])))
    out = {}
    for y, v in by.items():
        out[y] = (np.array([t for t, _ in v]), np.vstack([x for _, x in v]))
    return out, keys


def fit_b(x):
    b = 0.0
    for _ in range(30):
        p = 1 / (1 + np.exp(-b * x))
        g = np.sum((1 - p) * x); h = np.sum(p * (1 - p) * x * x) + 1e-9
        b += g / h
    return b


def nll(b, x):
    return np.logaddexp(0, -b * x)


def score(data, j, loso):
    ys = sorted(data)
    per = {}
    allx = np.concatenate([data[y][1][:, j] for y in ys])
    bp = fit_b(allx)
    for y in ys:
        x = data[y][1][:, j]
        b = fit_b(np.concatenate([data[z][1][:, j] for z in ys if z != y])) if loso else bp
        per[y] = (nll(b, x), (1 - 1 / (1 + np.exp(-b * x))) ** 2)
    return per


def r2(per, ys):
    ll = sum(per[y][0].sum() for y in ys); n = sum(len(per[y][0]) for y in ys)
    return 1 - ll / (n * LN2)


def summary(per):
    ys = sorted(per)
    boots = []
    for _ in range(2000):
        s = rng.choice(ys, len(ys))
        boots.append(r2(per, s))
    n = sum(len(per[y][0]) for y in ys)
    return {'r2': round(r2(per, ys), 4), 'ci90': [round(float(np.percentile(boots, 5)), 4), round(float(np.percentile(boots, 95)), 4)],
            'll': round(float(sum(per[y][0].sum() for y in ys) / n), 5),
            'brier': round(float(sum(per[y][1].sum() for y in ys) / n), 5), 'n': int(n)}


def player_r(snaps, k, minm=10):
    xs, ys_, ws, season = [], [], [], []
    for y in range(Y0, Y1 + 1):
        a, b = pool(snaps.get(y, {}), minm), pool(snaps.get(y + 1, {}), minm)
        for tour in ('atp', 'wta'):
            ps = [p for p in a if p in b and a[p]['tour'] == tour]
            if len(ps) < 20: continue
            u = np.array([a[p][k] for p in ps]); v = np.array([b[p][k] for p in ps]); w = np.array([b[p]['m'] for p in ps], float)
            u = u - np.average(u, weights=w); v = v - np.average(v, weights=w)
            xs.append(u); ys_.append(v); ws.append(w); season.append(y)

    def wr(idx):
        u = np.concatenate([xs[i] for i in idx]); v = np.concatenate([ys_[i] for i in idx]); w = np.concatenate([ws[i] for i in idx])
        return float(np.sum(w * u * v) / math.sqrt(np.sum(w * u * u) * np.sum(w * v * v)))
    idx = list(range(len(xs)))
    uniq = sorted(set(season))
    boots = []
    for _ in range(1000):
        s = rng.choice(uniq, len(uniq))
        boots.append(wr([i for z in s for i in idx if season[i] == z]))
    return {'r': round(wr(idx), 4), 'ci90': [round(float(np.percentile(boots, 5)), 4), round(float(np.percentile(boots, 95)), 4)],
            'pairs': int(sum(len(x) for x in xs))}


def cand_test(data, keys, base, cand, loso):
    jb, jc = keys.index(base), keys.index(cand)
    pb, pc = score(data, jb, loso), score(data, jc, loso)
    d, tids, seas = [], [], []
    better = 0
    for y in sorted(data):
        dd = pc[y][0] - pb[y][0]
        d.append(dd); tids.append(data[y][0]); seas.append(y)
        better += dd.mean() < 0
    d = np.concatenate(d); t_ = np.concatenate(tids)
    cl = defaultdict(float)
    for tid, v in zip(t_, d): cl[tid] += v
    c = np.array(list(cl.values()))
    se = math.sqrt(len(c) * np.sum((c - c.mean()) ** 2) / (len(c) - 1)) / len(d)
    t = d.mean() / se
    from math import erf
    p1 = 0.5 * (1 + erf(t / math.sqrt(2)))     # one-sided: small when the candidate is better
    return {'base_r2': round(r2(pb, sorted(pb)), 4), 'cand_r2': round(r2(pc, sorted(pc)), 4),
            'd_ll_1e4': round(float(d.mean() * 1e4), 2), 't': round(float(t), 2), 'p1': float(p1),
            'seasons_better': f'{better}/{len(data)}', 'n': int(len(d)), 'clusters': len(c)}


def main():
    full = pickle.load(open(os.path.join(OUT, 'full.pkl'), 'rb'))
    half = pickle.load(open(os.path.join(OUT, 'half.pkl'), 'rb'))
    rk = year_end_ranks()
    add_ranks(full['snaps'], rk); add_ranks(half['snaps'], rk)
    din, keys = build(full['snaps'], full['matches'], 0, 10)
    dho, _ = build(half['snaps'], half['matches'], 0, 5)
    dpr, _ = build(full['snaps'], full['matches'], 1, 10)
    res = {'metrics': {}, 'candidates': {}}
    for k in MET:
        j = keys.index(k)
        res['metrics'][k] = {
            'describe_in': summary(score(din, j, False)),
            'describe_held': None if k in LEAK else summary(score(dho, j, True)),
            'predict': summary(score(dpr, j, True)),
            'player_r': player_r(full['snaps'], k)}
        print(k, res['metrics'][k]['describe_in']['r2'], (res['metrics'][k]['describe_held'] or {}).get('r2'),
              res['metrics'][k]['predict']['r2'], res['metrics'][k]['player_r']['r'], flush=True)
    data = {'describe_held': dho, 'predict': dpr}
    fam = defaultdict(list)
    for name, (b, c, tgt) in CAND.items():
        out = cand_test(data[tgt], keys, b, c, True)
        out['target'] = tgt
        out['player_r'] = {'base': player_r(full['snaps'], b)['r'], 'cand': player_r(full['snaps'], c)['r']}
        res['candidates'][name] = out
        fam[name[0]].append(name)
    for f, names in fam.items():          # Holm within family
        names.sort(key=lambda n: res['candidates'][n]['p1'])
        m = len(names); prev = 0
        for i, n in enumerate(names):
            ph = max(prev, min(1.0, (m - i) * res['candidates'][n]['p1'])); prev = ph
            c = res['candidates'][n]
            c['holm_p'] = round(ph, 5)
            nb, ns = map(int, c['seasons_better'].split('/'))
            ok_r = c['player_r']['cand'] >= c['player_r']['base'] - 0.01
            c['pass'] = bool(ph < 0.05 and nb >= 9 and ok_r)
            c['p1'] = round(c['p1'], 6)
    for k, v in res['candidates'].items(): print(k, v)
    json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
