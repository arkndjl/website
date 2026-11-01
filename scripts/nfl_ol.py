#!/usr/bin/env python3
"""Offensive line play parts for NFL XV (scripts/nfl_xv.py): what the five on the field allowed, from nflverse
play-by-play and participation (who was on the field, was_pressure), 2018 on.

    python3 scripts/nfl_ol.py [years]     # scripts/.cache/nfl/ol_<y>.json, {gsis|team: parts}
    python3 scripts/nfl_ol.py --test      # stability and next-season unit tests: scripts/.cache/nfl/ol_test.json

Per season, each outcome is fit with a ridge on every play (RAPM-style): the outcome on the offensive linemen on the
field, the passer (dropbacks) or ball carrier (runs) and the defense, each shrunk toward 0 (LAM plays). A lineman's
coefficient is his part, oriented up = good; linemen who always play together split the unit's result evenly, so it
falls back to the snap-weighted unit stat where there is no rotation to tell them apart.

  prs    pressure on dropbacks (was_pressure, or a sack or QB hit)
  sk     sack on dropbacks
  ly     line yards a designed run (losses x 1.2, 0-4 yards full, 5-10 half, past 10 none: the runner's part removed)
  repa   EPA a designed run
  pepa   EPA a dropback
  gap    line yards over the team's mean on designed runs at his spot (run_location + run_gap, his depth-chart spot)
  u_*    the raw on-field unit rates (snap-weighted team attribution, no adjustment); u_ybc: the team's yards before
         contact a carry (PFR advanced rushing) in the games he played

    python3 scripts/nfl_ol.py --test --xv  # data/nfl_ol_backtest.json (parts: stability, unit, contracts; xv: XV variants)
    OL_CLEAN=1 OL_TAG=_clean python3 scripts/nfl_ol.py   # the same parts from healthy-line games only (see --xv)

Results (2026-11-01, 2018-25): nothing passes, so XV keeps penalties as the only OL part and AV keeps snaps.
  stability   year to year among regulars, all / changed teams: unit rates .24-.33 / .04-.12 (the team, not the player);
              ridge parts .02-.16 / .05-.16; gap .08 / .00; penalties .33 / .31 (the one individual trait that repeats)
  unit        next season's unit pressure rate or line yards from the returning linemen's parts, beyond last season's
              unit rate and returning share (leave one season out): best ridge pressure (lam 1000) R^2 .073 -> .120,
              t 1.7; every line-yards part loses
  contracts   rank among linemen of the next veteran deal (274): unit line yards .27, run EPA .21 against AV WAR .27 and
              snap share .40; beyond snap share the parts add .03-.25 partial r, under playing time
  XV          each variant refit in nfl_xv.py's backtest, only the linemen's values changed. The board blend's missed-games
              t against the shipped values:
                same games    pass EPA 8.6: circular, a part read off on/off splits that include the very games he
                              missed, so the test scores itself
                last season   -.7 to .6: parts that don't repeat carry no value into the next season's absences
                clean         healthy-line games only (no circularity): 1.2-1.9 (unit pressure + line yards + pass EPA
                              XV alone 2.2, but the blend 1.85, forward R^2 -.004, t -1.5, and pass EPA is the QB's);
                              yards before contact .2
"""

import csv
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_war as W   # noqa: E402

CACHE = W.CACHE
REL = W.REL
YEARS = list(range(2018, 2026))
OLPOS = {'T', 'G', 'C', 'OT', 'OG', 'OL', 'LT', 'RT', 'LG', 'RG'}
LAM = {'prs': 300, 'sk': 600, 'ly': 300, 'repa': 300, 'pepa': 300}
NUIS = 50   # ridge on the passer, ball carrier and defense
ALIAS = {'LV': 'OAK', 'OAK': 'LV', 'LA': 'LAR', 'LAR': 'LA', 'LAC': 'SD', 'SD': 'LAC'}


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def line_yards(y):
    if y < 0:
        return 1.2 * y
    return min(y, 4) + 0.5 * max(0.0, min(y, 10) - 4)


