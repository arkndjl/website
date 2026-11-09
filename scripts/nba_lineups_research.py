#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Research (Nov 2 2026): ESPN lineup stints (scripts/nba_lineups.py) as NBA player-value and game-model inputs.

    python3 scripts/nba_lineups_research.py --team        # (a) team-season forward test of prior on/off in player values
    python3 scripts/nba_lineups_research.py --games [--only 0,3]   # (a)-(d) on the shipped game model
    -> data/nba_lineups_research.json (each run merges its section)

Every test is walk-forward: an input for game g uses only stints of games before g (in-season) or of earlier seasons.
(a) prior on/off: each player's on-off net per 100 (on court minus off court, his team, garbage time out) over the two
    seasons before (older at half weight), possession-weighted and shrunk to 0 with n0 possessions, then mixed into the
    shipped player value (XPM two seasons + ARC .25) at weight oow on the XPM prior's scale (as arc_blend).
(b) in-season on/off: after each game a player's value is (opening value x K + m(on-off to date) x possessions) /
    (K + possessions); m maps on-off to the value scale by last season's regression of XPM on on-off.
(c) lineup familiarity: tonight's expected minutes (role minutes x play chance, as 'lin') weighted by how much each pair
    has played together (shared minutes this season and last at half, capped at 150) and the share from players with
    fewer than 5 games for this team this season ('newrot'), home minus away, as margin terms.
