#!/usr/bin/env python3
"""Research: college basketball lineups and on/off (Noah, Nov 2 2026: "lineup charts, on-offs for basketball, and
incorporating this into player/team ratings if it passes").

Data: scripts/cbb_lineups.py stints from NCAA play-by-play (ncaa-api proxy). Only seasons whose games carry
substitution lines can be tested (see 'coverage' in the output); that is not the house 2016-20 / 2021-26 split, so
each test says which seasons it tuned on and which it held out.

  OMP_NUM_THREADS=1 python3 scripts/cbb_lineups_research.py      # data/cbb_lineups_research.json

Tests (walk-forward: an input for a game uses only games before its date, or the season before):
  validate  stint minutes vs Barttorvik's box minutes (player-games within 2 minutes)
  a. onoff_inj  the availability term (cbb_games 'inj') values a player who sat at BPM to date + w x his shrunk
                on-off to date (on-off is in team-net points per 100; BPM in player points per 100)
  b. cont       margin term: share of a team's floor time to date (pair-seconds) from teammate pairs that played
                100+ minutes together for the team last season
     pri_oo     preseason prior: returners' last-season shrunk on-off x last-season minutes share, on the residual of
                the final net over the walk's prior
  c. player     last-season shrunk on-off next to last-season BPM for next-season BPM (players with 300+ min both)
  d. garbage    margin term: a team's net to date with garbage time (2nd half or OT, margin 20+ when the stint began)
                taken out, minus its full net to date
"""
import os
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import gzip
import json
import math
import sys
from collections import defaultdict
from multiprocessing import get_context

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C
import cbb_lineups as L
import names as N

OUT = os.path.join(C.ROOT, 'data', 'cbb_lineups_research.json')
K_OO = 600.0


# ---------------------------------------------------------------- joins
def bt_raw(season):
    C.bt_logs(season)
    try:
        return json.load(gzip.open(os.path.join(C.BTLOG, f'{season}.json.gz')))
    except Exception:
        return []


def bt_index(season):
    """Barttorvik: team -> player rows {name, team, pid}; (team, date, pid) -> minutes; pid -> (min, gbpm x min)"""
    rows = bt_raw(season)
    roster = defaultdict(dict)
    mins = {}
    tot = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        try:
            d = str(r[0]); d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            roster[r[47]][r[51]] = dict(name=r[48], team=r[47], pid=r[51])
            mn = float(r[8] or 0)
            mins[(r[47], d, r[51])] = mn
            tot[r[51]][0] += mn; tot[r[51]][1] += mn * float(r[44] or 0)
        except (IndexError, TypeError, ValueError):
            continue
    return {t: list(v.values()) for t, v in roster.items()}, mins, dict(tot)


def ncaa_to_bt(games, roster):
    """NCAA team id -> Barttorvik team (most shared player names, 3+), and (tid, name) -> pid via the shared matcher"""
    names = defaultdict(set)
    for g in games.values():
        if 'stints' in g:
            for t in (g['home'], g['away']):
                names[t].update(N.key(n) for n in g['players'][t])
    bkeys = {t: {N.key(r['name']) for r in v} for t, v in roster.items()}
    inv = defaultdict(set)
    for t, ks in bkeys.items():
        for k in ks:
            inv[k].add(t)
    tm = {}
    for t, ks in names.items():
        c = defaultdict(int)
        for k in ks:
            for b in inv.get(k, ()):
                c[b] += 1
        if c:
            b = max(c, key=c.get)
            if c[b] >= 3:
                tm[t] = b
    pm = {}
    for t, b in tm.items():
        M = N.Matcher(roster[b], name='name', team='team', id='pid', sport='basketball')
        for n in names_disp(games, t):
            r, how = M.find(n, team=b, cross_team='none')
            if r:
                pm[(t, n)] = r['pid']
    return tm, pm


def names_disp(games, t):
    s = set()
    for g in games.values():
        if 'stints' in g and t in (g['home'], g['away']):
            s.update(g['players'][t])
    return s


