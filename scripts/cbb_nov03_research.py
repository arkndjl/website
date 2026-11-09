#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB game model research, Nov 3 2026: do the day's new CBB metrics (PR #734 production tabs, Stat+ FV driver, team
context in xBPM) improve the preseason prior of the game model (= the ARK Ranking)?

    python3 scripts/cbb_nov03_research.py [--only lab,lab]    # -> data/cbb_nov03_research.json

Candidates, each built from the research seasons (one row per player season, nothing from the season itself but
roster membership and class), each run through the full game walk (walk-forward prior regression):
  fvx       fvtop with the board's full returner FV model: porpag, ht_g and Stat+ (the Nov 3 driver) were missing
            from research_feats / team_fv_live, so they sat at the mean in the game model's top-5 E[FV]
  rret_x    the returners' projected sum (cbb_roster rret) with PR #734's xBPM context in each player projection:
            returning teammates' WAR (mates_war), teammates' recruiting (tal_team), transfer up / down a level
  rtr_x     the same for transfers (in place of tr / trmin, the raw last-season sums)
  rost_x    the whole projected roster with the context (rost failed Oct 21 without it)
  rwar      returning WAR (production tabs: (BPM + 2) x minutes x pace x wins per point); inwar transfers in; netwar
            returning + in - last season's total
  retsp     returners' minutes-share-weighted Stat+ z (BPM against his position); trsp the same for transfers
  tal8      the roster's top-8 recruiting (mean -ln rank), the production tabs' team talent on recruiting
Bar: tune 2016-20 paired t <= -1.5 (clustered by game day and home team-season), 2021-26 MAE and lined MAE no worse,
and Holm (family-wise .05, one-sided) on the 2021-26 t over every candidate run.
"""
import json
import math
import os
import sys
from collections import defaultdict
from statistics import NormalDist

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'cbb_nov03_research.json')
WPP = 0.01243
SPLUS = {'G': (0.10, 3.85), 'F': (0.50, 4.05), 'C': (0.52, 4.31)}
POS3 = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}
ROLES = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'W', 'Wing F': 'W', 'Stretch 4': 'B', 'PF/C': 'B', 'C': 'B'}
POWER = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}


def f(x, d=None):
    try:
        v = float(x)
        return d if math.isnan(v) else v
    except (TypeError, ValueError):
        return d


def lrk(r):
    lr = f(r.get('rg_lrk'))
    return lr if lr is not None and f(r.get('unranked'), 1) == 0 else -math.log(600)


def team_games(rows):
    g = defaultdict(float)
    for r in rows.values():
        g[r['team']] = max(g[r['team']], f(r['gp'], 0))
    return g


def war(r, G):
    """a research row's WAR as the production tabs count it, at 68 possessions"""
    b = f(r['bpm'])
    if b is None:
        return 0.0
    mpt = f(r['min_per'], 0) / 100 * 40 * G.get(r['team'], 30)
    return (b + 2) * mpt / 40 * 0.68 * WPP


def splus_z(r):
    mu, sd = SPLUS.get(POS3.get(r.get('role'), 'F'), SPLUS['F'])
    return (f(r['bpm'], -4.0) - mu) / sd


def context(by):
    """(year, pid) -> mates_war, tal_team (cbb_fit.team_terms on the research seasons)"""
    out = {}
    for y in sorted(by):
        if y - 1 not in by:
            continue
        G1 = team_games(by[y - 1])
        W1 = {pid: war(r, G1) for pid, r in by[y - 1].items()}
        roster = defaultdict(list)
        for pid, r in by[y].items():
            roster[r['team']].append(pid)
        for team, L in roster.items():
            back = [q for q in L if q in by[y - 1] and by[y - 1][q]['team'] == team and f(by[y - 1][q]['min_per'])]
            tw = sum(W1[q] for q in back)
            ranks = sorted(((lrk(by[y][q]), q) for q in L), reverse=True)
            for pid in L:
                rl = [v for v, q in ranks if q != pid][:8]
                out[(y, pid)] = (tw - (W1[pid] if pid in back else 0.0), sum(rl) / len(rl) if rl else -math.log(600))
    return out


