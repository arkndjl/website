#!/usr/bin/env python3
"""Research: FV as the prior for low-sample players (Noah, Oct 29 2026: "project game impact for provisional players /
players with not a lot of games played based on their FV").

    python3 scripts/fv_lowsample_research.py nba      # player level, NBA years 2-4 -> data/fv_lowsample_research.json

NBA. Rookies already enter at slot + final college BPM, and the board's FV adds nothing to that on rookie-season XPM
(data/fv_mean_games.json). The untested group is years 2-4: their prior is the last two seasons' XPM shrunk toward
-1.0 with 600 minutes, so a 2nd-year player with 300 minutes sits two thirds of the way to a newcomer. Candidates
shrink them instead toward an entry prior (the slot + college BPM curve, fit on earlier classes) plus the board's
draft-season grade. Target: season-S XPM weighted by season-S minutes; walk-forward by season (fit only on seasons
before S). Kept by the usual rule: paired t <= -1.5 on 2015-21, 2022-26 no worse.

    python3 scripts/fv_lowsample_research.py nbagames # game level: nba_games ypf (fitted years 2-4 prior), ~1.5 min/walk
    python3 scripts/fv_lowsample_research.py nhl      # NHL newcomers at replacement + hockey draft grade, players + games
    OMP_NUM_THREADS=1 python3 scripts/fv_lowsample_research.py cbb   # CBB 'inj' term, FV-implied BPM prior, ~6 min

Results (Oct 29 2026), nothing shipped:
- NBA players, years 2-4 (1,589 player seasons): FV on top of the slot + college BPM entry prior t +0.0 / -1.0 (k 600);
  FV alone worse than the entry prior. The fitted entry prior itself (intercept ~+1 XPM development, shrink k 600)
  beats the shipped -1.0 shrink t -2.4 / -4.3, but in the game model (ypf 1) t +0.9 / +0.7 worse, and without the
  development level (ypf 2) no better: the ratings and lineup baseline already carry it (as with ypk, age, in-season).
- CBB: absent freshmen / everyone shrunk to FV-implied BPM (pk 150/400) in place of -1: tune t -1.0..+1.4, held worse.
- NHL newcomers (no line or <200 min last season) at replacement + grade offset (~.005 GAR/60 per FV point): players
  t -1.7 / -0.9; games all-seasons tune t +2.3 helps, lined tune +1.3, held out 2024-26 worse in both (-.5 / -.7).
- CFB: non-QB players are already priced by FV (starters, injury WAR); backup QBs sit at replacement EPA, but the QB
  test needs the CFBD model dump (2025-26 only), too few QB changes to pass a gate. Not run.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_games as N
import nba_prior_research as R

OUT = os.path.join(N.ROOT, 'data', 'fv_lowsample_research.json')


def save(key, block):
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d[key] = block
    json.dump(d, open(OUT, 'w'), indent=1)


def nba_rows():
    brd, cb = R.board(), N.rookie_college()
    rows = []
    for S in range(2013, 2027):
        xf = R.xfile(S)
        pc = N.pick_curves(S)
        if not xf or not pc:
            continue
        vcur, _, ccur = pc
        for d, picks in N.draft().items():
            yr = S - 1 - d
            if not 1 <= yr <= 3:
                continue
            for pk, bid, nm, _ in picks:
                p = xf.get(bid)
                if not p or not p.get('mp') or p.get('pr'):
                    continue
                a, b = N.lookup(S - 1, nm), N.lookup(S - 2, nm)
                m = (a[1] if a else 0.0) + (0.5 * b[1] if b and yr >= 2 else 0.0)
                sx = (a[0] * a[1] if a else 0.0) + (0.5 * b[0] * b[1] if b and yr >= 2 else 0.0)
                bd = brd.get((N.norm(nm), d))
                rows.append({'S': S, 'yr': yr, 'n': nm, 'pk': pk, 'y': p['xpm'], 'w': p['mp'], 'm': m,
                             'xb': sx / m if m else 0.0,
                             'cur': N.values(S, {0: nm}, 600.0, -1.0)[0],
                             'pv': ccur(pk, cb[bid]) if ccur and bid in cb else vcur(pk),
                             'fvx': bd['fvx'] if bd else None, 'fvg': bd['fvg'] if bd else None})
    return rows


def wf(rows, M):
    S = np.array([r['S'] for r in rows]); y = np.array([r['y'] for r in rows]); w = np.array([r['w'] for r in rows])
    pr = np.full(len(rows), np.nan)
    for s in sorted(set(S)):
        tr, te = S < s, S == s
        if tr.sum() < 150:
            continue
        pr[te] = M[te] @ R.wls(M[tr], y[tr], w[tr])
    return pr


def score(rows, pr, ref, sub=None):
    S = np.array([r['S'] for r in rows]); y = np.array([r['y'] for r in rows]); w = np.array([r['w'] for r in rows])
    out = {}
    for nm, k in (('2015_21', (S >= 2015) & (S < 2022)), ('2022_26', S >= 2022)):
        k = k & ~np.isnan(pr) & ~np.isnan(ref)
        if sub is not None:
            k = k & sub
        e = w[k] * (pr[k] - y[k]) ** 2 / w[k].mean(); e0 = w[k] * (ref[k] - y[k]) ** 2 / w[k].mean()
        out[nm] = {'n': int(k.sum()), 'rmse': round(math.sqrt(e.mean()), 4),
                   'd': round(math.sqrt(e.mean()) - math.sqrt(e0.mean()), 4), 't': round(R.paired_t(e, e0), 2)}
    return out


def nba():
    rows = nba_rows()
    m = np.array([r['m'] for r in rows]); xb = np.array([r['xb'] for r in rows])
    pv = np.array([r['pv'] for r in rows])
    fvx = np.array([r['fvx'] if r['fvx'] is not None else np.nan for r in rows])
    fvg = np.array([r['fvg'] if r['fvg'] is not None else np.nan for r in rows])
    nof = np.isnan(fvx).astype(float)
    fvx = np.where(np.isnan(fvx), 28.0, fvx); fvg = np.where(np.isnan(fvg), 28.0, fvg)
    cur = np.array([r['cur'] for r in rows])
    one = np.ones(len(rows))
    res = {'n': len(rows), 'onBoard': int((nof == 0).sum()), 'by_k': {}}
    ref = wf(rows, np.column_stack([one, cur]))          # the shipped prior, recalibrated walk-forward
    raw = cur.copy()
    S = np.array([r['S'] for r in rows])
    res['shipped_raw_vs_recal'] = score(rows, raw, ref)
    low = m < 1000
    for k in (300, 600, 1000, 1500, 2500):
        sh = m / (m + k); q = 1 - sh
        cands = {
            'flat': [sh * xb, q],
            'entry': [sh * xb, q, q * pv],
            'entry+fvx': [sh * xb, q, q * pv, q * fvx, q * nof],
            'entry+fvg': [sh * xb, q, q * pv, q * fvg, q * nof],
            'fvx only': [sh * xb, q, q * fvx, q * nof],
        }
        blk = {}
        for nm, cols in cands.items():
            pr = wf(rows, np.column_stack([one] + cols))
            blk[nm] = {'all': score(rows, pr, ref), 'under1000': score(rows, pr, ref, low)}
            print(k, nm, blk[nm]['all']['2015_21'], blk[nm]['all']['2022_26'], '| low', blk[nm]['under1000']['2015_21']['t'], blk[nm]['under1000']['2022_26']['t'], flush=True)
        res['by_k'][k] = blk
    save('nba', res)


def nbagames():
    """game level: the live NBA model vs ypf (years 2-4 at nba_games.young_value), same walk-forward as the fit, MAE
    on final margins, 2015-21 selection / 2022-26 held out; openers = before both teams' 15th game"""
    import nba_games_fit as Fit
    F = json.load(open(N.FIT))
    games, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']

    def design(params):
        _, data = N.walk(games, names, P, params, inj=inj)
        D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x in D], float) for f in D[0][1]}
        return X, np.array([g['hs'] - g['as'] for g, _ in D], float), np.array([g['S'] for g, _ in D]), \
            np.array([g['L'] if g.get('L') is not None else np.nan for g, _ in D])
    X0, y, S, line = design(base)
    early = X0['gpn'] < 15
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    out = []
    for lab, extra in (('ypf', {'ypf': 1}), ('ypf, no development level', {'ypf': 2})):
        X, _, _, _ = design({**base, **extra})
        pr = Fit.wf(Fit.mat(X, feats), y, S)
        r = {'label': lab}
        for nm, k in (('2015_21', (S >= N.SCORE_FROM) & (S < N.HOLD_FROM)), ('2022_26', S >= N.HOLD_FROM)):
            for sub, kk in (('all', k), ('openers', k & early)):
                e, e0 = np.abs(pr[kk] - y[kk]), np.abs(ref[kk] - y[kk])
                r[sub + nm] = {'n': int(kk.sum()), 'mae': round(float(e.mean()), 4), 'd': round(float(e.mean() - e0.mean()), 4),
                               't': round(Fit.paired_t(e, e0), 2), 'maeLine': round(float(np.nanmean(np.abs(line[kk] - y[kk]))), 4)}
        print(json.dumps(r), flush=True)
        out.append(r)
    save('nbagames', out)


