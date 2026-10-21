#!/usr/bin/env python3
"""Travel, tip time and the second day of back-to-back days in the college basketball game model.

    python3 scripts/cbb_venues.py           # first: team home cities and neutral-site venues (scripts/data/cbb_venues.json)
    python3 scripts/cbb_sched_research.py   # writes data/cbb_sched_research.json (numpy; ~10 min, Barttorvik logs cached)

The fit's walk-forward (scripts/cbb_games.py): each season scored by weights fit on the seasons before (D-I games),
the shipped settings and inputs; 2016-20 tunes, 2021-26 is held out. A candidate is kept only at paired per-game
t <= -1.5 on 2016-20 and not worse on 2021-26. Each candidate's plain effect (points, full-sample t) and the same
input against the closing line are reported too.
    margin   the visitor's trip (km), and at neutral sites the gap in the two teams' trips (the nearer crowd); km
             since each team's last game; time zones crossed; body-clock early (before 12:30) and late (9:30 PM+)
    totals   early and late local tips, body-clock early / late for either team
    players  rotation players on the second of back-to-back days (tournaments, events): played share and minutes
             against other games (Barttorvik logs), the availability side of rest (rest itself failed: cbb-game-model)
"""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_games as C
import harness as H

OUT = os.path.join(C.ROOT, 'data', 'cbb_sched_research.json')
VEN = os.path.join(C.HERE, 'data', 'cbb_venues.json')
ET = ZoneInfo('America/New_York')


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def r4(v):
    return round(float(v), 4)


def sched_feats(games):
    """game id -> (margin candidates, totals candidates)"""
    V = json.load(open(VEN))
    T, GV = V['teams'], V['games']
    lastv = {}                                            # team -> (season, venue) of its last game
    out = {}
    for g in sorted(games, key=lambda g: (g['date'], g['id'])):
        h, a = g['home'], g['away']
        H, A = T.get(h), T.get(a)
        site = GV.get(g['id']) if g['neutral'] else H
        t = dt.datetime.fromisoformat(g['date'].replace('Z', '+00:00')).astimezone(ET)
        eh = t.hour + t.minute / 60
        x = {k: 0.0 for k in ('trav', 'nearN', 'kmLast', 'tz', 'bodyE', 'bodyL', 'body')}
        tx = {k: 0.0 for k in ('tearly', 'tlate', 'tbodyE', 'tbodyL')}
        known = H is not None and A is not None and site is not None
        if known:
            kh, ka = hav(H, site), hav(A, site)
            if g['neutral']:
                x['nearN'] = max(-3.0, min(3.0, (ka - kh) / 1000))
            else:
                x['trav'] = ka / 1000
            lh, la = lastv.get(h), lastv.get(a)
            if lh and la and lh[0] == g['season'] and la[0] == g['season']:
                x['kmLast'] = (hav(la[1], site) - hav(lh[1], site)) / 1000
            x['tz'] = abs(A[2] - site[2]) - abs(H[2] - site[2])
            loc = eh + site[2]
            bh, ba = eh + H[2], eh + A[2]
            x['bodyE'] = (1.0 if ba < 12.5 else 0.0) - (1.0 if bh < 12.5 else 0.0)
            x['bodyL'] = (1.0 if ba >= 21.5 else 0.0) - (1.0 if bh >= 21.5 else 0.0)
            x['body'] = ba - bh
            tx = {'tearly': 1.0 if loc < 13 else 0.0, 'tlate': 1.0 if loc >= 21 else 0.0,
                  'tbodyE': (1.0 if ba < 12.5 else 0.0) + (1.0 if bh < 12.5 else 0.0),
                  'tbodyL': (1.0 if ba >= 21.5 else 0.0) + (1.0 if bh >= 21.5 else 0.0)}
        if site is not None:
            lastv[h] = lastv[a] = (g['season'], site)
        out[g['id']] = (x, tx, known)
    return out


def players(seasons):
    """rotation players (20+ minutes when they play, in 60% of games, 5+ games in) on the second of back-to-back days
    vs other games: minutes-weighted played share and minutes when played over their average, by season block"""
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
    for s in seasons:
        logs = C.bt_logs(s)
        for t, gl in logs.items():
            st = {}
            prev = None
            for k, (d, rows) in enumerate(gl):
                day = dt.date.fromisoformat(d)
                b2b = prev is not None and (day - prev).days == 1
                blk = '2016_20' if s <= C.TUNE_END else '2021_26'
                if k >= 5:
                    for pid, (g, mn) in st.items():
                        avg = mn / g
                        if g < 0.6 * k or avg < 20:
                            continue
                        a = acc[(blk, b2b, 'star' if avg >= 30 else 'rot')]
                        pl = pid in rows
                        a[0] += avg * pl; a[1] += avg; a[4] += 1
                        if pl:
                            a[2] += rows[pid][0]; a[3] += avg
                for pid, (mn, _) in rows.items():
                    z = st.setdefault(pid, [0, 0.0])
                    z[0] += 1; z[1] += mn
                prev = day
    out = {}
    for blk in ('2016_20', '2021_26'):
        for r in ('star', 'rot'):
            a, b = acc[(blk, True, r)], acc[(blk, False, r)]
            if not a[1] or not b[1]:
                continue
            out[f'{r}{blk}'] = {'n2': a[4], 'played2': r4(a[0] / a[1]), 'playedOther': r4(b[0] / b[1]),
                                'min2': r4(a[2] / a[3]), 'minOther': r4(b[2] / b[3])}
    return out