def ol_ids(y):
    """gsis ids of the season's offensive linemen (roster position), and each one's depth-chart spot (LT LG C RG RT)."""
    ids = set()
    for r in W.rows(W.get(f'roster_{y}.csv', f'{REL}/rosters/roster_{y}.csv')):
        if r['position'] in OLPOS or r.get('depth_chart_position') in OLPOS:
            ids.add(r['gsis_id'])
    spot = defaultdict(Counter)
    p = W.get(f'depth_charts_{y}.csv', f'{REL}/depth_charts/depth_charts_{y}.csv')
    for r in W.rows(p):
        d = (r.get('depth_position') or r.get('pos_abb') or '').strip()
        if d in ('LT', 'LG', 'C', 'RG', 'RT') and r.get('gsis_id'):
            if 'depth_team' in r and r['depth_team'] not in ('1', '2'):
                continue
            spot[r['gsis_id']][d] += 1 if r.get('depth_team', '1') == '1' else 0.3
    return ids, {g: c.most_common(1)[0][0] for g, c in spot.items()}


def gap_spot(loc, gap):
    if loc == 'middle':
        return 'C'
    if loc not in ('left', 'right'):
        return None
    s = loc[0].upper()
    return s + ('G' if gap == 'guard' else 'T') if gap in ('guard', 'tackle', 'end') else None


