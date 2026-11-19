# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 8 (PREREG.md): national TV, NBA Cup and star x policy flags in the play-chance model's j3 logistic.

    python3 play_test.py ESPN_DIR      # -> impl/nba/play_tv.json

Rows = nba_play.rows (rotation players in reported games) with the game's broadcast flags; each flag alone is added to
j3's inputs; walk-forward by season (fit on the seasons before, from 2022); log loss weighted by role minutes, paired,
clustered by game day. Tune 2022-23, held 2024-26."""
import glob, json, os, sys
from collections import Counter
import numpy as np
import common as C
import nba_games as N
import nba_play as PL
from logit_ridge import fit_ridge, predict


def rows():
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj, prev = N.load_inj(), N.load_prev()
    m = N.Model(names, F['P'], inj=inj, prev=prev, play=False, **F['params'])
    out = []
    for g in games:
        m.feats(g)
        if g.get('fin') and g.get('pl') and g['S'] >= PL.FIRST and inj.get(g['id']) is not None:
            for t in (g['h'], g['a']):
                if t not in g['pl']: continue
                mins = dict(g['pl'][t])
                st, _ = m.status_for(g, t)
                for p in m.roster(t):
                    w, n = m.role[p]
                    R = w / n if n else 0.0
                    if R >= PL.MIN_ROLE:
                        out.append((g['S'], str(N.gday(N.tipdt(g))), m.play_ctx(p, t, st.get(p), R), float(mins.get(p, 0) > 0), g['id'], p))
        m.update(g)
    return out, names


def main():
    R, names = rows()
    tv = {}
    for fn in glob.glob(os.path.join(sys.argv[1], 'tv_*.json')): tv.update(json.load(open(fn)))
    ps, tm, st = C.frame()
    S = np.array([r[0] for r in R]); day = np.array([r[1] for r in R]); y = np.array([r[3] for r in R]); w = np.array([r[2]['R'] for r in R])
    star = np.zeros(len(R))
    for s in sorted(set(S)):
        pool = {r[5] for r in R if r[0] == s}
        find = C.matcher([(pid, names[pid]) for pid in pool if pid in names])
        stars = {find(nm) for (yy, pid, t, mp, pos, aw, nm) in st if s - 3 <= yy <= s - 1 and any(a == 'AS' or a.startswith('NBA') for a in (aw or '').split(','))}
        star[S == s] = [float(r[5] in stars) for r in R if r[0] == s]
    has = np.array([r[4] in tv for r in R])
    natl = np.array([float(bool(tv.get(r[4], [[], []])[0])) for r in R])
    cup = np.array([float(any(h and ('Cup' in h or 'In-Season' in h) for h in tv.get(r[4], [[], []])[1])) for r in R])
    pol = star * np.maximum(natl, cup) * (S >= 2024)
    print('rows', len(R), 'with tv', int(has.sum()), 'natl', round(float(natl.mean()), 3), 'cup', round(float(cup.mean()), 4), 'star', round(float(star.mean()), 3), 'policy rows', int(pol.sum()), flush=True)
    cats = [PL._cats(r[2]) for r in R]

    def walk(extra):
        p = np.full(len(R), np.nan)
        for s in range(PL.FIRST + 2, int(S.max()) + 1):
            tr, te = S < s, S == s
            rate = {}
            sts = np.array([r[2]['st'] for r in R], dtype=object)
            for v in set(sts[tr]):
                i = tr & (sts == v)
                rate[v] = round(float((w[i] * y[i]).sum() / w[i].sum()), 4)
            nm = []
            for key in ('cell', 'n2', 'last'):
                lv = [v for v, n in Counter(c[key] for c, k in zip(cats, tr) if k).most_common() if n >= 30]
                nm += [f'{key}={v}' for v in lv[1:]]
            X = np.array([PL._vec(r[2], nm, rate, c) for r, c in zip(R, cats)])
            if extra is not None: X = np.column_stack([X, extra])
            b, mu, sd = fit_ridge(X[tr], y[tr], PL.LAM3, w[tr])
            p[te] = predict(X[te], b, mu, sd)
        return np.clip(p, 0.001, 0.999)
    ll = lambda p: -(y * np.log(p) + (1 - y) * np.log(1 - p)) * w / w.mean()
    l0 = ll(walk(None))
    res = {'n': len(R), 'natlShare': float(natl.mean()), 'policyRows': int(pol.sum())}
    for nm, col in (('natl', natl), ('cup', cup), ('star', pol)):
        d = ll(walk(col)) - l0
        r = {}
        late = nm in ('cup', 'star')                 # no row before 2024: scored on the seasons whose fit has seen one
        for sp, k in (('tune', np.isin(S, (2022, 2023))), ('held', S >= (2025 if late else 2024)), ('heldStars', (S >= (2025 if late else 2024)) & (star > 0))):
            k = k & ~np.isnan(d)
            p = C.paired(d[k], day[k]); ss = sorted(set(S[k]))
            r[sp] = {'n': int(k.sum()), 'll0': round(float(l0[k].mean()), 5), 'd': round(p['d'], 6), 't': round(p['t'], 2),
                     'seasonsLower': int(sum(d[k & (S == s)].mean() < 0 for s in ss)), 'seasons': len(ss)}
        r['p'] = C.p2(r['held']['t']) if r['held']['t'] < 0 else 1.0
        res[nm] = r
        print(nm, r, flush=True)
    hp = C.holm({k: res[k]['p'] for k in ('natl', 'cup', 'star')})
    for k in hp:
        r = res[k]; r['holm'] = round(hp[k], 4)
        late = k in ('cup', 'star')
        r['pass'] = bool(r['held']['t'] <= -2 and (r['held']['seasonsLower'] == r['held']['seasons'] if late else r['tune']['d'] < 0 and r['held']['seasonsLower'] * 2 > r['held']['seasons']) and hp[k] <= 0.05)
    json.dump(res, open(os.path.join(C.IMPL, 'play_tv.json'), 'w'), indent=1)
    print({k: res[k]['pass'] for k in hp})


if __name__ == '__main__':
    main()
