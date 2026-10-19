#!/usr/bin/env python3
"""Research on the college basketball game model (scripts/cbb_games.py) -> data/cbb_games_research.json.
Every test is the fit's walk-forward (each season scored from the seasons before), tuned or chosen on 2016-20 and
reported on 2021-26 held out; a change is kept only at paired per-game t <= -1.5 on 2016-20 and not worse on 2021-26.

    python3 scripts/cbb_games_research.py totals   # totals: the efficiency total's parts, tempo shrinkage, market total
    python3 scripts/cbb_games_research.py totals2  # totals: tempo knobs by coordinate search, then inputs by forward selection
    python3 scripts/cbb_games_research.py wp       # win probability sd widening with fewer games played (log loss)
    python3 scripts/cbb_games_research.py sims     # season sims: the rating shock, scored on past seasons' rest of season
    python3 scripts/cbb_games_research.py blend    # model/close blend weight by season
"""
import gzip
import json
import math
import os
import pickle
import re
import sys
from collections import defaultdict

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

import cbb_games as C

OUT = os.path.join(C.ROOT, 'data', 'cbb_games_research.json')
CUTS = ['12-01', '01-15', '02-15']       # season sims start the morning of these dates
NSIM = 2000
POST = re.compile(r'tournament|championship|playoff', re.I)


def regular(g):
    """a regular-season game (conference tournaments and March left out, as the daily sims do)"""
    return g.get('stype') != 3 and not (g.get('conf') and POST.search(g.get('note') or ''))


