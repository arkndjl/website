#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CBB game-model research: the market-disagreement rating and three more pre-registered terms.

    python3 scripts/cbb_mdis_research.py [--only a1,a2,a3,a4]    # -> data/cbb_mdis_research.json

Pre-registration: /mnt/project-files/cbb/audit-nov13/prereg-games.md (sha256 in the output). Five tests, Holm at .05.
  A1 mdis  each team's running disagreement between the close and the shipped model's walk-forward margin (season
           start 0; after each day, e = (L - p0) - (d_home - d_away), both sides move .2 e). Input d_home - d_away
  A2 tdis  the same on totals (e = (T - t0) - (d_home + d_away))
  A3 era   the preseason-prior regression weighted .5 ^ (seasons back / 3)
  A4 lwj   two-point jump shots made over expected (ESPN play-by-play shot type) taken off the score at .5 before the
           efficiency solve, the constants of lw3
  A5 lwj   zero-sum: only the difference between the two sides' jumper luck comes off (the total is untouched;
           amendment 1, after A4 hurt totals: shot-type labels are a venue scorer's call and hit both sides alike)
Primary: held 2021-26, paired absolute error clustered by game day, lined D-I games (A3: every D-I game).
Pass: Holm p < .05, 2016-20 t <= -1.5 (A3: <= +1.5), 2025-26 change <= 0, every D-I game 2021-26 change <= 0.
Needs scripts/.cache/cbb/bpi (public_ratings.py --cbb-bpi or the saved cache) and, for A4, the play-by-play files
(scripts/.cache/edge/pbp/<season>.parquet, pulled here; pyarrow).
"""
import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import defaultdict

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cbb_games as C
import harness as H

OUT = os.path.join(C.ROOT, 'data', 'cbb_mdis_research.json')
PREREG = '/mnt/project-files/cbb/audit-nov13/prereg-games.md'
PBPD = os.path.join(HERE, '.cache', 'edge', 'pbp')
PBP = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_mens_college_basketball_pbp/play_by_play_{y}.parquet'
MK = 0.2
JS = {}


def jump_table(y):
    """game id -> {ESPN team id: [2-pt jumpers made, attempted]} from the season's ESPN play-by-play"""
    out = os.path.join(PBPD, f'jump_{y}.json.gz')
    if os.path.exists(out):
        return json.load(gzip.open(out))
    import pyarrow.parquet as pq
    p = os.path.join(PBPD, f'{y}.parquet')
    if not os.path.exists(p):
        os.makedirs(PBPD, exist_ok=True)
        subprocess.run(['curl', '-sL', '-m', '900', PBP.format(y=y), '-o', p], check=True)
    t = pq.read_table(p, columns=['game_id', 'type_text', 'team_id', 'scoring_play']).to_pandas()
    t = t[(t['type_text'] == 'JumpShot') & t['team_id'].notna()]
    res = defaultdict(dict)
    for (gid, tid), g in t.groupby(['game_id', 'team_id']):
        res[str(int(gid))][str(int(tid))] = [int(g['scoring_play'].sum()), int(len(g))]
    with gzip.open(out, 'wt') as f:
        json.dump(res, f, separators=(',', ':'))
    return res


def patch_era(hl=3.0):
    def prior_coef(self, s):
        if s in self.pcoef:
            return self.pcoef[s]
        R = [r for r in self.prior_rows if r[0] < s]
        if len({r[0] for r in R}) < 1:
            c = {k: 0.0 for k in C.PRIOR_F}; c['last'] = 0.6; c['one'] = -1.0
        else:
            Xp = np.array([[r[2][k] for k in C.PRIOR_F] for r in R]); y = np.array([r[3] for r in R])
            w = np.array([0.5 ** ((s - 1 - r[0]) / hl) for r in R])
            A = Xp.T @ (Xp * w[:, None]) + np.diag([0.0] + [5.0] * (len(C.PRIOR_F) - 1))
            c = dict(zip(C.PRIOR_F, np.linalg.solve(A, Xp.T @ (w * y))))
        self.pcoef[s] = c
        return c
    C.Walk.prior_coef = prior_coef


