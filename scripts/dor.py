#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""DoR (Declare or Return): the money on each side of the stay-or-go decision for a draft-eligible college player with
eligibility left. A decision model (what pays more), not Ret% (what he will do).

    python3 scripts/dor.py          # NFL / CFB fit + history check -> data/dor_fit.json (read by scripts/cfb_teams.mjs dorOf)

  declare  E over this year's pick spread of [ rookie deal + d^4 x later earnings ]
  return   college pay for the season (yNIL) + d x E over next year's pick spread of the same, one year older
  DoR      return - declare, in dollars at this season's cap (+ = return pays more)

Pieces, each from data:
  rookie deal     the 2026 slotted four-year totals (scripts/cfb_declare_econ.py SCALE); the guaranteed share by pick
                  from OverTheCap rookie deals 2017-21 (nflverse historical_contracts); the rest counts at the odds he is
                  still on a roster (P(later contract) + half of the others). Undrafted: a three-year minimum deal.
  later earnings  everything after the rookie deal, drafts 2011-15: each veteran contract's APY as a share of that
                  year's cap x the years it ran before the next one (the last one: its guarantee at least), priced at
                  this season's cap. Poisson fit on ln pick, ln pick^2, position and age at the draft, so the age term
                  is what a year older at the same pick costs on the back end.
  pick spread     this year: declared prospects on each draft's last PFF board before the January deadline (105 to
                  200 days out, 2021-25; a fall board would count a season gone wrong as the cost of going back) to the pick they went at,
                  censored at undrafted (Tobit: ln pick = a + b ln xPick + sd e). Next year: the same for players who
                  went back to school, to their pick in the next draft (not drafted then = undrafted). Injuries and
                  bad seasons are in that spread.
  d               .97 a year on cap-indexed dollars (the cap grows about 7% a year, so about 10% in plain dollars)
History check: the same boards of the 2022-25 drafts, underclassmen and seniors with a year left; NIL from today's yNIL
shape scaled to that season's market (as scripts/research/ret_pay_nov27/pay.py).
"""
import collections, csv, gzip, json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
OUT = os.path.join(ROOT, 'data', 'dor_fit.json')
CAP = 301.2            # $M, 2026
D = 0.97
LAST = 257
UD = {'total': 2.9, 'g': 0.02, 'keep': 0.2, 'later': 0.5}     # undrafted: 3-year minimum deal, share kept; later earnings as a share of the last pick's
GRP = {'QB': 'QB', 'LT': 'OL', 'RT': 'OL', 'LG': 'OL', 'RG': 'OL', 'C': 'OL', 'T': 'OL', 'G': 'OL', 'OL': 'OL', 'OT': 'OL', 'IOL': 'OL',
       'WR': 'WR', 'TE': 'TE', 'RB': 'RB', 'FB': 'RB', 'HB': 'RB', 'ED': 'EDGE', 'EDGE': 'EDGE', 'IDL': 'DL', 'DI': 'DL', 'DL': 'DL', 'LB': 'LB',
       'CB': 'CB', 'S': 'S', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
GROUPS = ['QB', 'OL', 'WR', 'TE', 'RB', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ST']
Z = np.linspace(-3.5, 3.5, 71); W = np.exp(-Z ** 2 / 2); W /= W.sum()
LX = np.round(np.linspace(0, 7.2, 37), 3)     # ln xPick grid, pick 1 to ~1340


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


def main():
    out = {'_readme': __doc__.split('\n\n')[1].strip(), 'cap': CAP, 'd': D, 'groups': GROUPS}
    rookie, late = nfl_value(out)
    fall, lastDraft = board_rows()
    lim = math.log(LAST + 0.5)
    dec = [r for r in fall if r['declared']]
    ret = [r for r in fall if not r['declared'] and not r['grad'] and r['draft'] + 1 <= lastDraft]
    def fit(S, key):
        return tobit(np.array([r['lx'] for r in S]), np.array([math.log(r[key]) if r[key] else lim for r in S]), np.array([r[key] is None for r in S]), lim)
    TD, TR = fit(dec, 'pickNow'), fit(ret, 'pickNext')
    TR['laterDraft'] = int(sum(1 for r in ret if not r['pickNext'] and r['pickLater']))
    out['spread'] = {'declare': TD, 'return': TR, 'drafts': sorted({r['draft'] for r in fall})}
    print('declare', TD); print('return', TR)

    def ev(T, lx, grp, age):
        """(rookie part, later part) in $M over the pick spread T from ln xPick lx"""
        s = T['a'] + T['b'] * lx + T['sd'] * Z; dr = s <= lim; l = np.clip(s, 0, lim)
        r = np.where(dr, rookie(l), UD['total'] * (UD['g'] + (1 - UD['g']) * UD['keep']))
        e = np.where(dr, late(l, grp, age), UD['later'] * late(lim, grp, age))
        return float(W @ r), float(W @ e)
    def dor(lx, grp, age, nil):
        rd, ed = ev(TD, lx, grp, age); rr, er = ev(TR, lx, grp, age + 1)
        vd = rd + D ** 4 * ed; vr = nil + D * (rr + D ** 4 * er)
        return vr - vd, vd, vr
    # the grid the board reads: by group, at age 22 on draft day; the age term scales the later part
    b = out['later']['b']
    out['grid'] = {'lx': [float(x) for x in LX], 'age0': 22, 'ageB': b[3],
                   'dec': {g: [[round(v, 3) for v in ev(TD, x, g, 22)] for x in LX] for g in GROUPS},
                   'ret': {g: [[round(v, 3) for v in ev(TR, x, g, 22)] for x in LX] for g in GROUPS}}
    TN = {**TR, 'a': TD['a'], 'b': TD['b']}            # no slide: next year's mean pick as this year's, with the returners' spread
    def be(p, g, T):
        rd, ed = ev(TD, math.log(p), g, 21.5); rr, er = ev(T, math.log(p), g, 22.5)
        return round(rd + D ** 4 * ed - D * (rr + D ** 4 * er), 2)
    out['table'] = [{'xPick': p, 'declare': round(dor(math.log(p), 'WR', 21.5, 0)[1], 2), 'breakEvenNil': be(p, 'WR', TR), 'breakEvenNilQB': be(p, 'QB', TR),
                     'noSlide': be(p, 'WR', TN), 'noSlideQB': be(p, 'QB', TN)} for p in (1, 5, 10, 20, 32, 50, 75, 100, 150, 200, 300, 500)]
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
    def realized(r, key, age):
        l = math.log(r[key]) if r[key] else None
        return float(rookie(np.array(l)) + D ** 4 * late(np.array(l), r['grp'], age)) if l is not None else UD['total'] * (UD['g'] + (1 - UD['g']) * UD['keep']) + D ** 4 * UD['later'] * float(late(lim, r['grp'], age))
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
    out['check'] = chk; print(json.dumps(chk, indent=1))
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
