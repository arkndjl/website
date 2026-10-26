#!/usr/bin/env python3
"""Soccer prospects ARKBOARD (Noah, Oct 24 2026): every player under 22 at the season start in the 14 European
leagues of the Transfermarkt dump and the feeder leagues, graded on the 20-80 FV scale against what past prospects
became.

    python3 scripts/soccer_prospect_data.py games   # feeder leagues 2012-26 + this season everywhere (cache)
    python3 scripts/soccer_prospects.py --fit       # club ratings, value, outcome scale, driver selection -> fit + base
    python3 scripts/soccer_prospects.py             # this season's grades -> data/soccer_prospects.json

Prospect  Under 22 on July 1 of the season (born on or after July 1, 2005 for 2026-27). The cut comes from the age
          curve: a player's value now against his best seasons over the next six reaches 80% at 21 and parity at 23;
          at 21 the mean player still gains a quarter of his value, at 22 an eighth, at 23 nothing.
Value     Goals above replacement (GAR), a provisional senior value until the soccer section's WAR covers every league:
          each match a player's minutes/90 x (his club's rating - replacement) / 11. Club ratings are goals a match
          against an average big-five side, a ridge fit on every league, cup and European result that season, shrunk
          toward what the club's squad market value implies (log value explains ~75% of club strength in the 14
          leagues); that prior is what places Brazil, Argentina and MLS, which rarely meet European sides.
          Replacement = -2.5 (a bottom side in Scotland, Greece or Denmark); a club below it adds nothing.
Outcome   Peak value: the mean of a player's best three GAR seasons at ages 22-26, missing seasons counted as 0.
FV scale  By rarity within a birth cohort and position group (GK, defence, midfield, attack, each counted as if it
          were the whole cohort), cohorts aged 22 in 2013-21: 80 = one in two cohorts, 75 = the best of a cohort,
          70 = top 3, 65 = top 8, 60 = top 20, 55 = top 45, 50 = top 90 (about a big-five regular), 45 = top 150,
          40 = top 250; below that 20 (no value) to 40 by peak. Steps of 1.
Model     FV = OLS on outcome FV (the mean outcome, Noah Oct 21), one fit per in-season snapshot (Jul 1, Sep 15,
          Oct 24, Jan 15, Apr 1) from what was known that day: age, market value, last season and this season so far
          (value, minutes share, club rating, league strength, scoring), bench and youth-league (Premier League 2)
          play, height, position. No transfer fees or other transfer-table inputs: the dump lists past transfers only
          for players it kept scraping, so having any transfer on record was worth +7 FV in hindsight (Oct 24 2026,
          scripts/soccer_fv_drivers.py), and the fee's signal was that record. Inputs added forward on the Oct 24 rows while they cut leave-one-season-out
          error with t >= 2 over the 2013-20 seasons and win 6 of 8; the other snapshots refit the same inputs.
Live      This season's lineups from Transfermarkt's JSON API (scripts/soccer_prospect_data.py), current market values
          and birth dates from player profiles; last season and before come frozen in scripts/data/ by --fit.
"""
import datetime as dt
import gzip
import io
import json
import math
import os
import sys
import urllib.request
import zipfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import soccer_prospect_data as SD

CACHE = os.path.join(HERE, '.cache', 'soccer_prospects')
DUMPD = os.path.join(CACHE, 'dump')
DUMP_URL = 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip'
FIT = os.path.join(ROOT, 'data', 'soccer_prospects_fit.json')
OUT = os.path.join(ROOT, 'data', 'soccer_prospects.json')
BASE = os.path.join(HERE, 'data', 'soccer_prospects_base.json.gz')
PAST = os.path.join(HERE, 'data', 'soccer_prospects_rows.json.gz')

DUMPL = SD.DUMP
EURO = SD.EURO + ['CLQ', 'ELQ', 'ECLQ', 'USC']
YOUTH = ['GB21']
FEEDV = [c for c in SD.FEED if c not in YOUTH]
VALUE = DUMPL + SD.EURO + FEEDV                     # competitions whose minutes count as senior value
FIRST, LAST = 2012, 2026
REPL, LAM = -2.5, 5.0
AGE_CUT = 22
PEAK_AGES = (22, 26)
COHORTS = (2013, 2021)
ROWS = (2013, 2020)
CUTS = [(80, .5), (75, 1), (70, 3), (65, 8), (60, 20), (55, 45), (50, 90), (45, 150), (40, 250)]
SNAPS = [(7, 1), (9, 15), (10, 24), (1, 15), (4, 1)]
SEL_SNAP = (10, 24)
GRP = {'Goalkeeper': 'G', 'Defender': 'D', 'Midfield': 'M', 'Attack': 'F'}
LEAGUE = {'GB1': 'Premier League', 'ES1': 'LaLiga', 'IT1': 'Serie A', 'L1': 'Bundesliga', 'FR1': 'Ligue 1',
          'NL1': 'Eredivisie', 'PO1': 'Liga Portugal', 'BE1': 'Belgian Pro League', 'TR1': 'Super Lig',
          'RU1': 'Russian Premier League', 'SC1': 'Scottish Premiership', 'GR1': 'Greek Super League',
          'DK1': 'Danish Superliga', 'UKR1': 'Ukrainian Premier League', 'GB2': 'Championship', 'L2': '2. Bundesliga',
          'IT2': 'Serie B', 'ES2': 'LaLiga 2', 'FR2': 'Ligue 2', 'NL2': 'Eerste Divisie', 'PO2': 'Liga Portugal 2',
          'BRA1': 'Brasileirao', 'AR1N': 'Argentine Primera', 'ARG1': 'Argentine Primera', 'MLS1': 'MLS',
          'C1': 'Swiss Super League', 'A1': 'Austrian Bundesliga', 'TS1': 'Czech First League', 'KR1': 'Croatian HNL',
          'NO1': 'Eliteserien', 'SE1': 'Allsvenskan', 'SER1': 'Serbian SuperLiga', 'PL1': 'Ekstraklasa',
          'GB21': 'Premier League 2'}
SHORT = {'GB1': 'EPL', 'ES1': 'LaLiga', 'IT1': 'Serie A', 'L1': 'BuLi', 'FR1': 'Ligue 1', 'NL1': 'Erediv.',
         'PO1': 'Portugal', 'BE1': 'Belgium', 'TR1': 'Turkey', 'RU1': 'Russia', 'SC1': 'Scotland', 'GR1': 'Greece',
         'DK1': 'Denmark', 'UKR1': 'Ukraine', 'GB2': 'Champ.', 'L2': 'BuLi 2', 'IT2': 'Serie B', 'ES2': 'LaLiga 2',
         'FR2': 'Ligue 2', 'NL2': 'Eerste D.', 'PO2': 'Portugal 2', 'BRA1': 'Brazil', 'AR1N': 'Argentina',
         'ARG1': 'Argentina', 'MLS1': 'MLS', 'C1': 'Swiss', 'A1': 'Austria', 'TS1': 'Czechia', 'KR1': 'Croatia',
         'NO1': 'Norway', 'SE1': 'Sweden', 'SER1': 'Serbia', 'PL1': 'Poland', 'GB21': 'PL2'}


