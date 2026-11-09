# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Measured size as an FV input (Noah, Nov 3 2026): does frame read on the measured height and weight
(scripts/cfb_measure.py) instead of the single ESPN listing improve FV out of sample, and do height / weight / BMI z
within the position a player projects to add anything beyond frameFV?

Rows: scripts/data/cfb_alltime_rows.json.gz, the harness's own grades (scripts/cfb_fv_refit.mjs --alltime: every FBS
season 2014-25 at QB-LB under the shipped weights, box-score stand-ins before 2019), restricted to the --wide universe
(last seasons 2014-22 of players gone by 2023, plus their earlier seasons through 2021). Frame enters FV after the
scarcity grade (fm = base + FRAME_W frameFV(listing) - years), so a variant swaps the frame term exactly:
fm' = clamp(fm - 1.4 frameFV(listing) + 1.4 frameFV(new)); rows graded at the floor (20) stay there.
The listing is the harness's (cfbfastR roster that season, name + school). The measured estimate uses the ESPN listing
and the 247 listing, with the measurement model refit without the row's draft class.
Gates as the harness's --gates: weight picked per class-out fold on the grid by pooled r(avOf(FV), AV) + mean
within-position r, t of the held-out fold gains and classes won; within-position Spearman (held out); top 32 model FV
a class (last seasons, AV and draft capital); forward (weight picked on the 2014-18 classes, 2019-23 graded).
  python3 scripts/cfb_measure_fv.py -> data/cfb_measure_fv.json          (the 28 variants)
  MEASURE_ONLY=ship python3 scripts/cfb_measure_fv.py -> data/cfb_measure_fv_ship.json   (the shipped form)
