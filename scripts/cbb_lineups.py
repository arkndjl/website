# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""College basketball lineups and on/off from NCAA play-by-play (substitution lines).

ESPN's and hoopR's men's college play-by-play carry no substitutions, so on/off can't come from them. NCAA.com's
game centre play-by-play does ("Subbing in for <team>-<player>"). It is read through the open ncaa-api proxy
(https://github.com/henrygd/ncaa-api, ncaa-api.henrygd.me, public, 5 requests/s a host; we stay near 3/s), which
serves the same JSON the ncaa.com game page shows. Coverage: see data/cbb_lineups_research.json ('coverage').

Each game becomes stints: the five players each team had on the floor between two substitutions, their seconds, and
the points each side scored. Starters per half come from the play-by-play itself (a player whose first entry in a
half is an action or a 'subbing out' started it; anyone on at the end of the last half with no entry carries over).
Possessions are the game's (box-score team counts: FGA - ORB + TO + .475 FTA, both teams' mean) shared by seconds.

  python3 scripts/cbb_lineups.py --pull 2026            # one season into scripts/.cache/cbb/lineups/2026.json.gz
  python3 scripts/cbb_lineups.py --daily                # this season's new games + static/data/cbb-lineups.json
  python3 scripts/cbb_lineups.py --build                # the display file from the cached seasons only

