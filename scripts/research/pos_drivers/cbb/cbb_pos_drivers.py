#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Position-purpose FV drivers for the College Basketball ARKBOARD (Nov 2 2026, research only).

    python3 scripts/cbb_careers_kit.py                                    # once
    OMP_NUM_THREADS=1 python3 scripts/research/pos_drivers/cbb/cbb_pos_drivers.py [cand,...]
        -> scripts/research/pos_drivers/cbb/results.json

Each driver says how well a returner did the job his role exists for, from his PRIOR season (role = Barttorvik role
of that season; 2008-09 seasons have none, so height decides: <= 6-3 lead guard, >= 6-9 big, else wing). The value is
centred on the role's training mean and is 0 for other roles, so it adds a within-role slope, not a role dummy. Added
alone to the shipped returner kept set (data/cbb_fit.json, same rung penalties) and scored on cbb_fv_sweep2's gate:
2009-16 boards OOS rung deviance (college-class folds + two player splits, player-clustered t), then fit 2009-16 and
grade held 2017-19 boards (top 10/25/50, top-300 corr, horizon outcome) and forward 2020-23 boards.

PRE-REGISTERED (written before any outcome was read), at most 2 per role:
  lead guard (Pure PG, Scoring PG, Combo G): run the offense, create for others without wasting possessions, and bend
    the defence by getting downhill.
    g_create   AST% - TO% (both shrunk as cbb_fit.season_line)            creation net of waste
    g_press    (rim attempts + FTA) a 40, shrunk to 8 by 300 min (2010+)   rim pressure
  wing (Wing G, Wing F): space the floor and guard across positions (3-and-D).
    w_space    3PA/100 x (3P% - .33) x 3   3-point points over a .33 shooter per 100 possessions
    w_3d       z_role(w_space) + z_role(STL% + .5 BLK%)   both halves of 3-and-D
  big (Stretch 4, PF/C, C): protect the rim, end the opponent's possession, finish at the rim.
    b_protect  z_role(BLK%) + z_role(DRB%)   (BLK% = blocks per opponent 2PA on the floor)
    b_finish   (rim makes - .60 x rim attempts) a 40, shrunk by 300 min (2010+)   rim points over par
