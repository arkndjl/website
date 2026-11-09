# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Measured height and weight for college football players.

Truth: NFL combine and pro day measurements (MockDraftable search pages, scripts/.cache/measure/md: height to 1/8 in,
source 1 combine / 2 pro day; nflverse combine.csv, whole inches, fills players MockDraftable lacks). Sources a college
player has before then:
  r   the ESPN roster listing (cfbfastR rosters 2012-26, matched by ESPN athlete id). The cfbfastR files carry one
      listing an athlete, the same in every season's file (0 of ~90,000 season-to-season pairs differ), so there is no
      per-season listing history to weight by recency; r is the latest listing
  hs  the 247Sports composite recruiting listing (half inches; scripts/.cache/fvrefit/247), with j = years since the class
Each source's bias and error SD against the measurement are reported by position group, by era and (247) by years
before the combine. The estimate is one linear predictor per coarse group and listing pattern (r, r + hs, hs), fit on
final seasons against the combine number: the listing's coefficient below 1 shrinks it toward the group's combine mean
(the empirical-Bayes prior), 247 gets the weight its independent error earns, group slopes are shrunk to pooled at 150
rows, and classes are weighted by recency (half-life 4 draft classes). Scored one draft class held out, and forward
(earlier classes only), against the latest listing alone and the latest listing less its group bias.
Result (Nov 3 2026; 3,838 measured players, classes 2013-25, 3,172 with a 247 listing): held out, height RMSE .83 in
(latest listing) -> .67 (less its bias) -> .62 (model), 13 of 13 classes; weight 7.7 -> 7.7 -> 7.1 lb, 8 of 8.
Listings run tall: ESPN +0.48 in (OL +.24, RB +.69; +.56 in 2013-17, +.37 in 2022-25), 247 +0.42 in; ESPN weight
+0.8 lb (OL +2.8, DL +1.5), 247 weight -18.5 lb (-13 three years before the combine, -23 six years).
Not fit (no history before a combine): On3's listing (for the board's On3 rows a recruiting-era listing: 90% differ
from ESPN, 15.6 lb lighter on average), Tankathon's (web.archive.org, the only archive of its past boards, is blocked
from here), PFN (its impact rankings carry no size).
  python3 scripts/cfb_measure.py -> data/cfb_measure.json (scripts/cfb_measure.mjs applies it on the board),
                                    scripts/.cache/measure/measure_report.json + measure_rows.json
