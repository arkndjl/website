#!/usr/bin/env python3
"""Player headshots for the boards that had none: NBA XPM, NHL WAR and goalies, NFL WAR, and the hockey prospects
board (big board and drafted prospects).

    python3 scripts/faces.py            # refresh the lookups and attach photos to the files the pages read now
    python3 scripts/faces.py --test     # print match rates only

Sources (free, no key, public image hosts the pages load directly):
  - NBA: ESPN's team rosters (site.api.espn.com) -> ESPN athlete id, matched to Basketball-Reference ids by name
    and team through the shared matcher (scripts/names.py). Kept in scripts/data/faces_nba.json (bbref id -> ESPN id),
    so a player who leaves a roster keeps his photo. Rows get ph = ESPN id.
  - NHL: the same from ESPN's NHL rosters, keyed by NHL id (scripts/data/faces_nhl.json). The NHL's own mugs are
    full-size PNGs (~110 KB each) with no resizer; ESPN's combiner serves a 96 px crop.
  - NFL: nflverse's season roster (headshot_url, NFL.com's Cloudinary image) keyed by PFR id; scripts/nfl_war.py
    attaches it while it builds (ph = the Cloudinary image id), and this script patches the current file.
  - Hockey prospects: the HockeyTech feeds of the OHL, WHL, QMJHL, USHL and AHL (the public keys in
    scripts/hockey_chl_games.py and hockey_data.py) -> each roster's player_image, matched by name within the
    player's league and club; drafted prospects in the NHL take the NHL map. Kept in scripts/data/faces_hockey.json ("<league>|<name key>" -> [HockeyTech client, player id]).
    Rows get ph = "<client>/<player id>" (assets.leaguestat.com/<client>/240x240/<id>.jpg).
Rows with no match carry no ph and the page shows the neutral frame (static/img/face.svg).
"""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names  # noqa: E402

ROOT = os.path.dirname(HERE)
NBA_MAP = os.path.join(HERE, 'data', 'faces_nba.json')
HOCKEY_MAP = os.path.join(HERE, 'data', 'faces_hockey.json')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
ESPN_NBA = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
ESPN_NHL = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'
NHL_MAP = os.path.join(HERE, 'data', 'faces_nhl.json')
# NHL abbreviation -> ESPN's
NHL_TEAM = {'NJD': 'NJ', 'SJS': 'SJ', 'TBL': 'TB', 'LAK': 'LA', 'UTA': 'UTAH', 'WSH': 'WSH', 'MTL': 'MTL'}
# bbref team -> ESPN abbreviation (as scripts/nba_espn.py)
NBA_TEAM = {'NJ': 'BKN', 'NOH': 'NO', 'NOR': 'NO', 'GSW': 'GS', 'NYK': 'NY', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH',
            'PHO': 'PHX', 'NOP': 'NO', 'BRK': 'BKN', 'CHO': 'CHA'}
HT = 'https://lscluster.hockeytech.com/feed/?feed=modulekit&fmt=json&lang=en&key=%s&client_code=%s'
# board league -> (HockeyTech client, key)
HT_LEAGUE = {'OHL': ('ohl', 'f1aa699db3d81487'), 'WHL': ('whl', '41b145a848f4bd67'),
             'QMJHL': ('lhjmq', 'f322673b6bcae299'), 'USHL': ('ushl', 'e828f89b243dc43f'), 'NTDP': ('ushl', 'e828f89b243dc43f'),
             'AHL': ('ahl', 'ccb91f29d6744675')}


def get(url, tries=3):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30))
        except Exception as e:
            if i == tries - 1:
                print('faces:', url[:90], e, file=sys.stderr)
                return None
            time.sleep(2 * (i + 1))


def load(fn):
    try:
        return json.load(open(fn))
    except (OSError, ValueError):
        return {}


def save(fn, d):
    old = load(fn)
    if old != d:
        with open(fn, 'w') as f:
            json.dump(dict(sorted(d.items())), f, separators=(',', ':'), indent=0)


# ---------------------------------------------------------------- NBA, NHL
def espn_rosters(base):
    """[{name, team, id}] from ESPN's team rosters (players with a headshot)"""
    teams = get(f'{base}/teams') or {}
    out = []
    for t in ((teams.get('sports') or [{}])[0].get('leagues') or [{}])[0].get('teams') or []:
        t = t['team']
        d = get(f"{base}/teams/{t['id']}/roster") or {}
        ath = d.get('athletes') or []
        if ath and 'items' in ath[0]:   # the NHL groups its roster by position
            ath = [a for g in ath for a in g.get('items') or []]
        for a in ath:
            if a.get('headshot'):
                out.append({'name': a.get('displayName') or a.get('fullName'), 'team': t['abbreviation'], 'id': a['id'],
                            'pos': (a.get('position') or {}).get('abbreviation')})
    return out


