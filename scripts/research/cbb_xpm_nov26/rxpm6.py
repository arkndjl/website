#!/usr/bin/env python3
"""rXPM round 3, amendment 2 (prereg.md): base share a profile, starters-only refit, half-split who-sat-out test.
    python3 rxpm6.py -> rxpm6.json"""
import json, os, pickle, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gl, rxpm4 as R4
from rxpm4 import paired, rates, CNT, YEARS, COL, ZC
HCA, B = pickle.load(open(os.path.join(gl.GB, 'built.pkl'), 'rb'))
RA = pickle.load(open(os.path.join(gl.GB, 'ra.pkl'), 'rb'))
LAM = 30; AG = [0, .25, .5, .75, 1]


def base(R, a): return a * R[:, COL['bpm']] + (1 - a) * R[:, COL['gbpm']]
def X2(R, a): return np.column_stack([base(R, a), R[:, ZC]])


def loso(RW, a, box, frozen=None):
    """per-season SSE; box=False slope only. frozen: season -> coefficient vector (fit elsewhere)"""
    out = {}; fits = {}
    for y in RW:
        tr = [s for s in RW if s != y]; R = RW[y]
        if frozen is not None: b = frozen[y]; out[y] = float(((R[:, 0] - X2(R, a) @ b) ** 2).sum()); continue
        if box:
            b = R4.ridge(np.vstack([X2(RW[s], a) for s in tr]), np.concatenate([RW[s][:, 0] for s in tr]), LAM, 1)
            out[y] = float(((R[:, 0] - X2(R, a) @ b) ** 2).sum())
        else:
            x = np.concatenate([base(RW[s], a) for s in tr]); yy = np.concatenate([RW[s][:, 0] for s in tr]); b = np.array([float(x @ yy / (x @ x))])
            out[y] = float(((R[:, 0] - b[0] * base(R, a)) ** 2).sum())
        fits[y] = b
    return out, fits


def strict_rows(y):
    """starters only (20+ mpg, 8+ games): x = sum over core players who appeared of (mpg/40) x (f - team non-core mean)"""
    st, tg = B[y]['st'], B[y]['tg']; Z, _ = rates(st, None)
    byteam = defaultdict(list)
    for k, q in st.items():
        if q['bpm'] is not None and k in Z: byteam[k[1]].append(k)
    games = defaultdict(list)
    for (d, t), r in tg.items(): games[t].append(r)
    out = []
    for t, ks in byteam.items():
        core = [k for k in ks if st[k]['g'] >= 8 and st[k]['mpg'] >= 20]; rest = [k for k in ks if k not in core]; G = games[t]
        if len(core) < 3 or not rest or len(G) < 10: continue
        feat = lambda k: np.array([st[k]['bpm'], st[k]['gbpm'], 0, 0, 0, 0] + list(Z[k]))
        wr = np.array([st[k]['min'] for k in rest]); fr = np.average(np.array([feat(k) for k in rest]), axis=0, weights=wr)
        F = np.array([feat(k) - fr for k in core]); w = np.array([st[k]['mpg'] / 40 for k in core])
        L = np.array([(w * np.array([1.0 if r['d'] in st[k]['games'] else 0.0 for k in core])) @ F for r in G])
        ya = np.array([r['a'] for r in G]); n = len(G); c = n / (n - 1)
        X = (L - L.mean(axis=0)) * c; Y = (ya - ya.mean()) * c; keep = np.abs(X).max(axis=1) > 1e-9
        out.append(np.column_stack([Y[keep], np.zeros(keep.sum()), np.zeros(keep.sum()), X[keep]]))
    return np.vstack(out)


