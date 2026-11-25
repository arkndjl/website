#!/usr/bin/env python3
"""Soccer metric audit (Nov 24 2026): every player metric on one describe / predict harness, plus the pre-registered
predictive candidates P1-P3 (prereg.md). Seasons 2015..2026 only (2027 = 2026-27 lockbox, never read).
    python3 scripts/research/metric_audit_nov24/soccer/audit.py   -> results.json"""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'team_adj_nov24')); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import core  # noqa: E402
import names as NM  # noqa: E402

SEASONS = list(range(2015, 2027)); PAIRS = SEASONS[:-1]
ESPN = json.load(open(os.path.join(ROOT, 'data', 'soccer_logos.json')))['espn']
G = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'soccer_games_hist.json.gz')))
BIG5 = {'eng.1', 'esp.1', 'ita.1', 'ger.1', 'fra.1'}
FMS = os.path.join(ROOT, 'scripts', '.cache', 'soccer', 'fms')
RATE_W, RATE_K = (1, .5, .25), {'F': 5, 'M': 5, 'D': 10, 'GK': 640}
RATE_MU = {'F': .0813, 'M': .0652, 'D': .0544, 'GK': .0617}
rng = np.random.default_rng(0); NB = int(os.environ.get("NB", 2000))


def results(S):
    lo, hi = f'{S - 1}-07-20', f'{S}-07-19'
    gd, gp = defaultdict(float), defaultdict(int)
    for g in G:
        if g['lg'] in BIG5 and lo <= g['day'] <= hi and g.get('st') == 'FT' and g.get('hs') is not None:
            for t, d in ((g['h'], g['hs'] - g['as']), (g['a'], g['as'] - g['hs'])):
                gd[(g['lg'], t)] += d; gp[(g['lg'], t)] += 1
    return gd, gp


def fotmob(S, rows):
    """{understat pid: FotMob rating} matched on name + club within league"""
    import gzip as gz
    by = defaultdict(list)
    for r in rows: by[(r['lg'], NM.key(r['n']))].append(r)
    out = {}
    for lg in BIG5:
        p = os.path.join(FMS, f'{lg}_{S}.json.gz')
        if not os.path.exists(p): continue
        for f in json.load(gz.open(p)):
            if f.get('rt') is None or not f.get('min'): continue
            c = [r for r in by.get((lg, NM.key(f['n'] or '')), []) if NM.same_team(r['team'], f['team'] or '')] or by.get((lg, NM.key(f['n'] or '')), [])
            if len({r['p'] for r in c}) == 1: out[c[0]['p']] = float(f['rt'])
    return out


def load(S):
    rows = json.load(open(os.path.join(ROOT, 'static', 'data', 'soccer-war', f'{S}.json')))['players']
    gd, gp = results(S)
    parts, team, cg = [], {}, {}
    P = defaultdict(lambda: defaultdict(float)); pos, age = {}, {}
    for r in rows:
        if not r.get('min'): continue
        tid = ESPN.get(r['team'])
        if not tid or (r['lg'], tid) not in gp: continue
        t = f"{r['lg']}|{tid}"; e = r['min'] / 90
        parts.append((r['p'], t, e)); team[t] = (gd[(r['lg'], tid)], gp[(r['lg'], tid)]); cg[t] = r['lg']
        a = P[r['p']]; a['e'] += e
        for k in ('gar', 'svar', 'g', 'a', 'npxg', 'xa', 'ch'): a[k] += r.get(k) or 0.0
        a['onx'] += (r.get('onxgd') or 0.0) * e; a['pg90'] += (r.get('pg90') or 0.0) * e
        for k in ('xmv', 'mv', 'pj', 'p3'):
            if r.get(k) is not None: a[k] = max(a[k], r[k]) if k + '_' in a else r[k]; a[k + '_'] = 1
        if r['min'] >= a['mx']: a['mx'] = r['min']; pos[r['p']] = r['pos']
        if r.get('age') is not None: age[r['p']] = r['age']
    fm = fotmob(S, rows)
    val = {}
    E = {p: a['e'] for p, a in P.items()}
    val['GAR'] = {p: a['gar'] / a['e'] for p, a in P.items()}
    val['SV/SVAR'] = {p: a['svar'] / a['e'] for p, a in P.items()}
    val['aGAR/90'] = {p: val['GAR'][p] - .0032 * (age[p] - 21) for p in P if p in age}
    val['p/90'] = {p: a['pg90'] / a['e'] for p, a in P.items()}
    val['xMV'] = {p: a['xmv'] for p, a in P.items() if a.get('xmv_')}
    val['TM value'] = {p: a['mv'] for p, a in P.items() if a.get('mv_')}
    val['G+A/90'] = {p: (a['g'] + a['a']) / a['e'] for p, a in P.items()}
    val['npxG+xA/90'] = {p: (a['npxg'] + a['xa']) / a['e'] for p, a in P.items()}
    val['xGChain/90'] = {p: a['ch'] / a['e'] for p, a in P.items()}
    val['on xGD/90'] = {p: a['onx'] / a['e'] for p, a in P.items()}
    if fm: val['FotMob rating'] = fm
    tot = {k: {p: a[k] for p, a in P.items() if a.get(k + '_')} for k in ('pj', 'p3')}
    tot['gar'] = {p: a['gar'] for p, a in P.items()}; tot['svar'] = {p: a['svar'] for p, a in P.items()}
    return {'parts': parts, 'team': team, 'cg': cg, 'grp': pos, 'val': val, 'E': E, 'tot': tot, 'age': age,
            'gar90': val['GAR'], 'sv90': val['SV/SVAR'], 'nfm': len(fm)}


