#!/usr/bin/env python3
"""Style matchup ("rock paper scissors") terms in the game models (thread "Test style matchup drivers across sports",
Oct 29 2026). Research only. Results in data/style_research.json.

The question: does a team's style pay off more or less depending on the opponent's style, beyond what the two teams'
ratings already say? Each term is the product of one side's style and the other side's matching style, so it is zero
on average and carries no main effect (the close and the model already price each team's strength).

Pre-registered before any outcome was looked at (52 tests, one BH family). Style values are each team's season to
date before the game, shrunk to a prior (half last season's team value, half the league) worth n0 games, then z-scored
within the season. A is one side's style, B the other side's. Margin terms are antisymmetric,
x = A(home) B(away) - A(away) B(home); totals terms are symmetric, x = A(home) B(away) + A(away) B(home).
Sign: + means the clash adds to what the A side would get from adding the two parts, 0 means two-sided.
  NBA, CBB (box scores: NBA ESPN, scripts/.cache/style/nba_box_hist.json.gz; CBB Barttorvik getgamestats)
    3pt_vol    margin  3PA/FGA x the opponent's 3PA/FGA allowed                       +
    oreb       margin  offensive rebound % x the opponent's offensive rebound % allowed   +
    tov        margin  turnovers forced a possession x the opponent's turnovers a possession   +
    3pt_slow   margin  3P% x the opponent's slowness (minus possessions a game)        0   (Noah's example)
    3pt_vol_T  totals  3pt_vol, symmetric                                            0
    ftr_T      totals  FTA/FGA x the opponent's FTA/FGA allowed, symmetric              +
  NFL (nflverse stats_team), CFB (ESPN box scores; CFB has no sacks in the box)
    mix        margin  pass share of plays x the opponent's pass-vs-run weakness (NFL EPA a dropback allowed minus
                       EPA a carry allowed, z each; CFB yards an attempt minus yards a carry)      +
    sack       margin  (NFL) sack rate allowed x the opponent's sack rate                 + (for the pass rush side)
    mix_T      totals  mix, symmetric                                                 +
    3rd        margin  third-down conversion % x the opponent's third-down % allowed (ESPN box)   +
    3rd_T      totals  3rd, symmetric                                                 +
    rz         margin  (NFL) red-zone TD % x the opponent's red-zone TD % allowed (ESPN box)      +
    run_run    margin  rushing EPA a carry x the opponent's rushing EPA a carry allowed (CFB: yards)   +
    pass_pass  margin  EPA a dropback x the opponent's EPA a dropback allowed (CFB: yards an attempt)  +
    tilt       margin  offense tilt (pass minus run efficiency) x the opponent's defensive tilt (pass allowed
                       minus run allowed): a pass-first-good offense against a pass-soft defense      +
    run_run_T, pass_pass_T  totals  symmetric                                              +
  (3rd, 3rd_T and rz were added at Noah's ask after the first 24 were scored, and the five unit clashes after the
  first 29, each before its own outcome was seen.)
  Round two (Noah: "any more combo / battle drivers"), registered after round one failed, before its outcomes:
    ast_stl    NBA, CBB margin  assists a field goal made x the opponent's steals a possession: ball movement beats
                       a gambling defense                                               - (for the steal side: +)
    rim        NBA, CBB margin  blocks a 2PA allowed... the defense's blocks per opponent 2PA x the opponent's
                       2PA share (FGA minus 3PA over FGA): rim protection against an inside offense   + (defense side)
    ftr        NBA, CBB margin  FTA/FGA x the opponent's FTA/FGA allowed                     +
    to_bat     NFL, CFB margin  the defense's takeaways a play x the opponent's giveaways a play     + (defense side)
    air        NFL margin  air yards an attempt x the opponent's air yards allowed an attempt      +
    ev5        NHL margin  5v5 xG for a game x the opponent's 5v5 xG against a game            +
    goals      soccer margin  goals a game x the opponent's goals allowed a game              +
    goals_T    soccer totals  goals, symmetric                                           +
    lefty      tennis win  left-hander vs right-hander (x = lefty(A) - lefty(B))             0
  The family is all 52 tests.
  NHL (MoneyPuck by game, scripts/nhl_games_hist.json.gz)
    pp_disc    margin  power-play xG a 60 x the opponent's penalty minutes taken a game     +
    pk_draw    margin  power-play time drawn a game x the opponent's penalty-kill xG allowed a 60   +
    pp_disc_T  totals  pp_disc, symmetric                                              +
  soccer (shots on target, scripts/soccer_games_hist.json.gz)
    sot        margin  shots on target a game x the opponent's shots on target allowed       +
    sot_T      totals  sot, symmetric (over 2.5 against the close's devigged over price)       +
  tennis (minmaxxxer 2025-26 match stats and closes; style by player over all prior matches, n0 10 matches)
    srv_ret    win     serve points won x the opponent's return points won (big server vs elite returner)  0
    ace_ret    win     ace rate x the opponent's return points won                         0
Outcomes: spread sports result - close (and - model), totals total - close total; NHL home win - close prob and goals -
close total; soccer (home win - away win) - (cH - cA), over 2.5 - devigged close; tennis win - close prob (side by
match id parity). Tune / held: NBA 2015-21 / 2022-26; CBB 2016-21 / 2022-26; NFL 2015-21 / 2022-26; CFB 2017-22 /
2023-26; NHL 2020-22 / 2023-26 (closes from 2020); soccer margin 2013-20 / 2021-26, totals 2020-22 / 2023-26; tennis
2025 / 2026. Regular season and playoffs alike. Errors clustered by game day.
Pass: tune t >= 1.5 in the expected direction (two-sided: |t| >= 1.5, and the held-out b the same sign) AND held-out
squared error of close + b x (b from tune) below the close at paired t <= -1.5, AND BH q <= .10 over the family
(Stouffer z of tune and held t, signed by the tune direction for two-sided terms).

Result (Oct 29 2026): none of the 52 passes; the lowest q is .87. Nothing ships; no model, ranking or picks change.
Closest, each on one split only (re-score after 2026-27 on the same definitions): soccer goals battle runs the wrong
way (held b -.012 t -2.3, tune t -0.5: the close already overrates attack x leaky defence), NBA oreb / 3pt_vol / tov
(both splits +, t 1.0-2.1, no held-out error gain), CBB 3pt_vol_T (t 1.3 both), NHL pp_disc_T (t 1.1 / 1.5).
Noah's 3P% vs slow pace example: NBA t 0.9 / 0.3, CBB -0.1 / -0.8.

    python3 scripts/style_research.py            # every sport -> data/style_research.json
Data pulls (cached in scripts/.cache/style/): Barttorvik getgamestats.php?year=Y&csv=1 (CBB), nflverse
stats_team_week_Y.csv (NFL), ESPN summary boxscores for the games_wf CFB ids (cfb_box.json), and the NBA box file
from the project files (team-models/nba_box_hist.json.gz).
"""
import ast
import collections
import csv
import datetime
import gzip
import json
import math
import os
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

