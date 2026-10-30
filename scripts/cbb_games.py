#!/usr/bin/env python3
"""College basketball game projections for the College Basketball ARKBOARD (data/cbb_games.json), the model behind them
(data/cbb_games_fit.json) and its picks (data/cbb_picks.json, scripts/cbb_picks.py).

    python3 scripts/cbb_games.py --fit     # walk-forward backtest 2016-2026 against the closing line, tune, select inputs
    python3 scripts/cbb_games.py           # today's and tomorrow's games, power ratings, season odds (run by cbb-board)

The same design as the football models (scripts/cfb_model.mjs, scripts/nfl_games.py): a rating core, market ratings
from earlier closing lines, availability, a player-based preseason prior, candidate inputs kept only on out-of-sample
evidence, win probability calibrated to results, everything judged against the closing line on held-out seasons.

Margin (home minus away, points) is a linear model, fit on the seasons before the one it scores, on:
    eff     opponent-adjusted efficiency: each team's offense and defense in points per 100 possessions, solved each day
            from this season's games (a ridge regression on both teams' points a possession, home court and the league
            average, recent games weighted up) and pulled toward the preseason prior; times the game's expected
            possessions (tempo solved the same way)
    elo     Elo difference (K, margin multiplier, part carried over each summer: tuned)
    mkt     market rating: each team's points against an average team as EARLIER games' closing spreads priced it
            (never the game's own line), part carried over each summer
    home    1 at a true home game, 0 neutral
    + candidates kept only when they cut 2016-20 error at t <= -1.5 (CANDS; data/cbb_games_fit.json 'select')
Preseason prior (the efficiency solve's starting point): last season's final rating and the roster, by player from
Barttorvik's lines: returning minutes, returners' projected BPM x projected minutes share (scripts/cbb_roster.py),
incoming transfers' BPM x minutes, freshmen by recruiting rank (On3, 247), newcomers with no D-I line (juco,
international), top-5 board FV, age, the head coach's tenure; weights fit on the seasons before
(scripts/data/cbb_team_prior.json; live rosters from scripts/cbb_prior.json.gz, written with cbb_roster.py --prior).
A school with no roster rows (non-D-I) starts at the mean final of those before it.
Total: the efficiency total (both offenses against both defenses, times possessions from the opponent-adjusted tempo
solve) and the market total rating, the market weighted up over each team's first 10 games ('early').
Win probability: normal around the margin with sd fit to results on the training seasons.
Data: ESPN (schedule, scores, every book's lines, scripts/cbb_games_hist.py), Barttorvik (possessions; per-game
player minutes for availability; player seasons for the prior).
"""
import gzip
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')        # one thread: the daily 780-team solves run 4x faster than with BLAS threads
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'cbb', 'games')
HIST = os.path.join(HERE, 'data', 'cbb_games_hist.json.gz')
TPRIOR = os.path.join(HERE, 'data', 'cbb_team_prior.json')
STATE = os.path.join(HERE, 'data', 'cbb_games_state.json')
FIT = os.path.join(ROOT, 'data', 'cbb_games_fit.json')
OUT = os.path.join(ROOT, 'data', 'cbb_games.json')
BTLOG = os.path.join(HERE, '.cache', 'cbb', 'games_bt')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
FIRST, SCORE0, TUNE_END, LAST = 2014, 2016, 2020, 2026
# Oct 21 2026, shared harness re-score (scripts/harness_rescore.py, data/model_ledger.json; cluster-robust paired t by
# game day x home team-season, one FDR family over every model): mkt (the market rating) and alt (altitude) were noise
# with the rest in (mkt: 2016-20 t +1.2, 2021-26 +.2 without it; alt: -1.9 tune but +1.5 held out), and so were the
# prior's fr, lastret and newmin. All five out together: 2016-20 MAE 9.3865 -> 9.3770 (t -2.1), 2021-26 9.7308 ->
# 9.7221 (t -3.4) on every D-I game; the rest re-scored in the reduced model and stayed
BASE = ['eff', 'elo', 'home']
CANDS = ['inj', 'rest', 'confh', 'early', 'tourn', 'form', 'mkteff', 'bpi', 'gc', 'gm', 'hatt']
# hatt (Oct 29 2026, edge sweep, scripts/cbb_edge_research.py): home court x the home team's trailing home crowd, log of
# (attendance / 1000 + 1) over this season's earlier home games with last season's mean worth ATT_K games, minus ATT_MID
# (ESPN scoreboard attendance; a 2021 empty arena counts as 0). Setting home to 0 in 2021's empty arenas fails
ATT_K, ATT_MID, EMPTY = 3.0, 1.43, {2021}
# bpi (team model idea 9, scripts/public_ratings_cbb.py, Oct 23 2026): ESPN BPI's own forecast margin for the game
# (scripts/public_ratings.py --cbb-bpi), written the morning of the game (median 15 hours before the tip), used only
# when written before the tip; otherwise the efficiency margin plus BPI_HOME at home stands in. On the shipped model:
# 2016-20 MAE -0.041 (t -4.1), 2021-26 -0.006 (t -0.4), lined games 2021-26 -0.038 (t -5.3). Barttorvik T-Rank from
# its time machine adds nothing (r .95 with eff; 2016-20 t +3.0)
BPI = {}
BPI_HOME = 3.0
# gc (team model idea 8, scripts/control_ratings.py): the home-minus-away game-control rating before the game (the
# time-weighted mean of each game's win probability from score and clock, opponent-adjusted by ridge, last season's
# rating carried whole), filled by load_all from scripts/data/cbb_control_hist.json.gz and live by cbb_games_live;
# gm: the same long-memory rating on final margins (scripts/control_ratings.py CBB_FIT). Oct 23 2026, each on top of the
# shipped inputs (eff, elo, home, confh, bpi, inj), paired abs error clustered by day x home team-season
# (data/control_research_cbb.json):
#   gc  2016-20 t -3.4 (MAE -.033), 2021-26 t -2.0 (-.023), lined games 2021-26 t -2.6   <- kept (tuning rule)
#   gm  2016-20 t -3.1 (-.043),     2021-26 t -1.5 (-.022), lined 2021-26 t -2.5; both together add nothing
# so most of the gain is the multi-season memory; control edges the margin twin on tuning. Forward selection from
# scratch puts the rating in first and then drops bpi, which is worse on lined games
GC = {'gc': {}, 'gm': {}}


def bpi_x(g, x):
    v = BPI.get(str(g.get('id', '')))
    if v and v[1] is not None and v[0] and v[0][:16] <= g['date'][:16]:
        return float(v[1])
    return x['eff'] + BPI_HOME * x['home']
TFEATS = ['efft', 'tmkt', 'one', 'early']
# totals (Oct 19 2026, scripts/cbb_games_research.py totals2): the tempo knobs tuned on 2016-20 total error (tempo
# prior weight tlam 4 -> 2 games, tempo carried over 0.6 -> 1.0, market total step 0.2 -> 0.5) and 'early' (the
# efficiency total's gap to the market total, fading over each team's first 10 games) kept at t -2.3: totals MAE
# 13.798 -> 13.756 on 2016-20 (t -5.4), 13.551 -> 13.508 held out (t -6.1); the margin gains too (t -4.2 / -5.6).
# Not kept: the total split into its possessions and efficiency parts (-1.3), home (-1.2), conference game, postseason
# thl (Oct 29 2026, pace research): the total's possessions from its own copy of the tempo solve, decayed with a 20-day
# half-life (the margin's tempo keeps the season-long weights, hl). Recent tempo is worth more to the total than early-
# season games: totals MAE 2016-20 13.741 -> 13.712 (t -2.2), 2021-26 13.475 -> 13.432 (t -2.8); on top of the closing
# total (stack of close + model gap) t -4.1 / -1.1. 45 days: -4.0 / -3.8, close -2.9 / -1.2 (20 has the lower tuning MAE)
TKNOBS = {'tlam': [1.0, 2.0, 3.0, 4.0], 'tcarry': [0.6, 0.8, 0.9, 1.0], 'tk': [0.2, 0.3, 0.4, 0.5, 0.7]}
# fvtop and agew: the board's FV model on the roster, kept Oct 19 2026 (fv_test: top-5 E[FV] t -3.6 on 2016-20, -4.0
# on 2021-26; minutes-weighted age on top of it t -5.0 / -8.8). Not kept: minutes-weighted E[FV] (+3.9 on top),
# freshmen E[FV] (+0.4, held out +4.5), minutes-weighted 3-season BPM (+1.7)
# rret, newmin, tenure (scripts/cbb_roster.py, Oct 21 2026; forward selection on 2016-20, t -2.2 / -5.1 / -3.6): the
# returners' projected BPM x projected minutes share in place of ret, the minutes share projected for non-freshman
# newcomers (juco, international, sit-outs), the head coach's seasons at the school
# Oct 23 2026 (scripts/cbb_returners_research.py): rret also counts players back from a lost season (injury, a sit-out
# year), projected off their last healthy line: 2016-20 t -3.7, 2021-26 t -0.9 (lined -2.6)
# fvfrm (scripts/fv_mean_games.py cbb, Oct 21 2026): freshmen's E[FV] at the mean of its outcome odds (the board's
# headline since PR #335), above 20, summed; t -3.4 on 2016-20, 2021-26 -.0009 (not worse). At the grade it passes
# tuning too (-3.5) but is worse held out (+.0003). fvtop stays on the grade (at the mean: +3.3 on 2016-20)
# Oct 30 2026 audit: history's fvtop/agew/fvfrm rebuilt (fvfrm had been cached under an older fv_dist map, +.55 a
# team live over history) with the board's age date, guard and power flags; live unranked freshmen count at FR_PLAY.
# History error unchanged (2021-26 MAE +.0001, t .5; lined t -.2); the live prior sits .28 lower, flat (sd .10)
PRIOR_F = ['one', 'last', 'retmin', 'tr', 'trmin', 'fvtop', 'agew', 'tenure', 'rret', 'fvfrm', 'nohist', 'ptrdn', 'cres']   # fr, lastret, newmin out Oct 21 2026
# nohist (Oct 26 2026, scripts/cbb_ark_research.py): 1 for a season with no final ratings the season before (2014, where
# the history starts). Every 2014 team's 'last' was the -8 stand-in, so those rows bent the 'last' coefficient (and the
# terms that stand in for it) in every later prior fit; the indicator gives them their own intercept. Never 1 live.
# Found by a placebo while testing T-Rank's preseason rating: 2016-20 margin MAE t -1.8, 2021-26 -0.0015 (t -8.4), lined
# 2021-26 t -6.3
# ptrdn (Oct 26 2026, scripts/cbb_ark_research.py): transfers' minutes share x their step down in level (new team's box
# margin minus the old one's, when negative) / 10, from the 2020-21 transfer waiver on (0 before 2021). Players who drop
# a level beat the roster projection (coef ~-4.7: a team whose transfers fill half the minutes, each from a team 10 pts
# better, gains ~2.4). Judged inside the portal era: 2021-23 margin MAE t -3.2, held out 2024-26 t -4.1 (lined -3.0);
# the same term over all seasons fails 2016-20 (few transfers then). Step-up transfers (ptrup) add nothing
# cres (Oct 30 2026, scripts/cbb_oct30_research.py, built by scripts/cbb_coach_prior.py): the head coach's misses
# against this preseason prior (final net - prior net) in his earlier seasons, any school, summed over (seasons + 2).
# Coaches who beat the roster projection keep doing it (coef ~.6). 2016-20 margin MAE t -1.85, 2021-26 -.0046 (t -3.9),
# lined -.0026 (t -2.4), 2021-23 t -2.8 and 2024-26 t -2.7. Failed the same day: the coach's misses at the current
# school only (cres_s, lined held out flat), the program's last three misses (pres), last season's late-season residual
# carried by the returning minutes (ltrend), projected-minutes-weighted roster height (hgt), and blowout damping in
# the efficiency solve (bcap: raw or from the expected margin, 15-30 pts per 100; helps 2016-20, worse 2021-26)
X = 'X'                                   # every non-D-I opponent, one rating
NOFEAT = True                             # roster-less teams take the mean final of earlier ones (Oct 21 2026)
# home courts a mile up or close (feet): Air Force, Colorado, Colorado St., Denver, Wyoming, Utah, Utah St., BYU,
# Utah Valley, Utah Tech, Southern Utah, Weber St., New Mexico, Northern Arizona, Montana St., Idaho St., Nevada, UNLV?
# (UNLV 2,000 ft, left out), Northern Colorado, Grand Canyon (1,100, left out)
ALT = {'2005', '38', '36', '2172', '2751', '254', '328', '252', '3084', '3101', '253', '2692', '167', '2464', '147', '304', '2440', '2458'}


