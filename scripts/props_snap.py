#!/usr/bin/env python3
"""NBA player prop snapshots for the props paper book (Noah, Oct 21 2026: "player props for picks based on DraftKings
lines from ESPN"). Free data only: DraftKings through ESPN's core API (odds provider 100, propBets), which serves a
game's props only until about a day after it ends, so there is no history to backtest on: the archive starts now.

    python3 scripts/props_snap.py           # the odds-snap workflow runs it every 30 minutes, after odds_snap.py

Each run reads the NBA scoreboard for yesterday, today and tomorrow, pulls every game's DK props that hasn't finished
more than a day ago, and appends to scripts/data/props/nba-<yyyy-mm>.jsonl one row per player prop whose line, price or
our projection changed since its last row:

    {t, id (game), k (tip), a (ESPN athlete id), n (name), s (pts|reb|ast|pra|fg3), L (line), oO, oU (American),
     m (our mean if he plays), sd, pr (our P(plays)), open: [L, oO, oU] on a prop's first row}

m, sd and pr are our projection as it stood at that moment (data/nba_players.json, the last build), so the paper book
never bets on news the line didn't have. The close is a prop's last row before tip. ESPN lists the over first in each
pair (checked against the milestone ladder: the over at 8.5 prices like 9+).

Since Oct 27 2026 (Noah: "switch everything to Novig") a prop takes Novig's main rung and asks where Novig lists it
two-sided (scripts/novig.py nba_props), DraftKings otherwise; src on each row says which ('novig' | 'dk'), and open stays
DraftKings' open where DK lists the prop.

NFL (Oct 29 2026, ARK Edge Sweep) -> scripts/data/props/nfl-<yyyy-mm>.jsonl, the same rows for this week's games:
    player props   s in py ptd pc pa pint ry ca wy rc rwy pry (scripts/nfl_props_archive.py TYPES); m is
                   nfl_fantasy's stat line if he plays (static/data/nfl-fantasy.json; None for pc, pa, ca), pr his
                   chance to play; a is the ESPN athlete id
    game markets   a = 'game', s in 1hs (first-half home-margin line, oO/oU = home/away price), 1hml (oO/oU = home/
                   away), 1ht (first-half total), ttH / ttA (team totals; m = the game model's team points),
                   tt1hH / tt1hA (team first-half totals, DraftKings only)
ESPN serves DraftKings' NFL lines without prices (oO/oU None on a 'dk' row); Novig's rows carry its asks. ESPN still
served DraftKings' NFL props for every 2026 game on Oct 29 2026, but the snapshot is what records the moves and the close.
"""
import datetime
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'data', 'props')
PROJ = os.path.join(ROOT, 'data', 'nba_players.json')
SITE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
CORE = 'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba'
TYPES = {'Total Points': 'pts', 'Total Rebounds': 'reb', 'Total Assists': 'ast',
         'Total Points, Rebounds, and Assists': 'pra', 'Total 3-Point Field Goals': 'fg3'}
SEASON = (10, 11, 12, 1, 2, 3, 4, 5, 6)
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'


def get(url):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
        except Exception:
            pass
    return None


def american(x):
    try:
        s = str(x).strip().lower()
        return 100.0 if s in ('even', 'ev') else float(s)
    except (TypeError, ValueError):
        return None


def props(gid):
    """{(athlete id, stat): [line, over, under, open line, open over, open under]} for one game"""
    items, page = [], 1
    while True:
        j = get(f'{CORE}/events/{gid}/competitions/{gid}/odds/100/propBets?limit=1000&page={page}')
        if not j:
            break
        items += j.get('items', [])
        if page >= j.get('pageCount', 1):
            break
        page += 1
    pairs = {}
    for it in items:
        s = TYPES.get((it.get('type') or {}).get('name'))
        ref = (it.get('athlete') or {}).get('$ref', '')
        if not s or '/athletes/' not in ref:
            continue
        a = ref.split('/athletes/')[1].split('?')[0]
        pairs.setdefault((a, s), []).append(it)
    out = {}
    for k, v in pairs.items():
        if len(v) != 2:
            continue
        o, u = v
        try:
            L = float(o['current']['target']['value'])
            Lo = float(o['open']['target']['value'])
        except (KeyError, TypeError, ValueError):
            continue
        if L != float(u['current']['target']['value']):
            continue
        ao, au = o['odds']['american'], u['odds']['american']
        out[k] = [L, american(ao.get('value')), american(au.get('value')), Lo, american(ao.get('open')), american(au.get('open'))]
    return out


