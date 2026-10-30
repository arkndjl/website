#!/usr/bin/env python3
"""Historical comps for the College Basketball ARKBOARD (Oct 30 2026): each player's nearest preseason profiles among
the 2009-19 boards' players who had left college by 2020, with what they did in the NBA. Display only: the comps' mix
failed as an FV driver (scripts/cbb_comps_fv.py: returners t 0.6 class folds / 0.9 held out, newcomers t -2.1).

Profile (the board's preseason features, cbb_fit.features, z-scored on the pool, 4 SD clip), weights picked on held-out
classes by how well the comps' realized FV predicts (cbb_comps_fv.py):
  returners: last-season production (BPM, O/D BPM, 3-season BPM, PORPAG, D-PORPAG) 3, age and seasons played 3,
             recruiting rank 1, height (and for his role) .5, conference and minutes .5; style rates 0
  newcomers: recruiting rank 3, service grades 2, height 1, class 1
A comp is a player (his nearest season counts once). The mix is his 100 nearest players; the three shown are the
nearest who reached the NBA among his 300 nearest.

    python3 scripts/cbb_careers_kit.py && python3 scripts/cbb_comps.py --pool   # scripts/data/cbb_comps_pool.json.gz
    python3 scripts/cbb_comps.py        # static/data/cbb-comps.json for the frozen board (scripts/cbb_prior.json.gz)
"""
import gzip, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F

POOL = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_comps_pool.json.gz')
OUT = os.path.join(D.ROOT, 'static', 'data', 'cbb-comps.json')
GROUPS = {
    'returner': [(3.0, ['bpm', 'obpm', 'dbpm', 'bpm3', 'porpag', 'dporpag']), (3.0, ['age', 'nprev']), (1.0, ['rg_lrk']),
                 (0.5, ['ht', 'ht_g', 'big', 'guard']), (0.5, ['power', 'min_per'])],
    'newcomer': [(3.0, ['rg_lrk', 'top', 'top5']), (2.0, ['on3', 'r247', 'btrec']), (1.0, ['ht']), (1.0, ['yr'])],
}
K, NEAR = 100, 300


def cols_w(grp):
    cols, w = [], []
    for g, ks in GROUPS[grp]:
        cols += ks; w += [g / np.sqrt(len(ks))] * len(ks)
    return cols, np.array(w)


def build_pool():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    out = {'note': 'cbb_comps.py --pool', 'groups': {}}
    for grp in GROUPS:
        cols, w = cols_w(grp)
        rows = []
        for c in careers:
            if c['last'] > 2020: continue
            y = F.xpm_fv(c, thr)
            for i, s in enumerate(c['seasons']):
                if not 2009 <= s['year'] <= 2019: continue
                f = F.features(c, i)
                if f['newcomer'] != (grp == 'newcomer'): continue
                x = [f.get(k) for k in cols]
                rows.append([c['pid'], c['name'], s['team'], s['year'], s['yr'], round(y, 1), c['nba']['role'], c['nba']['pick'], c['nba']['draft'],
                             [None if v is None else round(float(v), 4) for v in x]])
        X = np.array([[np.nan if v is None else v for v in r[-1]] for r in rows], float)
        with np.errstate(all="ignore"): mu, sd = np.nan_to_num(np.nanmean(X, 0)), np.nanstd(X, 0)
        sd[~(sd > 0)] = 1   # a column no pool row has (Barttorvik recruit score for a newcomer) drops out
        out['groups'][grp] = {'cols': cols, 'w': w.round(4).tolist(), 'mu': mu.round(4).tolist(), 'sd': sd.round(4).tolist(),
                              'rowCols': ['pid', 'name', 'team', 'season', 'cls', 'fv', 'role', 'pick', 'draft', 'x'], 'rows': rows}
        print(grp, len(rows), 'pool rows')
    with gzip.open(POOL, 'wt') as fh: json.dump(out, fh, separators=(',', ':'))


def zw(X, g):
    return np.nan_to_num(np.clip((X - np.array(g['mu'])) / np.array(g['sd']), -4, 4)) * np.array(g['w'])


def comps(feats):
    """feats: [(key, feature dict)] -> {key: [[pool row, distance] x <=3, [n, NBA, starter 45+, All-Star 60+]]}, pool rows"""
    P = json.load(gzip.open(POOL))
    out, used = {}, {}
    shown = []
    for grp, g in P['groups'].items():
        rows = g['rows']
        Zp = zw(np.array([[np.nan if v is None else v for v in r[-1]] for r in rows], float), g)
        pid = np.array([r[0] for r in rows]); fv = np.array([r[5] for r in rows])
        q = [(k, f) for k, f in feats if f['newcomer'] == (grp == 'newcomer')]
        if not q: continue
        Zq = zw(np.array([[np.nan if f.get(c) is None else f[c] for c in g['cols']] for _, f in q], float), g)
        pn = (Zp ** 2).sum(1)
        for a in range(0, len(q), 500):
            d = (Zq[a:a + 500] ** 2).sum(1)[:, None] + pn[None, :] - 2 * Zq[a:a + 500] @ Zp.T
            d = np.sqrt(np.maximum(d, 0) / np.array(g['w']).sum())
            part = np.argpartition(d, NEAR * 3, 1)[:, :NEAR * 3]
            for j in range(len(part)):
                o = part[j][np.argsort(d[j, part[j]])]
                seen, near = set(), []
                for i in o:
                    if pid[i] in seen: continue
                    seen.add(pid[i]); near.append(i)
                    if len(near) == NEAR: break
                mix = near[:K]; y = fv[mix]
                nba = [i for i in near if fv[i] >= 30][:3]
                ent = []
                for i in nba:
                    key = (grp, int(i))
                    if key not in used: used[key] = len(shown); r = rows[i]; shown.append([r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]])
                    ent.append([used[key], round(float(d[j, i]), 2)])
                out[q[a + j][0]] = ent + [[len(mix), round(float((y >= 30).mean()), 3), round(float((y >= 45).mean()), 3), round(float((y >= 60).mean()), 3)]]
    return out, shown


def write(feats, path=OUT):
    if not os.path.exists(POOL): print('cbb comps: no pool (scripts/cbb_comps.py --pool)'); return
    out, shown = comps(feats)
    json.dump({'cols': ['name', 'team', 'season', 'cls', 'fv', 'role', 'pick', 'draft'], 'k': K, 'pool': shown, 'players': out},
              open(path, 'w'), separators=(',', ':'))
    print(f'cbb comps: {len(out)} players, {len(shown)} comps shown')


def from_prior():
    import cbb_live as L
    pr = json.load(gzip.open(L.PRIOR))
    ci = {c: j for j, c in enumerate(pr['cols'])}
    feats = []
    for row, m in zip(pr['rows'], pr['careers']):
        cc = {'pid': m['pid'], 'name': row[ci['name']], 'dob': m['dob'], 'rec': m['rec'], 'seasons': [dict(zip(pr['keep'], s)) for s in m['seasons']]}
        feats.append((row[ci['name']] + '|' + row[ci['team']], F.features(cc, len(cc['seasons']) - 1)))
    write(feats)


if __name__ == '__main__':
    build_pool() if '--pool' in sys.argv else from_prior()