Exploratory variants (added after the primaries, counted in the test total) are listed in EXPLOR."""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..'))
import cbb_data as D
import cbb_fit as F
import cbb_fv_sweep2 as S

OUT = os.path.join(HERE, 'results.json')
R3 = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'W', 'Wing F': 'W', 'Stretch 4': 'B', 'PF/C': 'B', 'C': 'B'}
PRIMARY = ['g_create', 'g_press', 'w_space', 'w_3d', 'b_protect', 'b_finish']
EXPLOR = ['g_create_c', 'w_space_c', 'b_protect_c']   # career-pooled versions (one season's rates are noisy, 3P% most)
OWN = {'g_create': 'G', 'g_press': 'G', 'w_space': 'W', 'w_3d': 'W', 'b_protect': 'B', 'b_finish': 'B'}
BASE = ('g_create', 'g_press', 'w_space', 'stocks', 'blk', 'drb', 'b_finish')


def role(p, f):
    r = R3.get(p['role'])
    if r: return r
    h = p['hti'] or f['ht']
    return 'G' if h <= 75 else 'B' if h >= 81 else 'W'


def raw(c, i, f):
    p = c['seasons'][i - 1]
    mpt = max(1.0, (p['mp'] or 0) * (p['gp'] or 0))
    v = {}
    v['g_create'] = f['ast'] - f['to']
    rim_ok = p['year'] >= 2010 and p['rima'] is not None
    v['g_press'] = F.shrink(((p['rima'] or 0) + (p['fta'] or 0)) / mpt * 40, mpt, 8.0, 300) if rim_ok else None
    v['w_space'] = f['tpa100'] * (f['tp'] - 0.33) * 3
    v['stocks'] = f['stl'] + 0.5 * f['blk']
    v['blk'] = f['blk']; v['drb'] = f['drb']
    v['b_finish'] = F.shrink(((p['rimm'] or 0) - 0.60 * (p['rima'] or 0)) / mpt * 40, mpt, 0.0, 300) if rim_ok else None
    raw_extra(c, i, f, p, mpt, v)
    return role(p, f), v


def raw_extra(c, i, f, p, mpt, v):
    """inputs for exploratory variants: career-pooled (minutes-weighted over every prior season, shrunk as season_line)"""
    prev = c['seasons'][:i]
    W = [(r['mp'] or 0) * (r['gp'] or 0) for r in prev]; T = sum(W)
    def mw(k, prior, kk):
        num = sum(w * r[k] for w, r in zip(W, prev) if r[k] is not None); den = sum(w for w, r in zip(W, prev) if r[k] is not None)
        return F.shrink(num / den if den else None, den, prior, kk)
    v['g_create_c'] = mw('ast', 10, 300) - mw('to', 20, 300)
    tpm = sum(r['tpm'] or 0 for r in prev); tpa = sum(r['tpa'] or 0 for r in prev)
    tp = (tpm + 0.32 * 60) / (tpa + 60)
    v['w_space_c'] = mw('tpa100', 4, 300) * (tp - 0.33) * 3
    v['blk_c'] = mw('blk', 1.5, 400); v['drb_c'] = mw('drb', 13, 300)


def build(careers):
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    M = fitj['models']['returner']; F.TOP_MEAN = M['topMean']
    rows, hr = [], []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2009 <= s['year'] <= 2023) or i == 0: continue
            f = F.features(c, i)
            rl, v = raw(c, i, f)
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'], 'last': c['last'],
                 'cls': (c['last'] - 2009) % F.FOLDS, 'f': f, 'role': rl, 'v': v}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] >= 2017 and c['nba']['fvh'] is not None: hr.append(r)
    seen = {r['pid'] for r in rows}
    hr = [r for r in hr if r['pid'] not in seen]
    # role means / sds on training rows only (no outcome used)
    st = {}
    keys = sorted({k for r in rows for k in r['v']})
    for rl in 'GWB':
        for k in keys:
            x = np.array([r['v'][k] for r in rows if r['role'] == rl and r['v'].get(k) is not None], float)
            st[(rl, k)] = (float(x.mean()), float(x.std()) or 1.0) if len(x) else (0.0, 1.0)
    z = lambda r, k: (r['v'][k] - st[(r['role'], k)][0]) / st[(r['role'], k)][1]
    for r in rows + hr:
        f, rl, v = r['f'], r['role'], r['v']
        for k in ('g_create', 'g_press', 'w_space', 'b_finish'):
            own = OWN[k] == rl
            f[k] = (None if v[k] is None else v[k] - st[(rl, k)][0]) if own else 0.0
        f['w_3d'] = z(r, 'w_space') + z(r, 'stocks') if rl == 'W' else 0.0
        f['b_protect'] = z(r, 'blk') + z(r, 'drb') if rl == 'B' else 0.0
        extra_feats(r, z)
    return rows, hr, M


def extra_feats(r, z):
    """exploratory variants (added after primaries; counted in the total)"""
    f, rl = r['f'], r['role']
    f['g_create_c'] = z(r, 'g_create_c') if rl == 'G' else 0.0
    f['w_space_c'] = z(r, 'w_space_c') if rl == 'W' else 0.0
    f['b_protect_c'] = z(r, 'blk_c') + z(r, 'drb_c') if rl == 'B' else 0.0


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    rows, hr, M = build(careers)
    from collections import Counter
    print('rows', len(rows), 'held', sum(r['year'] <= 2019 for r in hr), 'fwd', sum(r['year'] >= 2020 for r in hr), Counter(r['role'] for r in rows))
    pick = sys.argv[1].split(',') if len(sys.argv) > 1 else PRIMARY
    res = json.load(open(OUT))['results'] if os.path.exists(OUT) else {}
    cvc, hc = {}, {}
    for cnd in pick:
        v = np.array([r['f'].get(cnd) if r['f'].get(cnd) is not None else np.nan for r in rows], float)
        on = v != 0
        nba = np.array([r['y'] >= 30 for r in rows])
        print(f'  {cnd}: on {int(on.sum())}, sd {np.nanstd(v[on]):.3f}, NBA {np.nanmean(v[on & nba]):+.3f} vs non {np.nanmean(v[on & ~nba]):+.3f}, missing {int(np.isnan(v).sum())}')
        a = S.cv(rows, M['kept'], M['lam'], cnd, cvc)
        b = S.held(rows, hr, M['kept'], M['lam'], cnd, hc)
        res[cnd] = {'cv': a, **b}
        print(cnd, json.dumps(res[cnd])); sys.stdout.flush()
        json.dump({'asof': '2026-11-02', 'results': res}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
