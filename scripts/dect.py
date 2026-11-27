#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""DECT (Declare, Even, College, Transfer; was DEC, before that DoR): what each way out of the stay-or-go decision is
worth to a draft-eligible college player with eligibility left. A decision model (what is worth more), not Ret% or
Transfer% (what he will do).

    python3 scripts/dect.py         # NFL / CFB + NBA / CBB fits and history checks -> data/dect_fit.json (scripts/cfb_teams.mjs dectOf, scripts/cbb_tabs.py)

  declare   the rookie deal + d^4 x later earnings, over the pick spread from his xPick and the spread of earnings at a pick
  college   pay at his school for the season (yNIL) + d x the same draft value one year older
  transfer  pay on the open market (xNIL) + d x the same draft value one year older. No draft cost for the move: the
            test for one (CBB returners who transferred against those who stayed) is in the fit and is not there
  DECT      the one worth most as a certainty equivalent (log utility over W0 + the outcome), dollars at this season's
            cap. Even when the top two are inside one standard error: against declare, yNIL's error and the age
            term's; college against transfer, the width of the reported school budgets. The mean edge rides along.

The return side holds his draft stock where it is: no expected rise or fall, so going back costs a year (the age term
on later earnings and the discount) and pays yNIL. Who went back is not a fair sample of what going back does (the
ones told they would go late, or hurt, stay), so their record is kept as the downside case (slide), not the model.

Pieces, each from data:
  rookie deal     NFL: the 2026 slotted four-year totals (scripts/cfb_declare_econ.py SCALE); the guaranteed share by
                  pick from OverTheCap rookie deals 2017-21 (nflverse historical_contracts); the rest counts at the
                  odds he is still on a roster (P(later contract) + half of the others). Undrafted: what the 2015
                  class's undrafted signees made, at odds of a contract that fade past the last pick. NBA: salary in seasons 1-4 by pick, 2011-22 drafts (Basketball-Reference team pages).
  later earnings  NFL: everything after the rookie deal, drafts 2011-15: each veteran contract's APY as a share of that
                  year's cap x the years it ran before the next one (the last one: its guarantee at least). NBA: salary
                  from season 5 on, 2008-14 drafts. Priced at this season's cap. Poisson fit on ln pick, ln pick^2,
                  age at the draft (and position, NFL), so the age term is what a year older at the same pick costs.
  pick spread     players with no choice, so nobody picked their spot: CFB redshirt seniors and grads on each draft's
                  last PFF board before the January deadline (105 to 200 days out, 2021-25); CBB seniors on the No
                  Ceilings midseason board (2022-26). Tobit: ln pick = a + b ln rank + sd e, censored at undrafted.
  slide           the downside case: returners' pick in the next draft from the same boards (not drafted then =
                  undrafted), fit the same way
  d               .97 a year on cap-indexed dollars (the cap grows about 7% a year, so about 10% in plain dollars)
History check: the same boards of the 2022-25 drafts, underclassmen and seniors with a year left; NIL from today's yNIL
shape scaled to that season's market (as scripts/research/ret_pay_nov27/pay.py).
"""
import collections, csv, gzip, json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
OUT = os.path.join(ROOT, 'data', 'dect_fit.json')
CAP = 301.2            # $M, 2026
D = 0.97
LAST = 257
UD = {'rookie': 0.64, 'later': 1.74, 'fade': 1.3}     # undrafted, $M per signee: the 2015 class's 424 undrafted signees in the contract history (first three years at
                                                      # half credit, later earnings through 2022); fade = how fast the odds of a contract fall past the last pick,
                                                      # exp(-fade x ln(pick / 257)), set so about 480 a year sign
GRP = {'QB': 'QB', 'LT': 'OL', 'RT': 'OL', 'LG': 'OL', 'RG': 'OL', 'C': 'OL', 'T': 'OL', 'G': 'OL', 'OL': 'OL', 'OT': 'OL', 'IOL': 'OL',
       'WR': 'WR', 'TE': 'TE', 'RB': 'RB', 'FB': 'RB', 'HB': 'RB', 'ED': 'EDGE', 'EDGE': 'EDGE', 'IDL': 'DL', 'DI': 'DL', 'DL': 'DL', 'LB': 'LB',
       'CB': 'CB', 'S': 'S', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
GROUPS = ['QB', 'OL', 'WR', 'TE', 'RB', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ST']
Z = np.linspace(-3.5, 3.5, 71); W = np.exp(-Z ** 2 / 2); W /= W.sum()
LX = np.round(np.linspace(0, 7.2, 37), 3)     # ln xPick grid, pick 1 to ~1340
W0 = 2.0               # $M he earns without the sport: a bachelor's lifetime earnings (Georgetown CEW median $2.8M, less the discount). 1 and 4 are in the fit as a check
K = 16                 # outcome bins the boards read
SIG = {'cfb': 0.49, 'cbb': 0.65}     # log error of yNIL against On3's valuations (scripts/research/nil_nov27)


def qbins(r, n=25):
    """n equal slices of a sample of ratios (actual / fit), each slice's mean, scaled to mean 1"""
    r = np.sort(np.asarray(r, float)); q = np.array([c.mean() for c in np.array_split(r, min(n, len(r)))])
    return q / q.mean() if q.mean() > 0 else np.ones(len(q))


def tobins(w, r, e, k=K):
    """nodes (weight, rookie part, later part) -> k bins by total value, [weight, mean rookie, mean later]"""
    o = np.argsort(r + D ** 4 * e); w, r, e = w[o], r[o], e[o]; c = np.cumsum(w) - w / 2; ix = np.minimum(k - 1, (c / w.sum() * k).astype(int)); out = []
    for i in range(k):
        m = ix == i; ww = w[m].sum()
        out.append([float(ww), float(w[m] @ r[m] / ww), float(w[m] @ e[m] / ww)] if ww > 0 else [0.0, 0.0, 0.0])
    return out


def wmed(w, v):
    o = np.argsort(v); c = np.cumsum(w[o]); return float(v[o][np.searchsorted(c, c[-1] / 2)])