Season = the year it ends (2027 = 2026-27). The display keeps this season and last.
"""
import datetime as dt
import gzip
import json
import os
import re
import sys
import threading
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as N  # noqa: E402
import lineup_leaders as LL  # noqa: E402

API = 'https://ncaa-api.henrygd.me'
UA = 'arkndjl.net cbb lineups'
CACHE = os.path.join(HERE, '.cache', 'cbb', 'lineups')
OUT = os.path.join(ROOT, 'static', 'data', 'cbb-lineups.json')
LEAD_OUT = os.path.join(ROOT, 'static', 'data', 'cbb-lineup-leaders.json')
# lineup leaders (scripts/lineup_leaders.py): sNet toward the team's net, k by unit size = the out-of-sample best
# (odd games predict even and back, 2025-26, 6,259 games; team prior beat a prior of 0 for every size: MSE 5-man
# 1022 vs 1054, trios 460 vs 479, pairs 345 vs 383; raw Net 1978 / 809 / 570)
K_LEAD = {5: 2400, 3: 1600, 2: 2400}
LIVE_SEASON = 2027
RATE = float(os.environ.get('CBB_LINEUP_RATE', 3.0))   # requests a second, all threads (the proxy allows 5)

_lock = threading.Lock()
_last = [0.0]


def _wait():
    with _lock:
        now = time.time()
        gap = 1.0 / RATE - (now - _last[0])
        if gap > 0:
            time.sleep(gap)
        _last[0] = time.time()


def get(path, tries=3):
    for i in range(tries):
        _wait()
        try:
            req = urllib.request.Request(API + path, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=25) as r:
                b = r.read()
            if b[:1] in (b'{', b'['):
                return json.loads(b)
            return None                  # an HTML error page (no play-by-play for the game)
        except urllib.error.HTTPError as e:
            if e.code in (404, 502):
                return None
            time.sleep(2 + 3 * i)
        except Exception:
            time.sleep(2 + 3 * i)
    return None


# ---------------------------------------------------------------- parse
SUB = re.compile(r'^Subbing (in|out) for (.+)$')
NEWACT = re.compile(r"^([A-Z][A-Za-z'\.\- ]+?) (makes|misses|defensive rebound|offensive rebound|turnover|personal foul|"
                    r"shooting foul|offensive foul|technical foul|flagrant|deadball|two point|three point)\b")
OLDACT = re.compile(r"^[A-Za-z0-9 ]+? (?:by|on) (.+?) ?'s ?([^()\[]+?)\s*(?:\(|\[|$)")


def clock_secs(c):
    try:
        x = c.split(':')
        return int(x[0]) * 60 + float(x[1])
    except Exception:
        return None


def period_len(p):
    return 1200 if p <= 2 else 300


def period_start(p):
    return 1200 * min(p - 1, 2) + 300 * max(0, p - 3)


def parse(pbp, box=None):
    """one game -> dict with stints, or a reason string"""
    teams = {str(t['teamId']): t for t in pbp.get('teams', [])}
    if len(teams) != 2:
        return 'teams'
    home = [k for k, t in teams.items() if t.get('isHome')]
    home = home[0] if home else list(teams)[0]
    away = [k for k in teams if k != home][0]
    prefixes = {k: sorted({x for x in (t.get('nameShort'), t.get('nameFull'), t.get('teamName'), t.get('name6Char')) if x}, key=len, reverse=True)
                for k, t in teams.items()}
    ev = []
    prev = None
    for per in pbp.get('periods', []):
        p = int(per.get('periodNumber') or 0)
        for x in per.get('playbyplayStats', []):
            d = (x.get('eventDescription') or '').strip()
            key = (p, x.get('clock'), d)
            if key == prev:
                continue
            prev = key
            cs = clock_secs(x.get('clock') or '')
            if cs is None or p < 1:
                continue
            side = home if (x.get('homeText') or '').strip() and not (x.get('visitorText') or '').strip() else (
                away if (x.get('visitorText') or '').strip() and not (x.get('homeText') or '').strip() else None)
            ev.append(dict(p=p, t=period_start(p) + period_len(p) - cs, d=d, tid=str(x.get('teamId')), side=side,
                           hs=x.get('homeScore'), vs=x.get('visitorScore')))
    if not ev:
        return 'empty'
    nsub = sum(1 for e in ev if e['d'].startswith('Subbing'))
    if nsub < 10:
        return 'nosubs'

    # who is who: sub lines carry the team; action lines vote
    vote = defaultdict(Counter)
    disp = {}
    tkeys = {N.key(y) for pf in prefixes.values() for x in pf for y in (x, re.sub(r'\s*\(.*?\)', '', x))} | {'team', 'tm', 'tv'}

    def nm(raw, tid=None):
        raw = fix_text(raw)
        k = N.key(raw)
        if k in tkeys:
            return None
        if k:
            disp.setdefault(k, raw.strip())
        return k

    for e in ev:
        m = SUB.match(e['d'])
        if m:
            rest = m.group(2)
            tid = e['tid'] if e['tid'] in teams else None
            name = None
            for k in ([tid] if tid else []) + [k for k in teams if k != tid]:
                for pf in prefixes[k]:
                    if rest.startswith(pf + '-'):
                        name, tid = rest[len(pf) + 1:], k
                        break
                if name:
                    break
            if name is None and '-' in rest and tid:
                name = rest.split('-', 1)[1]
            if name and tid:
                k = nm(name)
                if k:
                    e["sub"] = (m.group(1), tid, k)
                    vote[k][tid] += 10
            continue
        # 2021-22 style: "Jumper by Kent St.'s VonCameron Davis" (the team is in the line)
        m = OLDACT.match(e['d'])
        if m:
            tname, pname = m.group(1).strip(), m.group(2).strip()
            tid = None
            for k2, pfs in prefixes.items():
                if any(N.key(pf) == N.key(tname) for pf in pfs):
                    tid = k2
            k = nm(pname)
            if k and tid:
                e['act'] = k
                vote[k][tid] += 1
            continue
        # 2024- style: "Kowacie Reeves Jr. misses three point jump shot" (the team from the side column; lines with a
        # second player in brackets put the line on either side, so they don't vote)
        if '(' in e['d'] and 'assists' not in e['d'] or ' blocks ' in e['d']:
            continue
        m = NEWACT.match(e['d'])
        if m and e['side']:
            if re.search(r'(makes|misses)$', m.group(1)):
                continue
            k = nm(m.group(1))
            if k:
                e['act'] = k
                vote[k][e['side']] += 1
    team_of = {k: c.most_common(1)[0][0] for k, c in vote.items() if c}
    for e in ev:
        if 'act' in e:
            e['act'] = (team_of.get(e['act']), e['act'])

    # on the floor at each period start
    periods = sorted({e['p'] for e in ev})
    on = {home: set(), away: set()}
    starts = {}
    for p in periods:
        first = {}
        for e in ev:
            if e['p'] != p:
                continue
            if 'sub' in e:
                io, tid, k = e['sub']
                first.setdefault((tid, k), io)
            elif 'act' in e and e['act'][0]:
                first.setdefault(e['act'], 'act')
        st = {}
        for tid in (home, away):
            s = {k for (t, k), f in first.items() if t == tid and f in ('out', 'act')}
            for k in on[tid]:
                if (tid, k) not in first and len(s) < 5:
                    s.add(k)
            if len(s) != 5 and p > 1 and len(on[tid]) == 5:
                # the five who ended the last period, changed by the subs logged at this period's opening clock
                s = set(on[tid])
                for e in ev:
                    if e['p'] == p and 'sub' in e and e['sub'][1] == tid and e['t'] == period_start(p):
                        (s.add if e['sub'][0] == 'in' else s.discard)(e['sub'][2])
            if len(s) != 5:
                return f'start{p}:{len(s)}'
            st[tid] = s
        starts[p] = st
        # play the period through to get its end lineup
        cur = {t: set(v) for t, v in st.items()}
        for e in ev:
            if e['p'] == p and 'sub' in e:
                io, tid, k = e['sub']
                (cur[tid].add if io == 'in' else cur[tid].discard)(k)
        on = cur

    # stints
    players = {home: [], away: []}
    idx = {}

    def ix(tid, k):
        if (tid, k) not in idx:
            idx[(tid, k)] = len(players[tid])
            players[tid].append(disp.get(k, k))
        return idx[(tid, k)]

    stints = []
    bad = 0.0
    cur = None
    acc = None

    def close(t, hs, vs):
        nonlocal acc, bad
        if acc is None:
            return
        secs = t - acc['t0']
        if len(cur[home]) == 5 and len(cur[away]) == 5:
            if secs > 0 or hs != acc['hs'] or vs != acc['vs']:
                stints.append([round(secs, 1), sorted(ix(home, k) for k in cur[home]), sorted(ix(away, k) for k in cur[away]),
                               (hs or 0) - acc['hs'], (vs or 0) - acc['vs']])
        else:
            bad += max(0.0, secs)
        acc = None

    # each player's entries in order, to mend a missed substitution line
    occ = defaultdict(list)
    for i, e in enumerate(ev):
        if 'sub' in e:
            occ[(e['sub'][1], e['sub'][2])].append((i, e['sub'][0]))
        elif 'act' in e and e['act'][0]:
            occ[e['act']].append((i, 'act'))

    def nxt(tid, k, i):
        for j, kind in occ.get((tid, k), ()):
            if j > i:
                return j, kind
        return None, None

    def mend(tid, i, group):
        """after the subs at one clock a team has 4 or 6 on the floor: a line was missed. Six: take off the one whose
        next entry is a sub in (else the one seen latest again, or never). Four: put on the one whose next entry is
        an action or a sub out, soonest"""
        s = cur[tid]
        while len(s) > 5:
            cand = [k for k in s if k not in group]
            if not cand:
                break
            def score(k):
                j, kind = nxt(tid, k, i)
                return (0 if kind == 'in' else 1, -(j if j is not None else 10 ** 9))
            s.discard(min(cand, key=score))
        if len(s) < 5:
            pool = [k for (t, k) in occ if t == tid and k not in s and k not in group]
            opts = []
            for k in pool:
                j, kind = nxt(tid, k, i)
                if kind in ('act', 'out') and ev[j]['p'] == ev[i]['p']:
                    opts.append((j, k))
            for _, k in sorted(opts)[:5 - len(s)]:
                s.add(k)

    hs = vs = 0
    lastp = None
    group = defaultdict(set)
    for i, e in enumerate(ev):
        if e['p'] != lastp:
            if acc is not None:
                close(period_start(lastp) + period_len(lastp), hs, vs)
            cur = {t: set(v) for t, v in starts[e['p']].items()}
            lastp = e['p']
            acc = dict(t0=period_start(e['p']), hs=hs, vs=vs)
        try:
            nh, nv = int(e['hs']), int(e['vs'])
        except (TypeError, ValueError):
            nh, nv = hs, vs
        if nh >= hs and nv >= vs:
            hs, vs = nh, nv
        if 'sub' in e:
            io, tid, k = e['sub']
            # a run of subs at one clock is one change
            if acc is not None and (e['t'] > acc['t0'] or hs != acc['hs'] or vs != acc['vs']):
                close(e['t'], hs, vs)
            (cur[tid].add if io == 'in' else cur[tid].discard)(k)
            if io == 'in':
                group[tid].add(k)
            if acc is None:
                acc = dict(t0=e['t'], hs=hs, vs=vs)
            last_of_group = i + 1 >= len(ev) or 'sub' not in ev[i + 1] or ev[i + 1]['t'] != e['t']
            if last_of_group:
                for t in (home, away):
                    if len(cur[t]) != 5:
                        mend(t, i, group[t])
                group = defaultdict(set)
    if acc is not None and lastp:
        close(period_start(lastp) + period_len(lastp), hs, vs)
    total = sum(s[0] for s in stints)
    return dict(home=home, away=away, players=players, stints=stints, bad=round(bad, 1), secs=round(total, 1),
                hs=hs, vs=vs, nper=len(periods))


def box_info(box):
    """possessions (box counts) and players' minutes from the boxscore JSON, when it has them"""
    if not box or 'teamBoxscore' not in box:
        return None, {}
    poss, mins = [], {}
    for tb in box['teamBoxscore']:
        ts = tb.get('teamStats') or {}
        try:
            poss.append(float(ts['fieldGoalsAttempted']) - float(ts['offensiveRebounds']) + float(ts['turnovers']) + .475 * float(ts['freeThrowsAttempted']))
        except (KeyError, TypeError, ValueError):
            pass
        for p in tb.get('playerStats') or []:
            try:
                mins[(str(tb['teamId']), N.key(f"{p.get('firstName', '')} {p.get('lastName', '')}"))] = (float(p.get('minutesPlayed') or 0), bool(p.get('starter')))
            except (TypeError, ValueError):
                pass
    return (round(sum(poss) / len(poss), 1) if len(poss) == 2 else None), mins


