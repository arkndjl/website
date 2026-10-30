#!/usr/bin/env python3
"""CBB game model research, Oct 30 2026: FV in the preseason prior in new forms, freshmen, and the prior's shape.

    python3 scripts/cbb_fvgame_research.py [--only lab,lab]    # -> data/cbb_fvgame_research.json

Prior terms (built per season and Barttorvik team from the research seasons, each player's projected minutes share from
cbb_roster's walk-forward minutes models, E[FV] from the board's model as cbb_games.team_fv):
  fvpm     projected-minutes-weighted E[FV] above 20 over the whole roster, freshmen included (fvw used last season's
           minutes and left freshmen out)
  fvfr2    freshmen's E[FV] at the mean above 20, squared, summed / 10 (elite freshmen worth more than their sum)
  fvfrmax  the best freshman's E[FV] at the mean above 20
  frlow    fvfrm x (1 - transfers' projected minutes share) (freshman-led teams with few transfers)
  frmin    freshmen's projected minutes share
  lastsq   max(0, last)^2 / 20 (the prior is compressed at the top: top-60 priors finish +1.0 over it)
  fvtopsq  max(0, fvtop)^2 / 10
Margin term (no rewalk): frdev = (frmin home - away) x days since Nov 1 / 100 (freshmen improve through the season)
Bar (as cbb_oct30_research): tune 2016-20 paired t <= -1.5 (clustered by game day and home team-season), 2021-26 no
worse, lined games no worse.
"""
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H
import cbb_oct30_research as O

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cbb_fvgame_research.json')


def roster_fv_terms():
    """season -> Barttorvik team -> the FV / freshman terms above"""
    import cbb_games as C
    import cbb_roster as R
    by = R.load_seasons()
    ts = R.team_strength(by)
    _, _, models = R.build(by, ts)
    f = R.f
    out = {}
    for y in sorted(by):
        if y - 1 not in by or y not in models:
            continue
        M = models[y]
        T = defaultdict(list)                  # team -> [(kind, projected minutes, E grade, E at mean)]
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            kd = R.kind(r, p, h)
            if kd not in M:
                continue
            x = R.xrow(kd, r, h if h else p, ts, y)
            mn = max(0.5, float(np.dot(M[kd][1], x)))
            q = h[0] if h else p
            if kd in ('ret', 'tr', 'back') and q is not None and f(q.get('min_per')):
                e = C.player_fv(C.research_feats(q, r['team']), 'returner'); em = e
            elif kd == 'fr':
                lr = [-math.log(min(float(v), 500)) for v in (r.get('on3rk'), r.get('rk247')) if v not in (None, '', 'nan') and float(v) > 0]
                l = sum(lr) / len(lr) if lr else -math.log(600)
                e = C.player_fv({'rg_lrk': l, 'top': max(0.0, l + math.log(25)), 'top5': max(0.0, l + math.log(5)), 'yr': 1.0}, 'newcomer')
                em = C.fr_mean(e, 'G' if r.get('guard') == '1.0' else 'C' if r.get('big') == '1.0' else 'F')
            else:
                e = em = 20.0
            T[r['team']].append((kd, mn, e, em))
        o = {}
        for t, L in T.items():
            tot = sum(m for _, m, _, _ in L)
            frs = [em - 20 for k, _, _, em in L if k == 'fr']
            fvfrm = sum(frs)
            trs = sum(m for k, m, _, _ in L if k == 'tr') / tot
            o[t] = {'fvpm': round(sum(m / tot * (e - 20) for _, m, e, _ in L), 4),
                    'fvfr2': round(sum(v * v for v in frs) / 10, 4), 'fvfrmax': round(max(frs) if frs else 0.0, 4),
                    'frlow': round(fvfrm * (1 - trs), 4), 'frmin': round(sum(m for k, m, _, _ in L if k == 'fr') / tot, 4)}
        out[y] = o
    return out


def walk_extra(W):
    """lastsq / fvtopsq: computed from the walk's own feats"""
    import cbb_games as C
    pf0 = C.Walk.prior_feats

    def pf(self, s, t, last):
        o = pf0(self, s, t, last)
        o['lastsq'] = max(0.0, o['last']) ** 2 / 20
        o['fvtopsq'] = max(0.0, o.get('fvtop', 0.0)) ** 2 / 10
        return o
    C.Walk.prior_feats = pf


