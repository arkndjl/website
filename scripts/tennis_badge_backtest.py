#!/usr/bin/env python3
"""Backtest: do tennis badges (scripts/tennis_badges.py) predict beyond each board's own grade?

    python3 scripts/tennis_badge_backtest.py            # both boards -> data/tennis_badge_backtest.json
    python3 scripts/tennis_badge_backtest.py pro        # one board (pro | prospects); the other's block is kept

Needs the local caches: scripts/.cache/tennis/hist.json.gz (python3 scripts/tennis_data.py) for the pro board and
scripts/.cache/tennis/rows.pkl (python3 scripts/tennis_prospects.py --download --rows) for the prospects board.

Each badge's stat is measured the way the board would show it: regressed toward the tour pool's volume-weighted
mean with its own k (k = n(1 - r)/r, r = the stat's year-to-year correlation at the mean volume n; r < .15 = noise,
dropped), then z'd within the tour-season pool (players above the badge's volume floor). Tests, per badge and tour:
  t       OLS of the outcome on the board's grade + the badge z, standard error CLUSTERED BY PLAYER (a player's
          seasons share his career)
  oos     out of sample: fold out one season (pro) / one birth year (prospects, the board's own fold), fit outcome ~
          grade (+ badge) on the rest, predict the fold; gain in R^2 x100 (1.0 = one point) and folds won
  pass    t >= 2 (positive: a badge is a good thing) and oos gain > 0; then jointly: a passer whose t falls under 2
          beside a stronger passer measures the same thing and is dropped. Pro board, also: the passer must still pass
          with last season's Elo change and the hard-court Elo added to the grade (a surface Elo gap can be a lagging
          hard-court Elo rather than a trait)
Boards and outcomes:
  pro        TENNIS ARKBOARD (scripts/tennis_model.py): every year-end 2006-24, players in the tour's top 300 by
             ARK with 10+ matches with statistics that year and active the next; outcome = overall Elo change over
             the next season; grade = Elo, logit ARK (the board's headline: the blend of Elo, the serve / return
             point ratings and the games rating against the average top-50 player), age, age^2
  prospects  Tennis prospects (scripts/tennis_prospects.py): October rows, births 1979-97; outcome = peak FV (the
             outcome the board's FV is fitted to); grade = the board's FV held out by birth year
Results (Nov 1 2026; every number in data/tennis_badge_backtest.json):
  pro ATP (4,449 rows, 875 players): Big Server (ace rate, r .89) t 3.3, oos +.10, 11/19 seasons, joint 3.1, robust
          3.2: PASS. Grass Court (grass over hard Elo, r .78) t 4.2, oos +.83, joint 3.2, robust 2.2 (+.17): PASS.
          First Strike t 2.5 but joint -.6 beside Big Server (the same serve trait): out. Second Serve 1.7, Returner
          -1.7, Clay Court .8: fail. Break points saved / converted over expected and tiebreaks: r .02-.04, noise.
  pro WTA (1,858 rows, 476 players): Grass Court t 2.2, oos +.26 but robust t 1.2 (oos -.13): out. Big Server 1.5,
          First Strike .9, Second Serve .7, Clay -.7: fail; Returner t -2.6 (negative: not a badge). Clutch and
          tiebreaks r under .04.
  prospects ATP (32,349 October rows, births 1979-97): Big Server t 1.1, Server .2, Returner .3, Giant Killer -1.5:
          fail; Dominator (game share over the Elo gap) and tiebreaks r .06 / .03, noise.
  prospects WTA (32,948): Server (serve points won, r .40) t 2.01, oos +.12, 11/17 birth years: PASS (t 1.6-2.0
          and a held-out gain at all four snapshots, Jan / Apr / Jul / Oct). Big Server 1.1, Returner -.8, Giant
          Killer 1.4: fail; Dominator, tiebreaks noise.
  Shipped as badges only (no FV or ARK change): ATP rows Big Server + Grass Court, WTA prospects Server.
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import tennis_badges as TB  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'tennis_badge_backtest.json')
CACHE = os.path.join(HERE, '.cache', 'tennis')


# ------------------------------------------------------------------------------------------------ stats helpers

def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_t(X, y, g):
    """OLS coefficients and their t with standard errors clustered by g (CR1)"""
    b = ols(X, y)
    e = y - X @ b
    XtXi = np.linalg.pinv(X.T @ X)
    meat = np.zeros((X.shape[1], X.shape[1]))
    idx = defaultdict(list)
    for i, c in enumerate(g):
        idx[c].append(i)
    for ii in idx.values():
        s = X[ii].T @ e[ii]
        meat += np.outer(s, s)
    G, n, k = len(idx), len(y), X.shape[1]
    V = XtXi @ meat @ XtXi * (G / (G - 1)) * ((n - 1) / (n - k))
    return b, b / np.sqrt(np.diag(V))


def oos(X0, z, y, fold):
    """held-out R^2 gain x100 of adding z (columns) to X0, folding out each value of fold; also folds won"""
    X1 = np.column_stack([X0, z])
    p0, p1 = np.zeros(len(y)), np.zeros(len(y))
    won, nf = 0, 0
    for f in np.unique(fold):
        te = fold == f
        if te.sum() < 5:
            continue
        p0[te] = X0[te] @ ols(X0[~te], y[~te])
        p1[te] = X1[te] @ ols(X1[~te], y[~te])
        won += int(np.sum((y[te] - p1[te]) ** 2) < np.sum((y[te] - p0[te]) ** 2))
        nf += 1
    sst = np.sum((y - y.mean()) ** 2)
    return 100 * (np.sum((y - p0) ** 2) - np.sum((y - p1) ** 2)) / sst, won, nf


def yty(pid, season, v, n, vmin):
    """year-to-year r of the raw stat (player's consecutive seasons, both above the floor) and the mean volume"""
    key = {(a, s): (x, w) for a, s, x, w in zip(pid, season, v, n) if np.isfinite(x) and w >= vmin}
    a, b, w = [], [], []
    for (p, s), (x, nn) in key.items():
        nx = key.get((p, s + 1))
        if nx:
            a.append(x); b.append(nx[0]); w.append(nn)
    if len(a) < 30:
        return float('nan'), float('nan'), len(a)
    return float(np.corrcoef(a, b)[0, 1]), float(np.mean(w)), len(a)


def badge_z(v, n, k, vmin, season):
    """regressed value, z'd within each season's pool (NaN outside the pool)"""
    reg = TB.regress(v, n, k)
    z = np.full(len(v), np.nan)
    pool = (n >= vmin) & np.isfinite(reg)
    for s in np.unique(season):
        m = pool & (season == s)
        if m.sum() >= 10:
            mu, sd = reg[m].mean(), reg[m].std() or 1
            z[m] = (reg[m] - mu) / sd
    return z


def test(cands, ctrl, y, pid, season, fold, use):
    """every candidate's numbers; ctrl: the grade columns (with intercept); use: rows in the test universe"""
    res = {}
    zs = {}
    for key, (name, stat, v, n, vmin) in cands.items():
        r, nbar, npair = yty(pid, season, v, n, vmin)
        c = dict(name=name, stat=stat, vmin=vmin, r=None if not np.isfinite(r) else round(r, 3), pairs=npair)
        if not np.isfinite(r) or r < TB.R_MIN:
            c.update(pass_=False, why='year-to-year r under %.2f' % TB.R_MIN)
            res[key] = c
            continue
        k = TB.k_of(r, nbar)
        z = badge_z(v, n, k, vmin, season)
        m = use & np.isfinite(z)
        b, t = cluster_t(np.column_stack([ctrl[m], z[m]]), y[m], pid[m])
        g, won, nf = oos(ctrl[m], z[m], y[m], fold[m])
        ok = bool(t[-1] >= 2 and g > 0)
        c.update(k=round(k, 1), nbar=round(nbar, 1), n=int(m.sum()), players=int(len(set(pid[m]))), beta=round(float(b[-1]), 3),
                 t=round(float(t[-1]), 2), oos=round(float(g), 3), folds=[won, nf], pass_=ok,
                 why='' if ok else ('negative' if t[-1] <= -2 else 't under 2' if t[-1] < 2 else 'no held-out gain'))
        res[key] = c
        zs[key] = z
    # jointly: the passers together (rows in every passer's pool, the rest at 0 = the pool mean)
    ps = [k for k, c in res.items() if c['pass_']]
    while len(ps) > 1:
        Z = np.column_stack([np.nan_to_num(zs[k]) for k in ps])
        m = use
        b, t = cluster_t(np.column_stack([ctrl[m], Z[m]]), y[m], pid[m])
        tj = dict(zip(ps, t[-len(ps):]))
        for k in ps:
            res[k]['tJoint'] = round(float(tj[k]), 2)
        worst = min(ps, key=lambda k: tj[k])
        if tj[worst] >= 2:
            break
        res[worst].update(pass_=False, why='joint t %.2f beside %s' % (tj[worst], ', '.join(res[k]['name'] for k in ps if k != worst)))
        ps.remove(worst)
    for c in res.values():
        c['pass'] = c.pop('pass_')
    return res


# ------------------------------------------------------------------------------------------------ pro board

def tb_count(score):
    """tiebreaks won by the winner and by the loser"""
    w = l = 0
    for tok in str(score).split():
        a = tok.split('(')[0]
        if a in ('7-6',):
            w += 1
        elif a == '6-7':
            l += 1
    return w, l


def pro_rows():
    import tennis_data as T
    import tennis_model as TM
    rows, players, tn = T.load()
    P = dict(TM.DEFAULT, **json.load(open(TM.FIT)).get('params', {}))
    m = TM.Model(P)
    m.set_bios(players)
    out = []
    agg, mix = {}, defaultdict(lambda: defaultdict(int))
    yr = rows[0][0] // 10000

    def snap(y):
        day = (TM.ymd(y * 10000 + 1231) - TM.DAY0).days
        for tour in ('atp', 'wta'):
            act = [p for p, d in m.last.items() if p[0] == tour[0] and day - d <= 183 and m.nm.get(p, 0) >= 15]
            if len(act) < 60:
                continue
            t = sum(mix[tour].values()) or 1
            mx = {s: mix[tour][s] / t for s in TM.SURFS}
            top = sorted(act, key=lambda p: -m.elo[p][0])[:50]
            ref = 'REF' + tour
            m.elo[ref] = [sum(m.elo[p][0] for p in top) / 50, 999, {s: [sum(m.elo[p][2][s][0] for p in top) / 50, 999] for s in TM.SURFS}]
            m.pt[ref] = [sum(m._pt(p, day)[0] for p in top) / 50, 0.0, sum(m._pt(p, day)[2] for p in top) / 50, 0.0, day]
            m.gr[ref] = [sum(m._g(p)[0] for p in top) / 50, 999, {s: [sum(m._g(p)[2][s][0] for p in top) / 50, 999] for s in TM.SURFS}]
            for p in act:
                e = m.elo[p]
                ark = sum(mx[s] * m.predict(p, ref, tour, s, day, 3, match=False)[0] for s in TM.SURFS)
                a = agg.get(p) or {'st': [0] * 9, 'rt': [0] * 9, 'sm': 0, 'tbw': 0, 'tbl': 0, 'n': 0}
                age = (day - m.born[p]) / 365.25 if p in m.born else np.nan
                out.append(dict(pid=p, tour=tour, y=y, elo=e[0], eH=e[2]['H'][0], eC=e[2]['C'][0], eG=e[2]['G'][0],
                                nC=a.get('sC', 0), nG=a.get('sG', 0), ark=ark, age=age, **{k: a[k] for k in ('sm', 'tbw', 'tbl', 'n')},
                                st=list(a['st']), rt=list(a['rt'])))
            for k in (ref,):
                for d_ in (m.elo, m.pt, m.gr):
                    d_.pop(k, None)

    for r in rows:
        y = r[0] // 10000
        if y > yr:
            snap(yr)
            agg, mix = {}, defaultdict(lambda: defaultdict(int))
            yr = y
        if r[2] in TM.TOUR_LV and not r[4].startswith('Q'):
            mix[r[1]][r[3]] += 1
        tw, tl = tb_count(r[9])
        for me, mine, theirs, tbw, tbl in ((r[7], r[10], r[11], tw, tl), (r[8], r[11], r[10], tl, tw)):
            a = agg.setdefault(me, {'st': [0] * 9, 'rt': [0] * 9, 'sm': 0, 'tbw': 0, 'tbl': 0, 'n': 0})
            a['n'] += 1
            a['tbw'] += tbw
            a['tbl'] += tbl
            a['s' + r[3]] = a.get('s' + r[3], 0) + 1
            if mine and theirs:
                a['sm'] += 1
                for i in range(9):
                    a['st'][i] += mine[i] or 0
                    a['rt'][i] += theirs[i] or 0
        m.update(r)
    return out


def pro_cands(R):
    st = np.array([r['st'] for r in R], float)
    rt = np.array([r['rt'] for r in R], float)
    # st / rt: [svpt, 1stIn, 1stWon, 2ndWon, SvGms, bpSaved, bpFaced, ace, df]
    with np.errstate(divide='ignore', invalid='ignore'):
        spw = (st[:, 2] + st[:, 3]) / st[:, 0]
        rpw = (rt[:, 0] - rt[:, 2] - rt[:, 3]) / rt[:, 0]
        c = {
            'ace': ('Big Server', 'aces a serve point', st[:, 7] / st[:, 0], st[:, 0], 500),
            'first': ('First Strike', 'first-serve points won', st[:, 2] / st[:, 1], st[:, 1], 300),
            'second': ('Second Serve', 'second-serve points won', st[:, 3] / (st[:, 0] - st[:, 1]), st[:, 0] - st[:, 1], 200),
            'ret': ('Returner', 'return points won', rpw, rt[:, 0], 500),
            'bps': ('Break Saver', 'break points saved over own serve-point rate', st[:, 5] / st[:, 6] - spw, st[:, 6], 30),
            'bpc': ('Converter', 'break points converted over own return-point rate', (rt[:, 6] - rt[:, 5]) / rt[:, 6] - rpw, rt[:, 6], 30),
            'tb': ('Tiebreaker', 'tiebreaks won', np.array([r['tbw'] / (r['tbw'] + r['tbl']) if r['tbw'] + r['tbl'] else np.nan for r in R]),
                   np.array([r['tbw'] + r['tbl'] for r in R], float), 5),
            'clay': ('Clay Court', 'clay Elo over hard-court Elo', np.array([r['eC'] - r['eH'] for r in R]), np.array([r['nC'] for r in R], float), 10),
            'grass': ('Grass Court', 'grass Elo over hard-court Elo', np.array([r['eG'] - r['eH'] for r in R]), np.array([r['nG'] for r in R], float), 5),
        }
    return c


def run_pro():
    pk = os.path.join(CACHE, 'badge_pro.pkl')
    if os.path.exists(pk) and '--refresh' not in sys.argv:
        R = pickle.load(open(pk, 'rb'))
    else:
        R = pro_rows()
        pickle.dump(R, open(pk, 'wb'))
    nxt = {(r['pid'], r['y']): r['elo'] for r in R}
    res = {}
    for tour in ('atp', 'wta'):
        Rt = [r for r in R if r['tour'] == tour and 2006 <= r['y'] <= 2025]
        # the board's universe: the tour's top 300 by ARK each year-end
        rk = {}
        for y in set(r['y'] for r in Rt):
            ys = sorted([r for r in Rt if r['y'] == y], key=lambda r: -r['ark'])
            for i, r in enumerate(ys):
                rk[(r['pid'], y)] = i + 1
        pid = np.array([r['pid'] for r in Rt])
        season = np.array([r['y'] for r in Rt])
        dy = np.array([nxt.get((r['pid'], r['y'] + 1), np.nan) - r['elo'] for r in Rt])
        sm = np.array([r['sm'] for r in Rt])
        use = np.isfinite(dy) & (sm >= 10) & np.array([rk[(r['pid'], r['y'])] <= 300 for r in Rt]) & (season <= 2024)
        elo = np.array([r['elo'] for r in Rt])
        ark = np.clip(np.array([r['ark'] for r in Rt]), 1e-4, 1 - 1e-4)
        age = np.array([r['age'] for r in Rt])
        age = np.where(np.isfinite(age), age, 26) - 26
        ctrl = np.column_stack([np.ones(len(Rt)), (elo - 2000) / 100, np.log(ark / (1 - ark)), age / 5, (age / 5) ** 2])
        y = np.nan_to_num(dy)
        # robustness: the board's grade plus last season's Elo change and the hard-court Elo (a surface gap must not
        # be a hard-Elo lag); rows with a rating a year earlier
        nxt_prev = np.array([r['elo'] - nxt.get((r['pid'], r['y'] - 1), np.nan) for r in Rt])
        ctrl2 = np.column_stack([ctrl, np.nan_to_num(nxt_prev) / 100, (np.array([r['eH'] for r in Rt]) - 2000) / 100])
        use2 = use & np.isfinite(nxt_prev)
        b, t = cluster_t(ctrl[use], y[use], pid[use])
        base_r2 = 1 - np.mean((y[use] - ctrl[use] @ b) ** 2) / np.var(y[use])
        res[tour] = dict(n=int(use.sum()), players=int(len(set(pid[use]))), seasons=[2006, 2024], outcome='overall Elo change, next season',
                         grade='Elo, logit ARK, age, age^2', r2Grade=round(float(base_r2), 3),
                         badges=test(pro_cands(Rt), ctrl, y, pid, season, season, use))
        cands = pro_cands(Rt)
        for k, c in res[tour]['badges'].items():
            if not c['pass']:
                continue
            rb = test({k: cands[k]}, ctrl2, y, pid, season, season, use2)[k]
            c['robust'] = dict(t=rb['t'], oos=rb['oos'], n=rb['n'], grade='+ last season Elo change, hard-court Elo')
            if not rb['pass']:
                c.update({'pass': False, 'why': 'not robust: t %.2f, oos %+.3f beside last season\'s Elo change and hard-court Elo' % (rb['t'], rb['oos'])})
        print(tour, res[tour]['n'], 'rows')
        for k, c in res[tour]['badges'].items():
            print('  %-8s r %-6s t %-6s oos %-7s %s %s' % (k, c['r'], c.get('t'), c.get('oos'), 'PASS' if c['pass'] else 'fail', c.get('why', '')))
    return res


# ------------------------------------------------------------------------------------------------ prospects board

def run_prospects():
    import tennis_prospects as TP
    rows = pickle.load(open(TP.ROWS, 'rb'))
    fit = json.load(open(TP.FIT))
    res = {}
    for tour in TP.TOURS:
        X, F, y, pos, by = TP.snap_rows(rows, tour, '%02d-%02d' % TP.SEL_SNAP)
        kept = fit[tour]['kept']
        _, _, E = TP.loso(F, y, pos, by, kept)
        pid = X.pid.values
        season = X.season.values.astype(int)
        with np.errstate(divide='ignore', invalid='ignore'):
            sv = X.svpt.values.astype(float)
            c = {
                'ace': ('Big Server', 'aces a serve point', np.where(sv > 0, X.acer.values, np.nan), sv, 150),
                'spw': ('Server', 'serve points won', np.where(sv > 0, X.spw.values, np.nan), sv, 150),
                'ret': ('Returner', 'return points won', np.where(sv > 0, X.rpw.values, np.nan), sv, 150),
                'gdx': ('Dominator', 'games won over what the Elo gap predicts', np.where(X.gn > 0, X.gdx / X.gn, np.nan), X.gn.values.astype(float), 10),
                'tb': ('Tiebreaker', 'tiebreaks won', np.where(X.tbw + X.tbl > 0, X.tbw / (X.tbw + X.tbl), np.nan),
                       (X.tbw + X.tbl).values.astype(float), 4),
                'upset': ('Giant Killer', 'wins over players 100+ Elo higher, per match', np.where(X.n > 0, X.upw / X.n, np.nan), X.n.values.astype(float), 15),
            }
        ctrl = np.column_stack([np.ones(len(X)), E])
        use = np.ones(len(X), bool)
        res[tour] = dict(n=int(len(X)), players=int(X.pid.nunique()), outcome='peak FV (best three seasons at 22-28)',
                         grade='FV held out by birth year', badges=test(c, ctrl, y, pid, season, by, use))
        print(tour, len(X), 'rows')
        for k, c_ in res[tour]['badges'].items():
            print('  %-8s r %-6s t %-6s oos %-7s %s %s' % (k, c_['r'], c_.get('t'), c_.get('oos'), 'PASS' if c_['pass'] else 'fail', c_.get('why', '')))
    return res


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not math.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


if __name__ == '__main__':
    import datetime as dt
    which = [a for a in sys.argv[1:] if a in ('pro', 'prospects')] or ['pro', 'prospects']
    try:
        out = json.load(open(OUT))
    except (OSError, ValueError):
        out = {}
    out.update(asof=dt.date.today().isoformat(), method='see scripts/tennis_badge_backtest.py')
    if 'pro' in which:
        out['pro'] = run_pro()
    if 'prospects' in which:
        out['prospects'] = run_prospects()
    json.dump(clean(out), open(OUT, 'w'), indent=1, allow_nan=False)
    print('wrote', OUT)
