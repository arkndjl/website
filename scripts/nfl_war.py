#!/usr/bin/env python3
"""NFL WAR leaderboards for the NFL ARKBOARD (data/nfl_war.json), and the AV model behind them (data/nfl_war_fit.json).

    python3 scripts/nfl_war.py          # this season's board from nflverse (stdlib only; run by the cfb board job)
    python3 scripts/nfl_war.py --fit    # refit the AV model on PFR's AV (numpy) and write data/nfl_war_fit.json
    python3 scripts/nfl_war.py --calibrate  # refit the WAR scale on 2021-25 team seasons: data/nfl_war_calib.json
    python3 scripts/nfl_war.py --positions  # refit the replacement line for each sub-position: data/nfl_war_pos.json

The board's WAR is .6 x this AV WAR + .4 x XV (scripts/nfl_xv.py, data/nfl_xv.json): XV measures quality by the stat-line
parts that track team margin, and the blend is where a point of value lost to an absence costs a point of margin
(missed games 2018-25, held-out seasons; AV WAR alone explains less than half as much, next season and contracts tie).
war_ledger (the game model's injury costs) stays on AV WAR. Rows carry wav (AV WAR) and xv.

The board's lines are by sub-position (data/nfl_war_pos.json, see positions()): AV sets the spread inside a spot, and
what an average regular there is worth over replacement blends missed games, veteran contracts and AV. NFL_REPL below
(one line per group) is the fallback when that file is missing, and the model input positions() starts from.

NFL WAR = (AV - NFL_REPL[group] x snap share) x NWAR_PER_AV (scripts/cfb_av.mjs). NWAR_PER_AV is wins per team AV
(least squares, 2021-25 team seasons, tested leaving out each season). NFL_REPL[group] is the AV a replacement player
at the position earns in a full season of snaps: the AV rate of the position's part-timers (5-35% of snaps, the
freely available players), scaled together so a team of replacements (its snap shares at the mean) wins REPL_WINS
of 17. Team WAR then sums to wins - REPL_WINS. One line for every position (6.2) left DBs and TEs at about zero
and RBs high, against what teams pay (veteran contracts signed after a 2021-25 season, cap %: see market in
data/nfl_war_calib.json); the AV rate of a starter differs by position (RB 16 a full season, DB 7). Snap share is the player's snaps over his team's plays on his side across
a 17-game season, so mid-season it is the share so far and replacement accrues as he plays.

AV: Pro Football Reference's Approximate Value (Drinen) is the target, but PFR can't be scraped, so the board
rebuilds it from nflverse's play stats (stats_player_week), PFR snap counts (snap_counts) and scores (nfldata
games.csv), the way Drinen builds it: each team gets an offense pool (100 at league-average scoring over 17 games)
and a defense pool (100 at league-average points allowed), and players split the pools by role and production.

    offense pool  100/17 x points for / league points a game
    defense pool  100/17 x (2 x games - points against / league points a game)
    player AV     sum over features of b[group][f] x share_f x pool, shares of the team's totals that season:
                  snaps (offense or defense), yards (rush, receive, pass, of the team's rush + pass yards), passing
                  TDs, sacks, tackles, tackles for loss, plays on the ball (INT + passes defended + forced fumbles)

Defense (DL, LB, DB) splits its pool its own way, FIP-style (python3 scripts/nfl_war.py --defense -> data/nfl_war_def.json):
    production    c x the player's EPA credits: pressures (sacks counted as expected sacks, pressures x the league's sack
                  rate a pressure, plus the small share of the conversion that repeats), run and pass stops (tackles on
                  runs and completions that failed, split among the tacklers), run TFLs, interceptions, passes defended
                  and forced fumbles, each at its play-by-play EPA (2018-25); c is fit on team seasons, the pool on the
                  credits, leave one season out
    snaps         the rest of the pool by defensive snap share
  Pressures come from PFR's advanced defense (nflverse pfr_advstats, 2018 on); before 2018 a pressure count is sacks over the
  league rate. PFR's own defensive AV leans on tackles and barely moves with sacks (b sack .04 for DL), and a season's
  sacks repeat far less than its pressures (year to year r .29 EDGE, .41 DT against .55, .65).

The b's are fit (non-negative least squares) to PFR's own AV: nflverse's draft picks carry each player's
weighted career AV (w_av: best season 100%, next 95%, ...), which PFR updates in season, so each drafted player
from 2016-25 is one equation over his seasons (2016-2025, ordered by predicted AV, refit until the order holds).
Tested on the 2024-25 draft classes after fitting on 2016-23 (the 2025 class alone is a one-season test).
PFR posts AV only after a season (2026 rookies all read 0 in October), so this season's AV is the model's. Groups: QB, RB, WR, TE, OL, DL, LB, DB;
the board shows DE and pass-rushing OLBs (sacks + QB hits a snap) as EDGE, DT/NT as DL, ILB/MLB and 4-3 OLBs as LB,
by the roster's depth-chart spot.
Kickers, punters and long snappers aren't graded (PFR gives them little AV too).
"""
import csv
import json
import math
import os
import sys
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM   # noqa: E402  the shared player-name key (scripts/names.py)
import faces   # noqa: E402  headshot ids (scripts/faces.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'nfl')
FIT = os.path.join(ROOT, 'data', 'nfl_war_fit.json')
OUT = os.path.join(ROOT, 'data', 'nfl_war.json')            # season, week, counts: read by Hugo
PLAYERS = os.path.join(ROOT, 'static', 'data', 'nfl-war.json')  # every player: fetched by the page
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
GAMES = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'

# keep in step with scripts/cfb_av.mjs
NFL_REPL_AV = 6.2   # the mean line (by FV, no position)
NFL_REPL = {'QB': 7.9, 'RB': 9.0, 'WR': 4.95, 'TE': 2.6, 'OL': 6.7, 'DL': 6.4, 'LB': 7.1, 'DB': 5.2}
CONTRACTS = f'{REL}/contracts/historical_contracts.csv.gz'
NWAR_PER_AV = 0.091
REPL_WINS = 3
CALIB = os.path.join(ROOT, 'data', 'nfl_war_calib.json')
POSFIT = os.path.join(ROOT, 'data', 'nfl_war_pos.json')   # the lines by sub-position: python3 scripts/nfl_war.py --positions
# sub-positions: tackles and interior line by the snap listing; the team's two most-used WRs and CBs outside, the rest in
# the slot (SWR) and at nickel (NCB); DE and pass-rushing OLBs are EDGE, DT/NT are DT
SUBS = ['QB', 'RB', 'WR', 'SWR', 'TE', 'OT', 'IOL', 'EDGE', 'DT', 'LB', 'CB', 'NCB', 'S']
SLOTS = {'QB': 1, 'RB': 1, 'WR': 2, 'SWR': 1, 'TE': 1, 'OT': 2, 'IOL': 3, 'EDGE': 2, 'DT': 2, 'LB': 2, 'CB': 2, 'NCB': 1, 'S': 2}
SUB_GROUP = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'SWR': 'WR', 'TE': 'TE', 'OT': 'OL', 'IOL': 'OL', 'EDGE': 'DL', 'DT': 'DL', 'LB': 'LB', 'CB': 'DB', 'NCB': 'DB', 'S': 'DB'}


def sub_lines():
    """{sub: replacement AV a full season}, {sub: wins an average regular adds a full season} and {sub: spread} from
    data/nfl_war_pos.json, else the group lines (NFL_REPL), no WAA and no spread."""
    try:
        with open(POSFIT) as f:
            d = json.load(f)
        return d['line'], d['value'], d.get('spread', {})
    except (OSError, KeyError, ValueError):
        return {s: NFL_REPL[SUB_GROUP[s]] for s in SUBS}, None, {}


def war_of(av, share, sub, line, value=None, spread=None):
    """WAR for AV at a snap share (a full season = 1): (AV - line x share) x .091; on defense the wins over an average
    regular at the spot are then scaled by the spot's spread (positions(): contracts and missed games against the
    team-fit scale of the defensive credits), so an average regular stays where he was."""
    w = NWAR_PER_AV * (av - line[sub] * share)
    if spread and value and sub in spread:
        w = value[sub] * share + spread[sub] * (w - value[sub] * share)
    return w

