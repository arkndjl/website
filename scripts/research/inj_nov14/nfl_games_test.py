#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""G1 (injury term priced with nfl_q) and G5 (game control) of PREREG.md, on the live model's walk-forward.

    python3 scripts/research/nfl_nov13/ledgers.py 2015 ... 2025      # once: the weekly ledgers
    python3 scripts/research/inj_nov14/nfl_games_test.py             # writes data/inj_nov14_nfl_games.json
"""
import csv, gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..')); sys.path.insert(0, os.path.join(HERE, '..', 'nfl_nov13'))
import harness as H
import nfl_games as N
import nfl_war as W
import ledgers as L

OUT = os.path.join(N.ROOT, 'data', 'inj_nov14_nfl_games.json')
LAST = 2025
_led = {}


def ledger(y, thru=None, maps=None):
    """nfl_war.war_ledger from the cached weekly ledgers (thru w = before week w's games; none = the season)"""
    if y not in _led and os.path.exists(L.path(y)):
        _led[y] = L.load(y)
    if thru is None:
        nxt = y + 1
        if nxt not in _led and os.path.exists(L.path(nxt)):
            _led[nxt] = L.load(nxt)
        return _led[nxt][0] if nxt in _led else _orig(y, maps=maps)
    return _led[y][1][min(thru, 19)]


_orig = W.war_ledger
W.war_ledger = ledger
W.gsis_map = lambda y: None


def control():
    """game_id -> home control: the time-weighted mean of Phi(lead / (13.5 sqrt(share of the game left)))"""
    cp = os.path.join(N.CACHE, 'inj_nov14_control.json')
    if os.path.exists(cp):
        return json.load(open(cp))
    phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    out = {}
    for y in range(2014, LAST + 1):
        cur, pts = None, []

        def close():
            if cur and len(pts) > 20:
                pts.sort(reverse=True)
                tot = acc = 0.0
                for (t0, l0), (t1, _) in zip(pts, pts[1:] + [(0.0, 0)]):
                    dur = max(0.0, t0 - t1)
                    sh = max(t0, 1.0) / 3600.0
                    acc += dur * phi(l0 / (13.5 * math.sqrt(sh))); tot += dur
                if tot > 0:
                    out[cur] = acc / tot
        with gzip.open(os.path.join(N.CACHE, f'play_by_play_{y}.csv.gz'), 'rt', newline='') as f:
            for r in csv.DictReader(f):
                if r['game_id'] != cur:
                    close(); cur, pts = r['game_id'], []
                try:
                    pts.append((float(r['game_seconds_remaining']), float(r['total_home_score']) - float(r['total_away_score'])))
                except ValueError:
                    pass
            close()
        print('control', y, len(out), flush=True)
    json.dump(out, open(cp, 'w'))
    return out


def probit(p):
    p = min(0.98, max(0.02, p))
    lo, hi = -3.0, 3.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def gc_feature(D, ctl):
    """rating gap before each game: ridge Massey of probit(control) with home, penalty 2 games toward half of last
    season's rating, re-solved before every week"""
    teams = sorted({N.team(g[f'{s}_team']) for g, _, _ in D for s in ('home', 'away')})
    ix = {t: i for i, t in enumerate(teams)}
    out = {}
    prior = np.zeros(len(teams))
    bys = defaultdict(list)
    for g, _, _ in D:
        bys[int(g['season'])].append(g)
    for s in sorted(bys):
        gs = bys[s]
        weeks = sorted({int(g['week']) for g in gs})
        r = prior.copy()
        for w in weeks:
            past = [g for g in gs if int(g['week']) < w and g['game_id'] in ctl]
            if past:
                n = len(teams)
                A = np.zeros((n + 1, n + 1)); b = np.zeros(n + 1)
                for g in past:
                    h, a = ix[N.team(g['home_team'])], ix[N.team(g['away_team'])]
                    v = np.zeros(n + 1); v[h] = 1; v[a] = -1; v[n] = 0 if g.get('location') == 'Neutral' else 1
                    A += np.outer(v, v); b += v * probit(ctl[g['game_id']])
                A[:n, :n] += 2.0 * np.eye(n); b[:n] += 2.0 * prior
                A[n, n] += 1e-6
                r = np.linalg.solve(A, b)[:n]
            for g in gs:
                if int(g['week']) == w:
                    out[g['game_id']] = float(r[ix[N.team(g['home_team'])]] - r[ix[N.team(g['away_team'])]])
        prior = 0.5 * r
    return out


def main():
    F = json.load(open(N.FIT))
    games, box, qbs = N.load(LAST)
    N.index_qbs(qbs, games); N.load_qb_teams(LAST)
    years = range(N.INJ_FIRST, LAST + 1)
    N.CACHE_SAVE = N.CACHE
    inj = {}
    for on in (False, True):
        N.Q_MODEL = on
        cp = os.path.join(N.CACHE, 'inj_hist_v5.json')
        if os.path.exists(cp):
            os.rename(cp, cp + '.keep')
        inj[on] = N.injury_history(games, years)
        os.rename(cp, os.path.join(N.CACHE, f'inj_nov14_hist_{int(on)}.json'))
        if os.path.exists(cp + '.keep'):
            os.rename(cp + '.keep', cp)
    _, data = N.walk(games, box, qbs, F['params'])
    D = [(g, x, tx) for g, x, tx in data if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]
    ctl = control()
    gc = gc_feature(D, ctl)
    S = np.array([int(g['season']) for g, _, _ in D]); WK = np.array([f"{g['season']}-{g['week']}" for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D]); line = np.array([N.num(g['spread_line'], np.nan) for g, _, _ in D])
    ok = ~np.isnan(line)

    def design(which, extra=()):
        X = []
        for g, x, _ in D:
            x = dict(x); r = inj[which].get(g['game_id'])
            if r:
                x['inj'] = (r[2] + r[3]) - (r[0] + r[1]); x['ir'] = r[5] - r[4]
            x['gc'] = gc.get(g['game_id'], 0.0)
            X.append([x[f] for f in list(N.FEATS) + list(extra)])
        return np.array(X)

    def wf(X):
        pred = np.full(len(y), np.nan)
        for s in range(2015, LAST + 1):
            tr, te = S < s, S == s
            pred[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        return pred, np.linalg.lstsq(X, y, rcond=None)[0]

    def cmp(p1, p0, k):
        r = H.paired(np.abs(p1[k] - y[k]), np.abs(p0[k] - y[k]), cluster=WK[k])
        return {'n': int(k.sum()), 'maeBase': round(float(np.abs(p0[k] - y[k]).mean()), 4), 'maeCand': round(float(np.abs(p1[k] - y[k]).mean()), 4),
                'd': round(r['d'], 4), 't': round(r['t'], 2), 'p': r['p']}
    p0, b0 = wf(design(False)); p1, b1 = wf(design(True)); p5, b5 = wf(design(False, ['gc']))
    A, B = (S >= 2015) & (S <= 2020) & ok, (S >= 2021) & ok
    res = {'prereg': 'scripts/research/inj_nov14/PREREG.md',
           'base': {'tune': round(float(np.abs(p0[A] - y[A]).mean()), 4), 'held': round(float(np.abs(p0[B] - y[B]).mean()), 4),
                    'lineTune': round(float(np.abs(line[A] - y[A]).mean()), 4), 'lineHeld': round(float(np.abs(line[B] - y[B]).mean()), 4)},
           'G1': {'tune': cmp(p1, p0, A), 'tune1820': cmp(p1, p0, A & (S >= 2018)), 'held': cmp(p1, p0, B),
                  'coefInj': [round(float(b0[N.FEATS.index('inj')]), 3), round(float(b1[N.FEATS.index('inj')]), 3)],
                  'bySeason': {int(s): round(float((np.abs(p1 - y) - np.abs(p0 - y))[(S == s) & ok].mean()), 4) for s in range(2018, LAST + 1)}},
           'G5': {'tune': cmp(p5, p0, A), 'held': cmp(p5, p0, B), 'coef': round(float(b5[-1]), 3),
                  'bySeason': {int(s): round(float((np.abs(p5 - y) - np.abs(p0 - y))[(S == s) & ok].mean()), 4) for s in range(2015, LAST + 1)}}}
    # G1: does the change in the injury input predict result minus the close (held)?
    mv = p1 - p0; k = B & (np.abs(mv) > 1e-9)
    bb = float((mv[k] @ (y[k] - line[k])) / (mv[k] @ mv[k])); rr = (y[k] - line[k]) - bb * mv[k]
    res['G1']['vsCloseHeld'] = {'b': round(bb, 2), 't': round(bb / math.sqrt(float(rr @ rr) / (k.sum() - 1) / float(mv[k] @ mv[k])), 2), 'sdMove': round(float(mv[k].std()), 3)}
    print(json.dumps(res, indent=1))
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