def walk(P, tag, cuts=False):
    """the fit's walk with the shipped params P, every game's inputs plus the rating parts (and, with cuts, every
    team's ratings the morning of each sim date). Cached by tag in scripts/.cache."""
    p = os.path.join(C.CACHE, f'research_{tag}.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    global _ALL
    if '_ALL' not in globals():
        _ALL = C.load_all()
    games, btname, d1s, tprior, avs = _ALL
    W = C.Walk(P, tprior, btname)
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    rows, snaps = [], {}
    for s in sorted(by_s):
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
        teams = sorted(d1s[s])

        def collect(g, x, tx, R):
            d = C.et_date(g['date'])
            if cuts:
                for c in CUTS:
                    cd = f'{s - 1 if c >= "08" else s}-{c}'
                    if d >= cd and (s, c) not in snaps:
                        snaps[(s, c)] = {'date': cd, 'net': {t: float(R.net(t)) for t in teams}, 'T': {t: float(R.T[R.i(t)]) for t in teams},
                                         'tau': float(R.tau), 'mkt': {t: W.mkt[t] for t in teams}, 'ng': {t: R.ng[t] for t in teams}}
            if g.get('hs') is None:
                return
            H, A = R.i(g['home']), R.i(g['away'])
            e = {'P': float(R.poss(g['home'], g['away'])), 'mu': float(R.mu), 'eh': float(R.mu + R.O[H] - R.D[A]),
                 'ea': float(R.mu + R.O[A] - R.D[H]), 'ngh': R.ng[g['home']], 'nga': R.ng[g['away']]}
            rows.append((g, x, tx, e))
        C.season_walk(W, s, gs, d1s[s], avs.get(s), collect)
    out = (rows, snaps, {s: sorted(v) for s, v in d1s.items()})
    os.makedirs(C.CACHE, exist_ok=True)
    pickle.dump(out, open(p, 'wb'))
    return out


def base_P():
    return json.load(open(C.FIT))['params']


def arrays(rows):
    D = [r for r in rows if r[0]['season'] >= C.FIRST + 1]
    S = np.array([g['season'] for g, *_ in D])
    d1 = np.array([g['home'] != C.X and g['away'] != C.X and 'hb' in g for g, *_ in D])
    return D, S, d1


def save(key, val):
    R = json.load(open(OUT)) if os.path.exists(OUT) else {}
    R[key] = val
    with open(OUT, 'w') as f:
        json.dump(R, f, indent=1)


def tstats(e1, e0, tune, held):
    return {'tune': round(float(e1[tune].mean()), 4), 'tuneBase': round(float(e0[tune].mean()), 4), 't': round(C.paired_t(e1[tune], e0[tune]), 2),
            'held': round(float(e1[held].mean()), 4), 'heldBase': round(float(e0[held].mean()), 4), 'heldT': round(C.paired_t(e1[held], e0[held]), 2)}


# ---------------------------------------------------------------- 1. totals
def tfeats(D):
    """candidate total inputs per game"""
    out = []
    for g, x, tx, e in D:
        P, mu = e['P'], e['mu']
        early = max(0.0, 1 - min(e['ngh'], e['nga']) / 10)
        out.append({'efft': tx['efft'], 'tmkt': tx['tmkt'], 'one': 1.0,
                    'pace': 2 * mu * P / 100,                              # possessions at the league's points a possession
                    'ppp': (e['eh'] + e['ea'] - 2 * mu) * P / 100,          # both matchups' efficiency above the league
                    'home': 0.0 if g['neutral'] else 1.0, 'conf': 1.0 if g.get('conf') else 0.0,
                    'early': (tx['efft'] - tx['tmkt']) * early, 'post': 0.0 if regular(g) else 1.0})
    return out


def totals():
    P = base_P()
    variants = {'base': {}, 'tlam1': {'tlam': 1.0}, 'tlam2': {'tlam': 2.0}, 'tlam8': {'tlam': 8.0}, 'tlam16': {'tlam': 16.0},
                'tcarry0.3': {'tcarry': 0.3}, 'tcarry0.8': {'tcarry': 0.8}, 'tk0.1': {'tk': 0.1}, 'tk0.35': {'tk': 0.35}}
    sets = {'current': ['efft', 'tmkt', 'one'], 'split': ['pace', 'ppp', 'tmkt', 'one'], '+home': ['efft', 'tmkt', 'one', 'home'],
            '+conf': ['efft', 'tmkt', 'one', 'conf'], '+early': ['efft', 'tmkt', 'one', 'early'], '+post': ['efft', 'tmkt', 'one', 'post'],
            'split+home+conf+early': ['pace', 'ppp', 'tmkt', 'one', 'home', 'conf', 'early']}
    res = {'note': 'total MAE vs the actual total, D-I games with a closing total; t paired per game against the shipped '
                   'totals (current inputs, shipped params). Walk variants change the tempo ridge (tlam: prior weight in games, '
                   'shipped = lam 4), tempo carried over (tcarry 0.6) or the market total rating step (tk 0.2).', 'sets': {}, 'walks': {}}
    base_err = None
    for name, ch in variants.items():
        rows, _, _ = walk(dict(P, **ch), 'tot_' + name)
        D, S, d1 = arrays(rows)
        F = tfeats(D)
        ty = np.array([g['hs'] + g['as'] for g, *_ in D], float)
        tline = np.array([g['total'] if g.get('total') else np.nan for g, *_ in D])
        ok = d1 & ~np.isnan(tline) & (S >= C.SCORE0)
        tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
        for sn, fs in (sets.items() if name == 'base' else [('current', sets['current'])]):
            Xm = np.array([[f[k] for k in fs] for f in F])
            pred = C.walk_pred(Xm, ty, S, d1)
            err = np.abs(pred - ty)
            if base_err is None:
                base_err = err
                le = np.abs(tline - ty)
                res['line'] = {'tune': round(float(le[tune].mean()), 4), 'held': round(float(le[held].mean()), 4)}
                # the shipped totals blended with the closing total (weight fit on 2016-20)
                ws = np.arange(0, 1.01, 0.05)
                wb = float(ws[np.argmin([np.mean(np.abs(w * pred[tune] + (1 - w) * tline[tune] - ty[tune])) for w in ws])])
                be = np.abs(wb * pred + (1 - wb) * tline - ty)
                res['blend'] = {'w': wb, 'tune': round(float(be[tune].mean()), 4), 'held': round(float(be[held].mean()), 4),
                                'heldTvsLine': round(C.paired_t(be[held], le[held]), 2)}
            r = tstats(err, base_err, tune, held)
            r['heldVsLine'] = round(float(err[held].mean() - np.abs(tline - ty)[held].mean()), 4)
            if name == 'base':
                r['feats'] = fs
                res['sets'][sn] = r
            else:
                res['walks'][name] = dict(r, change=ch)
            print(name, sn, r, flush=True)
    save('totals', res)


TSETS = ['efft', 'tmkt', 'one']
TCANDS = ['pace', 'ppp', 'home', 'conf', 'early', 'post']


def tot_score(rows, fs):
    D, S, d1 = arrays(rows)
    F = tfeats(D)
    ty = np.array([g['hs'] + g['as'] for g, *_ in D], float)
    tline = np.array([g['total'] if g.get('total') else np.nan for g, *_ in D])
    ok = d1 & ~np.isnan(tline) & (S >= C.SCORE0)
    Xm = np.array([[f[k] for k in fs] for f in F])
    pred = C.walk_pred(Xm, ty, S, d1)
    return np.abs(pred - ty), ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END), np.abs(tline - ty), pred