def last_rows(fn_list):
    last = {}
    for fn in fn_list:
        if not os.path.exists(fn):
            continue
        for ln in open(fn):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            last[(r['id'], r['a'], r['s'])] = r
    return last


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.month in SEASON:
        nba(now)
    if now.month in NFL_SEASON:
        try:
            nfl(now)
        except Exception as ex:          # the NBA rows above are written already
            print('nfl props failed:', ex)


def nba(now):
    games = {}
    for d in (-1, 0, 1):
        day = (now + datetime.timedelta(days=d)).strftime('%Y%m%d')
        j = get(f'{SITE}/scoreboard?dates={day}&limit=100') or {}
        for e in j.get('events', []):
            st = e.get('status', {}).get('type', {})
            tip = datetime.datetime.fromisoformat(e['date'].replace('Z', '+00:00'))
            if st.get('completed') and now - tip > datetime.timedelta(hours=30):
                continue
            games[e['id']] = (e['date'], st.get('state') == 'pre')
    try:
        proj = json.load(open(PROJ))
        P = {(g['id'], p['id']): p for g in proj.get('games', []) for p in g.get('players', [])}
    except (OSError, ValueError):
        P = {}
    os.makedirs(OUT, exist_ok=True)
    fn = os.path.join(OUT, f"nba-{now.strftime('%Y-%m')}.jsonl")
    prev = os.path.join(OUT, f"nba-{(now.replace(day=1) - datetime.timedelta(days=1)).strftime('%Y-%m')}.jsonl")
    last = last_rows([prev, fn])
    with ThreadPoolExecutor(6) as ex:
        got = dict(zip(games, ex.map(props, games)))
    # Novig's main prop rung where it has one (Noah, Oct 27 2026: "switch everything to Novig"), DraftKings otherwise;
    # Novig names its players, so they join ESPN athletes through the shared matcher within the game
    src = {}
    try:
        sys.path.insert(0, HERE)
        import names
        import novig
        nv = novig.nba_props()
    except Exception as ex:
        print('novig props failed:', ex)
        nv = {}
    for gid, lines in nv.items():
        if gid not in got:
            continue
        roster = {a: p.get('n') for (g, a), p in P.items() if g == gid and p.get('n')}
        for (name, s), v in lines.items():
            hit = [a for a, n in roster.items() if names.same(name, n)]
            if len(hit) != 1:
                continue
            old = got[gid].get((hit[0], s))
            got[gid][(hit[0], s)] = v + (old[3:] if old else v)
            src[(gid, hit[0], s)] = 'novig'
    t = now.strftime('%Y-%m-%dT%H:%MZ')
    rows = []
    for gid, pr in got.items():
        tip, pre = games[gid]
        if not pre:
            continue                                         # started: the close is the last row before tip
        for (a, s), v in pr.items():
            me = P.get((gid, a)) or {}
            r = {'t': t, 'id': gid, 'k': tip, 'a': a, 's': s, 'L': v[0], 'oO': v[1], 'oU': v[2],
                 'm': me.get(s), 'sd': (me.get('sd') or {}).get(s), 'pr': me.get('pr'),
                 'src': src.get((gid, a, s), 'dk')}
            old = last.get((gid, a, s))
            if old and all(old.get(k) == r[k] for k in ('L', 'oO', 'oU', 'm', 'sd', 'pr')) and old.get('src', 'dk') == r['src']:
                continue
            if not old:
                r['open'] = v[3:]
                r['n'] = me.get('n')
            rows.append(r)
    if rows:
        with open(fn, 'a') as f:
            for r in rows:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    print(len(games), 'games,', sum(len(v) for v in got.values()), 'props (', len(src), 'Novig ),', len(rows), 'rows written')


