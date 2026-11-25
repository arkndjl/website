#!/usr/bin/env python3
"""Port round, NHL (prereg.md): N3 uncovered skater time in descriptive WAR, N4 Marcel on season-only WAR as the
predictive rate, N6 pWAR rate with the position's value over replacement added back; plus the duplicate game check.
Harness = round 1 (../../nhl/audit.py). Seasons 2009..2026; 2027 (2026-27) never read.
    python3 scripts/research/metric_audit_nov24/port/nhl_soccer_nba/nhl.py -> nhl.json"""
import gzip, json, math, os, sys
from collections import defaultdict
from math import erf
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, SC); sys.path.insert(0, os.path.join(SC, 'research', 'team_adj_nov24'))
import core, nhl_players as P, nhl_data as D

LAST = 2026
SEAS = list(range(P.FIRST, LAST + 1)); PAIRS = list(range(P.FIRST, LAST))
LO, MIN_NEXT = 300 / 60, 500 / 60
FIT = json.load(open(P.FIT)); NEST = json.load(gzip.open(P.NESTED, 'rt'))
PV = FIT['desc']['penValue']

SK = {S: P.skaters(S) for S in range(P.FIRST - 2, LAST + 1)}      # current code: HPM reads flurry adjusted xG (P3 shipped)
GK = {S: P.goalies(S) for S in range(P.FIRST - 2, LAST + 1)}
RES = {S: P.team_results(S) for S in SEAS}
SPL = {S: (P.team_split(S) if S >= P.FIRST else ({}, {})) for S in range(P.FIRST - 2, LAST + 1)}
print('loaded', flush=True)

base = {}
for S in range(P.FIRST - 2, LAST + 1):
    sk = [dict(r) for r in SK[S]]; gk = [dict(r) for r in GK[S]]
    pv = PV.get(str(S)) or P.pen_value(S) or PV[str(P.FIRST)]
    parts = P.describe_split(S, sk, gk, pv, SPL[S])
    base[S] = {'parts': [(x['id'], x['tm'], x['toi'] / 3600) for x in parts], 'pos': {x['id']: x['pos'] for x in parts},
               'team': {t: (gd * gp, gp) for t, (gd, ppg, gp) in RES[S].items()} if S in RES else {},
               'grp': {r['id']: r['pos'] for r in sk + gk}, 'dr': {r['id']: r['dr'] for r in sk + gk},
               'toi': {r['id']: r['toi'] for r in sk + gk}, 'rows': sk + gk}
print('desc done', flush=True)


def hpm(S):
    fitd = dict(FIT, w=NEST[str(S)]['w']); wts = tuple(FIT['wts'])
    six = {Y: {r['id']: r for r in SK[Y]} for Y in range(S - len(wts) + 1, S + 1)}
    gix = {Y: {r['id']: r for r in GK[Y]} for Y in range(S - len(wts) + 1, S + 1)}
    out = {}
    for rows, idx in ((SK[S], six), (GK[S], gix)):
        v = {r['id']: P.rate(r, P.history(r['id'], idx, S + 1, wts), fitd)[0] for r in rows}
        tt = sum(r['toi'] for r in rows); mu = sum(v[r['id']] * r['toi'] for r in rows) / tt
        out.update({k: x - mu for k, x in v.items()})
    return out


def Dn(S, val):
    b = base[S]; return {'parts': b['parts'], 'val': val, 'team': b['team'], 'grp': b['grp']}


def predict(V):
    """per pair: team rows (x, y) and player rows (v_n, dr_{n+1}, toi_{n+1})"""
    per, pr = {}, {}
    for n in PAIRS:
        vn = V[n]; nx = Dn(n + 1, None); expo = defaultdict(float)
        for pid, t, x in base[n]['parts']: expo[pid] += x
        gf, af = core.fillv(vn, expo, base[n]['grp'], LO)
        fill = {pid: gf.get(base[n + 1]['grp'].get(pid), af) for pid, t, x in nx['parts'] if pid not in vn}
        per[n] = [(x, y) for t, x, y, _ in core.centred(dict(nx, val=vn), n + 1, vn, fill)]
        e1 = defaultdict(float)
        for pid, t, x in nx['parts']: e1[pid] += x
        pr[n] = [(vn[pid], base[n + 1]['dr'][pid], x) for pid, x in e1.items()
                 if x >= MIN_NEXT and pid in vn and pid in base[n + 1]['dr']]
    return per, pr