def totals2():
    """the tempo/market-total knobs by coordinate search on 2016-20 total MAE (current inputs), then the inputs by
    forward selection (t <= -1.5), the result against the shipped totals; the margin re-scored on the new walk"""
    F0 = json.load(open(C.FIT))
    P = dict(F0['params'])
    P.setdefault('tlam', P['lam'])
    tag = lambda Q: 'tot_' + '_'.join(f'{k}{Q[k]}' for k in ('tlam', 'tcarry', 'tk'))
    e0, tune, held, le, _ = tot_score(walk(F0['params'], 'tot_base')[0], TSETS)
    best = float(e0[tune].mean())
    grid = {'tlam': [1.0, 1.5, 2.0, 3.0, 4.0], 'tcarry': [0.6, 0.7, 0.8, 0.9, 1.0], 'tk': [0.2, 0.3, 0.4, 0.5, 0.7]}
    log = []
    for rnd in range(3):
        changed = False
        for k, vals in grid.items():
            for v in vals:
                if v == P[k]:
                    continue
                Q = dict(P, **{k: v})
                e, *_ = tot_score(walk(Q, tag(Q))[0], TSETS)
                m = float(e[tune].mean())
                log.append([k, v, round(m, 4)]); print(rnd, k, v, round(m, 4), flush=True)
                if m < best - 1e-4:
                    best, P, changed = m, Q, True
        if not changed:
            break
    rows = walk(P, tag(P))[0]
    fs = list(TSETS)
    e, *_ = tot_score(rows, fs)
    sel = []
    while True:
        tries = []
        for c in TCANDS:
            if c in fs:
                continue
            f2 = fs + [c]
            if c == 'ppp':
                continue
            if c == 'pace':                          # both parts, in place of the efficiency total
                f2 = [z for z in fs if z != 'efft'] + ['pace', 'ppp']
            e1, *_ = tot_score(rows, f2)
            tries.append((C.paired_t(e1[tune], e[tune]), f2, e1))
        if not tries:
            break
        tries.sort(key=lambda z: z[0])
        for t, f2, e1 in tries:
            sel.append({'with': f2, **tstats(e1, e, tune, held)})
            print('cand', sel[-1], flush=True)
        if tries[0][0] > -1.5:
            break
        fs, e = tries[0][1], tries[0][2]
    e1, _, _, _, pred = tot_score(rows, fs)
    res = {'params': {k: P[k] for k in ('tlam', 'tcarry', 'tk')}, 'feats': fs, 'grid': log, 'select': sel,
           'vsShipped': tstats(e1, e0, tune, held), 'line': {'tune': round(float(le[tune].mean()), 4), 'held': round(float(le[held].mean()), 4)}}
    # the margin on the new walk (the tempo knobs move the efficiency term's possessions)
    D, S, d1 = arrays(walk(F0['params'], 'tot_base')[0])
    p0, y = margin_pred(D, S, d1, F0['feats'])
    D1, S1, d11 = arrays(rows)
    p1, _ = margin_pred(D1, S1, d11, F0['feats'])
    ok = d1 & ~np.isnan(p0)
    res['margin'] = tstats(np.abs(p1 - y), np.abs(p0 - y), ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END))
    print(res)
    save('totals2', res)