def game(gid, meta):
    pbp = get(f'/game/{gid}/play-by-play')
    if not pbp or 'periods' not in pbp:
        return dict(id=gid, err='nopbp', **meta)
    r = parse(pbp)
    if isinstance(r, str):
        return dict(id=gid, err=r, **meta)
    box = get(f'/game/{gid}/boxscore')
    poss, mins = box_info(box)
    r['poss'] = poss
    # minutes check against the box score: player-games within 2 minutes
    if mins:
        mine = defaultdict(float)
        for s in r['stints']:
            for i in s[1]:
                mine[(r['home'], i)] += s[0] / 60
            for i in s[2]:
                mine[(r['away'], i)] += s[0] / 60
        ok = n = 0
        for tid in (r['home'], r['away']):
            for i, name in enumerate(r['players'][tid]):
                b = mins.get((tid, N.key(name)))
                if b is None:
                    continue
                n += 1
                ok += abs(b[0] - mine[(tid, i)]) <= 2.0
        r['chk'] = [ok, n]
    r['tn'] = {k: dict(name=t.get('nameShort'), seo=t.get('seoname')) for k, t in ((str(t['teamId']), t) for t in pbp['teams'])}
    r.update(id=gid, **meta)
    return r


def season_days(season, upto=None):
    d = dt.date(season - 1, 11, 1)
    end = min(dt.date(season, 4, 10), upto or dt.date(season, 4, 10))
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def cache_path(season):
    return os.path.join(CACHE, f'{season}.json.gz')


