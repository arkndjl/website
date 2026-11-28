"""Who wins the starting job: held-out test of the drivers in prereg.md (CFB and CBB).

python3 scripts/research/start_odds_nov28/test.py [cfb|cbb]  -> results_<sport>.json (and data/start_odds_fit.json, the
model the team builders read, from the drivers that passed). PFN pages are cached in scripts/.cache/statplus (see
scripts/cfb_statplus_backtest.mjs; this script fetches OL, CB and S too)."""
import csv, gzip, json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE)); ROOT = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import names
import team_years as CH

N_CFB = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OL': 5, 'DL': 4, 'LB': 2, 'DB': 4}
PFN_ROOM = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'EDGE': 'DL', 'DL': 'DL', 'LB': 'LB', 'CB': 'DB', 'S': 'DB'}
USE = {'QB': 'att', 'RB': 'share', 'WR': 'tar', 'TE': 'tar', 'OL': 'snaps', 'EDGE': 'snaps', 'DL': 'snaps', 'LB': 'snaps', 'CB': 'tar', 'S': 'tar'}
ROS_ROOM = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'OT': 'OL', 'G': 'OL', 'C': 'OL', 'DL': 'DL', 'DE': 'DL',
            'DT': 'DL', 'NT': 'DL', 'EDGE': 'DL', 'LB': 'LB', 'DB': 'DB', 'CB': 'DB', 'S': 'DB'}
ORIG = {'cfb': [2021, 2022, 2023, 2024], 'cbb': [2022, 2023, 2024, 2025]}


def num(x): return x if isinstance(x, (int, float)) else None


# ------------------------------------------------------------------------------------------------------------ CFB
def cfb_rows():
    cache = os.path.join(SCR, '.cache', 'cfb_rosters')
    roster = lambda y: list(csv.DictReader(open(os.path.join(cache, f'r{y}.csv'))))
    P = json.load(gzip.open(os.path.join(SCR, 'data', 'cfb_recruits_cfbd.json.gz')))
    byname = CH.cfb_index(P)
    first = {}
    for y in range(2014, 2027):
        for r in roster(y): first.setdefault(r['athlete_id'], y)
    # PFN: (season, team key, name key) -> (pfn spot, use, score z)
    pfn = {}
    for g in PFN_ROOM:
        L = json.load(open(os.path.join(SCR, '.cache', 'statplus', f'pfn_{g}.json')))
        by = defaultdict(list)
        for r in L:
            if r['season'] < 2026 and num(r.get('score')) is not None: by[r['season']].append(r)
        for s, R in by.items():
            sc = np.array([r['score'] for r in R], float); m, sd = sc.mean(), sc.std() or 1
            for r in R:
                u = num(r.get(USE[g]))
                if u is None and g == 'RB': u = num(r.get('ryds'))
                pfn[(s, names.team_key(r['team']), names.key(r['name']))] = (g, u or 0.0, (r['score'] - m) / sd)
    ros = {}
    for y in range(2019, 2026):
        out = []
        for r in roster(y):
            nm = f"{r['first_name']} {r['last_name']}"; tk = names.team_key(r['team'])
            p = pfn.get((y, tk, names.key(nm)))
            room = PFN_ROOM[p[0]] if p else ROS_ROOM.get(r['position'])
            if not room: continue
            cy, comp = CH.cfb_recruit(byname, nm, r['team'], y)
            f = cy if cy is not None else first.get(r['athlete_id'], y)
            out.append({'id': r['athlete_id'], 'name': nm, 't': tk, 'room': room, 'c': max(1, min(4, y - f + 1)), 'v': CH.cfb_value(comp),
                        'use': p[1] if p else 0.0, 'sc': p[2] if p else None, 'pfnyr': y >= 2024 or room not in ('OL', 'DB')})
        # starters: top N by use among the PFN-listed in the room
        rm = defaultdict(list)
        for o in out: rm[(o['t'], o['room'])].append(o)
        for (t, g), L in rm.items():
            Ls = sorted([o for o in L if o['sc'] is not None], key=lambda o: -o['use'])
            tot = sum(o['use'] for o in Ls[:N_CFB[g]]) or 1.0
            for i, o in enumerate(Ls):
                o['st'] = int(i < N_CFB[g]); o['rk'] = i + 1; o['sh'] = min(1.5, o['use'] / tot * N_CFB[g])
            for o in L: o.setdefault('st', 0); o.setdefault('rk', None); o.setdefault('sh', 0.0)
        ros[y] = out
    rows = []
    for y in range(2020, 2025):
        prev = {o['id']: o for o in ros[y]}
        for o in ros[y + 1]:
            if o['room'] in ('OL', 'DB') and y < 2024: continue
            p = prev.get(o['id'])
            r = {'y': y, 't': o['t'], 'room': o['room'], 'name': o['name'], 'st': o['st'], 'v': o['v'], 'c': o['c'],
                 'tr': int(bool(p) and p['t'] != o['t']), 'fr': int(not p and o['c'] == 1), 'new': int(not p),
                 'inc': int(bool(p) and p['t'] == o['t'] and p['st'] == 1),
                 'wasst': int(bool(p) and p['st'] == 1),
                 'sc': p['sc'] if p and p['sc'] is not None else 0.0, 'lst': int(bool(p) and p['sc'] is not None),
                 'sh': p['sh'] if p else 0.0, 'rk': (p['rk'] if p else None)}
            rows.append(r)
    # FBS rooms only: PFN lists FBS players, so a room with no listed starter (FCS, or a name that did not join) has no truth
    g = defaultdict(int)
    for r in rows: g[(r['y'], r['t'], r['room'])] += r['st']
    return [r for r in rows if g[(r['y'], r['t'], r['room'])]]


