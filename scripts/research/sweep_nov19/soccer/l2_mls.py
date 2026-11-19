# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""L2: do ASA goals-added action types carry MLS team goal difference beyond xG + xA + keeper lines? Last season's
shrunk per-90 rates at this season's minutes -> team goal difference a match, ridge. Prereg:
/mnt/project-files/research-sweep-nov19/impl/soccer/prereg.md.

    python3 scripts/research/sweep_nov19/soccer/l2_mls.py <asa dir>
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

OUT = os.environ.get('SWEEP_OUT', '/home/user/scratch-soccer')
GRP = {'GK': 'GK', 'CB': 'D', 'FB': 'D', 'DM': 'M', 'CM': 'M', 'AM': 'M', 'W': 'F', 'ST': 'F'}
GA = {'Passing': 'pas', 'Receiving': 'rec', 'Interrupting': 'int', 'Dribbling': 'dri', 'Fouling': 'fou', 'Shooting': 'sho'}
NULL = ['xg', 'xa', 'gk']
CAND = NULL + ['pas', 'rec', 'int', 'dri', 'fou']
ALL = ['xg', 'xa', 'gk', 'pas', 'rec', 'int', 'dri', 'fou', 'sho']
LAMS = (0.3, 1.0, 3.0, 10.0)
SHRINK = 300


def load(dr, S0=2013, S1=2025):
    rows, ts = [], {}
    for S in range(S0, S1 + 1):
        P = defaultdict(lambda: defaultdict(float))
        pos = {}
        for x in json.load(open(os.path.join(dr, f'ga_{S}.json'))):
            k = (x['player_id'], x['team_id'] if isinstance(x['team_id'], str) else tuple(x['team_id']))
            P[k]['min'] = x.get('minutes_played') or 0
            pos[k] = x.get('general_position')
            for a in x['data']:
                P[k][GA[a['action_type']]] = a['goals_added_raw'] or 0.0
                P[k]['aa_' + GA[a['action_type']]] = a['goals_added_above_avg'] or 0.0
        for x in json.load(open(os.path.join(dr, f'xg_{S}.json'))):
            k = (x['player_id'], x['team_id'] if isinstance(x['team_id'], str) else tuple(x['team_id']))
            P[k]['min'] = max(P[k]['min'], x.get('minutes_played') or 0)
            pos.setdefault(k, x.get('general_position'))
            P[k]['xg'] = x.get('xgoals') or 0.0
            P[k]['xa'] = x.get('xassists') or 0.0
            P[k]['g'] = x.get('goals') or 0
            P[k]['a'] = x.get('primary_assists') or 0
        for x in json.load(open(os.path.join(dr, f'gkx_{S}.json'))):
            k = (x['player_id'], x['team_id'] if isinstance(x['team_id'], str) else tuple(x['team_id']))
            P[k]['min'] = max(P[k]['min'], x.get('minutes_played') or 0)
            pos[k] = 'GK'
            P[k]['gk'] = -(x.get('goals_minus_xgoals_gk') or 0.0)
            P[k]['sf'] = x.get('shots_faced') or 0
            P[k]['gc'] = x.get('goals_conceded') or 0
            P[k]['xgf'] = x.get('xgoals_gk_faced') or 0.0
        for (p, t), v in P.items():
            if v['min'] > 0 and isinstance(t, str):
                rows.append(dict(v, p=p, tid=t, S=S, pos=GRP.get(pos.get((p, t)) or '', 'M'), gp=pos.get((p, t))))
        T = defaultdict(lambda: [0, 0])
        for g in json.load(open(os.path.join(dr, f'games_{S}.json'))):
            if g.get('knockout_game') or g.get('home_score') is None or g.get('status') not in ('FullTime', None):
                continue
            d = g['home_score'] - g['away_score']
            T[g['home_team_id']][0] += 1; T[g['home_team_id']][1] += d
            T[g['away_team_id']][0] += 1; T[g['away_team_id']][1] -= d
        for t, (mp, gd) in T.items():
            ts[(S, t)] = {'mp': mp, 'gd': gd}
    return rows, ts


def rates(rows, shrink=SHRINK):
    by = defaultdict(list)
    for r in rows:
        by[r['S']].append(r)
    for rs in by.values():
        tot = sum(r['min'] for r in rs) or 1
        for k in ALL:
            for r in rs:
                r['_' + k] = r.get(k, 0.0) / max(r['min'], 1) * 90
            mu = sum(r['_' + k] * r['min'] for r in rs) / tot
            for r in rs:
                r['_' + k] -= mu
            for pos in ('GK', 'D', 'M', 'F'):
                ps = [r for r in rs if r['pos'] == pos]
                pm = sum(r['min'] for r in ps) or 1
                pmu = sum(r['_' + k] * r['min'] for r in ps) / pm
                for r in ps:
                    w = r['min'] / (r['min'] + shrink)
                    r['r_' + k] = w * r['_' + k] + (1 - w) * pmu
    return rows