def fix_text(s):
    """the feed sometimes double-encodes UTF-8 ('BukumiroviÄ‡' for 'Bukumirović')"""
    if s and any(c in s for c in 'ÃÄÅÐÑÂ'):
        for enc in ('cp1252', 'latin-1'):
            try:
                return s.encode(enc).decode('utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    return s


def _mend_names(g):
    """repair double-encoded names in a cached game; two spellings of one player in a game become one"""
    if 'stints' not in g:
        return g
    for si, t in ((1, g['home']), (2, g['away'])):
        names_ = g['players'][t]
        fixed = [fix_text(n) if n else n for n in names_]
        if fixed == names_:
            continue
        uniq, ix = [], {}
        for n in fixed:
            if n not in ix:
                ix[n] = len(uniq); uniq.append(n)
        remap = [ix[n] for n in fixed]
        g['players'][t] = uniq
        for s in g['stints']:
            s[si] = sorted(set(remap[i] for i in s[si]))
    return g


def load(season):
    try:
        games = json.load(gzip.open(cache_path(season)))
    except Exception:
        return {}
    for g in games.values():
        _mend_names(g)
    return games


def save(season, games):
    os.makedirs(CACHE, exist_ok=True)
    tmp = cache_path(season) + '.tmp'
    with gzip.open(tmp, 'wt') as fh:
        json.dump(games, fh, separators=(',', ':'))
    os.replace(tmp, cache_path(season))


def pull(season, upto=None, workers=3, log=True, budget=None, retry=False):
    """fetch the season's final games not yet read. Scoreboards older than 3 days are kept (CACHE/<season>_sb.json),
    so a daily run asks for the last few days only. budget: seconds to spend fetching games (the rest wait for the
    next run)"""
    t0 = time.time()
    games = load(season)
    sbp = os.path.join(CACHE, f'{season}_sb.json')
    try:
        sbc = json.load(open(sbp))
    except Exception:
        sbc = {}
    today = upto or dt.date.today()
    todo = []
    for d in season_days(season, upto):
        ds = d.isoformat()
        if ds in sbc:
            day = sbc[ds]
        else:
            sb = get(f'/scoreboard/basketball-men/d1/{d.year}/{d.month:02d}/{d.day:02d}')
            if sb is None:
                continue
            day = [[str(g['game']['gameID']), g['game']['home']['names']['seo'], g['game']['away']['names']['seo']]
                   for g in sb.get('games', []) if g['game'].get('gameState') == 'final']
            if d < today - dt.timedelta(days=3):
                sbc[ds] = day
        for gid, h, a in day:
            old = games.get(gid)
            if old and 'stints' in old and not (retry and old.get('bad', 0) > 30):
                continue
            if old and old.get('err') and d < today - dt.timedelta(days=3) and not (retry and old['err'].startswith('start')):
                continue                    # an old miss stays a miss
            todo.append((gid, dict(date=ds, h=h, a=a)))
    os.makedirs(CACHE, exist_ok=True)
    json.dump(sbc, open(sbp, 'w'), separators=(',', ':'))
    if log:
        print(f'{season}: {len(todo)} games to fetch', flush=True)
    done = 0

    def one(x):
        if budget and time.time() - t0 > budget:
            return None
        return game(*x)
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, todo):
            if r is None:
                continue
            games[r['id']] = r
            done += 1
            if done % 200 == 0:
                save(season, games)
                if log:
                    print(f'  {done}/{len(todo)}', flush=True)
    save(season, games)
    return games


