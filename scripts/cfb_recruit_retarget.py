#!/usr/bin/env python3
"""Recruit model retarget (audit Oct 25, #25): fit the recruit profile on a pedigree-free outcome.

    python3 scripts/cfb_recruit_retarget.py            # pulls (cached in scripts/.cache/recruit, fvrefit), test, write
    python3 scripts/cfb_recruit_retarget.py --offline

Why: scripts/cfb_recruit_fit.py trains on this season's board grade (fvg). For young players that grade is mostly
pedigree (fetch_cfb.mjs hsZ reads 247's composite), so a recruit model fit on it learns to copy the 247 composite
(the shipped FV(on) part weighs composite 2.7 to ESPN grade 1.6 per 5 points, through the gap term).

Outcome here: what the recruit became in the NFL, with nothing from recruiting in it. ESPN's 2011-19 classes (the
signees the live fit uses: every ranked and unranked recruit with an FBS or FCS school), each linked to the NFL draft
by ESPN athlete id (nflverse players.espn_id), else by name through scripts/names.py with the college and a draft
year 3-6 years after the class. Two outcomes, as the FV refits use (scripts/cfb_fv_refit.mjs): weighted NFL AV a
season through 2025, and draft capital (the AV a season the slot returns, a + b ln(pick) on the 2012-19 drafts);
undrafted 0. The target is their mean, put on the FV scale through the board's own AV map (AV_BY_FV), so an
undrafted recruit is the floor (20) and a starter's career reads in the 50s.

Programs: the signing school as the recruit saw it, last season's final Elo and conference (cfbfastR schedules),
Pac-12 counted with the Power 4. Folds hold out whole schools, as the live fit's do.

Tests (each held out): the live model scored at year 3 (as ARK stars are) against the same model's blocks refit on
the NFL outcome. Rank correlation with the outcome (Spearman, pooled and within position), the share of NFL
starters in each model's top 3% / 10%, and per-class wins with a t across the nine classes.
"""
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_recruit_fit as R   # noqa: E402
from names import Matcher     # noqa: E402

ROOT = R.ROOT
SP = os.path.join(ROOT, 'scripts', '.cache', 'statplus')
SCH = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'ros')
OUT = os.path.join(ROOT, 'data', 'cfb_recruit_retarget.json')
BEFORE = os.path.join(ROOT, 'scripts', 'cfb_recruit_fit_boardfit.json')   # the Oct 14 board-fit model, kept to score against
CLASSES = range(2011, 2020)
NFL_THROUGH = 2025
AV_BY_FV = [(20, 0), (30, 0.4), (40, 1.7), (50, 3.7), (60, 5.0), (65, 6.3), (70, 7.2), (75, 8.1), (80, 10.1)]   # as cfb_teams.mjs
P5 = {'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12'}


def fv_of(av):
    """the FV whose AV a season is av (the inverse of the board's avOf)"""
    if av <= 0: return 20.0
    for (f0, a0), (f1, a1) in zip(AV_BY_FV, AV_BY_FV[1:]):
        if av <= a1: return f0 + (f1 - f0) * (av - a0) / (a1 - a0)
    return 80.0


def pull(url, f):
    if not os.path.exists(f) or not os.path.getsize(f):
        if R.OFFLINE: raise SystemExit('missing ' + f)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        os.system(f'curl -sSLf -o {f} "{url}"')
    return list(csv.DictReader(open(f)))


def programs_hist(y):
    """The programs as a class-y recruit saw them: final Elo and conference of season y - 1 (eloZ among FBS)."""
    g = pull(f'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/csv/cfb_schedules_{y - 1}.csv', os.path.join(SCH, f's{y - 1}.csv'))
    last, conf, div, name = {}, {}, {}, {}
    for r in sorted(g, key=lambda r: (int(r['week'] or 0), r['season_type'] == 'postseason')):
        for s in ('home', 'away'):
            t = r[s + '_id']; conf[t] = r[s + '_conference']; div[t] = r[s + '_division']; name[t] = r[s + '_team']
            if r[s + '_postgame_elo'] not in ('', 'NA'): last[t] = float(r[s + '_postgame_elo'])
    fbs = [t for t in last if div.get(t) == 'fbs']
    m = np.mean([last[t] for t in fbs]); sd = np.std([last[t] for t in fbs])
    out = {}
    for t, d in div.items():
        if d == 'fbs': out[t] = {'level': 'P4' if conf[t] in P5 or t == '87' else 'G5', 'eloZ': (last.get(t, m) - m) / sd, 'team': name[t]}
        elif d == 'fcs': out[t] = {'level': 'FCS', 'eloZ': 0.0, 'team': name[t]}
    return out


