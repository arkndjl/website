#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB pXPM: projected (next-season) box plus-minus per 100 possessions, O and D, from Barttorvik player seasons.

Per side s (O, D), a player's season n line and the two before it:
  h_s   = sum_k w_k e_k BPM_s,k / sum_k w_k e_k   (k = n, n-1, n-2; e = minutes)
  sh_s  = (E h_s + K mu_s) / (E + K)              (E = sum_k w_k e_k; mu_s = season n mean BPM_s of players under 200 minutes)
  pXPM_s = b . [1, sh_s, ln(1 + e_n/100), So, Jr, Sr, z(12 box rates) x e_n/(e_n + 200)]
  pXPM  = pXPM_O + pXPM_D
Box rates (steal, block, OREB, DREB, assist, turnover, FT rate, 3PA/100, rim share of shots, usage, TS, height) are
z-scored on the season's own norms (300+ minute players, minutes weighted, stored in the fit; a season after the fit
uses the last stored one), capped at 3 SD. b is fit on next-season side BPM weighted by next-season minutes, ridge 10 on
the box terms. Reads only columns every source of a season line carries (Barttorvik's file, the board's frozen prior,
cbb_live's game-log lines), so the FV board, its in-season regrade and the roster prior read one number.
Research and the backtests against BPM: scripts/research/cbb_xpm_nov26/ (the D side there took 25% GBPM; GBPM is not on
every line source, and BPM alone costs .4% of the D side's next-season squared error).

    python3 scripts/cbb_xpm.py --fit      # data/cbb_xpm_fit.json from the 2008-09 ... 2025-26 pairs (no 2026-27 outcome)
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D

FIT = os.path.join(D.ROOT, 'data', 'cbb_xpm_fit.json')
FIRST, LAST_TARGET = 2008, 2026          # lockbox: 2026-27 outcomes never enter the fit
PRM = {'o': (0.35, 0.2, 200), 'd': (0.6, 0.4, 100)}   # w1, w2, K (walk-forward modal pick)
BOX = ['stl', 'blk', 'orb', 'drb', 'ast', 'to', 'ftr', 'tpa100', 'rims', 'usg', 'ts', 'ht']
CLS = ['So', 'Jr', 'Sr']
LAM, LO = 10.0, 200
RATES = ('obpm', 'dbpm', 'stl', 'blk', 'orb', 'drb', 'ast', 'to', 'ftr', 'tpa100', 'usg', 'ts')


def mins(r): return (r.get('gp') or 0) * (r.get('mp') or 0) if r else 0.0


def box(r, k):
    if k == 'rims':
        a = (r.get('twopa') or 0) + (r.get('tpa') or 0)
        return (r.get('rima') or 0) / a if a else None
    if k == 'ht':
        h = r.get('hti'); return h if h and 66 <= h <= 90 else None
    return r.get(k)


def season_lines(y):
    """pid -> one line for season y from Barttorvik's file (stints merged, rates minutes weighted)"""
    P = defaultdict(lambda: defaultdict(float)); meta = {}
    if y < FIRST: return {}
    try: rows = D.load_bt(y)
    except Exception: rows = []
    for r in rows:
        e = mins(r)
        if not e or r.get('bpm') is None: continue
        pid = str(r['pid']); q = P[pid]; q['e'] += e
        for k in RATES: q[k] += (r.get(k) or 0.0) * e
        for k in ('rima', 'twopa', 'tpa'): q[k] += r.get(k) or 0.0
        meta[pid] = {'yr': r.get('yr'), 'hti': r.get('hti') or meta.get(pid, {}).get('hti'), 'name': r.get('name'), 'team': r.get('team')}
    out = {}
    for pid, q in P.items():
        e = q['e']; v = {k: q[k] / e for k in RATES}
        v.update(rima=q['rima'], twopa=q['twopa'], tpa=q['tpa'], gp=1.0, mp=e, year=y, **meta[pid])
        out[pid] = v
    return out


def norms(lines):
    """the season's box z norms and the sub-200-minute side means, from its lines"""
    L = list(lines); big = [r for r in L if mins(r) >= 300]; out = {'z': {}}
    for k in BOX:
        xs = [(box(r, k), mins(r)) for r in big if box(r, k) is not None]
        x, w = np.array([a for a, _ in xs]), np.array([b for _, b in xs])
        m = float(np.average(x, weights=w)); out['z'][k] = [round(m, 5), round(float(math.sqrt(np.average((x - m) ** 2, weights=w))) or 1.0, 5)]
    lo = [r for r in L if mins(r) < LO]
    out['mu'] = {s: round(float(np.mean([r[s + 'bpm'] or 0.0 for r in lo])), 4) for s in 'od'}
    return out


_FIT = None
def _fit():
    global _FIT
    if _FIT is None: _FIT = json.load(open(FIT))
    return _FIT


def row(seasons, NM):
    """design rows (O, D) for the last line of seasons (a career's lines in order); NM = norms of that line's season"""
    n = seasons[-1]; y = n.get('year'); e0 = mins(n)
    by = {s.get('year'): s for s in seasons[-3:]}
    out = {}
    for s, (w1, w2, K) in PRM.items():
        num = E = 0.0
        for k, w in enumerate((1.0, w1, w2)):
            q = by.get(y - k) if y is not None else (n if k == 0 else None)
            if q is None or q.get(s + 'bpm') is None: continue
            m = mins(q); num += w * m * q[s + 'bpm']; E += w * m
        x = [1.0, (num + K * NM['mu'][s]) / max(E + K, 1e-9), math.log1p(e0 / 100)] + [1.0 if n.get('yr') == c else 0.0 for c in CLS]
        for k in BOX:
            v = box(n, k); m, sd = NM['z'][k]
            x.append(0.0 if v is None else max(-3.0, min(3.0, (v - m) / sd)) * e0 / (e0 + 200))
        out[s] = np.array(x)
    return out


def pxpm_parts(seasons):
    """(pXPM, O, D) after a career's last line (seasons in order, each a Barttorvik-style line); None without minutes"""
    if not seasons or not mins(seasons[-1]) or seasons[-1].get('obpm') is None or seasons[-1].get('dbpm') is None: return None
    F = _fit(); y = seasons[-1].get('year')
    NM = F['norms'].get(str(y)) or F['norms'][max(F['norms'], key=int)]
    X = row(seasons, NM)
    o, d = float(X['o'] @ np.array(F['beta']['o'])), float(X['d'] @ np.array(F['beta']['d']))
    return o + d, o, d


def pxpm_lines(seasons):
    """the FV driver: pXPM after a career's last line (cbb_fit.features passes the seasons before the board season)"""
    try: p = pxpm_parts(seasons)
    except (OSError, ValueError, KeyError): return None
    return p[0] if p else None


_V = {}
def values(y):
    """season y -> {pid: (pXPM, O, D, minutes)} from Barttorvik's files"""
    if y in _V: return _V[y]
    S = {k: season_lines(k) for k in (y - 2, y - 1, y)}
    res = {}
    for pid, n in S[y].items():
        p = pxpm_parts([S[k][pid] for k in (y - 2, y - 1) if pid in S[k]] + [n])
        if p: res[pid] = p + (mins(n),)
    _V[y] = res
    return res


def pxpm_of(pid, year):
    """one player season's pXPM from Barttorvik's files (None without a line): the roster prior's input"""
    try: v = values(int(year)).get(str(pid))
    except (OSError, ValueError, TypeError, KeyError): return None
    return v[0] if v else None


def fit():
    global _FIT
    S = {y: season_lines(y) for y in range(FIRST, LAST_TARGET + 1)}
    NM = {str(y): norms(S[y].values()) for y in S}
    A = {s: np.zeros((6 + len(BOX),) * 2) for s in 'od'}; b = {s: np.zeros(6 + len(BOX)) for s in 'od'}
    for n in range(FIRST, LAST_TARGET):
        rows, ys, ws = {'o': [], 'd': []}, {'o': [], 'd': []}, []
        for pid, q in S[n].items():
            nx = S[n + 1].get(pid)
            X = row([S[k][pid] for k in (n - 2, n - 1) if k in S and pid in S[k]] + [q], NM[str(n)])
            ws.append(mins(nx))
            for s in 'od': rows[s].append(X[s]); ys[s].append(nx[s + 'bpm'] if nx else 0.0)
        w = np.array(ws); w = w / (w.sum() / max(1, (w > 0).sum()))
        for s in 'od':
            Xs = np.array(rows[s]); A[s] += (Xs * w[:, None]).T @ Xs; b[s] += (Xs * w[:, None]).T @ np.array(ys[s])
    P = np.zeros(6 + len(BOX)); P[6:] = LAM
    beta = {s: [round(float(x), 5) for x in np.linalg.solve(A[s] + np.diag(P) + 1e-9 * np.eye(len(P)), b[s])] for s in 'od'}
    out = {'asof': f'pairs {FIRST}-{FIRST + 1} ... {LAST_TARGET - 1}-{LAST_TARGET}', 'params': {s: list(p) for s, p in PRM.items()},
           'cols': ['const', 'history', 'ln_minutes'] + CLS + BOX, 'lam': LAM, 'beta': beta, 'norms': NM}
    json.dump(out, open(FIT, 'w'), indent=1); _FIT = out
    print('cbb_xpm fit', beta)
    return out


if __name__ == '__main__':
    if '--fit' in sys.argv: fit()