_A = {}


def _one(v):
    import cbb_games as C
    lab, pf = v[0], v[1]
    games, btname, d1s, tprior, avs, P, feats = _A['args']
    walk_extra(None)
    C.PRIOR_F = list(C.PRIOR_F) + pf
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pc = W.prior_coef(C.LAST + 1)
    res = {'pr': C.walk_pred(Xm, y, S, d1), 'ids': [g['id'] for g, _, _ in D],
           'prior': {k: round(float(pc[k]), 4) for k in C.PRIOR_F}}
    if lab == 'base':
        res.update(y=y, S=S, line=line, d1=d1, D=[(g['id'], g['date'][:10], g['season'], g['home'], g['away'], g['neutral']) for g, _, _ in D])
        # margin-only terms on the same walk
        fr = _A['terms']
        for nm, scale in (('frdev', 1.0),):
            col = []
            for g, x, _ in D:
                s = g['season']; day = max(0, (datetime.strptime(C.et_date(g['date']), '%Y-%m-%d') - datetime(s - 1, 11, 1)).days)
                fh = fr.get(s, {}).get(btname.get(g['home']), {}).get('frmin', 0.0)
                fa = fr.get(s, {}).get(btname.get(g['away']), {}).get('frmin', 0.0)
                col.append((fh - fa) * day / 100 * scale)
            X2 = np.column_stack([Xm, np.array(col)])
            res['m_' + nm] = C.walk_pred(X2, y, S, d1)
    return lab, res


VARIANTS = [('base', []), ('fvpm', ['fvpm']), ('fvfr2', ['fvfr2']), ('fvfrmax', ['fvfrmax']), ('frlow', ['frlow']),
            ('frmin', ['frmin']), ('lastsq', ['lastsq']), ('fvtopsq', ['fvtopsq'])]


def main():
    import multiprocessing as mp
    import cbb_games as C
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    terms = roster_fv_terms()
    _A['terms'] = terms
    cover = {}
    for s, T in tprior.items():
        for t, f in T.items():
            f.update(terms.get(int(s), {}).get(t, {}))
        cover[s] = sum(1 for f in T.values() if 'fvpm' in f)
    print('coverage', cover, flush=True)
    _A['args'] = (games, btname, d1s, tprior, avs, F['params'], list(F['feats']))
    V = VARIANTS
    if '--only' in sys.argv:
        keep = sys.argv[sys.argv.index('--only') + 1].split(',')
        V = [V[0]] + [v for v in V if v[0] in keep]
    with mp.get_context('fork').Pool(int(os.environ.get('PROCS', 4)), maxtasksperchild=1) as pool:
        out_r = dict(pool.map(_one, V))
    b = out_r['base']
    ok = ~np.isnan(b['pr']) & b['d1']
    S = b['S']
    k1 = ok & (S >= C.SCORE0) & (S <= C.TUNE_END); k2 = ok & (S > C.TUNE_END)
    day = np.array([d[1] for d in b['D']]); team = np.array([f'{d[3]}|{d[2]}' for d in b['D']])
    early = np.array([d[5:] >= '11-01' and d[5:] <= '12-15' for d in day])
    late = np.array([d[5:] >= '02-01' and d[5:] <= '04-30' for d in day])
    masks = {'tune': k1, 'held': k2, 'tuneEarly': k1 & early, 'heldEarly': k2 & early, 'heldLate': k2 & late,
             'held21_23': k2 & (S <= 2023), 'held24_26': k2 & (S >= 2024)}
    cl = [day, team]
    out = []
    for v in V[1:]:
        lab, pf = v[0], v[1]
        r = out_r[lab]
        assert r['ids'] == b['ids']
        out.append(O.score(lab, r['pr'], b['pr'], b['y'], b['line'], masks, cl, {'priorTerms': pf, 'priorCoef': {k: r['prior'][k] for k in pf}}))
    for k in [k for k in b if k.startswith('m_')]:
        out.append(O.score(k, b[k], b['pr'], b['y'], b['line'], masks, cl, {'marginTerm': k[2:]}))
    base_mae = {nm: round(float(np.abs(b['pr'][k] - b['y'][k]).mean()), 4) for nm, k in masks.items()}
    with open(OUT, 'w') as f:
        json.dump({'results': out, 'base': base_mae, 'coverage': cover}, f, indent=1)


if __name__ == '__main__':
    main()
