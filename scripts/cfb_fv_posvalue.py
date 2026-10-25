"""Positional value on the CFB FV scale (FV_POS_VALUE in scripts/fetch_cfb.mjs), fit on NFL outcomes (audit #24).
FV grades rarity within a position (data/cfb_calibration.json tiers: players a class at or above each grade), then
scales each position's top counts by its value, ramping in from 50 to full at 60 (the k-th best RB per class grades
lower than the k-th best QB). The hand-set values (RB, LB, DT .7; TE, S .75; the rest 1) are replaced by a fit:
  1. every drafted player's realized outcome, ranked within his NFL position and draft class, is put on the FV scale
     with fvFromRank (his realized FV), so every position sits on the same rarity ladder
  2. a pooled value curve, log-linear in realized FV over 45-75, says what an outcome at each grade is worth
  3. each position's value is the count multiplier that makes its realized 55+ outcomes worth, on the ratio of sums,
     what the pooled curve promises at their grades (grid, three passes so the pooled curve settles)
  4. the multipliers are scaled so the class's total count at 60+ matches today's: value moves slots between positions,
     it doesn't add any
Value units: apy  second-contract APY as a share of the cap (classes 2012-18; nflverse contracts end mid-2022)
             war  NFL WAR a season since the draft on sub-position lines (classes 2016-21, seasons 2016-25)
             av   model AV a season (the old target's unit, as a check)
             blend  geometric mean of apy and war (market and on-field value, the brief's blended target)
Each unit is also fit with every draft class held out once (`drop`), for the nested class-out harness
(node scripts/cfb_fv_refit.mjs --wide --target).
  python3 scripts/cfb_fv_target.py && python3 scripts/cfb_fv_posvalue.py -> data/cfb_fv_posvalue.json
Result (Oct 25 2026): value at equal rarity, top outcomes against the pool (apy / war): QB 1.46 / 2.88, EDGE 1.44 / 1.17,
WR 1.21 / 1.56, CB 1.18 / .92, TE .97 / .78, RB .94 / 1.07, DL .91 / .69, OL .91 / .79, LB .87 / .72, S .68 / .71. The
market and WAR agree on the direction (QB, WR, EDGE up; DL, LB, OL, S down) but none of the fits beat today's hand-set
values held out on every target (scripts/cfb_fv_refit.mjs --target), so FV_POS_VALUE is unchanged.
"""
import collections
import csv
import json
import math
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'nfl_targets.json')
PICKS = os.path.join(ROOT, 'scripts', '.cache', 'statplus', 'draft_picks.csv')
OUT = os.path.join(ROOT, 'data', 'cfb_fv_posvalue.json')
CAL = json.load(open(os.path.join(ROOT, 'data', 'cfb_calibration.json')))
# as scripts/fetch_cfb.mjs
N26 = {'QB': 171, 'RB': 397, 'WR': 607, 'TE': 389, 'EDGE': 692, 'DL': 798, 'LB': 616, 'OL': 976, 'CB': 907, 'S': 458}
CUR = {'QB': 1, 'OL': 1, 'EDGE': 1, 'WR': 1, 'CB': 1, 'DL': 0.7, 'TE': 0.75, 'S': 0.75, 'LB': 0.7, 'RB': 0.7}
TOP, PEAK, QB_MID = -0.115, -0.173, 1.6
SUB = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'SWR': 'WR', 'TE': 'TE', 'OT': 'OL', 'IOL': 'OL', 'EDGE': 'EDGE', 'DT': 'DL',
       'LB': 'LB', 'CB': 'CB', 'NCB': 'CB', 'S': 'S'}
DRAFT_POS = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL',
             'DE': 'EDGE', 'OLB': 'EDGE', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'ILB': 'LB', 'CB': 'CB',
             'DB': 'CB', 'S': 'S', 'SAF': 'S'}
UNITS = {'apy': (2012, 2018), 'war': (2016, 2021), 'av': (2016, 2021)}
GRID = [round(0.25 * 1.05 ** i, 3) for i in range(60)]


def tiers(g, pv):
    """TIERS[g] of fetch_cfb.mjs at positional value pv."""
    a = CAL['tiers'][g]
    pts = [(f, math.log(n)) for f, n in a if 30 <= f <= 55 and n > 0]
    mx, my = st.mean(p[0] for p in pts), st.mean(p[1] for p in pts)
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sum((p[0] - mx) ** 2 for p in pts)
    at = lambda f: math.exp(my + b * (f - mx)) if f <= 55 else math.exp(my + b * (55 - mx) + TOP * (min(f, 60) - 55) + PEAK * max(0, f - 60))
    pvf = lambda f: (1 - (1 - pv) * min(1, max(0, (f - 50) / 10))) * ((1 + (QB_MID - 1) * min(1, max(0, (55 - f) / 10))) if g == 'QB' else 1)
    raw = dict(a)
    top = lambda f: max(at(f), raw.get(f, 0)) if f > 55 and g == 'QB' else at(f)
    out = [[f, top(f) * pvf(f)] for f in (80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30)]
    if g == 'QB':
        out[5][1] = max(out[5][1], math.sqrt(out[4][1] * out[6][1]))
    return out


