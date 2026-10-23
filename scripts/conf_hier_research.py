#!/usr/bin/env python3
"""Hierarchical conference ratings (team model idea 5, Oct 2026): a team's rating as its conference's effect plus its
own deviation, each with its own prior and season carryover, in place of one flat shrink toward the national mean.
Conferences link to each other only through non-conference games (most of them in November and December), so a flat
ridge can't tell a strong team in a weak league from a weak team in a strong one until those games are in; a shared
conference effect moves every member when one of them plays outside the league.

    python3 scripts/conf_hier_research.py cbb [--only i,j]   # cbb_games ratings: P['cv'] and the 'clast' prior term
    python3 scripts/conf_hier_research.py cfbfeat            # CFB research features -> scripts/.cache/cfb/conf_feat.json
                                                             # (scored by scripts/cfb_conf_backtest.mjs)

CBB, both in scripts/cbb_games.py and off by default:
  cv     the conference effect's prior variance as a multiple of a team's (Ratings: the O and D priors become
         lam x (I + cv Z Z')^-1 in place of lam x I; prior means unchanged)
  clast  a preseason prior term: last season's final rating of this season's conference-mates (the team left out),
         over the D-I mean: the conference's own carryover next to the team's ('last')
Ship bar (briefs.md): tune 2016-20 paired t <= -1.5 (clustered by game day and home team-season), 2021-26 no worse.
Also scored on the first six weeks (games through Dec 15) alone. Results -> data/conf_hier_research.json.
"""
import json
import os
import sys

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')        # before numpy: BLAS threads in forked workers make the CBB solves crawl

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'conf_hier_research.json')


def save(sport, rows):
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    old = [r for r in d.get(sport, []) if r['label'] not in {o['label'] for o in rows}]
    d[sport] = old + rows
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1)


def score(lab, pr, ref, y, line, masks, cl, extra=None):
    ok = ~np.isnan(line)
    r = {'label': lab, **(extra or {})}
    for nm, k in masks.items():
        e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
        p = H.paired(e, e0, cluster=[c[k] for c in cl])
        kk = k & ok
        r[nm] = {'n': int(k.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4),
                 't': round(p['t'], 2), 'maeLined': round(float(np.abs(pr[kk] - y[kk]).mean()), 4),
                 'dLined': round(float(np.abs(pr[kk] - y[kk]).mean() - np.abs(ref[kk] - y[kk]).mean()), 4)}
    r['pass'] = r['tune']['t'] <= -1.5 and r['held']['d'] <= 0
    print(json.dumps(r), flush=True)
    return r


# ---------------------------------------------------------------- CBB
_CBB = {}
CBB_V = [('base', {}, []), ('cv .1', {'cv': 0.1}, []), ('cv .25', {'cv': 0.25}, []), ('cv .5', {'cv': 0.5}, []),
         ('cv 1', {'cv': 1.0}, []), ('clast', {}, ['clast']), ('cv .25 + clast', {'cv': 0.25}, ['clast']),
         ('cv .5 + clast', {'cv': 0.5}, ['clast']), ('cv 2', {'cv': 2.0}, []), ('cv .05', {'cv': 0.05}, [])]