def et_date(iso):
    return (datetime.fromisoformat(iso.replace('Z', '+00:00')) - timedelta(hours=5)).strftime('%Y-%m-%d')


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ---------------------------------------------------------------- data
def load_hist():
    return json.load(gzip.open(HIST))


def bt_map(games, prior_rows=None):
    """ESPN team id -> Barttorvik name (the possessions join carries both)"""
    m = defaultdict(lambda: defaultdict(int))
    for g in games:
        if 'hb' in g:
            m[g['home']][g['hb']] += 1; m[g['away']][g['ab']] += 1
    out = {t: max(c, key=c.get) for t, c in m.items()}
    return out


def d1_set(games):
    """D-I teams: the ones Barttorvik rates (non-D-I games have no Barttorvik row)"""
    c = defaultdict(int)
    for g in games:
        if 'hb' in g:
            c[g['home']] += 1; c[g['away']] += 1
    return {t for t, n in c.items() if n >= 3}


def bt_logs(season):
    """Barttorvik per-game player rows: team -> [(date, {pid: (min, gbpm)})] in date order"""
    p = os.path.join(BTLOG, f'{season}.json.gz')
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        os.makedirs(BTLOG, exist_ok=True)
        subprocess.run(['curl', '-s', '-m', '300', '-A', UA, f'https://barttorvik.com/{season}_all_advgames.json.gz', '-o', p], check=False)
    try:
        rows = json.load(gzip.open(p))
    except Exception:
        return {}
    by = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        try:
            d = str(r[0]); d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            if (r[8] or 0) > 0:
                by[r[47]][d][r[51]] = (float(r[8]), float(r[44] or 0))
        except (IndexError, TypeError, ValueError):
            continue
    return {t: sorted(v.items()) for t, v in by.items()}


def bt_shoot(season):
    """Barttorvik per-game player rows summed by team: (team, date) -> [3PM, 3PA, FTM, FTA, points]"""
    bt_logs(season)
    try:
        rows = json.load(gzip.open(os.path.join(BTLOG, f'{season}.json.gz')))
    except Exception:
        return {}
    out = defaultdict(lambda: [0.0] * 5)
    for r in rows:
        try:
            d = str(r[0]); d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
            v = out[(r[47], d)]
            for i, c in enumerate((25, 26, 27, 28, 33)):
                v[i] += float(r[c] or 0)
        except (IndexError, TypeError, ValueError):
            continue
    return dict(out)


# a rotation player who sat his team's last game sits the next one at these rates, by games missed in a row (1, 2, 3,
# 4+; Barttorvik logs 2016-20, weighted by the term's player value; all games 2016-26: .644); SIT_AGAIN is the
# all-streak rate the 'inj' weight was fit on. Weighting each player by his streak's rate (avail streak=True) fails:
# 2016-20 t +0.2, 2021-26 +0.65 (scripts/cbb_inj_research.py, Oct 21 2026), so the live term counts every one at 1
SIT_STREAK = {1: 0.518, 2: 0.678, 3: 0.765, 4: 0.863}
SIT_AGAIN = 0.644
# the absent player's value is over his own team's bench, shrunk to the flat -3 by this many bench minutes (Oct 21 2026,
# scripts/cbb_inj_research.py: 400 min t -1.77 on 2016-20, -1.86 on 2021-26; 150 min -1.28 / -1.20)
BENCH = 400.0


def avail(logs, repl=-3.0, n0=150.0, streak=False, listed=None, bench=BENCH, prior=None, pk=0.0):
    """value of the rotation players who sat out the team's last game, per 100 possessions against a replacement:
    (BPM to date, shrunk to -1 by n0 minutes, minus repl) x his minutes a team game / 40. Rotation: 12+ minutes when he
    plays and in 60% of the team's games, 3+ games in. Keyed (team, date of the game it applies to); 'next' = after the last.
    streak: each player who sat at his chance to sit again by his run of missed games (SIT_STREAK) over SIT_AGAIN, the
    rate the term's weight was fit on. listed: team -> {pid: chance he sits} from the injury report, for the 'next'
    game: a listed player counts at that chance over SIT_AGAIN, whether or not he played the last game. bench: the
    replacement level is the team's own bench (its non-rotation players' minutes-weighted BPM to date, shrunk to repl
    by `bench` minutes) in place of the flat repl: the value lost is the absent player's over who takes his minutes.
    prior / pk (in-season values, team idea 4): a player with a line last season (prior: pid -> his BPM then, shrunk)
    is shrunk to that with pk minutes in place of the flat -1 with n0 (scripts/cbb_inseason_research.py)"""
    out = {}
    for t, gl in logs.items():
        st = {}            # pid -> [games, minutes, gbpm x minutes]
        run = defaultdict(int)
        L = (listed or {}).get(t, {})
        for k in range(len(gl) + 1):
            v = 0.0
            if k >= 3:
                last = gl[k - 1][1]
                rp = repl
                if bench:
                    bs = [(mn, bm) for g, mn, bm in st.values() if g < 0.6 * k or mn / g < 12]
                    rp = (sum(b for _, b in bs) + repl * bench) / (sum(m for m, _ in bs) + bench)
                for pid, (g, mn, bm) in st.items():
                    if g < 0.6 * k or mn / g < 12:
                        continue
                    if k == len(gl) and pid in L:
                        f = L[pid] / SIT_AGAIN
                    elif pid in last:
                        continue
                    else:
                        f = SIT_STREAK[min(run[pid], 4)] / SIT_AGAIN if streak else 1.0
                    if prior and pk and pid in prior:
                        bpm = (bm + prior[pid] * pk) / (mn + pk)
                    else:
                        bpm = (bm + -1.0 * n0) / (mn + n0)
                    v += f * max(0.0, bpm - rp) * (mn / k) / 40
            out[(t, gl[k][0] if k < len(gl) else 'next')] = round(v, 3)
            if k < len(gl):
                for pid, (mn, gb) in gl[k][1].items():
                    s = st.setdefault(pid, [0, 0.0, 0.0])
                    s[0] += 1; s[1] += mn; s[2] += gb * mn
                for pid in st:
                    run[pid] = 0 if pid in gl[k][1] else run[pid] + 1
    return out


def last_bpm(season, n0=150.0):
    """pid -> his minutes-weighted game BPM over the season before, shrunk to -1 by n0 minutes (any team: a transfer
    keeps his Barttorvik id)"""
    tot = defaultdict(lambda: [0.0, 0.0])
    for t, gl in bt_logs(season - 1).items():
        for _, d in gl:
            for pid, (mn, gb) in d.items():
                tot[pid][0] += mn; tot[pid][1] += gb * mn
    return {pid: (b - n0) / (m + n0) for pid, (m, b) in tot.items() if m > 0}


def team_prior_hist():
    """scripts/data/cbb_team_prior.json from the board's Barttorvik research seasons (one row per player season):
    season -> Barttorvik team -> roster features (see PRIOR_F)"""
    import csv
    src = '/mnt/project-files/cbb/backtest/research_seasons.csv'
    by = defaultdict(dict)                     # year -> pid -> row
    for r in csv.DictReader(open(src)):
        by[int(r['year'])][r['pid']] = r
    out = {}
    for y in range(FIRST, LAST + 1):
        T = defaultdict(lambda: {'ret': 0.0, 'retmin': 0.0, 'tr': 0.0, 'trmin': 0.0, 'fr': 0.0})
        for pid, r in by[y].items():
            f = T[r['team']]
            p = by[y - 1].get(pid)
            if p and p['min_per']:
                share = float(p['min_per']) / 100
                v = share * float(p['bpm'] or 0)
                if p['team'] == r['team']:
                    f['ret'] += v; f['retmin'] += share / 5
                else:
                    f['tr'] += v; f['trmin'] += share / 5
            elif r['yr'] == 'Fr':
                f['fr'] += recruit_pts(r.get('on3rk'), r.get('rk247'))
        out[y] = {t: {k: round(v, 3) for k, v in f.items()} for t, f in T.items()}
        for t, f in team_fv(y, by).items():
            out[y].setdefault(t, {}).update(f)
    out = {str(y): v for y, v in out.items()}
    import cbb_roster
    cbb_roster.add_terms(out)
    return out


FV_CANDS = ['fvw', 'fvfr', 'fvtop', 'bpm3w', 'agew']


