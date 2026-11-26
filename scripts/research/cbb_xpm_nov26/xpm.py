#!/usr/bin/env python3
"""CBB XPM research (Nov 26 2026, prereg.md): rXPM (descriptive) and pXPM (predictive) against Barttorvik BPM on the
Nov 24 metric-audit harness (scripts/research/metric_audit_nov24/cbb/audit.py). Data: scripts/.cache/team_adj/adv<y>.csv +
tr<y>.json, 2008-2026 (no 2026-27).   python3 xpm.py -> results.json (+ pxpm_rows.json.gz: walk-forward pXPM by season)"""
import csv, gzip, itertools, json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb'))
import audit as A                      # loads S (2010-2026) and the harness
import core
C = A.C; ix = A.ix; fl = A.fl
YRS = list(range(2008, 2027)); PAIRS = A.PAIRS
BOX = ['stl', 'blk', 'orb', 'drb', 'ast', 'to', 'ftr', 'tpa100', 'rims', 'usg', 'ts', 'ht']
CLS = ['Fr', 'So', 'Jr', 'Sr']


def ht(s):
    try: a, b = str(s).split('-'); return int(a) * 12 + int(b)
    except ValueError: return None


def load(y):
    """pid -> minutes-weighted season line (every stint), sides and box rates"""
    P = defaultdict(lambda: defaultdict(float))
    for row in csv.reader(open(os.path.join(C, f'adv{y}.csv'), encoding='utf-8', errors='replace')):
        if len(row) < 66: continue
        gp, mp, b = fl(row[ix['gp']]), fl(row[ix['mp']]), fl(row[ix['bpm']])
        if not gp or not mp or b is None: continue
        e = gp * mp; q = P[row[ix['pid']]]; q['e'] += e
        for k in ('bpm', 'obpm', 'dbpm', 'gbpm', 'ogbpm', 'dgbpm', 'stl', 'blk', 'orb', 'drb', 'ast', 'to', 'ftr', 'tpa100', 'usg', 'ts'):
            q[k] += (fl(row[ix[k]]) or 0.0) * e
        ra, ma, ta = fl(row[ix['rima']]) or 0, fl(row[ix['mida']]) or 0, fl(row[ix['tpa']]) or 0
        q['ra'] += ra; q['sa'] += ra + ma + ta
        h = ht(row[ix['ht']])
        if h and 66 <= h <= 90: q['ht'] = h
        q['yr'] = row[ix['yr']]; q['team'] = row[ix['team']]
    out = {}
    for pid, q in P.items():
        e = q['e']; v = {k: q[k] / e for k in ('bpm', 'obpm', 'dbpm', 'gbpm', 'ogbpm', 'dgbpm', 'stl', 'blk', 'orb', 'drb', 'ast', 'to', 'ftr', 'tpa100', 'usg', 'ts')}
        v['rims'] = q['ra'] / q['sa'] if q['sa'] else None; v['ht'] = q.get('ht'); v['e'] = e; v['yr'] = q['yr']; v['team'] = q['team']
        out[pid] = v
    # box z within season (minutes weighted, 10+ mpg-ish players set the scale), winsorised, times reliability e/(e+200)
    big = [v for v in out.values() if v['e'] >= 300]
    for k in BOX:
        xs = np.array([v[k] for v in big if v[k] is not None]); ws = np.array([v['e'] for v in big if v[k] is not None])
        m = float(np.average(xs, weights=ws)); s = float(math.sqrt(np.average((xs - m) ** 2, weights=ws))) or 1.0
        for v in out.values():
            z = 0.0 if v[k] is None else max(-3.0, min(3.0, (v[k] - m) / s))
            v['z_' + k] = z * v['e'] / (v['e'] + 200)
    return out


L = {y: load(y) for y in YRS}
MU = {y: {s: float(np.mean([v[s + 'bpm'] for v in L[y].values() if v['e'] < 200])) for s in ('o', 'd')} for y in YRS}
for y in YRS:
    MU[y].update({('g' + s): float(np.mean([v[s + 'gbpm'] for v in L[y].values() if v['e'] < 200])) for s in ('o', 'd')})

