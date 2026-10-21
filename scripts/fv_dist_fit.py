#!/usr/bin/env python3
"""FV as a distribution: the chance of each outcome tier, an 80% range and the expected value, for every player on the
CFB and college basketball boards (data/fv_dist.json, read by fetch_cfb.mjs, cfb_teams.mjs, fetch_cbb.py, cbb_live.py).

    node scripts/cfb_fv_refit.mjs --dist=scripts/.cache/fvdist/cfb_rows.json   # CFB boards 2019-22, NFL outcomes
    python3 scripts/fv_dist_fit.py                                              # CBB rows from static/data/cbb-past.json

Outcome: the realized FV on each board's own scale. CFB: NFL AV a season (drafts 2020-23, AV through 2025, undrafted
0) read back through the board's AV map (cfb_teams.mjs AV_BY_FV), so 50 = 3.7 AV a season, 60 = 5.0, and an outcome
below 0.4 AV a season sits under 30. Basketball: the career's peak-XPM FV (cbb_fit.py; 20 = never reached the NBA).

Model: a location-scale ordered probit on the outcome ladder (bins cut at 30, 35, ... 70). The location is the
player's graded FV (piecewise linear: CFB hinges at 45 and 60, basketball one hinge picked held out), the same for everyone with that grade, so the headline FV
keeps its meaning; the spread can differ by group (position, class, newcomer, a consensus board or not), each term
kept only if it improves the held-out score. Cut points are free, so the shape (the mass of busts at the floor, the
long right tail) comes from the data, not from a normal curve.

Held-out scoring: CFB leaves one draft class out (2020-23 drafts); basketball holds out a fifth of the players at a
time (a player's boards stay together). Scores: ranked probability score (RPS) over the ladder, log loss on the five
display tiers, CRPS on the outcome FV, 80% range coverage and a PIT histogram, against two baselines: the graded FV
with one spread for everyone, and with a spread per position.

Result (Oct 21, 2026; CFB on the PR #289 weights, 5,771 rows; basketball 2,099 rows), held out:
  CFB    RPS .0398 vs .0408 one spread (-2.5%, better in all 5 classes), .0557 grade +/- a normal spread, .0561 no
         information; log loss .421 vs .446; CRPS 2.46 vs 2.53. Kept spread terms: a season a year or more before the
         draft (x2.1), walk-on (x1.3), on a consensus board (x1.4), underclassman, grade level. Position spreads lose.
         PIT deciles .094-.111. Location shifts by group (early, under, walk-on) don't help held out, so one grade
         means one centre. Expected NFL AV over the tiers vs the AV map of the grade: MSE 1.547 vs 1.576, r .596 vs
         .588 (its mean .454 against .469 realized; the map's .529).
  CBB    (Oct 21, grades restated at the mean outcome, cbb_fit r .81) RPS .0767 vs .0810 grade +/- a normal spread,
         .0871 no information; one hinge at 35 picked held out (35 .0767, 40 .0769, 45 .0772, 50 .0775; 45 and 60 .0772);
         seniors a little tighter (x.87), the only spread term kept. On the 75th-percentile grades it was .0769, no terms.
Downstream: CFB team talent summed on expected AV tracked 2026 SRS worse (r .64 vs .68 on avOf(FV), 138 teams), so
team talent stays on the grade; xNIL tests expected AV ('ev') against its other value candidates on On3's valuations
and keeps the best (nilFit.valueTest). Basketball's game prior already reads E[FV] over the model's own rungs.
"""
import json, math, os, sys, hashlib
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'fvdist')
OUT = os.path.join(ROOT, 'data', 'fv_dist.json')
EDGES = [30, 35, 40, 45, 50, 55, 60, 65, 70]          # bins: <30, 30-34, ..., 65-69, 70+
TIERS = [30, 40, 50, 60]                              # display tiers: <30, 30-39, 40-49, 50-59, 60+
TOP = 80.0
AV_BY_FV = [[20, 0], [30, 0.4], [40, 1.7], [50, 3.7], [60, 5.0], [65, 6.3], [70, 7.2], [75, 8.1], [80, 10.1]]   # as cfb_teams.mjs