def roster_terms(by):
    """cbb_roster.build with the PR #734 context appended to every player projection -> year -> team -> rret_x, ..."""
    import cbb_roster as R
    ts = R.team_strength(by)
    ctx = context(by)
    pairs = defaultdict(list)
    for y in sorted(by):
        if y - 1 not in by:
            continue
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            h = R.healthy({y - k: by[y - k][pid] for k in (1, 2, 3) if y - k in by and pid in by[y - k]}, y)
            k = R.kind(r, p, h)
            x = R.xrow(k, r, h if h else p, ts, y)
            mw, tt = ctx.get((y, pid), (0.0, -math.log(600)))
            ex = [mw, tt + math.log(600)]
            if k == 'tr':
                pc = p['conf'] in POWER
                nc = r['conf'] in POWER
                ex += [1.0 if nc and not pc else 0.0, 1.0 if pc and not nc else 0.0]
            pairs[y].append((k, x + ex, f(r['bpm'], R.REPL), f(r['min_per'], 0), r['team'], x))
    out = {}
    for y in range(2014, 2027):
        tr = [q for yy in pairs if yy < y for q in pairs[yy]]
        M = {}
        for k in ('ret', 'tr', 'fr', 'new', 'back'):
            Q = [q for q in tr if q[0] == k]
            if not Q:
                continue
            bw = R.wls([q[1] for q in Q], [max(-15, min(15, q[2])) for q in Q], [q[3] / 100 + 0.02 for q in Q])
            mw = R.wls([q[5] for q in Q], [q[3] for q in Q], [1.0] * len(Q))      # minutes: the shipped inputs
            M[k] = (bw, mw)
        T = defaultdict(list)
        for k, x, _, _, team, x0 in pairs[y]:
            if k not in M:
                continue
            T[team].append((k, float(np.dot(M[k][0], x)), max(0.5, float(np.dot(M[k][1], x0)))))
        out[y] = {}
        for team, L in T.items():
            tot = sum(m for _, _, m in L)
            g = lambda ks: sum(500 * m / tot / 100 * b for k, b, m in L if k in ks)
            out[y][team] = {'rret_x': round(g({'ret', 'back'}), 3), 'rtr_x': round(g({'tr'}), 3),
                            'rost_x': round(g({'ret', 'tr', 'fr', 'new', 'back'}), 3)}
    return out


def war_terms(by):
    out = defaultdict(dict)
    for y in sorted(by):
        if y - 1 not in by:
            continue
        G1 = team_games(by[y - 1])
        tot = defaultdict(float)
        for r in by[y - 1].values():
            tot[r['team']] += war(r, G1)
        T = defaultdict(lambda: {'rwar': 0.0, 'inwar': 0.0, 'retsp': 0.0, 'trsp': 0.0, 'rk': []})
        for pid, r in by[y].items():
            t = T[r['team']]
            t['rk'].append(lrk(r))
            p = by[y - 1].get(pid)
            if p and f(p['min_per']):
                share = f(p['min_per'], 0) / 100
                if p['team'] == r['team']:
                    t['rwar'] += war(p, G1); t['retsp'] += share * splus_z(p)
                else:
                    t['inwar'] += war(p, G1); t['trsp'] += share * splus_z(p)
        for team, t in T.items():
            rk = sorted(t['rk'], reverse=True)[:8]
            out[y][team] = {'rwar': round(t['rwar'], 3), 'inwar': round(t['inwar'], 3),
                            'netwar': round(t['rwar'] + t['inwar'] - tot.get(team, 0.0), 3),
                            'retsp': round(t['retsp'], 3), 'trsp': round(t['trsp'], 3),
                            'tal8': round(sum(rk) / len(rk) + math.log(600), 3) if rk else 0.0}
    return out


def fv_terms(by):
    """fvtop with porpag, ht_g and Stat+ in the returner FV inputs (C.research_feats_full)"""
    import cbb_games as C
    out = {}
    for y in sorted(by):
        if y - 1 not in by:
            continue
        T = defaultdict(list)
        for pid, r in by[y].items():
            p = by[y - 1].get(pid)
            if p and p['min_per']:
                T[r['team']].append(C.player_fv(C.research_feats(p, r['team'], full=True), 'returner'))
            elif r['yr'] == 'Fr':
                lr = [-math.log(min(float(v), 500)) for v in (r.get('on3rk'), r.get('rk247')) if v not in (None, '', 'nan') and float(v) > 0]
                l = sum(lr) / len(lr) if lr else -math.log(600)
                T[r['team']].append(C.player_fv({'rg_lrk': l, 'top': max(0.0, l + math.log(25)), 'top5': max(0.0, l + math.log(5)), 'yr': 1.0}, 'newcomer'))
        out[y] = {t: {'fvx': round(sum(sorted(es, reverse=True)[:5]) / min(5, len(es)) - 20, 3)} for t, es in T.items() if es}
    return out