# -------- per player-season arrays (features at n, target at n+1)
ROWS = {}     # n -> dict of arrays
for n in YRS:
    pids = list(L[n]); a = defaultdict(list)
    for pid in pids:
        v = L[n][pid]
        for k, yy in enumerate((n, n - 1, n - 2)):
            w = L.get(yy, {}).get(pid)
            a[f'e{k}'].append(w['e'] if w else 0.0)
            for s in ('o', 'd'):
                a[f'{s}b{k}'].append(w[s + 'bpm'] if w else 0.0); a[f'{s}g{k}'].append(w[s + 'gbpm'] if w else 0.0)
        for c in CLS[1:]: a['c_' + c].append(1.0 if v['yr'] == c else 0.0)
        for k in BOX: a['z_' + k].append(v['z_' + k])
        nx = L.get(n + 1, {}).get(pid)
        a['ye'].append(nx['e'] if nx else 0.0)
        a['yo'].append(nx['obpm'] if nx else 0.0); a['yd'].append(nx['dbpm'] if nx else 0.0)
    R = {k: np.array(x) for k, x in a.items()}; R['pid'] = pids
    tot = R['ye'].sum(); R['w'] = R['ye'] / (tot / max(1, (R['ye'] > 0).sum())) if tot else R['ye']
    ROWS[n] = R

GRID = list(itertools.product([0, .35, .6, 1], [0, .2, .4], [0, 100, 200, 400, 800], [0, .25, .5]))


def design(n, s, prm, box):
    w2, w3, K, g = prm; R = ROWS[n]; W = [1.0, w2, w3]
    num = sum(W[k] * R[f'e{k}'] * ((1 - g) * R[f'{s}b{k}'] + g * R[f'{s}g{k}']) for k in range(3))
    E = sum(W[k] * R[f'e{k}'] for k in range(3))
    mu = (1 - g) * MU[n][s] + g * MU[n]['g' + s]
    sh = (num + K * mu) / np.maximum(E + K, 1e-9)
    cols = [np.ones_like(sh), sh, np.log1p(R['e0'] / 100)] + [R['c_' + c] for c in CLS[1:]]
    if box: cols += [R['z_' + k] for k in BOX]
    return np.column_stack(cols)


NB0 = 3 + len(CLS) - 1   # unpenalised columns


def grams(s, prm, box):
    out = {}
    for m in YRS[:-1]:
        X = design(m, s, prm, box); R = ROWS[m]; w = R['w']; y = R['y' + s]
        Xw = X * w[:, None]; out[m] = (X.T @ Xw, Xw.T @ y, float((w * y * y).sum()))
    return out


def solve(G, ms, box, lam=10.0):
    A_ = sum(G[m][0] for m in ms); b = sum(G[m][1] for m in ms)
    P = np.zeros(A_.shape[0]); P[NB0:] = lam if box else 0.0
    return np.linalg.solve(A_ + np.diag(P) + 1e-9 * np.eye(len(P)), b)


def sse(G, m, beta): return G[m][2] - 2 * beta @ G[m][1] + beta @ G[m][0] @ beta


def pxpm_walk(box):
    """n -> {pid: pXPM} for each pair n (fit on pairs m <= n-1, i.e. targets <= n), chosen params, O/D"""
    GG = {(s, prm): grams(s, prm, box) for s in ('o', 'd') for prm in GRID}
    out, ch, side = {}, {}, {}
    for n in PAIRS + [2026]:
        tr = [m for m in YRS[:-1] if m <= n - 1]
        vals = {}
        for s in ('o', 'd'):
            def cv(prm):
                G = GG[(s, prm)]; return sum(sse(G, m, solve(G, [q for q in tr if q != m], box)) for m in tr)
            best = min(GRID, key=cv); beta = solve(GG[(s, best)], tr, box)
            vals[s] = design(n, s, best, box) @ beta; ch[(n, s)] = (best, [round(float(b), 3) for b in beta])
        pids = ROWS[n]['pid']
        out[n] = {pid: float(vals['o'][i] + vals['d'][i]) for i, pid in enumerate(pids)}
        side[n] = {pid: (round(float(vals['o'][i]), 2), round(float(vals['d'][i]), 2)) for i, pid in enumerate(pids)}
        print('pxpm', 'box' if box else 'hist', n, ch[(n, 'o')][0], ch[(n, 'd')][0], flush=True)
    return out, ch, side


def score_vs(per, pp, base):
    sc = A.predict_score(per, pp); d = [sc['byPair'][n] - base['byPair'][n] for n in PAIRS]; t, p = A.paired_t(d)
    return sc, {'before': base['teamR2'], 'after': sc['teamR2'], 'pairsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': p,
                'playerR_vsBPM': [base['playerR_vsBPM'], sc['playerR_vsBPM']], 'guard': bool(sc['playerR_vsBPM'] >= base['playerR_vsBPM'] - .01)}