def nba_attach(players, fresh=True):
    """set p['ph'] (ESPN id) on bbref-keyed rows [{id, n, tm}]; returns how many have one"""
    m = load(NBA_MAP)
    if fresh:
        ros = espn_rosters(ESPN_NBA)
        if ros:
            M = names.Matcher(ros, sport='basketball')
            for p in players:
                tm = NBA_TEAM.get(p.get('tm'), p.get('tm'))
                r, _ = M.find(p['n'], team=None if tm == 'TOT' else tm)
                if r:
                    m[p['id']] = r['id']
            save(NBA_MAP, m)
    for p in players:
        if m.get(p['id']):
            p['ph'] = m[p['id']]
    return sum(1 for p in players if p.get('ph'))


def nhl_attach(players, fresh=True, name='n', team='tm'):
    """set p['ph'] (ESPN id) on NHL-id-keyed rows [{id, n, tm}]; returns how many have one"""
    m = load(NHL_MAP)
    if fresh:
        ros = espn_rosters(ESPN_NHL)
        if ros:
            M = names.Matcher(ros, sport='hockey')
            for p in players:
                tm = p.get(team)
                r, _ = M.find(p[name], team=NHL_TEAM.get(tm, tm) if tm else None)
                if r:
                    m[str(p['id'])] = r['id']
            save(NHL_MAP, m)
    for p in players:
        if m.get(str(p['id'])):
            p['ph'] = m[str(p['id'])]
    return sum(1 for p in players if p.get('ph'))


# ---------------------------------------------------------------- NFL
def nfl_ph(url):
    """NFL.com Cloudinary headshot url -> its image id (the page adds a 96 px transform), or None"""
    if not url or url == 'NA' or '/image/upload/' not in url:
        return None
    return url.rsplit('/league/', 1)[-1] if '/league/' in url else None


# ---------------------------------------------------------------- hockey
def hockey_rosters():
    """[{name, team, league, ph}] from every HockeyTech league's rosters this regular season (league = the client)"""
    from concurrent.futures import ThreadPoolExecutor
    clients = {c: k for c, k in HT_LEAGUE.values()}

    def league(ck):
        c, k = ck
        base = HT % (k, c)
        seasons = ((get(base + '&view=seasons') or {}).get('SiteKit') or {}).get('Seasons') or []
        reg = [s for s in seasons if s.get('career') == '1' and s.get('playoff') == '0']
        if not reg:
            return []
        sid = reg[0]['season_id']
        teams = ((get(base + f'&view=teamsbyseason&season_id={sid}') or {}).get('SiteKit') or {}).get('Teamsbyseason') or []

        def roster(t):
            ros = ((get(base + f"&view=roster&team_id={t['id']}&season_id={sid}") or {}).get('SiteKit') or {}).get('Roster') or []
            out = []
            for p in ros:
                if not isinstance(p, dict):
                    continue
                pid = p.get('player_id') or p.get('id')
                # the QMJHL lists 'Last, First' (and its clubs 'City, Nickname'): use the name parts
                nm = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or p.get('name', '')
                if pid and nm:
                    out.append({'name': nm, 'team': ' '.join(reversed(t['name'].split(', '))), 'league': c, 'ph': f'{c}/{pid}'})
            return out
        with ThreadPoolExecutor(4) as ex:
            return [r for rs in ex.map(roster, teams) for r in rs]
    with ThreadPoolExecutor(len(clients)) as ex:
        return [r for rs in ex.map(league, clients.items()) for r in rs]


def _club_eq(a, b):
    a, b = names.key(a or ''), names.key(b or '')
    return bool(a and b) and (a in b or b in a or a.split()[0] == b.split()[0])


