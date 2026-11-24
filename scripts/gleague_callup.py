#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""G League call-up odds for the NBA ARKBOARD: every G League player this season with his chance of NBA minutes next
season, of being an NBA regular next season (1,000+ minutes), his expected NBA VORX per season over the next three,
and his expected NBA XPM over the minutes he plays in those three (xXPM).

    python3 scripts/gleague_callup.py --research   # fetch every season, fit, backtest -> data/gleague_callup_fit.json
    python3 scripts/gleague_callup.py              # this season -> static/data/gleague.json (uses the fit file)
    python3 scripts/gleague_callup.py --past       # every past season's end-of-season board -> static/data/gleague-past.json

Source: stats.gleague.nba.com leaguedashplayerstats (LeagueID 20), Base + Advanced totals, regular season and
Showcase Cup (its own season type since 2021-22), cached in scripts/.cache/gleague/<YYYY-YY>_<Base|Advanced>_<0|SC>.json.
PLAYER_ID is the NBA person id; the NBA side is the XPM board (static/data/nba-xpm/<season>.json, bbref ids), joined
by scripts/names.py (key + surname) and birth year from both sides' ages (within 1.6 years).

Rows: a player's G League season (both season types summed, 50+ minutes). Features: age (and squared), log G League
minutes, games, per-36 box (pts reb ast stl blk tov 3PA FTA, Game Score, +/-), TS%, usage, AST%, OREB%, DREB%, net
rating, PIE; NBA history through LAST season only (log career minutes, career XPM shrunk to -2 with 500 MP), draft
round 1 / 2, log pick, years since the draft; `part` = 1 while only the Showcase Cup is played, falling to 0 as the
34-game regular season fills. Training pools full seasons 2009-25 (2008-09 on) with Showcase-only rows 2022-25 (part 1).
Targets: NBA 1 = any NBA minutes next season; REG = 1,000+ minutes (per 82 games; the league's 270th player, nine a team, plays about
1,000 every season, and that line splits later VORX best: Nov 17 2026, was 500); xVORX 3Y = P(any NBA game in the
next 3 seasons) x E[3-season VORX | he plays] (ridge, lambda POS_LAM, on those who played), shown per season (/ 3); a season out
of the NBA counts 0, so xVORX sits near 0 for most of the league. xXPM = E[minute-weighted XPM, next 3 seasons | he plays]
(ridge, lambda XX_LAM, weighted by those minutes): the rate, without the chance or the minutes.
Ridge logistic (lambda 1), standardized. Draft slot counts only drafts held before the G League season.
Backtest: leave one season out, scored per season against the same model without G League production.
Display only (build): exact age on Feb 1 from the G League team rosters' birth dates (ESPN's NBA rosters for assigned
players missing there), contract tag TW = the stats API's TwoWay list, NBA = on an ESPN NBA roster and not two-way;
cached in scripts/data/gleague_status.json. Exhibit 10 deals have no free source.
"""
import json, math, os, sys, time, glob, collections, datetime, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names

CACHE = os.path.join(HERE, '.cache', 'gleague')
XPM = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
DRAFT = os.path.join(HERE, 'nba_draft.json')
FIT = os.path.join(ROOT, 'data', 'gleague_callup_fit.json')
OUT = os.path.join(ROOT, 'static', 'data', 'gleague.json')
PAST = os.path.join(ROOT, 'static', 'data', 'gleague-past.json')
STATUS = os.path.join(HERE, 'data', 'gleague_status.json')   # {season: {'dob': {pid: date}, 'tw': [pid], 'nba': [pid]}}
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
API = ('https://stats.gleague.nba.com/stats/leaguedashplayerstats?LeagueID=20&Season={s}&SeasonType={t}&PerMode=Totals'
       '&MeasureType={m}&LastNGames=0&Month=0&OpponentTeamID=0&PaceAdjust=N&Period=0&PlusMinus=N&Rank=N&TeamID=0&TwoWay=0')
REG_GAMES = 34
REG_MP = 1000      # NBA regular: minutes next season per 82 games
MIN_ROW = 50        # the fit's floor: fewer G League minutes than this and he is not on the board yet
# G League team -> NBA parent (None: no affiliate) and its ESPN logo code
TEAMS = {'AUS': ('SA', 'aus'), 'CCG': ('WSH', 'cap'), 'CLC': ('CLE', 'clc'), 'CVL': ('LAL', 'cvl'), 'CPS': ('ATL', 'cps'),
         'DEL': ('PHI', 'del'), 'GBO': ('CHA', 'gbo'), 'GRG': ('DEN', 'grd'), 'IWA': ('MIN', 'iwa'), 'LIN': ('BKN', 'lin'),
         'MNE': ('BOS', 'mne'), 'MHU': ('MEM', 'mhu'), 'MXC': (None, 'mxc'), 'MCC': ('DET', 'mcc'), 'NOB': ('IND', 'nob'),
         'OKL': ('OKC', 'okl'), 'OSC': ('ORL', 'osc'), 'RAP': ('TOR', 'rap'), 'RCR': ('POR', 'rcity'), 'RGV': ('HOU', 'rgv'),
         'SLC': ('UTAH', 'slc'), 'SDC': ('LAC', 'san'), 'SCW': ('GS', 'scw'), 'SXF': ('MIA', 'sxf'), 'STO': ('SAC', 'sto'),
         'TEX': ('DAL', 'tex'), 'VAL': ('PHX', 'valley'), 'WES': ('NY', 'wes'), 'WCB': ('CHI', 'wcb'), 'WIS': ('MIL', 'wis'),
         'LTN': ('NO', 'lak'), 'BIR': ('NO', 'bir'), 'GLI': (None, 'gli')}

SUM = ['GP', 'MIN', 'FGM', 'FGA', 'FG3M', 'FG3A', 'FTM', 'FTA', 'OREB', 'DREB', 'REB', 'AST', 'TOV', 'STL', 'BLK', 'PF', 'PTS', 'PLUS_MINUS']
WAV = ['TS_PCT', 'USG_PCT', 'AST_PCT', 'OREB_PCT', 'DREB_PCT', 'NET_RATING', 'PIE']
PROD = ['pts36', 'reb36', 'ast36', 'stl36', 'blk36', 'tov36', 'gs36', 'fg3a36', 'fta36', 'ts', 'usg', 'astp', 'orb', 'drb', 'net', 'pie', 'pm36']
HIST = ['age', 'lnmp_c', 'xpm_p', 'r1', 'r2', 'lpk', 'yrs_d', 'lmin', 'gp', 'part']
FEATS = HIST + PROD


def sname(y): return f'{y - 1}-{str(y)[2:]}'


def current_season(today=None):
    t = today or datetime.date.today()
    return t.year + (t.month >= 9)


def fetch(y, fresh=False):
    """both season types x Base/Advanced for season y (end year) into the cache; refetched when fresh"""
    os.makedirs(CACHE, exist_ok=True)
    for tag, st in (('0', 'Regular%20Season'), ('SC', 'Showcase')):
        if tag == 'SC' and y < 2022: continue
        for m in ('Base', 'Advanced'):
            fn = os.path.join(CACHE, f'{sname(y)}_{m}_{tag}.json')
            if os.path.exists(fn) and not fresh: continue
            req = urllib.request.Request(API.format(s=sname(y), t=st, m=m), headers={
                'User-Agent': UA, 'Referer': 'https://gleague.nba.com/', 'Origin': 'https://gleague.nba.com', 'Accept': 'application/json'})
            for k in range(4):
                try:
                    d = json.load(urllib.request.urlopen(req, timeout=90)); break
                except Exception as e:
                    if k == 3: raise
                    time.sleep(5 * (k + 1))
            json.dump(d, open(fn, 'w')); time.sleep(1.5)


def gl_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://gleague.nba.com/', 'Origin': 'https://gleague.nba.com',
                                               'Accept': 'application/json'})
    for k in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            if k == 2: raise
            time.sleep(4 * (k + 1))


def table(d):
    r = d['resultSets'][0]; return [dict(zip(r['headers'], x)) for x in r['rowSet']]


def status(y, players):
    """birth dates (G League team rosters), two-way contracts (the stats API's TwoWay filter, both season types) and
    NBA contracts on assignment (on an ESPN NBA roster, not two-way) for season y; each part keeps the last good pull"""
    st = json.load(open(STATUS)) if os.path.exists(STATUS) else {}
    cur = st.get(str(y), {'dob': {}, 'tw': [], 'nba': []})
    teams = set()
    for tag in ('0', 'SC'):
        teams |= {r['TEAM_ID'] for r in rs(os.path.join(CACHE, f'{sname(y)}_Base_{tag}.json')) if r.get('TEAM_ID')}
    for t in sorted(teams):
        try:
            for r in table(gl_get(f'https://stats.gleague.nba.com/stats/commonteamroster?LeagueID=20&Season={sname(y)}&TeamID={t}')):
                try: cur['dob'][str(r['PLAYER_ID'])] = datetime.datetime.strptime(r['BIRTH_DATE'], '%b %d, %Y').date().isoformat()
                except (TypeError, ValueError): pass
        except Exception as e: print('roster', t, 'kept:', e)
        time.sleep(0.6)
    try:
        tw = set()
        for st_ in ('Regular%20Season', 'Showcase'):
            tw |= {r['PLAYER_ID'] for r in table(gl_get(API.format(s=sname(y), t=st_, m='Base').replace('TwoWay=0', 'TwoWay=1')))}
            time.sleep(0.6)
        cur['tw'] = sorted(tw)
    except Exception as e: print('two-way list kept:', e)
    try:
        import faces
        ros = faces.espn_rosters(faces.ESPN_NBA)
        by_ph = {str(a['id']) for a in ros}; by_nm = {(names.key(a['name']), a['team']) for a in ros}
        tws = set(cur['tw']); dph = {str(a['id']): a.get('dob') for a in ros}; dnm = {(names.key(a['name']), a['team']): a.get('dob') for a in ros}
        on = [p for p in players if (p.get('ph') and str(p['ph']) in by_ph) or (p.get('nba') and (names.key(p['n']), p['nba']) in by_nm)]
        cur['nba'] = sorted(p['id'] for p in on if p['id'] not in tws)
        for p in on:      # assigned NBA players are not always on the G League club's roster: ESPN's birth date
            d = dph.get(str(p.get('ph'))) or dnm.get((names.key(p['n']), p.get('nba')))
            if d and str(p['id']) not in cur['dob']: cur['dob'][str(p['id'])] = d
    except Exception as e: print('NBA rosters kept:', e)
    st[str(y)] = cur
    json.dump(st, open(STATUS, 'w'), separators=(',', ':'), sort_keys=True)
    return cur


def rs(fn):
    if not os.path.exists(fn): return []
    d = json.load(open(fn))['resultSets'][0]
    return [dict(zip(d['headers'], r)) for r in d['rowSet']]


def gl_season(y, tags=('0', 'SC')):
    """{person id: summed season row} with minute-weighted advanced rates; team = most minutes"""
    out = {}
    for tag in tags:
        b = rs(os.path.join(CACHE, f'{sname(y)}_Base_{tag}.json'))
        a = {r['PLAYER_ID']: r for r in rs(os.path.join(CACHE, f'{sname(y)}_Advanced_{tag}.json'))}
        for r in b:
            p = r['PLAYER_ID']
            o = out.setdefault(p, {'id': p, 'n': None, 'age': None, 'tm': None, 'tmmin': -1, 'reg': 0,
                                   **{k: 0 for k in SUM}, **{'w_' + k: 0.0 for k in WAV}})
            if r['PLAYER_NAME']: o['n'] = r['PLAYER_NAME']
            if r['AGE'] and 16 <= r['AGE'] <= 45: o['age'] = r['AGE']
            m = r['MIN'] or 0
            for k in SUM: o[k] += r[k] or 0
            if tag == '0': o['reg'] += r['GP'] or 0
            if m > o['tmmin']: o['tm'], o['tmmin'] = r['TEAM_ABBREVIATION'], m
            ad = a.get(p)
            if ad:
                for k in WAV: o['w_' + k] += (ad.get(k) or 0) * m
    for o in out.values():
        m = o['MIN'] or 1e-9
        for k in WAV: o[k] = o.pop('w_' + k) / m
    return out


def load_nba():
    by, games = {}, {}
    for f in sorted(glob.glob(os.path.join(XPM, '*.json'))):
        y = int(os.path.basename(f)[:4]); d = json.load(open(f))
        by[y] = {p['id']: p for p in d['players']}; games[y] = d.get('games') or 82
    return by, games


class World:
    def __init__(self):
        self.NB, self.GAMES = load_nba()
        bb, bn = collections.defaultdict(list), {}
        for y, ps in self.NB.items():
            for b, p in ps.items():
                if p.get('age') is None: continue
                bb[b].append(y - p['age']); bn[b] = p['n']
        self.idx = collections.defaultdict(dict)
        for b, v in bb.items(): self.idx[names.parts(bn[b])[1]][b] = (bn[b], sum(v) / len(v))
        self.draft = {}
        for y, rows in json.load(open(DRAFT)).items():
            for pk, bid, n, tm in rows: self.draft.setdefault(names.key(n), []).append((int(y), pk, bid))
        self.pb = {}

    def link(self, p, n, births):
        """person id -> bbref id: same name by names.strength (2+), implied birth years within 1.6"""
        if p in self.pb: return self.pb[p]
        bb = sum(births) / len(births) if births else None
        best = None
        for b, (bnm, by_) in self.idx.get(names.parts(n)[1], {}).items():
            st = names.strength(n, bnm)
            if st < 2: continue
            dd = abs(by_ - bb) if bb is not None else 0.5
            sc = dd + (0 if st == 3 else 0.3)
            if dd <= 1.6 and (best is None or sc < best[0]): best = (sc, b)
        self.pb[p] = best[1] if best else None
        return self.pb[p]

    def xpm_thru(self, b, upto):
        s = m = 0.0
        for z, ps in self.NB.items():
            if z <= upto and b in ps:
                q = ps[b]; mp = q.get('mp') or 0
                if q.get('xpm') is not None: s += q['xpm'] * mp; m += mp
        return (s - 2 * 500) / (m + 500), m

    def dinfo(self, n, y, age, b):
        for dy, pk, bid in self.draft.get(names.key(n), []):
            if dy >= y: continue        # the June draft after this G League season is not known during it
            if (b and bid == b) or (not b and (age is None or 17 <= age - (y - dy) <= 25.5)): return pk, dy
        return None, None

    def row(self, y, o, part):
        n = o['n'] or ''; age = o['age']; b = self.pb.get(o['id'])
        m = o['MIN'] or 0
        r36 = lambda k: 36 * o[k] / m if m > 0 else 0.0
        pk, dy = self.dinfo(n, y, age, b)
        xp, cmp_ = self.xpm_thru(b, y - 1) if b else (-2.0, 0.0)
        gs = (o['PTS'] + .4 * o['FGM'] - .7 * o['FGA'] - .4 * (o['FTA'] - o['FTM']) + .7 * o['OREB'] + .3 * o['DREB'] + o['STL']
              + .7 * o['AST'] + .7 * o['BLK'] - .4 * o['PF'] - o['TOV'])
        f = {'age': age if age else 24.0, 'lmin': math.log1p(m), 'gp': o['GP'], 'part': part,
             'pts36': r36('PTS'), 'reb36': r36('REB'), 'ast36': r36('AST'), 'stl36': r36('STL'), 'blk36': r36('BLK'),
             'tov36': r36('TOV'), 'gs36': 36 * gs / m if m > 0 else 0.0, 'fg3a36': r36('FG3A'), 'fta36': r36('FTA'),
             'ts': o['TS_PCT'], 'usg': o['USG_PCT'], 'astp': o['AST_PCT'], 'orb': o['OREB_PCT'], 'drb': o['DREB_PCT'],
             'net': o['NET_RATING'], 'pie': o['PIE'], 'pm36': r36('PLUS_MINUS'),
             'lnmp_c': math.log1p(cmp_), 'xpm_p': xp, 'r1': 1.0 if pk and pk <= 30 else 0.0, 'r2': 1.0 if pk and pk > 30 else 0.0,
             'lpk': math.log(pk) if pk else 0.0, 'yrs_d': float(y - dy) if dy else 0.0}
        info = {'pk': pk, 'dy': dy, 'cmp': cmp_, 'gs36': f['gs36'], 'b': b}
        mp = lambda z: (self.NB.get(z, {}).get(b, {}).get('mp') or 0) * 82 / self.GAMES.get(z, 82) if b else 0.0
        vx = lambda z: (self.NB.get(z, {}).get(b, {}).get('vorx0', self.NB.get(z, {}).get(b, {}).get('vorx')) or 0) if b else 0.0
        t = {'nba1': 1.0 if mp(y + 1) > 0 else 0.0, 'stick': 1.0 if mp(y + 1) >= REG_MP else 0.0,
             'any3': 1.0 if b and any(self.NB.get(z, {}).get(b) for z in (y + 1, y + 2, y + 3)) else 0.0,
             'xv3': sum(vx(z) for z in (y + 1, y + 2, y + 3)), 'mp3': 0.0, 'xpm3': 0.0}
        for z in (y + 1, y + 2, y + 3):     # NBA minutes and minute-weighted XPM over the next three seasons (xXPM target)
            q = self.NB.get(z, {}).get(b) if b else None
            if q and q.get('xpm') is not None and (q.get('mp') or 0) > 0: t['mp3'] += q['mp']; t['xpm3'] += q['xpm'] * q['mp']
        if t['mp3'] > 0: t['xpm3'] /= t['mp3']
        return f, t, info


def design(F, feats, mu=None, sd=None):
    X = np.array([[f[k] for k in feats] for f in F], float)
    X = np.column_stack([X, (X[:, feats.index('age')] - 24) ** 2])
    if mu is None: mu, sd = X.mean(0), X.std(0) + 1e-9
    return (X - mu) / sd, mu, sd


def logit_fit(X, y, lam=1.0):
    n, k = X.shape; Xb = np.column_stack([np.ones(n), X]); b = np.zeros(k + 1)
    P = lam * np.eye(k + 1); P[0, 0] = 0
    for _ in range(60):
        p = 1 / (1 + np.exp(-np.clip(Xb @ b, -30, 30))); W = p * (1 - p) + 1e-9
        st = np.linalg.solve(Xb.T @ (Xb * W[:, None]) + P, Xb.T @ (y - p) - P @ b); b += st
        if np.abs(st).max() < 1e-9: break
    return b


# E[3-season VORX | plays] ridge. Lambda 3 -> 300 (Nov 17 2026): early-season boards (3 / 6 / 10 games in, DateTo
# snapshots 2009-10..2022-23) overshot, held-out slope of actual on predicted .56 (.43 at 3 games). Leave one season out
# on snapshot rows, lambda nested from {3, 30, 100, 300}: MSE .7205 -> .6976, t -3.20, 11/13 seasons, passes Holm over
# 4; full seasons .8736 -> .8800, t +0.71. Minute shrinkage of rates, training on snapshots, a global calibration slope
# and a wider grid {300..10000} failed
POS_LAM = 300.0


def ridge_fit(X, y, lam=3.0, w=None):
    n, k = X.shape; Xb = np.column_stack([np.ones(n), X]); P = lam * np.eye(k + 1); P[0, 0] = 0
    w = np.ones(n) if w is None else w / w.mean()
    return np.linalg.solve(Xb.T @ (Xb * w[:, None]) + P, Xb.T @ (w * y))


# xXPM = E[NBA XPM over his NBA minutes, next 3 seasons | he plays]: ridge (lambda XX_LAM) on the rows that played, weighted
# by those minutes (Nov 23 2026). Leave one season out, minute-weighted MSE vs the same model without G League stats:
# full seasons 2.23 vs 2.62, t -3.6, 11/15 (lambda 30 / 300 / 3000 and weight caps 250 / 1,000 / 3,000 / none all pass;
# uncapped = unbiased on the minute-weighted target, bias .00 vs +.43 capped at 1,000). Boards 3 / 6 / 10 games in: 2.04 vs
# 2.28, t -1.45, 9/13, slope .75 (better, not significant)
XX_LAM = 300.0


def lin(b, X): return np.column_stack([np.ones(len(X)), X]) @ b
def sig(z): return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def fit_all(rows, feats):
    """{'mu','sd','nba1','stick','any3','pos'} from rows [(y, f, t)]"""
    F = [r[1] for r in rows]; X, mu, sd = design(F, feats)
    out = {'mu': mu.tolist(), 'sd': sd.tolist()}
    for k in ('nba1', 'stick'):
        out[k] = logit_fit(X, np.array([r[2][k] for r in rows])).tolist()
    m3 = np.array([r[0] <= LAST3 for r in rows])
    a = np.array([r[2]['any3'] for r in rows])
    out['any3'] = logit_fit(X[m3], a[m3]).tolist()
    pos = m3 & (a == 1)
    out['pos'] = ridge_fit(X[pos], np.array([r[2]['xv3'] for r in rows])[pos], POS_LAM).tolist()
    mp3 = np.array([r[2]['mp3'] for r in rows]); pl = m3 & (mp3 > 0)
    out['xx'] = ridge_fit(X[pl], np.array([r[2]['xpm3'] for r in rows])[pl], XX_LAM, mp3[pl]).tolist()
    return out


def predict(fit, F, feats):
    X, _, _ = design(F, feats, np.array(fit['mu']), np.array(fit['sd']))
    p1, p5 = sig(lin(np.array(fit['nba1']), X)), sig(lin(np.array(fit['stick']), X))
    p5 = np.minimum(p5, p1)
    xv = sig(lin(np.array(fit['any3']), X)) * lin(np.array(fit['pos']), X)
    xx = lin(np.array(fit['xx']), X)
    return p1, p5, xv, xx


LAST1, LAST3 = 2025, 2023


def ll(p, y): p = np.clip(p, 1e-4, 1 - 1e-4); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(p, y):
    o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1); n1 = y.sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def tdist_p(t, df):
    """two-sided p for Student t (numeric integration, no scipy)"""
    x = np.linspace(0, abs(t), 4001); c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
    dens = c * (1 + x ** 2 / df) ** (-(df + 1) / 2)
    return float(max(0.0, 1 - 2 * np.trapezoid(dens, x)))


def research():
    W = World()
    for y in range(2008, current_season() + 1): fetch(y, fresh=(y >= current_season() - 1))
    rows = []      # (season, features, targets, sc flag)
    seasons = {}
    # from 2008-09: a 2007-08 row's label is the 2008-09 NBA season, before the XPM boards (2009-10 on), so every one
    # read 'no NBA'. Dropping them (Nov 16 2026), leave one season out: NBA% LL .3345 -> .3338 (t -0.7, 10/17), REG% (500 MP)
    # .1886 -> .1885 (t -0.4, 11/17), xVORX MSE .881 -> .880 (t -1.8, 11/15); shipped as a label fix
    for y in range(2009, LAST1 + 1):
        seasons[y] = (gl_season(y), [gl_season(y, ('SC',))] if y >= 2022 else [])
    births = collections.defaultdict(list); nm = {}
    for y, (full, scs) in seasons.items():
        for p, o in full.items():
            if o['n']: nm[p] = o['n']
            if o['age']: births[p].append(y - o['age'])
    for p, n in nm.items(): W.link(p, n, births[p])
    for y, (full, scs) in seasons.items():
        for part, src in [(0.0, full)] + [(1.0, s) for s in scs]:
            for p, o in src.items():
                o['n'] = o['n'] or nm.get(p)
                if (o['MIN'] or 0) < MIN_ROW or not o['n']: continue
                f, t, info = W.row(y, o, part)
                rows.append((y, f, t, part, info))
    print('rows', len(rows), 'linked persons', sum(1 for v in W.pb.values() if v))
    yrs = sorted({r[0] for r in rows})
    # leave one season out: the served model vs the same model without G League production
    oos = {'full': collections.defaultdict(list), 'hist': collections.defaultdict(list)}
    for s in yrs:
        tr = [r for r in rows if r[0] != s]; te = [r for r in rows if r[0] == s]
        for name, feats in (('full', FEATS), ('hist', HIST)):
            fit = fit_all([(r[0], r[1], r[2]) for r in tr], feats)
            p1, p5, xv, xx = predict(fit, [r[1] for r in te], feats)
            for i, r in enumerate(te):
                oos[name]['p1'].append(p1[i]); oos[name]['p5'].append(p5[i]); oos[name]['xv'].append(xv[i]); oos[name]['xx'].append(xx[i])
                if name == 'full':
                    oos['y'] = oos.get('y', collections.defaultdict(list))
                    for k in ('nba1', 'stick', 'xv3', 'xpm3', 'mp3'): oos['y'][k].append(r[2][k])
                    oos['y']['yr'].append(r[0]); oos['y']['part'].append(r[3]); oos['y']['nonba'].append(r[1]['lnmp_c'] == 0)
    Y = {k: np.array(v) for k, v in oos['y'].items()}
    P = {n: {k: np.array(v) for k, v in oos[n].items()} for n in ('full', 'hist')}
    tests, rep = [], {}
    for key, tk, kind, last in (('p1', 'nba1', 'll', LAST1), ('p5', 'stick', 'll', LAST1), ('xv', 'xv3', 'mse', LAST3),
                                ('xx', 'xpm3', 'wmse', LAST3)):
        d = []; ss = [s for s in yrs if s <= last]
        sel = (lambda m: m & (Y['mp3'] > 0) & (Y['part'] == 0)) if kind == 'wmse' else (lambda m: m)
        for s in ss:
            m = sel(Y['yr'] == s); y = Y[tk][m]; w = Y['mp3'][m]
            sc = (lambda p: ll(p, y)) if kind == 'll' else (lambda p: float(np.mean((p - y) ** 2))) if kind == 'mse' else (lambda p: float(np.average((p - y) ** 2, weights=w)))
            d.append(sc(P['full'][key][m]) - sc(P['hist'][key][m]))
        d = np.array(d); t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
        m = sel(Y['yr'] <= last); y = Y[tk][m]; pf = P['full'][key][m]; ph = P['hist'][key][m]
        e = {'target': tk, 'seasons': len(ss), 'n': int(m.sum()), 't': round(t, 2), 'p': round(tdist_p(t, len(ss) - 1), 4),
             'wins': int((d < 0).sum())}
        if kind == 'll':
            nb = m & Y['nonba']
            e.update({'ll': round(ll(pf, y), 4), 'll_hist': round(ll(ph, y), 4), 'brier': round(float(np.mean((pf - y) ** 2)), 4),
                      'auc': round(auc(pf, y), 3), 'auc_hist': round(auc(ph, y), 3), 'rate': round(float(y.mean()), 3),
                      'auc_nonba': round(auc(P['full'][key][nb], Y[tk][nb]), 3), 'auc_nonba_hist': round(auc(P['hist'][key][nb], Y[tk][nb]), 3),
                      'showcase_ll': round(ll(P['full'][key][m & (Y['part'] == 1)], Y[tk][m & (Y['part'] == 1)]), 4)})
            q = np.quantile(pf, np.linspace(0, 1, 11)); bins = []
            for i in range(10):
                s_ = (pf >= q[i]) & (pf <= q[i + 1]) if i == 9 else (pf >= q[i]) & (pf < q[i + 1])
                bins.append([round(float(pf[s_].mean()), 3), round(float(y[s_].mean()), 3), int(s_.sum())])
            e['calibration'] = bins
        elif kind == 'wmse':
            w = Y['mp3'][m]
            e.update({'rmse': round(float(np.sqrt(np.average((pf - y) ** 2, weights=w))), 3), 'rmse_hist': round(float(np.sqrt(np.average((ph - y) ** 2, weights=w))), 3),
                      'bias': round(float(np.average(y - pf, weights=w)), 3)})
        else:
            e.update({'rmse': round(float(np.sqrt(np.mean((pf - y) ** 2))), 3), 'rmse_hist': round(float(np.sqrt(np.mean((ph - y) ** 2))), 3),
                      'corr': round(float(np.corrcoef(pf, y)[0, 1]), 3), 'corr_hist': round(float(np.corrcoef(ph, y)[0, 1]), 3)})
        tests.append(e); print(e)
    # Holm over the four
    order = sorted(range(len(tests)), key=lambda i: tests[i]['p'])
    for j, i in enumerate(order): tests[i]['holm'] = bool(tests[i]['p'] < .05 / (len(tests) - j) and tests[i]['t'] < 0 and all(tests[k]['holm'] for k in order[:j]))
    fit = fit_all([(r[0], r[1], r[2]) for r in rows], FEATS)
    fit.update({'feats': FEATS, 'extra': ['age2'], 'tests': tests, 'rows': len(rows), 'seasons': [yrs[0], yrs[-1]],
                'updated': datetime.date.today().isoformat()})
    json.dump(fit, open(FIT, 'w'), indent=1)
    print('wrote', FIT)


def build():
    fit = json.load(open(FIT)); y = current_season()
    fetch(y, fresh=True)
    cur = gl_season(y)
    if not cur:      # before the Showcase Cup tips: last season's players
        y -= 1; fetch(y); cur = gl_season(y)
    W = World()
    reg = max([o['reg'] for o in cur.values()] or [0])
    part = max(0.0, 1 - min(reg, REG_GAMES) / REG_GAMES)
    F, keep = [], []
    for p, o in cur.items():
        if not o['n'] or (o['MIN'] or 0) < MIN_ROW: continue
        W.link(p, o['n'], [y - o['age']] if o['age'] else [])
        f, t, info = W.row(y, o, part); F.append(f); keep.append((o, f, info))
    p1, p5, xv, xx = predict(fit, F, fit['feats'])
    players = []
    for i, (o, f, info) in enumerate(keep):
        b = info['b']; nb = W.NB.get(y, {}).get(b, {}) if b else {}
        now = nb.get('mp') or 0
        ph = nb.get('ph') or next((W.NB[z][b].get('ph') for z in sorted(W.NB, reverse=True) if b and b in W.NB[z] and W.NB[z][b].get('ph')), None)
        par, logo = TEAMS.get(o['tm'], (None, None))
        players.append({'id': o['id'], 'n': o['n'], 'tm': o['tm'], 'nba': par, 'lg': logo, 'age': int(o['age']) if o['age'] else None,
                        'gp': o['GP'], 'min': round(o['MIN']), 'pts': round(f['pts36'], 1), 'gs': round(f['gs36'], 1),
                        'ts': round(100 * o['TS_PCT'], 1) if o['MIN'] else None,
                        'cmp': round(info['cmp'] + now), 'ph': ph, 'pk': info['pk'], 'dy': info['dy'], 'bb': b,
                        'p1': round(float(p1[i]), 3), 'p5': round(float(p5[i]), 3), 'xv': round(float(xv[i]) / 3, 2),
                        'xx': round(float(xx[i]), 1)})
    try:
        stt = status(y, players)
    except Exception as e:
        print('status skipped:', e); stt = (json.load(open(STATUS)) if os.path.exists(STATUS) else {}).get(str(y), {'dob': {}, 'tw': [], 'nba': []})
    tw, nb = set(stt['tw']), set(stt['nba'])
    NBADOB = json.load(open(os.path.join(HERE, 'data', 'nba_dob.json'))) if os.path.exists(os.path.join(HERE, 'data', 'nba_dob.json')) else {}
    for r in players:
        dob = stt['dob'].get(str(r['id'])) or (NBADOB.get(r['bb']) if r.get('bb') else None)
        if dob: r['ax'] = round((datetime.date(y, 2, 1) - datetime.date.fromisoformat(dob)).days / 365.25, 1)    # Feb 1, like the XPM board
        if r['id'] in tw: r['ct'] = 'TW'
        elif r['id'] in nb: r['ct'] = 'NBA'
    print('ages', sum('ax' in r for r in players), 'two-way', sum(r.get('ct') == 'TW' for r in players), 'NBA', sum(r.get('ct') == 'NBA' for r in players))
    players.sort(key=lambda r: (-r['p1'], -r['xv']))
    out = {'season': y, 'label': sname(y), 'next': sname(y + 1), 'part': round(part, 2), 'reg': reg,
           'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'tests': {t['target']: {k: t.get(k) for k in ('auc', 'brier', 'rate', 'rmse', 'corr', 't', 'holm')} for t in fit['tests']},
           'players': players}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    s = json.dumps(out, separators=(',', ':'), allow_nan=False)
    open(OUT, 'w').write(s); print('wrote', OUT, len(players), 'players, part', part)


def past():
    """each past season's board as it read the day that G League season ended: the same features, fit walk forward on
    the seasons whose outcome was known by then (NBA% and REG%: seasons through s-1; xVORX: through s-3, shown once four
    seasons are in). Training starts with 2008-09 (the XPM boards begin 2009-10, so 2007-08 has no next-season label).
    Each row carries what happened next: NBA minutes the next season (per 82) and NBA VORX per season over the next three."""
    W = World(); last = current_season() - 1
    seasons = {y: (gl_season(y), [gl_season(y, ('SC',))] if y >= 2022 else []) for y in range(2009, last + 1)}
    births = collections.defaultdict(list); nm = {}
    for y, (full, scs) in seasons.items():
        for p, o in full.items():
            if o['n']: nm[p] = o['n']
            if o['age']: births[p].append(y - o['age'])
    for p, n in nm.items(): W.link(p, n, births[p])
    rows = []
    for y, (full, scs) in seasons.items():
        for part, src in [(0.0, full)] + [(1.0, s) for s in scs]:
            for p, o in src.items():
                o['n'] = o['n'] or nm.get(p)
                if (o['MIN'] or 0) < MIN_ROW or not o['n']: continue
                f, t, info = W.row(y, o, part)
                rows.append((y, f, t, part, info, o))
    have = max(W.NB)            # the latest NBA season on the XPM board (may be running)
    out, score = [], collections.defaultdict(list)
    for s in range(2011, last + 1):
        tr1 = [r for r in rows if r[0] <= s - 1]; tr3 = [r for r in rows if r[0] <= s - 3]
        te = [r for r in rows if r[0] == s and r[3] == 0.0]
        X, mu, sd = design([r[1] for r in tr1], FEATS)
        b1 = logit_fit(X, np.array([r[2]['nba1'] for r in tr1])); b5 = logit_fit(X, np.array([r[2]['stick'] for r in tr1]))
        Xt, _, _ = design([r[1] for r in te], FEATS, mu, sd)
        p1 = sig(lin(b1, Xt)); p5 = np.minimum(sig(lin(b5, Xt)), p1); xv = [None] * len(te); xx = [None] * len(te)
        if len({r[0] for r in tr3}) >= 4:
            X3, m3, s3 = design([r[1] for r in tr3], FEATS); a = np.array([r[2]['any3'] for r in tr3])
            ba = logit_fit(X3, a); bp = ridge_fit(X3[a == 1], np.array([r[2]['xv3'] for r in tr3])[a == 1], POS_LAM)
            Xt3, _, _ = design([r[1] for r in te], FEATS, m3, s3)
            xv = (sig(lin(ba, Xt3)) * lin(bp, Xt3)).tolist()
            mp3 = np.array([r[2]['mp3'] for r in tr3]); pl = mp3 > 0
            xx = lin(ridge_fit(X3[pl], np.array([r[2]['xpm3'] for r in tr3])[pl], XX_LAM, mp3[pl]), Xt3).tolist()
        players = []
        for i, (y, f, t, part, info, o) in enumerate(te):
            b = info['b']; nb = W.NB.get(s, {}).get(b, {}) if b else {}
            ph = next((W.NB[z][b].get('ph') for z in sorted(W.NB, reverse=True) if b and b in W.NB[z] and W.NB[z][b].get('ph')), None)
            par, logo = TEAMS.get(o['tm'], (None, None))
            done1, done3 = s + 1 < have, s + 3 < have
            mp1 = round((W.NB.get(s + 1, {}).get(b, {}).get('mp') or 0) * 82 / W.GAMES.get(s + 1, 82)) if b else 0
            # no NBA parent: TEAMS is today's affiliations, and several clubs changed parents (or names) since
            players.append({'id': o['id'], 'n': o['n'], 'tm': o['tm'], 'lg': logo, 'age': int(o['age']) if o['age'] else None,
                            'gp': o['GP'], 'min': round(o['MIN']), 'gs': round(f['gs36'], 1), 'ts': round(100 * o['TS_PCT'], 1) if o['MIN'] else None,
                            'cmp': round(info['cmp'] + (nb.get('mp') or 0)), 'ph': ph, 'pk': info['pk'], 'dy': info['dy'],
                            'p1': round(float(p1[i]), 3), 'p5': round(float(p5[i]), 3), 'xv': None if xv[i] is None else round(float(xv[i]) / 3, 2),
                            'xx': None if xx[i] is None else round(float(xx[i]), 1),
                            'o1': mp1 if done1 else None, 'o3': round(t['xv3'] / 3, 2) if done3 else None,
                            'ox': round(t['xpm3'], 1) if done3 and t['mp3'] > 0 else None})
            if done1:
                score['p1'].append(float(p1[i])); score['y1'].append(t['nba1'])
        players.sort(key=lambda r: (-r['p1'], -(r['xv'] or 0)))
        out.append({'season': s, 'label': sname(s), 'next': sname(s + 1), 'train': [2009, s - 1], 'players': players})
        print(s, len(players), 'trained on', len(tr1), 'rows', '3y' if xv[0] is not None else '')
    p, y = np.array(score['p1']), np.array(score['y1'])
    base = np.full(len(y), y.mean())
    res = {'n': len(y), 'auc': round(auc(p, y), 3), 'll': round(ll(p, y), 4), 'brier': round(float(np.mean((p - y) ** 2)), 4), 'rate': round(float(y.mean()), 3)}
    print('walk forward NBA%', res)
    s = json.dumps({'asof': datetime.date.today().isoformat(), 'test': res, 'seasons': out[::-1]}, separators=(',', ':'), allow_nan=False)
    open(PAST, 'w').write(s); print('wrote', PAST, round(len(s) / 1e6, 2), 'MB')


if __name__ == '__main__':
    if '--research' in sys.argv: research()
    elif '--past' in sys.argv: past()
    else: build()
