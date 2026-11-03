#!/usr/bin/env python3
"""NCAA Division II and III players on the College Basketball ARKBOARD, with D-1%: the chance a player is on a D-I
roster next season (the football board's FBS% for FCS players, scripts/cfb_fcs_up_fit.py).

    python3 scripts/cbb_lowdiv_pull.py 2024 2025 2026      # box scores (ncaa.com), once
    python3 scripts/cbb_lowdiv.py --fit                     # build, backtest, fit (needs the D-I careers kit and
                                                            # the 2023-24 / 2024-25 boxes in /mnt/project-files/cbb/lowdiv)
    python3 scripts/cbb_lowdiv.py                           # grade the live players with the committed fit (daily)

Universe: every D-II and D-III player with a box-score line in season S, S = 2023-24, 2024-25, 2025-26 (ncaa.com box
scores carry player lines from 2023-24). Outcome: on a D-I roster in S+1 and not in S, name-matched (scripts/names.py),
not listed as a D-I freshman (a D-I freshman sharing his name is a high school recruit). D-I rosters: Barttorvik
seasons (the careers kit, /mnt/project-files/cbb/kit) for 2024-25 and 2025-26, the 2026-27 board (cbb-all.json).

Features, all from season S: production (Game Score per 100 possessions at the team's pace, shrunk to the division
mean by minutes, z within division and season), minutes, games and starts shares, per-100 rates, team strength
(SRS from every score: margin = home - away + court, ridge), division, position. Class is in the 2023-24 box scores
only, so it can't be fit on the later cycles and stays out.

Fit on 2023-24 -> 2024-25 and 2024-25 -> 2025-26; a candidate stays if it lowers out-of-fold log loss (5 folds of
whole teams) in 4 of 5 folds. Tested out of time on 2025-26 -> 2026-27 (log loss, AUC, calibration by decile); the
live coefficients are refit on all three. Writes data/cbb_lowdiv.json (fit + backtest) and static/data/cbb-lowdiv.json.

Live: the players on this season's D-II and D-III rosters (ESPN: class, height, weight) with a line this season or
last (this season's minutes pooled with last season's at half weight), not on a D-I roster now. E[FV] = 20 + D-1% x V,
V = what his first D-I season would be worth: the translation (his line -> first D-I season BPM shrunk by minutes, a
ridge on the 318 movers of the first two cycles, chosen on the first and tested out of time both ways), spread by its
out-of-time misses, through the arrival value (FV above 20 from a first D-I season and class: a Poisson index and a
monotone map, chosen and checked out of fold on the careers kit's 2009-16 arrivals from below D-I, first D-I season not
as a freshman, no recruiting rank). NBA% the same with the NBA rate. The headline is the D-I board's own E[FV] -> FV
map, from (20, 20). The translation's end-to-end check (its V against what the movers' first seasons were worth) is
right-signed both ways but not significant (t .98 / .54), so V is not applied to D-I newcomers, who keep the board's
own newcomer grade.
"""
import concurrent.futures as cf
import csv
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fv_scale as FS
import names as N

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'scripts', 'data', 'cbb_lowdiv')
ARCH = os.environ.get('CBB_LOWDIV_ARCH', '/mnt/project-files/cbb/lowdiv')   # 2023-24, 2024-25 boxes (fit only)
KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit/college_seasons_nba.csv')
FIT = os.path.join(ROOT, 'data', 'cbb_lowdiv.json')
OUT = os.path.join(ROOT, 'static', 'data', 'cbb-lowdiv.json')
ALL = os.path.join(ROOT, 'static', 'data', 'cbb-all.json')
ESPN = os.path.join(RAW, 'espn.json.gz')
LIVE = 2027
CYCLES = [(2024, 2025), (2025, 2026), (2026, 2027)]
TRAIN, TEST = CYCLES[:2], CYCLES[2]
DIVS = {'d2': 'D-II', 'd3': 'D-III'}
K_MIN = 200          # minutes that weigh a line half toward the division mean
PRIOR_W = 0.5        # live: last season's minutes count half
I = {k: j for j, k in enumerate(['team', 'name', 'pos', 'yr', 'st', 'mp', 'fg', 'fga', 'fg3', 'fg3a', 'ft', 'fta', 'orb', 'trb', 'ast',
                                  'tov', 'pf', 'stl', 'blk', 'pts'])}
SUM = ['mp', 'fg', 'fga', 'fg3', 'fg3a', 'ft', 'fta', 'orb', 'trb', 'ast', 'tov', 'pf', 'stl', 'blk', 'pts']
LABEL = {'prod': 'production (Game Score per 100, vs his division)', 'msh': 'share of team minutes', 'gsh': 'games played',
         'stsh': 'starts', 'srs': 'team strength', 'wpct': 'team win%', 'd3': 'Division III', 'pts': 'scoring rate',
         'reb': 'rebounding rate', 'ast': 'assist rate', 'stl': 'steal rate', 'blk': 'block rate', 'tov': 'turnover rate',
         'ts': 'true shooting', 'tpr': '3PA rate', 'big': 'center', 'guard': 'guard', 'prodxsrs': 'production x team strength',
         'prod2': 'production (top end)'}
CANDS = ['prod', 'prod2', 'msh', 'gsh', 'stsh', 'srs', 'wpct', 'd3', 'pts', 'reb', 'ast', 'stl', 'blk', 'tov', 'ts', 'tpr', 'big', 'guard', 'prodxsrs']


# ---------------------------------------------------------------- seasons
def load_games(s):
    """{game id: (div, date, teams, players)} for season s, both divisions (a D-II vs D-III game once)."""
    out = {}
    for d in DIVS:
        p = os.path.join(RAW, f'{d}-{s}.json.gz')
        if not os.path.exists(p): p = os.path.join(ARCH, f'{d}-{s}.json.gz')
        if not os.path.exists(p): continue
        for gid, (date, teams, players) in json.load(gzip.open(p, 'rt')).items():
            out.setdefault(gid, (d, date, teams, players))
    return out