"""
import collections
import csv
import glob
import html
import json
import math
import os
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names  # noqa: E402

C = os.path.join(ROOT, 'scripts', '.cache')
ROS = os.path.join(C, 'fvrefit', 'ros')
R247 = os.path.join(C, 'fvrefit', '247')
MD = os.path.join(C, 'measure', 'md')
OUT = os.path.join(ROOT, 'data', 'cfb_measure.json')
HIST = os.path.join(ROOT, 'data', 'cfb_size_hist.json')
RES = os.environ.get('MEASURE_RES', os.path.join(C, 'measure'))
FIRST_ROS, LAST_ROS = 2012, 2026
VARS = ['r0', 'r1', 'r2', 'r3', 'hs']
GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DT', 'LB', 'CB', 'S']
COARSE = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'HB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'OT': 'OL', 'G': 'OL', 'OG': 'OL',
          'C': 'OL', 'OC': 'OL', 'T': 'OL', 'IOL': 'OL', 'DL': 'DL', 'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'EDGE': 'DL', 'IDL': 'DL',
          'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'DB': 'DB', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'SAF': 'DB'}
# the fit's groups are the measured player's NFL position (MockDraftable / nflverse), so an edge's prior is the edge
# mean, not the whole line's; the board applies them by its own group
BOARD_COARSE = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'EDGE': 'EDGE', 'DL': 'DT', 'LB': 'LB', 'CB': 'CB', 'S': 'S'}
# 247 positions
P247 = {'PRO': 'QB', 'DUAL': 'QB', 'QB': 'QB', 'RB': 'RB', 'APB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OT': 'OL', 'OG': 'OL',
        'OC': 'OL', 'IOL': 'OL', 'SDE': 'DL', 'WDE': 'DL', 'DT': 'DL', 'EDGE': 'DL', 'DL': 'DL', 'ILB': 'LB', 'OLB': 'LB', 'LB': 'LB',
        'CB': 'DB', 'S': 'DB', 'SAF': 'DB', 'ATH': None, 'K': None, 'P': None, 'LS': None}


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) and v > 0 else None
    except (TypeError, ValueError):
        return None


def inches(h):
    m = re.match(r'^\s*(\d)\D+(\d+(?:\.\d+)?)', h or '')
    return int(m.group(1)) * 12 + float(m.group(2)) if m else None


# ---- sources --------------------------------------------------------------------------------------------------
def rosters():
    """{season: [row]}, {aid: {season: row}}; row = aid, name, team, pos, g, ht, wt, season"""
    by_s, by_a = {}, collections.defaultdict(dict)
    for y in range(FIRST_ROS, LAST_ROS + 1):
        f = os.path.join(ROS, f'r{y}.csv')
        if not os.path.exists(f):
            continue
        L = []
        for r in csv.DictReader(open(f, encoding='utf-8')):
            ht, wt = num(r['height']), num(r['weight'])
            if ht and not 60 <= ht <= 84: ht = None
            if wt and not 140 <= wt <= 420: wt = None
            row = {'aid': r['athlete_id'], 'name': f"{r['first_name']} {r['last_name']}".strip(), 'team': r['team'], 'pos': r['position'],
                   'g': COARSE.get(r['position']), 'ht': ht, 'wt': wt, 'season': y}
            L.append(row)
            if r['athlete_id'] and r['athlete_id'][0] != '-':
                by_a[r['athlete_id']][y] = row
        by_s[y] = L
    return by_s, by_a


def recruits():
    """247 composite listings: [{name, cls, ht, wt, g, school, rating}]"""
    out = []
    for f in sorted(glob.glob(os.path.join(R247, 'c_*_*.html'))):
        y = int(os.path.basename(f).split('_')[1])
        s = open(f, encoding='utf-8', errors='replace').read()
        for x in s.split('rankings-page__list-item"')[1:]:
            nmm = re.search(r'name-link"[^>]*>([^<]*)', x)
            met = re.search(r'class="metrics">\s*([^<]*?)\s*<', x)
            if not nmm or not met:
                continue
            ps = re.search(r'class="position">\s*([^<]*?)\s*<', x)
            sch = re.search(r'class="img-link"[^>]*>\s*<img alt="([^"]*)"', x)
            sc = re.search(r'class="score">([\d.]+)', x)
            a = met.group(1).split('/')
            ht = inches(a[0]) if a else None
            wt = num(a[1]) if len(a) > 1 else None
            if ht and not 60 <= ht <= 84: ht = None
            if wt and not 130 <= wt <= 420: wt = None
            out.append({'name': html.unescape(nmm.group(1)).strip(), 'cls': y, 'ht': ht, 'wt': wt,
                        'pos': (ps.group(1) if ps else ''), 'g': P247.get(ps.group(1) if ps else ''), 'school': html.unescape(sch.group(1)) if sch else '',
                        'rating': float(sc.group(1)) if sc else None})
    return out


def truth():
    """combine / pro day: [{name, D, school, pos, ht, wt, src}] (MockDraftable first, nflverse fills)"""
    out, seen = [], set()
    for f in sorted(glob.glob(os.path.join(MD, 's*_*.json'))):
        d = json.load(open(f))
        for p in d['players'].values():
            m = {x['measurableKey']: x for x in p.get('measurements', [])}
            ht, wt = m.get(1), m.get(2)
            if not ht and not wt:
                continue
            src = (ht or wt)['source']
            k = (names.key(p['name']), p['draft'])
            if k in seen:
                continue
            seen.add(k)
            out.append({'name': p['name'], 'D': p['draft'], 'school': p.get('school') or '', 'pos': p['positions']['primary'],
                        'ht': ht['measurement'] if ht else None, 'wt': wt['measurement'] if wt else None,
                        'src': 'combine' if src == 1 else 'proday', 'frac': True})
    f = os.path.join(C, 'sources', 'combine.csv')
    if os.path.exists(f):
        for r in csv.DictReader(open(f, encoding='utf-8')):
            k = (names.key(r['player_name']), int(r['season']))
            if k in seen:
                continue
            ht, wt = inches(r['ht']), num(r['wt'])
            if not ht and not wt:
                continue
            seen.add(k)
            out.append({'name': r['player_name'], 'D': int(r['season']), 'school': r['school'], 'pos': r['pos'], 'ht': ht, 'wt': wt,
                        'src': 'combine' if int(r['season']) != 2021 else 'proday', 'frac': False})
    return out


MDPOS = {'QB': 'QB', 'RB': 'RB', 'HB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OT': 'OL', 'OG': 'OL', 'OC': 'OL', 'C': 'OL', 'OL': 'OL', 'G': 'OL', 'T': 'OL',
         'EDGE': 'EDGE', 'DE': 'EDGE', 'OLB': 'EDGE', '34B': 'EDGE', 'DT': 'DT', 'NT': 'DT', 'IDL': 'DT', 'ILB': 'LB', 'LB': 'LB', 'MLB': 'LB',
         'CB': 'CB', 'S': 'S', 'SAF': 'S', 'FS': 'S', 'SS': 'S'}


def truth_group(t):
    """the measured player's NFL group; DL and DB split by measured weight"""
    if t['pos'] == 'DL':
        return 'DT' if (t['wt'] or 0) >= 280 else 'EDGE'
    if t['pos'] == 'DB':
        return 'CB' if (t['wt'] or 0) < 200 else 'S'
    return MDPOS.get(t['pos'])