# ---------------------------------------------------------------- NHL
def nhl_grades():
    """NHL id -> draft grade: the class-out grade for 2008-19 picks the board lists (data/hockey.json past), else the
    draft model's grade (data/hockey_fit.json coef; fit on 2008-19, so out of sample for 2020+ classes)"""
    import gzip
    import hockey_prospects as HP
    H = json.load(open(os.path.join(N.ROOT, 'data', 'hockey.json')))
    rows = json.load(gzip.open(os.path.join(HERE, 'data', 'hockey_rows.json.gz')))
    C = json.load(open(os.path.join(N.ROOT, 'data', 'hockey_fit.json')))['coef']
    idm = {(r['year'], r['pick']): r for r in rows}
    fv = {}
    for p in H['past']:
        r = idm.get((p['year'], p['pick']))
        if r and r['id']:
            fv[r['id']] = float(p['fv'])
    for r in rows:
        if r['id'] and r['id'] not in fv:
            f = HP.feats(r)
            fv[r['id']] = C['const'] + sum(C[k] * f[k] for k in C if k != 'const')
    return fv


def nhl_newcomers():
    """skater newcomers (no line, or under 200 minutes, the season before): rows (S, has grade, grade, GAR a 60, TOI, D)
    and S -> {id: value offset}. Offset = GAR a 60 on a + D + graded + grade line minus the line without the grade,
    both fit (TOI-weighted) on seasons before S, so the average newcomer stays at replacement"""
    fv = nhl_grades()
    W = {}
    for S in range(2009, 2027):
        fn = os.path.join(N.ROOT, 'static', 'data', 'nhl-war', f'{S}.json')
        if os.path.exists(fn):
            W[S] = {p['id']: p for p in json.load(open(fn))['players'] if p['grp'] in ('F', 'D')}
    R, ids = [], []
    for S in range(2011, 2027):
        if S - 1 not in W:
            continue
        for i, p in W[S].items():
            if (i not in W[S - 1] or W[S - 1][i]['toi'] < 200) and p['toi'] > 0:
                R.append((S, i in fv, fv.get(i, 0.0), p['gar'] / p['toi'] * 60, p['toi'], p['grp'] == 'D')); ids.append(i)
    A = np.array(R, float)
    S, hf, f, y, w, D = (A[:, k] for k in range(6))
    one = np.ones(len(y))
    M0, M1 = np.column_stack([one, D]), np.column_stack([one, D, hf, hf * (f - 30)])
    off = {}
    pr0, pr1 = np.full(len(y), np.nan), np.full(len(y), np.nan)
    for s in range(2013, 2028):
        tr = S < s
        b0, b1 = R_wls(M0[tr], y[tr], w[tr]), R_wls(M1[tr], y[tr], w[tr])
        te = S == s
        pr0[te], pr1[te] = M0[te] @ b0, M1[te] @ b1
        # live offsets for every graded player (by id), D or F doesn't change the gap
        off[s] = {i: float(b1[2] + b1[3] * (g - 30)) for i, g in fv.items()}
    return (S, y, w, pr0, pr1), off