def srs(games):
    """team ratings in points: margin = r_home - r_away + court (neutral when neither is home), ridge toward 0."""
    ids = sorted({t[0] for _, _, teams, _ in games.values() for t in teams})
    col = {t: j for j, t in enumerate(ids)}
    A, b = [], []
    for _, _, teams, _ in games.values():
        (a, pa, ha), (c, pc, hc) = (teams[0][0], teams[0][2], teams[0][3]), (teams[1][0], teams[1][2], teams[1][3])
        row = np.zeros(len(ids) + 1); row[col[a]] = 1; row[col[c]] = -1; row[-1] = ha - hc
        A.append(row); b.append(max(-30, min(30, pa - pc)))
    A, b = np.array(A), np.array(b)
    P = np.eye(A.shape[1]) * 2.0; P[-1, -1] = 0
    beta = np.linalg.solve(A.T @ A + P, A.T @ b)
    return {t: float(beta[col[t]]) for t in ids}


def season_lines(s):
    """player lines for season s: {(div, team id, name key): row}, with team context."""
    G = load_games(s)
    if not G: return {}, {}
    R = srs(G)
    team = defaultdict(lambda: {'g': 0, 'w': 0, 'poss': 0.0, 'name': '', 'div': None})
    pl = {}
    for gid, (d, date, teams, players) in G.items():
        for k, t in enumerate(teams):
            o = teams[1 - k]; T = team[t[0]]
            T['g'] += 1; T['w'] += t[2] > o[2]; T['name'] = t[1] or T['name']
            st = t[4]; T['poss'] += st['fieldGoalsAttempted'] + 0.44 * st['freeThrowsAttempted'] - st['offensiveRebounds'] + st['turnovers']
        divs = {}
        for p in players: divs.setdefault(p[0], d)
        for p in players:
            if p[I['mp']] <= 0: continue
            key = N.key(p[I['name']])
            if not key: continue
            r = pl.setdefault((p[0], key), {'team': p[0], 'key': key, 'name': p[I['name']], 'g': 0, 'gs': 0, 'pos': Counter(), 'yr': Counter(),
                                              'last': date, **{k: 0.0 for k in SUM}})
            r['g'] += 1; r['gs'] += p[I['st']]; r['pos'][p[I['pos']]] += 1; r['yr'][p[I['yr']]] += 1; r['last'] = max(r['last'], date)
            for k in SUM: r[k] += p[I[k]]
    # a team's division: where most of its games were filed
    tdiv = defaultdict(Counter)
    for d, _, teams, _ in G.values():
        for t in teams: tdiv[t[0]][d] += 1
    for t, T in team.items():
        T['div'] = tdiv[t].most_common(1)[0][0]; T['pace'] = T['poss'] / max(1, T['g']); T['srs'] = R.get(t, 0.0)
    out = {}
    for (tid, key), r in pl.items():
        T = team[tid]
        if T['g'] < 8: continue            # an NAIA or other visitor: only the games against D-II / D-III teams
        r['div'] = T['div']; r['tg'] = T['g']; r['tw'] = T['w']; r['pace'] = T['pace']; r['srs'] = T['srs']; r['tname'] = T['name']
        r['pos'] = r['pos'].most_common(1)[0][0] or ''
        y = [c for c, n in r['yr'].most_common() if c]; r['yr'] = y[0] if y else ''
        out[(T['div'], tid, key)] = r
    return out, team


def gs(r):
    return (r['pts'] + 0.4 * r['fg'] - 0.7 * r['fga'] - 0.4 * (r['fta'] - r['ft']) + 0.7 * r['orb'] + 0.3 * (r['trb'] - r['orb']) + r['stl']
            + 0.7 * r['ast'] + 0.7 * r['blk'] - 0.4 * r['pf'] - r['tov'])


def per100(r, x):
    poss = max(r['mp'], 1) / 40 * r['pace']
    return x / poss * 100


def norms(lines):
    """minute-weighted division means and SDs of the shrunk rates, and the SRS spread, for one season."""
    out = {}
    for d in DIVS:
        rs = [r for (dv, _, _), r in lines.items() if dv == d and r['mp'] >= 40]
        if not rs: continue
        w = np.array([r['mp'] for r in rs])
        o = {}
        for k, f in RATE.items():
            v = np.array([f(r) for r in rs]); m = float((w * v).sum() / w.sum())
            o[k] = [m, float(math.sqrt((w * (v - m) ** 2).sum() / w.sum())) or 1.0]
        out[d] = o
    s = np.array([r['srs'] for r in lines.values()])
    out['srs'] = [float(s.mean()), float(s.std()) or 1.0]
    return out


RATE = {'gs': lambda r: per100(r, gs(r)), 'pts': lambda r: per100(r, r['pts']), 'reb': lambda r: per100(r, r['trb']),
        'ast': lambda r: per100(r, r['ast']), 'stl': lambda r: per100(r, r['stl']), 'blk': lambda r: per100(r, r['blk']),
        'tov': lambda r: per100(r, r['tov']),
        'ts': lambda r: r['pts'] / (2 * (r['fga'] + 0.44 * r['fta'])) if r['fga'] + r['fta'] > 0 else 0.5,
        'tpr': lambda r: r['fg3a'] / r['fga'] if r['fga'] > 0 else 0.0}


def features(r, nm):
    """the candidate features of one line (r may pool two seasons: mp and stat sums, tg its team games)."""
    d = r['div']; z = {}
    for k, f in RATE.items():
        m, sd = nm[d][k]
        v = f(r) if r['mp'] > 0 else m
        v = (r['mp'] * v + K_MIN * m) / (r['mp'] + K_MIN)          # shrunk to the division mean by minutes
        z[k] = (v - m) / sd
    z['prod'] = z.pop('gs')
    z['prod2'] = max(0.0, z['prod'] - 1.0)
    z['msh'] = min(1.0, r['mp'] / (40 * max(1, r['tg'])))
    z['gsh'] = min(1.0, r['g'] / max(1, r['tg']))
    z['stsh'] = r['gs'] / max(1, r['g'])
    z['srs'] = (r['srs'] - nm['srs'][0]) / nm['srs'][1]
    z['wpct'] = r['tw'] / max(1, r['tg']) - 0.5
    z['d3'] = 1.0 if d == 'd3' else 0.0
    z['big'] = 1.0 if r['pos'] == 'C' else 0.0
    z['guard'] = 1.0 if r['pos'] == 'G' else 0.0
    z['prodxsrs'] = z['prod'] * z['srs']
    return z