def plays(y):
    """Dropbacks and designed runs with the offensive linemen on the field."""
    part = {}
    with open(W.get(f'pbp_participation_{y}.csv', f'{REL}/pbp_participation/pbp_participation_{y}.csv')) as f:
        for r in csv.DictReader(f):
            part[(r['nflverse_game_id'], r['play_id'])] = (r['offense_players'].split(';') if r['offense_players'] else [], r['was_pressure'])
    ol, spot = ol_ids(y)
    out = []
    with gzip.open(W.get(f'play_by_play_{y}.csv.gz', f'{REL}/pbp/play_by_play_{y}.csv.gz'), 'rt', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['season_type'] != 'REG' or r['two_point_attempt'] == '1' or r['qb_spike'] == '1' or r['qb_kneel'] == '1':
                continue
            pp = part.get((r['game_id'], r['play_id']))
            if not pp:
                continue
            line = [g for g in pp[0] if g in ol]
            if not 4 <= len(line) <= 7:
                continue
            epa = fnum(r['epa'])
            if epa is None:
                continue
            if r['qb_dropback'] == '1' and r['play_type'] in ('pass', 'qb_spike') or (r['qb_dropback'] == '1' and r['qb_scramble'] == '1'):
                if not r['passer_player_id'] and not r['rusher_player_id']:
                    continue
                sack = r['sack'] == '1'
                prs = pp[1] == 'TRUE' or sack or r['qb_hit'] == '1'
                out.append({'k': 'db', 'gid': r['game_id'], 't': r['posteam'], 'd': r['defteam'], 'who': r['passer_player_id'] or r['rusher_player_id'], 'ol': line,
                            'prs': float(prs), 'sk': float(sack), 'pepa': epa})
            elif r['play_type'] == 'run' and r['qb_scramble'] != '1' and r['rusher_player_id']:
                yg = fnum(r['yards_gained']) or 0.0
                out.append({'k': 'ru', 'gid': r['game_id'], 't': r['posteam'], 'd': r['defteam'], 'who': r['rusher_player_id'], 'ol': line,
                            'ly': line_yards(yg), 'repa': epa, 'gap': gap_spot(r['run_location'], r['run_gap'])})
    return out, spot


def ridge(P, outcome, lam, lam_who=300):
    """{(season, gsis): coefficient} for the linemen, pooled over seasons: a lineman a season, the passer or ball
    carrier over his career (so a QB's own pressure rate is told apart from his line's by his other lines) and the
    defense a season, each shrunk toward 0 (lineman lam, passer/runner lam_who, defense NUIS plays)."""
    import numpy as np
    idx = {}
    for p in P:
        for g in p['ol']:
            idx.setdefault(('o', p['y'], g), len(idx))
    n_ol = len(idx)
    for p in P:
        idx.setdefault(('w', p['who']), len(idx)); idx.setdefault(('d', p['y'], p['d']), len(idx))
    n = len(idx)
    M = np.zeros((n, n)); v = np.zeros(n)
    Y = np.array([p[outcome] for p in P])
    mu = defaultdict(lambda: [0.0, 0])
    for p, yv in zip(P, Y):
        mu[p['y']][0] += yv; mu[p['y']][1] += 1
    for p, yv in zip(P, Y):
        yv -= mu[p['y']][0] / mu[p['y']][1]
        cols = [idx[('o', p['y'], g)] for g in p['ol']] + [idx[('w', p['who'])], idx[('d', p['y'], p['d'])]]
        v[cols] += yv
        M[np.ix_(cols, cols)] += 1
    reg = np.full(n, float(NUIS)); reg[:n_ol] = lam
    reg[[i for k, i in idx.items() if k[0] == 'w']] = lam_who
    beta = np.linalg.solve(M + np.diag(reg), v)
    return {(k[1], k[2]): float(beta[i]) for k, i in idx.items() if k[0] == 'o'}


def clean_games(P):
    """drop the team-games where one of the team's five most-used linemen sat the whole game, so a part is never
    read off the games a missed-games test then scores (the on/off split there would make the test circular)"""
    used, onf = defaultdict(Counter), defaultdict(set)
    for p in P:
        for g in p['ol']:
            used[p['t']][g] += 1
            onf[(p['t'], p['gid'])].add(g)
    top = {t: {g for g, _ in c.most_common(5)} for t, c in used.items()}
    return [p for p in P if top[p['t']] <= onf[(p['t'], p['gid'])]]


def build(ys):
    ALLP, spots, out = [], {}, {y: defaultdict(lambda: defaultdict(float)) for y in ys}
    for y in ys:
        P, spot = plays(y)
        if os.environ.get('OL_CLEAN') == '1':
            P = clean_games(P)
        spots[y] = spot
        for p in P:
            p['y'] = y
        db = [p for p in P if p['k'] == 'db']; ru = [p for p in P if p['k'] == 'ru']
        print(f'ol {y}: {len(db)} dropbacks, {len(ru)} runs', flush=True)
        O = out[y]
        # on-field counts and raw on-field unit rates (the snap-weighted unit attribution)
        for p in db:
            for g in p['ol']:
                o = O[g + '|' + p['t']]; o['ndb'] += 1; o['rprs'] -= p['prs']; o['rsk'] -= p['sk']; o['rpepa'] += p['pepa']
        for p in ru:
            for g in p['ol']:
                o = O[g + '|' + p['t']]; o['nru'] += 1; o['rly'] += p['ly']; o['rrepa'] += p['repa']
        # gap: line yards over the team's mean on runs at his spot, while he was on the field
        tm = defaultdict(lambda: [0.0, 0])
        for p in ru:
            a = tm[p['t']]; a[0] += p['ly']; a[1] += 1
        for p in ru:
            if p['gap']:
                m = tm[p['t']][0] / tm[p['t']][1]
                for g in p['ol']:
                    if spot.get(g) == p['gap']:
                        o = O[g + '|' + p['t']]; o['ngap'] += 1; o['gap'] += p['ly'] - m
        ALLP += P
    db = [p for p in ALLP if p['k'] == 'db']; ru = [p for p in ALLP if p['k'] == 'ru']
    for part, P_, sgn in (('prs', db, -1), ('sk', db, -1), ('pepa', db, 1), ('ly', ru, 1), ('repa', ru, 1)):
        for lam in (100, 300, 1000):
            cf = ridge(P_, part, lam)
            for y in ys:
                for k, o in out[y].items():
                    c = cf.get((y, k.split('|')[0]))
                    if c is not None:
                        o[f'{part}_{lam}'] = sgn * c
            print(f'ridge {part} {lam}', flush=True)
    for y in ys:
        with open(os.path.join(CACHE, f'ol_{y}{os.environ.get("OL_TAG", "")}.json'), 'w') as f:
            json.dump({'spot': spots[y], 'players': {k: dict(o) for k, o in out[y].items()}}, f, separators=(',', ':'))


def load(y):
    p = os.path.join(CACHE, f'ol_{y}{os.environ.get("OL_TAG", "")}.json')
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)['players']