C = os.path.join(HERE, '.cache', 'style')
WF = os.path.join(HERE, 'data', 'games_wf', '{}.json.gz')
OUT = os.path.join(ROOT, 'data', 'style_research.json')
SIGN = {'ast_stl': -1, 'rim': 1, 'ftr': 1, 'to_bat': 1, 'air': 1, 'ev5': 1, 'goals': 1, 'goals_T': 1, 'lefty': 0, 'run_run': 1, 'pass_pass': 1, 'tilt': 1, 'run_run_T': 1, 'pass_pass_T': 1, '3rd': 1, '3rd_T': 1, 'rz': 1, '3pt_vol': 1, 'oreb': 1, 'tov': 1, '3pt_slow': 0, '3pt_vol_T': 0, 'ftr_T': 1, 'mix': 1, 'sack': 1, 'mix_T': 1,
        'pp_disc': 1, 'pk_draw': 1, 'pp_disc_T': 1, 'sot': 1, 'sot_T': 1, 'srv_ret': 0, 'ace_ret': 0}


def when(s):
    s = s.replace('Z', '')
    return datetime.datetime.fromisoformat(s[:16] if 'T' in s else s[:10] + 'T12:00')


# ---------------------------------------------------------------- rolling style values
class Roll:
    """each team's season-to-date rate of every stat (sum of num / sum of den), before a game, shrunk to a prior worth
    n0 games: half the team's last-season rate, half the league's (last season's, else this season's so far)"""

    def __init__(self, n0):
        self.n0 = n0
        self.cur = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, 0]))   # (S, team) -> stat -> [num, den, n]
        self.lg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, 0]))    # S -> stat -> ...

    def get(self, S, team, stat):
        c = self.cur[(S, team)][stat]
        lg = self.lg[S - 1][stat] if self.lg[S - 1][stat][1] > 0 else self.lg[S][stat]
        if lg[1] <= 0:
            return None
        lr, dpg = lg[0] / lg[1], lg[1] / max(lg[2], 1)
        last = self.cur.get((S - 1, team), {}).get(stat)
        p = 0.5 * lr + 0.5 * (last[0] / last[1]) if last and last[1] > 0 else lr
        k = self.n0 * dpg
        return (c[0] + k * p) / (c[1] + k)

    def add(self, S, team, stat, num, den=1.0):
        if num is None or den is None or den <= 0:
            return
        for v in (self.cur[(S, team)][stat], self.lg[S][stat]):
            v[0] += num
            v[1] += den
            v[2] += 1