# ---------------------------------------------------------------- tables
def season_tables(games, upto=None, k_lineup=150.0, k_onoff=600.0):
    """per team: 5-man units and player on/off over the season's games (before `upto` when given).
    Net shrunk to the team's own net by k possessions (units) / to 0 by k possessions (on-off)."""
    unit = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])        # (team, names) -> secs, poss, pf, pa, games
    on = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])              # (team, name) -> secs, poss, pf, pa
    tot = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
    tname = {}
    for g in games.values():
        if 'stints' not in g or (upto and g['date'] >= upto) or None in g['players'][g['home']] + g['players'][g['away']]:
            continue
        secs = g['secs'] or 1
        poss = g.get('poss') or 68.0 * secs / 2400
        for side, opp, si, oi in ((g['home'], g['away'], 1, 3), (g['away'], g['home'], 2, 4)):
            tname[side] = g['tn'][side]
            names_ = g['players'][side]
            seen = set()
            T = tot[side]
            T[4] += 1
            for s in g['stints']:
                ps = poss * s[0] / secs
                pf, pa = (s[3], s[4]) if si == 1 else (s[4], s[3])
                T[0] += s[0]; T[1] += ps; T[2] += pf; T[3] += pa
                key = (side, tuple(sorted(names_[i] for i in s[si])))
                u = unit[key]
                u[0] += s[0]; u[1] += ps; u[2] += pf; u[3] += pa
                if key not in seen:
                    u[4] += 1; seen.add(key)
                for i in s[si]:
                    o = on[(side, names_[i])]
                    o[0] += s[0]; o[1] += ps; o[2] += pf; o[3] += pa
    return unit, on, tot, tname