GROUP = {'QB': 'QB', 'RB': 'RB', 'HB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE',
         'OL': 'OL', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OT': 'OL', 'OG': 'OL',
         'DL': 'DL', 'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'LB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'OLB': 'LB',
         'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'DB': 'DB'}
FEATS = {'QB': ['snap', 'pass', 'ptd', 'rush'], 'RB': ['snap', 'rush', 'rec'], 'WR': ['snap', 'rec'],
         'TE': ['snap', 'rec'], 'OL': ['snap'],
         'DL': ['snap', 'prod'], 'LB': ['snap', 'prod'], 'DB': ['snap', 'prod']}
OFFENSE = {'QB', 'RB', 'WR', 'TE', 'OL'}
# defense before --defense: PFR AV's split (shares of the team's sacks, tackles, TFLs and plays on the ball), kept to
# compare against and as the fallback without data/nfl_war_def.json
PFR_DEF_FEATS = ['snap', 'sack', 'tkl', 'tfl', 'ball']
PFR_DEF_COEF = {'DL': {'snap': 0.0405, 'sack': 0.0417, 'tkl': 0.5255, 'tfl': 0.225, 'ball': 0.0},
                'LB': {'snap': 0.0193, 'sack': 0.0604, 'tkl': 0.3418, 'tfl': 0.1657, 'ball': 0.2551},
                'DB': {'snap': 0.0308, 'sack': 0.1868, 'tkl': 0.1308, 'tfl': 0.0, 'ball': 0.2186}}
DEFFIT = os.path.join(ROOT, 'data', 'nfl_war_def.json')   # python3 scripts/nfl_war.py --defense
_DEF = []


def def_model():
    """The defensive split (EPA values, sack conversion, c) from data/nfl_war_def.json, or None."""
    if not _DEF:
        try:
            with open(DEFFIT) as f:
                _DEF.append(json.load(f)['model'])
        except (OSError, KeyError, ValueError):
            _DEF.append(None)
    return _DEF[0]
EDGE_RUSH = 1.5   # sacks + QB hits per 100 defensive snaps that makes a roster OLB an EDGE (3-4) and not a 4-3 SAM/WILL


def get(name, url, fresh=False):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if fresh or not os.path.exists(p):
        req = urllib.request.Request(url, headers={'User-Agent': 'arkndjl.net arkboard'})
        with urllib.request.urlopen(req, timeout=120) as r, open(p + '.tmp', 'wb') as f:
            f.write(r.read())
        os.replace(p + '.tmp', p)
    return p


_MEMO = {}     # parsed files, kept while war_ledger walks one season week by week


def rows(p):
    if p in _MEMO:
        yield from _MEMO[p]
        return
    with open(p, newline='', encoding='utf-8') as f:
        yield from csv.DictReader(f)


def num(x):
    try:
        return float(x) if x not in (None, '', 'NA') else 0.0
    except ValueError:
        return 0.0


def season_data(y, fresh=False, thru=None):
    """Per player-team season: snaps, play stats and pools. Keyed (pfr_id, team); stats rows joined by gsis id.
    thru: only weeks before it (the season to date before that week's games)."""
    games = [g for g in rows(get('games.csv', GAMES, fresh)) if g['season'] == str(y) and g['game_type'] == 'REG'
             and g['home_score'] not in ('', 'NA') and (thru is None or int(g['week']) < thru)]
    team = defaultdict(lambda: {'g': 0, 'pf': 0.0, 'pa': 0.0})
    for g in games:
        h, a, hs, as_ = g['home_team'], g['away_team'], num(g['home_score']), num(g['away_score'])
        for t, pf, pa in ((h, hs, as_), (a, as_, hs)):
            team[t]['g'] += 1; team[t]['pf'] += pf; team[t]['pa'] += pa
    lg = sum(t['pf'] for t in team.values()) / max(1, sum(t['g'] for t in team.values()))
    for t in team.values():
        t['off'] = 100 / 17 * t['pf'] / lg
        t['def'] = 100 / 17 * (2 * t['g'] - t['pa'] / lg)
    played = {g['game_id'] for g in games}

    snaps = defaultdict(lambda: {'off': 0, 'def': 0, 'g': 0, 'pos': Counter(), 'name': ''})
    gmax = defaultdict(lambda: [0, 0])     # (game, team) -> most offense / defense snaps by one player = team plays
    for r in rows(get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv', fresh)):
        if r['game_type'] != 'REG' or r['game_id'] not in played:
            continue
        o, d = num(r['offense_snaps']), num(r['defense_snaps'])
        s = snaps[(r['pfr_player_id'], r['team'])]
        s['off'] += o; s['def'] += d; s['name'] = r['player']
        if o or d: s['g'] += 1
        s['pos'][r['position']] += 1
        m = gmax[(r['game_id'], r['team'])]
        m[0] = max(m[0], o); m[1] = max(m[1], d)
    plays = defaultdict(lambda: [0, 0])
    for (_, t), m in gmax.items():
        plays[t][0] += m[0]; plays[t][1] += m[1]

    # play stats and play-by-play carry the franchise's current code (LV for the 2016-19 Raiders): map to the season's
    alias = {a_: b_ for a_, b_ in (('LV', 'OAK'), ('OAK', 'LV'), ('LA', 'LAR'), ('LAR', 'LA'), ('LAC', 'SD'), ('SD', 'LAC')) if a_ not in team and b_ in team}
    tm_ = lambda t: alias.get(t, t)
    stat = defaultdict(lambda: defaultdict(float))
    meta = {}
    tot = defaultdict(lambda: defaultdict(float))
    for r in rows(get(f'stats_player_week_{y}.csv', f'{REL}/stats_player/stats_player_week_{y}.csv', fresh)):
        if r['season_type'] != 'REG' or r.get('game_id') not in played:
            continue
        k = (r['player_id'], tm_(r['team']))
        meta[r['player_id']] = (r['player_display_name'], r['position'], r.get('headshot_url', ''))
        v = {'pass': num(r['passing_yards']), 'ptd': num(r['passing_tds']), 'rush': num(r['rushing_yards']),
             'rec': num(r['receiving_yards']), 'sack': num(r['def_sacks']),
             'tkl': num(r['def_tackles_solo']) + num(r['def_tackle_assists']), 'tfl': num(r['def_tackles_for_loss']),
             'ball': num(r['def_interceptions']) + num(r['def_pass_defended']) + num(r['def_fumbles_forced']),
             'hit': num(r['def_qb_hits']), 'pint': num(r['passing_interceptions']), 'rtd': num(r['rushing_tds']),
             'retd': num(r['receiving_tds']), 'int': num(r['def_interceptions']), 'pd': num(r['def_pass_defended']),
             'ff': num(r['def_fumbles_forced']), 'recs': num(r['receptions']), 'car': num(r['carries']),
             'fl': sum(num(r.get(c)) for c in ('rushing_fumbles_lost', 'receiving_fumbles_lost', 'sack_fumbles_lost')),
             'tp': sum(num(r.get(c)) for c in ('passing_2pt_conversions', 'rushing_2pt_conversions', 'receiving_2pt_conversions')),
             'sttd': num(r.get('special_teams_tds'))}
        for f, x in v.items():
            stat[k][f] += x
            tot[k[1]][f] += x
    for t in tot.values():
        t['yds'] = t['pass'] + t['rush']
    sd = {'team': team, 'snaps': snaps, 'plays': plays, 'stat': stat, 'tot': tot, 'meta': meta, 'lg': lg}
    D = def_model()
    if D:
        sd['dplay'] = {(g_, tm_(t)): v for (g_, t), v in def_plays(y, fresh, thru).items()}
        sd['adv'] = {(p_, tm_(t)): v for (p_, t), v in def_adv(y, fresh, thru).items()}
        # each team's EPA credits and defensive snap shares, for the pool split
        cr, dsn = Counter(), Counter()
        for (g_, t) in set(stat) | set(sd['dplay']):
            st = stat.get((g_, t))
            cr[t] += play_credit(D, st, sd['dplay'].get((g_, t)))
            if not sd['adv']:
                cr[t] += rush_credit(D, st, None)
        for (p_, t), a in sd['adv'].items():
            cr[t] += rush_credit(D, None, a)
        for (p_, t), s_ in snaps.items():
            if plays[t][1]:
                dsn[t] += s_['def'] / plays[t][1]
        sd['dcredit'], sd['dsnaps'] = cr, dsn
    return sd


def def_plays(y, fresh=False, thru=None):
    """{(gsis, team): [run stops, pass stops, run TFLs]} from play-by-play: a stop is a tackle on a run or a completed
    pass that failed (EPA <= 0), one to each tackler; cached by week (scripts/.cache/nfl/defplays_<y>.json)."""
    src = get(f'play_by_play_{y}.csv.gz', f'{REL}/pbp/play_by_play_{y}.csv.gz', fresh)
    cache = os.path.join(CACHE, f'defplays_{y}.json')
    if not os.path.exists(cache) or os.path.getmtime(cache) < os.path.getmtime(src):
        import gzip
        TK = ['solo_tackle_1_player_id', 'solo_tackle_2_player_id', 'assist_tackle_1_player_id', 'assist_tackle_2_player_id',
              'assist_tackle_3_player_id', 'assist_tackle_4_player_id', 'tackle_with_assist_1_player_id', 'tackle_with_assist_2_player_id']
        acc = defaultdict(lambda: [0, 0, 0])
        with gzip.open(src, 'rt', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['season_type'] != 'REG' or r['play_type'] not in ('run', 'pass') or r['epa'] in ('', 'NA'):
                    continue
                run = r['play_type'] == 'run'
                if r['success'] == '1' or not (run or r['complete_pass'] == '1'):
                    continue
                k_ = r['week'] + '|' + r['defteam'] + '|'
                for gid in {r[c] for c in TK if r[c] not in ('', 'NA')}:
                    acc[k_ + gid][0 if run else 1] += 1
                if run:
                    for c in ('tackle_for_loss_1_player_id', 'tackle_for_loss_2_player_id'):
                        if r[c] not in ('', 'NA'):
                            acc[k_ + r[c]][2] += 1
        with open(cache, 'w') as f:
            json.dump(acc, f, separators=(',', ':'))
    with open(cache) as f:
        raw = json.load(f)
    out = defaultdict(lambda: [0, 0, 0])
    for k_, v in raw.items():
        w, t, gid = k_.split('|')
        if thru is None or int(w) < thru:
            o = out[(gid, t)]
            for i in range(3):
                o[i] += v[i]
    return out


def def_adv(y, fresh=False, thru=None):
    """{(pfr, team): {'prss': pressures, 'sk': sacks}} from PFR's advanced defense (2018 on), else {}."""
    if y < 2018:
        return {}
    out = defaultdict(lambda: {'prss': 0.0, 'sk': 0.0})
    for r in rows(get(f'advstats_week_def_{y}.csv', f'{REL}/pfr_advstats/advstats_week_def_{y}.csv', fresh)):
        if r['game_type'] == 'REG' and (thru is None or int(r['week']) < thru):
            a = out[(r['pfr_player_id'], r['team'])]
            a['prss'] += num(r['def_pressures']); a['sk'] += num(r['def_sacks'])
    return out


def rush_credit(D, st, adv):
    """EPA credit for the pass rush: expected sacks (pressures x the league's sacks a pressure, plus convRel of his own
    conversion above it) at a sack's EPA, the other pressures at theirs. Without PFR pressures, sacks over the rate."""
    V, conv, rel = D['values'], D['conv'], D['convRel']
    sk = adv['sk'] if adv else (st or {}).get('sack', 0.0)
    prss = adv['prss'] if adv else sk / conv
    xs = conv * prss + rel * (sk - conv * prss)
    return V['sack'] * xs + V['press'] * max(0.0, prss - sk)


def play_credit(D, st, pl):
    """EPA credit for stops, run TFLs and plays on the ball."""
    V, st, pl = D['values'], st or {}, pl or (0, 0, 0)
    return (V['stopR'] * pl[0] + V['stopP'] * pl[1] + V['tfl'] * pl[2] + V['int'] * st.get('int', 0.0)
            + V['pd'] * max(0.0, st.get('pd', 0.0) - st.get('int', 0.0)) + V['ff'] * st.get('ff', 0.0))


def features(sd, pfr, gsis, t, group, pfr_split=False):
    """{feature: share x pool} for one player-team season, and the snap line."""
    s, st, T, P, tm = sd['snaps'].get((pfr, t)), sd['stat'].get((gsis, t), {}), sd['tot'][t], sd['plays'][t], sd['team'].get(t)
    if not tm:
        return None
    off = group in OFFENSE
    pool = tm['off'] if off else tm['def']
    snapshare = ((s['off'] / P[0]) if off else (s['def'] / P[1])) if s and P[0] and P[1] else 0.0
    D = None if off or pfr_split else def_model()
    if D and 'dcredit' in sd:
        # c x his EPA credits, and the rest of the pool by defensive snap share
        a = sd['adv'].get((pfr, t)) if sd['adv'] else None
        cr = play_credit(D, st, sd['dplay'].get((gsis, t))) + rush_credit(D, st, a)
        rest = pool - D['c'] * sd['dcredit'][t]
        return {'snap': snapshare / sd['dsnaps'][t] * rest if sd['dsnaps'][t] else 0.0, 'prod': D['c'] * cr}
    x = {}
    for f in (FEATS[group] if off else PFR_DEF_FEATS):
        if f == 'snap':
            v = snapshare
        elif f in ('pass', 'rush', 'rec'):
            v = max(0.0, st.get(f, 0.0)) / T['yds'] if T['yds'] > 0 else 0.0
        else:
            v = max(0.0, st.get(f, 0.0)) / T[f] if T[f] > 0 else 0.0
        x[f] = v * pool
    return x


def group_of(pos_counter, fallback):
    pos = pos_counter.most_common(1)[0][0] if pos_counter else fallback
    return GROUP.get(pos), pos


def display_pos(group, pos, dc, st, snaps):
    """Board position: the roster's depth-chart spot (dc) where it settles it, else the snap-count listing."""
    rush = (st.get('sack', 0) + st.get('hit', 0)) / max(1, snaps) * 100
    if group == 'DL':
        return 'DL' if dc in ('DT', 'NT') or (not dc and pos != 'DE') else 'EDGE'
    if group == 'LB':
        # OLB is a 3-4 edge or a 4-3 SAM/WILL: the pass rush rate tells them apart
        return 'EDGE' if dc == 'DE' or (dc == 'OLB' and (rush >= EDGE_RUSH or snaps < 100)) else 'LB'
    if group == 'DB':
        return 'CB' if (dc or pos) == 'CB' else 'S' if (dc or pos) in ('S', 'FS', 'SS') else 'CB' if dc == 'DB' else 'S'
    return group


def predict(b, group, x):
    if group not in OFFENSE:
        # defense: the split from --defense (coefficients 1), else PFR AV's
        return sum(x.values()) if 'prod' in x else sum(PFR_DEF_COEF[group].get(f, 0.0) * v for f, v in x.items())
    return sum(b[group].get(f, 0.0) * v for f, v in x.items())


def sub_of(o):
    d = o['disp']
    if d == 'WR':
        return 'WR' if o['rk'] < 2 else 'SWR'
    if d == 'CB':
        return 'CB' if o['rk'] < 2 else 'NCB'
    if d == 'OL':
        return 'OT' if o['pos'] in ('T', 'OT', 'LT', 'RT') else 'IOL'
    return 'DT' if d == 'DL' else d


def team_rows(sd, b, ros):
    """Every player-team season: group, board position, sub-position, AV, snaps and share of the team's plays on his side."""
    out = []
    for (pfr, t), s in sd['snaps'].items():
        g, pos = group_of(s['pos'], '')
        if not g or t not in sd['team']:
            continue
        r = ros.get(pfr, {})
        gsis = r.get('gsis_id', '')
        x = features(sd, pfr, gsis, t, g)
        if x is None:
            continue
        st = sd['stat'].get((gsis, t), {})
        snaps = s['off'] if g in OFFENSE else s['def']
        P = sd['plays'][t]
        plays = P[0] if g in OFFENSE else P[1]
        out.append({'pfr': pfr, 't': t, 'g': g, 'pos': pos, 'disp': display_pos(g, pos, r.get('depth_chart_position', ''), st, snaps),
                    'av': predict(b, g, x), 'snaps': snaps, 'share': snaps / plays if plays else 0.0, 'st': st, 'name': s['name'], 'games': s['g'], 'rk': 0})
    rank = defaultdict(list)
    for o in out:
        if o['disp'] in ('WR', 'CB'):
            rank[(o['t'], o['disp'])].append(o)
    for lst in rank.values():
        for i, o in enumerate(sorted(lst, key=lambda o: -o['snaps'])):
            o['rk'] = i
    for o in out:
        o['sub'] = sub_of(o)
    return out


def rosters(y, fresh=False):
    """Roster rows by PFR id; a third of the file has no PFR id, matched to snap-count players by name and team."""
    ros, by_name = {}, {}
    for r in rows(get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv', fresh)):
        if r['pfr_id']:
            ros[r['pfr_id']] = r
        else:
            by_name[(r['full_name'].lower(), r['team'])] = r
    return ros, by_name


# ---------------------------------------------------------------- fit
def fit():
    import numpy as np

    def nnls(A, y, tol=1e-10):
        # Lawson-Hanson active set
        n = A.shape[1]
        P, w = np.zeros(n, bool), np.zeros(n)
        for _ in range(3 * n):
            g = A.T @ (y - A @ w)
            if P.all() or g[~P].max() <= tol:
                break
            P[np.argmax(np.where(P, -np.inf, g))] = True
            while True:
                z = np.zeros(n)
                z[P] = np.linalg.lstsq(A[:, P], y, rcond=None)[0]
                if (z[P] > 0).all():
                    w = z
                    break
                neg = P & (z <= 0)
                a = np.min(w[neg] / (w[neg] - z[neg]))
                w = w + a * (z - w)
                P &= w > tol
                w[~P] = 0
        return w

    picks = [r for r in rows(get('draft_picks.csv', f'{REL}/draft_picks/draft_picks.csv'))
             if 2016 <= int(r['season']) <= 2025 and r['pfr_player_id'] and r['w_av'] not in ('', 'NA')]
    years = range(2016, 2026)   # PFR posts AV after the season: 2026 rookies all show 0 in October
    SD = {y: season_data(y) for y in years}
    byp = {y: defaultdict(list) for y in years}
    for y in years:
        for (pid, t), s in SD[y]['snaps'].items():
            byp[y][pid].append((t, s))
    # offense is fit; defense (its own split, --defense) is a fixed part of each season's AV
    cols = [(g, f) for g in FEATS if g in OFFENSE for f in FEATS[g]]
    ci = {c: i for i, c in enumerate(cols)}
    # each player's seasons as feature vectors
    players = []
    for p in picks:
        D, pfr, gsis = int(p['season']), p['pfr_player_id'], p['gsis_id']
        seasons = []
        for y in years:
            if y < D:
                continue
            sd = SD[y]
            v, dv = np.zeros(len(cols)), 0.0
            for t, s in byp[y].get(pfr, []):
                g, pos = group_of(s['pos'], p['position'])
                if not g:
                    continue
                x = features(sd, pfr, gsis, t, g)
                if x and g not in OFFENSE:
                    dv += predict(None, g, x)
                    continue
                for f, val in (x or {}).items():
                    v[ci[(g, f)]] += val
            if v.any() or dv:
                seasons.append((y, v, dv))
        players.append({'D': D, 'y': float(p['w_av']), 'seasons': seasons, 'name': p['pfr_player_name'], 'pos': p['position']})

    def design(ps, b):
        # Y: weighted career AV less the defensive part, so the NNLS fits the offense
        A, Y, O = [], [], []
        for p in ps:
            pred = sorted(p['seasons'], key=lambda s: -(s[1] @ b + s[2])) if b is not None else sorted(p['seasons'], key=lambda s: -(s[1].sum() + s[2]))
            row, off = np.zeros(len(cols)), 0.0
            for k, (_, v, dv) in enumerate(pred):
                row += max(0.0, 1 - 0.05 * k) * v; off += max(0.0, 1 - 0.05 * k) * dv
            A.append(row); Y.append(p['y'] - off); O.append(off)
        return np.array(A), np.array(Y), np.array(O)

    def train(ps):
        b = None
        for _ in range(6):
            A, Y, _ = design(ps, b)
            b = nnls(A, Y)
        return b

    def score(ps, b):
        A, Y, O = design(ps, b)
        pr, Y = A @ b + O, Y + O
        r = float(np.corrcoef(pr, Y)[0, 1])
        return {'n': len(ps), 'r': round(r, 3), 'rmse': round(float(np.sqrt(np.mean((pr - Y) ** 2))), 2)}

    tr = [p for p in players if p['D'] <= 2023]
    te = [p for p in players if p['D'] >= 2024]
    b_tr = train(tr)
    test = {'train_2016_23': score(tr, b_tr), 'test_2024_25': score(te, b_tr)}
    # one season, one number: the 2025 class, whose w_av is its 2025 AV
    test['rookies_2025_one_season'] = score([p for p in players if p['D'] == 2025], b_tr)
    by = {}
    for g in FEATS:
        sub = [p for p in te if any(GROUP.get(p['pos'], p['pos']) == g for _ in [0])]
        if len(sub) >= 10:
            by[g] = score(sub, b_tr)
    test['test_by_group'] = by
    b = train(players)
    coef = {g: {f: round(float(b[ci[(g, f)]]), 4) for f in FEATS[g]} if g in OFFENSE else {f: 1.0 for f in FEATS[g]} for g in FEATS}
    out = {'coef': coef, 'test': test, 'fit': score(players, b), 'edgeRush': EDGE_RUSH,
           'note': 'AV = sum of coef x share x team pool; NNLS on PFR weighted career AV (nflverse draft picks), drafted 2016-26'}
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- board
def build():
    games = list(rows(get('games.csv', GAMES, fresh=True)))
    done = [g for g in games if g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    y = max(int(g['season']) for g in done)
    week = max(int(g['week']) for g in done if int(g['season']) == y)
    out, lines, alpha = board(y, fresh=True)
    publish(out, y, week, done, lines, alpha)


def board(y, thru=None, fresh=False):
    """the board's rows for season y before week thru (whole season if None): (players, replacement lines, XV alpha);
    scripts/player_pctl.py walks past seasons week by week through it"""
    with open(FIT) as f:
        b = json.load(f)['coef']
    sd = season_data(y, fresh, thru)
    ros, by_name = rosters(y, fresh=fresh)
    # match the snap-count players without a PFR id in the roster by name and team, so their play stats (joined by
    # gsis id), age and experience still land
    for (pfr, t), s_ in sd['snaps'].items():
        if pfr not in ros and (s_['name'].lower(), t) in by_name:
            ros[pfr] = by_name[(s_['name'].lower(), t)]
    lines, value, spread = sub_lines()
    agg = {}
    for o in team_rows(sd, b, ros):
        pfr, t, g = o['pfr'], o['t'], o['g']
        share = o['share'] * sd['team'][t]['g'] / 17
        a = agg.setdefault(pfr, {'name': o['name'], 'teams': [], 'g': 0, 'snaps': 0, 'av': 0.0, 'sh': 0.0, 'war': 0.0, 'avg': 0.0, 'grp': Counter(), 'st': Counter(), 'pos': Counter(), 'sub': Counter()})
        a['teams'].append((o['snaps'], t)); a['g'] += o['games']; a['snaps'] += o['snaps']; a['av'] += o['av']; a['sh'] += share
        # WAR over replacement by sub-position, accruing with the snaps played; avg: what an average regular there adds at the same snaps
        a['war'] += war_of(o['av'], share, o['sub'], lines, value, spread)
        a['avg'] += (value or {}).get(o['sub'], 0.0) * share
        a['grp'][g] += o['snaps'] + 0.01; a['pos'][o['pos']] += o['snaps'] + 0.01; a['sub'][o['sub']] += o['snaps'] + 0.01
        for k, v in o['st'].items():
            a['st'][k] += v
        if sd.get('adv'):
            a['st']['prss'] += sd['adv'].get((pfr, t), {}).get('prss', 0)
    teamg = {t: v['g'] for t, v in sd['team'].items()}
    # XV (scripts/nfl_xv.py): WAR on the stat-line parts that track team margin; the board's WAR blends it with AV's
    try:
        import nfl_xv
        prow = []
        xvs, alpha = nfl_xv.board_xv(y, sd, ros, b, rows_out=prow)
    except Exception as e:   # the board still builds on AV alone
        print(f'nfl war: XV skipped ({e!r})')
        xvs, alpha, prow = None, None, []
    # predictive badges (scripts/nfl_badges.py: only those that beat this season's WAR on next season's, held out)
    try:
        import nfl_badges
        bdg = nfl_badges.board_badges(y, prow, thru=thru, frac=max(teamg.values() or [17]) / 17) if prow else {}
    except Exception as e:
        print(f'nfl war: badges skipped ({e!r})')
        bdg = {}
    out = []
    for pfr, a in agg.items():
        if a['snaps'] <= 0:
            continue
        g = a['grp'].most_common(1)[0][0]
        team = max(a['teams'])[1]
        r = ros.get(pfr, {})
        pos = display_pos(g, a['pos'].most_common(1)[0][0], r.get('depth_chart_position', ''), a['st'], a['snaps'])
        tg = max(1, teamg.get(team, 1))
        av = a['av']
        # replacement accrues with the snaps played (share of a 17-game season's plays); below replacement is negative
        wav = a['war']
        xv = xvs.get(pfr, 0.0) if xvs else None
        war = wav if xv is None else alpha * xv + (1 - alpha) * wav
        st = a['st']
        line = (f"{int(st['pass'])} pass yds, {int(st['ptd'])} TD, {int(st['pint'])} INT" if g == 'QB' else
                f"{int(st['rush'])} rush yds, {int(st['rec'])} rec yds" if g == 'RB' else
                f"{int(st['rec'])} rec yds, {int(st['retd'])} TD" if g in ('WR', 'TE') else
                '' if g == 'OL' else
                (f"{int(st['prss'])} prss, " if sd.get('adv') else '') + f"{st['sack']:g} sk, {int(st['tkl'])} tkl, {int(st['tfl'])} TFL, {int(st['ball'])} on ball")
        sub = a['sub'].most_common(1)[0][0]
        # waa: wins over an average regular at his sub-position for the same snaps
        waa = war - a['avg'] if value else None
        out.append({'n': a['name'], 'id': pfr, 't': team, 'tm': '/'.join(sorted({t for _, t in a['teams']})), 'pos': pos,
                    'sp': {'SWR': 'slot', 'NCB': 'nickel', 'OT': 'OT', 'IOL': 'IOL'}.get(sub, ''),
                    'g': a['g'], 'sn': int(a['snaps']), 'av': round(av, 2), 'war': round(war, 2),
                    'wav': round(wav, 2), 'xv': None if xv is None else round(xv, 2), 'waa': None if waa is None else round(waa, 2),
                    'pace': round(war * 17 / tg, 2), 'waaP': None if waa is None else round(waa * 17 / tg, 2), 'sh': round(a['sh'], 3), 'line': line, 'age': age(r.get('birth_date'), y),
                    'exp': r.get('years_exp', ''), 'rook': r.get('rookie_year') == str(y) or r.get('years_exp') == '0', 'col': (r.get('college') or '').split(';')[0],
                    '_st': dict(st), '_g': g, **({'bdg': bdg[pfr]} if pfr in bdg else {})})
    out = [p for p in out if p['sn'] >= 1]
    for p in out:   # NFL.com headshot from the nflverse roster (scripts/faces.py)
        ph = faces.nfl_ph(ros.get(p['id'], {}).get('headshot_url'))
        if ph:
            p['ph'] = ph
    out.sort(key=lambda p: -p['war'])
    return out, lines, alpha


def publish(out, y, week, done, lines, alpha):
    out = [{k: v for k, v in p.items() if k[0] != '_'} for p in out]
    import datetime
    last = max(g['gameday'] for g in done if int(g['season']) == y)
    meta = {'season': y, 'week': week, 'last': last, 'n': len(out), 'replAv': lines, 'warPerAv': round(NWAR_PER_AV, 4), 'replWins': REPL_WINS, 'xvAlpha': alpha,
            'top': [{k: p[k] for k in ('n', 't', 'pos', 'war')} for p in out[:3]]}
    body = json.dumps({'season': y, 'week': week, 'last': last, 'players': out}, separators=(',', ':'))
    try:
        same = open(PLAYERS).read() == body
    except OSError:
        same = False
    if same:
        return print('nfl war: no change')
    meta['asof'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(PLAYERS, 'w') as f:
        f.write(body)
    with open(OUT, 'w') as f:
        json.dump(meta, f, indent=1)
    print(f'nfl war: {y} through week {week}, {len(out)} players; top: ' +
          ', '.join(f"{p['n']} {p['war']}" for p in out[:5]))


def age(bd, y):
    try:
        by, bm, bdd = map(int, bd.split('-'))
    except (AttributeError, ValueError):
        return None
    return y - by - ((9, 1) < (bm, bdd))   # age on Sept 1 of the season


# ---------------------------------------------------------------- WAR by gsis id (game projections' injury costs)
def gsis_map(y, fresh=False):
    """pfr id -> gsis id from the season's roster file, and (lower name, team) -> gsis id for rows without a pfr id."""
    by_pfr, by_name = {}, {}
    for r in rows(get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv', fresh)):
        if r['gsis_id']:
            if r['pfr_id']:
                by_pfr[r['pfr_id']] = r['gsis_id']
            by_name[(r['full_name'].lower(), r['team'])] = r['gsis_id']
    return by_pfr, by_name


def war_ledger(y, thru=None, maps=None, fresh=False):
    """{gsis: [WAR, games]} for season y before week thru (whole season if None), on the board's formula."""
    with open(FIT) as f:
        b = json.load(f)['coef']
    by_pfr, by_name = maps or gsis_map(y, fresh)
    sd = season_data(y, fresh, thru)
    out = {}
    for (pfr, t), s in sd['snaps'].items():
        gsis = by_pfr.get(pfr) or by_name.get((s['name'].lower(), t))
        g, _ = group_of(s['pos'], '')
        if not gsis or not g:
            continue
        x = features(sd, pfr, gsis, t, g)
        if x is None:
            continue
        P = sd['plays'][t]
        share = ((s['off'] / P[0]) if g in OFFENSE else (s['def'] / P[1])) * sd['team'][t]['g'] / 17 if P[0] and P[1] else 0.0
        a = out.setdefault(gsis, [0.0, 0])
        a[0] += (predict(b, g, x) - NFL_REPL[g] * share) * NWAR_PER_AV
        a[1] += s['g']
    return out


# ---------------------------------------------------------------- WAR scale
def calibrate(years=range(2021, 2026)):
    """Wins per team AV and the replacement line, from team seasons on this model's AV (data/nfl_war_calib.json)."""
    with open(FIT) as f:
        b = json.load(f)['coef']
    games = [g for g in rows(get('games.csv', GAMES)) if g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
    W = Counter()
    for g in games:
        y, hs, as_ = int(g['season']), float(g['home_score']), float(g['away_score'])
        for t, d in ((g['home_team'], hs - as_), (g['away_team'], as_ - hs)):
            W[(y, t)] += 1 if d > 0 else 0.5 if d == 0 else 0
    teams, players = [], []
    for y in years:
        sd = season_data(y)
        gsis_of = {r['pfr_id']: r['gsis_id'] for r in rows(get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv')) if r['pfr_id']}
        T = {}
        for (pfr, t), s in sd['snaps'].items():
            g, _ = group_of(s['pos'], '')
            if not g:
                continue
            x = features(sd, pfr, gsis_of.get(pfr, ''), t, g)
            if x is None:
                continue
            P = sd['plays'][t]
            share = ((s['off'] / P[0]) if g in OFFENSE else (s['def'] / P[1])) if P[0] and P[1] else 0.0
            av = predict(b, g, x)
            a = T.setdefault(t, [0.0, 0.0, 0.0]); a[0] += av; a[1] += share; a[2] += NFL_REPL[g] * share
            players.append((av, share, g, y, s['name']))
        teams += [{'y': y, 't': t, 'av': a[0], 'sh': a[1], 'repl': a[2], 'w': W[(y, t)] * 17 / sd['team'][t]['g']} for t, a in T.items()]
    mean = lambda xs: sum(xs) / len(xs)

    def slope(rs):
        mx, my = mean([r['av'] for r in rs]), mean([r['w'] for r in rs])
        return sum((r['av'] - mx) * (r['w'] - my) for r in rs) / sum((r['av'] - mx) ** 2 for r in rs)
    k = slope(teams)
    mav, msh, mw = mean([r['av'] for r in teams]), mean([r['sh'] for r in teams]), mean([r['w'] for r in teams])
    sx = math.sqrt(sum((r['av'] - mav) ** 2 for r in teams)); sy = math.sqrt(sum((r['w'] - mw) ** 2 for r in teams))
    r = sum((t['av'] - mav) * (t['w'] - mw) for t in teams) / (sx * sy)
    loso = {}
    for y in years:
        tr, te = [t for t in teams if t['y'] != y], [t for t in teams if t['y'] == y]
        ky = slope(tr); a = mean([t['w'] for t in tr]) - ky * mean([t['av'] for t in tr])
        loso[y] = {'k': round(ky, 4), 'rmseWins': round(math.sqrt(mean([(t['w'] - a - ky * t['av']) ** 2 for t in te])), 2)}
    # replacement: team WAR = k x (AV - R x share) sums to wins - REPL_WINS at the mean team
    R = (mav - (mw - REPL_WINS) / k) / msh
    # by position: the part-timers' AV a full season of snaps, scaled together to the same replacement team
    part = defaultdict(lambda: [0.0, 0.0]); shg = Counter()
    for av, sh, g, *_ in players:
        shg[g] += sh / len(teams)
        if 0.05 <= sh < 0.35:
            part[g][0] += av; part[g][1] += sh
    rate = {g: v[0] / v[1] for g, v in part.items()}
    c = (mav - (mw - REPL_WINS) / k) / sum(rate[g] * shg[g] for g in rate)
    used = (NWAR_PER_AV, NFL_REPL)
    war = [used[0] * (t['av'] - t['repl']) for t in teams]
    bins = {}
    for av, sh, *_ in players:
        bins.setdefault(min(14, int(av)), []).append(sh)
    out = {'years': [min(years), max(years)], 'teams': len(teams), 'meanTeamAv': round(mav, 1), 'meanShare': round(msh, 2),
           'meanWins': round(mw, 2), 'winsPerAv': round(k, 4), 'r': round(r, 3), 'leaveOneSeasonOut': loso,
           'replWins': REPL_WINS, 'replAvFullSeason': round(R, 2), 'replTeamAv': round(R * msh, 1),
           'partTimeRate': {g: round(v, 2) for g, v in rate.items()}, 'replByPos': {g: round(c * v, 2) for g, v in rate.items()},
           'used': {'warPerAv': used[0], 'replAv': used[1], 'meanTeamWar': round(mean(war), 2),
                    'teamWarVsWinsSlope': round(sum((w - mean(war)) * (t['w'] - mw) for w, t in zip(war, teams)) / sum((w - mean(war)) ** 2 for w in war), 3)},
           'shareByAv': {a: round(mean(v), 3) for a, v in sorted(bins.items())}}
    out['market'] = market(players, k)
    with open(CALIB, 'w') as f:
        json.dump(out, f, indent=1)
        f.write('\n')
    print(json.dumps(out, indent=1))


def market(players, k):
    """WAR against what teams pay: veteran contracts (3+ years after the draft) signed after a season, the player's
    rank by WAR that season against his rank by cap %, one replacement line for all against NFL_REPL."""
    import gzip, io, re
    # one name can be two players (Josh Johnson the QB and the CB): seasons kept apart by position group, and a
    # contract goes to the one whose position fits it
    by, grps = {}, defaultdict(set)
    for av, sh, g, y, n in players:
        a = by.setdefault((NM.key(n), y, g), [0.0, 0.0, Counter()]); a[0] += av; a[1] += sh; a[2][g] += sh
        grps[(NM.key(n), y)].add(g)
    raw = urllib.request.urlopen(urllib.request.Request(CONTRACTS, headers={'User-Agent': 'arkboard'}), timeout=120).read()
    rowsm = []
    for c in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)), 'utf-8')):
        try:
            ys, cap = int(c['year_signed']), float(c['apy_cap_pct'])
        except ValueError:
            continue
        dy = c['draft_year']
        if dy not in ('', 'NA') and ys - int(dy) < 3:
            continue
        k = (NM.key(c['player']), ys - 1)
        fit = [by[k + (g,)] for g in grps.get(k, ()) if NM.pos_fits(c['position'], g)]
        a = [sum(x[0] for x in fit), sum(x[1] for x in fit), sum((x[2] for x in fit), Counter())] if fit else None
        if a and a[1] >= 0.3:
            rowsm.append((a, cap))
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        for j, i in enumerate(o):
            r[i] = j / len(v)
        return r
    rc = rank([c for _, c in rowsm])
    res = {'contracts': len(rowsm)}
    for name, repl in (('oneLine', lambda a: NFL_REPL_AV * a[1]), ('byPosition', lambda a: sum(NFL_REPL[g] * s for g, s in a[2].items()))):
        rw = rank([(a[0] - repl(a)) * k for a, _ in rowsm])
        mr = sum(rw) / len(rw); mc = sum(rc) / len(rc)
        rho = sum((x - mr) * (y - mc) for x, y in zip(rw, rc)) / math.sqrt(sum((x - mr) ** 2 for x in rw) * sum((y - mc) ** 2 for y in rc))
        bias = defaultdict(list)
        for i, (a, _) in enumerate(rowsm):
            bias[a[2].most_common(1)[0][0]].append(rw[i] - rc[i])
        b = {g: round(sum(v) / len(v), 3) for g, v in sorted(bias.items())}
        res[name] = {'rankCorr': round(rho, 3), 'posBias': b, 'meanAbsBias': round(sum(abs(v) for v in b.values()) / len(b), 3)}
    return res


# ---------------------------------------------------------------- lines by sub-position
def positions(years=range(2016, 2026), cal=range(2021, 2026)):
    """The replacement line for each sub-position (data/nfl_war_pos.json). AV sets the spread inside a sub-position; how
    much an average regular there is worth over replacement blends three measures of the same thing, each weighted by
    its precision:
      missed   points a game a team loses when an average regular sits (a regular: 6+ games, 60%+ of his side's snaps
               when he plays; absent = no snaps in a team game after his first, unless he had moved to another team):
               game margin (capped 35) on team-season ratings + home field + each side's absent regulars by sub-position
               and their AV a game, least squares with a light ridge, 2016-25
      market   veteran contracts (signed 3+ years after the draft, OTC via nflverse) of regulars, mean cap % less the
               minimum, sampling SE plus 25% for what the market misprices (rookie deals, the QB ceiling)
      model    what AV over the sub-position's own part-timers (5-35% of snaps, scaled to the replacement team) already
               gives an average regular, with a 40% prior SD
    Each comes as a share of a 22-man lineup's value; the blend is scaled so a team of replacements wins REPL_WINS of 17
    over the `cal` seasons (team WAR = wins - REPL_WINS), which sets each line: R = regulars' AV a full season - value / k.
    Checked on the 2021-25 missed games with the blend fit on 2016-20 inputs, and on contracts and team wins."""
    import numpy as np
    import gzip, io, re
    with open(FIT) as f:
        b = json.load(f)['coef']
    k = NWAR_PER_AV
    allg = list(rows(get('games.csv', GAMES)))
    W = Counter()
    for g in allg:
        if g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA'):
            hs, as_ = float(g['home_score']), float(g['away_score'])
            for t, d in ((g['home_team'], hs - as_), (g['away_team'], as_ - hs)):
                W[(int(g['season']), t)] += 1 if d > 0 else 0.5 if d == 0 else 0
    regs, team_tot, games_by = [], [], {}
    part = defaultdict(lambda: [0.0, 0.0])
    for y in years:
        sd = season_data(y)
        ros, by_name = rosters(y)
        for (pfr, t), s_ in sd['snaps'].items():
            if pfr not in ros and (s_['name'].lower(), t) in by_name:
                ros[pfr] = by_name[(s_['name'].lower(), t)]
        TR = team_rows(sd, b, ros)
        for o in TR:
            if 0.05 <= o['share'] < 0.35:
                part[o['sub']][0] += o['av']; part[o['sub']][1] += o['share']
        if y in cal:
            T = defaultdict(lambda: {'av': 0.0, 'sh': Counter()})
            for o in TR:
                T[o['t']]['av'] += o['av']; T[o['t']]['sh'][o['sub']] += o['share']
            team_tot += [{'y': y, 't': t, 'av': v['av'], 'sh': v['sh'], 'w': W[(y, t)] * 17 / sd['team'][t]['g']} for t, v in T.items()]
        gl = sorted([g for g in allg if g['season'] == str(y) and g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')],
                    key=lambda g: (int(g['week']), g['game_id']))
        snap, gmax = defaultdict(dict), defaultdict(lambda: [0.0, 0.0])
        for r in rows(get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv')):
            if r['game_type'] == 'REG':
                o, d = num(r['offense_snaps']), num(r['defense_snaps'])
                snap[(r['game_id'], r['team'])][r['pfr_player_id']] = (o, d)
                m = gmax[(r['game_id'], r['team'])]; m[0] = max(m[0], o); m[1] = max(m[1], d)
        tg = defaultdict(list)
        for g in gl:
            for t in (g['home_team'], g['away_team']):
                tg[t].append(g['game_id'])
        last = {}
        for t, ids in tg.items():
            for i, gid in enumerate(ids):
                for pid in snap.get((gid, t), {}):
                    last[pid] = max(last.get(pid, ('', '')), (gid[5:7] + gid, t))
        for o in TR:
            t, side = o['t'], 0 if o['g'] in OFFENSE else 1
            ids = tg.get(t, [])
            played = [i for i, gid in enumerate(ids) if snap.get((gid, t), {}).get(o['pfr'], (0, 0))[side] > 0]
            if len(played) < 6:
                continue
            sh = [snap[(ids[i], t)][o['pfr']][side] / max(1, gmax[(ids[i], t)][side]) for i in played]
            if sum(sh) / len(sh) < 0.6:
                continue
            end = len(ids) if last.get(o['pfr'], ('', t))[1] == t else played[-1] + 1
            regs.append({**{k_: o[k_] for k_ in ('pfr', 't', 'sub', 'av', 'share', 'name')}, 'y': y, 'g': len(played), 'gshare': sum(sh) / len(sh),
                         'start': played[0], 'end': end, 'played': set(played)})
        games_by[y] = (gl, tg)

    def missed(ys):
        R = [r for r in regs if r['y'] in ys]
        mu = {s_: float(np.mean([r['av'] / r['g'] for r in R if r['sub'] == s_])) for s_ in SUBS}
        by = defaultdict(list)
        for r in R:
            by[(r['y'], r['t'])].append(r)
        fe, eqs, seen = {}, [], Counter()
        for y in ys:
            gl, tg = games_by[y]
            for g in gl:
                h, a_ = g['home_team'], g['away_team']
                x = np.zeros(2 * len(SUBS))
                for t, sgn in ((h, 1), (a_, -1)):
                    gi = tg[t].index(g['game_id'])
                    for r in by.get((y, t), []):
                        if r['start'] <= gi < r['end'] and gi not in r['played']:
                            j = SUBS.index(r['sub']); x[j] += sgn; x[len(SUBS) + j] += sgn * (r['av'] / r['g'] - mu[r['sub']]); seen[r['sub']] += 1
                eqs.append((fe.setdefault((y, h), len(fe)), fe.setdefault((y, a_), len(fe)), 0 if g.get('location') == 'Neutral' else 1, x,
                            max(-35.0, min(35.0, float(g['home_score']) - float(g['away_score'])))))
        nf, ne = len(fe), 2 * len(SUBS)
        A = np.zeros((len(eqs), nf + 1 + ne)); Y = np.zeros(len(eqs))
        for i, (h, a_, hfa, x, m) in enumerate(eqs):
            A[i, h] = 1; A[i, a_] = -1; A[i, nf] = hfa; A[i, nf + 1:] = x; Y[i] = m
        reg = np.zeros(nf + 1 + ne); reg[:nf] = 2; reg[nf + 1:] = 0.5
        M = A.T @ A + np.diag(reg)
        c = np.linalg.solve(M, A.T @ Y); res = Y - A @ c
        cov = (res @ res / (len(Y) - A.shape[1])) * np.linalg.inv(M)
        return {s_: {'absences': seen[s_], 'drop': round(float(-c[nf + 1 + j]), 2), 'se': round(float(math.sqrt(cov[nf + 1 + j, nf + 1 + j])), 2),
                     'perAvGame': round(float(-c[nf + 1 + len(SUBS) + j]), 2), 'perAvGameSe': round(float(math.sqrt(cov[nf + 1 + len(SUBS) + j, nf + 1 + len(SUBS) + j])), 2)}
                for j, s_ in enumerate(SUBS)} | {'_': {'games': len(eqs), 'homeField': round(float(c[nf]), 2)}}

    # market: veteran contracts in force for regulars
    norm = NM.key
    raw = gzip.open(get('historical_contracts.csv.gz', CONTRACTS)).read().decode('utf-8')
    con = defaultdict(list)
    for c_ in csv.DictReader(io.StringIO(raw)):
        try:
            con[norm(c_['player'])].append((int(c_['year_signed']), int(c_['years']), float(c_['apy_cap_pct']), int(c_['draft_year']) if c_['draft_year'] not in ('', 'NA') else None, c_['position']))
        except ValueError:
            pass
    caps = defaultdict(list)
    for r in regs:
        cs = [c_[:4] for c_ in con.get(norm(r['name']), []) if c_[0] <= r['y'] < c_[0] + max(1, c_[1]) and NM.pos_fits(c_[4], r['sub'])]
        if cs:
            c_ = max(cs)
            if c_[3] is not None and c_[0] - c_[3] >= 3:
                caps[r['sub']].append(c_[2] * 100)

    def market_val(s_):
        v = caps[s_]; m = float(np.mean(v)) - 0.5
        return m, math.sqrt(float(np.var(v)) / len(v) + (0.25 * m) ** 2), len(v)

    # model: an average regular's points a game now (AV a game over the group line), in points (35.5 a win)
    # over the sub-position's own part-timers (5-35% of the snaps): their AV a full season, scaled together to the
    # replacement team (as --calibrate scales the group lines); the group's line mixed EDGE with DT and slot with outside
    PTS_PER_WIN = 35.5
    mav0 = float(np.mean([t['av'] for t in team_tot])); mw0 = float(np.mean([t['w'] for t in team_tot]))
    msh0 = {s_: float(np.mean([t['sh'][s_] for t in team_tot])) for s_ in SUBS}
    # outside WRs and CBs are the team's top two by snaps, so their part-timers are the group's (slot, nickel)
    grp = defaultdict(lambda: [0.0, 0.0])
    for s_, v in part.items():
        grp[SUB_GROUP[s_]][0] += v[0]; grp[SUB_GROUP[s_]][1] += v[1]
    prate = {s_: part[s_][0] / part[s_][1] if part[s_][1] >= 5 else grp[SUB_GROUP[s_]][0] / grp[SUB_GROUP[s_]][1] for s_ in SUBS}
    pc = (mav0 - (mw0 - REPL_WINS) / k) / sum(prate[s_] * msh0[s_] for s_ in SUBS)
    partline = {s_: pc * prate[s_] for s_ in SUBS}
    model = {s_: PTS_PER_WIN * k * float(np.mean([r['av'] / r['g'] - partline[s_] / 17 * r['gshare'] for r in regs if r['sub'] == s_])) for s_ in SUBS}

    def shares(est):
        # {sub: (value per slot, se)} -> {sub: (share of the lineup, se of the share)}
        tot = sum(SLOTS[s_] * max(0.0, est[s_][0]) for s_ in SUBS)
        return {s_: (SLOTS[s_] * est[s_][0] / tot, SLOTS[s_] * est[s_][1] / tot) for s_ in SUBS}

    def blend(mis):
        src = {'missed': shares({s_: (mis[s_]['drop'], mis[s_]['se']) for s_ in SUBS}),
               'market': shares({s_: market_val(s_)[:2] for s_ in SUBS}),
               'model': shares({s_: (model[s_], 0.4 * model[s_]) for s_ in SUBS})}
        out = {}
        for s_ in SUBS:
            w = {n_: 1 / max(1e-6, src[n_][s_][1]) ** 2 for n_ in src}
            out[s_] = sum(w[n_] * src[n_][s_][0] for n_ in src) / sum(w.values())
            out[s_] = max(0.0, out[s_])
        z = sum(out.values())
        return {s_: v / z for s_, v in out.items()}, src, {s_: {n_: round((1 / max(1e-6, src[n_][s_][1]) ** 2) / sum(1 / max(1e-6, src[m_][s_][1]) ** 2 for m_ in src), 2) for n_ in src} for s_ in SUBS}

    mis_all = missed(list(years))
    share, src, wts = blend(mis_all)
    # hold-out: blend on 2016-20 inputs, against 2021-25 missed games (share of the lineup by sub-position)
    early, late = missed([y for y in years if y <= 2020]), missed([y for y in years if y >= 2021])
    sh_e, src_e, _ = blend(early)
    late_sh = shares({s_: (late[s_]['drop'], late[s_]['se']) for s_ in SUBS})
    def wcorr(a_):
        xs = [a_[s_] for s_ in SUBS]; ys = [late_sh[s_][0] for s_ in SUBS]; ws = [1 / late_sh[s_][1] ** 2 for s_ in SUBS]
        mx = sum(w * x for w, x in zip(ws, xs)) / sum(ws); my = sum(w * y for w, y in zip(ws, ys)) / sum(ws)
        cxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys)); cxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs)); cyy = sum(w * (y - my) ** 2 for w, y in zip(ws, ys))
        return round(cxy / math.sqrt(cxx * cyy), 3)
    def werr(a_):
        return round(math.sqrt(sum((a_[s_] - late_sh[s_][0]) ** 2 / late_sh[s_][1] ** 2 for s_ in SUBS) / len(SUBS)), 2)
    holdout = {n_: {'r': wcorr(v), 'zRmse': werr(v)} for n_, v in (('blend', sh_e), ('model', {s_: src_e['model'][s_][0] for s_ in SUBS}),
                                                                  ('market', {s_: src_e['market'][s_][0] for s_ in SUBS}), ('missed2016_20', {s_: src_e['missed'][s_][0] for s_ in SUBS}))}

    # anchor: lines so team WAR sums to wins - REPL_WINS over the cal seasons
    avbar = {}
    for s_ in SUBS:
        R = [r for r in regs if r['sub'] == s_ and r['y'] in cal]
        avbar[s_] = sum(r['av'] for r in R) / sum(r['share'] for r in R)
    mav = float(np.mean([t['av'] for t in team_tot])); mw = float(np.mean([t['w'] for t in team_tot]))
    msh = {s_: float(np.mean([t['sh'][s_] for t in team_tot])) for s_ in SUBS}
    u = {s_: share[s_] / SLOTS[s_] for s_ in SUBS}
    Tw = (mw - REPL_WINS - k * (mav - sum(msh[s_] * avbar[s_] for s_ in SUBS))) / sum(msh[s_] * u[s_] for s_ in SUBS)
    value = {s_: round(Tw * u[s_], 3) for s_ in SUBS}
    line = {s_: round(avbar[s_] - value[s_] / k, 2) for s_ in SUBS}
    # checks: team WAR on wins, old and new lines
    def teamwar(t, ln):
        return k * (t['av'] - sum(t['sh'][s_] * ln[s_] for s_ in SUBS))
    old = {s_: NFL_REPL[SUB_GROUP[s_]] for s_ in SUBS}
    def tw_check(ln):
        x = [teamwar(t, ln) for t in team_tot]; y = [t['w'] for t in team_tot]
        return {'meanTeamWar': round(float(np.mean(x)), 2), 'r': round(float(np.corrcoef(x, y)[0, 1]), 3)}
    # market check: rank by WAR against rank by cap % of the next veteran contract (signed after the season), regulars and part-timers with 30%+ snaps
    mk = {}
    pl, pl_all = [], []
    for y in years:
        if y > 2024:
            continue
        sd = season_data(y); ros, by_name = rosters(y)
        for (pfr, t), s_ in sd['snaps'].items():
            if pfr not in ros and (s_['name'].lower(), t) in by_name:
                ros[pfr] = by_name[(s_['name'].lower(), t)]
        for o in team_rows(sd, b, ros):
            if o['share'] >= 0.3:
                cs = [c_[:4] for c_ in con.get(norm(o['name']), []) if c_[0] == y + 1 and c_[3] is not None and c_[0] - c_[3] >= 3 and NM.pos_fits(c_[4], o['sub'])]
                if cs:
                    pl_all.append((o, max(cs)[2] * 100))
                    if y <= 2021:
                        pl.append((o, max(cs)[2]))

    # spread on defense: the defensive credits' scale is a team-level fit (points allowed on the credits), not PFR's.
    # Two checks on it, each as a ratio to what WAR assumes: what teams pay a WAR at the spot (cap % of the next
    # veteran deal on the season's WAR, divided by the year-to-year r of WAR a snap so noise doesn't flatten it) against
    # offense (QB aside), and the points a team loses when a regular sits per AV a game above the spot's average
    # (missed games) against the 3.2 WAR assumes. Blended with no change (1, SD .5) by precision. The market check
    # below (subLinesSpread) tests it
    def ols(x, y_):
        x, y_ = np.array(x), np.array(y_); xm = x - x.mean(); sl = float(xm @ (y_ - y_.mean()) / (xm @ xm))
        res = y_ - y_.mean() - sl * xm
        return sl, float(math.sqrt(res @ res / (len(x) - 2) / (xm @ xm)))
    rel, slope = {}, {}
    seas = defaultdict(dict)
    for r in regs:
        if r['share'] >= 0.5:
            seas[r['pfr']][r['y']] = (r['sub'], k * (r['av'] - line[r['sub']] * r['share']) / r['share'])
    for s_ in SUBS:
        prs = [(v[y][1], v[y + 1][1]) for v in seas.values() for y in v if y + 1 in v and v[y][0] == s_ and v[y + 1][0] == s_]
        rel[s_] = max(0.2, float(np.corrcoef([a_ for a_, _ in prs], [b_ for _, b_ in prs])[0, 1])) if len(prs) > 20 else None
        L = [(k * (o['av'] - line[o['sub']] * o['share']), c_) for o, c_ in pl_all if o['sub'] == s_]
        if len(L) > 20 and rel[s_]:
            sl, se = ols([x for x, _ in L], [c_ for _, c_ in L])
            slope[s_] = (sl / rel[s_], se / rel[s_], len(L))
    offs = [s_ for s_ in slope if SUB_GROUP[s_] in OFFENSE and s_ != 'QB']
    ref = sum(slope[s_][0] / slope[s_][1] ** 2 for s_ in offs) / sum(1 / slope[s_][1] ** 2 for s_ in offs)
    ptsav = PTS_PER_WIN * k
    spread, sp_src = {}, {}
    for s_ in SUBS:
        if SUB_GROUP[s_] in OFFENSE:
            continue
        src_ = {'prior': (1.0, 0.5)}
        if s_ in slope:
            src_['market'] = (slope[s_][0] / ref, slope[s_][1] / ref)
        src_['missed'] = (mis_all[s_]['perAvGame'] / ptsav, mis_all[s_]['perAvGameSe'] / ptsav)
        w_ = {n_: 1 / v[1] ** 2 for n_, v in src_.items()}
        spread[s_] = round(min(2.5, max(0.5, sum(w_[n_] * v[0] for n_, v in src_.items()) / sum(w_.values()))), 2)
        sp_src[s_] = {n_: [round(v[0], 2), round(v[1], 2)] for n_, v in src_.items()}

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i]); r_ = [0.0] * len(v)
        for j, i in enumerate(order):
            r_[i] = j / len(v)
        return r_
    rc = rank([c_ for _, c_ in pl])
    for name_, ln, sp_ in (('groupLines', old, None), ('subLines', line, None), ('subLinesSpread', line, spread)):
        rw = rank([war_of(o['av'], o['share'], o['sub'], ln, value, sp_) for o, _ in pl])
        rho = float(np.corrcoef(rw, rc)[0, 1])
        bias = defaultdict(list)
        for i, (o, _) in enumerate(pl):
            bias[o['sub']].append(rw[i] - rc[i])
        bb = {s_: round(float(np.mean(v)), 3) for s_, v in bias.items()}
        mk[name_] = {'rankCorr': round(rho, 3), 'posBias': bb, 'meanAbsBias': round(float(np.mean([abs(v) for v in bb.values()])), 3)}
    mk['contracts'] = len(pl)
    out = {'asof': __import__('datetime').date.today().isoformat(), 'years': [min(years), max(years)], 'cal': [min(cal), max(cal)], 'warPerAv': k, 'replWins': REPL_WINS,
           **fv_curves(b, line, k),
           # tested and not applied: widening defense by these factors lowers the rank r with contracts (.47 to .44) and
           # puts EDGE further under its pay (posBias -.03 to -.11); to apply, write the m dict as 'spread'
           'spreadCheck': {'m': spread, 'sources': sp_src, 'marketRef': round(ref, 2), 'warRel': {s_: None if v is None else round(v, 2) for s_, v in rel.items()},
                      'marketSlope': {s_: [round(v[0], 1), round(v[1], 1), v[2]] for s_, v in slope.items()}},
           'slots': SLOTS, 'line': line, 'value': value, 'regularAv': {s_: round(v, 2) for s_, v in avbar.items()}, 'groupLine': old,
           'share': {s_: round(v, 4) for s_, v in share.items()}, 'weights': wts,
           'sources': {n_: {s_: [round(v[s_][0], 4), round(v[s_][1], 4)] for s_ in SUBS} for n_, v in src.items()},
           'missed': mis_all, 'market': {s_: {'capPctOverMin': round(market_val(s_)[0], 2), 'n': market_val(s_)[2]} for s_ in SUBS},
           'modelPtsGame': {s_: round(v, 2) for s_, v in model.items()}, 'partTimeLine': {s_: round(v, 2) for s_, v in partline.items()}, 'holdout': holdout,
           'teams': {'groupLines': tw_check(old), 'subLines': tw_check(line), 'meanWins': round(mw, 2)}, 'marketCheck': mk}
    with open(POSFIT, 'w') as f:
        json.dump(out, f, indent=1)
        f.write('\n')
    print(json.dumps({k_: out[k_] for k_ in ('line', 'value', 'share', 'weights', 'holdout', 'teams', 'marketCheck')}, indent=1))



def fv_curves(b, line, k, value=None, spread=None):
    """WAR by FV on these lines. careerCurve: drafted players (2016-21 classes, seasons through 2025), their mean AV a
    season active (the FV scale's AV_BY_FV unit) against their mean WAR a season active, binned: the expected WAR at an
    FV, busts and backup years in. seasonPct: WAR of regulars' seasons (half or more of the snaps, 2021-25) at the top
    1, 2, 4, 8, 14, 25, 50 and 75%: what a season at an outcome tier is worth (All-Pro about the top 4%)."""
    picks = {r['pfr_player_id'] for r in rows(get('draft_picks.csv', f'{REL}/draft_picks/draft_picks.csv'))
             if r['pfr_player_id'] and 2016 <= int(r['season']) <= 2021}
    car = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
    seas = []
    for y in range(2016, 2026):
        sd = season_data(y)
        ros, by_name = rosters(y)
        for (pfr, t), s_ in sd['snaps'].items():
            if pfr not in ros and (s_['name'].lower(), t) in by_name:
                ros[pfr] = by_name[(s_['name'].lower(), t)]
        agg = defaultdict(lambda: [0.0, 0.0])
        for o in team_rows(sd, b, ros):
            w = war_of(o['av'], o['share'], o['sub'], line, value, spread)
            if o['pfr'] in picks:
                c = car[o['pfr']][y]; c[0] += o['av']; c[1] += w; c[2] += o['share']
            a = agg[o['pfr']]; a[0] += w; a[1] += o['share']
        if y >= 2021:
            seas += [w for w, sh in agg.values() if sh >= 0.5]
    pl = []
    for pid in picks:
        act = [v for v in car.get(pid, {}).values() if v[2] > 0]
        pl.append((sum(v[0] for v in act) / len(act), sum(v[1] for v in act) / len(act)) if act else (0.0, 0.0))
    curve = []
    for lo, hi in ((0, 0.5), (0.5, 1.25), (1.25, 2.25), (2.25, 3.25), (3.25, 4.25), (4.25, 5.5), (5.5, 7), (7, 9), (9, 99)):
        r = [x for x in pl if lo <= x[0] < hi]
        if r:
            curve.append([round(sum(x[0] for x in r) / len(r), 2), round(sum(x[1] for x in r) / len(r), 3), len(r)])
    seas.sort(reverse=True)
    pct = {str(q): round(seas[int(len(seas) * q / 100)], 2) for q in (1, 2, 4, 8, 14, 25, 50, 75)}
    return {'careerCurve': curve, 'seasonPct': pct, 'regularSeasons': len(seas)}



def defense(years=range(2018, 2026)):
    """The defensive split (data/nfl_war_def.json): each event's EPA from play-by-play and NGS pressure flags, the league's
    sacks a pressure and how much of a player's conversion repeats, and c (AV a point of EPA credit) from team seasons,
    the pool on the credits, leave one season out. Tests against PFR AV's split: year-to-year r of AV a snap (300+ snaps
    both seasons), rank r with the next veteran contract (30%+ snaps), and the team fit with actual sacks in place of
    expected ones."""
    import numpy as np
    import gzip, io, re
    TK = ['solo_tackle_1_player_id', 'solo_tackle_2_player_id', 'assist_tackle_1_player_id', 'assist_tackle_2_player_id',
          'assist_tackle_3_player_id', 'assist_tackle_4_player_id', 'tackle_with_assist_1_player_id', 'tackle_with_assist_2_player_id']
    acc = defaultdict(lambda: [0.0, 0])
    def add(k_, v):
        a = acc[k_]; a[0] += v; a[1] += 1
    for y in years:
        pr = {(r['nflverse_game_id'], r['play_id']): r['was_pressure'] == 'TRUE'
              for r in rows(get(f'pbp_participation_{y}.csv', f'{REL}/pbp_participation/pbp_participation_{y}.csv')) if r['was_pressure'] in ('TRUE', 'FALSE')}
        with gzip.open(get(f'play_by_play_{y}.csv.gz', f'{REL}/pbp/play_by_play_{y}.csv.gz'), 'rt', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['season_type'] != 'REG' or r['play_type'] not in ('run', 'pass') or r['epa'] in ('', 'NA'):
                    continue
                e, ntk = float(r['epa']), sum(r[c] not in ('', 'NA') for c in TK)
                if r['play_type'] == 'run':
                    add('run', e)
                    if r['success'] != '1' and ntk:
                        add('runStop', e); add('runStopTacklers', ntk)
                    if r['tackled_for_loss'] == '1':
                        add('runTfl', e)
                elif r['qb_dropback'] == '1':
                    add('dropback', e)
                    p_ = pr.get((r['game_id'], r['play_id']))
                    if r['sack'] == '1':
                        add('sack', e)
                    elif p_ is not None:
                        add('pressure' if p_ else 'clean', e)
                    if r['complete_pass'] == '1' and r['success'] != '1' and ntk:
                        add('passStop', e); add('passStopTacklers', ntk)
                    if r['interception'] == '1':
                        add('int', e)
                    elif r['pass_defense_1_player_id'] not in ('', 'NA'):
                        add('pd', e)
                if r['fumble_forced'] == '1':
                    add('ff', e)
    m = {k_: v[0] / v[1] for k_, v in acc.items()}
    db, run = m['dropback'], m['run']
    # each event's EPA against what the play would have been without it: a sack or pressure against a clean dropback,
    # the rest against the average play of its kind; a stop split among its tacklers; a run TFL over a stop
    V = {'sack': m['clean'] - m['sack'], 'press': m['clean'] - m['pressure'], 'stopR': (run - m['runStop']) / m['runStopTacklers'],
         'stopP': (db - m['passStop']) / m['passStopTacklers'], 'tfl': m['runStop'] - m['runTfl'], 'int': db - m['int'],
         'pd': db - m['pd'], 'ff': -m['ff']}
    V = {k_: round(v, 3) for k_, v in V.items()}
    # sacks a pressure, and how much of a player's conversion above it repeats (15+ pressures both seasons)
    sea = defaultdict(lambda: [0.0, 0.0])
    for y in years:
        for (pfr, t), a in def_adv(y).items():
            sea[(pfr, y)][0] += a['prss']; sea[(pfr, y)][1] += a['sk']
    conv = sum(v[1] for v in sea.values()) / sum(v[0] for v in sea.values())
    pairs = [(v, sea[(pfr, y + 1)]) for (pfr, y), v in sea.items() if v[0] >= 15 and sea.get((pfr, y + 1), [0])[0] >= 15]
    xr = [(a[1] - conv * a[0]) / a[0] for a, _ in pairs]; zr = [(b_[1] - conv * b_[0]) / b_[0] for _, b_ in pairs]
    rel = max(0.0, float(np.corrcoef(xr, zr)[0, 1]))
    # c: the pool on each team's credits (a 17-game season), leave one season out; and with actual sacks
    W = {}
    def team_fit(D):
        _DEF[:] = [D]
        X, Y, ys = [], [], []
        for y in years:
            sd = season_data(y)
            W[y] = sd
            for t, tm in sd['team'].items():
                if t in sd['dcredit']:
                    X.append(sd['dcredit'][t] * 17 / tm['g']); Y.append(tm['def']); ys.append(y)
        X, Y = np.array(X), np.array(Y)
        sse = sst = 0.0
        for y in years:
            tr = np.array([v != y for v in ys])
            cf = np.polyfit(X[tr], Y[tr], 1)
            sse += float(((Y[~tr] - np.polyval(cf, X[~tr])) ** 2).sum()); sst += float(((Y[~tr] - Y[tr].mean()) ** 2).sum())
        return float(np.polyfit(X, Y, 1)[0]), round(1 - sse / sst, 3), round(float(np.corrcoef(X, Y)[0, 1]), 3)
    c_act, r2_act, r_act = team_fit({'values': V, 'conv': conv, 'convRel': 1.0, 'c': 0.0})
    c, r2, r_ = team_fit({'values': V, 'conv': conv, 'convRel': rel, 'c': 0.0})
    D = {'values': V, 'conv': round(conv, 4), 'convRel': round(rel, 3), 'c': round(c, 4)}
    _DEF[:] = [D]
    # tests: AV a snap year to year, and against the next veteran contract, by board position
    with open(FIT) as f:
        b = json.load(f)['coef']
    norm = NM.key
    con = defaultdict(list)
    for c_ in csv.DictReader(io.StringIO(gzip.open(get('historical_contracts.csv.gz', CONTRACTS)).read().decode('utf-8'))):
        try:
            con[norm(c_['player'])].append((int(c_['year_signed']), float(c_['apy_cap_pct']), int(c_['draft_year']) if c_['draft_year'] not in ('', 'NA') else None, c_['position']))
        except ValueError:
            pass
    GRP = {'EDGE': 'EDGE', 'DT': 'DT', 'LB': 'LB', 'CB': 'DB', 'NCB': 'DB', 'S': 'DB'}
    P = {}
    for y in years:
        sd = season_data(y); W[y] = sd
        ros, by_name = rosters(y)
        for (pfr, t), s_ in sd['snaps'].items():
            if pfr not in ros and (s_['name'].lower(), t) in by_name:
                ros[pfr] = by_name[(s_['name'].lower(), t)]
        for o in team_rows(sd, b, ros):
            if o['g'] in OFFENSE:
                continue
            gsis = ros.get(o['pfr'], {}).get('gsis_id', '')
            old = predict(None, o['g'], features(sd, o['pfr'], gsis, o['t'], o['g'], pfr_split=True))
            a = P.setdefault((o['pfr'], y), {'n': o['name'], 'snaps': 0.0, 'share': 0.0, 'old': 0.0, 'new': 0.0, 'sub': Counter()})
            a['snaps'] += o['snaps']; a['share'] += o['share']; a['old'] += old; a['new'] += o['av']; a['sub'][GRP[o['sub']]] += o['snaps']
    def spear(x, z):
        rx, rz = np.argsort(np.argsort(x)), np.argsort(np.argsort(z))
        return round(float(np.corrcoef(rx, rz)[0, 1]), 3)
    stab, mkt, level = {}, {}, {}
    for g in ('EDGE', 'DT', 'LB', 'DB'):
        pr_ = [(a, P[(pfr, y + 1)]) for (pfr, y), a in P.items() if a['sub'].most_common(1)[0][0] == g and a['snaps'] >= 300
               and P.get((pfr, y + 1), {}).get('snaps', 0) >= 300 and P[(pfr, y + 1)]['sub'].most_common(1)[0][0] == g]
        stab[g] = {'n': len(pr_), **{k_: round(float(np.corrcoef([a[k_] / a['snaps'] for a, _ in pr_], [z[k_] / z['snaps'] for _, z in pr_])[0, 1]), 3) for k_ in ('old', 'new')}}
        L = []
        for (pfr, y), a in P.items():
            if a['sub'].most_common(1)[0][0] == g and a['share'] >= 0.3:
                cs = [c_[:3] for c_ in con.get(norm(a['n']), []) if c_[0] == y + 1 and c_[2] is not None and c_[0] - c_[2] >= 3 and NM.pos_fits(c_[3], g)]
                if cs:
                    L.append((a, max(cs)[1]))
        mkt[g] = {'n': len(L), **{k_: spear([a[k_] for a, _ in L], [c_ for _, c_ in L]) for k_ in ('old', 'new')}}
        R = [a for a in P.values() if a['sub'].most_common(1)[0][0] == g and a['share'] >= 0.5]
        level[g] = {k_: round(sum(a[k_] for a in R) / sum(a['share'] for a in R), 2) for k_ in ('old', 'new')}
    out = {'asof': __import__('datetime').date.today().isoformat(), 'years': [min(years), max(years)], 'model': D,
           'epa': {k_: round(v, 3) for k_, v in m.items()}, 'convPairs': len(pairs),
           'team': {'expectedSacks': {'looR2': r2, 'r': r_}, 'actualSacks': {'looR2': r2_act, 'r': r_act, 'c': round(c_act, 4)}},
           'stability': stab, 'contracts': mkt, 'avFullSeason': level}
    with open(DEFFIT, 'w') as f:
        json.dump(out, f, indent=1)
        f.write('\n')
    with open(FIT) as f:
        fj = json.load(f)
    for g in ('DL', 'LB', 'DB'):
        fj['coef'][g] = {'snap': 1.0, 'prod': 1.0}
    fj['defense'] = 'DL, LB and DB split the defensive pool by EPA credits (data/nfl_war_def.json); their PFR-fit coefficients are PFR_DEF_COEF'
    with open(FIT, 'w') as f:
        json.dump(fj, f, indent=1)
    print(json.dumps({k_: out[k_] for k_ in ('model', 'team', 'stability', 'contracts', 'avFullSeason')}, indent=1))


if __name__ == '__main__':
    (calibrate() if '--calibrate' in sys.argv else fit() if '--fit' in sys.argv else positions() if '--positions' in sys.argv
     else defense() if '--defense' in sys.argv else build())
