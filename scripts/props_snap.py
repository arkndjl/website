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
    if now.month not in SEASON:
        return
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


if __name__ == '__main__':
    main()