def lookup(D, gsis, t):
    """a player's parts from the season's table by gsis and team (franchise aliases)."""
    if not D:
        return {}
    return D.get(gsis + '|' + t) or D.get(gsis + '|' + ALIAS.get(t, t)) or {}


# ---------------------------------------------------------------- tests
def parts_of(o, lam=300):
    """{part: (rate up = good, sample)} from a lineman's table row."""
    per = lambda a, n: (o.get(a, 0.0) / o[n], o[n]) if o.get(n) else (None, 0)
    out = {'u_prs': per('rprs', 'ndb'), 'u_sk': per('rsk', 'ndb'), 'u_pepa': per('rpepa', 'ndb'), 'u_ly': per('rly', 'nru'),
           'u_repa': per('rrepa', 'nru'), 'gap': per('gap', 'ngap')}
    for part, n in (('prs', 'ndb'), ('sk', 'ndb'), ('pepa', 'ndb'), ('ly', 'nru'), ('repa', 'nru')):
        for L in (100, 300, 1000):
            k = f'{part}_{L}'
            out[k] = (o[k], o.get(n, 0)) if k in o else (None, 0)
    return out


def corr(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a)); sb = math.sqrt(sum((x - mb) ** 2 for x in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else None


def tests():
    import numpy as np
    import nfl_xv as XV
    S = XV.load()
    T = {y: load(y) for y in S}
    # lineman seasons (summed over teams for the year-to-year test)
    rows = {}
    for y, d in S.items():
        for p in d['players']:
            if XV.GROUP_OF[p['sub']] != 'OL':
                continue
            o = lookup(T[y], p['gsis'], p['t'])
            if o:
                p['ol'] = parts_of(o)
                rows.setdefault((y, p['pfr']), []).append(p)
    names = list(next(iter(rows.values()))[0]['ol']) + ['pen']
    def val(p, k):
        if k == 'pen':
            return (-p['c'].get('pen', 0.0) / max(1.0, p['snaps']), p['snaps'])
        return p['ol'][k]
    res = {'stability': {}, 'stabilityMovers': {}}
    for k in names:
        a, b, am, bm = [], [], [], []
        for (y, pfr), L in rows.items():
            nxt = rows.get((y + 1, pfr))
            if not nxt:
                continue
            p, q = max(L, key=lambda r: r['snaps']), max(nxt, key=lambda r: r['snaps'])
            if p['share'] < 0.4 or q['share'] < 0.4:
                continue
            u, v = val(p, k), val(q, k)
            if u[0] is None or v[0] is None:
                continue
            a.append(u[0]); b.append(v[0])
            if p['t'] != q['t']:
                am.append(u[0]); bm.append(v[0])
        res['stability'][k] = {'n': len(a), 'r': round(corr(a, b), 3)}
        res['stabilityMovers'][k] = {'n': len(am), 'r': round(corr(am, bm), 3) if len(am) > 5 else None}
    # next season's unit: pressure rate allowed and line yards a run, from the returning linemen's parts last season
    unit = {}
    for y in S:
        U = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for key, o in (T[y] or {}).items():
            t = key.split('|')[1]
            u = U[t]; u[0] += -o.get('rprs', 0.0); u[1] += o.get('ndb', 0.0); u[2] += o.get('rly', 0.0); u[3] += o.get('nru', 0.0)
        unit[y] = {t: (u[0] / u[1], u[2] / u[3]) for t, u in U.items() if u[1] and u[3]}
    zs = {}
    for k in names:
        # z of a lineman season on the regulars' pool (40%+), shrunk by sample as XV does
        Kk = 300 if k != 'gap' else 60
        for y in S:
            L = [p for (yy, _), ps in rows.items() if yy == y for p in ps]
            pool = [val(p, k)[0] for p in L if p['share'] >= 0.4 and val(p, k)[0] is not None]
            if len(pool) < 8:
                continue
            m = sum(pool) / len(pool); s = math.sqrt(sum((x - m) ** 2 for x in pool) / len(pool)) or 1
            for p in L:
                r, n = val(p, k)
                zs[(k, y, p['pfr'])] = 0.0 if r is None else max(-3, min(3, (r - m) / s)) * n / (n + Kk)
    fw = {}
    for target, ti in (('prs', 0), ('ly', 1)):
        fw[target] = {}
        for k in names + ['none']:
            R = []
            for y in sorted(S):
                if y + 1 not in S:
                    continue
                for t, cur in unit[y + 1].items():
                    last = unit[y].get(t) or unit[y].get(ALIAS.get(t, t))
                    if not last:
                        continue
                    ret, sh = 0.0, 0.0
                    for p in S[y + 1]['players']:
                        if p['t'] != t or XV.GROUP_OF[p['sub']] != 'OL':
                            continue
                        if (k, y, p['pfr']) in zs or k == 'none':
                            prev = [q for q in rows.get((y, p['pfr']), [])]
                            if prev:
                                ret += p['share'] * (zs.get((k, y, p['pfr']), 0.0) if k != 'none' else 0.0); sh += p['share']
                    R.append((y, [last[ti], sh] + ([ret] if k != 'none' else []), cur[ti]))
            e = []
            for y in sorted({r[0] for r in R}):
                tr = [r for r in R if r[0] != y]; te = [r for r in R if r[0] == y]
                A = np.array([[1] + r[1] for r in tr]); b_ = np.array([r[2] for r in tr])
                cf = np.linalg.lstsq(A, b_, rcond=None)[0]
                e += [(r[2] - np.array([1] + r[1]) @ cf) ** 2 for r in te]
            tg = np.array([r[2] for r in R])
            fw[target][k] = np.array(e), 1 - float(np.mean(e)) / float(tg.var())
        base = fw[target]['none'][0]
        res.setdefault('unitForward', {})[target] = {k: {'r2': round(v[1], 4), 't': round(float((base - v[0]).mean() / ((base - v[0]).std() / math.sqrt(len(base)))), 2) if k != 'none' else None}
                                                      for k, v in fw[target].items()}
    # contracts: rank among linemen of the next veteran deal (cap %) on the part (30%+ of the snaps), against AV WAR
    import gzip, io
    raw = gzip.open(W.get('historical_contracts.csv.gz', W.CONTRACTS)).read().decode('utf-8')
    con = {}
    for c_ in csv.DictReader(io.StringIO(raw)):
        try:
            ys_, cap, dy = int(c_['year_signed']), float(c_['apy_cap_pct']), c_['draft_year']
        except ValueError:
            continue
        if dy not in ('', 'NA') and ys_ - int(dy) >= 3 and c_['position'] in ('LT', 'RT', 'T', 'OT', 'G', 'LG', 'RG', 'C', 'OL', 'IOL'):
            con.setdefault((W.NM.key(c_['player']), ys_), []).append(cap)
    M = []
    for (y, pfr), L in rows.items():
        p = max(L, key=lambda r: r['snaps'])
        c_ = max(con.get((W.NM.key(p['n']), y + 1), []), default=None)
        if c_ and sum(q['share'] for q in L) >= 0.3:
            M.append((p, y, c_))
    rank = lambda v: list(np.argsort(np.argsort(v)) / len(v))
    rc = rank([c for _, _, c in M])
    mk = {'contracts': len(M), 'war': round(corr(rank([p['war'] for p, _, _ in M]), rc), 3), 'share': round(corr(rank([p['share'] for p, _, _ in M]), rc), 3)}
    for k in names:
        z = [zs.get((k, y, p['pfr']), 0.0) for p, y, _ in M]
        mk[k] = round(corr(rank(z), rc), 3)
        # beyond playing time: partial on share
        sh = rank([p['share'] for p, _, _ in M]); zr = rank(z)
        A = np.column_stack([np.ones(len(M)), sh]); 
        r1 = np.array(zr) - A @ np.linalg.lstsq(A, np.array(zr), rcond=None)[0]; r2 = np.array(rc) - A @ np.linalg.lstsq(A, np.array(rc), rcond=None)[0]
        mk[k + ':partialShare'] = round(corr(list(r1), list(r2)), 3)
    res['market'] = mk
    return res


def ybc(y):
    """{pfr|team: [yards before contact, carries]}: the team's runs (PFR advanced rushing, by game) in the games where
    its five most-used linemen all played, credited to each lineman who played them"""
    tg = defaultdict(lambda: [0.0, 0.0])
    for r in W.rows(W.get(f'advstats_week_rush_{y}.csv', f'{REL}/pfr_advstats/advstats_week_rush_{y}.csv')):
        if r['game_type'] == 'REG':
            a = tg[(r['pfr_game_id'], r['team'])]; a[0] += W.num(r['rushing_yards_before_contact']); a[1] += W.num(r['carries'])
    snaps, tot = defaultdict(dict), defaultdict(Counter)
    for r in W.rows(W.get(f'snap_counts_{y}.csv', f'{REL}/snap_counts/snap_counts_{y}.csv')):
        if r['game_type'] == 'REG' and r['position'] in ('T', 'G', 'C', 'OL') and W.num(r['offense_snaps']) > 0:
            snaps[(r['pfr_game_id'], r['team'])][r['pfr_player_id']] = 1; tot[r['team']][r['pfr_player_id']] += W.num(r['offense_snaps'])
    top = {t: {p for p, _ in c.most_common(5)} for t, c in tot.items()}
    out = defaultdict(lambda: [0.0, 0.0])
    for (gid, t), pl in snaps.items():
        a = tg.get((gid, t)) or tg.get((gid, ALIAS.get(t, t)))
        if a and top[t] <= set(pl):
            for q in pl:
                o = out[q + '|' + t]; o[0] += a[0]; o[1] += a[1]
    return out


# ---------------------------------------------------------------- XV tests
# variants: (OL parts beside penalties, shrink K, table: '' all games / '_clean' healthy-line games, lag: last season's parts)
VARIANTS = {
    'pepa (same games)': (['pepa_300'], 50, '', False),
    'prs+ly+pepa (same games)': (['prs_1000', 'ly_1000', 'pepa_300'], 50, '', False),
    'unit prs+ly+pepa (same games)': (['u_prs', 'u_ly', 'u_pepa'], 300, '', False),
    'pepa (last season)': (['pepa_300'], 50, '', True),
    'prs+ly+pepa (last season)': (['prs_1000', 'ly_1000', 'pepa_300'], 50, '', True),
    'unit prs+ly+pepa (last season)': (['u_prs', 'u_ly', 'u_pepa'], 300, '', True),
    'prs+sk (last season)': (['prs_300', 'sk_300'], 50, '', True),
    'gap (last season)': (['gap'], 60, '', True),
    'pepa (clean)': (['pepa_300'], 50, '_clean', False),
    'prs+ly+pepa (clean)': (['prs_1000', 'ly_1000', 'pepa_300'], 50, '_clean', False),
    'prs+sk (clean)': (['prs_300', 'sk_300'], 50, '_clean', False),
    'unit prs+ly+pepa (clean)': (['u_prs', 'u_ly', 'u_pepa'], 300, '_clean', False),
    'unit prs+sk+ly (clean)': (['u_prs', 'u_sk', 'u_ly'], 300, '_clean', False),
    'unit ybc (clean)': (['u_ybc'], 150, '_clean', False),
    'unit ybc+prs+sk (clean)': (['u_ybc', 'u_prs', 'u_sk'], 300, '_clean', False),
}


def xv_run(extra, Kx, tag, lag, YB):
    """nfl_xv's backtest with the OL parts extra beside penalties; held-out XV (season out, and next season out too)"""
    import nfl_xv as XV
    parts0, K0, rates0 = list(XV.PARTS['OL']), dict(XV.K), XV.rates
    XV.PARTS['OL'] = ['pen'] + extra
    for e in extra:
        XV.K[e] = Kx
    XV.COLS[:] = [(g, part) for g in XV.GROUPS for part in XV.PARTS[g]]
    T = {}

    def rates(p):
        r = rates0(p)
        if XV.GROUP_OF[p['sub']] == 'OL' and extra:
            y = p['y'] - 1 if lag else p['y']
            if y not in T:
                os.environ['OL_TAG'] = tag; T[y] = load(y) or {}
            if lag:
                c = [v for k, v in T[y].items() if k.split('|')[0] == p['gsis']]
                o = max(c, key=lambda v: v.get('ndb', 0)) if c else None
            else:
                o = lookup(T[y], p['gsis'], p['t'])
            pp = parts_of(o) if o else {}
            v = YB.get(y, {}).get(p['pfr'] + '|' + p['t'])
            pp['u_ybc'] = (v[0] / v[1], v[1]) if v and v[1] else (None, 0)
            for e in extra:
                r[e] = pp.get(e, (None, 0))
        return r
    XV.rates = rates
    try:
        res, model = XV.backtest()
        S = XV.load(); XV.zscore(S); _, value, _ = W.sub_lines()
        xv, xvf = {}, {}
        for y in sorted(S):
            xv[y] = XV.xv_of(S, y, XV.fit_w(S, [v for v in S if v != y], model['lambda']), value)
            xvf[y] = XV.xv_of(S, y, XV.fit_w(S, [v for v in S if v not in (y, y + 1)], model['lambda']), value)
    finally:
        XV.PARTS['OL'], XV.rates = parts0, rates0
        XV.K.clear(); XV.K.update(K0)
        XV.COLS[:] = [(g, part) for g in XV.GROUPS for part in XV.PARTS[g]]
    return res, model, xv, xvf


def xv_tests():
    """each variant against the shipped XV, with only the linemen's values changed (the rest of the lineup kept at the
    shipped XV): missed games together (does the new OL value survive the old), forward and contracts, on XV and on
    the board blend (.4 XV + .6 AV WAR)"""
    import nfl_xv as XV
    YB = {y: ybc(y) for y in YEARS}
    S = XV.load()
    war = {y: [p['war'] for p in S[y]['players']] for y in S}
    isol = {y: [XV.GROUP_OF[p['sub']] == 'OL' for p in S[y]['players']] for y in S}
    _, _, base, basef = xv_run([], 0, '', False, YB)
    mix = lambda V, B: {y: [v if o else b for v, b, o in zip(V[y], B[y], isol[y])] for y in S}
    blend = lambda D: {y: [.4 * a + .6 * b for a, b in zip(D[y], war[y])] for y in S}
    sd = lambda D: round(float(__import__('statistics').pstdev([D[y][i] for y in S for i, p in enumerate(S[y]['players']) if isol[y][i] and p['share'] >= .4])), 3)
    out = {'olSdShipped': sd(base)}
    for name, (extra, Kx, tag, lag) in VARIANTS.items():
        _, model, xv, xvf = xv_run(extra, Kx, tag, lag, YB)
        h, hf = mix(xv, base), mix(xvf, basef)
        if all(abs(a - b) < 1e-9 for y in S for a, b in zip(h[y], base[y])):
            out[name] = {'weights': {k: v for k, v in model['weights'].items() if k.startswith('OL.')}, 'sameAsShipped': True}
            continue
        m = XV.missed_test(S, {'base': base, 'new': h})
        mb = XV.missed_test(S, {'base': blend(base), 'new': blend(h)})
        out[name] = {'weights': {k: v for k, v in model['weights'].items() if k.startswith('OL.')}, 'olSd': sd(h),
                     'missed': m['new'], 'missedTogether': m['together']['new'], 'missedTogetherBlend': mb['together']['new'],
                     'forward': XV.forward_test(S, {'base': basef, 'new': hf})['new'],
                     'forwardBlend': XV.forward_test(S, {'base': blend(basef), 'new': blend(hf)})['new'],
                     'market': XV.market_test(S, {'base': base, 'new': h})}
        print(name, json.dumps(out[name]), flush=True)
    return out


if __name__ == '__main__':
    ys = [int(a) for a in sys.argv[1:] if a.isdigit()] or YEARS
    if '--test' in sys.argv or '--xv' in sys.argv:
        import datetime
        res = {'asof': datetime.date.today().isoformat()}
        if '--test' in sys.argv:
            res['parts'] = tests()
        if '--xv' in sys.argv:
            res['xv'] = xv_tests()
        dst = os.path.join(W.ROOT, 'data', 'nfl_ol_backtest.json')
        old = json.load(open(dst)) if os.path.exists(dst) else {}
        old.update(res)
        with open(dst, 'w') as f:
            json.dump(old, f, indent=1)
            f.write('\n')
    else:
        build(ys)