def split_rows(y):
    """who sat out, leak-free: ratings from half H (game BPM mean, BPM minus the other half's game-BPM share, box z of H),
    scored on the other half's games"""
    S = gl.season(y); st, tg = B[y]['st'], B[y]['tg']
    byteam = defaultdict(list)
    for k, q in st.items():
        if q['rot']: byteam[k[1]].append(k)
    games = defaultdict(list)
    for (d, t), r in tg.items(): games[t].append(r)
    rows = []
    for H in (0, 1):
        Z, _ = rates(st, H)
        for t, ks in byteam.items():
            kk = [k for k in ks if k in Z and st[k]['h'][H]['e'] >= 50]
            G = [r for r in games[t] if r['odd'] != (H == 0)]
            if len(kk) < 5 or len(G) < 5: continue
            F = []
            for k in kk:
                q = st[k]; h = q['h'][H]; pf = (q['h'][0]['gb'] + q['h'][1]['gb']) / q['e']; ph = h['gb'] / h['e']
                F.append([q['bpm'] - (pf - ph), ph, 0, 0, 0, 0] + list(Z[k]))
            F = np.array(F); w = np.array([st[k]['mpg'] for k in kk]); Lg = []
            for r in G:
                a = np.array([1.0 if r['d'] in st[k]['games'] else 0.0 for k in kk]); ww = w * a
                Lg.append((ww @ F) / ww.sum() if ww.sum() > 0 else np.full(F.shape[1], np.nan))
            Lg = np.array(Lg); ok = ~np.isnan(Lg[:, 0])
            if ok.sum() < 5: continue
            ya = np.array([r['a'] for r in G]); n = ok.sum(); c = n / (n - 1); Lm = Lg[ok].mean(axis=0)
            for i in np.where(ok)[0]:
                x = Lg[i] - Lm
                if np.abs(x).max() < 1e-9: continue
                rows.append(np.concatenate([[(ya[i] - ya[ok].mean()) * c, 0, 0], x * c]))
    return np.array(rows)


def table(RW, frozenA=None):
    none = {y: float((RW[y][:, 0] ** 2).sum()) for y in RW}; tot = sum(none.values()); res = {}
    sb, _ = loso(RW, 1.0, False); sg, _ = loso(RW, 0.0, False)
    res['BPM'] = round(1 - sum(sb.values()) / tot, 5); res['GBPM'] = round(1 - sum(sg.values()) / tot, 5)
    for a in AG:
        s1, _ = loso(RW, a, False); s2, f2 = loso(RW, a, True); e = {'base': round(1 - sum(s1.values()) / tot, 5), 'box': round(1 - sum(s2.values()) / tot, 5)}
        for nm, s in (('vsBPM', sb), ('vsGBPM', sg), ('vsBase', s1)):
            t, p, n = paired([s[y] - s2[y] for y in RW]); e[nm] = [t, n]
        if frozenA:
            s3, _ = loso(RW, a, True, frozen=frozenA[a]); e['frozenA'] = round(1 - sum(s3.values()) / tot, 5)
            for nm, s in (('frozen_vsBPM', sb), ('frozen_vsGBPM', sg), ('frozen_vsBase', s1)):
                t, p, n = paired([s[y] - s3[y] for y in RW]); e[nm] = [t, n]
        last = f2[max(f2)]; e['w'] = {c: round(float(v / last[0]), 2) for c, v in zip(CNT, last[1:])}; e['slope'] = round(float(last[0]), 3)
        res[f'a={a}'] = e
    return res


if __name__ == '__main__':
    out = {}
    out['A (all rotation absences)'] = table(RA); print(json.dumps(out['A (all rotation absences)']), flush=True)
    frozen = {a: loso(RA, a, True)[1] for a in AG}
    pickle.dump(frozen, open(os.path.join(gl.GB, 'frozenA.pkl'), 'wb'))
    RS = {y: strict_rows(y) for y in YEARS}
    # frozen A weights apply to mean-rating x; strict x is in team points (mpg/40 sums), so rescale: slope refit, weights d kept
    fz = {}
    for a in AG:
        fz[a] = {}
        for y in YEARS:
            b = frozen[a][y]; d = b[1:] / b[0]; tr = [s for s in YEARS if s != y]
            x = np.concatenate([base(RS[s], a) + RS[s][:, ZC] @ d for s in tr]); yy = np.concatenate([RS[s][:, 0] for s in tr]); sl = float(x @ yy / (x @ x))
            fz[a][y] = np.concatenate([[sl], sl * d])
    out['R1 starters only'] = table(RS, fz); print(json.dumps(out['R1 starters only']), flush=True)
    RSP = {y: split_rows(y) for y in YEARS}
    fz2 = {}
    for a in AG:
        fz2[a] = {}
        for y in YEARS:
            b = frozen[a][y]; d = b[1:] / b[0]; tr = [s for s in YEARS if s != y]
            x = np.concatenate([base(RSP[s], a) + RSP[s][:, ZC] @ d for s in tr]); yy = np.concatenate([RSP[s][:, 0] for s in tr]); sl = float(x @ yy / (x @ x))
            fz2[a][y] = np.concatenate([[sl], sl * d])
    out['R2b half-split (ratings from the other half)'] = table(RSP, fz2); print(json.dumps(out['R2b half-split (ratings from the other half)']), flush=True)
    json.dump(out, open(os.path.join(HERE, 'rxpm6.json'), 'w'), indent=1)
