#!/usr/bin/env python3
"""NHL metric audit (Nov 24 2026): every player metric on one harness (prereg.md), plus team xG metrics and the
pre-registered candidates P1-P3 (D1 withdrawn before scoring: invariant, see prereg.md).
    python3 scripts/research/metric_audit_nov24/nhl/audit.py -> results.json
Seasons 2009 ... 2026 (2025-26); the 2026-27 lockbox is never read."""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(HERE, '..', '..', '..')
sys.path.insert(0, SC); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..', 'team_adj_nov24'))
import core, nhl_players as P, nhl_data as D

LAST = 2026                                   # 2025-26; 2027 = lockbox
SEAS = list(range(P.FIRST, LAST + 1))
PAIRS = list(range(P.FIRST, LAST))
LO, MIN_NEXT = 300 / 60, 500 / 60
FIT = json.load(open(P.FIT))
NEST = json.load(gzip.open(P.NESTED, 'rt'))
PV = FIT['desc']['penValue']
REPL = FIT['desc']['repl']; GPW = FIT['goalsPerWin']
MU = json.load(open(P.PROJ))['mu']

from audit_variant import variant, _mp   # MoneyPuck columns swapped before nhl_players.skaters reads them (P2, P3)


def load(kind):
    P.mp_file = variant(kind)
    try:
        return {S: P.skaters(S) for S in range(P.FIRST - 1, LAST + 1)}
    finally:
        P.mp_file = _mp

SK = {'raw': load('raw')}
GK = {S: P.goalies(S) for S in range(P.FIRST - 1, LAST + 1)}
RES = {S: P.team_results(S) for S in SEAS}
SPL = {S: P.team_split(S) for S in SEAS}
print('loaded', flush=True)

# ---- descriptive WAR, exposure parts, the outcome
base = {}
for S in SEAS:
    sk = [dict(r) for r in SK['raw'][S]]; gk = [dict(r) for r in GK[S]]
    parts = P.describe_split(S, sk, gk, PV[str(S)], SPL[S])
    base[S] = {'parts': [(x['id'], x['tm'], x['toi'] / 3600) for x in parts],
               'team': {t: (gd * gp, gp) for t, (gd, ppg, gp) in RES[S].items()},
               'grp': {r['id']: r['pos'] for r in sk + gk}, 'dr': {r['id']: r['dr'] for r in sk + gk},
               'sk': sk, 'gk': gk, 'toi': {r['id']: r['toi'] for r in sk + gk}}
    # D1 check: the penalties term off
    sk0 = [dict(r) for r in SK['raw'][S]]; gk0 = [dict(r) for r in GK[S]]
    P.describe_split(S, sk0, gk0, 0.0, SPL[S])
    base[S]['dr_nopen'] = {r['id']: r['dr'] for r in sk0 + gk0}
print('desc done', flush=True)


def hpm(S, kind='raw', w=None, pp=0.0):
    """Marcel HPM through season S on weights w (nested through S by default), centred per skaters / goalies"""
    fitd = dict(FIT, w=w or NEST[str(S)]['w']); wts = tuple(FIT['wts'])
    six = {Y: {r['id']: r for r in SK[kind][Y]} for Y in range(S - len(wts) + 1, S + 1) if Y in SK[kind]}
    gix = {Y: {r['id']: r for r in GK[Y]} for Y in range(S - len(wts) + 1, S + 1) if Y in GK}
    out = {}
    for grp, rows, idx in (('s', SK[kind][S], six), ('g', GK[S], gix)):
        v = {}
        for r in rows:
            h = P.history(r['id'], idx, S + 1, wts)
            v[r['id']] = P.rate(r, h, fitd)[0]
            if pp and r['pos'] != 'G':
                m, _ = P.marcel(h, fitd['K'], P.COMPS); v[r['id']] += pp * m['pp']
        tt = sum(r['toi'] for r in rows); mu = sum(v[r['id']] * r['toi'] for r in rows) / tt
        out.update({k: x - mu for k, x in v.items()})
    return out


def marcel_war(S):
    """projections tab Marcel: descriptive WAR a minute over S, S-1, S-2 at 1/.7/.5, 1,600 minutes toward the group
    mean, back to goals a 60 over average"""
    out = {}
    for r in base[S]['sk'] + base[S]['gk']:
        g = r['pos']; num = den = 0.0
        for w, Y in zip((1, .7, .5), (S, S - 1, S - 2)):
            q = base.get(Y, {}).get('dr', {}).get(r['id'])
            if q is None: continue
            tq = base[Y]['toi'][r['id']]
            num += w * (q - REPL[g]) / 60 * tq / 60 / GPW; den += w * tq / 60
        pm = (num + 1600 * MU[g]) / (den + 1600)
        out[r['id']] = pm * 60 * GPW + REPL[g]
    return out


