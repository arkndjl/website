#!/usr/bin/env python3
"""Tennis prospects ARKBOARD (Noah, Oct 26 2026): every ATP and WTA player under the age cut, graded on the shared
20-80 FV value scale against what past prospects with the same profile became.

    python3 scripts/tennis_prospects.py --rows     # history -> snapshot rows (scripts/.cache/tennis/rows.pkl)
    python3 scripts/tennis_prospects.py --fit      # outcome, driver selection, hurdle model -> data/tennis_prospects_fit.json
    python3 scripts/tennis_prospects.py            # today's grades -> data/tennis_prospects.json

Data      Jeff Sackmann's ATP and WTA files (CC BY-NC-SA 4.0; the GitHub repos went offline in 2026, read from the
          Hugging Face mirror datasets/Aneeshers/tennis-sackmann-archive): weekly rankings, every main-draw, qualifying,
          Challenger / WTA 125, Futures / ITF match since 1991, birth dates. Cached in scripts/.cache/tennis/sackmann.
Value     Ranking points above replacement (the rank-200 player's points that season), at the year-end ranking,
          as a share of the top 100's mean surplus that season (an average top-100 player = 1), which washes out the
          points-table changes (ATP 2009, WTA 2016) and puts ATP and WTA alike.
Outcome   Peak value: the mean of the best three seasons at ages 22-28 (age on July 1), missing seasons 0.
FV scale  By rarity within a birth year and tour (Noah, Oct 26 2026: tennis's own scale, not the cross-sport value
          scale), births 1979-97: 80 = one in eight birth years (an all-time great), 75 = one in four (a No. 1),
          70 = one in two (a top-5 peak), 65 = the best of a birth year, 60 = top 2 (a top-10 peak), 55 = top 4
          (top 30), 50 = top 7 (top 50), 45 = top 10 (top 75), 40 = top 13 (a top-100 tour regular); below that
          20 (no value) to 40 by peak. Steps of 1.
Model     Hurdle: logistic P(any peak value) and OLS on outcome FV given value, on what was known at the snapshot.
          FV = the mean outcome, (1 - p) x 20 + p x the mean given value; ranges and tier odds from the same mixture
          with out-of-sample residuals. Inputs kept when they cut leave-one-birth-year-out error with t >= 2, win two
          thirds of the years and do not hurt the forward test (fit on births to 1993, grade 1994-97).
"""
import datetime as dt
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
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'tennis')
SACK = os.path.join(CACHE, 'sackmann')
MIRROR = 'https://huggingface.co/datasets/Aneeshers/tennis-sackmann-archive/resolve/main/'
ROWS = os.path.join(CACHE, 'rows.pkl')
FIT = os.path.join(ROOT, 'data', 'tennis_prospects_fit.json')
OUT = os.path.join(ROOT, 'data', 'tennis_prospects.json')

FIRST = 1991
REPL_RANK = 200
REG = 100
PEAK_AGES = (22, 28)
CUTS = [(80, .125), (75, .25), (70, .5), (65, 1), (60, 2), (55, 4), (50, 7), (45, 10), (40, 13)]

# levels: G slam, M masters/1000, A tour, F finals, D team, C challenger/125, S futures/ITF, Q tour qualifying
LEVEL = {'G': 'T', 'M': 'T', 'A': 'T', 'F': 'T', 'D': 'D', 'P': 'T', 'PM': 'T', 'I': 'T', 'W': 'T', 'O': 'T',
         'C': 'C', 'S': 'S', '15': 'S', '25': 'S', '10': 'S', '50': 'S', '75': 'C', '100': 'C', '60': 'S', '80': 'S',
         '35': 'S', '40': 'S', '125': 'C', 'T1': 'T', 'T2': 'T', 'T3': 'T', 'T4': 'T', 'T5': 'T', 'CC': 'T'}


