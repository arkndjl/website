# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
#!/usr/bin/env python3
"""FV sweep Nov 9 2026, tests C1-C4 (research only; pre-registered in /mnt/project-files/fv/sweep-nov09/prereg.md).
Shot-creation stats from ESPN play-by-play, each offered on top of the kept returner ladder (data/cbb_fit.json).

    python3 scripts/cbb_careers_kit.py
    python3 scripts/research/fv_nov09/cbb_pbp_agg.py
    OMP_NUM_THREADS=1 python3 scripts/research/fv_nov09/cbb_pbp_test.py [out.json]

Drivers (the last college season before the board, like the ladder's other rate drivers; position = cbb_fit.ROLES of
that season, G / W / B):
  uarim  unassisted made layups + dunks + tips per 40 estimated minutes in the covered games, shrunk by those minutes
         (k 300, the ladder's rate shrink) to the position mean
  ua3    unassisted made threes per 40, the same way
  astd   assisted share of his made field goals, shrunk by makes (k 40) to the position mean
  estimated minutes = Barttorvik season minutes x covered team games / team games (no per-game minutes before 2010).
  Era: the files record fewer assists in 2008-11 (assisted share .44 against .52 from 2012), so every stat is shrunk
  to its own season's position mean and then moved by (all-season position mean - that season's position mean): each
  season's position mean is the same number. Missing (no pbp match) = that position mean; the flag pbp_miss is kept
  for the coverage table only, never offered.
Statistic: cbb_fv_sweep2.cv, class folds ('cls'): rung deviance gain, folds won, player-clustered t.
Gates: (a) 2009-16 boards out of fold (class folds), each board's top 25 / top 50 returners by E[FV]: mean realized FV
not lower; (b) forward: fit 2009-16, grade the 2017-20 boards (cbb_fv_drivers.forward's rows: careers over by 2022,
realized FV): rung deviance not higher and top 25 / top 50 not lower."""
import json, math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_data as D
import cbb_fit as F
import cbb_fv_drivers as H
import cbb_fv_sweep2 as S2
import harness as HS

OUT = next((a for a in sys.argv[1:] if not a.startswith('-')), os.path.join(HERE, 'cbb.json'))
K_MIN, K_FGM = 300, 40
STATS = ['uarim', 'ua3', 'astd']
TESTS = {'C1 uarim': 'uarim', 'C2 ua3': 'ua3', 'C3 astd': 'astd', 'C4 block': 'uarim+ua3+astd'}
S2.colset = lambda kept, cand: kept + cand.split('+')     # a block is offered as one candidate


def pbp_table(careers):
    """(pid, year) -> {uarim, ua3, astd} era-centred and shrunk; and the position means used for the missing"""
    P = {(r['pid'], r['year']): r for r in json.load(open(os.path.join(D.CACHE, 'pbp_shots.json')))['rows']}
    raw = {}; acc = defaultdict(lambda: np.zeros(5))
    for c in careers:
        for s in c['seasons']:
            p = P.get((c['pid'], s['year']))
            if not p or not p['cg']: continue
            mpt = (s['mp'] or 0) * (s['gp'] or 0)
            share = min(1.0, p['cg'] / (p['tg'] or s['gp'] or p['cg']))
            em = mpt * share
            if em <= 0: continue
            pos = F.ROLES.get(s['role'], 'W')
            raw[(c['pid'], s['year'])] = (pos, em, p)
            acc[(s['year'], pos)] += [em, p['uarim'], p['ua3'], p['fgm'], p['ast']]
    mean = {k: {'uarim': v[1] / v[0] * 40, 'ua3': v[2] / v[0] * 40, 'astd': v[4] / v[3]} for k, v in acc.items()}
    ref = {}
    for pos in 'GWB':
        v = sum(acc[(y, pos)] for y in range(2008, 2016))          # the seasons the 2009-16 boards read
        ref[pos] = {'uarim': v[1] / v[0] * 40, 'ua3': v[2] / v[0] * 40, 'astd': v[4] / v[3]}
    out = {}
    for (pid, y), (pos, em, p) in raw.items():
        m = mean[(y, pos)]
        o = {'uarim': F.shrink(p['uarim'] / em * 40, em, m['uarim'], K_MIN), 'ua3': F.shrink(p['ua3'] / em * 40, em, m['ua3'], K_MIN),
             'astd': F.shrink(p['ast'] / p['fgm'], p['fgm'], m['astd'], K_FGM)}
        out[(pid, y)] = {k: o[k] - m[k] + ref[pos][k] for k in STATS}
        out[(pid, y)].update(em=em, fgm=p['fgm'])
    return out, ref, mean, raw


