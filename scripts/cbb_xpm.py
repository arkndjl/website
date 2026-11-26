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

The form above is the core the fitted models read (the FV returner driver and the roster prior were fit on it, and both
carry recruiting rank and team terms of their own). The pXPM shown on the boards (pxpm2_*, beta2 in the fit file; Nov 26
2026, scripts/research/cbb_xpm_nov26/pxpm2.py) adds, per side, ridge 10:
  team context  = 5 x the minutes-weighted mean side BPM of his season-n team's lines / 10, and that x Fr
  recruit rating = Barttorvik rec / 100 x (Fr, So, Jr+), and a has-rating flag x (Fr, So, Jr+)
Walk-forward next-season team R2 .7325 -> .7457 (13/14 pairs, t 7.9), player r .770 -> .780, RMSE 2.359 -> 2.316; inside the
roster prior .7649 -> .7677 (t 3.7), as the FV driver a tie (t .9, 1.0), so the fitted models move at their next refit.

rXPM (descriptive, season only; rxpm_lines): BPM's split between teammates on GBPM's team totals, per side:
  rXPM_s = BPM_s + team minutes-weighted mean of (GBPM_s - BPM_s)
scripts/research/cbb_xpm_nov26/rxpm10.py: against GBPM the who-sat-out test is better in all three designs (t 3.0, 4.9, 1.9)
and next-season team R2 .611 -> .624 (12/14) on identical team totals; against BPM schedule-adjusted wins (WAB a game) R2
.880 -> .888 and win% .652 -> .676 (19/19 seasons each) on an identical split.

    python3 scripts/cbb_xpm.py --fit      # data/cbb_xpm_fit.json from the 2008-09 ... 2025-26 pairs (no 2026-27 outcome)
    python3 scripts/cbb_xpm.py --fit2     # adds beta2 (the board form) to that file; the core beta is left as it is
    python3 scripts/cbb_xpm.py --freeze   # scripts/data/cbb_pxpm_2026.json: board-form pXPM by Barttorvik pid after 2025-26
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
        meta[pid] = {'yr': r.get('yr'), 'hti': r.get('hti') or meta.get(pid, {}).get('hti'), 'name': r.get('name'), 'team': r.get('team'),
                     'rec': max(r.get('rec') or 0.0, meta.get(pid, {}).get('rec') or 0.0)}
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


CORE = True       # True: the fitted models read the box form (pxpm_parts), as before Nov 26 2026; research switch


def pxpm_lines(seasons):
    """the FV driver: pXPM after a career's last line (cbb_fit.features passes the seasons before the board season).
    The fuller form (pxpm2_parts: + team context + recruit rating) since Nov 26 2026 (pxpm3.py); team context from
    scripts/data/cbb_team_ctx.json, a season not in it from set_ctx or Barttorvik's file"""
    try: p = pxpm_parts(seasons) if CORE else pxpm2_parts(seasons)
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
    try: v = (values if CORE else values2)(int(year)).get(str(pid))
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


# ---------------------------------------------------------------- the board form (core + team context + recruit rating)
COLS2 = ['ctx', 'ctx_fr', 'rec_fr', 'rec_so', 'rec_up', 'has_fr', 'has_so', 'has_up']
FROZEN = os.path.join(D.ROOT, 'scripts', 'data', f'cbb_pxpm_{LAST_TARGET}.json')
_CTX = {}


def team_ctx(rows):
    """team -> (O, D): 5 x the minutes-weighted mean side BPM of a season's lines (a team's BPM sums to its rating)"""
    a = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        e = mins(r)
        if not e or r.get('obpm') is None or r.get('dbpm') is None: continue
        q = a[r.get('team')]; q[0] += e * r['obpm']; q[1] += e * r['dbpm']; q[2] += e
    return {t: (5 * q[0] / q[2], 5 * q[1] / q[2]) for t, q in a.items() if q[2]}


CTXF = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_team_ctx.json')
_CTXF = None


