#!/usr/bin/env python3
"""FotMob team xG in the soccer game model outside the big five (Oct 2026 edge sweep).

    python3 scripts/soccer_fmxg_research.py --pull   # FotMob matchDetails team stats (soccer_data.fm_xg) -> scripts/.cache/soccer/fmx/
    python3 scripts/soccer_fmxg_research.py          # -> data/soccer_fmxg_research.json

FotMob has team xG in the Eredivisie, Primeira Liga, Belgian Pro League, Scottish Premiership, Austrian Bundesliga,
Swiss Super League, Danish Superliga and Championship from 2020-21, Eliteserien and Allsvenskan from 2020, 2. Bundesliga
from 2021-22, Super Lig from 2022-23 (the rest of the second tiers, Greece, Poland, Czechia only from 2026-27, where
football-data's HxG/AxG already sits). Understat stays the big-five source.
Joined to ESPN rows by day and score (soccer_games.join_side). Tested as the model's xG side rating ('x', same learning
rate and weight as Understat) and as its own side rating ('f') at a grid of weights; scored on those leagues' matches
with a close, tune = seasons ending 2021-23, held out = 2024 on (xG starts too late for the house 2013-22 split).
Bar: held-out log loss better, and the change beats the close (a 1X2 tilt of the Shin close by the model's change in
home-minus-away log odds, fitted on tune, lowers held-out log loss vs the plain close)."""
import glob
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soccer_data as D
import soccer_games as G

OUT = os.path.join(G.ROOT, 'data', 'soccer_fmxg_research.json')
FMX = os.path.join(D.CACHE, 'fmx')
TUNE, HOLD = (2020, 2023), (2024, 2100)
LGS = list(D.FMX_LG)


def pull():
    for lg in D.FMX_LG:
        for S in range(2020, D.current_season() + 1):
            print(lg, S, len(D.fm_xg(lg, S)), flush=True)


def load_fmx():
    out = []
    for p in glob.glob(os.path.join(FMX, '*.json')):
        o = json.load(open(p))
        xg = o['st'].get('expected_goals')
        try:
            hs, as_ = [int(x) for x in o['sc'].split(' - ')]
        except (ValueError, AttributeError):
            continue
        if not xg:
            continue
        out.append({'lg': o['lg'], 'S': o['S'], 'day': o['t'][:10], 'hn': o['hn'], 'an': o['an'], 'hs': hs, 'as': as_,
                    'hx': float(xg[0]), 'ax': float(xg[1])})
    return out


def attach_fmx(rows):
    """FotMob xG on the ESPN rows as 'hf'/'af'; returns rows joined by league"""
    fm = defaultdict(list)
    for o in load_fmx():
        fm[(o['lg'], o['S'])].append(o)
    by = defaultdict(list)
    for r in rows:
        if r.get('hs') is not None:
            by[(r['lg'], D.season_of(r['day'], r['lg']))].append(r)
    names = D.load(G.NAMES)
    for r in rows:
        r.setdefault('hn', (names.get(r['h']) or ['?'])[0]); r.setdefault('an', (names.get(r['a']) or ['?'])[0])
    n = defaultdict(int)
    for k, os_ in fm.items():
        es = by.get(k, [])
        j, _ = G.join_side(es, os_, 'day', lambda o: (o['hs'], o['as']), ('hn', 'an'))
        em = {e['id']: e for e in es}
        for mid, o in j.items():
            em[mid]['hf'], em[mid]['af'] = o['hx'], o['ax']
        n[k[0]] += len(j)
        n[k[0] + ' of'] += len(os_)
    return dict(n)


def season(r):
    return D.season_of(r['day'], r['lg'])


def run(rows, P, scored):
    out = {}

    def score(r, S, lh, la, R):
        p = G.wdl(lh, la, P['rho'])
        out[r['id']] = (S, r['day'], r['lg'], G.ll_of(p, G.res(r)), p)
    saved = G.SCORED
    G.SCORED = scored
    try:
        G.run(rows, P, score)
    finally:
        G.SCORED = saved
    return out


def compare(base, new, lo, hi, only=None):
    d, k = [], []
    for i, b in base.items():
        if lo <= b[0] <= hi and (only is None or only(b[2])) and i in new:
            d.append(new[i][3] - b[3]); k.append(b[1])
    return {'n': len(d), 'dLL': round(sum(d) / max(1, len(d)) * 1e4, 2), 't': G.cl_t(d, k)}


def lo_(p):
    return math.log(max(p[0], 1e-6) / max(p[2], 1e-6))