def simple(S, f):
    return {r['id']: f(r) for r in base[S]['sk']}

print('metrics', flush=True)
M = {}
M['WAR (descriptive)'] = {S: base[S]['dr'] for S in SEAS}
M['pWAR / HPM (nested weights)'] = {S: hpm(S) for S in SEAS}
M['pWAR / HPM (board weights)'] = {S: hpm(S, w=FIT['w']) for S in SEAS}
M['Marcel WAR (projections tab)'] = {S: marcel_war(S) for S in SEAS}
M['GSAx a 60 (goalies)'] = {S: dict({r['id']: 0.0 for r in base[S]['sk']}, **{r['id']: r['gsax60'] for r in base[S]['gk']}) for S in SEAS}
M['points a 60'] = {S: simple(S, lambda r: r['g'] + r['a1'] + r['a2']) for S in SEAS}
gs = {}
for S in SEAS:
    v = {r['playerId']: float(r['gameScore'] or 0) / (float(r['icetime']) / 3600) for r in _mp('skaters', S)
         if r['situation'] == 'all' and float(r['icetime'] or 0) >= 60}
    tt = sum(r['toi'] for r in base[S]['sk']); mu = sum(v.get(r['id'], 0) * r['toi'] for r in base[S]['sk']) / tt
    gs[S] = {k: x - mu for k, x in v.items()}
M['MoneyPuck game score a 60'] = gs
M['5v5 on-ice relative xG'] = {S: simple(S, lambda r: r['evf'] + r['eva']) for S in SEAS}
print('candidates', flush=True)
SK['sva'] = load('sva'); SK['fsva'] = load('fsva')
C = {'P1 pWAR + PP xG at .2': {S: hpm(S, pp=0.2) for S in SEAS},
     'P2 pWAR, score-venue adj 5v5 xG': {S: hpm(S, 'sva') for S in SEAS},
     'P3 pWAR, flurry+score-venue adj xG': {S: hpm(S, 'fsva') for S in SEAS}}
D1 = {S: base[S]['dr_nopen'] for S in SEAS}


# ---- the harness
def Dn(S, val):
    b = base[S]
    return {'parts': b['parts'], 'val': val, 'team': b['team'], 'grp': b['grp']}


def score(V):
    dx = {}; per = {}; pr = defaultdict(list); own = defaultdict(list)
    for S in SEAS:
        rows = core.centred(Dn(S, V[S]), S, V[S])
        dx[S] = [(x, y) for t, x, y, _ in rows]
    for n in PAIRS:
        vn = V[n]; nx = Dn(n + 1, V[n + 1]); expo = defaultdict(float)
        for pid, t, x in base[n]['parts']: expo[pid] += x
        gf, af = core.fillv(vn, expo, base[n]['grp'], LO)
        fill = {pid: gf.get(base[n + 1]['grp'].get(pid), af) for pid, t, x in nx['parts'] if pid not in vn}
        per[n] = [(x, y) for t, x, y, _ in core.centred(nx, n + 1, vn, fill)]
        e1 = defaultdict(float)
        for pid, t, x in nx['parts']: e1[pid] += x
        for pid, x in e1.items():
            if x >= MIN_NEXT and pid in vn and pid in base[n + 1]['dr']:
                pr[n].append((vn[pid], base[n + 1]['dr'][pid], x))
                if pid in V[n + 1]: own[n].append((vn[pid], V[n + 1][pid], x))
    return dx, per, pr, own


def stats(dx, per, pr, own, Ss=SEAS, pp=PAIRS):
    X = np.array([r for S in Ss for r in dx[S]])
    ins = core.r2(X[:, 0], X[:, 1])
    sse = sst = 0.0
    for S in Ss:
        o = np.array([r for s in Ss if s != S for r in dx[s]]); b = float(np.dot(o[:, 0], o[:, 1]) / np.dot(o[:, 0], o[:, 0]))
        a = np.array(dx[S]); sse += float(((a[:, 1] - b * a[:, 0]) ** 2).sum()); sst += float((a[:, 1] ** 2).sum())
    T = np.array([r for n in pp for r in per[n]])
    R = np.array([r for n in pp for r in pr[n]]); O = np.array([r for n in pp for r in own[n]])
    return {'describe': ins, 'describeHeld': 1 - sse / sst, 'predictTeam': core.r2(T[:, 0], T[:, 1]),
            'playerR': core.wcorr(R[:, 0], R[:, 1], R[:, 2]), 'ownR': core.wcorr(O[:, 0], O[:, 1], O[:, 2]) if len(O) > 2 else None,
            'nPlayers': len(R), 'teamSeasonsPredict': len(T)}


rng = np.random.default_rng(0)
BS = [rng.choice(PAIRS, len(PAIRS)) for _ in range(2000)]