# ---------------------------------------------------------------- D-I rosters (labels)
def d1_rosters():
    """{season: {name key: set of classes}} for the D-I seasons used as outcomes."""
    out = defaultdict(lambda: defaultdict(set))
    need = {s for c in CYCLES for s in c}
    with open(KIT, newline='') as f:
        for r in csv.DictReader(f):
            y = int(float(r['year'] or 0))
            if y in need or y + 1 in need: out[y][N.key(r['name'])].add(r['yr'] or '')
    a = json.load(open(ALL)); ci = {c: j for j, c in enumerate(a['cols'])}
    for r in a['rows']: out[LIVE][N.key(r[ci['name']])].add(r[ci['cls']] or '')
    return out


def frame(cycles, D1):
    X, y, grp, meta = [], [], [], []
    for s, s1 in cycles:
        lines, _ = season_lines(s)
        nm = norms(lines)
        dup = Counter(k for (_, _, k) in lines)
        for (d, tid, key), r in lines.items():
            if dup[key] > 1 or key in D1[s]: continue        # two players under one name; or on a D-I roster this season too
            nxt = D1[s1].get(key)
            moved = bool(nxt) and not (nxt <= {'Fr'})
            X.append(features(r, nm)); y.append(1 if moved else 0); grp.append(f'{s}:{tid}'); meta.append((s, d, r['name'], r['tname']))
    return X, np.array(y), grp, meta


# ---------------------------------------------------------------- logit
def logit_fit(X, y, lam=1.0, w=None):
    X = np.column_stack([np.ones(len(X)), X]); b = np.zeros(X.shape[1])
    w = np.ones(len(y)) if w is None else w
    P = np.eye(X.shape[1]) * lam; P[0, 0] = 0
    for _ in range(50):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        g = X.T @ (w * (p - y)) + P @ b
        H = (X * (w * p * (1 - p))[:, None]).T @ X + P
        step = np.linalg.solve(H, g); b -= step
        if np.abs(step).max() < 1e-8: break
    return b


def predict(b, X): return 1 / (1 + np.exp(-np.clip(np.column_stack([np.ones(len(X)), X]) @ b, -30, 30)))


def ll(p, y): p = np.clip(p, 1e-6, 1 - 1e-6); return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def auc(p, y):
    o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else float('nan')


def mat(F, keys, sc=None):
    M = np.array([[f[k] for k in keys] for f in F]) if keys else np.zeros((len(F), 0))
    if sc is None: sc = (M.mean(0), M.std(0) + 1e-9) if keys else (np.zeros(0), np.ones(0))
    return (M - sc[0]) / sc[1], sc


def folds(grp, k=5):
    ts = sorted(set(grp)); rng = np.random.RandomState(7); rng.shuffle(ts)
    f = {t: i % k for i, t in enumerate(ts)}
    return np.array([f[g] for g in grp])


def cv_loss(F, y, fo, keys):
    out = []
    for i in range(fo.max() + 1):
        tr, te = fo != i, fo == i
        Xtr, sc = mat([F[j] for j in np.where(tr)[0]], keys)
        Xte, _ = mat([F[j] for j in np.where(te)[0]], keys, sc)
        out.append(ll(predict(logit_fit(Xtr, y[tr]), Xte), y[te]))
    return np.array(out)


def select(F, y, grp):
    """forward selection: add the candidate that lowers mean out-of-fold log loss most, while it beats the current set
    in 4 of 5 team folds; then drop any kept term whose removal doesn't hurt in 4 of 5."""
    fo = folds(grp); keep = []; base = cv_loss(F, y, fo, keep); ev = []
    while True:
        best = None
        for c in CANDS:
            if c in keep: continue
            l = cv_loss(F, y, fo, keep + [c]); gain = base - l
            if (gain > 0).sum() >= 4 and (best is None or gain.mean() > best[1].mean()): best = (c, gain, l)
        if not best: break
        keep.append(best[0]); base = best[2]
        ev.append({'driver': best[0], 'gain': round(float(best[1].mean()), 5), 'folds': int((best[1] > 0).sum())})
        print(f'  + {best[0]:9s} OOF log loss {base.mean():.5f} (gain {best[1].mean():.5f}, {int((best[1] > 0).sum())}/5)')
    for c in list(keep):
        rest = [k for k in keep if k != c]
        l = cv_loss(F, y, fo, rest)
        if ((l - base) > 0).sum() < 4:
            keep = rest; base = l; print(f'  - {c} (dropped: removal doesn\'t hurt in 4 of 5)')
    return keep, ev


def calib(p, y, n=10):
    o = np.argsort(p); out = []
    for b in np.array_split(o, n):
        if len(b): out.append([round(float(p[b].mean()), 4), round(float(y[b].mean()), 4), int(len(b))])
    return out


