# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Altitude gap tests (PREREG.md M8) on scripts/data/venue_elev.json. -> out/altitude.json

    python3 scripts/research/sweep_nov19/methods/altitude.py intl <results.csv>
    python3 scripts/research/sweep_nov19/methods/altitude.py cfb cbb

intl walks soccer_intl.run once with the shipped parameters (never --fit) and shifts the stored goal rates.
"""
import csv
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

OUT = os.environ.get('METHODS_OUT', os.path.join(HERE, 'out'))
EL = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'venue_elev.json')))
END = '2026-07-31'


def gap(V, Eh, Ea):
    return (max(0.0, V - Ea - 1000) - max(0.0, V - Eh - 1000)) / 1000


def intl(results_f):
    import soccer_intl as I
    city = {(r['date'], r['home_team'], r['away_team']): f"{r['city']}|{r['country']}" for r in csv.DictReader(open(results_f, encoding='utf-8'))}
    rows = [r for r in I.mj_rows() if r['day'] <= END]
    I.attach_sq(rows)
    I.attach_cu(rows)
    P = I.params()
    home = {}
    for r in rows:
        if r['day'] >= '1990-01-01' and not r['neu']:
            e = EL['intl'].get(city.get((r['day'], r['h'], r['a'])))
            if e is not None:
                home.setdefault(r['h'], []).append(e)
    E = {k: float(np.median(v)) for k, v in home.items()}
    _, sc = I.run(rows, P, '2000-01-01', END, keep=True)
    day, y, lh, la, g, year, conm = [], [], [], [], [], [], []
    hi_n = hi_res = 0
    CONMEBOL = {'Argentina', 'Bolivia', 'Brazil', 'Chile', 'Colombia', 'Ecuador', 'Paraguay', 'Peru', 'Uruguay', 'Venezuela'}
    for x in sc:
        r = x[0]
        v = EL['intl'].get(city.get((r['day'], r['h'], r['a'])))
        Eh, Ea = E.get(r['h']), E.get(r['a'])
        if not r['neu'] and (Eh or 0) >= 1500:
            hi_n += 1
            hi_res += v is not None
        if v is None and not r['neu']:
            v = Eh
        gg = gap(v, Eh if Eh is not None else v, Ea) if (v is not None and Ea is not None) else 0.0
        day.append(r['day']); y.append(I.outcome(r)); lh.append(x[5]); la.append(x[6]); g.append(gg); year.append(int(r['day'][:4])); conm.append(r['h'] in CONMEBOL)
    day, y, lh, la, g, year, conm = np.array(day), np.array(y), np.array(lh), np.array(la), np.array(g), np.array(year), np.array(conm)
    rho = P['rho']

    def ll(c):
        out = np.empty(len(y))
        for i in range(len(y)):
            if g[i] == 0 and c != 0:
                out[i] = base[i]
                continue
            s = c * g[i] / 2
            out[i] = -math.log(max(I.wdl(lh[i] * math.exp(s), la[i] * math.exp(-s), rho)[y[i]], 1e-9))
        return out
    base = None
    base = ll(0.0)
    tune, held = day <= '2015-12-31', day >= '2016-01-01'
    grid = [round(.05 * i, 2) for i in range(11)]
    tl = {c: float(ll(c)[tune].mean()) for c in grid}
    c = min(grid, key=lambda k: tl[k])
    lc = ll(c)
    pt, ph = H.paired(lc[tune], base[tune], day[tune]), H.paired(lc[held], base[held], day[held])
    ys = sorted(set(year[held].tolist()))
    d = lc - base
    yr = {int(s): float(d[held & (year == s)].sum()) for s in ys}
    nz = g != 0
    out = {'n': len(y), 'tuneN': int(tune.sum()), 'heldN': int(held.sum()), 'gapMatches': {'tune': int((tune & nz).sum()), 'held': int((held & nz).sum())},
           'highHome': {'matches': hi_n, 'cityResolved': hi_res, 'share': round(hi_res / max(hi_n, 1), 3)},
           'tuneLL': {str(k): round(v, 6) for k, v in tl.items()}, 'c': c,
           'tune': {'d': pt['d'], 't': round(pt['t'], 2)}, 'held': {'d': ph['d'], 't': round(ph['t'], 2), 'p': ph['p'], 'G': ph['G']},
           'heldYearsBetter': int(sum(v < 0 for v in yr.values())), 'heldYears': len(yr),
           'heldConmebolHome': round(float(d[held & nz & conm].mean()), 5) if (held & nz & conm).any() else None,
           'heldOther': round(float(d[held & nz & ~conm].mean()), 5) if (held & nz & ~conm).any() else None,
           'nationsHigh': {k: round(v) for k, v in sorted(E.items(), key=lambda kv: -kv[1])[:12]}}
    return out


def stack(sp):
    import placebo as PB
    rows = PB.load(sp)
    if sp == 'cfb':
        W = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_weather_om.json')))
        elev = {t: EL['cfb'].get(v) for t, v in W['home'].items()}
        eh = [elev.get(r['h']) for r in rows]; ea = [elev.get(r['a']) for r in rows]
    else:
        hist = {g['id']: g for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_games_hist.json.gz')))}
        wf = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'cbb.json.gz')))
        ids = {(g['date'][:10], str(g['home']), str(g['away'])): g['id'] for g in wf}
        eh, ea = [], []
        for r in rows:
            g = hist.get(ids.get((r['day'], r['h'], r['a'])))
            eh.append(EL['cbb'].get(g['home']) if g else None); ea.append(EL['cbb'].get(g['away']) if g else None)
    keep = [i for i, r in enumerate(rows) if not r['neutral'] and eh[i] is not None and ea[i] is not None]
    cover = len(keep) / max(1, sum(1 for r in rows if not r['neutral']))
    rows = [rows[i] for i in keep]
    g = np.array([gap(eh[i], eh[i], ea[i]) for i in keep])
    S = np.array([r['S'] for r in rows]); y = np.array([r['y'] for r in rows]); m = np.array([r['m'] for r in rows])
    seasons = sorted(set(S.tolist()))
    one = np.ones(len(y))
    base = H.ae(PB.walk(np.column_stack([one, m]), y, S, seasons), y)
    cand = H.ae(PB.walk(np.column_stack([one, m, g]), y, S, seasons), y)
    t0, t1, h0, h1 = PB.SPLIT[sp]
    tune, held = (S >= t0) & (S <= t1), (S >= h0) & (S <= h1)
    day = np.array([r['day'] for r in rows]); ht = np.array([f"{r['h']}|{r['S']}" for r in rows])
    pt, ph = H.paired(cand[tune], base[tune], [day[tune], ht[tune]]), H.paired(cand[held], base[held], [day[held], ht[held]])
    hs = [s for s in seasons if h0 <= s <= h1]
    b = np.linalg.lstsq(np.column_stack([one, m, g]), y, rcond=None)[0]
    return {'n': len(y), 'coverage': round(cover, 3), 'gapGames': {'tune': int((tune & (g != 0)).sum()), 'held': int((held & (g != 0)).sum())},
            'coefAllPtsPerKm': round(float(b[2]), 3), 'tune': {'d': pt['d'], 't': round(pt['t'], 2)}, 'held': {'d': ph['d'], 't': round(ph['t'], 2), 'p': ph['p']},
            'heldSeasonsBetter': int(sum((cand - base)[S == s].mean() < 0 for s in hs)), 'heldSeasons': len(hs)}


def main(a):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, 'altitude.json')
    res = json.load(open(p)) if os.path.exists(p) else {}
    i = 0
    while i < len(a):
        if a[i] == 'intl':
            res['intl'] = intl(a[i + 1]); i += 2
            print('intl', json.dumps(res['intl']), flush=True)
        else:
            res[a[i]] = stack(a[i]); print(a[i], json.dumps(res[a[i]]), flush=True); i += 1
    json.dump(res, open(p, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1:])
