#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""prereg.md: does the roster chain predict a team's strength 1-3 seasons out beyond its strength now?
    python3 scripts/research/team_years_nov28/test.py [cbb|cfb]   -> results_<sport>.json here"""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE)); ROOT = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, HERE)
import team_years as CH  # noqa: E402

ORIG = {'cbb': {1: [2022, 2023, 2024, 2025], 2: [2022, 2023, 2024], 3: [2022, 2023]},
        'cfb': {1: [2021, 2022, 2023, 2024], 2: [2021, 2022, 2023], 3: [2021, 2022]}}
REP = -3.0
USE_CURVE = '--curve' in sys.argv   # CBB: the player development curve (dev.py) in place of the class means


def z(d):
    v = np.array(list(d.values()), float); m, s = v.mean(), v.std() or 1.0
    return {k: (x - m) / s for k, x in d.items()}


# ------------------------------------------------------------------------------------------------------------ CBB
def cbb_data():
    import cbb_market_fit as M
    by = M.player_rows(write=False)
    TS, _ = M.team_seasons()
    class SD(dict): pass
    S = SD()
    for (s, t), v in TS.items(): S.setdefault(s, {})[t] = v['srs']
    F = json.load(open(os.path.join(ROOT, 'data', 'cbb_market_fit.json')))['fresh']
    R = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')))['recruits']
    rec = defaultdict(list)   # season he arrives -> [(team, rk)]
    for r in R:
        c = r.get('college') or {}
        if c.get('team') and r.get('rk') and c.get('y1') == r['cls'] + 1: rec[r['cls'] + 1].append((c['team'], r['rk']))
    val = lambda r: (r['px'] if r.get('px') is not None else (r.get('bpm') or REP)) - REP
    def pairs(y):
        nxt = {r['pid']: r for r in by.get(y + 1, [])}
        out = []
        for r in by.get(y, []):
            c = CH.CLS.get(r.get('yr'));
            if not c: continue
            n = nxt.get(r['pid']); st = int(bool(n and n['team'] == r['team']))
            out.append((c, st, (val(n) - val(r)) if st else None))
        return out
    def rows(y):
        out = [{'t': r['team'], 'c': CH.CLS[r['yr']], 'v': val(r), 'm': (r.get('min_per') or 0) / 100, 'age': r.get('age')} for r in by.get(y, []) if CH.CLS.get(r.get('yr'))]
        for t, rk in rec.get(y + 1, []):
            l = -math.log(rk)
            out.append({'t': t, 'c': 1, 'new': 1, 'v': F['bpm'][0] + F['bpm'][1] * l - REP, 'm': (F['min'][0] + F['min'][1] * l) / 100})
        return out
    def curve(y):
        """the development curve fit on the k = 1 pairs known by season y (dev.py)"""
        import dev as DV
        tr = []
        for yy in range(y - 3, y):
            nx = {x['pid']: x for x in by.get(yy + 1, [])}
            tr += [(r, nx[r['pid']]) for r in by.get(yy, []) if CH.CLS.get(r.get('yr')) and r['pid'] in nx]
        return CH.curve_of(DV.fit_curve(tr))
    S.curve = curve
    return S, pairs, rows


# ------------------------------------------------------------------------------------------------------------ CFB
def cfb_data():
    import csv, names
    cache = os.path.join(SCR, '.cache', 'cfb_rosters'); os.makedirs(cache, exist_ok=True)
    def roster(y):
        p = os.path.join(cache, f'r{y}.csv')
        if not os.path.exists(p) or os.path.getsize(p) < 1000:
            os.system(f'curl -s -m 120 -o {p} https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/rosters/csv/cfb_rosters_{y}.csv')
        return list(csv.DictReader(open(p)))
    H = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_hist_md.json.gz')))
    S = {}
    for s, G in H['games'].items():
        G = [g for g in G if g.get('homeClassification') == 'fbs' and g.get('awayClassification') == 'fbs' and g.get('homePoints') is not None]
        ids = sorted({g['homeId'] for g in G} | {g['awayId'] for g in G}); ix = {t: i for i, t in enumerate(ids)}
        X = np.zeros((len(G), len(ids) + 1)); yv = np.zeros(len(G))
        for i, g in enumerate(G):
            X[i, ix[g['homeId']]] = 1; X[i, ix[g['awayId']]] = -1; X[i, -1] = 0 if g.get('neutralSite') else 1
            yv[i] = max(-35, min(35, g['homePoints'] - g['awayPoints']))
        b = np.linalg.solve(X.T @ X + 1e-2 * np.eye(len(ids) + 1), X.T @ yv); r = b[:-1] - b[:-1].mean()
        S[int(s)] = {str(t): float(r[ix[t]]) for t in ids}
    # team name -> ESPN id, from the games' names
    nm2id = {}
    for G in H['games'].values():
        for g in G:
            for side in ('home', 'away'):
                if g.get(side + 'Classification') == 'fbs': nm2id.setdefault(names.team_key(g[side + 'Team']), str(g[side + 'Id']))
    tid = lambda t: nm2id.get(names.team_key(t))
    P = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_recruits_cfbd.json.gz')))
    byname = CH.cfb_index(P)
    recruit = lambda first, last, team, y: CH.cfb_recruit(byname, f'{first} {last}', team, y)
    first = {}   # athlete id -> first season on a roster file (ESPN's class field does not advance: not used)
    for y in range(2014, 2027):
        try:
            for r in roster(y): first.setdefault(r['athlete_id'], y)
        except OSError: pass
    R = {}
    def ros(y):
        if y not in R:
            out = []
            for r in roster(y):
                t = tid(r['team'])
                if not t: continue
                cy, rt = recruit(r['first_name'], r['last_name'], r['team'], y)
                f = cy if cy is not None else first.get(r['athlete_id'], y)
                if f == 2014 and cy is None: continue   # first file: his class is unknown
                c = max(1, min(4, y - f + 1))
                out.append({'id': r['athlete_id'], 't': t, 'c': c, 'v': CH.cfb_value(rt)})
            R[y] = out
        return R[y]
    def pairs(y):
        nxt = {r['id']: r for r in ros(y + 1)}
        return [(r['c'], int(r['id'] in nxt and nxt[r['id']]['t'] == r['t']), 0.0 if r['id'] in nxt else None) for r in ros(y)]
    def rows(y):
        out = list(ros(y))
        for r in P.get(str(y + 1), []):
            t = tid(r[4])
            if t and r[1]: out.append({'t': t, 'c': 1, 'new': 1, 'v': CH.cfb_value(r[1])})
        return out
    return S, pairs, rows


def paired_t(d, cl):
    g = defaultdict(float)
    for x, c in zip(d, cl): g[c] += x
    v = np.array(list(g.values())); return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))) if len(v) > 2 and v.std() > 0 else 0.0


def main():
    sp = ([a for a in sys.argv[1:] if not a.startswith('--')] or ['cbb'])[0]
    S, pairs, rows = cbb_data() if sp == 'cbb' else cfb_data()
    out = {'sport': sp, 'h': {}}
    for k, origins in ORIG[sp].items():
        D = []   # (origin, team, z now, z talent, z target)
        for y in origins:
            pr = [p for yy in range(y - 3, y) for p in pairs(yy)]
            stay, dev = CH.rates(pr)
            cv = S.curve(y) if USE_CURVE and hasattr(S, 'curve') else None
            T = CH.chain(rows(y), stay, dev, k, curve=cv, rep=REP)
            now, tgt = S.get(y, {}), S.get(y + k, {})
            common = [t for t in now if t in tgt and t in T]
            zn, zt, zy = z({t: now[t] for t in common}), z({t: T[t] for t in common}), z({t: tgt[t] for t in common})
            D += [(y, t, zn[t], zt[t], zy[t]) for t in common]
            out.setdefault('rates', {})[str(y)] = {'stay': {c: round(v, 3) for c, v in stay.items()}, 'dev': {c: round(v, 3) for c, v in dev.items()}}
        A = np.array([[d[2], d[3], d[4]] for d in D]); O = np.array([d[0] for d in D]); Tm = [d[1] for d in D]
        e0 = np.zeros(len(D)); e1 = np.zeros(len(D)); folds = {}
        for y in origins:
            tr, te = O != y, O == y
            X0 = np.c_[np.ones(tr.sum()), A[tr, 0]]; X1 = np.c_[X0, A[tr, 1]]
            b0 = np.linalg.lstsq(X0, A[tr, 2], rcond=None)[0]; b1 = np.linalg.lstsq(X1, A[tr, 2], rcond=None)[0]
            p0 = b0[0] + b0[1] * A[te, 0]; p1 = b1[0] + b1[1] * A[te, 0] + b1[2] * A[te, 1]
            e0[te] = (A[te, 2] - p0) ** 2; e1[te] = (A[te, 2] - p1) ** 2
            folds[str(y)] = {'n': int(te.sum()), 'mse0': round(float(e0[te].mean()), 4), 'mse1': round(float(e1[te].mean()), 4)}
        t = paired_t(e0 - e1, Tm)
        won = sum(f['mse1'] < f['mse0'] for f in folds.values())
        X1 = np.c_[np.ones(len(D)), A[:, 0], A[:, 1]]; b = np.linalg.lstsq(X1, A[:, 2], rcond=None)[0]
        X0 = np.c_[np.ones(len(D)), A[:, 0]]; b0 = np.linalg.lstsq(X0, A[:, 2], rcond=None)[0]
        r2 = lambda e: 1 - e.mean() / A[:, 2].var()
        res = {'n': len(D), 'mse0': round(float(e0.mean()), 4), 'mse1': round(float(e1.mean()), 4), 'r2_0': round(float(r2(e0)), 3), 'r2_1': round(float(r2(e1)), 3),
               't': round(t, 2), 'won': won, 'of': len(origins), 'folds': folds, 'b': [round(float(x), 4) for x in b], 'b0': [round(float(x), 4) for x in b0],
               'rTalent': round(float(np.corrcoef(A[:, 1], A[:, 2])[0, 1]), 3)}
        res['pass'] = bool(t >= 2 and won >= len(origins) - 1)
        res['_e1'] = [round(float(x), 5) for x in e1]; res['_cl'] = Tm
        out['h'][str(k)] = res
        print(sp, k, {x: res[x] for x in ('n', 'r2_0', 'r2_1', 't', 'won', 'of', 'pass', 'b')}, flush=True)
    # the live origin's rates: the three latest origins with a next season on file
    last = max(y for y in range(2015, 2027) if S.get(y + 1)) if sp == 'cfb' else 2025
    stay, dev = CH.rates([p for yy in range(last - 2, last + 1) for p in pairs(yy)])
    out['live'] = {'origins': [last - 2, last], 'stay': {c: round(v, 4) for c, v in stay.items()}, 'dev': {c: round(v, 4) for c, v in dev.items()}}
    if USE_CURVE:
        try:
            import subprocess
            base = json.load(open(os.path.join(HERE, '.base_e.json')))
            for k, v in out['h'].items():
                d = np.array(base[k]) - np.array(v['_e1']); v['vsClassMeans'] = {'t': round(paired_t(d, v['_cl']), 2), 'mse': [round(float(np.mean(base[k])), 4), round(float(np.mean(v['_e1'])), 4)]}
                print('curve vs class means', k, v['vsClassMeans'])
        except OSError: pass
        for v in out['h'].values(): v.pop('_e1', None); v.pop('_cl', None)
        json.dump(out, open(os.path.join(HERE, f'results_{sp}_curve.json'), 'w'), indent=1); return
    json.dump(out, open(os.path.join(HERE, f'results_{sp}.json'), 'w'), indent=1)
    json.dump({k: v['_e1'] for k, v in out['h'].items()}, open(os.path.join(HERE, '.base_e.json'), 'w')) if sp == 'cbb' else None
    for v in out['h'].values(): v.pop('_e1', None); v.pop('_cl', None)
    F = os.path.join(ROOT, 'data', 'team_years_fit.json')
    allf = json.load(open(F)) if os.path.exists(F) else {}
    allf[sp] = {'h': {k: {x: v[x] for x in ('b', 'b0', 'pass', 't', 'won', 'of', 'n', 'r2_0', 'r2_1')} for k, v in out['h'].items()}, 'live': out['live']}
    json.dump(allf, open(F, 'w'), indent=1)


if __name__ == '__main__':
    main()
