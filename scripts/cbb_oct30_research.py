#!/usr/bin/env python3
"""CBB team-ranking research, Oct 30 2026: preseason-prior terms not tried before (the ARK Ranking = cbb_games ratings).

    python3 scripts/cbb_oct30_research.py [--only lab,lab]    # -> data/cbb_oct30_research.json

Each term is built from a first (shipped) walk: per team-season, the walk's preseason prior net and its final net.
  cres     the head coach's mean prior miss (final - prior) over his earlier seasons, any school (Sports Reference
           coaches, 2015 on), shrunk: sum / (n + k). Coaches who beat the roster projection year after year
  cres_s   the same, only seasons at the current school
  pres     the program's mean prior miss over the last three seasons, shrunk (a projection bias by program)
  ltrend   last season's walk-forward residual over the team's last 12 D-I games x the returning minutes share
           (a team that improved late, and keeps the players who did it)
  hgt      the roster's projected-minutes-weighted height (inches over the season's D-I mean), from cbb_roster's
           walk-forward minutes models
Bar (as cbb_ark_research): tune 2016-20 paired t <= -1.5 (clustered by game day and home team-season), 2021-26 no worse,
lined games no worse.
"""
import json
import math
import os
import sys
from collections import defaultdict

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cbb_oct30_research.json')
RES0 = 2015          # first season whose prior miss counts (2014's prior had no history)


def base_tables(W, D, pr, y, d1s, btname):
    """per (season, Barttorvik team): prior net, final net; per team-season the walk-forward residuals in date order"""
    prior, final = {}, {}
    for s in sorted(W.final):
        if s not in d1s:
            continue
        p, _ = W.season_prior(s, sorted(d1s[s]))
        for t, v in p.items():
            b = btname.get(t)
            if b and t in W.final[s]:
                prior[(s, b)] = v['net']; final[(s, b)] = W.final[s][t]['net']
    res = defaultdict(list)
    for (g, _, _), p, yy in zip(D, pr, y):
        if np.isnan(p) or g['home'] not in d1s[g['season']] or g['away'] not in d1s[g['season']]:
            continue
        r = yy - p
        for t, sg in ((g['home'], 1), (g['away'], -1)):
            b = btname.get(t)
            if b:
                res[(g['season'], b)].append((g['date'], sg * r))
    return prior, final, res


def coach_terms(prior, final, tprior, k):
    import cbb_roster as R
    raw = R.coach_feats(R.load_coaches(), tprior, raw=True)
    hist = defaultdict(list)       # coach -> [(season, team, miss)]
    for s in sorted(raw):
        for t, v in raw[s].items():
            if s >= RES0 and (s, t) in prior:
                hist[v['coach']].append((s, t, final[(s, t)] - prior[(s, t)]))
    out = defaultdict(dict)
    for s in sorted(raw):
        for t, v in raw[s].items():
            h = [m for ss, tt, m in hist[v['coach']] if ss < s]
            hs = [m for ss, tt, m in hist[v['coach']] if ss < s and tt == t]
            out[s][t] = {f'cres{k}': sum(h) / (len(h) + k), f'cres_s{k}': sum(hs) / (len(hs) + k)}
    return out


def program_terms(prior, final, k=3.0, back=3):
    out = defaultdict(dict)
    teams = {t for _, t in prior}
    for s in range(2014, 2028):
        for t in teams:
            m = [final[(ss, t)] - prior[(ss, t)] for ss in range(s - back, s) if ss >= RES0 and (ss, t) in prior]
            out[s][t] = {'pres': sum(m) / (len(m) + k)}
    return out


def trend_terms(res, tprior, n=12):
    out = defaultdict(dict)
    for (s, t), L in res.items():
        L = sorted(L)
        if len(L) < 20:
            continue
        late = float(np.mean([r for _, r in L[-n:]]))
        f = (tprior.get(str(s + 1)) or {}).get(t)
        if f is not None:
            out[s + 1][t] = {'ltrend': late * f.get('retmin', 0.0), 'ltrend0': late}
    return out


def height_terms():
    """season -> team -> projected-minutes-weighted height over the season's mean (cbb_roster's minutes models)"""
    import cbb_roster as R
    by = R.load_seasons()
    ts = R.team_strength(by)
    _, _, models = R.build(by, ts)
    out = {}
    for y in sorted(by):
        if y - 1 not in by or y not in models:
            continue
        M = models[y]
        T = defaultdict(list)
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            kd = R.kind(r, p, h)
            if kd not in M:
                continue
            try:
                ht = float(r.get('hti') or 'nan')
            except ValueError:
                ht = float('nan')
            x = R.xrow(kd, r, h if h else p, ts, y)
            T[r['team']].append((max(0.5, float(np.dot(M[kd][1], x))), ht))
        v = {}
        for team, L in T.items():
            L2 = [(m, h) for m, h in L if not math.isnan(h) and 66 <= h <= 90]
            if len(L2) >= 5:
                v[team] = sum(m * h for m, h in L2) / sum(m for m, _ in L2)
        if v:
            mu = float(np.mean(list(v.values())))
            out[y] = {t: {'hgt': x - mu} for t, x in v.items()}
    return out


