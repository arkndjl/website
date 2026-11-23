#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Port pass Nov 23 2026, NHL cells C1-C7 (pre-registered: prereg.md here, sha256 in prereg.sha256).

    python3 scripts/research/port_nov23/hockey/port_hockey.py   -> results.json here

Lockbox: the NHL 2026-27 season (S = 2027) is never read: the game history stops at 2025-26 and the rookie test reads
season files up to 2026 only."""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
import harness as H                # noqa: E402
import nhl_data as D               # noqa: E402
import nhl_games as G              # noqa: E402
import nhl_audit_research as A     # noqa: E402

ROOT = os.path.dirname(SCR)
OUT = os.path.join(HERE, 'results.json')
LOCK = 2027


def cut(r):
    return {'d': round(float(r['d']), 6), 't': round(float(r['t']), 2), 'p': round(float(r['p']), 4), 'n': int(r['n'])}


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def season_start(rows):
    s0 = {}
    for g, f in rows:
        if not g['po']:
            s0[g['S']] = min(s0.get(g['S'], g['day']), g['day'])
    return s0


def early_flag(rows):
    s0 = season_start(rows)
    return np.array([float(G._days(s0[g['S']], g['day']) < 21) if g['S'] in s0 else 0.0 for g, f in rows])


def base_logit(rows, feats, y, S):
    """walk-forward logit from 2017; 2016 rows in-sample (training rows only)"""
    X = G.design(rows, feats)
    z = logit(G.walk_logit(X, y, S, 2017))
    m = S == 2016
    z[m] = X[m] @ G.logit_fit(X[m], y[m])
    return z


def base_total(rows, tot, S, lt):
    X = G.design(rows, G.TFEATS)
    T = G.walk_ols(X, tot, S, 2021, lt)
    m = (S == 2020) & lt
    b = np.linalg.lstsq(X[m], tot[m], rcond=None)[0]
    m2 = S == 2020
    T[m2] = X[m2] @ b
    return T


def returner_patch(on):
    orig = G.skater_value.__wrapped__ if hasattr(G.skater_value, '__wrapped__') else G.skater_value
    if not on:
        G.skater_value = orig
        return
    cnt = defaultdict(int)

    def sv(S, x):
        w = G._war(S)
        if w is None:
            return None
        ps, repl, avg = w
        pid, g = x[:-1], x[-1]
        if pid not in ps:
            w1 = G._war(S - 1)
            q = w1[0].get(pid) if w1 else None
            if q and q['gp'] >= 20:
                r = repl.get(g, 0.0)
                cnt[S] += 1
                return (r + 0.85 * (q['hpm'] - r)) * min(q['toi'] * 60 / q['gp'], 1800) / 3600
        return orig(S, x)
    sv.__wrapped__ = orig
    sv.cnt = cnt
    G.skater_value = sv


def rdel_feats(hist, k):
    """C6: team's latest lineup value this season minus its last S-1 lineup, both on season S's pricing"""
    out = {}
    cur, gp, last_ids = {}, defaultdict(int), {}
    prev_last, end = {}, {}
    S0 = None
    for g in hist:
        S = g['S']
        if S != S0:
            prev_last = {t: ids for (s, t), ids in last_ids.items() if s == S0}
            end = {}
            for t, ids in prev_last.items():
                v = G.ids_value(S, ids)
                if v is not None:
                    end[t] = v
            cur.clear(); gp.clear()
            S0 = S
        h, a = g['h'], g['a']
        f = {}
        for kk in k:
            if h in cur and a in cur and h in end and a in end:
                wh = math.exp(-gp[h] / kk) if kk else 1.0
                wa = math.exp(-gp[a] / kk) if kk else 1.0
                f[kk] = (cur[h] - end[h]) * wh - (cur[a] - end[a]) * wa
            else:
                f[kk] = 0.0
        out[g['id']] = f
        if g.get('hs') is None:
            continue
        for t in (h, a):
            ids = G._lineups(S).get(str(g['id']), {}).get(t)
            v = G.ids_value(S, ids)
            if v is not None:
                cur[t] = v
                last_ids[(S, t)] = ids
            gp[t] += 1
    return out


def win_cells(res):
    hist = [g for g in G.load_hist() if g['S'] < LOCK]
    assert max(g['S'] for g in hist) <= 2026
    sbr = D.load(A.SBR_OUT)
    fit = json.load(open(G.FIT))
    P, feats = fit['params'], fit['feats']
    mv = G.hist_moves(hist)
    h1 = A.with_sbr(hist, sbr)
    _, rows, _ = G.walk(h1, P, moves=mv)
    S, y, mg, tot, pc, tc, day = G.arrays(rows)
    tune, held = (S >= 2017) & (S <= 2023), S >= 2024
    tune2 = (S >= 2018) & (S <= 2023)

    def ll(X, first=2017, train=None):
        return H.logloss(G.walk_logit(X, y, S, first, train), y)
    lb = ll(G.design(rows, feats))

    def judge(l1, l0, tm):
        return {'tune': cut(H.paired(l1[tm], l0[tm], day[tm])), 'held': cut(H.paired(l1[held], l0[held], day[held])),
                'byHeldSeason': {int(s): round(float((l1[S == s] - l0[S == s]).mean() * 1000), 3) for s in (2024, 2025, 2026)}}
    z0 = base_logit(rows, feats, y, S)
    # C1 early stretch
    e = early_flag(rows)
    tr = S >= 2017
    l2b = ll(z0[:, None], 2018, tr)
    l2e = ll(np.column_stack([z0, e * z0, e]), 2018, tr)
    res['C1 early stretch win'] = judge(l2e, l2b, tune2)
    Xs = np.column_stack([z0, e * z0, e])[tr]
    res['C1 early stretch win']['coef_all'] = [round(float(v), 3) for v in G.logit_fit(Xs, y[tr])]
    res['C1 early stretch win']['earlyGames'] = int(e.sum())
    # C3 mdis
    d = defaultdict(float)
    mdis = np.zeros(len(rows))
    Sp = None
    for i, (g, f) in enumerate(rows):
        if g['S'] != Sp:
            d.clear(); Sp = g['S']
        h, a = g['h'], g['a']
        mdis[i] = d[h] - d[a]
        if not np.isnan(pc[i]):
            err = (logit(pc[i]) - z0[i]) - (d[h] - d[a])
            d[h] += 0.2 * err; d[a] -= 0.2 * err
    lm = ll(np.column_stack([G.design(rows, feats), mdis]))
    res['C3 mdis'] = judge(lm, lb, tune)
    res['C3 mdis']['coef_all'] = round(float(G.logit_fit(np.column_stack([G.design(rows, feats), mdis]), y)[-1]), 3)
    # C6 rdel
    rd = rdel_feats(h1, (20, 0))
    best = None
    var = {}
    for kk, lab in ((20, 'A exp(-gp/20)'), (0, 'B flat')):
        x = np.array([rd[g['id']][kk] for g, f in rows])
        l1 = ll(np.column_stack([G.design(rows, feats), x]))
        j = judge(l1, lb, tune)
        j['nonzero'] = int((x != 0).sum())
        var[lab] = j
        if best is None or j['tune']['t'] < var[best]['tune']['t']:
            best = lab
    res['C6 roster turnover rdel'] = {'variants': var, 'picked': best, 'tune': var[best]['tune'], 'held': var[best]['held']}
    # C5 returners: rerun the walk with the patched pricing
    returner_patch(True)
    G._LV.clear()
    _, rows_r, _ = G.walk(h1, P, moves=mv)
    cnt = dict(G.skater_value.cnt)
    returner_patch(False)
    G._LV.clear()
    assert [g['id'] for g, f in rows_r] == [g['id'] for g, f in rows]
    Xr = G.design(rows, feats)
    Xr[:, feats.index('rv')] = [f['rv'] for g, f in rows_r]
    lr = ll(Xr)
    res['C5 returners rv'] = judge(lr, lb, tune)
    res['C5 returners rv']['returnerSkaterGames'] = {int(k): v for k, v in sorted(cnt.items())}
    res['C5 returners rv']['rvChangedGames'] = int((np.abs(Xr[:, feats.index('rv')] - G.design(rows, ['rv'])[:, 0]) > 1e-9).sum())
    res['_win'] = {'games': int(len(rows)), 'baseFeats': feats, 'baseLLtune': round(float(lb[tune].mean()), 5),
                   'baseLLheld': round(float(lb[held].mean()), 5)}


def total_cells(res):
    hist = [g for g in G.load_hist() if g['S'] < LOCK]
    fit = json.load(open(G.FIT))
    P = fit['params']
    _, rows, _ = G.walk(hist, P, moves=G.hist_moves(hist))
    S, y, mg, tot, pc, tc, day = G.arrays(rows)
    lt = ~np.isnan(tc)
    held = (S >= 2024) & lt
    T0 = base_total(rows, tot, S, lt)

    def judge(T1, Tb, tm):
        k = tm & ~np.isnan(T1) & ~np.isnan(Tb)
        kh = held & ~np.isnan(T1) & ~np.isnan(Tb)
        return {'tune': cut(H.paired((T1[k] - tot[k]) ** 2, (Tb[k] - tot[k]) ** 2, day[k])),
                'held': cut(H.paired((T1[kh] - tot[kh]) ** 2, (Tb[kh] - tot[kh]) ** 2, day[kh])),
                'maeHeld': [round(float(np.abs(Tb[kh] - tot[kh]).mean()), 4), round(float(np.abs(T1[kh] - tot[kh]).mean()), 4)]}
    # C2 early totals shrink
    e = early_flag(rows)
    dm = defaultdict(list)
    for i, (g, f) in enumerate(rows):
        dm[g['day']].append(T0[i])
    dmean = np.array([np.mean(dm[g['day']]) for g, f in rows])
    tr = lt & (S >= 2021)
    one = np.ones(len(rows))
    Tb = H.walk_ols(np.column_stack([one, T0]), tot, S, 2022, train=tr)
    Te = H.walk_ols(np.column_stack([one, T0, e * (T0 - dmean)]), tot, S, 2022, train=tr)
    res['C2 early totals shrink'] = judge(Te, Tb, (S >= 2022) & (S <= 2023) & lt)
    res['C2 early totals shrink']['coef_all'] = [round(float(v), 3) for v in np.linalg.lstsq(
        np.column_stack([one, T0, e * (T0 - dmean)])[tr], tot[tr], rcond=None)[0]]
    # C4 tdis
    td = defaultdict(float)
    tdis = np.zeros(len(rows))
    Sp = None
    for i, (g, f) in enumerate(rows):
        if g['S'] != Sp:
            td.clear(); Sp = g['S']
        h, a = g['h'], g['a']
        tdis[i] = td[h] + td[a]
        if lt[i] and not np.isnan(T0[i]):
            err = (tc[i] - T0[i]) - (td[h] + td[a])
            td[h] += 0.2 * err; td[a] += 0.2 * err
    X = G.design(rows, G.TFEATS)
    Tbase = H.walk_ols(X, tot, S, 2021, train=lt)
    Tt = H.walk_ols(np.column_stack([X, tdis]), tot, S, 2021, train=lt)
    res['C4 tdis'] = judge(Tt, Tbase, (S >= 2021) & (S <= 2023) & lt)
    res['C4 tdis']['coef_all'] = round(float(np.linalg.lstsq(np.column_stack([X, tdis])[lt], tot[lt], rcond=None)[0][-1]), 3)


def rookie_cell(res):
    SD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
    files = {S: json.load(open(os.path.join(SD, f'{S}.json'))) for S in range(2009, LOCK)}
    gp = defaultdict(list)
    rk = []
    by = {S: {p['id']: p for p in d['players']} for S, d in files.items()}
    for S in sorted(files):
        d = files[S]
        if 2011 <= S <= 2023:
            for p in d['players']:
                g = gp.get(p['id'], [])
                if max(g, default=0) >= 25 or sum(1 for x in g if x >= 6) >= 2 or (p.get('age') or 0) >= 26:
                    continue
                if p['grp'] not in ('F', 'D') or p['toi'] < 200 or p.get('hpm') is None or p.get('ax') is None:
                    continue
                r = d['repl'][p['grp']]
                go = toi = 0.0
                for s in (S + 1, S + 2, S + 3):
                    q = by[s].get(p['id'])
                    if q:
                        go += q['go'] + q['gd']; toi += q['toi']
                tgt = (go + r * 600 / 60) / (toi + 600) * 60
                rk.append((S, p['hpm'], p['ax'] - 21, tgt, p['toi']))
        for p in d['players']:
            gp[p['id']].append(p['gp'])
    a = np.array(rk, float)
    C, hp, ag, tg, w = a.T
    pred = np.empty(len(a)); ks = {}
    for c in np.unique(C):
        m = C != c
        k = float(np.sum(w[m] * ag[m] * (tg[m] - hp[m])) / np.sum(w[m] * ag[m] ** 2))
        ks[int(c)] = round(k, 3)
        pred[C == c] = hp[C == c] + k * ag[C == c]
    wn = w / w.mean()
    sn, sb = wn * (tg - pred) ** 2, wn * (tg - hp) ** 2
    r = H.paired(sn, sb, C)
    better = sum(1 for c in np.unique(C) if sn[C == c].sum() < sb[C == c].sum())
    kall = float(np.sum(w * ag * (tg - hp)) / np.sum(w * ag ** 2))
    odd, even = (C % 2 == 1), (C % 2 == 0)
    kh = [float(np.sum(w[m] * ag[m] * (tg[m] - hp[m])) / np.sum(w[m] * ag[m] ** 2)) for m in (odd, even)]
    sp = [float(np.corrcoef(hp + kh[0] * ag, hp + kh[1] * ag)[0, 1])]
    res['C7 aHPM rookies'] = {'n': len(a), 'classes': len(np.unique(C)), 'held': cut(r), 'classesBetter': better,
                              'kLOCO': ks, 'kAll': round(kall, 3), 'kOddEven': [round(v, 3) for v in kh],
                              'splitHalfR': round(sp[0], 4),
                              'rmse': [round(float(math.sqrt(sb.mean())), 4), round(float(math.sqrt(sn.mean())), 4)]}


def main():
    res = {'asof': dt.date.today().isoformat(), 'prereg': 'prereg.md', 'prereg_sha256': open(os.path.join(HERE, 'prereg.sha256')).read().split()[2]}
    rookie_cell(res)
    print(json.dumps(res['C7 aHPM rookies']), flush=True)
    total_cells(res)
    print(json.dumps({k: res[k] for k in ('C2 early totals shrink', 'C4 tdis')}), flush=True)
    win_cells(res)
    cells = [k for k in res if k[:1] == 'C']
    ps = []
    for k in cells:
        ps.append(res[k]['held']['p'])
    adj = H.holm(ps)
    for k, p in zip(cells, adj):
        c = res[k]
        tune_ok = c['tune']['t'] <= -1.5 if 'tune' in c else True
        if k.startswith('C7'):
            tune_ok = c['held']['t'] <= -2 and c['classesBetter'] >= 8
        c['holmP'] = round(float(p), 4)
        c['pass'] = bool(tune_ok and p < 0.05)
    json.dump(res, open(OUT, 'w'), indent=1)
    for k in cells:
        print(k, json.dumps({x: res[k].get(x) for x in ('tune', 'held', 'holmP', 'pass')}))


if __name__ == '__main__':
    main()
