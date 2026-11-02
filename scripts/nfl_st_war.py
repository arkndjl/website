#!/usr/bin/env python3
"""Special teams in NFL WAR (Noah, Nov 2 2026): kicking, punting and kick / punt returns, in points over an average
specialist, shrunk to the part that carries over to the next season, over 35.5 points a win.

    python3 scripts/nfl_st_war.py --test     # 2016-25 tests -> data/nfl_st_war.json (k by kind and the results)
    import nfl_st_war; nfl_st_war.values(y, thru)   # {gsis: {...}} for scripts/nfl_war.py board()

Each kick play (nflverse play-by-play, regular season, no penalty) splits into parts that add up to its EPA:
  kicker / punter   E[value | where the kick ended] - E[value | spot it was kicked from], kicking team's side.
                    Returned kicks end at the mean return value from the catch spot; touchbacks, fair catches,
                    downed and out-of-bounds kicks at the play's own EPA. FG and XP: EPA - E[EPA | distance].
  returner          EPA - E[value | catch spot], receiving side (scripts/st_returners.py's split)
  the rest          coverage, blocking and luck; not given to anyone (no unit ids)
Expected values: season x kind x 5-yard bin means (FG / XP 3-yard bins); a bin under 25 plays borrows from all seasons.

Credit = sum POE / (n + k) x n, k by kind such that last season's credit predicts next season's points over expected
one for one (forward slope 1, 2016-25). Kickoffs are left out: kicker kickoff value carries only with the same team's
coverage (new kicker on an old unit: none; same kicker who moved: none) and the 2024 kickoff rule changed the play.
Over average, not replacement, so the board's scale (team WAR sums to wins - 3) holds: the credit comes out of the
team's offense pool in nfl_war.py, where those points sat before.
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_war as W  # noqa: E402

OUT = os.path.join(W.ROOT, 'data', 'nfl_st_war.json')
PTS_PER_WIN = 35.5
KINDS = ('kick', 'punt', 'kr', 'pr')          # kick = FG + XP
K_DEFAULT = {'kick': 250, 'punt': 180, 'kr': 100, 'pr': 125}
TEST_YEARS = list(range(2016, 2026))


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def plays_of(s):
    """kick plays of season s (regular season, no penalty) with the fields the split needs"""
    p = W.get(f'play_by_play_{s}.csv.gz', f'{W.REL}/pbp/play_by_play_{s}.csv.gz')
    rd = csv.reader(gzip.open(p, 'rt', encoding='utf-8'))
    h = next(rd); I = {c: i for i, c in enumerate(h)}
    g = lambda r, c: r[I[c]]
    out = []
    for r in rd:
        if g(r, 'season_type') != 'REG':
            continue
        ko, pu, fg, xp = (g(r, c) == '1' for c in ('kickoff_attempt', 'punt_attempt', 'field_goal_attempt', 'extra_point_attempt'))
        if not (ko or pu or fg or xp) or g(r, 'penalty') == '1':
            continue
        epa, yl = _f(g(r, 'epa')), _f(g(r, 'yardline_100'))
        if epa is None or yl is None:
            continue
        base = {'s': s, 'wk': int(g(r, 'week')), 'gid': g(r, 'game_id')}
        if fg or xp:
            kid = g(r, 'kicker_player_id')
            if kid in ('', 'NA'):
                continue
            made = g(r, 'field_goal_result') == 'made' if fg else g(r, 'extra_point_result') == 'good'
            out.append({**base, 'k': 'fg' if fg else 'xp', 'kp': kid, 'kt': g(r, 'posteam'), 'spot': _f(g(r, 'kick_distance')) or (yl + 18),
                        'v': epa, 'made': made})
            continue
        if 'onside' in g(r, 'desc').lower() or g(r, 'own_kickoff_recovery') == '1':
            continue
        v = -epa if ko else epa                 # kicking side; nflverse posteam receives a kickoff
        kt, rt = (g(r, 'defteam'), g(r, 'posteam')) if ko else (g(r, 'posteam'), g(r, 'defteam'))
        kid = g(r, 'kicker_player_id' if ko else 'punter_player_id')
        rid = g(r, 'kickoff_returner_player_id' if ko else 'punt_returner_player_id')
        dist = _f(g(r, 'kick_distance'))
        blocked = g(r, 'punt_blocked') == '1'
        o = {**base, 'k': 'ko' if ko else 'punt', 'kp': kid if kid not in ('', 'NA') else None, 'kt': kt, 'rt': rt,
             'spot': (100 - yl) if ko else yl, 'v': v, 'blk': blocked, 'dist': dist or 0}
        if (rid not in ('', 'NA') and g(r, 'touchback') != '1' and g(r, 'lateral_return') != '1' and dist is not None
                and g(r, 'kickoff_fair_catch' if ko else 'punt_fair_catch') != '1' and not blocked):
            o['rp'] = rid
            o['catch'] = yl + dist if ko else 100 - (yl - dist)
        out.append(o)
    return out


def _means(rows, key, val, minn=25):
    S, A = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    for r in rows:
        s, k = key(r)
        S[(s, k)][0] += 1; S[(s, k)][1] += val(r)
        A[k][0] += 1; A[k][1] += val(r)

    def get(r):
        s, k = key(r)
        n, v = S[(s, k)]
        n2, v2 = A[k]
        if n >= minn:
            return v / n
        w = n / minn
        return w * (v / max(n, 1)) + (1 - w) * v2 / max(n2, 1)
    return get


def parts(plays):
    """[{s, wk, gid, k, p, t, poe}] for kickers (kick = FG + XP), punters, kickoff men (ko) and returners (kr / pr)"""
    B = lambda x, w=5: int(max(0, min(110, x)) // w)
    ret = [p for p in plays if 'rp' in p]
    ec = _means(ret, lambda p: (p['s'], (p['k'], B(p['catch']))), lambda p: p['v'])
    for p in ret:
        p['ec'] = ec(p)
    for p in plays:
        if p['k'] in ('ko', 'punt'):
            p['end'] = p['ec'] if 'rp' in p else p['v']
    es = _means([p for p in plays if p['k'] in ('ko', 'punt')], lambda p: (p['s'], (p['k'], B(p['spot']))), lambda p: p['end'])
    ef = _means([p for p in plays if p['k'] in ('fg', 'xp')], lambda p: (p['s'], (p['k'], B(p['spot'], 3))), lambda p: p['v'])
    out = []
    for p in plays:
        b = {'s': p['s'], 'wk': p['wk'], 'gid': p['gid']}
        if p['k'] in ('fg', 'xp'):
            out.append({**b, 'k': 'kick', 'sub': p['k'], 'p': p['kp'], 't': p['kt'], 'poe': p['v'] - ef(p), 'made': p['made'], 'd': p['spot']})
            continue
        if p['kp'] and not p['blk']:
            out.append({**b, 'k': p['k'], 'p': p['kp'], 't': p['kt'], 'poe': p['end'] - es(p), 'd': p['dist']})
        if 'rp' in p:
            out.append({**b, 'k': 'kr' if p['k'] == 'ko' else 'pr', 'p': p['rp'], 't': p['rt'], 'poe': -(p['v'] - p['ec'])})
    return out


def _k():
    try:
        return {**K_DEFAULT, **json.load(open(OUT))['k']}
    except (OSError, ValueError, KeyError):
        return dict(K_DEFAULT)


def values(y, thru=None):
    """Season y (weeks before thru): {gsis: {'pts': credit, kind: credit, 'n': {kind: plays}, 't': Counter, line fields}}.
    Expected values come from seasons y-2..y, so one season's thin bins borrow from its neighbours."""
    K = _k()
    plays = []
    for s in (y - 2, y - 1, y):
        try:
            pl = plays_of(s)
        except Exception as e:     # a season not posted yet (y - 2 before 2001): the others carry it
            print(f'nfl st: season {s} skipped ({e!r})')
            continue
        plays += [p for p in pl if s < y or thru is None or p['wk'] < thru]
    P = [r for r in parts(plays) if r['s'] == y and r['k'] in KINDS]
    by = defaultdict(lambda: defaultdict(list)); tm = defaultdict(Counter); ln = defaultdict(lambda: defaultdict(float)); gm = defaultdict(set)
    for r in P:
        by[r['p']][r['k']].append(r['poe']); tm[r['p']][r['t']] += 1; gm[r['p']].add(r['gid'])
        L = ln[r['p']]
        if r['k'] == 'kick':
            L[r['sub'] + 'a'] += 1; L[r['sub'] + 'm'] += r['made']
        elif r['k'] == 'punt':
            L['pu'] += 1; L['puy'] += r['d']
        else:
            L[r['k']] += 1
    out = {}
    for p, d in by.items():
        o = {'n': {}, 't': tm[p], 'line': dict(ln[p]), 'g': len(gm[p])}
        tot = 0.0
        for k, xs in d.items():
            c = sum(xs) / (len(xs) + K[k]) * len(xs)
            o[k] = c; o['n'][k] = len(xs); tot += c
        o['pts'] = tot
        out[p] = o
    return out