# ---- linking --------------------------------------------------------------------------------------------------
def link(T, by_s, by_a, R):
    """each measured player -> his ESPN athlete id (roster in the season before the draft, else two before) and his
    247 listing"""
    M = {y: names.Matcher([r for r in L if r['aid'] and r['aid'][0] != '-'], pos='pos') for y, L in by_s.items()}
    RM = names.Matcher(R, team='school', pos='pos', cls='cls')
    out = []
    for t in T:
        hit = None
        for y in (t['D'] - 1, t['D'] - 2):
            if y not in M:
                continue
            r, _ = M[y].find(t['name'], team=t['school'], pos=t['pos'])
            if r:
                hit = r
                break
        if not hit:
            continue
        hist = by_a[hit['aid']]
        first = min(hist)
        rc, _ = RM.find(t['name'], team=hist[first]['team'], pos=t['pos'], cls=lambda c, D=t['D']: D - 7 <= c <= D - 1)
        if rc and not (t['D'] - 7 <= rc['cls'] <= t['D'] - 1):
            rc = None
        g = truth_group(t)
        out.append({**t, 'aid': hit['aid'], 'g': g, 'hist': hist, 'rec': rc, 'last': max(s for s in hist if s < t['D'])})
    return out


def features(hist, rec, s, m):
    """what the board knows at the end of season s: r the ESPN listing (the cfbfastR files carry one listing an athlete,
    the same in every season's file, so there is no season-by-season history), hs the 247 listing, j years since the
    high school class (s + 1 - class)"""
    ys = [y for y in sorted(hist) if y <= s and hist[y][m]]
    r = hist[ys[-1]][m] if ys else None
    hs = rec[m] if rec and rec.get(m) and rec['cls'] <= s + 1 else None
    return {'r': r, 'hs': hs, 'j': (s + 1 - rec['cls']) if hs is not None else None}


# ---- the estimator --------------------------------------------------------------------------------------------
# one linear predictor per group and listing pattern, fit on final seasons against the combine number:
#   r   T = a + b (r - mr)                      ESPN listing only
#   rh  T = a + b (r - mr) + c (hs - mh) + d (j - mj)
#   h   T = a + c (hs - mh) + d (j - mj)        247 only
# b, c < 1 shrink toward the group's combine mean (a), so the implied weights are b on the listing, c on 247 and the
# rest on the prior. Group coefficients are shrunk toward the pooled ones at K_POOL rows; classes can be weighted by
# recency (half-life HALF draft classes)
K_POOL = 150
PATTERNS = {'r': ['r'], 'rh': ['r', 'hs', 'j'], 'h': ['hs', 'j']}


def pattern(f):
    return 'rh' if f['r'] is not None and f['hs'] is not None else 'r' if f['r'] is not None else 'h' if f['hs'] is not None else None


def wls(X, y, w):
    W = np.sqrt(w)[:, None]
    A = X * W
    return np.linalg.lstsq(A.T @ A + np.eye(X.shape[1]) * 1e-6, A.T @ (y * W[:, 0]), rcond=None)[0]