# ------------------------------------------------------------------------------------------------------------ CBB
def cbb_rows():
    import cbb_market_fit as M
    by = M.player_rows(write=False)
    F = json.load(open(os.path.join(ROOT, 'data', 'cbb_market_fit.json')))['fresh']
    R = json.load(gzip.open(os.path.join(SCR, 'data', 'cbb_recruit_hist.json.gz')))['recruits']
    rk = {}
    for r in R:
        c = r.get('college') or {}
        if c.get('team') and r.get('rk'): rk[(r['cls'] + 1, names.team_key(c['team']), names.key(r.get('name') or ''))] = r['rk']
    YR = {'Fr': 1, 'So': 2, 'Jr': 3, 'Sr': 4}
    st = {}
    for y, L in by.items():
        t = defaultdict(list)
        for r in L: t[r['team']].append(r)
        for tm, l in t.items():
            l.sort(key=lambda r: -(r.get('min_per') or 0))
            for i, r in enumerate(l): st[(y, r['pid'])] = (int(i < 5), i + 1, (r.get('min_per') or 0) / 100)
    rows = []
    for y in range(2021, 2026):
        prev = {r['pid']: r for r in by.get(y, [])}
        for o in by.get(y + 1, []):
            p = prev.get(o['pid'])
            room = 'C' if o.get('big') else 'G' if o.get('guard') else 'F'
            if p:
                v = p['px'] if p.get('px') is not None else (p.get('bpm') or -4.0)
            else:
                k = rk.get((y + 1, names.team_key(o['team']), names.key(o['name'])))
                v = F['bpm'][0] + F['bpm'][1] * -math.log(k) if k else F['bpm'][0] + F['bpm'][1] * -math.log(250)
            ps = st.get((y, o['pid']))
            rows.append({'y': y, 't': o['team'], 'room': room, 'rg': 'T', 'name': o['name'], 'st': st[(y + 1, o['pid'])][0], 'v': v,
                         'c': YR.get(o.get('yr'), 4), 'age': o.get('age'),
                         'tr': int(bool(p) and p['team'] != o['team']), 'fr': int(not p and o.get('yr') == 'Fr'), 'new': int(not p),
                         'inc': int(bool(p) and p['team'] == o['team'] and ps[0] == 1), 'wasst': int(bool(ps) and ps[0] == 1),
                         'sc': 0.0, 'lst': int(bool(p)), 'sh': ps[2] if ps else 0.0, 'rk': ps[1] if ps else None,
                         'rec': int(not p and (y + 1, names.team_key(o['team']), names.key(o['name'])) in rk)})
    return rows


# ------------------------------------------------------------------------------------------------------- model
def roomz(rows, key):
    g = defaultdict(list)
    for r in rows: g[(r['y'], r['t'], r.get('rg', r['room']))].append(r)
    for L in g.values():
        a = np.array([r[key.lstrip('_')] for r in L], float); m, s = a.mean(), a.std() or 1.0
        for r, x in zip(L, a): r['z' + key] = (x - m) / s


def design(rows, rooms, drivers, by_room=()):
    cols = []
    def add(name, f): cols.append((name, f))
    for g in rooms[1:]: add('room:' + g, lambda r, g=g: float(r['room'] == g))
    add('zv', lambda r: r['zv']); add('zsc', lambda r: r['zsc']); add('lst', lambda r: r['lst'])
    for d in drivers:
        for name, f in DRV[d]:
            if d in by_room:
                for g in rooms: add(f'{name}:{g}', lambda r, f=f, g=g: f(r) * (r['room'] == g))
            else: add(name, f)
    X = np.array([[1.0] + [f(r) for _, f in cols] for r in rows]); return X, ['const'] + [n for n, _ in cols]