D = {S: load(S) for S in SEASONS}
for S in SEASONS: print(S, len(D[S]['team']), 'teams', len(D[S]['E']), 'players', D[S]['nfm'], 'FotMob matched', flush=True)


def Dn(S, val): return {'parts': D[S]['parts'], 'team': D[S]['team'], 'cg': D[S]['cg'], 'grp': D[S]['grp'], 'val': val}


def team_rows(S, val, fill=None):
    return [(x, y) for t, x, y, _ in core.centred(Dn(S, val), S, val, fill)]


def pred_rows(n, vn):
    """season n rates x season n+1 exposure -> n+1 rows (x, y), fill as core.run"""
    gf, af = core.fillv(vn, D[n]['E'], D[n]['grp'], 10)
    g1 = D[n + 1]['grp']
    fill = {pid: gf.get(g1.get(pid), af) for pid, t, x in D[n + 1]['parts'] if pid not in vn}
    return team_rows(n + 1, vn, fill)


def player_pairs(n, vn, target):
    e1 = D[n + 1]['E']
    return [(vn[p], target[p], x) for p, x in e1.items() if x >= 10 and p in vn and p in target]


def pooled_r2(rows): return core.r2([r[0] for r in rows], [r[1] for r in rows])


def oos_r2(per):
    """LOSO slope through the origin; per = {season: [(x, y)]}"""
    sse = ss = 0.0
    for s, rr in per.items():
        o = [r for k, v in per.items() if k != s for r in v]
        b = sum(x * y for x, y in o) / sum(x * x for x, y in o)
        sse += sum((y - b * x) ** 2 for x, y in rr); ss += sum(y * y for x, y in rr)
    return 1 - sse / ss


def wr(tr):
    if len(tr) < 3: return float('nan')
    a, b, w = zip(*tr); return core.wcorr(a, b, w)


def ci(f, keys):
    bs = [f(list(rng.choice(keys, len(keys)))) for _ in range(NB)]
    return [round(float(np.nanpercentile(bs, 5)), 3), round(float(np.nanpercentile(bs, 95)), 3)]


def score(name, getv, seasons=SEASONS, pairs=PAIRS):
    """getv(S) -> {pid: rate}"""
    V = {S: getv(S) for S in seasons}
    desc = {S: team_rows(S, V[S]) for S in seasons}
    pr = {n: pred_rows(n, V[n]) for n in pairs if n + 1 in V}
    pp = {n: player_pairs(n, V[n], V[n + 1]) for n in pr}
    pc = {n: player_pairs(n, V[n], D[n + 1]['sv90']) for n in pr}
    ks, kp = list(desc), list(pr)
    o = {'describe': round(pooled_r2([r for s in ks for r in desc[s]]), 3),
         'describeCI': ci(lambda kk: pooled_r2([r for s in kk for r in desc[s]]), ks),
         'describeHeld': round(oos_r2(desc), 3),
         'describeHeldCI': ci(lambda kk: oos_r2({i: desc[s] for i, s in enumerate(kk)}), ks),
         'predictTeam': round(pooled_r2([r for n in kp for r in pr[n]]), 3),
         'predictTeamCI': ci(lambda kk: pooled_r2([r for n in kk for r in pr[n]]), kp),
         'playerR': round(wr([r for n in kp for r in pp[n]]), 3),
         'playerRCI': ci(lambda kk: wr([r for n in kk for r in pp[n]]), kp),
         'playerR_SVnext': round(wr([r for n in kp for r in pc[n]]), 3),
         'playerR_SVnextCI': ci(lambda kk: wr([r for n in kk for r in pc[n]]), kp),
         'nPairs': len(kp), 'nPlayers': sum(len(pp[n]) for n in kp), 'seasons': [ks[0], ks[-1]],
         'byPairTeam': {n: round(pooled_r2(pr[n]), 4) for n in kp}}
    print(name, {k: v for k, v in o.items() if k != 'byPairTeam'}, flush=True)
    return o