def patch_lwj(w=0.5, k=600.0, hl=30.0, zero_sum=False):
    orig = C.Walk.luck

    def luck(self, g, d):
        out, ln = orig(self, g, d)
        js = JS.get(g['season'], {}).get(str(g['id']))
        if not js or str(g['home']) not in js or str(g['away']) not in js:
            return out, ln
        st = self.__dict__.setdefault('jshot', defaultdict(lambda: [0.0, 0.0]))
        lg = self.__dict__.setdefault('lgj', [0.36, 1.0])
        if self.__dict__.get('jseason') != g['season']:
            self.jseason = g['season']
            for v in st.values():
                v[:] = [x * 0.5 for x in v]
        a = 0.5 ** (1 / hl)
        adj = []
        for t in (g['home'], g['away']):
            v = js[str(t)]
            s = st[t]
            x = (s[0] + k * lg[0] / lg[1]) / (s[1] + k)
            adj.append((1 - w) * 2 * (v[0] - v[1] * x))
        for t in (g['home'], g['away']):
            v = js[str(t)]
            s = st[t]
            s[:] = [s[0] * a + v[0], s[1] * a + v[1]]
            if v[1]:
                lg[0] = lg[0] * 0.999 + v[0] / v[1]; lg[1] = lg[1] * 0.999 + 1
        if zero_sum:
            adj = [(adj[0] - adj[1]) / 2, (adj[1] - adj[0]) / 2]
        return (out[0] + adj[0], out[1] + adj[1]), ln
    C.Walk.luck = luck


_A = {}


def _walk(kind):
    games, btname, d1s, tprior, avs, P, feats = _A['args']
    tfeats = C.TFEATS
    if kind in ('a6', 'base6'):          # on the model as shipped after A1 / A2
        feats, tfeats = feats + ['mdis'], C.TFEATS + ['tdis']
    if kind == 'a3':
        patch_era()
    if kind == 'a4':
        patch_lwj()
    if kind == 'a5':
        patch_lwj(zero_sum=True)
    if kind == 'a6':
        P = {**P, 'lgcar': 1.0}
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats, tfeats)
    r = {'pr': C.walk_pred(Xm, y, S, d1), 'tpr': C.walk_pred(TX, ty, S, d1), 'ids': [g['id'] for g, _, _ in D]}
    if kind in ('base', 'base6'):
        r.update(Xm=Xm, TX=TX, y=y, ty=ty, S=S, line=line, tline=tline, d1=d1,
                 meta=[(g['id'], C.et_date(g['date']), g['season'], g['home'], g['away']) for g, _, _ in D])
    return kind, r


def insample_first(Xm, y, S, d1, pr):
    """the first season has no earlier one to fit on: its own fit stands in (training rows only, never scored)"""
    p = pr.copy()
    k = np.isnan(p)
    if k.any():
        tr = (S == S[k].min()) & d1
        b = np.linalg.lstsq(Xm[tr], y[tr], rcond=None)[0]
        p[k] = Xm[k] @ b
    return p


def dis_col(meta, p0, line, sign, k=MK):
    """the running team disagreement input. sign -1: margin (home minus away), +1: total (home plus away)"""
    out = np.zeros(len(meta))
    by = defaultdict(lambda: defaultdict(list))
    for i, (_, day, s, _, _) in enumerate(meta):
        by[s][day].append(i)
    for s in sorted(by):
        d = defaultdict(float)
        for day in sorted(by[s]):
            for i in by[s][day]:
                out[i] = d[meta[i][3]] + sign * d[meta[i][4]]
            for i in by[s][day]:
                if line[i] != line[i] or p0[i] != p0[i]:
                    continue
                h, a = meta[i][3], meta[i][4]
                e = (line[i] - p0[i]) - (d[h] + sign * d[a])
                d[h] += k * e; d[a] += sign * k * e
    return out