def av_of(fv):
    f, a = zip(*AV_BY_FV)
    return float(np.interp(fv, f, a))


def fv_of_av(av):
    """the FV whose AV a season is av (the inverse of the board's AV map); 20 at 0 AV."""
    f, a = zip(*AV_BY_FV)
    return float(np.interp(av, a, f))


def ncdf(x):
    """standard normal CDF, vectorized (Abramowitz-Stegun 7.1.26 erf, error under 2e-7)."""
    z = np.asarray(x, float) / math.sqrt(2); a = np.abs(z)
    t = 1 / (1 + 0.3275911 * a)
    e = 1 - t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * np.exp(-a * a)
    return 0.5 * (1 + np.sign(z) * e)


def bin_of(y):
    return int(np.searchsorted(EDGES, y, side='right'))


# ---------------------------------------------------------------- the model
class Model:
    """ordered probit, P(Y <= edge k) = Phi((c_k - mu) / sigma), mu = X b, log sigma = Z g (no intercept: sigma 1 for
    the base group), c increasing (c_0 free, then exp steps)."""
    def __init__(self, nx, nz, ridge=1.0):
        self.nx, self.nz, self.ridge = nx, nz, ridge
        self.th = np.zeros(len(EDGES) + nx + nz)
        self.th[0] = -1.0; self.th[1:len(EDGES)] = math.log(0.3)

    def unpack(self, th):
        K = len(EDGES)
        c = np.concatenate([[th[0]], th[0] + np.cumsum(np.exp(th[1:K]))])
        return c, th[K:K + self.nx], th[K + self.nx:]

    def cdf(self, th, X, Z):
        c, b, g = self.unpack(th)
        mu = X @ b; s = np.exp(np.clip(Z @ g, -3, 3)) if self.nz else np.ones(len(X))
        return ncdf((c[None, :] - mu[:, None]) / s[:, None])            # n x K: P(Y < edge k)

    def probs(self, th, X, Z):
        F = self.cdf(th, X, Z)
        F = np.hstack([np.zeros((len(F), 1)), F, np.ones((len(F), 1))])
        return np.clip(np.diff(F, axis=1), 1e-9, 1)

    def nll(self, th, X, Z, k, w):
        P = self.probs(th, X, Z)
        _, b, g = self.unpack(th)
        return -(w * np.log(P[np.arange(len(k)), k])).sum() / w.sum() + self.ridge * 1e-3 * (g @ g) + 1e-6 * (b @ b)

    def grad(self, th, X, Z, k, w):
        """analytic gradient of nll."""
        K = len(EDGES); n = len(k)
        c, b, g = self.unpack(th)
        lz = np.clip(Z @ g, -3, 3) if self.nz else np.zeros(n); s = np.exp(lz)
        mu = X @ b
        U = (c[None, :] - mu[:, None]) / s[:, None]                      # n x K
        F = ncdf(U); D = np.exp(-U * U / 2) / math.sqrt(2 * math.pi)
        Fp = np.hstack([np.zeros((n, 1)), F, np.ones((n, 1))]); Dp = np.hstack([np.zeros((n, 1)), D, np.zeros((n, 1))])
        Up = np.hstack([np.zeros((n, 1)), U, np.zeros((n, 1))])
        ix = np.arange(n)
        P = np.clip(Fp[ix, k + 1] - Fp[ix, k], 1e-9, 1)
        hi, lo = Dp[ix, k + 1] / P, -Dp[ix, k] / P                         # d loglik / d u at the bin's upper / lower edge
        ww = w / w.sum()
        # d u / d c_j = 1/s at edge j; d u / d mu = -1/s; d u / d log s = -u
        dc = np.zeros(K)
        up = k < K; lw = k > 0
        np.add.at(dc, k[up], (ww * hi / s)[up]); np.add.at(dc, k[lw] - 1, (ww * lo / s)[lw])
        # c_0 = th0, c_j = th0 + sum_{i<=j} exp(th_i)
        gth = np.zeros(K)
        gth[0] = dc.sum()
        e = np.exp(th[1:K])
        gth[1:] = e * np.cumsum(dc[::-1])[::-1][1:]
        dmu = -(ww * (hi + lo) / s)
        gb = X.T @ dmu
        out = -np.concatenate([gth, gb])
        if self.nz:
            dls = -(ww * (hi * Up[ix, k + 1] + lo * Up[ix, k]))
            dls = np.where(np.abs(Z @ g) < 3, dls, 0)
            out = np.concatenate([out, -(Z.T @ dls) + 2 * self.ridge * 1e-3 * g])
        out[K:K + self.nx] += 2e-6 * b
        return out

    def fit(self, X, Z, k, w=None):
        w = np.ones(len(k)) if w is None else w
        f = lambda th: self.nll(th, X, Z, k, w)
        gr = lambda th: self.grad(th, X, Z, k, w)
        # start: location slope 1/10 per FV point on the first column (the grade, centred)
        self.th[len(EDGES)] = 0.1
        self.th = bfgs(f, self.th, gr)
        return self

    def predict(self, X, Z):
        return self.probs(self.th, X, Z)