_A = {}


def _one(v):
    import cbb_games as C
    lab, pf = v[0], v[1]
    drop = v[2] if len(v) > 2 else []
    games, btname, d1s, tprior, avs, P, feats = _A['args']
    C.PRIOR_F = [k for k in C.PRIOR_F if k not in drop] + pf
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
    r['gate'] = r['tune']['t'] <= -1.5 and r['held']['d'] <= 0 and r['held']['dLined'] <= 0
    print(json.dumps(r), flush=True)
    return r


def holm(rs, alpha=0.05):
    """one-sided Holm over the held-out t of every candidate: True where the family-wise test rejects 'no gain'"""
    nd = NormalDist()
    ps = sorted(((nd.cdf(r['held']['t']), i) for i, r in enumerate(rs)))
    ok, m = {}, len(ps)
    for j, (p, i) in enumerate(ps):
        if p > alpha / (m - j):
            break
        ok[i] = True
    for i, r in enumerate(rs):
        r['holm'] = bool(ok.get(i))
        r['pass'] = r['gate'] and r['holm']


VARIANTS = [('base', []),
                    ('fvx', ['fvx'], ['fvtop']),
            ('rret_x', ['rret_x'], ['rret']),
            ('rtr_x', ['rtr_x'], ['tr', 'trmin']),
            ('rtr_x+', ['rtr_x']),
            ('rost_x', ['rost_x']),
            ('rwar', ['rwar']),
            ('inwar', ['inwar']),
            ('netwar', ['netwar']),
            ('retsp', ['retsp']),
            ('trsp', ['trsp']),
            ('tal8', ['tal8'])]


def main():
    import multiprocessing as mp
    import cbb_games as C
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    by = C.research_seasons()
    add = defaultdict(lambda: defaultdict(dict))
    for src in (roster_terms(by), war_terms(by), fv_terms(by)):
        for s, T in src.items():
            for t, v in T.items():
                add[int(s)][t].update(v)
    cover = {}
    for s, T in tprior.items():
        for t, fz in T.items():
            fz.update(add.get(int(s), {}).get(t, {}))
        cover[s] = {k: sum(1 for fz in T.values() if k in fz) for k in ('fvx', 'rret_x', 'rwar')}
    print('coverage', cover, flush=True)
    feats = list(F['feats'])
    # without ESPN's BPI history (scripts/.cache/cbb/bpi; public_ratings.py --cbb-bpi) 'bpi' falls back to eff + home and
    # is exactly collinear with them: walk_pred's unridged solve then turns on rounding (one season 0.7 MAE off).
    # cbb_games --fit drops it in that case; so does this
    if not C.BPI or os.environ.get('NO_BPI'):
        feats = [k for k in feats if k != 'bpi']
    print('feats', feats, flush=True)
    _A['args'] = (games, btname, d1s, tprior, avs, F['params'], feats)
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
        out.append(score(lab, r['pr'], b['pr'], b['y'], b['line'], masks, cl,
                         {'priorTerms': pf, 'dropped': v[2] if len(v) > 2 else [], 'priorCoef': {k: r['prior'][k] for k in pf}}))
    holm(out)
    base_mae = {nm: round(float(np.abs(b['pr'][k] - b['y'][k]).mean()), 4) for nm, k in masks.items()}
    with open(OUT, 'w') as fh:
        json.dump({'base': base_mae, 'coverage': cover, 'results': out}, fh, indent=1)
    for r in out:
        print(f"{r['label']:8s} tune t {r['tune']['t']:6.2f} held d {r['held']['d']:+.4f} t {r['held']['t']:6.2f} lined {r['held']['dLined']:+.4f} "
              f"gate {r['gate']} holm {r['holm']} {r['priorCoef']}")


if __name__ == '__main__':
    main()