def add(c, i, f, T, ref):
    p = c['seasons'][i - 1]
    pos = F.ROLES.get(p['role'], 'W')
    t = T.get((c['pid'], p['year']))
    for k in STATS: f[k] = t[k] if t else ref[pos][k]
    f['pbp_miss'] = 0.0 if t else 1.0
    mpt = max(1.0, f['mpt'])
    f['rim_rate'] = F.shrink((p['rima'] or 0) / mpt * 40, mpt, 3, 300) if p['year'] >= 2010 and p['rima'] is not None else None
    f['pos'] = pos
    return f


def tp(t, df):
    """exact one-sided p of Student t"""
    return float(1 - HS.t_cdf(t, df))


def clus_t(d, cl):
    g = defaultdict(float)
    for p, v in zip(cl, d): g[p] += v
    v = np.array(list(g.values()))
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), len(v)


def tops(rs, E, y, Ns=(25, 50)):
    yrs = np.array([r['year'] for r in rs]); out = {}
    for N in Ns:
        out[f'top{N}'] = [float(y[(ix := np.where(yrs == Y)[0])[np.argsort(-E[ix])[:N]]].mean()) for Y in sorted(set(yrs))]
    return out


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    F.set_context(careers)
    T, ref, mean, raw = pbp_table(careers)
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    M = fitj['models']['returner']; F.TOP_MEAN = M['topMean']
    kept, lam = list(M['kept']), M['lam']
    rows, fw = [], []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if i == 0 or not (2009 <= s['year'] <= 2020): continue
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'], 'last': c['last'],
                 'cls': (c['last'] - 2009) % F.FOLDS, 'f': add(c, i, F.features(c, i), T, ref)}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            if 2017 <= s['year'] <= 2020 and c['last'] <= 2022: fw.append(r)
    seen = {r['pid'] for r in rows}
    res = {'asof': '2026-11-09', 'kept': kept, 'lam': lam, 'rows': {'train': len(rows), 'forward': len(fw)},
           'pos_mean': ref, 'season_pos_mean': {f'{y}{p}': {k: round(v, 4) for k, v in m.items()} for (y, p), m in sorted(mean.items())}}
    print('rows', res['rows'], 'kept', kept, 'position means', ref)

    # ---- coverage ----
    cov = {}
    for Y in range(2009, 2021):
        rs = [r for r in (rows if Y <= 2016 else fw) if r['year'] == Y]
        have = np.array([1 - r['f']['pbp_miss'] for r in rs]); mp = np.array([r['f']['mpt'] for r in rs]); nba = np.array([r['y'] >= 30 for r in rs])
        em = np.array([T[(r['pid'], Y - 1)]['em'] if (r['pid'], Y - 1) in T else 0.0 for r in rs])
        cov[Y] = {'rows': len(rs), 'with_pbp': round(float(have.mean()), 3), 'with_pbp_300min': round(float(have[mp >= 300].mean()), 3),
                  'with_pbp_nba': round(float(have[nba].mean()), 3) if nba.any() else None,
                  'covered_minute_share': round(float(em.sum() / max(1.0, mp[have > 0].sum())), 3)}
        print('coverage', Y, cov[Y])
    res['coverage'] = cov

    # ---- sanity: pbp makes against Barttorvik makes x covered share ----
    a, b = [], []
    for c in careers:
        for s in c['seasons']:
            k = (c['pid'], s['year'])
            if k in raw and s['twopm'] is not None and s['tpm'] is not None:
                pos, em, p = raw[k]; mpt = (s['mp'] or 0) * (s['gp'] or 0)
                a.append(p['fgm']); b.append((s['twopm'] + s['tpm']) * em / mpt)
    res['sanity_fgm'] = {'n': len(a), 'corr': round(float(np.corrcoef(a, b)[0, 1]), 4), 'ratio': round(float(np.sum(a) / np.sum(b)), 4)}
    print('pbp makes vs Barttorvik makes x covered share', res['sanity_fgm'])

    # ---- base out of fold (class folds) ----
    y = np.array([r['y'] for r in rows], float); pid = [r['pid'] for r in rows]
    fo = np.array([r['cls'] for r in rows])
    X0 = F.matrix(rows, kept); P0 = H.oof(rows, X0, list(range(len(kept))), lam, fo, kept); E0 = F.expected(P0)
    T0 = tops(rows, E0, y)

    # ---- plain correlations ----
    cols = STATS + ['usg', 'ast', 'rim', 'rim_rate', 'tpa100', 'tp', 'ftr', 'bpm', 'obpm', 'porpag', 'big', 'guard', 'ht']
    V = F.matrix(rows, cols); have = np.array([r['f']['pbp_miss'] == 0 for r in rows])
    def cr(u, v, m=None):
        ok = ~np.isnan(u) & ~np.isnan(v) & (have if m is None else m)
        return round(float(np.corrcoef(u[ok], v[ok])[0, 1]), 3)
    corr = {}
    top = np.zeros(len(rows), bool)
    yrs = np.array([r['year'] for r in rows])
    for Y in sorted(set(yrs)):
        ix = np.where(yrs == Y)[0]; top[ix[np.argsort(-E0[ix])[:300]]] = True
    for j, s in enumerate(STATS):
        corr[s] = {'fv': cr(V[:, j], y), 'nba': cr(V[:, j], (y >= 30).astype(float)), 'fv_given_nba': cr(V[:, j], y, have & (y >= 30)),
                   'base_E_oof': cr(V[:, j], E0), 'resid_oof': cr(V[:, j], y - E0),
                   'fv_top300': cr(V[:, j], y, have & top), 'resid_top300': cr(V[:, j], y - E0, have & top),
                   'sd': round(float(np.std(V[have, j])), 4), **{k: cr(V[:, j], V[:, q]) for q, k in enumerate(cols) if k != s}}
        print('corr', s, corr[s])
    res['corr'] = corr; res['corr_rows'] = int(have.sum())

    # ---- forward base ----
    yf = np.array([r['y'] for r in fw], float)
    m0 = F.fit(rows, X0, list(range(len(kept))), lam)
    Pf0 = F.predict(m0, F.matrix(fw, kept))[1]; Ef0 = F.expected(Pf0); Tf0 = tops(fw, Ef0, yf)
    new = np.array([r['pid'] not in seen for r in fw])
    res['base'] = {'oof_top25': round(float(np.mean(T0['top25'])), 3), 'oof_top50': round(float(np.mean(T0['top50'])), 3),
                   'oof_dev': round(float(F.deviance(P0, y)), 5), 'fwd_dev': round(float(F.deviance(Pf0, yf)), 5),
                   'fwd_top25': round(float(np.mean(Tf0['top25'])), 3), 'fwd_top50': round(float(np.mean(Tf0['top50'])), 3),
                   'fwd_rmse': round(float(np.sqrt(((Ef0 - yf) ** 2).mean())), 4), 'fwd_unseen_rows': int(new.sum())}
    print('base', res['base'])

    cvc, hc = {}, {}
    hr = [r for r in fw if r['yh'] is not None and r['pid'] not in seen]     # S2.held: 'held' = 2017-19 (its 'fwd' slice, 2020 only here, is not read)
    res['tests'] = {}
    for name, cnd in TESTS.items():
        cols = kept + cnd.split('+')
        a = S2.cv(rows, kept, lam, cnd, cvc)
        X = F.matrix(rows, cols); idx = list(range(len(cols)))
        P1 = H.oof(rows, X, idx, lam, fo, cols); E1 = F.expected(P1); T1 = tops(rows, E1, y)
        d = (F.row_dev(P0, y) - F.row_dev(P1, y)).sum(1)
        t_pl, n_pl = clus_t(d, pid)
        t_cl, n_cl = clus_t(d, [r['last'] for r in rows])          # sensitivity: clustered by college class (last season)
        by_board = [float(d[yrs == Y].sum() * 100) for Y in sorted(set(yrs))]
        m1 = F.fit(rows, X, idx, lam)
        Pf1 = F.predict(m1, F.matrix(fw, cols))[1]; Ef1 = F.expected(Pf1); Tf1 = tops(fw, Ef1, yf)
        df = (F.row_dev(Pf0, yf) - F.row_dev(Pf1, yf)).sum(1)
        fyr = np.array([r['year'] for r in fw])
        o = {'cols': cnd.split('+'),
             'cv_cls': a['cls'], 'cv_md5': a['md5'], 'cv_salt': a['salt'],
             'gain': a['cls']['gain'], 't': a['cls']['t'], 'p_one_sided': tp(a['cls']['t'], n_pl - 1), 'clusters': n_pl, 'folds': f"{a['cls']['folds']}/{F.FOLDS}",
             't_class_clustered': round(t_cl, 2), 'p_class_clustered': tp(t_cl, n_cl - 1), 'classes': n_cl,
             'boards_won': f"{sum(x > 0 for x in by_board)}/{len(by_board)}", 'gain_by_board': [round(x, 3) for x in by_board],
             'oof_top25': [round(float(np.mean(T0['top25'])), 3), round(float(np.mean(T1['top25'])), 3), int(np.sum(np.array(T1['top25']) > np.array(T0['top25']))), int(np.sum(np.array(T1['top25']) < np.array(T0['top25'])))],
             'oof_top50': [round(float(np.mean(T0['top50'])), 3), round(float(np.mean(T1['top50'])), 3), int(np.sum(np.array(T1['top50']) > np.array(T0['top50']))), int(np.sum(np.array(T1['top50']) < np.array(T0['top50'])))],
             'fwd': {'gain': round(float(df.sum() * 100), 3), 't': round(clus_t(df, [r['pid'] for r in fw])[0], 2),
                     'boards_won': f"{sum(df[fyr == Y].sum() > 0 for Y in range(2017, 2021))}/4",
                     'gain_unseen': round(float(df[new].sum() * 100), 3),
                     'top25': [round(float(np.mean(Tf0['top25'])), 3), round(float(np.mean(Tf1['top25'])), 3)],
                     'top50': [round(float(np.mean(Tf0['top50'])), 3), round(float(np.mean(Tf1['top50'])), 3)],
                     'top25_by_board': [[round(u, 2), round(v, 2)] for u, v in zip(Tf0['top25'], Tf1['top25'])],
                     'top50_by_board': [[round(u, 2), round(v, 2)] for u, v in zip(Tf0['top50'], Tf1['top50'])],
                     'rmse': [round(float(np.sqrt(((Ef0 - yf) ** 2).mean())), 4), round(float(np.sqrt(((Ef1 - yf) ** 2).mean())), 4)]},
             'held_2017_19_horizon_unseen': S2.held(rows, hr, kept, lam, cnd, hc)['held'],
             'weights_z': {c: [round(float(w[1 + len(kept) + q]), 4) for w in m1['w']] for q, c in enumerate(cnd.split('+'))}}
        g_top = o['oof_top25'][1] >= o['oof_top25'][0] and o['oof_top50'][1] >= o['oof_top50'][0]
        g_fwd = o['fwd']['gain'] >= 0 and o['fwd']['top25'][1] >= o['fwd']['top25'][0] and o['fwd']['top50'][1] >= o['fwd']['top50'][0]
        o['gate_top'] = bool(g_top); o['gate_fwd'] = bool(g_fwd); o['gates'] = 'PASS' if g_top and g_fwd else 'FAIL'
        res['tests'][name] = o
        print(name, json.dumps(o)); sys.stdout.flush()
        json.dump(res, open(OUT, 'w'), indent=1)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