def num_grad(f, x, h=1e-5):
    g = np.zeros_like(x)
    for i in range(len(x)):
        e = np.zeros_like(x); e[i] = h
        g[i] = (f(x + e) - f(x - e)) / (2 * h)
    return g


def bfgs(f, x, grad=None, iters=400, tol=1e-9):
    grad = grad or (lambda v: num_grad(f, v))
    n = len(x); H = np.eye(n); fx = f(x); g = grad(x)
    for _ in range(iters):
        p = -H @ g; t = 1.0
        while True:
            xn = x + t * p; fn = f(xn)
            if fn <= fx + 1e-4 * t * (g @ p) or t < 1e-10: break
            t *= 0.5
        gn = grad(xn); s = xn - x; yv = gn - g
        if abs(fx - fn) < tol and np.abs(gn).max() < 1e-5: x, fx, g = xn, fn, gn; break
        sy = s @ yv
        if sy > 1e-12:
            r = 1 / sy; I = np.eye(n)
            H = (I - r * np.outer(s, yv)) @ H @ (I - r * np.outer(yv, s)) + r * np.outer(s, s)
        x, fx, g = xn, fn, gn
    return x


# ---------------------------------------------------------------- features
HINGES = (45, 60)   # the location's hinges (per board: CFB 45 and 60; basketball picks its own held out, fit_cbb)


def loc_x(fv):
    """location basis: the grade (centred at 40, per 10 points) with a hinge at each of HINGES."""
    fv = np.asarray(fv, float)
    return np.column_stack([(fv - 40) / 10] + [np.maximum(0, fv - h) / 10 for h in HINGES])


def scale_z(rows, terms):
    return np.array([[t[1](r) for t in terms] for r in rows], float).reshape(len(rows), len(terms))


# ---------------------------------------------------------------- distribution summaries
def bin_stats(ys, vals=None):
    """mean outcome FV (and mean value) inside each bin, pooled over the training rows."""
    ys = np.asarray(ys, float)
    k = np.array([bin_of(y) for y in ys])
    lo = [20.0] + EDGES; hi = EDGES + [TOP]
    m = [float(ys[k == j].mean()) if (k == j).sum() >= 3 else (lo[j] + hi[j]) / 2 for j in range(len(EDGES) + 1)]
    v = None
    if vals is not None:
        vals = np.asarray(vals, float)
        v = [float(vals[k == j].mean()) if (k == j).sum() >= 3 else av_of((lo[j] + hi[j]) / 2) for j in range(len(EDGES) + 1)]
    return m, v


def floor_share(ys):
    """inside the bottom bin, the share of outcomes at the floor (20: never reached the league / no AV)."""
    ys = np.asarray(ys, float); b = ys[ys < EDGES[0]]
    return float((b <= 20.0001).mean()) if len(b) else 1.0


def cdf_at(P, x, fl):
    """CDF of the outcome FV at x (piecewise linear inside a bin; the bottom bin is a point mass at 20 of share fl plus
    a flat stretch 20-30)."""
    F = np.concatenate([[0], np.cumsum(P)])
    lo = [20.0] + EDGES; hi = EDGES + [TOP]
    if x < 20: return 0.0
    if x >= TOP: return 1.0
    j = bin_of(x)
    if j == 0: return P[0] * (fl + (1 - fl) * (x - 20) / 10)
    return F[j] + P[j] * (x - lo[j]) / (hi[j] - lo[j])