def R_wls(X, y, w):
    return R.wls(X, y, w)


def nhl():
    """player level, then the game model: newcomers at replacement plus their grade's offset (in place of rv's
    replacement level). Game gate as nhl_games.passes: log loss t >= 1.5 on tuning, held out > -1, lined and all games"""
    import nhl_games as G
    (S, y, w, pr0, pr1), off = nhl_newcomers()
    out = {'player': {}}
    for nm, k in (('2013_20', (S >= 2013) & (S < 2021)), ('2021_26', S >= 2021)):
        e1, e0 = w[k] * (pr1[k] - y[k]) ** 2 / w[k].mean(), w[k] * (pr0[k] - y[k]) ** 2 / w[k].mean()
        out['player'][nm] = {'n': int(k.sum()), 'rmse': round(math.sqrt(e1.mean()), 4), 'rmse0': round(math.sqrt(e0.mean()), 4), 't': round(R.paired_t(e1, e0), 2)}
    print(out['player'], flush=True)
    F = json.load(open(G.FIT))
    P, feats = F['params'], F['feats']
    hist = G.load_hist()
    _, rows0, _ = G.walk(hist, P)
    lv0 = G.lineup_value

    def lv(Sx, gid, t):
        ids = G._lineups(Sx).get(str(gid), {}).get(t)
        v = lv0(Sx, gid, t)
        if v is None:
            return v
        ps, repl, avg = G._war(Sx)
        for x in ids:
            if x[:-1] not in ps and x[:-1] in off.get(Sx, {}):
                v += off[Sx][x[:-1]] * avg[x[-1]] / 3600
        return v
    G.lineup_value = lv
    G._LV.clear() if hasattr(G, '_LV') else None
    _, rows1, _ = G.walk(hist, P)
    G.lineup_value = lv0
    assert [g['id'] for g, _ in rows0] == [g['id'] for g, _ in rows1]
    for (g, f0), (_, f1) in zip(rows0, rows1):
        f0['rvf'] = f1['rv']
    alt = [x if x != 'rv' else 'rvf' for x in feats] if 'rv' in feats else feats + ['rvf']
    import harness as H
    Sx, yy, m, tot, pc, tc, day = G.arrays(rows0)
    out['games'] = {'feats': feats}
    for lab, lined, first, tune_s in (('lined', True, G.FIRST_TEST, G.TUNE), ('all', False, G.SCORE_FROM + 1, (G.SCORE_FROM + 1, G.TUNE[1]))):
        ok = ~np.isnan(pc) if lined else np.ones(len(yy), bool)
        l0 = H.logloss(G.walk_logit(G.design(rows0, feats), yy, Sx, first, ok), yy)
        l1 = H.logloss(G.walk_logit(G.design(rows0, alt), yy, Sx, first, ok), yy)
        r = {}
        for nm, k in (('tune', (Sx >= tune_s[0]) & (Sx <= tune_s[1]) & ok), ('held', (Sx >= G.HOLD_FROM) & ok)):
            k = k & ~np.isnan(l0) & ~np.isnan(l1)
            pr = H.paired(l0[k], l1[k], day[k])
            r[nm] = {'n': int(k.sum()), 'dLL1000': round(float((l1[k] - l0[k]).mean()) * 1000, 3), 'tHelps': round(pr['t'], 2)}
        out['games'][lab] = r
        print(lab, r, flush=True)
    save('nhl', out)


