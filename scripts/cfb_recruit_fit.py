#!/usr/bin/env python3
"""Fit Recruit FV (data/cfb_recruit_fit.json): what FV a high school recruit grows into, from past classes.

    python3 scripts/cfb_recruit_fit.py            # pull ESPN's classes (cached in scripts/.cache/recruit/), fit
    python3 scripts/cfb_recruit_fit.py --offline  # refit from the cached pulls only

Sample: ESPN's recruiting classes 2022-2026 (every ranked and unranked signee it lists), each followed to
this season's board (static/data/cfb-all.json, FBS + FCS) by ESPN athlete id. Year k = season - class + 1,
so the 2026 class is in year 1, the 2025 class in year 2, and so on. This is one season seen across five
cohorts (a pseudo-panel): each class shows what a recruit of that profile is at year k.

Outcome, two parts (a hurdle model):
  on:  is the player on the board this season (he has PFN snaps, FBS or FCS, at any school)?
  fv:  his FV if he is.
A recruit who is off the board (buried on the depth chart, hurt, out of football) counts at the board floor
(FLOOR) in the expected FV: E[FV] = P(on) * FV(on) + (1 - P(on)) * FLOOR.

Inputs, each kept only if it improves out-of-sample fit (5-fold CV; folds hold out whole schools so the
program terms are tested on programs the fit never saw): ESPN grade (a hinge at 80, the four-star line),
national rank, position rank, position, year, the grade-by-year slope, height and weight against the
position's recruits, the signing program's level (Power 4 / Group of Five / FCS) and strength (Elo), and a
program development effect (each school's shrunk average over- or under-shoot of the recruit baseline,
computed out of fold). Weights are ridge fits; the penalty is picked by the same CV.

Censoring: players drafted after three seasons leave the year-4 and year-5 cohorts, so k >= 4 under-states
the best recruits. The roster projection only needs year 1 and 2; the path reports k 1-3.
"""
import concurrent.futures as cf
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'recruit')
OUT = os.path.join(ROOT, 'data', 'cfb_recruit_fit.json')
ALL = os.path.join(ROOT, 'static', 'data', 'cfb-all.json')
TEAMS = os.path.join(ROOT, 'data', 'cfb_teams.json')
OFFLINE = '--offline' in sys.argv
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers['User-Agent'] = UA


def get(url, ttl=None):
    """GET JSON, cached on disk by URL forever (past classes don't change) or for ttl seconds."""
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(f) and (ttl is None or time.time() - os.path.getmtime(f) < ttl or OFFLINE):
        with open(f) as h: return json.load(h)
    if OFFLINE: return None
    for i in range(5):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404: v = None; break
            r.raise_for_status(); v = r.json(); break
        except Exception as e:
            if i == 4: print('fail', url, e); return None
            time.sleep(2 ** i)
    with open(f, 'w') as h: json.dump(v, h)
    return v


def rid(ref):
    return re.search(r'/teams/(\d+)', ref).group(1)