DRV = {
    'tr': [('tr', lambda r: r['tr'])],
    'inc': [('inc', lambda r: r['inc'])],
    'class': [('So', lambda r: float(r['c'] == 2)), ('Jr', lambda r: float(r['c'] == 3)), ('Sr', lambda r: float(r['c'] >= 4))],
    'fr': [('fr', lambda r: r['fr'])],
    'frRB': [('frRB', lambda r: r['fr'] * (r['room'] == 'RB'))],
    'age': [('age', lambda r: (r['age'] - 20.5) if r.get('age') else 0.0)],
    'use': [('sh', lambda r: r['sh'])],
    'role': [('rk1', lambda r: float(r['rk'] == 1)), ('rk2', lambda r: float(r['rk'] == 2)), ('rk3', lambda r: float(bool(r['rk']) and r['rk'] >= 3))],
}


def fit(X, y, lam=0.1):
    b = np.zeros(X.shape[1]); R = lam * np.eye(X.shape[1]); R[0, 0] = 0
    for _ in range(50):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30))); W = p * (1 - p)
        g = X.T @ (y - p) - R @ b; H = (X * W[:, None]).T @ X + R
        st = np.linalg.solve(H, g); b += st
        if np.abs(st).max() < 1e-8: break
    return b


def ll(X, y, b):
    p = np.clip(1 / (1 + np.exp(-np.clip(X @ b, -30, 30))), 1e-6, 1 - 1e-6); return -(y * np.log(p) + (1 - y) * np.log(1 - p)), p


def paired_t(d, cl):
    g = defaultdict(float)
    for x, c in zip(d, cl): g[c] += x
    v = np.array(list(g.values())); return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))) if len(v) > 2 and v.std() > 0 else 0.0


def held_out(rows, rooms, A, B, folds):
    """leave one origin out: loss of model A and model B (A = base side) on each held-out row"""
    ya = np.array([r['st'] for r in rows], float)
    XA, _ = design(rows, rooms, *A); XB, _ = design(rows, rooms, *B)
    la = np.zeros(len(rows)); lb = np.zeros(len(rows)); pa = np.zeros(len(rows)); pb = np.zeros(len(rows))
    fy = np.array([f(r) for r in rows for f in [folds]])
    for k in sorted(set(fy)):
        te = fy == k; tr = ~te
        ba = fit(XA[tr], ya[tr]); bb = fit(XB[tr], ya[tr])
        la[te], pa[te] = ll(XA[te], ya[te], ba); lb[te], pb[te] = ll(XB[te], ya[te], bb)
    d = la - lb   # > 0: B better
    cl = [f"{r['y']}|{r['t']}" for r in rows]
    fw = {str(k): round(float(d[fy == k].mean() * 1000), 2) for k in sorted(set(fy))}
    return {'llA': round(float(la.mean()), 4), 'llB': round(float(lb.mean()), 4), 't': round(paired_t(d, cl), 2), 'folds': fw,
            'wins': sum(v > 0 for v in fw.values()), 'n': len(rows), 'hitA': hit(rows, pa), 'hitB': hit(rows, pb)}


def hit(rows, p):
    g = defaultdict(list)
    for r, x in zip(rows, p): g[(r['y'], r['t'], r.get('rg', r['room']))].append((x, r['st']))
    h = n = 0
    for L in g.values():
        k = sum(s for _, s in L)
        if not k: continue
        top = sorted(L, key=lambda z: -z[0])[:k]; h += sum(s for _, s in top); n += k
    return round(h / n, 4) if n else None


def gate(res, nf): return res['t'] >= 2 and res['wins'] >= nf - 1


