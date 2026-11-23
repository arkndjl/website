# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFB season value (layouts/shortcodes/cfbseason.html: leaders > QB SV, skill players) -> data/cfb_season_value.json.
Descriptive, this season only; nothing here feeds a model. No CFBD call.

    python3 scripts/cfb_season_value.py [--force]     # skips when the release's ETag is the one on file

Plays: the cfbfastR release (sportsdataverse-data, cfbfastR_cfb_pbp/play_by_play_<season>.parquet, rebuilt Saturday to
Monday; scripts/cfb_mirror.py reads the same file), FBS games, every run and pass play with an EPA, regular season +
postseason, ESPN athlete ids. Dropbacks go to the passer (completion / incompletion / sack / INT), runs to the rusher,
passes to the receiver or target.
  aEPA   EPA a play less the defense's EPA allowed a play of that kind (run / pass) over the league's, from its other
         games, shrunk with K_DEF = 300 plays (QB, RB); WR and TE stay raw
  SV  sum(aEPA - replacement) / games with a play (QB: 10+); replacement = the mean a play (QB) or a run / target
         (skill) of the players past the starters by volume in 2025 (QB 134, RB 268, WR 402, TE 134), REPL below
Kept only where split-half reliability rose (alternate games, P >= .9 of 1,000 boots; 2021-26 player-seasons: QB 250+
plays, RB 100+, WR 60+, TE 40+; target ids are complete only from 2025, so receiving was rechecked on 2025-26):
  opponent  QB r .360 -> .403 (P 1.0; 2025-26 .335 -> .371, .99), RB .179 -> .199 (1.0; .106 -> .132, .99),
            WR .461 -> .465 (.84; .240 -> .242, .62), TE .318 -> .329 (.91; .004 -> .027, .88)
  weather   (Open-Meteo at the stadium, scripts/data/cfb_weather_om.json) on top: QB .32, RB .78, WR .35, TE .83: none kept