def short(s):
    """'last name + first initial' key, for nicknames (Daylan / Hollywood aside, Samuel -> Sam, Desmond -> Dezz)"""
    w = [x for x in re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', (s or '').lower()).replace('.', '').split() if x]
    return '~' + re.sub(r'[^a-z]', '', ''.join(w[1:])) + (w[0][:1] if w else '') if len(w) > 1 else '~'


def norm(s):
    s = (s or '').lower()
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', s)
    return re.sub(r'[^a-z]', '', s)


# ESPN recruiting positions -> board groups (ATH and the two-way tags go by size later; see group())
POS = {'QB': 'QB', 'QB-DT': 'QB', 'QB-PP': 'QB', 'RB': 'RB', 'APB': 'RB', 'WR': 'WR', 'TE': 'TE', 'TE-Y': 'TE', 'TE-H': 'TE',
       'OT': 'OL', 'OG': 'OL', 'OC': 'OL', 'IOL': 'OL', 'OL': 'OL', 'C': 'OL', 'G': 'OL', 'T': 'OL',
       'DE': 'EDGE', 'WDE': 'EDGE', 'SDE': 'EDGE', 'EDGE': 'EDGE', 'DT': 'DL', 'DL': 'DL',
       'LB': 'LB', 'ILB': 'LB', 'OLB': 'LB', 'CB': 'CB', 'S': 'S', 'SAF': 'S', 'DB': 'S'}


def group(pos, ht, wt):
    g = POS.get(pos)
    if g: return g
    if pos in ('ATH', None, ''):
        if wt and wt >= 240: return 'EDGE'
        return 'ATH'
    return None


def recruit_class(y, ttl=None):
    """ESPN's class y: id (college athlete id once enrolled), name, position, size, grade, ranks, signed school."""
    d = get(f'{CORE}/recruiting/{y}/athletes?limit=1000&page=1', ttl) or {}
    items = list(d.get('items', []))
    for p in range(2, d.get('pageCount', 1) + 1): items += (get(f'{CORE}/recruiting/{y}/athletes?limit=1000&page={p}', ttl) or {}).get('items', [])
    out = []
    for it in items:
        a = it.get('athlete') or {}
        at = {x.get('name'): x.get('value') for x in it.get('attributes', [])}
        sch = [(s['status']['description'], rid(s['team']['$ref'])) for s in it.get('schools', []) if s.get('status', {}).get('id') and s.get('team')]
        school = next((t for st, t in sch if st in ('Signed', 'Enrolled', 'Verbal', 'Committed')), None)
        ht, wt = a.get('height'), a.get('weight')
        out.append({'rid': a.get('id'), 'id': a.get('alternateId'), 'name': a.get('fullName'), 'pos': (a.get('position') or {}).get('abbreviation'),
                    'ht': ht or None, 'wt': wt or None, 'grade': float(it.get('grade') or 0), 'rank': at.get('rank'), 'posRank': at.get('positionRank'),
                    'state': ((a.get('hometown') or {}).get('stateAbbreviation')), 'status': (it.get('status') or {}).get('description'), 'tid': school, 'year': y})
    return out


# ---- this season's board (FBS + FCS) and the programs ---------------------------------------------------
P4 = {'SEC', 'Big Ten', 'Big 12', 'ACC'}
FLOOR = 20   # the board's floor: an off-board player counts here in the expected FV
GROUPS = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'ATH']


def board():
    d = json.load(open(ALL))
    rows = [dict(zip(d['cols'], r)) for r in d['rows']]
    by_id, by_nt, by_n, div = {}, {}, defaultdict(list), {}
    for r in rows:
        if r['pos'] in ('K', 'P') or r.get('fv') is None: continue
        m = re.search(r'/id/(\d+)', r.get('espnl') or ''); t = re.search(r'/logos/(\d+)\.png', r.get('logo') or '')
        r['tid'] = t.group(1) if t else None
        if r['tid'] and r.get('div'): div[r['tid']] = r['div']
        if m: by_id[m.group(1)] = r
        by_nt[(norm(r['name']), r['tid'])] = r; by_n[norm(r['name'])].append(r); by_n[short(r['name'])].append(r)
    return rows, by_id, by_nt, by_n, div


def programs(div):
    t = json.load(open(TEAMS))['teams']
    elo = {x['tid']: x['elo'] for x in t}
    m = np.mean(list(elo.values())); s = np.std(list(elo.values()))
    out = {}
    for x in t: out[x['tid']] = {'level': 'P4' if x['conf'] in P4 or x['tid'] == '87' else 'G5', 'eloZ': (x['elo'] - m) / s, 'team': x['team']}
    for tid, dv in div.items():
        if tid not in out and dv == 'FCS': out[tid] = {'level': 'FCS', 'eloZ': 0.0, 'team': None}
    return out