def quantile(P, q, fl):
    F = np.concatenate([[0], np.cumsum(P)])
    lo = [20.0] + EDGES; hi = EDGES + [TOP]
    if q <= P[0] * fl: return 20.0
    if q <= P[0]: return 20 + 10 * (q / P[0] - fl) / max(1e-9, 1 - fl)
    j = int(np.searchsorted(F, q, side='left')) - 1
    j = min(max(j, 1), len(P) - 1)
    return lo[j] + (hi[j] - lo[j]) * (q - F[j]) / max(1e-12, P[j])


GRID = np.arange(20, 80.01, 0.5)


def cdf_grid(P, fl, grid=GRID):
    """cdf_at for every row of P on a grid of outcome FVs (n x len(grid))."""
    Fc = np.hstack([np.zeros((len(P), 1)), np.cumsum(P, 1)])
    lo = np.array([20.0] + EDGES); hi = np.array(EDGES + [TOP])
    j = np.array([bin_of(x) for x in grid])
    frac = (grid - lo[j]) / (hi[j] - lo[j])
    F = Fc[:, j] + P[:, j] * frac[None, :]
    b0 = j == 0
    F[:, b0] = P[:, [0]] * (fl + (1 - fl) * frac[b0][None, :])
    return np.minimum(F, 1.0)


def crps(P, y, fl, grid=GRID):
    F = cdf_grid(P[None, :], fl, grid)[0]
    return float(((F - (grid >= y)) ** 2).sum() * 0.5)


def tiers(P):
    """P over the five display tiers from the bins."""
    out, j = [], 0
    for t in TIERS + [TOP + 1]:
        s = 0.0
        while j < len(P) and ([20.0] + EDGES)[j] < t: s += P[j]; j += 1
        out.append(s)
    return np.array(out)


def scores(P, ys, fl, fast=False):
    k = np.array([bin_of(y) for y in ys])
    O = np.zeros_like(P); O[np.arange(len(k)), k] = 1
    rps = float(((np.cumsum(P, 1) - np.cumsum(O, 1)) ** 2).sum(1).mean() / (P.shape[1] - 1))
    T = np.array([tiers(p) for p in P]); kt = np.array([sum(1 for t in TIERS if y >= t) for y in ys])
    ll = float(-np.log(np.clip(T[np.arange(len(kt)), kt], 1e-9, 1)).mean())
    if fast: return {'rps': round(rps, 5), 'logloss': round(ll, 4)}
    Fg = cdf_grid(P, fl)
    cr = float((((Fg - (GRID[None, :] >= np.asarray(ys, float)[:, None])) ** 2).sum(1) * 0.5).mean())
    lo = np.array([quantile(p, 0.1, fl) for p in P]); hi = np.array([quantile(p, 0.9, fl) for p in P])
    ys = np.asarray(ys, float)
    # an outcome at the floor is inside the range when the range reaches the floor
    cov = float(np.mean((ys >= lo - 1e-9) & (ys <= hi + 1e-9)))
    below, above = float(np.mean(ys < lo - 1e-9)), float(np.mean(ys > hi + 1e-9))
    # randomized PIT (the floor is a point mass): deciles should hold 10% each
    rng = np.random.default_rng(7)
    pit = []
    for p, y in zip(P, ys):
        a = cdf_at(p, y - 1e-6, fl) if y > 20.0001 else 0.0; b = cdf_at(p, y, fl)
        pit.append(a + (b - a) * rng.random())
    hist = np.histogram(pit, bins=10, range=(0, 1))[0] / len(pit)
    return {'rps': round(rps, 5), 'logloss': round(ll, 4), 'crps': round(cr, 3), 'cover80': round(cov, 3), 'below': round(below, 3), 'above': round(above, 3),
            'pit': [round(float(x), 3) for x in hist], 'n': len(ys)}


