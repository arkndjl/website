#!/usr/bin/env python3
"""NBA 5-man lineup stints from ESPN play-by-play, for the NBA ARKBOARD's lineups and on/off tabs, and the lineup
research (scripts/nba_lineups_research.py). Stdlib only.

    python3 scripts/nba_lineups.py                 # this season: static/data/nba-lineups.json (daily, nba-xpm.yml)
    python3 scripts/nba_lineups.py --pull 2015 2026   # cache stints for seasons from..to (research history)
    python3 scripts/nba_lineups.py --check 2025    # validation: lineup minutes per team-game, player minutes vs box
    python3 scripts/nba_lineups.py --split 2025    # shrinkage for sNet / sOn-Off from odd vs even games

How: one ESPN summary per game (site.api.espn.com .../summary?event=<id>, the same call as nba_espn.box; its box is
saved to that cache too). Q1 starters come from the box score. Each later period's five are the players who appear in
it before they are subbed in (a substitution "X enters the game for Y" carries both athlete ids, entering first);
anyone not seen all period is carried from the end of the period before. Every play's elapsed time goes to the ten on
the floor; points come from the score change on each play (free throws after a mid-trip sub go to the new five).
Possessions per side are estimated per stint as FGA - OREB + TOV + .44 FTA, averaged over the two sides. A stint is
[home five, away five, seconds, home pts, away pts, home poss, away poss, garbage time 0/1] (Cleaning the Glass's rule).
Final games never change: each game's stints are cached in scripts/.cache/nba/lineups/<id>.json.
"""
import datetime as dt, json, os, sys, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nba_espn as E
import lineup_leaders as LL

CACHE = os.path.join(E.ROOT, 'scripts', '.cache', 'nba', 'lineups')
OUT = os.path.join(E.ROOT, 'static', 'data', 'nba-lineups.json')
LEAD_OUT = os.path.join(E.ROOT, 'static', 'data', 'nba-lineup-leaders.json')
# shrinkage (possessions) for the display's sNet and sOn-Off: noise variance over true variance from odd/even game
# splits (--split; 2024-26: units 447 / 671 / 751, on-off 1,408 / 2,610 / 1,462): Net of a five (20+ possessions in both halves) and a player's on-off
# (effective possessions 1 / (1/on + 1/off))
K_UNIT, K_ONOFF = 600, 1800
# lineup leaders (scripts/lineup_leaders.py): sNet toward the team's net, k by unit size = the out-of-sample best
# (odd games predict even and back, 2024-26 pooled; a team prior beat a prior of 0 in every season and size:
# MSE 5-man 820 vs 841, trios 330 vs 348, pairs 215 vs 226; raw Net 1558 / 613 / 385)
K_LEAD = {5: 800, 3: 1600, 2: 1600}
NOT_ON_FLOOR = ('Technical', 'Ejection', 'Delay', 'Timeout', 'Coach', 'Ref-Initiated', 'Review', 'Defensive 3-Seconds')


def secs(clock):
    """'11:49' or '45.3' -> seconds left"""
    s = str(clock or '0')
    if ':' in s:
        m, x = s.split(':')
        return int(m) * 60 + float(x)
    try:
        return float(s)
    except ValueError:
        return 0.0


def code(p):
    t = (p.get('type') or {}).get('text') or ''
    tid = str((p.get('type') or {}).get('id') or '')
    if tid == '584' or 'enters the game' in (p.get('text') or ''):
        return 'S'
    if t.startswith('Free Throw'):
        return 'T'
    if 'Turnover' in t:
        return 'V'
    if t == 'Offensive Rebound':
        return 'O'
    if t == 'End Period':
        return 'E'
    if p.get('shootingPlay'):
        return 'F'
    if any(x in t for x in NOT_ON_FLOOR):
        return 'X'                                   # bench players and coaches can be named: not evidence of the floor
    return ''