# ---------------------------------------------------------------- 2. win probability
def ll_vec(p, win):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(win * np.log(p) + (1 - win) * np.log(1 - p))


def margin_pred(D, S, d1, feats):
    Xm = np.array([[x[f] for f in feats] for _, x, _, _ in D])
    y = np.array([g['hs'] - g['as'] for g, *_ in D], float)
    return C.walk_pred(Xm, y, S, d1), y


def wp():
    from math import erf
    F = json.load(open(C.FIT))
    rows, _, _ = walk(F['params'], 'tot_base')
    D, S, d1 = arrays(rows)
    pred, y = margin_pred(D, S, d1, F['feats'])
    ngh = np.array([e['ngh'] for *_, e in D], float); nga = np.array([e['nga'] for *_, e in D], float)
    ok = d1 & ~np.isnan(pred) & (y != 0)
    tune, held = ok & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    win = (y > 0).astype(float)
    Phi = lambda z: 0.5 * (1 + np.vectorize(erf)(z / math.sqrt(2)))
    sd0 = F['sd']
    l0 = ll_vec(Phi(pred / sd0), win)
    from datetime import datetime
    day = np.array([(datetime.strptime(C.et_date(g['date']), '%Y-%m-%d') - datetime(g['season'] - 1, 11, 1)).days for g, *_ in D], float)
    # the extra variance: by games played (each team, k games to halve it) or by date (linear to 0 at day L)
    forms = {f'games k{k:g}': k / (k + ngh) + k / (k + nga) for k in (3.0, 6.0, 10.0, 20.0, 40.0, 80.0, 160.0)}
    forms.update({f'days L{L}': 2 * np.maximum(0.0, 1 - day / L) for L in (30, 60, 90, 120, 150)})
    res = {}
    grid = []
    for fn, u in forms.items():
        best = None
        for s0 in np.arange(9.6, 12.01, 0.2):
            for c in (0.0, 4.0, 8.0, 16.0, 25.0, 36.0, 50.0, 70.0, 100.0, 140.0):
                l = ll_vec(Phi(pred / np.sqrt(s0 ** 2 + c * u)), win)
                v = float(l[tune].mean())
                grid.append([fn, round(float(s0), 1), c, round(v, 5)])
                if best is None or v < best[0]:
                    best = (v, float(s0), c, l)
        res[fn] = best
    fn = min(res, key=lambda z: res[z][0])
    v, s0, c, l = res[fn]
    r = tstats(l, l0, tune, held)
    r.update({'form': fn, 'sd0': round(s0, 1), 'c': c, 'shippedSd': sd0,
              'formula': 'p = Phi(m / sqrt(sd0^2 + c u)); games k: u = k/(k+gh) + k/(k+ga) (games each team has played); days L: u = 2 max(0, 1 - day/L), day from Nov 1',
              'byForm': {z: dict(tstats(res[z][3], l0, tune, held), sd0=round(res[z][1], 1), c=res[z][2]) for z in res}})
    # where it matters: the first 10 games
    e = ok & (np.minimum(ngh, nga) < 10)
    r['early'] = {'n': int((e & held).sum()), 'heldLl': round(float(l[e & held].mean()), 4), 'heldLlBase': round(float(l0[e & held].mean()), 4),
                  'heldT': round(C.paired_t(l[e & held], l0[e & held]), 2)}
    print(json.dumps(r, indent=0))
    save('winProb', {'best': r, 'grid': grid, 'note': 'log loss of the home win, D-I games (no ties), shipped margin walk-forward; '
                     'grid fit on 2016-20, t paired per game against the shipped constant sd'})


# ---------------------------------------------------------------- 3. season sims
def conferences(games, teams):
    """season's conferences: components of the conference-game graph"""
    par = {t: t for t in teams}

    def f(t):
        while par[t] != t:
            par[t] = par[par[t]]; t = par[t]
        return t
    for g in games:
        if g.get('conf') and g['home'] in par and g['away'] in par and regular(g):
            par[f(g['home'])] = f(g['away'])
    return {t: f(t) for t in teams}