# ---------------------------------------------------------------- held-out comparison
def held_out(rows, folds, specs, grade_key='x'):
    """each spec (name, scale terms) fit on the other folds, scored on the held-out one; returns OOF probabilities."""
    out = {}
    ys = np.array([r['y'] for r in rows]); k = np.array([bin_of(y) for y in ys])
    X = loc_x([r[grade_key] for r in rows])
    for name, terms in specs:
        Z = scale_z(rows, terms)
        P = np.zeros((len(rows), len(EDGES) + 1))
        for f in sorted(set(folds)):
            tr, te = folds != f, folds == f
            m = Model(X.shape[1], Z.shape[1]).fit(X[tr], Z[tr], k[tr])
            P[te] = m.predict(X[te], Z[te])
        out[name] = P
    return out


def naive(rows, folds):
    """the two yardsticks: the share of each bin on the training boards (no information), and the graded FV as the
    centre of a normal curve with one fitted spread (the point grade read as 'FV give or take s')."""
    ys = np.array([r['y'] for r in rows]); k = np.array([bin_of(y) for y in ys]); x = np.array([r['x'] for r in rows])
    E = np.array(EDGES, float)
    def nprobs(x, sd):
        F = ncdf((E[None, :] - x[:, None]) / sd)
        return np.clip(np.diff(np.hstack([np.zeros((len(x), 1)), F, np.ones((len(x), 1))]), axis=1), 1e-9, 1)
    C = np.zeros((len(rows), len(EDGES) + 1)); N = np.zeros_like(C)
    for f in sorted(set(folds)):
        tr, te = folds != f, folds == f
        C[te] = np.bincount(k[tr], minlength=len(EDGES) + 1) / tr.sum()
        sd = min(np.arange(2, 30.1, 0.5), key=lambda sd: -np.log(nprobs(x[tr], sd)[np.arange(tr.sum()), k[tr]]).sum())
        N[te] = nprobs(x[te], sd)
    return {'no information': C, 'grade +/- one spread': N}


def by_group(P, rows, ys, fl, key):
    g = defaultdict(list)
    for i, r in enumerate(rows): g[key(r)].append(i)
    return {str(a): scores(P[ix], ys[ix], fl) for a, ix in sorted(g.items()) if len(ix) >= 30}


def compare(label, rows, folds, base_terms, cand_terms, groups):
    ys = np.array([r['y'] for r in rows]); fl = floor_share(ys)
    specs = [('one spread', []), ('spread by position', base_terms), ('model', cand_terms)]
    P = {**naive(rows, folds), **held_out(rows, folds, specs)}
    specs = [('no information', None), ('grade +/- one spread', None)] + specs
    res = {name: scores(P[name], ys, fl) for name, _ in specs}
    for name, _ in specs: print(f'{label} {name:22s}', res[name])
    # each scale term's held-out worth: the model with it left out
    drop = {}
    for t in cand_terms:
        Pd = held_out(rows, folds, [('d', [x for x in cand_terms if x is not t])])['d']
        s = scores(Pd, ys, fl); drop[t[0]] = {'rps': round(s['rps'] - res['model']['rps'], 5), 'logloss': round(s['logloss'] - res['model']['logloss'], 4)}
        print(f'   without {t[0]:10s} rps {drop[t[0]]["rps"]:+.5f}  logloss {drop[t[0]]["logloss"]:+.4f}')
    per_fold = {}
    for f in sorted(set(folds)):
        ix = folds == f
        per_fold[str(f)] = {n: scores(P[n][ix], ys[ix], fl)['rps'] for n, _ in specs}
    return res, drop, per_fold, {g: by_group(P['model'], rows, ys, fl, kf) for g, kf in groups.items()}, P


def final_fit(rows, terms, vals=None):
    ys = np.array([r['y'] for r in rows]); k = np.array([bin_of(y) for y in ys])
    X = loc_x([r['x'] for r in rows]); Z = scale_z(rows, terms)
    m = Model(X.shape[1], Z.shape[1]).fit(X, Z, k)
    c, b, g = m.unpack(m.th)
    means, vmeans = bin_stats(ys, vals)
    return {'edges': EDGES, 'tiers': TIERS, 'cuts': [round(float(x), 5) for x in c], 'loc': [round(float(x), 5) for x in b], 'hinges': list(HINGES),
            'scale': {t[0]: round(float(x), 5) for t, x in zip(terms, g)}, 'binMean': [round(x, 2) for x in means],
            'binValue': [round(x, 3) for x in vmeans] if vmeans else None, 'floorShare': round(floor_share(ys), 4), 'n': len(rows)}, m


