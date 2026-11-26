#!/usr/bin/env python3
"""rXPM round 3 amendment 4: team anchors W1 (wins mix) and W2 (capped game margins) on BPM. python3 rxpm9.py -> rxpm9.json"""
import json, math, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gl
from rxpm4 import paired, YEARS
from rxpm5 import loso_slope_sse, r2
HCA, B = pickle.load(open(os.path.join(gl.GB, 'built.pkl'), 'rb'))
SIG = 16.0
Phi = lambda z: .5 * (1 + math.erf(z / math.sqrt(2)))
CANDS = [('W1', .25), ('W1', .5), ('W2', 10), ('W2', 15), ('W2', 20), ('W2', 30)]


def anchors(y, sel):
    """team -> dict(adj mean, waa mean, capped means) over the games sel(r) keeps"""
    acc = defaultdict(lambda: defaultdict(list))
    for (d, t), r in B[y]['tg'].items():
        if not sel(r): continue
        q = acc[t]; q['a'].append(r['a']); q['waa'].append(r['win'] - Phi((-r['oem'] + HCA * r['h']) / SIG))
        for c in (10, 15, 20, 30): q[c].append(max(-c, min(c, r['a'])))
    return {t: {k: float(np.mean(v)) for k, v in q.items()} | {'n': len(q['a'])} for t, q in acc.items()}


# pooled rescale of each anchor to adjusted-margin points (slope of season mean adjusted margin on the anchor, centred within season)
def scales():
    xs = defaultdict(list); ys = []
    for y in YEARS:
        An = anchors(y, lambda r: True); ts = list(An); a = np.array([An[t]['a'] for t in ts]); ys.append(a - a.mean())
        for k in ('waa', 10, 15, 20, 30):
            v = np.array([An[t][k] for t in ts]); xs[k].append(v - v.mean())
    Y = np.concatenate(ys); return {k: float(np.concatenate(v) @ Y / (np.concatenate(v) @ np.concatenate(v))) for k, v in xs.items()}


SC = scales()


def target(An, t, cand, mu):
    """anchor in adjusted-margin points (centred with the season means mu)"""
    kind, c = cand; a = An[t]['a'] - mu['a']
    if kind == 'BPM': return a
    if kind == 'W1': return (1 - c) * a + c * SC['waa'] * (An[t]['waa'] - mu['waa'])
    return SC[c] * (An[t][c] - mu[c])


def full(y, cand):
    """(pid, team) -> BPM re-anchored (season): shift = (target - own adjusted mean) / 5 on top of BPM (whose sum is adjEM)"""
    An = anchors(y, lambda r: True); mu = {k: float(np.mean([An[t][k] for t in An])) for k in ('a', 'waa', 10, 15, 20, 30)}
    out = {}
    for k, q in B[y]['st'].items():
        if q['bpm'] is None or k[1] not in An: continue
        sh = 0.0 if cand[0] in ('BPM', 'GBPM') else (target(An, k[1], cand, mu) - (An[k[1]]['a'] - mu['a'])) / 5
        out[k] = (q['bpm'] + sh, q['min'], q['gbpm'])
    return out


def test_c(cand):
    res = {}
    for tgt in ('em', 'wab_g', 'wp'):
        rows = {}
        for y in YEARS:
            V = full(y, cand); num = defaultdict(float); den = defaultdict(float)
            for (pid, t), (v, e, g) in V.items(): num[t] += (g if cand[0] == 'GBPM' else v) * e; den[t] += e
            ts = [t for t in num if t in B[y]['tr']]; x = np.array([5 * num[t] / den[t] for t in ts]); yy = np.array([B[y]['tr'][t][tgt] for t in ts])
            rows[y] = (x - x.mean(), yy - yy.mean())
        L = loso_slope_sse(rows); res[tgt] = (r2(L), {y: L[y][0] for y in L})
    return res