def sides(B, x, ageB, nil, d=D, w0=W0):
    """B = bins or nodes [[w, rookie, later], ...] at the grid's age; x = years over that age. -> (ce edge, ce declare, mean edge, mean declare, median edge)"""
    B = np.asarray(B, float); w, r, e = B[:, 0] / B[:, 0].sum(), B[:, 1], B[:, 2]
    vd = r + d ** 4 * e * math.exp(ageB * x); vr = nil + d * (r + d ** 4 * e * math.exp(ageB * (x + 1)))
    ce = lambda v: math.exp(float(w @ np.log(w0 + v))) - w0
    return ce(vr) - ce(vd), ce(vd), float(w @ vr - w @ vd), float(w @ vd), wmed(w, vr) - wmed(w, vd)


def verdict(B, x, ageB, ageSE, nil, sig, d=D):
    """[ce edge (+ = college), ce declare, mean edge, even?]: even when the edge is inside one standard error, from the error in yNIL and in the age term"""
    c = sides(B, x, ageB, nil, d); f = lambda b, n: sides(B, x, b, n, d)[0]
    se = math.hypot((f(ageB, nil * math.exp(sig)) - f(ageB, nil * math.exp(-sig))) / 2, (f(ageB + ageSE, nil) - f(ageB - ageSE, nil)) / 2)
    return [round(c[0], 2), round(c[1], 2), round(c[2], 2), int(abs(c[0]) < se), round(se, 2)]


def sig_gap():
    """how far a school's pay can sit from the market's: half the log width of the reported roster budgets (data/nil_budgets.json), by sport"""
    d = json.load(open(os.path.join(ROOT, 'data', 'nil_budgets.json')))
    return {k: round(float(np.mean([math.log(hi / lo) / 2 for lo, hi in d[k]['teams'].values() if lo > 0])), 3) for k in ('cfb', 'cbb')}


def verdict4(B, x, ageB, ageSE, nilC, nilT, sig, gap, d=D, w0=W0):
    """[edge, ce declare, mean edge, label, pair, transfer - college]: label D / C / T = the side worth most, E = the top two inside one
    standard error (pair names them). edge = the better of college and transfer less declare; nilT None = no market price, college only"""
    B = np.asarray(B, float)
    def val(n, b=ageB): c = sides(B, x, b, n, d, w0); return c[0] + c[1], c[2] + c[3]         # ce and mean of staying on pay n
    c0 = sides(B, x, ageB, 0.0, d, w0); V = {'D': c0[1], 'C': val(nilC)[0]}; N = {'C': nilC}
    if nilT is not None: V['T'] = val(nilT)[0]; N['T'] = nilT
    o = sorted(V, key=lambda k: -V[k]); a, b_ = o[0], o[1]
    if 'D' in (a, b_):
        k = b_ if a == 'D' else a; f = lambda bb, n: sides(B, x, bb, n, d, w0)[0]
        se = math.hypot((f(ageB, N[k] * math.exp(sig)) - f(ageB, N[k] * math.exp(-sig))) / 2, (f(ageB + ageSE, N[k]) - f(ageB - ageSE, N[k])) / 2)
    else: se = abs(val(N[a] * math.exp(gap))[0] - val(N[a] * math.exp(-gap))[0]) / 2
    even = V[a] - V[b_] < se; st = 'T' if 'T' in V and V['T'] > V['C'] else 'C'
    return [round(V[st] - V['D'], 2), round(V['D'], 2), round(val(N[st])[1] - c0[3], 2), 'E' if even else a, ''.join(sorted((a, b_))) if even else '',
            round(V['T'] - V['C'], 2) if 'T' in V else None]


def interp(G, key, lx):
    L = G['lx']; lx = min(max(lx, L[0]), L[-1]); i = max(1, next(j for j, v in enumerate(L) if v >= lx)); t = (lx - L[i - 1]) / (L[i] - L[i - 1])
    return (1 - t) * np.asarray(key[i - 1], float) + t * np.asarray(key[i], float)


def load(name, file):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file)); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None


# ------------------------------------------------------------------------------------------------- contracts
def contracts():
    import nfl_war as NW
    P = collections.defaultdict(list)
    with gzip.open(NW.get('historical_contracts.csv.gz', NW.CONTRACTS), 'rt') as f:
        for c in csv.DictReader(f):
            dy, ys, apy, pct = num(c['draft_year']), num(c['year_signed']), num(c['apy']), num(c['apy_cap_pct'])
            if not dy or not ys or not apy or not pct: continue
            cap = apy / pct; do = num(c['draft_overall'])
            P[c['otc_id']].append({'dy': int(dy), 'pick': int(do) if do else None, 'ys': int(ys), 'yrs': num(c['years']) or 1, 'val': (num(c['value']) or 0) / cap,
                                   'g': (num(c['guaranteed']) or 0) / cap, 'apy': pct, 'pos': c['position'], 'dob': c['date_of_birth']})
    return P


def earned(cs, dy, end=2022):
    v = sorted([c for c in cs if c['ys'] - dy >= 3], key=lambda c: c['ys']); tot = 0.0
    for i, c in enumerate(v):
        e = c['apy'] * max(0, min(c['yrs'], (v[i + 1]['ys'] if i + 1 < len(v) else end) - c['ys']))
        if i + 1 == len(v): e = max(e, min(c['g'], c['val']))
        tot += e
    return tot


def poisson(X, y, it=60):
    b = np.zeros(X.shape[1]); b[0] = math.log(max(y.mean(), 1e-9))
    for _ in range(it * 5):
        mu = np.exp(np.clip(X @ b, -30, 30)); H = (X * mu[:, None]).T @ X + 1e-6 * np.eye(X.shape[1]); s = np.linalg.solve(H, X.T @ (y - mu)); b += s * min(1.0, 1.0 / max(np.abs(s).max(), 1e-9))
        if np.abs(s).max() < 1e-9: break
    mu = np.exp(X @ b); Hi = np.linalg.inv((X * mu[:, None]).T @ X); M = (X * ((y - mu) ** 2)[:, None]).T @ X
    return b, np.sqrt(np.diag(Hi @ M @ Hi))


def logit(X, y, l2=1e-6):
    b = np.zeros(X.shape[1])
    for _ in range(100):
        p = 1 / (1 + np.exp(-X @ b)); s = np.linalg.solve((X * (p * (1 - p))[:, None]).T @ X + l2 * np.eye(X.shape[1]), X.T @ (y - p)); b += s
        if np.abs(s).max() < 1e-9: break
    return b