def ctx_of(team, year):
    """(O, D) team context of a Barttorvik team-season: the committed file (finished seasons, written by --freeze), else
    set_ctx (the season in progress, from the caller's own lines), else Barttorvik's season file; (0, 0), the average
    team, when none has it"""
    global _CTXF
    if year is None: return (0.0, 0.0)
    year = int(year)
    if year not in _CTX:
        if _CTXF is None:
            try: _CTXF = json.load(open(CTXF))['seasons']
            except (OSError, ValueError, KeyError): _CTXF = {}
        if str(year) in _CTXF: _CTX[year] = {t: tuple(v) for t, v in _CTXF[str(year)].items()}
        else:
            try: _CTX[year] = team_ctx(D.load_bt(year))
            except Exception: _CTX[year] = {}
    return _CTX[year].get(team, (0.0, 0.0))


def set_ctx(year, lines):
    """team context of a season from the caller's lines (cbb_live: the season in progress, where no file is committed)"""
    _CTX[int(year)] = team_ctx(lines)


def extra(n, ctx):
    """the board form's added terms for a line n, per side"""
    yr = n.get('yr'); fr = 0.0 if yr in CLS else 1.0; so = 1.0 if yr == 'So' else 0.0; up = 1.0 if yr in ('Jr', 'Sr') else 0.0
    rec = (n.get('rec') or 0.0) / 100; has = 1.0 if rec > 0 else 0.0
    return {s: np.array([c / 10, c / 10 * fr, rec * fr, rec * so, rec * up, has * fr, has * so, has * up]) for s, c in zip('od', ctx)}


def pxpm2_parts(seasons, ctx=None):
    """(pXPM, O, D), board form, after a career's last line; ctx = that line's team (O, D) context (looked up when None)"""
    if not seasons or not mins(seasons[-1]) or seasons[-1].get('obpm') is None or seasons[-1].get('dbpm') is None: return None
    F = _fit(); n = seasons[-1]; y = n.get('year')
    if 'beta2' not in F: return pxpm_parts(seasons)
    NM = F['norms'].get(str(y)) or F['norms'][max(F['norms'], key=int)]
    X = row(seasons, NM); E = extra(n, ctx if ctx is not None else ctx_of(n.get('team'), y))   # rec: the line's, 0 without
    o, d = (float(np.concatenate([X[s], E[s]]) @ np.array(F['beta2'][s])) for s in 'od')
    return o + d, o, d


_V2 = {}
def values2(y):
    """season y -> {pid: (pXPM, O, D, minutes)}, board form, from Barttorvik's files"""
    if y in _V2: return _V2[y]
    S = {k: season_lines(k) for k in (y - 2, y - 1, y)}; C = team_ctx(S[y].values()); res = {}
    for pid, n in S[y].items():
        p = pxpm2_parts([S[k][pid] for k in (y - 2, y - 1) if pid in S[k]] + [n], C.get(n.get('team'), (0.0, 0.0)))
        if p: res[pid] = p + (mins(n),)
    _V2[y] = res
    return res


def fit2():
    """beta2: the core's design plus COLS2, same target, weights and ridge; the core beta is not refit"""
    global _FIT
    F = json.load(open(FIT)); S = {y: season_lines(y) for y in range(FIRST, LAST_TARGET + 1)}; k = 6 + len(BOX) + len(COLS2)
    A = {s: np.zeros((k, k)) for s in 'od'}; b = {s: np.zeros(k) for s in 'od'}
    for n in range(FIRST, LAST_TARGET):
        C = team_ctx(S[n].values()); rows, ys, ws = {'o': [], 'd': []}, {'o': [], 'd': []}, []
        for pid, q in S[n].items():
            nx = S[n + 1].get(pid)
            X = row([S[j][pid] for j in (n - 2, n - 1) if j in S and pid in S[j]] + [q], F['norms'][str(n)]); E = extra(q, C.get(q.get('team'), (0.0, 0.0)))
            ws.append(mins(nx))
            for s in 'od': rows[s].append(np.concatenate([X[s], E[s]])); ys[s].append(nx[s + 'bpm'] if nx else 0.0)
        w = np.array(ws); w = w / (w.sum() / max(1, (w > 0).sum()))
        for s in 'od':
            Xs = np.array(rows[s]); A[s] += (Xs * w[:, None]).T @ Xs; b[s] += (Xs * w[:, None]).T @ np.array(ys[s])
    P = np.zeros(k); P[6:] = LAM
    F['beta2'] = {s: [round(float(x), 5) for x in np.linalg.solve(A[s] + np.diag(P) + 1e-9 * np.eye(k), b[s])] for s in 'od'}
    F['cols2'] = F['cols'] + COLS2
    json.dump(F, open(FIT, 'w'), indent=1); _FIT = F
    print('cbb_xpm fit2', {s: dict(zip(COLS2, F['beta2'][s][-len(COLS2):])) for s in 'od'})
    return F