def fit():
    D1 = d1_rosters()
    print('building the cycles')
    F, y, grp, meta = frame(TRAIN, D1)
    Ft, yt, gt, mt = frame([TEST], D1)
    print(f'train {len(y)} lines, {int(y.sum())} moved up ({y.mean():.2%}); test {len(yt)}, {int(yt.sum())} ({yt.mean():.2%})')
    for s in sorted({m[0] for m in meta}) + [TEST[0]]:
        for d in DIVS:
            ys = [yy for yy, m in zip(list(y) + list(yt), meta + mt) if m[0] == s and m[1] == d]
            if ys: print(f'  {s} {d}: {len(ys)} lines, {np.mean(ys):.2%} on D-I next season')
    keep, ev = select(F, y, grp)
    X, sc = mat(F, keep); b = logit_fit(X, y)
    Xt, _ = mat(Ft, keep, sc); pt = predict(b, Xt)
    base = np.full(len(yt), y.mean())
    test = {'cycle': f'{TEST[0] - 1}-{str(TEST[0])[2:]} to {TEST[1] - 1}-{str(TEST[1])[2:]}', 'n': int(len(yt)), 'moved': int(yt.sum()),
            'auc': round(auc(pt, yt), 4), 'll': round(ll(pt, yt), 5), 'llBase': round(ll(base, yt), 5),
            'mean': round(float(pt.mean()), 4), 'rate': round(float(yt.mean()), 4), 'calib': calib(pt, yt),
            'byDiv': {DIVS[d]: {'pred': round(float(pt[[m[1] == d for m in mt]].mean()), 4), 'rate': round(float(yt[[m[1] == d for m in mt]].mean()), 4)}
                      for d in DIVS if any(m[1] == d for m in mt)}}
    # the top of the test: how often the highest-odds players moved
    o = np.argsort(-pt)
    test['top'] = {str(n): round(float(yt[o[:n]].mean()), 3) for n in (25, 100, 250)}
    test['topPred'] = {str(n): round(float(pt[o[:n]].mean()), 3) for n in (25, 100, 250)}
    print('test', json.dumps({k: v for k, v in test.items() if k != 'calib'}))
    for c in test['calib']: print('   pred %.3f  actual %.3f  n %d' % tuple(c))
    # live coefficients: refit on all three cycles
    Fa, ya = F + Ft, np.concatenate([y, yt])
    Xa, sca = mat(Fa, keep); ba = logit_fit(Xa, ya)
    nba = arrivals()
    A = arrive_fit(); T = translate_fit(D1, A)
    out = {'asof': time.strftime('%Y-%m-%d'), 'train': '2023-24 to 2025-26', 'n': int(len(ya)), 'moved': int(ya.sum()),
           'kept': keep, 'keptLabels': [LABEL[k] for k in keep], 'evidence': [dict(e, label=LABEL[e['driver']]) for e in ev],
           'beta': [round(float(v), 5) for v in ba], 'mu': [round(float(v), 5) for v in sca[0]], 'sd': [round(float(v), 5) for v in sca[1]],
           'test': test, 'arrivals': nba, 'kMin': K_MIN, 'priorW': PRIOR_W, 'arrive': A, 'translate': T}
    json.dump(out, open(FIT, 'w'), indent=1)
    print('wrote', FIT)
    return out


def arrivals():
    """D-I arrivals from below D-I in the careers kit: first D-I season not as a freshman, no recruiting rank, first
    seasons 2009-16 (careers scored). Their NBA rate and mean realized FV."""
    first = {}
    with open(KIT, newline='') as f:
        for r in csv.DictReader(f):
            pid = r['pid'] or r['name'] + r['team']; y = int(float(r['year'] or 0))
            if pid not in first or y < first[pid][0]: first[pid] = (y, r)
    rs = [r for y, r in first.values() if 2009 <= y <= 2016 and (r['yr'] or '') in ('So', 'Jr', 'Sr') and not (r['on3rk'] or r['rk247'] or r['rec'] and float(r['rec'] or 0) > 0)]
    fv = [float(r['realized_fv']) if r['realized_fv'] else 20.0 for r in rs]
    nba = [1 if float(r['nba_games'] or 0) > 0 else 0 for r in rs]
    return {'n': len(rs), 'nba': round(float(np.mean(nba)), 4), 'fv': round(float(np.mean(fv)), 3)}



# ---------------------------------------------------------------- FV: translation and arrival value
POWER = {'ACC', 'B10', 'B12', 'SEC', 'P12', 'BE'}
BS_K, BS_0 = 300, -6.0       # a D-I season's BPM shrunk to -6 by 300 minutes (the arrival value's input)
T_CANDS = ['prod', 'prod2', 'msh', 'stsh', 'gsh', 'srs', 'd3', 'pts', 'reb', 'ast', 'stl', 'blk', 'tov', 'ts', 'tpr', 'big', 'guard', 'ht']
A_CANDS = ['bs', 'bs2', 'bs4', 'cls', 'ht']      # what a projection below D-I can fill


def num(v, d=float('nan')):
    try: return float(v)
    except (TypeError, ValueError): return d


def bs_of(r):
    """a Barttorvik season's BPM, shrunk by minutes (mp is per game)"""
    mp = num(r['mp'], 0) * num(r['gp'], 0); b = num(r['bpm'], BS_0)
    return (b * mp + BS_0 * BS_K) / (mp + BS_K)


def ht_of(h):
    m = re.match(r"\s*(\d)\D+(\d+)", h or '')
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def ridge(X, y, lam=3.0):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd]); P = np.eye(Z.shape[1]) * lam; P[0, 0] = 0
    return np.linalg.solve(Z.T @ Z + P, Z.T @ y), mu, sd


def rpred(m, X): b, mu, sd = m; return np.column_stack([np.ones(len(X)), (X - mu) / sd]) @ b


def poisson(Z, y, lam=1.0):
    A = np.column_stack([np.ones(len(Z)), Z]); b = np.zeros(A.shape[1]); b[0] = math.log(y.mean() + 1e-6)
    P = np.eye(A.shape[1]) * lam; P[0, 0] = 0
    for _ in range(100):
        m = np.exp(np.clip(A @ b, -20, 8)); step = np.linalg.solve((A * m[:, None]).T @ A + P, A.T @ (m - y) + P @ b); b -= step
        if np.abs(step).max() < 1e-9: break
    return b


def pav(x, y):
    """non-decreasing fit of y on sorted x, as (x, y) knots"""
    vals, wts, xs = [], [], []
    for xi, yi in zip(x, y):
        vals.append(yi); wts.append(1.0); xs.append(xi)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            w = wts[-2] + wts[-1]
            xs[-2:] = [(xs[-2] * wts[-2] + xs[-1] * wts[-1]) / w]; vals[-2:] = [(vals[-2] * wts[-2] + vals[-1] * wts[-1]) / w]; wts[-2:] = [w]
    return np.array(xs), np.array(vals)


def arrive_map(X, y, nba):
    """FV above 20 (and NBA odds) from a first D-I season: a Poisson index, then the non-decreasing map of the outcome
    on it (bounded by what such players became, where the exponential alone ran the top 10 at 2.7x their outcome)"""
    mu, sd = X.mean(0), X.std(0) + 1e-9; b = poisson((X - mu) / sd, y)
    idx = np.column_stack([np.ones(len(X)), (X - mu) / sd]) @ b; o = np.argsort(idx)
    kx, ky = pav(idx[o], y[o]); nx, ny = pav(idx[o], nba[o])
    return {'b': b.tolist(), 'mu': mu.tolist(), 'sd': sd.tolist(), 'kx': kx.tolist(), 'ky': ky.tolist(), 'nx': nx.tolist(), 'ny': ny.tolist()}