def nfl():
    """Draft picks 2014-25 with ESPN ids, and the capital map."""
    pe = {x['gsis_id']: x['espn_id'] for x in csv.DictReader(open(os.path.join(SP, 'players.csv'))) if x['gsis_id']}
    d = [r for r in csv.DictReader(open(os.path.join(SP, 'draft_picks.csv'))) if 2012 <= int(r['season']) <= NFL_THROUGH]
    S = [r for r in d if int(r['season']) <= 2019 and int(r['pick'] or 0) > 0]
    x = np.log([int(r['pick']) for r in S]); yv = np.array([float(r['w_av'] or 0) / (NFL_THROUGH - int(r['season']) + 1) for r in S])
    b = np.cov(x, yv)[0, 1] / x.var(ddof=1); a = yv.mean() - b * x.mean()
    cap = lambda p: max(0.0, a + b * math.log(p))
    rows = []
    for r in d:
        s = int(r['season'])
        if s < 2014: continue
        av = float(r['w_av'] or 0) / (NFL_THROUGH - s + 1)
        rows.append({'name': r['pfr_player_name'], 'team': r['college'], 'pos': r['position'], 'season': s, 'espn': pe.get(r['gsis_id']) or None,
                     'pick': int(r['pick']), 'av': av, 'cap': cap(int(r['pick']))})
    return rows, (round(float(a), 4), round(float(b), 4))


def dataset():
    picks, capfit = nfl()
    M = Matcher(picks, name='name', team='team', pos=None, cls='season', id='espn')
    data, how = [], Counter()
    for y in CLASSES:
        prog = programs_hist(y)
        cl = R.enrich(R.recruit_class(y), prog, Counter())
        n = Counter()
        for r in cl:
            if not r['tid'] or r['tid'] not in prog: continue
            g = R.group(r['pos'], r['ht'], r['wt'])
            if g is None: continue
            # by ESPN id, else the name with his signing school as the draft college (a transfer drafted from his
            # second school is missed by name: a common name drafted out of another school is too often someone else)
            pk, h = M.find(r['name'], team=prog[r['tid']]['team'], id=r['id'], cls=lambda s, y=y: y + 3 <= s <= y + 6, cross_team='none')
            if pk is not None and h != 'id' and not (y + 3 <= pk['season'] <= y + 6): pk, h = None, None
            how[h] += 1
            av, cap = (pk['av'], pk['cap']) if pk else (0.0, 0.0)
            data.append({**r, **prog[r['tid']], 'g': g, 'k': 3, 'drafted': pk is not None, 'pick': pk['pick'] if pk else None,
                         'avps': av, 'capps': cap, 'out': (av + cap) / 2, 'rfv': fv_of((av + cap) / 2)})
    return data, how, capfit


# ---- scoring ------------------------------------------------------------------------------------------------
def rank(a):
    o = np.argsort(a, kind='stable'); r = np.empty(len(a)); r[o] = np.arange(len(a)); _, inv, c = np.unique(a, return_inverse=True, return_counts=True)
    return (np.cumsum(c) - c + (c - 1) / 2)[inv]


def spear(a, b): return float(np.corrcoef(rank(np.asarray(a)), rank(np.asarray(b)))[0, 1])


def evaluate(data, scores):
    """scores: {name: array}. Pooled and within-position Spearman with each outcome, top-share hit rates, per class."""
    y = {k: np.array([r[k] for r in data], float) for k in ('out', 'avps', 'capps')}
    start = np.array([r['avps'] >= 3.0 for r in data])          # an NFL starter's career (3+ AV a season)
    r1 = np.array([bool(r['pick']) and r['pick'] <= 64 for r in data])
    cls = np.array([r['year'] for r in data]); pos = np.array([r['g'] for r in data])
    res = {}
    for nm, s in scores.items():
        o = {f'rho_{k}': round(spear(s, v), 4) for k, v in y.items()}
        o['rho_pos'] = round(float(np.mean([spear(s[pos == p], y['out'][pos == p]) for p in R.GROUPS if (pos == p).sum() > 200])), 4)
        o['r_out'] = round(float(np.corrcoef(s, y['out'])[0, 1]), 4)
        for q in (0.03, 0.10):
            i = s >= np.quantile(s, 1 - q)
            o[f'top{int(q * 100)}'] = {'n': int(i.sum()), 'drafted': round(float(np.mean([data[j]['drafted'] for j in np.where(i)[0]])), 3),
                                        'top64': round(float(r1[i].mean()), 3), 'starter': round(float(start[i].mean()), 3), 'avps': round(float(y['avps'][i].mean()), 3)}
        o['byClass'] = {int(c): round(spear(s[cls == c], y['out'][cls == c]), 4) for c in sorted(set(cls))}
        res[nm] = o
    return res