def season_of(d):
    return d.dt.year - (d.dt.month < 7).astype(int)


# ---------------------------------------------------------------- data
def dump():
    if os.path.exists(os.path.join(DUMPD, 'players.csv.gz')):
        return
    os.makedirs(DUMPD, exist_ok=True)
    with urllib.request.urlopen(DUMP_URL, timeout=600) as r:
        zipfile.ZipFile(io.BytesIO(r.read())).extractall(DUMPD)


def rd(name, **kw):
    return pd.read_csv(os.path.join(DUMPD, name + '.csv.gz'), **kw)


def tm_games(comps, seasons):
    """compact Transfermarkt games -> games, appearances (bench rows have minutes 0)"""
    gs, ap = [], []
    for c in comps:
        for s in seasons:
            fn = os.path.join(SD.CACHE, f'{c}_{s}.json.gz')
            if not os.path.exists(fn):
                continue
            for g in json.load(gzip.open(fn, 'rt')):
                gid, comp, _, date, h, a, hg, ag, dur, pl, acts = g
                if hg is None or ag is None or not date:
                    continue
                gs.append((int(gid), comp, date[:10], h, a, hg, ag))
                dur = dur or 90
                on, off, gl, asst = {}, {}, {}, {}
                for pid, club, st, pos, age, mv in pl:
                    if st:
                        on[pid] = 0
                for typ, m, add, club, act, pas, rs in acts:
                    m = min(m or 0, dur)
                    if typ == 'SUBSTITUTE':
                        if act:
                            off[act] = m
                        if pas:
                            on[pas] = m
                    elif typ == 'GOAL' and act:
                        gl[act] = gl.get(act, 0) + 1
                        if pas:
                            asst[pas] = asst.get(pas, 0) + 1
                for pid, club, st, pos, age, mv in pl:
                    mins = max(off.get(pid, dur) - on[pid], 1) if pid in on else 0
                    ap.append((int(gid), int(pid), club, mins, gl.get(pid, 0), asst.get(pid, 0), st, pos, age, mv))
    G = pd.DataFrame(gs, columns=['game_id', 'comp', 'date', 'home', 'away', 'hg', 'ag'])
    A = pd.DataFrame(ap, columns=['game_id', 'player_id', 'club', 'mins', 'gl', 'ast', 'start', 'pos', 'age', 'mv'])
    for k in ('home', 'away'):
        G[k] = pd.to_numeric(G[k], errors='coerce')
    A['club'] = pd.to_numeric(A.club, errors='coerce')
    G['date'] = pd.to_datetime(G.date)
    return G, A


def load(live_only=False):
    """unified games, appearances (with bench), players, market values"""
    dump()
    comp = rd('competitions')
    clubc = comp[~comp.type.eq('national_team_competition')].competition_id.tolist()
    g = rd('games', usecols=['game_id', 'competition_id', 'date', 'home_club_id', 'away_club_id', 'home_club_goals',
                             'away_club_goals']).dropna()
    g = g[g.competition_id.isin(clubc)].rename(columns={'competition_id': 'comp', 'home_club_id': 'home',
                                                       'away_club_id': 'away', 'home_club_goals': 'hg',
                                                       'away_club_goals': 'ag'})
    g['date'] = pd.to_datetime(g.date)
    g = g[g.date < '2026-07-01']
    a = rd('appearances', usecols=['game_id', 'player_id', 'player_club_id', 'goals', 'assists', 'minutes_played'])
    a = a.rename(columns={'player_club_id': 'club', 'goals': 'gl', 'assists': 'ast', 'minutes_played': 'mins'})
    a = a[a.game_id.isin(g.game_id)]
    lu = rd('game_lineups', usecols=['game_id', 'player_id', 'club_id', 'type'])
    lu = lu[lu.game_id.isin(g.game_id)]
    lu['start'] = lu.type.eq('starting_lineup').astype(int)
    a = a.merge(lu[['game_id', 'player_id', 'start']].drop_duplicates(['game_id', 'player_id']), on=['game_id', 'player_id'], how='left')
    bench = lu[lu.start.eq(0)].merge(a[['game_id', 'player_id']], on=['game_id', 'player_id'], how='left', indicator=True)
    bench = bench[bench._merge.eq('left_only')].rename(columns={'club_id': 'club'})[['game_id', 'player_id', 'club', 'start']]
    bench = bench.assign(mins=0, gl=0, ast=0)
    a = pd.concat([a, bench], ignore_index=True)
    a['start'] = a.start.fillna((a.mins >= 60).astype(int))
    a['pos'], a['age'], a['mv'] = None, np.nan, np.nan
    seasons = range(FIRST, LAST + 1)
    G2, A2 = tm_games(SD.FEED, seasons)
    G3, A3 = tm_games(DUMPL + SD.EURO, [2026])
    G = pd.concat([g, G2, G3], ignore_index=True).drop_duplicates('game_id')
    A = pd.concat([a, A2, A3], ignore_index=True).drop_duplicates(['game_id', 'player_id'])
    A = A.merge(G[['game_id', 'comp', 'date']], on='game_id')
    G['season'] = season_of(G.date)
    A['season'] = season_of(A.date)
    A['napp'] = (A.mins > 0).astype(int)
    A['nbench'] = (A.mins == 0).astype(int)
    # players: the dump, then lineup ages for everyone else (birth date bounded by the integer age at each game)
    p = rd('players', usecols=['player_id', 'name', 'date_of_birth', 'position', 'sub_position', 'height_in_cm',
                               'country_of_citizenship', 'image_url'])
    p['dob'] = pd.to_datetime(p.date_of_birth, errors='coerce')
    P = p.drop(columns='date_of_birth').set_index('player_id')
    ag = A[A.age.notna()].copy()
    if len(ag):
        ag['lo'] = ag.date - pd.to_timedelta((ag.age + 1) * 365.25, unit='D')     # born after
        ag['hi'] = ag.date - pd.to_timedelta(ag.age * 365.25, unit='D')           # born before
        b = ag.groupby('player_id').agg(lo=('lo', 'max'), hi=('hi', 'min'))
        est = b.lo + (b.hi - b.lo).clip(lower=pd.Timedelta(0)) / 2
        miss = est.index.difference(P.index[P.dob.notna()])
        add = pd.DataFrame({'dob': est.loc[miss]})
        P = pd.concat([P[~P.index.isin(miss)], add])
    prof = profiles()
    for pid, d in prof.items():
        pid = int(pid)
        dob = ((d.get('lifeDates') or {}).get('dateOfBirth'))
        at = d.get('attributes') or {}
        cat = ((at.get('position') or {}).get('category'))
        row = {'name': d.get('name'), 'dob': pd.to_datetime(dob, errors='coerce') if dob else pd.NaT,
               'position': {'Goalkeeper': 'Goalkeeper', 'Defender': 'Defender', 'Midfield': 'Midfield',
                            'Striker': 'Attack'}.get(cat), 'sub_position': (at.get('position') or {}).get('name'),
               'height_in_cm': (at.get('height') or 0) * 100 or np.nan}
        if pid in P.index:
            for k, v in row.items():
                if v is not None and not (isinstance(v, float) and math.isnan(v)) and not (k == 'dob' and pd.isna(v)):
                    if k in ('name', 'dob', 'height_in_cm', 'position', 'sub_position') and pd.isna(P.at[pid, k] if k in P.columns else np.nan):
                        P.at[pid, k] = v
        else:
            P.loc[pid] = pd.Series(row)
    P['dob'] = pd.to_datetime(P.dob, errors='coerce')
    P['height_in_cm'] = pd.to_numeric(P.height_in_cm, errors='coerce')
    # lineup positions for anyone still without one
    sp = A[A.pos.notna() & A.start.eq(1)].groupby('player_id').pos.agg(lambda s: s.value_counts().index[0])
    POSG = {'GK': 'Goalkeeper', 'CB': 'Defender', 'LB': 'Defender', 'RB': 'Defender', 'DM': 'Midfield', 'CM': 'Midfield',
            'AM': 'Midfield', 'LM': 'Midfield', 'RM': 'Midfield', 'LW': 'Attack', 'RW': 'Attack', 'SS': 'Attack',
            'CF': 'Attack'}
    P['position'] = P.position.where(P.position.notna() & P.position.ne('Missing'), P.index.map(sp).map(POSG))
    P['grp'] = P.position.map(GRP).fillna('M')
    # market values: the dump's valuation history plus the value shown on each lineup
    v = rd('player_valuations', usecols=['player_id', 'date', 'market_value_in_eur'])
    v = v.rename(columns={'market_value_in_eur': 'mv'})
    v['date'] = pd.to_datetime(v.date)
    V = pd.concat([v, A[A.mv.notna()][['player_id', 'date', 'mv']]], ignore_index=True).sort_values('date')
    return G, A, P, V