# ---------------------------------------------------------------- college basketball
_A = {}


def cbb_fv_bpm():
    """season -> {Barttorvik pid: (expected BPM from the board's preseason E[FV], group)}. E[FV] as cbb_games.team_fv
    builds it: returners and transfers from last season's line ('returner' model), freshmen from recruit rank
    ('newcomer'). E[FV] -> BPM: minutes-weighted line per group, fit on seasons before"""
    import csv
    import cbb_games as C
    by = {}
    for r in csv.DictReader(open('/mnt/project-files/cbb/backtest/research_seasons.csv')):
        by.setdefault(int(r['year']), {})[r['pid']] = r
    E = {}
    for y in range(C.FIRST - 3, C.LAST + 1):
        E[y] = {}
        for pid, r in by.get(y, {}).items():
            p = by.get(y - 1, {}).get(pid)
            if p and p['min_per']:
                e, g = C.player_fv(C.research_feats(p, r['team']), 'returner'), 'ret'
            elif r['yr'] == 'Fr':
                lr = [-math.log(min(float(v), 500)) for v in (r.get('on3rk'), r.get('rk247')) if v not in (None, '', 'nan') and float(v) > 0]
                l = sum(lr) / len(lr) if lr else -math.log(600)
                e, g = C.player_fv({'rg_lrk': l, 'top': max(0.0, l + math.log(25)), 'top5': max(0.0, l + math.log(5)), 'yr': 1.0}, 'newcomer'), 'fr'
            else:
                continue
            b, m = r.get('bpm'), r.get('min_per')
            E[y][pid] = (e, g, float(b) if b not in (None, '', 'nan') else None, float(m) if m not in (None, '', 'nan') else 0.0)
    out = {}
    for y in range(C.FIRST, C.LAST + 1):
        coef = {}
        for g in ('ret', 'fr'):
            rows = [(e, b, m) for s in range(C.FIRST - 3, y) for e, gg, b, m in E[s].values() if gg == g and b is not None and m > 0]
            X = np.array([[1.0, e - 20] for e, _, _ in rows]); yy = np.array([b for _, b, _ in rows]); w = np.array([m for _, _, m in rows])
            coef[g] = R.wls(X, yy, w)
        out[y] = {int(pid): (coef[g][0] + coef[g][1] * (e - 20), g) for pid, (e, g, _, _) in E[y].items()}
    return out


