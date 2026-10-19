"""CFB Elo research on ESPN history (scripts/cfb_espn_hist.py; no CFBD calls). Tune on 2016-20 (2015 is the
burn-in season every run starts from), report on 2021-25 held out.
  1. Elo variants against the live rule in scripts/cfb_model.mjs (eloRun, replicated exactly: 538's margin
     multiplier ln(|m|+1) x 2.2 / (0.001 x winner's edge + 2.2), K 20, home 70). Each variant's Elo-only margin is
     b1 x Elo gap / 25 + b2 x home + b3 x FBS side, fit on the tuning seasons; win chance Phi(m / sigma) with sigma
     fit to the winners. Scored on margin MAE and win log loss (paired per game), and next to the closing line.
  2. Season simulation spread: the team shock simulate() draws (fixed 4 points), scored on final regular-season
     win totals from weeks 1, 5 and 9 (log loss of the win count, CRPS).
  3. Market blend weight (report only).
Writes data/cfb_elo_research.json. Results, Oct 2026 (4,093 tuning games, 4,546 held out):
  1. Elo alone: a margin Elo (K 25 / 10 Elo a point of miss, K 2x in week 1 fading by week 8) beats the live rule
     held out: MAE 13.52 -> 12.92 (t -8.4), log loss .516 -> .498 (t -5.5); with the offseason pulled to the
     conference mean (carry .8) 12.71. The live rule re-tuned reaches only 13.23. Inside the full game model (the
     cfb-research dump, 2025 <-> 2026 season-swap CV) every margin-Elo form is worse (t +1.6 to +3.1; EPA already
     carries the margin) and margin Elo as an extra input fails (t > -1.1), so nothing shipped (fullModel in the json).
  2. Season sim: the team shock 8 x sqrt(games left / 12) beats the fixed 4 (tuned t -4.4, held out t -5.4; the full
     model's own 2025 ratings t -2.1). Shipped in simulate().
  3. Next to the close: Elo adds nothing (held out t +0.2 to +0.6); log-loss blend weight 0 (live Elo), .10 (margin Elo).
  OMP_NUM_THREADS=1 python3 scripts/cfb_elo_research.py
"""
import json
import math
import os
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist')
SEASONS = list(range(2015, 2026))
TUNE, HOLD = list(range(2016, 2021)), list(range(2021, 2026))
OUT = os.path.join(ROOT, 'data', 'cfb_elo_research.json')
r4 = lambda x: round(float(x), 4)