def parse(j):
    """ESPN summary -> {'h', 'a', 'st': [[home five], [away five], sec, home pts, away pts, home poss, away poss], 'bx':
    {pid: box minutes}, 'ok': periods with 5 on the floor for both sides / periods}"""
    comp = j['header']['competitions'][0]
    side = {c['homeAway']: c for c in comp['competitors']}
    tid = {side[s]['team']['id']: s for s in ('home', 'away')}
    ab = {s: E.team(side[s]['team']['abbreviation']) for s in ('home', 'away')}
    team_of, starters, bx, nmap = {}, {'home': [], 'away': []}, {}, {}
    for t in j['boxscore'].get('players', []):
        s = tid.get(t['team']['id'])
        if s is None:
            continue
        for st in t.get('statistics', [])[:1]:
            nm = st.get('names') or st.get('labels') or []
            for p in st.get('athletes', []):
                pid = (p.get('athlete') or {}).get('id')
                if not pid:
                    continue
                team_of[pid] = s
                nmap[pid] = (p.get('athlete') or {}).get('displayName')
                mn = dict(zip(nm, p.get('stats', []))).get('MIN')
                try:
                    bx[pid] = float(mn)
                except (TypeError, ValueError):
                    bx[pid] = 0.0
                if p.get('starter'):
                    starters[s].append(pid)
    plays = []
    for p in j.get('plays', []):
        per = (p.get('period') or {}).get('number') or 0
        pids = [x['athlete']['id'] for x in p.get('participants', []) if (x.get('athlete') or {}).get('id')]
        plays.append((per, secs((p.get('clock') or {}).get('displayValue')), code(p), tid.get((p.get('team') or {}).get('id')),
                      pids, p.get('homeScore') or 0, p.get('awayScore') or 0))
    if not plays or len(starters['home']) != 5 or len(starters['away']) != 5:
        return None
    nper = max(x[0] for x in plays)
    floor = {'home': set(starters['home']), 'away': set(starters['away'])}
    st0 = set(starters['home']) | set(starters['away'])
    agg = {}
    ok = 0
    hs0 = as0 = 0
    for per in range(1, nper + 1):
        pp = [x for x in plays if x[0] == per]
        length = 720.0 if per <= 4 else 300.0
        if per > 1:
            seen, first = {'home': set(), 'away': set()}, {'home': [], 'away': []}
            for _, _, c, _, pids, _, _ in pp:
                if c == 'X':
                    continue
                for i, pid in enumerate(pids):
                    s = team_of.get(pid)
                    if s is None or pid in seen[s]:
                        continue
                    seen[s].add(pid)
                    if not (c == 'S' and i == 0):
                        first[s].append(pid)
            for s in ('home', 'away'):
                f = first[s][:5]
                for pid in floor[s]:                   # quiet all period: carried from the period before
                    if len(f) < 5 and pid not in seen[s]:
                        f.append(pid)
                if len(f) < 5:                          # still short: the most box minutes not yet placed
                    for pid in sorted((p for p, t in team_of.items() if t == s and p not in f and p not in seen[s]), key=lambda p: -bx.get(p, 0)):
                        if len(f) < 5:
                            f.append(pid)
                floor[s] = set(f)
        good = True
        t_prev = length
        acc = None

        def key(left):
            return (tuple(sorted(floor['home'])), tuple(sorted(floor['away'])), garbage(per, left))

        def garbage(per, left):
            # Cleaning the Glass's garbage time: 4th quarter, margin 25+ with 12-9 minutes left, 20+ with 9-6, 10+
            # under 6, and two or fewer starters on the floor (both teams)
            if per != 4:
                return 0
            m = abs(hs0 - as0)
            need = 25 if left >= 540 else 20 if left >= 360 else 10
            return 1 if m >= need and len((floor['home'] | floor['away']) & st0) <= 2 else 0
        for _, left, c, side_, pids, hs, as_ in pp:
            el = max(0.0, t_prev - left)
            cur = key(t_prev)
            t_prev = min(t_prev, left)
            a = agg.setdefault(cur, [0.0, 0, 0, [0.0] * 4, [0.0] * 4])
            a[0] += el
            dh, da = hs - hs0, as_ - as0
            if dh > 0 or da > 0:
                a[1] += max(dh, 0); a[2] += max(da, 0)
            hs0, as0 = max(hs0, hs), max(as0, as_)
            if side_ in ('home', 'away'):
                v = a[3] if side_ == 'home' else a[4]
                if c == 'F':
                    v[0] += 1
                elif c == 'T':
                    v[1] += 1
                elif c == 'O':
                    v[2] += 1
                elif c == 'V':
                    v[3] += 1
            if c == 'S' and len(pids) >= 2:
                s = team_of.get(pids[0])
                if s and team_of.get(pids[1]) == s:
                    floor[s].discard(pids[1]); floor[s].add(pids[0])
        if t_prev > 0:
            a = agg.setdefault(key(t_prev), [0.0, 0, 0, [0.0] * 4, [0.0] * 4])
            a[0] += t_prev
        if len(floor['home']) == 5 and len(floor['away']) == 5:
            ok += 1
    st = []
    for (h5, a5, gt), (sec, hp, ap, hv, av) in agg.items():
        if sec <= 0 and hp == 0 and ap == 0:
            continue
        ph = hv[0] - hv[2] + hv[3] + 0.44 * hv[1]
        pa = av[0] - av[2] + av[3] + 0.44 * av[1]
        st.append([list(h5), list(a5), round(sec, 1), hp, ap, round(ph, 2), round(pa, 2), gt])
    return {'h': ab['home'], 'a': ab['away'], 'st': st, 's0': [starters['home'], starters['away']], 'bx': bx, 'nm': nmap, 'ok': [ok, nper]}