def fit_model(rows, m, half=None, last=None):
    """{pattern: {group: {mean: {...}, coef: [...], sd}}}"""
    last = last or max(r['D'] for r in rows)
    out = {}
    for pat, ks in PATTERNS.items():
        R = [r for r in rows if r['t'][m] and all(r['f'][m][k] is not None for k in ks)]
        if len(R) < 30:
            continue
        wt = np.array([0.5 ** ((last - r['D']) / half) if half else 1.0 for r in R])
        mus = {k: float(np.average([r['f'][m][k] for r in R], weights=wt)) for k in ks}
        # pooled slopes on group-demeaned data (group intercepts free)
        G = {}
        for i, r in enumerate(R):
            G.setdefault(r['g'], []).append(i)
        Xc, yc = np.zeros((len(R), len(ks))), np.zeros(len(R))
        gm = {}
        for g, ix in G.items():
            w_ = wt[ix]
            gm[g] = ({k: float(np.average([R[i]['f'][m][k] for i in ix], weights=w_)) for k in ks}, float(np.average([R[i]['t'][m] for i in ix], weights=w_)))
            for i in ix:
                Xc[i] = [R[i]['f'][m][k] - gm[g][0][k] for k in ks]
                yc[i] = R[i]['t'][m] - gm[g][1]
        bp = wls(Xc, yc, wt)
        out[pat] = {}
        for g in GROUPS:
            if g not in G:
                continue
            ix = G[g]
            n = len(ix)
            bg = wls(Xc[ix], yc[ix], wt[ix]) if n >= len(ks) + 5 else bp
            b = (n * bg + K_POOL * bp) / (n + K_POOL)
            res = yc[ix] - Xc[ix] @ b
            out[pat][g] = {'mx': {k: round(gm[g][0][k], 3) for k in ks}, 'mt': round(gm[g][1], 3), 'b': [round(float(x), 4) for x in b],
                           'sd': round(float(np.sqrt(np.average(res ** 2, weights=wt[ix]))), 3), 'n': n}
    return out


def predict(P, g, f):
    pat = pattern(f)
    if pat is None or pat not in P or g not in P[pat]:
        return None, None
    q = P[pat][g]
    return q['mt'] + sum(b * (f[k] - q['mx'][k]) for b, k in zip(q['b'], PATTERNS[pat])), pat


def bias_tables(rows, L):
    """listing - combine: ESPN listing by group and era; 247 listing by group and years from the class to the draft"""
    out = {}
    for m in ('ht', 'wt'):
        o = {'espn': {}, 'espnEra': {}, '247': {}, '247years': {}}
        for g in GROUPS + ['all']:
            d = [r['f'][m]['r'] - r['t'][m] for r in rows if (g == 'all' or r['g'] == g) and r['f'][m]['r'] is not None and r['t'][m]]
            if len(d) >= 15:
                o['espn'][g] = [round(float(np.mean(d)), 2), round(float(np.std(d)), 2), len(d)]
            d = [r['f'][m]['hs'] - r['t'][m] for r in rows if (g == 'all' or r['g'] == g) and r['f'][m]['hs'] is not None and r['t'][m]]
            if len(d) >= 15:
                o['247'][g] = [round(float(np.mean(d)), 2), round(float(np.std(d)), 2), len(d)]
        for lo, hi in ((2013, 2017), (2018, 2021), (2022, 2025), (2026, 2026)):
            d = [r['f'][m]['r'] - r['t'][m] for r in rows if lo <= r['D'] <= hi and r['f'][m]['r'] is not None and r['t'][m]]
            if len(d) >= 15:
                o['espnEra'][f'{lo}-{hi}'] = [round(float(np.mean(d)), 2), round(float(np.std(d)), 2), len(d)]
        for j in (3, 4, 5, 6):
            d = [r['f'][m]['hs'] - r['t'][m] for r in rows if r['f'][m]['hs'] is not None and r['t'][m] and min(r['f'][m]['j'], 6) == j]
            if len(d) >= 15:
                o['247years'][j] = [round(float(np.mean(d)), 2), round(float(np.std(d)), 2), len(d)]
        out[m] = o
    return out


def evaluate(rows, m, half, forward=False):
    n = collections.Counter(r['D'] for r in rows if r['t'][m] and r['f'][m]['r'] is not None)
    classes = sorted(c for c in n if n[c] >= 30)
    err, byc = collections.defaultdict(list), collections.defaultdict(lambda: collections.defaultdict(list))
    for c in classes:
        tr = [r for r in rows if (r['D'] < c if forward else r['D'] != c)]
        if len(set(r['D'] for r in tr if r['t'][m] and r['f'][m]['r'] is not None)) < 3:
            continue
        P0, P1 = fit_model(tr, m), fit_model(tr, m, half, last=c - 1 if forward else None)
        bias = {g: np.mean([r['f'][m]['r'] - r['t'][m] for r in tr if r['g'] == g and r['t'][m] and r['f'][m]['r'] is not None]) for g in GROUPS}
        for r in rows:
            f = r['f'][m]
            if r['D'] != c or not r['t'][m] or f['r'] is None:
                continue
            t, g = r['t'][m], r['g']
            e = {'latest': f['r'] - t, 'latest-bias': f['r'] - bias[g] - t, 'model': predict(P0, g, f)[0] - t, 'model-recent': predict(P1, g, f)[0] - t}
            for k, v in e.items():
                err[k].append(v)
                byc[k][c].append(v)
    cs = [c for c in classes if byc['latest'][c]]
    res = {'n': len(err['latest']), 'classes': len(cs), 'rmse': {k: round(float(np.sqrt(np.mean(np.square(v)))), 3) for k, v in err.items()},
           'mae': {k: round(float(np.mean(np.abs(v))), 3) for k, v in err.items()}, 'bias': {k: round(float(np.mean(v)), 3) for k, v in err.items()}}
    for base in ('latest', 'latest-bias'):
        tt, won = {}, {}
        for k in err:
            if k == base:
                continue
            gn = [np.mean(np.square(byc[base][c])) - np.mean(np.square(byc[k][c])) for c in cs]
            sd = np.std(gn, ddof=1)
            tt[k] = round(float(np.mean(gn) / (sd / math.sqrt(len(gn)))), 2) if sd > 0 else None
            won[k] = f"{sum(1 for x in gn if x > 0)}/{len(gn)}"
        res['t_vs_' + base], res['won_vs_' + base] = tt, won
    return res