def pstats(per, pr):
    T = [r for n in PAIRS for r in per[n]]; R = np.array([r for n in PAIRS for r in pr[n]])
    return {'predictTeam': round(core.r2(*zip(*T)), 4), 'playerR': round(core.wcorr(R[:, 0], R[:, 1], R[:, 2]), 4)}


def onesided(d):
    d = np.asarray(d, float); t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    return t, 1 - 0.5 * (1 + erf(t / math.sqrt(2)))


OUT = {'asof': '2026-11-24', 'seasons': [SEAS[0], SEAS[-1]], 'pairs': len(PAIRS), 'candidates': {}}

# ---------------- predictive base: shipped pWAR (HPM, nested weights, flurry adjusted xG)
H = {S: hpm(S) for S in SEAS}
B_per, B_pr = predict(H); b0 = pstats(B_per, B_pr); OUT['base_pWAR'] = b0
print('base pWAR', b0, flush=True)
bpair = {n: core.r2(*zip(*B_per[n])) for n in PAIRS}


def lopo(build, grid):
    cache = {g: predict({S: build(S, g) for S in SEAS}) for g in grid}
    per, pr, pick = {}, {}, {}
    for n in PAIRS:
        best = max(grid, key=lambda g: core.r2(*zip(*[r for m in PAIRS if m != n for r in cache[g][0][m]])))
        per[n], pr[n], pick[n] = cache[best][0][n], cache[best][1][n], best
    full = max(grid, key=lambda g: core.r2(*zip(*[r for m in PAIRS for r in cache[g][0][m]])))
    return per, pr, pick, full, {str(g): pstats(*cache[g]) for g in grid}


def judge(name, per, pr, extra=None):
    a = pstats(per, pr); d = [core.r2(*zip(*per[n])) - bpair[n] for n in PAIRS]; t, p = onesided(d)
    o = {'target': 'predict team R2 (n+1 GD a game)', 'before': b0, 'after': a, 't': round(t, 2), 'p': round(p, 4),
         'pairsBetter': int(sum(x > 0 for x in d)), 'guard': bool(a['playerR'] >= b0['playerR'] - .01)}
    if extra: o.update(extra)
    OUT['candidates'][name] = o; print(name, o, flush=True)


# ---------------- N4: Marcel on season-only WAR (dr), toward the F / D / G mean of regulars, seasons <= n
def regmu(S):
    a = defaultdict(lambda: [0.0, 0.0])
    for Y in range(P.FIRST - 2, S + 1):
        for r in base[Y]['rows']:
            if r['toi'] >= 500 * 60: x = a[r['pos']]; x[0] += r['dr'] * r['toi']; x[1] += r['toi']
    return {k: v[0] / v[1] for k, v in a.items()}


MU = {S: regmu(S) for S in SEAS}


def marcel_dr(S, g):
    w, K = g; K *= 60; out = {}
    for r in base[S]['rows']:
        num, den = K * MU[S][r['pos']], K
        for j, wt in enumerate((1, w, w * w)):
            Y = S - j; q = base[Y]['dr'].get(r['id'])
            if q is not None: num += wt * q * base[Y]['toi'][r['id']]; den += wt * base[Y]['toi'][r['id']]
        out[r['id']] = num / den
    return out


per, pr, pick, full, grid_scores = lopo(marcel_dr, [(w, K) for w in (.25, .5, .75) for K in (400, 800, 1600, 3200, 6400)])
judge('N4 Marcel season-only WAR (pos mean, no age)', per, pr, {'picks': {n: list(pick[n]) for n in PAIRS}, 'fullFitPick': list(full),
                                                              'grid': grid_scores})


# ---------------- N6: pWAR a 60 = HPM - the season's replacement HPM of the position (season_table's line)
def repl_hpm(S):
    rows = [dict(r, hpm=H[S][r['id']], S=S) for r in base[S]['rows']]
    out = {}
    for pos, top in (('F', 13), ('D', 7), ('G', 2)):
        rest = P.depth_rest(rows, pos, top); tt = sum(r['toi'] for r in rest)
        out[pos] = sum(r['hpm'] * r['toi'] for r in rest) / tt
    return out


