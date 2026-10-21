#!/usr/bin/env python3
"""Fit the College Basketball ARKBOARD FV model (data/cbb_fit.json) on past preseason boards.

    python3 scripts/cbb_link.py   # once: link college careers to NBA careers and recruiting grades
    python3 scripts/cbb_fit.py    # driver test, fit, FV scale, backtests

A preseason board for season s holds everyone who played D-I that season, graded with what was known before it
tipped off: past college seasons (Barttorvik) for returners, recruiting grades (On3 industry, 247 composite,
Barttorvik's recruit score) for everyone, height, and age for returners (newcomers have no date of birth in our live
sources, so the newcomer model doesn't use it either).

Outcome: the realized FV of the career on peak XPM (50/50 BPM and DPM, best three NBA seasons; see xpm_scale: each FV
starts where as many careers reached as reached the matching cbb_link.py TIERS role; 20 = non-NBA). Training boards are
2009-2016, whose players all finished college by 2020 and have six or more NBA seasons to show their role.
Model, two parts (a hurdle): P(NBA) = P(realized FV >= 30), logistic; FV if NBA, linear. E[FV] = 20 + P x (FV if
NBA - 20). Newcomers and returners are separate fits on their own drivers; their E[FV] sit on one scale.

Drivers: each candidate is kept only if it improves out-of-sample fit (5 folds that hold out whole players, so a
player's later boards never grade his earlier ones): backward elimination on OOS error of E[FV]. Weights are ridge
fits, penalty picked by the same CV. Forward test: the fit on 2009-2016 boards grades the 2017-2026 boards, scored
against NBA draft slot (no NBA careers yet to score).

FV scale (scarcity): realized FV counts per 2009-2016 preseason board (how many players on a board went on to
each FV) set how many players on today's board get each FV, in steps of 1, after a shrink (exp_rank, tune_shrink):
a forecast misses, so a board rank maps to the outcome rank it predicts, set so each grade is the mean outcome of the
players graded there (Noah, Oct 21 2026: the headline is the mean, as on the football board; it was the 75th
percentile, r .92). The ranking is E[FV].
"""
import json, math, os, sys, hashlib
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
from cbb_link import TIERS

TRAIN = range(2009, 2017)
TEST = range(2017, 2027)
FOLDS = 5
MIN_FOLDS = 4   # a kept driver must lower OOS error in at least 4 of the 5 folds
FLOOR = 20
OUT = os.path.join(D.ROOT, 'data', 'cbb_fit.json')
PAST_N = 300     # past-season boards keep their top 300

POWER = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}
ROLES = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'W', 'Wing F': 'W', 'Stretch 4': 'B', 'PF/C': 'B', 'C': 'B'}
POS3 = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}
CLS = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4}


def shrink(x, n, prior, k):
    if x is None or n is None: return prior
    return (x * n + prior * k) / (n + k)


def rec_feats(c, s_year):
    """recruiting grades known before season s (the HS class precedes the first D-I season). Barttorvik's recruit
    score is read only from earlier seasons: the live board has no Barttorvik line for a newcomer."""
    g = c.get('rec') or {}
    bt = next((r['rec'] for r in c['seasons'] if r['rec'] and r['year'] < s_year), None)
    on3, r247 = g.get('on3'), g.get('r247')
    btrk = round((100 - bt) / 0.2) + 1 if bt else None
    rk = g.get('on3rk') or g.get('rk247') or btrk
    # log rank, averaged over the sources that rank him (cbb/backtest: the log of the rank beats every rating; ratings
    # squeeze the top 50 together)
    lr = [-math.log(min(x, 500)) for x in (g.get('on3rk'), g.get('rk247'), btrk) if x]
    return {'on3': on3, 'r247': r247 * 100 if r247 else None, 'btrec': bt, 'rank': rk,
            'rg_lrk': sum(lr) / len(lr) if lr else -math.log(600), 'unranked2': 0.0 if lr else 1.0}


def season_line(r):
    mpt = (r['mp'] or 0) * (r['gp'] or 0)
    return {
        'mpt': mpt, 'min_per': r['min_per'] or 0,
        'bpm': shrink(r['bpm'], mpt, -4.0, 300), 'obpm': shrink(r['obpm'], mpt, -3.0, 300), 'dbpm': shrink(r['dbpm'], mpt, -1.0, 300),
        'usg': shrink(r['usg'], mpt, 16, 300), 'ast': shrink(r['ast'], mpt, 10, 300), 'to': shrink(r['to'], mpt, 20, 300),
        'stl': shrink(r['stl'], mpt, 1.4, 400), 'blk': shrink(r['blk'], mpt, 1.5, 400), 'orb': shrink(r['orb'], mpt, 5, 300),
        'drb': shrink(r['drb'], mpt, 13, 300), 'ft': shrink(r['ft'], r['fta'], 0.69, 40), 'tp': shrink(r['tp'], r['tpa'], 0.32, 60),
        'tpa100': shrink(r['tpa100'], mpt, 4, 300), 'ftr': shrink(r['ftr'], mpt, 30, 300),
        'rim': shrink(r['rim'], r['rima'], 0.58, 30), 'dunk': (r['dunkm'] or 0) / max(1, mpt) * 100,
        'ortg': shrink(r['ortg'], mpt, 95, 300), 'porpag': shrink(r['porpag'], mpt, 0, 300), 'dporpag': shrink(r['dporpag'], mpt, 0, 300),
        'power': 1.0 if r['conf'] in POWER else 0.0,
        'prpg': shrink(r['porpag'], mpt, 0, 300) * (r['min_per'] or 0) / 100,
        'dprpg': shrink(r['dporpag'], mpt, 0, 300) * (r['min_per'] or 0) / 100,
        'dunk40': math.log1p((r['dunka'] or 0) / max(40, mpt) * 40) if r['year'] >= 2010 else None,
    }