def arrive_x(M, bs, ht, cls):
    """the arrival value's inputs from a first-season BPM (array), height and class at arrival (2 So .. 4 Sr)"""
    bs = np.asarray(bs, float); one = np.ones(len(bs))
    v = {'bs': bs, 'bs2': np.maximum(0, bs - 2), 'bs4': np.maximum(0, bs - 4), 'ht': one * ht, 'cls': one * cls}
    return np.column_stack([v[k] for k in M['keep']])


def arrive_val(M, X, nba=False):
    idx = np.column_stack([np.ones(len(X)), (X - np.array(M['mu'])) / np.array(M['sd'])]) @ np.array(M['b'])
    return np.interp(idx, M['nx'], M['ny']) if nba else np.interp(idx, M['kx'], M['ky'])


def arrival_frame():
    """D-I arrivals from below D-I in the careers kit (first D-I season not as a freshman, no recruiting rank, first
    seasons 2009-16): their first D-I season and what their careers became (FV above 20, any NBA game)."""
    first = {}
    with open(KIT, newline='') as f:
        for r in csv.DictReader(f):
            pid = r['pid'] or r['name'] + r['team']; y = int(num(r['year'], 0))
            if pid not in first or y < first[pid][0]: first[pid] = (y, r)
    F, y, nba = [], [], []
    for yr, r in first.values():
        if not (2009 <= yr <= 2016 and (r['yr'] or '') in ('So', 'Jr', 'Sr')) or r['on3rk'] or r['rk247'] or num(r['rec'], 0) > 0: continue
        b = bs_of(r)
        F.append({'bs': b, 'bs2': max(0.0, b - 2), 'bs4': max(0.0, b - 4), 'mpct': num(r['min_per'], 0) / 100, 'cls': {'So': 2, 'Jr': 3, 'Sr': 4}[r['yr']],
                  'ht': num(r['hti'], 78), 'power': 1.0 if r['conf'] in POWER else 0.0, 'obpm': num(r['obpm'], -3), 'usg': num(r['usg'], 20)})
        y.append(num(r['realized_fv'], 20) - 20); nba.append(1.0 if num(r['nba_games'], 0) > 0 else 0.0)
    return F, np.array(y), np.array(nba)


def fwd(cands, loss, base):
    """forward selection on 5 fold losses: the candidate that cuts mean loss most while it helps in 4 of 5 folds"""
    keep, ev, tested = [], [], 0
    while True:
        best = None
        for c in cands:
            if c in keep: continue
            tested += 1; l = loss(keep + [c]); g = base - l
            if (g > 0).sum() >= 4 and g.mean() > 0 and (best is None or g.mean() > best[1].mean()): best = (c, g, l)
        if not best: return keep, ev, tested
        keep.append(best[0]); base = best[2]
        ev.append({'driver': best[0], 'gain': round(float(best[1].mean()), 4), 'folds': int((best[1] > 0).sum())})
        print(f'  + {best[0]:6s} gain {best[1].mean():.4f} ({int((best[1] > 0).sum())}/5)')


def pdev(y, m):
    """Poisson deviance per player (the FV above 20 is a count-like, mostly-zero outcome)"""
    m = np.maximum(m, 1e-6); return 2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-12) / m), 0) - (y - m))


def tstat(d): return float(d.mean() / (d.std() / math.sqrt(len(d)))) if len(d) > 1 and d.std() > 0 else 0.0


def arrive_fit():
    """the arrival value: FV above 20 from a first D-I season, selected and checked out of fold on 2009-16 arrivals"""
    F, y, nba = arrival_frame()
    fo = np.random.RandomState(3).randint(0, 5, len(y))
    M = lambda keys: np.array([[x[k] for k in keys] for x in F], float)
    def oof(keys):
        out = np.zeros(len(y))
        for k in range(5):
            tr = fo != k
            out[~tr] = arrive_val(arrive_map(M(keys)[tr], y[tr], nba[tr]), M(keys)[~tr]) if keys else y[tr].mean()
        return out
    mse = lambda p: np.array([((y[fo == k] - p[fo == k]) ** 2).mean() for k in range(5)])
    print(f'arrival value: {len(y)} D-I arrivals from below D-I, 2009-16')
    keep, ev, tested = fwd(A_CANDS, lambda ks: mse(oof(ks)), mse(oof([])))
    p, p0 = oof(keep), np.full(len(y), y.mean())
    o = np.argsort(-p)
    test = {'n': int(len(y)), 'mse': round(float(((y - p) ** 2).mean()), 4), 'mseFlat': round(float(((y - y.mean()) ** 2).mean()), 4),
            't': round(tstat((y - p0) ** 2 - (y - p) ** 2), 2), 'tDev': round(tstat(pdev(y, p0) - pdev(y, p)), 2), 'candidates': tested,
            'top': {str(n): [round(float(p[o[:n]].mean()), 2), round(float(y[o[:n]].mean()), 2)] for n in (25, 50, 100, 200)}}
    print('  ', test)
    return dict(arrive_map(M(keep), y, nba), keep=keep, evidence=ev, test=test, mean=round(float(y.mean()), 4))


def mover_frame(D1):
    """D-II / D-III players on a D-I roster the next season (not as a freshman), with that first D-I season"""
    kit, dupk = defaultdict(dict), Counter()
    with open(KIT, newline='') as f:
        for r in csv.DictReader(f):
            y = int(num(r['year'], 0))
            if y in {c[1] for c in TRAIN}: k = N.key(r['name']); dupk[(y, k)] += 1; kit[y][k] = r
    rows = []
    for s, s1 in TRAIN:
        lines, _ = season_lines(s); nm = norms(lines); dup = Counter(k for (_, _, k) in lines)
        for (d, tid, key), r in lines.items():
            k1 = kit[s1].get(key)
            if dup[key] > 1 or key in D1[s] or dupk[(s1, key)] != 1 or not k1 or k1['yr'] == 'Fr': continue
            x = features(r, nm); x['ht'] = num(k1['hti'], 78)
            rows.append({'s': s, 'x': x, 'bs': bs_of(k1), 'cls': {'So': 2, 'Jr': 3, 'Sr': 4}.get(k1['yr'], 3), 'team': f'{s}:{tid}', 'name': r['name']})
    return rows


