#!/usr/bin/env python3
"""Soccer prospects FV sweep (Oct 31 2026): coach-trust and level signals beyond league minutes share, tested on top of
the board's kept model (data/soccer_prospects_fit.json) on the board's own rows.

    python3 scripts/soccer_prospect_data.py games ...           # the board's rebuild (feeder + academy leagues)
    python3 scripts/soccer_prospect_data.py games EMQ EURO UNLA UNLB UNLC UNLD WMQ1 WMQ2 WMQ3 WMQ4 WMQ5 WMQ6 FIWC COPA FS --seasons 2010-2020
    python3 scripts/soccer_trust_research.py                     # -> data/soccer_trust_research.json

Candidates (all known by the snapshot):
  euro_*   European club competition play incl. qualifiers (CL, EL, UECL, their qualifying rounds, Super Cup): the
           board already offers main-stage minutes (emins: t 0.8, 4/8 in the selection), so these are the untested cuts:
           qualifiers, starts, squad registration (bench + apps), share of the club's European minutes, young for it.
  cup_*    domestic cup play (FA Cup, League Cup, Copa del Rey, DFB-Pokal, Coppa Italia, KNVB beker, Taca, ...): not
           senior value on the board; tested as trust for fringe players (low league share) and overall.
  snt_*    senior national team play before the snapshot, from Transfermarkt API games (Euro and World Cup qualifiers,
           Nations League, tournaments, friendlies). Not the profile's national-team assignment: the API lists it only
           for some current internationals (Pedri yes, Salah no), so it is hindsight. Youth national teams are another
           thread's.
  rec_*    recent trust: starts in the club's last five league games before the snapshot; minutes against stronger
           opponents.
Gate (brief Oct 31): cohort-out folds (birth cohort, the board's held-out rule) t >= 2 and 2/3 of folds won; season
folds reported too; top of board: each season's top 50 by the base held-out grade, their MSE not worse, and the top 50
by the new grade not lower in outcome; forward: fit 2013-17, grade 2018-20, MSE and top-50 not worse.
"""
import gzip
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
import soccer_prospect_data as SD      # noqa: E402

CACHE = os.path.join(SP.CACHE, 'trust')
OUT = os.path.join(ROOT, 'data', 'soccer_trust_research.json')
EUROALL = ['CL', 'EL', 'UCOL', 'CLQ', 'ELQ', 'ECLQ', 'USC']
EUROQ = ['CLQ', 'ELQ', 'ECLQ']
CUPS = ['FAC', 'CGB', 'CDR', 'DFB', 'CIT', 'NLP', 'POCP', 'DKP', 'SFA', 'UKRP', 'GRP', 'RUP', 'KLUB']
FWD = (2013, 2017)
SNAPS = [SP.SEL_SNAP, (1, 15)]


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
    # cups the dump has games for but leaves out of its competitions table (Taca de Portugal, EFL Cup 2022+, KLUB):
    # kept apart so the board's own inputs (and its pool flag) stay as built
    g = SP.rd('games', usecols=['game_id', 'competition_id', 'date', 'home_club_id', 'away_club_id'])
    g = g[g.competition_id.isin(['POCP', 'CGB', 'KLUB'])].rename(columns={'competition_id': 'comp', 'home_club_id': 'home',
                                                                       'away_club_id': 'away'})
    g['date'] = pd.to_datetime(g.date)
    a = SP.rd('appearances', usecols=['game_id', 'player_id', 'player_club_id', 'minutes_played'])
    a = a[a.game_id.isin(g.game_id)].rename(columns={'player_club_id': 'club', 'minutes_played': 'mins'})
    lu = SP.rd('game_lineups', usecols=['game_id', 'player_id', 'type'])
    lu = lu[lu.game_id.isin(g.game_id) & lu.type.eq('starting_lineup')].drop_duplicates(['game_id', 'player_id'])
    a = a.merge(lu.assign(start=1)[['game_id', 'player_id', 'start']], on=['game_id', 'player_id'], how='left')
    a['start'] = a.start.fillna(0)
    AC = a.merge(g[['game_id', 'comp', 'date']], on='game_id')
    AC['season'] = SP.season_of(AC.date)
    G = pd.concat([G, g.assign(season=SP.season_of(g.date))], ignore_index=True)
    A = pd.concat([A, AC.assign(gar=0.0, napp=(AC.mins > 0).astype(int), nbench=0, _cup=1)], ignore_index=True)
    out = (G, A, P, V, R, O, TG)
    pickle.dump(out, open(fn, 'wb'))
    return out