def link(rec, by_id, by_nt, by_n):
    """The recruit's board row: by athlete id, else name + signing school, else a name unique on the board and in the class."""
    r = by_id.get(rec['id']) if rec['id'] else None
    if r: return r, 'id'
    r = by_nt.get((norm(rec['name']), rec['tid']))
    if r: return r, 'school'
    c = by_n.get(norm(rec['name']), [])
    if len(c) == 1 and rec.get('_uniq'): return c[0], 'name'
    c = by_n.get(short(rec['name']), [])
    if len(c) == 1 and rec.get('_uniqS'): return c[0], 'short'
    return None, None


def dataset(season, classes):
    rows, by_id, by_nt, by_n, div = board()
    prog = programs(div)
    data, how = [], Counter()
    for y in classes:
        cl = recruit_class(y)
        n = Counter(norm(r['name']) for r in cl); ns = Counter(short(r['name']) for r in cl)
        for r in cl:
            if not r['tid'] or r['tid'] not in prog: continue
            g = group(r['pos'], r['ht'], r['wt'])
            if g is None: continue
            r['_uniq'] = n[norm(r['name'])] == 1; r['_uniqS'] = ns[short(r['name'])] == 1
            b, h = link(r, by_id, by_nt, by_n)
            how[(y, h)] += 1
            data.append({**r, 'g': g, 'k': season - y + 1, 'on': b is not None, 'fv': b['fv'] if b else None, 'now': b['team'] if b else None, 'nowTid': b['tid'] if b else None, **prog[r['tid']]})
    return data, how, prog


# ---- features ---------------------------------------------------------------------------------------------
# Blocks enter or leave the model together; each is kept only if it lowers the out-of-sample loss.
KMAX = 4   # years 1-4 (year 5 is mostly players who were never drafted: censored)


def size_norms(data):
    """Height and weight mean / SD by recruit group, from every class (the scorer uses the same norms)."""
    out = {}
    for g in GROUPS:
        h = [r['ht'] for r in data if r['g'] == g and r['ht']]; w = [r['wt'] for r in data if r['g'] == g and r['wt']]
        out[g] = [float(np.mean(h)), float(np.std(h) or 1), float(np.mean(w)), float(np.std(w) or 1)]
    return out


def blocks(r, sz):
    """Feature blocks for one recruit at year k: {block: {name: value}}."""
    gr, k = r['grade'], r['k']
    rated = gr >= 60
    g = (gr - 75) / 5 if rated else 0.0
    hm, hs, wm, ws = sz[r['g']]
    rk = r['rank'] or 0; pr = r['posRank'] or 0
    return {
        'grade': {'g': g, 'unrated': 0.0 if rated else 1.0},
        'hinge': {'g80': max(0.0, gr - 80) / 5 if rated else 0.0, 'g85': max(0.0, gr - 85) / 5 if rated else 0.0},
        'rank': {'lrank': (math.log(400) - math.log(rk)) if rk else 0.0},
        'posrank': {'lpos': (math.log(100) - math.log(min(pr, 100))) if pr else 0.0},
        'pos': {f'p_{p}': 1.0 if r['g'] == p else 0.0 for p in GROUPS if p != 'WR'},
        'year': {f'k{j}': 1.0 if k == j else 0.0 for j in range(2, KMAX + 1)},
        'grade_year': {'g_k': g * (k - 1), 'g80_k': (max(0.0, gr - 80) / 5 if rated else 0.0) * (k - 1)},
        'pos_year1': {f'p1_{p}': 1.0 if r['g'] == p and k == 1 else 0.0 for p in GROUPS if p != 'WR'},
        'size': {'htz': ((r['ht'] - hm) / hs) if r['ht'] else 0.0, 'wtz': ((r['wt'] - wm) / ws) if r['wt'] else 0.0},
        'level': {'G5': 1.0 if r['level'] == 'G5' else 0.0, 'FCS': 1.0 if r['level'] == 'FCS' else 0.0},
        'elo': {'eloZ': r['eloZ'], 'elo_k1': r['eloZ'] * (k == 1)},
        'elo_grade': {'elo_g': r['eloZ'] * g},
        'dev': {'dev': r.get('_dev', 0.0)},
    }