def profiles():
    fn = os.path.join(SD.CACHE, 'players.json.gz')
    return json.load(gzip.open(fn, 'rt')) if os.path.exists(fn) else {}


# ---------------------------------------------------------------- club ratings and value
def club_mv(A, V):
    """minutes-weighted mean log market value of each club's players, per season"""
    a = A[A.mins > 0][['player_id', 'date', 'club', 'season', 'mins']].sort_values('date')
    m = pd.merge_asof(a, V[['player_id', 'date', 'mv']].sort_values('date'), on='date', by='player_id', direction='backward')
    m = m[m.mv.notna() & m.club.notna()]
    m['l'] = np.log(m.mv.clip(lower=25000)) * m.mins
    s = m.groupby(['club', 'season']).agg(l=('l', 'sum'), w=('mins', 'sum'))
    return (s.l / s.w).rename('lmv')


def ridge(G, prior, lam):
    clubs = pd.Index(pd.unique(pd.concat([G.home, G.away])))
    n, k = len(G), len(clubs)
    hi, ai = clubs.get_indexer(G.home), clubs.get_indexer(G.away)
    y = (G.hg - G.ag).clip(-4, 4).values.astype(float)
    # normal equations: (X'X + lam I) r = X'y + lam mu, with a home term
    M = np.zeros((k + 1, k + 1))
    b = np.zeros(k + 1)
    np.add.at(M, (hi, hi), 1); np.add.at(M, (ai, ai), 1)
    np.add.at(M, (hi, ai), -1); np.add.at(M, (ai, hi), -1)
    np.add.at(M, (hi, k), 1); np.add.at(M, (k, hi), 1)
    np.add.at(M, (ai, k), -1); np.add.at(M, (k, ai), -1)
    M[k, k] += n
    np.add.at(b, hi, y); np.add.at(b, ai, -y); b[k] = y.sum()
    mu = np.array([prior.get(c, np.nan) for c in clubs])
    has = ~np.isnan(mu)
    M[np.arange(k), np.arange(k)] += np.where(has, lam, 1e-3)
    b[:k] += np.where(has, lam * np.nan_to_num(mu), 0)
    r = np.linalg.solve(M, b)
    return pd.Series(r[:k], index=clubs), r[k]


def club_ratings(G, A, V, upto=None):
    """per season: ridge on every club result shrunk toward the club's squad-value prior; 0 = mean big-five club"""
    L = club_mv(A, V)
    lg = A[A.comp.isin(DUMPL + FEEDV) & A.mins.gt(0)].groupby(['club', 'season']).comp.agg(lambda s: s.value_counts().index[0])
    out = []
    for s, d in G[G.comp.ne('GB21')].groupby('season'):
        if upto is not None and s > upto:
            continue
        lm = L.xs(s, level='season') if s in L.index.get_level_values('season') else pd.Series(dtype=float)
        r0, _ = ridge(d, {}, 0)           # unshrunk pass: the value -> strength line on the 14 dump leagues
        dl = lg.xs(s, level='season') if s in lg.index.get_level_values('season') else pd.Series(dtype=object)
        cal = pd.DataFrame({'r': r0, 'l': lm}).dropna()
        cal = cal[cal.index.map(dl).isin(DUMPL)]
        nG = pd.concat([d.home, d.away]).value_counts()
        cal = cal[cal.index.map(nG) >= 15]
        bb = np.polyfit(cal.l, cal.r, 1) if len(cal) > 30 else np.array([.6, -9.3])
        prior = {c: bb[0] * v + bb[1] for c, v in lm.items()}
        r, hfa = ridge(d, prior, LAM)
        big5 = r[r.index.map(dl).isin(['GB1', 'ES1', 'IT1', 'L1', 'FR1'])]
        shift = big5.mean() if len(big5) else 0
        out.append(pd.DataFrame({'club': r.index, 'season': s, 'r': r.values - shift,
                                 'comp': r.index.map(dl), 'lmv': r.index.map(lm), 'a': bb[1] - shift, 'b': bb[0]}))
    return pd.concat(out, ignore_index=True)


def add_value(A, R):
    A = A.merge(R[['club', 'season', 'r']], on=['club', 'season'], how='left')
    A['gar'] = np.where(A.comp.isin(VALUE), A.mins / 90 * (A.r.fillna(REPL) - REPL).clip(lower=0) / 11, 0)
    return A


# ---------------------------------------------------------------- outcome and FV scale
def age_at(t, dob):
    return (pd.Timestamp(f'{t}-07-01') - dob).dt.days / 365.25


def outcome(A, P):
    """peak value (best three GAR seasons at ages 22-26, zeros for missing) and its FV on the rarity scale"""
    s = A[A.gar > 0].groupby(['player_id', 'season']).gar.sum().reset_index()
    s['dob'] = s.player_id.map(P.dob)
    s['age'] = np.floor((pd.to_datetime(s.season.astype(str) + '-07-01') - s.dob).dt.days / 365.25)
    s = s[s.age.between(*PEAK_AGES)]
    peak = s.groupby('player_id').gar.apply(lambda v: float(np.sort(np.r_[v.values, 0, 0, 0])[-3:].mean()))
    d = P[P.dob.notna()].copy()
    d['s22'] = d.dob.dt.year + 22 - (d.dob.dt.month >= 7).astype(int)
    d['peak'] = d.index.map(peak).fillna(0.0)
    ref = d[d.s22.between(*COHORTS) & d.index.isin(A.player_id.unique())]
    nco = COHORTS[1] - COHORTS[0] + 1
    scale = {'nco': nco, 'ref': {}, 'sh': {}, 'v40': {}}
    for g in 'GDMF':
        v = np.sort(ref[ref.grp == g].peak.values)[::-1]
        scale['ref'][g] = v
        scale['sh'][g] = float((ref.grp == g).mean())
        scale['v40'][g] = float(v[int(250 * nco * scale['sh'][g]) - 1])
    d['fv'] = fv_from_peak(d.peak.values, d.grp.values, scale)
    return d, scale