def freeze():
    """board-form pXPM by pid after LAST_TARGET's lines (a player whose last line is the season before carries that one),
    read by the boards so no workflow needs Barttorvik's season files"""
    out = {}
    for y in (LAST_TARGET - 1, LAST_TARGET):
        S = season_lines(y)
        for pid, v in values2(y).items(): out[pid] = [round(v[0], 2), round(v[1], 2), round(v[2], 2), y, S[pid].get('name'), S[pid].get('team')]
    json.dump({'season': LAST_TARGET, 'cols': ['pxpm', 'o', 'd', 'line', 'name', 'team'], 'players': out}, open(FROZEN, 'w'), separators=(',', ':'))
    print(FROZEN, len(out))
    ctx = {str(y): {t: [round(o, 3), round(d, 3)] for t, (o, d) in sorted(team_ctx(season_lines(y).values()).items())} for y in range(FIRST, LAST_TARGET + 1)}
    json.dump({'through': LAST_TARGET, 'seasons': ctx}, open(CTXF, 'w'), separators=(',', ':'))
    print(CTXF, sum(len(v) for v in ctx.values()))


_FZ = None
def frozen():
    """pid -> [pXPM, O, D, line season, name, team] (scripts/data/cbb_pxpm_<season>.json); {} when the file is missing"""
    global _FZ
    if _FZ is None:
        try: _FZ = json.load(open(FROZEN))['players']
        except (OSError, ValueError, KeyError): _FZ = {}
    return _FZ


# ---------------------------------------------------------------- rXPM (descriptive)
def rxpm_shift(lines, team=lambda l: l.get('team'), m=mins):
    """team -> (O, D) shift = minutes-weighted mean of (GBPM_s - BPM_s) over a season's lines that carry both"""
    a = defaultdict(lambda: [0.0, 0.0, 0.0])
    for l in lines:
        e = m(l)
        if not e or any(l.get(k) is None for k in ('obpm', 'dbpm', 'ogbpm', 'dgbpm')): continue
        q = a[team(l)]; q[0] += e * (l['ogbpm'] - l['obpm']); q[1] += e * (l['dgbpm'] - l['dbpm']); q[2] += e
    return {t: (q[0] / q[2], q[1] / q[2]) for t, q in a.items() if q[2]}


def rxpm_lines(lines, team=lambda l: l.get('team'), m=mins, shift=None):
    """sets xpm / oxpm / dxpm (rXPM) on each line of one season; a team with no game BPM keeps BPM"""
    sh = shift if shift is not None else rxpm_shift(lines, team, m)
    for l in lines:
        if l.get('obpm') is None or l.get('dbpm') is None: continue
        o, d = sh.get(team(l), (0.0, 0.0)); l['oxpm'] = l['obpm'] + o; l['dxpm'] = l['dbpm'] + d; l['xpm'] = l['oxpm'] + l['dxpm']
    return lines


if __name__ == '__main__':
    if '--fit' in sys.argv: fit()
    if '--fit2' in sys.argv: fit2()
    if '--freeze' in sys.argv: freeze()