def player_fv(feats, grp):
    """E[FV] from the board's model (data/cbb_fit.json): the same continuation ladder fetch_cbb.py scores"""
    global _FVFIT
    try:
        _FVFIT
    except NameError:
        _FVFIT = json.load(open(os.path.join(ROOT, 'data', 'cbb_fit.json')))['models']
    m = _FVFIT[grp]
    z = []
    for k, mu, sd in zip(m['kept'], m['mean'], m['sd']):
        v = feats.get(k)
        z.append(0.0 if v is None or sd == 0 else max(-4.0, min(4.0, (v - mu) / sd)))
    z = np.array(z)
    ps, c = [], 1.0
    for w in m['w']:
        c *= 1 / (1 + math.exp(-max(-30, min(30, w[0] + np.dot(w[1:], z)))))
        ps.append(c)
    return 20 + 10 * (ps[0] + ps[1] + ps[2]) + (m['topMean'] - 50) * ps[3]


def research_feats(p, team):
    """a player's preseason FV inputs for the season after research row p (Barttorvik line, cbb/backtest columns)"""
    n = lambda k: float(p[k]) if p.get(k) not in (None, '', 'nan') else None
    age = n('age')
    # as the board's model (cbb_fit.features) reads them: age on Nov 1 entering the season (the research age is on Feb 1
    # of the season before, so + .75), guard = point and combo guards only (the research flag also counts wings), and
    # the old Pac-12 a power conference through its last season (Oct 30 2026: history had age +1 and the research
    # flags, so its E[FV] sat below the live board's: top-5 mean -.24 FV)
    return {'on3': n('on3'), 'bpm': n('bpm'), 'bpm3': n('bpm3'), 'dbpm': n('dbpm'), 'trend': n('bpm_trend'), 'min_per': n('min_per'),
            'ast': n('ast'), 'stl': n('stl'), 'blk': n('blk'), 'ftr': n('ftr'), 'rim': n('rim'), 'dporpag': n('dporpag'),
            'power': power(p['conf'], int(p['year'])), 'age': age + 0.75 if age else None,
            'guard': 1.0 if p.get('role') in GUARDS else 0.0, 'transfer': 1.0 if p['team'] != team else 0.0}


GUARDS = {'Pure PG', 'Scoring PG', 'Combo G'}