OUT = {'metrics': {}}
for m in ['GAR', 'SV/SVAR', 'aGAR/90', 'p/90', 'xMV', 'TM value', 'G+A/90', 'npxG+xA/90', 'xGChain/90', 'on xGD/90']:
    OUT['metrics'][m] = score(m, lambda S, m=m: D[S]['val'][m])
fs = [S for S in SEASONS if 'FotMob rating' in D[S]['val']]
OUT['metrics']['FotMob rating'] = score('FotMob rating', lambda S: D[S]['val']['FotMob rating'], fs, fs[:-1])


# team baseline: season n GD a match -> n+1 GD a match (teams in both seasons, centred within league-season n+1)
def team_base(kk):
    xs, ys = [], []
    for n in kk:
        a = {t: v[0] / v[1] for t, v in D[n]['team'].items()}
        rows = [(t, a[t], v[0] / v[1], D[n + 1]['cg'][t]) for t, v in D[n + 1]['team'].items() if t in a]
        for g in set(r[3] for r in rows):
            rr = [r for r in rows if r[3] == g]; mx, my = np.mean([r[1] for r in rr]), np.mean([r[2] for r in rr])
            xs += [r[1] - mx for r in rr]; ys += [r[2] - my for r in rr]
    return core.r2(xs, ys)


OUT['teamBaseline'] = {'predictTeam': round(team_base(PAIRS), 3), 'CI': ci(team_base, PAIRS),
                       'note': 'returning clubs only (promoted clubs have no season n GD)'}


# totals: 1Y, 3Y vs GAR / SVAR total in the same roster-sum form
def roster_rows(n, tv):
    e1 = D[n + 1]['E']; s = defaultdict(float)
    for pid, t, x in D[n + 1]['parts']: s[t] += tv.get(pid, 0.0) * x / e1[pid]
    rows = [(t, s[t] / g, y / g, D[n + 1]['cg'][t]) for t, (y, g) in D[n + 1]['team'].items()]
    out = []
    for g_ in set(r[3] for r in rows):
        rr = [r for r in rows if r[3] == g_]; mx, my = np.mean([r[1] for r in rr]), np.mean([r[2] for r in rr])
        out += [(r[1] - mx, r[2] - my) for r in rr]
    return out


def gar_ahead(n, k):
    acc = defaultdict(float)
    for j in range(1, k + 1):
        for p, v in D[n + j]['tot']['gar'].items(): acc[p] += v
    return acc


TOT = {}
for nm, key in (('1Y (pj)', 'pj'), ('GAR total', 'gar'), ('SVAR total', 'svar')):
    kp = [n for n in PAIRS if D[n]['tot'][key]]
    pr = {n: roster_rows(n, D[n]['tot'][key]) for n in kp}
    pl = {n: [(D[n]['tot'][key][p], v, 1.0) for p, v in D[n + 1]['tot']['gar'].items() if p in D[n]['tot'][key]] for n in kp}
    TOT[nm] = {'pairs': [kp[0], kp[-1]], 'rosterTeamR2': round(pooled_r2([r for n in kp for r in pr[n]]), 3),
               'CI': ci(lambda kk: pooled_r2([r for n in kk for r in pr[n]]), kp),
               'playerR_GARnext': round(wr([r for n in kp for r in pl[n]]), 3),
               'playerCI': ci(lambda kk: wr([r for n in kk for r in pl[n]]), kp)}
    if key in ('pj', 'gar'):     # same pairs for both (2017 ..): pj exists from 2017
        k3 = [n for n in range(2017, 2024)]
        p3 = {n: [(D[n]['tot']['p3' if key == 'pj' else 'gar'][p], v, 1.0) for p, v in gar_ahead(n, 3).items() if p in D[n]['tot']['p3' if key == 'pj' else 'gar']] for n in k3}
        TOT[nm]['3y_playerR'] = round(wr([r for n in k3 for r in p3[n]]), 3)
        TOT[nm]['3y_label'] = '3Y (p3)' if key == 'pj' else 'GAR total vs next three'
    print(nm, TOT[nm], flush=True)
