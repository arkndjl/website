#!/usr/bin/env python3
"""Soccer prospects FV driver search (Noah, Oct 24 2026): candidate inputs a recruitment analyst would look at, each
tested on top of the board's kept model (scripts/soccer_prospects.py) with the board's own rule, plus the top of the
board and a forward test.

    python3 scripts/soccer_prospect_data.py games U21Q U19Q U17Q --seasons 2010-2026   # UEFA youth qualifiers
    python3 scripts/soccer_fv_drivers.py            # build rows (cached), test every candidate -> data/soccer_fv_drivers.json

Finding (Oct 24 2026): the dump's transfer table is a hindsight leak. Prospects in the dump leagues with any transfer
on record became +7 FV better than the inputs said (t 5): the dump lists transfer histories only for players it kept
scraping, i.e. those still around later. Every transfer-table input (fee, loans, moves, academy) rides on that; the
board's summer-fee input added nothing once the record was known, and was dropped.

Gate (all three): the board's rule (leave-one-season-out MSE gain with t >= 2 and 2/3 of seasons won, on the Oct 24
rows); the top of the board (each season's top 50 by out-of-sample grade: mean outcome not lower); forward (fit
2013-17, grade 2018-20: MSE and top-50 outcome not worse). Inputs whose history starts late (Understat from 2014-15,
debut age) are tested only on the seasons they cover.

Hindsight guards: nothing after the snapshot date; static attributes (foot, height) coded so a missing value carries
no information (missing = the mean of the known); transfer-table features only for players with minutes in the dump
leagues by the snapshot (the dump only lists transfers of players who appeared in its leagues, at any time).
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
sys.path.insert(0, HERE)
import soccer_prospects as SP          # noqa: E402
import names as NM                    # noqa: E402

ROOT = os.path.dirname(HERE)
CACHE = os.path.join(SP.CACHE, 'drivers')
US = os.environ.get('UNDERSTAT_DIR', os.path.join(HERE, '.cache', 'soccer', 'us'))
OUT = os.path.join(ROOT, 'data', 'soccer_fv_drivers.json')
YQ = ['U21Q', 'U19Q', 'U17Q']
USL = {'GB1': 'EPL', 'ES1': 'La_liga', 'IT1': 'Serie_A', 'L1': 'Bundesliga', 'FR1': 'Ligue_1'}
FWD = (2013, 2017)                     # forward test: fit these seasons, grade the rest


# ---------------------------------------------------------------- data
def base():
    fn = os.path.join(CACHE, 'base.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    os.makedirs(CACHE, exist_ok=True)
    f0 = os.path.join(CACHE, 'core.pkl')
    if os.path.exists(f0):
        G, A, P, V, R, O = pickle.load(open(f0, 'rb'))
    else:
        G, A, P, V = SP.load()
        R = SP.club_ratings(G, A, V)
        A = SP.add_value(A, R)
        O, scale = SP.outcome(A, P)
        pickle.dump((G, A, P, V, R, O), open(f0, 'wb'))
    TG = SP.team_games(G)
    TR = SP.rd('transfers', usecols=['player_id', 'transfer_date', 'from_club_id', 'to_club_id', 'from_club_name',
                                    'to_club_name', 'transfer_fee', 'market_value_in_eur'])
    TR['transfer_date'] = pd.to_datetime(TR.transfer_date, errors='coerce')
    # dump lineups: position, shirt number and armband for the dump-league games
    lu = SP.rd('game_lineups', usecols=['game_id', 'player_id', 'type', 'position', 'number', 'team_captain'], low_memory=False)
    lu = lu[lu.game_id.isin(A.game_id)].drop_duplicates(['game_id', 'player_id'])
    pl = SP.rd('players', usecols=['player_id', 'foot'])
    b = dict(G=G, A=A, P=P, V=V, R=R, O=O, TG=TG, TR=TR, lu=lu, foot=pl.set_index('player_id').foot)
    pickle.dump(b, open(fn, 'wb'))
    return b


def youth_apps():
    G, A = SP.tm_games(YQ, range(2010, 2027))
    if not len(A):
        return pd.DataFrame(columns=['player_id', 'date', 'comp', 'mins', 'age'])
    A = A.merge(G[['game_id', 'comp', 'date']], on='game_id')
    return A[A.mins > 0][['player_id', 'date', 'comp', 'mins', 'age', 'gl', 'ast']]


def understat(A, P):
    """Understat season lines (big five, 2014-15 on) joined to Transfermarkt ids: same league season, matching
    name, minutes within 15%"""
    rows = []
    for c, lg in USL.items():
        for end in range(2015, 2027):
            fn = os.path.join(US, f'{lg}_{end}.json.gz')
            if not os.path.exists(fn):
                continue
            for p in json.load(gzip.open(fn, 'rt'))['players']:
                rows.append({'comp': c, 'season': end - 1, 'name': p['player_name'], 'time': float(p['time']),
                             'npxg': float(p['npxG']), 'xa': float(p['xA']), 'chain': float(p['xGChain']),
                             'build': float(p['xGBuildup']), 'shots': float(p['shots']), 'kp': float(p['key_passes'])})
    U = pd.DataFrame(rows)
    tm = A[A.comp.isin(USL) & A.mins.gt(0)].groupby(['comp', 'season', 'player_id']).mins.sum().reset_index()
    tm['name'] = tm.player_id.map(P.name)
    out = []
    for (c, s), u in U.groupby(['comp', 'season']):
        t = tm[(tm.comp == c) & (tm.season == s) & tm.name.notna()]
        m = NM.Matcher(t.to_dict('records'), name='name', team='mins', pos=None, id=None, sport='soccer',
                       team_eq=lambda want, have: abs(want - have) <= .15 * max(want, have) + 90)
        for r in u.itertuples():
            hit, _ = m.find(r.name, team=r.time)
            if hit:
                out.append({**r._asdict(), 'player_id': hit['player_id']})
    J = pd.DataFrame(out).drop(columns=['Index'])
    print('understat', len(U), 'lines,', len(J), 'joined', flush=True)
    return J


# ---------------------------------------------------------------- candidate features at a snapshot
def extras(b, X, t, snap, Y, U, parent):
    A, P, V, TR, lu, TG = b['A'], b['P'], b['V'], b['TR'], b['lu'], b['TG']
    snap = pd.Timestamp(snap)
    ids = X.index
    E = pd.DataFrame(index=ids)
    win = A[A.player_id.isin(ids) & A.season.isin([t - 1, t]) & (A.date < snap)]
    val = win[win.comp.isin(SP.VALUE)]
    apps = val[val.mins > 0]
    n = apps.groupby('player_id').size()
    st = apps.groupby('player_id').start.sum()
    E['start_sh'] = ((st / n).where(n >= 3) - .6).reindex(ids).fillna(0)
    E['sub_n'] = np.log1p((n - st).reindex(ids).fillna(0))
    # age-adjusted playing time: this season's league share x years under 21
    E['young_share'] = X.share_td_ * (21 - X.age).clip(lower=0) if 'share_td_' in X else 0
    # positions started (Transfermarkt lineup slots) in league games
    lw = lu[lu.player_id.isin(ids) & lu.game_id.isin(win.game_id) & lu.type.eq('starting_lineup')]
    pos_d = lw.groupby('player_id').position.nunique()
    pos_f = win[win.start.eq(1) & win.pos.notna()].groupby('player_id').pos.nunique()
    E['npos'] = pos_d.reindex(ids).fillna(pos_f.reindex(ids)).fillna(0).clip(upper=4)
    E['multi_pos'] = (E.npos >= 3).astype(float)
    # first-team shirt number (1-25) and armband in dump-league lineups
    lw2 = lu[lu.player_id.isin(ids) & lu.game_id.isin(win.game_id)].copy()
    lw2['num'] = pd.to_numeric(lw2.number, errors='coerce')
    nm = lw2.groupby('player_id').num.median()
    E['low_num'] = ((nm <= 25).astype(float) - (nm > 25).astype(float)).reindex(ids).fillna(0)
    E['captain'] = (lw2.groupby('player_id').team_captain.sum() > 0).astype(float).reindex(ids).fillna(0)
    # matchday-squad absence after first appearing (injury, form): club league games he missed from his first squad game
    lg = A[A.comp.isin(SP.DUMPL + SP.FEEDV) & A.player_id.isin(ids) & A.season.eq(t) & (A.date < snap)]
    first = lg.groupby('player_id').date.min()
    club = X.club_td.dropna()
    tg = TG[TG.season.eq(t) & (TG.date < snap)]
    cg = tg.groupby('club').date.apply(np.sort)
    insq = lg.groupby('player_id').size()
    miss = {}
    for pid, c in club.items():
        if pid not in first.index or c not in cg.index:
            continue
        k = int((cg[c] >= np.datetime64(first[pid])).sum())
        if k >= 5:
            miss[pid] = max(0.0, 1 - insq.get(pid, 0) / k)
    E['absent_td'] = pd.Series(miss).reindex(ids).fillna(0)
    lg1 = A[A.comp.isin(SP.DUMPL + SP.FEEDV) & A.player_id.isin(ids) & A.season.eq(t - 1)]
    first1 = lg1.groupby('player_id').date.min()
    tg1 = TG[TG.season.eq(t - 1)]
    cg1 = tg1.groupby('club').date.apply(np.sort)
    insq1 = lg1.groupby('player_id').size()
    miss1 = {}
    for pid, c in X.club1.dropna().items():
        if pid not in first1.index or c not in cg1.index:
            continue
        k = int((cg1[c] >= np.datetime64(first1[pid])).sum())
        if k >= 10:
            miss1[pid] = max(0.0, 1 - insq1.get(pid, 0) / k)
    E['absent1'] = pd.Series(miss1).reindex(ids).fillna(0)
    # league strength (the board's lg_share since Oct 24 2026): his club against his league
    R = b['R']
    lgr = R[R.season.eq(t - 1)].groupby('comp').r.mean()
    E['club_vs_lg'] = (X.rclub_td - X.comp_td.map(lgr)).fillna(0).clip(-3, 3) * (X.share_td_ > 0)
    # market value path: last six months, peak to now, value rank within his club
    vv = V[V.player_id.isin(ids) & (V.date <= snap)]
    v6 = vv[vv.date <= snap - pd.Timedelta(days=182)].groupby('player_id').mv.last()
    now = X.mv
    E['dmv6'] = np.log(now.clip(lower=25000) / v6.reindex(ids).clip(lower=25000)).where(now.notna() & v6.reindex(ids).notna()).fillna(0)
    pk = vv.groupby('player_id').mv.max().reindex(ids)
    E['off_peak'] = np.log(pk.clip(lower=25000) / now.clip(lower=25000)).where(now.notna() & pk.notna()).fillna(0)
    vc = pd.DataFrame({'club': X.club_td.fillna(X.club1), 'mv': now})
    E['club_mv_rank'] = vc.groupby('club').mv.rank(pct=True).fillna(0) - .5 * vc.mv.notna()
    # youth internationals (UEFA U17/U19/U21 qualifiers before the snapshot)
    y = Y[Y.player_id.isin(ids) & (Y.date < snap)]
    for c in YQ:
        E['yi_' + c[:3].lower()] = np.log1p(y[y.comp.eq(c)].groupby('player_id').size().reindex(ids).fillna(0))
    yy = y.merge(P[['dob']], left_on='player_id', right_index=True)
    up = yy[(yy.comp.eq('U21Q') & ((yy.date - yy.dob).dt.days / 365.25 < 19.5))
            | (yy.comp.eq('U19Q') & ((yy.date - yy.dob).dt.days / 365.25 < 17.5))]
    E['yi_up'] = np.log1p(up.groupby('player_id').size().reindex(ids).fillna(0))
    E['yi_any'] = (y.groupby('player_id').size().reindex(ids).fillna(0) > 0).astype(float)
    # Understat per 90 last season (big five, 450+ minutes)
    u = U[U.season.eq(t - 1) & U.player_id.isin(ids)].groupby('player_id')[['time', 'npxg', 'xa', 'chain', 'build', 'shots', 'kp']].sum()
    u = u[u.time >= 450]
    p90 = lambda c: (u[c] / u.time * 90).reindex(ids).fillna(0)
    E['us_xgxa'] = p90('npxg') + p90('xa')
    E['us_chain'] = p90('chain')
    E['us_build'] = p90('build')
    E['us_kp'] = p90('kp')
    E['us_xgxa_fwd'] = E.us_xgxa * X.grp.eq('F')
    E['us_has'] = pd.Series(1.0, index=u.index).reindex(ids).fillna(0)
    # debut: age at first senior minutes in the data (seasons from 2012), years since
    s = A[A.player_id.isin(ids) & A.comp.isin(SP.VALUE) & A.mins.gt(0) & (A.date < snap)].groupby('player_id').date.min()
    dage = (s - P.dob.reindex(s.index)).dt.days / 365.25
    E['debut_age'] = (dage.reindex(ids) - 18).fillna(0).clip(-3, 4) * dage.reindex(ids).notna()
    E['debuted'] = dage.reindex(ids).notna().astype(float)
    E['debut_young'] = (dage.reindex(ids) < 18).astype(float)
    # relative age: birth month inside the youth calendar year (Jan 1 cut)
    m = P.dob.reindex(ids).dt.month
    E['late_born'] = ((m >= 10).astype(float) - (m <= 3).astype(float)).fillna(0)
    E['birth_q'] = ((m - 1) // 3).fillna(1.5) - 1.5
    # foot: left-footed, missing = the share of known left feet
    ft = b['foot'].reindex(ids)
    known = ft.isin(['left', 'right', 'both'])
    E['left'] = np.where(known, ft.eq('left').astype(float), (b['foot'] == 'left').mean() / max(b['foot'].isin(['left', 'right', 'both']).mean(), 1e-9))
    E['two_foot'] = np.where(known, ft.eq('both').astype(float), 0.03)
    # height, missing = the mean of the known (the board fills 181 cm); and a version with the missing flag kept for
    # the leak check (not a candidate)
    ht = P.height_in_cm.reindex(ids)
    E['ht_mean'] = ((ht - 181) / 7).fillna((P.height_in_cm.mean() - 181) / 7)
    E['_noht'] = ht.isna().astype(float)
    # transfers (dump coverage only): fee over market value, club moves, loans from a stronger club
    dl = A[A.comp.isin(SP.DUMPL) & A.mins.gt(0) & (A.date < snap) & A.season.ge(t - 1)].player_id.unique()
    tr = TR[TR.player_id.isin(ids) & (TR.transfer_date <= snap)]
    last = tr[tr.transfer_date > snap - pd.Timedelta(days=150)].sort_values('transfer_date').groupby('player_id').tail(1).set_index('player_id')
    prem = np.log((last.transfer_fee.clip(lower=1e5)) / last.market_value_in_eur.clip(lower=1e5)).where(last.transfer_fee > 0)
    E['fee_prem'] = np.where(ids.isin(dl), prem.reindex(ids).fillna(0), 0)
    # leak checks (not candidates): any transfer on record, and the summer fee the board used to take
    E['_has_tr'] = np.where(ids.isin(dl), ids.isin(tr.player_id).astype(float), 0)
    E['_fee'] = np.where(ids.isin(dl), np.log1p(last.transfer_fee.reindex(ids).fillna(0) / 1e6), 0)
    nmov = tr[tr.transfer_date > snap - pd.Timedelta(days=730)].groupby('player_id').size()
    E['moves2y'] = np.where(ids.isin(dl), np.log1p(nmov.reindex(ids).fillna(0)), 0)
    # loan: this summer's free move out of a club (or its youth/reserve side) that rates higher than the new one
    r1 = R[R.season.eq(t - 1)].set_index('club').r
    fl = last[last.transfer_fee.fillna(0).eq(0)]
    src = fl.from_club_name.map(lambda s: parent.get(_base_club(s))).fillna(fl.from_club_id)
    pr = src.map(r1)
    dst = fl.to_club_id.map(r1)
    gap = (pr - dst).where(pr.notna() & dst.notna())
    E['loan_down'] = np.where(ids.isin(dl), gap.clip(lower=0).reindex(ids).fillna(0), 0)
    E['loan_big'] = np.where(ids.isin(dl), ((gap > 1) & (pr > -1)).astype(float).reindex(ids).fillna(0), 0)
    # academy: the latest youth/reserve club he came through, rated as its first team
    yt = tr[tr.from_club_name.fillna('').str.contains(YRX, regex=True)].sort_values('transfer_date').groupby('player_id').tail(1)
    ac = yt.set_index('player_id').from_club_name.map(lambda s: parent.get(_base_club(s))).map(r1)
    E['academy_r'] = np.where(ids.isin(dl), (ac.reindex(ids) + 2.5).clip(lower=0).fillna(0), 0)
    return E


YRX = r'(?i)\b(?:U\d\d|Yth\.?|Youth|B|II|Res\.?|Reserves|Jgd\.?|Juv\.?|Primavera|Sub-\d\d|Next Gen)\b'


def _base_club(s):
    import re
    return re.sub(r'\s+', ' ', re.sub(YRX, '', str(s))).strip().lower()


def parents(TR):
    """club name (youth/reserve tags stripped) -> club id, from first-team names in the transfer table"""
    d = pd.concat([TR[['from_club_name', 'from_club_id']].set_axis(['n', 'i'], axis=1),
                   TR[['to_club_name', 'to_club_id']].set_axis(['n', 'i'], axis=1)]).dropna()
    d = d[~d.n.str.contains(YRX, regex=True)]
    d['k'] = d.n.map(_base_club)
    return d.groupby('k').i.agg(lambda s: s.value_counts().index[0]).to_dict()


# ---------------------------------------------------------------- rows
def rows(b):
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    Y = youth_apps()
    print('youth apps', len(Y), Y.comp.value_counts().to_dict() if len(Y) else {}, flush=True)
    U = understat(b['A'], b['P'])
    par = parents(b['TR'])
    done = b['O'][b['O'].s22 <= SP.COHORTS[1]]
    out = {}
    for md in [SP.SEL_SNAP, (1, 15)]:
        xs = []
        for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
            snap = SP.snapdate(t, md)
            X = SP.features(b['A'], b['P'], b['V'], b['R'], b['TG'], t, snap)
            X = X[X.index.isin(done.index)]
            F = SP.design(X)
            X['share_td_'] = F.share_td
            E = extras(b, X, t, snap, Y, U, par)
            Z = pd.concat([F, E], axis=1)
            Z['fv_out'] = done.fv.reindex(X.index)
            Z['t'] = t
            xs.append(Z)
            print('rows', md, t, len(Z), flush=True)
        out[md] = pd.concat(xs)
    pickle.dump(out, open(fn, 'wb'))
    return out


# ---------------------------------------------------------------- tests
def top50(p, y, t, k=50):
    return float(np.mean([y[t == s][np.argsort(-p[t == s])[:k]].mean() for s in np.unique(t)]))


def test(Z, kept, cand, seasons=None):
    if seasons is not None:
        Z = Z[Z.t.isin(seasons)]
    y, t = Z.fv_out.values, Z.t.values
    e0, p0 = SP.loso(Z, y, t, kept)
    e1, p1 = SP.loso(Z, y, t, kept + cand)
    d = e0 ** 2 - e1 ** 2
    ss = np.unique(t)
    per = np.array([d[t == s].mean() for s in ss])
    tt = per.mean() / (per.std(ddof=1) / math.sqrt(len(per)) + 1e-12)
    tr, te = Z.t.between(*FWD).values, ~Z.t.between(*FWD).values
    if seasons is not None and te.sum() == 0:
        tr = Z.t.values < ss[-2]
        te = ~tr
    b0, b1 = SP.ols(Z[tr], y[tr], kept), SP.ols(Z[tr], y[tr], kept + cand)
    f0, f1 = SP.pred(Z[te], kept, b0), SP.pred(Z[te], kept + cand, b1)
    coef = dict(zip(['const'] + kept + cand, SP.ols(Z, y, kept + cand)))
    r = {'gain': round(float(d.mean()), 3), 't': round(float(tt), 2), 'wins': int((per > 0).sum()), 'of': len(per),
         'top50': round(top50(p1, y, t) - top50(p0, y, t), 2), 'top100': round(top50(p1, y, t, 100) - top50(p0, y, t, 100), 2),
         'fwdMse': round(float(((y[te] - f1) ** 2).mean() - ((y[te] - f0) ** 2).mean()), 3),
         'fwdTop50': round(top50(f1, y[te], t[te]) - top50(f0, y[te], t[te]), 2),
         'coef': {c: round(float(coef[c]), 3) for c in cand}, 'nz': int((Z[cand].abs().sum(axis=1) > 0).sum()),
         'seasons': [int(ss[0]), int(ss[-1])]}
    r['cv'] = r['t'] >= 2 and r['wins'] >= math.ceil(r['of'] * 2 / 3)
    r['pass'] = r['cv'] and r['top50'] >= 0 and r['fwdMse'] <= 0 and r['fwdTop50'] >= -.1
    return r


CANDS = [
    (['start_sh'], None), (['sub_n'], None), (['young_share'], None), (['npos'], None), (['multi_pos'], None),
    (['low_num'], None), (['captain'], None), (['absent_td'], None), (['absent1'], None),
    (['club_vs_lg'], None), (['dmv6'], None), (['off_peak'], None), (['club_mv_rank'], None),
    (['yi_u21'], None), (['yi_u19'], None), (['yi_u17'], None), (['yi_up'], None), (['yi_any'], None),
    (['yi_u21', 'yi_u19', 'yi_u17'], None),
    (['us_xgxa'], range(2015, 2021)), (['us_chain'], range(2015, 2021)), (['us_build'], range(2015, 2021)),
    (['us_kp'], range(2015, 2021)), (['us_xgxa_fwd'], range(2015, 2021)), (['us_has'], range(2015, 2021)),
    (['debut_age'], range(2016, 2021)), (['debut_young'], range(2016, 2021)),
    (['late_born'], None), (['birth_q'], None), (['left'], None), (['two_foot'], None),
    (['fee_prem'], None), (['moves2y'], None), (['loan_down'], None), (['loan_big'], None), (['academy_r'], None),
]


def main():
    b = base()
    print('base loaded', flush=True)
    R = rows(b)
    fitj = json.load(open(os.path.join(ROOT, 'data', 'soccer_prospects_fit.json')))
    kept = [c for c in fitj['kept']]
    out = {'kept': kept, 'snap': {}}
    for md, Z in R.items():
        key = '%02d-%02d' % md
        y, t = Z.fv_out.values, Z.t.values
        e, p = SP.loso(Z, y, t, kept)
        res = {'n': int(len(Z)), 'mse': round(float((e ** 2).mean()), 2), 'top50': round(top50(p, y, t), 2)}
        # leak checks: the missing-height flag; height filled at the mean of the known instead of 181 cm; any
        # transfer on record (the dump's transfer table); the summer fee alone and given a record
        res['leaks'] = {'noht': test(Z, kept, ['_noht']), 'has_tr': test(Z, kept, ['_has_tr']),
                        'fee': test(Z, kept, ['_fee']), 'fee_given_record': test(Z, kept + ['_has_tr'], ['_fee'])}
        Zm = Z.copy()
        Zm['ht'] = Zm.ht_mean
        e2, p2 = SP.loso(Zm, y, t, kept)
        res['leaks']['ht_mean_fill'] = {'mse': round(float((e2 ** 2).mean()), 2), 'top50': round(top50(p2, y, t), 2)}
        res['cands'] = {}
        for cols, ss in CANDS:
            r = test(Z, kept, cols, list(ss) if ss else None)
            res['cands']['+'.join(cols)] = r
            print(key, '+'.join(cols), r, flush=True)
        out['snap'][key] = res
    json.dump(out, open(OUT, 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
