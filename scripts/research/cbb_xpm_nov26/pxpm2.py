#!/usr/bin/env python3
"""pXPM round 2 (prereg.md): feature blocks on top of v1, walk-forward. python3 pxpm2.py -> pxpm2.json"""
import csv, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import xpm as X
import gl
A = X.A; ix = X.ix; fl = X.fl; PAIRS = X.PAIRS; YRS = X.YRS
PRM = {'o': (.35, .2, 200, 0), 'd': (.6, .4, 100, .25)}
POS = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}

# ---- extra per player-season inputs
EX = {}
for y in YRS:
    TR = gl.team_results(y); ex = defaultdict(dict); P = defaultdict(lambda: defaultdict(float))
    for row in csv.reader(open(os.path.join(X.C, f'adv{y}.csv'), encoding='utf-8', errors='replace')):
        if len(row) < 66: continue
        gp, mp = fl(row[ix['gp']]), fl(row[ix['mp']])
        if not gp or not mp or fl(row[ix['bpm']]) is None: continue
        e = gp * mp; pid = row[ix['pid']]; q = P[pid]; t = TR.get(row[ix['team']])
        q['e'] += e; q['oe'] += (t['oe'] if t else 0.0) * e; q['de'] += (t['de'] if t else 0.0) * e; q['mpct'] += (fl(row[ix['min_per']]) or 0.0)
        ex[pid]['rec'] = max(ex[pid].get('rec', 0.0), fl(row[ix['rec']]) or 0.0); ex[pid]['pos'] = POS.get(row[ix['role']], 'F')
        try: yy, mm, dd = (int(v) for v in row[ix['dob']].split('-')); ex[pid]['age'] = min(26.0, max(17.0, y - yy + (11 - mm) / 12 + (1 - dd) / 365))
        except ValueError: ex[pid]['age'] = None
    for pid, q in P.items(): ex[pid].update(toe=q['oe'] / q['e'], tde=q['de'] / q['e'], mpct=min(100.0, q['mpct']) / 100)
    # game logs: late form per side, consistency
    S = gl.season(y); G = defaultdict(list)
    for p in S['pg']: G[p['pid']].append((p['d'], p['e'], p['ogb'], p['dgb'], p['gb']))
    sds = {}
    for pid, g in G.items():
        if pid not in ex: continue
        g.sort(); e = np.array([r[1] for r in g]); E = e.sum(); cum = np.cumsum(e); late = cum > E * 2 / 3
        if late.sum() == 0 or E <= 0: continue
        rel = E / (E + 200)
        for s, j in (('o', 2), ('d', 3)):
            v = np.array([r[j] for r in g]); ex[pid]['form_' + s] = float((np.average(v[late], weights=e[late]) - np.average(v, weights=e)) * rel)
        v = np.array([r[4] for r in g]); m = np.average(v, weights=e); sds[pid] = (float(math.sqrt(np.average((v - m) ** 2, weights=e))), E)
    big = [v for v in sds.values() if v[1] >= 500]; mu = np.mean([v[0] for v in big]); sd = np.std([v[0] for v in big])
    for pid, (v, E) in sds.items(): ex[pid]['cons'] = float(max(-3, min(3, (v - mu) / sd)) * E / (E + 200))
    EX[y] = ex


def block(n, s, name, sh):
    R = X.ROWS[n]; pids = R['pid']; ex = EX[n]; pe = EX.get(n - 1, {})
    g = lambda k, d=0.0: np.array([(ex.get(p, {}).get(k) if ex.get(p, {}).get(k) is not None else d) for p in pids])
    fr = 1 - R['c_So'] - R['c_Jr'] - R['c_Sr']
    if name == 'F1': return [g('form_' + s)]
    if name == 'F2':
        rec = g('rec') / 100; has = (rec > 0).astype(float); up = R['c_Jr'] + R['c_Sr']
        return [rec * fr, rec * R['c_So'], rec * up, has * fr, has * R['c_So'], has * up]
    if name == 'F3':
        t = (g('toe') if s == 'o' else -g('tde')) / 10; return [t, t * fr]
    if name == 'F4':
        pos = [ex.get(p, {}).get('pos', 'F') for p in pids]; ht = R['z_ht']
        return [np.array([1.0 if q == 'G' else 0.0 for q in pos]), np.array([1.0 if q == 'C' else 0.0 for q in pos]), ht * fr]
    if name == 'F5':
        m = g('mpct'); pm = np.array([pe.get(p, {}).get('mpct', np.nan) for p in pids]); dm = np.where(np.isnan(pm), 0.0, m - pm)
        return [(sh - sh.mean()) ** 2 / 10, m, dm]
    if name == 'F6': return [g('cons')]
    if name == 'F7':
        a = g('age', 21.0) + 1 - 21; return [a, a ** 2]