def main():
    sp = ([a for a in sys.argv[1:] if not a.startswith('--')] or ['cfb'])[0]
    rows = cfb_rows() if sp == 'cfb' else cbb_rows()
    rooms = list(N_CFB) if sp == 'cfb' else ['G', 'F', 'C']
    roomz(rows, 'v'); roomz(rows, 'sc')
    drivers = ['tr', 'inc', 'class', 'fr', 'use', 'role'] + (['age'] if sp == 'cbb' else [])
    main_rows = [r for r in rows if r['y'] in ORIG[sp] and r['room'] not in ('OL', 'DB')]
    nf = len(ORIG[sp]); out = {'sport': sp, 'n': len(main_rows), 'starters': int(sum(r['st'] for r in main_rows)), 'single': {}, 'room': {}}
    fold = lambda r: r['y']
    for d in drivers:
        res = held_out(main_rows, rooms, ([],), ([d],), fold); res['pass'] = gate(res, nf); out['single'][d] = res
        print(sp, 'single', d, res)
    # stepwise: add passing drivers in order of t, each must pass on top of the ones kept
    keep = []
    for d in sorted([d for d in drivers if out['single'][d]['pass']], key=lambda d: -out['single'][d]['t']):
        res = held_out(main_rows, rooms, (keep,), (keep + [d],), fold)
        print(sp, 'step', keep, '+', d, res)
        if gate(res, nf): keep.append(d)
        out.setdefault('step', []).append({'add': d, 'on': list(keep), **res, 'kept': d in keep})
    # by spot: each driver x room against the pooled driver (on top of the kept set)
    for d in drivers:
        base = [x for x in keep if x != d] + [d]
        res = held_out(main_rows, rooms, (base,), (base, [d]), fold); res['pass'] = gate(res, nf)
        rws = main_rows; ya = np.array([r['st'] for r in rws], float)
        X, cn = design(rws, rooms, base, [d]); b = fit(X, ya)
        res['coef'] = {c: round(float(v), 3) for c, v in zip(cn, b) if c.split(':')[0] in [n for n, _ in DRV[d]]}
        out['room'][d] = res; print(sp, 'room', d, res)
    if sp == 'cfb':
        res = held_out(main_rows, rooms, (keep,), (keep + ['frRB'],), fold); res['pass'] = gate(res, nf); out['frRB'] = res
        print(sp, 'frRB', res)
        out['frRate'] = {g: [sum(r['st'] for r in main_rows + [] if r['room'] == g and r['fr']), sum(1 for r in rows if r['room'] == g and r['fr'])] for g in rooms}
    # OL and DB (one origin): two-fold team split
    if sp == 'cfb':
        od = [r for r in rows if r['room'] in ('OL', 'DB')]
        hf = lambda r: hash(r['t']) % 2
        out['oldb'] = {}
        for d in drivers:
            res = held_out(od, rooms, ([],), ([d],), hf); res['pass'] = gate(res, 2); out['oldb'][d] = res
            print(sp, 'oldb', d, res)
    # the shipped model: kept drivers (spot-specific where the spot test passed), fit on every origin
    byr = [d for d in keep if out['room'][d]['pass']]
    allr = [r for r in rows if r['y'] in ORIG[sp]]
    X, cn = design(allr, rooms, keep, byr); b = fit(X, np.array([r['st'] for r in allr], float))
    out['model'] = {'drivers': keep, 'byRoom': byr, 'coef': dict(zip(cn, [round(float(v), 4) for v in b]))}
    # seasons 2-3 on the live page: last season's terms by whether he started last season (scripts/start_odds.py expect)
    pv = [r for r in allr if not r['new']]
    out['means'] = {k: [round(float(np.mean([r[k] for r in pv if r['wasst'] == w])), 4) for w in (0, 1)] for k in ('sc', 'lst', 'sh')}
    json.dump(out, open(os.path.join(HERE, f'results_{sp}.json'), 'w'), indent=1)
    fp = os.path.join(ROOT, 'data', 'start_odds_fit.json')
    F = json.load(open(fp)) if os.path.exists(fp) else {}
    F['_'] = 'scripts/research/start_odds_nov28/test.py (prereg.md): P(start) for the college depth charts, read by scripts/start_odds.py'
    F[sp] = {'model': out['model'], 'rooms': rooms, 'N': N_CFB if sp == 'cfb' else {g: 5 for g in rooms}, 'means': out['means'],
             'single': {d: {k: v[k] for k in ('t', 'wins', 'pass', 'llA', 'llB', 'hitA', 'hitB')} for d, v in out['single'].items()},
             'step': [{k: v[k] for k in ('add', 't', 'wins', 'kept', 'hitA', 'hitB')} for v in out.get('step', [])],
             'room': {d: {k: v[k] for k in ('t', 'wins', 'pass', 'coef')} for d, v in out['room'].items()},
             'frRB': {k: out['frRB'][k] for k in ('t', 'wins', 'pass')} if 'frRB' in out else None, 'n': out['n'], 'origins': ORIG[sp]}
    json.dump(F, open(fp, 'w'), indent=1, allow_nan=False)
    print(json.dumps(out['model']))


if __name__ == '__main__':
    main()