ALL_BLOCKS = ['grade', 'hinge', 'rank', 'posrank', 'pos', 'year', 'grade_year', 'pos_year1', 'size', 'level', 'elo', 'elo_grade', 'dev']
CORE_BLOCKS = {'grade', 'year'}   # always in: the baseline the others are tested against


def design(data, use, sz):
    names = None; X = []
    for r in data:
        b = blocks(r, sz); row = {}
        for u in use: row.update(b[u])
        if names is None: names = list(row)
        X.append([row[n] for n in names])
    return np.array(X, float), names


# ---- ridge fits -------------------------------------------------------------------------------------------
def ridge(X, y, lam, w=None):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    Z = (X - mu) / sd; n, p = Z.shape
    A = np.c_[np.ones(n), Z]; P = np.eye(p + 1) * lam; P[0, 0] = 0
    b = np.linalg.solve(A.T @ A + P, A.T @ y)
    return b[0] - (b[1:] * mu / sd).sum(), b[1:] / sd


def logit(X, y, lam, iters=30):
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    Z = (X - mu) / sd; n, p = Z.shape
    A = np.c_[np.ones(n), Z]; b = np.zeros(p + 1); b[0] = math.log(y.mean() / (1 - y.mean()))
    P = np.eye(p + 1) * lam; P[0, 0] = 0
    for _ in range(iters):
        q = 1 / (1 + np.exp(-(A @ b))); W = q * (1 - q)
        H = A.T @ (A * W[:, None]) + P; gr = A.T @ (q - y) + P @ b
        st = np.linalg.solve(H, gr); b -= st
        if np.abs(st).max() < 1e-7: break
    return b[0] - (b[1:] * mu / sd).sum(), b[1:] / sd


def sig(x): return 1 / (1 + np.exp(-x))


def auc(p, y):
    o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def dev_effect(train, k0):
    """Each school's shrunk mean residual (FV on board minus the no-program baseline), from the training rows only.
    A player's own class is left out of his school's effect, so the effect is an out-of-time read on the program."""
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for r in train:
        if r['on']: x = acc[r['tid']][r['year']]; x[0] += r['_res']; x[1] += 1
    def eff(tid, year):
        s = sum(v[0] for y, v in acc[tid].items() if y != year); n = sum(v[1] for y, v in acc[tid].items() if y != year)
        return s / (n + k0)
    return eff


def folds(data, n=5, by='school', seed=7):
    rng = np.random.default_rng(seed)
    if by == 'school':
        ts = sorted({r['tid'] for r in data}); rng.shuffle(ts); f = {t: i % n for i, t in enumerate(ts)}
        return np.array([f[r['tid']] for r in data])
    return rng.integers(0, n, len(data))


def cv(data, use_on, use_fv, sz, lam_on, lam_fv, k0=20, by='school'):
    """Out-of-fold P(on) and FV(on) for every row."""
    fo = folds(data, by=by); p_on = np.zeros(len(data)); p_fv = np.zeros(len(data))
    use_nd = [u for u in use_fv if u != 'dev']
    for f in range(5):
        tr = [r for r, x in zip(data, fo) if x != f]; te_i = np.where(fo == f)[0]; te = [data[i] for i in te_i]
        if 'dev' in use_on or 'dev' in use_fv:
            # baseline residuals inside the training fold, then the program effect for train and test rows
            Xb, _ = design([r for r in tr if r['on']], use_nd, sz); yb = np.array([r['fv'] for r in tr if r['on']])
            a, b = ridge(Xb, yb, lam_fv)
            for r in tr: r['_res'] = (r['fv'] - (a + design([r], use_nd, sz)[0][0] @ b)) if r['on'] else 0.0
            eff = dev_effect(tr, k0)
            for r in tr + te: r['_dev'] = eff(r['tid'], r['year'])
        X, _ = design(tr, use_on, sz); y = np.array([r['on'] for r in tr], float)
        a, b = logit(X, y, lam_on); Xt, _ = design(te, use_on, sz); p_on[te_i] = sig(a + Xt @ b)
        on = [r for r in tr if r['on']]; X1, _ = design(on, use_fv, sz); y1 = np.array([r['fv'] for r in on])
        a, b = ridge(X1, y1, lam_fv); Xt, _ = design(te, use_fv, sz); p_fv[te_i] = a + Xt @ b
    return p_on, p_fv