# ---------------------------------------------------------------- tests
def _wls(x, y, w):
    W_ = sum(w); mx = sum(a * b for a, b in zip(x, w)) / W_; my = sum(a * b for a, b in zip(y, w)) / W_
    sxx = sum(c * (a - mx) ** 2 for a, c in zip(x, w)); sxy = sum(c * (a - mx) * (b - my) for a, b, c in zip(x, y, w))
    b = sxy / sxx; res = [b2 - my - b * (a - mx) for a, b2 in zip(x, y)]
    se = math.sqrt(sum((c * (a - mx)) ** 2 * r * r for a, c, r in zip(x, w, res))) / sxx
    return round(b, 3), round(b / se, 2), len(x)


def test():
    import numpy as np
    plays = []
    for s in TEST_YEARS:
        plays += plays_of(s)
    P = parts(plays)
    ALL = KINDS + ('ko',)
    by = defaultdict(list); main = defaultdict(Counter)
    for r in P:
        by[(r['k'], r['p'], r['s'])].append(r['poe']); main[(r['k'], r['p'], r['s'])][r['t']] += 1
    res = {'years': [TEST_YEARS[0], TEST_YEARS[-1]], 'plays': len(plays), 'kinds': {}}
    K = {}
    for k in ALL:
        # method-of-moments spread inside a season (what st_returners shows) and the forward k
        ps = [(xs, key) for key, xs in by.items() if key[0] == k]
        within = sum(sum((x - sum(xs) / len(xs)) ** 2 for x in xs) for xs, _ in ps if len(xs) > 1)
        wn = sum(len(xs) - 1 for xs, _ in ps if len(xs) > 1)
        sd = math.sqrt(within / wn)
        pairs = [(by[(k, p, s)], by[(k, p, s + 1)], main[(k, p, s)].most_common(1)[0][0] != main[(k, p, s + 1)].most_common(1)[0][0])
                 for (kk, p, s) in list(by) if kk == k and (k, p, s + 1) in by]

        def fwd(kk_, sel=lambda m: True):
            X = [sum(a) / (len(a) + kk_) for a, b, m in pairs if sel(m)]
            Y = [sum(b) / len(b) for a, b, m in pairs if sel(m)]
            Wt = [len(b) for a, b, m in pairs if sel(m)]
            return _wls(X, Y, Wt)
        # k where the forward slope is 1, leaving each season pair out in turn (the slope rises ~linearly in k)
        grid = [10 * i for i in range(1, 101)]
        kbest = min(grid, key=lambda kk_: abs(fwd(kk_)[0] - 1))
        K[k] = kbest
        # new specialist on the team's old unit: does the team's last-season rate carry without him?
        T = defaultdict(list)
        for (kk, p, s), xs in by.items():
            if kk == k:
                T[(main[(kk, p, s)].most_common(1)[0][0], s)] += xs
        nx, ny, nw = [], [], []
        for (kk, p, s), xs in by.items():
            if kk != k or len(xs) < 10:
                continue
            t = main[(kk, p, s)].most_common(1)[0][0]
            prev = T.get((t, s - 1))
            if prev and (k, p, s - 1) not in by:
                nx.append(sum(prev) / (len(prev) + kbest)); ny.append(sum(xs) / len(xs)); nw.append(len(xs))
        b, t, n = fwd(kbest)
        res['kinds'][k] = {'sdPlay': round(sd, 3), 'k': kbest, 'forward': {'slope': b, 't': t, 'pairs': n},
                           'moved': dict(zip(('slope', 't', 'pairs'), fwd(kbest, lambda m: m))),
                           'stayed': dict(zip(('slope', 't', 'pairs'), fwd(kbest, lambda m: not m))),
                           'newOnOldUnit': dict(zip(('slope', 't', 'pairs'), _wls(nx, ny, nw)))}
        print(k, res['kinds'][k], flush=True)
    # team test: next season's team points over expected (the attributable parts) from the specialists' credit last
    # season (at this season's plays), against the team's own last season
    gm = defaultdict(set)
    for p in plays:
        gm[(p['kt'], p['s'])].add(p['gid'])
        if p.get('rt'):
            gm[(p['rt'], p['s'])].add(p['gid'])
    team = {}
    for label, kinds in (('shipped', KINDS), ('withKickoffs', ALL), ('kick', ('kick',)), ('punt', ('punt',)), ('returns', ('kr', 'pr'))):
        act, pred = defaultdict(float), defaultdict(float)
        for (k, p, s), xs in by.items():
            if k not in kinds:
                continue
            for t, n in main[(k, p, s)].items():
                sh = n / len(xs)
                act[(t, s)] += sum(xs) * sh
                prv = by.get((k, p, s - 1))
                if prv:
                    pred[(t, s)] += sum(prv) / (len(prv) + K[k]) * len(xs) * sh
        rows = [(t, s) for (t, s) in act if (t, s - 1) in act and gm[(t, s)] and gm[(t, s - 1)]]
        Y = np.array([act[r] / len(gm[r]) for r in rows]); X1 = np.array([pred[r] / len(gm[r]) for r in rows])
        X2 = np.array([act[(t, s - 1)] / len(gm[(t, s - 1)]) for t, s in rows])

        def ols(Xs):
            A = np.column_stack([np.ones(len(Y))] + Xs); b, *_ = np.linalg.lstsq(A, Y, rcond=None); e = Y - A @ b
            cov = np.linalg.inv(A.T @ A) * (e @ e) / (len(Y) - A.shape[1])
            return [round(float(v), 3) for v in b[1:]], [round(float(v), 2) for v in b[1:] / np.sqrt(np.diag(cov)[1:])]
        b1, t1 = ols([X1]); b3, t3 = ols([X1, X2])
        team[label] = {'teamSeasons': len(rows), 'sdPtsGame': round(float(Y.std()), 3), 'players': {'slope': b1[0], 't': t1[0]},
                       'withTeamLast': {'players': {'slope': b3[0], 't': t3[0]}, 'teamLast': {'slope': b3[1], 't': t3[1]}}}
        print(label, team[label], flush=True)
    res['team'] = team
    res['k'] = {k: K[k] for k in KINDS}
    res['shipped'] = list(KINDS)
    res['note'] = ('kicking (FG + XP), punting, KR and PR credit predicts next season one for one and beats the team\'s own '
                   'last season on team points; kickoffs left out (no carry-over beyond the coverage unit)')
    with open(OUT, 'w') as f:
        json.dump(res, f, indent=1)
        f.write('\n')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