def player_rmse(vn_by_n):
    """next-season BPM RMSE, weighted by next minutes, players with 300+ next minutes and a season-n line"""
    se = w = 0.0
    for n in PAIRS:
        P1 = A.S[n + 1]['pl']
        for pid, x in vn_by_n[n].items():
            q = P1.get(pid)
            if q and q['e'] >= A.MINN and pid in A.S[n]['pl']: se += q['e'] * (x - q['bpm']) ** 2; w += q['e']
    return round(math.sqrt(se / w), 4)


def holm(cand):
    order = sorted(cand, key=lambda k: cand[k]['p']); m = len(order); stop = False
    for i, k in enumerate(order):
        adj = min(1.0, cand[k]['p'] * (m - i)); cand[k]['pHolm'] = round(adj, 4)
        ok = (not stop) and adj < .05 and cand[k]['after'] > cand[k]['before'] and cand[k]['guard']
        if adj >= .05: stop = True
        cand[k]['pass'] = bool(ok); cand[k]['p'] = round(cand[k]['p'], 5)


# ---------------------------------------------------------------- rXPM (descriptive)
def side_vals(y, a, c):
    out = {}
    for pid, v in L[y].items():
        out[pid] = ((1 - a) * v['obpm'] + a * v['ogbpm'], (1 - c) * v['dbpm'] + c * v['dgbpm'])
    return out


def tadj(y, sv):
    """one shift a minute per team per side so the side's minute-weighted mean x 5 hits adjOE - mean / mean - adjDE"""
    tr = json.load(open(os.path.join(C, f'tr{y}.json'))); T = {}
    for r in tr:
        try: g = sum(int(v) for v in str(r[3]).split('-')[:2])
        except ValueError: continue
        if g: T[r[1]] = (r[4], r[6])
    lo = np.mean([v[0] for v in T.values()]); ld = np.mean([v[1] for v in T.values()])
    num = defaultdict(lambda: [0.0, 0.0]); den = defaultdict(float); stints = []
    for row in csv.reader(open(os.path.join(C, f'adv{y}.csv'), encoding='utf-8', errors='replace')):
        if len(row) < 66: continue
        t, pid = row[ix['team']], row[ix['pid']]; gp, mp = fl(row[ix['gp']]), fl(row[ix['mp']])
        if t not in T or not gp or not mp or pid not in sv: continue
        e = gp * mp; stints.append((pid, t, e)); den[t] += e; num[t][0] += sv[pid][0] * e; num[t][1] += sv[pid][1] * e
    # slope b pooled within season: side target = b x 5 x weighted mean (b fit, then exact shift)
    xo = np.array([5 * num[t][0] / den[t] for t in den]); yo = np.array([T[t][0] - lo for t in den])
    xd = np.array([5 * num[t][1] / den[t] for t in den]); yd = np.array([ld - T[t][1] for t in den])
    bo = float(np.polyfit(xo - xo.mean(), yo, 1)[0]); bd = float(np.polyfit(xd - xd.mean(), yd, 1)[0])
    sh = {}
    for i, t in enumerate(den):
        sh[t] = ((yo[i] / bo - (xo[i] - xo.mean())) / 5, (yd[i] / bd - (xd[i] - xd.mean())) / 5)
    acc = defaultdict(lambda: [0.0, 0.0, 0.0])
    for pid, t, e in stints:
        acc[pid][0] += sh[t][0] * e; acc[pid][1] += sh[t][1] * e; acc[pid][2] += e
    out = {}
    for pid, (o, d) in sv.items():
        q = acc.get(pid)
        out[pid] = (o + q[0] / q[2], d + q[1] / q[2]) if q and q[2] else (o, d)
    return out


def total(sv): return {pid: o + d for pid, (o, d) in sv.items()}


def describe_tuned(ys, grid, make):
    """leave-one-season-out choice of the grid value on held-out win% SSE; returns per-season SSE, choices"""
    G = {g: {y: A.drows(y, make(y, g), 'wp') for y in ys} for g in grid}
    sse_, ch = {}, {}
    for y in ys:
        oth = [s for s in ys if s != y]
        def ho(g):
            Lq = A.loso_sse({s: G[g][s] for s in oth}, oth); return sum(a for a, _ in Lq.values()) / sum(b for _, b in Lq.values())
        g = min(grid, key=ho) if len(grid) > 1 else grid[0]; ch[y] = g
        xs = np.array([x for s in oth for x, _ in G[g][s]]); yy = np.array([b for s in oth for _, b in G[g][s]]); b = float(xs @ yy / (xs @ xs))
        X = np.array([x for x, _ in G[g][y]]); Y = np.array([v for _, v in G[g][y]]); sse_[y] = float(((Y - b * X) ** 2).sum())
    return sse_, ch