def paired(a, b):
    """per-class differences of Spearman: mean, t across classes, classes won"""
    d = np.array([b['byClass'][c] - a['byClass'][c] for c in a['byClass']])
    return {'mean': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'won': f'{int((d > 0).sum())}/{len(d)}'}


def boot(data, s0, s1, n=400, seed=3):
    """Spearman gain with a school bootstrap (the folds' unit), for a second read on the t"""
    y = np.array([r['out'] for r in data]); sch = np.array([r['tid'] for r in data]); u = np.unique(sch)
    idx = {t: np.where(sch == t)[0] for t in u}; rng = np.random.default_rng(seed); g = []
    for _ in range(n):
        i = np.concatenate([idx[t] for t in rng.choice(u, len(u))])
        g.append(spear(s1[i], y[i]) - spear(s0[i], y[i]))
    g = np.array(g); return {'gain': round(float(g.mean()), 4), 'se': round(float(g.std()), 4), 't': round(float(g.mean() / g.std()), 2)}


BLOCKS = ['grade', 'hinge', 'rank', 'posrank', 'pos', 'size', 'level', 'elo', 'elo_grade', 'offer_q', 'comp', 'gap', 'offers', 'bmi', 'frame', 'state']
CORE = {'grade'}


def logit_safe(X, y, lam, iters=60):
    """R.logit with the Newton step damped (a rare outcome: 7% drafted, near-separated blocks overshoot)"""
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    Z = (X - mu) / sd; n, p = Z.shape
    A = np.c_[np.ones(n), Z]; b = np.zeros(p + 1); b[0] = math.log(y.mean() / (1 - y.mean()))
    P = np.eye(p + 1) * lam; P[0, 0] = 0
    for _ in range(iters):
        q = 1 / (1 + np.exp(-np.clip(A @ b, -30, 30))); W = q * (1 - q) + 1e-9
        st = np.linalg.solve(A.T @ (A * W[:, None]) + P, A.T @ (q - y) + P @ b)
        b -= np.clip(st, -1, 1)
        if np.abs(st).max() < 1e-7: break
    return b[0] - (b[1:] * mu / sd).sum(), b[1:] / sd


R.logit = logit_safe


def as_hurdle(data):
    for r in data: r['on'] = r['drafted']; r['fv'] = r['rfv'] if r['drafted'] else None; r.pop('_bc', None)


def cvx(data, use, sz, lam=R.LAM):
    p_on, p_fv = R.cv(data, use['on'], use['fv'], sz, lam, lam)
    return p_on * np.maximum(p_fv, R.FLOOR) + (1 - p_on) * R.FLOOR, p_on, p_fv


def select(data, sz):
    """Backward elimination by block on school-held-out CV, P(drafted) on log loss and FV(drafted) on squared error,
    as the live fit's select() (a block stays if dropping it costs with t >= 2)."""
    saved = R.ALL_BLOCKS, R.CORE_BLOCKS
    R.ALL_BLOCKS, R.CORE_BLOCKS = BLOCKS, CORE
    try: use, gains, _ = R.select(data, sz, R.LAM, R.LAM)
    finally: R.ALL_BLOCKS, R.CORE_BLOCKS = saved
    return use, gains


def index_fit(data, use, sz, rows=None):
    """The NFL hurdle's linear parts on (a subset of) the history rows: the recruit-profile index the live fit uses
    (intercepts kept for reference; the live fit puts its own level on the board)."""
    rows = data if rows is None else rows
    for r in rows: r.pop('_bc', None)
    on = [r for r in rows if r['on']]
    X, n_on = R.design(rows, use['on'], sz); a, b = R.logit(X, np.array([r['on'] for r in rows], float), R.LAM)
    X1, n_fv = R.design(on, use['fv'], sz); a1, b1 = R.ridge(X1, np.array([r['fv'] for r in on]), R.LAM)
    return {'on': {'blocks': use['on'], 'names': n_on, 'b0': round(float(a), 5), 'coef': [round(float(x), 5) for x in b]},
            'fv': {'blocks': use['fv'], 'names': n_fv, 'b0': round(float(a1), 4), 'coef': [round(float(x), 4) for x in b1]}}


def stage_b(data, use, sz, live):
    """The shipped live model (board-calibrated on the index), year 3, with the index refit without each held-out
    fold's schools: what it would have said about recruits it never saw, on the NFL outcome."""
    fo = R.folds(data); s = np.zeros(len(data)); keep = R.INDEX
    try:
        for f in range(5):
            R.INDEX = index_fit(data, use, sz, [r for r, x in zip(data, fo) if x != f])
            for i in np.where(fo == f)[0]: s[i] = R.predict(live['model'], {**data[i], 'k': 3, '_dev': 0.0}, live['sizeNorms'])[2]
    finally: R.INDEX = keep
    return s