def read(tour, kind):
    """kind: rankings | main | qc (qualifying + challenger, or WTA qualifying + ITF) | fut"""
    d = os.path.join(SACK, tour)
    if kind == 'rankings':
        fs = sorted(glob.glob(os.path.join(d, f'{tour}_rankings_*.csv')))
        R = pd.concat([pd.read_csv(f, usecols=[0, 1, 2, 3]) for f in fs if not f.endswith('_70s.csv')])
        R.columns = ['date', 'rank', 'pid', 'pts']
        return R.drop_duplicates(['date', 'pid']).sort_values(['date', 'rank']).reset_index(drop=True)
    pat = {'main': f'{tour}_matches_[0-9]*.csv', 'qc': f'{tour}_matches_qual_*.csv',
           'fut': f'{tour}_matches_futures_*.csv'}[kind]
    out = []
    for f in sorted(glob.glob(os.path.join(d, pat))):
        y = int(f[-8:-4])
        if y < FIRST - 1:
            continue
        out.append(pd.read_csv(f, low_memory=False, dtype={'tourney_level': str, 'winner_entry': str,
                                                           'loser_entry': str, 'winner_seed': str, 'loser_seed': str}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


RORDER = {'Q1': 0, 'Q2': 1, 'Q3': 2, 'Q4': 3, 'R128': 4, 'R64': 5, 'R32': 6, 'R16': 7, 'QF': 8, 'SF': 9, 'F': 10,
          'RR': 7, 'BR': 9, 'ER': 4}


def matches(tour):
    """Every singles match since 1991 with level class (T tour main draw, Q tour qualifying, C challenger / 125,
    S futures / ITF, D team), sorted by date and round."""
    parts = []
    for kind in ('main', 'qc', 'fut'):
        M = read(tour, kind)
        if M.empty:
            continue
        lv = M.tourney_level.astype(str)
        cls = lv.map(LEVEL).fillna('X')
        if kind == 'qc':
            q = M['round'].astype(str).str.startswith('Q')
            cls = np.where(q & cls.eq('T'), 'Q', cls)
            if tour == 'wta':
                # WTA qualifying file holds tour qualifying (level of the event) and ITF events (prize levels)
                cls = np.where(q & ~lv.str.isdigit() & lv.ne('C'), 'Q', cls)
        M = M.assign(cls=cls)
        parts.append(M)
    M = pd.concat(parts, ignore_index=True)
    M = M[(M.tourney_date >= FIRST * 10000) & M.cls.ne('X')].copy()
    M['ro'] = M['round'].map(RORDER).fillna(4)
    M['date'] = pd.to_datetime(M.tourney_date.astype(int).astype(str), format='%Y%m%d')
    M = M.sort_values(['date', 'tourney_id', 'ro', 'match_num'], kind='stable').reset_index(drop=True)
    M['walk'] = M.score.astype(str).str.contains('W/O|DEF|Walkover|unfinished', case=False, na=False)
    return M


def elo(M, k0=250, off=5, shape=.4):
    """FiveThirtyEight-style Elo over every level (k = 250 / (n + 5)^.4, start 1500); Slams x1.1. Returns the pre-match
    ratings and match counts on each row, and the final dict."""
    R, N = {}, {}
    w = M.winner_id.to_numpy()
    l = M.loser_id.to_numpy()
    walk = M.walk.to_numpy()
    slam = (M.tourney_level.astype(str) == 'G').to_numpy()
    rw = np.empty(len(M))
    rl = np.empty(len(M))
    pw = np.empty(len(M))
    pl = np.empty(len(M))
    nw = np.empty(len(M), dtype=np.int32)
    nl = np.empty(len(M), dtype=np.int32)
    for i in range(len(M)):
        a, b = w[i], l[i]
        ra, rb = R.get(a, 1500.0), R.get(b, 1500.0)
        na, nb = N.get(a, 0), N.get(b, 0)
        rw[i], rl[i], nw[i], nl[i] = ra, rb, na, nb
        if walk[i]:
            pw[i], pl[i] = ra, rb
            continue
        p = 1 / (1 + 10 ** ((rb - ra) / 400))
        m = 1.1 if slam[i] else 1.0
        R[a] = pw[i] = ra + m * k0 / (na + off) ** shape * (1 - p)
        R[b] = pl[i] = rb - m * k0 / (nb + off) ** shape * (1 - p)
        N[a], N[b] = na + 1, nb + 1
    M['w_elo'], M['l_elo'], M['w_n'], M['l_n'], M['w_post'], M['l_post'] = rw, rl, nw, nl, pw, pl
    return R, N


def players(tour):
    P = pd.read_csv(os.path.join(SACK, tour, f'{tour}_players.csv'), low_memory=False)
    P = P.rename(columns={'player_id': 'pid', 'name_first': 'first', 'name_last': 'last'})
    P['dobd'] = pd.to_datetime(P.dob.dropna().astype(int).astype(str), format='%Y%m%d', errors='coerce')
    return P.set_index('pid')


def season_values(R):
    """Year-end ranking each season -> surplus over the rank-200 player's points and the TS share."""
    R = R.copy()
    R['y'] = R.date // 10000
    last = R.groupby('y').date.max()
    E = R[R.date.isin(last.values)].copy()
    # fill missing points (ATP year-ends before 1996) from the same week's rank -> points curve, or from the
    # 1999-2008 median curve of points / top-100 mean when the week has none
    ref = []
    for d, g in E.groupby('date'):
        if d // 10000 in range(1999, 2009) and g.pts.notna().mean() > .99:
            ref.append(pd.Series((g.pts / g.loc[g['rank'] <= REG, 'pts'].mean()).values, index=g['rank'].values).groupby(level=0).median())
    ref = pd.concat(ref, axis=1).median(axis=1).sort_index()
    for d, g in E.groupby('date'):
        if g.pts.isna().any():
            ok = g.dropna(subset=['pts'])
            if g.loc[g['rank'] <= REG, 'pts'].notna().mean() > .9:
                fill = np.interp(np.log(g['rank']), np.log(ok['rank']), ok.pts)
            else:
                fill = 1000 * np.interp(np.log(g['rank']), np.log(ref.index.values), ref.values)
                g = g.assign(pts=np.nan)
            E.loc[g.index, 'pts'] = g.pts.fillna(pd.Series(fill, index=g.index))
    out = []
    for y, g in E.groupby('y'):
        g = g.sort_values('rank')
        repl = g.loc[g['rank'] <= REPL_RANK, 'pts'].iloc[-1] if (g['rank'] >= REPL_RANK).any() else g.pts.min()
        sur = (g.pts - repl).clip(lower=0)
        top = sur[g['rank'] <= REG].mean()
        out.append(pd.DataFrame({'y': y, 'pid': g.pid.values, 'rank': g['rank'].values, 'pts': g.pts.values,
                                 'sur': sur.values, 'ts': .05 * sur.values / top}))
    return pd.concat(out, ignore_index=True)


def age_at(dob, d):
    return (pd.Timestamp(d) - dob).dt.days / 365.25


def peaks(S, P, ages=PEAK_AGES):
    """Mean of the best three TS seasons at ages a0-a1 (age on July 1), missing = 0, per player; and per-age TS."""
    S = S.join(P[['dobd']], on='pid')
    S = S[S.dobd.notna()]
    S['age'] = ((pd.to_datetime(S.y.astype(str) + '-07-01') - S.dobd).dt.days / 365.25).astype(float)
    S['ai'] = np.floor(S.age).astype(int)
    W = S[(S.ai >= ages[0]) & (S.ai <= ages[1])]
    pk = W.groupby('pid').ts.apply(lambda s: np.sort(s.values)[::-1][:3].sum() / 3)
    return pk, S


def games(score):
    """Games and tiebreaks won by the winner and the loser from a score string ('7-6(5) 3-6 6-4', RET kept)."""
    gw = gl = tw = tl = 0
    for st in str(score).split():
        a, _, b = st.partition('-')
        b = b.split('(')[0]
        if not (a.isdigit() and b.isdigit()):
            continue
        a, b = int(a), int(b)
        if a > 7 or b > 7:          # match tiebreak or long set: one game to the set winner
            a, b = (1, 0) if a > b else (0, 1)
        gw, gl = gw + a, gl + b
        if (a, b) == (7, 6):
            tw += 1
        elif (a, b) == (6, 7):
            tl += 1
    return gw, gl, tw, tl


def long(M):
    """One row per player per match: pid, date, class, won, opponent rank and Elo, post-match Elo, serve and return
    points."""
    cols = ['date', 'cls', 'tourney_level', 'round', 'walk', 'surface']
    G = np.array([games(x) for x in M.score.values], dtype=float)
    out = []
    for me, op, won in (('winner', 'loser', 1), ('loser', 'winner', 0)):
        a, b = me[0], op[0]
        d = M[cols].copy()
        d['pid'] = M[f'{me}_id'].values
        d['opp'] = M[f'{op}_id'].values
        d['won'] = won
        d['orank'] = M[f'{op}_rank'].values
        d['elo_pre'] = M[f'{a}_elo'].values
        d['oelo'] = M[f'{b}_elo'].values
        d['elo'] = M[f'{a}_post'].values
        d['svpt'] = M[f'{a}_svpt'].values
        d['svw'] = (M[f'{a}_1stWon'] + M[f'{a}_2ndWon']).values
        d['rtpt'] = M[f'{b}_svpt'].values
        d['rtw'] = (M[f'{b}_svpt'] - M[f'{b}_1stWon'] - M[f'{b}_2ndWon']).values
        d['ace'] = M[f'{a}_ace'].values
        d['age'] = M[f'{me}_age'].values
        d['ht'] = M[f'{me}_ht'].values
        d['ioc'] = M[f'{me}_ioc'].values
        d['hand'] = M[f'{me}_hand'].values
        d['entry'] = M[f'{me}_entry'].astype(str).str.strip().str.upper().values
        d['gw'], d['gl'] = (G[:, 0], G[:, 1]) if won else (G[:, 1], G[:, 0])
        d['tbw'], d['tbl'] = (G[:, 2], G[:, 3]) if won else (G[:, 3], G[:, 2])
        d['i'] = M.index.values
        out.append(d)
    L = pd.concat(out, ignore_index=True).sort_values(['i', 'won']).reset_index(drop=True)
    return L



GSLOPE = {'atp': .00043, 'wta': .00053}   # game share per Elo point of gap (OLS on 2010-19 matches)
AGE_CUT = 22          # under 22 on July 1 of the season (the outcome window starts the next season)
SNAPS = [(1, 15), (4, 15), (7, 1), (10, 26)]
SEL_SNAP = (10, 26)


def snapdate(season, md):
    return pd.Timestamp(season, *md)


def features(R, L, P, D, season, tour, ages=(14, AGE_CUT)):
    """Every player under the age cut on July 1 of `season` with a ranking or a pro match in the 52 weeks before D,
    described from what was known at D (matches count once their event week is over: event start <= D - 7 days)."""
    D = pd.Timestamp(D)
    di = int(D.strftime('%Y%m%d'))
    jul = pd.Timestamp(season, 7, 1)
    age = ((jul - P.dobd).dt.days / 365.25).rename('age')
    young = age[(age >= ages[0]) & (age < ages[1])]
    Lp = L[(L.date <= D - pd.Timedelta(days=7)) & L.pid.isin(young.index)]
    Ly = Lp[Lp.date > D - pd.Timedelta(days=365)]
    Rp = R[(R.date <= di) & R.pid.isin(young.index)]
    rd = Rp.date.max() if len(Rp) else None
    X = pd.DataFrame(index=pd.Index(sorted(set(Ly.pid) | set(Rp.loc[Rp.date > di - 10000, 'pid'])), name='pid'))
    if not len(X.index):
        return X
    X['age'] = young.reindex(X.index)
    X['agesnap'] = ((D - P.dobd.reindex(X.index)).dt.days / 365.25).values
    now = Rp[Rp.date == rd].set_index('pid') if rd else pd.DataFrame(columns=['rank', 'pts'])
    X['rank'] = now['rank'].reindex(X.index)
    X['pts'] = now['pts'].reindex(X.index)
    X['best'] = Rp.groupby('pid')['rank'].min().reindex(X.index)
    ago = Rp[Rp.date <= di - 10000]
    if len(ago):
        a = ago[ago.date == ago.date.max()].set_index('pid')
        X['rank1'] = a['rank'].reindex(X.index)
    else:
        X['rank1'] = np.nan
    X['wkr'] = Rp[Rp.date > di - 10000].groupby('pid').size().reindex(X.index).fillna(0)
    g = Lp.groupby('pid')
    X['elo'] = g.elo.last().reindex(X.index)
    X['elon'] = g.size().reindex(X.index).fillna(0)
    X['elopk'] = g.elo.max().reindex(X.index)
    X['first'] = (g.date.min().reindex(X.index) - P.dobd.reindex(X.index)).dt.days / 365.25
    old = Lp[Lp.date <= D - pd.Timedelta(days=365)].groupby('pid').elo.last()
    X['elo1'] = old.reindex(X.index)
    nw = Ly[~Ly.walk]
    for c in 'TQCSD':
        q = nw[nw.cls == c].groupby('pid').won
        X['n' + c] = q.size().reindex(X.index).fillna(0)
        X['w' + c] = q.sum().reindex(X.index).fillna(0)
    t = nw[(nw['round'] == 'F') & (nw.won == 1)].groupby(['pid', 'cls']).size().unstack()
    for c in 'CS':
        X['t' + c] = t[c].reindex(X.index).fillna(0) if c in t else 0
    X['n'] = nw.groupby('pid').size().reindex(X.index).fillna(0)
    X['w'] = nw.groupby('pid').won.sum().reindex(X.index).fillna(0)
    X['w100'] = nw[nw.orank <= 100].groupby('pid').won.sum().reindex(X.index).fillna(0)
    X['tcar'] = Lp[(Lp.cls == 'T') & ~Lp.walk].groupby('pid').size().reindex(X.index).fillna(0)
    X['ocar'] = Lp[~Lp.walk].groupby('pid').oelo.mean().reindex(X.index)
    st = nw[nw.svpt > 0].groupby('pid')[['svpt', 'svw', 'rtpt', 'rtw', 'ace']].sum().reindex(X.index)
    X['svpt'] = st.svpt.fillna(0)
    X['spw'] = st.svw / st.svpt
    X['rpw'] = st.rtw / st.rtpt
    X['acer'] = st.ace / st.svpt
    X['ox'] = nw.groupby('pid').oelo.mean().reindex(X.index)
    # game share above what the Elo gap predicts (GD+ source), tiebreak record, entries, surfaces
    gg = nw[(nw.gw + nw.gl) > 0]
    gsh = gg.gw / (gg.gw + gg.gl)
    exp = .5 + GSLOPE[tour] * (gg.elo_pre - gg.oelo).clip(-600, 600)
    X['gdx'] = (gsh - exp).groupby(gg.pid).sum().reindex(X.index).fillna(0)
    X['gn'] = gg.groupby('pid').size().reindex(X.index).fillna(0)
    X['tbw'] = nw.groupby('pid').tbw.sum().reindex(X.index).fillna(0)
    X['tbl'] = nw.groupby('pid').tbl.sum().reindex(X.index).fillna(0)
    X['upw'] = nw[(nw.won == 1) & (nw.oelo > nw.elo_pre + 100)].groupby('pid').size().reindex(X.index).fillna(0)
    L2 = Lp[Lp.date > D - pd.Timedelta(days=730)]
    X['je'] = L2[L2.entry.isin(['JE', 'JR', 'ITF'])].groupby('pid').size().reindex(X.index).fillna(0)
    X['wc'] = Ly[Ly.entry == 'WC'].groupby('pid').size().reindex(X.index).fillna(0)
    X['clay'] = (nw.surface == 'Clay').groupby(nw.pid).mean().reindex(X.index)
    X['ht'] = P.height.reindex(X.index)
    X['hand'] = P.hand.reindex(X.index)
    X['ioc'] = P.ioc.reindex(X.index)
    X['season'] = season
    return X




# ------------------------------------------------------------------------------------------------ history -> rows

TOURS = ('atp', 'wta')
COHORTS = (1979, 1997)        # birth years whose ages 22-28 all fall in 2001-2025
FWD = 1993                    # forward test: fit on births through 1993, grade 1994-97
BASE_PKL = os.path.join(CACHE, 'base.pkl')


def download():
    """the Sackmann mirror's ATP and WTA files (singles, 1990+) into scripts/.cache/tennis/sackmann"""
    import urllib.request
    tree = json.load(urllib.request.urlopen(
        'https://huggingface.co/api/datasets/Aneeshers/tennis-sackmann-archive/tree/main?recursive=1', timeout=60))
    for x in tree:
        p = x['path']
        if x['type'] != 'file' or p.split('/')[0] not in TOURS or 'doubles' in p or 'amateur' in p:
            continue
        if any(f'_19{d}' in p for d in range(68, 90)) or p.endswith('_70s.csv') or p.endswith('_80s.csv'):
            continue
        dst = os.path.join(SACK, p)
        if os.path.exists(dst) and os.path.getsize(dst) == x.get('size'):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.system(f'curl -sSL --retry 3 -o "{dst}" "{MIRROR}{p}"')


def base(refresh=False):
    if os.path.exists(BASE_PKL) and not refresh:
        return pickle.load(open(BASE_PKL, 'rb'))
    out = {}
    for tour in TOURS:
        M = matches(tour)
        R = read(tour, 'rankings')
        P = players(tour)
        elo(M)
        out[tour] = dict(M=M, R=R, P=P, S=season_values(R), L=long(M))
    pickle.dump(out, open(BASE_PKL, 'wb'))
    return out


def build_rows():
    B = base()
    rows = {}
    for tour in TOURS:
        b = B[tour]
        pk, _ = peaks(b['S'], b['P'])
        last = b['L'].date.max()
        out = []
        for season in range(1993, 2027):
            for md in SNAPS:
                D = snapdate(season, md)
                if D > last:
                    continue
                X = features(b['R'], b['L'], b['P'], D, season, tour)
                X['snap'] = '%02d-%02d' % md
                out.append(X)
        X = pd.concat(out).reset_index()
        X['by'] = b['P'].dobd.reindex(X.pid).dt.year.values
        X['pk'] = X.pid.map(pk).fillna(0)
        rows[tour] = X
        print(tour, len(X), 'rows')
    pickle.dump(rows, open(ROWS, 'wb'))
    return rows


# ------------------------------------------------------------------------------------------------ inputs

MAXR = 2500
BASEF = ['age', 'lr', 'unr']
# hindsight leaks, never inputs: Sackmann fills in heights (and hands) mostly for players who went on to make it, so
# "no listed height" was worth +3.4 FV (ATP, t 6.6) and +6.2 (WTA, t 8.6) out of sample, and a height filled in at
# the mean rides on the same record
LEAKS = ['noht', 'ht']


def design(X):
    F = pd.DataFrame(index=X.index)
    a = X.age - 18
    F['age'] = a
    F['age2'] = a * a
    lr = np.log(X['rank'].fillna(MAXR).clip(upper=MAXR)) - 6
    F['lr'] = lr
    F['unr'] = X['rank'].isna().astype(float)
    F['lr2'] = lr * lr
    F['lr_age'] = lr * a
    F['lpts'] = np.log1p(X.pts.fillna(0))
    F['lbest'] = np.log(X.best.fillna(MAXR).clip(upper=MAXR)) - 6 - lr
    F['dr'] = np.log(X.rank1.fillna(MAXR).clip(upper=MAXR)) - 6 - lr
    F['wkr'] = X.wkr / 52
    n = X.elon
    e = (X.elo.fillna(1500) - 1500) / 100
    F['elo'] = e
    F['elo_age'] = e * a
    F['elo2'] = e * e
    F['elos'] = e * n / (n + 20)
    F['lelon'] = np.log1p(n)
    F['delo'] = (X.elo - X.elo1).fillna(0) / 100
    F['elopk'] = (X.elopk.fillna(1500) - X.elo.fillna(1500)) / 100
    F['first'] = X['first'].fillna(X.agesnap) - X.agesnap
    for c in 'TQCS':
        F['ln' + c] = np.log1p(X['n' + c])
        F['wp' + c] = ((X['w' + c] + 1) / (X['n' + c] + 2) - .5) * np.log1p(X['n' + c])
    F['wpall'] = ((X.w + 1) / (X.n + 2) - .5) * np.log1p(X.n)
    F['tC'] = np.log1p(X.tC)
    F['tS'] = np.log1p(X.tS)
    F['w100'] = np.log1p(X.w100)
    F['ltcar'] = np.log1p(X.tcar)
    F['ox'] = (X.ox.fillna(1500) - 1500) / 100
    st = X.svpt >= 150
    F['spw'] = np.where(st, (X.spw - .6) * 10, 0)
    F['rpw'] = np.where(st, (X.rpw - .38) * 10, 0)
    F['stx'] = st.astype(float)
    F['acer'] = np.where(st, (X.acer - .06) * 10, 0)
    F['gdx'] = X.gdx / (X.gn + 10) * 10
    F['tbluck'] = (X.tbw - X.tbl) / (X.tbw + X.tbl + 4)
    F['upw'] = np.log1p(X.upw)
    F['je'] = (X.je > 0).astype(float)
    F['wc'] = np.log1p(X.wc)
    F['clay'] = X.clay.fillna(.4) - .4
    F['lefty'] = (X.hand == 'L').astype(float)
    F['big'] = X.ioc.isin({'USA', 'ESP', 'FRA', 'ITA', 'GER', 'AUS', 'RUS', 'ARG', 'GBR', 'CZE', 'JPN', 'CHN'}).astype(float)
    F['ht'] = ((X.ht - 183) / 10).fillna(0)
    F['noht'] = X.ht.isna().astype(float)
    return F


NAMES = {'age': 'age (July 1)', 'age2': 'age, squared', 'lr': 'ranking (log)', 'unr': 'unranked', 'lr2': 'ranking, squared',
         'lr_age': 'ranking x age', 'lpts': 'ranking points (log)', 'lbest': 'career-high ranking', 'dr': 'ranking change on the year',
         'wkr': 'weeks ranked in the last year', 'elo': 'Elo, every level', 'elo_age': 'Elo x age', 'elo2': 'Elo, squared',
         'elos': 'Elo shrunk by matches played', 'lelon': 'pro matches, career (log)', 'delo': 'Elo change on the year',
         'elopk': 'Elo below its peak', 'first': 'years since the first pro match', 'lnT': 'tour main-draw matches',
         'wpT': 'tour main-draw win rate', 'lnQ': 'tour qualifying matches', 'wpQ': 'tour qualifying win rate',
         'lnC': 'Challenger / 125 matches', 'wpC': 'Challenger / 125 win rate', 'lnS': 'Futures / ITF matches',
         'wpS': 'Futures / ITF win rate', 'wpall': 'win rate, every level, last year', 'tC': 'Challenger / 125 titles',
         'tS': 'Futures / ITF titles', 'w100': 'wins over the top 100', 'ltcar': 'tour main-draw matches, career',
         'ox': 'opponents\' mean Elo', 'spw': 'serve points won', 'rpw': 'return points won', 'stx': 'has serve stats',
         'acer': 'ace rate', 'gdx': 'game dominance (games won over what the Elo gap predicts)', 'tbluck': 'tiebreak record',
         'upw': 'upset wins (100+ Elo up)', 'je': 'junior exempt entry (top juniors)', 'wc': 'wildcards', 'clay': 'share of matches on clay',
         'lefty': 'left-handed', 'big': 'big tennis nation', 'ht': 'height', 'noht': 'no listed height'}


# ------------------------------------------------------------------------------------------------ hurdle model

def logit(X, y, l2=1e-3, it=40):
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        H = X.T @ (X * (p * (1 - p) + 1e-9)[:, None]) + l2 * np.eye(len(b))
        d = np.linalg.solve(H, X.T @ (y - p) - l2 * b)
        b += d
        if np.abs(d).max() < 1e-8:
            break
    return b


def hurdle(F, y, pos, cols, tr):
    Xa = np.column_stack([np.ones(len(F)), F[cols].values])
    bl = logit(Xa[tr], pos[tr].astype(float))
    m = tr & pos
    bo = np.linalg.lstsq(Xa[m], y[m], rcond=None)[0]
    return bl, bo


def hpred(F, cols, bl, bo):
    Xa = np.column_stack([np.ones(len(F)), F[cols].values])
    return 1 / (1 + np.exp(-np.clip(Xa @ bl, -30, 30))), Xa @ bo


def loso(F, y, pos, by, cols):
    """leave one birth year out: P(any value), mean FV given value, and the mean FV"""
    P = np.zeros(len(F))
    MU = np.zeros(len(F))
    for b in np.unique(by):
        te = by == b
        bl, bo = hurdle(F, y, pos, cols, ~te)
        P[te], MU[te] = hpred(F[te], cols, bl, bo)
    return P, MU, (1 - P) * 20 + P * MU


def fold_mse(pred, y, by):
    return np.array([np.mean((pred[by == b] - y[by == b]) ** 2) for b in np.unique(by)])


def gate(m0, m1):
    g = m0 - m1
    t = g.mean() / (g.std(ddof=1) / math.sqrt(len(g)) + 1e-12)
    return dict(gain=round(float(g.mean()), 3), t=round(float(t), 2), wins=int((g > 0).sum()), of=len(g))


def forward(F, y, pos, by, season, cols):
    tr, te = by <= FWD, by > FWD
    bl, bo = hurdle(F, y, pos, cols, tr)
    p, mu = hpred(F[te], cols, bl, bo)
    pr = (1 - p) * 20 + p * mu
    o = np.argsort(-pr)
    top = pd.Series(y[te][o]).groupby(season[te][o]).head(50).mean()
    return float(np.mean((pr - y[te]) ** 2)), float(top)


SCALE = {}


def scale(B, tour):
    """the reference peaks: every player born in the cohort years, best first"""
    if tour not in SCALE:
        pk, _ = peaks(B[tour]['S'], B[tour]['P'])
        by = B[tour]['P'].dobd.dt.year.reindex(pk.index)
        ref = np.sort(pk[(by >= COHORTS[0]) & (by <= COHORTS[1])].values)[::-1]
        nco = COHORTS[1] - COHORTS[0] + 1
        SCALE[tour] = dict(ref=ref, nco=nco, v40=float(ref[int(round(CUTS[-1][1] * nco)) - 1]))
    return SCALE[tour]


def fv_rarity(pk, sc):
    xs, ys = np.log([c[1] for c in CUTS]), [c[0] for c in CUTS]
    ref = sc['ref']
    r = np.searchsorted(-ref, -np.asarray(pk, float), side='right') / sc['nco']
    out = np.interp(np.log(np.maximum(r, .05)), xs, ys)
    low = 20 + 20 * np.minimum(np.asarray(pk, float) / sc['v40'], 1)
    out = np.where(r > CUTS[-1][1], low, out)
    return np.where(np.asarray(pk) <= 0, 20.0, out)


def scale_cuts(sc):
    return [[fv, round(float(sc['ref'][max(int(round(n * sc['nco'])) - 1, 0)]), 4)] for fv, n in CUTS]


def snap_rows(rows, tour, snap):
    X = rows[tour]
    X = X[(X.snap == snap) & (X.by >= COHORTS[0]) & (X.by <= COHORTS[1])].reset_index(drop=True)
    return X, design(X), fv_rarity(X.pk.values, scale(base(), tour)), X.pk.values > 0, X.by.values


def select(rows):
    """forward selection on the October rows: an input joins while it cuts leave-one-birth-year-out error with t >= 2,
    wins two thirds of the years, and does not raise the forward test's error (fit 1979-93, grade 1994-97)"""
    snap = '%02d-%02d' % SEL_SNAP
    out = {}
    for tour in TOURS:
        X, F, y, pos, by = snap_rows(rows, tour, snap)
        cands = [c for c in F.columns if c not in BASEF + LEAKS]
        cur = list(BASEF)
        m0 = fold_mse(loso(F, y, pos, by, cur)[2], y, by)
        f0 = forward(F, y, pos, by, X.season.values, cur)
        ev, failfwd = {}, set()
        while True:
            best = None
            for c in cands:
                if c in cur or c in failfwd:
                    continue
                m = fold_mse(loso(F, y, pos, by, cur + [c])[2], y, by)
                ev[c] = gate(m0, m)
                e = ev[c]
                if e['t'] >= 2 and e['wins'] >= 2 * e['of'] / 3 and (best is None or e['gain'] > best[1]):
                    best = (c, e['gain'], m)
            if not best:
                break
            f1 = forward(F, y, pos, by, X.season.values, cur + [best[0]])
            ev[best[0]]['fwd'] = [round(f0[0], 3), round(f1[0], 3)]
            if f1[0] > f0[0]:
                failfwd.add(best[0])
                print(tour, 'fails forward', best[0], ev[best[0]])
                continue
            cur.append(best[0])
            m0, f0 = best[2], f1
            print(tour, '+', best[0], ev[best[0]])
        for c in LEAKS:
            ev[c] = gate(fold_mse(loso(F, y, pos, by, cur)[2], y, by), fold_mse(loso(F, y, pos, by, cur + [c])[2], y, by))
            ev[c]['leak'] = True
        out[tour] = dict(kept=cur, ev=ev, failfwd=sorted(failfwd))
    return out


# outcome distribution: positives' out-of-sample residuals in bands of the predicted mean
NB = 8
NQ = 41


def resid_bands(MU, y, pos):
    rmu, res = MU[pos], (y - MU)[pos]
    edges = np.quantile(rmu, np.linspace(0, 1, NB + 1))[1:-1]
    bi = np.searchsorted(edges, rmu)
    q = [np.quantile(res[bi == k], np.linspace(0, 1, NQ)).tolist() for k in range(NB)]
    return edges.tolist(), q


def dist(p, mu, edges, q, cap=80):
    """the mixture: FV 20 with 1 - p, else mu + residual (the band's quantiles), within [20, cap]. Returns the mean,
    tier odds at 30/40/50/60 and the 10th / 90th percentiles"""
    p, mu = np.atleast_1d(p).astype(float), np.atleast_1d(mu).astype(float)
    bi = np.searchsorted(np.asarray(edges), mu)
    Q = np.asarray(q)[bi]                                         # rows x NQ residual quantiles
    mids = (Q[:, 1:] + Q[:, :-1]) / 2                             # equal-weight draws between quantiles
    v = np.clip(mu[:, None] + mids, 20, cap)
    mean = (1 - p) * 20 + p * v.mean(1)
    odds = {t: p * (v >= t).mean(1) for t in (30, 40, 50, 60)}
    srt = np.sort(v, 1)
    k = srt.shape[1]

    def pct(a):          # P(FV <= x) = (1 - p) + p F(x)
        out = np.full(len(p), 20.0)
        need = (1 - p) < a
        j = np.clip(np.ceil((a - (1 - p[need])) / p[need] * k).astype(int) - 1, 0, k - 1)
        out[need] = srt[need, j]
        return out
    return mean, odds, pct(.1), pct(.9)


def platt(x, y):
    """recalibrate a tier's odds: logistic on the logit of the raw odds"""
    z = np.log(np.clip(x, 1e-4, 1 - 1e-4) / (1 - np.clip(x, 1e-4, 1 - 1e-4)))
    return logit(np.column_stack([np.ones(len(z)), z]), y.astype(float)).tolist()


def platt_apply(x, w):
    z = np.log(np.clip(x, 1e-4, 1 - 1e-4) / (1 - np.clip(x, 1e-4, 1 - 1e-4)))
    return 1 / (1 + np.exp(-(w[0] + w[1] * z)))


def rank_curve(S):
    """median TS at each year-end rank 1-300, 2010-25: E[TS] -> the rank whose seasons are worth that"""
    S = S[(S.y >= 2010) & (S.y <= 2025) & (S['rank'] <= 300)]
    m = S.groupby('rank').ts.median()
    return [[int(r), round(float(v), 5)] for r, v in m.items()]


def xrank(ets, curve):
    r = np.array([c[0] for c in curve], float)
    v = np.array([c[1] for c in curve], float)
    out = np.interp(-np.asarray(ets), -v[::-1], r[::-1])
    return np.where(np.asarray(ets) < v[-1], np.nan, out)


def fit(scorecard_only=False):
    rows = pickle.load(open(ROWS, 'rb')) if os.path.exists(ROWS) else build_rows()
    B = base()
    old = json.load(open(FIT)) if os.path.exists(FIT) else {}
    if '--select' in sys.argv or not old:
        sel = select(rows)
    else:
        sel = {t: {k: old[t][k] for k in ('kept', 'ev', 'failfwd')} for t in TOURS}
    F_ = {'asof': dt.date.today().isoformat(), 'peakAges': list(PEAK_AGES), 'cohorts': list(COHORTS), 'replRank': REPL_RANK,
          'reg': REG, 'fwd': FWD, 'snaps': ['%02d-%02d' % s for s in SNAPS]}
    from fv_scorecard import card
    for tour in TOURS:
        kept = sel[tour]['kept']
        T_ = dict(sel[tour], snaps={}, rank=rank_curve(B[tour]['S']), cuts=scale_cuts(scale(B, tour)), v40=round(scale(B, tour)['v40'], 4))
        for md in SNAPS:
            snap = '%02d-%02d' % md
            X, F, y, pos, by = snap_rows(rows, tour, snap)
            P, MU, E = loso(F, y, pos, by, kept)
            Pb, MUb, Eb = loso(F, y, pos, by, BASEF)
            edges, q = resid_bands(MU, y, pos)
            head, odds, lo, hi = dist(P, MU, edges, q)
            cal = {str(t): platt(odds[t], y >= t) for t in (30, 40, 50, 60)}
            bl, bo = hurdle(F, y, pos, kept, np.ones(len(F), bool))
            fw, fwb = forward(F, y, pos, by, X.season.values, kept), forward(F, y, pos, by, X.season.values, BASEF)
            o = np.argsort(-head)
            top50 = float(pd.Series(y[o]).groupby(X.season.values[o]).head(50).mean())
            ob = np.argsort(-Eb)
            top50b = float(pd.Series(y[ob]).groupby(X.season.values[ob]).head(50).mean())
            mse, mseb = float(np.mean((E - y) ** 2)), float(np.mean((Eb - y) ** 2))
            s = dict(n=int(len(X)), players=int(X.pid.nunique()), seasons=[int(X.season.min()), int(X.season.max())],
                     coefL=dict(zip(['const'] + kept, np.round(bl, 5).tolist())), coefO=dict(zip(['const'] + kept, np.round(bo, 5).tolist())),
                     means={c: round(float(F[c].mean()), 5) for c in kept}, edges=np.round(edges, 3).tolist(),
                     q=np.round(q, 3).tolist(), cal=cal, mse=round(mse, 3), mseBase=round(mseb, 3),
                     mseNull=round(float(np.var(y)), 3), r2=round(1 - mse / float(np.var(y)), 3), top50=round(top50, 2),
                     top50Base=round(top50b, 2), fwd=[round(fw[0], 3), round(fwb[0], 3), round(fw[1], 2), round(fwb[1], 2)],
                     pos=round(float(pos.mean()), 4))
            # bands of the headline, out of sample: the band's mean outcome against its mean grade
            band = np.minimum(np.floor(head / 5) * 5, 65)
            s['calib'] = [dict(band=int(b), n=int((band == b).sum()), pred=round(float(head[band == b].mean()), 1),
                               real=round(float(y[band == b].mean()), 1),
                               p50=round(float((y[band == b] >= 50).mean()), 3)) for b in np.unique(band)]
            T_['snaps'][snap] = s
            print(tour, snap, 'mse %.2f base %.2f null %.2f top50 %.2f/%.2f fwd %s' % (mse, mseb, np.var(y), top50, top50b, s['fwd']))
            if snap == '%02d-%02d' % SEL_SNAP:
                oc = np.column_stack([platt_apply(odds[t], cal[str(t)]) for t in (30, 40, 50, 60)])
                sc = card(head, y, odds=oc, note='%s born %d-%d, October grades, each birth year graded by a fit without it' % (tour.upper(), *COHORTS))
                T_['scorecard'] = sc
                # Elo+ (display): Elo against players the same age with 20+ pro matches, 100 + 25 per SD
                ok = X.elon >= 20
                b = np.polyfit(X.age[ok], X.elo[ok], 1)
                T_['eloplus'] = [round(float(b[0]), 3), round(float(b[1]), 2), round(float((X.elo[ok] - np.polyval(b, X.age[ok])).std()), 2)]
                # past prospects: each player's youngest October grade with a ranking, out of sample
                Xp = X.assign(head=head, out=y)
                Xp = Xp[Xp['rank'].notna()].sort_values('age').drop_duplicates('pid')
                Xp = Xp[(Xp['head'] >= 45) | (Xp.out >= 55)].sort_values('head', ascending=False)
                Pn = B[tour]['P']
                T_['past'] = [dict(pid=int(r.pid), name=f"{Pn.at[r.pid, 'first']} {Pn.at[r.pid, 'last']}", season=int(r.season),
                                   age=round(float(r.age), 1), rank=int(r.rank), fv=int(round(r.head)), out=int(round(r.out)),
                                   peak=round(float(r.pk) * 20, 2), ioc=None if pd.isna(r.ioc) else str(r.ioc))
                              for r in Xp.itertuples()]
        F_[tour] = T_
    if scorecard_only and old:
        for t in TOURS:
            old[t]['scorecard'] = F_[t]['scorecard']
        F_ = old
    json.dump(F_, open(FIT, 'w'), indent=1)
    print('wrote', FIT)


# ------------------------------------------------------------------------------------------------ live

LIVE_BORN = 2003                     # the frozen base keeps every player born this year or later
FROZEN = os.path.join(HERE, 'data', 'tennis_prospects_base.json.gz')
RATINGS = os.path.join(HERE, 'data', 'tennis_ratings.json.gz')
TA_CACHE = os.path.join(CACHE, 'ta')
TA_PAUSE = 1.0                       # seconds between ATP player pages (a CGI that answers 429 when hurried)
TA_HEAD = ['date', 'tourn', 'surf', 'level', 'wl', 'rank', 'seed', 'entry', 'round', 'score', 'max', 'opp', 'orank',
           'oseed', 'oentry', 'ohand', 'obday', 'oht', 'ocountry']
LCOLS = ['date', 'cls', 'tourney_level', 'round', 'walk', 'surface', 'pid', 'won', 'orank', 'elo_pre', 'oelo', 'elo',
         'entry', 'gw', 'gl', 'tbw', 'tbl']
STATS = ['svpt', 'svw', 'rtpt', 'rtw', 'ace']           # not in the live inputs: left out of the frozen base


def freeze():
    """scripts/data/tennis_prospects_base.json.gz: what the live board needs from the archive. Every match and
    weekly ranking of the players born in LIVE_BORN or later, their bios, and the end-of-archive Elo and match count
    of everyone who played since 2024 (opponents of the Tennis Abstract results)."""
    import names
    B = base()
    out = {'asof': dt.date.today().isoformat()}
    for tour in TOURS:
        b = B[tour]
        P, L, R = b['P'], b['L'], b['R']
        young = P.index[P.dobd.dt.year >= LIVE_BORN]
        Ly = L[L.pid.isin(young)][LCOLS].copy()
        Ly['date'] = Ly.date.dt.strftime('%Y%m%d').astype(int)
        for c in ('elo_pre', 'oelo', 'elo'):
            Ly[c] = Ly[c].round(1)
        # weekly rankings from last year on, and each player's career high before that
        Ry = R[R.pid.isin(young)]
        old = Ry[Ry.date < 20250101].sort_values('rank').drop_duplicates('pid')
        Ry = pd.concat([old, Ry[Ry.date >= 20250101]])
        g = L[L.date >= '2024-01-01'].groupby('pid')
        last = L.groupby('pid').tail(1).set_index('pid')
        act = g.size().index
        n = L.groupby('pid').size()
        opp = {}
        for pid in act:
            if pid not in P.index or pd.isna(P.at[pid, 'dob']):
                continue
            k = names.key(f"{P.at[pid, 'first']} {P.at[pid, 'last']}")
            opp[f'{k}|{int(P.at[pid, "dob"])}'] = [int(pid), round(float(last.at[pid, 'elo']), 1), int(n[pid])]
        rk = R[R.date == R.date.max()].set_index('pid')['rank']
        el = np.array([v[1] for v in opp.values()])
        rr = np.array([rk.get(v[0], np.nan) for v in opp.values()], float)
        ok = ~np.isnan(rr)
        curve = np.polyfit(np.log(rr[ok]), el[ok], 1)
        Py = P.loc[young, ['first', 'last', 'dob', 'hand', 'height', 'ioc']].copy()
        out[tour] = dict(end=int(L.date.max().strftime('%Y%m%d')), cols=LCOLS,
                         L=[[None if (isinstance(v, float) and math.isnan(v)) else v for v in r] for r in
                            Ly.astype(object).where(Ly.notna(), None).values.tolist()],
                         R=Ry[['date', 'rank', 'pid', 'pts']].astype(object).where(Ry[['date', 'rank', 'pid', 'pts']].notna(), None).values.tolist(),
                         P={int(k): [None if pd.isna(x) else x for x in v] for k, v in zip(Py.index, Py.values.tolist())},
                         opp=opp, curve=[round(float(c), 3) for c in curve])
        print(tour, len(Ly), 'matches', len(Ry), 'rankings', len(Py), 'players', len(opp), 'opponents')
    with gzip.open(FROZEN, 'wt') as fh:
        json.dump(out, fh, separators=(',', ':'), default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    print('wrote', FROZEN, os.path.getsize(FROZEN) // 1024, 'KB')


def ta_param(name):
    import unicodedata
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return ''.join(ch for ch in s if ch.isalpha())


def ta_fetch(name, tour, days=6):
    """a player's Tennis Abstract page (bio + every match it lists), cached for `days`"""
    import re
    import urllib.error
    import urllib.request
    p = ta_param(name)
    os.makedirs(TA_CACHE, exist_ok=True)
    f = os.path.join(TA_CACHE, f'{tour}_{p}.json')
    if os.path.exists(f) and (dt.datetime.now().timestamp() - os.path.getmtime(f)) < days * 86400:
        return json.load(open(f))
    url = (f'https://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={p}' if tour == 'atp'
           else f'https://www.tennisabstract.com/jsmatches/{p}.js')
    import time
    h = None
    for k in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (arkboard; arkndjl.net)'})
            h = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                return {'err': str(e)[:80]}
            time.sleep(15 * (k + 1))                 # the player pages are rate limited: back off and retry
        except Exception as e:  # noqa: BLE001
            return {'err': str(e)[:80]}
    if h is None:
        return {'err': 'rate limited'}
    if tour == 'atp':
        time.sleep(TA_PAUSE)
    bio = {}
    for v in ('dob', 'currentrank', 'country', 'hand', 'ht', 'fullname'):
        m = re.search(r"var %s\s*=\s*'?([^';\n]*)'?;?" % v, h)
        bio[v] = m.group(1).strip() if m else None
    rows = []
    i = h.find('matchmx = [[')
    if i >= 0:
        i = h.index('[', i)
        depth, j, q = 0, i, False
        while j < len(h):                      # the array ends where its brackets close (strings hold no brackets)
            c = h[j]
            if c == '"':
                q = not q
            elif not q and c == '[':
                depth += 1
            elif not q and c == ']':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        try:
            rows = [r[:len(TA_HEAD)] for r in json.loads(h[i:j + 1])]
        except ValueError:
            rows = []
    out = {'bio': bio, 'rows': rows}
    json.dump(out, open(f, 'w'))
    return out


def ta_rows(rows, tour, pid, end, opp, curve, elo0, n0):
    """Tennis Abstract results after the archive's end as long rows, Elo carried on from the archive (opponents at
    their end-of-archive Elo, or at the Elo their ranking implies)"""
    import names
    out = []
    rows = [r for r in rows if r[4] in ('W', 'L') and r[0].isdigit() and int(r[0]) > end]
    rows.sort(key=lambda r: (r[0], RORDER.get(r[8], 4)))
    e, n = elo0, n0
    for r in rows:
        d = dict(zip(TA_HEAD, r + [''] * (len(TA_HEAD) - len(r))))
        lv = d['level']
        cls = LEVEL.get(lv, 'S' if lv.isdigit() else 'T')
        if d['round'].startswith('Q') and cls == 'T':
            cls = 'Q'
        o = opp.get(f"{names.key(d['opp'])}|{d['obday']}")
        orank = float(d['orank']) if d['orank'].isdigit() else np.nan
        oe = o[1] if o else (curve[0] * math.log(orank) + curve[1] if orank == orank else 1450.0)
        won = 1 if d['wl'] == 'W' else 0
        walk = any(x in d['score'].upper() for x in ('W/O', 'WALKOVER', 'DEF'))
        pre = e
        if not walk:
            p = 1 / (1 + 10 ** ((oe - e) / 400))
            e = e + (1.1 if lv == 'G' else 1.0) * 250 / (n + 5) ** .4 * (won - p)
            n += 1
        g = games(d['score'])
        gw, gl, tw, tl = (g if won else (g[1], g[0], g[3], g[2]))
        out.append(dict(date=pd.Timestamp(d['date']), cls=cls, tourney_level=lv, round=d['round'], walk=walk,
                        surface=d['surf'], pid=pid, won=won, orank=orank, elo_pre=pre, oelo=oe, elo=e, svpt=np.nan,
                        svw=np.nan, rtpt=np.nan, rtw=np.nan, ace=np.nan, entry=str(d['entry']).upper(), gw=gw, gl=gl,
                        tbw=tw, tbl=tl))
    return out


def snap_for(d):
    md = (d.month, d.day)
    past = [s for s in SNAPS if s <= md]
    return '%02d-%02d' % (past[-1] if past else SNAPS[-1])


def grade(X, s, kept, B=None):
    F = design(X)
    bl = np.array([s['coefL']['const']] + [s['coefL'][c] for c in kept])
    bo = np.array([s['coefO']['const']] + [s['coefO'][c] for c in kept])
    p, mu = hpred(F, kept, bl, bo)
    mean, odds, lo, hi = dist(p, mu, s['edges'], s['q'])
    odds = {t: platt_apply(odds[t], s['cal'][str(t)]) for t in odds}
    # each input's push on the mean against the average prospect of the fit: d mean = (mu - 20) dp + p dmu
    parts = {}
    for c in kept:
        dx = F[c].values - s['means'][c]
        parts[c] = ((mu - 20) * p * (1 - p) * s['coefL'][c] + p * s['coefO'][c]) * dx
    return mean, odds, lo, hi, parts, p, mu


PART = {'age': 'age', 'lr': 'rank', 'unr': 'rank', 'lr_age': 'rank', 'elo': 'elo', 'wpall': 'form', 'first': 'pro',
        'lnS': 'itf', 'lnQ': 'qual'}


def build():
    import names
    from concurrent.futures import ThreadPoolExecutor
    fit_ = json.load(open(FIT))
    Z = json.load(gzip.open(FROZEN, 'rt'))
    # the tennis section's ratings file (scripts/tennis_model.py, twice a day): names, flags, birth dates, ESPN ids and
    # Tennis Abstract's ranks for everyone with a match in the last year
    pl = json.load(gzip.open(RATINGS, 'rt'))['players']
    today = pd.Timestamp(dt.date.today())
    season = today.year
    born = pd.Timestamp(season - AGE_CUT, 7, 2)
    snap = snap_for(today)
    out = {'asof': today.strftime('%Y-%m-%d'), 'season': season, 'snap': snap, 'born': born.strftime('%Y-%m-%d')}
    for tour in TOURS:
        z, tf = Z[tour], fit_[tour]
        pre = tour[0]
        L = pd.DataFrame(z['L'], columns=z['cols'])
        L['date'] = pd.to_datetime(L.date.astype(str), format='%Y%m%d')
        L['pid'] = pre + L.pid.astype(int).astype(str)
        for c in STATS:
            L[c] = np.nan
        for c in ('won', 'walk'):
            L[c] = L[c].astype(int) if c == 'won' else L[c].astype(bool)
        R = pd.DataFrame(z['R'], columns=['date', 'rank', 'pid', 'pts'])
        R['pid'] = pre + R.pid.astype(int).astype(str)
        P = pd.DataFrame.from_dict(z['P'], orient='index', columns=['first', 'last', 'dob', 'hand', 'height', 'ioc'])
        P.index = pre + P.index.astype(str)
        # the section's player file: names, flags, birth dates and ranks for players the archive lacks or ranks late
        sp = {k: v for k, v in pl.items() if k.startswith(pre) and v.get('dob') and int(v['dob']) >= int(born.strftime('%Y%m%d'))}
        new = {k: [(v.get('n') or '').rsplit(' ', 1)[0], (v.get('n') or '').rsplit(' ', 1)[-1], int(v['dob']), None, None, None]
               for k, v in sp.items() if k not in P.index}
        if new:
            P = pd.concat([P, pd.DataFrame.from_dict(new, orient='index', columns=P.columns)])
        P.index = P.index.astype(str)
        P['dobd'] = pd.to_datetime(P.dob.astype(float).astype('Int64').astype(str), format='%Y%m%d', errors='coerce')
        P = P[P.dobd >= born]
        last = L.groupby('pid').tail(1).set_index('pid')
        cnt = L[~L.walk].groupby('pid').size()
        # Tennis Abstract for every ranked prospect: results since the archive ends
        todo = [(k, (sp.get(k) or {}).get('n') or f"{P.at[k, 'first']} {P.at[k, 'last']}") for k in P.index
                if (sp.get(k) or {}).get('rank')]
        with ThreadPoolExecutor(1 if tour == 'atp' else 4) as ex:
            pages = dict(zip([k for k, _ in todo], ex.map(lambda kn: ta_fetch(kn[1], tour), todo)))
        add, nta = [], 0
        for k, pg in pages.items():
            if 'rows' not in pg:
                continue
            b = pg.get('bio') or {}
            if b.get('dob') and b['dob'].isdigit() and P.at[k, 'dob'] and int(b['dob']) != int(P.at[k, 'dob']):
                continue                                     # another player under that name
            nta += 1
            e0 = float(last.at[k, 'elo']) if k in last.index else 1500.0
            add += ta_rows(pg['rows'], tour, k, z['end'], z['opp'], z['curve'], e0, int(cnt.get(k, 0)))
        if add:
            L = pd.concat([L, pd.DataFrame(add)], ignore_index=True).sort_values(['date'], kind='stable')
        rk = pd.DataFrame([dict(date=int(today.strftime('%Y%m%d')), rank=int(v['rank']), pid=k, pts=v.get('pts'))
                           for k, v in sp.items() if v.get('rank')])
        if len(rk):
            R = pd.concat([R, rk], ignore_index=True)
        R = R.sort_values(['date', 'rank'])
        L['ioc'] = None
        X = features(R, L, P, today + pd.Timedelta(days=7), season, tour)
        X = X[X.age < AGE_CUT]
        kept = tf['kept']
        mean, odds, lo, hi, parts, p, mu = grade(X, tf['snaps'][snap], kept)
        a, b0, sd = tf['eloplus']
        rows = []
        for i, (pid, r) in enumerate(X.iterrows()):
            v = sp.get(pid) or {}
            nm = v.get('n') or f"{P.at[pid, 'first']} {P.at[pid, 'last']}"
            pr = {}
            for c in kept:
                pr[PART.get(c, c)] = pr.get(PART.get(c, c), 0) + float(parts[c][i])
            elo = None if pd.isna(r.elo) else round(float(r.elo))
            rows.append(dict(id=pid, name=nm, nat=v.get('nat'), espn=v.get('espn'), wd=v.get('wd'),
                             age=round(float(r.agesnap), 1), rank=None if pd.isna(r['rank']) else int(r['rank']),
                             best=None if pd.isna(r.best) else int(r.best), elo=elo,
                             ep=None if elo is None or r.elon < 10 else int(round(100 + 25 * (r.elo - (a * r.age + b0)) / sd)),
                             n=int(r.n), w=int(r.w), nT=int(r.nT), wT=int(r.wT), nC=int(r.nC), wC=int(r.wC), nS=int(r.nS), wS=int(r.wS),
                             nQ=int(r.nQ), wQ=int(r.wQ), car=int(r.elon), deb=None if pd.isna(r['first']) else round(float(r['first']), 1),
                             fvx=round(float(mean[i]), 2), fv=int(round(mean[i])), lo=int(round(lo[i])), hi=int(round(hi[i])),
                             p30=round(float(odds[30][i]), 3), p40=round(float(odds[40][i]), 3), p50=round(float(odds[50][i]), 3),
                             p60=round(float(odds[60][i]), 3), pv=round(float(p[i]), 3), prov=bool(pd.isna(r['rank'])),
                             parts=sorted([[k, round(x, 2)] for k, x in pr.items()], key=lambda t: -abs(t[1]))))
        rows.sort(key=lambda r: (-r['fvx'], r['rank'] or 9999))
        out[tour] = {'board': rows, 'pool': len(rows), 'ta': nta}
        print(tour, len(rows), 'prospects,', nta, 'Tennis Abstract pages;', [(r['name'], r['fv'], r['rank']) for r in rows[:8]])
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print('wrote', OUT)


if __name__ == '__main__':
    if '--download' in sys.argv:
        download()
    elif '--rows' in sys.argv:
        base(refresh='--refresh' in sys.argv)
        build_rows()
    elif '--fit' in sys.argv:
        fit()
    elif '--scorecard' in sys.argv:
        fit(scorecard_only=True)
    elif '--freeze' in sys.argv:
        freeze()
    else:
        build()