def phi(z):
    # the normal CDF, as cfb_model.mjs (Abramowitz-Stegun)
    z = np.asarray(z, float)
    t = 1 / (1 + 0.2316419 * np.abs(z))
    d = 0.3989423 * np.exp(-z * z / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
    return np.where(z > 0, 1 - p, p)


# ---- data --------------------------------------------------------------------------------------------------
def close_of(lines):
    """Home closing margin: the median over named books (ESPN's 'consensus' row is often stale: 'EVEN' with the
    books at 6), the consensus row only when it is all there is. Live (in-game) feeds are out."""
    lines = [l for l in lines if 'Live' not in (l.get('prov') or '')]    # in-game lines (2023 on) leak the result
    books = [l['spread'] for l in lines if l.get('prov') != 'consensus' and l.get('spread') is not None]
    if not books:
        books = [l['spread'] for l in lines if l.get('spread') is not None and l.get('details') not in (None, 'EVEN')]
    return -float(np.median(books)) if books else None


def load():
    G = {}
    for S in SEASONS:
        with open(os.path.join(DIR, f'games{S}.json')) as f:
            gs = [g for g in json.load(f) if g['done'] and g['hp'] is not None and g['ap'] is not None]
        n80 = Counter()
        for g in gs:
            if g['grp'] == 'fbs':
                n80[g['h']] += 1
                n80[g['a']] += 1
        fbs = {t for t, c in n80.items() if c >= 4}   # FCS teams play one or two FBS games; 2020 Pac-12 and MAC teams played five or six
        rows = []
        for g in gs:
            rows.append({'id': g['id'], 'S': S, 'w': g['w'], 'date': g['date'], 'h': g['h'], 'a': g['a'], 'n': g['n'],
                         'conf': g['conf'], 'm': g['hp'] - g['ap'], 'fbsGame': g['h'] in fbs or g['a'] in fbs,
                         'fh': g['h'] in fbs, 'fa': g['a'] in fbs, 'close': close_of(g.get('lines') or []),
                         'ccg': g['w'] < 20 and bool(g.get('note')) and 'Championship' in g['note'] and not g['note'].startswith('FCS'),
                         'hcf': g.get('hcf'), 'acf': g.get('acf')})
        rows.sort(key=lambda r: r['date'])
        G[S] = {'rows': rows, 'fbs': fbs}
    return G


# ---- Elo ---------------------------------------------------------------------------------------------------
# P: k, home, mov ('538' with a, b; 'none'; 'lin': update on the margin miss), carry (FBS start: carry x last
# final over 1500), fcsCarry (non-FBS: regress toward the non-FBS mean, the live 2/3), confReg (share of the FBS
# carryover pulled to the conference's mean instead of 1500), kEarly (K multiplier in week 1, fading to 1 by week
# kWeeks), fcsStart (a team new to the table), cap (margin cap for 'lin')
LIVE = {'k': 20, 'home': 70, 'mov': '538', 'a': 2.2, 'b': 0.001, 'carry': 0.6, 'fcsCarry': 2 / 3, 'confReg': 0.0,
        'kEarly': 1.0, 'kWeeks': 5, 'cap': 99, 'scale': 25.0}


def expected(hr, ar):
    return 1 / (1 + 10 ** ((ar - hr) / 400))


def update(r, g, P):
    hr = r[g['h']] + (0 if g['n'] else P['home'])
    ar = r[g['a']]
    k = P['k']
    if P['kEarly'] != 1 and g['w'] < P['kWeeks']:
        k *= 1 + (P['kEarly'] - 1) * (P['kWeeks'] - g['w']) / (P['kWeeks'] - 1)
    m = g['m']
    if P['mov'] == 'lin':
        # margin Elo: move by the miss against the Elo margin (scale Elo a point), capped
        mm = max(-P['cap'], min(P['cap'], m))
        s = k * (mm - (hr - ar) / P['scale']) / 10
    else:
        e = expected(hr, ar)
        res = 1 if m > 0 else 0 if m < 0 else 0.5
        if P['mov'] == 'none':
            mult = 1
        else:
            edge = hr - ar if res == 1 else ar - hr
            mm = min(abs(m), P['cap'])
            mult = math.log(mm + 1) * P['a'] / (P['b'] * edge + P['a'])
        s = k * mult * (res - e)
    r[g['h']] += s
    r[g['a']] -= s


def run_seasons(G, P, keep_weeks=()):
    """Walk every season in date order. Returns the pregame Elo-gap features of every game with an FBS side, by
    season, and (keep_weeks) the full rating table before those weeks."""
    final, feats, snaps = None, {}, {}
    for S in SEASONS:
        rows, fbs = G[S]['rows'], G[S]['fbs']
        r = {}
        if final is None:
            for t in fbs:
                r[t] = 1500.0
            fcsMean = 1200.0
        else:
            prev, fcsMean = final
            pf = {t: v for t, v in prev.items() if t in G[S - 1]['fbs']}
            conf = conf_means(G[S - 1], pf) if P['confReg'] else {}
            for t, v in prev.items():
                if t not in G[S - 1]['fbs'] and t not in fbs:
                    r[t] = fcsMean + (v - fcsMean) * P['fcsCarry']
            for t in fbs:
                if t in pf:
                    c = conf.get(t, 1500.0)
                    tgt = 1500 + P['confReg'] * (c - 1500)
                    r[t] = tgt + P['carry'] * (pf[t] - tgt)
                else:
                    # new to FBS: last year's FCS rating, carried, or the FCS mean
                    v = prev.get(t, fcsMean)
                    r[t] = 1500 + P['carry'] * (v - 1500)
        rr = defaultdict(lambda: fcsMean)
        rr.update(r)
        weeks = sorted({g['w'] for g in rows})
        out = []
        by = defaultdict(list)
        for g in rows:
            by[g['w']].append(g)
        for w in weeks:
            if w in keep_weeks:
                snaps[(S, w)] = dict(rr)
            for g in by[w]:
                if g['fbsGame']:
                    out.append(((rr[g['h']] - rr[g['a']]) / 25, 0 if g['n'] else 1, (1 if g['fh'] else 0) - (1 if g['fa'] else 0)))
            for g in by[w]:
                update(rr, g, P)
        feats[S] = np.array(out)
        non = [v for t, v in rr.items() if t not in fbs]
        final = (dict(rr), float(np.mean(non)) if non else 1200.0)
    return feats, snaps


def conf_means(GS, pf):
    """Each FBS team's conference mean final Elo (conference from ESPN's conference id on its games)."""
    cf = defaultdict(Counter)
    for g in GS['rows']:
        if g['hcf']:
            cf[g['h']][g['hcf']] += 1
        if g['acf']:
            cf[g['a']][g['acf']] += 1
    team_conf = {t: cf[t].most_common(1)[0][0] for t in pf if cf[t]}
    sums = defaultdict(list)
    for t, c in team_conf.items():
        sums[c].append(pf[t])
    return {t: float(np.mean(sums[c])) for t, c in team_conf.items()}


# ---- scoring -----------------------------------------------------------------------------------------------
def targets(G):
    Y, C = {}, {}
    for S in SEASONS:
        rows = [g for g in G[S]['rows'] if g['fbsGame']]
        Y[S] = np.array([g['m'] for g in rows], float)
        C[S] = np.array([g['close'] if g['close'] is not None else np.nan for g in rows], float)
    return Y, C


def fit_map(X, y):
    b = np.linalg.lstsq(X, np.clip(y, -45, 45), rcond=None)[0]
    return b


def fit_sigma(m, y):
    yy = np.where(y > 0, 1.0, np.where(y < 0, 0.0, 0.5))
    best = None
    for s in np.arange(8, 22.01, 0.1):
        p = np.clip(phi(m / s), 1e-9, 1 - 1e-9)
        ll = -np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p))
        if best is None or ll < best[0]:
            best = (ll, s)
    return best[1]