def stints(gid, fresh=False):
    fn = os.path.join(CACHE, f'{gid}.json')
    if not fresh and os.path.exists(fn):
        return json.load(open(fn))
    j = E.get(f'{E.SITE}/summary?event={gid}')
    if j is None or 'boxscore' not in j or not j.get('plays'):
        return None
    try:
        r = parse(j)
    except (KeyError, IndexError, TypeError):
        r = None
    if r is None:
        return None
    E.save(fn, r)
    return r


def season(S, workers=8):
    """{game id: stints} for the final games of season S (regular season and playoffs), plus the game rows"""
    gs = [g for g in E.games(S) if g['final']]
    with ThreadPoolExecutor(workers) as ex:
        res = dict(zip([g['id'] for g in gs], ex.map(lambda g: stints(g['id']), gs)))
    return gs, res


def check(S):
    gs, res = season(S)
    n = len(gs); have = sum(1 for v in res.values() if v)
    lens, diffs, bad, nobox = [], [], 0, 0
    for g in gs:
        r = res.get(g['id'])
        if not r:
            continue
        tot = sum(s[2] for s in r['st']) / 60
        lens.append(tot)
        on = defaultdict(float)
        for h5, a5, sec, *_ in r['st']:
            for p in h5 + a5:
                on[p] += sec / 60
            if len(h5) != 5 or len(a5) != 5:
                bad += 1
        if sum(r['bx'].values()) < 400:
            nobox += 1                                  # ESPN lost the box minutes of some older games
            continue
        for pid, m in r['bx'].items():
            if m > 0 or on.get(pid):
                diffs.append(abs(on.get(pid, 0) - m))
    reg = [x for x in lens]
    within = lambda t: sum(1 for d in diffs if d <= t) / max(1, len(diffs))
    out = {'season': S, 'games': n, 'parsed': have, 'mean_game_min': round(sum(reg) / max(1, len(reg)), 2),
           'games_240_or_ot': round(sum(1 for x in reg if any(abs(x - (48 + 5 * k)) < 0.6 for k in range(5))) / max(1, len(reg)), 4),
           'no_box_minutes': nobox, 'player_games': len(diffs), 'within_1min': round(within(1.0), 4), 'within_2min': round(within(2.0), 4),
           'mean_abs_min': round(sum(diffs) / max(1, len(diffs)), 3), 'stints_not_5': bad}
    print(json.dumps(out), flush=True)
    return out