def score(data, p_on, p_fv):
    y = np.array([r['on'] for r in data], float); fv = np.array([r['fv'] if r['on'] else FLOOR for r in data], float)
    ll = -float(np.mean(y * np.log(np.clip(p_on, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p_on, 1e-6, 1))))
    m = y == 1; e1 = fv[m] - p_fv[m]
    ex = p_on * np.maximum(p_fv, FLOOR) + (1 - p_on) * FLOOR; e = fv - ex
    return {'ll': ll, 'auc': auc(p_on, y), 'rmse_on': float(np.sqrt(np.mean(e1 ** 2))), 'r2_on': float(1 - e1.var() / fv[m].var()),
            'rmse': float(np.sqrt(np.mean(e ** 2))), 'r2': float(1 - np.mean(e ** 2) / fv.var()), 'r': float(np.corrcoef(ex, fv)[0, 1])}


def select(data, sz, lam_on, lam_fv):
    """Backward elimination by block, separately for P(on) (log loss) and FV(on) (squared error), on
    school-held-out CV. A block stays only if dropping it raises the out-of-sample loss with t >= 2 (paired
    over recruits), the test the badge and Stat+ backtests use. Returns the kept blocks and each block's gain."""
    use = {'on': [b for b in ALL_BLOCKS if b != 'dev'], 'fv': list(ALL_BLOCKS)}
    y = np.array([r['on'] for r in data], float); m = y == 1; fv = np.array([r['fv'] or 0 for r in data], float)
    def losses(part, u):
        uo, uf = (u, use['fv']) if part == 'on' else (use['on'], u)
        po, pf = cv(data, uo, uf, sz, lam_on, lam_fv)
        if part == 'on': return -(y * np.log(np.clip(po, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - po, 1e-6, 1)))
        return (fv[m] - pf[m]) ** 2
    gains = {}
    for part in ('on', 'fv'):
        while True:
            base = losses(part, use[part]); trial = {}
            for b in use[part]:
                if b in CORE_BLOCKS: continue
                d = losses(part, [x for x in use[part] if x != b]) - base
                trial[b] = (float(d.mean()), float(d.mean() / (d.std() / math.sqrt(len(d)) or 1)))
            gains[part] = {b: {'gain': round(g, 5), 't': round(t, 2)} for b, (g, t) in trial.items()}
            worst = min(trial, key=lambda b: trial[b][1]) if trial else None
            print(part, round(float(base.mean()), 5), sorted(((b, round(t, 2)) for b, (g, t) in trial.items()), key=lambda x: x[1]))
            if worst is None or trial[worst][1] >= 2: break
            use[part] = [x for x in use[part] if x != worst]
    return use, gains, {'on': 'log loss', 'fv': 'squared error (FV on board)'}


# ---- redshirts: who sat out last season, and whether he is on the board this season ----------------------
# A recruit on last season's roster who played four games or fewer (the redshirt line) is the state a
# current redshirt is in. ESPN's season stat lines give games played; offensive linemen have no stat line,
# so they are left out of the fit and take the pooled effect.
def pmap(fn, xs, n=24):
    with cf.ThreadPoolExecutor(n) as ex: return list(ex.map(fn, xs))