def per_game(m, y, s):
    yy = np.where(y > 0, 1.0, np.where(y < 0, 0.0, 0.5))
    p = np.clip(phi(m / s), 1e-9, 1 - 1e-9)
    return np.abs(y - m), -(yy * np.log(p) + (1 - yy) * np.log(1 - p))


def evaluate(G, Y, P):
    """Elo-only margin map and sigma fit on TUNE; per-game errors on TUNE (in sample for the 3-weight map, as the
    grid picks P there) and HOLD."""
    F, _ = run_seasons(G, P)
    Xt, yt = np.vstack([F[S] for S in TUNE]), np.concatenate([Y[S] for S in TUNE])
    b = fit_map(Xt, yt)
    s = fit_sigma(Xt @ b, yt)
    res = {}
    for name, ss in (('tune', TUNE), ('hold', HOLD)):
        X, y = np.vstack([F[S] for S in ss]), np.concatenate([Y[S] for S in ss])
        m = X @ b
        ae, ll = per_game(m, y, s)
        res[name] = {'m': m, 'ae': ae, 'll': ll}
    res['b'], res['sigma'], res['F'] = b, s, F
    return res


def paired(a, b):
    d = a - b
    se = d.std(ddof=1) / math.sqrt(len(d))
    return float(d.mean()), float(d.mean() / se) if se > 0 else 0.0


def summary(ev):
    return {k: {'mae': r4(ev[k]['ae'].mean()), 'logLoss': r4(ev[k]['ll'].mean()), 'n': int(len(ev[k]['ae']))} for k in ('tune', 'hold')}


def compare(ev, ref):
    out = {}
    for k in ('tune', 'hold'):
        da, ta = paired(ev[k]['ae'], ref[k]['ae'])
        dl, tl = paired(ev[k]['ll'], ref[k]['ll'])
        out[k] = {'dMae': r4(da), 'tMae': round(ta, 2), 'dLogLoss': r4(dl), 'tLogLoss': round(tl, 2)}
    return out