Defenders are left out: the public plays carry sacks, pass breakups, INTs and forced fumbles but no tackles or snaps, and
splash credits a team game had no split-half reliability (r <= 0 at every group).
Game model (scripts/data/games_wf/cfb.json.gz margins, 2022-26 scored, coefficients fit on earlier seasons): the starter's
season value against his team's, opponent-adjusted, scored the same as raw season EPA (MAE 12.061 vs 12.059, t +0.5);
absent skill players at season value added nothing (t +0.9). The model keeps its QB charge
(/mnt/project-files/qb-season-metric/nonqb/).
Board join by ESPN id (static/data/cfb-all.json): photo, conference, class, WAR."""
import email.utils
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cfb_all  # noqa: E402
import cfb_mirror  # noqa: E402

CACHE = os.path.join(ROOT, 'scripts', '.cache', 'cfb')
OUT = os.path.join(ROOT, 'data', 'cfb_season_value.json')
K_DEF = 300
OPP = {'QB', 'RB'}
REPL = {'QB': -0.0741, ('RB', 0): -0.0862, ('RB', 1): 0.0828, ('WR', 0): -0.0251, ('WR', 1): 0.3377, ('TE', 0): 0.4468,
        ('TE', 1): 0.4082}
MIN_QB, MIN_SKILL = 100, 30
# pSV/60 (QBs): the predictive pair of SV, as NFL pXP/60 is of rXP/60. Points over replacement a play over seasons S, S-1,
# S-2 (play weights 1 / .7 / .5; past seasons from scripts/data/sv_hist.json.gz), shrunk to the QB mean a play with K plays,
# x 60. Pre-registered (scripts/research/port_nov23/football/prereg.md C1), next season's rate, 2016-25 leave one season
# out, 1,714 QB/RB pairs: weighted MSE .0258 raw -> .0159 (paired t -11.7, 10 of 10 seasons), slope .96, K QB 650.
PSV_K, PSV_W = 650, (1.0, 0.7, 0.5)


def add_psv(qbs, y):
    """adds 'psv' (pSV/60) to each QB row in place; rows keep no field when the history file is missing"""
    import gzip
    try:
        H = [r for r in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'sv_hist.json.gz'), 'rt'))['cfb'] if r['g'] == 'QB']
    except (OSError, ValueError, KeyError):
        return
    tot, pl = sum(r['tot'] for r in H if r['pl'] > 0), sum(r['pl'] for r in H if r['pl'] > 0)
    if not pl:
        return
    m = tot / pl
    by = {(str(r['id']), r['y']): r for r in H}
    for q in qbs:
        P, S = q['tot'] * PSV_W[0], q['plays'] * PSV_W[0]
        for i, w in enumerate(PSV_W[1:], 1):
            h = by.get((str(q['id']), y - i))
            if h and h['pl'] > 0:
                P += w * h['tot']; S += w * h['pl']
        q['psv'] = round((P + PSV_K * m) / (S + PSV_K) * 60, 1)


def pts_per_win():
    """season points a win in FBS: 1 / the slope of win % on margin a game (data/cfb_war_backtest.json college fit; ~53)"""
    try:
        return 1 / json.load(open(os.path.join(ROOT, 'data', 'cfb_war_backtest.json')))['college']['slope']
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        return 52.9

DUP_N, DUP_SHARE = 110, 0.2   # duplicate team-games: run / pass plays a side above DUP_N (real games top out near 100) or repeats
COLS = ['season', 'week', 'season_type', 'game_id', 'pos_team', 'def_pos_team', 'home', 'away', 'home_team_id', 'away_team_id',
        'home_team_division', 'away_team_division', 'EPA', 'rush', 'pass', 'period', 'play_text', 'rush_player_id', 'rush_player', 'position_rush',
        'reception_player_id', 'reception_player', 'position_reception', 'target_player_id', 'target_player', 'position_target',
        'completion_player_id', 'completion_player', 'incompletion_player_id', 'incompletion_player', 'sack_taken_player_id',
        'sack_taken_player', 'interception_thrown_player_id', 'interception_thrown_player']


def nn(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def sid(x):
    x = nn(x)
    if x is None:
        return None
    return str(int(x)) if isinstance(x, float) else str(x)


def season_now():
    A = cfb_all.read_cfb_all()
    a = str(A.get('asof') or '')
    y = int(a[:4] or 0)
    return (y if (a[5:7] or '12') >= '07' else y - 1), A


def plays(path):
    import pyarrow.parquet as pq
    have = set(pq.ParquetFile(path).schema_arrow.names)
    t = pq.read_table(path, columns=[c for c in COLS if c in have]).to_pydict()
    out, key, fbs, tid = [], [], set(), {}
    for i in range(len(t['game_id'])):
        g = lambda k: nn(t[k][i]) if k in t else None  # noqa: E731
        for s in ('home', 'away'):
            if g(f'{s}_team_division') == 'fbs':
                fbs.add(g(s))
            if g(f'{s}_team_id') is not None:
                tid[g(s)] = sid(g(f'{s}_team_id'))
        if g('season_type') not in ('regular', 'postseason') or g('EPA') is None:
            continue
        if 'fbs' not in (g('home_team_division'), g('away_team_division')):
            continue
        db = g('pass') == 1
        if not db and g('rush') != 1:
            continue
        qb = qbn = None
        for k in ('completion', 'incompletion', 'sack_taken', 'interception_thrown'):
            if sid(g(f'{k}_player_id')):
                qb, qbn = sid(g(f'{k}_player_id')), g(f'{k}_player')
                break
        rec, recp, recn = None, None, None
        if db:
            for k in ('reception', 'target'):
                if sid(g(f'{k}_player_id')):
                    rec, recp, recn = sid(g(f'{k}_player_id')), g(f'position_{k}'), g(f'{k}_player')
                    break
        ru = sid(g('rush_player_id')) if not db else None
        out.append((g('game_id'), g('pos_team'), g('def_pos_team'), int(db), float(g('EPA')), qb if db else None, qbn,
                    ru, g('position_rush'), g('rush_player'), rec, recp, recn))
        key.append((g('period'), g('play_text')))
    # some team-games are in the release twice (two feeds merged; 2021 and 2025 worst, none in 2026 so far): a side with
    # more than DUP_N run / pass plays, or with more than DUP_SHARE of its plays repeating a (quarter, play text) it already
    # has (real games: ~0.05%), keeps each (quarter, play text) once
    n, u = Counter((r[0], r[1]) for r in out), defaultdict(set)
    for r, k in zip(out, key):
        u[(r[0], r[1])].add(k)
    dup = {sk for sk, c in n.items() if c > DUP_N or len(u[sk]) < (1 - DUP_SHARE) * c}
    seen, keep = set(), []
    for r, k in zip(out, key):
        if (r[0], r[1]) in dup:
            if (r[0], r[1]) + k in seen:
                continue
            seen.add((r[0], r[1]) + k)
        keep.append(r)
    return keep, fbs, tid


def main():
    y, B = season_now()
    os.makedirs(CACHE, exist_ok=True)
    h = cfb_mirror.head(y)
    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    if old.get('season') == y and old.get('etag') == h.get('etag') and '--force' not in sys.argv:
        import datetime as dt
        import checked                 # weekly release: a quiet week keeps the file fresh-stamped, asof stays the release
        w = checked.stamp(old, old, dt.datetime.now(dt.timezone.utc))
        if w is not None:
            with open(OUT, 'w') as fh:
                json.dump(w, fh, separators=(',', ':'), allow_nan=False)
        print(f'cfb_season_value: release unchanged ({h.get("modified")}), kept')
        return
    pq_path = os.path.join(CACHE, f'cfbfastr_pbp_{y}.parquet')
    cfb_mirror.download(y, pq_path)
    try:
        P, fbs, tid = plays(pq_path)
    finally:
        os.remove(pq_path)
    # positions: each player's most common one this season
    pc = defaultdict(Counter)
    nm = {}
    for gid, ot, dt, db, epa, qb, qbn, ru, rup, run, rec, recp, recn in P:
        if qb:
            pc[qb]['QB'] += 1; nm[qb] = (qbn, ot)
        if ru and rup:
            pc[ru][rup] += 1; nm[ru] = (run, ot)
        if rec and recp:
            pc[rec][recp] += 1; nm[rec] = (recn, ot)
    POS = {}
    for i, c in pc.items():
        p = c.most_common(1)[0][0]
        POS[i] = 'QB' if p == 'QB' else 'RB' if p in ('RB', 'FB') else p if p in ('WR', 'TE') else ''
    A = defaultdict(lambda: [0.0, 0])
    for gid, ot, dt, db, epa, *_ in P:
        for key in (('d', dt, db), ('dg', gid, dt, db), ('l', db)):
            A[key][0] += epa; A[key][1] += 1

    def rel(t, gid, k):
        s, n = A[('d', t, k)]; sg, ng = A[('dg', gid, t, k)]
        m = A[('l', k)][0] / A[('l', k)][1] if A[('l', k)][1] else 0.0
        return ((s - sg) - m * (n - ng)) / (n - ng + K_DEF)
    V = defaultdict(lambda: defaultdict(float))
    GP = defaultdict(Counter)
    for gid, ot, dt, db, epa, qb, qbn, ru, rup, run, rec, recp, recn in P:
        ids = {i for i in ((qb if db else None), ru, rec) if i}
        for i in ids:
            g = POS.get(i)
            if g not in ('QB', 'RB', 'WR', 'TE'):
                continue
            a = epa - (rel(dt, gid, db) if g in OPP else 0.0)
            X = V[i]; X['a'] += a; X['n'] += 1; X['raw'] += epa
            X['par'] += a - (REPL['QB'] if g == 'QB' else REPL[(g, db)])
            X[f'a{db}'] += a; X[f'n{db}'] += 1
            if g == 'QB' and db:
                X['db'] += 1
            GP[i][gid] += 1
    # board join by ESPN id
    c = B['cols']
    board = {}
    for r in B['rows']:
        p = dict(zip(c, r))
        m = re.search(r'/id/(\d+)', p.get('espnl') or '')
        if m:
            board[m.group(1)] = p
    r1 = lambda x, k=1: None if x is None else round(x, k)  # noqa: E731
    qbs, skill = [], []
    PPW = pts_per_win()
    for i, X in V.items():
        g = POS[i]
        n, t = nm.get(i, (None, None))
        if t not in fbs or not n:
            continue
        b = board.get(i, {})
        gp = sum(1 for v in GP[i].values() if v >= (10 if g == 'QB' else 1)) or 1
        base = {'id': i, 'n': b.get('name') or n, 't': t, 'lo': b.get('logo') or (f'/img/cfb/logos/{tid[t]}.png' if tid.get(t) else None),
                'conf': b.get('conf'), 'cls': b.get('cls'), 'war': b.get('war'), 'waa': b.get('waa'),
                'ph': f'https://a.espncdn.com/combiner/i?img=/i/headshots/college-football/players/full/{i}.png&w=96&h=70&scale=crop&cquality=60' if b.get('photo') else None,
                'pts': r1(X['par'] / gp), 'tot': r1(X['par']), 'svar': r1(X['par'] / PPW, 2), 'aepa': r1(X['a'] / X['n'], 3), 'g': gp, 'plays': int(X['n'])}
        if g == 'QB' and X['n'] >= MIN_QB:
            qbs.append(dict(base, epa=r1(X['raw'] / X['n'], 3), db=int(X['db']), runs=int(X['n0'])))
        elif g in ('RB', 'WR', 'TE') and X['n'] >= MIN_SKILL:
            skill.append(dict(base, pos=g, ra=r1(X['a0'] / X['n0'], 3) if X['n0'] else None, ta=r1(X['a1'] / X['n1'], 3) if X['n1'] else None,
                              car=int(X['n0']), tgt=int(X['n1'])))
    for L in (qbs, skill):
        L.sort(key=lambda r: -r['pts'])
    add_psv(qbs, y)
    try:
        asof = email.utils.parsedate_to_datetime(h.get('modified')).strftime('%Y-%m-%d')
    except (TypeError, ValueError):
        asof = None
    out = {'season': y, 'asof': asof, 'etag': h.get('etag'), 'qbs': qbs, 'skill': skill}
    with open(OUT, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'), allow_nan=False)
    print(f'cfb_season_value: {len(qbs)} QBs ({MIN_QB}+ plays), {len(skill)} skill players ({MIN_SKILL}+), '
          f'{sum(1 for r in qbs + skill if r["war"] is not None)} on the board')


if __name__ == '__main__':
    if '--psv' in sys.argv:          # add pSV/60 to the file on hand (no release pull)
        d = json.load(open(OUT))
        add_psv(d['qbs'], d['season'])
        with open(OUT, 'w') as fh:
            json.dump(d, fh, separators=(',', ':'), allow_nan=False)
    else:
        main()
