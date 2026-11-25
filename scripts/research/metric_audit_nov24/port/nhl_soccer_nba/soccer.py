#!/usr/bin/env python3
"""Port round, soccer (prereg.md): S3 / S3b uncovered team minutes (red cards, data gaps) at a fitted line c in team
GAR / SVAR sums (held-out describe), the idea 6 diagnostic (p/90 vs p/90 centred by position, predict team), and the
duplicate match check. Harness = round 1 (../../soccer/audit.py). Seasons 2015..2026; 2027 never read.
    python3 scripts/research/metric_audit_nov24/port/nhl_soccer_nba/soccer.py -> soccer.json"""
import gzip, json, math, os, sys
from collections import defaultdict
from math import erf
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'team_adj_nov24'))
import core  # noqa: E402

SEASONS = list(range(2015, 2027)); PAIRS = SEASONS[:-1]
ESPN = json.load(open(os.path.join(ROOT, 'data', 'soccer_logos.json')))['espn']
G = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))
BIG5 = {'eng.1', 'esp.1', 'ita.1', 'ger.1', 'fra.1'}


def results(S):
    lo, hi = f'{S - 1}-07-20', f'{S}-07-19'
    gd, gp = defaultdict(float), defaultdict(int)
    for g in G:
        if g['lg'] in BIG5 and lo <= g['day'] <= hi and g.get('st') == 'FT' and g.get('hs') is not None:
            for t, d in ((g['h'], g['hs'] - g['as']), (g['a'], g['as'] - g['hs'])):
                gd[(g['lg'], t)] += d; gp[(g['lg'], t)] += 1
    return gd, gp


def load(S):
    rows = json.load(open(os.path.join(ROOT, 'static', 'data', 'soccer-war', f'{S}.json')))['players']
    gd, gp = results(S)
    parts, team, cg, E, pos = [], {}, {}, defaultdict(float), {}
    A = defaultdict(lambda: defaultdict(float)); mx = defaultdict(float); cov = defaultdict(float)
    for r in rows:
        if not r.get('min'): continue
        tid = ESPN.get(r['team'])
        if not tid or (r['lg'], tid) not in gp: continue
        t = f"{r['lg']}|{tid}"; e = r['min'] / 90
        parts.append((r['p'], t, e)); team[t] = (gd[(r['lg'], tid)], gp[(r['lg'], tid)]); cg[t] = r['lg']
        E[r['p']] += e; cov[t] += e
        a = A[r['p']]
        for k in ('gar', 'svar'): a[k] += r.get(k) or 0.0
        a['pg90'] += (r.get('pg90') or 0.0) * e
        if r['min'] >= mx[r['p']]: mx[r['p']] = r['min']; pos[r['p']] = r['pos']
    unc = {t: max(0.0, 11 * team[t][1] - cov[t]) for t in team}
    val = {'GAR': {p: a['gar'] / E[p] for p, a in A.items()}, 'SVAR': {p: a['svar'] / E[p] for p, a in A.items()},
           'p/90': {p: a['pg90'] / E[p] for p, a in A.items()}}
    return {'parts': parts, 'team': team, 'cg': cg, 'grp': pos, 'E': dict(E), 'val': val, 'unc': unc}


D = {S: load(S) for S in SEASONS}
print('loaded', flush=True)


def onesided(d):
    d = np.asarray(d, float); t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    return t, 1 - 0.5 * (1 + erf(t / math.sqrt(2)))


def dx_rows(S, key, c):
    """centred within league-season: (sum value x 90s + c x uncovered 90s) / matches vs GD a match"""
    d = D[S]; s = defaultdict(float)
    for pid, t, x in d['parts']: s[t] += d['val'][key][pid] * x
    rows = [(t, (s[t] + c * d['unc'][t]) / g, y / g, d['cg'][t]) for t, (y, g) in d['team'].items()]
    out = []
    for L in set(r[3] for r in rows):
        rr = [r for r in rows if r[3] == L]; mx_, my = np.mean([r[1] for r in rr]), np.mean([r[2] for r in rr])
        out += [(r[1] - mx_, r[2] - my) for r in rr]
    return out


CG = [round(-.30 + .02 * i, 2) for i in range(21)]


def held(key, seasons, cfun):
    out = {}
    for S in seasons:
        c = cfun(S); o = [r for Y in seasons if Y != S for r in dx_rows(Y, key, c)]
        b = sum(x * y for x, y in o) / sum(x * x for x, y in o); a = dx_rows(S, key, c)
        out[S] = (sum((y - b * x) ** 2 for x, y in a), sum(y * y for x, y in a), c)
    return out


def pick_c(key, seasons, excl):
    def sse(c):
        rows = [r for Y in seasons if Y != excl for r in dx_rows(Y, key, c)]
        b = sum(x * y for x, y in rows) / sum(x * x for x, y in rows)
        return sum((y - b * x) ** 2 for x, y in rows)
    return min(CG, key=sse)