def split(S):
    """odd vs even games of season S: K = noise variance (per possession) / true variance for a five's Net and a
    player's on-off (possession-weighted; the shrinkage in K_UNIT, K_ONOFF)"""
    gs, res = season(S)
    halves = []
    for h in (0, 1):
        sub = [g for i, g in enumerate(gs) if i % 2 == h]
        halves.append(agg_season(sub, res))

    def est(xs, ys, n1, n2):
        import statistics as st
        w = [(a * b) ** 0.5 for a, b in zip(n1, n2)]
        W = sum(w)
        mx = sum(a * b for a, b in zip(xs, w)) / W; my = sum(a * b for a, b in zip(ys, w)) / W
        cov = sum((a - mx) * (b - my) * c for a, b, c in zip(xs, ys, w)) / W
        s2 = st.mean((a - b) ** 2 / (1 / p + 1 / q) for a, b, p, q in zip(xs, ys, n1, n2))
        return {'n': len(xs), 'true_sd': round(cov ** 0.5, 2) if cov > 0 else None, 'k': round(s2 / cov) if cov > 0 else None}
    U = [h[0] for h in halves]
    xs, ys, n1, n2 = [], [], [], []
    for t in U[0]:
        for f, a in U[0][t].items():
            b = U[1].get(t, {}).get(f)
            if b and a[1] >= 20 and b[1] >= 20:
                xs.append(100 * (a[2] - a[3]) / a[1]); ys.append(100 * (b[2] - b[3]) / b[1]); n1.append(a[1]); n2.append(b[1])
    out = {'season': S, 'units': est(xs, ys, n1, n2)}
    xs, ys, n1, n2 = [], [], [], []
    for t in halves[0][2]:
        for p, a in halves[0][2][t].items():
            b = halves[1][2].get(t, {}).get(p)
            if not b:
                continue
            oo = []
            for (U_, T_, ON_), x in ((halves[0], a), (halves[1], b)):
                T = T_[t]
                offp = T[1] - x[1]
                oo.append(100 * (x[2] - x[3]) / x[1] - 100 * ((T[2] - x[2]) - (T[3] - x[3])) / offp if x[1] >= 100 and offp >= 100 else None)
            if None in oo:
                continue
            # noise of an on-off: on and off samples both count; effective n = 1 / (1/on + 1/off)
            ef = [1 / (1 / x[1] + 1 / (T_[t][1] - x[1])) for (U_, T_, ON_), x in ((halves[0], a), (halves[1], b))]
            xs.append(oo[0]); ys.append(oo[1]); n1.append(ef[0]); n2.append(ef[1])
    out['onoff'] = est(xs, ys, n1, n2)
    print(json.dumps(out), flush=True)
    return out


# ------------------------------------------------------------------- display
def agg_season(gs, res, upto=None):
    """per team: 5-man units, pairs, player on/off from the cached stints of season games (tip before upto)"""
    U = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))   # team -> five -> [sec, poss, pf, pa]
    T = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    ON = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))
    for g in gs:
        if upto and g['tip'] >= upto:
            continue
        r = res.get(g['id'])
        if not r:
            continue
        for h5, a5, sec, hp, ap, ph, pa, *_ in r['st']:
            poss = (ph + pa) / 2
            for t, five, pf, pg in ((r['h'], h5, hp, ap), (r['a'], a5, ap, hp)):
                u = U[t][tuple(sorted(five))]
                u[0] += sec; u[1] += poss; u[2] += pf; u[3] += pg
                x = T[t]
                x[0] += sec; x[1] += poss; x[2] += pf; x[3] += pg
                for p in five:
                    o = ON[t][p]
                    o[0] += sec; o[1] += poss; o[2] += pf; o[3] += pg
    return U, T, ON


