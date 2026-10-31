#!/usr/bin/env python3
"""Penalty and foul discipline as team terms in the game models (thread "Test penalty discipline in game models",
Oct 31 2026; Noah: "Do we account for penalty discipline in each team/game model?"). Research only. Results in
data/penalty_research.json.

Already in or already tested (not redone here): CBB opponent free-throw luck (ldft, shipped); NBA free-throw luck and
referee crews (failed / forward log); NBA, CBB FT-rate battles and NHL PP x discipline battles (style_research.py,
failed); NFL penalty yards as an opponent-adjusted rating (nfl_splits_research.py, failed); CFB penalty luck (failed);
NHL "penalties" in the lineup-value round (failed); soccer red cards from line-ups (failed). What none of those tried:
a team's own discipline (committed) and the opponent's it draws as plain main effects, side by side, on the margin and
on the total, against the close, with the referee noise shrunk out.

Pre-registered before any outcome was looked at (one BH family over every test below). Each rate is the team's season
to date before the game (a day's games all see that morning's table), shrunk to a prior worth n0 games (half last
season's team rate, half the league's), z-scored within the season. n0 is set from the split-half reliability of the
rate (odd vs even games of a team season, Spearman-Brown): a whistle count mostly driven by referees needs more games
before it says anything, so n0 = the games at which the shrunk rate's reliability reaches .5 for the noisier of the
two, floored at the style_research n0 (refs are random across a season, so the noise averages out with games).
Margin x = (drawn - committed)(home) - (drawn - committed)(away), expected + (a disciplined team that draws whistles
beats the close). Committed alone, x = c(away) - c(home), +. Totals x = sum of both sides' committed + drawn, +
(more whistles: more free throws, power plays, extended drives), soccer cards two-sided.
  NBA, CBB  personal fouls a possession committed / drawn   (NBA ESPN box, CBB Barttorvik getgamestats)
  NFL       penalty yards a play committed / drawn          (nflverse stats_team_week; offense + defense snaps proxy)
  CFB       penalty yards a play committed / drawn          (ESPN summary boxes, totalPenaltiesYards)
  NHL       penalty-kill minutes (taken) / power-play minutes (drawn) a game   (MoneyPuck, nhl_games_hist)
  soccer    fouls committed / drawn a match; cards (yellow 1, red 3) a match; red cards alone (football-data)
Outcomes, splits and pass rule as style_research.py: residual vs the close, tune vs held seasons, errors clustered by
game day; pass = tune t >= 1.5 in the expected direction, held-out b the same sign, held-out squared error of
close + b x below the close at paired t <= -1.5, and BH q <= .10. Also scored against the model's own prediction
(walk-forward, data/games_wf) to see whether the model misses something the close already has.

Result (Oct 31 2026): none of the 21 passes. Nothing ships; no model, ranking or picks change.
Referee noise: season split-half reliability of fouls committed NBA .92, CBB .85, soccer .90 (team habits); NHL
penalty minutes taken .76, CFB penalty yards .52, NFL .46, soccer reds .36 (mostly whistle noise), so n0 runs 6-40.
Closest, each on one split only: soccer fouls committed (held t 2.7, tune 0.1), NHL net PP time drawn (held 2.3, tune
0.3), NFL whistles total (tune 2.3, held 0.7). CBB foul volume runs the WRONG way on totals (foul-heavy games go under:
vs close t -4.2 / -2.0 with no held-out error gain; vs the model -5.9 / -4.1, the model and close both overrate them).

    python3 scripts/penalty_research.py     # every sport -> data/penalty_research.json
Caches (scripts/.cache/style/ and .cache/pen/, not committed): see style_research.py; football-data CSVs
mmz4281/{code}/{div}.csv for fouls and cards (HF AF HY AY HR AR).
"""
import ast
import collections
import csv
import datetime
import glob
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import style_research as SR  # noqa: E402

C, CP = SR.C, os.path.join(HERE, '.cache', 'pen')
OUT = os.path.join(ROOT, 'data', 'penalty_research.json')
N0_FLOOR = {'nba': 8, 'cbb': 6, 'nfl': 4, 'cfb': 3, 'nhl': 10, 'soccer': 6}