def fv_from_rank(k, g, pv, pool):
    an = [list(x) for x in tiers(g, pv)] + [[20, 0]]
    an[-1][1] = max(pool, an[-2][1] * 2)
    for i in range(1, len(an)):
        an[i][1] = max(an[i][1], an[i - 1][1] * 1.08)
    x = math.log(k)
    if x <= math.log(an[0][1]):
        return an[0][0]
    for i in range(1, len(an)):
        (f0, n0), (f1, n1) = an[i - 1], an[i]
        if x <= math.log(n1):
            return f0 + (f1 - f0) * (x - math.log(n0)) / (math.log(n1) - math.log(n0))
    return 20


def load(unit):
    T = json.load(open(TARGETS))
    pos = {r['pfr_player_id']: r['position'] for r in csv.DictReader(open(PICKS)) if r['pfr_player_id']}
    lo, hi = UNITS[unit]
    out = []
    for pid, v in T.items():
        d = v['draft']
        if not lo <= d <= hi:
            continue
        if unit == 'apy':
            val = v['apy'] * 100
        else:
            val = sum(x[1] if unit == 'war' else x[0] for x in v['seasons'].values()) / (2025 - d + 1)
        sh = collections.Counter()
        for x in v['seasons'].values():
            sh[SUB[x[3]]] += x[2]
        g = sh.most_common(1)[0][0] if sh else DRAFT_POS.get(pos.get(pid))
        if g:
            out.append((d, g, val))
    return out


def realized(recs, pv):
    by = collections.defaultdict(list)
    for r in recs:
        by[(r[0], r[1])].append(r)
    out = []
    for (d, g), L in by.items():
        for k, r in enumerate(sorted(L, key=lambda r: -r[2])):
            out.append((g, fv_from_rank(k + 0.5, g, pv[g], N26[g] / 4), r[2]))
    return out


def curve(R):
    b = collections.defaultdict(list)
    for g, f, v in R:
        if 45 <= f <= 75:
            b[round(f)].append(v)
    pts = [(f, math.log(st.mean(v))) for f, v in b.items() if len(v) >= 3 and st.mean(v) > 0]
    mx, my = st.mean(p[0] for p in pts), st.mean(p[1] for p in pts)
    s = sum((p[0] - mx) * (p[1] - my) for p in pts) / sum((p[0] - mx) ** 2 for p in pts)
    return (lambda f: math.exp(my + s * (f - mx))), s


def ratio(R, V, g):
    s = [(v, V(f)) for gg, f, v in R if gg == g and f >= 55]
    return sum(a for a, _ in s) / sum(b for _, b in s) if s else 1.0


def top_total(pv):
    """Players a class at 60+ over every position."""
    return sum(dict(tiers(g, pv[g]))[60] for g in N26)


def solve(recs):
    pv = {g: 1.0 for g in N26}
    for _ in range(3):
        V, s = curve(realized(recs, pv))
        new = {}
        for g in N26:
            rg = [r for r in recs if r[1] == g]
            new[g] = min(GRID, key=lambda x: abs(math.log(max(1e-6, ratio(realized(rg, {**pv, g: x}), V, g)))))
        pv = new
    R1 = {g: round(ratio(realized(recs, {g: 1.0 for g in N26}), curve(realized(recs, {g: 1.0 for g in N26}))[0], g), 3) for g in N26}
    return norm(pv), s, R1


def norm(pv):
    lo, hi = 0.2, 5.0     # one scale for every position, bisected so the 60+ total matches today's
    want = top_total(CUR)
    for _ in range(40):
        m = math.sqrt(lo * hi)
        if top_total({g: v * m for g, v in pv.items()}) > want:
            hi = m
        else:
            lo = m
    m = math.sqrt(lo * hi)
    return {g: round(v * m, 3) for g, v in pv.items()}


def main():
    out = {'method': 'see scripts/cfb_fv_posvalue.py', 'current': CUR, 'units': {}}
    for unit in UNITS:
        recs = load(unit)
        pv, s, R1 = solve(recs)
        lo, hi = UNITS[unit]
        drop = {}
        for c in range(2012, 2024):
            drop[str(c)] = solve([r for r in recs if r[0] != c])[0] if lo <= c <= hi else pv
        out['units'][unit] = {'classes': [lo, hi], 'n': len(recs), 'slope': round(s, 4), 'ratioAtRarity': R1, 'pv': pv, 'drop': drop}
        print(unit, 'pv', pv, 'value ratio at equal rarity', R1, flush=True)
    a, w = out['units']['apy'], out['units']['war']
    gm = lambda x, y: norm({g: math.sqrt(x[g] * y[g]) for g in N26})
    out['units']['blend'] = {'pv': gm(a['pv'], w['pv']), 'drop': {c: gm(a['drop'][c], w['drop'][c]) for c in a['drop']},
                             'ratioAtRarity': {g: round(math.sqrt(a['ratioAtRarity'][g] * w['ratioAtRarity'][g]), 3) for g in N26}}
    print('blend pv', out['units']['blend']['pv'])
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