def fv_from_peak(peak, grp, scale):
    xs, ys = np.log([c[1] for c in CUTS]), [c[0] for c in CUTS]
    out = np.zeros(len(peak))
    for i, (x, g) in enumerate(zip(peak, grp)):
        ref = scale['ref'][g]
        r = np.searchsorted(-ref, -x, side='right') / scale['nco'] / scale['sh'][g]
        if x <= 0:
            out[i] = 20
        elif r > CUTS[-1][1]:
            out[i] = 20 + 20 * min(x / scale['v40'][g], 1)
        else:
            out[i] = float(np.interp(math.log(max(r, .05)), xs, ys))
    return out


def peak_cuts(scale):
    """the outfield-midfield peak GAR at each FV cut, for the model tab"""
    out = []
    for fv, n in CUTS:
        row = [fv]
        for g in 'GDMF':
            ref, k = scale['ref'][g], int(round(n * scale['nco'] * scale['sh'][g]))
            row.append(round(float(ref[max(k - 1, 0)]), 2))
        out.append(row)
    return out


# ---------------------------------------------------------------- features at a snapshot
def team_games(G):
    g = G[G.comp.isin(DUMPL + FEEDV)]
    x = pd.concat([g[['home', 'season', 'date']].rename(columns={'home': 'club'}), g[['away', 'season', 'date']].rename(columns={'away': 'club'})])
    return x


def features(A, P, V, R, TG, t, snap, live=None):
    """one row per prospect (under 22 on July 1 of season t) with what was known on the snapshot date"""
    snap = pd.Timestamp(snap)
    prev = A[A.season.eq(t - 1)]
    prev2 = A[A.season.eq(t - 2)]
    cur = A[A.season.eq(t) & (A.date < snap)]
    seen = pd.Index(pd.concat([prev.player_id, cur.player_id]).unique())
    dob = P.dob.reindex(seen)
    age = (pd.Timestamp(f'{t}-07-01') - dob).dt.days / 365.25
    ids = age[(age < AGE_CUT) & (age >= 15)].index
    X = pd.DataFrame(index=ids)
    X['age'] = age.loc[ids]
    lgs = DUMPL + FEEDV

    def block(d, suf, tg):
        d = d[d.player_id.isin(ids)]
        v = d[d.comp.isin(VALUE)]
        X['gar' + suf] = v.groupby('player_id').gar.sum()
        X['mins' + suf] = v.groupby('player_id').mins.sum()
        X['gl' + suf] = v.groupby('player_id').gl.sum()
        X['ast' + suf] = v.groupby('player_id').ast.sum()
        lg = d[d.comp.isin(lgs)]
        X['lmins' + suf] = lg.groupby('player_id').mins.sum()
        main = lg.groupby(['player_id', 'club']).agg(m=('mins', 'sum'), n=('napp', 'sum'), b=('nbench', 'sum'))
        main['k'] = main.m * 1000 + main.n + main.b
        mc = main.reset_index().sort_values('k').groupby('player_id').tail(1).set_index('player_id')
        X['club' + suf] = mc.club
        cl = lg.groupby(['player_id']).comp.agg(lambda s: s.value_counts().index[0])
        X['comp' + suf] = cl
        X['tg' + suf] = mc.club.map(tg)
        X['bench' + suf] = d[d.comp.isin(VALUE)].groupby('player_id').nbench.sum()
        X['emins' + suf] = d[d.comp.isin(SD.EURO)].groupby('player_id').mins.sum()
        y = d[d.comp.isin(YOUTH)]
        X['ymins' + suf] = y.groupby('player_id').mins.sum()
        X['yga' + suf] = y.groupby('player_id').gl.sum() + y.groupby('player_id').ast.sum()

    block(prev, '1', TG[TG.season.eq(t - 1)].groupby('club').size())
    block(cur, '_td', TG[TG.season.eq(t) & (TG.date < snap)].groupby('club').size())
    X['gar2'] = prev2[prev2.player_id.isin(ids)].groupby('player_id').gar.sum()
    # this season's value at last season's club ratings (a club new to the data: what its squad value implies)
    R1 = R[R.season.eq(t - 1)].set_index('club')
    ab = R[R.season.eq(t - 1)][['a', 'b']].iloc[0] if (R.season == t - 1).any() else pd.Series({'a': -9.3, 'b': .6})
    cv = club_mv(cur, V) if len(cur) else pd.Series(dtype=float)
    cvt = cv.xs(t, level='season') if len(cv) and t in cv.index.get_level_values('season') else pd.Series(dtype=float)
    rp = {c: R1.r.get(c, ab.a + ab.b * cvt.get(c, np.nan)) for c in cur.club.dropna().unique()}
    c2 = cur[cur.player_id.isin(ids) & cur.comp.isin(VALUE)]
    rr = c2.club.map(rp).fillna(REPL)
    X['gar_td'] = (c2.mins / 90 * (rr - REPL).clip(lower=0) / 11).groupby(c2.player_id).sum()
    X['rclub1'] = X.club1.map(R1.r)
    X['rclub_td'] = X.club_td.map(rp)
    X['rlg_td'] = X.comp_td.map(R[R.season.eq(t - 1)].groupby('comp').r.mean())
    # market value on the day and a year before
    vv = V[V.player_id.isin(ids) & (V.date <= snap)].groupby('player_id').last()
    X['mv'] = vv.mv
    vv1 = V[V.player_id.isin(ids) & (V.date <= snap - pd.Timedelta(days=365))].groupby('player_id').last()
    X['mv1'] = vv1.mv
    if live is not None:
        X['mv'] = pd.Series(live).reindex(X.index).fillna(X.mv)
    X['grp'] = P.grp.reindex(X.index).fillna('M')
    X['ht'] = P.height_in_cm.reindex(X.index)
    X['t'] = t
    return X