def rows_from_wf(sp, pre, key='id'):
    out = []
    for r in json.load(gzip.open(SR.WF.format(sp))):
        g = pre.get(str(r[key]))
        if g is None:
            continue
        if sp == 'nhl':
            c = r.get('c')
            if not c or c.get('p') is None:
                continue
            out.append(dict(S=r['S'], day=r['day'], st=g, ym=float(r['hs'] > r['as']), cm=c['p'], mm=r['p'],
                            yt=float(r['hs'] + r['as']), ct=c.get('t'), mt=r.get('T')))
        elif sp == 'soccer':
            if not r.get('c'):
                continue
            c, p = r['c'], r['p']
            ov = None
            if r.get('ouc') and all(r['ouc']):
                io, iu = 1 / r['ouc'][0], 1 / r['ouc'][1]
                ov = io / (io + iu)
            out.append(dict(S=r['S'], day=r['day'], st=g, ym=float((r['hs'] > r['as']) - (r['as'] > r['hs'])),
                            cm=c[0] - c[2], mm=p[0] - p[2], yt=float(r['hs'] + r['as'] > 2.5), ct=ov, mt=r.get('o25')))
        else:
            if r.get('res') is None or r.get('L') is None:
                continue
            out.append(dict(S=r['S'], day=r['date'][:10], st=g, ym=r['res'], cm=r['L'], mm=r['m'], yt=r.get('tot'),
                            ct=r.get('T'), mt=r.get('tm')))
    return out