def main():
    out = {'prereg': 'prereg.md', 'pairs': PAIRS}
    # ---- rXPM
    ys = PAIRS + [2026]
    RG = {y: A.drows(y, A.vals(y, 'gbpm'), 'wp') for y in ys}; LG = A.loso_sse(RG, ys)
    RB = {y: A.drows(y, A.vals(y, 'bpm'), 'wp') for y in ys}; LB = A.loso_sse(RB, ys)
    sst = sum(LG[y][1] for y in ys)
    AC = [(a, c) for a in (0, .25, .5, .75, 1) for c in (0, .25, .5, .75, 1)]
    cands = {
        'R1 side blend': describe_tuned(ys, AC, lambda y, g: total(side_vals(y, *g))),
        'R2 GBPM team-adjusted': describe_tuned(ys, [(1, 1)], lambda y, g: total(tadj(y, side_vals(y, *g)))),
        'R3 side blend + team adjustment': describe_tuned(ys, AC, lambda y, g: total(tadj(y, side_vals(y, *g)))),
    }
    rc = {}
    for name, (sse_, ch) in cands.items():
        d = [LG[y][0] - sse_[y] for y in ys]; t, p = A.paired_t(d)
        g = max(set(ch.values()), key=list(ch.values()).count)
        mk = (lambda y: total(tadj(y, side_vals(y, *g)))) if 'adjust' in name else (lambda y: total(side_vals(y, *g)))
        _, dem = A.describe(mk, 'em')
        rc[name] = {'target': 'held-out win% R2 (vs GBPM)', 'before': round(1 - sum(LG[y][0] for y in ys) / sst, 4),
                    'after': round(1 - sum(sse_.values()) / sst, 4), 'bpm': round(1 - sum(LB[y][0] for y in ys) / sst, 4),
                    'seasonsBetter': int(sum(x > 0 for x in d)), 't': t, 'p': p, 'chosen': {str(k): v for k, v in ch.items()},
                    'adjEM': dem['heldOut'], 'guard': bool(dem['heldOut'] >= .9985 - .001)}
        print(name, rc[name]['bpm'], rc[name]['before'], rc[name]['after'], t, dem['heldOut'], flush=True)
    holm(rc); out['rxpm'] = rc

    # ---- pXPM
    _, _, base = A.predict(lambda n: A.vals(n, 'bpm'))
    RP = A.roster_prior()
    rpv = {n: {pid: v for pid, (v, k) in RP[n].items() if k in ('ret', 'tr', 'back')} for n in PAIRS}
    _, _, rbase = A.predict(lambda n: rpv[n])
    out['baselines'] = {'BPM': base, 'roster prior BPM_hat (returners, same fill)': rbase,
                        'playerRMSE': {'BPM': player_rmse({n: A.vals(n, 'bpm') for n in PAIRS}), 'BPM_hat': player_rmse(rpv)}}
    pc, rows = {}, {}
    for box, nm in ((False, 'X1 history'), (True, 'X2 history + box')):
        vn, ch, side = pxpm_walk(box)
        per, pp = {}, {}
        for n in PAIRS: per[n], pp[n] = A.predict_rows(n, vn[n], 'bpm')
        sc, vb = score_vs(per, pp, base); _, vr = score_vs(per, pp, rbase)
        out[nm] = {'score': sc, 'playerRMSE': player_rmse(vn), 'chosen': {f'{n}{s}': v for (n, s), v in ch.items()}}
        pc[nm + ' vs BPM'] = vb; pc[nm + ' vs BPM_hat'] = vr
        rows[nm] = {str(n): side[n] for n in side}
        print(nm, sc['teamR2'], sc['playerR_vsBPM'], out[nm]['playerRMSE'], vb['t'], vr['t'], flush=True)
    holm(pc); out['pxpm'] = pc
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    with gzip.open(os.path.join(HERE, 'pxpm_rows.json.gz'), 'wt') as f: json.dump(rows, f)


if __name__ == '__main__':
    main()