def crps_int(samples, actual, kmax):
    """CRPS of integer sample columns (n x m) against actual (m), by the step CDFs"""
    out = np.zeros(samples.shape[1])
    for k in range(kmax + 1):
        Fk = (samples <= k).mean(0)
        out += (Fk - (actual <= k)) ** 2
    return out


def sims():
    F = json.load(open(C.FIT))
    rows, snaps, d1s = walk(F['params'], 'sims', cuts=True)
    D, S, d1 = arrays(rows)
    feats = F['feats']
    Xm = np.array([[x[f] for f in feats] for _, x, _, _ in D])
    y = np.array([g['hs'] - g['as'] for g, *_ in D], float)
    games = C.load_hist()
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    sd = F['sd']
    # shock configs: sd of each team's strength over the rest of the season, a x sqrt(k / (k + games played)) and a
    # drift b x sqrt(share of its season left); live: a 3, k 8, b 0
    configs = [('live a3 k8', 3, 8, 0)]
    for a in (0, 1, 2, 3, 4, 5):
        configs.append((f'fixed {a}', a, None, 0))
    for a in (2, 4, 6, 8):
        for kk in (4, 8, 16):
            configs.append((f'a{a} k{kk}', a, kk, 0))
    for a in (0, 2, 3, 4):
        for b in (1, 2, 3, 4, 5, 6):
            configs.append((f'a{a} k8 b{b}', a, 8 if a else None, b))
    for a in (1, 2, 3):
        for b in (2, 3, 4, 5, 6):
            configs.append((f'fixed {a} b{b}', a, None, b))
    rec = defaultdict(lambda: defaultdict(list))        # config -> metric -> per team-cut values
    meta = []
    home_mode = {'liveHome': False, 'confHome': True}
    for s in range(C.SCORE0, C.LAST + 1):
        tr = (S < s) & d1
        coef = dict(zip(feats, np.linalg.lstsq(Xm[tr], y[tr], rcond=None)[0]))
        teams = d1s[s]
        ti = {t: i for i, t in enumerate(teams)}
        gs = [g for g in by_s[s] if regular(g) and g['home'] in ti and g['away'] in ti]
        conf = conferences(gs, teams)
        tot_g = np.zeros(len(teams))
        for g in gs:
            tot_g[ti[g['home']]] += 1; tot_g[ti[g['away']]] += 1
        for c in CUTS:
            sn = snaps.get((s, c))
            if not sn:
                continue
            left = [g for g in gs if C.et_date(g['date']) >= sn['date']]
            done = [g for g in gs if C.et_date(g['date']) < sn['date']]
            if len(left) < 50:
                continue
            P0 = sn['tau'] + 2 * float(np.mean([sn['T'][t] for t in teams]))
            mn = float(np.mean([sn['net'][t] for t in teams])); mk = float(np.mean([sn['mkt'][t] for t in teams]))
            rating = np.array([coef['eff'] * (sn['net'][t] - mn) * P0 / 100 + coef.get('mkt', 0) * (sn['mkt'][t] - mk) for t in teams])
            hi = np.array([ti[g['home']] for g in left]); ai = np.array([ti[g['away']] for g in left])
            hm = np.array([0.0 if g['neutral'] else 1.0 for g in left]); cf = np.array([1.0 if g.get('conf') else 0.0 for g in left])
            alt = np.array([1.0 if g['home'] in C.ALT else 0.0 for g in left]) * hm
            hw_act = np.array([g['hs'] > g['as'] for g in left], float)
            nt, ng_ = len(teams), len(left)
            Ih = np.zeros((ng_, nt), np.float32); Ia = np.zeros((ng_, nt), np.float32)
            Ih[np.arange(ng_), hi] = 1; Ia[np.arange(ng_), ai] = 1
            Ihc, Iac = Ih * cf[:, None], Ia * cf[:, None]
            act_w = hw_act @ Ih + (1 - hw_act) @ Ia
            act_cw = hw_act @ Ihc + (1 - hw_act) @ Iac
            # the season's conference standings: done games plus the rest
            cw0 = np.zeros(nt); cl0 = np.zeros(nt)
            for g in done:
                if g.get('conf'):
                    w = g['hs'] > g['as']
                    cw0[ti[g['home']]] += w; cl0[ti[g['home']]] += not w; cw0[ti[g['away']]] += not w; cl0[ti[g['away']]] += w
            ncl = Ihc.sum(0) + Iac.sum(0)
            act_pct = cw0 + act_cw - (cl0 + (ncl - act_cw))
            cid = np.array([conf[t] for t in teams])
            act_title = np.zeros(nt)
            groups = {}
            for cc in set(cid):
                k = cid == cc
                if k.sum() >= 4:
                    groups[cc] = k
                    act_title[k] = act_pct[k] >= act_pct[k].max() - 1e-9
            ng0 = np.array([sn['ng'][t] for t in teams], float)
            left_n = Ih.sum(0) + Ia.sum(0)
            frac = np.where(tot_g > 0, left_n / np.maximum(tot_g, 1), 0)
            has = left_n > 0
            inconf = np.zeros(nt, bool)
            for k in groups.values():
                inconf |= k
            rng = np.random.default_rng(s * 100 + CUTS.index(c))
            Zs = rng.normal(0, 1, (NSIM, nt)).astype(np.float32); Zg = rng.normal(0, 1, (NSIM, ng_)).astype(np.float32)
            meta.append({'season': s, 'cut': sn['date'], 'games': ng_, 'teams': int(has.sum())})
            for mode, ch in home_mode.items():
                mm = rating[hi] - rating[ai] + hm * coef['home']
                if ch:
                    mm = mm + hm * cf * coef.get('confh', 0) + alt * coef.get('alt', 0)
                for name, a, kk, b in (configs if mode == 'confHome' else configs[:1]):
                    tsd = np.sqrt((a ** 2) * (kk / (kk + ng0) if kk else 1.0) + b ** 2 * frac)
                    sh = Zs * tsd.astype(np.float32)
                    m = mm[None, :] + sh[:, hi] - sh[:, ai] + sd * Zg
                    hw = (m > 0).astype(np.float32)
                    w = hw @ Ih + (1 - hw) @ Ia
                    cw = hw @ Ihc + (1 - hw) @ Iac
                    pct = cw0 + cw - (cl0 + (ncl - cw))
                    title = np.zeros(nt)
                    for k in groups.values():
                        top = pct[:, k].max(1, keepdims=True)
                        title[k] = (pct[:, k] >= top - 1e-9).mean(0)
                    key = name if mode == 'confHome' else name + ' (home only)'
                    R = rec[key]
                    R['season'] += [s] * int(has.sum())
                    R['crpsW'] += list(crps_int(w[:, has], act_w[has], int(left_n.max())))
                    R['maeW'] += list(np.abs(w[:, has].mean(0) - act_w[has]))
                    R['crpsCW'] += list(crps_int(cw[:, has], act_cw[has], int(ncl.max())))
                    pt = np.clip(title[inconf], 0.5 / NSIM, 1 - 0.5 / NSIM)
                    R['llTitle'] += list(ll_vec(pt, act_title[inconf]))
                    R['seasonT'] += [s] * int(inconf.sum())
            print(s, c, ng_, flush=True)
    base = rec['live a3 k8']
    st = np.array(base['season']); stt = np.array(base['seasonT'])
    out = {}
    for name, R in rec.items():
        r = {}
        for mtr in ('crpsW', 'maeW', 'crpsCW', 'llTitle'):
            v, v0 = np.array(R[mtr]), np.array(base[mtr])
            ss = stt if mtr == 'llTitle' else st
            r[mtr] = tstats(v, v0, ss <= C.TUNE_END, ss > C.TUNE_END)
        out[name] = r
    best = min((n for n in out if 'home only' not in n), key=lambda n: out[n]['crpsW']['tune'])
    print('best', best, out[best])
    save('sims', {'note': 'past seasons from the morning of Dec 1, Jan 15, Feb 15: the rest of the regular season (conference '
                  'tournaments and March left out) simulated %d times from the walk-forward ratings (power rating as the daily '
                  'build makes it, weights fit on the seasons before), each game normal around its margin with the fit sd; '
                  'each team\'s strength drawn once with sd sqrt(a^2 k/(k+games played) + b^2 x share of its season left) '
                  '(a 0 or k none: fixed a). Scored per team and cut: CRPS of rest-of-season wins and conference wins, MAE of '
                  'expected wins, log loss of a share of the conference title. t paired per team-cut against the live shock '
                  '(a 3, k 8, b 0, with confh/alt home terms); "(home only)" is the live build\'s margin, home court in every '
                  'game without the conference-home and altitude terms.' % NSIM, 'cuts': meta, 'configs': out, 'bestTune': best})