def _cbb_one(v):
    import cbb_games as C
    games, btname, d1s, tprior, avs, P, feats, fvb = _A['a']
    lab, grp, pk = v
    if pk:
        av = {s: C.avail(C.bt_logs(s), prior={pid: b for pid, (b, g) in fvb.get(s, {}).items() if g in grp}, pk=pk) for s in avs}
    else:
        av = avs
    _, rows = C.run_walk(P, games, tprior, btname, d1s, av)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    return lab, (C.walk_pred(Xm, y, S, d1), y, S, d1, [g['id'] for g, _, _ in D])


def cbb():
    """game level: the 'inj' term values a rotation player who sat at his to-date BPM shrunk to a flat -1 by 150
    minutes. Variants shrink toward his FV-implied BPM (cbb_fv_bpm) with pk minutes, freshmen only or everyone.
    Tune 2016-20 paired t <= -1.5, 2021-26 no worse"""
    from multiprocessing import get_context
    import cbb_games as C
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    fvb = cbb_fv_bpm()
    _A['a'] = (games, btname, d1s, tprior, avs, F['params'], list(F['feats']), fvb)
    vs = [('live', (), 0.0)] + [(f'{nm} pk{int(pk)}', grp, pk) for nm, grp in (('fr', ('fr',)), ('all', ('fr', 'ret'))) for pk in (150.0, 400.0)]
    with get_context('fork').Pool(int(os.environ.get('PROCS', 4))) as pool:
        res = dict(pool.map(_cbb_one, vs))
    p0, y, S, d1, ids = res['live']
    ok = ~np.isnan(p0) & d1
    tune, held = ok & (S >= C.SCORE0) & (S <= C.TUNE_END), ok & (S > C.TUNE_END)
    e0 = np.abs(p0 - y)
    out = {'live': {'tuneMae': round(float(e0[tune].mean()), 4), 'heldMae': round(float(e0[held].mean()), 4)}, 'variants': []}
    for lab, _, _ in vs[1:]:
        assert res[lab][4] == ids
        e1 = np.abs(res[lab][0] - y)
        r = {'v': lab, 'tuneD': round(float(e1[tune].mean() - e0[tune].mean()), 4), 'heldD': round(float(e1[held].mean() - e0[held].mean()), 4),
             't': round(C.paired_t(e1[tune], e0[tune]), 2), 'heldT': round(C.paired_t(e1[held], e0[held]), 2)}
        r['kept'] = r['t'] <= -1.5 and r['heldD'] <= 0
        out['variants'].append(r)
        print(r, flush=True)
    save('cbb', out)


if __name__ == '__main__':
    {'nba': nba, 'nbagames': nbagames, 'cbb': cbb, 'nhl': nhl}[sys.argv[1]]()
