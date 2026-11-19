# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Per-game player line candidates on the shipped walk's rows (PREREG.md 7a, 10b, 11).

    python3 player_test.py pre ROWS.pkl ESPN_DIR        # 7a preseason starts in the first 10 games' minutes
    python3 player_test.py ast ROWS.pkl TRACK_DIR       # 10b potential assists as the assists prior
    python3 player_test.py darko ROWS.pkl DARKO_DIR     # 11 DARKO minutes / per-100 scorecard and PRA stack

Walk-forward as the shipped fit (each season on the seasons before, 1,000+ training rows); |error| paired, clustered
by game. -> impl/nba/player_<name>.json"""
import datetime as dt, glob, json, os, pickle, sys
import numpy as np
import common as C
import nba_espn as E

STATS = ('min', 'pts', 'reb', 'ast')


def load(fn):
    d = pickle.load(open(fn, 'rb'))
    D = [r for r in d['rows'] if r['y'] and r['nv'] and r['mS'] >= 10 and not r['po']]
    return D, d['names'], d['feats']


def wf(A, y, S):
    pred = np.full(len(S), np.nan)
    for yr in sorted(set(S)):
        tr, te = S < yr, S == yr
        if tr.sum() < 1000: continue
        pred[te] = A[te] @ np.linalg.lstsq(A[tr], y[tr], rcond=None)[0]
    return pred


def base(D, feats, s):
    A = np.column_stack([[r['fx'][s][f] for r in D] for f in feats[s]])
    y = np.array([r['y'][STATS.index(s)] for r in D], float)
    return A, y


def score(e1, e0, msk, G, S):
    out = {}
    for nm, k in msk.items():
        k = k & ~np.isnan(e1) & ~np.isnan(e0)
        if not k.any(): continue
        p = C.paired((e1 - e0)[k], G[k])
        ss = sorted(set(S[k]))
        out[nm] = {'n': int(k.sum()), 'mae0': round(float(e0[k].mean()), 4), 'mae1': round(float(e1[k].mean()), 4), 'd': round(p['d'], 5), 't': round(p['t'], 2),
                   'seasonsLower': int(sum((e1 - e0)[k & (S == s)].mean() < 0 for s in ss)), 'seasons': len(ss)}
    return out


def verdict(r):
    h, t = r.get('held'), r.get('tune')
    return bool(h and t and h['t'] <= -2 and t['d'] < 0 and h['seasonsLower'] * 2 > h['seasons'])


def pre(D, names, feats, folder):
    S = np.array([r['S'] for r in D]); G = np.array([r['g'] for r in D])
    ps = {}
    for fn in glob.glob(os.path.join(folder, 'pre_*.json')):
        s = int(os.path.basename(fn)[4:8])
        by = {}
        for ev, day, tm, pid, nm, mn, st in json.load(open(fn)):
            by.setdefault(E.team(tm), {}).setdefault((day, ev), []).append((pid, mn, st))
        for tm, gm in by.items():
            last = sorted(gm)[-2:]
            for k in last:
                for pid, mn, st in gm[k]:
                    if st and mn > 0: ps[(s, tm, pid)] = ps.get((s, tm, pid), 0.0) + 1.0 / len(last)
    have = {int(os.path.basename(fn)[4:8]) for fn in glob.glob(os.path.join(folder, 'pre_*.json'))}
    A, y = base(D, feats, 'min')
    e = np.array([max(0.0, 1 - (r['gn'] - 1) / 10.0) if 1 <= r['gn'] <= 10 else 0.0 for r in D])
    p = np.array([ps.get((r['S'], r['t'], r['p']), 0.0) for r in D])
    b = np.array([r['fx']['min']['base'] for r in D])
    ok = np.isin(S, sorted(have))
    A, y, S, G, e, p, b = A[ok], y[ok], S[ok], G[ok], e[ok], p[ok], b[ok]
    p0 = wf(A, y, S); p1 = wf(np.column_stack([A, p * e, p * b * e]), y, S)
    early = e > 0
    msk = {'tune': early & np.isin(S, (2021, 2022)), 'mid2023': early & (S == 2023), 'held': early & (S >= 2024)}
    r = score(np.abs(p1 - y), np.abs(p0 - y), msk, G, S)
    r['startersShare'] = round(float(p[early].mean()), 3); r['seasonsWithPreseason'] = sorted(have)
    r['p'] = C.p2(r['held']['t']) if r['held']['t'] < 0 else 1.0
    r['pass_pre_holm'] = verdict(r)
    return r


def ast(D, names, feats, folder):
    import pandas as pd
    S = np.array([r['S'] for r in D]); G = np.array([r['g'] for r in D])
    pa = pd.read_csv(os.path.join(folder, 'passing.csv'))
    rate, conv = {}, {}
    for s in sorted(set(S)):
        d = pa[(pa.year == s - 1) & (pa.Minutes >= 200)]
        if not len(d): continue
        conv[s] = float(d.Assists.sum() / d['Potential Assists'].sum())
        find = C.matcher([(pid, names[pid]) for pid in {r['p'] for r in D if r['S'] == s} if pid in names])
        for nm, pot, mn in zip(d.Name, d['Potential Assists'], d.Minutes):
            pid = find(str(nm))
            if pid: rate[(s, pid)] = float(pot / mn)
    A, y = base(D, feats, 'ast')
    col = np.array([r['mS'] * rate[(r['S'], r['p'])] * conv[r['S']] if (r['S'], r['p']) in rate else r['fx']['ast']['base'] for r in D])
    p0 = wf(A, y, S); p1 = wf(np.column_stack([A, col]), y, S)
    msk = {'tune': np.isin(S, (2022, 2023)), 'held': S >= 2024}
    r = score(np.abs(p1 - y), np.abs(p0 - y), msk, G, S)
    r['matched'] = round(float(np.mean([(x['S'], x['p']) in rate for x in D])), 3)
    r['p'] = C.p2(r['held']['t']) if r['held']['t'] < 0 else 1.0
    r['pass_pre_holm'] = verdict(r)
    return r


def darko(D, names, feats, folder):
    import gzip
    import nba_games as N
    S = np.array([r['S'] for r in D]); G = np.array([r['g'] for r in D])
    hist = json.load(gzip.open(N.HIST))['games']
    poss = {}
    for g in hist:
        if g.get('poss') and g.get('t') == 2: poss.setdefault(g['S'], []).append(g['poss'])
    poss = {s: float(np.mean(v)) for s, v in poss.items()}
    pred0 = {}
    for s in STATS:
        A, y = base(D, feats, s); pred0[s] = (wf(A, y, S), y)
    snap = {}
    for fn in glob.glob(os.path.join(folder, 'x_*.json')):
        m, d = os.path.basename(fn)[:-5].rsplit('_', 1)
        snap.setdefault(dt.date.fromisoformat(d), {})[m] = json.load(open(fn))
    dates = sorted(d for d, v in snap.items() if len(v) == 5)
    idx = {}
    for d in dates:
        s = d.year + 1 if d.month >= 10 else d.year
        find = C.matcher([(pid, names[pid]) for pid in {r['p'] for r in D if r['S'] == s} if pid in names])
        mp = {}
        for nid, v in snap[d]['x_minutes'].items():
            pid = find(v[0])
            if pid and all(nid in snap[d][m] for m in snap[d]):
                mp[pid] = {m: snap[d][m][nid][2] for m in snap[d]}
        idx[d] = mp
    dk = {s: np.full(len(D), np.nan) for s in STATS}; rate = {s: np.full(len(D), np.nan) for s in STATS}
    for i, r in enumerate(D):
        day = dt.date.fromisoformat(r['tip'][:10])
        for d in dates:
            if 0 < (day - d).days <= 21 and r['p'] in idx[d]:
                v = idx[d][r['p']]; ps = poss.get(r['S'] - 1, 100.0) / 100.0
                per = {'pts': v['x_pts_100'], 'reb': v['x_drb_100'] + v['x_orb_100'], 'ast': v['x_ast_100']}
                dk['min'][i] = v['x_minutes']
                for s in per:
                    rate[s][i] = per[s] * ps / 48.0
                    dk[s][i] = rate[s][i] * v['x_minutes']
    ok = ~np.isnan(dk['min']) & ~np.isnan(pred0['min'][0])
    res = {'n': int(ok.sum()), 'dates': [str(d) for d in dates], 'scorecard': {}}
    for s in STATS:
        p0, y = pred0[s]
        res['scorecard'][s] = {'ours': round(float(np.abs(p0 - y)[ok].mean()), 4), 'darko': round(float(np.abs(dk[s] - y)[ok].mean()), 4),
                               't': round(C.paired((np.abs(dk[s] - y) - np.abs(p0 - y))[ok], G[ok])['t'], 2)}
    fit, hold = ok & (S == 2024), ok & (S >= 2025)
    pra0 = sum(pred0[s][0] for s in ('pts', 'reb', 'ast')); yy = sum(pred0[s][1] for s in ('pts', 'reb', 'ast'))
    pra1 = np.zeros(len(D)); cs = {}
    for s in ('pts', 'reb', 'ast'):
        p0, y = pred0[s]
        gap = rate[s] * pred0['min'][0] - p0
        c = float((gap[fit] * (y - p0)[fit]).sum() / (gap[fit] ** 2).sum())
        cs[s] = round(c, 4)
        pra1 += p0 + c * gap
    r = score(np.abs(pra1 - yy), np.abs(pra0 - yy), {'tune': fit, 'held': hold}, G, S)
    res['stack'] = r; res['c'] = cs
    res['p'] = C.p2(r['held']['t']) if r['held']['t'] < 0 else 1.0
    res['pass_pre_holm'] = bool(r['held']['t'] <= -2 and r['held']['seasonsLower'] == r['held']['seasons'])
    return res


if __name__ == '__main__':
    D, names, feats = load(sys.argv[2])
    r = {'pre': pre, 'ast': ast, 'darko': darko}[sys.argv[1]](D, names, feats, sys.argv[3])
    print(json.dumps(r, indent=1))
    json.dump(r, open(os.path.join(C.IMPL, f'player_{sys.argv[1]}.json'), 'w'), indent=1)