def nfl_value(out):
    import nfl_war as NW
    P = contracts(); CE = load('ce', 'cfb_declare_econ.py')
    # later earnings, drafts 2011-15; age at the draft from nflverse draft picks
    AGE = {(int(r['season']), int(r['pick'])): float(r['age']) for r in csv.DictReader(open(NW.get('draft_picks.csv', f'{NW.REL}/draft_picks/draft_picks.csv'))) if num(r['age'])}
    rows = []
    for cs in P.values():
        c0 = cs[0]
        if not c0['pick'] or not 2011 <= c0['dy'] <= 2015 or c0['pos'] not in GRP: continue
        age = AGE.get((c0['dy'], c0['pick']))
        rows.append((math.log(c0['pick']), GRP[c0['pos']], age, earned(cs, c0['dy'])))
    am = float(np.mean([r[2] for r in rows if r[2] is not None]))
    X = np.array([[1, l, l * l, (a if a is not None else am) - 22] + [g == k for k in GROUPS[1:]] for l, g, a, _ in rows], float)
    y = np.array([r[3] for r in rows]) * CAP
    b, se = poisson(X, y)
    b2 = logit(X[:, :3], (y > 0).astype(float))
    later = {'n': len(rows), 'drafts': [2011, 2015], 'b': [round(float(x), 4) for x in b], 'se': [round(float(x), 4) for x in se],
             'cols': ['const', 'lnPick', 'lnPick2', 'age-22'] + GROUPS[1:], 'ageMean': round(am, 2), 'agePct': round(100 * (math.exp(b[3]) - 1), 1),
             'ageT': round(float(b[3] / se[3]), 2), 'p2': [round(float(x), 4) for x in b2],
             'byRound': []}
    lp = np.array([r[0] for r in rows]); fit = np.exp(X @ b)
    RB = [(0, 32), (33, 64), (65, 100), (101, 140), (141, 180), (181, 262)]
    Q = [qbins(y[(lp >= math.log(a)) & (lp <= math.log(c) + 1e-9)] / fit[(lp >= math.log(a)) & (lp <= math.log(c) + 1e-9)]) for a, c in ((max(1, a), c) for a, c in RB)]
    QU = qbins([earned(cs, cs[0]['dy']) for cs in P.values() if not cs[0]['pick'] and 2011 <= cs[0]['dy'] <= 2015])       # undrafted signees
    out['_q'] = (np.log([c + 0.5 for _, c in RB]), Q, QU)
    for a, c in ((1, 10), (11, 32), (33, 64), (65, 100), (101, 140), (141, 180), (181, 220), (221, 262)):
        m = (lp >= math.log(a)) & (lp <= math.log(c)); later['byRound'].append({'picks': f'{a}-{c}', 'n': int(m.sum()), 'mean': round(float(y[m].mean()), 1), 'fit': round(float(fit[m].mean()), 1),
                                                                                  'any': round(float((y[m] > 0).mean()), 3)})
    # guaranteed share of the rookie deal by pick, 2017-21
    G = collections.defaultdict(list)
    for cs in P.values():
        for c in cs:
            if c['pick'] and c['ys'] == c['dy'] and 2017 <= c['dy'] <= 2021 and c['yrs'] >= 4 and c['val'] > 0: G[c['pick']].append(min(1.0, c['g'] / c['val']))
    gp = sorted(G); gs = np.array([np.mean(G[p]) for p in gp])
    gs = np.minimum.accumulate(np.convolve(np.pad(gs, 2, mode='edge'), np.ones(5) / 5, mode='valid'))      # smooth, never rising with the pick
    out['later'] = later
    out['rookie'] = {'scale': CE.SCALE, 'gShare': [[int(p), round(float(g), 3)] for p, g in zip(gp, gs) if p in (1, 16, 32, 33, 40, 48, 56, 64, 65, 80, 100, 120, 140, 160, 180, 200, 220, 240, 257)],
                     'undrafted': UD}
    slp = np.log([p for p, _ in CE.SCALE]); sv = np.array([v for _, v in CE.SCALE]); glp = np.log(gp)
    def rookie(l):            # $M expected from the rookie deal at ln pick l (array), drafted
        T = np.interp(l, slp, sv); g = np.interp(l, glp, gs); p2 = 1 / (1 + np.exp(-(b2[0] + b2[1] * l + b2[2] * l * l)))
        return T * (g + (1 - g) * (p2 + (1 - p2) / 2))
    def late(l, grp, age):
        gi = GROUPS.index(grp)
        return np.exp(b[0] + b[1] * l + b[2] * l * l + b[3] * (age - 22) + (b[3 + gi] if gi else 0))
    return rookie, late


# ------------------------------------------------------------------------------------------------- pick spread
def tobit(lx, s, cens, lim):
    """ln pick = a + b lx + sd e; cens rows are undrafted (true value above lim)"""
    from math import erf
    Phi = np.vectorize(lambda z: 0.5 * (1 + erf(z / math.sqrt(2))))
    def nll(t):
        a, b, ls = t; sd = math.exp(ls); m = a + b * lx
        ll = np.where(cens, np.log(np.clip(1 - Phi((lim - m) / sd), 1e-12, 1)), -0.5 * ((s - m) / sd) ** 2 - ls)
        return -ll.sum()
    t = np.array([0.5, 0.9, 0.0]); step = np.array([0.5, 0.2, 0.3]); f = nll(t)
    for _ in range(400):                       # coordinate search: three parameters, smooth
        for i in range(3):
            for sgn in (1, -1):
                u = t.copy(); u[i] += sgn * step[i]; g = nll(u)
                if g < f: t, f = u, g; break
            else: step[i] *= 0.6
        if step.max() < 1e-5: break
    return {'a': round(float(t[0]), 3), 'b': round(float(t[1]), 3), 'sd': round(float(math.exp(t[2])), 3), 'n': int(len(lx)), 'undrafted': round(float(cens.mean()), 3)}


def board_rows():
    bt = load('bt', 'cfb_draft_pct_backtest.py')
    rows, _ = bt.build_rows()
    picks = collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(bt.CACHE, 'draft_picks.csv'))):
        if int(r['season']) >= 2018: f, l = bt.parts(r['pfr_player_name']); picks[l].append((int(r['season']), int(r['pick']), f))
    latest = {}
    for r in rows:
        if 105 <= r['days'] <= 200 and (r['draft'] not in latest or r['days'] < latest[r['draft']]): latest[r['draft']] = r['days']
    fall = [r for r in rows if latest.get(r['draft']) == r['days']]
    for r in fall:
        f, l = bt.parts(r['name']); c = [x for x in picks.get(l, []) if bt.fmatch(f, x[2])]
        r['lx'] = bt.lnPick(r['rank']); r['pickNow'] = next((x[1] for x in c if x[0] == r['draft']), None)
        r['pickNext'] = next((x[1] for x in c if x[0] == r['draft'] + 1), None); r['pickLater'] = next((x[1] for x in c if x[0] == r['draft'] + 2), None)
        r['grad'] = r['cls'] in ('RS Sr.', 'G'); r['grp'] = GRP.get(r['pos'], 'LB')
    return fall, max(x[0] for v in picks.values() for x in v)