NFL_SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
NFL_CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl'
NFL_SEASON = (9, 10, 11, 12, 1, 2)
NFL_GAME = {'Team Total Points': 'tt', 'Team 1st Half Total Points': 'tt1h', '1st Half Spread': '1hs', '1st Half Total': '1ht'}
NFL_PROJ = os.path.join(ROOT, 'static', 'data', 'nfl-fantasy.json')
NFL_GAMES = os.path.join(ROOT, 'data', 'nfl_games.json')
# a prop's stat line from nfl_fantasy's (the parts it sums)
NFL_M = {'py': ('py',), 'ptd': ('ptd',), 'pint': ('pint',), 'ry': ('ry',), 'wy': ('wy',), 'rc': ('rc',),
         'rwy': ('ry', 'wy'), 'pry': ('py', 'ry')}


def main_pair(v):
    """the over/under pair among a prop's items [(line, over, under, open line, open over, open under)]: the only two
    items, or the one current line listed exactly twice (the rest are alternate rungs); over first"""
    if len(v) != 2:
        tw = [x for x in {i[0] for i in v} if sum(i[0] == x for i in v) == 2]
        if len(tw) != 1:
            return None
        v = [i for i in v if i[0] == tw[0]]
    o, u = v
    if o[0] is None or o[0] != u[0]:
        return None
    return [o[0], o[1], u[1], o[3], o[4], u[4]]


def nfl_props(gid, home):
    """DraftKings' NFL lines for one game through ESPN: ({(athlete, stat): [L, over, under, open L, open over,
    open under]}, {game key: [...]}); home = ESPN's home team id"""
    from nfl_props_archive import TYPES
    items, page = [], 1
    while True:
        j = get(f'{NFL_CORE}/events/{gid}/competitions/{gid}/odds/100/propBets?limit=1000&page={page}')
        if not j:
            break
        items += j.get('items', [])
        if page >= j.get('pageCount', 1):
            break
        page += 1
    by = {}
    for it in items:
        nm = (it.get('type') or {}).get('name')
        ref = ((it.get('athlete') or it.get('team') or {}).get('$ref') or '')
        tid = ref.split('/teams/')[1].split('?')[0] if '/teams/' in ref else ''
        if nm in TYPES and '/athletes/' in ref:
            key = (ref.split('/athletes/')[1].split('?')[0], TYPES[nm])
        elif nm in NFL_GAME:
            key = ('game', NFL_GAME[nm] + ('' if nm in ('1st Half Spread', '1st Half Total') else 'H' if tid == home else 'A'), tid)
        else:
            continue
        try:
            L, Lo = float(it['current']['target']['value']), float(it['open']['target']['value'])
        except (KeyError, TypeError, ValueError):
            continue
        am = (it.get('odds') or {}).get('american') or {}
        by.setdefault(key, []).append((L, american(am.get('value')), None, Lo, american(am.get('open')), None))
    pl, gm = {}, {}
    for key, v in by.items():
        if key[0] != 'game':
            p = main_pair(v)
            if p:
                pl[key] = p
        elif key[1] == '1hs':
            continue
        else:
            p = main_pair(v)
            if p:
                gm[key[1]] = p
    # first-half spread: one item a team, its own handicap; the home team's sets the line
    hs = [v for k, v in by.items() if k[:2] == ('game', '1hs') and k[2] == home]
    aw = [v for k, v in by.items() if k[:2] == ('game', '1hs') and k[2] != home]
    if len(hs) == 1 and len(hs[0]) == 1:
        h = hs[0][0]
        a = aw[0][0] if len(aw) == 1 and len(aw[0]) == 1 else (None,) * 6
        gm['1hs'] = [-h[0], h[1], a[1], -h[3], h[4], a[4]]
    return pl, gm