def features(c, i):
    """the preseason feature dict for career c's i-th season (its board season)."""
    s = c['seasons'][i]
    prev = c['seasons'][:i]
    f = {'ht': s['hti'] or 77.0, 'yr': CLS.get(s['yr'], 1)}
    f.update(rec_feats(c, s['year']))
    rk = f['rank']
    f['lrank'] = -math.log(min(rk, 500)) if rk else -math.log(600)
    f['rated'] = 1.0 if rk else 0.0
    f['grade'] = (f['on3'] if f['on3'] else f['r247'] if f['r247'] else 75.0)
    f['top'] = max(0.0, f['lrank'] + math.log(25))   # hinge: inside the top 25
    f['top5'] = max(0.0, f['lrank'] + math.log(5))
    f['newcomer'] = not prev
    if prev:
        a = D.age_on(c['dob'], s['year'] - 1, 11, 1)
        f['age'] = a if a else 18.6 + len(prev)
        f['age_known'] = 1.0 if a else 0.0
        L = season_line(prev[-1])
        for k, v in L.items(): f[k] = v
        # weighted career BPM, 5/4/3 by season with minutes
        w = [5, 4, 3]
        num = den = 0
        for j, r in enumerate(reversed(prev[-3:])):
            m = (r['mp'] or 0) * (r['gp'] or 0)
            if r['bpm'] is not None: num += w[j] * m * r['bpm']; den += w[j] * m
        f['bpm3'] = shrink(num / den if den else None, den / 5, -4.0, 300)
        f['trend'] = f['bpm'] - season_line(prev[-2])['bpm'] if len(prev) >= 2 else 0.0
        f['nprev'] = len(prev)
        f['young'] = max(0.0, 20.5 - f['age'])
        f['bpm_x_young'] = f['bpm'] * f['young']
        f['ht_g'] = f['ht'] - {'G': 75, 'W': 78, 'B': 81}.get(ROLES.get(prev[-1]['role'], 'W'), 78)
        f['guard'] = 1.0 if ROLES.get(prev[-1]['role']) == 'G' else 0.0
        f['big'] = 1.0 if ROLES.get(prev[-1]['role']) == 'B' else 0.0
        f['transfer'] = 1.0 if prev[-1]['team'] != s['team'] else 0.0
        # Barttorvik BPM by role (500+ minute seasons, 2008-26): guards +0.2 (O +0.8, D -0.7), wings +0.5, bigs +1.7
        # (O 0, D +1.6): a big's rebounds and blocks lift his BPM, so production is also tested against his role
        g = ROLES.get(prev[-1]['role'], 'W')
        f['bpm_rel'] = f['bpm'] - {'G': 0.2, 'W': 0.5, 'B': 1.7}[g]
        f['obpm_rel'] = f['obpm'] - {'G': 0.8, 'W': 0.45, 'B': 0.0}[g]
        f['dbpm_rel'] = f['dbpm'] - {'G': -0.7, 'W': 0.0, 'B': 1.6}[g]
        f['bpm_x_age'] = f['bpm_rel'] * (f['age'] - 20.5)
        f['age2'] = (f['age'] - 20.5) ** 2
        # dunk attempts per 40 against his family's norm (2010 on: an athletic proxy for players who never test)
        f['dunk_rel'] = f['dunk40'] - {'G': 0.075, 'W': 0.265, 'B': 0.55}[g] if f['dunk40'] is not None else None
    return f


NEW_CANDS = ['lrank', 'rg_lrk', 'unranked2', 'top', 'top5', 'rated', 'grade', 'on3', 'r247', 'ht', 'yr']
# dunk rate is out: it scrapes past 4 of 5 folds here (+0.1%) but the full-column backtest (cbb/backtest) finds it
# hurting in every form (t -3 to -5); two harnesses that disagree are not evidence for it
RET_CANDS = ['lrank', 'rg_lrk', 'unranked2', 'prpg', 'dprpg', 'age2', 'top', 'top5', 'grade', 'on3', 'r247', 'btrec', 'bpm', 'bpm3', 'obpm', 'dbpm', 'bpm_rel', 'obpm_rel', 'dbpm_rel', 'bpm_x_age', 'trend', 'min_per', 'usg', 'ast', 'to', 'stl', 'blk',
             'orb', 'drb', 'ft', 'tp', 'tpa100', 'ftr', 'rim', 'ortg', 'porpag', 'dporpag', 'power', 'age', 'young',
             'bpm_x_young', 'ht', 'ht_g', 'guard', 'big', 'yr', 'nprev', 'transfer']


def fold_of(pid): return int(hashlib.md5(str(pid).encode()).hexdigest(), 16) % FOLDS


def matrix(rows, cols):
    X = np.array([[(r['f'].get(k) if r['f'].get(k) is not None else np.nan) for k in cols] for r in rows], float)
    return X


class Std:
    def __init__(self, X):
        ok = ~np.isnan(X)
        cnt = np.maximum(ok.sum(0), 1)
        self.m = np.where(ok, X, 0).sum(0) / cnt
        self.s = np.sqrt(np.where(ok, (X - self.m) ** 2, 0).sum(0) / cnt)
        # a sparse hinge (top-25 recruit, mostly 0) is scaled by its spread where it's on, with 0 kept at 0: scaled by
        # the whole sample's SD, the No. 1 and No. 20 recruits would both sit past the 4-SD cap
        for j in range(X.shape[1]):
            col = X[ok[:, j], j]
            nz = col[col != 0]
            if len(col) and len(nz) < 0.2 * len(col) and len(nz) > 10:
                self.m[j] = 0.0; self.s[j] = float(np.sqrt((nz ** 2).mean()))
        self.s[~(self.s > 0)] = 1
    def __call__(self, X):
        Z = (X - self.m) / self.s
        # a missing grade sits at the mean; z capped at 4 SD so a sparse hinge (top-5 recruit: SD .04) can't extrapolate
        return np.clip(np.nan_to_num(Z), -4, 4)


def logit_fit(Z, y, lam):
    n, k = Z.shape
    A = np.hstack([np.ones((n, 1)), Z]); w = np.zeros(k + 1)
    w[0] = math.log(max(y.mean(), 1e-4) / max(1 - y.mean(), 1e-4))
    P = np.eye(k + 1) * lam; P[0, 0] = 1e-3
    for _ in range(60):
        p = 1 / (1 + np.exp(-(A @ w)))
        g = A.T @ (p - y) + P @ w
        H = (A * np.maximum(p * (1 - p), 1e-9)[:, None]).T @ A + P
        step = np.linalg.solve(H, g)
        step *= min(1.0, 2.0 / max(1e-12, np.abs(step).max()))   # damped: no step moves a weight by more than 2
        w -= step
        if np.abs(step).max() < 1e-7: break
    return w


