#!/usr/bin/env python3
"""Personnel inputs (Nov 2 2026): the NFL game model and the receiving props.

    python3 scripts/nfl_personnel.py --research    # -> data/nfl_personnel_research.json (numpy; ~10 min warm)

A. Game model (the live walk-forward refit, nfl_games.fit's run(): OLS on the inputs, each season fit on the
   seasons before it). Candidates, home minus away, from nflverse participation 2016-25, games before kickoff only:
     pmatch   personnel matchup: the offense's grouping mix (usage, exponentially weighted by game at the live
              half-life, carried .7 over the summer) against how the opponent's defense does against each of those
              groupings relative to its overall EPA allowed (shrunk to its overall with 150 plays a grouping), and
              the reverse; EPA a play x 62 plays
     heavyxb  heavy-set rate (12, 13, 21, 22, jumbo) over the league times the opponent's base-defense deficit
              (league base rate minus its own): heavy offenses against light defenses
     pmatchP  pmatch from LAST season's full-season numbers only (what 2026 games could use: 2026 participation
              isn't published)
   Margin MAE, tune 2016-20, held 2021-25, paired by game, clustered by season-week. Gate: tune t <= -1.5 and held
   the same sign.
B. Props: route share. A receiver's share of his team's dropbacks with him on the field (participation, the free
   proxy for routes run; it counts a TE kept in to block as a route) less his share of all snaps, on the same
   short memory (half-life 1.5 games) and long memory (8 games) the fantasy model uses for snaps. Fit on the rows
   before each season: (y - mu) / mu on the two route terms, receptions and receiving yards, WR/TE/RB. Scored
   against the shipped props rule on the archived opening lines: 2024 tune, 2025 held (2026: no participation).
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import nfl_games as N  # noqa: E402
import nfl_personnel as NP  # noqa: E402

YEARS = range(2016, 2026)
HEAVY = ('12', '13', '21', '22', 'jumbo')
KG = 150.0


# ---------------------------------------------------------------- A. game model
def team_game(years=YEARS):
    """{(game_id, offense): {'u': {group: n}, 'e': {group: epa sum}, 'n': plays, 'base': base snaps, 'dn': def-group
    snaps}} with the defense's view read from the opponent's row"""
    out = defaultdict(lambda: {'u': defaultdict(float), 'e': defaultdict(float), 'n': 0.0, 'E': 0.0, 'base': 0.0, 'dn': 0.0})
    for y in years:
        for gid, wk, o, d, og, dg, epa, s, db, wp, ids in NP.plays(y):
            if og is None:
                continue
            A = out[(gid, o)]
            A['u'][og] += 1; A['e'][og] += epa; A['n'] += 1; A['E'] += epa
            if dg:
                A['dn'] += 1; A['base'] += dg == 'base'
    return out


class Mem:
    """exponentially weighted sums by team (per game decay a, summer carry)"""
    def __init__(self, a, carry):
        self.a, self.carry = a, carry
        self.v = defaultdict(lambda: defaultdict(float))

    def season(self):
        for t in self.v:
            for k in self.v[t]:
                self.v[t][k] *= self.carry

    def add(self, t, d):
        V = self.v[t]
        for k in list(V):
            V[k] *= self.a
        for k, x in d.items():
            V[k] += x


def matchup(off, dfn, lgE):
    """offense usage mix x (defense's EPA allowed in the grouping - its overall), groupings shrunk to the overall"""
    n = sum(off.get('u' + g, 0) for g in NP.GROUPS)
    if n < 30 or dfn.get('n', 0) < 30:
        return 0.0
    allow = dfn['E'] / dfn['n']
    tot = 0.0
    for g in NP.GROUPS:
        u = off.get('u' + g, 0) / n
        if not u:
            continue
        m = dfn.get('u' + g, 0)
        eg = (dfn.get('e' + g, 0) + allow * KG) / (m + KG)
        tot += u * (eg - allow)
    return tot * 62


def heavy_base(off, dfn, lg):
    n = sum(off.get('u' + g, 0) for g in NP.GROUPS)
    if n < 30 or dfn.get('dn', 0) < 30:
        return 0.0
    hv = sum(off.get('u' + g, 0) for g in HEAVY) / n
    return (hv - lg['heavy']) * (lg['base'] - dfn['base'] / dfn['dn'])


def game_candidates(games, params):
    TG = team_game()
    a = 0.5 ** (1 / params['hl'])
    O, Dm = Mem(a, params['carry']), Mem(a, params['carry'])          # offense usage/EPA; defense allowed by group
    season_tot = defaultdict(lambda: defaultdict(lambda: {'o': defaultdict(float), 'd': defaultdict(float)}))   # y -> team -> sums
    lg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])                     # y -> [heavy, plays, base, def plays]
    out = {}
    cur = None
    for g in games:
        y = int(g['season'])
        if y != cur:
            O.season(); Dm.season(); cur = y
        h, aw = N.team(g['home_team']), N.team(g['away_team'])
        L = lg[y] if lg[y][1] > 500 else lg[y - 1]
        lgd = {'heavy': L[0] / L[1] if L[1] else .4, 'base': L[2] / L[3] if L[3] else .25}
        x = {'pmatch': matchup(O.v[h], Dm.v[aw], None) - matchup(O.v[aw], Dm.v[h], None),
             'heavyxb': heavy_base(O.v[h], Dm.v[aw], lgd) - heavy_base(O.v[aw], Dm.v[h], lgd)}
        P = season_tot.get(y - 1)
        if P:
            x['pmatchP'] = matchup(P[h]['o'], P[aw]['d'], None) - matchup(P[aw]['o'], P[h]['d'], None)
        else:
            x['pmatchP'] = 0.0
        out[g['game_id']] = x
        if g['home_score'] in ('', 'NA'):
            continue
        for t, o in ((h, aw), (aw, h)):
            A = TG.get((g['game_id'], t))
            if not A:
                continue
            d_off = {'u' + k: v for k, v in A['u'].items()}
            d_off.update({'e' + k: v for k, v in A['e'].items()})
            d_off['n'] = A['n']; d_off['E'] = A['E']
            O.add(t, d_off)
            # what o's defense faced: t's offense groupings and EPA, and o's own packages
            d_def = dict(d_off); d_def['base'] = A['base']; d_def['dn'] = A['dn']
            Dm.add(o, d_def)
            for k, v in d_off.items():
                season_tot[y][t]['o'][k] += v
            for k, v in d_def.items():
                season_tot[y][o]['d'][k] += v
            lg[y][0] += sum(A['u'][k] for k in HEAVY); lg[y][1] += A['n']; lg[y][2] += A['base']; lg[y][3] += A['dn']
    return out