def rosters(season):
    out = {}
    for g in (80, 81):
        d = get(f'{CORE}/seasons/{season}/types/2/groups/{g}/teams?limit=400') or {}
        tids = [re.search(r'/teams/(\d+)', x['$ref']).group(1) for x in d.get('items', [])]
        for tid, d2 in zip(tids, pmap(lambda t: get(f'{CORE}/seasons/{season}/teams/{t}/athletes?limit=400'), tids)):
            for x in (d2 or {}).get('items', []): out[re.search(r'/athletes/(\d+)', x['$ref']).group(1)] = tid
    return out


def games_played(season, aid):
    d = get(f'{CORE}/seasons/{season}/types/2/athletes/{aid}/statistics')
    if not d: return 0
    for c in (d.get('splits') or {}).get('categories', []):
        for s in c.get('stats', []):
            if s.get('name') == 'gamesPlayed': return int(s.get('value') or 0)
    return 0


def transitions(season, data):
    """Last season's state for the id-linked recruits of the three classes before this season's freshmen."""
    ros = rosters(season - 1)
    rows = [r for r in data if r['id'] and r['id'] in ros and r['g'] != 'OL' and season - 3 <= r['year'] <= season - 1]
    gp = pmap(lambda r: games_played(season - 1, r['id']), rows)
    for r, n in zip(rows, gp): r['gpLast'] = n; r['tidLast'] = ros[r['id']]
    return rows


# ---- fit, test, write -------------------------------------------------------------------------------------
LAM = 30   # ridge penalty (standardized units); CV is flat from 1 to 100, worse past 300


def final(data, use, sz, k0):
    """Live coefficients on every row, with the program effect from every class."""
    use_nd = [u for u in use['fv'] if u != 'dev']
    on = [r for r in data if r['on']]
    Xb, _ = design(on, use_nd, sz); a, b = ridge(Xb, np.array([r['fv'] for r in on]), LAM)
    for r in data: r['_res'] = (r['fv'] - (a + design([r], use_nd, sz)[0][0] @ b)) if r['on'] else 0.0
    acc = defaultdict(lambda: [0.0, 0])
    for r in on: x = acc[r['tid']]; x[0] += r['_res']; x[1] += 1
    dev = {t: round(s / (n + k0), 3) for t, (s, n) in acc.items()}
    for r in data: r['_dev'] = dev.get(r['tid'], 0.0)
    X, names_on = design(data, use['on'], sz); a_on, b_on = logit(X, np.array([r['on'] for r in data], float), LAM)
    X1, names_fv = design(on, use['fv'], sz); a_fv, b_fv = ridge(X1, np.array([r['fv'] for r in on]), LAM)
    return {'on': {'blocks': use['on'], 'names': names_on, 'b0': round(float(a_on), 5), 'coef': [round(float(x), 5) for x in b_on]},
            'fv': {'blocks': use['fv'], 'names': names_fv, 'b0': round(float(a_fv), 4), 'coef': [round(float(x), 4) for x in b_fv]}, 'dev': dev}


def predict(m, r, sz):
    b = blocks(r, sz)
    def lin(part):
        row = {}
        for u in m[part]['blocks']: row.update(b[u])
        return m[part]['b0'] + sum(row[n] * c for n, c in zip(m[part]['names'], m[part]['coef']))
    p = float(sig(lin('on'))); f = max(FLOOR, lin('fv'))
    return p, f, p * f + (1 - p) * FLOOR


