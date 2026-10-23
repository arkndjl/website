#!/usr/bin/env python3
"""Research: players back from a lost season in the NFL priors (Oct 23 2026; the NBA's is PR #347).

    python3 scripts/nfl_returners_research.py      # numpy; writes data/nfl_returners_research.json

The offseason roster prior (scripts/nfl_roster.py) projects each player's WAR from his last two seasons (.49 x last
season + .21 x the one before, age, draft slot). A player who lost last season to injury enters on his few games
(about nothing) plus a fifth of his last healthy season. And the team sum treats him two ways: missed every game, he is
off last season's ledger and counts as a new arrival at that small projection; played a game or two, he cancels out
(last season's players are counted at their projection too), though the ratings never saw him.

Returner: on the week-1 roster, under GMAX games last season, GMIN+ games in one of the two seasons before (his last
healthy season, h). Variant 'ir' also needs IRMIN+ weeks on a reserve list last season (injured reserve, PUP, NFI,
designated to return: nflverse weekly rosters), so a benched or cut player isn't counted. Player projection, tested on
every week-1 roster player, tune 2015-20 / held out 2021-25 (walk-forward fits):
    base     the live projection
    shift    a returner's last healthy season and the one before it stand in for last season and the one before, with
             a returner flag and flag x WAR (the return discount, fit on earlier seasons); age is his age now, so the
             aging curve covers the lost year
Team: the roster prior on top of the live game model and the shipped prior (moves .25, half-life 8), each fixed share
picked on 2015-20 as in nfl_offseason_research.py:
    movesShift   moves with the shift projection (only returners who missed all of last season move)
    ret          returners on the team last season: shift projection minus the WAR he posted for it (the ratings
                 never saw him), its own share
The QB term carries a QB's career EPA line through a lost season (decayed .7 a season like everyone's), so a returning
starter is credited from week 1; the check here is whether returning QBs beat or miss the model (signed residual).

Results (Oct 23 2026, data/nfl_returners_research.json): nothing ships. Returners (under 6 games last season, 8+ in one
of the two before): ~105 a season. The live projection already has them right on average (2015-20 actual .064 WAR,
projected .062; 2021-25 .070 / .061); shift RMSE on them t -0.3 / +0.2, with the IR rule -0.1 / +0.3. Team terms all
fail tuning: moves on the shift projection 2015-20 MAE +.0044 (t +4.0), ret at every share and half-life t +0.7 to +1.8
(weeks 1-4 t +2 to +2.7), flat held out. Teams starting a returning QB (under 200 plays last season, 350+ before,
their first 8 games): -1.2 points against the model (t -1.2, n 138), not a fix.
"""
import json
import math
import os
import pickle
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N   # noqa: E402
from nfl_roster import team_ledger, rosters, pfeat, age, pick, RPOS, team_moves, ROSTER  # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nfl_returners_research.json')
FIRST, LAST = 2013, 2025
GMAX, GMIN, IRMIN = int(os.environ.get('GMAX', 6)), 8, 6
INJ = {'R01', 'R04', 'R05', 'R48', 'R27'}       # injured reserve, PUP, NFI, IR designated to return, IR (other)
TMP = os.environ.get('NFLRET_CACHE', os.path.join(N.CACHE, 'returners_v2.pkl'))


def reserve_weeks(y):
    """{gsis: weeks on an injury reserve list} in season y (regular season)."""
    w = defaultdict(set)
    for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
        # before 2020 the reserve rows carry no code (or A01); COVID (R59), suspensions and the like are coded after
        if r['game_type'] == 'REG' and r['gsis_id'] and r['status'] in ('RES', 'PUP') and r.get('status_description_abbr', '') in INJ | {'', 'A01'}:
            w[r['gsis_id']].add(r['week'])
    return {g: len(v) for g, v in w.items()}