def game_test():
    last = 2025
    F = json.load(open(N.FIT))
    params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, params)
    cand = game_candidates(games, params)
    D = []
    for g, x, tx in data:
        if g['home_score'] in ('', 'NA') or int(g['season']) < 2012:
            continue
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        x = dict(x); x.update(cand.get(g['game_id'], {'pmatch': 0.0, 'heavyxb': 0.0, 'pmatchP': 0.0}))
        D.append((g, x))
    S = np.array([int(g['season']) for g, _ in D])
    wk = np.array([f"{g['season']}-{g['week']}" for g, _ in D])
    y = np.array([N.num(g['result']) for g, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D])
    A = (S >= 2016) & (S <= 2020); B = S >= 2021

    def wf(feats):
        X = np.array([[x[f] for f in feats] for _, x in D])
        pred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        return np.abs(pred - y), pred, dict(zip(feats, np.linalg.lstsq(X, y, rcond=None)[0]))
    base = list(N.FEATS)
    e0, p0, _ = wf(base)
    res = {'base': {'feats': base, 'mae1620': round(float(e0[A].mean()), 4), 'mae2125': round(float(e0[B].mean()), 4),
                    'line2125': round(float(np.nanmean(np.abs(line[B] - y[B]))), 4)}}
    for k in ('pmatch', 'heavyxb', 'pmatchP'):
        e1, p1, b = wf(base + [k])
        ta = H.paired(e1[A], e0[A], wk[A]); tb = H.paired(e1[B], e0[B], wk[B])
        # does it explain the result beyond the close? (residual on the term, held)
        xv = np.array([x[k] for _, x in D])
        ok = B & ~np.isnan(line)
        rc = np.polyfit(xv[ok], (y - line)[ok], 1)[0] if xv[ok].std() > 0 else 0.0
        res[k] = {'coef': round(float(b[k]), 3), 'sd': round(float(xv[S >= 2017].std()), 3),
                  'tune1620': {'d': round(ta['d'], 4), 't': round(ta['t'], 2)}, 'held2125': {'d': round(tb['d'], 4), 't': round(tb['t'], 2)},
                  'slopeVsClose2125': round(float(rc), 3),
                  'pass': bool(ta['t'] <= -1.5 and tb['d'] < 0)}
        print(k, res[k], flush=True)
    return res