NTC = ['EMQ', 'EURO', 'UNLA', 'UNLB', 'UNLC', 'UNLD', 'WMQ1', 'WMQ2', 'WMQ3', 'WMQ4', 'WMQ5', 'WMQ6', 'FIWC', 'COPA', 'FS']


def senior_apps():
    """senior national team appearances (Transfermarkt API games of NTC, 2010-20), squad rows included (mins 0):
    only clubs that are senior national teams (the dump's national_teams table, or a club name with no age tag)"""
    import re
    G, A = SP.tm_games(NTC, range(2010, 2021))
    sen = set(SP.rd('national_teams', usecols=['national_team_id']).national_team_id.astype(int))
    fn = os.path.join(CACHE, 'natl_clubs.json')
    have = json.load(open(fn)) if os.path.exists(fn) else {}
    todo = [str(int(c)) for c in A.club.dropna().unique() if int(c) not in sen and str(int(c)) not in have]
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(10) as ex:
        for i, r in zip(todo, ex.map(lambda i: SD.get(f'/club/{i}', tries=3), todo)):
            have[i] = ((r or {}).get('data') or {}).get('name')
    os.makedirs(CACHE, exist_ok=True)
    json.dump(have, open(fn, 'w'))
    ok = sen | {int(k) for k, v in have.items() if v and not re.search(r'U\s?\d\d|Olymp|B$|Youth|Amateur', v)}
    A = A[A.club.isin(ok)].merge(G[['game_id', 'comp', 'date']], on='game_id')
    print('senior national apps', len(A), (A.mins > 0).sum(), 'teams', A.club.nunique(), flush=True)
    return A


