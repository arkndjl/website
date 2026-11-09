#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer prospects: position-purpose FV drivers (Nov 2 2026), tested on top of the board's kept model on the board's
own rows with the Oct 31 gate (scripts/soccer_trust_research.test: cohort-out t >= 2 and 2/3 of folds, base top-50 MSE
and new top-50 outcome not worse, forward fit 2013-17 / grade 2018-20 not worse).

What each role is for, and the one number that measures it (pre-registered before any outcome was looked at):
  GK  stop goals: his club's goals against per 90 while he is on the pitch minus while he is off (on/off), sign so that
      + = fewer goals against with him                                                                  -> ga_oo x GK
  CB  stop goals (aerial, box defending, line): the same on/off goals against                            -> ga_oo x CB
  FB  defend the flank AND supply width: on/off goal difference                                          -> gd_oo x FB
      (secondary) final-ball supply from wide: assists per 90, shrunk to the FB mean                     -> ast90 x FB
  DM  screen the back line: on/off goals against                                                         -> ga_oo x DM
  CM  connect both boxes: on/off goal difference                                                         -> gd_oo x CM
  AM  be the hub of the attack: share of his club's goals while he is on that he scores or assists       -> gi_sh x AM
  W   create and finish from wide: the same goal-involvement share                                       -> gi_sh x W
  ST  finish: share of his club's goals while he is on that he scores, penalties out                     -> g_sh x ST
      (secondary) make the team score: on/off goals for                                                  -> gf_oo x ST
Pooled checks: all primary terms at once (one fit), and on/off goal difference for every outfielder.