def ci(sc):
    dx, per, pr, own = sc
    out = defaultdict(list)
    for b in BS:
        bs = list(b); Ss = sorted(set(bs + [x + 1 for x in bs]))
        T = np.array([r for n in bs for r in per[n]]); R = np.array([r for n in bs for r in pr[n]])
        X = np.array([r for S in bs for r in dx[S]])
        out['describe'].append(core.r2(X[:, 0], X[:, 1])); out['predictTeam'].append(core.r2(T[:, 0], T[:, 1]))
        out['playerR'].append(core.wcorr(R[:, 0], R[:, 1], R[:, 2]))
    return {k: [round(float(np.percentile(v, 5)), 3), round(float(np.percentile(v, 95)), 3)] for k, v in out.items()}


res = {'asof': '2026-11-24', 'seasons': [SEAS[0], SEAS[-1]], 'pairs': len(PAIRS),
       'playerTarget': 'season n+1 descriptive WAR rate (500+ min), n+1 ice time weighted; ownR = vs the same metric n+1',
       'metrics': {}, 'candidates': {}, 'team': {}}
SC_ = {}
for k, V in list(M.items()) + list(C.items()):
    sc = score(V); SC_[k] = sc
    st = {a: (round(b, 4) if isinstance(b, float) else b) for a, b in stats(*sc).items()}
    st['from2015'] = {a: round(b, 4) for a, b in stats(*sc, Ss=[s for s in SEAS if s >= 2015], pp=[p for p in PAIRS if p >= 2015]).items()
                      if a in ('predictTeam', 'playerR')}
    st['ci90'] = ci(sc)
    (res['candidates'] if k in C else res['metrics'])[k] = st
    print(k, st, flush=True)

sc = score(D1); st = stats(*sc); b0 = res['metrics']['WAR (descriptive)']
res['D1'] = {'describe': round(st['describe'], 5), 'describeHeld': round(st['describeHeld'], 5),
             'base': [b0['describe'], b0['describeHeld']], 'note': 'withdrawn before scoring: team sums invariant to the pen term'}


def pairdiff(a, b):
    """per pair team R2 (adj - base), t over pairs, one sided p; player r change"""
    d = np.array([core.r2(*zip(*SC_[a][1][n])) - core.r2(*zip(*SC_[b][1][n])) for n in PAIRS])
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
    from math import erf
    p = 1 - 0.5 * (1 + erf(t / math.sqrt(2)))
    return t, p, int((d > 0).sum())

base_k = 'pWAR / HPM (nested weights)'
tests = []
for k in C:
    t, p, won = pairdiff(k, base_k)
    tests.append([k, t, p, won])
tests.sort(key=lambda r: r[2])
m = len(tests)
for i, (k, t, p, won) in enumerate(tests):
    padj = min(1.0, p * (m - i))
    c, b = res['candidates'][k], res['metrics'][base_k]
    ok = padj < .05 and c['predictTeam'] > b['predictTeam'] and c['playerR'] >= b['playerR'] - .01
    c['test'] = {'predictTeam': [b['predictTeam'], c['predictTeam']], 'playerR': [b['playerR'], c['playerR']],
                 't': round(t, 2), 'p': round(p, 4), 'pHolm': round(padj, 4), 'pairsBetter': won, 'pass': bool(ok)}
    print(k, c['test'], flush=True)

# ---- team level: MoneyPuck xGD, score-venue adjusted xGD, GD
tv = {}
for S in SEAS:
    rows = {D.team(r['team']): r for r in _mp('teams', S) if r['situation'] == 'all'}
    tv[S] = {t: ((float(r['xGoalsFor']) - float(r['xGoalsAgainst'])) / float(r['games_played']),
                 (float(r['scoreVenueAdjustedxGoalsFor']) - float(r['scoreVenueAdjustedxGoalsAgainst'])) / float(r['games_played']),
                 RES[S][t][0]) for t, r in rows.items() if t in RES[S]}
for j, nm in enumerate(('team xGD a game (MoneyPuck)', 'team score-venue adj xGD a game', 'team GD a game')):
    xs = [(tv[S][t][j], tv[S][t][2]) for S in SEAS for t in tv[S]]
    ps = [(tv[n][t][j], tv[n + 1][t][2]) for n in PAIRS for t in tv[n] if t in tv[n + 1]]
    pb = []
    for b in BS:
        q = [(tv[n][t][j], tv[n + 1][t][2]) for n in b for t in tv[n] if t in tv[n + 1]]; pb.append(core.r2(*zip(*q)))
    res['team'][nm] = {'describe': round(core.r2(*zip(*xs)), 4), 'predict': round(core.r2(*zip(*ps)), 4),
                       'predictCi90': [round(float(np.percentile(pb, 5)), 3), round(float(np.percentile(pb, 95)), 3)], 'n': len(ps)}
    print(nm, res['team'][nm])
json.dump(res, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
print('wrote results.json')