def coef(Xm, y, names):
    b = np.linalg.lstsq(Xm, y, rcond=None)[0]
    r = y - Xm @ b
    cov = (r @ r / (len(y) - len(b))) * np.linalg.pinv(Xm.T @ Xm)
    return {f: {'pts': round(float(v), 3), 't': round(float(v / math.sqrt(cov[i, i])), 2)} for i, (f, v) in enumerate(zip(names, b))}


def main():
    F = json.load(open(C.FIT))
    games, btname, d1s, tprior, avs = C.load_all()
    res = {'players': players(range(C.SCORE0, C.LAST + 1))}
    print('players', res['players'], flush=True)
    W, rows = C.run_walk(F['params'], games, tprior, btname, d1s, avs)
    feats = F['feats']
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    SF = sched_feats(games)
    names = ['trav', 'nearN', 'kmLast', 'tz', 'bodyE', 'bodyL', 'body']
    tnames = ['tearly', 'tlate', 'tbodyE', 'tbodyL']
    XC = np.array([[SF[g['id']][0][f] for f in names] for g, _, _ in D])
    TC = np.array([[SF[g['id']][1][f] for f in tnames] for g, _, _ in D])
    known = np.array([SF[g['id']][2] for g, _, _ in D])
    CL = (np.array([g['date'][:10] for g, _, _ in D]), np.array([f"{g['home']}-{g['season']}" for g, _, _ in D]))
    tune = (S >= C.SCORE0) & (S <= C.TUNE_END) & d1
    held = (S > C.TUNE_END) & d1
    base = C.walk_pred(Xm, y, S, d1)
    tbase = C.walk_pred(TX, ty, S, d1)
    res['base'] = {'feats': feats, 'games': int((tune | held).sum()), 'located': r4(known[tune | held].mean()),
                   'mae2016_20': r4(np.abs(base - y)[tune].mean()), 'mae2021_26': r4(np.abs(base - y)[held].mean()),
                   'tmae2016_20': r4(np.abs(tbase - ty)[tune].mean()), 'tmae2021_26': r4(np.abs(tbase - ty)[held].mean())}

    def cmp(p1, p0, yy):
        e1, e0 = np.abs(p1 - yy), np.abs(p0 - yy)
        c = {'mae2016_20': r4(e1[tune].mean()), 'd2016_20': r4(e1[tune].mean() - e0[tune].mean()),
             't2016_20': round(C.paired_t(e1[tune], e0[tune]), 2), 'mae2021_26': r4(e1[held].mean()),
             'd2021_26': r4(e1[held].mean() - e0[held].mean()), 't2021_26': round(C.paired_t(e1[held], e0[held]), 2)}
        for lab, k in (('2016_20', tune), ('2021_26', held)):
            c['tc' + lab] = round(H.paired(e1[k], e0[k], [CL[0][k], CL[1][k]])['t'], 2)   # harness: clustered by day, home team-season
        c['passes'] = bool(c['t2016_20'] <= -1.5 and c['d2021_26'] <= 0)
        return c

    def vs_close(v, res_, okk):
        out = {}
        for lab, k in (('2016_20', tune), ('2021_26', held)):
            kk = okk & k
            Z = np.column_stack([np.ones(kk.sum()), v[kk]])
            out[lab] = coef(Z, res_[kk], ['one', 'x'])['x']
        return out

    ok = ~np.isnan(line) & d1
    okt = ~np.isnan(tline) & d1
    M = {}
    for i, c in enumerate(names):
        X1 = np.column_stack([Xm, XC[:, i]])
        p1 = C.walk_pred(X1, y, S, d1)
        M[c] = cmp(p1, base, y)
        M[c]['games'] = int((XC[:, i] != 0)[tune | held].sum())
        M[c]['effect'] = coef(X1[d1 & (S >= C.SCORE0)], y[d1 & (S >= C.SCORE0)], feats + [c])[c]
        Z = np.column_stack([np.ones(ok.sum()), XC[ok, i]])
        M[c]['vsClose'] = coef(Z, (y - line)[ok], ['one', c])[c]
        M[c]['vsCloseBy'] = vs_close(XC[:, i], y - line, ok)
        print(c, M[c], flush=True)
    res['margin'] = M
    T = {}
    for i, c in enumerate(tnames):
        X1 = np.column_stack([TX, TC[:, i]])
        p1 = C.walk_pred(X1, ty, S, d1)
        T[c] = cmp(p1, tbase, ty)
        T[c]['games'] = int((TC[:, i] != 0)[tune | held].sum())
        T[c]['effect'] = coef(X1[d1 & (S >= C.SCORE0)], ty[d1 & (S >= C.SCORE0)], C.TFEATS + [c])[c]
        Z = np.column_stack([np.ones(okt.sum()), TC[okt, i]])
        T[c]['vsClose'] = coef(Z, (ty - tline)[okt], ['one', c])[c]
        T[c]['vsCloseBy'] = vs_close(TC[:, i], ty - tline, okt)
        print(c, T[c], flush=True)
    res['totals'] = T
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
