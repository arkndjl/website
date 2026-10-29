#!/usr/bin/env python3
"""Four college basketball game-model drivers from the Oct 28 2026 edge sweep, each judged against the closing line.

    python3 scripts/cbb_edge_research.py --pull    # caches: Barttorvik coaches, ESPN attendance, hoopR possession time
    python3 scripts/cbb_edge_research.py --merge   # writes 'att' and 'pt' (possession seconds) into cbb_games_hist.json.gz
    python3 scripts/cbb_edge_research.py           # writes data/cbb_edge_research.json (~1 h: one instrumented walk)
2026's hoopR file is broken (plays out of order: possession time past the game clock), so 2026 is read from ESPN's
own summaries with cbb_games.poss_secs (the live reader; it matches the hoopR reading play for play on 2024)

    coach   a new head coach brings his own tempo: when a school changes coach, the tempo prior is the coach's final
            tempo at his school last season (a mover) instead of the school's, and/or the school's carried tempo is
            shrunk toward the league for a coach with no D-I tempo of his own. Coaches from Barttorvik getgamestats
            (each game names both head coaches, 2010+), the coach of a team-season = the one with most of its games
    apl     asymmetric tempo: each side's average possession length in seconds, offense + opposing defense, ridge-solved
            by day (the offense and defense parts with their own prior weights), possessions = game seconds / (both
            sides' expected lengths). Possession time from hoopR's ESPN play-by-play (time between events goes to the
            side with the ball); games without play-by-play enter as the sum of both lengths (the symmetric solve)
    oppft   opponent free-throw luck stripped: free throws made over the shooter's FT% to date (shrunk, lkft 300) taken
            off the score at weight w; 'D' variants take the defense ratings from the stripped solve and keep the
            offense ratings raw (a defense has no say over its opponents' FT%, a shooter's FT% persists); 'M' variants
            use the stripped ratings on the margin only (the both-sides version, lwft, hurt totals on Oct 23)
    hatt    home court x the home team's trailing home attendance (log, this season's earlier home games, last season's
            mean worth 3 games); h21: home (and confh) set to 0 for 2021 games played in empty arenas (ESPN attendance
            under 300); hatt21 both

Everything on top of the shipped model (data/cbb_games_fit.json params and inputs) with the tempo half-life thl 20.
The FT variants are exact for this season's ratings (the extra right-hand side of the same ridge solve, linear in w)
but carry the shipped final ratings into next season's prior; the tempo variants re-walk the tempo solve on its own
(it never touches the efficiency solve), checked against the walk's possessions game by game.

The test, per variant (the house bar, as scripts/style_research.py): x = the variant's walk-forward prediction minus
the shipped one; the residual against the close (result minus closing spread or total) on x, clustered by day,
2016-20 (tune) and 2021-26 (held out) separately; the held-out squared error of the close moved by the tune fit
against the close alone. Passes at tune t >= 1.5, held-out slope > 0, held-out SE gain t <= -1.5, BH q <= .10 over
every test here, and the model's own MAE not worse in either period.
"""
import csv
import glob
import gzip
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C
import harness as H

OUT = os.path.join(C.ROOT, 'data', 'cbb_edge_research.json')
EC = os.path.join(C.HERE, '.cache', 'edge')
THL = 20.0
SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={d}&groups=50&limit=1000'
PBP = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_mens_college_basketball_pbp/play_by_play_{y}.parquet'
GGS = 'https://barttorvik.com/getgamestats.php?year={y}&tvalue=All&csv=1'


def r4(v):
    return round(float(v), 4)