# ---------------------------------------------------------------- events: (side stats {stat: (num, den)})
def ev_nba():
    box = json.load(gzip.open(os.path.join(C, 'nba_box_hist.json.gz')))
    hist = {str(g['id']): g for g in json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz')))['games']}
    ev = []
    for gid, tm in box.items():
        g = hist.get(gid)
        if not g or g['h'] not in tm or g['a'] not in tm:
            continue
        f = {}
        for side in ('h', 'a'):
            s = np.zeros(len(SR.NBA_COLS))
            for ln in tm[g[side]]:
                s += np.array(ln[1:], float)
            f[side] = dict(zip(SR.NBA_COLS, s))
        if f['h']['fga'] < 50 or f['a']['fga'] < 50:
            continue
        P = 0.5 * sum(x['fga'] - x['oreb'] + x['tov'] + 0.44 * x['fta'] for x in f.values())
        sd = lambda me, op: {'c': (me['pf'], P), 'd': (op['pf'], P)}
        ev.append(dict(t=SR.when(g['tip']), S=g['S'], h=g['h'], a=g['a'], gid=gid, sh=sd(f['h'], f['a']), sa=sd(f['a'], f['h'])))
    return ev


def ev_cbb():
    """Barttorvik box list: date, min, t1, t2, then 15 a side: fgm fga 3pm 3pa ftm fta orb drb trb ast stl blk tov pf pts"""
    ev, idx, seen = [], collections.defaultdict(list), set()
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
                continue
            m = f'{y}:{r[24]}'
            if m in seen:
                continue
            seen.add(m)
            mo, dd, yy = b[0].split('/')
            d = datetime.datetime(int(yy) + (2000 if len(yy) == 2 else 0), int(mo), int(dd))
            try:
                v1, v2 = [float(v) for v in b[4:19]], [float(v) for v in b[19:34]]
            except (TypeError, ValueError):
                continue
            if v1[1] < 30 or v2[1] < 30:
                continue
            P = 0.5 * sum(v[1] - v[6] + v[12] + 0.44 * v[5] for v in (v1, v2))
            s1, s2 = {'c': (v1[13], P), 'd': (v2[13], P)}, {'c': (v2[13], P), 'd': (v1[13], P)}
            ev.append(dict(t=d, S=y, h=b[2], a=b[3], gid=m, sh=s1, sa=s2))
            idx[(d.date(), tuple(sorted((v1[14], v2[14]))))].append((m, v1[14], v2[14]))
    return ev, idx


def cbb_rows(pre, idx):
    rows = []
    for r in json.load(gzip.open(SR.WF.format('cbb'))):
        if r.get('res') is None or r.get('L') is None or r.get('tot') is None:
            continue
        hs, as_ = (r['tot'] + r['res']) / 2, (r['tot'] - r['res']) / 2
        d = datetime.date.fromisoformat(r['date'][:10])
        hit = None
        for dd in (d, d - datetime.timedelta(days=1)):      # ESPN dates are UTC, Barttorvik's local
            c = idx.get((dd, tuple(sorted((hs, as_)))))
            if c and len(c) == 1:
                hit = c[0]
                break
        if not hit or hs == as_:
            continue
        gid, p1, _ = hit
        st = pre[gid] if p1 == hs else {'h': pre[gid]['a'], 'a': pre[gid]['h']}
        rows.append(dict(S=r['S'], day=r['date'][:10], st=st, ym=r['res'], cm=r['L'], mm=r['m'], yt=r['tot'], ct=r.get('T'), mt=r.get('tm')))
    return rows


def ev_nfl():
    tg = collections.defaultdict(dict)
    for y in range(2014, 2027):
        p = os.path.join(C, f'nfl_team{y}.csv')
        if os.path.exists(p):
            for r in csv.DictReader(open(p)):
                tg[r['game_id']][r['team']] = r
    F = lambda r, k: float(r.get(k) or 0)
    sched = {r['id']: r for r in json.load(gzip.open(SR.WF.format('nfl')))}
    ev = []
    for gid, tm in tg.items():
        y, wk, aw, hm = gid.split('_')
        if hm not in tm or aw not in tm:
            continue
        r0 = sched.get(gid)
        dt = SR.when(r0['date']) if r0 else datetime.datetime(int(y), 9, 1) + datetime.timedelta(days=7 * int(wk))
        plays = lambda r: F(r, 'attempts') + F(r, 'sacks_suffered') + F(r, 'carries')
        P = plays(tm[hm]) + plays(tm[aw])           # both offenses' snaps: a game's chances to draw a flag
        sd = lambda me, op: {'c': (F(me, 'penalty_yards'), P), 'd': (F(op, 'penalty_yards'), P)}
        ev.append(dict(t=dt, S=int(y) + 1, h=hm, a=aw, gid=gid, sh=sd(tm[hm], tm[aw]), sa=sd(tm[aw], tm[hm])))
    return ev


def ev_cfb():
    box = json.load(open(os.path.join(C, 'cfb_box.json')))
    num = lambda s: float(str(s).replace(',', '') or 0)
    ev = []
    for r in json.load(gzip.open(SR.WF.format('cfb'))):
        b = box.get(str(r['id']))
        if not b or 'home' not in b or 'away' not in b:
            continue
        try:
            py = {k: num(b[k]['totalPenaltiesYards'].split('-')[1]) for k in ('home', 'away')}
            P = sum(num(b[k]['completionAttempts'].split('/')[1]) + num(b[k]['rushingAttempts']) for k in ('home', 'away'))
        except (KeyError, IndexError, ValueError):
            continue
        if P < 60:
            continue
        sh, sa = {'c': (py['home'], P), 'd': (py['away'], P)}, {'c': (py['away'], P), 'd': (py['home'], P)}
        ev.append(dict(t=SR.when(r['date']), S=r['S'], h=r['home'], a=r['away'], gid=str(r['id']), sh=sh, sa=sa))
    return ev


def ev_nhl():
    ev = []
    for g in json.load(gzip.open(os.path.join(HERE, 'nhl_games_hist.json.gz'))):
        x = g.get('x')
        if not x or g.get('hs') is None:
            continue
        # x: [sva xGF, xGF, GF, 5v5 xGF, 5v5 xGA, PP xGF, PK xGA, PP min, PK min]
        sd = lambda me: {'c': (me[8], 1.0), 'd': (me[7], 1.0)}
        ev.append(dict(t=SR.when(g['day']), S=g['S'], h=g['h'], a=g['a'], gid=str(g['id']), sh=sd(x['h']), sa=sd(x['a'])))
    return ev


def ev_soccer():
    """football-data fouls and cards joined to the walk-forward rows by league, day, score and shots on target"""
    import soccer_data as D
    hist = {r['id']: r for r in json.load(gzip.open(os.path.join(HERE, 'soccer_games_hist.json.gz')))}
    fd = {}
    div_lg = {v: k for k, v in D.FD_DIV.items()}
    for p in glob.glob(os.path.join(CP, 'fd_*.csv')):
        div = os.path.basename(p).split('_')[1]
        for r in csv.DictReader(open(p, encoding='utf-8-sig', errors='replace')):
            try:
                dd = r['Date'].strip().split('/')
                day = datetime.date(int(dd[2]) + (2000 if len(dd[2]) == 2 else 0), int(dd[1]), int(dd[0])).isoformat()
                v = [int(float(r[k])) for k in ('FTHG', 'FTAG', 'HF', 'AF', 'HY', 'AY', 'HR', 'AR')]
                st = (int(float(r['HST'])), int(float(r['AST']))) if r.get('HST') not in (None, '') else None
            except (KeyError, ValueError, TypeError, IndexError):
                continue
            fd.setdefault((div_lg[div], day, v[0], v[1]), []).append((st, v[2:]))
    wf = json.load(gzip.open(SR.WF.format('soccer')))
    ev, n = [], 0
    for r in wf:
        g = hist.get(r['id']) or {}
        c = fd.get((r['lg'], r['day'], r['hs'], r['as']), [])
        if len(c) > 1:
            c = [x for x in c if x[0] == (g.get('hst'), g.get('ast'))]
        sh = sa = None
        if len(c) == 1:
            hf, af, hy, ay, hr, ar = c[0][1]
            sh = {'c': (hf, 1.0), 'd': (af, 1.0), 'cd': (hy + 3 * hr, 1.0), 'cdd': (ay + 3 * ar, 1.0), 'rd': (hr, 1.0), 'rdd': (ar, 1.0)}
            sa = {'c': (af, 1.0), 'd': (hf, 1.0), 'cd': (ay + 3 * ar, 1.0), 'cdd': (hy + 3 * hr, 1.0), 'rd': (ar, 1.0), 'rdd': (hr, 1.0)}
            n += 1
        ev.append(dict(t=SR.when(r['day']), S=r['S'], h=r['h'], a=r['a'], gid=r['id'], sh=sh, sa=sa))
    print('soccer fouls joined', n, 'of', len(wf), flush=True)
    return ev


# ---------------------------------------------------------------- referee noise: split-half reliability and n0
def reliability(ev, stats):
    """per stat: split-half r of team-season rates (odd vs even games, teams with 10+ games), the games a season
    (median), and the games n at which a season-to-date rate's reliability reaches .5 (Spearman-Brown on per-game r1)"""
    g = collections.defaultdict(lambda: collections.defaultdict(list))
    for e in sorted(ev, key=lambda e: e['t']):
        for s, k in (('h', 'sh'), ('a', 'sa')):
            for st, (num, den) in (e.get(k) or {}).items():
                if den:
                    g[st][(e['S'], e[s])].append((num, den))
    out = {}
    for st in stats:
        a, b, ng = [], [], []
        for v in g[st].values():
            if len(v) < 10:
                continue
            o, e_ = v[0::2], v[1::2]
            a.append(sum(x[0] for x in o) / sum(x[1] for x in o))
            b.append(sum(x[0] for x in e_) / sum(x[1] for x in e_))
            ng.append(len(v))
        if len(a) < 20:
            continue
        r = float(np.corrcoef(a, b)[0, 1])
        half = np.median(ng) / 2
        r1 = r / (half - (half - 1) * r) if r > 0 else 0.0     # one game's reliability (inverse Spearman-Brown)
        n50 = (1 - r1) / r1 if r1 > 0 else float('inf')          # games for reliability .5
        out[st] = {'split_half_r': round(r, 3), 'season_r': round(2 * r / (1 + r), 3) if r > 0 else 0.0,
                   'games': float(np.median(ng)), 'n50': round(float(n50), 1)}
    return out


# ---------------------------------------------------------------- terms
def zget(z, k):
    return z.get(k)


def mterm(rows, f):
    """margin: f(home z) - f(away z)"""
    x = []
    for r in rows:
        a, b = f(r['z']['h']), f(r['z']['a'])
        x.append(a - b if a is not None and b is not None else np.nan)
    return np.array(x, float)


def tterm(rows, f):
    x = []
    for r in rows:
        a, b = f(r['z']['h']), f(r['z']['a'])
        x.append(a + b if a is not None and b is not None else np.nan)
    return np.array(x, float)


def net(d, c):
    return lambda z: z[d] - z[c] if z.get(d) is not None and z.get(c) is not None else None


def neg(k):
    return lambda z: -z[k] if z.get(k) is not None else None


def both(d, c):
    return lambda z: z[d] + z[c] if z.get(d) is not None and z.get(c) is not None else None


def terms(sp, rows):
    stats = ['c', 'd', 'cd', 'cdd', 'rd', 'rdd'] if sp == 'soccer' else ['c', 'd']
    SR.zs(rows, stats)
    t = {'net': (mterm(rows, net('d', 'c')), False, 1), 'committed': (mterm(rows, neg('c')), False, 1),
         'whistles_T': (tterm(rows, both('d', 'c')), True, 1 if sp != 'soccer' else 0)}
    if sp == 'soccer':
        t['cards_net'] = (mterm(rows, net('cdd', 'cd')), False, 1)
        t['reds_net'] = (mterm(rows, net('rdd', 'rd')), False, 1)
        t['cards_T'] = (tterm(rows, both('cdd', 'cd')), True, 0)
    return t


TUNE = dict(SR.TUNE)


def main():
    only = sys.argv[1:] or ['nba', 'cbb', 'nfl', 'cfb', 'nhl', 'soccer']
    res, rel = {}, {}
    for sp in only:
        idx = None
        if sp == 'cbb':
            ev, idx = ev_cbb()
        else:
            ev = {'nba': ev_nba, 'nfl': ev_nfl, 'cfb': ev_cfb, 'nhl': ev_nhl, 'soccer': ev_soccer}[sp]()
        ev.sort(key=lambda e: e['t'])
        stats = ['c', 'd', 'cd', 'cdd', 'rd', 'rdd'] if sp == 'soccer' else ['c', 'd']
        rel[sp] = reliability(ev, stats)
        n50 = max(rel[sp][s]['n50'] for s in ('c', 'd') if s in rel[sp])
        n0 = max(N0_FLOOR[sp], min(round(n50), 40))
        rel[sp]['n0'] = n0
        print(sp, 'events', len(ev), 'reliability', rel[sp], flush=True)
        pre = SR.run_roll(ev, n0, stats)
        rows = cbb_rows(pre, idx) if sp == 'cbb' else rows_from_wf(sp, pre)
        res[sp] = {}
        for k, (x, tot, sign) in terms(sp, rows).items():
            ty = TUNE['soccer_T'] if sp == 'soccer' and tot else TUNE[sp]
            o = SR.score(rows, x, tot, ty, sign)
            res[sp][k] = o
            print(f"{sp:7}{k:11} n {o['n']}  tune {o['tune']} held {o['held']} held SE {o['seHeld']}  z {o['z']}  model {o.get('model')}", flush=True)
    tests = [(sp, k) for sp in res for k in res[sp]]
    p = [2 * (1 - 0.5 * (1 + math.erf(abs(res[sp][k]['z']) / math.sqrt(2)))) for sp, k in tests]
    for (sp, k), pi, q in zip(tests, p, H.bh(p)):
        o = res[sp][k]
        o['p'], o['q'] = round(pi, 5), round(float(q), 4)
        o['pass'] = bool(o['pass_split'] and q <= .10)
        print(f"{sp:7}{k:11} z {o['z']:6} q {o['q']}  {'PASS' if o['pass'] else ''}")
    if set(only) == {'nba', 'cbb', 'nfl', 'cfb', 'nhl', 'soccer'}:
        json.dump({'asof': datetime.date.today().isoformat(), 'tests': len(tests), 'reliability': rel, 'sports': res},
                  open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