def net(pf, pa, poss):
    return 100.0 * (pf - pa) / poss if poss > 0 else 0.0


def onoff_rows(on, tot, k=600.0):
    """(team, name) -> dict(on net, off net, on-off, shrunk on-off, minutes, poss on)"""
    out = {}
    for (t, n), (s, p, pf, pa) in on.items():
        T = tot[t]
        offp = T[1] - p
        if p <= 0:
            continue
        onn = net(pf, pa, p)
        offn = net(T[2] - pf, T[3] - pa, offp) if offp > 20 else None
        diff = (onn - offn) if offn is not None else None
        # shrink: on-off has noise ~ 1/p + 1/offp; weight by harmonic possessions
        h = 1.0 / (1.0 / p + 1.0 / max(offp, 1.0))
        out[(t, n)] = dict(min=s / 60, poss=p, on=onn, off=offn, oo=diff, oos=(diff * h / (h + k)) if diff is not None else None, h=h)
    return out


def load_board():
    """the live board's rows by team key: name, team, fv, logo, pos, conf"""
    board = defaultdict(list)
    try:
        b = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json')))
        ci = {c: i for i, c in enumerate(b['cols'])}
        for r in b['rows']:
            board[N.team_key(r[ci['team']] or '')].append(dict(name=r[ci['name']], team=r[ci['team']], fv=r[ci['fv']], logo=r[ci['logo']],
                                                              pos=r[ci['pos']], conf=r[ci['conf']]))
    except Exception:
        pass
    return board


def board_teams(board, tname, on):
    """NCAA team id -> board team key: the school name (bracketed state dropped: 'Miami (FL)'), else the board team
    sharing the most player names (3+)"""
    out = {}
    names = defaultdict(set)
    for (t, n) in on:
        names[t].add(N.key(n))
    bnames = {k: {N.key(r['name']) for r in v} for k, v in board.items()}
    for t, tn in tname.items():
        for s in (tn.get('name') or '', re.sub(r'\s*\(.*?\)', '', tn.get('name') or ''), (tn.get('seo') or '').replace('-', ' ')):
            k = N.team_key(s)
            if k in board:
                out[t] = k
                break
        else:
            best = max(bnames, key=lambda k: len(bnames[k] & names[t]), default=None)
            if best and len(bnames[best] & names[t]) >= 3:
                out[t] = best
    return out