(d) garbage time out of the team efficiency ratings (Cleaning the Glass's rule): each game enters the eff ratings with
    garbage-time stints removed (points and possessions), so blowout tails don't move the ratings.
Gate (house rule): 2015-21 paired clustered t <= -1.5 and 2022-26 same sign.
Results Nov 2 2026 (data/nba_lineups_research.json; base MAE 9.8965 / 10.7149): ALL FAIL, nothing wired.
  team-season (prior values x actual minutes -> team net, 2015-26): oow .1-.5 tune t -0.3..+1.0; on/off alone far worse.
  (a) oow .1 / .25 / .25 n0 6000: tune t -0.05 / +0.38 / +0.35, held -0.9 / -0.4 / -0.3.
  (b) iok 8000 / 20000 / 60000: tune +0.76 / +0.21 / -0.21, held -1.6 / -2.1 / -2.4 (later seasons only); with ib worse.
  (c) pairc / newrot / newrotL: tune +0.3 / +0.1 / -0.1, held 0.0 / -0.7 / -0.1.
  (d) garbage time out of eff: tune -0.24, held +0.96.
"""
import json
import os
import sys
from collections import defaultdict

os.environ.setdefault('OMP_NUM_THREADS', '1'); os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_espn as E
import nba_games as N
import nba_lineups as L

OUT = os.path.join(N.ROOT, 'data', 'nba_lineups_research.json')
SEASONS = range(2013, 2027)
_ST = {}


def stints_by_game():
    """{game id: stint record} from the cache (no network)"""
    if not _ST:
        for fn in os.listdir(L.CACHE):
            if fn.endswith('.json'):
                try:
                    _ST[fn[:-5]] = json.load(open(os.path.join(L.CACHE, fn)))
                except ValueError:
                    pass
    return _ST


_OO = {}


def onoff_season(S, garbage=False, types=(2,)):
    """{pid: (on poss, on net/100, off poss, off net/100, team)} for season S's regular season, garbage time out"""
    if S in _OO:
        return _OO[S]
    ST = stints_by_game()
    on = defaultdict(lambda: [0.0, 0.0])
    tot = defaultdict(lambda: [0.0, 0.0])
    team = {}
    for g in E.games(S):
        if g['type'] not in types or g['id'] not in ST:
            continue
        r = ST[g['id']]
        for h5, a5, sec, hp, ap, ph, pa, gt in r['st']:
            if gt and not garbage:
                continue
            poss = (ph + pa) / 2
            for t, five, d in ((r['h'], h5, hp - ap), (r['a'], a5, ap - hp)):
                x = tot[t]; x[0] += poss; x[1] += d
                for p in five:
                    o = on[(t, p)]; o[0] += poss; o[1] += d
    out = {}
    for (t, p), (ps, d) in on.items():
        T = tot[t]
        offp = T[0] - ps
        if ps <= 0 or offp <= 50:
            continue
        cur = out.get(p)
        if cur and cur[0] >= ps:
            continue                                   # traded: his team with the most possessions
        out[p] = (ps, 100 * d / ps, offp, 100 * (T[1] - d) / offp, t)
    _OO[S] = out
    return out


def onoff_prior(S, names, n0=3000.0, w2=0.5):
    """pid -> (shrunk on-off over S-1 and S-2, possessions)"""
    a, b = onoff_season(S - 1), onoff_season(S - 2)
    out = {}
    for pid in names:
        num, den = 0.0, n0
        for d, k in ((a, 1.0), (b, w2)):
            r = d.get(pid)
            if r:
                num += (r[1] - r[3]) * r[0] * k; den += r[0] * k
        if den > n0:
            out[pid] = (num / den, den - n0)
    return out


def onoff_blend(S, names, val, w, n0=3000.0, skip=()):
    """val with prior on/off mixed in at w, on val's scale (possession-weighted mean and sd matched)"""
    oo = {p: v for p, v in onoff_prior(S, names, n0).items() if p in val and p not in skip}
    if len(oo) < 50:
        return val
    ks = list(oo)
    x = np.array([oo[k][0] for k in ks]); y = np.array([val[k] for k in ks]); ww = np.array([oo[k][1] for k in ks])
    mx, my = np.average(x, weights=ww), np.average(y, weights=ww)
    sx, sy = np.sqrt(np.average((x - mx) ** 2, weights=ww)), np.sqrt(np.average((y - my) ** 2, weights=ww))
    out = dict(val)
    for k, xv, yv in zip(ks, x, y):
        out[k] = (1 - w) * yv + w * (my + (xv - mx) * sy / sx)
    return out


# ------------------------------------------------------------------ team-season forward test
def team_test():
    """prior values x actual minutes -> team net per 100 (season), base (shipped XPM two seasons + ARC .25) vs + on/off"""
    import harness as H
    G, names = N.load_hist()
    F = json.load(open(N.FIT))
    prm = F['params']
    rows = defaultdict(lambda: {'min': defaultdict(float), 'pf': 0.0, 'pa': 0.0, 'poss': 0.0})
    for g in G:
        if g['t'] != 2 or not g.get('poss') or not g.get('pl'):
            continue
        for t, o, pf, pa in ((g['h'], g['a'], g['hs'], g['as']), (g['a'], g['h'], g['as'], g['hs'])):
            r = rows[(g['S'], t)]
            r['pf'] += pf; r['pa'] += pa; r['poss'] += g['poss']
            for pid, m in g['pl'].get(t, []):
                r['min'][pid] += m
    seasons = sorted({S for S, _ in rows if S >= 2015})
    base, cand = {}, {}
    V = [('xpm1 alone', None), ('oow .1', (0.1, 3000)), ('oow .25', (0.25, 3000)), ('oow .4', (0.4, 3000)),
         ('oow .25 n0 1500', (0.25, 1500)), ('oow .25 n0 6000', (0.25, 6000)), ('oow .5', (0.5, 3000)), ('on/off alone', (1.0, 3000))]
    preds = {lab: {} for lab, _ in V}
    preds['base'] = {}
    for S in seasons:
        val = N.values(S, names, prm['n0'], prm['rook'], ret=prm.get('ret', 0))
        skip = {pid for pid, nm in names.items() if N.returner([N.lookup(S - k, nm) for k in range(1, 5)], prm.get('ret') or N.RET_MIN)}
        vb = N.arc_blend(S, names, val, prm['arcw'], skip=skip)
        tabs = {'base': vb}
        for lab, v in V:
            if v is None:
                tabs[lab] = {pid: (lambda a: a[0] if a else prm['rook'])(N.lookup(S - 1, nm)) for pid, nm in names.items()}
            else:
                tabs[lab] = onoff_blend(S, names, vb, v[0], v[1], skip=skip)
        for (s, t), r in rows.items():
            if s != S:
                continue
            tm = sum(r['min'].values())
            for lab, tab in tabs.items():
                preds[lab][(S, t)] = sum(tab.get(p, prm['rook']) * m for p, m in r['min'].items()) * 5 / tm
    keys = sorted(k for k in preds['base'])
    y = np.array([100 * (rows[k]['pf'] - rows[k]['pa']) / rows[k]['poss'] for k in keys])
    Sx = np.array([k[0] for k in keys])

    def fwd(x):
        pr = np.full(len(y), np.nan)
        for s in seasons:
            tr, te = Sx < s, Sx == s
            if tr.sum() < 30:
                tr = Sx != s                           # first season: leave-one-season-out
            A = np.column_stack([x[tr], np.ones(tr.sum())])
            c = np.linalg.lstsq(A, y[tr], rcond=None)[0]
            pr[te] = c[0] * x[te] + c[1]
        return pr
    x0 = np.array([preds['base'][k] for k in keys])
    p0 = fwd(x0)
    out = {'n': len(keys), 'base': {'r': round(float(np.corrcoef(x0, y)[0, 1]), 4), 'rmse': round(float(np.sqrt(np.mean((p0 - y) ** 2))), 4)}}
    for lab, _ in V:
        x = np.array([preds[lab][k] for k in keys])
        p = fwd(x)
        r = {'r': round(float(np.corrcoef(x, y)[0, 1]), 4), 'rmse': round(float(np.sqrt(np.mean((p - y) ** 2))), 4)}
        for nm, k in (('2015_21', Sx < 2022), ('2022_26', Sx >= 2022)):
            pd_ = H.paired((p[k] - y[k]) ** 2, (p0[k] - y[k]) ** 2, cluster=Sx[k])
            r[nm] = {'dMSE': round(float(pd_['d']), 4), 't': round(float(pd_['t']), 2)}
        out[lab] = r
        print(lab, json.dumps(r), flush=True)
    return out


# ------------------------------------------------------------------ game model: (a)-(d)
class LModel(N.Model):
    def __init__(self, names, P, oow=0.0, oon0=3000.0, iok=0.0, cont=1, gto=0.0, **kw):
        super().__init__(names, P, **kw)
        self.oow, self.oon0, self.iok, self.cont, self.gto = oow, oon0, iok, cont, gto
        self.ST = stints_by_game()
        self.pair = defaultdict(float)                  # (p, q) sorted -> shared minutes (this season + last at half)
        self.tg = defaultdict(int)                      # (team, pid) -> games for this team this season
        self.ion = {}                                   # pid -> [on poss, on margin, team off poss, off margin]
        self.tot = defaultdict(lambda: [0.0, 0.0])
        self.map = (0.0, 0.0)
        # (e) lineup sNet (Nov 3 2026): on-court margin and possessions per pair / five (sorted ids), this
        # season + last at half, garbage time out; team totals the same way (the shrink target)
        self.u2 = defaultdict(lambda: [0.0, 0.0]); self.u5 = defaultdict(lambda: [0.0, 0.0])
        self.ut = defaultdict(lambda: [0.0, 0.0])

    def new_season(self, S):
        super().new_season(S)
        if self.oow:
            skip = {pid for pid, nm in self.names.items() if self.ret and N.returner([N.lookup(S - k, nm) for k in range(1, 5)], self.ret)}
            self.val = onoff_blend(S, self.names, self.val, self.oow, self.oon0, skip=skip)
        for k in list(self.pair):
            self.pair[k] *= 0.5
        for D in (self.u2, self.u5, self.ut):
            for k in D:
                D[k][0] *= 0.5; D[k][1] *= 0.5
        self.tg.clear()
        if self.iok:
            self.val0 = dict(self.val)
            self.ion, self.tot = {}, defaultdict(lambda: [0.0, 0.0])
            # m(on-off): last season's XPM on its on/off, players with 1,000+ possessions (descriptive, S-1 only)
            oo = onoff_season(S - 1)
            xs, ys = [], []
            for pid, nm in self.names.items():
                r, a = oo.get(pid), N.lookup(S - 1, nm)
                if r and a and r[0] >= 1000:
                    xs.append(r[1] - r[3]); ys.append(a[0])
            if len(xs) > 50:
                c = np.polyfit(xs, ys, 1)
                self.map = (float(c[1]), float(c[0]))

    def expected(self, t, g):
        st, rep = self.status_for(g, t)
        st = st or {}
        out = {}
        for p in self.roster(t):
            m, w = self.role[p]
            if w <= 0:
                continue
            out[p] = m / w * N.play_prob(self.P, st.get(p), self.streak[p], rep)
        tot = sum(out.values())
        if tot > 240:
            out = {p: v * 240 / tot for p, v in out.items()}
        return out

    def feats(self, g):
        x, tx = super().feats(g)
        if self.cont:
            f = {}
            for t in (g['h'], g['a']):
                e = self.expected(t, g)
                ps = list(e)
                num = den = 0.0
                for i in range(len(ps)):
                    for j in range(i + 1, len(ps)):
                        w = e[ps[i]] * e[ps[j]]
                        k = (ps[i], ps[j]) if ps[i] < ps[j] else (ps[j], ps[i])
                        num += w * min(1.0, self.pair.get(k, 0.0) / 150); den += w
                tm = sum(e.values()) or 1.0
                nr = sum(v for p, v in e.items() if self.tg[(t, p)] < 5) / tm
                f[t] = (num / den if den else 0.0, nr)
            h, a = g['h'], g['a']
            x['pairc'] = f[h][0] - f[a][0]
            x['newrot'] = f[h][1] - f[a][1]
            early = max(0.0, 1 - self.gp(h, a) / 20)
            x['newrotL'] = x['newrot'] * (1 - early)       # after the first 20 games: trades and returns, not the summer
            # (e) tonight's expected rotation, its pairs' sNet (shrunk to the team's net per 100, k 1600) minus the
            # team's net, weighted by the pair's expected shared minutes; and the expected top-five's 5-man sNet minus
            # the team's net (k 800). Home minus away
            sn = {}
            for t in (g['h'], g['a']):
                e = self.expected(t, g)
                T = self.ut[t]
                tn = 100 * T[1] / T[0] if T[0] > 0 else 0.0
                ps = sorted(e)
                num = den = 0.0
                for i in range(len(ps)):
                    for j in range(i + 1, len(ps)):
                        w = e[ps[i]] * e[ps[j]]
                        u = self.u2.get((ps[i], ps[j]))
                        if u and u[0] > 0:
                            num += w * 100 * (u[1] - u[0] * tn / 100) / (u[0] + 1600)
                        den += w
                top = tuple(sorted(sorted(e, key=lambda p: -e[p])[:5]))
                u = self.u5.get(top)
                sn[t] = (num / den if den else 0.0, 100 * (u[1] - u[0] * tn / 100) / (u[0] + 800) if u and u[0] > 0 else 0.0)
            x['pairnet'] = sn[h][0] - sn[a][0]
            x['unit5'] = sn[h][1] - sn[a][1]
        return x, tx

    def update(self, g):
        r = self.ST.get(g['id']) if g.get('fin') else None
        if self.gto and r and g.get('poss'):
            # garbage-time stints out of the eff ratings (Elo, the market and pelo keep the real result)
            gs = [s for s in r['st'] if s[7]]
            tp = sum((s[5] + s[6]) / 2 for s in r['st'])
            if gs and tp > 0:
                gh, ga = sum(s[3] for s in gs), sum(s[4] for s in gs)
                gp = sum((s[5] + s[6]) / 2 for s in gs) * g['poss'] / tp
                if r['h'] != g['h']:
                    gh, ga = ga, gh
                if g['poss'] - self.gto * gp > 60:
                    g = dict(g, ehs=g['hs'] - self.gto * gh, eas=g['as'] - self.gto * ga, eposs=g['poss'] - self.gto * gp)
        super().update(g)
        if not r:
            return
        for h5, a5, sec, hp, ap, ph, pa, gt in r['st']:
            poss = (ph + pa) / 2
            for t, f, d in ((r['h'], h5, hp - ap), (r['a'], a5, ap - hp)):
                fs = sorted(f)
                if not gt and poss > 0:
                    T = self.ut[t]; T[0] += poss; T[1] += d
                    if len(fs) == 5:
                        U = self.u5[tuple(fs)]; U[0] += poss; U[1] += d
                for i in range(len(fs)):
                    for j in range(i + 1, len(fs)):
                        self.pair[(fs[i], fs[j])] += sec / 60
                        if not gt and poss > 0:
                            U = self.u2[(fs[i], fs[j])]; U[0] += poss; U[1] += d
        for t in (g['h'], g['a']):
            for pid, m in (g.get('pl') or {}).get(t, []):
                if m > 0:
                    self.tg[(t, pid)] += 1
        if self.iok:
            tot = {}
            on = defaultdict(lambda: [0.0, 0.0])
            for h5, a5, sec, hp, ap, ph, pa, gt in r['st']:
                if gt:
                    continue
                poss = (ph + pa) / 2
                for t, f, d in ((r['h'], h5, hp - ap), (r['a'], a5, ap - hp)):
                    x = tot.setdefault(t, [0.0, 0.0]); x[0] += poss; x[1] += d
                    for p in f:
                        o = on[p]; o[0] += poss; o[1] += d
            for t, (tp, td) in tot.items():
                T = self.tot[t]; T[0] += tp; T[1] += td
            for p, (ps, d) in on.items():
                s = self.ion.setdefault(p, [0.0, 0.0, None])
                s[0] += ps; s[1] += d
            a0, b1 = self.map
            for t in tot:
                T = self.tot[t]
                for p in self.members[t]:
                    s = self.ion.get(p)
                    if not s or s[0] < 50 or T[0] - s[0] < 50:
                        continue
                    # off-court: the team's season to date minus his on-court part (his own team only)
                    oo = 100 * s[1] / s[0] - 100 * (T[1] - s[1]) / max(1.0, T[0] - s[0])
                    v0 = self.val0.get(p, self.rook)
                    self.val[p] = (v0 * self.iok + (a0 + b1 * oo) * s[0]) / (self.iok + s[0])


def games_test(only=None):
    import nba_games_fit as Fit
    import harness as H
    F = json.load(open(N.FIT))
    G, names = N.load_hist()
    inj = Fit.load_inj()
    P, feats, base = F['P'], F['feats'], F['params']
    N.Model = LModel

    def design(params):
        _, data = N.walk(G, names, P, params, inj=inj)
        D = [(g, x) for g, x, _ in data if g.get('fin') and g['S'] >= N.FIRST + 1]
        X = {f: np.array([x[f] for _, x in D], float) for f in D[0][1]}
        meta = dict(y=np.array([g['hs'] - g['as'] for g, _ in D], float), S=np.array([g['S'] for g, _ in D]),
                    day=np.array([g['tip'][:10] for g, _ in D]), hts=np.array([f"{g['h']}{g['S']}" for g, _ in D]))
        return X, meta
    X0, M = design(base)
    y, S = M['y'], M['S']
    k1 = (S >= N.SCORE_FROM) & (S < N.HOLD_FROM); k2 = S >= N.HOLD_FROM
    ref = Fit.wf(Fit.mat(X0, feats), y, S)
    out = {'base': {nm: round(float(np.abs(ref[k] - y[k]).mean()), 4) for nm, k in (('2015_21', k1), ('2022_26', k2))}}

    def score(pr, lab, extra=None):
        r = {'label': lab}
        if extra:
            r['params'] = extra
        for nm, k in (('2015_21', k1), ('2022_26', k2)):
            e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
            pd_ = H.paired(e, e0, cluster=[M['day'][k], M['hts'][k]])
            r[nm] = {'mae': round(float(e.mean()), 4), 'd': round(float(pd_['d']), 4), 't': round(float(pd_['t']), 2)}
        # games with a big lineup gap (|lin| > 2 points: missed players), where an in-season update should show
        big = np.abs(X0['lin']) > 2
        for nm, k in (('2015_21 big lin', k1 & big), ('2022_26 big lin', k2 & big)):
            e, e0 = np.abs(pr[k] - y[k]), np.abs(ref[k] - y[k])
            pd_ = H.paired(e, e0, cluster=[M['day'][k], M['hts'][k]])
            r[nm] = {'n': int(k.sum()), 'd': round(float(pd_['d']), 4), 't': round(float(pd_['t']), 2)}
        r['kept'] = r['2015_21']['t'] <= -1.5 and r['2022_26']['d'] < 0
        print(json.dumps(r), flush=True)
        return r
    res = []
    # (c) familiarity terms from the base walk (computed in every walk; no parameter change)
    for col in (['pairnet', 'unit5'] if os.environ.get('SNET_ONLY') else ['pairc', 'newrot', 'newrotL', 'pairnet', 'unit5']):
        res.append(score(Fit.wf(Fit.mat(X0, feats + [col]), y, S), f'(c) {col} margin term'))
    V = [('(a) oow .1', {'oow': 0.1}), ('(a) oow .25', {'oow': 0.25}), ('(a) oow .25 n0 6000', {'oow': 0.25, 'oon0': 6000.0}),
         ('(b) iok 20000', {'iok': 20000.0}), ('(b) iok 60000', {'iok': 60000.0}),
         ('(d) garbage time out of eff', {'gto': 1.0}),
         ('(b) iok 8000', {'iok': 8000.0}), ('(b) iok 20000 ib', {'iok': 20000.0, 'ib': 1}), ('(b) iok 60000 ib', {'iok': 60000.0, 'ib': 1})]
    if only is not None:
        V = [V[i] for i in only]
    for lab, extra in V:
        X, _ = design({**base, **extra})
        res.append(score(Fit.wf(Fit.mat(X, feats), y, S), lab, extra))
    out['variants'] = res
    return out


def save(section, obj):
    try:
        d = json.load(open(OUT))
    except (OSError, ValueError):
        d = {}
    d[section] = obj
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1, allow_nan=False)


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--team' in a:
        save('team_season', team_test())
    if '--games' in a:
        only = [int(i) for i in a[a.index('--only') + 1].split(',') if i] if '--only' in a else None
        save('games' + ('_' + '_'.join(map(str, only)) if only else '_snet' if only == [] else ''), games_test(only))