# ---------------------------------------------------------------- 4. blend
def blend():
    F = json.load(open(C.FIT))
    rows, _, _ = walk(F['params'], 'tot_base')
    D, S, d1 = arrays(rows)
    pred, y = margin_pred(D, S, d1, F['feats'])
    line = np.array([-g['spread'] if g.get('spread') is not None else np.nan for g, *_ in D])
    ok = d1 & ~np.isnan(pred) & ~np.isnan(line)
    ws = np.round(np.arange(0, 1.01, 0.05), 2)
    w0 = F['blend']
    out = {'shipped': w0, 'bySeason': {}}
    lw = {}
    for s in range(C.SCORE0, C.LAST + 1):
        k = ok & (S == s)
        maes = [float(np.mean(np.abs(w * pred[k] + (1 - w) * line[k] - y[k]))) for w in ws]
        bw = float(ws[int(np.argmin(maes))])
        # walk-forward weight: fit on every season before (2016 from 2015)
        kp = ok & (S < s) & (S >= C.FIRST + 1)
        wf = float(ws[int(np.argmin([np.mean(np.abs(w * pred[kp] + (1 - w) * line[kp] - y[kp])) for w in ws]))]) if kp.any() else w0
        lw[s] = wf
        e_b = np.abs(w0 * pred[k] + (1 - w0) * line[k] - y[k]); e_l = np.abs(line[k] - y[k])
        out['bySeason'][s] = {'games': int(k.sum()), 'bestW': bw, 'maeBest': round(min(maes), 4), 'maeLine': round(float(e_l.mean()), 4),
                              'maeShipped': round(float(e_b.mean()), 4), 'tShippedVsLine': round(C.paired_t(e_b, e_l), 2), 'walkW': wf}
        print(s, out['bySeason'][s])
    for nm, kk in (('tune', ok & (S >= C.SCORE0) & (S <= C.TUNE_END)), ('held', ok & (S > C.TUNE_END))):
        e_b = np.abs(w0 * pred[kk] + (1 - w0) * line[kk] - y[kk]); e_l = np.abs(line[kk] - y[kk])
        wwf = np.array([lw.get(int(s), w0) for s in S[kk]])
        e_w = np.abs(wwf * pred[kk] + (1 - wwf) * line[kk] - y[kk])
        out[nm] = {'games': int(kk.sum()), 'maeLine': round(float(e_l.mean()), 4), 'maeShipped': round(float(e_b.mean()), 4),
                   'tShippedVsLine': round(C.paired_t(e_b, e_l), 2), 'maeWalkW': round(float(e_w.mean()), 4), 'tWalkWVsLine': round(C.paired_t(e_w, e_l), 2)}
    out['note'] = ('margin MAE of w x model + (1 - w) x close, D-I games with a close; bestW is in-sample for that season, walkW fit '
                   'on the seasons before it. Report only: the page shows the model margin, not the blend.')
    print(out['tune'], out['held'])
    save('blend', out)


if __name__ == '__main__':
    {'totals': totals, 'totals2': totals2, 'wp': wp, 'sims': sims, 'blend': blend}[sys.argv[1]]()