# ---- next to the close ---------------------------------------------------------------------------------------
def market(G, Y, C, ev):
    """Margin ~ close + Elo margin, fit on TUNE, scored on HOLD (games with a close), against close alone; and the
    log-loss blend weight on the Elo margin (fit on TUNE)."""
    def stack(ss):
        y = np.concatenate([Y[S] for S in ss])
        c = np.concatenate([C[S] for S in ss])
        return y, c
    out = {}
    yt, ct = stack(TUNE)
    yh, ch = stack(HOLD)
    mt, mh = ev['tune']['m'], ev['hold']['m']
    kt, kh = ~np.isnan(ct), ~np.isnan(ch)
    # close alone (slope fit) vs close + Elo
    A = np.c_[ct[kt], mt[kt]]
    b2 = np.linalg.lstsq(A, np.clip(yt[kt], -45, 45), rcond=None)[0]
    b1 = np.linalg.lstsq(ct[kt, None], np.clip(yt[kt], -45, 45), rcond=None)[0]
    for name, (y, c, m, k) in (('tune', (yt, ct, mt, kt)), ('hold', (yh, ch, mh, kh))):
        e1 = np.abs(y[k] - b1[0] * c[k])
        e2 = np.abs(y[k] - (b2[0] * c[k] + b2[1] * m[k]))
        d, t = paired(e2, e1)
        out[name] = {'n': int(k.sum()), 'maeClose': r4(np.abs(y[k] - c[k]).mean()), 'maeElo': r4(np.abs(y[k] - m[k]).mean()),
                     'maeCloseFit': r4(e1.mean()), 'maeCloseElo': r4(e2.mean()), 'dMae': r4(d), 't': round(t, 2)}
    out['weights'] = {'close': r4(b2[0]), 'elo': r4(b2[1])}
    # blend: phi((a x Elo + (1 - a) x close) / s), a and s fit on TUNE
    def bl(y, c, m, a, s):
        return per_game(a * m + (1 - a) * c, y, s)[1]
    best = None
    for a in np.arange(0, 0.61, 0.025):
        s = fit_sigma(a * mt[kt] + (1 - a) * ct[kt], yt[kt])
        v = bl(yt[kt], ct[kt], mt[kt], a, s).mean()
        if best is None or v < best[0]:
            best = (v, a, s)
    _, a, s = best
    s0 = fit_sigma(ct[kt], yt[kt])
    ll0, ll1 = bl(yh[kh], ch[kh], mh[kh], 0, s0), bl(yh[kh], ch[kh], mh[kh], a, s)
    d, t = paired(ll1, ll0)
    out['blend'] = {'eloWeight': r4(a), 'holdLogLossClose': r4(ll0.mean()), 'holdLogLossBlend': r4(ll1.mean()), 'dLogLoss': r4(d), 't': round(t, 2)}
    return out