def _cbb_one(v):
    import cbb_games as C
    games, btname, d1s, tprior, avs, P, feats = _CBB['args']
    C.PRIOR_F = list(C.PRIOR_F) + v[2]
    W, rows = C.run_walk({**P, **v[1]}, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pc = W.prior_coef(C.LAST + 1)
    return v[0], {'pr': C.walk_pred(Xm, y, S, d1), 'y': y, 'S': S, 'line': line, 'd1': d1,
                  'day': np.array([g['date'][:10] for g, _, _ in D]),
                  'team': np.array([f"{g['home']}|{g['season']}" for g, _, _ in D]), 'ids': [g['id'] for g, _, _ in D],
                  'nc': np.array([not g.get('conf') for g, _, _ in D]),
                  'prior': {k: round(float(pc[k]), 4) for k in v[2]}}


def cbb():
    import multiprocessing as mp
    import cbb_games as C
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    _CBB['args'] = (games, btname, d1s, tprior, avs, F['params'], list(F['feats']))
    V = CBB_V
    if '--only' in sys.argv:
        V = [V[0]] + [V[int(i)] for i in sys.argv[sys.argv.index('--only') + 1].split(',')]
    with mp.get_context('fork').Pool(int(os.environ.get('PROCS', 3))) as pool:
        res = dict(pool.map(_cbb_one, V))
    b = res['base']
    ok = ~np.isnan(b['pr']) & b['d1']
    k1 = ok & (b['S'] >= C.SCORE0) & (b['S'] <= C.TUNE_END); k2 = ok & (b['S'] > C.TUNE_END)
    early = np.array([d[5:] >= '11-01' and d[5:] <= '12-15' for d in b['day']])
    masks = {'tune': k1, 'held': k2, 'tuneEarly': k1 & early, 'heldEarly': k2 & early, 'heldNonConf': k2 & b['nc']}
    out = []
    for lab, extra, pf in V[1:]:
        r = res[lab]
        assert r['ids'] == b['ids']
        out.append(score(lab, r['pr'], b['pr'], b['y'], b['line'], masks, [b['day'], b['team']],
                         {'params': extra, 'priorTerms': pf, 'priorCoef': r['prior']}))
    save('cbb', out)


# ---------------------------------------------------------------- CFB
def hier_ratings(games, lam=3.0, cv=1.0, carry=0.6, ccarry=0.8, cap=28.0, hl=None, tier=None, tv=25.0):
    """games: [(id, date, season, home, away, neutral, home conf, away conf, margin or None)] in date order. A ridge
    Massey fit, each team = its conference's effect + its own deviation (+ home court): deviations shrunk toward
    carry x last season's deviation with lam games of weight, conference effects toward ccarry x last season's effect
    with lam / cv (cv 0: no conference effect, the flat rating). Teams with no conference (independents) have only a
    deviation. tier: conference -> tier (P4, G5, FCS), a third level over the conferences, its effect with lam / tv
    and carried whole; the conference-effect gap then includes the tier's. Returns {id: (full home-minus-away rating
    gap, conference-effect gap)} before each game, and the finals."""
    from collections import defaultdict
    feat, finals = {}, {}
    by = defaultdict(list)
    for g in games:
        by[g[2]].append(g)
    prevT, prevC, prevU = {}, {}, {}
    for S in sorted(by):
        gs = sorted(by[S], key=lambda g: g[1])
        teams = sorted({t for g in gs for t in (g[3], g[4])})
        confs = sorted({c for g in gs for c in (g[6], g[7]) if c}) if cv else []
        conf = {}
        for g in gs:
            if g[6]:
                conf[g[3]] = g[6]
            if g[7]:
                conf[g[4]] = g[7]
        ix = {t: k for k, t in enumerate(teams)}
        nt = len(teams)
        cx = {c: nt + k for k, c in enumerate(confs)}
        tiers = sorted({tier(S, c) for c in confs}) if tier else []
        tx = {u: nt + len(confs) + k for k, u in enumerate(tiers)}
        n = nt + len(confs) + len(tiers) + 1
        A = np.zeros((n, n)); b = np.zeros(n)
        pri = np.zeros(n); reg = np.full(n, lam); reg[-1] = 1e-3
        for t in teams:
            pri[ix[t]] = carry * prevT.get(t, 0.0)
        for c in confs:
            pri[cx[c]] = ccarry * prevC.get(c, 0.0); reg[cx[c]] = lam / cv
        for u in tiers:
            pri[tx[u]] = prevU.get(u, 0.0); reg[tx[u]] = lam / tv
        r = pri.copy()
        last = None
        k = 0

        def row(t):
            x = np.zeros(n); x[ix[t]] = 1
            c = conf.get(t)
            if c in cx:
                x[cx[c]] = 1
                if tiers:
                    x[tx[tier(S, c)]] = 1
            return x
        ceff = lambda c: (r[cx[c]] + (r[tx[tier(S, c)]] if tiers else 0.0)) if c in cx else 0.0
        while k < len(gs):
            day = gs[k][1]
            if last is not None and hl:
                f = 0.5 ** ((np.datetime64(day) - np.datetime64(last)).astype(int) / hl)
                A *= f; b *= f
            last = day
            if A.any():
                r = np.linalg.solve(A + np.diag(reg), b + reg * pri)
            todays = []
            while k < len(gs) and gs[k][1] == day:
                todays.append(gs[k]); k += 1
            for g in todays:
                ch, ca = conf.get(g[3]), conf.get(g[4])
                cg = ceff(ch) - ceff(ca)
                full = float((row(g[3]) - row(g[4])) @ r)
                feat[g[0]] = (round(full, 3), round(float(cg), 3))
            for g in todays:
                if g[8] is None:
                    continue
                x = row(g[3]) - row(g[4])
                if not g[5]:
                    x[-1] = 1
                A += np.outer(x, x); b += x * max(-cap, min(cap, g[8]))
        r = np.linalg.solve(A + np.diag(reg), b + reg * pri)
        prevT = {t: float(r[ix[t]]) for t in teams}
        prevC = {c: float(r[cx[c]]) for c in confs}
        prevU = {u: float(r[tx[u]]) for u in tiers}
        finals[S] = {'team': prevT, 'conf': prevC, 'tier': prevU, 'hca': float(r[-1])}
    return feat, finals


P4C = {'SEC', 'Big Ten', 'Big 12', 'ACC'}


def cfb_tier(S, c):
    """Power 4 (the Pac-12 through 2023), Group of 5, FCS"""
    return 'FCS' if c == 'FCS' else 'P4' if c in P4C or (c == 'Pac-12' and S <= 2023) else 'G5'


CFB_GRID = {'flat': dict(cv=0.0), 'cv.5': dict(cv=0.5), 'cv1': dict(cv=1.0), 'cv2': dict(cv=2.0), 'cv4': dict(cv=4.0),
            'cv1c1': dict(cv=1.0, ccarry=1.0), 'cv1c.5': dict(cv=1.0, ccarry=0.5), 'cv2c1': dict(cv=2.0, ccarry=1.0),
            'cv1t.3': dict(cv=1.0, carry=0.3), 'cv1l6': dict(cv=1.0, lam=6.0),
            't_cv1': dict(cv=1.0, tier=cfb_tier), 't_cv.5': dict(cv=0.5, tier=cfb_tier), 't_cv1c1': dict(cv=1.0, ccarry=1.0, tier=cfb_tier),
            't_cv2c1': dict(cv=2.0, ccarry=1.0, tier=cfb_tier), 't_cv1tv100': dict(cv=1.0, tier=cfb_tier, tv=100.0)}


def cfb_games(md_path=None):
    """[(id, date, season, home, away, neutral, home conf, away conf, margin)] from the ESPN md (FCS teams share one
    conference, 'FCS'; FBS independents have none)"""
    import gzip
    md = json.load(gzip.open(md_path or os.path.join(HERE, '.cache', 'cfb', 'espn_md.json.gz'), 'rt'))
    def cf(c, cls):
        if cls != 'fbs':
            return 'FCS'
        return None if not c or 'Independent' in c else c
    out = []
    for S, gs in md['games'].items():
        for g in gs:
            m = g['homePoints'] - g['awayPoints'] if g.get('completed') and g.get('homePoints') is not None and g.get('awayPoints') is not None else None
            out.append((str(g['id']), g['startDate'][:10], int(S), str(g['homeId']), str(g['awayId']), bool(g.get('neutralSite')),
                        cf(g.get('homeConference'), g.get('homeClassification')), cf(g.get('awayConference'), g.get('awayClassification')), m))
    out.sort(key=lambda g: g[1])
    return out


def cfb_feat(md_path=None):
    gl = cfb_games(md_path)
    out = {'params': {}, 'variants': {}}
    for k, p in CFB_GRID.items():
        f, _ = hier_ratings(gl, **p)
        q = {a: (b if a != 'tier' else 'P4/G5/FCS') for a, b in p.items()}
        out['params'][k] = q
        out['variants'][k] = {i: v[0] for i, v in f.items()}
        if p['cv']:
            out['params'][k + '_c'] = {**q, 'part': 'conference effect only'}
            out['variants'][k + '_c'] = {i: v[1] for i, v in f.items()}
        print(k, len(f), flush=True)
    p = os.path.join(HERE, '.cache', 'cfb', 'conf_feat.json')
    json.dump(out, open(p, 'w'))
    print(len(gl), 'games ->', p)


if __name__ == '__main__':
    if sys.argv[1] == 'cbb':
        cbb()
    elif sys.argv[1] == 'cfbfeat':
        cfb_feat(sys.argv[2] if len(sys.argv) > 2 else None)