def score(lab, pr, ref, y, line, S, d1, days, lined_primary=True):
    ok = ~np.isnan(pr) & ~np.isnan(ref) & d1
    has = ~np.isnan(line)
    r = {'label': lab}
    for nm, lo, hi in (('tune', 2016, 2020), ('held', 2021, 2026), ('post', 2025, 2026), ('h2124', 2021, 2024)):
        for sub, kk in (('all', ok), ('lined', ok & has)):
            k = kk & (S >= lo) & (S <= hi)
            e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
            p = H.paired(e, e0, cluster=days[k])
            r[f'{nm}_{sub}'] = {'n': int(k.sum()), 'base': round(float(e0.mean()), 4), 'mae': round(float(e.mean()), 4),
                                'd': round(p['d'], 4), 't': round(p['t'], 2), 'p': p['p']}
            if sub == 'lined':
                r[f'{nm}_{sub}']['close'] = round(float(np.abs(line[k] - y[k]).mean()), 4)
    r['bySeason'] = {}
    for s in range(2016, 2027):
        k = ok & has & (S == s)
        r['bySeason'][str(s)] = round(float(np.abs(pr[k] - y[k]).mean() - np.abs(ref[k] - y[k]).mean()), 4)
    prim = r['held_lined'] if lined_primary else r['held_all']
    r['primary'] = {'t': prim['t'], 'p': prim['p']}
    print(json.dumps({k: v for k, v in r.items() if k != 'bySeason'}), flush=True)
    return r