# same 2017+ pairs for GAR total, for a like-for-like with pj
kp = [n for n in PAIRS if n >= 2017]
TOT['GAR total (2017+ pairs)'] = {'rosterTeamR2': round(pooled_r2([r for n in kp for r in roster_rows(n, D[n]['tot']['gar'])]), 3),
                                  'playerR_GARnext': round(wr([(D[n]['tot']['gar'][p], v, 1.0) for n in kp for p, v in D[n + 1]['tot']['gar'].items() if p in D[n]['tot']['gar']]), 3)}
TOT['1Y pj minus GAR total, per pair'] = {n: round(pooled_r2(roster_rows(n, D[n]['tot']['pj'])) - pooled_r2(roster_rows(n, D[n]['tot']['gar'])), 4) for n in kp}
OUT['totals'] = TOT


# ---- candidates --------------------------------------------------------------------------------------------------------
def marcel(S, src, w, kmul, mu):
    """{pid: rate}: (K mu + sum w_k total_k) / (K + sum w_k 90s_k) over S, S-1, S-2 (files on hand)"""
    out = {}
    for p in D[S]['E']:
        pos = D[S]['grp'].get(p, 'M'); K = RATE_K.get(pos, 5) * kmul
        num, den = K * mu[pos], K
        for j, wt in enumerate((1, w, w * w)):
            s = S - j
            if s in D and p in D[s]['E']:
                num += wt * D[s]['tot'][src][p]; den += wt * D[s]['E'][p]
        out[p] = num / den
    return out


def sv_mu(S):
    """SV a 90 mean of regulars (900+ min) by position, seasons <= S"""
    a = defaultdict(lambda: [0.0, 0.0])
    for s in SEASONS:
        if s > S: continue
        for p, e in D[s]['E'].items():
            if e >= 10: x = a[D[s]['grp'].get(p, 'M')]; x[0] += D[s]['tot']['svar'][p]; x[1] += e
    return {k: v[0] / v[1] for k, v in a.items()}


ctrl = {n: marcel(n, 'gar', .5, 1, RATE_MU) for n in SEASONS}
chk = [abs(ctrl[2025][p] - D[2025]['val']['p/90'][p]) for p in D[2025]['E']]
OUT['controlCheck'] = {'meanAbsDiffVsStoredPg90': round(float(np.mean(chk)), 4)}
print('control rebuild vs stored pg90, mean abs diff', np.mean(chk), flush=True)

GRID = [(w, k) for w in (.25, .5, .75, 1.0) for k in (.5, 1, 2, 4)]
AGE = [(cy, co) for cy in (0, -.002, -.004, -.008) for co in (0, -.002, -.004, -.008)]


def lopo(build, grid):
    """per held pair n: grid value with best pooled team R2 on the other pairs; returns ({n: rows}, {n: player pairs}, picks)"""
    cache = {g: {n: build(n, g) for n in PAIRS} for g in grid}
    rows = {g: {n: pred_rows(n, cache[g][n]) for n in PAIRS} for g in grid}
    R, P, pick = {}, {}, {}
    for n in PAIRS:
        best = max(grid, key=lambda g: pooled_r2([r for m in PAIRS if m != n for r in rows[g][m]]))
        R[n] = rows[best][n]; P[n] = player_pairs(n, cache[best][n], D[n + 1]['sv90']); pick[n] = best
    full = max(grid, key=lambda g: pooled_r2([r for m in PAIRS for r in rows[g][m]]))
    return R, P, pick, full


CR = {n: pred_rows(n, ctrl[n]) for n in PAIRS}; CP = {n: player_pairs(n, ctrl[n], D[n + 1]['sv90']) for n in PAIRS}
svmu = {n: sv_mu(n) for n in SEASONS}


def agev(n, g):
    cy, co = g; A = D[n]['age']
    return {p: v + cy * min(A.get(p, 27) - 25, 0) + co * max(A.get(p, 27) - 29, 0) for p, v in ctrl[n].items()}


