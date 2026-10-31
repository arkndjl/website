#!/usr/bin/env python3
"""Do the AP and Coaches polls add to the CBB / CFB game models? Research only (data/poll_research.json).

Inputs: the walk-forward game files (scripts/data/games_wf/<sport>.json.gz: model margin m, close L, result res) and
every poll release (scripts/data/polls/<sport>.json, scripts/rank_polls.py, with points and receiving votes). For
each game the latest release of each poll stamped (ESPN lastUpdated, else its date) at least a day before the game
day, so no poll can postdate the game.

Poll value of a team = poll points / that release's top points (others receiving votes included; unvoted 0), averaged
over AP and Coaches when both are out. Gap = home - away. Terms, each a stack on the model's margin, coefficients fit
walk-forward (each season on the seasons before it):
    pre    preseason poll gap, fading k/(k+g), g = the pair's mean games played (k fit on tune)
    wk     latest poll gap (weekly)
    wkchg  latest poll gap minus the gap in the poll before it (the voters' move)
    pre+wk both
Scored: abs error paired against the model (clustered by day) on tune and held seasons, and against the close: res - L
on the term, walk-forward fit, does it beat the close (abs error of L + b x term vs L); and the pick edge (`edge`): does
the term add to the model's disagreement with the close (L + a(m - L) + b x term vs L + a(m - L)).

Result (Oct 31 2026): nothing passes. CBB and CFB stacks on the model are flat or worse; CBB preseason poll vs close
tune t -1.9 but held 0.0 once the model is in.

    python3 scripts/poll_research.py cbb      # tune 2016-20, held 2021-26
    python3 scripts/poll_research.py cfb      # tune 2017-21, held 2022-26"""
import bisect
import collections
import datetime as dt
import gzip
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

SPLIT = {'cbb': (range(2016, 2021), range(2021, 2027)), 'cfb': (range(2017, 2022), range(2022, 2027))}


def day(s):
    return dt.date.fromisoformat(s[:10])


def releases(sport):
    P = json.load(open(os.path.join(HERE, 'data', 'polls', f'{sport}.json')))
    ids = collections.defaultdict(set)
    for i, n in P['names'].items():
        ids[n].add(i)
    by = collections.defaultdict(list)          # (S, poll) -> [(stamp day, {id: value})]
    for r in P['releases']:
        if r['poll'] not in ('ap', 'coaches') or not r.get('ranks'):
            continue
        stamp = max(day(r['date']), day(r['upd'])) if r.get('upd') else day(r['date'])
        top = max(x['pts'] or 0 for x in r['ranks']) or 1.0
        v = {x['id']: (x['pts'] or 0) / top for x in r['ranks'] + r.get('others', [])}
        if all(x['pts'] is None for x in r['ranks']):     # no points: rank only
            v = {x['id']: (26 - x['rk']) / 25 for x in r['ranks']}
        by[(r['S'], r['poll'])].append((stamp, v))
    for k in by:
        by[k].sort(key=lambda z: z[0])
    return by, P['names']


def build(sport):
    G = json.load(gzip.open(os.path.join(HERE, 'data', 'games_wf', f'{sport}.json.gz')))
    by, names = releases(sport)
    nid = collections.defaultdict(list)
    for i, n in names.items():
        nid[n].append(i)
    G = [g for g in G if g.get('res') is not None and g.get('m') is not None]
    G.sort(key=lambda g: g['date'])
    played = collections.Counter()
    rows = []
    for g in G:
        S, d = g['S'], day(g['date'])
        if sport == 'cfb':                       # kickoff in UTC: the ET day (late games roll past midnight UTC)
            d = (dt.datetime.fromisoformat(g['date'].replace('Z', '+00:00')) - dt.timedelta(hours=5)).date()
        gp = (played[(S, g['home'])] + played[(S, g['away'])]) / 2
        played[(S, g['home'])] += 1
        played[(S, g['away'])] += 1
        val = {}
        for poll in ('ap', 'coaches'):
            rel = by.get((S, poll), [])
            k = bisect.bisect_left([z[0] for z in rel], d - dt.timedelta(days=0)) - 1   # stamp < game day
            while k >= 0 and rel[k][0] >= d:
                k -= 1
            if k < 0:
                continue
            def tv(team, v):
                return max((v.get(i, 0.0) for i in nid.get(team, [])), default=0.0)
            cur, prv, pre = rel[k][1], rel[k - 1][1] if k > 0 else None, rel[0][1]
            val[poll] = (tv(g['home'], cur) - tv(g['away'], cur),
                         None if prv is None else tv(g['home'], prv) - tv(g['away'], prv),
                         tv(g['home'], pre) - tv(g['away'], pre))
        if not val:
            continue
        avg = lambda j: np.mean([v[j] for v in val.values() if v[j] is not None]) if any(v[j] is not None for v in val.values()) else 0.0
        wk, prv, pre = avg(0), avg(1), avg(2)
        rows.append({'S': S, 'd': str(d), 'm': g['m'], 'L': g.get('L'), 'res': g['res'], 'g': gp,
                     'wk': wk, 'wkchg': wk - prv if any(v[1] is not None for v in val.values()) else 0.0, 'pre': pre,
                     'ranked': int(wk != 0), 'voted': bool(val) and any(v[0] != 0 or v[2] != 0 for v in val.values())})
    return rows


def walk(X, y, S, seasons):
    """per-season OLS (no intercept) on earlier seasons only; first season of data -> 0"""
    b = np.zeros(len(X))
    for s in seasons:
        tr, te = S < s, S == s
        if tr.sum() < 200:
            continue
        coef, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        b[te] = X[te] @ coef
    return b