def translate_fit(D1, A):
    """a line below D-I -> his first D-I season (shrunk BPM), fit on the movers; chosen on the first cycle's movers (5
    team folds) and tested out of time both ways, on the BPM and on the arrival value it implies"""
    rows = mover_frame(D1)
    S = np.array([r['s'] for r in rows]); Y = np.array([r['bs'] for r in rows]); H = np.array([r['x']['ht'] for r in rows])
    C = np.array([r['cls'] for r in rows], float)
    X = lambda keys, idx: np.array([[rows[i]['x'][k] for k in keys] for i in idx], float)
    s0, s1 = TRAIN[0][0], TRAIN[1][0]
    tr = np.where(S == s0)[0]
    teams = sorted({rows[i]['team'] for i in tr}); perm = np.random.RandomState(5).permutation(len(teams))
    fo = np.array([perm[teams.index(rows[i]['team'])] % 5 for i in tr])
    def loss(keys):
        out = []
        for k in range(5):
            a, b = tr[fo != k], tr[fo == k]
            p = rpred(ridge(X(keys, a), Y[a]), X(keys, b)) if keys else np.full(len(b), Y[a].mean())
            out.append(((Y[b] - p) ** 2).mean())
        return np.array(out)
    print(f'translation: {len(rows)} movers ({(S == s0).sum()} after {s0 - 1}-{str(s0)[2:]}, {(S == s1).sum()} after {s1 - 1}-{str(s1)[2:]})')
    keep, ev, tested = fwd(T_CANDS, loss, loss([]))
    G = lambda bs, ht, cl: arrive_val(A, arrive_x(A, bs, ht, cl))
    act = G(Y, H, C); tests, res_all, dd = [], [], []
    for a, b in ((S == s0, S == s1), (S == s1, S == s0)):
        m = ridge(X(keep, np.where(a)[0]), Y[a]); mu = rpred(m, X(keep, np.where(b)[0]))
        res = Y[a] - rpred(m, X(keep, np.where(a)[0])); res_all += list(Y[b] - mu)
        V = np.array([G(u + res, np.full(len(res), h), np.full(len(res), c)).mean() for u, h, c in zip(mu, H[b], C[b])])
        d = (act[b] - act[a].mean()) ** 2 - (act[b] - V) ** 2; dd += list(d)
        tests.append({'fit': f'{int(S[a][0]) - 1}-{str(int(S[a][0]))[2:]}', 'n': int(b.sum()),
                      'rmse': round(float(np.sqrt(((Y[b] - mu) ** 2).mean())), 3), 'rmseFlat': round(float(np.sqrt(((Y[b] - Y[a].mean()) ** 2).mean())), 3),
                      'r': round(float(np.corrcoef(mu, Y[b])[0, 1]), 3), 'tBpm': round(tstat((Y[b] - Y[a].mean()) ** 2 - (Y[b] - mu) ** 2), 2),
                      'value': round(float(V.mean()), 3), 'valueActual': round(float(act[b].mean()), 3), 'tValue': round(tstat(d), 2)})
        print('  ', tests[-1])
    m = ridge(X(keep, range(len(rows))), Y)
    # the spread around a projection: the out-of-time misses of both directions (in-sample residuals run narrow)
    q = np.quantile(np.array(res_all), np.linspace(0.01, 0.99, 49))
    return {'keep': keep, 'evidence': ev, 'candidates': tested, 'b': m[0].tolist(), 'mu': m[1].tolist(), 'sd': m[2].tolist(),
            'res': [round(float(v), 3) for v in q], 'n': len(rows), 'test': tests, 'tValue': round(tstat(np.array(dd)), 2)}

# ---------------------------------------------------------------- live
def espn_get(url):
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())
        except Exception:
            time.sleep(1 + 2 * i)
    return None