def run_roll(events, n0, stats):
    """events: time-ordered dicts (t, S, h, a, gid, sh, sa) with sh/sa {stat: (num, den)} for the home and away side
    (what that side did). Returns gid -> {'h': {stat: pre-game value}, 'a': {...}} for every stat."""
    R, out = Roll(n0), {}
    by = collections.OrderedDict()
    for e in events:
        by.setdefault(e['t'].date(), []).append(e)
    for _, es in by.items():        # a day's games all see the table as of that morning
        for e in es:
            out[e['gid']] = {s: {st: R.get(e['S'], e[s], st) for st in stats} for s in ('h', 'a')}
        for e in es:
            for s, k in (('h', 'sh'), ('a', 'sa')):
                for st, v in (e.get(k) or {}).items():
                    R.add(e['S'], e[s], st, *v)
    return out


# ---------------------------------------------------------------- basketball
def bb_line(f):
    """team box dict -> stats; o = the opponent's box (for rebounds and allowed rates)"""
    fga, fg3a, fg3m, fta, orb, tov = f['fga'], f['fg3a'], f['fg3m'], f['fta'], f['orb'], f['tov']
    return fga, fg3a, fg3m, fta, orb, tov, fga - orb + tov + 0.44 * fta


def bb_sides(fh, fa):
    out = []
    for me, op in ((fh, fa), (fa, fh)):
        fga, fg3a, fg3m, fta, orb, tov, poss = bb_line(me)
        o_fga, o_fg3a, _, o_fta, o_orb, o_tov, o_poss = bb_line(op)
        P = 0.5 * (poss + o_poss)
        out.append({'3pa': (fg3a, fga), '3pa_al': (o_fg3a, o_fga), '3p': (fg3m, fg3a), 'orb': (orb, orb + op['drb']),
                    'orb_al': (o_orb, o_orb + me['drb']), 'tov': (tov, P), 'tovf': (o_tov, P), 'ftr': (fta, fga),
                    'ftr_al': (o_fta, o_fga), 'pace': (P, 1.0), 'ast': (me['ast'], me['fgm']), 'stl': (me['stl'], P),
                    'blk': (me['blk'], o_fga - o_fg3a), '2pa': (fga - fg3a, fga)})
    return out


BB_STATS = ['3pa', '3pa_al', '3p', 'orb', 'orb_al', 'tov', 'tovf', 'ftr', 'ftr_al', 'pace', 'ast', 'stl', 'blk', '2pa']
NBA_COLS = ['min', 'pts', 'fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta', 'oreb', 'dreb', 'ast', 'stl', 'blk', 'tov', 'pf', 'pm']


