#!/usr/bin/env python3
"""Soccer prospects FV sweep 2 (Nov 1 2026): constructed proxies from data the board already pulls, tested on top of
the board's kept model (data/soccer_prospects_fit.json) on the board's own rows, with the Oct 31 harness's gate
(scripts/soccer_trust_research.py: cohort-out t >= 2 and 2/3 of folds, base top-50 MSE and new top-50 outcome not
worse, forward fit 2013-17 / grade 2018-20 not worse).

    python3 scripts/soccer_prospect_data.py games ...            # the board's rebuild (feeder + academy leagues)
    python3 scripts/soccer_fv_sweep2_research.py                 # -> data/soccer_fv_sweep2_research.json

Candidates (all known by the snapshot; no transfer-table input anywhere; clubs and moves come from lineups):
  mgr_*    manager youth trust: the head coach's share of league minutes given to under-21s in EARLIER seasons (any
           club; dump leagues, which carry manager names on every game), shrunk to the league mean; offered alone and
           times the player's minutes share (minutes from a coach who rarely plays kids should say more)
  clubyt_* the same youth share for the club (earlier seasons, whatever the coach)
  dev_*    club development environment: the club's earlier prospects' next-season value over what a simple model
           expected (rows from seasons s <= t-2, so the next season is complete before season t starts; shrunk)
  pct_*    minutes at age: percentile of league-strength-weighted minutes share within position and age year, all
           covered leagues pooled
  role_*   minutes share by team strength: share x club rating, share on a below-league-average club
  pos_*    position scarcity: youth minutes share for keepers/centre-backs (who play later), age x position
  dur_*    durability: earlier seasons with a big minutes drop at the same club (lineups only), and this season so far
  comp_*   competition beaten: minutes share x market value of his position-group teammates at his club
  newmgr   share earned under a coach new to the club this season
"""
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import soccer_prospects as SP          # noqa: E402
import soccer_trust_research as TR     # noqa: E402

CACHE = os.path.join(SP.CACHE, 'sweep2')
OUT = os.path.join(ROOT, 'data', 'soccer_fv_sweep2_research.json')
SNAPS = [SP.SEL_SNAP, (1, 15)]
LGS = SP.DUMPL + SP.FEEDV