def design(n, s, blocks):
    base = X.design(n, s, PRM[s], True); sh = base[:, 1]
    cols = [base] + [np.column_stack(block(n, s, b, sh)) for b in blocks]
    return np.hstack(cols)


def walk(blocks):
    out = {}
    G = {}
    for s in 'od':
        for m in YRS[:-1]:
            D = design(m, s, blocks); R = X.ROWS[m]; w = R['w']; y = R['y' + s]; Dw = D * w[:, None]; G[(s, m)] = (D.T @ Dw, Dw.T @ y)
    for n in PAIRS:
        tr = [m for m in YRS[:-1] if m <= n - 1]; v = 0
        for s in 'od':
            A_ = sum(G[(s, m)][0] for m in tr); b = sum(G[(s, m)][1] for m in tr); P = np.zeros(A_.shape[0]); P[X.NB0:] = 10.0
            v = v + design(n, s, blocks) @ np.linalg.solve(A_ + np.diag(P) + 1e-9 * np.eye(len(P)), b)
        out[n] = {pid: float(v[i]) for i, pid in enumerate(X.ROWS[n]['pid'])}
    return out


def score(vn):
    per, pp = {}, {}
    for n in PAIRS: per[n], pp[n] = A.predict_rows(n, vn[n], 'bpm')
    sc = A.predict_score(per, pp); sc['rmse'] = X.player_rmse(vn); return sc


def cmp(a, b):
    t, p = A.paired_t([a['byPair'][n] - b['byPair'][n] for n in PAIRS]); return {'t': t, 'pairsBetter': int(sum(a['byPair'][n] > b['byPair'][n] for n in PAIRS))}


if __name__ == '__main__':
    out = {}; v1 = score(walk([])); out['v1'] = v1; print('v1', v1['teamR2'], v1['playerR_vsBPM'], v1['rmse'], flush=True)
    single = {}
    for b in ('F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7'):
        sc = score(walk([b])); single[b] = {'teamR2': sc['teamR2'], 'playerR': sc['playerR_vsBPM'], 'rmse': sc['rmse'], **cmp(sc, v1)}; print(b, single[b], flush=True)
    out['single'] = single
    kept = []; cur = v1; steps = []
    for b in sorted(single, key=lambda k: -single[k]['t']):
        sc = score(walk(kept + [b])); c = cmp(sc, cur); ok = c['t'] > 2 and sc['playerR_vsBPM'] >= cur['playerR_vsBPM']
        steps.append({'block': b, 'teamR2': sc['teamR2'], 'playerR': sc['playerR_vsBPM'], 'rmse': sc['rmse'], **c, 'kept': bool(ok)}); print('step', steps[-1], flush=True)
        if ok: kept.append(b); cur = sc
    out['forward'] = steps; out['kept'] = kept; out['v2'] = cur; out['v2 vs v1'] = cmp(cur, v1)
    _, _, base = A.predict(lambda n: A.vals(n, 'bpm')); out['BPM'] = base; out['v2 vs BPM'] = cmp(cur, base); out['v1 vs BPM'] = cmp(v1, base)
    print('v2', kept, cur['teamR2'], cur['playerR_vsBPM'], cur['rmse'], out['v2 vs v1'], out['v2 vs BPM'], flush=True)
    json.dump(out, open(os.path.join(HERE, 'pxpm2.json'), 'w'), indent=1)