def vs_close(rows, base, new):
    """tilt the close by b x the model's change in home-minus-away log odds; b fit on tune, held out vs the close"""
    rid = {r['id']: r for r in rows}
    xs = []
    for i, b in base.items():
        r = rid[i]
        c = G.close_probs(r) or G.novig(r.get('nc'))
        if c and r['lg'] in LGS:
            xs.append((b[0], b[1], c, lo_(new[i][4]) - lo_(b[4]), G.res(r)))

    def ll(sub, k):
        return [G.ll_of(G_tilt(c, k, z), y) - G.ll_of(c, y) for S, d, c, z, y in sub]
    tu = [x for x in xs if TUNE[0] <= x[0] <= TUNE[1]]; ho = [x for x in xs if x[0] >= HOLD[0]]
    best = min([i / 20 for i in range(-20, 41)], key=lambda k: sum(ll(tu, k)))
    a, b = ll(tu, best), ll(ho, best)
    gap = lambda sub, m: sum(G.ll_of(m(x), x[4]) for x in sub) / max(1, len(sub))
    return {'k': best, 'tune': {'n': len(a), 'dLL': round(sum(a) / max(1, len(a)) * 1e4, 2), 't': G.cl_t(a, [x[1] for x in tu])},
            'hold': {'n': len(b), 'dLL': round(sum(b) / max(1, len(b)) * 1e4, 2), 't': G.cl_t(b, [x[1] for x in ho])}}


def G_tilt(p, k, z):
    a, c = p[0] * math.exp(k * z / 2), p[2] * math.exp(-k * z / 2)
    s = a + p[1] + c
    return [a / s, p[1] / s, c / s]


def gap_close(rows, out, lo, hi):
    """model minus close log loss on those leagues"""
    rid = {r['id']: r for r in rows}
    d, k = [], []
    for i, b in out.items():
        r = rid[i]
        c = G.close_probs(r) or G.novig(r.get('nc'))
        if c and r['lg'] in LGS and lo <= b[0] <= hi:
            d.append(b[3] - G.ll_of(c, G.res(r))); k.append(b[1])
    return {'n': len(d), 'gap': round(sum(d) / max(1, len(d)) * 1e4, 2), 't': G.cl_t(d, k)}


def main():
    if '--pull' in sys.argv:
        pull()
        return
    rows = G.add_inj(G.add_mv(G.add_market(D.load(G.HIST))))
    for r in rows:                      # the history carries FotMob xG as hx/ax since the Oct 2026 ship: start without it
        if r['lg'] not in D.US_LG:
            r.pop('hx', None); r.pop('ax', None)
    res = {'joined': attach_fmx(rows)}
    print(res['joined'], flush=True)
    # xG level vs goals (sanity): FotMob vs goals per league
    lv = defaultdict(lambda: [0, 0.0, 0.0])
    for r in rows:
        if r.get('hf') is not None:
            v = lv[r['lg']]; v[0] += 1; v[1] += r['hf'] + r['af']; v[2] += r['hs'] + r['as']
    res['level'] = {lg: {'n': v[0], 'xg': round(v[1] / v[0], 3), 'goals': round(v[2] / v[0], 3)} for lg, v in lv.items()}
    P = G.params()
    scored = set(LGS)
    base = run(rows, P, scored)
    res['baseGap'] = {'tune': gap_close(rows, base, *TUNE), 'hold': gap_close(rows, base, *HOLD)}
    print('base gap', res['baseGap'], flush=True)
    tests = []
    G.SUBS['f'] = ('hf', 'af')
    for nm, extra in (('as Understat (x: kx, wx)', None),
                      ('own rating f w .05', {'kf': P['kx'], 'carf': 1.0, 'wf': 0.05}),
                      ('own rating f w .10', {'kf': P['kx'], 'carf': 1.0, 'wf': 0.10}),
                      ('own rating f w .20', {'kf': P['kx'], 'carf': 1.0, 'wf': 0.20}),
                      ('own rating f w .35', {'kf': P['kx'], 'carf': 1.0, 'wf': 0.35}),
                      ('own rating f w .20 k x.6', {'kf': P['kx'] * 0.6, 'carf': 1.0, 'wf': 0.20}),
                      ('own rating f w .20 k x1.5', {'kf': P['kx'] * 1.5, 'carf': 1.0, 'wf': 0.20})):
        if extra is None:
            for r in rows:
                if r.get('hf') is not None and r.get('hx') is None:
                    r['hx'], r['ax'], r['_fx'] = r['hf'], r['af'], 1
            Q = dict(P, kf=0.0, carf=1.0, wf=0.0)
        else:
            for r in rows:
                if r.pop('_fx', None):
                    r.pop('hx'); r.pop('ax')
            Q = dict(P, **extra)
        s = run(rows, Q, scored)
        t = {'name': nm, 'tune': compare(base, s, *TUNE), 'hold': compare(base, s, *HOLD),
             'byLeagueHold': {lg: compare(base, s, *HOLD, lambda l, lg=lg: l == lg)['dLL'] for lg in LGS},
             'bySeason': {S: compare(base, s, S, S)['dLL'] for S in range(2020, 2028)},
             'gapHold': gap_close(rows, s, *HOLD), 'vsClose': vs_close(rows, base, s)}
        tests.append(t)
        print(json.dumps(t), flush=True)
    res['tests'] = tests
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
