#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research: current-season BPM as a live CBB FV driver on top of the shipped in-season grade (pre-registered,
/mnt/project-files/cbb/audit-nov16/prereg.md, C family, Holm over 3 cuts). Needs scripts/.cache/cbb/careers.json
(scripts/cbb_careers_kit.py) and Barttorvik game logs (cbb_live_backtest.games).

    OMP_NUM_THREADS=1 python3 scripts/research/cbb_audit_nov16/fvbpm.py   # -> data/cbb_fvbpm_research.json
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import cbb_data as D
import cbb_fit as F
import cbb_live as L
import cbb_live_backtest as B

OUT = os.path.join(D.ROOT, 'data', 'cbb_fvbpm_research.json')
SEASONS = range(2010, 2020)
CUTS = [(12, 1), (1, 15), (2, 15)]
RAW = [i for i in range(23) if i not in (1, 2, 18, 19)]     # rx() without the adjusted per-game BPM terms


def fit_raw(seasons):
    X, Y, W = [], [], []
    for y in seasons:
        by_p, tg = B.load_season(y)
        off = {r['pid']: r for r in D.load_bt(y)}
        for pid, rs in by_p.items():
            o = off.get(pid)
            if not o or (o['mp'] or 0) * (o['gp'] or 0) < 40 or o['bpm'] is None: continue
            a = L.summed(rs, len(tg.get(rs[-1][L.C['team']], [])) or 1)
            X.append([L.rx(a)[i] for i in RAW]); Y.append(o['bpm']); W.append(min(1000.0, (o['mp'] or 0) * (o['gp'] or 0)))
    X, W = np.array(X, float), np.sqrt(np.array(W))
    b = np.linalg.lstsq(X * W[:, None], np.array(Y) * W, rcond=None)[0]
    return b, float(np.corrcoef(X @ b, Y)[0, 1])


def main():
    fit = json.load(open(F.OUT)); lf = json.load(open(L.LIVE_FIT))
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    F.horizon_fv(careers); F.set_context(careers)
    by_pid = {str(c['pid']): c for c in careers}
    recon = lf['recon']
    braw, rraw = fit_raw(list(SEASONS))
    print('raw recon r', round(rraw, 4), flush=True)
    rows = []
    for y in SEASONS:
        by_p, tg = B.load_season(y)
        full_games = np.median([len(v) for v in tg.values() if len(v) >= 10])
        cuts = [f'{y - 1 if m >= 11 else y}{m:02d}{d:02d}' for m, d in CUTS]
        for pid, rs in by_p.items():
            c = by_pid.get(pid)
            if not c or c['nba'].get('fvh') is None: continue
            i = next((j for j, s in enumerate(c['seasons']) if s['year'] == y), None)
            if i is None: continue
            meta = c['seasons'][i]
            srow = {k: meta.get(k) for k in ('year', 'team', 'conf', 'yr', 'hti', 'role', 'rec')}
            pre_cc = dict(c, seasons=c['seasons'][:i] + [srow])
            f_pre = F.features(pre_cc, i)
            for j, cut in enumerate(cuts):
                sub, tgd = B.to_date(rs, tg, cut)
                if not sub: continue
                a = L.summed(sub, max(1, tgd))
                n = a['mp'] * a['gp']
                if n <= 0: continue
                ln = L.line(a, recon, meta)
                gp_full = a['gp'] * full_games / max(1, tgd) if tgd < full_games else None
                rows.append({'y': y, 'cut': j, 'new': bool(f_pre['newcomer']), 'out': c['nba']['fvh'], 'n': n, 'f_pre': f_pre,
                             'f_now': F.features(L.next_career(pre_cc, ln, gp_full), i + 1),
                             'bpm': ln['bpm'], 'raw': float(np.array([L.rx(a)[k] for k in RAW]) @ braw)})
        print(y, len(rows), flush=True)
    e_pre = L.score_many([r['f_pre'] for r in rows], fit, ladder=True)[0]
    e_now = L.score_many([r['f_now'] for r in rows], fit, ladder=True)[0]
    NEW = np.array([r['new'] for r in rows]); N = np.array([r['n'] for r in rows]); YR = np.array([r['y'] for r in rows])
    CU = np.array([r['cut'] for r in rows]); Y = np.array([r['out'] for r in rows], float)
    k = np.where(NEW, lf['k']['newcomer'], lf['k']['returner']); kb = np.where(NEW, lf['kb']['newcomer']['k'], lf['kb']['returner']['k'])
    w = N / (N + k)
    E = (1 - w) * np.array(e_pre) + w * np.array(e_now)
    shr = N / (N + kb)
    xs = {'raw': shr * np.array([r['raw'] for r in rows]), 'adjusted': shr * np.array([r['bpm'] for r in rows])}
    out = {'n': len(rows), 'rawReconR': round(rraw, 4), 'cuts': {}}
    bars = [-2.13, -1.96, -1.645]
    for j, (m, d) in enumerate(CUTS):
        mk = CU == j
        res = {}
        for name in ('raw', 'adjusted'):
            x = xs[name]
            X0 = np.column_stack([np.ones(len(Y)), E]); X1 = np.column_stack([X0, x, x * NEW])
            e0, e1, sw = [], [], 0
            for s in SEASONS:
                tr, te = mk & (YR != s), mk & (YR == s)
                b0 = np.linalg.lstsq(X0[tr], Y[tr], rcond=None)[0]; b1 = np.linalg.lstsq(X1[tr], Y[tr], rcond=None)[0]
                a0 = (X0[te] @ b0 - Y[te]) ** 2; a1 = (X1[te] @ b1 - Y[te]) ** 2
                e0.append(a0); e1.append(a1); sw += a1.mean() < a0.mean()
            e0, e1 = np.concatenate(e0), np.concatenate(e1)
            dd = e1 - e0
            t = float(dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd))))
            bf = np.linalg.lstsq(X1[mk], Y[mk], rcond=None)[0]
            res[name] = {'n': int(mk.sum()), 'mse0': round(float(e0.mean()), 4), 'mse1': round(float(e1.mean()), 4), 't': round(t, 2),
                         'seasonsBetter': int(sw), 'coef': [round(float(v), 4) for v in bf[2:]]}
        out['cuts'][f'{m}/{d}'] = res
        print(f'{m}/{d}', res, flush=True)
    order = sorted(out['cuts'], key=lambda c: out['cuts'][c]['raw']['t'])
    alive = True
    for c, bar in zip(order, bars):
        r = out['cuts'][c]['raw']
        alive = alive and r['t'] <= bar and r['seasonsBetter'] >= 6
        r['pass'] = bool(alive)
    out['ship'] = all(out['cuts'][c]['raw']['pass'] for c in out['cuts'])
    json.dump(out, open(OUT, 'w'), indent=1)
    print('ship', out['ship'])


if __name__ == '__main__':
    main()