def ridge_fit(Z, y, lam):
    n, k = Z.shape
    A = np.hstack([np.ones((n, 1)), Z])
    P = np.eye(k + 1) * lam; P[0, 0] = 0
    return np.linalg.solve(A.T @ A + P, A.T @ y)


LADDER = [30, 40, 50, 60]   # rungs: P(FV >= t | FV >= the rung below), a continuation-ratio ladder
TOP_MEAN = 67.0             # mean realized FV of the 60+ careers (2008-19 college exits; set in main)


def expected(P):
    """E[FV] from the cumulative rung probabilities: 20 + 10 x P(30+) + 10 x P(40+) + 10 x P(50+) + (TOP_MEAN - 50) x P(60+)."""
    return FLOOR + 10 * P[:, 0] + 10 * P[:, 1] + 10 * P[:, 2] + (TOP_MEAN - 50) * P[:, 3]


def predict(model, X):
    """P(NBA) = P(FV >= 30), the cumulative rung probabilities, and E[FV]."""
    Z = model['std'](X[:, model['idx']])
    A = np.hstack([np.ones((len(Z), 1)), Z])
    C = np.column_stack([1 / (1 + np.exp(-np.clip(A @ w, -30, 30))) for w in model['w']])
    P = np.cumprod(C, axis=1)
    return P[:, 0], P, expected(P)


def fit(rows, X, idx, lam):
    y = np.array([r['y'] for r in rows], float)
    std = Std(X[:, idx]); Z = std(X[:, idx])
    ws = []
    lams = lam if isinstance(lam, (list, tuple)) else [lam] * len(LADDER)
    for j, t in enumerate(LADDER):
        on = y >= (LADDER[j - 1] if j else -1)
        ws.append(logit_fit(Z[on], (y[on] >= t).astype(float), lams[j] * max(1.0, on.sum() / 1000)))   # small upper rungs keep a full penalty
    return {'std': std, 'idx': idx, 'w': ws}


def rung_dev(P, y):
    out = []
    for j, t in enumerate(LADDER):
        on = y >= (LADDER[j - 1] if j else -1)
        prev = P[on, j - 1] if j else np.ones(on.sum())
        c = np.clip(P[on, j] / np.maximum(prev, 1e-9), 1e-6, 1 - 1e-6)
        o = (y[on] >= t).astype(float); m = np.clip(o.mean(), 1e-6, 1 - 1e-6)
        out.append(-(o * np.log(c) + (1 - o) * np.log(1 - c)).sum() / -(o * np.log(m) + (1 - o) * np.log(1 - m)).sum())
    return out


def deviance(P, y):
    """mean over the rungs of OOS deviance / null deviance, each rung on the players who reached the rung below: who
    becomes a starter or an All-Star weighs as much as who reaches the NBA (an error on E[FV] alone is ruled by the
    many who never do)."""
    return float(np.mean(rung_dev(P, y)))


def cv_error(rows, X, idx, lam=1.0):
    y = np.array([r['y'] for r in rows], float)
    folds = np.array([fold_of(r['pid']) for r in rows])
    P = np.zeros((len(rows), len(LADDER))); errs = []
    for k in range(FOLDS):
        tr, te = folds != k, folds == k
        m = fit([r for r, t in zip(rows, tr) if t], X[tr], idx, lam)
        P[te] = predict(m, X[te])[1]
        errs.append(deviance(P[te], y[te]))
    return deviance(P, y), np.array(errs), expected(P)


_POOL = {}


def _drop_job(args):
    j, idx, lam = args
    rows, X = _POOL['rows'], _POOL['X']
    e, fe, _ = cv_error(rows, X, [i for i in idx if i != j], lam)
    return j, e, fe


def drop_one(rows, X, idx, lam):
    """OOS deviance with each driver left out, in parallel: [(rise over the full set, j, per-fold deviance)]."""
    import multiprocessing as mp
    base, _, _ = cv_error(rows, X, idx, lam)
    _POOL['rows'], _POOL['X'] = rows, X
    with mp.get_context('fork').Pool(min(4, os.cpu_count() or 1)) as pool:
        res = pool.map(_drop_job, [(j, idx, lam) for j in idx])
    return [(e - base, j, fe) for j, e, fe in res]