def run(sport):
    rows = build(sport)
    tune, held = SPLIT[sport]
    S = np.array([r['S'] for r in rows])
    m, res = np.array([r['m'] for r in rows]), np.array([r['res'] for r in rows], float)
    L = np.array([np.nan if r['L'] is None else -r['L'] if sport == 'cfb_neg' else r['L'] for r in rows], float)
    day_ = np.array([r['d'] for r in rows])
    g = np.array([r['g'] for r in rows])
    seasons = sorted(set(S))
    out = {'sport': sport, 'n': len(rows), 'ranked_share': float(np.mean([r['ranked'] for r in rows])), 'terms': {}}
    # which sign does L carry? (home spread as a home margin)
    ok = ~np.isnan(L)
    if np.corrcoef(L[ok], m[ok])[0, 1] < 0:
        L = -L
    out['L_r_m'] = float(np.corrcoef(L[ok], m[ok])[0, 1])

    def score(name, X, kfade=None):
        y = res - m
        pred = m + walk(X, y, S, seasons)
        rec = {}
        for lab, yrs, extra in (('tune', tune, None), ('held', held, None), ('tune_early', tune, early), ('held_early', held, early),
                                ('tune_voted', tune, voted), ('held_voted', held, voted)):
            k = np.isin(S, list(yrs)) & (True if extra is None else extra)
            p = H.paired(H.ae(pred[k], res[k]), H.ae(m[k], res[k]), cluster=day_[k])
            rec[lab] = {'n': int(k.sum()), 'd': round(float(p['d']), 4), 't': round(float(p['t']), 2)}
            # against the close: res - L on the term (walk-forward), lined games
            kl = k & ok
            if not kl.any():
                continue
            pc = L.copy()
            pc[ok] = L[ok] + walk(X[ok], (res - L)[ok], S[ok], seasons)
            pp = H.paired(H.ae(pc[kl], res[kl]), H.ae(L[kl], res[kl]), cluster=day_[kl])
            rec[lab + '_vs_close'] = {'n': int(kl.sum()), 'd': round(float(pp['d']), 4), 't': round(float(pp['t']), 2)}
        # coefficient on the residual vs model and vs close, all seasons
        rec['b_model'] = [round(float(c), 3) for c in np.linalg.lstsq(X, res - m, rcond=None)[0]]
        rec['b_close'] = [round(float(c), 3) for c in np.linalg.lstsq(X[ok], (res - L)[ok], rcond=None)[0]]
        if kfade is not None:
            rec['k'] = kfade
        out['terms'][name] = rec
        print(sport, name, json.dumps(rec), flush=True)

    wk = np.array([r['wk'] for r in rows])
    early = g < 4                                  # the pair's first four games
    voted = np.array([r['voted'] for r in rows])   # a team in the game had poll points
    chg = np.array([r['wkchg'] for r in rows])
    pre = np.array([r['pre'] for r in rows])
    # fade k picked on tune seasons (model residual, in-sample on tune only)
    kt = np.isin(S, list(tune))
    best = None
    for k in (2, 4, 6, 10, 15, 25, 1e9):
        x = pre * k / (k + g)
        b = np.linalg.lstsq(x[kt, None], (res - m)[kt], rcond=None)[0]
        e = np.abs(res[kt] - m[kt] - x[kt] * b[0]).mean()
        if best is None or e < best[0]:
            best = (e, k)
    k = best[1]
    pref = pre * k / (k + g)
    score('pre', pref[:, None], kfade=k)
    score('wk', wk[:, None])
    score('wkchg', chg[:, None])
    score('pre+wk', np.c_[pref, wk])
    score('wk+wkchg', np.c_[wk, chg])
    # pick edge: does the poll add to the model's disagreement with the close? base L + a(m - L), candidate adds b x term
    ok = ~np.isnan(L)
    out['edge'] = {}
    for lab, mask in (('all', ok), ('early', ok & early)):
        Sx, mx, Lx, rx, Dx = S[mask], m[mask], L[mask], res[mask], day_[mask]
        base = Lx + walk((mx - Lx)[:, None], rx - Lx, Sx, seasons)
        for name, x in (('pre', pref[mask]), ('wk', wk[mask])):
            X = np.c_[mx - Lx, x]
            cand = Lx + walk(X, rx - Lx, Sx, seasons)
            rec = {'b': [round(float(c), 3) for c in np.linalg.lstsq(X, rx - Lx, rcond=None)[0]]}
            for sl, yrs in (('tune', tune), ('held', held)):
                k = np.isin(Sx, list(yrs))
                pp = H.paired(H.ae(cand[k], rx[k]), H.ae(base[k], rx[k]), cluster=Dx[k])
                rec[sl] = {'n': int(k.sum()), 'd': round(float(pp['d']), 4), 't': round(float(pp['t']), 2)}
            out['edge'][f'{lab}_{name}'] = rec
            print(sport, 'edge', lab, name, json.dumps(rec), flush=True)
    out['note'] = 'early = the pair averaged < 4 games played; voted = either team had poll points; d = candidate minus base mean abs error (negative = better); t clustered by day; pass bar: tune t <= -1.5, held no worse'
    return out


if __name__ == '__main__':
    res = {s: run(s) for s in (sys.argv[1:] or ['cbb', 'cfb'])}
    path = os.path.join(os.path.dirname(HERE), 'data', 'poll_research.json')
    old = json.load(open(path)) if os.path.exists(path) else {}
    old.update(res)
    json.dump(old, open(path, 'w'), indent=1)