def stars_nfl(data, scores):
    """ARK stars at the live shares (cut within each class), each model's tiers against what the recruits became"""
    t = {x['stars']: x['share'] for x in json.load(open(BEFORE))['stars']['schemes']['band']['tiers']}
    q = list(np.cumsum([t[1], t[2], t[3], t[4]]))
    cls = np.array([r['year'] for r in data]); out = {}
    for nm, sc in scores.items():
        st = np.zeros(len(data), int)
        for c in set(cls):
            i = cls == c; st[i] = R.cut(sc[i], np.quantile(sc[i], q))
            top = np.argsort(-sc[i])[:R.PLUS_PER]; st[np.where(i)[0][top]] = 6
        rows = []
        for v in (6, 5, 4, 3, 2, 1):
            j = st == v
            rows.append({'stars': v, 'n': int(j.sum()), 'drafted': round(float(np.mean([data[x]['drafted'] for x in np.where(j)[0]])), 3),
                         'top64': round(float(np.mean([bool(data[x]['pick']) and data[x]['pick'] <= 64 for x in np.where(j)[0]])), 3),
                         'starter': round(float(np.mean([data[x]['avps'] >= 3 for x in np.where(j)[0]])), 3), 'avps': round(float(np.mean([data[x]['avps'] for x in np.where(j)[0]])), 3)})
        out[nm] = {'rho': round(spear(st, [r['out'] for r in data]), 4), 'tiers': rows}
    return out


def main():
    data, how, capfit = dataset()
    print('rows', len(data), 'drafted', sum(r['drafted'] for r in data), dict(how), flush=True)
    live = json.load(open(BEFORE)); szl = live['sizeNorms']
    SZ = R.size_norms(data)
    # the board-fit model (before the retarget), scored at year 3 (as the ARK stars are), on recruits it never saw
    R.INDEX = None
    cur = np.array([R.predict(live['model'], {**r, 'k': 3, '_dev': 0.0}, szl)[2] for r in data])
    as_hurdle(data)
    # baselines: ESPN grade alone, the 247 composite alone
    gr = np.array([r['grade'] if r['grade'] >= 60 else 50 for r in data], float)
    comp = np.array([r['comp'] or 0.0 for r in data], float)
    # the live blocks refit on the NFL outcome (no year terms: one horizon)
    lb = {p: [b for b in live['model'][p]['blocks'] if b not in ('year', 'grade_year', 'grade_k4', 'pos_year1', 'dev')] for p in ('on', 'fv')}
    refit, _, _ = cvx(data, lb, SZ)
    sel = os.path.join(R.CACHE, 'retarget_select.json')
    if '--reuse-select' in sys.argv and os.path.exists(sel): use, gains = json.load(open(sel))
    else:
        use, gains = select(data, SZ); json.dump([use, gains], open(sel, 'w'))
    new, p_on, p_fv = cvx(data, use, SZ)
    shipped = json.load(open(R.OUT))
    sb = stage_b(data, use, SZ, shipped) if 'idx' in shipped['model']['fv']['blocks'] else None
    # boardFit: the Oct 14 model (fit on the board grade) at year 3; refit: its blocks on the NFL outcome; nfl: blocks
    # selected on the NFL outcome; shipped: the live model (the nfl index on the board's scale) at year 3
    sc = {'boardFit': cur, 'espn': gr, 'comp247': comp, 'refit': refit, 'nfl': new}
    if sb is not None: sc['shipped'] = sb
    ev = evaluate(data, sc)
    for k, v in ev.items(): print(k.ljust(26), {a: b for a, b in v.items() if a != 'byClass'})
    vs = {k: {'byClass': paired(ev['boardFit'], ev[k]), 'boot': boot(data, cur, sc[k])} for k in sc if k != 'boardFit'}
    print(json.dumps(vs, indent=1))
    stars = stars_nfl(data, {'boardFit': cur, 'shipped': sb}) if sb is not None else None
    if stars: print(json.dumps(stars, indent=1))
    out = {'classes': [CLASSES[0], CLASSES[-1]], 'n': len(data), 'drafted': int(sum(r['drafted'] for r in data)), 'link': dict(how), 'capital': capfit,
           'use': use, 'gains': gains, 'eval': ev, 'vsLive': vs, 'index': index_fit(data, use, SZ), 'sizeNorms': SZ, 'starsNFL': stars}
    json.dump(out, open(OUT, 'w'), indent=1)
    return data, use, SZ


if __name__ == '__main__':
    main()