def hr2(h): return 1 - sum(v[0] for v in h.values()) / sum(v[1] for v in h.values())


OUT = {'asof': '2026-11-24', 'seasons': [SEASONS[0], SEASONS[-1]], 'candidates': {}}
u = [D[S]['unc'][t] / D[S]['team'][t][1] for S in SEASONS for t in D[S]['team']]
OUT['uncovered90sAMatch'] = {'mean': round(float(np.mean(u)), 4), 'sd': round(float(np.std(u)), 4),
                             'bySeason': {S: round(float(np.mean([D[S]['unc'][t] / D[S]['team'][t][1] for t in D[S]['team']])), 4) for S in SEASONS}}
for name, key in (('S3 GAR + uncovered minutes at c', 'GAR'), ('S3b SV/SVAR + uncovered minutes at c', 'SVAR')):
    res = {}
    for lab, ss in (('all', SEASONS), ('no2020_21', [S for S in SEASONS if S not in (2020, 2021)])):
        H0 = held(key, ss, lambda S: 0.0); H1 = held(key, ss, lambda S: pick_c(key, ss, S))
        d = [(H0[S][0] - H1[S][0]) / H0[S][1] for S in ss]; t, p = onesided(d)
        res[lab] = {'before': round(hr2(H0), 5), 'after': round(hr2(H1), 5), 't': round(t, 2), 'p': round(p, 4),
                    'seasonsBetter': int(sum(x > 0 for x in d)), 'n': len(ss), 'cPicks': {S: H1[S][2] for S in ss}}
    o = {'target': 'held-out describe R2 (same season GD a match)', **res['all'], 'sensitivity_no2020_21': res['no2020_21'], 'guard': True}
    OUT['candidates'][name] = o; print(name, o, flush=True)


# ---- idea 6 diagnostic: p/90 (over the position's replacement line) vs p/90 minus its position mean, predict team
def pred(V):
    per = {}
    for n in PAIRS:
        vn = V[n]; gf, af = core.fillv(vn, D[n]['E'], D[n]['grp'], 10)
        fill = {pid: gf.get(D[n + 1]['grp'].get(pid), af) for pid, t, x in D[n + 1]['parts'] if pid not in vn}
        Dn = {'parts': D[n + 1]['parts'], 'team': D[n + 1]['team'], 'cg': D[n + 1]['cg'], 'grp': D[n + 1]['grp'], 'val': vn}
        per[n] = [(x, y) for t, x, y, _ in core.centred(Dn, n + 1, vn, fill)]
    return per


def centre_pos(n):
    v = D[n]['val']['p/90']; a = defaultdict(lambda: [0.0, 0.0])
    for p, x in v.items(): q = a[D[n]['grp'].get(p, 'M')]; q[0] += x * D[n]['E'][p]; q[1] += D[n]['E'][p]
    mu = {k: q[0] / q[1] for k, q in a.items()}
    return {p: x - mu[D[n]['grp'].get(p, 'M')] for p, x in v.items()}, mu


A = pred({n: D[n]['val']['p/90'] for n in SEASONS}); Bc = pred({n: centre_pos(n)[0] for n in SEASONS})
d = [core.r2(*zip(*A[n])) - core.r2(*zip(*Bc[n])) for n in PAIRS]; t, p = onesided(d)
OUT['idea6_diagnostic'] = {'p90_predictTeam': round(core.r2(*zip(*[r for n in PAIRS for r in A[n]])), 4),
                           'p90_centredByPosition_predictTeam': round(core.r2(*zip(*[r for n in PAIRS for r in Bc[n]])), 4),
                           't_shipped_minus_centred': round(t, 2), 'pairsBetter': int(sum(x > 0 for x in d)),
                           'positionMeans2025': {k: round(v, 4) for k, v in centre_pos(2025)[1].items()}}
print('idea6', OUT['idea6_diagnostic'], flush=True)

# ---- duplicate matches (idea 8): same day + same two clubs in the ESPN log, by league
seen = defaultdict(list); ids = defaultdict(int)
for g in G:
    seen[(g['lg'], g['day'], frozenset((g['h'], g['a'])))].append(g)
    if g.get('id') is not None: ids[g['id']] += 1
dd = [k for k, v in seen.items() if len(v) > 1]
OUT['duplicates'] = {'matches': len(G), 'sameDayClubs': len(dd), 'sameId': sum(v - 1 for v in ids.values() if v > 1),
                     'examples': [[k[0], k[1], sorted(k[2])] for k in dd[:5]]}
print('dups', OUT['duplicates'], flush=True)
json.dump(OUT, open(os.path.join(HERE, 'soccer.json'), 'w'), indent=1, default=str)
print('wrote soccer.json')