HALF = 4
# the 2026 class's ESPN heights look rewritten from the combine (56% equal its measured height rounded down, against
# ~30% in 2018-25, and the listing bias falls to +0.05 in), so it isn't a pre-combine listing: left out of every fit
SKIP = {2026}


def clean(r):
    """a measured player matched to the wrong roster row (4+ inches or 45+ lb off) is a link error, not a listing"""
    for m, cut in (('ht', 4), ('wt', 45)):
        f, t = r['f'][m], r['t'][m]
        for k in ('r', 'hs'):
            if f[k] is not None and t and abs(f[k] - t) > cut * (2 if k == 'hs' else 1):
                return False
    return r['D'] not in SKIP


def main():
    by_s, by_a = rosters()
    R = recruits()
    T = truth()
    L = link(T, by_s, by_a, R)
    print('truth', len(T), 'linked to a roster', len(L), 'with 247', sum(1 for r in L if r['rec']), file=sys.stderr)
    rows = []
    for r in L:
        s = r['D'] - 1
        if r['g'] not in GROUPS:
            continue
        rows.append({'D': r['D'], 'g': r['g'], 'name': r['name'], 'aid': r['aid'], 'src': r['src'], 'frac': r['frac'],
                     't': {'ht': r['ht'], 'wt': r['wt']}, 'f': {m: features(r['hist'], r['rec'], s, m) for m in ('ht', 'wt')}})
    nall = len(rows)
    rows = [r for r in rows if clean(r)]
    print('fit rows', len(rows), 'of', nall, file=sys.stderr)
    classes = sorted(set(r['D'] for r in rows))
    rep = {'n': len(rows), 'classes': [classes[0], classes[-1]], 'byGroup': dict(collections.Counter(r['g'] for r in rows)),
           'with247': sum(1 for r in rows if r['f']['ht']['hs'] is not None), 'bias': bias_tables(rows, L), 'heldOut': {}, 'forward': {}}
    for m in ('ht', 'wt'):
        rep['heldOut'][m] = evaluate(rows, m, HALF)
        rep['forward'][m] = evaluate(rows, m, HALF, forward=True)
        print(m, 'held out', json.dumps(rep['heldOut'][m]), file=sys.stderr)
        print(m, 'forward', json.dumps(rep['forward'][m]), file=sys.stderr)
    params = {m: fit_model(rows, m, HALF) for m in ('ht', 'wt')}
    rep['params'] = params
    out = {'_readme': 'scripts/cfb_measure.py: combine-equivalent height (in) and weight (lb) from the ESPN listing (r) and the '
                      '247 listing (hs, j = years since the class), by coarse group and listing pattern: T = mt + b . (x - mx). '
                      f'Fit on final seasons, draft classes {classes[0]}-{classes[-1]}, recency half-life {HALF} classes.',
           'groups': GROUPS, 'boardCoarse': BOARD_COARSE, 'coarse': COARSE, 'patterns': PATTERNS, 'params': params,
           'heldOut': {m: {k: rep['heldOut'][m][k] for k in ('n', 'classes', 'rmse', 'bias', 't_vs_latest', 'won_vs_latest')} for m in ('ht', 'wt')}}
    json.dump(out, open(OUT, 'w'), indent=1)
    os.makedirs(RES, exist_ok=True)
    json.dump(rep, open(os.path.join(RES, 'measure_report.json'), 'w'), indent=1)
    json.dump([{k: r[k] for k in ('D', 'g', 'name', 'aid', 'src', 't', 'f')} for r in rows], open(os.path.join(RES, 'measure_rows.json'), 'w'))


if __name__ == '__main__':
    main()