def espn_rosters(force=False):
    """this season's rosters of ESPN's non-D-I teams (class, height, weight), refreshed weekly."""
    if not force and os.path.exists(ESPN) and time.time() - os.path.getmtime(ESPN) < 6 * 86400:
        return json.load(gzip.open(ESPN, 'rt'))
    core = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball'
    lst = espn_get(f'{core}/seasons/{LIVE}/types/2/groups/51/teams?limit=1000') or espn_get(f'{core}/seasons/{LIVE - 1}/types/2/groups/51/teams?limit=1000')
    ids = [re.search(r'teams/(\d+)', x['$ref']).group(1) for x in (lst or {}).get('items', [])]
    def one(t):
        d = espn_get(f'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{t}/roster')
        if not d or not d.get('athletes'): return t, None
        return t, {'loc': d['team'].get('location'), 'name': d['team'].get('displayName'),
                   'players': [[a['id'], a.get('fullName'), (a.get('position') or {}).get('abbreviation'), (a.get('experience') or {}).get('abbreviation'),
                                a.get('displayHeight'), a.get('weight'), (a.get('headshot') or {}).get('href')] for a in d['athletes']]}
    def logo(t):
        u = f'https://a.espncdn.com/i/teamlogos/ncaa/500/{t}.png'
        try:
            with urllib.request.urlopen(urllib.request.Request(u, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'}), timeout=20) as r:
                return u if r.status == 200 else None
        except Exception:
            return None
    out = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for t, v in ex.map(one, ids):
            if v: out[t] = v
        for t, u in zip(list(out), ex.map(logo, list(out))): out[t]['logo'] = u
    print(f'ESPN: {len(out)} of {len(ids)} non-D-I teams with a roster')
    if len(out) >= 100 or not os.path.exists(ESPN): json.dump(out, gzip.open(ESPN, 'wt'), separators=(',', ':'))
    else: out = json.load(gzip.open(ESPN, 'rt'))
    return out


CLS = {'FR': ('Fr', 1), 'SO': ('So', 2), 'JR': ('Jr', 3), 'SR': ('Sr', 4), 'GR': ('Gr', 5), '5Y': ('Gr', 5)}


def pool(a, b, wb):
    """a line pooling this season (a) and last (b, weighted wb); team context from the newer."""
    if not b: return dict(a)
    if not a:
        r = dict(b); [r.__setitem__(k, b[k] * wb) for k in SUM + ['g', 'gs']]; r['tg'] = b['tg'] * wb; return r
    r = dict(a)
    for k in SUM + ['g', 'gs']: r[k] = a[k] + wb * b[k]
    r['tg'] = a['tg'] + wb * b['tg']
    return r


def grade():
    fit = json.load(open(FIT))
    keep, beta, mu, sd = fit['kept'], np.array(fit['beta']), np.array(fit['mu']), np.array(fit['sd'])
    now, tnow = season_lines(LIVE)
    prev, tprev = season_lines(LIVE - 1)
    nm_prev = norms(prev); nm = norms(now) if sum(r['mp'] for r in now.values()) > 20000 else nm_prev
    ros = espn_rosters('--rosters' in sys.argv)
    a = json.load(open(ALL)); ci = {c: j for j, c in enumerate(a['cols'])}
    d1 = {N.key(r[ci['name']]) for r in a['rows']}
    # the D-I board's E[FV] -> headline FV (as the D-I players it doesn't list are placed, cbb_live.unboarded), from
    # (20, 20): an E of 20, no NBA career, is a 20
    eb = sorted((r[ci['e']], r[ci['fvx']]) for r in a['rows'] if r[ci['e']] is not None)
    ex, fx = np.array([20.0] + [e for e, _ in eb]), np.maximum.accumulate(np.array([20.0] + [x for _, x in eb]))
    AV, TR = fit.get('arrive'), fit.get('translate')
    # ncaa.com teams (name, division) of the two seasons, matched to ESPN's by name
    teams = {}
    for T in (tprev, tnow):
        for tid, t in T.items():
            if t['g'] >= 8: teams[tid] = t
    espn_of = match_teams(teams, now, prev, ros)
    lines_now = defaultdict(list); lines_prev = defaultdict(list)
    for (d, tid, key), r in now.items(): lines_now[key].append(r)
    for (d, tid, key), r in prev.items(): lines_prev[key].append(r)
    rows = []
    seen = set()
    for tid, eid in espn_of.items():
        e = ros[eid]; t = teams[tid]
        for aid, name, pos, cls, ht, wt, photo in e['players']:
            key = N.key(name or '')
            if not key or key in d1 or (tid, key) in seen: continue
            a_ = [r for r in lines_now[key] if r['team'] == tid]
            b_ = [r for r in lines_prev[key] if r['team'] == tid] or (lines_prev[key] if len(lines_prev[key]) == 1 else [])
            if not a_ and not b_: continue
            if CLS.get(cls, ('', 0))[1] >= 5: continue                 # out of eligibility after this season
            seen.add((tid, key))
            ra = a_[0] if a_ else None; rb = b_[0] if b_ else None
            r = pool(ra, rb, PRIOR_W)
            r['div'] = t['div']
            if ra is None:     # last season's line, this season's team
                r['srs'] = t['srs'] if tid in tnow and tnow[tid]['g'] >= 8 else rb['srs']
            f = features(r, nm if ra else nm_prev)
            x = (np.array([f[k] for k in keep]) - mu) / sd
            lo = float(beta[0] + x @ beta[1:]); p = 1 / (1 + math.exp(-lo))
            parts = [['Division II' if k == 'd3' and not f[k] else LABEL[k], round(float(beta[j + 1] * x[j]), 3)] for j, k in enumerate(keep)]
            lns = [line_of(x_, teams.get(x_['team'], {}).get('name') or x_['tname'], s_) for x_, s_ in ((ra, LIVE), (rb, LIVE - 1)) if x_]
            rep = {'plus': [l for l, v in sorted(parts, key=lambda t: -t[1]) if v >= 0.15][:4], 'minus': [l for l, v in sorted(parts, key=lambda t: t[1]) if v <= -0.15][:4]}
            arr = fit['arrivals']
            c = CLS.get(cls, ('', 0))
            hti = ht_of(ht) or 78
            if AV and TR:
                # his first D-I season if he moves up (the translation, over its out-of-time spread), then what such a
                # first season has been worth (the arrival value): E[FV] = 20 + D-1% x that value
                f['ht'] = hti
                bs = float(rpred((np.array(TR['b']), np.array(TR['mu']), np.array(TR['sd'])), np.array([[f[k] for k in TR['keep']]]))[0])
                Xg = arrive_x(AV, bs + np.array(TR['res']), float(hti), float(min(4, c[1] + 1) if c[1] else 3))
                val, pn = float(arrive_val(AV, Xg).mean()), float(arrive_val(AV, Xg, True).mean())
            else:
                bs, val, pn = None, arr['fv'] - 20, arr['nba']
            e_ = 20 + p * val
            fvx = float(np.interp(e_, ex, fx))
            rows.append([name, e['loc'] or t['name'], e.get('logo'), DIVS[t['div']], pos_of(pos, r['pos']), None, 0, 0,
                         FS.fv_of('cbb', fvx), False, round(fvx, 3), round(p * pn, 5), None, c[0] or None, c[1] or 0, None,
                         round(17.6 + c[1], 1) if c[1] else None, ht, int(wt) if wt else None, photo, 0, lns, None, parts, rep,
                         {'espn': f'https://www.espn.com/mens-college-basketball/player/_/id/{aid}'}, DIVS[t['div']], round(p, 4),
                         round(1 / (1 + math.exp(-beta[0])), 4), None if bs is None else round(bs, 2), round(e_, 4), round(val, 3)])
    rows.sort(key=lambda r: (-r[10], -r[27]))
    # pbpm: his projected first D-I season (BPM shrunk by minutes); e: E[FV]; val: E[FV] - 20 if he moves up
    cols = ['name', 'team', 'logo', 'conf', 'pos', 'role', 'ovr', 'posRank', 'fv', 'plus', 'fvx', 'nbaP', 'xbpm', 'cls', 'elig', 'age', 'ageEst',
            'ht', 'wt', 'photo', 'new', 'last', 'rec', 'parts', 'report', 'links', 'div', 'd1P', 'base', 'pbpm', 'e', 'val']
    for k, r in enumerate(rows): r[6] = k + 1
    json.dump({'cols': cols, 'rows': rows, 'asof': time.strftime('%Y-%m-%d'), 'teams': len(espn_of)}, open(OUT, 'w'), separators=(',', ':'))
    print(f'{len(rows)} D-II / D-III players on {len(espn_of)} matched rosters ({len(ros)} ESPN non-D-I rosters); top:')
    for r in rows[:15]: print(f'  {r[0]:24s} {r[1]:22s} {r[3]:5s} {r[13] or "":3s} {r[17] or "":7s} D-1% {r[27]:5.1%}  D-I BPM {r[29]}  FV {r[10]:.2f}  NBA {r[11]:.2%}')
    print('wrote', OUT)


ABBR = {'st': 'state', 'okla': 'oklahoma', 'wash': 'washington', 'colo': 'colorado', 'mich': 'michigan', 'minn': 'minnesota',
        'ark': 'arkansas', 'tex': 'texas', 'ga': 'georgia', 'fla': 'florida', 'ala': 'alabama', 'alas': 'alaska', 'mo': 'missouri',
        'ill': 'illinois', 'ind': 'indiana', 'ky': 'kentucky', 'tenn': 'tennessee', 'va': 'virginia', 'conn': 'connecticut',
        'mass': 'massachusetts', 'pa': 'pennsylvania', 'wis': 'wisconsin', 'mont': 'montana', 'neb': 'nebraska', 'kan': 'kansas',
        'ore': 'oregon', 'cal': 'california', 'calif': 'california', 'miss': 'mississippi', 'la': 'louisiana', 'dist': 'district',
        'intl': 'international', 'sch': 'school', 'atl': 'atlantic', 'md': 'maryland', 'del': 'delaware', 'vt': 'vermont',
        'me': 'maine', 'wyo': 'wyoming', 'ariz': 'arizona', 'nev': 'nevada', 'univ': '', 'u': '', 'university': '', 'college': '',
        'of': '', 'the': '', 'at': '', 'n': 'north', 's': 'south', 'w': 'west', 'e': 'east', 'so': 'southern', 'no': 'northern',
        'mt': 'mount', 'ft': 'fort', 'ste': 'sainte', 'chr': 'christian', 'bapt': 'baptist', 'wesl': 'wesleyan'}


TEAM_ALIAS = {'uah': 'alabama huntsville', 'uindy': 'indianapolis', 'aum': 'auburn montgomery', 'dbu': 'dallas baptist',
              'csusb': 'california state san bernardino', 'cui': 'concordia irvine', 'regis co': 'regis', 'msu moorhead': 'minnesota state moorhead',
              'california state la': 'california state los angeles', 'pitt johnstown': 'pittsburgh johnstown', 'fort hays state': 'fort hays',
              'uccs': 'colorado colorado springs'}
NOT_SAME = {('lewis', 'lewis clark state')}       # Lewis (D-II, Illinois) is not Lewis-Clark State (NAIA)


def tname(s):
    t = re.sub(r"[^a-z0-9 ]", ' ', N.fold(s or '').replace('&', ' ').replace("'", '')).split()
    t = ' '.join(w for w in (ABBR.get(x, x) for x in t) if w)
    return TEAM_ALIAS.get(t, t)


def match_teams(teams, now, prev, ros):
    """ncaa.com team -> ESPN team, by name (ncaa.com's short names spelled out) and by the player names the team's
    box-score lines share with the ESPN roster; one ESPN team per ncaa.com team, best pairs first."""
    import difflib
    inv = defaultdict(set)
    for eid, e in ros.items():
        for p in e['players']:
            if p[1]: inv[N.key(p[1])].add(eid)
    keys = defaultdict(set)
    for L in (now, prev):
        for (d, tid, key) in L: keys[tid].add(key)
    en = {eid: (tname(e['loc']), tname(e['name'])) for eid, e in ros.items()}
    cand = []
    for tid, t in teams.items():
        a = tname(t['name']); ov = Counter(e for k in keys[tid] for e in inv.get(k, ()))
        best = []
        for eid, (l, nm) in en.items():
            if (a, l) in NOT_SAME: continue
            sim = max(difflib.SequenceMatcher(None, a, l).ratio(), 1.0 if l and (a == l or nm.startswith(a + ' ')) else 0.0)
            if sim >= 0.75 or ov.get(eid, 0) >= 3: best.append((sim + 0.08 * min(ov.get(eid, 0), 5), sim, ov.get(eid, 0), eid))
        best.sort(reverse=True)
        if not best: continue
        sc, sim, n, eid = best[0]
        nxt = best[1][0] if len(best) > 1 else 0
        if (sim >= 0.86 and sc - nxt >= 0.04) or (n >= 3 and sc - nxt >= 0.15) or sim == 1.0: cand.append((sc, tid, eid))
    out, used = {}, set()
    for sc, tid, eid in sorted(cand, reverse=True):
        if eid in used or tid in out: continue
        out[tid] = eid; used.add(eid)
    return out


def pos_of(espn, box):
    p = (espn or box or '').upper()[:1]
    return p if p in ('G', 'F', 'C') else 'F'


def line_of(r, team, s):
    g = max(1, r['g'])
    tsa = r['fga'] + 0.44 * r['fta']
    return {'season': f'{s - 1}-{str(s)[2:]}', 'team': team, 'div': DIVS.get(r['div'], r['div']), 'gp': int(r['g']), 'mpg': round(r['mp'] / g, 1),
            'ppg': round(r['pts'] / g, 1), 'rpg': round(r['trb'] / g, 1), 'apg': round(r['ast'] / g, 1),
            'gs40': round(gs(r) / max(1, r['mp']) * 40, 1), 'ts': round(100 * r['pts'] / (2 * tsa), 1) if tsa > 0 else None,
            'tp': round(100 * r['fg3'] / r['fg3a'], 1) if r['fg3a'] else None, 'tpa': int(r['fg3a']),
            'ft': round(100 * r['ft'] / r['fta'], 1) if r['fta'] else None}


if __name__ == '__main__':
    if '--fit' in sys.argv: fit()
    grade()