def extras(A, G, R, X, t, snap, natl):
    snap = pd.Timestamp(snap)
    ids = X.index
    E = pd.DataFrame(index=ids)
    w = A[A.player_id.isin(ids) & A.season.isin([t - 1, t]) & (A.date < snap)]
    age = X.age
    # Europe incl. qualifiers
    eu = w[w.comp.isin(EUROALL)]
    em = eu.groupby('player_id').mins.sum().reindex(ids).fillna(0)
    E['euro_all'] = em / 900
    E['euro_q'] = eu[eu.comp.isin(EUROQ)].groupby('player_id').mins.sum().reindex(ids).fillna(0) / 900
    E['euro_lst'] = np.log1p(eu[eu.mins > 0].groupby('player_id').start.sum().reindex(ids).fillna(0))
    E['euro_squad'] = np.log1p(eu.groupby('player_id').size().reindex(ids).fillna(0))
    E['euro_young'] = (21 - age).clip(lower=0) * em / 900
    # share of his club's European minutes (club games x 90)
    cg = G[G.comp.isin(EUROALL) & G.season.isin([t - 1, t]) & (G.date < snap)]
    ng = pd.concat([cg.home, cg.away]).value_counts()
    ec = eu.groupby(['player_id', 'club']).mins.sum().reset_index()
    ec['sh'] = ec.mins / (ec.club.map(ng) * 90)
    E['euro_sh'] = ec.groupby('player_id').sh.max().reindex(ids).fillna(0).clip(0, 1)
    # domestic cups
    cu = w[w.comp.isin(CUPS)]
    cm = cu.groupby('player_id').mins.sum().reindex(ids).fillna(0)
    E['cup'] = cm / 900
    E['cup_log'] = np.log1p(cm / 90)
    lsh = (X.share_td_ + X.share1_) / 2
    E['cup_fringe'] = np.log1p(cm / 90) * (lsh < .2)
    E['cup_lst'] = np.log1p(cu[cu.mins > 0].groupby('player_id').start.sum().reindex(ids).fillna(0))
    cug = G[G.comp.isin(CUPS) & G.season.isin([t - 1, t]) & (G.date < snap)]
    ncg = pd.concat([cug.home, cug.away]).value_counts()
    cc = cu.groupby(['player_id', 'club']).mins.sum().reset_index()
    cc['sh'] = cc.mins / (cc.club.map(ncg) * 90)
    E['cup_sh'] = cc.groupby('player_id').sh.max().reindex(ids).fillna(0).clip(0, 1)
    r1 = R[R.season.eq(t - 1)].set_index('club').r
    cr = cu.club.map(r1).fillna(SP.REPL)
    E['cup_r'] = ((cr - SP.REPL).clip(lower=0) * cu.mins / 900).groupby(cu.player_id).sum().reindex(ids).fillna(0)
    E['trust_all'] = np.log1p((em + cm) / 90)
    # senior national team play before the snapshot (qualifiers, Nations League, tournaments, friendlies)
    nt = natl[natl.player_id.isin(ids) & (natl.date < snap)]
    na = nt[nt.mins > 0]
    E['snt'] = ids.isin(na.player_id.unique()).astype(float)
    E['snt_n'] = np.log1p(na.groupby('player_id').size().reindex(ids).fillna(0))
    E['snt_min'] = na.groupby('player_id').mins.sum().reindex(ids).fillna(0) / 900
    E['snt_call'] = ids.isin(nt.player_id.unique()).astype(float)
    first = na.groupby('player_id').date.min().reindex(ids)
    dage = (first - pd.to_datetime(X.dob)).dt.days / 365.25
    E['snt_young'] = (21.5 - dage).clip(lower=0).fillna(0)
    E['snt_mv'] = E.snt * X.lmv_
    # recent trust: starts in the club's last five league games before the snapshot
    lg = A[A.comp.isin(SP.DUMPL + SP.FEEDV) & A.season.eq(t) & (A.date < snap)]
    clubg = G[G.comp.isin(SP.DUMPL + SP.FEEDV) & G.season.eq(t) & (G.date < snap)]
    x = pd.concat([clubg[['game_id', 'home', 'date']].rename(columns={'home': 'club'}),
                   clubg[['game_id', 'away', 'date']].rename(columns={'away': 'club'})])
    last5 = x.sort_values('date').groupby('club').tail(5)
    l5 = lg[lg.game_id.isin(last5.game_id) & lg.player_id.isin(ids)]
    l5 = l5[l5.club.eq(l5.player_id.map(X.club_td))]
    E['rec_st5'] = (l5.groupby('player_id').start.sum() / 5).reindex(ids).fillna(0) * X.club_td.notna()
    E['rec_trend'] = E.rec_st5 - X.share_td_
    # minutes against stronger opponents (last season's ratings): share of his league minutes
    gg = clubg.set_index('game_id')
    l2 = lg[lg.player_id.isin(ids) & lg.mins.gt(0)].copy()
    opp = np.where(l2.club.values == l2.game_id.map(gg.home).values, l2.game_id.map(gg.away).values, l2.game_id.map(gg.home).values)
    l2['ro'] = pd.Series(opp, index=l2.index).map(r1).values
    l2['rc'] = l2.club.map(r1)
    l2['big'] = (l2.ro > l2.rc).astype(float) * l2.mins
    s = l2.groupby('player_id').agg(b=('big', 'sum'), m=('mins', 'sum'))
    E['rec_big'] = ((s.b / s.m).where(s.m >= 270) - .5).reindex(ids).fillna(0)
    # league-adjusted scoring: goal contributions per 90 this season x league strength over replacement (the board
    # keeps the raw rate, ga90_td); and the same for feeder leagues only
    lv = (X.rlg_td.fillna(SP.REPL) - SP.REPL).clip(lower=0) / 2.5
    E['ga_lg'] = X.ga90_td_ * lv
    E['ga_feed'] = X.ga90_td_ * X.comp_td.isin(SP.FEEDV) * lv
    return E


def rows():
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    G, A, P, V, R, O, TG = core()
    natl = senior_apps()
    AB = A[A._cup.isna()].drop(columns='_cup')          # the board's own appearances
    done = O[O.s22 <= SP.COHORTS[1]]
    fitj = json.load(open(SP.FIT))
    out = {}
    for md in SNAPS:
        xs = []
        for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
            snap = SP.snapdate(t, md)
            X = SP.features(AB, P, V, R, TG, t, snap)
            X['mvlvl'] = SP.mv_level(X.mv)
            X = X[X.index.isin(done.index) & X.old]
            X['mvd'] = X.mv * np.exp(fitj['mvRef']['%02d-%02d' % md] - X.mvlvl)
            F = SP.design(X)
            X['share_td_'], X['share1_'], X['lmv_'], X['ga90_td_'] = F.share_td, F.share1, F.lmv, F.ga90_td
            X['dob'] = P.dob.reindex(X.index)
            E = extras(A, G, R, X, t, snap, natl)
            Z = pd.concat([F, E], axis=1)
            Z['fv_out'] = done.fv.reindex(X.index)
            Z['s22'] = done.s22.reindex(X.index)
            Z['t'] = t
            Z['pid'] = X.index
            xs.append(Z.reset_index(drop=True))
            print('rows', md, t, len(Z), flush=True)
        out[md] = pd.concat(xs, ignore_index=True)
    pickle.dump(out, open(fn, 'wb'))
    return out