# ------------------------------------------------------------------------------------------------- NBA / CBB
NBA_CAP_NOW = 165.0          # $M, 2026-27
NBA_LAST = 60


def nba_salary_hist():
    """{bbref id: {season end year: $M}} from Basketball-Reference team pages 2011-26 (scripts/xaav.py's cache and reader)"""
    import time, xaav as X
    f = os.path.join(X.CACHE, 'nba_salary_hist.json')
    if os.path.exists(f): return json.load(open(f)), X.NBA_CAP
    T = 'ATL BOS BRK CHO CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHO POR SAC SAS TOR UTA WAS'.split()
    old = {('BRK', 2012): 'NJN', ('CHO', 2014): 'CHA', ('NOP', 2013): 'NOH'}
    out = {}
    for y in range(2011, 2027):
        for t in T:
            c = next((v for (k, yy), v in old.items() if k == t and y <= yy), t)
            miss = not os.path.exists(os.path.join(X.CACHE, 'bbref', f'{c}_{y}.html'))
            for pid, v in X.nba_salaries(c, y).items(): out.setdefault(pid, {}); out[pid][str(y)] = round(out[pid].get(str(y), 0) + v, 4)
            if miss: time.sleep(3.3)
    json.dump(out, open(f, 'w')); return out, X.NBA_CAP