def design(X):
    z = lambda c: X[c].fillna(0) if c in X else pd.Series(0, index=X.index)
    F = pd.DataFrame(index=X.index)
    F['age'] = X.age - 20
    F['age2'] = F.age ** 2
    F['lmv'] = np.log(X.mv.fillna(25000).clip(lower=25000) / 1e6)
    F['lmv2'] = F.lmv ** 2
    F['nomv'] = X.mv.isna().astype(float)
    F['dmv'] = np.where(X.mv.notna() & X.mv1.notna(), np.log(X.mv.clip(lower=25000) / X.mv1.clip(lower=25000)), 0)
    F['gar1'] = z('gar1')
    F['gar2'] = z('gar2')
    F['share1'] = (z('lmins1') / (z('tg1') * 90).replace(0, np.nan)).fillna(0).clip(0, 1)
    F['rclub1'] = ((z('rclub1') - REPL).clip(lower=0)) * (F.share1 > 0)
    F['ga90_1'] = np.where(z('mins1') >= 450, (z('gl1') + z('ast1')) / z('mins1').clip(lower=1) * 90, 0)
    F['gar_td'] = z('gar_td')
    F['share_td'] = (z('lmins_td') / (z('tg_td') * 90).replace(0, np.nan)).fillna(0).clip(0, 1)
    F['rclub_td'] = ((X.rclub_td.fillna(REPL) - REPL).clip(lower=0)) * (F.share_td > 0)
    # minutes share in a strong league: league strength (mean club rating last season) over replacement x share
    F['lg_share'] = (X.rlg_td.fillna(REPL) - REPL).clip(lower=0) * F.share_td
    F['ga90_td'] = np.where(z('mins_td') >= 270, (z('gl_td') + z('ast_td')) / z('mins_td').clip(lower=1) * 90, 0)
    F['emins'] = (z('emins1') + z('emins_td')) / 900
    F['bench'] = np.log1p(z('bench1') + z('bench_td'))
    F['ymins'] = (z('ymins1') + z('ymins_td')) / 900
    F['yga'] = np.where(z('ymins1') + z('ymins_td') >= 450, (z('yga1') + z('yga_td')) / (z('ymins1') + z('ymins_td')).clip(lower=1) * 90, 0)
    F['ht'] = ((X.ht - 181) / 7).fillna(0)
    F['gk'] = X.grp.eq('G').astype(float)
    F['fwd'] = X.grp.eq('F').astype(float)
    F['mid'] = X.grp.eq('M').astype(float)
    F['tier2'] = X.comp1.isin(FEEDV).astype(float) * (F.share1 > 0)
    F['noseen'] = ((z('mins1') + z('mins_td')) == 0).astype(float)
    F['age_lmv'] = F.age * F.lmv
    F['ga90_fwd'] = (F.ga90_1 + F.ga90_td) * F.fwd
    F['ht_gk'] = F.ht * F.gk
    F['age_share'] = F.age * (F.share1 + F.share_td)
    F['lmv_fwd'] = F.lmv * F.fwd
    F['lmv_gk'] = F.lmv * F.gk
    up = (X.rclub_td - X.rclub1).where(X.club_td.notna() & X.club1.notna() & X.club_td.ne(X.club1))
    F['club_up'] = up.fillna(0).clip(-3, 3)
    return F


# ---------------------------------------------------------------- fit
BASEF = ['age', 'lmv', 'nomv']


def snapdate(t, md):
    m, d = md
    return pd.Timestamp(year=t + (1 if m < 7 else 0), month=m, day=d)


def ols(F, y, cols):
    A = np.c_[np.ones(len(F)), F[cols].values]
    return np.linalg.lstsq(A, y, rcond=None)[0]


def pred(F, cols, b):
    return np.c_[np.ones(len(F)), F[cols].values] @ b


def loso(F, y, t, cols):
    e, p = np.zeros(len(y)), np.zeros(len(y))
    for s in np.unique(t):
        tr, te = t != s, t == s
        b = ols(F[tr], y[tr], cols)
        p[te] = pred(F[te], cols, b)
        e[te] = y[te] - p[te]
    return e, p


def select(F, y, t):
    cur = list(BASEF)
    e0, _ = loso(F, y, t, cur)
    seasons = np.unique(t)
    ev, log = {}, []
    cands = [c for c in F.columns if c not in cur]
    while True:
        best = None
        for c in cands:
            e, _ = loso(F, y, t, cur + [c])
            d = e0 ** 2 - e ** 2
            per = np.array([d[t == s].mean() for s in seasons])
            tt = per.mean() / (per.std(ddof=1) / math.sqrt(len(per)) + 1e-12)
            ev[c] = {'gain': round(float(d.mean()), 3), 't': round(float(tt), 1), 'wins': int((per > 0).sum()), 'of': len(per)}
            if tt >= 2 and (per > 0).sum() >= math.ceil(len(per) * 2 / 3) and (best is None or (e ** 2).mean() < best[1]):
                best = (c, (e ** 2).mean(), e)
        if not best:
            break
        cur.append(best[0]); cands.remove(best[0]); e0 = best[2]
        log.append((best[0], round(float(best[1]), 2)))
        print('  add', best[0], round(best[1], 2), ev[best[0]], flush=True)
    return cur, ev, log


# Oct 26 2026 (FV scorecard): the 40+ odds bend at the cut and 10 FV below it. One straight logistic ran ~5-7 points
# hot at FV 40-49 and cold at 25-34; with the two hinges, season-out log loss gains t 3.9 (7 of 8 seasons) and the
# band gap falls 1.6 -> 0.6 points. The same hinges at 50+ (t 1.8) and 60+ (t 0.9) fail t >= 2, so those stay straight.
ODDS_HINGES = {'p40': (0, -10), 'p50': (), 'p60': ()}


def odds_x(x, hinges=()):
    x = np.asarray(x, dtype=float)
    return np.c_[np.ones(len(x)), x, *[np.maximum(0, x - h) for h in hinges]]


def odds(w, x):
    """P(outcome >= the rung) from the grade minus the rung: a, b, then one slope change per hinge (ODDS_HINGES)"""
    hs = next((h for h in ODDS_HINGES.values() if len(h) == len(w) - 2), ())
    return 1 / (1 + np.exp(-(odds_x(np.atleast_1d(x), hs) @ np.array(w))))


def logit_fit(x, y, hinges=()):
    """P(y | x) = 1/(1+exp(-(a+bx+...))) by Newton"""
    X = odds_x(x, hinges)
    w = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (y - p)
        H = (X * (p * (1 - p))[:, None]).T @ X + 1e-6 * np.eye(len(w))
        w = w + np.linalg.solve(H, g)
    return [round(float(v), 4) for v in w]


def isotonic(p, y, width=2.5, nmin=30):
    """monotone map from out-of-sample grade to mean outcome: bins of the grade pooled until increasing"""
    o = np.argsort(p)
    p, y = p[o], y[o]
    bins, cur = [], []
    edge = math.floor(p[0] / width) * width
    for pi, yi in zip(p, y):
        if pi >= edge + width and len(cur) >= nmin:
            bins.append(cur); cur = []
            edge = math.floor(pi / width) * width
        cur.append((pi, yi))
    if cur:
        if len(cur) < nmin and bins:
            bins[-1] += cur
        else:
            bins.append(cur)
    blocks = [[np.mean([a for a, _ in b]), np.mean([c for _, c in b]), len(b)] for b in bins]
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][1] >= out[-1][1]:
            b2, b1 = out.pop(), out.pop()
            n = b1[2] + b2[2]
            out.append([(b1[0] * b1[2] + b2[0] * b2[2]) / n, (b1[1] * b1[2] + b2[1] * b2[2]) / n, n])
    return [[round(float(a), 2), round(float(c), 2)] for a, c, _ in out]