def test_b(cand):
    """odd-game GBPM shifted to the odd-game anchor -> even-game mean adjusted margin (and the reverse)"""
    rows = {}
    for y in YEARS:
        st = B[y]['st']; xs, ys = [], []
        for H in (0, 1):
            An = anchors(y, lambda r: r['odd'] == (H == 0)); Ao = anchors(y, lambda r: r['odd'] != (H == 0))
            mu = {k: float(np.mean([An[t][k] for t in An])) for k in ('a', 'waa', 10, 15, 20, 30)}
            num = defaultdict(float); den = defaultdict(float)
            for k, q in st.items():
                h = q['h'][H]
                if h['e'] > 0: num[k[1]] += h['gb'] / h['e'] * h['min']; den[k[1]] += h['min']
            vals = {}; lo = []
            for k, q in st.items():
                h = q['h'][H]; t = k[1]
                if h['e'] <= 0 or t not in An: continue
                g = h['gb'] / h['e']; vals[k] = g if cand[0] == 'GBPM' else g + (target(An, t, cand, mu) - 5 * num[t] / den[t]) / 5
                if h['e'] < 150: lo.append(vals[k])
            fill = float(np.mean(lo)); n2 = defaultdict(float); d2 = defaultdict(float)
            for k, q in st.items():
                mn = q['h'][1 - H]['min']
                if mn > 0: n2[k[1]] += mn * vals.get(k, fill); d2[k[1]] += mn
            ts = [t for t in d2 if t in Ao and Ao[t]['n'] >= 5]
            x = np.array([5 * n2[t] / d2[t] for t in ts]); yy = np.array([Ao[t]['a'] for t in ts]); xs.append(x - x.mean()); ys.append(yy - yy.mean())
        rows[y] = (np.concatenate(xs), np.concatenate(ys))
    L = loso_slope_sse(rows); return r2(L), {y: L[y][0] for y in L}


def test_n(cand):
    sys.path.insert(0, os.path.join(gl.ROOT, 'scripts', 'research', 'metric_audit_nov24', 'cbb'))
    import audit as A
    def vals(n):
        V = full(n, cand); num = defaultdict(float); den = defaultdict(float)
        for (pid, t), (v, e, g) in V.items(): num[pid] += (g if cand[0] == 'GBPM' else v) * e; den[pid] += e
        return {pid: num[pid] / den[pid] for pid in num if pid in A.S[n]['pl']}
    _, _, s = A.predict(vals); return s


if __name__ == '__main__':
    out = {'scale': {str(k): round(v, 4) for k, v in SC.items()}}
    base = {nm: {'C': test_c(c), 'B': test_b(c), 'N': test_n(c)} for nm, c in (('BPM', ('BPM', 0)), ('GBPM', ('GBPM', 0)))}
    for nm, e in base.items():
        out[nm] = {'adjEM': e['C']['em'][0], 'WAB': e['C']['wab_g'][0], 'win%': e['C']['wp'][0], 'B': e['B'][0], 'N teamR2': e['N']['teamR2'], 'N playerR_vsBPM': e['N']['playerR_vsBPM']}
        print(nm, out[nm], flush=True)
    for cand in CANDS:
        C = test_c(cand); Bq = test_b(cand); N = test_n(cand); e = {'adjEM': C['em'][0], 'WAB': C['wab_g'][0], 'win%': C['wp'][0], 'B': Bq[0], 'N teamR2': N['teamR2'], 'N playerR_vsBPM': N['playerR_vsBPM']}
        for k, tg in (('WAB', 'wab_g'), ('adjEM', 'em'), ('win%', 'wp')):
            for b in ('BPM', 'GBPM'):
                t, p, n = paired([base[b]['C'][tg][1][y] - C[tg][1][y] for y in YEARS]); e[f'{k} vs {b}'] = [t, n]
        for b in ('BPM', 'GBPM'):
            t, p, n = paired([base[b]['B'][1][y] - Bq[1][y] for y in YEARS]); e[f'B vs {b}'] = [t, n]
            t, p, n = paired([N['byPair'][k] - base[b]['N']['byPair'][k] for k in N['byPair']]); e[f'N vs {b}'] = [t, n]
        out[f'{cand[0]} {cand[1]}'] = e; print(cand, e, flush=True)
    json.dump(out, open(os.path.join(HERE, 'rxpm9.json'), 'w'), indent=1)