def hockey_attach(board, fresh=True):
    """set r['ph'] on prospect rows [{name, club, league, id?}]: "e<ESPN id>" for one with an NHL id in the NHL map
    (scripts/data/faces_nhl.json), else "<client>/<HockeyTech id>" matched by name (and club) within his league's
    rosters, or by a name unique across all of them (a drafted prospect whose league is last season's). Returns
    how many have one."""
    nm = load(NHL_MAP)
    m = load(HOCKEY_MAP)
    if fresh:
        ros = hockey_rosters()
        if ros:
            by = {}
            for r in ros:
                by.setdefault(r['league'], []).append(r)
            M = {c: names.Matcher(rows, sport='hockey', pos=None, team_eq=_club_eq) for c, rows in by.items()}
            ALL = names.Matcher(ros, sport='hockey', pos=None)
            for b in board:
                c = HT_LEAGUE.get(b.get('league'), (None,))[0]
                r = M[c].find(b['name'], team=b.get('club'))[0] if c in M else None
                if r:
                    m[f"{b['league']}|{names.key(b['name'])}"] = r['ph']
                elif b.get('id') or c:      # the board's players stay in their league; drafted ones may have moved
                    r, how = ALL.find(b['name']) if b.get('id') else (None, None)
                    if r and how == 'name':     # the exact name, held by one player in all of them
                        m[f"*|{names.key(b['name'])}"] = r['ph']
            save(HOCKEY_MAP, m)
    for b in board:
        e = nm.get(str(b.get('id') or ''))
        ph = 'e' + e if e else m.get(f"{b.get('league')}|{names.key(b['name'])}") or (m.get(f"*|{names.key(b['name'])}") if b.get('id') else None)
        if ph:
            b['ph'] = ph
    return sum(1 for b in board if b.get('ph'))


# ---------------------------------------------------------------- the files the pages read now
def patch_nba(test=False):
    d = os.path.join(ROOT, 'static', 'data', 'nba-xpm')
    fn = os.path.join(d, max(f for f in os.listdir(d) if f[:4].isdigit()))
    x = json.load(open(fn))
    n = nba_attach(x['players'])
    print(f"NBA {os.path.basename(fn)}: {n}/{len(x['players'])} with a photo")
    if not test:
        json.dump(x, open(fn, 'w'), separators=(',', ':'))


def patch_nhl(test=False):
    d = os.path.join(ROOT, 'static', 'data', 'nhl-war')
    fn = os.path.join(d, max(f for f in os.listdir(d) if f[:4].isdigit()))
    x = json.load(open(fn))
    n = nhl_attach(x['players'])
    print(f"NHL {os.path.basename(fn)}: {n}/{len(x['players'])} with a photo")
    gf = os.path.join(ROOT, 'data', 'nhl_games.json')
    g = json.load(open(gf))
    ng = nhl_attach(g['goalies'], fresh=False, name='name', team='t')
    print(f"NHL goalies: {ng}/{len(g['goalies'])} with a photo")
    if not test:
        json.dump(x, open(fn, 'w'), separators=(',', ':'))
        json.dump(g, open(gf, 'w'), separators=(',', ':'))


def patch_nfl(test=False):
    import csv, io
    fn = os.path.join(ROOT, 'static', 'data', 'nfl-war.json')
    x = json.load(open(fn))
    url = f"https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{x['season']}.csv"
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=120).read().decode('utf8')
    rows = list(csv.DictReader(io.StringIO(raw)))
    hs = {r['pfr_id']: nfl_ph(r['headshot_url']) for r in rows if r['pfr_id'] not in ('', 'NA')}
    by_name = {(r['full_name'].lower(), r['team']): nfl_ph(r['headshot_url']) for r in rows}   # rows with no PFR id, as nfl_war.py
    for p in x['players']:
        ph = hs.get(p['id']) or by_name.get((p['n'].lower(), p['t']))
        if ph:
            p['ph'] = ph
    print(f"NFL {x['season']}: {sum(1 for p in x['players'] if p.get('ph'))}/{len(x['players'])} with a photo")
    if not test:
        json.dump(x, open(fn, 'w'), separators=(',', ':'))


def patch_hockey(test=False):
    fn = os.path.join(ROOT, 'data', 'hockey.json')
    x = json.load(open(fn))
    n = hockey_attach(x['board'])
    chl = sum(1 for b in x['board'] if b.get('league') in HT_LEAGUE)
    print(f"hockey board: {n}/{len(x['board'])} with a photo ({chl} in the HockeyTech leagues)")
    n = hockey_attach(x['pipe'])   # no club on these rows: the name alone, within the league
    print(f"hockey drafted prospects: {n}/{len(x['pipe'])} with a photo")
    if not test:
        json.dump(x, open(fn, 'w'), separators=(',', ':'))


if __name__ == '__main__':
    t = '--test' in sys.argv
    patch_nba(t)
    patch_nhl(t)
    patch_nfl(t)
    patch_hockey(t)