# ---------------------------------------------------------------- B. route share on the props
def route_rows(years=YEARS):
    """{(season, week, gsis): (route share short, long, snap share short, long)} before each game"""
    out = {}
    for y in years:
        team_db = defaultdict(lambda: [0, 0])                    # (gid, team) -> [dropbacks, plays]
        pl = defaultdict(lambda: [0, 0])                         # (gid, team, pid) -> [on dropbacks, on plays]
        order = {}
        for gid, wk, o, d, og, dg, epa, s, db, wp, ids in NP.plays(y):
            if not ids:
                continue
            order[(gid, o)] = wk
            team_db[(gid, o)][0] += db; team_db[(gid, o)][1] += 1
            for p in ids:
                pl[(gid, o, p)][0] += db; pl[(gid, o, p)][1] += 1
        by_player = defaultdict(list)                            # pid -> [(week, team, route share, snap share)]
        for (gid, t, p), (rdb, rpl) in pl.items():
            tdb, tpl = team_db[(gid, t)]
            if tdb and tpl:
                by_player[p].append((order[(gid, t)], rdb / tdb, rpl / tpl))
        for p, v in by_player.items():
            v.sort()
            fs = fl = ss = sl = None
            af, al = 0.5 ** (1 / 1.5), 0.5 ** (1 / 8)
            for wk, rs, sn in v:
                if fs is not None:
                    out[(y, wk, p)] = (fs[0] / fs[1], fl[0] / fl[1], ss[0] / ss[1], sl[0] / sl[1])
                fs = (rs + (fs[0] * af if fs else 0), 1 + (fs[1] * af if fs else 0))
                fl = (rs + (fl[0] * al if fl else 0), 1 + (fl[1] * al if fl else 0))
                ss = (sn + (ss[0] * af if ss else 0), 1 + (ss[1] * af if ss else 0))
                sl = (sn + (sl[0] * al if sl else 0), 1 + (sl[1] * al if sl else 0))
    return out