# ---- season simulation -----------------------------------------------------------------------------------------
def sim_eval(G, P, ev, starts=(1, 5, 9), N=4000, seed=7):
    """From the ratings before week w, simulate every FBS team's remaining regular-season games (title games out)
    with a team shock N(0, u(left)) and the game noise sigma; score the final win count (log loss of the count
    with +0.5 smoothing over N draws, CRPS). u forms: fixed u, or u0 x sqrt(share of the 12-game season left)."""
    _, snaps = run_seasons(G, P, keep_weeks=starts)
    b, sigma = ev['b'], ev['sigma']
    rng = np.random.default_rng(seed)
    forms = [('fixed', u) for u in (0, 2, 3, 4, 5, 6, 7, 8, 10, 12)] + [('sqrt', u) for u in (4, 6, 7, 8, 10, 12)] + [('lin', u) for u in (6, 8, 10, 12, 14)]
    cases = []      # (season, week, team list, games, actual remaining wins)
    for S in SEASONS[1:]:
        rows, fbs = G[S]['rows'], G[S]['fbs']
        for w in starts:
            if (S, w) not in snaps:
                continue
            rr = snaps[(S, w)]
            left = [g for g in rows if w <= g['w'] < 20 and not g['ccg']]
            teams = sorted(fbs)
            ix = {t: i for i, t in enumerate(teams)}
            gl = [g for g in left if g['h'] in ix or g['a'] in ix]
            mu = np.array([b[0] * (rr.get(g['h'], 1200) - rr.get(g['a'], 1200)) / 25 + b[1] * (0 if g['n'] else 1)
                           + b[2] * ((1 if g['fh'] else 0) - (1 if g['fa'] else 0)) for g in gl])
            hi = np.array([ix.get(g['h'], -1) for g in gl])
            ai = np.array([ix.get(g['a'], -1) for g in gl])
            won = np.array([g['m'] > 0 for g in gl])
            nleft = np.zeros(len(teams))
            act = np.zeros(len(teams))
            for j, g in enumerate(gl):
                if hi[j] >= 0:
                    nleft[hi[j]] += 1
                    act[hi[j]] += won[j]
                if ai[j] >= 0:
                    nleft[ai[j]] += 1
                    act[ai[j]] += not won[j]
            cases.append((S, w, mu, hi, ai, nleft, act, len(teams)))
    res = defaultdict(lambda: defaultdict(list))
    for S, w, mu, hi, ai, nleft, act, T in cases:
        noise = rng.standard_normal((N, len(mu))) * sigma
        z = rng.standard_normal((N, T))
        for form, u in forms:
            if form == 'fixed':
                ut = np.full(T, float(u))
            elif form == 'sqrt':
                ut = u * np.sqrt(np.minimum(1, nleft / 12))
            else:
                ut = u * np.minimum(1, nleft / 12)
            sh = z * ut
            shp = np.c_[sh, np.zeros(N)]          # index -1: a non-FBS side takes no shock
            m = mu + shp[:, hi] - shp[:, ai] + noise
            hw = m > 0
            W = np.zeros((N, T + 1))
            np.add.at(W.T, hi, hw.T)
            np.add.at(W.T, ai, (~hw).T)
            W = W[:, :T]
            ll, cr = [], []
            for i in range(T):
                if nleft[i] == 0:
                    continue
                k = int(nleft[i])
                cnt = np.bincount(W[:, i].astype(int), minlength=k + 1)[:k + 1] + 0.5
                p = cnt / cnt.sum()
                ll.append(-math.log(p[int(act[i])]))
                F = np.cumsum(p)
                cr.append(float(np.sum((F[:-1] - (np.arange(k) >= act[i])) ** 2)))
            res[(form, u)][w].append((np.array(ll), np.array(cr), S))
    out = []
    for (form, u), byw in res.items():
        row = {'form': form, 'u': u}
        for part, ss in (('tune', TUNE), ('hold', HOLD)):
            ll = np.concatenate([x[0] for w in byw for x in byw[w] if x[2] in ss])
            cr = np.concatenate([x[1] for w in byw for x in byw[w] if x[2] in ss])
            row[part] = {'logLoss': r4(ll.mean()), 'crps': r4(cr.mean()), 'n': int(len(ll)),
                         'byWeek': {str(w): r4(np.concatenate([x[0] for x in byw[w] if x[2] in ss]).mean()) for w in byw}}
            row['_ll_' + part] = ll
        out.append(row)
    return out