def select(rows, cands, label):
    X = matrix(rows, cands)
    idx = list(range(len(cands)))
    # penalty per rung (a rung's deviance depends on its own weights only): the CV best of the grid; a rung the
    # drivers can't call goes to a near-flat fit at the top of the grid
    y = np.array([r['y'] for r in rows], float)
    folds = np.array([fold_of(r['pid']) for r in rows])
    grid = (1, 3, 10, 30, 100, 300, 1000)
    devs = []
    for g in grid:
        P = np.zeros((len(rows), len(LADDER)))
        for k in range(FOLDS):
            tr, te = folds != k, folds == k
            P[te] = predict(fit([r for r, t in zip(rows, tr) if t], X[tr], idx, g), X[te])[1]
        devs.append(rung_dev(P, y))
    lam = [grid[int(np.argmin([d[j] for d in devs]))] for j in range(len(LADDER))]
    print(f'{label}: penalty per rung {lam}; OOS deviance/null per rung {[round(min(d[j] for d in devs), 3) for j in range(len(LADDER))]}')
    err, ferr, _ = cv_error(rows, X, idx, lam)
    log = []
    # bulk pass: drop every driver whose removal doesn't raise OOS deviance, re-test, until none
    while len(idx) > 1:
        trial = drop_one(rows, X, idx, lam)
        bad = sorted((d, j) for d, j, fe in trial if d <= 0)
        if not bad: break
        # two near-copies (log rank and the top-25 hinge, BPM and role BPM) each look useless while the other is in:
        # drop at most one of any correlated pair per pass, so the other is re-tested alone
        C = np.corrcoef(np.nan_to_num(X[:, idx] - np.nanmean(X[:, idx], 0)), rowvar=False)
        pos = {j: k for k, j in enumerate(idx)}
        pick = []
        for d, j in bad:
            if all(abs(C[pos[j], pos[q]]) < 0.6 for _, q in pick): pick.append((d, j))
        bad = pick
        for d, j in bad: log.append({'drop': cands[j], 'oos_change': round(-d * 100, 4)})
        idx = [i for i in idx if i not in {j for _, j in bad}]
        err, ferr, _ = cv_error(rows, X, idx, lam)
    # evidence for each kept driver: OOS deviance when it alone is removed, and in how many folds that hurts. A driver
    # that helps in fewer than MIN_FOLDS of the folds is noise the ridge happened to like: drop the weakest, re-test
    while True:
        kept = [{'driver': cands[j], 'j': j, 'oos_gain': round(d * 100, 3), 'folds_helped': int((fe > ferr).sum())} for d, j, fe in drop_one(rows, X, idx, lam)]
        weak = [k for k in kept if k['folds_helped'] < MIN_FOLDS or k['oos_gain'] <= 0]
        if not weak or len(idx) <= 1: break
        w = min(weak, key=lambda k: (k['folds_helped'], k['oos_gain']))
        log.append({'drop': w['driver'], 'oos_change': -w['oos_gain'], 'folds_helped': w['folds_helped']})
        idx = [i for i in idx if i != w['j']]
        err, ferr, _ = cv_error(rows, X, idx, lam)
    for k in kept: k.pop('j')
    kept.sort(key=lambda k: -k['oos_gain'])
    r2 = 1 - err
    print(f'{label}: {len(rows)} board rows, OOS pseudo-R2 (mean over rungs) {r2:.4f}, lam {lam}; kept {[k["driver"] for k in kept]}')
    for k in kept: print(f'   {k["driver"]:12s} OOS +{k["oos_gain"]:.3f}%  folds {k["folds_helped"]}/{FOLDS}')
    return {'cands': cands, 'kept': [cands[i] for i in idx], 'idx': idx, 'lam': lam, 'r2': r2, 'evidence': kept, 'dropped': log}


def auc(score, y):
    o = np.argsort(score); r = np.empty(len(score)); r[o] = np.arange(1, len(score) + 1)
    pos = y.astype(bool); n1 = pos.sum(); n0 = len(y) - n1
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else None


def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def model_json(sel, m):
    return {'kept': sel['kept'], 'mean': [round(float(x), 6) for x in m['std'].m], 'sd': [round(float(x), 6) for x in m['std'].s],
            'ladder': LADDER, 'topMean': TOP_MEAN, 'w': [[round(float(x), 6) for x in w] for w in m['w']],
            'r2': round(sel['r2'], 4), 'lam': sel['lam'], 'evidence': sel['evidence'], 'dropped': sel['dropped']}


def xbpm_fit(rows, cands):
    """projected college BPM this season: ridge on the same inputs, rows weighted by minutes (capped at 600)."""
    rr = [r for r in rows if r['bpm_now'] is not None and r['mpt_now'] >= 100]
    X = matrix(rr, cands); std = Std(X); Z = std(X)
    y = np.array([r['bpm_now'] for r in rr]); w = np.array([min(600, r['mpt_now']) for r in rr]) / 600
    A = np.hstack([np.ones((len(Z), 1)), Z]); P = np.eye(A.shape[1]) * 50; P[0, 0] = 0
    b = np.linalg.solve((A * w[:, None]).T @ A + P, (A * w[:, None]).T @ y)
    pred = A @ b
    r = float(np.corrcoef(pred, y)[0, 1])
    return {'cols': cands, 'mean': [round(float(x), 6) for x in std.m], 'sd': [round(float(x), 6) for x in std.s],
            'w': [round(float(x), 6) for x in b], 'r': round(r, 3)}


def scarcity(rows, years):
    """how many players on an average preseason board went on to each realized FV (or better)."""
    out = {}
    for fv, _, _ in TIERS:
        if fv == FLOOR: continue
        out[fv] = round(float(np.mean([sum(1 for r in rows if r['year'] == y and r['y'] >= fv) for y in years])), 2)
    return out


VALIDITY = 1.0   # set in main: how far a board rank is from the outcome rank it predicts (see validity)


def rank_normal(v):
    """normal scores of a vector's ranks (ties share their mean rank)."""
    v = np.asarray(v, float); o = np.argsort(v, kind='stable'); r = np.empty(len(v)); r[o] = np.arange(1, len(v) + 1)
    for x in np.unique(v):
        m = v == x
        if m.sum() > 1: r[m] = r[m].mean()
    nd = __import__('statistics').NormalDist()
    return np.array([nd.inv_cdf(min(max(q, 1e-9), 1 - 1e-9)) for q in r / (len(v) + 1)])


def validity(rows):
    """latent validity of the out-of-fold score: the polyserial correlation of its normal score (within each board)
    with the outcome tier (the ordinal 20 / 30 / ... / 80 ladder, a latent normal cut at the tiers' shares). Plain
    correlation would be pulled down by the 95% of players tied at 20."""
    from statistics import NormalDist
    nd = NormalDist()
    x, t = [], []
    tiers = sorted(fv for fv, _, _ in TIERS)
    for yr in TRAIN:
        ix = [r for r in rows if r['year'] == yr]
        x += list(rank_normal([r['e'] for r in ix])); t += [sum(1 for c in tiers if r['y'] >= c) - 1 for r in ix]
    x, t = np.array(x), np.array(t, float)
    r = np.corrcoef(x, t)[0, 1]
    cum = np.cumsum([np.mean(t == k) for k in range(len(tiers))])[:-1]   # thresholds between adjacent tiers
    dens = sum(nd.pdf(nd.inv_cdf(min(max(c, 1e-9), 1 - 1e-9))) for c in cum)   # unit steps between tier indices
    return round(float(min(0.99, r * t.std() / dens)), 3)