def power(conf, year):
    """cbb_fit's power flag: the six power conferences, the old Pac-12 through 2024 (P12_LAST)"""
    return 1.0 if conf in {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'} and (conf != 'P12' or year <= 2024) else 0.0


def height_pos(hti):
    """a freshman's position from his listed height (known before the season), for the at-mean restatement"""
    h = float(hti) if hti not in (None, '', 'nan') else None
    return 'G' if h is not None and h <= 76 else 'C' if h is not None and h >= 82 else 'F'


def team_fv(y, by):
    """team FV terms for season y: minutes-weighted E[FV] above 20 of returners and transfers (last season's minutes
    share), freshmen's E[FV] above 20 summed, the mean of the top 5 E[FV], minutes-weighted 3-season BPM and age"""
    T = defaultdict(lambda: {'fvw': 0.0, 'fvfr': 0.0, 'fvfrm': 0.0, 'bpm3w': 0.0, 'agen': 0.0, 'aged': 0.0, 'es': []})
    for pid, r in by[y].items():
        f = T[r['team']]
        p = by[y - 1].get(pid)
        if p and p['min_per']:
            share = float(p['min_per']) / 100
            x = research_feats(p, r['team'])
            e = player_fv(x, 'returner')
            f['fvw'] += (e - 20) * share; f['es'].append(e)
            f['bpm3w'] += (x['bpm3'] or 0) * share
            if x['age']:
                f['agen'] += x['age'] * share; f['aged'] += share
        elif r['yr'] == 'Fr':
            lr = [-math.log(min(float(v), 500)) for v in (r.get('on3rk'), r.get('rk247')) if v not in (None, '', 'nan') and float(v) > 0]
            l = sum(lr) / len(lr) if lr else -math.log(600)
            e = player_fv({'rg_lrk': l, 'top': max(0.0, l + math.log(25)), 'top5': max(0.0, l + math.log(5)), 'yr': 1.0}, 'newcomer')
            f['fvfr'] += e - 20; f['es'].append(e)
            # position from height, not the season's own Barttorvik role (that is drawn from the minutes he went on to play)
            f['fvfrm'] += fr_mean(e, height_pos(r.get('hti'))) - 20
    out = {}
    for t, f in T.items():
        es = sorted(f['es'], reverse=True)[:5]
        out[t] = {'fvw': round(f['fvw'], 3), 'fvfr': round(f['fvfr'], 3), 'fvfrm': round(f['fvfrm'], 3), 'fvtop': round(sum(es) / len(es) - 20, 3) if es else 0.0,
                  'bpm3w': round(f['bpm3w'], 3), 'agew': round(f['agen'] / f['aged'] - 21, 3) if f['aged'] else 0.0}
    return out


def fr_mean(e, pos):
    """a freshman's E[FV] restated at the mean of its outcome odds, as the board restates its headline (fv_dist)"""
    from fv_dist import at_mean, cbb_z
    return at_mean('cbb', e, cbb_z('Fr', False, pos, e))


def recruit_pts(*ranks):
    rk = [float(x) for x in ranks if x not in (None, '', 'nan') and float(x) > 0]
    return max(0.0, math.log(300 / min(rk))) if rk else 0.0


def team_prior_live(season, espn_bt=None):
    """the same features for the coming season from the board's frozen prior (scripts/cbb_prior.json.gz: each 2026-27
    player's ESPN team, Barttorvik team and past lines). Returns ({Barttorvik team: features}, {ESPN id: Barttorvik team},
    {ESPN id: board conference})"""
    import re
    d = json.load(gzip.open(os.path.join(HERE, 'cbb_prior.json.gz')))
    K = {k: i for i, k in enumerate(d['keep'])}
    ci = {k: i for i, k in enumerate(d['cols'])}
    T = defaultdict(lambda: {'ret': 0.0, 'retmin': 0.0, 'tr': 0.0, 'trmin': 0.0, 'fr': 0.0})
    bt, conf = {}, {}
    for row, c in zip(d['rows'], d['careers']):
        m = re.search(r'/(\d+)\.png', row[ci['logo']] or '')
        if not m:
            continue
        conf[m[1]] = row[ci['conf']]
        team = c.get('bt') or (espn_bt or {}).get(m[1])      # the board leaves a few schools unmatched; the games join knows them
        if not team:
            continue
        bt[m[1]] = team
        f = T[team]
        prev = [s for s in c['seasons'] if s[K['year']] == season - 1]
        if prev and prev[0][K['min_per']]:
            s = prev[0]; share = s[K['min_per']] / 100; v = share * (s[K['bpm']] or 0)
            if s[K['team']] == team:
                f['ret'] += v; f['retmin'] += share / 5
            else:
                f['tr'] += v; f['trmin'] += share / 5
        elif row[ci['cls']] == 'Fr' and c.get('rec'):
            f['fr'] += recruit_pts(c['rec'].get('on3rk'), c['rec'].get('rk247'))
    out = {t: {k: round(v, 3) for k, v in f.items()} for t, f in T.items()}
    for t, f in team_fv_live(d, bt, season).items():
        out.setdefault(t, {}).update(f)
    # the roster and coach terms for the season, written offline by scripts/cbb_roster.py --prior (they need the
    # research seasons) and the coach's record against the projection (scripts/cbb_coach_prior.py): rosters are frozen
    # once the season starts
    for t, f in (json.load(open(TPRIOR)).get(str(season)) or {}).items():
        if t in out:
            out[t].update({k: v for k, v in f.items() if k in ('rret', 'newmin', 'tenure', 'trdn', 'cres')})
    return out, bt, conf


# unranked freshmen with minutes in the research seasons 2022-26 (735 a season) over unranked freshmen on the 2026-27
# preseason rosters (1,023); ranked freshmen match (about 350 a season against 370 rostered)
FR_PLAY = 0.72


def team_fv_live(d, bt, season):
    """fvtop, agew and fvfrm (team_fv) for the coming season from the frozen prior's careers, the same inputs team_fv reads
    from the research seasons"""
    import re
    K = {k: i for i, k in enumerate(d['keep'])}
    ci = {k: i for i, k in enumerate(d['cols'])}
    T = defaultdict(lambda: {'agen': 0.0, 'aged': 0.0, 'es': [], 'fvfrm': 0.0})
    for row, c in zip(d['rows'], d['careers']):
        m = re.search(r'/(\d+)\.png', row[ci['logo']] or '')
        team = c.get('bt') or (bt.get(m[1]) if m else None)
        if not team:
            continue
        f = T[team]
        prev = [dict(zip(d['keep'], s)) for s in c['seasons'] if s[K['year']] < season]
        if prev and prev[-1]['min_per']:
            p = prev[-1]
            num = den = 0.0
            for w, r in zip((5, 4, 3), reversed(prev[-3:])):
                mm = (r['mp'] or 0) * (r['gp'] or 0)
                if r['bpm'] is not None:
                    num += w * mm * r['bpm']; den += w * mm
            bpm3 = ((num / den) * den / 5 + -4.0 * 300) / (den / 5 + 300) if den else -4.0
            age = None
            if c.get('dob'):
                try:
                    b = datetime.strptime(c['dob'], '%Y-%m-%d')
                    age = (datetime(season - 1, 11, 1) - b).days / 365.25
                except ValueError:
                    pass
            x = {'on3': (c.get('rec') or {}).get('on3'), 'bpm': p['bpm'], 'bpm3': bpm3, 'dbpm': p['dbpm'],
                 'trend': p['bpm'] - prev[-2]['bpm'] if len(prev) >= 2 and p['bpm'] is not None and prev[-2]['bpm'] is not None else 0.0,
                 'min_per': p['min_per'], 'ast': p['ast'], 'stl': p['stl'], 'blk': p['blk'], 'ftr': p['ftr'], 'rim': p['rim'],
                 'dporpag': p['dporpag'], 'power': power(p['conf'], p['year']), 'age': age,
                 'guard': 1.0 if p['role'] in GUARDS else 0.0, 'transfer': 1.0 if p['team'] != team else 0.0}
            f['es'].append(player_fv(x, 'returner'))
            if age:
                share = p['min_per'] / 100
                f['agen'] += age * share; f['aged'] += share
        elif row[ci['cls']] == 'Fr':
            g = c.get('rec') or {}
            lr = [-math.log(min(float(v), 500)) for v in (g.get('on3rk'), g.get('rk247')) if v]
            l = sum(lr) / len(lr) if lr else -math.log(600)
            e = player_fv({'rg_lrk': l, 'top': max(0.0, l + math.log(25)), 'top5': max(0.0, l + math.log(5)), 'yr': 1.0}, 'newcomer')
            f['es'].append(e)
            # history counts only the freshmen who logged minutes; the live roster lists every one, walk-ons included.
            # An unranked freshman counts at the share of them who play (FR_PLAY), ranked ones in full
            f['fvfrm'] += (fr_mean(e, row[ci['pos']]) - 20) * (1.0 if lr else FR_PLAY)
    out = {}
    for t, f in T.items():
        es = sorted(f['es'], reverse=True)[:5]
        out[t] = {'fvtop': round(sum(es) / len(es) - 20, 3) if es else 0.0, 'agew': round(f['agen'] / f['aged'] - 21, 3) if f['aged'] else 0.0,
                  'fvfrm': round(f['fvfrm'], 3)}
    return out


# ---------------------------------------------------------------- ratings
class Ratings:
    """one season's ratings, walked a date at a time"""

    def __init__(self, teams, prior, P, conf=None):
        self.P = P
        self.teams = list(teams) + [X]
        self.ix = {t: i for i, t in enumerate(self.teams)}
        n = self.n = len(self.teams)
        self.pO = np.array([prior.get(t, {}).get('O', -10.0 if t == X else -2.0) for t in self.teams])
        self.pD = np.array([prior.get(t, {}).get('D', -10.0 if t == X else -2.0) for t in self.teams])
        self.pT = np.array([prior.get(t, {}).get('T', 0.0) for t in self.teams])
        # asymmetric tempo (P['aplmix']): each side's seconds a possession, its offense's part plus the opposing
        # defense's, with prior weights aplo / apld games around last season's final
        self.pAo = np.array([prior.get(t, {}).get('ao', 0.0) for t in self.teams])
        self.pAd = np.array([prior.get(t, {}).get('ad', 0.0) for t in self.teams])
        # each team's prior weight as a multiple of lam ('lm'; 1 = the same for every team): research only so far
        # (scripts/cbb_kalman_research.py, a prior's precision by how uncertain the roster makes it)
        self.lm = np.array([prior.get(t, {}).get('lm', 1.0) for t in self.teams])
        # hierarchical prior (team model idea 5): with P['cv'] > 0 each team's offense and defense are its conference's
        # effect plus its own deviation, the conference effect with cv times a team's prior variance, so a result moves
        # every conference-mate's rating a little (precision lam x (I - cv / (1 + cv n_k) J) inside conference k)
        self.PM = None
        cv = P.get('cv', 0.0)
        if cv and conf:
            M = np.eye(n)
            by = defaultdict(list)
            for t, c in conf.items():
                if t in self.ix and t != X:
                    by[c].append(self.ix[t])
            for c, ix in by.items():
                if len(ix) >= 4:
                    M[np.ix_(ix, ix)] -= cv / (1 + cv * len(ix))
            r = np.sqrt(self.lm)
            self.PM = M * np.outer(r, r)
        m = 2 * n + 2
        # the data side of both normal equations, decayed a day at a time (recent games weighted up) and grown by each
        # date's games; solve() adds the prior
        self.A, self.b, self.TA, self.Tb = np.zeros((m, m)), np.zeros(m), np.zeros((n + 1, n + 1)), np.zeros(n + 1)
        # the total's own copy of the tempo solve, on its own half-life (P['thl'], days; none: the same as the margin's)
        self.TA2, self.Tb2 = np.zeros((n + 1, n + 1)), np.zeros(n + 1)
        # the results' change from each side's free throws over expected off its score (ldft), and the asymmetric tempo
        self.dB = np.zeros(m)
        self.dO, self.dD, self.dmu = np.zeros(n), np.zeros(n), 0.0
        self.AA, self.Ab = np.zeros((2 * n + 1, 2 * n + 1)), np.zeros(2 * n + 1)
        self.ao, self.ad, self.ac = self.pAo.copy(), self.pAd.copy(), 1200.0 / P['tau0']
        self.day = None
        self.nobs = 0
        self.O, self.D, self.T = self.pO.copy(), self.pD.copy(), self.pT.copy()
        self.T2 = self.T
        self.tau2 = P['tau0']
        self.mu, self.h, self.tau = P['mu0'], P['h0'], P['tau0']
        self.ng = defaultdict(int)

    def i(self, t):
        return self.ix.get(t, self.ix[X])

    def decay(self, day):
        if self.day is not None and self.P['hl'] and day > self.day:
            f = 0.5 ** ((day - self.day) / self.P['hl'])
            self.A *= f; self.b *= f; self.TA *= f; self.Tb *= f; self.dB *= f
        if self.day is not None and self.P.get('thl') and day > self.day:
            f = 0.5 ** ((day - self.day) / self.P['thl'])
            self.TA2 *= f; self.Tb2 *= f; self.AA *= f; self.Ab *= f
        self.day = day

    def add(self, g, day, gap=(0.0, 0.0), luck=(0.0, 0.0), ft=(0.0, 0.0)):
        """gap: (home, away) points per 100 the result is corrected by, for who sat that night (lineup-adjusted
        ratings: half of each side's absences on its offense, half on its defense); luck: (home, away) points of
        shooting luck taken off each side's score (luck-stripped efficiency, P['lw3']); ft: (home, away) free throws
        made over the shooter's FT% to date (the defense ratings' share, P['ldft'])"""
        self.decay(day)
        n = self.n
        h, a = self.i(g['home']), self.i(g['away'])
        poss = g.get('poss') or (g['hs'] + g['as']) / 2.06
        loc = 0.0 if g['neutral'] else 1.0
        # blowout damping (research, P['bcap'] points per 100, off by default): the efficiency margin beyond bcap counts
        # at bslope; P['brel'] measures it from the margin the ratings expected before the game instead of from 0
        damp = 0.0
        if cap := self.P.get('bcap'):
            m = 100 * ((g['hs'] - luck[0]) - (g['as'] - luck[1])) / poss + gap[0] - gap[1]
            e = ((self.O[h] - self.D[a]) - (self.O[a] - self.D[h]) + 2 * self.h * loc) if self.P.get('brel') else 0.0
            r = m - e
            if abs(r) > cap:
                damp = (math.copysign(cap + (abs(r) - cap) * self.P.get('bslope', 0.5), r) - r) / 2
        for off, dfn, pts, l, j in ((h, a, g['hs'] - luck[0], loc, (gap[0] - gap[1]) / 2 + damp),
                                    (a, h, g['as'] - luck[1], -loc, (gap[1] - gap[0]) / 2 - damp)):
            y = 100 * pts / poss + j
            idx = (off, n + dfn, 2 * n, 2 * n + 1)
            val = (1.0, -1.0, 1.0, l)
            for p in range(4):
                for q in range(4):
                    self.A[idx[p], idx[q]] += val[p] * val[q]
                self.b[idx[p]] += val[p] * y
        for off, dfn, f, l in ((h, a, ft[0], loc), (a, h, ft[1], -loc)):
            if f:
                for p, v in zip((off, n + dfn, 2 * n, 2 * n + 1), (1.0, -1.0, 1.0, l)):
                    self.dB[p] -= v * 100 * f / poss
        if self.P.get('aplmix') and g.get('poss'):
            # seconds a possession: each side's from its share of the possession time (play-by-play), else both together
            sec = (2400 + 300 * (g.get('ot') or 0)) / g['poss']
            pt = g.get('pt')
            f = pt[0] / (pt[0] + pt[1]) if pt and pt[0] and pt[1] else None
            if f is not None and 0.3 < f < 0.7:
                rows = [((h, n + a, 2 * n), (1.0, 1.0, 1.0), sec * f), ((a, n + h, 2 * n), (1.0, 1.0, 1.0), sec * (1 - f))]
            else:
                rows = [((h, n + a, a, n + h, 2 * n), (1.0, 1.0, 1.0, 1.0, 2.0), sec)]
            for idx, val, yv in rows:
                for p, vp in zip(idx, val):
                    for q, vq in zip(idx, val):
                        self.AA[p, q] += vp * vq
                    self.Ab[p] += vp * yv
        if g.get('poss'):
            for p in (h, a, n):
                for q in (h, a, n):
                    self.TA[p, q] += 1; self.TA2[p, q] += 1
                self.Tb[p] += poss; self.Tb2[p] += poss
        self.nobs += 1
        self.ng[g['home']] += 1; self.ng[g['away']] += 1

    def solve(self, day):
        P, n = self.P, self.n
        lam = P['lam']
        if not self.nobs:
            return
        self.decay(day)
        m = 2 * n + 2
        pri = np.concatenate([self.pO, self.pD, [P['mu0'], P['h0']]])
        prec = np.concatenate([lam * self.lm, lam * self.lm, [0.01, 0.5]])
        prec[self.ix[X]] = prec[n + self.ix[X]] = 0.5
        if self.PM is not None:
            Pm = np.diag(prec)
            Pm[:n, :n] = Pm[n:2 * n, n:2 * n] = lam * self.PM
            Pm[self.ix[X], self.ix[X]] = Pm[n + self.ix[X], n + self.ix[X]] = 0.5
            M, rhs = self.A + Pm, self.b + Pm @ pri
        else:
            M, rhs = self.A + np.diag(prec), self.b + prec * pri
        s = np.linalg.solve(M, np.column_stack([rhs, self.dB]))
        self.O, self.D, self.mu, self.h = s[:n, 0], s[n:2 * n, 0], s[2 * n, 0], s[2 * n + 1, 0]
        # opponent free-throw luck (ldft): the defense ratings from the solve with each side's free throws at the
        # shooter's FT% to date at weight ldft, the offense ratings from the raw one (dO, dmu: research)
        self.dO, self.dD, self.dmu = s[:n, 1], s[n:2 * n, 1], s[2 * n, 1]
        self.D = self.D + P.get('ldft', 0.0) * self.dD
        prec = np.concatenate([np.full(n, P.get('tlam', lam)), [0.01]])
        pt = prec * np.concatenate([self.pT, [P['tau0']]])
        s = np.linalg.solve(self.TA + np.diag(prec), self.Tb + pt)
        self.T, self.tau = s[:n], s[n]
        self.T2, self.tau2 = self.T, self.tau
        if P.get('thl'):
            s = np.linalg.solve(self.TA2 + np.diag(prec), self.Tb2 + pt)
            self.T2, self.tau2 = s[:n], s[n]
        if P.get('aplmix'):
            prec = np.concatenate([np.full(n, P['aplo']), np.full(n, P['apld']), [0.01]])
            s = np.linalg.solve(self.AA + np.diag(prec), self.Ab + prec * np.concatenate([self.pAo, self.pAd, [1200.0 / P['tau0']]]))
            self.ao, self.ad, self.ac = s[:n], s[n:2 * n], s[2 * n]

    def net(self, t):
        k = self.i(t)
        return self.O[k] + self.D[k]

    def poss(self, h, a):
        return self.tau + self.T[self.i(h)] + self.T[self.i(a)]

    def tposs(self, h, a):
        """possessions for the total: the thl copy of the tempo solve, mixed (aplmix) with 40 minutes over both sides'
        expected seconds a possession (x APLK, its gap to the raw count with overtimes, 2015-26)"""
        p, w = self.tau2 + self.T2[self.i(h)] + self.T2[self.i(a)], self.P.get('aplmix', 0.0)
        if not w:
            return p
        H, A = self.i(h), self.i(a)
        L = 2 * self.ac + self.ao[H] + self.ad[A] + self.ao[A] + self.ad[H]
        return (1 - w) * p + w * APLK * 2400 / L

    def game(self, h, a):
        H, A = self.i(h), self.i(a)
        P = self.poss(h, a)
        eh, ea = self.mu + self.O[H] - self.D[A], self.mu + self.O[A] - self.D[H]
        return (eh - ea) * P / 100, (eh + ea) * self.tposs(h, a) / 100, P


class Walk:
    """every season in order: ratings, Elo, market ratings; feats() before a date's games, then they're added"""

    def __init__(self, P, tprior, btname, coefs=None):
        self.P, self.tprior, self.btname = P, tprior, btname
        self.elo = defaultdict(lambda: 1500.0)
        self.mkt, self.tm = defaultdict(float), defaultdict(float)
        self.tm0 = {}                   # last season's final market total gaps ('tpri')
        self.tlg = 140.0
        self.final = {}                 # season -> team -> {O, D, T, net}
        self.pcoef = coefs or {}        # season -> prior coefficients
        self.prior_rows = []            # (season, team, features, target) for the prior regression
        self.nofeat = []                # (season, final net) of teams with no roster rows
        self.conf = {}                  # season -> team -> conference (conferences())
        # luck-stripped efficiency (team model idea 6): each side's made threes over expected (its 3P% to date, shrunk
        # to the league's with lk3 attempts) and free throws over its FT% to date (lkft), times 1 - lw3 / 1 - lwft,
        # come off its score before the result enters the efficiency solve. 1 = raw points
        self.shot = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        self.lgs = [0.34, 1.0, 0.71, 1.0]
        self.bshoot = {}                # season -> Barttorvik (team, date) -> [3PM, 3PA, FTM, FTA, points]
        self.ftl = (0.0, 0.0)           # the last game's free throws over expected, (home, away) (ldft)
        self.att = defaultdict(list)    # team -> this season's home crowds, log(attendance / 1000 + 1) ('hatt')
        self.attm = {}                  # season -> team -> its mean

    def prior_feats(self, s, t, last):
        bt = self.btname.get(t)
        f = (self.tprior.get(str(s)) or self.tprior.get(s) or {}).get(bt) or {}
        L = last.get(t)
        ln = L['net'] if L else -8.0
        out = {'one': 1.0, 'last': ln, 'lastret': ln * f.get('retmin', 0.0), 'nohist': 0.0 if (s - 1) in self.final else 1.0,
               'ptrdn': f.get('trdn', 0.0) if int(s) >= 2021 else 0.0}
        if 'clast' in PRIOR_F:
            out['clast'] = self.conf_last(s, t, last)
        for k in PRIOR_F:
            if k not in out:
                out[k] = f.get(k, 0.0)
        return out

    def conf_last(self, s, t, last):
        """the mean final rating last season of the team's conference-mates this season (the team left out), minus last
        season's D-I mean; 0 for a team with no conference"""
        cf = self.conf.get(s) or {}
        c = cf.get(t)
        if c is None:
            return 0.0
        v = [last[u]['net'] for u, k in cf.items() if k == c and u != t and u in last]
        allv = [r['net'] for u, r in last.items() if u in cf]
        return float(np.mean(v) - np.mean(allv)) if len(v) >= 3 and allv else 0.0

    def prior_coef(self, s):
        if s in self.pcoef:
            return self.pcoef[s]
        R = [r for r in self.prior_rows if r[0] < s]
        if len({r[0] for r in R}) < 1:
            c = {k: 0.0 for k in PRIOR_F}; c['last'] = 0.6; c['one'] = -1.0
        else:
            Xp = np.array([[r[2][k] for k in PRIOR_F] for r in R]); y = np.array([r[3] for r in R])
            A = Xp.T @ Xp + np.diag([0.0] + [5.0] * (len(PRIOR_F) - 1))
            c = dict(zip(PRIOR_F, np.linalg.solve(A, Xp.T @ y)))
        self.pcoef[s] = c
        return c

    def season_prior(self, s, teams):
        last = self.final.get(s - 1, {})
        c = self.prior_coef(s)
        out, feats = {}, {}
        keep = self.P['split']
        tp = self.tprior.get(str(s)) or self.tprior.get(s) or {}
        # a team with no roster rows (a non-D-I school with a few D-I games) takes the mean final of those before it:
        # the roster terms at zero read as an average D-I roster
        nf = [n for (ss, n) in self.nofeat if ss < s]
        nfm = sum(nf) / len(nf) if nf and NOFEAT else None
        for t in teams:
            f = self.prior_feats(s, t, last); feats[t] = f
            pn = sum(c[k] * f[k] for k in PRIOR_F)
            if tp and self.btname.get(t) not in tp:
                feats.pop(t)
                if nfm is not None:
                    pn = nfm
            L = last.get(t)
            if L:
                d = pn - keep * (L['O'] + L['D'])
                out[t] = {'O': keep * L['O'] + d / 2, 'D': keep * L['D'] + d / 2, 'T': L['T'] * self.P['tcarry'], 'net': pn,
                          'ao': L.get('ao', 0.0), 'ad': L.get('ad', 0.0)}
            else:
                out[t] = {'O': pn / 2, 'D': pn / 2, 'T': 0.0, 'net': pn}
        return out, feats

    def new_season(self, s):
        P = self.P
        for t in list(self.elo):
            self.elo[t] = 1500 + (self.elo[t] - 1500) * P['ecarry']
        for t in list(self.mkt):
            self.mkt[t] *= P['mrev']
        self.tm0 = dict(self.tm)
        for v in self.shot.values():
            v[:] = [x * 0.5 for x in v]
        if self.att:
            self.attm[s - 1] = {t: sum(v) / len(v) for t, v in self.att.items() if v}
        self.att = defaultdict(list)
        for t in list(self.tm):
            self.tm[t] *= P.get('tcar', 0.0)

    def market(self, g):
        L = -g['spread'] if g.get('spread') is not None else None
        h, a = g['home'], g['away']
        if L is not None:
            e = L - (self.mkt[h] - self.mkt[a] + (0 if g['neutral'] else 3.0))
            self.mkt[h] += self.P['mk'] * e; self.mkt[a] -= self.P['mk'] * e
        if g.get('total'):
            e = g['total'] - (self.tlg + self.tm[h] + self.tm[a])
            self.tm[h] += self.P['tk'] * e; self.tm[a] += self.P['tk'] * e; self.tlg += 0.005 * e

    def luck(self, g, d):
        """(home, away) points of shooting luck to take off each score, and the shooting lines to add after"""
        P = self.P
        w3, wf = 1 - P.get('lw3', 1.0), 1 - P.get('lwft', 1.0)
        self.ftl = (0.0, 0.0)
        if not (w3 or wf or P.get('ldft')):
            return (0.0, 0.0), None
        s = g['season']
        if s not in self.bshoot:
            self.bshoot[s] = bt_shoot(s)
        bs = self.bshoot[s]
        ln = [bs.get((self.btname.get(t), d)) for t in (g['home'], g['away'])]
        if not all(ln):
            return (0.0, 0.0), None
        k3, kf = P.get('lk3', 600.0), P.get('lkft', 300.0)
        out, ft = [], []
        for t, v in zip((g['home'], g['away']), ln):
            st = self.shot[t]
            x3 = (st[0] + k3 * self.lgs[0] / self.lgs[1]) / (st[1] + k3)
            xf = (st[2] + kf * self.lgs[2] / self.lgs[3]) / (st[3] + kf)
            out.append(w3 * 3 * (v[0] - v[1] * x3) + wf * (v[2] - v[3] * xf))
            ft.append(v[2] - v[3] * xf)
        self.ftl = tuple(ft)
        return tuple(out), ln

    def hatt(self, g):
        """home x the home side's trailing crowd (log scale) minus ATT_MID; 0 at a neutral site"""
        if g['neutral']:
            return 0.0
        v = self.att.get(g['home']) or []
        pm = self.attm.get(g['season'] - 1, {}).get(g['home'])
        den = len(v) + (ATT_K if pm is not None else 0)
        return (sum(v) + (ATT_K * pm if pm is not None else 0.0)) / den - ATT_MID if den else 0.0

    def add_att(self, g):
        a = g.get('att')
        if not g['neutral'] and a is not None and (a > 0 or g['season'] in EMPTY):
            self.att[g['home']].append(math.log1p(a / 1000))

    def add_shot(self, g, ln):
        a = 0.5 ** (1 / self.P.get('lshl', 30.0))
        for t, v in zip((g['home'], g['away']), ln):
            st = self.shot[t]
            st[:] = [st[0] * a + v[0], st[1] * a + v[1], st[2] * a + v[2], st[3] * a + v[3]]
            if v[1] and v[3]:
                self.lgs[0] = self.lgs[0] * 0.999 + v[0] / v[1]; self.lgs[1] = self.lgs[1] * 0.999 + 1
                self.lgs[2] = self.lgs[2] * 0.999 + v[2] / v[3]; self.lgs[3] = self.lgs[3] * 0.999 + 1

    def elo_update(self, g, shift=0.0):
        """shift: the home side's expected margin moved by who sat that night (points; 25 Elo a point)"""
        h, a = g['home'], g['away']
        hfa = 0 if g['neutral'] else self.P['ehfa']
        d = self.elo[h] - self.elo[a] + hfa + 25 * shift
        exp = 1 / (1 + 10 ** (-d / 400))
        m = g['hs'] - g['as']
        res = 1.0 if m > 0 else 0.0
        mult = math.log(abs(m) + 1) * 2.2 / ((d if m > 0 else -d) * 0.001 + 2.2)
        k = self.P['K'] * mult * (res - exp)
        self.elo[h] += k; self.elo[a] -= k


def conferences(games, d1):
    """team -> conference for one season: the groups that the season's conference games join (ESPN flags each one), 4
    teams or more; independents and the rest are left out"""
    par = {t: t for t in d1}

    def f(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for g in games:
        if g.get('conf') and g['home'] in par and g['away'] in par:
            par[f(g['home'])] = f(g['away'])
    n = defaultdict(int)
    for t in d1:
        n[f(t)] += 1
    return {t: f(t) for t in d1 if n[f(t)] >= 4}


def realized(av):
    """(team, date) -> value of the rotation players who sat THAT game (avail's key for a game holds who sat the one
    before it, so each game takes the next game's value; the season's last takes 'next')"""
    by = defaultdict(list)
    for (t, d), v in av.items():
        if d != 'next':
            by[t].append(d)
    out = {}
    for t, ds in by.items():
        ds.sort()
        for i, d in enumerate(ds):
            out[(t, d)] = av.get((t, ds[i + 1]) if i + 1 < len(ds) else (t, 'next'), 0.0)
    return out


def season_walk(W, s, games, d1, av, collect, live_prior=None, upto=None):
    """walk one season's games (sorted by date). collect(g, x, tx, R) is called for every game before its date is
    added. Returns the Ratings at the end."""
    P = W.P
    W.new_season(s)
    teams = sorted(d1)
    W.conf[s] = conferences(games, d1)
    if live_prior is not None:
        pri, pfeats = live_prior
    else:
        pri, pfeats = W.season_prior(s, teams)
    R = Ratings(teams, pri, P, W.conf.get(s))
    btn = W.btname
    av = av or {}
    by_day = defaultdict(list)
    for g in games:
        by_day[et_date(g['date'])].append(g)
    day0 = datetime(s - 1, 11, 1)
    lastday = {}                      # team -> ordinal of its last game
    resid = defaultdict(list)         # team -> recent (margin - eff expectation), own side
    lk, lke = P.get('lk', 0.0), P.get('lke', 0.0)  # lineup-adjusted ratings: share of who sat taken off results
    rz = realized(av) if (lk or lke) else {}
    for d in sorted(by_day):
        if upto and d > upto:
            break
        day = (datetime.strptime(d, '%Y-%m-%d') - day0).days
        R.solve(day)
        for g in by_day[d]:
            h, a = g['home'], g['away']
            m, tot, poss = R.game(h, a)
            home = 0.0 if g['neutral'] else 1.0
            ph, pa = pri.get(h, {}).get('net', -8.0), pri.get(a, {}).get('net', -8.0)
            ng = min(R.ng[h], R.ng[a])
            rest = lambda t: max(1, min(7, day - lastday[t])) if t in lastday else 7
            ih = av.get((btn.get(h), d), av.get((btn.get(h), 'next'), 0.0) if g.get('hs') is None else 0.0)
            ia = av.get((btn.get(a), d), av.get((btn.get(a), 'next'), 0.0) if g.get('hs') is None else 0.0)
            fr = lambda t: sum(resid[t][-5:]) / max(1, len(resid[t][-5:]))
            post = 1.0 if (g.get('stype') == 3 or 'tournament' in (g.get('note') or '').lower() or 'championship' in (g.get('note') or '').lower()) else 0.0
            x = {'eff': m, 'elo': (W.elo[h] - W.elo[a]) / 25, 'mkt': W.mkt[h] - W.mkt[a], 'home': home,
                 'inj': (ia - ih) * poss / 100, 'rest': rest(h) - rest(a), 'confh': home * (1.0 if g.get('conf') else 0.0),
                 'alt': home * (1.0 if h in ALT else 0.0), 'early': (ph - pa) * poss / 100 * max(0.0, 1 - ng / 10),
                 'tourn': post * m, 'form': fr(h) - fr(a), 'mkteff': (W.mkt[h] - W.mkt[a]) * max(0.0, 1 - ng / 10)}
            x['bpi'] = bpi_x(g, x)
            x['gc'] = GC['gc'].get(str(g.get('id', '')), 0.0)
            x['gm'] = GC['gm'].get(str(g.get('id', '')), 0.0)
            x['hatt'] = W.hatt(g)
            tm = W.tlg + W.tm[h] + W.tm[a]
            tph = P.get('tphl', 80.0)
            tx = {'efft': tot, 'tmkt': tm, 'one': 1.0, 'early': (tot - tm) * max(0.0, 1 - ng / 10),
                  # last season's closing totals, team by team, fading as each team plays
                  'tpri': sum(W.tm0.get(t, 0.0) * tph / (tph + R.ng[t]) for t in (h, a))}
            collect(g, x, tx, R)
        for g in by_day[d]:
            W.market(g)
            if g.get('hs') is None:
                continue
            m, _, _ = R.game(g['home'], g['away'])
            hc = (R.h * 2) * R.poss(g['home'], g['away']) / 100 if not g['neutral'] else 0.0
            r = (g['hs'] - g['as']) - (m + hc)
            resid[g['home']].append(r); resid[g['away']].append(-r)
            vh, va = rz.get((btn.get(g['home']), d), 0.0), rz.get((btn.get(g['away']), d), 0.0)
            pp = R.poss(g['home'], g['away']) / 100
            W.elo_update(g, lke * (va - vh) * pp)
            lu, ln = W.luck(g, d)
            R.add(g, day, (lk * vh, lk * va), lu, W.ftl)
            W.add_att(g)
            if ln:
                W.add_shot(g, ln)
            lastday[g['home']] = lastday[g['away']] = day
    if not upto:
        R.solve((datetime(s, 4, 10) - day0).days)
        W.final[s] = {t: {'O': float(R.O[R.ix[t]]), 'D': float(R.D[R.ix[t]]), 'T': float(R.T[R.ix[t]]),
                          'net': float(R.O[R.ix[t]] + R.D[R.ix[t]]), 'ao': float(R.ao[R.ix[t]]), 'ad': float(R.ad[R.ix[t]])} for t in teams}
        for t in teams:
            if t in pfeats and R.ng[t] >= 15:
                W.prior_rows.append((s, t, pfeats[t], W.final[s][t]['net']))
            elif t not in pfeats and R.ng[t] >= 3:
                W.nofeat.append((s, W.final[s][t]['net']))
    return R, pri, pfeats


# tcar: share of each team's market total rating (its gap to the league's closing totals) carried into the next season,
# where it used to start at 0 (scripts/cbb_market_prior.py, Oct 21 2026): totals 2016-20 MAE -0.0135 (t -3.4), 2021-26
# -0.0149 (t -3.9) at .75; .5 -0.012 / -0.014, 1.0 -0.012 / -0.011. Last season's totals as their own fading input
# (tpri) fail 2016-20 (t +1 to +1.8) though they help 2021-26
# cv (team model idea 5, scripts/conf_hier_research.py, Oct 23 2026): hierarchical conference ratings, each team's
# offense and defense its conference's effect plus its own deviation, the conference effect with cv x a team's prior
# variance (Ratings). On the shipped model, every D-I game: 2016-20 MAE -0.0053 (t -3.2), 2021-26 -0.0106 (t -3.1),
# non-conference games 2021-26 -0.024 (t -3.0); lined games -0.0049 / -0.0005. Larger cv gains more on all games (cv 1:
# 2021-26 -0.062) but loses on lined ones (+0.017), so .1. Last season's conference-mates as a prior term (clast) fails
# held out (t +2.9)
# lw3 (team model idea 6, scripts/luck_research.py cbb, Oct 23 2026): luck-stripped efficiency, half of each side's
# threes made over expected (its 3P% to date, shrunk to the league's with 600 attempts) off its score before the result
# enters the efficiency solve (shooting from Barttorvik's game lines). Picked on 2016-20 from .75/.5/.25/0: margin MAE
# -0.039 (t -5.2), 2021-26 -0.071 (t -9.7); totals -0.012 (t -1.9), 2021-26 -0.019 (t -3.9). All threes at expected
# (0) is worse on 2016-20 (t +0.8); free throws at the team's FT% (lwft .5) -0.004 (t -1.6) on margin, hurts totals
# ldft, aplmix, hatt (Oct 29 2026, edge sweep, scripts/cbb_edge_research.py, data/cbb_edge_research.json; on top of
# thl). Judged against the close: result minus closing line on the change in the walk-forward prediction, clustered by
# day, 2016-20 and 2021-26 apart, then the held-out squared error of the close moved by the 2016-20 fit (BH over 31 tests)
#   ldft .5   the defense ratings take half of each opponent's free throws over the shooter's FT% to date off (a defense
#             has no say over them; a shooter's FT% persists, so the offense keeps raw points): margin vs close t 2.6 /
#             5.1, SE t -3.4, MAE -.0029 (t -2.7) / -.0030 (t -3.2); totals t 2.1 / 3.9, SE t -2.8. Both sides (lwft)
#             gain less on the margin and hurt totals; ldft 1 passes too, smaller on totals
#   aplmix .5 (aplo 1, apld 4)  the total's possessions half from an asymmetric tempo in seconds a possession
#             (offense + opposing defense, possession time from play-by-play): totals vs close t 3.5 / 4.8, SE t -2.5,
#             MAE -.058 (t -7.2) / -.038 (t -4.3); alone (no mix) t 2.6 / 3.8. The symmetric version in seconds
#             (aplo = apld 2) fails the close; on the margin it hurts, so the margin keeps the tempo solve
#   hatt      margin vs close t 3.7 / 3.1, SE t -2.4, MAE -.0125 (t -2.9) / -.0044 (t -2.3)
# all three: margin vs close t 4.4 / 5.2 (SE t -4.1), MAE -.016 / -.008; totals t 3.9 / 5.7 (SE t -3.1), MAE -.058 /
# -.041. A new head coach's own tempo as the tempo prior fails (4 variants: movers' old-school tempo at full or half
# weight, other new coaches' carried tempo halved; none beats the close)
APLK = 1.0107
DEFAULT = {'ldft': 0.5, 'aplmix': 0.5, 'aplo': 1.0, 'apld': 4.0, 'thl': 20.0, 'lw3': 0.5, 'cv': 0.1, 'hl': 45.0, 'lam': 4.0, 'mu0': 103.0, 'h0': 1.4, 'tau0': 68.0, 'split': 0.5, 'tcarry': 1.0, 'ecarry': 0.6,
           'mrev': 0.0, 'mk': 0.15, 'tk': 0.5, 'K': 25.0, 'ehfa': 80.0, 'tlam': 2.0, 'tcar': 0.75}


def run_walk(P, games, tprior, btname, d1s, av_by_season, seasons=None):
    """the full history walk: rows of (game, x, tx) for every game with a result"""
    W = Walk(P, tprior, btname)
    by_s = defaultdict(list)
    for g in games:
        by_s[g['season']].append(g)
    out = []
    for s in sorted(by_s):
        if seasons and s not in seasons:
            continue
        gs = sorted(by_s[s], key=lambda g: (g['date'], g['id']))
        season_walk(W, s, gs, d1s[s], av_by_season.get(s), lambda g, x, tx, R: out.append((g, x, tx)) if g.get('hs') is not None else None)
    return W, out


# ---------------------------------------------------------------- fit
def load_all():
    import public_ratings
    BPI.update(public_ratings.bpi_load())
    games = load_hist()
    import control_ratings
    for k, v in control_ratings.cbb_feat_hist(games).items():
        GC[k].update(v)
    btname = bt_map(games)
    by = defaultdict(list)
    for g in games:
        by[g['season']].append(g)
    d1s = {s: d1_set(v) for s, v in by.items()}
    if not os.path.exists(TPRIOR):
        tp = team_prior_hist()
        with open(TPRIOR, 'w') as f:
            json.dump(tp, f, separators=(',', ':'))
    tprior = json.load(open(TPRIOR))
    avc = os.path.join(CACHE, f'avail_b{int(BENCH)}.json.gz')
    if os.path.exists(avc):
        avs = {int(s): {tuple(k.split('|')): v for k, v in d.items()} for s, d in json.load(gzip.open(avc)).items()}
    else:
        avs = {}
        for s in sorted(by):
            avs[s] = avail(bt_logs(s))
            print('avail', s, len(avs[s]), flush=True)
        os.makedirs(CACHE, exist_ok=True)
        with gzip.open(avc, 'wt') as f:
            json.dump({s: {'|'.join(k): v for k, v in d.items()} for s, d in avs.items()}, f)
    return games, btname, d1s, tprior, avs


def matrices(rows, feats, tfeats=TFEATS):
    D = [(g, x, tx) for g, x, tx in rows if g['season'] >= FIRST + 1]
    Xm = np.array([[x[f] for f in feats] for _, x, _ in D]); y = np.array([g['hs'] - g['as'] for g, _, _ in D], float)
    TX = np.array([[tx[f] for f in tfeats] for _, _, tx in D]); ty = np.array([g['hs'] + g['as'] for g, _, _ in D], float)
    S = np.array([g['season'] for g, _, _ in D])
    line = np.array([-g['spread'] if g.get('spread') is not None else np.nan for g, _, _ in D])
    tline = np.array([g['total'] if g.get('total') else np.nan for g, _, _ in D])
    d1 = np.array([g['home'] != X and g['away'] != X and 'hb' in g for g, _, _ in D])
    return D, Xm, y, TX, ty, S, line, tline, d1


def walk_pred(Xm, y, S, d1, first=SCORE0, ridge=0.0):
    """each season from the seasons before it (D-I games only in training)"""
    pred = np.full(len(y), np.nan)
    for s in range(first, LAST + 1):
        tr, te = (S < s) & d1, S == s
        if not te.any():
            continue
        A = Xm[tr].T @ Xm[tr] + ridge * np.eye(Xm.shape[1])
        pred[te] = Xm[te] @ np.linalg.solve(A, Xm[tr].T @ y[tr])
    return pred


def paired_t(a, b):
    d = a - b
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 else 0.0


def ml_prob(mlh, mla):
    """no-vig home win chance from both moneylines"""
    imp = lambda o: 100 / (o + 100) if o > 0 else -o / (-o + 100)
    a, b = imp(mlh), imp(mla)
    return a / (a + b)


def fit():
    t0 = time.time()
    games, btname, d1s, tprior, avs = load_all()
    print('loaded', len(games), f'{time.time() - t0:.0f}s', flush=True)

    def score(P, feats):
        W, rows = run_walk(P, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = matrices(rows, feats)
        pred = walk_pred(Xm, y, S, d1)
        k = (S >= SCORE0) & (S <= TUNE_END) & d1 & ~np.isnan(pred)
        return float(np.mean(np.abs(pred[k] - y[k]))), W, rows

    # 1. rating memory, tuned on 2016-20 margin error with the base inputs, one knob at a time from the defaults
    #    (coordinate search, two passes); 2021-26 is never looked at here
    P = dict(DEFAULT)
    if '--keep-params' in sys.argv and os.path.exists(FIT):
        # reuse the last tuning (the grid is the slow part); everything after it reruns
        P = json.load(open(FIT))['params']
        P.setdefault('cv', DEFAULT['cv'])
        P.setdefault('lw3', DEFAULT['lw3'])
        for k in ('thl', 'ldft', 'aplmix', 'aplo', 'apld'):
            P.setdefault(k, DEFAULT[k])
        log = json.load(open(FIT))['grid']
        W, rows = run_walk(P, games, tprior, btname, d1s, avs)
        return after_tune(P, W, rows, log)
    grid = {'hl': [0.0, 30.0, 45.0, 70.0], 'lam': [2.0, 4.0, 8.0], 'K': [15.0, 25.0, 40.0], 'ecarry': [0.4, 0.6, 0.8],
            'mk': [0.08, 0.15, 0.25], 'mrev': [0.0, 0.3], 'split': [0.3, 0.5, 0.7]}
    log = []
    best, _, _ = score(P, BASE)
    log.append([round(best, 4), dict(P)]); print('base', round(best, 4), flush=True)
    for rnd in range(2):
        changed = False
        for k, vals in grid.items():
            for v in vals:
                if v == P[k]:
                    continue
                Q = dict(P, **{k: v})
                e, _, _ = score(Q, BASE)
                log.append([round(e, 4), {k: v}]); print(rnd, k, v, round(e, 4), flush=True)
                if e < best - 1e-4:
                    best, P, changed = e, Q, True
        if not changed:
            break
    print('tuned', P, round(best, 4), f'{time.time() - t0:.0f}s', flush=True)
    # 1b. the tempo and market-total knobs (TKNOBS), the same search on 2016-20 total error with the total inputs
    def tscore(Q):
        W, rows = run_walk(Q, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = matrices(rows, BASE)
        tp = walk_pred(TX, ty, S, d1)
        k = (S >= SCORE0) & (S <= TUNE_END) & d1 & ~np.isnan(tp) & ~np.isnan(tline)
        return float(np.mean(np.abs(tp[k] - ty[k])))
    tbest = tscore(P)
    for rnd in range(2):
        changed = False
        for k, vals in TKNOBS.items():
            for v in vals:
                if v == P[k]:
                    continue
                Q = dict(P, **{k: v})
                e = tscore(Q)
                log.append([round(e, 4), {k: v}, 'total']); print('total', rnd, k, v, round(e, 4), flush=True)
                if e < tbest - 1e-4:
                    tbest, P, changed = e, Q, True
        if not changed:
            break
    W, rows = run_walk(P, games, tprior, btname, d1s, avs)
    return after_tune(P, W, rows, log)


def after_tune(P, W, rows, log):
    D, Xa, y, TX, ty, S, line, tline, d1 = matrices(rows, BASE + CANDS)
    col = {f: i for i, f in enumerate(BASE + CANDS)}
    tune = (S >= SCORE0) & (S <= TUNE_END) & d1
    held = (S > TUNE_END) & d1

    def pr(feats):
        return walk_pred(Xa[:, [col[f] for f in feats]], y, S, d1)

    # 2. candidates: forward selection on 2016-20 absolute error, a candidate kept only at paired t <= -1.5;
    #    2021-26 reported for each, never used to choose. CBB_FEATS=a,b,... fixes the inputs instead (Oct 23 2026: the
    #    shipped set plus gc, see the note at GC; greedy reselection let gm push out bpi, worse on lined games)
    feats = list(BASE)
    base = pr(feats)
    cand_log = []
    if os.environ.get('CBB_FEATS'):
        feats = os.environ['CBB_FEATS'].split(',')
        base = pr(feats)
    while not os.environ.get('CBB_FEATS'):
        tries = []
        for c in CANDS:
            if c in feats:
                continue
            p = pr(feats + [c])
            e0, e1 = np.abs(base - y), np.abs(p - y)
            tries.append((paired_t(e1[tune], e0[tune]), c, p,
                          {'cand': c, 'with': feats + [c], 'tuneMae': round(float(e1[tune].mean()), 4), 'baseMae': round(float(e0[tune].mean()), 4),
                           't': round(paired_t(e1[tune], e0[tune]), 2), 'heldMae': round(float(e1[held].mean()), 4),
                           'heldBase': round(float(e0[held].mean()), 4), 'heldT': round(paired_t(e1[held], e0[held]), 2)}))
        if not tries:
            break
        tries.sort(key=lambda z: z[0])
        cand_log.extend(z[3] for z in tries)
        for z in tries:
            print('cand', z[3], flush=True)
        if tries[0][0] > -1.5:
            break
        feats.append(tries[0][1]); base = tries[0][2]
        print('kept', tries[0][1], flush=True)
    # each core input taken out, same test: one whose removal cuts 2016-20 error at t <= -1.5 is dropped (worst first,
    # then the rest re-tested), so the core earns its place the way a candidate does
    drop_log = []
    while True:
        tries = []
        for f in BASE:
            if f not in feats or f == 'eff':
                continue
            p = pr([z for z in feats if z != f])
            e0, e1 = np.abs(base - y), np.abs(p - y)
            tries.append((paired_t(e1[tune], e0[tune]), f, p, {'drop': f, 'without': [z for z in feats if z != f], 't': round(paired_t(e1[tune], e0[tune]), 2),
                                                               'heldT': round(paired_t(e1[held], e0[held]), 2)}))
        tries.sort(key=lambda z: z[0])
        drop_log.extend(z[3] for z in tries)
        if not tries or tries[0][0] > -1.5:
            break
        feats.remove(tries[0][1]); base = tries[0][2]
        print('dropped', tries[0][1], flush=True)
    pred = base
    return P, W, rows, log, feats, pred, cand_log, drop_log, (D, Xa, y, TX, ty, S, line, tline, d1, col)


def report():
    P, W, rows, log, feats, pred, cand_log, drop_log, M = fit()
    D, Xa, y, TX, ty, S, line, tline, d1, col = M
    Xm = Xa[:, [col[f] for f in feats]]
    tpred = walk_pred(TX, ty, S, d1)
    ok = ~np.isnan(pred) & d1
    tune = ok & (S <= TUNE_END); held = ok & (S > TUNE_END)
    mlh = np.array([g.get('mlh') or np.nan for g, _, _ in D]); mla = np.array([g.get('mla') or np.nan for g, _, _ in D])
    pm = np.array([ml_prob(a, b) if a == a and b == b else np.nan for a, b in zip(mlh, mla)])
    win = (y > 0).astype(float)

    # win probability: sd of a normal around the margin, by maximum likelihood on 2016-20 (and checked on 2021-26)
    def ll(p, k):
        p = np.clip(p, 1e-4, 1 - 1e-4)
        return float(-np.mean(win[k] * np.log(p[k]) + (1 - win[k]) * np.log(1 - p[k])))
    Phi = np.vectorize(phi)
    k = tune & (y != 0)
    sds = np.arange(9.0, 14.01, 0.1)
    sd0 = float(sds[np.argmin([ll(Phi(pred / s), k) for s in sds])])
    # walk-forward and weighted to recent seasons (half-life 2), as the NBA's: the noise around the model has grown,
    # and one sd fit on 2016-20 (11.3) left 2021-26 chances too sure. Each season priced with the sd fit on the seasons
    # before it (2016, the first, with the 2016-20 fit); live, the same fit through the last season
    # (scripts/cbb_kalman_research.py, Oct 2026: 2021-26 log loss .49859 -> .49805, live 12.0)
    seas = sorted({int(s_) for s_ in S[ok]})
    LLs = {s_: np.array([ll(Phi(pred / x), ok & (S == s_) & (y != 0)) * int((ok & (S == s_) & (y != 0)).sum()) for x in sds]) for s_ in seas}
    wsd = lambda s_: float(sds[np.argmin(sum(0.5 ** ((s_ - 1 - t) / 2) * LLs[t] for t in seas if t < s_))]) if any(t < s_ for t in seas) else sd0
    sd_by = {s_: wsd(s_) for s_ in seas}
    sd = wsd(max(seas) + 1)
    pw = Phi(pred / np.array([sd_by.get(int(s_), sd) for s_ in S]))
    # blend with the market's line (share of the model's edge that holds up), fit on 2016-20
    has = ~np.isnan(line)
    ws = np.arange(0, 1.01, 0.05)
    wb = float(ws[np.argmin([np.mean(np.abs(w * pred[tune & has] + (1 - w) * line[tune & has] - y[tune & has])) for w in ws])])

    def block(k):
        k = k & has
        e = pred[k] - line[k]; r = y[k] - line[k]
        res = {'games': int(k.sum()), 'maeModel': round(float(np.mean(np.abs(pred[k] - y[k]))), 3),
               'maeLine': round(float(np.mean(np.abs(line[k] - y[k]))), 3),
               'maeBlend': round(float(np.mean(np.abs(wb * pred[k] + (1 - wb) * line[k] - y[k]))), 3),
               'tVsLine': round(paired_t(np.abs(pred[k] - y[k]), np.abs(line[k] - y[k])), 2),
               'rModelVsLine': round(float(np.corrcoef(pred[k], line[k])[0, 1]), 3),
               'edgeSlope': round(float(np.polyfit(e, r, 1)[0]), 3)}
        for th in (1, 2, 3, 4):
            pick = (np.abs(e) >= th) & (r != 0)
            n = int(pick.sum())
            res[f'ats{th}'] = {'n': n, 'pct': round(float((np.sign(e[pick]) == np.sign(r[pick])).mean()), 3) if n else None}
        km = k & ~np.isnan(pm) & (y != 0)
        res['llModel'], res['llMarket'], res['mlGames'] = ll(pw, km), ll(pm, km), int(km.sum())
        res['llModel'] = round(res['llModel'], 4); res['llMarket'] = round(res['llMarket'], 4)
        kt = k & ~np.isnan(tline) & ~np.isnan(tpred)
        res['totalMaeModel'] = round(float(np.mean(np.abs(tpred[kt] - ty[kt]))), 3)
        res['totalMaeLine'] = round(float(np.mean(np.abs(tline[kt] - ty[kt]))), 3)
        return res

    test = {'2016-20 (tuning)': block(tune), '2021-26 (held out)': block(held), 'all 2016-26': block(ok)}
    by_season = {int(s): block(ok & (S == s)) for s in range(SCORE0, LAST + 1)}
    # calibration: model win chance in bins against how often the side won, held out
    cal = []
    kk = held & (y != 0)
    for lo in np.arange(0.5, 1.0, 0.05):
        fav = np.maximum(pw, 1 - pw)
        b = kk & (fav >= lo) & (fav < lo + 0.05)
        if b.sum():
            won = np.where(pw[b] >= 0.5, win[b], 1 - win[b])
            cal.append({'bin': round(float(lo), 2), 'n': int(b.sum()), 'model': round(float(fav[b].mean()), 3), 'won': round(float(won.mean()), 3)})
    # final weights on every D-I season
    tr = ok | ((S < SCORE0) & d1 & (S > FIRST))
    b = np.linalg.lstsq(Xm[tr], y[tr], rcond=None)[0]
    res = y[tr] - Xm[tr] @ b; cov = (res @ res / (tr.sum() - len(b))) * np.linalg.inv(Xm[tr].T @ Xm[tr])
    tb = np.linalg.lstsq(TX[tr], ty[tr], rcond=None)[0]
    tsd = float(np.std((tpred - ty)[ok & ~np.isnan(tpred)]))
    # the preseason prior: walk-forward fit (each season's weights from the seasons before) against the season's final rating
    pri = W.prior_rows
    pr_test = []
    for s in range(SCORE0, LAST + 1):
        c = W.pcoef.get(s)
        R = [r for r in pri if r[0] == s]
        if not c or not R:
            continue
        p = np.array([sum(c[k] * r[2][k] for k in PRIOR_F) for r in R]); t = np.array([r[3] for r in R])
        l = np.array([r[2]['last'] for r in R])
        pr_test.append({'season': s, 'teams': len(R), 'rPrior': round(float(np.corrcoef(p, t)[0, 1]), 3), 'rLast': round(float(np.corrcoef(l, t)[0, 1]), 3),
                        'maePrior': round(float(np.mean(np.abs(p - t))), 2)})
    pc = W.prior_coef(LAST + 1)
    out = {'params': P, 'feats': feats, 'coef': {f: round(float(v), 4) for f, v in zip(feats, b)},
           't': {f: round(float(v / math.sqrt(cov[i, i])), 1) for i, (f, v) in enumerate(zip(feats, b))},
           'tcoef': {f: round(float(v), 4) for f, v in zip(TFEATS, tb)}, 'sd': round(sd, 2), 'sdBySeason': {str(k_): round(v, 2) for k_, v in sd_by.items()}, 'sdFixed2016_20': round(sd0, 2), 'tsd': round(tsd, 2), 'blend': wb,
           'prior': {k: round(float(v), 4) for k, v in pc.items()}, 'priorTest': pr_test,
           'test': test, 'bySeason': by_season, 'calib': cal, 'select': cand_log, 'drop': drop_log,
           'grid': log, 'seasons': [SCORE0, LAST], 'tune': [SCORE0, TUNE_END]}
    if os.path.exists(FIT):
        # the FV tests (--fv-test) run apart from the fit; keep their record
        out.update({k: v for k, v in json.load(open(FIT)).items() if k.startswith('fvTest')})
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    # the state the daily build starts the next season from
    st = {'elo': {t: round(v, 1) for t, v in W.elo.items()}, 'mkt': {t: round(v, 2) for t, v in W.mkt.items()}, 'tlg': round(W.tlg, 2),
          'tm': {t: round(v, 2) for t, v in W.tm.items()},
          'final': {t: {k: round(v, 3) for k, v in r.items()} for t, r in W.final[LAST].items()}, 'season': LAST,
          'att': {t: round(sum(v) / len(v), 4) for t, v in W.att.items() if v}}
    with open(STATE, 'w') as f:
        json.dump(st, f, separators=(',', ':'))
    # walk-forward predictions for the picks backtest (scripts/cbb_picks.py --backtest)
    bt = [{'id': g['id'], 'S': int(s), 'm': round(float(m), 2), 'L': (None if np.isnan(l) else float(l)), 'res': int(r),
           'mlH': g.get('mlh'), 'mlA': g.get('mla'), 'open': (-g['open'] if g.get('open') is not None else None)}
          for (g, _, _), m, s, l, r, kk in zip(D, pred, S, line, y, ok) if kk]
    with gzip.open(os.path.join(CACHE, 'walk_pred.json.gz'), 'wt') as f:
        json.dump(bt, f)
    print(json.dumps({k: v for k, v in out.items() if k not in ('grid', 'select', 'bySeason')}, indent=1))




def fv_test():
    """the board's FV grades and drivers as team terms in the preseason prior, each added on its own (and all together,
    and in place of the BPM terms), against the shipped model on 2016-20 margin error (paired t; kept at t <= -1.5 with
    2021-26 not worse) -> data/cbb_games_fit.json 'fvTest'"""
    global PRIOR_F
    games, btname, d1s, tprior, avs = load_all()
    F = json.load(open(FIT))
    P, feats = F['params'], F['feats']
    base_pf = list(PRIOR_F)

    def run(pf):
        global PRIOR_F
        PRIOR_F = pf
        W, rows = run_walk(P, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = matrices(rows, feats)
        pred = walk_pred(Xm, y, S, d1)
        pr = []
        for s in range(SCORE0, LAST + 1):
            c = W.pcoef.get(s); R = [r for r in W.prior_rows if r[0] == s]
            if c and R:
                p = np.array([sum(c[k] * r[2][k] for k in pf) for r in R]); t = np.array([r[3] for r in R])
                pr.append(float(np.mean(np.abs(p - t))))
        return pred, y, S, d1, float(np.mean(pr)), W.prior_coef(LAST + 1)
    b, y, S, d1, bpr, _ = run(base_pf)
    ok = ~np.isnan(b) & d1
    tune, held = ok & (S <= TUNE_END), ok & (S > TUNE_END)
    out = []
    trials = [[c] for c in FV_CANDS] + [FV_CANDS, ['fvw', 'fvfr']]
    for add in trials:
        for repl in (False, True):
            if repl and add not in (FV_CANDS, ['fvw', 'fvfr']):
                continue
            pf = [k for k in base_pf if not (repl and k in ('ret', 'tr', 'fr'))] + add
            p, _, _, _, ppr, pc = run(pf)
            e0, e1 = np.abs(b - y), np.abs(p - y)
            r = {'add': add, 'replaceBpm': repl, 't': round(paired_t(e1[tune], e0[tune]), 2), 'heldT': round(paired_t(e1[held], e0[held]), 2),
                 'tuneMae': round(float(e1[tune].mean()), 4), 'baseTune': round(float(e0[tune].mean()), 4),
                 'heldMae': round(float(e1[held].mean()), 4), 'baseHeld': round(float(e0[held].mean()), 4),
                 'priorMae': round(ppr, 3), 'basePriorMae': round(bpr, 3), 'coef': {k: round(float(pc[k]), 3) for k in add}}
            print(r, flush=True)
            out.append(r)
    PRIOR_F = base_pf
    F['fvTest'] = out
    with open(FIT, 'w') as f:
        json.dump(F, f, indent=1)


if __name__ == '__main__':
    if '--fv-test' in sys.argv:
        fv_test()
    elif '--fit' in sys.argv:
        report()
    else:
        import cbb_games_live
        cbb_games_live.build()