# ---------------------------------------------------------------- walk-forward on/off
def poss_of(g):
    return g.get('poss') or 68.0 * (g['secs'] or 2400) / 2400


def team_games(games):
    by = defaultdict(list)
    for g in games.values():
        if 'stints' in g and g['secs'] > 1800 and None not in g['players'][g['home']] + g['players'][g['away']]:
            by[g['home']].append(g); by[g['away']].append(g)
    for t in by:
        by[t].sort(key=lambda g: (g['date'], g['id']))
    return by


def side(g, t):
    return (1, 3, 4) if t == g['home'] else (2, 4, 3)


def onoff_to_date(games, k=K_OO):
    """(tid, date) -> {name: shrunk on-off from the team's games before that date}; (tid, 'end') the full season"""
    out = {}
    for t, gl in team_games(games).items():
        on = defaultdict(lambda: [0.0, 0.0])           # name -> poss on, net pts on
        T = [0.0, 0.0]
        i = 0
        dates = sorted({g['date'] for g in gl})
        for d in dates + ['end']:
            snap = {}
            for n, (p, m) in on.items():
                offp = T[0] - p
                if p > 0 and offp > 20:
                    diff = 100 * m / p - 100 * (T[1] - m) / offp
                    h = 1 / (1 / p + 1 / offp)
                    snap[n] = diff * h / (h + k)
            out[(t, d)] = snap
            while i < len(gl) and (d == 'end' or gl[i]['date'] < d):
                g = gl[i]; i += 1
                si, a, b = side(g, t)
                P = poss_of(g); secs = g['secs']
                names_ = g['players'][t]
                for s in g['stints']:
                    ps = P * s[0] / secs
                    m = s[a] - s[b]
                    T[0] += ps; T[1] += m
                    for j in s[si]:
                        on[names_[j]][0] += ps; on[names_[j]][1] += m
    return out


# ---------------------------------------------------------------- a. availability with on/off
def avail_oo(logs, adj, w, repl=-3.0, n0=150.0, bench=C.BENCH):
    """cbb_games.avail (live settings) with each absent player's BPM moved by w x adj(team, date, pid)"""
    out = {}
    for t, gl in logs.items():
        st = {}
        for k in range(len(gl) + 1):
            v = 0.0
            dk = gl[k][0] if k < len(gl) else 'next'
            if k >= 3:
                last = gl[k - 1][1]
                bs = [(mn, bm) for g, mn, bm in st.values() if g < 0.6 * k or mn / g < 12]
                rp = (sum(b for _, b in bs) + repl * bench) / (sum(m for m, _ in bs) + bench)
                A = adj(t, dk) if w else {}
                for pid, (g, mn, bm) in st.items():
                    if g < 0.6 * k or mn / g < 12 or pid in last:
                        continue
                    bpm = (bm + -1.0 * n0) / (mn + n0) + w * A.get(pid, 0.0)
                    v += max(0.0, bpm - rp) * (mn / k) / 40
            out[(t, dk)] = round(v, 3)
            if k < len(gl):
                for pid, (mn, gb) in gl[k][1].items():
                    s = st.setdefault(pid, [0, 0.0, 0.0])
                    s[0] += 1; s[1] += mn; s[2] += gb * mn
    return out


_A = {}


def walk(av):
    games, btname, d1s, tprior, P, feats = _A['a']
    W, rows = C.run_walk(P, games, tprior, btname, d1s, av)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    return C.walk_pred(Xm, y, S, d1), y, S, d1, line, [g for g, _, _ in D], W


def one(key):
    av = _A['avs'][key]
    p, y, S, d1, line, D, W = walk(av)
    return key, (p, [g['id'] for g in D])


def tstat(e1, e0, days):
    """paired t on abs error, clustered by date"""
    d = defaultdict(float)
    for a, b, dd in zip(e1, e0, days):
        d[dd] += a - b
    v = np.array(list(d.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))) if len(v) > 2 else 0.0