# ---------------------------------------------------------------- tests
def top_mean(p, y, t, k=50):
    return float(np.mean([y[t == s][np.argsort(-p[t == s])[:k]].mean() for s in np.unique(t)]))


def top_mask(p, t, k=50):
    m = np.zeros(len(p), bool)
    for s in np.unique(t):
        ix = np.where(t == s)[0]
        m[ix[np.argsort(-p[ix])[:k]]] = True
    return m


def folds_t(e0, e1, f):
    d = e0 ** 2 - e1 ** 2
    per = np.array([d[f == s].mean() for s in np.unique(f)])
    return float(d.mean()), float(per.mean() / (per.std(ddof=1) / math.sqrt(len(per)) + 1e-12)), int((per > 0).sum()), len(per)


def test(Z, kept, cand):
    y, t, co = Z.fv_out.values, Z.t.values, Z.s22.values
    e0, p0 = SP.loso(Z, y, co, kept)
    e1, p1 = SP.loso(Z, y, co, kept + cand)
    gain, tt, wins, of = folds_t(e0, e1, co)
    es0, _ = SP.loso(Z, y, t, kept)
    es1, _ = SP.loso(Z, y, t, kept + cand)
    sg, st, sw, so = folds_t(es0, es1, t)
    b50 = top_mask(p0, t)
    tr, te = Z.t.between(*FWD).values, ~Z.t.between(*FWD).values
    b0, b1 = SP.ols(Z[tr], y[tr], kept), SP.ols(Z[tr], y[tr], kept + cand)
    f0, f1 = SP.pred(Z[te], kept, b0), SP.pred(Z[te], kept + cand, b1)
    fb50 = top_mask(f0, t[te])
    coef = dict(zip(['const'] + kept + cand, SP.ols(Z, y, kept + cand)))
    r = {'gain': round(gain, 3), 't': round(tt, 2), 'wins': wins, 'of': of,
         'seasonGain': round(sg, 3), 'seasonT': round(st, 2), 'seasonWins': sw, 'seasonOf': so,
         'b50Mse': round(float((e1[b50] ** 2).mean() - (e0[b50] ** 2).mean()), 3),
         'top50': round(top_mean(p1, y, t) - top_mean(p0, y, t), 2),
         'fwdMse': round(float(((y[te] - f1) ** 2).mean() - ((y[te] - f0) ** 2).mean()), 3),
         'fwdB50Mse': round(float(((y[te] - f1)[fb50] ** 2).mean() - ((y[te] - f0)[fb50] ** 2).mean()), 3),
         'fwdTop50': round(top_mean(f1, y[te], t[te]) - top_mean(f0, y[te], t[te]), 2),
         'coef': {c: round(float(coef[c]), 3) for c in cand}, 'nz': int((Z[cand].abs().sum(axis=1) > 0).sum())}
    r['cv'] = r['t'] >= 2 and r['wins'] >= math.ceil(r['of'] * 2 / 3)
    r['pass'] = bool(r['cv'] and r['b50Mse'] <= 0 and r['top50'] >= 0 and r['fwdMse'] <= 0 and r['fwdB50Mse'] <= 0
                     and r['fwdTop50'] >= -.1)
    return r


CANDS = [['euro_all'], ['euro_q'], ['euro_lst'], ['euro_squad'], ['euro_young'], ['euro_sh'],
         ['cup'], ['cup_log'], ['cup_fringe'], ['cup_lst'], ['cup_sh'], ['cup_r'], ['trust_all'],
         ['snt'], ['snt_n'], ['snt_min'], ['snt_call'], ['snt_young'], ['snt', 'snt_young'], ['snt_mv'],
         ['rec_st5'], ['rec_trend'], ['rec_big'], ['ga_lg'], ['ga_feed']]


def main():
    R = rows()
    kept = json.load(open(SP.FIT))['kept']
    out = {'kept': kept, 'snap': {}}
    for md, Z in R.items():
        key = '%02d-%02d' % md
        y, co = Z.fv_out.values, Z.s22.values
        e, p = SP.loso(Z, y, co, kept)
        res = {'n': int(len(Z)), 'mse': round(float((e ** 2).mean()), 2), 'top50': round(top_mean(p, y, Z.t.values), 2),
               'cover': {c: int((Z[c] != 0).sum()) for c in sorted({c for cs in CANDS for c in cs})}, 'cands': {}}
        for cols in CANDS:
            r = test(Z, kept, cols)
            res['cands']['+'.join(cols)] = r
            print(key, '+'.join(cols), r, flush=True)
        out['snap'][key] = res
    json.dump(out, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