def props_test():
    import nfl_props_research as R
    rows = R.build_rows()
    rr = route_rows()
    n = len(rows['s'])
    X = np.zeros((n, 2)); has = np.zeros(n, bool)
    for i in range(n):
        v = rr.get((int(rows['s'][i]), int(rows['w'][i]), rows['id'][i]))
        if v and rows['pos'][i] in ('WR', 'TE', 'RB'):
            X[i] = (v[0] - v[2], v[1] - v[3]); has[i] = True
    S = rows['s']
    res = {'coverage': {str(s): round(float(has[(S == s) & np.isin(rows['pos'], ['WR', 'TE', 'RB'])].mean()), 3) for s in range(2016, 2027)}}
    adj = {}
    for ver in ('wed', 'full'):
        for st in ('rc', 'wy'):
            mu = rows[f'{ver}_{st}'].astype(float); y = rows['y_' + st].astype(float)
            new = mu.copy()
            coefs = {}
            for s in range(2017, 2027):
                tr = (S < s) & (S >= 2016) & has & (mu > .5)
                te = (S == s) & has & (mu > .5)
                if tr.sum() < 1000 or not te.any():
                    continue
                Z = X[tr]; r = (y[tr] - mu[tr]) / mu[tr]
                w = mu[tr]                                        # weight the relative error by volume
                b = np.linalg.solve((Z * w[:, None]).T @ Z + 1e-3 * np.eye(2), (Z * w[:, None]).T @ r)
                new[te] = mu[te] * (1 + X[te] @ b)
                coefs[str(s)] = [round(float(c), 3) for c in b]
            adj[(ver, st)] = new
            for name, ss in (('tune2024', (2024,)), ('held2025', (2025,)), ('fit2017_23', tuple(range(2017, 2024)))):
                k = np.isin(S, ss) & has & (mu > .5)
                pr = H.paired(np.abs(new[k] - y[k]), np.abs(mu[k] - y[k]))
                res.setdefault('mae', {})[f'{ver} {st} {name}'] = {'n': int(k.sum()), 'mae0': round(float(np.abs(mu[k] - y[k]).mean()), 4),
                                                                   'd': round(pr['d'], 4), 't': round(pr['t'], 2)}
            res.setdefault('coef', {})[f'{ver} {st}'] = coefs
    print(json.dumps(res['mae'], indent=0), flush=True)
    # the props rule with the adjusted means (receptions and receiving yards; other stats unchanged)
    ix = {(int(s), int(w), i): k for k, (s, w, i) in enumerate(zip(rows['s'], rows['w'], rows['id']))}
    g2 = {str(r[0]): (int(r[1]), int(r[2])) for r in rows['g2']}
    a2 = {str(r[0]): r[1] for r in rows['a2']}
    O = json.load(gzip.open(R.OPENS, 'rt'))
    out = {}
    for ver in ('wed', 'full'):
        alt = {k: (rows[k] if k[len(ver) + 1:] not in ('rc', 'wy') else adj[(ver, k[len(ver) + 1:])]) for k in rows if k.startswith(ver + '_')}
        rows2 = dict(rows); rows2.update(alt)
        sh0, sh1 = R.shape(rows, ver), R.shape(rows2, ver)
        cmp_ = {}
        for tag, rw, sh in (('base', rows, sh0), ('route', rows2, sh1)):
            bets = defaultdict(list)
            for gid, g in O.items():
                sw = g2.get(gid)
                if not sw or sw[0] not in (2024, 2025):
                    continue
                for a, st, Lr in g['props']:
                    if st not in ('rc', 'wy'):
                        continue
                    gs = a2.get(a); k = ix.get((sw[0], sw[1], gs)) if gs else None
                    if k is None or not has[k]:
                        continue
                    yv = rows['y_' + st][k]
                    if yv == Lr:
                        continue
                    p = R.p_over(sh, st, float(rw[f'{ver}_{st}'][k]), Lr)
                    if p is None:
                        continue
                    bets[sw[0]].append((gid, p, float(yv > Lr)))
            for s, bb in bets.items():
                p = np.array([b[1] for b in bb]); yy = np.array([b[2] for b in bb]); cl = np.array([b[0] for b in bb])
                cmp_.setdefault(str(s), {})[tag] = (p, yy, cl)
        for s, v in cmp_.items():
            pb, yb, cl = v['base']; pr_, yr, _ = v['route']
            br = H.paired((pr_ - yr) ** 2, (pb - yb) ** 2, cl)
            ps = 0.60
            def roi(p, yy):
                sel = (p >= ps) | (1 - p >= ps)
                win = np.where(p >= ps, yy, 1 - yy)[sel]
                return {'n': int(sel.sum()), 'hit': round(float(win.mean()), 4) if sel.any() else None}
            out[f'{ver} {s}'] = {'n': int(len(yb)), 'brierBase': round(float(((pb - yb) ** 2).mean()), 5),
                                 'brierRoute': round(float(((pr_ - yr) ** 2).mean()), 5), 'd': round(br['d'], 5), 't': round(br['t'], 2),
                                 'bets60Base': roi(pb, yb), 'bets60Route': roi(pr_, yr)}
            print(ver, s, out[f'{ver} {s}'], flush=True)
    res['props'] = out
    return res


def main():
    res = {'updated': __import__('datetime').date.today().isoformat()}
    if '--props' in sys.argv and os.path.exists(NP.RES):      # props part only, keeping the game part on file
        res = json.load(open(NP.RES))
    else:
        res['game'] = game_test()
    res['props'] = props_test()
    res['cfb'] = 'no free college personnel or participation source: CFBD has no on-field personnel, ESPN college play-by-play has none, PFN snap counts are per player-game'
    with open(NP.RES, 'w') as f:
        json.dump(res, f, indent=1, allow_nan=False)
    print('wrote', NP.RES)


if __name__ == '__main__':
    main()