# ---------------------------------------------------------------- data
def pull():
    import concurrent.futures as cf
    os.makedirs(os.path.join(EC, 'ggs'), exist_ok=True)
    for y in range(2010, C.LAST + 1):
        p = os.path.join(EC, 'ggs', f'{y}.csv')
        if not os.path.exists(p) or os.path.getsize(p) < 100000:
            subprocess.run(['curl', '-s', '-m', '300', '-A', C.UA, GGS.format(y=y), '-o', p], check=False)
    games = C.load_hist()
    ds = {C.et_date(g['date']).replace('-', '') for g in games}
    ds |= {(datetime.strptime(d, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d') for d in ds}
    os.makedirs(os.path.join(EC, 'sb'), exist_ok=True)

    def sb(d):
        p = os.path.join(EC, 'sb', f'{d}.json')
        if os.path.exists(p) and os.path.getsize(p) > 2:
            return
        for _ in range(3):
            r = subprocess.run(['curl', '-s', '-m', '60', SB.format(d=d)], capture_output=True)
            try:
                ev = json.loads(r.stdout)['events']
            except (ValueError, KeyError):
                continue
            json.dump({e['id']: [e['competitions'][0].get('attendance'), (e['competitions'][0].get('venue') or {}).get('id')] for e in ev}, open(p, 'w'))
            return
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(sb, sorted(ds)))
    os.makedirs(os.path.join(EC, 'pbp'), exist_ok=True)
    for y in range(C.FIRST, 2026):
        pbp_secs(y)
    pull26()


def pbp_secs(y):
    """hoopR ESPN play-by-play -> game id -> {ESPN team id: seconds with the ball} (running clock only: time between
    two events goes to the side that had the ball after the first; a made shot or free throw or a turnover hands it
    over, a rebound, steal or jump ball goes to its team, a miss keeps it until the rebound)"""
    out = os.path.join(EC, 'pbp', f'apl_{y}.json.gz')
    if os.path.exists(out):
        return json.load(gzip.open(out))
    import pyarrow.parquet as pq
    p = os.path.join(EC, 'pbp', f'{y}.parquet')
    if not os.path.exists(p):
        subprocess.run(['curl', '-sL', '-m', '900', PBP.format(y=y), '-o', p], check=True)
    cols = ['game_id', 'sequence_number', 'period_number', 'clock_minutes', 'clock_seconds', 'type_text', 'text', 'team_id',
            'home_team_id', 'away_team_id', 'shooting_play', 'scoring_play']
    t = pq.read_table(p, columns=cols).to_pandas()
    t['sequence_number'] = t['sequence_number'].astype(float)
    t = t.sort_values(['game_id', 'period_number', 'sequence_number'])
    res = {}
    for gid, g in t.groupby('game_id', sort=False):
        Hm, Aw = int(g['home_team_id'].iloc[0]), int(g['away_team_id'].iloc[0])
        opp = {Hm: Aw, Aw: Hm}
        sec = {Hm: 0.0, Aw: 0.0}
        own = prev = per = None
        nshot = 0
        for r in g.itertuples(index=False):
            try:
                clk = float(r.clock_minutes) * 60 + float(r.clock_seconds)
            except (TypeError, ValueError):
                continue
            if r.period_number != per:
                per, prev, own = r.period_number, clk, None
            T = int(r.team_id) if r.team_id == r.team_id and r.team_id is not None else None
            if T not in opp:
                T = None
            ty = r.type_text if isinstance(r.type_text, str) else ''
            tx = f" {r.text.lower()} " if isinstance(r.text, str) else ''
            dt = prev - clk
            if dt > 0:
                o = own
                if o is None and T is not None and (r.shooting_play or 'Turnover' in ty):
                    o = T
                if o is not None:
                    sec[o] += dt
            prev = clk
            if T is None:
                continue
            if 'FreeThrow' in ty or 'Free Throw' in ty:
                own = opp[T] if ' made ' in tx else T
            elif r.shooting_play:
                nshot += 1
                own = opp[T] if r.scoring_play else T
            elif 'Rebound' in ty or 'Jumpball' in ty or 'Steal' in ty:
                own = T
            elif 'Turnover' in ty:
                own = opp[T]
        if nshot >= 60:
            res[str(gid)] = {str(Hm): round(sec[Hm], 1), str(Aw): round(sec[Aw], 1)}
    json.dump(res, gzip.open(out, 'wt'))
    os.remove(p)
    return res


def merge_hist():
    g = json.load(gzip.open(C.HIST))
    att = attendance()
    pt = {}
    for y in range(C.FIRST, C.LAST + 1):
        p = os.path.join(EC, 'pbp', f'apl_{y}.json.gz')
        if os.path.exists(p):
            pt.update(json.load(gzip.open(p)))
    for x in g:
        if x['id'] in att:
            x['att'] = att[x['id']]
        v = pt.get(x['id'])
        if v and x['home'] in v and x['away'] in v:
            x['pt'] = [v[x['home']], v[x['away']]]
    with gzip.GzipFile(C.HIST, 'wb', mtime=0) as f:
        f.write(json.dumps(g, separators=(',', ':')).encode())


def pull26():
    """2026 possession time from ESPN summaries (hoopR's 2026 file is out of order)"""
    import concurrent.futures as cf
    g = [x for x in C.load_hist() if x['season'] == 2026 and x.get('poss')]

    def f(x):
        for _ in range(3):
            r = subprocess.run(['curl', '-s', '-m', '60', 'https://site.api.espn.com/apis/site/v2/sports/basketball/'
                                'mens-college-basketball/summary?event=' + x['id']], capture_output=True)
            try:
                j = json.loads(r.stdout)
            except ValueError:
                continue
            v = C.poss_secs(j.get('plays') or [], x['home'], x['away'])
            return x['id'], ({x['home']: v[0], x['away']: v[1]} if v else None)
        return x['id'], None
    out = {}
    with cf.ThreadPoolExecutor(12) as ex:
        for i, v in ex.map(f, g):
            if v:
                out[i] = v
    json.dump(out, gzip.open(os.path.join(EC, 'pbp', 'apl_2026.json.gz'), 'wt'))


def coaches():
    """season -> Barttorvik team -> head coach (most of its games)"""
    out = {}
    for p in sorted(glob.glob(os.path.join(EC, 'ggs', '*.csv'))):
        y = int(os.path.basename(p)[:4])
        n = defaultdict(lambda: defaultdict(int))
        for r in csv.reader(open(p)):
            if len(r) > 26 and r[25]:
                n[r[2]][r[25]] += 1
        out[y] = {t: max(c, key=c.get) for t, c in n.items()}
    return out


def attendance():
    a = {}
    for p in glob.glob(os.path.join(EC, 'sb', '*.json')):
        for i, v in json.load(open(p)).items():
            if v and v[0] is not None:
                a[i] = float(v[0])
    return a


# ---------------------------------------------------------------- instrumented walk
def instrumented(P, games, tprior, btname, d1s, avs):
    W = C.Walk(P, tprior, btname)
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    rows = []

    def col(g, x, tx, R):
        if g.get('hs') is None:
            return
        H_, A_ = R.i(g['home']), R.i(g['away'])
        e = {'O': (R.O[H_], R.O[A_]), 'D': (R.D[H_], R.D[A_]), 'mu': R.mu, 'dO': (R.dO[H_], R.dO[A_]),
             'dD': (R.dD[H_], R.dD[A_]), 'dmu': R.dmu, 'P': R.poss(g['home'], g['away']), 'P2': R.tposs(g['home'], g['away']),
             'ng': min(R.ng[g['home']], R.ng[g['away']])}
        rows.append((g, x, tx, e))
    for s in sorted(by_s):
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
        C.season_walk(W, s, gs, d1s[s], avs.get(s), col)
        print('walk', s, len(rows), flush=True)
    return W, rows


# ---------------------------------------------------------------- tempo-only walks
def tempo_walk(P, games, d1s, prior_fn=None):
    """the shipped tempo solves on their own (Ratings' TA/Tb on hl for the margin, TA2/Tb2 on thl for the total):
    game id -> (margin possessions, total possessions). prior_fn(s, last) -> team -> prior tempo, default last
    season's final (the margin copy) x tcarry"""
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    final, out = {}, {}
    for s in sorted(by_s):
        teams = sorted(d1s[s]) + [C.X]
        ix = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        last = final.get(s - 1, {})
        pr = prior_fn(s, last) if prior_fn else {t: last[t] * P['tcarry'] for t in teams if t in last}
        pT = np.array([pr.get(t, 0.0) for t in teams])
        TA, Tb = np.zeros((n + 1, n + 1)), np.zeros(n + 1)
        TA2, Tb2 = np.zeros((n + 1, n + 1)), np.zeros(n + 1)
        T = T2 = pT.copy()
        tau = tau2 = P['tau0']
        st = {'day': None}
        nobs = 0
        prec = np.concatenate([np.full(n, P.get('tlam', P['lam'])), [0.01]])
        pv = prec * np.concatenate([pT, [P['tau0']]])
        I = lambda t: ix.get(t, ix[C.X])
        by_day = defaultdict(list)
        for g in by_s[s]:
            by_day[C.et_date(g['date'])].append(g)
        day0 = datetime(s - 1, 11, 1)

        def dec(day):
            d0 = st['day']
            if d0 is not None and day > d0:
                if P['hl']:
                    f = 0.5 ** ((day - d0) / P['hl'])
                    TA[:] *= f; Tb[:] *= f
                if P.get('thl'):
                    f = 0.5 ** ((day - d0) / P['thl'])
                    TA2[:] *= f; Tb2[:] *= f
            st['day'] = day

        def sol():
            a = np.linalg.solve(TA + np.diag(prec), Tb + pv)
            b = np.linalg.solve(TA2 + np.diag(prec), Tb2 + pv) if P.get('thl') else a
            return a[:n], a[n], b[:n], b[n]
        for d in sorted(by_day):
            day = (datetime.strptime(d, '%Y-%m-%d') - day0).days
            if nobs:
                dec(day)
                T, tau, T2, tau2 = sol()
            for g in by_day[d]:
                out[g['id']] = (tau + T[I(g['home'])] + T[I(g['away'])], tau2 + T2[I(g['home'])] + T2[I(g['away'])])
            for g in by_day[d]:
                if g.get('hs') is None:
                    continue
                dec(day)
                if g.get('poss'):
                    k = (I(g['home']), I(g['away']), n)
                    for p in k:
                        for q in k:
                            TA[p, q] += 1; TA2[p, q] += 1
                        Tb[p] += g['poss']; Tb2[p] += g['poss']
                nobs += 1
        dec((datetime(s, 4, 10) - day0).days)
        T, tau, _, _ = sol()
        final[s] = {t: float(T[ix[t]]) for t in teams if t != C.X}
    return out, final


def apl_walk(P, games, d1s, secs, lo, ld, carry=1.0):
    """asymmetric tempo in seconds a possession: L(home) = c + o[home] + d[away], L(away) = c + o[away] + d[home], each
    game's lengths from its possession time share (games without play-by-play: one row on L(home) + L(away)); o, d
    with prior weights lo, ld games around last season's final x carry. game id -> expected possessions in 40 minutes"""
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    final, out = {}, {}
    th = P.get('thl') or P['hl']
    for s in sorted(by_s):
        teams = sorted(d1s[s]) + [C.X]
        ix = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        last = final.get(s - 1, {})
        po = np.array([last.get(t, (0.0, 0.0))[0] * carry for t in teams])
        pd = np.array([last.get(t, (0.0, 0.0))[1] * carry for t in teams])
        m = 2 * n + 1
        A, b = np.zeros((m, m)), np.zeros(m)
        prec = np.concatenate([np.full(n, lo), np.full(n, ld), [0.01]])
        pv = np.concatenate([po, pd, [2400 / P['tau0'] / 2]])
        sol = pv.copy()
        I = lambda t: ix.get(t, ix[C.X])
        by_day = defaultdict(list)
        for g in by_s[s]:
            by_day[C.et_date(g['date'])].append(g)
        day0 = datetime(s - 1, 11, 1)
        day_, nobs = None, 0
        for d in sorted(by_day):
            day = (datetime.strptime(d, '%Y-%m-%d') - day0).days
            if day_ is not None and th and day > day_:
                f = 0.5 ** ((day - day_) / th)
                A *= f; b *= f
            day_ = day
            if nobs:
                sol = np.linalg.solve(A + np.diag(prec), b + prec * pv)
            for g in by_day[d]:
                h, a = I(g['home']), I(g['away'])
                Ls = 2 * sol[2 * n] + sol[h] + sol[n + a] + sol[a] + sol[n + h]
                out[g['id']] = 2400 / Ls
            for g in by_day[d]:
                if g.get('hs') is None or not g.get('poss'):
                    continue
                h, a = I(g['home']), I(g['away'])
                Ssec = (2400 + 300 * (g.get('ot') or 0)) / g['poss']
                sp = secs.get(g['id'])
                sh = sp.get(g['home']) if sp else None
                sa = sp.get(g['away']) if sp else None
                rows = []
                if sh and sa and 0.3 < sh / (sh + sa) < 0.7:
                    f = sh / (sh + sa)
                    rows = [((h, n + a, 2 * n), Ssec * f), ((a, n + h, 2 * n), Ssec * (1 - f))]
                else:
                    rows = [((h, n + a, a, n + h, 2 * n), Ssec)]
                for idx, yv in rows:
                    w = [1.0] * len(idx)
                    if len(idx) == 5:
                        w[4] = 2.0
                    for p, vp in zip(idx, w):
                        for q, vq in zip(idx, w):
                            A[p, q] += vp * vq
                        b[p] += vp * yv
                nobs += 1
        sol = np.linalg.solve(A + np.diag(prec), b + prec * pv)
        final[s] = {t: (float(sol[ix[t]]), float(sol[n + ix[t]])) for t in teams if t != C.X}
    return out


# ---------------------------------------------------------------- scoring
def ols_cl(X, y, c):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    _, inv = np.unique(c, return_inverse=True)
    G = inv.max() + 1
    sc = np.zeros((G, X.shape[1]))
    np.add.at(sc, inv, X * e[:, None])
    nn, k = X.shape
    V = XtXi @ (sc.T @ sc) @ XtXi * G / (G - 1) * (nn - 1) / (nn - k)
    return b, np.sqrt(np.diag(V))


def judge(p1, p0, y, close, S, day, d1, hc):
    """p1 the variant's prediction, p0 the shipped one; close the closing line (nan where none)"""
    tune = (S >= C.SCORE0) & (S <= C.TUNE_END) & d1
    held = (S > C.TUNE_END) & d1
    o = {}
    e1, e0 = np.abs(p1 - y), np.abs(p0 - y)
    for lab, k in (('tune', tune), ('held', held)):
        pr = H.paired(e1[k], e0[k], [c[k] for c in hc])
        o['mae_' + lab] = [r4(e1[k].mean()), r4(pr['d']), round(pr['t'], 2)]
    ok = ~np.isnan(close) & ~np.isnan(p1) & ~np.isnan(p0)
    x = p1 - p0
    res = y - close
    Tm, Hm = tune & ok, held & ok
    o['n'] = [int(Tm.sum()), int(Hm.sum())]
    o['sd_x'] = [r4(x[Tm].std()), r4(x[Hm].std())]
    X = np.c_[np.ones(len(x)), x]
    if x[Hm].std() < 1e-9:
        o.update(tune=[0, 0], held=[0, 0], seHeld=[0, 0], z=0.0, split=False, modelOk=False)
        return o
    if x[Tm].std() < 1e-9:
        # a regime fix with no tuning-season rows (2021's empty arenas): held-out slope only, and the model's own error
        b, s = ols_cl(X[Hm], res[Hm], day[Hm])
        o.update(tune=[0, 0], held=[r4(b[1]), round(float(b[1] / s[1]), 2)], seHeld=[0, 0], z=round(float(b[1] / s[1]), 2),
                 split=False, heldOnly=True, modelOk=bool(o['mae_held'][2] <= -1.5))
        return o
    for lab, m in (('tune', Tm), ('held', Hm)):
        b, s = ols_cl(X[m], res[m], day[m])
        o[lab] = [r4(b[1]), round(float(b[1] / s[1]), 2)]
    bt = ols_cl(X[Tm], res[Tm], day[Tm])[0]
    new, old = close + bt[0] + bt[1] * x, close + res[Tm].mean()
    pr = H.paired(H.se(new[Hm], y[Hm]), H.se(old[Hm], y[Hm]), cluster=day[Hm])
    o['seHeld'] = [round(float(pr['d']), 5), round(pr['t'], 2)]
    o['z'] = round(H.stouffer([o['tune'][1], o['held'][1]]), 2)
    o['split'] = bool(o['tune'][1] >= 1.5 and o['held'][0] > 0 and o['seHeld'][1] <= -1.5)
    o['modelOk'] = bool(o['mae_tune'][1] <= 0 and o['mae_held'][1] <= 0)
    return o


def main():
    if '--pull' in sys.argv:
        pull()
        return
    if '--merge' in sys.argv:
        merge_hist()
        return
    F = json.load(open(C.FIT))
    P = dict(F['params'], thl=THL, ldft=0.0, aplmix=0.0)     # the shipped model before this sweep
    feats = F['feats']
    games, btname, d1s, tprior, avs = C.load_all()
    print('loaded', len(games), flush=True)
    pk = os.path.join(EC, 'walk.pkl')
    smoke = os.environ.get('EDGE_SMOKE')
    if smoke:                                   # a quick run of the first seasons, nothing written
        games = [g for g in games if g['season'] <= int(smoke)]
        C.TUNE_END, C.LAST = int(smoke) - 1, int(smoke)
        pk = pk + '.smoke'
    if os.path.exists(pk):
        import pickle
        rows = pickle.load(open(pk, 'rb'))
    else:
        import pickle
        _, rows = instrumented(P, games, tprior, btname, d1s, avs)
        pickle.dump(rows, open(pk, 'wb'))
    D = [r for r in rows if r[0]['season'] >= C.FIRST + 1]
    g_ = [r[0] for r in D]
    S = np.array([g['season'] for g in g_])
    y = np.array([g['hs'] - g['as'] for g in g_], float)
    ty = np.array([g['hs'] + g['as'] for g in g_], float)
    line = np.array([-g['spread'] if g.get('spread') is not None else np.nan for g in g_])
    tline = np.array([g['total'] if g.get('total') else np.nan for g in g_])
    d1 = np.array([g['home'] != C.X and g['away'] != C.X and 'hb' in g for g in g_])
    day = np.array([g['date'][:10] for g in g_])
    hc = [day, np.array([f"{g['home']}-{g['season']}" for g in g_])]
    E = [r[3] for r in D]
    P0 = np.array([e['P'] for e in E])          # the margin's possessions
    P2 = np.array([e['P2'] for e in E])         # the total's (thl)

    def mats(eff=None, efft=None, xmod=None):
        Xm = np.array([[r[1][f] for f in feats] for r in D])
        TX = np.array([[r[2][f] for f in C.TFEATS] for r in D])
        if eff is not None:
            Xm[:, feats.index('eff')] = eff
        if efft is not None:
            TX[:, C.TFEATS.index('efft')] = efft
            tm = TX[:, C.TFEATS.index('tmkt')]
            fade = np.array([max(0.0, 1 - e['ng'] / 10) for e in E])
            TX[:, C.TFEATS.index('early')] = (efft - tm) * fade
        if xmod:
            Xm = xmod(Xm)
        return Xm, TX

    def ehea(w=0.0, mode='both'):
        """per game (eh, ea) points per 100 at FT-strip weight w"""
        o = []
        for e in E:
            wo = w if mode == 'both' else 0.0
            mu = e['mu'] + w * e['dmu'] if mode == 'both' else e['mu']
            Oh, Oa = e['O'][0] + wo * e['dO'][0], e['O'][1] + wo * e['dO'][1]
            Dh, Da = e['D'][0] + w * e['dD'][0], e['D'][1] + w * e['dD'][1]
            o.append((mu + Oh - Da, mu + Oa - Dh))
        return np.array(o)
    EA0 = ehea()
    Xm0, TX0 = mats()
    # sanity: the instrumented walk reproduces the shipped eff and efft
    assert np.allclose((EA0[:, 0] - EA0[:, 1]) * P0 / 100, Xm0[:, feats.index('eff')], atol=1e-6)
    assert np.allclose((EA0[:, 0] + EA0[:, 1]) * P2 / 100, TX0[:, C.TFEATS.index('efft')], atol=1e-6)
    pm0 = C.walk_pred(Xm0, y, S, d1)
    pt0 = C.walk_pred(TX0, ty, S, d1)
    tune = (S >= C.SCORE0) & (S <= C.TUNE_END) & d1
    held = (S > C.TUNE_END) & d1
    res = {'base': {'feats': feats, 'params': P, 'games': [int(tune.sum()), int(held.sum())],
                    'mae': [r4(np.abs(pm0 - y)[tune].mean()), r4(np.abs(pm0 - y)[held].mean())],
                    'tmae': [r4(np.abs(pt0 - ty)[tune].mean()), r4(np.abs(pt0 - ty)[held].mean())]},
           'tests': {}}
    print('base', res['base'], flush=True)
    T = res['tests']

    def run(name, eff=None, efft=None, xmod=None, info=None):
        Xm, TX = mats(eff, efft, xmod)
        if eff is not None or xmod is not None:
            p1 = C.walk_pred(Xm, y, S, d1)
            T[name + ':margin'] = judge(p1, pm0, y, line, S, day, d1, hc)
            print(name, 'margin', T[name + ':margin'], flush=True)
        if efft is not None:
            p1 = C.walk_pred(TX, ty, S, d1)
            T[name + ':total'] = judge(p1, pt0, ty, tline, S, day, d1, hc)
            print(name, 'total', T[name + ':total'], flush=True)
        if info:
            for k in [k for k in T if k.startswith(name + ':')]:
                T[k]['info'] = info

    # ---- opponent FT luck
    for w in (0.5, 1.0):
        for mode in ('both', 'D'):
            ea = ehea(w, mode)
            run(f'oppft_{mode}{w}', (ea[:, 0] - ea[:, 1]) * P0 / 100, (ea[:, 0] + ea[:, 1]) * P2 / 100)
        ea = ehea(w, 'both')
        run(f'oppft_M{w}', (ea[:, 0] - ea[:, 1]) * P0 / 100)

    # ---- tempo: the replica first
    tp, tfinal = tempo_walk(P, games, d1s)
    Pr = np.array([tp[g['id']] for g in g_])
    res['tempoReplica'] = r4(max(np.abs(Pr[:, 0] - P0).max(), np.abs(Pr[:, 1] - P2).max()))
    print('tempo replica max diff', res['tempoReplica'], flush=True)
    assert res['tempoReplica'] < 1e-6

    def with_poss(name, Pm_, Pt_, info=None):
        run(name, (EA0[:, 0] - EA0[:, 1]) * Pm_ / 100, (EA0[:, 0] + EA0[:, 1]) * Pt_ / 100, info=info)

    # ---- coach tempo
    CO = coaches()
    inv = {}
    for t, b in btname.items():
        inv.setdefault(b, t)
    moves = defaultdict(lambda: [0, 0, 0])

    def coach_prior(w, k):
        def f(s, last):
            c, c0 = CO.get(s, {}), CO.get(s - 1, {})
            where = {v: u for u, v in c0.items()}
            out = {}
            for t in d1s[s]:
                if t not in last:
                    continue
                b = btname.get(t)
                v = last[t] * P['tcarry']
                if b in c and b in c0 and c[b] != c0[b]:
                    old = where.get(c[b])
                    ot = inv.get(old) if old else None
                    if ot and ot in last and ot != t:
                        v = (1 - w) * v + w * last[ot] * P['tcarry']
                        if w == 1.0 and k == 1.0:
                            moves[s][0] += 1
                    else:
                        v *= k
                        if w == 1.0 and k == 1.0:
                            moves[s][1] += 1
                elif w == 1.0 and k == 1.0:
                    moves[s][2] += 1
                out[t] = v
            return out
        return f
    for w, k in ((1.0, 1.0), (0.5, 1.0), (1.0, 0.5), (0.0, 0.5)):
        tpv, _ = tempo_walk(P, games, d1s, coach_prior(w, k))
        v = np.array([tpv[g['id']] for g in g_])
        with_poss(f'coach_w{w}_k{k}', v[:, 0], v[:, 1])
    res['coachMoves'] = {s: {'mover': v[0], 'newOther': v[1], 'same': v[2]} for s, v in sorted(moves.items())}
    # first-two-weeks slice of the mover variant, the brief's mechanism
    print('coach moves', res['coachMoves'], flush=True)

    # ---- asymmetric tempo
    secs = {}
    for yv in range(C.FIRST, C.LAST + 1):
        p = os.path.join(EC, 'pbp', f'apl_{yv}.json.gz')
        if os.path.exists(p):
            secs.update(json.load(gzip.open(p)))
    cov = np.array([g['id'] in secs for g in g_])
    res['aplCoverage'] = {str(s): r4(cov[(S == s) & d1].mean()) for s in range(C.SCORE0, C.LAST + 1)}
    print('pbp coverage', res['aplCoverage'], flush=True)
    for lo, ld in ((2.0, 2.0), (2.0, 6.0), (1.0, 4.0), (2.0, 15.0)):
        ap = apl_walk(P, games, d1s, secs, lo, ld)
        Pa = np.array([ap[g['id']] for g in g_]) * C.APLK
        with_poss(f'apl_o{lo}_d{ld}', Pa, Pa)
        with_poss(f'aplmix_o{lo}_d{ld}', (Pa + P0) / 2, (Pa + P2) / 2)

    # ---- home court x attendance
    ATT = attendance()
    # the walk's own term (cbb_games Walk.hatt: home x trailing crowd minus ATT_MID, the 2016-20 home mean)
    hatt = np.array([r[1]['hatt'] for r in D])
    hom = np.array([0.0 if g['neutral'] else 1.0 for g in g_])
    mtl = C.ATT_MID + float(hatt[tune & (hom == 1)].mean())
    empty = np.array([g['season'] == 2021 and not g['neutral'] and (ATT.get(g['id']) or 0) < 300 for g in g_])
    res['attendance'] = {'covered': r4(np.mean([g['id'] in ATT for g in g_ if not g['neutral']])), 'meanLogK': r4(mtl),
                         'empty2021': int(empty.sum()), 'home2021': int(((S == 2021) & (hom == 1)).sum())}
    print('attendance', res['attendance'], flush=True)
    ih, ic = feats.index('home'), feats.index('confh')

    def add_col(v):
        return lambda Xm: np.column_stack([Xm, v])

    def zero21(Xm):
        Xm = Xm.copy()
        Xm[empty, ih] = 0.0
        Xm[empty, ic] = 0.0
        return Xm
    run('hatt', xmod=add_col(hatt))
    run('h21', xmod=zero21)
    run('hatt21', xmod=lambda Xm: np.column_stack([zero21(Xm), hatt]))

    # ---- the passers together (margin: defense-side FT strip .5 + hatt; total: the same ratings x the asymmetric
    # tempo mix o1/d4), judged the same way but outside the BH family
    ea = ehea(0.5, 'D')
    ap = apl_walk(P, games, d1s, secs, 1.0, 4.0)
    Pm = (np.array([ap[g['id']] for g in g_]) * C.APLK + P2) / 2
    J = {}
    Xm, TX = mats((ea[:, 0] - ea[:, 1]) * P0 / 100, (ea[:, 0] + ea[:, 1]) * Pm / 100, add_col(hatt))
    J['margin'] = judge(C.walk_pred(Xm, y, S, d1), pm0, y, line, S, day, d1, hc)
    J['total'] = judge(C.walk_pred(TX, ty, S, d1), pt0, ty, tline, S, day, d1, hc)
    res['joint'] = J
    print('joint', J, flush=True)

    # ---- one BH family over every test
    ks = [k for k in T]
    p = [H.p_of_z(T[k]['z']) if T[k].get('z') else 0.5 for k in ks]
    q = H.bh(p)
    for k, qq in zip(ks, q):
        if k == 'joint':
            continue
        T[k]['q'] = round(float(qq), 3)
        T[k]['pass'] = bool(T[k].get('split') and qq <= 0.10 and T[k].get('modelOk'))
        print(f"{k:28} tune {T[k]['tune']} held {T[k]['held']} se {T[k]['seHeld']} q {T[k]['q']} "
              f"mae {T[k]['mae_tune'][1:]} {T[k]['mae_held'][1:]} {'PASS' if T[k]['pass'] else ''}", flush=True)
    with open(OUT if not smoke else os.path.join(EC, 'smoke.json'), 'w') as f:
        json.dump(res, f, indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
