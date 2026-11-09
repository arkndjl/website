#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Special teams tab: kick and punt returners ranked by points over expected a return, shrunk for sample.

    python3 scripts/st_returners.py nfl     # nflverse play-by-play -> data/st_returners_nfl.json (run by nfl.yml)
    python3 scripts/st_returners.py cfb     # ESPN play-by-play cache -> data/st_returners_cfb.json (run by cfb-board.yml)

A return = a kickoff or punt the returner fielded and ran back, or muffed (fair catches, touchbacks, kicks nobody fielded
and plays with a penalty are left out: the call, not the run, decides those). Each return is worth points to the
receiving team:
  NFL  nflverse EPA from the receiving side (fumbles, TDs and field position all in).
  CFB  drive points by field position: D(x) = mean points scored on drives starting x yards from the goal (TD 7, FG 3),
       fit on every ESPN drive of the season and the one before; value = D(end of return), a TD 7, a lost fumble -D(100 - spot).
Expected = the mean value of returns fielded at the same spot (5-yard bins, by season and kick type), so the kick's
distance and hang are not the returner's. Points over expected (POE) a return = value - expected; RYOE the same in yards.

Shrinkage: per-return POE is noise-heavy. Between-returner variance tau^2 is the method-of-moments estimate on
player-seasons (this season and the two before): var(player means) - mean(sigma^2 / n). Shrunk POE a return =
sum POE / (n + k), k = sigma^2 / tau^2 (returns at which half the observed rate is kept). Value = shrunk rate x returns.
Year-to-year r of per-return POE (returners with 8+ returns in both seasons) is reported beside k.
"""
import csv
import gzip
import json
import math
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
import names as NM  # noqa: E402

MIN_LIST = {'kr': 4, 'pr': 4}        # returns to be listed
TOP = 150                            # rows a view
BIN = 5


def season_now():
    import datetime
    d = datetime.date.today()
    return d.year if d.month >= 8 else d.year - 1


def f(x, d=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except (TypeError, ValueError):
        return d


# ------------------------------------------------------------------ shared math
def bin_of(catch):
    return int(max(0, min(110, catch)) // BIN)


def expected(rets):
    """Mean value and yards by (season, type, bin); thin bins borrow from (type, bin) over all seasons."""
    S, A = defaultdict(lambda: [0, 0.0, 0.0]), defaultdict(lambda: [0, 0.0, 0.0])
    for r in rets:
        b = bin_of(r['catch'])
        for D, k in ((S, (r['s'], r['k'], b)), (A, (r['k'], b))):
            D[k][0] += 1; D[k][1] += r['v']; D[k][2] += r['y']
    out = {}
    for r in rets:
        b = bin_of(r['catch'])
        n, v, y = S[(r['s'], r['k'], b)]
        if n < 25:
            n2, v2, y2 = A[(r['k'], b)]
            w = n / 25
            r['ev'] = w * v / max(n, 1) + (1 - w) * v2 / n2
            r['ey'] = w * y / max(n, 1) + (1 - w) * y2 / n2
        else:
            r['ev'], r['ey'] = v / n, y / n
        r['poe'], r['ryoe'] = r['v'] - r['ev'], r['y'] - r['ey']
    return out


def hyper(rets, kind, seasons, fld='ryoe'):
    """k = sigma^2 / tau^2 on player-seasons, and the year-to-year r of the per-return rate."""
    by = defaultdict(list)
    for r in rets:
        if r['k'] == kind and r['s'] in seasons:
            by[(r['p'], r['s'])].append(r[fld])
    within, wn, means = 0.0, 0, []
    for xs in by.values():
        n = len(xs)
        if n >= 2:
            m = sum(xs) / n
            within += sum((x - m) ** 2 for x in xs); wn += n - 1
    sig2 = within / wn
    for xs in by.values():
        if len(xs) >= 5:
            means.append((sum(xs) / len(xs), len(xs)))
    W = sum(n for _, n in means)
    mu = sum(m * n for m, n in means) / W
    # weighted moments: E[sum n (m - mu)^2] = (N - sum n^2 / N) tau^2 + (J - 1) sigma^2
    ss = sum(n * (m - mu) ** 2 for m, n in means)
    tau2 = max((ss - (len(means) - 1) * sig2) / (W - sum(n * n for _, n in means) / W), 1e-6)
    pairs = []
    for (p, s), xs in by.items():
        ys = by.get((p, s + 1))
        if ys and len(xs) >= 8 and len(ys) >= 8:
            pairs.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    r = None
    if len(pairs) >= 10:
        mx = sum(a for a, _ in pairs) / len(pairs); my = sum(b for _, b in pairs) / len(pairs)
        sxy = sum((a - mx) * (b - my) for a, b in pairs)
        sxx = sum((a - mx) ** 2 for a, _ in pairs); syy = sum((b - my) ** 2 for _, b in pairs)
        r = sxy / math.sqrt(sxx * syy) if sxx and syy else None
    # a season with no measurable spread would zero every row: hold k inside [5, 300] returns
    return {'k': round(min(300.0, max(5.0, sig2 / tau2)), 1), 'sd': round(math.sqrt(sig2), 3), 'tau': round(math.sqrt(tau2), 3),
            'r': None if r is None else round(r, 2), 'pairs': len(pairs), 'ps': len(means)}


def table(rets, kind, season, H, info):
    P = defaultdict(lambda: {'n': 0, 'y': 0, 'td': 0, 'fum': 0, 'lng': 0, 'poe': 0.0, 'ryoe': 0.0, 'v': 0.0})
    for r in rets:
        if r['k'] != kind or r['s'] != season:
            continue
        a = P[r['p']]
        a['n'] += 1; a['y'] += r['y']; a['td'] += r['td']; a['fum'] += r['fum']; a['lng'] = max(a['lng'], r['y'])
        a['poe'] += r['poe']; a['ryoe'] += r['ryoe']
        a.setdefault('t', r['t'])
    k = H['k']
    rows = []
    for p, a in P.items():
        if a['n'] < MIN_LIST[kind] or p not in info:
            continue
        sh = a['ryoe'] / (a['n'] + k)
        rows.append({**info[p], 'id': p, 'ret': a['n'], 'yds': int(a['y']), 'avg': round(a['y'] / a['n'], 1), 'lng': int(a['lng']),
                     'td': a['td'], 'fum': a['fum'], 'ryoe': round(a['ryoe'] / a['n'], 1), 'poe': round(a['poe'], 2),
                     'sry': round(sh, 2), 'val': round(sh * a['n'], 1)})
    rows.sort(key=lambda o: -o['sry'])
    return rows[:TOP], sum(1 for a in P.values() if a['n'] >= MIN_LIST[kind])


def write(sport, rets, season, info, note):
    out = {'asof': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'season': season, 'sport': sport, 'min': MIN_LIST, 'note': note}
    expected(rets)
    for kind in ('kr', 'pr'):
        ss = {season - 2, season - 1, season}
        H = hyper(rets, kind, ss)
        rows, n = table(rets, kind, season, H, info)
        out[kind] = {'h': H, 'hp': hyper(rets, kind, ss, 'poe'), 'rows': rows, 'n': n, 'ret': sum(1 for r in rets if r['k'] == kind and r['s'] == season)}
        print(sport, kind, H, len(rows), 'listed of', n, flush=True)
    p = os.path.join(ROOT, 'data', f'st_returners_{sport}.json')
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return out


# ------------------------------------------------------------------ NFL
def nfl():
    import nfl_war as W
    y = season_now()
    rets, seen = [], set()
    for s in (y - 2, y - 1, y):
        p = W.get(f'play_by_play_{s}.csv.gz', f'{W.REL}/pbp/play_by_play_{s}.csv.gz')
        rd = csv.reader(gzip.open(p, 'rt', encoding='utf-8'))
        h = next(rd); I = {c: i for i, c in enumerate(h)}
        for r in rd:
            ko, pu = r[I['kickoff_attempt']] == '1', r[I['punt_attempt']] == '1'
            if not (ko or pu) or r[I['penalty']] == '1' or r[I['touchback']] == '1':
                continue
            if r[I['kickoff_fair_catch' if ko else 'punt_fair_catch']] == '1' or r[I['punt_blocked']] == '1':
                continue
            pid = r[I['kickoff_returner_player_id' if ko else 'punt_returner_player_id']]
            epa, yl, dist = f(r[I['epa']]), f(r[I['yardline_100']]), f(r[I['kick_distance']])
            if pid in ('', 'NA') or epa is None or yl is None or dist is None:
                continue
            if r[I['lateral_return']] == '1':
                continue
            # receiver's yards to goal where the ball was fielded; nflverse posteam receives a kickoff, kicks a punt
            catch = yl + dist if ko else 100 - (yl - dist)
            v = epa if ko else -epa
            fum = 1 if r[I['fumble_lost']] == '1' and r[I['fumbled_1_player_id']] == pid else 0
            ry = f(r[I['return_yards']], 0.0)
            rt = W.tm(r[I['defteam']] if pu else r[I['posteam']]) if hasattr(W, 'tm') else (r[I['defteam']] if pu else r[I['posteam']])
            rets.append({'s': s, 'k': 'kr' if ko else 'pr', 'p': pid, 't': rt, 'catch': catch, 'y': ry, 'v': v,
                         'td': 1 if r[I['return_touchdown']] == '1' else 0, 'fum': fum, 'wk': int(r[I['week']])})
            if s == y:
                seen.add(pid)
    ros = {}
    for r in W.rows(W.get(f'roster_{y}.csv', f'{W.REL}/rosters/roster_{y}.csv')):
        if r['gsis_id']:
            ros[r['gsis_id']] = r
    last_t = {}
    for r in sorted((r for r in rets if r['s'] == y), key=lambda r: r['wk']):
        last_t[r['p']] = r['t']
    info = {}
    for pid in seen:
        r = ros.get(pid)
        if not r:
            continue
        info[pid] = {'n': r['full_name'], 'pos': r['position'] or r.get('depth_chart_position') or '', 't': last_t.get(pid, r['team']),
                     **({'ph': r['headshot_url'].rsplit('/', 1)[-1]} if 'static.www.nfl.com' in (r.get('headshot_url') or '') else {})}
    wk = max((r['wk'] for r in rets if r['s'] == y), default=0)
    return write('nfl', rets, y, info, {'week': wk, 'value': 'EPA'})


# ------------------------------------------------------------------ CFB
def cfb_returns(seasons, pull=True):
    """Every FBS return in these seasons from the ESPN play-by-play cache: (returns, drive-point curve D, unmatched names).
    pull=False reads only cached box-score returner ids (scripts/research/st_value: the 2011-22 history for the FV test)."""
    import cfb_espn_hist as EH
    PBP = os.path.join(EH.DIR, '..', 'espn_pbp')
    RET = os.path.join(EH.DIR, '..', 'espn_ret')
    os.makedirs(RET, exist_ok=True)

    def box_ret(gid):
        """Kick / punt returners in the box score, by team: ESPN athlete id and full name (one summary call, cached)."""
        p = os.path.join(RET, f'{gid}.json')
        if os.path.exists(p):
            return json.load(open(p))
        if not pull:
            return None
        d = EH.get(f'{EH.BASE}/summary?event={gid}')
        if d is None:
            return None
        out = {}
        for t in (d.get('boxscore') or {}).get('players') or []:
            for st in t.get('statistics') or []:
                if st.get('name') in ('kickReturns', 'puntReturns'):
                    for a in st.get('athletes') or []:
                        at = a.get('athlete') or {}
                        if at.get('id'):
                            out.setdefault(t['team']['id'], {})[at['id']] = at.get('displayName')
        json.dump(out, open(p, 'w'))
        return out

    games = []
    for s in seasons:
        gp = os.path.join(EH.DIR, f'games{s}.json')
        if not os.path.exists(gp):
            continue
        for g in json.load(open(gp)):
            if g.get('done') and g.get('grp') == 'fbs' and os.path.exists(os.path.join(PBP, f"{g['id']}.json.gz")):
                games.append((s, g))
    # drive points by start (yards to goal), for the value curve
    dp = defaultdict(lambda: [0, 0.0])
    load = lambda gid: json.load(gzip.open(os.path.join(PBP, f"{gid}.json.gz"), 'rt'))   # read twice, not held (10k games)
    for s, g in games:
        d = load(g['id'])
        for dr in d['drives']:
            pl = [p for p in dr['plays'] if (p.get('t') or '') not in ('Kickoff', 'Kickoff Return (Offense)', 'Punt', 'Punt Return')]
            if not pl or pl[0].get('dn') != 1 or not pl[0].get('yl') or str(pl[0].get('st')) != str(dr.get('tm')):
                continue
            res = (dr.get('res') or '').upper()
            pts = 7 if 'TD' in res or 'TOUCHDOWN' in res else 3 if res in ('FG', 'FIELD GOAL', 'FG GOOD') else 0
            if 'MISSED' in res:
                pts = 0
            x = int(pl[0]['yl'])
            if 1 <= x <= 99:
                dp[x][0] += 1; dp[x][1] += pts
    # smooth: mean in a +/-4 yard window, then made monotone (more points nearer the goal)
    D = {}
    for x in range(1, 100):
        n = sum(dp[z][0] for z in range(x - 4, x + 5)); v = sum(dp[z][1] for z in range(x - 4, x + 5))
        D[x] = v / n if n else None
    xs = [x for x in range(1, 100) if D[x] is not None]
    for x in range(1, 100):
        if D[x] is None:
            D[x] = D[min(xs, key=lambda z: abs(z - x))]
    for x in range(2, 100):
        D[x] = min(D[x], D[x - 1])
    D[0] = 7.0
    print('drive points: own 25', round(D[75], 2), 'midfield', round(D[50], 2), 'opp 20', round(D[20], 2), flush=True)

    def name_key(s):
        s = re.sub(r'^#\d+\s+', '', s.strip())
        t = [w for w in re.split(r'[\s.]+', NM.fold(s).lower()) if w and w not in ('jr', 'sr', 'ii', 'iii', 'iv')]
        return (t[0][0] + '|' + t[-1]) if len(t) >= 2 else ''

    NAME = r"(#\d+\s+)?([A-Z][A-Za-z'\-]*\.?(?:\s?[A-Z][A-Za-z'\-]*\.?)*?(?:\s(?:Jr\.?|Sr\.?|II|III|IV))?)"
    RX = [re.compile(NAME + r"\s+returns?\s+(?:for\s+)?(-?\d+)\s+(?:yards?|yds?)"),
          re.compile(NAME + r"\s+(-?\d+)\s+Yd\s+(?:Kickoff|Punt)\s+Return"),
          re.compile(r"muffed by\s+" + NAME),
          # ESPN's 2011-17 text: "kickoff for 50 yards returned by Jeremy Gallon for 12 yards to the Mich 27"
          re.compile(r"returned by\s+" + NAME + r"\s+for\s+(-?\d+|no gain)\s*(?:yards?|yds?)?")]
    KD = re.compile(r"(?:kickoff|punt)\s+(?:for\s+)?(\d+)\s+(?:yards?|yds?)", re.I)
    rets, miss = [], 0
    pend = [g for s, g in games]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(12) as ex:
        boxes = dict(zip([g['id'] for g in pend], ex.map(box_ret, [g['id'] for g in pend])))
    for s, g in games:
        d = load(g['id']); bx = boxes.get(g['id']) or {}
        tids = [t['id'] for t in d['teams']]
        keys = {tid: {name_key(nm): aid for aid, nm in (bx.get(tid) or {}).items()} for tid in tids}
        for dr in d['drives']:
            for p in dr['plays']:
                t = p.get('t') or ''; x = p.get('x') or ''
                ko = t.startswith('Kickoff'); pu = t.startswith('Punt')
                if not (ko or pu) or 'Blocked' in t or 'blocked' in x or p.get('pen') or 'PENALTY' in x.upper() or 'onside' in x.lower():
                    continue
                m = None; muff = False
                for i, rx in enumerate(RX):
                    m = rx.search(x)
                    if m:
                        muff = i == 2
                        break
                if not m:
                    continue
                ry = 0 if muff or m.group(3) == 'no gain' else int(m.group(3))
                td = 1 if (p.get('sc') and not muff and ('TOUCHDOWN' in x.upper() or 'for a TD' in x or 'Return (' in x or 'Return Touchdown' in t)) else 0
                kick = str(p.get('st') or '')
                recv = [tid for tid in tids if tid != kick]
                nk = name_key(m.group(2))
                aid = tm = None
                for tid in recv + [kick]:
                    if nk and nk in keys.get(tid, {}):
                        aid, tm = keys[tid][nk], tid
                        break
                if not aid:
                    miss += 1
                    continue
                if td:
                    catch = ry
                else:
                    kd = KD.search(x); yl = p.get('yl')
                    if not kd or not yl:
                        continue
                    catch = 100 - (int(yl) - int(kd.group(1)))
                    if tm == kick:          # the start team was the receiver on this row
                        continue
                end = catch - ry
                if not (0 <= end <= 100) or catch > 110:
                    continue
                lost = bool(p.get('to')) and ('fumble' in x.lower() or muff) and not td
                fum = 1 if lost else 0
                if td:
                    v = 7.0
                elif lost:
                    v = -D[max(1, min(99, 100 - max(1, end)))]
                else:
                    v = D[max(1, min(99, end))]
                rets.append({'s': s, 'k': 'kr' if ko else 'pr', 'p': aid, 't': tm, 'catch': catch, 'y': ry, 'v': v, 'td': td, 'fum': fum,
                             'w': g.get('w', 0), 'd': g.get('date', '')})
    print('returns', len(rets), 'unmatched names', miss, flush=True)
    return rets, D, miss


def cfb():
    import cfb_all
    y = season_now()
    rets, D, miss = cfb_returns((y - 2, y - 1, y))
    A = cfb_all.read_cfb_all(); c = {k: i for i, k in enumerate(A['cols'])}
    board = {}
    for r in A['rows']:
        m = re.search(r'/id/(\d+)', r[c['espnl']] or '')
        if m:
            board[m.group(1)] = r
    cur = {r['p'] for r in rets if r['s'] == y}
    info = {}
    for aid in cur:
        r = board.get(aid)
        if not r or r[c['div']] != 'FBS':
            continue
        info[aid] = {'n': r[c['name']], 'pos': r[c['pos']], 't': r[c['team']], 'lg': r[c['logo']], 'fv': r[c['fv']],
                     'cls': r[c['cls']], 'dv': r[c['div']]}
    wk = max((r['w'] for r in rets if r['s'] == y), default=0)
    out = write('cfb', rets, y, info, {'week': wk, 'value': 'drive points', 'd25': round(D[75], 2), 'd50': round(D[50], 2),
                                       'unmatched': miss})
    fv_file(rets, y, wk)
    return out


def fv_file(rets, y, wk):
    """scripts/data/cfb_ret_fv.json for the FV return term (fetch_cfb.mjs, data/cfb_fv_returns.json): every returner's
    career KR / PR count and yards over expected, from the frozen history (scripts/data/cfb_ret_hist.json.gz, 2019-25)
    for the seasons this run did not pull, and the seasons he returned in. {p: {ESPN id: [KR, KR yoe, PR, PR yoe,
    seasons, returned this season]}}"""
    H = {}
    try:
        with gzip.open(os.path.join(HERE, 'data', 'cfb_ret_hist.json.gz'), 'rt') as f:
            H = json.load(f)
    except (OSError, ValueError):
        pass
    live = {r['s'] for r in rets}
    acc = defaultdict(lambda: {'v': [0, 0.0, 0, 0.0], 's': set()})
    for s, d in H.items():
        if int(s) in live or int(s) > y:
            continue
        for aid, x in d.items():
            a = acc[aid]
            for i in range(4):
                a['v'][i] += x[i]
            a['s'].add(int(s))
    for r in rets:
        a = acc[r['p']]
        i = 0 if r['k'] == 'kr' else 2
        a['v'][i] += 1; a['v'][i + 1] += r['ryoe']; a['s'].add(r['s'])
    P = {aid: [a['v'][0], round(a['v'][1], 1), a['v'][2], round(a['v'][3], 1), len(a['s']), int(y in a['s'])]
         for aid, a in acc.items() if y in a['s'] or y - 1 in a['s'] or y - 2 in a['s'] or y - 3 in a['s']}
    with open(os.path.join(HERE, 'data', 'cfb_ret_fv.json'), 'w') as f:
        json.dump({'season': y, 'week': wk, 'p': P}, f, separators=(',', ':'))
    print('cfb_ret_fv:', len(P), 'returners', flush=True)


if __name__ == '__main__':
    {'nfl': nfl, 'cfb': cfb}[sys.argv[1]]()