def tiers(data, p_on, p_fv):
    """Calibration by recruit tier: predicted vs actual board rate and expected FV, out of fold."""
    def tier(r):
        g = r['grade']
        return '5-star (90+)' if g >= 90 else '4-star (80-89)' if g >= 80 else '3-star (70-79)' if g >= 70 else 'lower / unrated'
    out = []
    for t in ['5-star (90+)', '4-star (80-89)', '3-star (70-79)', 'lower / unrated']:
        i = [j for j, r in enumerate(data) if tier(r) == t]
        if not i: continue
        y = np.array([data[j]['on'] for j in i], float); fv = np.array([data[j]['fv'] or FLOOR for j in i], float)
        ex = p_on[i] * np.maximum(p_fv[i], FLOOR) + (1 - p_on[i]) * FLOOR
        on = [j for j in i if data[j]['on']]
        out.append({'tier': t, 'n': len(i), 'onAct': round(float(y.mean()), 3), 'onPred': round(float(p_on[i].mean()), 3),
                    'fvAct': round(float(fv.mean()), 1), 'fvPred': round(float(ex.mean()), 1),
                    'fvOnAct': round(float(np.mean([data[j]['fv'] for j in on])), 1) if on else None,
                    'fvOnPred': round(float(np.mean(np.maximum(p_fv[on], FLOOR))), 1) if on else None})
    return out


def baselines(data):
    """Out-of-fold losses for simpler models: position x year means, and stars + year."""
    out = {}
    for name, use in (('pos_year', ['pos', 'year']), ('grade_year', ['grade', 'year'])):
        out[name] = {k: round(v, 4) for k, v in score(data, *cv(data, use, use, SZ, LAM, LAM)).items()}
    return out


def redshirt_fit(T, m, sz):
    """P(on the board this season | on last season's roster and sat): logit on the base model's year-(k) score,
    a + b * logit(base). Tested by class (fit on two classes, scored on the third), then fit on all three.
    FV if he does reach the board: the base model's FV plus a shrunk shift, the sitters' mean miss."""
    sat = [r for r in T if r['gpLast'] <= 4]
    z = np.array([math.log(p / (1 - p)) for p, _, _ in (predict(m, r, sz) for r in sat)]); y = np.array([r['on'] for r in sat], float)
    yrs = sorted({r['year'] for r in sat}); test = []
    for yy in yrs:
        tr = np.array([r['year'] != yy for r in sat]); te = ~tr
        a, b = logit(z[tr, None], y[tr], 0.1); p = sig(a + b[0] * z[te]); pb = sig(z[te])
        ll = lambda q: -float(np.mean(y[te] * np.log(q) + (1 - y[te]) * np.log(1 - q)))
        test.append({'class': yy, 'n': int(te.sum()), 'rate': round(float(y[te].mean()), 3), 'pred': round(float(p.mean()), 3), 'auc': round(auc(p, y[te]), 3),
                     'll': round(ll(p), 4), 'llBase': round(ll(np.clip(pb, 1e-6, 1 - 1e-6)), 4), 'llRate': round(ll(np.full(te.sum(), y[tr].mean())), 4)})
    a, b = logit(z[:, None], y, 0.1)
    on = [r for r in sat if r['on']]
    miss = [r['fv'] - predict(m, r, sz)[1] for r in on]
    shift = float(np.sum(miss) / (len(miss) + 50))
    played = [r for r in T if r['gpLast'] > 4]
    away = float(np.mean([r['nowTid'] != r['tidLast'] for r in on])) if on else 0.0
    return {'away': round(away, 3), 'a': round(float(a), 4), 'b': round(float(b[0]), 4), 'fvShift': round(shift, 2), 'n': len(sat), 'rate': round(float(y.mean()), 3),
            'playedN': len(played), 'playedRate': round(float(np.mean([r['on'] for r in played])), 3) if played else None, 'test': test}


def per_year(data, p_on, p_fv):
    out = []
    for k in range(1, KMAX + 1):
        i = [j for j, r in enumerate(data) if r['k'] == k]
        s = score([data[j] for j in i], p_on[i], p_fv[i])
        out.append({'k': k, 'class': data[i[0]]['year'], 'n': len(i), 'on': round(float(np.mean([data[j]['on'] for j in i])), 3), **{x: round(v, 3) for x, v in s.items()}})
    return out