Needs python3 scripts/cfb_measure.py first (scripts/.cache/measure/measure_rows.json) and the cfbfastR rosters, 247 pages
and nflverse draft picks in scripts/.cache (as the harness).
Result (Nov 3 2026; 14,265 rows, 7,211 last seasons, 1,269 drafted; 29 variants, Holm not cleared by any):
  frame on the measured size (meas)        t 0.15, 4/10 classes: fail (the measurement is better, FV isn't)
  frame on the 247 listing (hs247)         picks 0 in every fold; at full weight t -3.08, 1/10 (a recruiting-era
                                           listing hurts: the live board read On3's, mostly that, first)
  frame over projected spots (move)        t -0.47: fail
  weight z / BMI z in the projected spot, pooled and by position (17)   best z_wt|LB 1.55, z_bmi|EDGE 1.68: fail
  height z in the projected spot (z_ht)    t 2.89, 9/10, Spearman .435 -> .448, top 32 AV +.04 / capital +.03,
                                           forward better: passes; the raw listing (z_ht_listing) t 3.11 passes too
  height z by position (7)                 EDGE 2.83, DL 2.10 (passes), LB 1.89; QB, RB, WR, TE ~0
  shipped form, z centred on the pool (z_ht_c): held-out pick 2 (t 2.53, 9/10); fixed 1.5 t 3.83, 10/10, Spearman
  .4476, top 32 AV +.043 (7/10), capital +.049 (7/10), forward r +.011 and top 32 4.167 -> 4.171: shipped at 1.5
  (scripts/cfb_frame.mjs heightFV)
"""
import collections
import csv
import gzip
import json
import math
import os
import re
import sys
import unicodedata

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cfb_measure as CM  # noqa: E402

C = os.path.join(ROOT, 'scripts', '.cache')
CAL = json.load(open(os.path.join(ROOT, 'data', 'cfb_calibration.json')))
MOVE = json.load(open(os.path.join(ROOT, 'data', 'cfb_move_combine_fit.json')))
OUT = os.path.join(ROOT, 'data', 'cfb_measure_fv.json')
G7 = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB']
FRAME_W = 1.4
AV_BY_FV = [(20, 0), (30, 0.4), (40, 1.7), (50, 3.7), (60, 5.0), (65, 6.3), (70, 7.2), (75, 8.1), (80, 10.1)]


def avOf(fv):
    for (f0, a0), (f1, a1) in zip(AV_BY_FV, AV_BY_FV[1:]):
        if fv <= f1:
            return a0 + (a1 - a0) * max(0, fv - f0) / (f1 - f0)
    return AV_BY_FV[-1][1]


def nm(s):
    s = unicodedata.normalize('NFKD', (s or '').lower())
    s = re.sub(r'[^a-z ]', '', s)
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def school(s):
    t = nm(s)
    t = re.sub(r'\bstate\b', 'st', t, count=1)
    t = re.sub(r'\s+', ' ', re.sub(r'\buniversity\b|\bof\b', '', t)).strip()
    return t.split(' ')[0] if t else ''


def frameFV(g, ht, wt):
    """as scripts/cfb_fv_refit.mjs frameFV (before FRAME_W)"""
    n = CAL['size'].get(g)
    if not n or not ht or not wt:
        return 0.0
    fv = 0.0
    h = n.get('hinge', {})
    for m, x in (('ht', ht), ('wt', wt)):
        q = n.get(m)
        if not q:
            continue
        if x < q['p10']:
            fv -= abs(h.get(m + '_lo', 0)) * (q['p10'] - x) / q['sd']
        elif x > q['p90']:
            fv += h.get(m + '_hi', 0) * (x - q['p90']) / q['sd'] if h.get(m + '_hi', 0) < 0 else 0
        else:
            fv += max(0, h.get(m + '_mid', 0)) * (x - q['p50']) / q['sd'] * 0.5
    fv = max(-8, min(3, fv * 0.5))
    if g == 'EDGE':
        fv += -min(5, max(0, n['wt']['p10'] - 10 - wt) * 0.25)
    return fv


def corr(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def rank(x):
    x = np.asarray(x, float)
    o = np.argsort(x, kind='mergesort')
    r = np.empty(len(x))
    i = 0
    xs = x[o]
    while i < len(x):
        j = i
        while j + 1 < len(x) and xs[j + 1] == xs[i]:
            j += 1
        r[o[i:j + 1]] = (i + j) / 2
        i = j + 1
    return r


# ---- data -----------------------------------------------------------------------------------------------------
def load():
    rows = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_alltime_rows.json.gz')))
    rows = [r for r in rows if r['s'] <= 2022 and r['last'] is not None and r['last'] <= 2023 and r['av'] is not None
            and (r['final'] or r['s'] <= 2021)]
    # rosters as the harness reads them: season|name -> [{team, ht, wt, pos, aid}]
    ros = collections.defaultdict(list)
    for y in range(2012, 2023):
        for r in csv.DictReader(open(os.path.join(C, 'fvrefit', 'ros', f'r{y}.csv'), encoding='utf-8')):
            ros[f"{y}|{nm(r['first_name'] + ' ' + r['last_name'])}"].append(
                {'team': school(r['team']), 'ht': CM.num(r['height']), 'wt': CM.num(r['weight']), 'pos': r['position'], 'aid': r['athlete_id']})
    # 247 as the harness reads it (name key -> classes), with the listing
    rec = collections.defaultdict(list)
    for x in CM.recruits():
        rec[nm(x['name'])].append({**x, 'sch': school(x['school'])})
    # draft capital: AV a season by slot, a + b ln(pick), 2012-19 drafts (as the harness)
    P = [r for r in csv.DictReader(open(os.path.join(C, 'statplus', 'draft_picks.csv'), encoding='utf-8'))
         if 2012 <= int(r['season']) <= 2019 and CM.num(r['pick'])]
    x = np.log([float(r['pick']) for r in P])
    y = np.array([(float(r['w_av'] or 0)) / (2025 - int(r['season']) + 1) for r in P])
    b = np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2)
    cap = lambda pk: max(0.0, y.mean() + b * (math.log(pk) - x.mean()))  # noqa: E731
    for r in rows:
        n, sch, s = nm(r['name']), school(r['team']), r['s']
        L = ros.get(f'{s}|{n}', [])
        rl = next((q for q in L if q['team'] == sch), L[0] if L else None)
        cands = [q for q in rec.get(n, []) if s - 6 <= q['cls'] <= s]
        rc = next((q for q in cands if q['sch'] == sch), cands[0] if len(cands) == 1 else None)
        r['rl'], r['rc'] = rl, rc
        r['cap'] = cap(r['pick']) if r['pick'] else 0.0
    return rows


# ---- the measured estimate per row, measurement model refit without the row's draft class -------------------------
def measured(rows):
    mrows = json.load(open(os.path.join(CM.RES, 'measure_rows.json')))
    mrows = [r for r in mrows if CM.clean(r)]
    models = {}
    for D in sorted(set(r['last'] + 1 for r in rows)):
        tr = [r for r in mrows if r['D'] != D]
        models[D] = {m: CM.fit_model(tr, m, CM.HALF) for m in ('ht', 'wt')}
    for r in rows:
        rl, rc, s = r['rl'], r['rc'], r['s']
        cg = CM.BOARD_COARSE[r['g']]
        est = {}
        for m in ('ht', 'wt'):
            f = {'r': rl[m] if rl and rl[m] else None, 'hs': rc[m] if rc and rc.get(m) else None}
            f['j'] = s + 1 - rc['cls'] if f['hs'] is not None else None
            p, _ = CM.predict(models[r['last'] + 1][m], cg, f)
            est[m] = p
        r['est'] = est
        r['hs'] = {m: (rc[m] if rc and rc.get(m) else None) for m in ('ht', 'wt')}
        r['lst'] = {m: (rl[m] if rl and rl[m] else None) for m in ('ht', 'wt')}


def move_odds(g, ht, wt, rc):
    """size-only odds of each NFL move the board scores (no PFN-stat flags: box-era rows have none), from the move
    model's pre-combine fit (data/cfb_move_combine_fit.json live.pre); history = recruited at the new spot"""
    MF, NORM = MOVE['live'], MOVE['norms']
    m = MF['pre']
    out = {}
    for to in MF['targets'].get(g, []):
        if to not in G7:
            continue
        a = m['a'].get(f'{g}-{to}')
        if a is None or g not in NORM or to not in NORM:
            continue
        z = lambda v, n: abs((v - n[0]) / n[1])  # noqa: E731
        fit = ((z(ht, NORM[g]['ht']) - z(ht, NORM[to]['ht'])) + (z(wt, NORM[g]['wt']) - z(wt, NORM[to]['wt']))) / 2
        was = 1 if rc and rc.get('pos') in MF['hsAt'].get(to, []) else 0
        out[to] = 1 / (1 + math.exp(-(a + m['b']['size'] * fit + m['b']['hist'] * was)))
    return out


def terms(rows):
    """each row's frame under the listing (today), the 247 listing, the measured estimate and the move-weighted
    measured estimate, and z of the measured size against the projected position's drafted combine norms"""
    for r in rows:
        g, L, E, H = r['g'], r['lst'], r['est'], r['hs']
        r['f0'] = FRAME_W * frameFV(g, L['ht'], L['wt'])
        r['fH'] = FRAME_W * frameFV(g, H['ht'], H['wt']) if H['ht'] and H['wt'] else r['f0']
        r['fM'] = FRAME_W * frameFV(g, E['ht'], E['wt']) if E['ht'] and E['wt'] else r['f0']
        if E['ht'] and E['wt']:
            od = move_odds(g, E['ht'], E['wt'], r['rc'])
            stay = max(0.0, 1 - sum(od.values()))
            r['fV'] = FRAME_W * (stay * frameFV(g, E['ht'], E['wt']) + sum(p * frameFV(to, E['ht'], E['wt']) for to, p in od.items()))
            r['odds'] = od
            # z within the projected position (the most likely spot when its odds pass the board's cut, else his own)
            best = max(od.items(), key=lambda kv: kv[1]) if od else None
            pg = best[0] if best and best[1] >= MOVE['live']['cut'] else g
            n = CAL['size'][pg]
            bmi = 703 * E['wt'] / E['ht'] ** 2
            r['z'] = {'ht': (E['ht'] - n['ht']['mean']) / n['ht']['sd'], 'wt': (E['wt'] - n['wt']['mean']) / n['wt']['sd'],
                      'bmi': (bmi - n['bmi']['mean']) / n['bmi']['sd']}
            r['pg'] = pg
        else:
            r['fV'], r['odds'], r['z'], r['pg'] = r['f0'], {}, None, g
        # control: the same height z on the raw listing (is the measurement what helps, or height itself?)
        n = CAL['size'][r['pg']]
        r['zL'] = {'ht': (L['ht'] - n['ht']['mean']) / n['ht']['sd']} if L['ht'] else None


# ---- the gates ------------------------------------------------------------------------------------------------
def score(fm, S, t='av'):
    x = [avOf(fm[i]) for i in S]
    y = [ROWS[i][t] for i in S]
    pooled = corr(x, y)
    within = np.mean([corr([fm[i] for i in S if ROWS[i]['g'] == g], [ROWS[i][t] for i in S if ROWS[i]['g'] == g]) for g in G7])
    return pooled, within


def obj(fm, S):
    p, w = score(fm, S)
    return p + w


def spear(fm, S):
    return float(np.mean([corr(rank([fm[i] for i in S if ROWS[i]['g'] == g]), rank([ROWS[i]['av'] for i in S if ROWS[i]['g'] == g])) for g in G7]))


def top32(fm, c, t):
    F = sorted([i for i in FIN if ROWS[i]['last'] == c], key=lambda i: -fm[i])[:32]
    return np.mean([ROWS[i][t] for i in F])


def run(name, gradeOf, grid):
    """gradeOf(w) -> fm array; w = 0 must be today's grade"""
    G = {w: gradeOf(w) for w in grid}
    base = G[0]
    picks, oof = [], np.array(base, float)
    for c in CLASSES:
        tr = [i for i in U if ROWS[i]['last'] != c]
        te = [i for i in U if ROWS[i]['last'] == c]
        w = max(grid, key=lambda v: (obj(G[v], tr) - (1e-9 if v != 0 else 0)))
        picks.append(w)
        for i in te:
            oof[i] = G[w][i]
    fg = [obj(oof, [i for i in U if ROWS[i]['last'] == c]) - obj(base, [i for i in U if ROWS[i]['last'] == c]) for c in CLASSES]
    m, se = np.mean(fg), np.std(fg, ddof=1) / math.sqrt(len(fg))
    t = m / se if se > 0 else 0.0
    c32 = [c for c in CLASSES if any(ROWS[i]['last'] == c for i in FIN)]
    d32 = {k: [top32(oof, c, k) - top32(base, c, k) for c in c32] for k in ('av', 'cap')}
    t32 = {k: [round(float(np.mean(v)), 3), round(float(np.mean(v) / (np.std(v, ddof=1) / math.sqrt(len(v)))), 2) if np.std(v) > 0 else 0.0,
               sum(1 for x in v if x > 1e-9)] for k, v in d32.items()}
    tr = [i for i in U if ROWS[i]['last'] <= 2018]
    te = [i for i in U if ROWS[i]['last'] >= 2019]
    wf = max(grid, key=lambda v: obj(G[v], tr) - (1e-9 if v != 0 else 0))
    cs = [c for c in c32 if c >= 2019]
    p1, w1 = score(G[wf], te)
    p0, w0 = score(base, te)
    fwd = {'w': wf, 'pooled': round(p1 - p0, 4), 'within': round(w1 - w0, 4),
           'cap': round(score(G[wf], te, 'cap')[1] - score(base, te, 'cap')[1], 4),
           'top32': [round(float(np.mean([top32(base, c, 'av') for c in cs])), 3), round(float(np.mean([top32(G[wf], c, 'av') for c in cs])), 3)]}
    fixed = {}
    for v in grid:
        if v == 0:
            continue
        g = [obj(G[v], [i for i in U if ROWS[i]['last'] == c]) - obj(base, [i for i in U if ROWS[i]['last'] == c]) for c in CLASSES]
        fixed[v] = [round(float(np.mean(g)), 4), round(float(np.mean(g) / (np.std(g, ddof=1) / math.sqrt(len(g)))), 2) if np.std(g) > 0 else 0.0, sum(1 for x in g if x > 0)]
    pb, wb = score(base, U)
    po, wo = score(oof, U)
    res = {'picks': picks, 'foldGain': [round(x, 4) for x in fg], 'won': f"{sum(1 for x in fg if x > 0)}/{len(fg)}", 't': round(float(t), 2),
           'pooled': [round(pb, 4), round(po, 4)], 'within': [round(wb, 4), round(wo, 4)],
           'spearman': [round(spear(base, U), 4), round(spear(oof, U), 4)], 'top32av': t32['av'], 'top32cap': t32['cap'], 'forward': fwd, 'fixed': fixed}
    sp_ok = res['spearman'][1] >= res['spearman'][0] - 1e-9
    res['pass'] = bool(t >= 2 and sum(1 for x in fg if x > 0) >= 7 and sp_ok and t32['av'][0] >= 0 and t32['cap'][0] >= 0
                       and fwd['pooled'] + fwd['within'] >= 0 and fwd['top32'][1] >= fwd['top32'][0])
    print(name.ljust(14), 't', res['t'], 'won', res['won'], 'picks', picks, 'fixed', fixed if VERBOSE_FIXED else '', 'spear', res['spearman'], 'top32av', t32['av'], 'cap', t32['cap'],
          'fwd', fwd, 'PASS' if res['pass'] else 'fail', flush=True)
    return res


ROWS, U, FIN, CLASSES = [], [], [], []
VERBOSE_FIXED = True


def main():
    global ROWS, U, FIN, CLASSES
    ROWS = load()
    measured(ROWS)
    terms(ROWS)
    U = list(range(len(ROWS)))
    FIN = [i for i in U if ROWS[i]['final']]
    CLASSES = sorted(set(ROWS[i]['last'] for i in U))
    fm0 = np.array([r['fm'] for r in ROWS], float)
    floor = fm0 <= 20 + 1e-9
    cov = {'rows': len(ROWS), 'finals': len(FIN), 'drafted': sum(1 for i in FIN if ROWS[i]['pick']), 'listing': round(float(np.mean([bool(r['lst']['ht'] and r['lst']['wt']) for r in ROWS])), 3),
           '247': round(float(np.mean([bool(r['hs']['ht'] and r['hs']['wt']) for r in ROWS])), 3), 'measured': round(float(np.mean([bool(r['est']['ht'] and r['est']['wt']) for r in ROWS])), 3),
           'floor': int(floor.sum()), 'frame': {k: round(float(np.mean([r[k] for r in ROWS])), 3) for k in ('f0', 'fH', 'fM', 'fV')},
           'frameSd': {k: round(float(np.std([r[k] for r in ROWS])), 3) for k in ('f0', 'fH', 'fM', 'fV')},
           'measMinusListing': {m: round(float(np.mean([r['est'][m] - r['lst'][m] for r in ROWS if r['est'][m] and r['lst'][m]])), 3) for m in ('ht', 'wt')}}
    print(json.dumps(cov), flush=True)

    def swap(key):
        def g(w):
            new = np.array([r['f0'] + w * (r[key] - r['f0']) for r in ROWS])
            fm = np.clip(fm0 - np.array([r['f0'] for r in ROWS]) + new, 20, 80)
            fm[floor] = 20
            return fm
        return g

    def zterm(m, pos=None, key='z'):
        def g(w):
            add = np.array([w * r[key][m] if r[key] is not None and (pos is None or r['g'] == pos) else 0.0 for r in ROWS])
            # on the measured frame (variant 1 at full weight) when asked by ZBASE, else today's
            base = MEAS_BASE if ZBASE else fm0
            fm = np.clip(base + add, 20, 80)
            fm[floor] = 20
            return fm
        return g

    out = {'coverage': cov, 'variants': {}}
    # the shipped form: height z (measured, against the projected position's drafted combine norms) centred on the
    # graded pool's mean at the position, so the term reorders within a position without moving its FV level
    zc = {g: float(np.mean([r['z']['ht'] for r in ROWS if r['z'] is not None and r['g'] == g])) for g in G7}
    for r in ROWS:
        r['zc'] = {'ht': max(-3, min(3, r['z']['ht'] - zc[r['g']]))} if r['z'] is not None else None
    cov['htCenter'] = {g: round(v, 3) for g, v in zc.items()}
    cov['projected'] = {'moved': sum(1 for r in ROWS if r['pg'] != r['g']), 'byPos': dict(collections.Counter(f"{r['g']}>{r['pg']}" for r in ROWS if r['pg'] != r['g']))}
    print('centre', cov['htCenter'], 'projected', cov['projected'], flush=True)
    if os.environ.get('MEASURE_ONLY') == 'ship':
        for w in (0.5, 1, 1.5, 2):
            out['variants'][f'z_ht_c@{w}'] = run(f'z_ht_c@{w}', zterm('ht', key='zc'), [0, w])
        out['variants']['z_ht_c'] = run('z_ht_c', zterm('ht', key='zc'), [-3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3])
        json.dump(out, open(OUT.replace('.json', '_ship.json'), 'w'), indent=1)
        return
    WG = [0, 0.25, 0.5, 0.75, 1, 1.25]
    out['variants']['meas'] = run('meas', swap('fM'), WG)
    out['variants']['hs247'] = run('hs247', swap('fH'), WG)
    out['variants']['move'] = run('move', swap('fV'), WG)
    ZG = [-3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3]
    global MEAS_BASE, ZBASE
    MEAS_BASE, ZBASE = swap('fM')(1), False
    for m in ('ht', 'wt', 'bmi'):
        out['variants'][f'z_{m}'] = run(f'z_{m}', zterm(m), ZG)
    for m in ('wt', 'bmi'):
        for g in G7:
            out['variants'][f'z_{m}|{g}'] = run(f'z_{m}|{g}', zterm(m, g), ZG)
    # added after the first pass showed z_ht clearing the fold rule (so counted as extra tests): the same z on the raw
    # listing, and z_ht by position
    out['variants']['z_ht_listing'] = run('z_ht_listing', zterm('ht', key='zL'), ZG)
    for g in G7:
        out['variants'][f'z_ht|{g}'] = run(f'z_ht|{g}', zterm('ht', g), ZG)
    out['tested'] = len(out['variants'])
    out['passed'] = [k for k, v in out['variants'].items() if v['pass']]
    json.dump(out, open(OUT, 'w'), indent=1)
    print('tested', out['tested'], 'passed', out['passed'])


MEAS_BASE, ZBASE = None, False

if __name__ == '__main__':
    main()
