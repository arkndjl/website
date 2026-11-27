#!/usr/bin/env python3
"""Round 2 R1-R3 (prereg.md) on scripts/nfl_war_proj_research.py's own frames and rows.

    python3 scripts/player_pctl.py --frames nfl
    python3 scripts/research/ctx_nov27/nfl/r123_proj.py     # -> r123.json

Checkpoint: the harness's week 11 rows (games before week 11) take this audit's through-week-9 replay for pXP/60 and
XV, so the candidate sees one week less than the baseline there, never more (the registered week 9 rows would have
given it one week more)."""
import json
import os

import numpy as np

import common as C
import nfl_war_proj_research as P
from nfl_war_proj import GROUPS, feats

MK = C.MK
mq = C.M.get('mq') or {}


def base(r, live):
    return feats('E', r['g'], r['W0'], r['W1'], r['W2'], r['h1'], r['h2'], r['s0'], r['s1'], r['a'], MK.signal(r['pid'], r['S']), live)


def extras(r, w):
    S, pid = r['S'], r['pid']
    rt = (C.RATE if w == 'end' else C.RATE9)[S].get(pid)
    px = C.pxp(S, pid, rt) if rt else 0.0
    f = [(px if r['g'] == g else 0.0) for g in GROUPS] + [1.0 if rt else 0.0]
    p0 = (C.FULL if w == 'end' else C.W9)[S].get(pid) or {}
    tg = max(1, p0.get('_tg') or 17)
    x0 = (p0.get('xv') or 0.0) * 17 / tg
    x1 = ((C.FULL.get(S - 1) or {}).get(pid) or {}).get('xv') or 0.0
    x2 = ((C.FULL.get(S - 2) or {}).get(pid) or {}).get('xv') or 0.0
    return f, [x0, x1, x2]


def test(R, tgt, live, w):
    R = [r for r in R if r[tgt] is not None and r['S'] >= 2018]
    y = np.array([r[tgt] for r in R]); S = np.array([r['S'] for r in R])
    E = [base(r, live) for r in R]
    ex = [extras(r, w) for r in R]
    e0 = (P.loso(np.array(E), y, S) - y) ** 2
    out = {'n': len(R), 'rmseE': round(float(np.sqrt(e0.mean())), 4)}
    seasons = sorted(set(S))
    for name, X in (('F_pxp', [a + b[0] for a, b in zip(E, ex)]), ('G_xv', [a + b[1] for a, b in zip(E, ex)])):
        e1 = (P.loso(np.array(X), y, S) - y) ** 2
        d = e1 - e0
        ds = np.array([d[S == s].mean() for s in seasons])
        out[name] = {'rmse': round(float(np.sqrt(e1.mean())), 4), 't': round(P.tstat(d), 2), 'tSeason': round(P.tstat(ds), 2),
                     'won': f'{int((ds < 0).sum())}/{len(seasons)}'}
    return out


def r3(R):
    """next-season WAR = rate x next-season snaps (17-game scale): Marcel WAR a snap prior, with and without the market shift"""
    rate = json.load(open(os.path.join(C.ROOT, 'data', 'pctl_fit_nfl.json')))['rates']['war']
    rows = []
    for r in R:
        if r['y1'] is None or r['S'] < 2015:
            continue
        n = T.get(r['S'] + 1, {}).get(r['pid'])
        if not n or n[1] <= 0:
            continue
        s = MK.signal(r['pid'], r['S'])
        k = f"{r['g']}:{s[0]}" if s else None
        sh = mq['b'][k] * (s[1] - mq['xb'][k]) if k in mq.get('b', {}) else 0.0
        den = r['marcel'] / (r['s0'] if r['s0'] else 1.0)          # at f = 1 marcel = rate x s0
        rows.append((r['S'], r['g'], den, sh, n[1], r['y1']))
    S = np.array([x[0] for x in rows]); y = np.array([x[5] for x in rows]); sn = np.array([x[4] for x in rows])
    r0 = np.array([x[2] for x in rows]); sh = np.array([x[3] for x in rows]); g = np.array([x[1] for x in rows])
    p0 = r0 * sn
    p1 = p0.copy()
    for s in sorted(set(S)):
        tr, te = S != s, S == s
        for G in GROUPS:
            a, b = tr & (g == G), te & (g == G)
            x = sh[a] * sn[a]
            sl = float((x * (y[a] - p0[a])).sum() / max((x * x).sum(), 1e-9))
            p1[b] = p0[b] + sl * sh[b] * sn[b]
    d = (p1 - y) ** 2 - (p0 - y) ** 2
    seasons = sorted(set(S))
    ds = np.array([d[S == s].mean() for s in seasons])
    return {'n': len(rows), 'rmse': [round(float(np.sqrt(((p0 - y) ** 2).mean())), 4), round(float(np.sqrt(((p1 - y) ** 2).mean())), 4)],
            't': round(P.tstat(d), 2), 'tSeason': round(P.tstat(ds), 2), 'won': f'{int((ds < 0).sum())}/{len(seasons)}'}


if __name__ == '__main__':
    F, rate, B = P.load()
    T = P.season_tab(F)
    live = json.load(open(P.OUT))['form']
    out = {}
    for w in ('11', 'end'):
        R = []
        for S in sorted(F):
            R += P.rows_at(F, T, B, rate, S, w)[0]
        for tgt in ('y1', 'y3'):
            out[f'{w}_{tgt}'] = test(R, tgt, live, w)
        if w == 'end':
            out['r3_pctl_prior'] = r3(R)
    json.dump(out, open(os.path.join(C.HERE, 'r123.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))