def build(seasons=None):
    seasons = seasons or [LIVE_SEASON - 1, LIVE_SEASON]
    board = load_board()
    out = dict(updated=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), seasons={})
    try:
        prev = json.load(open(OUT)).get('seasons', {})
    except Exception:
        prev = {}
    try:
        lprev = json.load(open(LEAD_OUT)).get('seasons', {})
    except Exception:
        lprev = {}
    lead = dict(asof=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), seasons={})
    for S in seasons:
        games = load(S)
        ok = [g for g in games.values() if 'stints' in g]
        if not ok and str(S) in prev and S < LIVE_SEASON:
            out['seasons'][str(S)] = prev[str(S)]       # a past season's tables stay when its cache isn't here (CI)
            if str(S) in lprev:
                lead['seasons'][str(S)] = lprev[str(S)]
            continue
        unit, on, tot, tname = season_tables(games)
        oo = onoff_rows(on, tot)
        teams = {}
        bt = board_teams(board, tname, on)
        U = defaultdict(dict)
        for (tt, ns), v in unit.items():
            if tt in bt:
                U[tt][ns] = v[:4]
        meta = {t: [board[bt[t]][0]['team'], board[bt[t]][0]['logo'], board[bt[t]][0]['conf']] for t in U}
        lead['seasons'][str(S)] = LL.season_block(U, K_LEAD, lambda t, n: n, meta, f'{S - 1}-{S % 100:02d}', len(ok))
        for t, T in tot.items():
            if T[1] < 1 or t not in bt:          # D-I only: the board's teams
                continue
            tn = tname[t]
            tnet = net(T[2], T[3], T[1])
            cand = board[bt[t]]
            fv, logo, conf = {}, cand[0]['logo'], cand[0]['conf']
            if S == LIVE_SEASON:
                # players by the shared matcher within the team (the board is this season's rosters)
                M = N.Matcher(cand, name='name', team='team', pos='pos', sport='basketball')
                for (tt, n) in on:
                    if tt == t:
                        r, how = M.find(n, team=cand[0]['team'], cross_team='none')
                        if r:
                            fv[n] = r['fv']
            us = []
            for (tt, ns), (s, p, pf, pa, ng) in unit.items():
                if tt != t or s < 120:
                    continue
                n_ = net(pf, pa, p)
                us.append([list(ns), round(s / 60, 1), round(p, 1), round(100 * pf / p, 1), round(100 * pa / p, 1), round(n_, 1),
                           round((n_ * p + tnet * 150.0) / (p + 150.0), 1), ng])
            us.sort(key=lambda u: -u[1])
            ps = []
            for (tt, n), r in oo.items():
                if tt != t:
                    continue
                ps.append([n, round(r['min'], 1), round(r['on'], 1), None if r['off'] is None else round(r['off'], 1),
                           None if r['oo'] is None else round(r['oo'], 1), None if r['oos'] is None else round(r['oos'], 1), fv.get(n)])
            ps.sort(key=lambda x: -x[1])
            us = us[:12]
            # unit members as positions in the players list (top 15 by minutes, plus anyone in a listed unit)
            need = {n for u in us for n in u[0]}
            ps = [p for i, p in enumerate(ps) if i < 15 or p[0] in need]
            pos = {p[0]: i for i, p in enumerate(ps)}
            for u in us:
                u[0] = [pos[n] for n in u[0]]
                u[2] = round(u[2])
            teams[t] = dict(name=cand[0]['team'], conf=conf, logo=logo, g=T[4], min=round(T[0] / 60), poss=round(T[1]), ortg=round(100 * T[2] / T[1], 1),
                            drtg=round(100 * T[3] / T[1], 1), units=us, players=ps)
        out['seasons'][str(S)] = dict(games=len(ok), teams=teams)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    s = json.dumps(out, separators=(',', ':'), allow_nan=False)
    open(OUT, 'w').write(s)
    print(f'wrote {OUT} ({len(s) // 1024} KB): ' + ', '.join(f"{k} {v['games']} games {len(v['teams'])} teams" for k, v in out['seasons'].items()))
    s = json.dumps(lead, separators=(',', ':'), allow_nan=False)
    open(LEAD_OUT, 'w').write(s)
    print(f'wrote {LEAD_OUT} ({len(s) // 1024} KB): ' + ', '.join(f"{k} " + '/'.join(str(len(v['rows'][z])) for z in '532') for k, v in lead['seasons'].items()))


def main():
    a = sys.argv[1:]
    if '--pull' in a:
        S = int(a[a.index('--pull') + 1])
        pull(S, retry='--retry' in a)
    elif '--daily' in a:
        today = dt.date.today()
        if today >= dt.date(LIVE_SEASON - 1, 11, 1):
            # at most ~6 minutes of game pulls a run (a lost cache catches up over a few runs)
            pull(LIVE_SEASON, upto=today, budget=float(os.environ.get('CBB_LINEUP_BUDGET', 360)))
        build()
    elif '--build' in a:
        build()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