# ---------------------------------------------------------------- CFB
CFB_POS = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB']


def cfb_rows():
    f = os.path.join(CACHE, 'cfb_rows.json')
    if not os.path.exists(f): sys.exit(f'missing {f}: run node scripts/cfb_fv_refit.mjs --dist={f}')
    rows = []
    for r in json.load(open(f)):
        x = r['fc'] if r['dt'] else r['fm']
        rows.append({**r, 'x': x, 'y': fv_of_av(r['av']), 'cls': r['last']})
    return rows


def cfb_terms():
    pos = [(f'pos_{g}', (lambda g: lambda r: 1.0 if r['g'] == g else 0.0)(g)) for g in CFB_POS if g != 'WR']
    extra = [('under', lambda r: 1.0 if r['years'] <= 2.5 else 0.0),            # one or two years on campus
             ('early', lambda r: 0.0 if r['final'] else 1.0),                   # not his last college season
             ('walkon', lambda r: 1.0 if r['walkOn'] else 0.0),                 # no 247 recruiting record
             ('lowsnap', lambda r: 1.0 if (r['snaps'] or 0) < 300 else 0.0),
             ('cons', lambda r: 1.0 if r['dt'] else 0.0),                       # a consensus board has him
             ('level', lambda r: (r['x'] - 45) / 10)]
    return pos, extra


# ---------------------------------------------------------------- basketball
def cbb_rows():
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-past.json')))
    c = {k: i for i, k in enumerate(d['cols'])}
    rows = []
    for r in d['rows']:
        if r[c['season']] > 2016 or r[c['outcome']] is None: continue
        x = r[c['fvg']] if 'fvg' in c else r[c['fvx']]   # the grade (fvx is the headline at the mean since Oct 21 2026)
        rows.append({'name': r[c['name']], 'season': r[c['season']], 'x': x, 'p': r[c['nbaP']], 'y': float(r[c['outcome']]),
                     'new': r[c['new']], 'cls': r[c['cls']], 'pos': r[c['pos']], 'conf': r[c['conf']]})
    return rows


def cbb_terms():
    pos = [('pos_G', lambda r: 1.0 if r['pos'] == 'G' else 0.0), ('pos_C', lambda r: 1.0 if r['pos'] == 'C' else 0.0)]
    extra = [('new', lambda r: float(r['new'])),
             ('fr', lambda r: 1.0 if r['cls'] == 'Fr' and not r['new'] else 0.0),
             ('sr', lambda r: 1.0 if r['cls'] in ('Sr', 'Gr') else 0.0),
             ('level', lambda r: (r['x'] - 45) / 10)]
    return pos, extra


def select_terms(label, rows, folds, base, extra):
    """backward: start from every scale term, drop the one whose removal lowers held-out RPS most, until none does."""
    ys = np.array([r['y'] for r in rows]); fl = floor_share(ys)
    cur = base + extra
    def score(T):
        v = scores(held_out(rows, folds, [('m', T)])['m'], ys, fl, fast=True)
        return v['rps'] + v['logloss'] / 100        # RPS with log loss as the tie-break
    best = score(cur); log = []
    while cur:
        trial = [(score([x for x in cur if x is not t]), t) for t in cur]
        s, t = min(trial, key=lambda a: a[0])
        if s > best + 5e-5: break                   # a term stays only if it is worth 5e-5 held out
        log.append({'drop': t[0], 'rps': round(s, 5)}); cur = [x for x in cur if x is not t]; best = min(best, s)
        print(f'{label}: drop {t[0]} -> rps {s:.5f}')
    return cur, log


def main():
    os.makedirs(CACHE, exist_ok=True)
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    out.update({'asof': __import__('datetime').date.today().isoformat(), 'method': 'scripts/fv_dist_fit.py'})
    only = sys.argv[1] if len(sys.argv) > 1 else None   # --cfb or --cbb: refit one board
    if only != '--cbb': fit_cfb(out)
    if only != '--cfb': fit_cbb(out)
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