CAND = {'P1 pSV/90': (lambda n, g: marcel(n, 'svar', g[0], g[1], svmu[n]), GRID),
        'P2 p/90 retune': (lambda n, g: marcel(n, 'gar', g[0], g[1], RATE_MU), GRID),
        'P3 p/90 + age': (agev, AGE)}

_sv = {}


def p4(n, g):
    w, k, cy, co = g
    if (n, w, k) not in _sv: _sv[(n, w, k)] = marcel(n, 'svar', w, k, svmu[n])
    A = D[n]['age']
    return {p: v + cy * min(A.get(p, 27) - 25, 0) + co * max(A.get(p, 27) - 29, 0) for p, v in _sv[(n, w, k)].items()}


CAND['P4 pSV/90 + age (post hoc)'] = (p4, [g + a for g in GRID for a in AGE])
res = {}
base_team = pooled_r2([r for n in PAIRS for r in CR[n]]); base_pr = wr([r for n in PAIRS for r in CP[n]])
for nm, (b, grid) in CAND.items():
    R, P, pick, full = lopo(b, grid)
    d = np.array([pooled_r2(R[n]) - pooled_r2(CR[n]) for n in PAIRS])
    t = float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if d.std(ddof=1) > 0 else 0.0
    from math import erf, sqrt
    p = float(1 - 0.5 * (1 + erf(t / sqrt(2))))
    after_team = pooled_r2([r for n in PAIRS for r in R[n]]); after_pr = wr([r for n in PAIRS for r in P[n]])
    res[nm] = {'before': {'predictTeam': round(base_team, 4), 'playerR_SVnext': round(base_pr, 4)},
               'after': {'predictTeam': round(after_team, 4), 'playerR_SVnext': round(after_pr, 4)},
               'meanPairGain': round(float(d.mean()), 4), 't': round(t, 2), 'p': round(p, 4),
               'pairsBetter': int((d > 0).sum()), 'picks': {n: list(pick[n]) for n in PAIRS}, 'fullFitPick': list(full),
               'guard': bool(after_pr >= base_pr - .01)}
    print(nm, {k: v for k, v in res[nm].items() if k != 'picks'}, flush=True)
# Holm
order = sorted([k for k in res if 'post hoc' not in k], key=lambda k: res[k]['p'])
for i, k in enumerate(order):
    a = .05 / (len(order) - i)
    res[k]['holmAlpha'] = round(a, 4)
    res[k]['pass'] = bool(res[k]['p'] <= a and res[k]['t'] > 0 and res[k]['guard'] and res[k]['pairsBetter'] >= 6
                          and all(res[j]['p'] <= .05 / (len(order) - order.index(j)) for j in order[:i]))
P4 = res['P4 pSV/90 + age (post hoc)']
P4['pass'] = bool(P4['p'] <= .05 and P4['t'] > 0 and P4['guard'] and P4['pairsBetter'] >= 6)
# head to head (Amendment 1): per-pair team R2 of P4 minus each single passing candidate
def _pp(nm):
    b, grid = CAND[nm]; R, *_ = lopo(b, grid); return np.array([pooled_r2(R[n]) for n in PAIRS])
H = {nm: _pp(nm) for nm in CAND}
for nm in ('P1 pSV/90', 'P3 p/90 + age', 'P2 p/90 retune'):
    d = H['P4 pSV/90 + age (post hoc)'] - H[nm]
    P4['vs ' + nm] = {'meanPairGain': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))), 2), 'pairsBetter': int((d > 0).sum())}
print('P4 head to head', {k: v for k, v in P4.items() if k.startswith('vs')}, flush=True)
OUT['candidates'] = res

# prospect FV: reported, not on this harness
F = json.load(open(os.path.join(ROOT, 'data', 'soccer_prospects_fit.json')))
past = json.load(open(os.path.join(ROOT, 'data', 'soccer_prospects.json')))['past']
pf = [(o['fv'], o['out']) for o in past if o.get('fv') is not None and o.get('out') is not None]
OUT['prospectFV'] = {'cohortOutMSE': F.get('mse'), 'baseMSE_ageMV': F.get('mseBase'), 'r2': F.get('r2'),
                     'pastBoardR_fv_out': round(float(np.corrcoef(*zip(*pf))[0, 1]), 3), 'pastN': len(pf),
                     'note': 'past board = showcased rows (selected), in-sample'}
json.dump(OUT, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
print('wrote results.json')