def build(S=None):
    S = S or N_current()
    gs, res = season(S)
    names = player_names(res)
    U, T, ON = agg_season(gs, res)
    out = {'season': S, 'label': f'{S - 1}-{S % 100:02d}', 'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'k': K_UNIT, 'ko': K_ONOFF, 'teams': {}}
    for t in sorted(U):
        tt = T[t]
        units = []
        for five, (sec, poss, pf, pa) in U[t].items():
            if sec < 60 or len(five) != 5:             # a missed substitution leaves 4 or 6 (about 1 stint in 800)
                continue
            units.append([list(five), round(sec / 60, 1), round(poss, 1), pf, pa])
        units.sort(key=lambda u: -u[1])
        pairs = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for five, (sec, poss, pf, pa) in U[t].items():
            if len(five) != 5:
                continue
            f = sorted(five)
            for i in range(5):
                for j in range(i + 1, 5):
                    x = pairs[(f[i], f[j])]
                    x[0] += sec; x[1] += poss; x[2] += pf; x[3] += pa
        pr = sorted(([list(k), round(v[0] / 60, 1), round(v[1], 1), v[2], v[3]] for k, v in pairs.items() if v[0] >= 600), key=lambda u: -u[1])
        onoff = []
        for p, (sec, poss, pf, pa) in ON[t].items():
            offp = tt[1] - poss
            onoff.append([p, round(sec / 60, 1), round(poss, 1), pf, pa, round(offp, 1), tt[2] - pf, tt[3] - pa])
        onoff.sort(key=lambda u: -u[1])
        out['teams'][t] = {'min': round(tt[0] / 60, 1), 'poss': round(tt[1], 1), 'pf': tt[2], 'pa': tt[3],
                           'units': units[:40], 'pairs': pr[:40], 'onoff': onoff}
    used = {p for t in out['teams'].values() for k in ('units', 'pairs') for u in t[k] for p in u[0]} | \
           {u[0] for t in out['teams'].values() for u in t['onoff']}
    out['names'] = {p: names.get(p, p) for p in sorted(used)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    print('lineups', S, len(gs), 'games', sum(1 for v in res.values() if v), 'parsed', '->', OUT)
    leaders(S, (gs, res, U, names))


def leaders(S, cur=None):
    """static/data/nba-lineup-leaders.json: league-wide 5-man / trio / pair leaders, this season and last (last
    season's block is kept from the old file once written; delete the file to rebuild it from the cache)"""
    try:
        prev = json.load(open(LEAD_OUT)).get('seasons', {})
    except Exception:
        prev = {}
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'seasons': {}}
    for s in (S, S - 1):
        if s == S and cur:
            gs, res, U, names = cur
        elif str(s) in prev:
            out['seasons'][str(s)] = prev[str(s)]      # a finished season never changes
            continue
        else:
            gs, res = season(s)
            names = player_names(res)
            U = agg_season(gs, res)[0]
        n = sum(1 for g in gs if res.get(g['id']))
        teams = {t: [t, f'/img/nba/{t.lower()}.png', ''] for t in U}
        out['seasons'][str(s)] = LL.season_block(U, K_LEAD, lambda t, p: names.get(p, p), teams, f'{s - 1}-{s % 100:02d}', n)
    with open(LEAD_OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'), allow_nan=False)
    print('leaders', ', '.join(f"{k} {len(v['rows']['5'])}/{len(v['rows']['3'])}/{len(v['rows']['2'])}" for k, v in out['seasons'].items()), '->', LEAD_OUT)


def player_names(res):
    """ESPN athlete id -> display name, from the cached games"""
    out = {}
    for r in res.values():
        if r:
            out.update({k: v for k, v in r.get('nm', {}).items() if v})
    return out


def N_current():
    t = dt.date.today()
    return t.year + (1 if t.month >= 8 else 0)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--pull':
        for S in range(int(a[1]), int(a[2]) + 1):
            t0 = time.time()
            gs, res = season(S)
            print(S, len(gs), 'games', sum(1 for v in res.values() if v), 'parsed', f'{time.time() - t0:.0f}s', flush=True)
    elif a and a[0] == '--split':
        for S in a[1:]:
            split(int(S))
    elif a and a[0] == '--check':
        for S in a[1:]:
            check(int(S))
    else:
        build(int(a[0]) if a else None)