def resid_test(r, x, S, mask, tune, held, days):
    """fit r ~ b x on tune seasons, apply to held seasons; abs error change and clustered t on each"""
    out = {}
    m = mask & np.isin(S, tune)
    if m.sum() < 50:
        return None
    b = float((x[m] @ r[m]) / (x[m] @ x[m]))
    res = r[m] - b * x[m]
    se = math.sqrt(res.var() / (x[m] @ x[m]))
    out['coef'] = round(b, 4); out['coefT'] = round(b / se, 2)
    for nm_, ss in (('tune', tune), ('held', held)):
        mm = mask & np.isin(S, ss)
        if mm.sum() < 50:
            continue
        e0, e1 = np.abs(r[mm]), np.abs(r[mm] - b * x[mm])
        out[nm_ + 'D'] = round(float(e1.mean() - e0.mean()), 4)
        out[nm_ + 'T'] = round(tstat(e1, e0, np.array(days)[mm]), 2)
        out[nm_ + 'N'] = int(mm.sum())
    return out


def main():
    seasons = [int(a) for a in sys.argv[1:]] or [s for s in range(2016, 2027) if os.path.exists(L.cache_path(s))]
    res = {'seasons': {}, 'validate': {}}
    LG, BT = {}, {}
    for s in seasons:
        g = L.load(s)
        ok = [x for x in g.values() if 'stints' in x]
        if len(ok) < 500:
            continue
        LG[s] = g
        roster, mins, tot = bt_index(s)
        tm, pm = ncaa_to_bt(g, roster)
        BT[s] = (roster, mins, tot, tm, pm)
        # coverage + minutes check
        errs = {}
        for x in g.values():
            errs[x.get('err', 'ok')] = errs.get(x.get('err', 'ok'), 0) + 1
        within = n = 0
        bchk = [0, 0]
        for x in ok:
            if 'chk' in x:
                bchk[0] += x['chk'][0]; bchk[1] += x['chk'][1]
            mine = defaultdict(float)
            for st in x['stints']:
                for j in st[1]:
                    mine[(x['home'], x['players'][x['home']][j])] += st[0] / 60
                for j in st[2]:
                    mine[(x['away'], x['players'][x['away']][j])] += st[0] / 60
            for (t, nme), mn in mine.items():
                pid = pm.get((t, nme)); b = tm.get(t)
                if pid is None or b is None:
                    continue
                bm = mins.get((b, x['date'], pid))
                if bm is None:
                    continue
                n += 1; within += abs(bm - mn) <= 2.0
        nd1 = len({x['id'] for x in g.values()})
        res['seasons'][s] = dict(games=nd1, read=len(ok), errors=errs, teamsMatched=len(tm),
                                 playersMatched=len(pm), btMinutesWithin2=round(within / max(1, n), 4), btN=n,
                                 boxMinutesWithin2=round(bchk[0] / max(1, bchk[1]), 4), boxN=bchk[1])
        print(s, res['seasons'][s], flush=True)
    if not LG:
        print('no lineup seasons'); return
    ls = sorted(LG)

    # base walk inputs
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    _A['a'] = (games, btname, d1s, tprior, F['params'], list(F['feats']))
    feats = list(F['feats'])
    # a. on/off-adjusted availability, in lineup seasons only
    OO = {s: onoff_to_date(LG[s]) for s in ls}
    import bisect

    def adj_for(s):
        """(Barttorvik team, date) -> {pid: shrunk on-off before that date}: the team's last snapshot on or before it
        (a snapshot keyed d holds games before d), the season's end for 'next'"""
        tm, pm = BT[s][3], BT[s][4]
        inv = {b: t for t, b in tm.items()}
        by = defaultdict(list)
        for (t, d) in OO[s]:
            if d != 'end':
                by[t].append(d)
        for t in by:
            by[t].sort()
        memo = {}

        def adj(bt, d):
            t = inv.get(bt)
            if t is None:
                return {}
            if (t, d) in memo:
                return memo[(t, d)]
            if d == 'next':
                snap = OO[s].get((t, 'end'), {})
            else:
                ds = by.get(t, [])
                j = bisect.bisect_right(ds, d) - 1
                snap = OO[s][(t, ds[j])] if j >= 0 else {}
            memo[(t, d)] = r = {pm[(t, n)]: v for n, v in snap.items() if (t, n) in pm}
            return r
        return adj
    ws = [0.25, 0.5, 1.0]
    _A['avs'] = {0.0: avs}
    for w in ws:
        av2 = dict(avs)
        for s in ls:
            av2[s] = avail_oo(C.bt_logs(s), adj_for(s), w)
        _A['avs'][w] = av2
    # live avail and the copy at w 0 must agree
    for s in ls[:1]:
        base = avail_oo(C.bt_logs(s), adj_for(s), 0.0)
        diff = sum(1 for k, v in base.items() if abs(v - avs[s].get(k, 0.0)) > 1e-6)
        res['availCopyMismatch'] = diff
    with get_context('fork').Pool(int(os.environ.get('PROCS', 4)), maxtasksperchild=1) as pool:
        out = dict(pool.map(one, [0.0] + ws))
    p0, ids = out[0.0]
    _, y, S, d1, line, D, W = walk(avs)
    days = [C.et_date(g['date']) for g in D]
    ok = ~np.isnan(p0) & d1
    lmask = ok & np.isin(S, ls)
    # the tune / held split inside the lineup seasons: the earliest half tunes
    tune_s = ls[:max(1, len(ls) // 2)] if len(ls) > 1 else ls
    held_s = [s for s in ls if s not in tune_s]
    res['split'] = dict(tune=tune_s, held=held_s)
    e0 = np.abs(p0 - y)
    res['onoff_inj'] = []
    for w in ws:
        p1, i1 = out[w]
        assert i1 == ids
        e1 = np.abs(p1 - y)
        r = {'w': w}
        for nm_, ss in (('tune', tune_s), ('held', held_s)):
            mm = ok & np.isin(S, ss)
            if mm.sum():
                r[nm_ + 'D'] = round(float(e1[mm].mean() - e0[mm].mean()), 4)
                r[nm_ + 'T'] = round(tstat(e1[mm], e0[mm], np.array(days)[mm]), 2)
                ll = mm & ~np.isnan(line)
                r[nm_ + 'LinedT'] = round(tstat(e1[ll], e0[ll], np.array(days)[ll]), 2)
        res['onoff_inj'].append(r)
        print('onoff_inj', r, flush=True)

    # margin-term residual tests (b cont, d garbage): per (tid, date) values from games before the date
    inv_bt = {s: {b: t for t, b in BT[s][3].items()} for s in ls}
    def tid_of(s, espn):
        return inv_bt[s].get(btname.get(espn))
    cont, garb = {}, {}
    for s in ls:
        prevpairs = None
        if s - 1 in LG:
            pp = defaultdict(float)
            for g in LG[s - 1].values():
                if 'stints' not in g:
                    continue
                for t, si in ((g['home'], 1), (g['away'], 2)):
                    nm_ = g['players'][t]
                    for st in g['stints']:
                        on5 = [nm_[j] for j in st[si]]
                        for a in range(5):
                            for b in range(a + 1, 5):
                                pp[(t,) + tuple(sorted((on5[a], on5[b])))] += st[0] / 60
            prevpairs = {k for k, v in pp.items() if v >= 100}
        for t, gl in team_games(LG[s]).items():
            num = den = 0.0
            full = [0.0, 0.0]; clean = [0.0, 0.0]
            i = 0
            for d in sorted({g['date'] for g in gl}):
                if prevpairs is not None and den > 0:
                    cont[(s, t, d)] = num / den
                if full[0] > 50 and clean[0] > 50:
                    garb[(s, t, d)] = 100 * clean[1] / clean[0] - 100 * full[1] / full[0]
                while i < len(gl) and gl[i]['date'] < d:
                    g = gl[i]; i += 1
                    si, a, b = side(g, t)
                    nm_ = g['players'][t]
                    P = poss_of(g); secs = g['secs']
                    mh = 0
                    tstart = 0.0
                    for st in g['stints']:
                        ps = P * st[0] / secs
                        m = st[a] - st[b]
                        full[0] += ps; full[1] += m
                        if not (tstart >= 1200 and abs(mh) >= 20):
                            clean[0] += ps; clean[1] += m
                        mh += m
                        tstart += st[0]
                        if prevpairs is not None:
                            on5 = [nm_[j] for j in st[si]]
                            for x1 in range(5):
                                for x2 in range(x1 + 1, 5):
                                    den += st[0] / 10
                                    num += st[0] / 10 * ((t,) + tuple(sorted((on5[x1], on5[x2]))) in prevpairs)
    r0 = y - p0
    def term(dic):
        x = np.zeros(len(y)); mask = np.zeros(len(y), bool)
        for i, g in enumerate(D):
            s = g['season']
            if s not in LG:
                continue
            th, ta = tid_of(s, g['home']), tid_of(s, g['away'])
            d = C.et_date(g['date'])
            vh, va = dic.get((s, th, d)), dic.get((s, ta, d))
            if vh is None or va is None:
                continue
            x[i] = vh - va; mask[i] = True
        return x, mask & ok
    xc, mc = term(cont)
    cs = sorted({s for (s, _, _) in cont})
    res['cont'] = dict(seasons=cs, n=int(mc.sum()))
    if len(cs) >= 2:
        res['cont'].update(resid_test(r0, xc, S, mc, cs[:len(cs) // 2], cs[len(cs) // 2:], days) or {})
    elif cs:
        # one season: fit on its first half of dates, test on the second
        dd = np.array(days)
        med = np.median([int(x.replace('-', '')) for x in dd[mc]])
        early = mc & np.array([int(x.replace('-', '')) <= med for x in dd])
        r = resid_test(r0, xc, np.where(early, 1, 2), mc, [1], [2], days)
        res['cont'].update(r or {}); res['cont']['note'] = 'one season with last season data: tune = its first half of dates, held = second half'
    print('cont', res['cont'], flush=True)
    xg, mg = term(garb)
    res['garbage'] = dict(n=int(mg.sum()))
    res['garbage'].update(resid_test(r0, xg, S, mg, tune_s, held_s, days) or {})
    print('garbage', res['garbage'], flush=True)

    # b2. preseason prior: returners' last-season on/off
    # the walk's prior net per team-season and the final net (W.final), Barttorvik team names
    res['pri_oo'] = {}
    pri = _A.get('pri') or {}
    rows = []
    for s in ls:
        if s - 1 not in LG:
            continue
        oo_prev = OO[s - 1]
        tm_prev, pm_prev = BT[s - 1][3], BT[s - 1][4]
        tot_prev = defaultdict(float)
        for (t, n), pid in pm_prev.items():
            pass
        # last season's minutes per (tid, name)
        mins_prev = defaultdict(float); team_min = defaultdict(float)
        for g in LG[s - 1].values():
            if 'stints' not in g:
                continue
            for t, si in ((g['home'], 1), (g['away'], 2)):
                for st in g['stints']:
                    team_min[t] += st[0] / 60
                    for j in st[si]:
                        mins_prev[(t, g['players'][t][j])] += st[0] / 60
        # this season's players by pid (returners = same Barttorvik team both seasons)
        roster_now = BT[s][0]
        for t, b in tm_prev.items():
            now = {r['pid'] for r in roster_now.get(b, [])}
            snap = oo_prev.get((t, 'end'), {})
            v = sum(snap.get(n, 0.0) * mins_prev[(t, n)] / max(1.0, team_min[t] / 5) for (tt, n), pid in pm_prev.items() if tt == t and pid in now)
            espn = [e for e, bn in btname.items() if bn == b]
            if not espn:
                continue
            e = espn[0]
            if s in W.final and e in W.final[s] and (s, e) in PRI:
                rows.append((s, e, v, W.final[s][e]['net'] - PRI[(s, e)]))
    if rows:
        Sx = np.array([r[0] for r in rows]); x = np.array([r[2] for r in rows]); r = np.array([r[3] for r in rows])
        b = float(x @ r / (x @ x)); se = math.sqrt(np.var(r - b * x) / (x @ x))
        res['pri_oo'] = dict(n=len(rows), seasons=sorted(set(Sx.tolist())), coef=round(b, 3), coefT=round(b / se, 2),
                             corr=round(float(np.corrcoef(x, r)[0, 1]), 3))
        for s in sorted(set(Sx.tolist())):
            m = Sx == s
            res['pri_oo'][f'corr{s}'] = round(float(np.corrcoef(x[m], r[m])[0, 1]), 3)
    print('pri_oo', res['pri_oo'], flush=True)

    # c. player: next-season BPM from last-season BPM (+ on/off)
    res['player'] = {}
    pr = []
    for s in ls:
        if s + 1 not in LG:
            continue
        tot0, tot1 = BT[s][2], BT[s + 1][2]
        snap = {}
        for t in BT[s][3]:
            for n, v in OO[s].get((t, 'end'), {}).items():
                pid = BT[s][4].get((t, n))
                if pid is not None:
                    snap[pid] = v
        for pid, v in snap.items():
            a, b = tot0.get(pid), tot1.get(pid)
            if a and b and a[0] >= 300 and b[0] >= 300:
                pr.append((s, a[1] / a[0], v, b[1] / b[0]))
    if len(pr) > 100:
        A = np.array(pr)
        X1 = np.c_[np.ones(len(A)), A[:, 1]]; X2 = np.c_[X1, A[:, 2]]
        yv = A[:, 3]
        # leave-one-season-pair-out when there are several pairs, else 5-fold by player
        folds = sorted(set(A[:, 0].tolist()))
        if len(folds) < 2:
            rng = np.random.default_rng(7); fid = rng.integers(0, 5, len(A))
        else:
            fid = np.searchsorted(folds, A[:, 0])
        p1 = np.zeros(len(A)); p2 = np.zeros(len(A))
        for f in set(fid.tolist()):
            tr, te = fid != f, fid == f
            p1[te] = X1[te] @ np.linalg.lstsq(X1[tr], yv[tr], rcond=None)[0]
            p2[te] = X2[te] @ np.linalg.lstsq(X2[tr], yv[tr], rcond=None)[0]
        e1, e2 = np.abs(p1 - yv), np.abs(p2 - yv)
        d = e2 - e1
        beta = np.linalg.lstsq(X2, yv, rcond=None)[0]
        res['player'] = dict(n=len(A), pairs=folds, maeBpm=round(float(e1.mean()), 4), maeBpmOO=round(float(e2.mean()), 4),
                             t=round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), coefOO=round(float(beta[2]), 4),
                             r2Bpm=round(1 - float(((p1 - yv) ** 2).mean() / yv.var()), 4), r2BpmOO=round(1 - float(((p2 - yv) ** 2).mean() / yv.var()), 4))
    print('player', res['player'], flush=True)
    json.dump(res, open(OUT, 'w'), indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    print('wrote', OUT)


PRI = {}
_orig_prior = C.Walk.season_prior


def _rec_prior(self, s, teams):
    pri, pf = _orig_prior(self, s, teams)
    for t, v in pri.items():
        PRI[(s, t)] = v.get('net', 0.0) if isinstance(v, dict) else v
    return pri, pf


C.Walk.season_prior = _rec_prior

if __name__ == '__main__':
    main()
