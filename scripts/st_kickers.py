#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Special teams tab, kickers and punters: points over expected by field position, shrunk for sample.

    python3 scripts/st_kickers.py nfl            # nflverse play-by-play -> data/st_kickers_nfl.json (nfl.yml)
    python3 scripts/st_kickers.py cfb            # ESPN play-by-play cache + kicking/punting box -> data/st_kickers_cfb.json
    python3 scripts/st_kickers.py --pull A B     # CFB: ESPN summaries for seasons A..B (play-by-play + kicking box)
    python3 scripts/st_kickers.py --current      # CFB: the same for the five-season window, scoreboards from the cache
Research (stability, punter weights, the FV driver test): scripts/research/st_kickers_nov02.py.

Every kick is valued in expected points (EP) of where the next possession starts, against the mean kick from the same
spot (same season), so the coach's choice to kick and the spot are not the kicker's:
  Punt     value = -EP(receiver's start), a return TD -7, a muff the kicking team recovers +EP(its spot). Expected = mean
           value of punts from the same line (3-yard bins). Pin = points over expected on punts from the opponent's 50 and
           in (inside-20s, touchbacks); Dist = punts from beyond the 50 (distance, hang, coverage). Blocks and fakes left out.
  FG       3 x (made - P(made)), P from a logistic fit on distance (cubic) and, NFL, roof, wind and cold x distance.
  XP       NFL: made - season rate. CFB: from the box score, made - season rate.
  Kickoff  value = -EP(receiver's start) against the mean kickoff from the same line that season (onside kicks left out),
           so 2024+ NFL rules have their own baseline.
EP: NFL nflverse ep on 1st-and-10 by yard line; CFB mean drive points by start (ESPN drives).
Shrinkage per part: total / (n + k), k = noise variance / player variance (method of moments, player-seasons over the
window; FG over each kicker's whole window, since one season's FG over expected barely repeats). Adj = sum of the
shrunk part rates x attempts = points over expected, shrunk; the rank.
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

TOP = 120
MIN_LIST = {'k': 4, 'p': 10}     # FG attempts + kickoffs / 3 (kickers), punts (punters) to be listed


# Shrinkage k (method of moments, plays at which half the observed rate is kept) and year-to-year r of the per-play rate,
# from the long backtest (NFL 2012-25, CFB FBS 2010-25; scripts/research/st_kickers_nov02.py). FG k is over
# each kicker's whole window. Punter grade = cv x shrunk points over expected + cg x shrunk gross yards over expected,
# both a punt: weights fit on next season's points over expected a punt (player-seasons, held out by season: NFL r .31,
# gross adds nothing; CFB r .24 against .19 for points alone, so leg carries weight there).
RES = {
    'nfl': {'fg': {'k': 150, 'r': -0.02}, 'xp': {'k': 68, 'r': 0.12}, 'ko': {'k': 135, 'r': 0.09}, 'pin': {'k': 159, 'r': -0.02},
            'far': {'k': 98, 'r': 0.30}, 'pu': {'k': 123, 'r': 0.33}, 'gross': {'k': 29, 'r': 0.45}, 'net': {'k': 60, 'r': 0.40},
            'cv': 0.93, 'cg': 0.0092},
    'cfb': {'fg': {'k': 49, 'r': 0.10}, 'xp': {'k': 59, 'r': 0.18}, 'ko': {'k': 48, 'r': 0.12}, 'pin': {'k': 72, 'r': 0.00},
            'far': {'k': 30, 'r': 0.22}, 'pu': {'k': 33, 'r': 0.23}, 'gross': {'k': 15, 'r': 0.46}, 'net': {'k': 24, 'r': 0.37},
            'cv': 0.26, 'cg': 0.0122},
}
FV_NET_K = 14       # CFB punter FV input: career net yards over expected a punt, sum / (punts + 14) (Nov 2 2026 test)


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


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


# ------------------------------------------------------------------ shared math
def logit_fit(X, y, it=30, lam=1e-4):
    """Logistic regression by Newton steps (small dense system)."""
    m = len(X[0]); b = [0.0] * m
    for _ in range(it):
        g = [0.0] * m; H = [[lam if i == j else 0.0 for j in range(m)] for i in range(m)]
        for x, t in zip(X, y):
            z = sum(bi * xi for bi, xi in zip(b, x)); p = 1 / (1 + math.exp(-max(-30, min(30, z)))); w = p * (1 - p)
            for i in range(m):
                g[i] += (t - p) * x[i]
                for j in range(i, m):
                    H[i][j] += w * x[i] * x[j]
        for i in range(m):
            for j in range(i):
                H[i][j] = H[j][i]
        step = solve(H, g)
        b = [bi + si for bi, si in zip(b, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return b


def solve(A, b):
    n = len(b); M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c])); M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c and M[c][c]:
                q = M[r][c] / M[c][c]
                M[r] = [a - q * bb for a, bb in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] if M[i][i] else 0.0 for i in range(n)]