def calibrate(p, knots):
    """the isotonic map; past the last knot the top-band slope (fit on grades of 50+) carries on, and a sliver of the
    raw grade keeps the order inside flat stretches"""
    k = np.array(knots['k'])
    p = np.asarray(p, dtype=float)
    out = np.interp(p, k[:, 0], k[:, 1]) + .001 * p
    hi = p > k[-1, 0]
    out[hi] += knots['slope'] * (p[hi] - k[-1, 0])
    return out


def fit(scorecard=False):
    """scorecard: write only the held-out FV scorecard (scripts/fv_scorecard.py) into data/soccer_prospects_fit.json"""
    t0 = dt.datetime.now()
    G, A, P, V = load()
    print('loaded', len(G), 'games', len(A), 'appearances', len(P), 'players', dt.datetime.now() - t0, flush=True)
    R = club_ratings(G, A, V)
    A = add_value(A, R)
    O, scale = outcome(A, P)
    TG = team_games(G)
    done = O[O.s22 <= COHORTS[1]]
    rows = {}
    for md in SNAPS:
        xs = []
        for t in range(ROWS[0], ROWS[1] + 1):
            X = features(A, P, V, R, TG, t, snapdate(t, md))
            X = X[X.index.isin(done.index)]
            X['fv_out'] = done.fv.reindex(X.index)
            X['peak'] = done.peak.reindex(X.index)
            xs.append(X.reset_index().rename(columns={'index': 'player_id'}))
        rows[md] = pd.concat(xs, ignore_index=True)
        print('rows', md, len(rows[md]), flush=True)
    S = rows[SEL_SNAP]
    F = design(S)
    y, t = S.fv_out.values, S.t.values
    print('selecting on', len(S), 'rows; outcome var', round(y.var(), 2), flush=True)
    kept, ev, log = select(F, y, t)
    e_base, _ = loso(F, y, t, BASEF)
    models, oos = {}, {}
    for md in SNAPS:
        Sx = rows[md]
        Fx = design(Sx)
        b = ols(Fx, Sx.fv_out.values, kept)
        e, p = loso(Fx, Sx.fv_out.values, Sx.t.values, kept)
        eb, _ = loso(Fx, Sx.fv_out.values, Sx.t.values, BASEF)
        key = '%02d-%02d' % md
        models[key] = {'coef': dict(zip(['const'] + kept, [round(float(v), 4) for v in b])),
                       'mse': round(float((e ** 2).mean()), 2), 'mseBase': round(float((eb ** 2).mean()), 2),
                       'var': round(float(Sx.fv_out.var()), 2), 'n': int(len(Sx)),
                       'sd': round(float(e.std()), 2)}
        oos[md] = p
        print(key, models[key]['mse'], models[key]['mseBase'], flush=True)
    # the raw grade is a little hot at the top: map it to the mean outcome of its band (monotone), per snapshot. The
    # map is scored leave-one-season-out (fit on the other seasons' out-of-sample grades, applied to the held season;
    # Oct 25 2026 audit: the map used to be scored on the grades it was fit on), and kept only if that beats the raw
    # grade; the live map is the one fit on every season
    def iso_fit(pp, yy):
        top = pp >= 50
        return {'k': isotonic(pp, yy), 'slope': round(float(np.polyfit(pp[top], yy[top], 1)[0]), 3)}
    oosc = {}
    for md in SNAPS:
        key = '%02d-%02d' % md
        yy, pp, tt = rows[md].fv_out.values, oos[md], rows[md].t.values
        full = iso_fit(pp, yy)
        pc = np.zeros(len(pp))
        for s in np.unique(tt):
            m = tt == s
            pc[m] = calibrate(pp[m], iso_fit(pp[~m], yy[~m]))
        models[key]['mseCal'] = round(float(((yy - pc) ** 2).mean()), 2)
        models[key]['mseCalIn'] = round(float(((yy - calibrate(pp, full)) ** 2).mean()), 2)
        models[key]['isoKept'] = bool(models[key]['mseCal'] < models[key]['mse'])
        if models[key]['isoKept']:
            models[key]['iso'], oosc[md] = full, pc
        else:                                            # the identity: the raw grade
            models[key]['iso'], oosc[md] = {'k': [[0.0, 0.0], [100.0, 100.0]], 'slope': 0.0}, pp + .001 * pp
    # chances of a 40+ (top-flight career) and 50+ (big-five regular level) outcome from the out-of-sample grade
    p = oosc[SEL_SNAP]
    pr = {k: logit_fit(p - c, (y >= c).astype(float), ODDS_HINGES[k]) for k, c in (('p40', 40), ('p50', 50), ('p60', 60))}
    calib = []
    for lo in range(20, 75, 5):
        m = (p >= lo) & (p < lo + 5)
        if m.sum() >= 5:
            calib.append({'band': lo, 'n': int(m.sum()), 'pred': round(float(p[m].mean()), 1), 'real': round(float(y[m].mean()), 1),
                          'p50': round(float((y[m] >= 50).mean()), 3)})
    if scorecard:
        from fv_scorecard import card
        sc_ = card(p, y, cls=t, hinges={int(k[1:]): h for k, h in ODDS_HINGES.items()}, note=f'{len(y):,} player-seasons {int(t.min())}-{int(t.max())} (under {AGE_CUT} at the Oct 24 snapshot), '
                   'each graded by a fit that left his season out; outcome: the FV his best three GAR seasons at 22-26 earned; tier odds from a logistic on that grade, also season-out')
        print('scorecard', sc_['summary'], 'calib', calib)
        np.savez(os.path.join(CACHE, 'oos_rows.npz'), p=p, y=y, t=t)   # the held-out rows, for tier-odds tests
        cur_fit = json.load(open(FIT)); cur_fit['scorecard'] = sc_
        if '--odds' in sys.argv:                     # refit only the tier odds (ODDS_HINGES) on these rows
            cur_fit['prob'] = pr
        json.dump(cur_fit, open(FIT, 'w'), indent=1)
        return
    # top of the board: each season's top 50 by grade
    top = []
    for s in np.unique(t):
        m = t == s
        o = np.argsort(-p[m])[:50]
        top.append(float(y[m][o].mean()))
    fitj = {'asof': dt.date.today().isoformat(), 'rows': [int(t.min()), int(t.max())], 'n': int(len(y)),
            'cohorts': list(COHORTS), 'peakAges': list(PEAK_AGES), 'ageCut': AGE_CUT, 'repl': REPL,
            'cuts': peak_cuts(scale), 'kept': kept, 'ev': ev, 'models': models, 'prob': pr, 'calib': calib,
            'mse': round(float(((y - p) ** 2).mean()), 2), 'mseBase': round(float((e_base ** 2).mean()), 2),
            'r2': round(float(1 - ((y - p) ** 2).mean() / y.var()), 3), 'top50': round(float(np.mean(top)), 1),
            'scale': {'nco': scale['nco'], 'sh': scale['sh'], 'v40': scale['v40'],
                      'ref': {g: [round(float(x), 3) for x in v[v > 0]] for g, v in scale['ref'].items()}},
            'clubLine': {str(int(s)): [round(float(d.b.iloc[0]), 3), round(float(d.a.iloc[0]), 3)] for s, d in R.groupby('season')},
            'leagues': {c: round(float(d.r.mean()), 2) for c, d in R[R.season.eq(LAST - 1)].groupby('comp') if c in LEAGUE}}
    json.dump(fitj, open(FIT, 'w'), indent=1)
    # past prospects: the youngest Oct 24 row of each player, out of sample, next to what he became
    S = S.assign(fv=np.round(p).astype(int))
    first = S.sort_values('age').groupby('player_id').head(1)
    first = first[(first.fv >= 50) | (first.fv_out >= 55)]
    past = []
    for r in first.itertuples():
        past.append({'id': int(r.player_id), 'name': P.name.get(r.player_id), 'season': int(r.t), 'age': round(float(r.age), 1),
                     'pos': r.grp, 'club': club_name(r.club_td if pd.notna(r.club_td) else r.club1),
                     'mv': None if pd.isna(r.mv) else int(r.mv), 'fv': int(r.fv), 'out': int(round(r.fv_out)), 'peak': round(float(r.peak), 1)})
    past.sort(key=lambda r: (-r['fv'], -r['out']))
    with gzip.open(PAST, 'wt') as f:
        json.dump(past, f)
    # frozen base for the daily build: last two seasons' lines for anyone young enough, values, ratings
    young = P.index[P.dob >= pd.Timestamp(f'{LAST - AGE_CUT - 1}-07-01')]
    a = A[A.season.isin([LAST - 2, LAST - 1]) & A.player_id.isin(young)]
    a = a.groupby(['player_id', 'season', 'club', 'comp']).agg(mins=('mins', 'sum'), gl=('gl', 'sum'), ast=('ast', 'sum'),
                                                              gar=('gar', 'sum'), napp=('napp', 'sum'),
                                                              nbench=('nbench', 'sum')).reset_index()
    v = V[V.player_id.isin(young) & (V.date >= pd.Timestamp(f'{LAST - 2}-07-01'))]
    v = v.sort_values('date').drop_duplicates(['player_id', 'mv'], keep='first')
    tg = TG[TG.season.eq(LAST - 1)].groupby('club').size()
    pp = P.loc[P.index.isin(young), ['name', 'dob', 'position', 'sub_position', 'height_in_cm', 'grp']]
    base = {'apps': a.assign(club=a.club.astype('Int64')).values.tolist(), 'appcols': list(a.columns),
            'values': [[int(r.player_id), r.date.strftime('%Y-%m-%d'), float(r.mv)] for r in v.itertuples()],
            'ratings': R[R.season.isin([LAST - 2, LAST - 1])][['club', 'season', 'r', 'a', 'b', 'comp']].values.tolist(),
            'tg': {str(int(k)): int(n) for k, n in tg.items()},
            'players': {str(int(i)): [r['name'], None if pd.isna(r['dob']) else r['dob'].strftime('%Y-%m-%d'), r['position'],
                                      r['sub_position'], None if pd.isna(r['height_in_cm']) else float(r['height_in_cm']), r['grp']]
                        for i, r in pp.iterrows()},
            'clubs': CLUBS}
    with gzip.open(BASE, 'wt') as f:
        json.dump(base, f, default=lambda o: None if pd.isna(o) else int(o))
    print('fit done', dt.datetime.now() - t0)


