#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB XPM history, point in time: every Barttorvik player season 2008-2026 with its rXPM and the pXPM a model fit only
on earlier seasons would have given after it. The fits that take XPM as an input (Next, breakout odds, Transfer%, landing,
xXPM) train on this file, so a past season never sees coefficients learned from its own future.

    python3 scripts/cbb_xpm_hist.py     # -> scripts/data/cbb_xpm_hist.json.gz  {"pid|year": [...COLS]}

  xpm, oxpm, dxpm   rXPM of the season (scripts/cbb_xpm.py rxpm_lines), a player's stints minutes weighted
  px, pxo, pxd      pXPM, core form, after the season (projects the next one)
  px2, px2o, px2d   pXPM, board form (team context and recruit rating added)
  e                 minutes
pXPM coefficients for a season-y line are refit on the pairs (n, n + 1) with n + 1 <= y (expanding walk-forward, the
ridge and design of scripts/cbb_xpm.py). A 2008-2010 line has under three pairs behind it and takes the pairs through
2010-11 less its own. The z norms are the line's own season's."""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_xpm as XP

OUT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_xpm_hist.json.gz')
FIRST, LAST = XP.FIRST, XP.LAST_TARGET
NB = 6 + len(XP.BOX); N2 = NB + len(XP.COLS2)
COLS = ['bpm', 'obpm', 'dbpm', 'xpm', 'oxpm', 'dxpm', 'px', 'pxo', 'pxd', 'px2', 'px2o', 'px2d', 'e']


def build():
    S = {y: XP.season_lines(y) for y in range(FIRST, LAST + 1)}
    NM = {y: XP.norms(S[y].values()) for y in S}
    CT = {y: XP.team_ctx(S[y].values()) for y in S}
    X = {}
    for y in S:
        for pid, q in S[y].items():
            r = XP.row([S[k][pid] for k in (y - 2, y - 1) if k in S and pid in S[k]] + [q], NM[y])
            E = XP.extra(q, CT[y].get(q.get('team'), (0.0, 0.0)))
            X[(pid, y)] = {s: np.concatenate([r[s], E[s]]) for s in 'od'}
    G = {}
    for n in range(FIRST, LAST):
        pids = list(S[n]); w = np.array([XP.mins(S[n + 1].get(p)) for p in pids]); w = w / (w.sum() / max(1, (w > 0).sum()))
        G[n] = {}
        for s in 'od':
            Xs = np.array([X[(p, n)][s] for p in pids]); ys = np.array([(S[n + 1][p][s + 'bpm'] if p in S[n + 1] else 0.0) for p in pids])
            G[n][s] = ((Xs * w[:, None]).T @ Xs, (Xs * w[:, None]).T @ ys)

    def beta(pairs, k):
        out = {}
        for s in 'od':
            A = sum(G[n][s][0] for n in pairs)[:k, :k]; b = sum(G[n][s][1] for n in pairs)[:k]
            P = np.zeros(k); P[6:] = XP.LAM
            out[s] = np.linalg.solve(A + np.diag(P) + 1e-9 * np.eye(k), b)
        return out
    M = {}
    for y in S:
        pairs = [n for n in G if n + 1 <= y]
        if len(pairs) < 3: pairs = [n for n in G if n + 1 <= FIRST + 3 and n != y]
        b1, b2 = beta(pairs, NB), beta(pairs, N2)
        raw = XP.rxpm_lines([r for r in D.load_bt(y) if XP.mins(r) and r.get('bpm') is not None])
        acc = defaultdict(lambda: defaultdict(float))
        for r in raw:
            e = XP.mins(r); a = acc[str(r['pid'])]; a['e'] += e
            for k in ('bpm', 'obpm', 'dbpm', 'xpm', 'oxpm', 'dxpm'):
                a[k] += e * (r.get(k) if r.get(k) is not None else r['bpm'] if k == 'xpm' else 0.0)
        for pid, q in S[y].items():
            a = acc[pid]; x = X[(pid, y)]
            o1, d1 = float(x['o'][:NB] @ b1['o']), float(x['d'][:NB] @ b1['d']); o2, d2 = float(x['o'] @ b2['o']), float(x['d'] @ b2['d'])
            M[f'{pid}|{y}'] = [round(a[k] / a['e'], 2) for k in COLS[:6]] + [round(v, 2) for v in (o1 + d1, o1, d1, o2 + d2, o2, d2)] + [round(a['e'])]
    with gzip.GzipFile(OUT, 'wb', mtime=0) as f: f.write(json.dumps({'cols': COLS, 'rows': M}, separators=(',', ':')).encode())
    print(OUT, len(M))
    return M


_M = None
def load():
    """{(pid str, year int): {col: value}}; {} when the file is missing"""
    global _M
    if _M is None:
        try:
            d = json.load(gzip.open(OUT, 'rt'))
            _M = {(k.split('|')[0], int(k.split('|')[1])): dict(zip(d['cols'], v)) for k, v in d['rows'].items()}
        except (OSError, ValueError, KeyError): _M = {}
    return _M


def get(pid, year, k, default=None):
    """one number of a player season (pid as Barttorvik writes it: '12345' or 12345.0)"""
    try: p = str(int(float(pid)))
    except (TypeError, ValueError): p = str(pid)
    try: q = load().get((p, int(year)))
    except (TypeError, ValueError): q = None
    return q[k] if q and q.get(k) is not None else default


if __name__ == '__main__':
    build()