def expect(rows, fld, out, key, thin=20):
    """rows[out] = rows[fld] - mean of fld over the same key (season, spot); thin cells borrow from the spot over all seasons."""
    S, A = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    for r in rows:
        k = key(r)
        S[k][0] += 1; S[k][1] += r[fld]; A[k[1:]][0] += 1; A[k[1:]][1] += r[fld]
    for r in rows:
        k = key(r); n, v = S[k]; n2, v2 = A[k[1:]]
        w = min(1.0, n / thin)
        r[out] = r[fld] - (w * v / max(n, 1) + (1 - w) * v2 / max(n2, 1))


def hyper(rows, fld, seasons, by_career=False, lo=5.0, hi=400.0, minn=8):
    """k = sigma^2 / tau^2 (method of moments), and the year-to-year r of the per-play rate (minn+ plays both seasons)."""
    by = defaultdict(list)
    for r in rows:
        if r['s'] in seasons and r.get(fld) is not None:
            by[r['p'] if by_career else (r['p'], r['s'])].append(r[fld])
    within, wn = 0.0, 0
    for xs in by.values():
        if len(xs) >= 2:
            m = mean(xs); within += sum((x - m) ** 2 for x in xs); wn += len(xs) - 1
    if not wn:
        return {'k': hi, 'r': None, 'pairs': 0, 'ps': 0, 'sd': None, 'tau': 0.0}
    sig2 = within / wn
    means = [(mean(xs), len(xs)) for xs in by.values() if len(xs) >= 5]
    W = sum(n for _, n in means) or 1
    mu = sum(m * n for m, n in means) / W
    ss = sum(n * (m - mu) ** 2 for m, n in means)
    den = W - sum(n * n for _, n in means) / W
    tau2 = max((ss - (len(means) - 1) * sig2) / den, 1e-9) if den > 0 else 1e-9
    # year-to-year r on player-seasons
    ps = defaultdict(list)
    for r in rows:
        if r['s'] in seasons and r.get(fld) is not None:
            ps[(r['p'], r['s'])].append(r[fld])
    pairs = [(mean(xs), mean(ps[(p, s + 1)])) for (p, s), xs in ps.items()
             if len(xs) >= minn and len(ps.get((p, s + 1), [])) >= minn]
    rr = None
    if len(pairs) >= 10:
        mx = mean([a for a, _ in pairs]); my = mean([b for _, b in pairs])
        sxy = sum((a - mx) * (b - my) for a, b in pairs); sxx = sum((a - mx) ** 2 for a, _ in pairs); syy = sum((b - my) ** 2 for _, b in pairs)
        rr = sxy / math.sqrt(sxx * syy) if sxx and syy else None
    return {'k': round(min(hi, max(lo, sig2 / tau2)), 1), 'sd': round(math.sqrt(sig2), 3), 'tau': round(math.sqrt(tau2), 3),
            'r': None if rr is None else round(rr, 2), 'pairs': len(pairs), 'ps': len(means)}


def fg_feats(r):
    z = (r['d'] - 40) / 10
    out = [1.0, z, z * z, z * z * z, (r['s'] - 2020) / 5]
    if 'roof' in r:     # NFL environment: dome, wind and cold, each scaled by distance
        dome = 1.0 if r['roof'] in ('dome', 'closed') else 0.0
        w = (r['wind'] or 0) * (1 - dome); t = r['temp'] if (r['temp'] is not None and not dome) else 60
        out += [dome, w / 10 * (r['d'] - 20) / 30, min(0.0, t - 50) / 20 * (r['d'] - 20) / 30]
    return out