CLUBS = {}
PART = {'age': 'age', 'age2': 'age', 'lmv': 'mv', 'lmv2': 'mv', 'nomv': 'mv', 'gk': 'pos', 'fwd': 'pos', 'mid': 'pos',
        'lmv_fwd': 'pos', 'lmv_gk': 'pos'}


def club_name(c):
    if c is None or pd.isna(c):
        return None
    c = int(c)
    if not CLUBS:
        try:
            cl = rd('clubs', usecols=['club_id', 'name'])
            CLUBS.update({int(k): v for k, v in zip(cl.club_id, cl.name)})
        except Exception:
            pass
    return CLUBS.get(c)


# ---------------------------------------------------------------- live build
POSS = {'Goalkeeper': 'GK', 'Centre-Back': 'CB', 'Left-Back': 'LB', 'Right-Back': 'RB', 'Defensive Midfield': 'DM',
        'Central Midfield': 'CM', 'Attacking Midfield': 'AM', 'Left Midfield': 'LM', 'Right Midfield': 'RM',
        'Left Winger': 'LW', 'Right Winger': 'RW', 'Second Striker': 'SS', 'Centre-Forward': 'CF'}


def club_names(ids, known):
    fn = os.path.join(SD.CACHE, 'clubs.json')
    have = json.load(open(fn)) if os.path.exists(fn) else {}
    todo = [str(i) for i in ids if str(i) not in have and int(i) not in known]
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(8) as ex:
        for i, r in zip(todo, ex.map(lambda i: SD.get(f'/club/{i}'), todo)):
            if r and r.get('data'):
                d = r['data']
                have[i] = (d.get('baseDetails') or {}).get('shortName') or d.get('name')
    json.dump(have, open(fn, 'w'))
    out = {int(k): v for k, v in known.items()}
    out.update({int(k): v for k, v in have.items()})
    return out


def refresh_profiles(ids, days=7):
    fn = os.path.join(SD.CACHE, 'players.json.gz')
    have = json.load(gzip.open(fn, 'rt')) if os.path.exists(fn) else {}
    today = dt.date.today().isoformat()
    lim = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    todo = [str(i) for i in ids if str(i) not in have or have[str(i)].get('_got', '') < lim]
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(10) as ex:
        for i, r in zip(todo, ex.map(lambda i: SD.get(f'/player/{i}'), todo)):
            if r and r.get('data'):
                d = r['data']
                keep = {k: d.get(k) for k in ('name', 'lifeDates', 'attributes', 'marketValueDetails')}
                keep['_got'] = today
                have[i] = keep
    with gzip.open(fn, 'wt') as f:
        json.dump(have, f)
    print('profiles', len(todo), 'fetched', flush=True)
    return have