Construction (prediction-date data only):
  * every club game in the data (Transfermarkt dump games + the Transfermarkt API games the board pulls: feeder,
    academy, reserve leagues, cups and Europe), goals with minutes and exact on/off intervals (starters from 0,
    substitutions and dump red cards), games whose goal events don't add up to the score are dropped;
  * per player x club x season x competition, "off" = the club's minutes in that competition between his first and
    last squad listing (bench included) when he was not on the pitch;
  * on/off rate difference per 90, combined over his career to the snapshot with harmonic-minutes weights
    w = on x off / (on + off), shrunk: sum(w d) / (sum(w) + 900);
  * shares: (his goals + k mu) / (club goals while on + k) - mu with k = 10 goals, mu the role mean at that snapshot;
    ast90: (assists + 10 mu) / (mins / 90 + 10) - mu;
  * role = his modal starting position in lineups before the snapshot (dump lineups' position, API shortName), so the
    profile's current position (hindsight) is never used.

    python3 scripts/research/pos_drivers/soccer/soccer_pos_drivers.py events     # goal/interval tables (cached)
    python3 scripts/research/pos_drivers/soccer/soccer_pos_drivers.py            # -> data/soccer_pos_drivers.json
"""
import glob
import gzip
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
ROOT = os.path.dirname(SCR)
sys.path.insert(0, SCR)
import soccer_prospects as SP            # noqa: E402
import soccer_prospect_data as SD        # noqa: E402
import soccer_trust_research as TR       # noqa: E402
import soccer_fv_sweep2_research as S2   # noqa: E402

CACHE = os.path.join(SP.CACHE, 'posdrv')
OUT = os.path.join(ROOT, 'data', 'soccer_pos_drivers.json')
SNAPS = [SP.SEL_SNAP, (1, 15)]
K_OO, K_SH, K_A = 900.0, 10.0, 10.0

ROLE = {'Goalkeeper': 'GK', 'Centre-Back': 'CB', 'Left-Back': 'FB', 'Right-Back': 'FB', 'Defensive Midfield': 'DM',
        'Central Midfield': 'CM', 'Left Midfield': 'CM', 'Right Midfield': 'CM', 'Attacking Midfield': 'AM',
        'Left Winger': 'W', 'Right Winger': 'W', 'Centre-Forward': 'ST', 'Second Striker': 'ST',
        'GK': 'GK', 'CB': 'CB', 'LB': 'FB', 'RB': 'FB', 'LWB': 'FB', 'RWB': 'FB', 'DM': 'DM', 'CM': 'CM', 'LM': 'CM',
        'RM': 'CM', 'AM': 'AM', 'LW': 'W', 'RW': 'W', 'CF': 'ST', 'SS': 'ST'}
ROLES = ['GK', 'CB', 'FB', 'DM', 'CM', 'AM', 'W', 'ST']


# ---------------------------------------------------------------- events
def _game_rows(gid, club_h, club_a, dur, starters, subs, reds, goals, listed):
    """starters/listed: {pid: club}; subs: [(min, off, on)]; reds: [(min, pid)]; goals: [(min, club, scorer, assist, pen)]
    -> player rows [gid, pid, club, start, on_min, gf_on, ga_on, g, npg, a] and club rows [gid, club, gf, ga]"""
    on = {p: 0.0 for p in starters}
    off = {}
    for m, o, i in subs:
        if o is not None and o in on and o not in off:
            off[o] = m
        if i is not None and i not in on:
            on[i] = m
    for m, p in reds:
        if p in on and p not in off:
            off[p] = m
    gf = {club_h: 0, club_a: 0}
    rows = []
    for p, c in listed.items():
        if p not in on:
            rows.append([gid, p, c, 0, 0.0, 0, 0, 0, 0, 0])
            continue
        s, e = on[p], off.get(p, dur)
        f = a_ = 0
        g = npg = ast = 0
        for m, gc, sc, asst, pen in goals:
            if s < m <= e or (s == 0 and m == 0):
                if gc == c:
                    f += 1
                else:
                    a_ += 1
            if sc == p and gc == c:
                g += 1
                npg += 0 if pen else 1
            if asst == p and gc == c:
                ast += 1
        rows.append([gid, p, c, int(p in starters), max(e - s, 0.0), f, a_, g, npg, ast])
    for m, gc, *_ in goals:
        if gc in gf:
            gf[gc] += 1
    cl = [[gid, club_h, gf[club_h], gf[club_a]], [gid, club_a, gf[club_a], gf[club_h]]]
    return rows, cl


def events():
    fn = os.path.join(CACHE, 'events.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    os.makedirs(CACHE, exist_ok=True)
    SP.dump()
    comp = SP.rd('competitions')
    clubc = set(comp[~comp.type.eq('national_team_competition')].competition_id)
    g = SP.rd('games', usecols=['game_id', 'competition_id', 'date', 'home_club_id', 'away_club_id', 'home_club_goals',
                                'away_club_goals']).dropna()
    g = g[g.competition_id.isin(clubc) & (g.date < '2026-07-01')]
    lim = os.environ.get('POSDRV_LIMIT')       # smoke test: a sample of dump games, API 2026 files only, no cache
    if lim:
        g = g.sample(int(lim), random_state=1)
    lu = SP.rd('game_lineups', usecols=['game_id', 'player_id', 'club_id', 'type', 'position'])
    lu = lu[lu.game_id.isin(g.game_id)]
    ev = SP.rd('game_events', usecols=['game_id', 'minute', 'type', 'club_id', 'player_id', 'description',
                                       'player_in_id', 'player_assist_id'])
    ev['minute'] = pd.to_numeric(ev.minute, errors='coerce').fillna(0).clip(0, 90)
    desc = ev.description.fillna('')
    ev['pen'] = desc.str.contains('Penalty')
    ev['red'] = ev.type.eq('Cards') & desc.str.contains('Red card|Second yellow', regex=True) & ev.player_id.notna()
    ev_all = ev
    ev = ev[ev.game_id.isin(g.game_id)]
    P, C, POS = [], [], []
    evg = dict(tuple(ev.groupby('game_id')))
    lug = dict(tuple(lu.groupby('game_id')))
    meta = []
    bad = 0
    for r in g.itertuples(index=False):
        gid = int(r.game_id)
        L = lug.get(gid)
        if L is None or not len(L):
            continue
        E = evg.get(gid)
        goals, subs, reds = [], [], []
        if E is not None:
            for e in E.itertuples(index=False):
                if e.type == 'Goals':
                    goals.append((float(e.minute), int(e.club_id),
                                  None if pd.isna(e.player_id) else int(e.player_id),
                                  # the dump names the fouled player as a penalty's "assist": not an assist
                                  None if pd.isna(e.player_assist_id) or e.pen else int(e.player_assist_id), bool(e.pen)))
                elif e.type == 'Substitutions':
                    subs.append((float(e.minute), None if pd.isna(e.player_id) else int(e.player_id),
                                 None if pd.isna(e.player_in_id) else int(e.player_in_id)))
                elif e.red:
                    reds.append((float(e.minute), int(e.player_id)))
        h, a = int(r.home_club_id), int(r.away_club_id)
        if sum(1 for x in goals if x[1] == h) != r.home_club_goals or sum(1 for x in goals if x[1] == a) != r.away_club_goals:
            bad += 1
            continue
        starters = {int(p): int(c) for p, c, t in zip(L.player_id, L.club_id, L.type) if t == 'starting_lineup'}
        listed = {int(p): int(c) for p, c in zip(L.player_id, L.club_id)}
        rows, cl = _game_rows(gid, h, a, 90.0, starters, sorted(subs), reds, goals, listed)
        P += rows
        C += cl
        for p, c, t, pos in zip(L.player_id, L.club_id, L.type, L.position):
            if t == 'starting_lineup' and isinstance(pos, str):
                POS.append((gid, int(p), pos))
        meta.append((gid, r.competition_id, r.date))
    print('dump games kept', len(meta), 'dropped (goals != score)', bad, flush=True)
    # penalty reason codes in the API: from dump-league games present in both (2026 pulls)
    pen_dump = {(int(x.game_id), int(x.player_id), int(x.minute)) for x in ev_all[ev_all.type.eq('Goals') & ev_all.pen & ev_all.player_id.notna()].itertuples()}
    dump_ids = set(ev_all.game_id.astype(int))
    seen = {}
    files = sorted(glob.glob(os.path.join(SD.CACHE, '*_20*.json.gz')))
    if lim:
        files = [f for f in files if '_2026' in f]
    tm = []
    for f in files:
        tm += json.load(gzip.open(f, 'rt'))
    for x in tm:
        for typ, m, add, club, act, pas, rs in x[10]:
            if typ == 'GOAL' and act:
                k = (int(x[0]), int(act), int(min(m or 0, 90)))
                if k in pen_dump or any((int(x[0]), int(act), mm) in pen_dump for mm in (k[2] - 1, k[2] + 1)):
                    seen.setdefault(rs, [0, 0])[0] += 1
                elif int(x[0]) in dump_ids:
                    seen.setdefault(rs, [0, 0])[1] += 1
    pen_codes = {rs for rs, (p, n) in seen.items() if p >= 5 and p > 2 * n}
    print('API goal reason codes (pen, non-pen in overlap):', seen, '-> penalty codes', pen_codes, flush=True)
    bad = 0
    have = {m[0] for m in meta}
    for x in tm:
        gid, comp_, _, date, h, a, hg, ag, dur, pl, acts = x
        if hg is None or ag is None or not date or int(gid) in have:
            continue
        dur = float(min(dur or 90, 90))
        goals, subs = [], []
        for typ, m, add, club, act, pas, rs in acts:
            m = float(min(m or 0, dur))
            if typ == 'SUBSTITUTE':
                subs.append((m, act, pas))
            elif typ == 'GOAL':
                goals.append((m, club, act, pas, rs in pen_codes))
        if sum(1 for q in goals if q[1] == h) != hg or sum(1 for q in goals if q[1] == a) != ag:
            bad += 1
            continue
        starters = {p[0]: p[1] for p in pl if p[2]}
        listed = {p[0]: p[1] for p in pl}
        rows, cl = _game_rows(int(gid), h, a, dur, starters, sorted(subs, key=lambda s: s[0]), [], goals, listed)
        P += rows
        C += cl
        for p in pl:
            if p[2] and p[3]:
                POS.append((int(gid), int(p[0]), p[3]))
        meta.append((int(gid), comp_, date[:10]))
        have.add(int(gid))
    print('API games dropped (goals != score)', bad, 'total games', len(meta), flush=True)
    M = pd.DataFrame(meta, columns=['game_id', 'comp', 'date'])
    M['date'] = pd.to_datetime(M.date)
    M['season'] = SP.season_of(M.date)
    PG = pd.DataFrame(P, columns=['game_id', 'player_id', 'club', 'start', 'on', 'gf', 'ga', 'g', 'npg', 'a'])
    CG = pd.DataFrame(C, columns=['game_id', 'club', 'gf', 'ga'])
    PS = pd.DataFrame(POS, columns=['game_id', 'player_id', 'pos'])
    PS['role'] = PS.pos.map(ROLE)
    PS = PS.dropna(subset=['role'])
    for D in (PG, CG, PS):
        D[['comp', 'date', 'season']] = D[['game_id']].merge(M, on='game_id', how='left')[['comp', 'date', 'season']].values
    PG['date'] = pd.to_datetime(PG.date)
    CG['date'] = pd.to_datetime(CG.date)
    PS['date'] = pd.to_datetime(PS.date)
    # club cumulative sums inside each club x season x competition, so a squad-listing window is two lookups
    CG = CG.sort_values(['club', 'season', 'comp', 'date', 'game_id']).reset_index(drop=True)
    grp = CG.groupby(['club', 'season', 'comp'])
    CG['cgf'], CG['cga'], CG['cn'] = grp.gf.cumsum(), grp.ga.cumsum(), grp.cumcount() + 1
    PG = PG.merge(CG[['game_id', 'club', 'cgf', 'cga', 'cn', 'gf', 'ga']].rename(columns={'gf': 'tgf', 'ga': 'tga'}),
                  on=['game_id', 'club'], how='left')
    out = (PG, PS)
    if not lim:
        pickle.dump(out, open(fn, 'wb'))
    return out


def drivers(PG, PS, ids, t, snap):
    """career-to-snapshot role drivers for players `ids`"""
    snap = pd.Timestamp(snap)
    d = PG[PG.player_id.isin(ids) & (PG.date < snap) & (PG.season <= t)]
    d = d.sort_values('date')
    k = ['player_id', 'club', 'season', 'comp']
    gb = d.groupby(k, sort=False)
    first, last = gb.head(1).set_index(k), gb.tail(1).set_index(k)
    s = gb.agg(on=('on', 'sum'), gf=('gf', 'sum'), ga=('ga', 'sum'), g=('g', 'sum'), npg=('npg', 'sum'), a=('a', 'sum'))
    tgf = last.cgf - first.cgf + first.tgf
    tga = last.cga - first.cga + first.tga
    tmin = (last.cn - first.cn + 1) * 90.0
    s['off'] = (tmin.reindex(s.index) - s.on).clip(lower=0)
    s['gf_off'] = (tgf.reindex(s.index) - s.gf).clip(lower=0)
    s['ga_off'] = (tga.reindex(s.index) - s.ga).clip(lower=0)
    w = s.on * s.off / (s.on + s.off).replace(0, np.nan)
    w = w.fillna(0)
    on90, off90 = (s.on / 90).replace(0, np.nan), (s.off / 90).replace(0, np.nan)
    dga = (s.ga / on90 - s.ga_off / off90).fillna(0)
    dgf = (s.gf / on90 - s.gf_off / off90).fillna(0)
    pid = s.index.get_level_values(0)
    W = w.groupby(pid).sum()
    E = pd.DataFrame(index=pd.Index(ids))
    E['ga_oo'] = (-(w * dga).groupby(pid).sum() / (W + K_OO)).reindex(E.index).fillna(0)
    E['gf_oo'] = ((w * dgf).groupby(pid).sum() / (W + K_OO)).reindex(E.index).fillna(0)
    E['gd_oo'] = E.gf_oo + E.ga_oo
    tot = s.groupby(pid)[['on', 'gf', 'g', 'npg', 'a']].sum().reindex(E.index).fillna(0)
    # role: modal starting position in lineups before the snapshot
    r = PS[PS.player_id.isin(ids) & (PS.date < snap)]
    role = r.groupby('player_id').role.agg(lambda x: x.value_counts().index[0]).reindex(E.index)
    E['role'] = role
    for c in ROLES:
        E['is_' + c] = role.eq(c).astype(float)
    E['g_sh'] = E['gi_sh'] = E['ast90'] = 0.0
    for c in ROLES:
        m = role.eq(c) & tot.on.gt(0)
        if m.sum() < 20:
            continue
        T = tot[m]
        mu_g = T.npg.sum() / max(T.gf.sum(), 1)
        mu_gi = (T.g + T.a).sum() / max(T.gf.sum(), 1)
        mu_a = T.a.sum() / max(T.on.sum() / 90, 1)
        E.loc[m, 'g_sh'] = (T.npg + K_SH * mu_g) / (T.gf + K_SH) - mu_g
        E.loc[m, 'gi_sh'] = (T.g + T.a + K_SH * mu_gi) / (T.gf + K_SH) - mu_gi
        E.loc[m, 'ast90'] = (T.a + K_A * mu_a) / (T.on / 90 + K_A) - mu_a
    E['oo_w'] = W.reindex(E.index).fillna(0)
    T = {}
    T['GK_ga'] = E.ga_oo * E.is_GK
    T['CB_ga'] = E.ga_oo * E.is_CB
    T['FB_gd'] = E.gd_oo * E.is_FB
    T['DM_ga'] = E.ga_oo * E.is_DM
    T['CM_gd'] = E.gd_oo * E.is_CM
    T['AM_gi'] = E.gi_sh * E.is_AM
    T['W_gi'] = E.gi_sh * E.is_W
    T['ST_g'] = E.g_sh * E.is_ST
    T['FB_a90'] = E.ast90 * E.is_FB
    T['ST_gf'] = E.gf_oo * E.is_ST
    T['OUT_gd'] = E.gd_oo * (1 - E.is_GK) * role.notna()
    for c, v in T.items():
        E[c] = v.fillna(0)
    return E


PRIMARY = ['GK_ga', 'CB_ga', 'FB_gd', 'DM_ga', 'CM_gd', 'AM_gi', 'W_gi', 'ST_g']
CANDS = [[c] for c in PRIMARY] + [['FB_a90'], ['ST_gf'], PRIMARY, ['OUT_gd']]


def rows():
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    PG, PS = events()
    G, A, P, V, R, O, TG = S2.core()
    done = O[O.s22 <= SP.COHORTS[1]]
    fitj = json.load(open(SP.FIT))
    out = {}
    for md in SNAPS:
        xs = []
        for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
            snap = SP.snapdate(t, md)
            X = SP.features(A, P, V, R, TG, t, snap)
            X['mvlvl'] = SP.mv_level(X.mv)
            X = X[X.old]
            X['mvd'] = X.mv * np.exp(fitj['mvRef']['%02d-%02d' % md] - X.mvlvl)
            F = SP.design(X)
            keep = X.index.isin(done.index)
            E = drivers(PG, PS, X.index[keep], t, snap)
            Z = pd.concat([F[keep], E.drop(columns=['role'])], axis=1)
            Z['role'] = E.role
            Z['fv_out'] = done.fv.reindex(Z.index)
            Z['s22'] = done.s22.reindex(Z.index)
            Z['t'] = t
            Z['pid'] = Z.index
            xs.append(Z.reset_index(drop=True))
            print('rows', md, t, len(Z), 'role known', int(Z.role.notna().sum()), flush=True)
        out[md] = pd.concat(xs, ignore_index=True)
    pickle.dump(out, open(fn, 'wb'))
    return out


def bh(ps, q=.10):
    """Benjamini-Hochberg: which of ps pass at FDR q"""
    o = np.argsort(ps)
    n = len(ps)
    ok = np.zeros(n, bool)
    kmax = -1
    for i, j in enumerate(o):
        if ps[j] <= q * (i + 1) / n:
            kmax = i
    if kmax >= 0:
        ok[o[:kmax + 1]] = True
    return ok


def main():
    if sys.argv[1:] == ['events']:
        PG, PS = events()
        print(len(PG), 'player-games', len(PS), 'starts with a position')
        return
    R = rows()
    kept = json.load(open(SP.FIT))['kept']
    out = {'kept': kept, 'k': {'oo': K_OO, 'share': K_SH, 'ast': K_A}, 'snap': {}, 'nTests': 0}
    from scipy import stats
    for md, Z in R.items():
        key = '%02d-%02d' % md
        res = {'n': int(len(Z)), 'roles': {k: int(v) for k, v in Z.role.value_counts().items()},
               'cover': {}, 'corr': {}, 'cands': {}}
        for cols in CANDS:
            name = '+'.join(cols) if len(cols) < 3 else 'ALL_PRIMARY'
            if any(Z[c].std() == 0 for c in cols):
                continue
            r = TR.test(Z, kept, cols)
            # one-sided fold t -> p (direction set by the role: positive coefficient expected)
            r['p'] = float(stats.t.sf(r['t'], r['of'] - 1))
            r['coefSignOk'] = all(v > 0 for v in r['coef'].values())
            res['cands'][name] = r
            out['nTests'] += 1
            if len(cols) == 1:
                c = cols[0]
                nz = Z[c] != 0
                res['cover'][c] = int(nz.sum())
                res['corr'][c] = {w: round(float(np.corrcoef(Z.loc[nz, c], Z.loc[nz, w])[0, 1]), 2)
                                  for w in ('gar_td', 'gar1', 'ga90_td', 'share_td', 'lmv', 'fv_out') if Z.loc[nz, w].std() > 0}
            print(key, name, r, flush=True)
        names = list(res['cands'])
        ok = bh(np.array([res['cands'][n]['p'] for n in names]))
        for n, o in zip(names, ok):
            res['cands'][n]['bh10'] = bool(o)
            res['cands'][n]['ship'] = bool(o and res['cands'][n]['pass'] and res['cands'][n]['coefSignOk'])
        out['snap'][key] = res
    json.dump(out, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