def nba():
    box = json.load(gzip.open(os.path.join(C, 'nba_box_hist.json.gz')))
    hist = {str(g['id']): g for g in json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz')))['games']}
    ev = []
    for gid, tm in box.items():
        g = hist.get(gid)
        if not g or g['h'] not in tm or g['a'] not in tm:
            continue
        f = {}
        for side in ('h', 'a'):
            s = np.zeros(len(NBA_COLS))
            for ln in tm[g[side]]:
                s += np.array(ln[1:], float)
            d = dict(zip(NBA_COLS, s))
            f[side] = {'fga': d['fga'], 'fg3a': d['fg3a'], 'fg3m': d['fg3m'], 'fta': d['fta'], 'orb': d['oreb'], 'drb': d['dreb'], 'tov': d['tov'],
                       'ast': d['ast'], 'stl': d['stl'], 'blk': d['blk'], 'fgm': d['fgm']}
        if f['h']['fga'] < 50 or f['a']['fga'] < 50:
            continue
        sh, sa = bb_sides(f['h'], f['a'])
        ev.append(dict(t=when(g['tip']), S=g['S'], h=g['h'], a=g['a'], gid=gid, sh=sh, sa=sa))
    ev.sort(key=lambda e: e['t'])
    pre = run_roll(ev, 8, BB_STATS)
    rows = []
    for r in json.load(gzip.open(WF.format('nba'))):
        if r.get('res') is None or r.get('L') is None or str(r['id']) not in pre:
            continue
        rows.append(dict(S=r['S'], day=r['date'][:10], st=pre[str(r['id'])], ym=r['res'], cm=r['L'], mm=r['m'],
                         yt=r.get('tot'), ct=r.get('T'), mt=r.get('tm')))
    return rows


def cbb():
    ev, idx = [], collections.defaultdict(list)
    seen = set()
    for y in range(2015, 2027):
        p = os.path.join(C, f'cbb_gs{y}.csv')
        if not os.path.exists(p):
            continue
        for r in csv.reader(open(p, encoding='utf-8', errors='replace')):
            if len(r) < 30:
                continue
            try:
                b = ast.literal_eval(r[29])
            except (ValueError, SyntaxError):
                try:
                    b = json.loads(r[29])
                except ValueError:
                    continue
            m = f'{y}:{r[24]}'
            mo, dd, yy = b[0].split('/')
            d = datetime.datetime(int(yy) + (2000 if len(yy) == 2 else 0), int(mo), int(dd))
            if m in seen:
                continue
            seen.add(m)
            n1, n2 = b[2], b[3]
            st = lambda v: {'fga': v[1], 'fg3a': v[3], 'fg3m': v[2], 'fta': v[5], 'orb': v[6], 'drb': v[7], 'tov': v[12], 'pts': v[14],
                            'ast': v[9], 'stl': v[10], 'blk': v[11], 'fgm': v[0]}
            try:
                f1, f2 = st([float(v) for v in b[4:19]]), st([float(v) for v in b[19:34]])
            except (TypeError, ValueError):
                continue
            if f1['fga'] < 30 or f2['fga'] < 30:
                continue
            s1, s2 = bb_sides(f1, f2)
            gid = m
            ev.append(dict(t=d, S=y, h=n1, a=n2, gid=gid, sh=s1, sa=s2))
            idx[(d.date(), tuple(sorted((f1['pts'], f2['pts']))))].append((gid, n1, n2, f1['pts'], f2['pts']))
    ev.sort(key=lambda e: e['t'])
    pre = run_roll(ev, 6, BB_STATS)
    rows, miss = [], 0
    for r in json.load(gzip.open(WF.format('cbb'))):
        if r.get('res') is None or r.get('L') is None or r.get('tot') is None:
            continue
        hs, as_ = (r['tot'] + r['res']) / 2, (r['tot'] - r['res']) / 2
        d = datetime.date.fromisoformat(r['date'][:10])
        hit = None
        for dd in (d, d - datetime.timedelta(days=1)):     # ESPN dates are UTC, Barttorvik's local
            c = idx.get((dd, tuple(sorted((hs, as_)))))
            if c and len(c) == 1:
                hit = c[0]
                break
        if not hit:
            miss += 1
            continue
        gid, n1, n2, p1, p2 = hit
        st = pre[gid]
        if p1 == hs:
            st = {'h': st['h'], 'a': st['a']}
        else:
            st = {'h': st['a'], 'a': st['h']}
        rows.append(dict(S=r['S'], day=r['date'][:10], st=st, ym=r['res'], cm=r['L'], mm=r['m'], yt=r['tot'], ct=r.get('T'), mt=r.get('tm')))
    print('cbb joined', len(rows), 'missed', miss, flush=True)
    return rows


# ---------------------------------------------------------------- football
FB_STATS = ['pshare', 'p_al', 'r_al', '3d', '3d_al', 'p_o', 'r_o', 'give', 'take', 'sk', 'sk_def', 'rz', 'rz_al', 'air', 'air_al']
CFB_STATS = FB_STATS[:9]


def made_att(x):
    try:
        m, a = (float(v) for v in str(x).split('-')[:2])
        return (m, a) if a > 0 else None
    except (TypeError, ValueError):
        return None


def nfl():
    tg = collections.defaultdict(dict)
    for y in range(2014, 2027):
        p = os.path.join(C, f'nfl_team{y}.csv')
        if not os.path.exists(p):
            continue
        for r in csv.DictReader(open(p)):
            tg[r['game_id']][r['team']] = r
    F = lambda r, k: float(r.get(k) or 0)
    eb = json.load(open(os.path.join(C, 'nfl_box.json')))
    giv = lambda r: F(r, 'passing_interceptions') + F(r, 'sack_fumbles_lost') + F(r, 'rushing_fumbles_lost') + F(r, 'receiving_fumbles_lost')
    sched = {}
    for r in json.load(gzip.open(WF.format('nfl'))):
        sched[r['id']] = r
    ev = []
    for gid, tm in tg.items():
        if len(tm) != 2:
            continue
        y, _, aw, hm = gid.split('_')
        if hm not in tm or aw not in tm:
            continue
        r0 = sched.get(gid)
        dt = when(r0['date']) if r0 else None
        if dt is None:
            wk = int(gid.split('_')[1])
            dt = datetime.datetime(int(y), 9, 1) + datetime.timedelta(days=7 * wk)
        sides = []
        bx = eb.get(gid, {})
        for (me, op), (bm, bo) in zip(((tm[hm], tm[aw]), (tm[aw], tm[hm])), ((bx.get('home'), bx.get('away')), (bx.get('away'), bx.get('home')))):
            db, ca = F(me, 'attempts') + F(me, 'sacks_suffered'), F(me, 'carries')
            odb, oca = F(op, 'attempts') + F(op, 'sacks_suffered'), F(op, 'carries')
            sides.append({'pshare': (db, db + ca), 'p_al': (F(op, 'passing_epa'), odb), 'r_al': (F(op, 'rushing_epa'), oca),
                          'p_o': (F(me, 'passing_epa'), db), 'r_o': (F(me, 'rushing_epa'), ca),
                          'sk': (F(me, 'sacks_suffered'), db), 'sk_def': (F(op, 'sacks_suffered'), odb),
                          'give': (giv(me), db + ca), 'take': (giv(op), odb + oca),
                          'air': (F(me, 'passing_air_yards'), F(me, 'attempts')), 'air_al': (F(op, 'passing_air_yards'), F(op, 'attempts'))})
            if bm and bo:
                for k, src, key in (('3d', bm, 'thirdDownEff'), ('3d_al', bo, 'thirdDownEff'), ('rz', bm, 'redZoneAttempts'), ('rz_al', bo, 'redZoneAttempts')):
                    v = made_att(src.get(key))
                    if v:
                        sides[-1][k] = v
        S = int(y) + 1          # games_wf season label: 2015 = the 2014 season
        ev.append(dict(t=dt, S=S, h=hm, a=aw, gid=gid, sh=sides[0], sa=sides[1]))
    ev.sort(key=lambda e: e['t'])
    pre = run_roll(ev, 4, FB_STATS)
    rows = []
    for r in sched.values():
        if r.get('res') is None or r.get('L') is None or r['id'] not in pre:
            continue
        rows.append(dict(S=r['S'], day=r['date'][:10], st=pre[r['id']], ym=r['res'], cm=r['L'], mm=r['m'], yt=r.get('tot'), ct=r.get('T'), mt=r.get('tm')))
    return rows


def cfb():
    box = json.load(open(os.path.join(C, 'cfb_box.json')))
    num = lambda s: float(str(s).replace(',', '') or 0)
    ev, wf = [], json.load(gzip.open(WF.format('cfb')))
    for r in wf:
        b = box.get(str(r['id']))
        if not b or 'home' not in b or 'away' not in b:
            continue
        try:
            sides = []
            for me, op in ((b['home'], b['away']), (b['away'], b['home'])):
                pa, oa = (num(x.get('completionAttempts', '0/0').split('/')[1]) for x in (me, op))
                ra, ora = num(me.get('rushingAttempts', 0)), num(op.get('rushingAttempts', 0))
                sides.append({'pshare': (pa, pa + ra), 'p_al': (num(op.get('netPassingYards', 0)), oa), 'r_al': (num(op.get('rushingYards', 0)), ora),
                              'p_o': (num(me.get('netPassingYards', 0)), pa), 'r_o': (num(me.get('rushingYards', 0)), ra),
                              'give': (num(me.get('turnovers', 0)), pa + ra), 'take': (num(op.get('turnovers', 0)), oa + ora)})
                for k, src in (('3d', me), ('3d_al', op)):
                    v = made_att(src.get('thirdDownEff'))
                    if v:
                        sides[-1][k] = v
        except (ValueError, IndexError):
            continue
        if min(sides[0]['pshare'][1], sides[1]['pshare'][1]) < 30:
            continue
        ev.append(dict(t=when(r['date']), S=r['S'], h=r['home'], a=r['away'], gid=str(r['id']), sh=sides[0], sa=sides[1]))
    ev.sort(key=lambda e: e['t'])
    pre = run_roll(ev, 3, CFB_STATS)
    rows = []
    for r in wf:
        if r.get('res') is None or r.get('L') is None or str(r['id']) not in pre:
            continue
        rows.append(dict(S=r['S'], day=r['date'][:10], st=pre[str(r['id'])], ym=r['res'], cm=r['L'], mm=r['m'], yt=r.get('tot'), ct=r.get('T'), mt=r.get('tm')))
    return rows


# ---------------------------------------------------------------- hockey, soccer
def nhl():
    ev = []
    for g in json.load(gzip.open(os.path.join(HERE, 'nhl_games_hist.json.gz'))):
        x = g.get('x')
        if not x or g.get('hs') is None:
            continue
        sides = []
        for me, op in ((x['h'], x['a']), (x['a'], x['h'])):
            # x: [sva xGF, xGF, GF, 5v5 xGF, 5v5 xGA, PP xGF, PK xGA, PP min, PK min]
            sides.append({'pp': (me[5], me[7] / 60), 'pk_al': (me[6], me[8] / 60), 'ppt': (me[7], 1.0), 'pkt': (me[8], 1.0), 'x5f': (me[3], 1.0), 'x5a': (me[4], 1.0)})
        ev.append(dict(t=when(g['day']), S=g['S'], h=g['h'], a=g['a'], gid=str(g['id']), sh=sides[0], sa=sides[1]))
    ev.sort(key=lambda e: e['t'])
    pre = run_roll(ev, 10, ['pp', 'pk_al', 'ppt', 'pkt', 'x5f', 'x5a'])
    rows = []
    for r in json.load(gzip.open(WF.format('nhl'))):
        c = r.get('c')
        if not c or c.get('p') is None or str(r['id']) not in pre:
            continue
        rows.append(dict(S=r['S'], day=r['day'], st=pre[str(r['id'])], ym=float(r['hs'] > r['as']), cm=c['p'], mm=r['p'],
                         yt=float(r['hs'] + r['as']), ct=c.get('t'), mt=r.get('T')))
    return rows


def soccer():
    hist = {r['id']: r for r in json.load(gzip.open(os.path.join(HERE, 'soccer_games_hist.json.gz')))}
    wf = json.load(gzip.open(WF.format('soccer')))
    ev = []
    for r in wf:
        g = hist.get(r['id']) or {}
        sh, sa = {'gf': (r['hs'], 1.0), 'ga': (r['as'], 1.0)}, {'gf': (r['as'], 1.0), 'ga': (r['hs'], 1.0)}
        if g.get('hst') is not None and g.get('ast') is not None:
            sh.update({'sot': (g['hst'], 1.0), 'sot_al': (g['ast'], 1.0)})
            sa.update({'sot': (g['ast'], 1.0), 'sot_al': (g['hst'], 1.0)})
        ev.append(dict(t=when(r['day']), S=r['S'], h=r['h'], a=r['a'], gid=r['id'], sh=sh, sa=sa))
    ev.sort(key=lambda e: e['t'])
    pre = run_roll(ev, 6, ['sot', 'sot_al', 'gf', 'ga'])
    rows = []
    for r in wf:
        if not r.get('c') or r['id'] not in pre:
            continue
        c, p = r['c'], r['p']
        ov = None
        if r.get('ouc') and all(r['ouc']):
            io, iu = 1 / r['ouc'][0], 1 / r['ouc'][1]
            ov = io / (io + iu)
        rows.append(dict(S=r['S'], day=r['day'], st=pre[r['id']], ym=float((r['hs'] > r['as']) - (r['as'] > r['hs'])), cm=c[0] - c[2], mm=p[0] - p[2],
                         yt=float(r['hs'] + r['as'] > 2.5), ct=ov, mt=r.get('o25')))
    return rows


# ---------------------------------------------------------------- tennis
def tennis():
    import tennis_data as T
    f = lambda x: float(x) if x not in (None, '') else None
    ms = []
    for r in T.mm_rows(refresh=False):
        try:
            pc, t = float(r['winner_close_prob']), when(r['start_time_utc'])
        except (ValueError, KeyError):
            continue
        st = {}
        for p, o in (('w_', 'l_'), ('l_', 'w_')):
            sv, w1, w2, ace = (f(r.get(p + k)) for k in ('svpt', '1stWon', '2ndWon', 'ace'))
            osv, ow1, ow2 = (f(r.get(o + k)) for k in ('svpt', '1stWon', '2ndWon'))
            if not sv or not osv or None in (w1, w2, ace, ow1, ow2):
                st = None
                break
            st[p] = {'srv': (w1 + w2, sv), 'ret': (osv - ow1 - ow2, osv), 'ace': (ace, sv)}
        ms.append(dict(id=r['match_id'], t=t, tour=r['_tour'], hw=r.get('winner_hand'), hl=r.get('loser_hand'), w=r['_tour'] + r['winner_id'], l=r['_tour'] + r['loser_id'], pc=pc if 0 < pc < 1 else None, st=st))
    ms.sort(key=lambda m: m['t'])
    ev = [dict(t=m['t'], S=0, h=m['w'], a=m['l'], gid=m['id'], sh=m['st']['w_'] if m['st'] else None, sa=m['st']['l_'] if m['st'] else None) for m in ms]
    pre = run_roll(ev, 10, ['srv', 'ret', 'ace'])
    rows = []
    for m in ms:
        if m['pc'] is None:
            continue
        flip = zlib.crc32(m['id'].encode()) % 2 == 1
        s = pre[m['id']]
        st = {'h': s['a'], 'a': s['h']} if flip else s
        y = 0.0 if flip else 1.0
        L = lambda h: None if h not in ('L', 'R') else float(h == 'L')
        lh = (L(m['hl']), L(m['hw'])) if flip else (L(m['hw']), L(m['hl']))
        rows.append(dict(S=m['t'].year, day=m['t'].date().isoformat(), st=st, ym=y, cm=1 - m['pc'] if flip else m['pc'], mm=None, yt=None, ct=None, mt=None, lh=lh))
    return rows


# ---------------------------------------------------------------- terms and scoring
def zs(rows, stats):
    """z of each pre-game style value within its season, over both sides"""
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        for s in ('h', 'a'):
            for k in stats:
                v = r['st'][s].get(k)
                if v is not None:
                    by[r['S']][k].append(v)
    ms = {S: {k: (np.mean(v), np.std(v) or 1.0) for k, v in d.items()} for S, d in by.items()}
    for r in rows:
        r['z'] = {s: {k: ((r['st'][s][k] - ms[r['S']][k][0]) / ms[r['S']][k][1] if r['st'][s].get(k) is not None else None) for k in stats} for s in ('h', 'a')}


def term(rows, A, B, sym):
    """A, B: functions of a side's z dict -> value (B reads the other side)"""
    x = []
    for r in rows:
        try:
            ab = A(r['z']['h']) * B(r['z']['a'])
            ba = A(r['z']['a']) * B(r['z']['h'])
            x.append(ab + ba if sym else ab - ba)
        except TypeError:
            x.append(np.nan)
    return np.array(x, float)


def ols_cl(X, y, c):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    _, inv = np.unique(c, return_inverse=True)
    G = inv.max() + 1
    sc = np.zeros((G, X.shape[1]))
    np.add.at(sc, inv, X * e[:, None])
    n, k = X.shape
    V = XtXi @ (sc.T @ sc) @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    return b, np.sqrt(np.diag(V))


def score(rows, x, total, tune_yrs, sign):
    yk, ck, mk = ('yt', 'ct', 'mt') if total else ('ym', 'cm', 'mm')
    ok = np.array([r[yk] is not None and r[ck] is not None for r in rows]) & ~np.isnan(x)
    R = [r for r, o in zip(rows, ok) if o]
    x = x[ok]
    y = np.array([r[yk] for r in R], float)
    c = np.array([r[ck] for r in R], float)
    S = np.array([r['S'] for r in R])
    day = np.array([r['day'] for r in R])
    tune = np.isin(S, list(tune_yrs))
    held = ~tune
    X = np.c_[np.ones(len(x)), x]
    o = {'n': [int(tune.sum()), int(held.sum())], 'sd_x': round(float(x.std()), 3)}
    res = y - c
    for part, m in (('tune', tune), ('held', held)):
        b, s = ols_cl(X[m], res[m], day[m])
        o[part] = [round(float(b[1]), 4), round(float(b[1] / s[1]), 2)]
    bt = ols_cl(X[tune], res[tune], day[tune])[0]
    new, old = c + bt[0] + bt[1] * x, c + res[tune].mean()
    pr = H.paired(H.se(new[held], y[held]), H.se(old[held], y[held]), cluster=day[held])
    o['seHeld'] = [round(float(pr['d']), 6), round(pr['t'], 2)]
    mm = np.array([r[mk] if r[mk] is not None else np.nan for r in R], float)
    if not np.isnan(mm).all():
        g = ~np.isnan(mm)
        rm = y - mm
        o['model'] = {}
        for part, m in (('tune', tune & g), ('held', held & g)):
            b, s = ols_cl(X[m], rm[m], day[m])
            o['model'][part] = [round(float(b[1]), 4), round(float(b[1] / s[1]), 2)]
    d = sign if sign else (1 if o['tune'][1] > 0 else -1)
    o['z'] = round(H.stouffer([d * o['tune'][1], d * o['held'][1]]), 2)
    o['pass_split'] = bool(d * o['tune'][1] >= 1.5 and d * o['held'][0] > 0 and o['seHeld'][1] <= -1.5)
    return o


Z = lambda k: (lambda z: z[k])
NEG = lambda k: (lambda z: -z[k] if z[k] is not None else None)


def bb_terms(rows):
    zs(rows, BB_STATS)
    return {
        '3pt_vol': (term(rows, Z('3pa'), Z('3pa_al'), False), False),
        'oreb': (term(rows, Z('orb'), Z('orb_al'), False), False),
        'tov': (term(rows, Z('tovf'), Z('tov'), False), False),
        '3pt_slow': (term(rows, Z('3p'), NEG('pace'), False), False),
        '3pt_vol_T': (term(rows, Z('3pa'), Z('3pa_al'), True), True),
        'ftr_T': (term(rows, Z('ftr'), Z('ftr_al'), True), True),
        'ast_stl': (term(rows, Z('ast'), Z('stl'), False), False),
        'rim': (term(rows, Z('blk'), Z('2pa'), False), False),
        'ftr': (term(rows, Z('ftr'), Z('ftr_al'), False), False),
    }


def fb_terms(rows, nfl_):
    zs(rows, FB_STATS if nfl_ else CFB_STATS)
    weak = lambda z: z['p_al'] - z['r_al'] if z['p_al'] is not None and z['r_al'] is not None else None
    t = {'mix': (term(rows, Z('pshare'), weak, False), False), 'mix_T': (term(rows, Z('pshare'), weak, True), True),
         '3rd': (term(rows, Z('3d'), Z('3d_al'), False), False), '3rd_T': (term(rows, Z('3d'), Z('3d_al'), True), True)}
    otilt = lambda z: z['p_o'] - z['r_o'] if z['p_o'] is not None and z['r_o'] is not None else None
    for k, A, B in (('run_run', Z('r_o'), Z('r_al')), ('pass_pass', Z('p_o'), Z('p_al'))):
        t[k] = (term(rows, A, B, False), False)
        t[k + '_T'] = (term(rows, A, B, True), True)
    t['tilt'] = (term(rows, otilt, weak, False), False)
    t['to_bat'] = (term(rows, Z('take'), Z('give'), False), False)
    if nfl_:
        # the pass rush side gains: its sack rate x the opponent's sack rate allowed
        t['sack'] = (term(rows, Z('sk_def'), Z('sk'), False), False)
        t['rz'] = (term(rows, Z('rz'), Z('rz_al'), False), False)
        t['air'] = (term(rows, Z('air'), Z('air_al'), False), False)
    return t


def nhl_terms(rows):
    zs(rows, ['pp', 'pk_al', 'ppt', 'pkt', 'x5f', 'x5a'])
    return {'pp_disc': (term(rows, Z('pp'), Z('pkt'), False), False), 'pk_draw': (term(rows, Z('ppt'), Z('pk_al'), False), False),
            'pp_disc_T': (term(rows, Z('pp'), Z('pkt'), True), True), 'ev5': (term(rows, Z('x5f'), Z('x5a'), False), False)}


def soccer_terms(rows):
    zs(rows, ['sot', 'sot_al', 'gf', 'ga'])
    return {'sot': (term(rows, Z('sot'), Z('sot_al'), False), False), 'sot_T': (term(rows, Z('sot'), Z('sot_al'), True), True),
            'goals': (term(rows, Z('gf'), Z('ga'), False), False), 'goals_T': (term(rows, Z('gf'), Z('ga'), True), True)}


def tennis_terms(rows):
    zs(rows, ['srv', 'ret', 'ace'])
    lefty = np.array([r['lh'][0] - r['lh'][1] if None not in r['lh'] else np.nan for r in rows], float)
    return {'srv_ret': (term(rows, Z('srv'), Z('ret'), False), False), 'ace_ret': (term(rows, Z('ace'), Z('ret'), False), False),
            'lefty': (lefty, False)}


TUNE = {'nba': range(2015, 2022), 'cbb': range(2016, 2022), 'nfl': range(2015, 2022), 'cfb': range(2017, 2023),
        'nhl': range(2020, 2023), 'soccer': range(2013, 2021), 'soccer_T': range(2020, 2023), 'tennis': [2025]}


def main():
    only = sys.argv[1:] or ['nba', 'cbb', 'nfl', 'cfb', 'nhl', 'soccer', 'tennis']
    res = {}
    for sp in only:
        rows = {'nba': nba, 'cbb': cbb, 'nfl': nfl, 'cfb': cfb, 'nhl': nhl, 'soccer': soccer, 'tennis': tennis}[sp]()
        terms = {'nba': bb_terms, 'cbb': bb_terms, 'nhl': nhl_terms, 'soccer': soccer_terms, 'tennis': tennis_terms,
                 'nfl': lambda r: fb_terms(r, True), 'cfb': lambda r: fb_terms(r, False)}[sp](rows)
        res[sp] = {}
        for k, (x, tot) in terms.items():
            ty = TUNE['soccer_T'] if sp == 'soccer' and tot else TUNE[sp]
            res[sp][k] = score(rows, x, tot, ty, SIGN[k])
            o = res[sp][k]
            print(f"{sp:7}{k:10} n {o['n']}  tune {o['tune']} held {o['held']} held SE {o['seHeld']}  z {o['z']}  model {o.get('model')}", flush=True)
    tests = [(sp, k) for sp in res for k in res[sp]]
    if set(only) == {'nba', 'cbb', 'nfl', 'cfb', 'nhl', 'soccer', 'tennis'}:
        p = [2 * (1 - 0.5 * (1 + math.erf(abs(res[sp][k]['z']) / math.sqrt(2)))) for sp, k in tests]
        for (sp, k), pi, q in zip(tests, p, H.bh(p)):
            o = res[sp][k]
            o['p'], o['q'] = round(pi, 5), round(float(q), 4)
            o['pass'] = bool(o['pass_split'] and q <= .10)
        json.dump({'asof': datetime.date.today().isoformat(), 'tests': len(tests), 'sports': res}, open(OUT, 'w'), indent=1)
        for sp, k in tests:
            o = res[sp][k]
            print(f"{sp:7}{k:10} z {o['z']:6} q {o['q']}  {'PASS' if o['pass'] else ''}")


if __name__ == '__main__':
    main()