def tune_shrink(rows, cuts):
    """the shrink r for exp_rank, picked on the out-of-fold training boards: with r = 1 the board hands out exactly
    as many grades as careers that reach them, but a forecast misses, so its top grades overshoot what those players
    became. r is set so that inside each 5-point band from 30 up, the graded FV matches the mean of what the players
    graded there went on to (weighted by sqrt players). Oct 21 2026: r .81 (the 75th percentile target gave .92)."""
    global VALIDITY
    log = []
    for r in np.round(np.arange(0.60, 1.001, 0.01), 2):
        VALIDITY = float(r)
        err = wsum = 0.0
        bands = defaultdict(lambda: ([], []))
        for yr in TRAIN:
            ix = [x for x in rows if x['year'] == yr]
            g, _, gx = grade(np.array([x['e'] for x in ix]), cuts)
            for x, a in zip(ix, gx):
                if a >= 30: bands[tier_of(a)][0].append(a); bands[tier_of(a)][1].append(x['y'])
        for t, (ga, ya) in bands.items():
            if len(ga) < 8: continue
            w = math.sqrt(len(ga)); err += w * (np.mean(ya) - np.mean(ga)) ** 2; wsum += w
        log.append((float(r), round(math.sqrt(err / wsum), 2)))
    best = min(log, key=lambda t: t[1])[0]
    VALIDITY = best
    return best, log


def exp_rank(scores):
    """the scarcity rank a board rank predicts, as football does it: the score as a normal score z within the board,
    expected talent r x z (r = the board's out-of-sample validity), and the rank of that talent on the board.
    A rank-1 score on a 5,000-player board (z 3.5) with r .85 is expected talent 3.0: about the 7th best outcome."""
    from statistics import NormalDist
    nd = NormalDist(); n = len(scores)
    z = rank_normal(scores)
    return np.array([max(0.5, n * (1 - nd.cdf(VALIDITY * x))) for x in z])


def grade(scores, cuts):
    """FV from rank on the board, in steps of 1: the top cuts[t] players are t or better (scarcity), and inside a band
    the FV runs from t to the next cut by log rank. 80 is the top of the scale. Below the 30 cut the FV runs 29 to 20
    by log rank down the rest of the board. Returns (FV, plus, FV with decimals); plus is always False (kept for older readers)."""
    order = np.argsort(-scores, kind='stable')   # ties keep board order (the board sorts the same way)
    fvx = np.full(len(scores), float(FLOOR))
    tiers = sorted(cuts.items(), key=lambda t: -t[0])
    n30 = cuts.get(30, 0)
    er = exp_rank(scores)
    for k, i in enumerate(order, 1):
        rank = max(float(er[i]), 0.5) if VALIDITY < 1 else k
        prev_n, prev_t = 0.0, 85
        for t, n in tiers:
            if rank <= max(n, 0.5) + 1e-9:
                lo, hi = max(prev_n, 0.5), max(n, 0.5)
                top = 80.0 if t == 80 else prev_t
                x = t + (top - t) * (math.log(hi) - math.log(max(rank, lo))) / max(1e-9, math.log(hi) - math.log(lo)) if hi > lo else t
                fvx[i] = min(80.0, x, prev_t - 0.01) if t < 80 else 80.0
                break
            prev_n, prev_t = n, t
        else:
            # below the 30 cut: 29.99 down to 20 by log rank over the rest of the board
            lo, hi = max(n30, 1.0), float(len(order))
            fvx[i] = FLOOR + 9.99 * (math.log(hi) - math.log(rank)) / max(1e-9, math.log(hi) - math.log(lo))
    fv = np.floor(fvx + 1e-9)
    return fv, np.zeros(len(scores), bool), fvx


SCALE_CLASSES = range(2008, 2017)   # careers whose college ended 2008-2016: ten-plus NBA seasons to show a peak


def xpm_scale(careers):
    """the 20-80 scale on NBA impact: FV t starts at the peak XPM that as many careers reached as reached role tier t
    (cbb_link TIERS: as many 80s as 3x All-NBA careers, as many 45s as two-year starters). The scarcity of each grade
    stays the role ladder's, the order inside it is XPM. Between cut points the FV runs linear in XPM; 20 = non-NBA."""
    cs = [c for c in careers if c['last'] in SCALE_CLASSES]
    nba = sorted((c['nba']['peakXpm'] for c in cs if c['nba']['games'] >= 1 and c['nba']['peakXpm'] is not None), reverse=True)
    thr = {}
    for fv, _, _ in TIERS:
        if fv == FLOOR: continue
        n = sum(1 for c in cs if c['nba']['fv'] >= fv)
        thr[fv] = nba[min(n, len(nba)) - 1]
    return thr


def xpm_fv(c, thr):
    if c['nba']['games'] < 1 or c['nba']['peakXpm'] is None: return float(FLOOR)
    ts = sorted(thr)
    return round(float(np.interp(c['nba']['peakXpm'], [thr[t] for t in ts], ts)), 2)


def tier_of(y):
    return max([t for t, _, _ in TIERS if y >= t] or [FLOOR])


def fv_table(careers, cuts, thr):
    """the measured FV scale: each FV band's peak XPM range, the NBA roles inside it, peak BPM / DPM, counts, draft slot."""
    classes = SCALE_CLASSES
    old = {80: 7.2, 70: 5.6, 60: 2.9, 55: 1.8, 50: 1.2, 45: 0.9}
    ts = sorted(thr)
    out = []
    for fv, label, _ in TIERS:
        cs = [c for c in careers if c['last'] in classes and tier_of(c['nba']['fvx']) == fv]
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
        vals = lambda k: [c['nba'][k] for c in cs if c['nba'].get(k) is not None]
        picks = [c['nba']['pick'] for c in cs if c['nba']['pick']]
        roles = defaultdict(int)
        for c in cs: roles[c['nba']['role']] += 1
        hi = next((thr[t] for t in ts if t > fv), None)
        out.append({'fv': fv, 'role': max(roles, key=roles.get) if roles else label, 'roleShare': round(max(roles.values()) / len(cs), 2) if cs else None,
                    'xpmLo': thr.get(fv), 'xpmHi': hi, 'n': len(cs), 'perClass': round(len(cs) / len(classes), 2), 'perBoard': cuts.get(fv),
                    'peakXpm': med(vals('peakXpm')), 'peakBpm': med(vals('peak')), 'peakDpm': med(vals('peakDpm')), 'oldDpm': old.get(fv),
                    'medPick': med(picks), 'drafted': round(len(picks) / len(cs), 3) if cs else None})
    return out