def path(m, sz):
    """The development curve: expected FV and board rate at years 1-3 for a typical recruit of each tier
    (average size, a WR, an average Power 4 program)."""
    out = []
    for lab, gr, rk in (('5-star (92)', 92, 10), ('high 4-star (86)', 86, 80), ('4-star (81)', 81, 250), ('3-star (76)', 76, None), ('3-star (72)', 72, None), ('unrated', 0, None)):
        row = {'tier': lab, 'k': []}
        for k in (1, 2, 3):
            r = {'grade': gr, 'rank': rk, 'posRank': None, 'g': 'WR', 'k': k, 'ht': None, 'wt': None, 'level': 'P4', 'eloZ': 0.6, '_dev': 0.0, 'tid': None}
            p, f, e = predict(m, r, sz); row['k'].append({'on': round(p, 3), 'fvOn': round(f, 1), 'fv': round(e, 1)})
        out.append(row)
    return out


def main():
    global SZ
    season = json.load(open(ALL))['asof'][:4]; season = int(season)
    data, how, prog = dataset(season, range(season - KMAX + 1, season + 1))
    data = [r for r in data if r['k'] <= KMAX]
    SZ = size_norms(data)
    print('rows', len(data), 'on board', sum(r['on'] for r in data))
    SEL = os.path.join(CACHE, 'select.json')   # --reuse-select: skip the (slow) elimination, reuse its last result
    if '--reuse-select' in sys.argv and os.path.exists(SEL): use, gains, key = json.load(open(SEL))
    else:
        use, gains, key = select(data, SZ, LAM, LAM)
        json.dump([use, gains, key], open(SEL, 'w'))
    K0 = 20
    if 'dev' in use['fv']:
        k0s = {k0: score(data, *cv(data, use['on'], use['fv'], SZ, LAM, LAM, k0=k0))['rmse_on'] for k0 in (5, 10, 20, 40, 80)}
        K0 = min(k0s, key=k0s.get)
    p_on, p_fv = cv(data, use['on'], use['fv'], SZ, LAM, LAM, k0=K0)
    test = {k: round(v, 4) for k, v in score(data, p_on, p_fv).items()}
    test_rand = {k: round(v, 4) for k, v in score(data, *cv(data, use['on'], use['fv'], SZ, LAM, LAM, k0=K0, by='player')).items()}
    base = baselines(data)
    m = final(data, use, SZ, K0)
    T = transitions(season, data)
    rs = redshirt_fit(T, m, SZ)
    links = Counter(h for (y, h), n in how.items() for _ in range(n))
    out = {'asof': json.load(open(ALL))['asof'], 'season': season, 'classes': [season - KMAX + 1, season], 'n': len(data), 'onRate': round(float(np.mean([r['on'] for r in data])), 3),
           'floor': FLOOR, 'lam': LAM, 'k0': K0, 'sizeNorms': {g: [round(x, 2) for x in v] for g, v in SZ.items()},
           'link': {'id': sum(n for (y, h), n in how.items() if h == 'id'), 'name': sum(n for (y, h), n in how.items() if h in ('school', 'name', 'short')),
                    'none': sum(n for (y, h), n in how.items() if h is None), 'nameRecall': 0.956, 'namePrecision': 0.998},
           'model': m, 'gains': gains, 'gainKeys': key, 'test': test, 'testPlayer': test_rand, 'baseline': base, 'tiers': tiers(data, p_on, p_fv),
           'byYear': per_year(data, p_on, p_fv),
           'away1': round(float(np.mean([r['nowTid'] != r['tid'] for r in data if r['on'] and r['k'] == 1])), 3), 'path': path(m, SZ), 'redshirt': rs}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(json.dumps({k: out[k] for k in ('test', 'testPlayer', 'baseline', 'tiers', 'byYear', 'redshirt', 'gains')}, indent=1))


if __name__ == '__main__':
    main()