def build():
    base = json.load(gzip.open(BASE, 'rt'))
    fitj = json.load(open(FIT))
    t = LAST
    today = pd.Timestamp(dt.date.today())
    SD.main_pull([*DUMPL, *SD.EURO, *SD.FEED], t)
    G, A = tm_games(DUMPL + SD.EURO + SD.FEED, [t])
    A = A.merge(G[['game_id', 'comp', 'date']], on='game_id')
    G['season'], A['season'] = t, t
    A = A[A.date >= pd.Timestamp(f'{t}-07-01')]
    G = G[G.date >= pd.Timestamp(f'{t}-07-01')]
    A['napp'] = (A.mins > 0).astype(int)
    A['nbench'] = (A.mins == 0).astype(int)
    A['gar'] = 0.0
    b = pd.DataFrame(base['apps'], columns=base['appcols'])
    b['date'] = pd.to_datetime(b.season.astype(str) + '-12-31')
    A = pd.concat([b, A], ignore_index=True)
    A['club'] = pd.to_numeric(A.club, errors='coerce')
    R = pd.DataFrame(base['ratings'], columns=['club', 'season', 'r', 'a', 'b', 'comp'])
    V = pd.DataFrame(base['values'], columns=['player_id', 'date', 'mv'])
    V['date'] = pd.to_datetime(V.date)
    V = pd.concat([V, A[A.mv.notna() & A.season.eq(t)][['player_id', 'date', 'mv']]], ignore_index=True).sort_values('date')
    tg_prev = pd.DataFrame([(int(k), t - 1, pd.Timestamp(f'{t - 1}-12-31')) for k, n in base['tg'].items() for _ in range(n)],
                           columns=['club', 'season', 'date'])
    TG = pd.concat([tg_prev, team_games(G)], ignore_index=True)
    P = pd.DataFrame.from_dict(base['players'], orient='index', columns=['name', 'dob', 'position', 'sub_position', 'height_in_cm', 'grp'])
    P.index = P.index.astype(int)
    P['dob'] = pd.to_datetime(P.dob)
    # anyone new: birth date from lineup ages, then a profile for everyone who may be under 22
    seen = pd.Index(A[A.season.isin([t - 1, t])].player_id.unique())
    ag = A[A.age.notna() & A.season.eq(t)]
    est = (ag.date - pd.to_timedelta((ag.age + .5) * 365.25, unit='D')).groupby(ag.player_id).median()
    dob = P.dob.reindex(seen).fillna(est.reindex(seen))
    cand = seen[((pd.Timestamp(f'{t}-07-01') - dob).dt.days / 365.25 < AGE_CUT + .5) | dob.isna()]
    prof = refresh_profiles(cand)
    live_mv = {}
    for i in cand:
        d = prof.get(str(i))
        if not d:
            continue
        at = d.get('attributes') or {}
        ld = d.get('lifeDates') or {}
        pos = at.get('position') or {}
        row = [d.get('name'), pd.to_datetime(ld.get('dateOfBirth'), errors='coerce'),
               {'Goalkeeper': 'Goalkeeper', 'Defender': 'Defender', 'Midfield': 'Midfield', 'Striker': 'Attack'}.get(pos.get('category')),
               pos.get('name'), (at.get('height') or 0) * 100 or np.nan, None]
        row[5] = GRP.get(row[2], 'M')
        old = P.loc[i].tolist() if i in P.index else [None] * 6
        P.loc[i] = [n if (n is not None and not (isinstance(n, float) and math.isnan(n)) and not (isinstance(n, type(pd.NaT)) and pd.isna(n))) else o
                    for n, o in zip(row, old)]
        cur = ((d.get('marketValueDetails') or {}).get('current') or {}).get('value')
        if cur:
            live_mv[i] = cur
    P['dob'] = pd.to_datetime(P.dob)
    X = features(A, P, V, R, TG, t, today, live=live_mv)
    F = design(X)
    doy = lambda d: (d - pd.Timestamp(year=d.year if d.month >= 7 else d.year - 1, month=7, day=1)).days
    key = min(fitj['models'], key=lambda k: abs(doy(snapdate(t if int(k[:2]) >= 7 else t, (int(k[:2]), int(k[3:])))) - doy(today)))
    m = fitj['models'][key]
    cols = [c for c in m['coef'] if c != 'const']
    fvx = calibrate(m['coef']['const'] + F[cols].values @ np.array([m['coef'][c] for c in cols]), m['iso']).clip(20, 80)
    X['fvx'] = fvx
    pr = fitj['prob']
    sig = lambda w, x: odds(w, x)[0]
    names = club_names(pd.concat([X.club_td, X.club1]).dropna().astype(int).unique(), {int(k): v for k, v in base['clubs'].items()})
    # scouting-report dropdowns (the shown top 500): each input's push on the raw grade against the average prospect in
    # the pool, inputs that move together summed
    push = (F[cols] - F[cols].mean()) * np.array([m['coef'][c] for c in cols])
    push = push.T.groupby(lambda c: PART.get(c, c)).sum().T
    rows = []
    for n, (i, r) in enumerate(X.sort_values('fvx', ascending=False).iterrows()):
        club = r.club_td if pd.notna(r.club_td) else r.club1
        comp = r.comp_td if isinstance(r.comp_td, str) else r.comp1
        sp = P.sub_position.get(i)
        rows.append({
            'id': int(i), 'name': P.name.get(i) or str(i), 'pos': POSS.get(sp, {'G': 'GK', 'D': 'D', 'M': 'M', 'F': 'F'}[r.grp]),
            'grp': r.grp, 'club': names.get(int(club)) if pd.notna(club) else None,
            'lg': SHORT.get(comp) if isinstance(comp, str) else None, 'league': LEAGUE.get(comp) if isinstance(comp, str) else None,
            'age': round(float(r.age), 1), 'fv': int(round(r.fvx)), 'fvx': round(float(r.fvx), 2),
            'mv': None if pd.isna(r.mv) else int(r.mv),
            'min': int(r.mins_td) if pd.notna(r.mins_td) else 0, 'min1': int(r.mins1) if pd.notna(r.mins1) else 0,
            'gar': round(float(F.gar_td[i]), 2), 'gar1': round(float(F.gar1[i]), 2),
            'sh': round(float(F.share_td[i]), 2), 'ga': int((r.gl_td if pd.notna(r.gl_td) else 0) + (r.ast_td if pd.notna(r.ast_td) else 0)),
            'p40': round(float(sig(pr['p40'], r.fvx - 40)), 3), 'p50': round(float(sig(pr['p50'], r.fvx - 50)), 3),
            'p60': round(float(sig(pr['p60'], r.fvx - 60)), 3),
            'prov': bool(F.noseen[i] > 0)})
        if n < 500:
            pp = push.loc[i]
            rows[-1].update({'parts': [[k, round(float(v), 2)] for k, v in pp[pp.abs() >= .05].sort_values(key=abs, ascending=False).items()],
                             'ht': None if pd.isna(r.ht) else int(r.ht), 'rc': None if pd.isna(r.rclub_td) else round(float(r.rclub_td), 2),
                             'ym': int(r.ymins1 if pd.notna(r.ymins1) else 0) + int(r.ymins_td if pd.notna(r.ymins_td) else 0)})
    past = json.load(gzip.open(PAST, 'rt'))
    out = {'asof': dt.date.today().isoformat(), 'season': f'{t}-{str(t + 1)[2:]}', 'born': f'{t - AGE_CUT}-07-01',
           'snap': key, 'pool': len(rows), 'board': rows[:2000], 'past': past[:400],
           'fit': {k: fitj[k] for k in ('rows', 'n', 'cohorts', 'peakAges', 'ageCut', 'repl', 'cuts', 'kept', 'ev', 'prob',
                                        'calib', 'mse', 'mseBase', 'r2', 'top50', 'leagues')},
           'model': {'key': key, **m}}
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), allow_nan=False)
    print('board', len(rows), 'snapshot', key)


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit()
    elif '--scorecard' in sys.argv:
        fit(scorecard=True)
    else:
        build()