# ---------------------------------------------------------------- the board stage: draft-board consensus
BOARDS = os.environ.get('CBB_BOARDS', '/mnt/project-files/cbb/boards')
CONS_FILL = -math.log(150)   # -ln rank of a player on neither final board


def june_ranks():
    """-ln June consensus rank by (draft year, name): the mean over ESPN's and NBADraft.net's final boards, a board
    that leaves him off counting him at 1.5 x its depth (as the international model reads them)."""
    import csv
    rk = defaultdict(dict)
    for src, f in (('espn', 'espn.csv'), ('ndn', 'nbadraftnet.csv')):
        with open(os.path.join(BOARDS, f), newline='', encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                if r['rank']: rk[(int(r['draft_year']), D.norm(r['name']))][src] = int(r['rank'])
    depth = defaultdict(dict)
    for (y, k), v in rk.items():
        for s, x in v.items(): depth[y][s] = max(depth[y].get(s, 0), x)
    return {(y, k): float(np.mean([-math.log(v.get(s, 1.5 * depth[y].get(s, 100))) for s in ('espn', 'ndn')])) for (y, k), v in rk.items()}


def preseason_att():
    """the June rank a preseason board rank predicts: -ln(ESPN final rank) on -ln(No Ceilings' first board rank),
    2022-26 classes (off the final board = 1.5 x its depth): intercept, slope, residual spread."""
    import csv
    nc = defaultdict(lambda: defaultdict(dict)); es = defaultdict(dict)
    with open(os.path.join(BOARDS, 'noceilings.csv'), newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh): nc[int(r['draft_year'])][r['board_date']][D.norm(r['name'])] = int(r['rank'])
    with open(os.path.join(BOARDS, 'espn.csv'), newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r['rank']: es[int(r['draft_year'])][D.norm(r['name'])] = int(r['rank'])
    X, Y = [], []
    for y in sorted(nc):
        if not es.get(y): continue
        b = nc[y][min(nc[y])]; dep = max(es[y].values())
        for k, r in b.items(): X.append(-math.log(r)); Y.append(-math.log(es[y].get(k, 1.5 * dep)))
    X, Y = np.array(X), np.array(Y)
    b, a = np.polyfit(X, Y, 1)
    return {'a': round(float(a), 4), 'b': round(float(b), 4), 'sd': round(float(np.std(Y - a - b * X, ddof=2)), 4), 'n': len(X),
            'r': round(float(np.corrcoef(X, Y)[0, 1]), 3)}


def board_stage(train, ranks):
    """a second ladder on two inputs, the model's out-of-fold E[FV] and where the June boards had him (-ln consensus
    rank, CONS_FILL if on neither), fit on the 2009-16 boards; kept only if it lowers out-of-sample deviance in 4 of 5
    folds. For the live board the June rank is unknown: a player on the preseason boards gets the June rank his
    preseason rank predicts (preseason_att), one on none gets the chance of making a June board and the rank he would
    get there, each from his E[FV] (fit on the same rows), all averaged over their spread."""
    rr = []
    for r in train:
        v = ranks.get((r['year'] + 0, D.norm(r['name'])))
        rr.append({'pid': r['pid'], 'y': r['y'], 'f': {'e': r['e'], 'lr': v if v is not None else CONS_FILL, 'on': v is not None}})
    y = np.array([r['y'] for r in rr], float)
    folds = np.array([fold_of(r['pid']) for r in rr])
    res = {}
    for name, cols in (('model', ['e']), ('model + boards', ['e', 'lr'])):
        X = matrix(rr, cols); idx = list(range(len(cols)))
        devs = []
        for g in (1, 3, 10, 30, 100, 300):
            P = np.zeros((len(rr), len(LADDER)))
            for k in range(FOLDS):
                tr, te = folds != k, folds == k
                P[te] = predict(fit([r for r, t in zip(rr, tr) if t], X[tr], idx, g), X[te])[1]
            devs.append(rung_dev(P, y))
        lam = [(1, 3, 10, 30, 100, 300)[int(np.argmin([d[j] for d in devs]))] for j in range(len(LADDER))]
        err, ferr, e = cv_error(rr, X, idx, lam)
        res[name] = {'r2': round(1 - err, 4), 'folds': ferr, 'lam': lam, 'auc_nba': round(auc(e, y >= 30), 3), 'auc_starter': round(auc(e, y >= 45), 3)}
    helped = int((res['model + boards']['folds'] < res['model']['folds']).sum())
    keep = helped >= MIN_FOLDS and res['model + boards']['r2'] > res['model']['r2']
    X = matrix(rr, ['e', 'lr'])
    m = fit(rr, X, [0, 1], res['model + boards']['lam'])
    # the chance of a June board and the rank there, from E[FV]
    e = np.array([r['f']['e'] for r in rr]); on = np.array([r['f']['on'] for r in rr], float); lr = np.array([r['f']['lr'] for r in rr])
    em, es = float(e.mean()), float(e.std())
    A = np.column_stack([np.ones(len(e)), (e - em) / es]); w = np.array([math.log(on.mean() / (1 - on.mean())), 0.0])
    for _ in range(100):
        p = 1 / (1 + np.exp(-np.clip(A @ w, -30, 30)))
        step = np.linalg.solve((A * np.maximum(p * (1 - p), 1e-9)[:, None]).T @ A + 1e-6 * np.eye(2), A.T @ (p - on))
        w -= step * min(1.0, 1.0 / max(1e-12, np.abs(step).max()))
    w = np.array([w[0] - w[1] * em / es, w[1] / es])      # back on the E[FV] scale
    d = np.polyfit(e[on == 1], lr[on == 1], 1)
    sd = float(np.std(lr[on == 1] - np.polyval(d, e[on == 1]), ddof=2))
    out = {'keep': bool(keep), 'foldsHelped': helped, 'model': {k: v for k, v in res['model'].items() if k != 'folds'},
           'withBoards': {k: v for k, v in res['model + boards'].items() if k != 'folds'}, 'rows': len(rr), 'onBoards': int(on.sum()),
           'mean': [round(float(x), 6) for x in m['std'].m], 'sd': [round(float(x), 6) for x in m['std'].s],
           'w': [[round(float(x), 6) for x in ww] for ww in m['w']], 'topMean': TOP_MEAN, 'fill': CONS_FILL,
           'onLogit': [round(float(x), 6) for x in w], 'onRank': [round(float(x), 6) for x in d], 'onSd': round(sd, 4), 'att': preseason_att()}
    print(f"board stage: OOS pseudo-R2 {res['model']['r2']} -> {res['model + boards']['r2']}, better in {helped}/{FOLDS} folds; "
          f"AUC NBA {res['model']['auc_nba']} -> {res['model + boards']['auc_nba']}; kept {keep}")
    return out


_GH = np.polynomial.hermite_e.hermegauss(9)


def board_e(e, lr_pre, C):
    """E[FV] and P(NBA) after the board stage, for a player whose model E[FV] is e and whose preseason consensus is
    -ln rank lr_pre (None when no board lists him). Returns (e, p) unchanged when the stage wasn't kept."""
    if not C or not C.get('keep'): return e, None
    mu, sd, W = np.array(C['mean']), np.array(C['sd']), [np.array(w) for w in C['w']]

    def at(lr):
        z = np.clip((np.array([e, max(lr, C['fill'])]) - mu) / sd, -4, 4)
        ps = np.cumprod([1 / (1 + math.exp(-max(-30, min(30, w[0] + w[1:] @ z)))) for w in W])
        return np.array([ps[0], FLOOR + 10 * (ps[0] + ps[1] + ps[2]) + (C['topMean'] - 50) * ps[3]])

    def spread(m, s):
        return sum(wt * at(m + s * x) for x, wt in zip(*_GH)) / _GH[1].sum()
    if lr_pre is not None:
        a = C['att']; v = spread(a['a'] + a['b'] * lr_pre, a['sd'])
    else:
        p_on = 1 / (1 + math.exp(-(C['onLogit'][0] + C['onLogit'][1] * e)))
        v = (1 - p_on) * at(C['fill']) + p_on * spread(C['onRank'][0] * e + C['onRank'][1], C['onSd'])
    return float(v[1]), float(v[0])


def live_consensus(names_teams):
    """-ln consensus rank on the current boards (scripts/data/cbb_boards, cbb_mock.consensus) for each (name, team),
    None when no board lists him."""
    import csv
    base = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_boards')
    files = sorted(f for f in os.listdir(base) if f.endswith('.csv')) if os.path.isdir(base) else []
    if not files: return [None] * len(names_teams)
    import cbb_mock as M
    boards = []
    for f in files:
        with open(os.path.join(base, f), newline='', encoding='utf-8') as fh:
            boards.append([(r['name'], r['school'], r['pos'], int(r['rank'])) for r in csv.DictReader(fh)])
    ppl = M.consensus(boards)
    idx = M.build_index([{'name': p['name'], 'school': p['school'], 'cons': p['cons']} for p in ppl.values()])
    out = []
    for n, t in names_teams:
        m = M.match(n, t, idx)
        out.append(-math.log(m['cons']) if m else None)
    return out


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = xpm_scale(careers)
    print('peak XPM where each FV starts:', thr)
    for c in careers: c['nba']['fvx'] = xpm_fv(c, thr)
    rows = []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if s['year'] < 2009: continue
            rows.append({'pid': c['pid'], 'name': c['name'], 'team': s['team'], 'brole': s['role'], 'conf': s['conf'], 'yr': s['yr'], 'ht': s['ht'],
                         'year': s['year'], 'last': c['last'], 'y': c['nba']['fvx'], 'role': c['nba']['role'], 'peak': c['nba']['peak'], 'xpm': c['nba']['peakXpm'],
                         'pick': c['nba']['pick'], 'draft': c['nba']['draft'], 'f': features(c, i),
                         'bpm_now': s['bpm'], 'mpt_now': (s['mp'] or 0) * (s['gp'] or 0)})
    train = [r for r in rows if r['year'] in TRAIN and r['last'] <= 2020]
    global TOP_MEAN
    tops = [c['nba']['fvx'] for c in careers if c['last'] in SCALE_CLASSES and c['nba']['fvx'] >= 60]
    TOP_MEAN = round(float(np.mean(tops)), 2)
    print(f'mean FV of the 60+ careers: {TOP_MEAN} ({len(tops)} careers)')
    models, report = {}, {}
    for grp, cands in (('newcomer', NEW_CANDS), ('returner', RET_CANDS)):
        tr = [r for r in train if r['f']['newcomer'] == (grp == 'newcomer')]
        sel = select(tr, cands, grp)
        X = matrix(tr, sel['kept'])
        m = fit(tr, X, list(range(len(sel['kept']))), sel['lam'])
        # out-of-fold predictions for the training boards (what the past-season grades show)
        _, _, oof = cv_error(tr, X, list(range(len(sel['kept']))), sel['lam'])
        for r, e in zip(tr, oof): r['oof'] = float(e)
        models[grp] = (sel, m)

    def score(rs):
        out = np.zeros(len(rs)); p = np.zeros(len(rs))
        for grp, (sel, m) in models.items():
            ix = [i for i, r in enumerate(rs) if r['f']['newcomer'] == (grp == 'newcomer')]
            if not ix: continue
            pp, _, e = predict(m, matrix([rs[i] for i in ix], sel['kept']))
            out[ix] = e; p[ix] = pp
        return out, p

    e_all, p_all = score(rows)
    for r, e, p in zip(rows, e_all, p_all):
        r['e'] = r.get('oof', float(e)); r['p'] = float(p)
    cuts = scarcity(train, TRAIN)
    print('players per preseason board at each FV or better:', cuts)
    global VALIDITY
    lat = validity(train)
    print('latent validity (polyserial, out of fold):', lat)
    VALIDITY, shrink_log = tune_shrink(train, cuts)
    print('board shrink r (graded FV = the mean outcome):', VALIDITY, shrink_log)

    # backtests
    y = np.array([r['y'] for r in train], float); e = np.array([r['e'] for r in train])
    bt = {'train': {'boards': f'{TRAIN[0]}-{TRAIN[-1]}', 'rows': len(train), 'corr': round(float(np.corrcoef(e, y)[0, 1]), 3),
                    'spearman_nba': round(spearman(e[y >= 30], y[y >= 30]), 3), 'auc_nba': round(auc(e, y >= 30), 3)}}
    tops = []
    for yr in TRAIN:
        b = sorted([r for r in train if r['year'] == yr], key=lambda r: -r['e'])[:10]
        tops.append(np.mean([r['y'] for r in b]))
    bt['train']['top10_realized_fv'] = round(float(np.mean(tops)), 1)
    print('training boards, out of fold:', bt['train'])
    fwd = []
    for yr in TEST:
        ix = [r for r in rows if r['year'] == yr]
        sc = np.array([r['e'] for r in ix]); picked = np.array([r['draft'] == yr for r in ix])
        top = sorted(ix, key=lambda r: -r['e'])[:60]
        ranks = {id(r): k for k, r in enumerate(sorted(ix, key=lambda r: -r['e']), 1)}
        pk = [(ranks[id(r)], r['pick']) for r in ix if r['draft'] == yr]
        rho = spearman(np.array([a for a, b in pk], float), np.array([b for a, b in pk], float)) if len(pk) > 5 else None
        t10 = [r for r in top[:10]]
        fwd.append({'year': yr, 'auc_picked': round(auc(sc, picked), 3), 'top60_picked': sum(1 for r in top if r['draft'] == yr),
                    'top10_first_round': sum(1 for r in t10 if r['pick'] and r['pick'] <= 30 and r['draft'] and r['draft'] <= yr + 3),
                    'picked': int(picked.sum()), 'rho_rank_pick': round(rho, 3) if rho else None})
        print('  ', fwd[-1])
    bt['forward'] = fwd
    # the same test for the plain recruiting rank / last season BPM, as the yardsticks
    def yard(key):
        res = []
        for yr in TEST:
            ix = [r for r in rows if r['year'] == yr]
            sc = np.array([(r['f'].get(key) if r['f'].get(key) is not None else -99) for r in ix], float)
            res.append(auc(sc, np.array([r['draft'] == yr for r in ix])))
        return round(float(np.mean(res)), 3)
    bt['yardsticks'] = {'model': round(float(np.mean([f['auc_picked'] for f in fwd])), 3), 'recruit_rank': yard('lrank'), 'last_bpm': yard('bpm')}
    print('mean AUC picked that June:', bt['yardsticks'])

    # projected college BPM
    xb = {grp: xbpm_fit([r for r in rows if r['year'] in range(2010, 2027) and r['f']['newcomer'] == (grp == 'newcomer')], cands)
          for grp, cands in (('newcomer', NEW_CANDS), ('returner', RET_CANDS))}
    print('xBPM r:', {g: v['r'] for g, v in xb.items()})

    # past-season grades: every preseason board 2010-2026 as the model graded it (out of fold for 2009-2016 boards,
    # forward for later ones), top PAST_N per board, with what became of each player
    past = []
    for yr in range(2010, 2027):
        ix = [r for r in rows if r['year'] == yr]
        sc = np.array([r['e'] for r in ix])
        fv, plus, fvx = grade(sc, cuts)
        order = np.argsort(-sc)[:PAST_N]
        for k, i in enumerate(order, 1):
            r = ix[i]
            past.append([yr, k, r['name'], r['team'], r['conf'], r['yr'], r['ht'], int(fv[i]), bool(plus[i]), round(float(fvx[i]), 2),
                         round(r['p'], 4), int(r['y']) if r['last'] <= 2020 or r['y'] > 20 else None,
                         (('peak XPM %+.1f, ' % r['xpm'] if r['y'] > 20 and r['xpm'] is not None else '') + r['role']) if r['last'] <= 2020 or r['y'] > 20 else None,
                         r['draft'], r['pick'], 1 if r['f']['newcomer'] else 0, POS3.get(r['brole'], 'F'), r['brole']])
    # calibration: on the 2009-16 boards (out of fold), what the players graded at each FV went on to do
    cal = defaultdict(list)
    for yr in TRAIN:
        ix = [r for r in train if r['year'] == yr]
        g, _, _ = grade(np.array([r['e'] for r in ix]), cuts)
        for r, t in zip(ix, g): cal[tier_of(t)].append(r['y'])
    calib = {t: {'n': len(v), 'meanFv': round(float(np.mean(v)), 1), 'nba': round(float(np.mean([x >= 30 for x in v])), 3),
                 'starter': round(float(np.mean([x >= 45 for x in v])), 3), 'star': round(float(np.mean([x >= 60 for x in v])), 3)}
             for t, v in sorted(cal.items(), reverse=True)}
    print('graded FV -> outcome (2009-16 boards, out of fold):', calib)
    cons = board_stage(train, june_ranks())
    fit_out = {'asof': __import__('datetime').date.today().isoformat(), 'train': f'{TRAIN[0]}-{TRAIN[-1]}', 'floor': FLOOR,
               'models': {g: model_json(sel, m) for g, (sel, m) in models.items()}, 'xbpm': xb, 'cuts': cuts,
               'fvTable': fv_table(careers, cuts, thr), 'xpmCuts': thr, 'validity': VALIDITY, 'calib': calib, 'backtest': bt,
               'boards': cons}
    json.dump(fit_out, open(OUT, 'w'), indent=1)
    json.dump({'cols': ['season', 'rk', 'name', 'team', 'conf', 'cls', 'ht', 'fv', 'plus', 'fvx', 'nbaP', 'outcome', 'role', 'draft', 'pick', 'new', 'pos', 'role0'],
               'rows': past}, open(os.path.join(D.ROOT, 'static', 'data', 'cbb-past.json'), 'w'), separators=(',', ':'))
    # the headline at the mean outcome (fvg the grade) and the calibration by headline FV: python3 scripts/fv_dist.py --past
    print(f'wrote {OUT} and static/data/cbb-past.json ({len(past)} rows)')


if __name__ == '__main__':
    main()