def core():
    fn = os.path.join(CACHE, 'core.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    os.makedirs(CACHE, exist_ok=True)
    G, A, P, V = SP.load()
    R = SP.club_ratings(G, A, V)
    A = SP.add_value(A, R)
    O, scale = SP.outcome(A, P)
    TG = SP.team_games(G)
    out = (G, A, P, V, R, O, TG)
    pickle.dump(out, open(fn, 'wb'))
    return out


def managers():
    """(game_id, club) -> head coach name, dump league games (every one has both names)"""
    g = SP.rd('games', usecols=['game_id', 'competition_id', 'home_club_id', 'away_club_id', 'home_club_manager_name',
                                'away_club_manager_name'])
    g = g[g.competition_id.isin(SP.DUMPL)]
    m = pd.concat([g[['game_id', 'home_club_id', 'home_club_manager_name']].set_axis(['game_id', 'club', 'mgr'], axis=1),
                   g[['game_id', 'away_club_id', 'away_club_manager_name']].set_axis(['game_id', 'club', 'mgr'], axis=1)])
    return m.dropna()


def youth_tables(A, P, M):
    """per manager-season and club-season: league minutes, of which by players under 21 on July 1 of the season"""
    a = A[A.comp.isin(SP.DUMPL) & A.mins.gt(0)][['game_id', 'player_id', 'club', 'mins', 'season', 'date', 'comp']]
    a = a.merge(M, on=['game_id', 'club'], how='inner')
    age = (pd.to_datetime(a.season.astype(str) + '-07-01') - a.player_id.map(P.dob)).dt.days / 365.25
    a['ym'] = a.mins * (age < 21)
    ms = a.groupby(['mgr', 'season']).agg(m=('mins', 'sum'), y=('ym', 'sum')).reset_index()
    cs = a.groupby(['club', 'season']).agg(m=('mins', 'sum'), y=('ym', 'sum')).reset_index()
    return a, ms, cs


def shrunk_share(tab, key, t, k=37620.0):
    """earlier seasons only: (youth mins + k x mean) / (mins + k) - mean, per key"""
    h = tab[tab.season < t]
    if not len(h):
        return pd.Series(dtype=float), 0.0
    mu = h.y.sum() / h.m.sum()
    s = h.groupby(key).agg(m=('m', 'sum'), y=('y', 'sum'))
    return (s.y + k * mu) / (s.m + k) - mu, mu


def dev_model(rows_all, t, k=20.0, col='nxt', lag=2):
    """club development: residual of next-season GAR on a simple model, rows from seasons s <= t-2, mean per club
    shrunk toward 0 (k pseudo-rows)"""
    h = rows_all[rows_all.t <= t - lag].assign(nxt=lambda d: d[col])
    if len(h) < 2000:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    cols = ['age', 'age2', 'lmv', 'lmv2', 'gar_td', 'gar1', 'share_td', 'rclub_td', 'ht', 'fwd', 'gk']
    b = SP.ols(h, h.nxt.values, cols)
    res = h.nxt.values - SP.pred(h, cols, b)
    s = pd.DataFrame({'c': h.dclub.values, 'r': res}).dropna().groupby('c').r.agg(['sum', 'count'])
    dev = s['sum'] / (s['count'] + k)
    # the same in FV-ish units: residual of a pass/fail "next-season GAR >= 1" logit is overkill; keep a share version
    hit = (h.nxt.values > 1).astype(float)
    bh = SP.ols(h, hit, cols)
    rh = hit - SP.pred(h, cols, bh)
    s2 = pd.DataFrame({'c': h.dclub.values, 'r': rh}).dropna().groupby('c').r.agg(['sum', 'count'])
    return dev, s2['sum'] / (s2['count'] + k)


def season_share(A, TG):
    """per player-season: league minutes share at his main club (lineups only)"""
    lg = A[A.comp.isin(LGS)]
    pc = lg.groupby(['player_id', 'season', 'club']).agg(m=('mins', 'sum'), n=('napp', 'sum'), b=('nbench', 'sum')).reset_index()
    pc['k'] = pc.m * 1000 + pc.n + pc.b
    mc = pc.sort_values('k').groupby(['player_id', 'season']).tail(1)
    tot = lg.groupby(['player_id', 'season']).mins.sum()
    ng = TG.groupby(['club', 'season']).size()
    mc = mc.set_index(['player_id', 'season'])
    mc['sh'] = (tot.reindex(mc.index) / (90 * ng.reindex(pd.MultiIndex.from_arrays([mc.club, mc.index.get_level_values(1)])).values)).clip(0, 1)
    return mc[['club', 'sh']].reset_index()


def extras(A, P, V, R, TG, X, F, t, snap, ctx):
    snap = pd.Timestamp(snap)
    ids = X.index
    E = pd.DataFrame(index=ids)
    sh, age = F.share_td, X.age
    lsh = (F.share_td + F.share1) / 2
    # ---------------- manager / club youth trust (dump leagues; earlier seasons only)
    a, ms, cs = ctx['ya'], ctx['ms'], ctx['cs']
    my, mu = shrunk_share(ms, 'mgr', t)
    cy, _ = shrunk_share(cs, 'club', t)
    sd = float(my.std()) if len(my) > 5 else 1.0
    cur = a[a.season.eq(t) & (a.date < snap)]
    # his coach: the coach of his main club's latest league game before the snapshot (dump leagues)
    lastg = cur.sort_values('date').groupby('club').tail(1).set_index('club').mgr
    mg = X.club_td.map(lastg)
    yv = mg.map(my) / sd                               # + = plays more kids than the average coach
    E['mgr_y'] = yv.fillna(0)
    E['mgr_trust'] = (-yv).fillna(0) * sh              # minutes from a coach who rarely plays kids
    E['mgr_low'] = (yv < -.5).astype(float) * sh
    E['mgr_has'] = yv.notna().astype(float)
    # minutes earned under coaches by their kid-trust, coach seen in earlier seasons only, this season so far
    pm = cur[cur.player_id.isin(ids)]
    pm = pm.assign(z=pm.mgr.map(my) / sd)
    pm = pm[pm.z.notna()]
    E['mgr_wmins'] = ((-pm.z).clip(lower=0) * pm.mins / 900).groupby(pm.player_id).sum().reindex(ids).fillna(0)
    cyv = X.club_td.map(cy) / (float(cy.std()) if len(cy) > 5 else 1.0)
    E['clubyt_y'] = cyv.fillna(0)
    E['clubyt_trust'] = (-cyv).fillna(0) * sh
    # new coach at his club this season (first league game of season t under a coach not in charge at the end of t-1)
    prev_last = a[a.season.eq(t - 1)].sort_values('date').groupby('club').tail(1).set_index('club').mgr
    newc = X.club_td.map(lastg).ne(X.club_td.map(prev_last)) & X.club_td.map(lastg).notna() & X.club_td.map(prev_last).notna()
    E['newmgr'] = newc.astype(float) * sh
    # ---------------- club development environment (residual next-season GAR of the club's earlier prospects)
    dev, devh = dev_model(ctx['rows_all'], t)
    _, devh2 = dev_model(ctx['rows_all'], t, col='nxt2', lag=3)     # next two seasons, rows s <= t-3
    dc = X.club_td.where(X.club_td.notna(), X.club1)
    E['dev_gar'] = dc.map(dev).fillna(0)
    E['dev_hit'] = dc.map(devh).fillna(0)
    E['dev_hit2'] = dc.map(devh2).fillna(0)
    E['dev_sh'] = E.dev_gar * lsh
    # ---------------- minutes at age, league-strength weighted, percentile within position x age year
    w = F.lg_share
    key = X.grp.astype(str) + np.floor(X.age).astype(int).astype(str)
    E['pct_lgsh'] = w.groupby(key).rank(pct=True).where(w > 0, 0)
    lvl = (X.rlg_td.fillna(SP.REPL) - SP.REPL).clip(lower=0)
    w2 = lvl * lsh
    E['pct_lgsh2'] = w2.groupby(key).rank(pct=True).where(w2 > 0, 0)
    E['young_lgsh'] = (21 - age).clip(lower=0) * F.lg_share
    # ---------------- role by team strength
    rc = (X.rclub_td.fillna(SP.REPL) - SP.REPL).clip(lower=0)
    E['role_r'] = sh * rc
    lgm = X.comp_td.map(R[R.season.eq(t - 1)].groupby('comp').r.mean())
    E['role_weak'] = sh * (X.rclub_td < lgm).astype(float)
    E['role_strong'] = sh * (X.rclub_td >= lgm).astype(float)
    # ---------------- position scarcity x youth
    gd = X.grp.isin(['G', 'D']).astype(float)
    E['pos_yGD'] = sh * (21 - age).clip(lower=0) * gd
    E['pos_yG'] = sh * (21 - age).clip(lower=0) * X.grp.eq('G')
    E['pos_shGD'] = sh * gd
    E['pos_ageG'] = F.age * X.grp.eq('G')
    E['pos_ageD'] = F.age * X.grp.eq('D')
    E['pos_lgGD'] = F.lg_share * gd
    # ---------------- durability: big drops at the same club (lineups only)
    ss = ctx['ss']
    h = ss[ss.player_id.isin(ids) & ss.season.lt(t)].sort_values(['player_id', 'season'])
    h = h.assign(psh=h.groupby('player_id').sh.shift(), pcl=h.groupby('player_id').club.shift(),
                 pse=h.groupby('player_id').season.shift())
    drop = (h.psh >= .3) & (h.sh < .5 * h.psh) & h.club.eq(h.pcl) & h.season.eq(h.pse + 1)
    nd = drop.groupby(h.player_id).sum().reindex(ids).fillna(0)
    E['dur_n'] = nd.clip(upper=2)
    E['dur_any'] = (nd > 0).astype(float)
    E['dur_td'] = ((F.share1 >= .3) & (sh < .5 * F.share1) & X.club_td.eq(X.club1)).astype(float)
    # ---------------- competition beaten: share x log MV of same-group teammates on his club this season
    c = A[A.season.eq(t) & (A.date < snap) & A.comp.isin(LGS) & A.mins.gt(0)][['player_id', 'club', 'mins']]
    c = c.groupby(['club', 'player_id']).mins.sum().reset_index()
    c = c[c.mins >= 270]
    c['grp'] = c.player_id.map(P.grp)
    vv = V[V.date <= snap].groupby('player_id').mv.last()
    # in the fit seasons' money, like his own lmv (X.mvd = X.mv x one factor per pool)
    fac = float((X.mvd / X.mv).dropna().median()) if X.mv.notna().any() else 1.0
    c['lmv'] = np.log((c.player_id.map(vv).fillna(25000) * fac).clip(lower=25000) / 1e6)
    me = pd.DataFrame({'club': X.club_td, 'grp': X.grp, 'lmv': F.lmv}).dropna(subset=['club'])
    g = c.groupby(['club', 'grp']).agg(s=('lmv', 'sum'), n=('lmv', 'size'))
    k = pd.MultiIndex.from_arrays([me.club, me.grp])
    s, n = g.s.reindex(k).values, g.n.reindex(k).values
    cm = c.set_index(['club', 'player_id']).mins
    own = cm.reindex(pd.MultiIndex.from_arrays([me.club, me.index])).notna().values
    mine = np.where(own, me.lmv.values, 0)
    oth = (np.nan_to_num(s) - mine) / np.maximum(np.nan_to_num(n) - own, 1)
    oth = np.where(np.nan_to_num(n) - own > 0, oth, np.nan)
    rel = pd.Series(oth, index=me.index).reindex(ids)
    E['comp_mv'] = (rel.fillna(rel.mean()) - rel.mean()) * sh
    E['comp_gap'] = (rel - F.lmv).clip(-4, 4).fillna(0) * sh       # teammates priced above him and he still plays
    E['comp_gap_pos'] = E.comp_gap.clip(lower=0)
    E['comp_gap_pos_lo'] = E.comp_gap_pos * (F.lmv < 0)
    return E


def nxt_gar(A, t):
    return A[A.season.eq(t + 1)].groupby('player_id').gar.sum()


def rows():
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    G, A, P, V, R, O, TG = core()
    M = managers()
    ya, ms, cs = youth_tables(A, P, M)
    print('manager seasons', len(ms), 'managers', ms.mgr.nunique(), flush=True)
    ss = season_share(A, TG)
    done = O[O.s22 <= SP.COHORTS[1]]
    fitj = json.load(open(SP.FIT))
    out = {}
    for md in SNAPS:
        xs, allr = [], []
        built = {}
        for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
            snap = SP.snapdate(t, md)
            X = SP.features(A, P, V, R, TG, t, snap)
            X['mvlvl'] = SP.mv_level(X.mv)
            X = X[X.old]
            X['mvd'] = X.mv * np.exp(fitj['mvRef']['%02d-%02d' % md] - X.mvlvl)
            F = SP.design(X)
            built[t] = (X, F)
            # every old-pool prospect of season t, for the club development model of later seasons
            ra = F.copy()
            ra['nxt'] = nxt_gar(A, t).reindex(F.index).fillna(0).values
            ra['nxt2'] = (nxt_gar(A, t).reindex(F.index).fillna(0) + nxt_gar(A, t + 1).reindex(F.index).fillna(0)).values / 2
            ra['dclub'] = X.club_td.where(X.club_td.notna(), X.club1).values
            ra['t'] = t
            allr.append(ra)
        rows_all = pd.concat(allr, ignore_index=True)
        ctx = {'ya': ya, 'ms': ms, 'cs': cs, 'ss': ss, 'rows_all': rows_all}
        for t, (X, F) in built.items():
            snap = SP.snapdate(t, md)
            E = extras(A, P, V, R, TG, X, F, t, snap, ctx)
            keep = X.index.isin(done.index)
            Z = pd.concat([F, E], axis=1)[keep]
            Z['fv_out'] = done.fv.reindex(Z.index)
            Z['s22'] = done.s22.reindex(Z.index)
            Z['t'] = t
            Z['pid'] = Z.index
            xs.append(Z.reset_index(drop=True))
            print('rows', md, t, len(Z), flush=True)
        out[md] = pd.concat(xs, ignore_index=True)
    pickle.dump(out, open(fn, 'wb'))
    return out


CANDS = [['mgr_y'], ['mgr_trust'], ['mgr_low'], ['mgr_wmins'], ['mgr_y', 'mgr_trust'], ['clubyt_y'], ['clubyt_trust'],
         ['newmgr'],
         ['dev_gar'], ['dev_hit'], ['dev_hit2'], ['dev_sh'],
         ['pct_lgsh'], ['pct_lgsh2'], ['young_lgsh'],
         ['role_r'], ['role_weak'], ['role_strong'],
         ['pos_yGD'], ['pos_yG'], ['pos_shGD'], ['pos_ageG'], ['pos_ageD'], ['pos_ageG', 'pos_ageD'], ['pos_lgGD'],
         ['dur_n'], ['dur_any'], ['dur_td'],
         ['comp_mv'], ['comp_gap'], ['comp_gap_pos'], ['comp_gap_pos_lo']]
CORR_WITH = ['lg_share', 'share_td', 'gar_td', 'rclub_td', 'lmv', 'age']


def main():
    R = rows()
    kept = json.load(open(SP.FIT))['kept']
    out = {'kept': kept, 'snap': {}}
    for md, Z in R.items():
        key = '%02d-%02d' % md
        y, co = Z.fv_out.values, Z.s22.values
        e, p = SP.loso(Z, y, co, kept)
        allc = sorted({c for cs in CANDS for c in cs})
        res = {'n': int(len(Z)), 'mse': round(float((e ** 2).mean()), 2), 'top50': round(TR.top_mean(p, y, Z.t.values), 2),
               'cover': {c: int((Z[c] != 0).sum()) for c in allc},
               'corr': {c: {w: round(float(np.corrcoef(Z[c], Z[w])[0, 1]), 2) for w in CORR_WITH} for c in allc
                        if Z[c].std() > 0},
               'cands': {}}
        for cols in CANDS:
            if any(Z[c].std() == 0 for c in cols):
                continue
            r = TR.test(Z, kept, cols)
            res['cands']['+'.join(cols)] = r
            print(key, '+'.join(cols), r, flush=True)
        out['snap'][key] = res
    json.dump(out, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