def pooled(rows):
    """(player, season) -> his rates over every team that season (minutes-weighted)"""
    acc = defaultdict(lambda: defaultdict(float))
    for r in rows:
        e = acc[(r['p'], r['S'])]
        e['min'] += r['min']
        for k in ALL:
            e[k] += r['r_' + k] * r['min']
    return {k: dict({a: v[a] / v['min'] for a in ALL}, min=v['min']) for k, v in acc.items()}


def design(rows, ts, feats, prior=True):
    PR = pooled(rows)
    X = defaultdict(lambda: np.zeros(len(feats)))
    has = set()
    for r in rows:
        k = (r['S'], r['tid'])
        if k not in ts:
            continue
        share = r['min'] / (90 * ts[k]['mp'])
        if prior:
            q = PR.get((r['p'], r['S'] - 1))
            if not q or q['min'] < 300:
                continue
            v = np.array([q[f_] for f_ in feats])
            has.add(k)
        else:
            v = np.array([r['r_' + f_] for f_ in feats])
            has.add(k)
        X[k] += share * v
    ks = sorted(has)
    Xm = np.array([X[k] for k in ks]); y = np.array([ts[k]['gd'] / ts[k]['mp'] for k in ks])
    for S in {k[0] for k in ks}:
        i = [j for j, k in enumerate(ks) if k[0] == S]
        Xm[i] -= Xm[i].mean(0); y[i] -= y[i].mean()
    return ks, Xm, y


def ridge(X, y, lam):
    sd = X.std(0) + 1e-12
    Z = X / sd
    return np.linalg.solve(Z.T @ Z + lam * np.eye(X.shape[1]), Z.T @ y) / sd


def loso(S, X, y, lam, only=None):
    p = np.full(len(y), np.nan)
    for s in np.unique(S):
        if only is not None and s not in only:
            continue
        tr = S != s
        p[S == s] = X[S == s] @ ridge(X[tr], y[tr], lam)
    return p


def tstat(d, keys):
    m = sum(d) / len(d)
    gs = defaultdict(float)
    for x, k in zip(d, keys):
        gs[k] += x - m
    se = math.sqrt(sum(v * v for v in gs.values())) / len(d)
    return m, (m / se if se else 0.0)


def main():
    rows, ts = load(sys.argv[1])
    rates(rows)
    res = {}
    D_ = {}
    for name, fs in (('null', NULL), ('cand', CAND)):
        ks, X, y = design(rows, ts, fs)
        S = np.array([k[0] for k in ks])
        tune = S <= 2021
        lam = min(LAMS, key=lambda l: float(np.mean((y[tune] - loso(S[tune], X[tune], y[tune], l)) ** 2)))
        pt = loso(S[tune], X[tune], y[tune], lam)
        ph = loso(S, X, y, lam, only=(2022, 2023, 2024, 2025))
        D_[name] = (ks, S, y, pt, ph, tune)
        res[name] = {'lam': lam, 'n': len(ks), 'tuneMse': round(float(np.mean((y[tune] - pt) ** 2)), 5),
                     'heldMse': round(float(np.nanmean((y[~tune] - ph[~tune]) ** 2)), 5),
                     'varTune': round(float(np.mean(y[tune] ** 2)), 5), 'varHeld': round(float(np.mean(y[~tune] ** 2)), 5),
                     'w': {a: round(float(b), 4) for a, b in zip(fs, ridge(X, y, lam))}}
    ks, S, y, pt0, ph0, tune = D_['null']
    assert D_['cand'][0] == ks
    _, _, _, pt1, ph1, _ = D_['cand']
    dt_ = (y[tune] - pt1) ** 2 - (y[tune] - pt0) ** 2
    dh = (y[~tune] - ph1[~tune]) ** 2 - (y[~tune] - ph0[~tune]) ** 2
    m, t = tstat(list(dt_), list(S[tune]))
    res['tune'] = {'n': int(tune.sum()), 'd': round(m, 6), 't': round(t, 2)}
    m, t = tstat(list(dh), list(S[~tune]))
    m2, t2 = tstat(list(dh), list(range(len(dh))))
    by = {int(s): round(float(dh[S[~tune] == s].mean()), 5) for s in np.unique(S[~tune])}
    res['held'] = {'n': int((~tune).sum()), 'd': round(m, 6), 't': round(t, 2), 'tTeamSeason': round(t2, 2), 'bySeason': by,
                   'seasonsBetter': sum(1 for v in by.values() if v < 0)}
    json.dump(res, open(os.path.join(OUT, 'l2_mls.json'), 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