def grade(pl, season, sport):
    """pl: {'fg': [...], 'xp': [...], 'ko': [...], 'pu': [...]} plays with s, p, and values. Returns hyper + per-player sums."""
    fit_s = {season - 4, season - 3, season - 2, season - 1, season}
    # FG expected
    fg = [r for r in pl['fg'] if r['s'] in fit_s]
    b = logit_fit([fg_feats(r) for r in fg], [r['m'] for r in fg])
    for r in fg:
        z = sum(bi * xi for bi, xi in zip(b, fg_feats(r))); r['xm'] = 1 / (1 + math.exp(-z)); r['poe'] = 3 * (r['m'] - r['xm'])
    xp = [r for r in pl['xp'] if r['s'] in fit_s]
    rate = defaultdict(list)
    for r in xp:
        rate[r['s']].append(r['m'])
    for r in xp:
        r['poe'] = r['m'] - mean(rate[r['s']])
    ko = [r for r in pl['ko'] if r['s'] in fit_s]
    expect(ko, 'v', 'poe', lambda r: (r['s'], int(r['yl'] // 5)))
    pu = [r for r in pl['pu'] if r['s'] in fit_s]
    expect(pu, 'v', 'poe', lambda r: (r['s'], int(min(99, r['yl']) // 3)))
    expect(pu, 'gross', 'goe', lambda r: (r['s'], int(min(99, r['yl']) // 3)))
    expect(pu, 'net', 'noe', lambda r: (r['s'], int(min(99, r['yl']) // 3)))
    pin = [r for r in pu if r['yl'] <= 50]; far = [r for r in pu if r['yl'] > 50]
    H = RES[sport]
    return H, {'fg': fg, 'xp': xp, 'ko': ko, 'pu': pu, 'pin': pin, 'far': far}


def kicker_rows(P, H, season, info):
    A = defaultdict(lambda: defaultdict(float))
    for part in ('fg', 'xp', 'ko'):
        for r in P[part]:
            if r['s'] != season:
                continue
            a = A[r['p']]
            a[part + 'n'] += 1; a[part + 'poe'] += r['poe']; a.setdefault('t', r['t']); a['t'] = r['t']
            if part == 'fg':
                a['fgm'] += r['m']; a['lng'] = max(a['lng'], r['d'] if r['m'] else 0)
                if r['d'] >= 50:
                    a['f50a'] += 1; a['f50m'] += r['m']
                a['fgx'] += r['xm']
            if part == 'xp':
                a['xpm'] += r['m']
            if part == 'ko':
                a['tb'] += r['tb']; a['kod'] += r['dist']
    rows = []
    for p, a in A.items():
        if p not in info or a['fgn'] + a['kon'] / 3 < MIN_LIST['k']:
            continue
        adj = sum(a[x + 'poe'] / (a[x + 'n'] + H[x]['k']) * a[x + 'n'] for x in ('fg', 'xp', 'ko') if a[x + 'n'])
        sh = {x: (a[x + 'poe'] / (a[x + 'n'] + H[x]['k']) * a[x + 'n'] if a[x + 'n'] else 0.0) for x in ('fg', 'xp', 'ko')}
        rows.append({**info[p], 'id': p, 'fga': int(a['fgn']), 'fgm': int(a['fgm']), 'pct': round(100 * a['fgm'] / a['fgn'], 1) if a['fgn'] else None,
                     'xpct': round(100 * a['fgx'] / a['fgn'], 1) if a['fgn'] else None, 'lng': int(a['lng']),
                     'f50': f"{int(a['f50m'])}/{int(a['f50a'])}", 'fgp': round(a['fgpoe'], 2),
                     'xpa': int(a['xpn']), 'xpm': int(a['xpm']), 'ko': int(a['kon']),
                     'tb': round(100 * a['tb'] / a['kon']) if a['kon'] else None, 'kop': round(a['kopoe'], 2) if a['kon'] else None,
                     'sfg': round(sh['fg'], 2), 'sko': round(sh['ko'], 2), 'sxp': round(sh['xp'], 2), 'adj': round(adj, 2),
                     'pts': round(a['fgpoe'] + a['xppoe'] + a['kopoe'], 2)})
    rows.sort(key=lambda o: -o['adj'])
    return rows[:TOP], len(rows)


def punter_rows(P, H, season, info):
    A = defaultdict(lambda: defaultdict(float))
    for r in P['pu']:
        if r['s'] != season:
            continue
        a = A[r['p']]
        a['n'] += 1; a['poe'] += r['poe']; a['gross'] += r['gross']; a['net'] += r['net']; a['t'] = r['t']; a['goe'] += r['goe']
        a['i20'] += r['i20']; a['tb'] += r['tb']; a['ret'] += r['ret']; a['ry'] += r['ry'] if r['ret'] else 0
        a['lng'] = max(a['lng'], r['dist'])
        side = 'pin' if r['yl'] <= 50 else 'far'
        a[side + 'n'] += 1; a[side] += r['poe']
    rows = []
    for p, a in A.items():
        if p not in info or a['n'] < MIN_LIST['p']:
            continue
        sp = a['pin'] / (a['pinn'] + H['pin']['k']) * a['pinn'] if a['pinn'] else 0.0
        sf = a['far'] / (a['farn'] + H['far']['k']) * a['farn'] if a['farn'] else 0.0
        n = a['n']
        leg = a['goe'] / (n + H['gross']['k'])           # gross yards over expected a punt, shrunk
        rate = H['cv'] * (sp + sf) / n + H['cg'] * leg     # predicted points over expected a punt
        rows.append({**info[p], 'id': p, 'pu': int(n), 'gross': round(a['gross'] / n, 1), 'net': round(a['net'] / n, 1), 'lng': int(a['lng']),
                     'i20': int(a['i20']), 'tb': int(a['tb']), 'nr': round(100 * (1 - a['ret'] / n)),
                     'ryr': round(a['ry'] / a['ret'], 1) if a['ret'] else None,
                     'pts': round(a['poe'], 2), 'spin': round(sp, 2), 'sfar': round(sf, 2), 'leg': round(leg, 1),
                     'rate': round(rate, 3), 'adj': round(rate * n, 2)})
    rows.sort(key=lambda o: -o['adj'])
    return rows[:TOP], len(rows)


def write(sport, pl, season, info, note):
    H, P = grade(pl, season, sport)
    kr, kn = kicker_rows(P, H, season, info)
    pr, pn = punter_rows(P, H, season, info)
    cnt = lambda part: sum(1 for r in P[part] if r['s'] == season)
    out = {'asof': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'season': season, 'sport': sport, 'min': MIN_LIST, 'note': note, 'h': H,
           'k': {'rows': kr, 'n': kn, 'fg': cnt('fg'), 'ko': cnt('ko')}, 'p': {'rows': pr, 'n': pn, 'pu': cnt('pu')}}
    if sport == 'cfb':
        # punter FV input (scripts/fetch_cfb.mjs): career net yards over expected a punt, shrunk, for every punter this season
        C = defaultdict(lambda: [0, 0.0])
        cur = {r['p'] for r in P['pu'] if r['s'] == season}
        for r in P['pu']:
            if r['p'] in cur:
                C[r['p']][0] += 1; C[r['p']][1] += r['noe']
        out['pcar'] = {p: [n, round(v / (n + FV_NET_K), 2)] for p, (n, v) in C.items()}
        # Big Leg badge (scripts/fetch_cfb.mjs): this season's gross yards over expected a punt, shrunk, every punter
        G = defaultdict(lambda: [0, 0.0])
        for r in P['pu']:
            if r['s'] == season:
                G[r['p']][0] += 1; G[r['p']][1] += r['goe']
        out['pleg'] = {p: [n, round(v / (n + H['gross']['k']), 2)] for p, (n, v) in G.items()}
    p = os.path.join(ROOT, 'data', f'st_kickers_{sport}.json')
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    print(sport, 'kickers', len(kr), 'of', kn, '· punters', len(pr), 'of', pn, flush=True)
    return out, H, P


# ------------------------------------------------------------------ NFL
def nfl_plays(seasons):
    import nfl_war as W
    pl = {'fg': [], 'xp': [], 'ko': [], 'pu': []}
    epc = defaultdict(lambda: [0, 0.0])
    raw = []
    for s in seasons:
        p = W.get(f'play_by_play_{s}.csv.gz', f'{W.REL}/pbp/play_by_play_{s}.csv.gz')
        rd = csv.reader(gzip.open(p, 'rt', encoding='utf-8'))
        h = next(rd); I = {c: i for i, c in enumerate(h)}
        g = lambda r, c: r[I[c]]
        for r in rd:
            yl = f(g(r, 'yardline_100'))
            if yl is None:
                continue
            if g(r, 'down') == '1' and g(r, 'ydstogo') == '10' and g(r, 'play_type') in ('run', 'pass') and f(g(r, 'ep')) is not None:
                epc[int(yl)][0] += 1; epc[int(yl)][1] += f(g(r, 'ep'))
            if g(r, 'penalty') == '1' or g(r, 'season_type') not in ('REG', 'POST'):
                continue
            fga, xpa, ko, pu = (g(r, c) == '1' for c in ('field_goal_attempt', 'extra_point_attempt', 'kickoff_attempt', 'punt_attempt'))
            if not (fga or xpa or ko or pu):
                continue
            raw.append((s, int(g(r, 'week')), fga, xpa, ko, pu, yl, {c: g(r, c) for c in (
                'kicker_player_id', 'punter_player_id', 'posteam', 'defteam', 'roof', 'temp', 'wind', 'kick_distance', 'field_goal_result',
                'extra_point_result', 'return_yards', 'touchback', 'punt_inside_twenty', 'punt_blocked', 'return_touchdown', 'fumble_lost',
                'punt_returner_player_id', 'punt_fair_catch', 'desc', 'own_kickoff_recovery', 'kickoff_returner_player_id')}))
    EPC = {k: v[1] / v[0] for k, v in epc.items() if v[0] >= 20}

    def ep(x):
        x = max(1, min(99, int(round(x))))
        while x not in EPC and x < 99:
            x += 1
        return EPC.get(x, 0.0)
    for s, wk, fga, xpa, ko, pu, yl, r in raw:
        base = {'s': s, 'wk': wk, 'yl': yl}
        if fga and r['kicker_player_id'] not in ('', 'NA'):
            pl['fg'].append({**base, 'p': r['kicker_player_id'], 't': r['posteam'], 'd': f(r['kick_distance']) or yl + 18, 'm': int(r['field_goal_result'] == 'made'),
                             'roof': r['roof'], 'wind': f(r['wind']), 'temp': f(r['temp'])})
        elif xpa and r['kicker_player_id'] not in ('', 'NA'):
            pl['xp'].append({**base, 'p': r['kicker_player_id'], 't': r['posteam'], 'm': int(r['extra_point_result'] == 'good')})
        elif ko and r['kicker_player_id'] not in ('', 'NA') and 'onside' not in r['desc'].lower():
            dist = f(r['kick_distance'])
            if dist is None:
                continue
            ry = f(r['return_yards'], 0.0)
            # nflverse: posteam receives a kickoff and yardline_100 is from its side, so the catch is yl + dist from its goal
            end = max(1, min(99, yl + dist - ry))
            if r['return_touchdown'] == '1':
                v = -7.0
            elif r['own_kickoff_recovery'] == '1':
                v = ep(100 - min(99, yl + dist))
            elif r['touchback'] == '1':
                v = -ep(75 if s < 2024 else 70 if s == 2024 else 65)
            elif r['fumble_lost'] == '1':
                v = ep(100 - end)
            else:
                v = -ep(end)
            pl['ko'].append({**base, 'p': r['kicker_player_id'], 't': r['defteam'], 'v': v, 'tb': int(r['touchback'] == '1'), 'dist': dist})
        elif pu and r['punter_player_id'] not in ('', 'NA') and r['punt_blocked'] != '1':
            dist = f(r['kick_distance'])
            if dist is None:
                continue
            ry = f(r['return_yards'], 0.0)
            ret = int(r['punt_returner_player_id'] not in ('', 'NA') and r['punt_fair_catch'] != '1')
            end = 80 if r['touchback'] == '1' else 100 - (yl - dist) - ry       # receiver's yards to goal
            if r['return_touchdown'] == '1':
                v = -7.0
            elif r['fumble_lost'] == '1' and ret:
                v = ep(100 - end)
            else:
                v = -ep(end)
            pl['pu'].append({**base, 'p': r['punter_player_id'], 't': r['posteam'], 'v': v, 'dist': dist, 'gross': min(dist, yl),
                             'net': yl - (100 - end), 'i20': int(r['punt_inside_twenty'] == '1'), 'tb': int(r['touchback'] == '1'),
                             'ret': ret, 'ry': ry})
    return pl


def nfl():
    import nfl_war as W
    y = season_now()
    pl = nfl_plays(range(y - 4, y + 1))
    ros = {r['gsis_id']: r for r in W.rows(W.get(f'roster_{y}.csv', f'{W.REL}/rosters/roster_{y}.csv')) if r['gsis_id']}
    last_t = {}
    for part in ('fg', 'xp', 'ko', 'pu'):
        for r in sorted((r for r in pl[part] if r['s'] == y), key=lambda r: r['wk']):
            last_t[r['p']] = r['t']
    info = {}
    for pid, t in last_t.items():
        r = ros.get(pid)
        if not r:
            continue
        info[pid] = {'n': r['full_name'], 'pos': r['position'] or '', 't': t,
                     **({'ph': r['headshot_url'].rsplit('/', 1)[-1]} if 'static.www.nfl.com' in (r.get('headshot_url') or '') else {})}
    wk = max((r['wk'] for r in pl['pu'] if r['s'] == y), default=0)
    write('nfl', pl, y, info, {'week': wk, 'ep': 'nflverse EP'})


# ------------------------------------------------------------------ CFB
def kp_dir():
    import cfb_espn_hist as EH
    d = os.path.join(EH.DIR, '..', 'espn_kp')
    os.makedirs(d, exist_ok=True)
    return d


def slim_kp(d):
    """Kickers and punters in an ESPN box score, by team id: {athlete id: [name, 'k'|'p', stats]}."""
    out = {}
    for t in (d.get('boxscore') or {}).get('players') or []:
        for st in t.get('statistics') or []:
            if st.get('name') in ('kicking', 'punting'):
                for a in st.get('athletes') or []:
                    at = a.get('athlete') or {}
                    if at.get('id'):
                        out.setdefault(t['team']['id'], {})[at['id']] = [at.get('displayName'), st['name'][0], a.get('stats')]
    return out


def pull_cfb(a, b, current=False):
    """ESPN summaries for every finished FBS-side game: slim play-by-play (cfb_espn_pbp's cache) plus the kicking and
    punting box (espn_kp/<id>.json), one summary call per game; a game already in the play-by-play cache costs one call
    for its box only once."""
    import cfb_espn_pbp as P
    import cfb_espn_hist as H
    import cfb_roster_hist as R
    from concurrent.futures import ThreadPoolExecutor
    KP = kp_dir()
    for x in ('sum', 'odds', 'box'):
        os.makedirs(os.path.join(H.DIR, x), exist_ok=True)
    os.makedirs(P.PBP, exist_ok=True)

    def pull(i):
        p, k = os.path.join(P.PBP, f'{i}.json.gz'), os.path.join(KP, f'{i}.json')
        if os.path.exists(p) and os.path.exists(k):
            return True
        d = H.get(f'{H.BASE}/summary?event={i}')
        if d is None:
            return False
        if not os.path.exists(p):
            s = P.slim(d)
            with gzip.open(p, 'wt') as fh:
                json.dump(s, fh)
            sp = os.path.join(H.DIR, 'sum', f'{i}.json')
            if not os.path.exists(sp):
                with open(sp, 'w') as fh:
                    json.dump({'lines': s['lines']}, fh)
            bp = os.path.join(R.BOX, f'{i}.json')
            if not os.path.exists(bp):
                with open(bp, 'w') as fh:
                    json.dump(R.slim_box(d), fh)
        with open(k, 'w') as fh:
            json.dump(slim_kp(d), fh)
        return True
    P.pull = pull
    for S in range(a, b + 1):
        gp = os.path.join(H.DIR, f'games{S}.json')
        if not (current and os.path.exists(gp)):
            H.season(S)
        games = json.load(open(gp))
        ids = [g['id'] for g in games if g['done'] and g.get('grp') == 'fbs']
        with ThreadPoolExecutor(12) as ex:
            ok = list(ex.map(pull, ids))
        print(S, len(ids), 'FBS-side games,', sum(ok), 'with a kicking box', flush=True)


def name_key(s):
    import names as NM
    s = re.sub(r'^(?:\(\d+:\d+\)\s*)?#\d+\s+', '', (s or '').strip())    # 2026 rows: '(13:40) #37 A.Flintoft'
    t = [w for w in re.split(r'[\s.,]+', NM.fold(s).lower()) if w and w not in ('jr', 'sr', 'ii', 'iii', 'iv')]
    return (t[0][0] + '|' + t[-1]) if len(t) >= 2 else ''


RX_FG = re.compile(r"^(.*?)\s+(\d+)\s*(?:yd|yard|yds|yards)\.?\s+(?:field goal|fg)", re.I)
RX_PU = re.compile(r"^(.*?)\s+punt(?:s)?\s+(?:for\s+)?(\d+)\s*(?:yd|yard|yds|yards)", re.I)
RX_RET = re.compile(r"(?:returns?|returned by [A-Za-z'.\- ]+?)\s+(?:for\s+)?(no gain|a loss of -?\d+|-?\d+)", re.I)
RX_KO = re.compile(r"^(.*?)\s+kickoff\s+(?:for\s+)?(\d+)\s*(?:yd|yard|yds|yards)", re.I)


def near(team_box, nm, kind):
    """A box-score spelling that differs from the play text (Ben Mahen / Ben Mehan): the one kicker or punter of that kind on
    the team that game whose last name is close."""
    import difflib
    c = [(aid, v[0]) for aid, v in team_box.items() if v[1] == kind]
    k = name_key(nm).split('|')[-1]
    c = [aid for aid, n2 in c if difflib.SequenceMatcher(None, k, name_key(n2).split('|')[-1]).ratio() >= 0.75]
    return c[0] if len(c) == 1 else None


def cfb_plays(seasons, fbs_only=True):
    """CFB kicks from the ESPN play-by-play cache, kickers and punters by ESPN athlete id (box score names)."""
    import cfb_espn_hist as EH
    PBP = os.path.join(EH.DIR, '..', 'espn_pbp'); KP = kp_dir()
    games = []
    for s in seasons:
        gp = os.path.join(EH.DIR, f'games{s}.json')
        if not os.path.exists(gp):
            continue
        for g in json.load(open(gp)):
            if g.get('done') and (g.get('grp') == 'fbs' or not fbs_only) and os.path.exists(os.path.join(PBP, f"{g['id']}.json.gz")) \
                    and os.path.exists(os.path.join(KP, f"{g['id']}.json")):
                games.append((s, g))
    loaded = {}
    dp = defaultdict(lambda: [0, 0.0])
    for s, g in games:
        d = json.load(gzip.open(os.path.join(PBP, f"{g['id']}.json.gz"), 'rt'))
        loaded[g['id']] = d
        for dr in d['drives']:
            pl = [p for p in dr['plays'] if not (p.get('t') or '').startswith(('Kickoff', 'Punt'))]
            if not pl or pl[0].get('dn') != 1 or not pl[0].get('yl') or str(pl[0].get('st')) != str(dr.get('tm')):
                continue
            res = (dr.get('res') or '').upper()
            pts = 7 if ('TD' in res or 'TOUCHDOWN' in res) else 3 if res in ('FG', 'FIELD GOAL', 'FG GOOD') else 0
            x = int(pl[0]['yl'])
            if 1 <= x <= 99:
                dp[x][0] += 1; dp[x][1] += pts
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
    ep = lambda x: D[max(1, min(99, int(round(x))))]
    pl = {'fg': [], 'xp': [], 'ko': [], 'pu': []}
    names = {}
    miss = defaultdict(int)
    for s, g in games:
        d = loaded[g['id']]
        box = json.load(open(os.path.join(KP, f"{g['id']}.json")))
        tids = [t['id'] for t in d['teams']]
        keys = {}
        for tid in tids:
            for aid, (nm, kind, st) in (box.get(tid) or {}).items():
                keys.setdefault(tid, {})[name_key(nm)] = aid
                names[aid] = (nm, tid)
                if kind == 'k' and st and len(st) >= 4:
                    m = re.match(r'(\d+)/(\d+)', st[3] or '')
                    if m:
                        for i in range(int(m[2])):
                            pl['xp'].append({'s': s, 'p': aid, 't': tid, 'm': int(i < int(m[1])), 'w': g.get('w', 0)})
        for dr in d['drives']:
            for p in dr['plays']:
                t = p.get('t') or ''; x = p.get('x') or ''; yl = p.get('yl'); st = str(p.get('st') or '')
                if p.get('pen') or 'PENALTY' in x.upper() or yl is None:
                    continue
                isfg = t in ('Field Goal Good', 'Field Goal Missed', 'Blocked Field Goal', 'Missed Field Goal Return', 'Blocked Field Goal Touchdown',
                             'Missed Field Goal Return Touchdown')
                ispu = t in ('Punt', 'Punt Return', 'Punt Return Touchdown') and 'blocked' not in x.lower()   # 2026 rows: 'Punt Return' when run back
                isko = t.startswith('Kickoff') and 'onside' not in x.lower()
                if not (isfg or ispu or isko):
                    continue
                rx = RX_FG if isfg else RX_PU if ispu else RX_KO
                m = rx.search(x)
                if not m:
                    if isfg:
                        m2 = re.match(r"^(.*?)\s+(?:field goal|fg)(?:\s+attempt\s+from\s+(\d+)\s+yards)?", x, re.I)   # 2026: 'field goal attempt from 42 yards'
                        if not m2:
                            continue
                        nm, dist = m2.group(1), int(m2.group(2)) if m2.group(2) else yl + 17
                    else:
                        continue
                else:
                    nm, dist = m.group(1), int(m.group(2))
                if isko:
                    kick = st if st else None
                    # the start team on a kickoff row is the kicking team on most rows; take the side whose box has the name
                    aid = None
                    for tid in [st] + [z for z in tids if z != st]:
                        aid = keys.get(tid, {}).get(name_key(nm))
                        if aid:
                            kick = tid
                            break
                    if not aid:
                        miss['ko'] += 1
                        continue
                else:
                    aid = keys.get(st, {}).get(name_key(nm)) or near(box.get(st) or {}, nm, 'k' if isfg else 'p')
                    kick = st
                    if not aid:
                        miss['fg' if isfg else 'pu'] += 1
                        continue
                if isfg:
                    made = int(t == 'Field Goal Good' or ('GOOD' in x.upper() and 'NO GOOD' not in x.upper() and t not in ('Blocked Field Goal',)))
                    if dist < 17 or dist > 70:
                        continue
                    pl['fg'].append({'s': s, 'p': aid, 't': kick, 'd': dist, 'm': made, 'w': g.get('w', 0), 'yl': yl})
                    continue
                recv = [z for z in tids if z != kick]
                et, eyl = str(p.get('et') or ''), p.get('eyl')
                td = bool(p.get('sc')) and ('TD' in x or 'TOUCHDOWN' in x.upper() or 'Touchdown' in t)
                if ispu:
                    if dist <= 0 or dist > 90:
                        continue
                    land = 100 - (yl - dist)              # receiver's yards to goal where the punt came down
                    tb = 'touchback' in x.lower() or land >= 100
                    mr = RX_RET.search(x)
                    ret = int(bool(mr) and not tb)
                    ry = 0
                    if ret:
                        g2 = mr.group(1) or ''
                        ry = 0 if 'no gain' in g2 else (-int(re.search(r'\d+', g2).group()) if 'loss' in g2 else int(re.search(r'\d+', g2).group()))
                    muff = bool(p.get('to')) and not td and et == kick
                    if td and et != kick:
                        v, end = -7.0, None
                    elif tb:
                        end = 80; v = -ep(end)
                    elif muff and eyl is not None:   # the kicking side has the ball at the end: muff or fumble recovered
                        end = None; v = ep(eyl)
                    else:
                        end = max(1, min(99, land - ry)); v = -ep(end)
                    nett = yl - (100 - end) if end is not None else yl
                    pl['pu'].append({'s': s, 'p': aid, 't': kick, 'yl': yl, 'v': v, 'dist': dist, 'gross': min(dist, yl), 'net': nett,
                                     'i20': int(end is not None and end >= 80 and not tb), 'tb': int(tb), 'ret': ret, 'ry': ry, 'w': g.get('w', 0)})
                else:
                    tb = 'touchback' in x.lower()
                    if td and et != kick:
                        v = -7.0
                    elif tb:
                        v = -ep(75)
                    elif eyl is None:
                        continue
                    elif et == kick:
                        v = ep(eyl)
                    else:
                        v = -ep(eyl)
                    pl['ko'].append({'s': s, 'p': aid, 't': kick, 'yl': yl, 'v': v, 'tb': int(tb), 'dist': dist, 'w': g.get('w', 0)})
    print('cfb plays', {k: len(v) for k, v in pl.items()}, 'unmatched', dict(miss), 'EP own 25', round(ep(75), 2), 'midfield', round(ep(50), 2), flush=True)
    return pl, names, D


def cfb():
    import cfb_all
    y = season_now()
    pl, names, D = cfb_plays(range(y - 4, y + 1))
    A = cfb_all.read_cfb_all(); c = {k: i for i, k in enumerate(A['cols'])}
    board = {}
    for r in A['rows']:
        m = re.search(r'/id/(\d+)', r[c['espnl']] or '')
        if m:
            board[m.group(1)] = r
    cur = set()
    for part in pl.values():
        cur |= {r['p'] for r in part if r['s'] == y}
    info = {}
    for aid in cur:
        r = board.get(aid)
        if r and r[c['div']] != 'FBS':
            continue
        if r:
            info[aid] = {'n': r[c['name']], 'pos': r[c['pos']], 't': r[c['team']], 'lg': r[c['logo']], 'fv': r[c['fv']], 'cls': r[c['cls']]}
    wk = max((r['w'] for r in pl['pu'] if r['s'] == y), default=0)
    write('cfb', pl, y, info, {'week': wk, 'ep': 'drive points', 'd20': round(D[80], 2), 'd50': round(D[50], 2)})


if __name__ == '__main__':
    a = sys.argv[1]
    if a == '--pull':
        pull_cfb(int(sys.argv[2]), int(sys.argv[3]))
    elif a == '--current':      # the cfb-board job: kicking boxes for the five-season window (one call a game not yet cached)
        y = season_now(); pull_cfb(y - 4, y, current=True)
    else:
        {'nfl': nfl, 'cfb': cfb}[a]()