RH = {S: repl_hpm(S) for S in SEAS}
V6 = {S: {pid: v - RH[S][base[S]['grp'][pid]] for pid, v in H[S].items()} for S in SEAS}
per, pr = predict(V6)
judge('N6 pWAR rate + position value over replacement (F/D/G)', per, pr,
      {'replHPM': {S: {k: round(v, 3) for k, v in RH[S].items()} for S in (2010, 2018, 2026)}})


# ---------------- N3: descriptive WAR + c x uncovered skater hours (5 x goalie hours - skater hours, per team)
def dx_rows(S, c):
    s = defaultdict(float); sk = defaultdict(float); gh = defaultdict(float)
    for pid, t, x in base[S]['parts']:
        s[t] += base[S]['dr'][pid] * x
        (gh if base[S]['pos'][pid] == 'G' else sk)[t] += x
    rows = [(t, (s[t] + c * (5 * gh[t] - sk[t])) / g, y / g) for t, (y, g) in base[S]['team'].items() if t in s and g]
    mx, my = np.mean([r[1] for r in rows]), np.mean([r[2] for r in rows])
    return [(x - mx, y - my) for t, x, y in rows], {t: 5 * gh[t] - sk[t] for t in gh}


def held(cfun):
    """per season held-out (SSE, SST): slope through origin (and c) fit on the other seasons"""
    out = {}
    for S in SEAS:
        c = cfun(S); o = [r for Y in SEAS if Y != S for r in dx_rows(Y, c)[0]]
        b = sum(x * y for x, y in o) / sum(x * x for x, y in o); a = dx_rows(S, c)[0]
        out[S] = (sum((y - b * x) ** 2 for x, y in a), sum(y * y for x, y in a), c)
    return out


def hr2(h): return 1 - sum(v[0] for v in h.values()) / sum(v[1] for v in h.values())


CG = [round(-1 + .1 * i, 1) for i in range(21)]


def pooled_fit(c, excl):
    rows = [r for Y in SEAS if Y != excl for r in dx_rows(Y, c)[0]]
    b = sum(x * y for x, y in rows) / sum(x * x for x, y in rows)
    return -sum((y - b * x) ** 2 for x, y in rows)


H0 = held(lambda S: 0.0)
H3 = held(lambda S: max(CG, key=lambda c: pooled_fit(c, S)))
d = [(H0[S][0] - H3[S][0]) / H0[S][1] for S in SEAS]; t, p = onesided(d)
unc = [v / base[S]['team'][t][1] for S in SEAS for t, v in dx_rows(S, 0)[1].items() if t in base[S]['team']]
OUT['candidates']['N3 WAR + uncovered skater time at c'] = {
    'target': 'held-out describe R2 (same season GD a game)', 'before': round(hr2(H0), 5), 'after': round(hr2(H3), 5),
    't': round(t, 2), 'p': round(p, 4), 'pairsBetter': int(sum(x > 0 for x in d)), 'guard': True,
    'cPicks': {S: H3[S][2] for S in SEAS},
    'uncoveredSkaterHoursAGame': {'mean': round(float(np.mean(unc)), 3), 'sd': round(float(np.std(unc)), 3)}}
print('N3', OUT['candidates']['N3 WAR + uncovered skater time at c'], flush=True)

# ---------------- duplicate games (idea 8)
dup = {}
for S in SEAS:
    seen = defaultdict(list)
    for g in D.games(S):
        seen[(g['day'], frozenset((g['h'], g['a'])))].append(g['id'])
    ids = [g['id'] for g in D.games(S)]
    dup[S] = {'games': len(ids), 'sameDayTeams': sum(len(v) - 1 for v in seen.values() if len(v) > 1),
              'sameId': len(ids) - len(set(ids))}
    lg = D._logs('skater', S, 2, False)
    k = [(r[0], r[1]) for r in lg]
    dup[S]['skaterLogDupRows'] = len(k) - len(set(k))
OUT['duplicates'] = dup
print('dups', {S: v for S, v in dup.items() if v['sameDayTeams'] or v['sameId'] or v['skaterLogDupRows']}, flush=True)
json.dump(OUT, open(os.path.join(HERE, 'nhl.json'), 'w'), indent=1, default=str)
print('wrote nhl.json')