def nba(out):
    import cbb_declare as CD, names as N
    sal, CAPS = nba_salary_hist()
    seas = collections.defaultdict(dict)
    with open(os.path.join(CD.KIT, 'college_seasons_nba.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f): seas[r['pid']][int(r['year'])] = r
    def share(bref, a, b):          # salary as cap share, seasons a..b (end years), priced at this season's cap
        s = sal.get(bref) or {}
        return NBA_CAP_NOW * sum(v / CAPS[int(y)] for y, v in s.items() if a <= int(y) <= b and int(y) in CAPS)
    last = {pid: by[max(by)] for pid, by in seas.items()}
    # ESPN's final board of each draft: who was a prospect and went undrafted
    espn = collections.defaultdict(list)
    with open(os.path.join(CD.BOARDS, 'all_boards.csv'), newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['source'] == 'espn': espn[int(r['draft_year'])].append((r['name'], r['school']))
    onb = set()
    for y, L in espn.items():
        M = N.Matcher([{'name': r['name'], 'team': r['team'], 'pid': pid} for pid, r in last.items() if int(r['year']) == y])
        for name, school in L:
            h = M.find(name, team=school)[0]
            if h: onb.add(h['pid'])
    P = []
    for pid, r in last.items():
        y = int(r['year']); pk = num(r['nba_pick']); dy = num(r['nba_draft'])
        if pk and dy and int(dy) != y: continue                      # drafted in another year than his last college season (stashed, G League year)
        if not pk and pid not in onb: continue
        a = CD.age_on(r['dob'], y)
        P.append({'y': y, 'pick': int(pk) if pk else None, 'age': a, 'bref': r['nba_bref'],
                  'rk': share(r['nba_bref'], y + 1, y + 4) if r['nba_bref'] else 0.0, 'late': share(r['nba_bref'], y + 5, 2026) if r['nba_bref'] else 0.0})
    RK = [p for p in P if 2011 <= p['y'] <= 2022]; LT = [p for p in P if 2008 <= p['y'] <= 2014]
    am = float(np.mean([p['age'] for p in LT if p['pick'] and p['age']]))
    def fit(S, key, age):
        S = [p for p in S if p['pick']]
        X = np.array([[1, math.log(p['pick']), math.log(p['pick']) ** 2] + ([(p['age'] or am) - 20.5] if age else []) for p in S], float)
        b, se = poisson(X, np.array([p[key] for p in S])); return b, se, len(S)
    br, _, nr = fit(RK, 'rk', False); bl, sl, nl = fit(LT, 'late', True)
    udr = [p for p in RK if not p['pick']]; udl = [p for p in LT if not p['pick']]
    UDN = {'rookie': round(float(np.mean([p['rk'] for p in udr])), 3), 'later': round(float(np.mean([p['late'] for p in udl])), 3), 'nRookie': len(udr), 'nLater': len(udl),
           'anyNba': round(float(np.mean([p['rk'] > 0 for p in udr])), 3)}
    def bands(S, key, b, age):
        o = []
        for a, c in ((1, 5), (6, 14), (15, 30), (31, 45), (46, 60)):
            s = [p for p in S if p['pick'] and a <= p['pick'] <= c]
            o.append({'picks': f'{a}-{c}', 'n': len(s), 'mean': round(float(np.mean([p[key] for p in s])), 1),
                      'fit': round(float(np.mean([math.exp(b[0] + b[1] * math.log(p['pick']) + b[2] * math.log(p['pick']) ** 2 + (b[3] * ((p['age'] or am) - 20.5) if age else 0)) for p in s])), 1)})
        return o
    V = {'cap': NBA_CAP_NOW, 'rookie': {'drafts': [2011, 2022], 'n': nr, 'b': [round(float(x), 4) for x in br], 'byPick': bands(RK, 'rk', br, False)},
         'later': {'drafts': [2008, 2014], 'n': nl, 'b': [round(float(x), 4) for x in bl], 'se': [round(float(x), 4) for x in sl], 'ageMean': round(am, 2),
                   'agePct': round(100 * (math.exp(bl[3]) - 1), 1), 'ageT': round(float(bl[3] / sl[3]), 2), 'byPick': bands(LT, 'late', bl, True)},
         'undrafted': UDN}
    print(json.dumps(V))
    rookie = lambda l: np.exp(br[0] + br[1] * l + br[2] * l * l)
    late = lambda l, age: np.exp(bl[0] + bl[1] * l + bl[2] * l * l + bl[3] * (age - 20.5))
    lim = math.log(NBA_LAST + 0.5)

    # pick spread from the No Ceilings midseason board (scripts/cbb_declare.py rows): leavers to their pick, returners to the next draft
    rows = CD.rows_from_kit(); byp = {(r['pid'], r['year']): r for r in rows}
    def outcome(pid, y):
        r = seas[pid].get(y)
        return int(float(r['nba_pick'])) if r and num(r['nba_pick']) and num(r['nba_draft']) == y else None
    ranked = [r for r in rows if r['nb']]
    for r in ranked: r['lx'] = math.log(min(r['nb'], 100))
    brd = CD.board_ranks(seas)
    dec = [{'pid': pid, 'year': y, 'lx': math.log(min(rk_, 100))} for (pid, y), rk_ in brd.items() if seas[pid][y]['yr'] == 'Sr']     # seniors: no choice in it
    def tb(S):
        return tobit(np.array([r['lx'] for r in S]), np.array([math.log(outcome(r['pid'], r['year'])) if outcome(r['pid'], r['year']) else lim for r in S]),
                     np.array([outcome(r['pid'], r['year']) is None for r in S]), lim)
    TDn = tb(dec); TAll = tb([r for r in ranked if r['left']])
    ret = [r for r in ranked if not r['left'] and r['year'] + 1 <= 2026 and (r['year'] + 1) in seas[r['pid']]]
    S, C, again = [], [], 0
    for r in ret:
        n = byp.get((r['pid'], r['year'] + 1)); pk = outcome(r['pid'], r['year'] + 1)
        if pk: S.append(math.log(pk)); C.append(False)
        elif n and not n['left']:                # back for another year: his next board rank through the declare curve stands in for the pick
            again += 1; v = TDn['a'] + TDn['b'] * math.log(min(n['nb'], 100)) if n['nb'] else lim
            S.append(min(v, lim)); C.append(v >= lim)
        else: S.append(lim); C.append(True)
    TRn = tobit(np.array([r['lx'] for r in ret]), np.array(S), np.array(C), lim); TRn['again'] = again
    print('nba declare (seniors)', TDn); print('nba early entrants', TAll); print('nba slide', TRn)

    def ev(T, lx, age):
        s = T['a'] + T['b'] * lx + T['sd'] * Z; dr = s <= lim; l = np.clip(s, 0, lim)
        return float(W @ np.where(dr, rookie(l), UDN['rookie'])), float(W @ np.where(dr, late(l, age), UDN['later'] * math.exp(bl[3] * (age - am))))
    def dor(lx, age, nil, T=None):
        rd, ed = ev(TDn, lx, age); rr, er = ev(T or TDn, lx, age + 1)
        vd = rd + D ** 4 * ed; vr = nil + D * (rr + D ** 4 * er); return vr - vd, vd, vr
    LXN = np.round(np.linspace(0, math.log(100), 24), 3)
    # outcome spread: drafts 2011-14, where both the first four seasons and the later ones are on record, as ratios to the fit
    NB = [(1, 14), (15, 30), (31, 45), (46, 60)]; J = [p for p in P if 2011 <= p['y'] <= 2014]
    def pairs(S, fr, fl):
        a = np.array([[p['rk'] / fr(p), p['late'] / fl(p)] for p in S]); return a / np.maximum(a.mean(0), 1e-9)
    QN = [pairs([p for p in J if p['pick'] and a <= p['pick'] <= c], lambda p: float(rookie(math.log(p['pick']))), lambda p: float(late(math.log(p['pick']), p['age'] or am))) for a, c in NB]
    QUN = pairs([p for p in J if not p['pick']], lambda p: 1.0, lambda p: 1.0)
    def nodes(lx, T=None):
        T = T or TDn; s = T['a'] + T['b'] * lx + T['sd'] * Z; w, r, e = [], [], []
        for z, wz in zip(s, W):
            if z <= lim:
                l = max(z, 0.0); q = QN[next(i for i, (_, c) in enumerate(NB) if math.exp(l) <= c + 0.5)]
                w += [wz / len(q)] * len(q); r += list(float(rookie(l)) * q[:, 0]); e += list(float(late(l, 20.5)) * q[:, 1])
            else:
                w += [wz / len(QUN)] * len(QUN); r += list(UDN['rookie'] * QUN[:, 0]); e += list(UDN['later'] * math.exp(bl[3] * (20.5 - am)) * QUN[:, 1])
        return np.array(w), np.array(r), np.array(e)
    def solve(f):
        lo, hi = 0.0, 400.0
        for _ in range(50):
            m = (lo + hi) / 2; lo, hi = (m, hi) if f(m) < 0 else (lo, m)
        return round(hi, 2)
    bece = lambda p, k=0, w0=W0: (lambda B: solve(lambda n: sides(B, -0.5, float(bl[3]), n, w0=w0)[k]))(np.column_stack(nodes(math.log(p))))
    V['spread'] = {'declare': TDn, 'slide': TRn, 'earlyEntrants': TAll, 'drafts': sorted({r['year'] for r in ranked})}
    V['grid'] = {'lx': [float(x) for x in LXN], 'age0': 20.5, 'ageB': round(float(bl[3]), 4), 'ageSE': round(float(sl[3]), 4), 'ageMean': round(am, 2), 'udLater': UDN['later'],
                 'dec': [[round(v, 3) for v in ev(TDn, x, 20.5)] for x in LXN],
                 'bins': [[[round(v, 4) for v in t] for t in tobins(*nodes(x))] for x in LXN]}
    V['spreadN'] = {'drafts': [2011, 2014], 'n': int(sum(len(q) for q in QN)), 'undrafted': int(len(QUN))}
    V['table'] = [{'rank': p, 'declare': round(dor(math.log(p), 20, 0)[1], 2), 'declareCE': round(sides(np.column_stack(nodes(math.log(p))), -0.5, float(bl[3]), 0)[1], 2),
                   'breakEvenNil': round(-dor(math.log(p), 20, 0)[0], 2), 'ce': bece(p), 'ceW1': bece(p, 0, 1.0), 'ceW4': bece(p, 0, 4.0), 'median': bece(p, 4),
                   'slide': round(-dor(math.log(p), 20, 0, TRn)[0], 2)} for p in (1, 5, 10, 14, 20, 30, 40, 50, 60, 80, 100)]
    for t in V['table']: print(t)

    # history check, 2022-26 boards
    sys.path.insert(0, os.path.join(HERE, 'research', 'ret_pay_nov27'))
    import pay as PAY
    Sh = PAY.cbb_ynil_shape(); HM = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}
    for r in ranked:
        hm = seas[r['pid']][r['year']]['conf'] in HM
        r['nil'] = 1e-6 * math.exp(Sh['a'] + Sh['b'] * r['lx'] + Sh['hm'] * hm) * PAY.NILM[r['year']] / PAY.NILM[2026]
        r['edge'], r['vd'], r['vr'] = dor(r['lx'], r['age'], r['nil'])
        B = np.column_stack(nodes(r['lx'])); c = sides(B, r['age'] - 20.5, float(bl[3]), r['nil']); r['ce'], r['med'] = c[0], c[4]
        r['even'] = verdict(B, r['age'] - 20.5, float(bl[3]), float(sl[3]), r['nil'], SIG['cbb'])[3]
    def real(pk, age): return float(rookie(math.log(pk)) + D ** 4 * late(math.log(pk), age)) if pk else UDN['rookie'] + D ** 4 * UDN['later'] * math.exp(bl[3] * (age - am))
    R = [r for r in ret if (lambda n: not (n and not n['left']))(byp.get((r['pid'], r['year'] + 1)))]      # returners whose next year ended in a draft or an exit
    for r in R: r['got'] = r['nil'] + D * real(outcome(r['pid'], r['year'] + 1), r['age'] + 1)
    def band(S, f): return [{'rank': f'{a}-{c}', 'n': len(s), **f(s)} for a, c in ((1, 14), (15, 30), (31, 60), (61, 100)) for s in [[r for r in S if a <= r['nb'] <= c]] if s]
    V['check'] = {'n': len(ranked), 'drafts': sorted({r['year'] for r in ranked}), 'saysReturn': round(float(np.mean([r['edge'] > 0 for r in ranked])), 3),
                  'returned': round(float(np.mean([1 - r['left'] for r in ranked])), 3),
                  'returnedWhenSaysReturn': round(float(np.mean([1 - r['left'] for r in ranked if r['edge'] > 0] or [0])), 3),
                  'returnedWhenSaysDeclare': round(float(np.mean([1 - r['left'] for r in ranked if r['edge'] <= 0] or [0])), 3),
                  'returners': {'n': len(R), 'again': again, 'drafted': round(float(np.mean([outcome(r['pid'], r['year'] + 1) is not None for r in R])), 3),
                                'meanDeclareEV': round(float(np.mean([r['vd'] for r in R])), 2), 'meanGot': round(float(np.mean([r['got'] for r in R])), 2),
                                'beatDeclare': round(float(np.mean([r['got'] > r['vd'] for r in R])), 3)},
                  'bands': band(ranked, lambda s: {'saysReturn': round(float(np.mean([r['edge'] > 0 for r in s])), 3), 'returned': round(float(np.mean([1 - r['left'] for r in s])), 3),
                                                   'medianEdge': round(float(np.median([r['edge'] for r in s])), 2)})}
    V['check']['readings'] = readings(ranked, lambda r: 1 - r['left'])
    # ---- transfer: who moved, whether the move cost draft stock, and the four-way verdict on the same boards
    GAPN = sig_gap()['cbb']
    def nxt(r): n = seas[r['pid']].get(r['year'] + 1); return None if n is None else int(n['team'] != seas[r['pid']][r['year']]['team'])
    for r in ranked:
        r['moved'] = None if r['left'] else nxt(r); hm = seas[r['pid']][r['year']]['conf'] in HM
        r['nilX'] = 1e-6 * math.exp(Sh['a'] + Sh['b'] * r['lx'] + Sh['hm']) * PAY.NILM[r['year']] / PAY.NILM[2026]            # the market: a high-major's price for him
        r['lab'] = verdict4(np.column_stack(nodes(r['lx'])), r['age'] - 20.5, float(bl[3]), float(sl[3]), r['nil'], None if hm else r['nilX'], SIG['cbb'], GAPN)[3]      # a high-major's market price is his own school's level here: no second price
        r['did'] = 'D' if r['left'] else None if r['moved'] is None else 'T' if r['moved'] else 'C'
    K = [r for r in ranked if r['did']]
    tab = {l: {'n': sum(r['lab'] == l for r in K), **{k: round(float(np.mean([r['did'] == k for r in K if r['lab'] == l])), 3) for k in 'DCT'}} for l in 'DECT' if any(r['lab'] == l for r in K)}
    # the cost of a move: every returning prospect in the declare model's rows since the 2021 rule (transfer and play at once), drafted in a later year or not
    A = [r for r in rows if not r['left'] and 2021 <= r['year'] <= 2024 and (r['year'] + 1) in seas[r['pid']]]
    for r in A: r['mv'] = int(seas[r['pid']][r['year'] + 1]['team'] != seas[r['pid']][r['year']]['team']); r['later'] = int(any(num(q['nba_draft']) and num(q['nba_draft']) > r['year'] for q in seas[r['pid']].values()))
    XA = np.array([[1, r['bpm'], r['rank'], r['age'], r['ht'], r['mv']] for r in A], float); XA[:, 1:5] = (XA[:, 1:5] - XA[:, 1:5].mean(0)) / XA[:, 1:5].std(0); ya = np.array([r['later'] for r in A], float)
    ba = logit(XA, ya, 1e-4); pa = 1 / (1 + np.exp(-XA @ ba)); sa = np.sqrt(np.diag(np.linalg.inv((XA * (pa * (1 - pa))[:, None]).T @ XA + 1e-4 * np.eye(6))))
    V['transfer'] = {'gap': GAPN, 'n': len(K), 'did': {k: round(float(np.mean([r['did'] == k for r in K])), 3) for k in 'DCT'}, 'byVerdict': tab,
                     'cost': {'n': len(A), 'moved': int(sum(r['mv'] for r in A)), 'draftedLater': int(ya.sum()), 'draftedMoved': round(float(np.mean([r['later'] for r in A if r['mv']])), 4),
                              'draftedStayed': round(float(np.mean([r['later'] for r in A if not r['mv']])), 4), 'b': round(float(ba[5]), 3), 't': round(float(ba[5] / sa[5]), 2), 'seasons': [2021, 2024]}}
    print(json.dumps(V['transfer'], indent=1))
    print(json.dumps(V['check']['readings'], indent=1))
    out['nba'] = V


def auc(x, y):
    x = np.asarray(x, float); y = np.asarray(y); o = np.argsort(x); rk = np.empty(len(x)); rk[o] = np.arange(1, len(x) + 1)
    for v in np.unique(x): m = x == v; rk[m] = rk[m].mean()
    n1 = y.sum(); n0 = len(y) - n1
    return float((rk[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def readings(H, ret):
    """which reading of the edge lines up with what players did: share it sends to college, AUC against who went back, and the same inside rank thirds"""
    y = np.array([ret(r) for r in H]); lx = np.array([r['lx'] for r in H]); cut = np.quantile(lx, [1 / 3, 2 / 3]); th = np.searchsorted(cut, lx); o = {'n': len(H), 'returned': round(float(y.mean()), 3)}
    for k in ('edge', 'med', 'ce'):
        e = np.array([r[k] for r in H]); rel = e / np.array([max(r['vd'], 0.05) for r in H])
        o[{'edge': 'mean', 'med': 'median', 'ce': 'ce'}[k]] = {'saysCollege': round(float((e > 0).mean()), 3), 'returnedWhenCollege': round(float(y[e > 0].mean()), 3) if (e > 0).any() else None,
            'returnedWhenDeclare': round(float(y[e <= 0].mean()), 3), 'auc': round(auc(e, y), 3), 'aucRel': round(auc(rel, y), 3),
            'aucInThirds': round(float(np.mean([auc(e[th == i], y[th == i]) for i in range(3) if 0 < y[th == i].sum() < (th == i).sum()])), 3)}
    ev = np.array([r['even'] for r in H]); e = np.array([r['ce'] for r in H])
    o['even'] = {'share': round(float(ev.mean()), 3), 'returned': round(float(y[ev == 1].mean()), 3) if ev.any() else None,
                 'returnedCollege': round(float(y[(ev == 0) & (e > 0)].mean()), 3) if ((ev == 0) & (e > 0)).any() else None, 'nCollege': int(((ev == 0) & (e > 0)).sum()),
                 'returnedDeclare': round(float(y[(ev == 0) & (e <= 0)].mean()), 3)}
    return o


def nba_dect(rank, age, ynil, xnil=None, fit=None):
    """verdict4 for a college player at consensus rank `rank`, `age` on draft night, `ynil` / `xnil` dollars (scripts/cbb_tabs.py)"""
    fit = fit or json.load(open(OUT)); G = fit['nba']['grid']
    if rank is None or age is None or ynil is None or rank > 100: return None
    return verdict4(interp(G, G['bins'], math.log(max(1, rank))), age - G['age0'], G['ageB'], G['ageSE'], ynil / 1e6, xnil / 1e6 if xnil is not None else None,
                    fit['sig']['cbb'], fit['gap']['cbb'], fit['d'], fit['w0'])


def main():
    out = {'_readme': __doc__.split('\n\n')[1].strip(), 'cap': CAP, 'd': D, 'groups': GROUPS}
    rookie, late = nfl_value(out)
    fall, lastDraft = board_rows()
    lim = math.log(LAST + 0.5)
    dec = [r for r in fall if r['grad'] and r['declared']]     # out of eligibility: no choice in it
    decAll = [r for r in fall if r['declared']]
    ret = [r for r in fall if not r['declared'] and not r['grad'] and r['draft'] + 1 <= lastDraft]
    def fit(S, key):
        return tobit(np.array([r['lx'] for r in S]), np.array([math.log(r[key]) if r[key] else lim for r in S]), np.array([r[key] is None for r in S]), lim)
    TD, TR = fit(dec, 'pickNow'), fit(ret, 'pickNext')
    TR['laterDraft'] = int(sum(1 for r in ret if not r['pickNext'] and r['pickLater']))
    out['spread'] = {'declare': TD, 'slide': TR, 'allDeclared': fit(decAll, 'pickNow'), 'drafts': sorted({r['draft'] for r in fall})}
    print('declare (no choice)', TD); print('all declared', out['spread']['allDeclared']); print('slide', TR)

    AGEB = out['later']['b'][3]
    def ev(T, lx, grp, age):
        """(rookie part, later part) in $M over the pick spread T from ln xPick lx"""
        s = T['a'] + T['b'] * lx + T['sd'] * Z; dr = s <= lim; l = np.clip(s, 0, lim)
        sign = np.exp(-UD['fade'] * np.maximum(0, s - lim))
        r = np.where(dr, rookie(l), UD['rookie'] * sign)
        e = np.where(dr, late(l, grp, age), UD['later'] * sign * math.exp(AGEB * (age - 22)))
        return float(W @ r), float(W @ e)
    def dor(lx, grp, age, nil, T=None):
        rd, ed = ev(TD, lx, grp, age); rr, er = ev(T or TD, lx, grp, age + 1)
        vd = rd + D ** 4 * ed; vr = nil + D * (rr + D ** 4 * er)
        return vr - vd, vd, vr
    QL, Q, QU = out.pop('_q')
    def nodes(lx, grp, T=None):
        """every outcome at age 22: pick node x where his later earnings fall around the fit (and, undrafted, whether he signs)"""
        T = T or TD; s = T['a'] + T['b'] * lx + T['sd'] * Z; w, r, e = [], [], []
        for z, wz in zip(s, W):
            if z <= lim:
                l = max(z, 0.0); q = Q[min(len(Q) - 1, int(np.searchsorted(QL, l)))]; rk = float(rookie(np.array(l))); lt = float(late(np.array(l), grp, 22))
                w += [wz / len(q)] * len(q); r += [rk] * len(q); e += list(lt * q)
            else:
                sg = math.exp(-UD['fade'] * (z - lim))
                w += [wz * sg / len(QU)] * len(QU) + [wz * (1 - sg)]; r += [UD['rookie']] * len(QU) + [0.0]; e += list(UD['later'] * QU) + [0.0]
        return np.array(w), np.array(r), np.array(e)
    # the grid the board reads: by group, at age 22 on draft day; the age term scales the later part
    b = out['later']['b']
    ASE = out['later']['se'][3]
    out['w0'] = W0; out['sig'] = SIG; GAP = out['gap'] = sig_gap()
    out['grid'] = {'lx': [float(x) for x in LX], 'age0': 22, 'ageB': b[3], 'ageSE': ASE,
                   'dec': {g: [[round(v, 3) for v in ev(TD, x, g, 22)] for x in LX] for g in GROUPS},
                   'bins': {g: [[[round(v, 4) for v in t] for t in tobins(*nodes(x, g))] for x in LX] for g in GROUPS}}
    def solve(f):                # the yNIL where f crosses zero, $M
        lo, hi = 0.0, 400.0
        for _ in range(50):
            m = (lo + hi) / 2; lo, hi = (m, hi) if f(m) < 0 else (lo, m)
        return round(hi, 2)
    def bece(p, g, w0=W0): B = np.column_stack(nodes(math.log(p), g)); return solve(lambda n: sides(B, -0.5, b[3], n, w0=w0)[0])
    def bemed(p, g): B = np.column_stack(nodes(math.log(p), g)); return solve(lambda n: sides(B, -0.5, b[3], n)[4])
    be = lambda p, g, T=None: round(-dor(math.log(p), g, 21.5, 0, T)[0], 2)
    out['table'] = [{'xPick': p, 'declare': round(dor(math.log(p), 'WR', 21.5, 0)[1], 2), 'declareCE': round(sides(np.column_stack(nodes(math.log(p), 'WR')), -0.5, b[3], 0)[1], 2),
                     'breakEvenNil': be(p, 'WR'), 'breakEvenNilQB': be(p, 'QB'), 'ce': bece(p, 'WR'), 'ceQB': bece(p, 'QB'), 'ceW1': bece(p, 'WR', 1.0), 'ceW4': bece(p, 'WR', 4.0),
                     'median': bemed(p, 'WR'), 'slide': be(p, 'WR', TR), 'slideQB': be(p, 'QB', TR)} for p in (1, 5, 10, 20, 32, 50, 75, 100, 150, 200, 300)]
    for t in out['table']: print(t)

    # ---- history check, NIL era fall boards
    sys.path.insert(0, os.path.join(HERE, 'research', 'ret_pay_nov27'))
    import pay as PAY
    S = PAY.cfb_ynil_shape()
    H = [r for r in fall if not r['grad'] and 2022 <= r['draft'] <= 2025]
    am = {g: float(np.mean([r['age'] + r['days'] / 365.25 for r in H if (r['cls'] == 'Sr.') == g and r['age'] is not None])) for g in (True, False)}
    for r in H:
        r['ageD'] = r['age'] + r['days'] / 365.25 if r['age'] is not None else am[r['cls'] == 'Sr.']
        r['nil'] = 1e-6 * math.exp(S['a'] + S['b'] * r['lx'] + S['qb'] * (r['pos'] == 'QB') + (S['fcs'] if r['fcs'] else 0 if r['p4'] else S['g5'])) * PAY.NILM[r['draft']] / PAY.NILM[2026]
        r['ageD'] -= 0.5      # nflverse draft age is whole years: the fit's age runs half a year under the age on draft day
        r['edge'], r['vd'], r['vr'] = dor(r['lx'], r['grp'], r['ageD'], r['nil'])
        B = np.column_stack(nodes(r['lx'], r['grp'])); c = sides(B, r['ageD'] - 22, b[3], r['nil']); r['ce'], r['med'] = c[0], c[4]
        r['even'] = verdict(B, r['ageD'] - 22, b[3], ASE, r['nil'], SIG['cfb'])[3]
    def realized(r, key, age):
        l = math.log(r[key]) if r[key] else None
        return float(rookie(np.array(l)) + D ** 4 * late(np.array(l), r['grp'], age)) if l is not None else UD['rookie'] + D ** 4 * UD['later'] * math.exp(AGEB * (age - 22))
    R = [r for r in H if not r['declared'] and r['draft'] + 1 <= lastDraft]
    for r in R: r['got'] = r['nil'] + D * realized(r, 'pickNext', r['ageD'] + 1)
    Dd = [r for r in H if r['declared']]
    for r in Dd: r['got'] = realized(r, 'pickNow', r['ageD'])
    def band(S, f):
        return [{'xPick': f'{a}-{c}', 'n': len(s), **f(s)} for a, c in ((1, 32), (33, 100), (101, 400)) for s in [[r for r in S if a <= math.exp(r['lx']) < c + 1]] if s]
    chk = {'n': len(H), 'drafts': sorted({r['draft'] for r in H}), 'saysReturn': round(float(np.mean([r['edge'] > 0 for r in H])), 3), 'returned': round(float(np.mean([1 - r['declared'] for r in H])), 3),
           'returnedWhenSaysReturn': round(float(np.mean([1 - r['declared'] for r in H if r['edge'] > 0] or [0])), 3), 'nSaysReturn': int(sum(r['edge'] > 0 for r in H)),
           'returnedWhenSaysDeclare': round(float(np.mean([1 - r['declared'] for r in H if r['edge'] <= 0])), 3),
           'returners': {'n': len(R), 'drafted': round(float(np.mean([r['pickNext'] is not None for r in R])), 3),
                         'meanDeclareEV': round(float(np.mean([r['vd'] for r in R])), 2), 'meanGot': round(float(np.mean([r['got'] for r in R])), 2),
                         'meanNil': round(float(np.mean([r['nil'] for r in R])), 2), 'beatDeclare': round(float(np.mean([r['got'] > r['vd'] for r in R])), 3),
                         'medianGain': round(float(np.median([r['got'] - r['vd'] for r in R])), 2),
                         'pickUp': round(float(np.mean([r['pickNext'] is not None and math.log(r['pickNext']) < TD['a'] + TD['b'] * r['lx'] for r in R])), 3),
                         'bands': band(R, lambda s: {'declareEV': round(float(np.mean([r['vd'] for r in s])), 2), 'got': round(float(np.mean([r['got'] for r in s])), 2),
                                                     'beat': round(float(np.mean([r['got'] > r['vd'] for r in s])), 3), 'drafted': round(float(np.mean([r['pickNext'] is not None for r in s])), 3)})},
           'declarers': {'n': len(Dd), 'meanEV': round(float(np.mean([r['vd'] for r in Dd])), 2), 'meanGot': round(float(np.mean([r['got'] for r in Dd])), 2)},
           'bands': band(H, lambda s: {'saysReturn': round(float(np.mean([r['edge'] > 0 for r in s])), 3), 'returned': round(float(np.mean([1 - r['declared'] for r in s])), 3),
                                       'medianEdge': round(float(np.median([r['edge'] for r in s])), 2)})}
    chk['readings'] = readings(H, lambda r: 1 - r['declared'])
    out['check'] = chk; print(json.dumps(chk, indent=1))
    nba(out)
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