def main():
    only = None
    if '--only' in sys.argv:
        only = set(sys.argv[sys.argv.index('--only') + 1].split(','))
    want = lambda k: only is None or k in only
    fit = json.load(open(C.FIT))
    P = {**C.DEFAULT, **fit['params']}
    feats = [f for f in fit['feats'] if f != 'mdis']
    games, btname, d1s, tprior, avs = C.load_all()
    if not C.BPI:
        sys.exit('no BPI cache: restore scripts/.cache/cbb/bpi first')
    if want('a4') or want('a5'):
        for s in sorted({g['season'] for g in games}):
            try:
                JS[s] = jump_table(s)
            except Exception as e:
                print('pbp', s, 'missing:', e, flush=True)
        print('jump tables', {s: len(v) for s, v in JS.items()}, flush=True)
    _A['args'] = (games, btname, d1s, tprior, avs, P, feats)
    kinds = ['base'] + [k for k in ('a3', 'a4', 'a5', 'a6') if want(k)] + (['base6'] if want('a6') else [])
    import multiprocessing as mp
    with mp.get_context('fork').Pool(min(len(kinds), int(os.environ.get('PROCS', 4))), maxtasksperchild=1) as pool:
        res = dict(pool.map(_walk, kinds))
    b = res['base']
    y, ty, S, line, tline, d1 = b['y'], b['ty'], b['S'], b['line'], b['tline'], b['d1']
    days = np.array([m[1] for m in b['meta']])
    ok = ~np.isnan(b['pr']) & d1
    held = ok & (S > 2020) & ~np.isnan(line)
    print(f"base held lined MAE {np.abs(b['pr'][held] - y[held]).mean():.4f} close {np.abs(line[held] - y[held]).mean():.4f} (fit file: {fit.get('test')})"[:400], flush=True)
    tests = []
    if want('a1'):
        col = dis_col(b['meta'], insample_first(b['Xm'], y, S, d1, b['pr']), line, -1)
        X2 = np.column_stack([b['Xm'], col])
        pr = C.walk_pred(X2, y, S, d1)
        r = score('a1 mdis', pr, b['pr'], y, line, S, d1, days)
        tr = d1 & (S <= C.LAST)
        r['coef'] = round(float(np.linalg.lstsq(X2[tr], y[tr], rcond=None)[0][-1]), 4)
        r['passTune'] = r['tune_lined']['t'] <= -1.5
        tests.append(r)
    if want('a2'):
        col = dis_col(b['meta'], insample_first(b['TX'], ty, S, d1, b['tpr']), tline, +1)
        X2 = np.column_stack([b['TX'], col])
        tp = C.walk_pred(X2, ty, S, d1)
        r = score('a2 tdis', tp, b['tpr'], ty, tline, S, d1, days)
        tr = d1 & (S <= C.LAST)
        r['coef'] = round(float(np.linalg.lstsq(X2[tr], ty[tr], rcond=None)[0][-1]), 4)
        r['passTune'] = r['tune_lined']['t'] <= -1.5
        tests.append(r)
    for k, lab, lp in (('a3', 'a3 era prior', False), ('a4', 'a4 lwj', True), ('a5', 'a5 lwj zero-sum', True)):
        if k in res:
            assert res[k]['ids'] == b['ids']
            r = score(lab, res[k]['pr'], b['pr'], y, line, S, d1, days, lined_primary=lp)
            r['passTune'] = (r['tune_all']['t'] <= 1.5) if k == 'a3' else (r['tune_lined']['t'] <= -1.5)
            if k in ('a4', 'a5'):
                r['totals'] = score(lab + ' totals', res[k]['tpr'], b['tpr'], ty, tline, S, d1, days)
                r['passTotals'] = all(r['totals'][m]['d'] <= 0.003 and r['totals'][m]['t'] < 1 for m in ('held_lined', 'post_lined'))
            tests.append(r)
    if 'a6' in res:
        assert res['a6']['ids'] == b['ids']
        b6 = res['base6']
        r = score('a6 lgcar', res['a6']['pr'], b6['pr'], y, line, S, d1, days)
        r['totals'] = score('a6 lgcar totals', res['a6']['tpr'], b6['tpr'], ty, tline, S, d1, days)
        first = {}
        for s_, d_ in zip(S, days):
            first[s_] = min(first.get(s_, d_), d_)
        import datetime as dt
        early = np.array([(dt.date.fromisoformat(d_) - dt.date.fromisoformat(first[s_])).days < 3 for s_, d_ in zip(S, days)])
        ok6 = ~np.isnan(res['a6']['tpr']) & ~np.isnan(b6['tpr']) & d1 & early
        r['open3'] = {}
        for nm, lo, hi in (('tune', 2016, 2020), ('held', 2021, 2026)):
            for lab, new, old, yy, ln in (('total', res['a6']['tpr'], b6['tpr'], ty, tline), ('margin', res['a6']['pr'], b6['pr'], y, line)):
                k = ok6 & (S >= lo) & (S <= hi) & ~np.isnan(ln)
                p = H.paired(np.abs(new[k] - yy[k]), np.abs(old[k] - yy[k]))
                r['open3'][f'{nm}_{lab}'] = {'n': int(k.sum()), 'base': round(float(np.abs(old[k] - yy[k]).mean()), 4), 'd': round(p['d'], 4), 't': round(p['t'], 2), 'p': p['p'],
                                             'biasBase': round(float((old[k] - ln[k]).mean()), 2), 'bias': round(float((new[k] - ln[k]).mean()), 2)}
        print(json.dumps(r['open3']), flush=True)
        r['primary'] = {'t': r['open3']['held_total']['t'], 'p': r['open3']['held_total']['p']}
        r['passA6'] = bool(r['open3']['held_total']['t'] <= -2 and r['open3']['tune_total']['d'] <= 0 and r['held_lined']['d'] <= 0.001 and r['totals']['held_lined']['d'] <= 0.001)
        r['passTune'] = True
        tests.append(r)
    adj = H.holm([t['primary']['p'] for t in tests])
    for t, a in zip(tests, adj):
        t['holm'] = a
        t['pass'] = bool(a < 0.05 and t['passA6']) if 'passA6' in t else bool(a < 0.05 and t['passTune'] and t['post_lined']['d'] <= 0 and t['held_all']['d'] <= 0 and t.get('passTotals', True))
        print(t['label'], 'holm p', f'{a:.2g}', 'PASS' if t['pass'] else 'fail', flush=True)
    out = {'prereg': {'file': PREREG, 'sha256': hashlib.sha256(open(PREREG, 'rb').read()).hexdigest() if os.path.exists(PREREG) else None},
           'family': len(tests), 'tests': tests}
    if only is None or os.environ.get('MERGE'):
        if only is not None:
            old = json.load(open(OUT))
            out['tests'] = [t for t in old['tests'] if t['label'] not in {x['label'] for x in tests}] + tests
            for t in out['tests']:
                t.pop('holm', None)
            adj = H.holm([t['primary']['p'] for t in out['tests']])
            for t, a in zip(out['tests'], adj):
                t['holm'] = a
            out['family'] = len(out['tests'])
        with open(OUT, 'w') as f:
            json.dump(out, f, indent=1)
        print('wrote', OUT)


if __name__ == '__main__':
    main()