_A = {}


def _one(v):
    import cbb_games as C
    lab, pf = v[0], v[1]
    games, btname, d1s, tprior, avs, P, feats = _A['args']
    P = {**P, **(v[2] if len(v) > 2 else {})}
    C.PRIOR_F = list(C.PRIOR_F) + pf
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pc = W.prior_coef(C.LAST + 1)
    res = {'pr': C.walk_pred(Xm, y, S, d1), 'ids': [g['id'] for g, _, _ in D],
           'prior': {k: round(float(pc[k]), 4) for k in C.PRIOR_F}}
    if lab == 'base':
        res.update(y=y, S=S, line=line, d1=d1, D=[(g['id'], g['date'][:10], g['season'], g['home'], g['away'], g['neutral']) for g, _, _ in D])
    return lab, res


def score(lab, pr, ref, y, line, masks, cl, extra=None):
    ok = ~np.isnan(line)
    r = {'label': lab, **(extra or {})}
    for nm, k in masks.items():
        e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
        p = H.paired(e, e0, cluster=[c[k] for c in cl])
        kk = k & ok
        r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4),
                 't': round(p['t'], 2), 'dLined': round(float(np.abs(pr[kk] - y[kk]).mean() - np.abs(ref[kk] - y[kk]).mean()), 4),
                 'tLined': round(H.paired(np.abs(pr[kk] - y[kk]), np.abs(ref[kk] - y[kk]), cluster=[c[kk] for c in cl])['t'], 2)}
    r['pass'] = r['tune']['t'] <= -1.5 and r['held']['d'] <= 0 and r['held']['dLined'] <= 0
    print(json.dumps(r), flush=True)
    return r


VARIANTS = [('base', []), ('cres2', ['cres2']), ('cres4', ['cres4']), ('cres_s2', ['cres_s2']), ('cres_s4', ['cres_s4']),
            ('pres', ['pres']), ('ltrend', ['ltrend']), ('ltrend0', ['ltrend0']), ('hgt', ['hgt']),
            # blowout damping inside the efficiency solve (cbb_games Ratings.add, P bcap / bslope / brel)
            ('b20', [], {'bcap': 20.0}), ('b30', [], {'bcap': 30.0}), ('b20s0', [], {'bcap': 20.0, 'bslope': 0.0}),
            ('r15', [], {'bcap': 15.0, 'brel': 1}), ('r25', [], {'bcap': 25.0, 'brel': 1}), ('r25s0', [], {'bcap': 25.0, 'brel': 1, 'bslope': 0.0})]


def main():
    import multiprocessing as mp
    import cbb_games as C
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    _A['args'] = (games, btname, d1s, tprior, avs, F['params'], list(F['feats']))
    if True:
        W, rows = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, list(F['feats']))
        pr = C.walk_pred(Xm, y, S, d1)
        # 2014-15 have no walk-forward prediction: their residuals come from one fit on those seasons (features only)
        k = np.isnan(pr) & d1 & (S >= 2014)
        if k.any():
            b = np.linalg.lstsq(Xm[k], y[k], rcond=None)[0]
            pr = np.where(k, Xm @ b, pr)
    prior, final, res = base_tables(W, D, pr, y, d1s, btname)
    add = defaultdict(lambda: defaultdict(dict))
    for kk in (2.0, 4.0):
        for s, T in coach_terms(prior, final, tprior, kk).items():
            for t, v in T.items():
                add[s][t].update({k.replace('.0', ''): x for k, x in v.items()})
    for src in (program_terms(prior, final), trend_terms(res, tprior), height_terms()):
        for s, T in src.items():
            for t, v in T.items():
                add[s][t].update(v)
    cover = {}
    for s, T in tprior.items():
        for t, f in T.items():
            f.update(add.get(int(s), {}).get(t, {}))
        cover[s] = {k: sum(1 for f in T.values() if k in f) for k in ('cres2', 'pres', 'ltrend', 'hgt')}
    print('coverage', cover, flush=True)
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
    masks = {'tune': k1, 'held': k2, 'tuneEarly': k1 & early, 'heldEarly': k2 & early,
             'held21_23': k2 & (S <= 2023), 'held24_26': k2 & (S >= 2024)}
    cl = [day, team]
    out = []
    for v in V[1:]:
        lab, pf = v[0], v[1]
        r = out_r[lab]
        assert r['ids'] == b['ids']
        out.append(score(lab, r['pr'], b['pr'], b['y'], b['line'], masks, cl, {'priorTerms': pf, 'priorCoef': {k: r['prior'][k] for k in pf}, 'params': (v[2] if len(v) > 2 else {})}))
    base_mae = {nm: round(float(np.abs(b['pr'][k] - b['y'][k]).mean()), 4) for nm, k in masks.items()}
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    old = {r['label']: r for r in d.get('results', [])}
    old.update({r['label']: r for r in out})
    d.update(results=list(old.values()), base=base_mae, coverage=cover)
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)


if __name__ == '__main__':
    main()