def nfl(now):
    games = {}
    for d in range(-1, 7):
        day = (now + datetime.timedelta(days=d)).strftime('%Y%m%d')
        j = get(f'{NFL_SITE}/scoreboard?dates={day}&limit=100') or {}
        for e in j.get('events', []):
            st = e.get('status', {}).get('type', {})
            if st.get('state') != 'pre':
                continue
            c = (e.get('competitions') or [{}])[0]
            home = next((x.get('team', {}).get('id') for x in c.get('competitors', []) if x.get('homeAway') == 'home'), None)
            games[e['id']] = (e['date'], home)
    if not games:
        print('nfl: no games ahead')
        return
    try:
        P = json.load(open(NFL_PROJ)).get('players', [])
    except (OSError, ValueError):
        P = []
    try:
        GM = {str(g['espn']): g for g in json.load(open(NFL_GAMES)).get('games', []) if g.get('espn')}
    except (OSError, ValueError):
        GM = {}
    by_espn = {p['espn']: p for p in P if p.get('espn')}
    with ThreadPoolExecutor(6) as ex:
        got = dict(zip(games, ex.map(lambda g: nfl_props(g, games[g][1]), games)))
    src = {}
    try:
        sys.path.insert(0, HERE)
        import names
        import novig
        nvp, nvg = novig.props('nfl', novig.NFL_PROPS), novig.derivs('nfl')
    except Exception as ex:
        print('novig nfl failed:', ex)
        nvp, nvg = {}, {}
    for gid, lines in nvp.items():
        if gid not in got or gid not in GM:
            continue
        teams = (GM[gid].get('home'), GM[gid].get('away'))
        roster = [p for p in P if p.get('t') in teams and p.get('espn')]
        for (name, s), v in lines.items():
            hit = [p['espn'] for p in roster if names.same(name, p.get('n'))]
            if len(hit) != 1:
                continue
            old = got[gid][0].get((hit[0], s))
            got[gid][0][(hit[0], s)] = v + (old[3:] if old else [None] * 3)
            src[(gid, hit[0], s)] = 'novig'
    for gid, lines in nvg.items():
        if gid not in got:
            continue
        for k, v in lines.items():
            old = got[gid][1].get(k)
            got[gid][1][k] = v + (old[3:] if old else [None] * 3)
            src[(gid, 'game', k)] = 'novig'
    os.makedirs(OUT, exist_ok=True)
    fn = os.path.join(OUT, f"nfl-{now.strftime('%Y-%m')}.jsonl")
    prev = os.path.join(OUT, f"nfl-{(now.replace(day=1) - datetime.timedelta(days=1)).strftime('%Y-%m')}.jsonl")
    last = last_rows([prev, fn])
    t = now.strftime('%Y-%m-%dT%H:%MZ')
    rows = []
    for gid, (pl, gm) in got.items():
        kick = games[gid][0]
        g = GM.get(gid) or {}
        cand = []
        for (a, s), v in pl.items():
            me = by_espn.get(a) or {}
            w = me.get('w') or {}
            m = round(sum(w.get(c, 0.0) for c in NFL_M[s]), 2) if s in NFL_M and w else None
            cand.append((a, s, v, {'m': m, 'pr': me.get('av') if me else None}, me))
        for k, v in gm.items():
            m = g.get('hs') if k == 'ttH' else g.get('as') if k == 'ttA' else None
            cand.append(('game', k, v, {'m': m, 'pr': None}, {}))
        for a, s, v, mm, me in cand:
            r = {'t': t, 'id': gid, 'k': kick, 'a': a, 's': s, 'L': v[0], 'oO': v[1], 'oU': v[2], **mm,
                 'src': src.get((gid, a, s), 'dk')}
            old = last.get((gid, a, s))
            if old and all(old.get(x) == r[x] for x in ('L', 'oO', 'oU', 'm', 'pr')) and old.get('src', 'dk') == r['src']:
                continue
            if not old:
                r['open'] = v[3:]
                if me:
                    r['n'], r['g'] = me.get('n'), me.get('id')
            rows.append(r)
    if rows:
        with open(fn, 'a') as f:
            for r in rows:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    print('nfl:', len(games), 'games,', sum(len(v[0]) for v in got.values()), 'player props,',
          sum(len(v[1]) for v in got.values()), 'game markets (', len(src), 'Novig ),', len(rows), 'rows written')


if __name__ == '__main__':
    main()