def fit_cfb(out):
    rows = cfb_rows()
    folds = np.array([r['last'] for r in rows])
    base, extra = cfb_terms()
    kept, log = select_terms('cfb', rows, folds, base, extra)
    res, drop, pf, grp, P = compare('cfb', rows, folds, base, kept, {
        'position': lambda r: r['g'], 'years': lambda r: min(5, int(r['years'] + 0.5)), 'fv': lambda r: min(70, int(r['x'] // 5 * 5)),
        'season': lambda r: 'last' if r['final'] else 'earlier', 'draftClass': lambda r: r['last'] + 1})
    fit, m = final_fit(rows, kept, [av_of(y) for y in [r['y'] for r in rows]])
    # downstream check: the expected AV a season from the distribution vs the AV map of the grade, held out
    av = np.array([r['av'] for r in rows]); ys = np.array([r['y'] for r in rows])
    ex = []
    for f in sorted(set(folds)):
        tr = folds != f
        _, vm = bin_stats(ys[tr], [av_of(y) for y in ys[tr]])
        ex += [(i, float(P['model'][i] @ np.array(vm))) for i in np.where(~tr)[0]]
    ex = np.array([v for _, v in sorted(ex)])
    point = np.array([av_of(r['x']) for r in rows])
    fin = np.array([bool(r['final']) for r in rows])
    out['cfb'] = {**fit, 'kept': [t[0] for t in kept], 'selection': log, 'heldOut': res, 'dropOne': drop, 'perFold': pf, 'byGroup': grp,
                  'expectedAv': {'mseDist': round(float(((ex - av) ** 2).mean()), 4), 'msePoint': round(float(((point - av) ** 2).mean()), 4),
                                 'rDist': round(float(np.corrcoef(ex, av)[0, 1]), 4), 'rPoint': round(float(np.corrcoef(point, av)[0, 1]), 4),
                                 'rDistLast': round(float(np.corrcoef(ex[fin], av[fin])[0, 1]), 4), 'rPointLast': round(float(np.corrcoef(point[fin], av[fin])[0, 1]), 4),
                                 'meanDist': round(float(ex.mean()), 3), 'meanPoint': round(float(point.mean()), 3), 'meanAv': round(float(av.mean()), 3)}}
    print('cfb expected AV:', out['cfb']['expectedAv'])


def fit_cbb(out):
    global HINGES
    rows = cbb_rows()
    folds = np.array([int(hashlib.md5(r['name'].encode()).hexdigest(), 16) % 5 for r in rows])
    base, extra = cbb_terms()
    # the hinge, held out: since Oct 21 2026 the headline is the mean outcome, the top grades sit near 55-60 and the
    # football hinges (45, 60) put the bend past most of the data; one hinge from 35 to 50, picked by held-out RPS
    ys = np.array([r['y'] for r in rows]); hl = []
    for h in ((35,), (40,), (45,), (50,), (45, 60)):
        HINGES = h
        sc = scores(held_out(rows, folds, [('m', [])])['m'], ys, floor_share(ys), fast=True)
        hl.append({'hinges': list(h), 'rps': round(sc['rps'], 5)}); print('cbb hinges', h, sc['rps'])
    HINGES = tuple(min(hl, key=lambda t: t['rps'])['hinges'])
    kept, log = select_terms('cbb', rows, folds, base, extra)
    res, drop, pf, grp, P = compare('cbb', rows, folds, base, kept, {
        'position': lambda r: r['pos'], 'newcomer': lambda r: r['new'], 'class': lambda r: r['cls'], 'fv': lambda r: min(60, int(r['x'] // 5 * 5)), 'season': lambda r: r['season']})
    fit, m = final_fit(rows, kept)
    HINGES = (45, 60)
    out['cbb'] = {**fit, 'kept': [t[0] for t in kept], 'hingeSelection': hl, 'selection': log, 'heldOut': res, 'dropOne': drop, 'perFold': pf, 'byGroup': grp,
                  'note': 'fit on the top 300 of each 2010-16 preseason board (model-only grades, out of fold); grades below ~27 extrapolate'}


if __name__ == '__main__':
    main()