def main():
    G = load()
    Y, C = targets(G)
    data = {'seasons': {'burnIn': 2015, 'tune': [TUNE[0], TUNE[-1]], 'hold': [HOLD[0], HOLD[-1]]},
            'games': {str(S): {'fbsGames': int(len(Y[S])), 'withClose': int((~np.isnan(C[S])).sum()), 'fbsTeams': len(G[S]['fbs'])} for S in SEASONS}}
    # 1. the live rule (carryover tuned for it, since the live start comes from a CFBD prior this harness lacks)
    base_runs = {}
    for c in (0.4, 0.5, 0.6, 0.7, 0.8):
        P = {**LIVE, 'carry': c}
        ev = evaluate(G, Y, P)
        base_runs[c] = ev
    cb = min(base_runs, key=lambda c: base_runs[c]['tune']['ll'].mean() + base_runs[c]['tune']['ae'].mean() / 100)
    ref = base_runs[cb]
    LIVEP = {**LIVE, 'carry': cb}
    data['live'] = {'params': LIVEP, **summary(ref), 'map': [r4(x) for x in ref['b']], 'sigma': r4(ref['sigma']),
                    'carryGrid': {str(c): summary(e) for c, e in base_runs.items()}}
    print('live', LIVEP, summary(ref), flush=True)
    # live-rule K and home over the live grid (cfb_model.mjs: K 15-40, home 40-70)
    lg = []
    for k in (15, 20, 25, 30, 40):
        for h in (40, 55, 70):
            ev = evaluate(G, Y, {**LIVEP, 'k': k, 'home': h})
            lg.append({'k': k, 'home': h, **summary(ev), 'vsLive': compare(ev, ref)})
    data['liveGrid'] = lg
    # variants: coordinate search on the tuning seasons (log loss, MAE as the tiebreak), each axis in turn
    axes = {
        'k': [15, 20, 25, 30, 35, 40, 50],
        'home': [20, 30, 40, 55, 70, 85],
        'carry': [0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        'confReg': [0, 0.25, 0.5, 0.75, 1.0],
        'kEarly': [1, 1.5, 2, 2.5, 3],
        'kWeeks': [4, 6, 8],
        'a': [1.2, 2.2, 3.5],
        'b': [0.0005, 0.001, 0.002],
        'cap': [21, 28, 35, 99],
        'fcsCarry': [0.5, 2 / 3, 0.8],
    }
    obj = lambda ev: ev['tune']['ll'].mean() + ev['tune']['ae'].mean() / 100
    cache = {}

    def ev_of(P):
        key = json.dumps(P, sort_keys=True)
        if key not in cache:
            cache[key] = evaluate(G, Y, P)
        return cache[key]

    def search(P0, keys):
        P = dict(P0)
        for _ in range(3):
            moved = False
            for ax in keys:
                best = min(axes[ax], key=lambda v: obj(ev_of({**P, ax: v})))
                if best != P[ax]:
                    P[ax] = best
                    moved = True
            if not moved:
                break
        return P
    variants = {}
    # (a) live rule, re-tuned K, home and carryover only
    variants['retuned'] = search(LIVEP, ['k', 'home', 'carry'])
    # (b) 538 multiplier with its constants and a margin cap free
    variants['mov538'] = search(LIVEP, ['k', 'home', 'carry', 'a', 'b', 'cap'])
    # (c) + higher early-season K
    variants['early'] = search(variants['mov538'], ['kEarly', 'kWeeks', 'k', 'home', 'carry'])
    # (d) + conference-mean regression in the offseason, and the FCS carryover
    variants['conf'] = search(variants['early'], ['confReg', 'fcsCarry', 'carry', 'k'])
    # (e) no margin (wins only), for scale
    variants['winsOnly'] = search({**LIVEP, 'mov': 'none'}, ['k', 'home', 'carry'])
    # (f) margin Elo: move by the miss against Elo's own margin (linear, optionally capped)
    axes['k'] = [10, 15, 20, 25, 30, 40, 50, 60]
    variants['linear'] = search({**LIVEP, 'mov': 'lin', 'k': 20, 'cap': 28}, ['k', 'home', 'carry', 'cap', 'kEarly', 'kWeeks', 'confReg'])
    data['variants'] = {}
    for name, P in variants.items():
        ev = ev_of(P)
        data['variants'][name] = {'params': P, **summary(ev), 'vsLive': compare(ev, ref), 'map': [r4(x) for x in ev['b']], 'sigma': r4(ev['sigma'])}
        print(name, P, summary(ev), compare(ev, ref), flush=True)
    # ship candidates: rule changes cfb_model.mjs can carry (K, home, multiplier, cap, early K), with the live
    # carryover and no conference regression, since the live start comes from the CFBD prior (ELO_PT x prior points,
    # ~0.6 of a full Elo scale) and not from last season's Elo; carryover and conference regression are reported only
    ship = {'ship538': search(LIVEP, ['k', 'home', 'a', 'b', 'cap', 'kEarly', 'kWeeks']),
            'shipLin': search({**LIVEP, 'mov': 'lin', 'k': 20, 'cap': 99}, ['k', 'home', 'cap', 'kEarly', 'kWeeks'])}
    data['ship'] = {}
    for name, P in ship.items():
        ev = ev_of(P)
        data['ship'][name] = {'params': P, **summary(ev), 'vsLive': compare(ev, ref), 'map': [r4(x) for x in ev['b']], 'sigma': r4(ev['sigma'])}
        print(name, P, summary(ev), compare(ev, ref), flush=True)
    evL = ev_of(ship['shipLin'])
    data['ship']['linVs538'] = compare(evL, ev_of(ship['ship538']))
    # the live grid (cfb_model.mjs refits K and home on each run) under the linear rule
    data['ship']['linGrid'] = [{'k': k, 'home': h, **summary(ev_of({**ship['shipLin'], 'k': k, 'home': h}))}
                               for k in (15, 20, 25, 30, 40) for h in (20, 40, 55, 70)]
    # by week, held out
    wk = np.concatenate([[g['w'] for g in G[S]['rows'] if g['fbsGame']] for S in HOLD])
    buckets = {'wk 0-2': wk <= 2, 'wk 3-4': (wk >= 3) & (wk <= 4), 'wk 5-8': (wk >= 5) & (wk <= 8), 'wk 9+': (wk >= 9) & (wk < 20), 'bowls': wk >= 20}
    data['byWeekHold'] = {b: {'n': int(k.sum()), 'maeLive': r4(ref['hold']['ae'][k].mean()), 'maeLin': r4(evL['hold']['ae'][k].mean()),
                              'llLive': r4(ref['hold']['ll'][k].mean()), 'llLin': r4(evL['hold']['ll'][k].mean())} for b, k in buckets.items()}
    print('byWeek', data['byWeekHold'], flush=True)
    # 2/3. market for the live rule, the ship candidates and the best variant
    best_name = min(data['variants'], key=lambda n: obj(ev_of(variants[n])))
    data['bestVariant'] = best_name
    data['market'] = {'live': market(G, Y, C, ref), 'shipLin': market(G, Y, C, evL), best_name: market(G, Y, C, ev_of(variants[best_name]))}
    print('market', json.dumps(data['market']), flush=True)
    # season simulation spread, on the live rule and the linear ship candidate (close to the full model's accuracy:
    # held-out MAE ~12.7 against the model's ~12.6 in its 2025-26 CV)
    for name, P in (('live', LIVEP), ('shipLin', ship['shipLin'])):
        rows = sim_eval(G, P, ev_of(P))
        ref4 = next(r for r in rows if r['form'] == 'fixed' and r['u'] == 4)
        top = min(rows, key=lambda r: r['_ll_tune'].mean())
        bestFixed = min((r for r in rows if r['form'] == 'fixed'), key=lambda r: r['_ll_tune'].mean())
        for r in rows:
            for part in ('tune', 'hold'):
                d, t = paired(r['_ll_' + part], ref4['_ll_' + part])
                r[part]['vsFixed4'] = {'d': r4(d), 't': round(t, 2)}
                d, t = paired(r['_ll_' + part], bestFixed['_ll_' + part])
                r[part]['vsBestFixed'] = {'d': r4(d), 't': round(t, 2)}
        for r in rows:
            r.pop('_ll_tune'), r.pop('_ll_hold')
        data.setdefault('sim', {})[name] = {'sigma': r4(ev_of(P)['sigma']), 'best': [top['form'], top['u']], 'bestFixed': bestFixed['u'],
                                            'forms': sorted(rows, key=lambda r: r['tune']['logLoss'])}
        print('sim', name, [(r['form'], r['u'], r['tune']['logLoss'], r['hold']['logLoss'], r['tune']['vsFixed4'], r['hold']['vsFixed4'], r['hold']['vsBestFixed']) for r in data['sim'][name]['forms'][:8]], flush=True)
    with open(OUT, 'w') as f:
        json.dump(data, f, indent=1)


if __name__ == '__main__':
    main()