def load():
    if os.path.exists(TMP):
        return pickle.load(open(TMP, 'rb'))
    L = {y: team_ledger(y) for y in range(FIRST, LAST + 1)}
    R = {y: rosters(y) for y in range(FIRST, LAST + 1)}
    IR = {y: reserve_weeks(y) for y in range(FIRST, LAST + 1)}
    pickle.dump((L, R, IR), open(TMP, 'wb'))
    return L, R, IR


def main():
    import numpy as np
    L, R, IR = load()
    pw = {y: defaultdict(float) for y in L}
    gpl = {y: defaultdict(int) for y in L}
    pos = {}
    for y, led in L.items():
        for (g, t), v in led.items():
            pw[y][g] += v[0]; gpl[y][g] += v[1]; pos[g] = v[2]

    def healthy(g, y, ir):
        """the returner's last healthy season before y, or None"""
        if gpl.get(y - 1, {}).get(g, 0) >= GMAX:
            return None
        if ir and IR.get(y - 1, {}).get(g, 0) < IRMIN:
            return None
        for h in (y - 2, y - 3):
            if gpl.get(h, {}).get(g, 0) >= GMIN:
                return h
        return None

    def rowsfor(y, mode, ir):
        X, ids, Y, rets = [], [], [], []
        for t, ros in R[y].items():
            for g, r in ros.items():
                ry = int(r['rookie_year']) if r.get('rookie_year', '').isdigit() else (int(r['entry_year']) if r.get('entry_year', '').isdigit() else y)
                rk = 1.0 if ry >= y else 0.0
                h = healthy(g, y, ir) if rk == 0 else None
                w1 = pw.get(y - 1, {}).get(g, 0.0); w2 = pw.get(y - 2, {}).get(g, 0.0)
                if mode == 'shift' and h:
                    w1, w2 = pw[h].get(g, 0.0), pw.get(h - 1, {}).get(g, 0.0)
                has2 = 1.0 if (y - 2) in pw else 0.0
                grp = pos.get(g) or RPOS.get(r['position'], 'DB')
                x = pfeat(w1, w2, has2, age(r, y), rk, y - ry, pick(r), grp, ROSTER['aging'])
                if mode == 'shift':
                    f = 1.0 if h else 0.0
                    x += [f, f * w1]
                X.append(x); ids.append(g); Y.append(pw[y].get(g, 0.0)); rets.append(h)
        return np.array(X), ids, np.array(Y), rets

    def project(mode, ir, lam_=5.0):
        PR = {y: rowsfor(y, mode, ir) for y in range(FIRST + 1, LAST + 1)}
        proj, err = {}, {}
        for y in range(FIRST + 1, LAST + 1):
            tr = [PR[k] for k in PR if k < y]
            X, ids, Y, _ = PR[y]
            if not tr:
                b = np.zeros(X.shape[1]); b[1] = 0.5
            else:
                Xt = np.vstack([t[0] for t in tr]); Yt = np.concatenate([t[2] for t in tr])
                lam = np.eye(Xt.shape[1]) * lam_; lam[0, 0] = 0
                b = np.linalg.solve(Xt.T @ Xt + lam, Xt.T @ Yt)
            p = X @ b
            proj[y] = dict(zip(ids, p))
            err[y] = (p - Y) ** 2
        Xa = np.vstack([PR[k][0] for k in PR]); Ya = np.concatenate([PR[k][2] for k in PR])
        lam = np.eye(Xa.shape[1]) * lam_; lam[0, 0] = 0
        return PR, proj, err, np.linalg.solve(Xa.T @ Xa + lam, Xa.T @ Ya)

    def tt(d):
        return round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2) if len(d) > 2 else None

    res = {'rule': {'gmax': GMAX, 'gmin': GMIN, 'irmin': IRMIN, 'reserveCodes': sorted(INJ)}, 'player': {}, 'team': {}}
    V = {'base': project('base', False)}
    for ir in (False, True):
        V[f'shift{"/ir" if ir else ""}'] = project('shift', ir)
    for key in ('shift', 'shift/ir'):
        ir = key.endswith('ir')
        out = {}
        for lab, ys in (('1520', range(2015, 2021)), ('2125', range(2021, LAST + 1))):
            e0 = np.concatenate([V['base'][2][y] for y in ys]); e1 = np.concatenate([V[key][2][y] for y in ys])
            isr = np.concatenate([[h is not None for h in V[key][0][y][3]] for y in ys])
            # returner rows: actual, base and shift projections
            act = np.concatenate([V[key][0][y][2] for y in ys])[isr]
            pb = np.concatenate([[V['base'][1][y][g] for g in V['base'][0][y][1]] for y in ys])[isr]
            ps = np.concatenate([[V[key][1][y][g] for g in V[key][0][y][1]] for y in ys])[isr]
            out[lab] = {'n': int(isr.sum()), 'rmseAll': [round(float(np.sqrt(e0.mean())), 4), round(float(np.sqrt(e1.mean())), 4)],
                        'tAll': tt(e1 - e0), 'rmseRet': [round(float(np.sqrt(e0[isr].mean())), 4), round(float(np.sqrt(e1[isr].mean())), 4)],
                        'tRet': tt(e1[isr] - e0[isr]), 'meanActual': round(float(act.mean()), 3), 'meanBase': round(float(pb.mean()), 3),
                        'meanShift': round(float(ps.mean()), 3)}
        b = V[key][3]
        out['coefAll'] = {'flag': round(float(b[-2]), 3), 'flag x WAR': round(float(b[-1]), 3), 'war1': round(float(b[1]), 3),
                          'war2': round(float(b[2]), 3)}
        res['player'][key] = out
        print('player', key, out, flush=True)

    # ---- game level: the live model and the shipped prior as the base
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(LAST)
    N.index_qbs(qbs, games); N.load_qb_teams(LAST)
    inj = N.injury_history(games, range(N.INJ_FIRST, LAST + 1))
    _, data = N.walk(games, box, qbs, params)
    gp = defaultdict(int)
    D = []
    for g, x, _ in data:
        s = int(g['season']); h, a = N.team(g['home_team']), N.team(g['away_team'])
        before = (gp[(s, h)], gp[(s, a)])
        if g['home_score'] not in ('', 'NA'):
            gp[(s, h)] += 1; gp[(s, a)] += 1
        if g['home_score'] in ('', 'NA') or s < 2012:
            continue
        x = dict(x)
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D.append((g, x, before))
    S = np.array([int(g['season']) for g, _, _ in D]); WK = np.array([int(g['week']) for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _, _ in D]); ok = ~np.isnan(line)
    XB = np.array([[x[f] for f in N.FEATS] for _, x, _ in D])

    def team_terms(key):
        """{(y, team): {'moves': .., 'ret': ..}} for a projection variant"""
        PR, proj = V[key][0], V[key][1]
        out = {}
        for yy in range(FIRST + 1, LAST + 1):
            T = team_moves(yy, L.get(yy - 1, {}), R[yy], proj[yy], pw.get(yy - 1, {}), pos)
            rets = {g for g, h in zip(PR[yy][1], PR[yy][3]) if h is not None}
            ret = defaultdict(float)
            if key != 'base':
                for t, ros in R[yy].items():
                    for g in ros:
                        if g in rets and pos.get(g) != 'QB' and (g, t) in L.get(yy - 1, {}):
                            ret[t] += proj[yy][g] - L[yy - 1][(g, t)][0]
            for t, v in T.items():
                out[(yy, t)] = {'moves': v['moves'], 'ret': ret.get(t, 0.0)}
        return out

    def feat(TQ, kind, hl):
        v = np.zeros(len(D))
        for i, (g, x, (nh, na)) in enumerate(D):
            s = int(g['season']); h, a = N.team(g['home_team']), N.team(g['away_team'])
            fh, fa = 0.5 ** (nh / hl), 0.5 ** (na / hl)
            if g['game_type'] != 'REG':
                fh = fa = 0.5 ** (17 / hl)
            v[i] = (fh * TQ.get((s, h), {}).get(kind, 0.0) - fa * TQ.get((s, a), {}).get(kind, 0.0)) * N.PTS_PER_WIN / 17
        return v

    pred = np.full(len(y), np.nan)
    for s in range(2015, LAST + 1):
        tr, te = S < s, S == s
        b = np.linalg.lstsq(XB[tr], y[tr], rcond=None)[0]; pred[te] = XB[te] @ b
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok
    blocks = {'all1520': A, 'all2125': B, 'wk1_4_1520': A & (WK <= 4), 'wk1_4_2125': B & (WK <= 4)}

    def cmp(e1, e0, k):
        d = e1[k] - e0[k]
        return [round(float(d.mean()), 4), tt(d), int(k.sum())]

    TB = team_terms('base')
    p0 = pred + ROSTER['c'] * feat(TB, 'moves', ROSTER['hl'])
    e0 = np.abs(p0 - y)
    res['team']['base'] = {k: round(float(e0[m].mean()), 4) for k, m in blocks.items()}
    for key in ('shift', 'shift/ir'):
        TQ = team_terms(key)
        nret = [v['ret'] for v in TQ.values() if v['ret']]
        res['team'][key] = {'teamsWithRet': len(nret), 'retMean': round(float(np.mean(nret)), 3) if nret else 0,
                            'retSd': round(float(np.std(nret)), 3) if nret else 0}
        mv = feat(TQ, 'moves', ROSTER['hl'])
        e = np.abs(pred + ROSTER['c'] * mv - y)
        res['team'][key]['movesShift'] = {k: cmp(e, e0, m) for k, m in blocks.items()}
        for hl in (4, 8, 17):
            rt = feat(TQ, 'ret', hl)
            for c in (0.1, 0.25, 0.5, 1.0):
                e = np.abs(pred + ROSTER['c'] * mv + c * rt - y)
                res['team'][key][f'movesShift+ret/hl{hl}/c{c}'] = {k: cmp(e, e0, m) for k, m in blocks.items()}
                e = np.abs(p0 + c * rt - y)
                res['team'][key][f'ret/hl{hl}/c{c}'] = {k: cmp(e, e0, m) for k, m in blocks.items()}
        print('team', key, json.dumps(res['team'][key]), flush=True)

    # ---- QB returners: the starting QB's plays last season vs his career; signed residual of the base model
    qplays = defaultdict(lambda: defaultdict(float))
    for (gid, gsis), q in qbs.items():
        qplays[int(gid[:4])][gsis] += q['plays']
    QR = []
    for i, (g, x, (nh, na)) in enumerate(D):
        s = int(g['season'])
        if s < 2015 or np.isnan(p0[i]):
            continue
        for side, q, n in ((1, g['home_qb_id'], nh), (-1, g['away_qb_id'], na)):
            if not q or n >= 8:
                continue
            last = qplays[s - 1].get(q, 0.0); before = max(qplays[s - 2].get(q, 0.0), qplays[s - 3].get(q, 0.0))
            if last < 200 and before >= 350:
                QR.append((s, side * (y[i] - p0[i])))
    if QR:
        r = np.array([v for _, v in QR]); ss = np.array([s for s, _ in QR])
        res['qbReturners'] = {lab: {'n': int(k.sum()), 'meanResid': round(float(r[k].mean()), 2), 't': tt(r[k])}
                              for lab, k in (('1520', ss <= 2020), ('2125', ss >= 2021), ('all', ss > 0))}
        print('qb returners', res['qbReturners'], flush=True)
    res['asof'] = __import__('datetime').date.today().isoformat()
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
