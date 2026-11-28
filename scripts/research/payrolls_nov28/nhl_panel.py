"""NHL payroll panel, 2011-2026 (season = end year): cap hits from CapWages signings, value from the site's NHL WAR.

    python3 scripts/research/payrolls_nov28/nhl_panel.py        -> panel_nhl.json.gz beside this file (spec: PANEL.md)

Pay: every CapWages signing by league year (capwages.com/signings/<yyyy-yy>, 2002-03 on; cached under
scripts/.cache/payrolls/nhl/). A contract signed in league year Y covers Y..Y+L-1 (start years); an extension
(`Std (Ext)`) starts at Y+1; any other deal signed Jan-Jun starts at Y when he has a WAR row that season, else at Y+1.
A later-signed contract wins the years it overlaps. The cap hit goes to the team in the WAR file that season (one row a
player there, his last team: no split on a trade; retained salary not modelled). A player under contract with no WAR row
(injured, buried or in the minors) is added to his last WAR team with v null only when the hit is above 1.5x the league
minimum and he had a WAR row in the last two seasons (minor leaguers' two-way and entry-level deals, and voided or
bought-out deals, would otherwise fill payrolls). A deal with another club ends the old one. No dead cap.
Standings: api.nhle.com/stats/rest/en/team/summary (w = regulation + OT wins, pts = points).
"""
import collections
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import names as NM          # noqa: E402
from xaav import NHL_CAP, NHL_MIN, next_data, money   # noqa: E402

CACHE = os.path.join(SCRIPTS, '.cache', 'payrolls', 'nhl')
UA = {'User-Agent': 'Mozilla/5.0 (arkboard)'}
SEASONS = range(2011, 2027)
MONTHS = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
# CapWages tricodes and NHL API names -> the WAR files' codes (ARI/PHX -> UTA, ATL -> WPG as the WAR files carry them)
CW_TM = {'ARI': 'UTA', 'PHX': 'UTA', 'ATL': 'WPG', 'UTAH': 'UTA', 'LA': 'LAK', 'NJ': 'NJD', 'SJ': 'SJS', 'TB': 'TBL'}
API_TM = {'Anaheim Ducks': 'ANA', 'Arizona Coyotes': 'UTA', 'Phoenix Coyotes': 'UTA', 'Utah Hockey Club': 'UTA',
          'Utah Mammoth': 'UTA', 'Atlanta Thrashers': 'WPG', 'Winnipeg Jets': 'WPG', 'Boston Bruins': 'BOS',
          'Buffalo Sabres': 'BUF', 'Calgary Flames': 'CGY', 'Carolina Hurricanes': 'CAR', 'Chicago Blackhawks': 'CHI',
          'Colorado Avalanche': 'COL', 'Columbus Blue Jackets': 'CBJ', 'Dallas Stars': 'DAL', 'Detroit Red Wings': 'DET',
          'Edmonton Oilers': 'EDM', 'Florida Panthers': 'FLA', 'Los Angeles Kings': 'LAK', 'Minnesota Wild': 'MIN',
          'Montréal Canadiens': 'MTL', 'Montreal Canadiens': 'MTL', 'Nashville Predators': 'NSH', 'New Jersey Devils': 'NJD',
          'New York Islanders': 'NYI', 'New York Rangers': 'NYR', 'Ottawa Senators': 'OTT', 'Philadelphia Flyers': 'PHI',
          'Pittsburgh Penguins': 'PIT', 'San Jose Sharks': 'SJS', 'Seattle Kraken': 'SEA', 'St. Louis Blues': 'STL',
          'Tampa Bay Lightning': 'TBL', 'Toronto Maple Leafs': 'TOR', 'Vancouver Canucks': 'VAN',
          'Vegas Golden Knights': 'VGK', 'Washington Capitals': 'WSH'}


def fetch(url, fn):
    p = os.path.join(CACHE, fn)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return open(p, 'rb').read()
    os.makedirs(CACHE, exist_ok=True)
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
    open(p, 'wb').write(raw)
    time.sleep(1.2)
    return raw


def parse_date(s):
    s = (s or '').strip()
    m = re.match(r'(\d{4})-(\d\d)-(\d\d)', s)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r'([A-Za-z]+)\.?\s+(\d+),\s*(\d{4})', s)
    if m and m[1][:3].lower() in MONTHS:
        return dt.date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2]))
    return None


def grp(pos):
    p = str(pos or '').split(',')[0].split('/')[0].strip().upper()
    return 'G' if p == 'G' else 'D' if p in ('D', 'LD', 'RD') else 'F'


def signings():
    out = []
    for y in range(2002, 2026):
        s = f'{y}-{str(y + 1)[2:]}'
        for r in next_data(fetch(f'https://capwages.com/signings/{s}', f'cw_signings_{s}.html').decode())['signings']:
            cap = money(r.get('capHit'))
            try:
                ln = int(r.get('length') or 0)
            except ValueError:
                ln = 0
            if cap is None or ln <= 0 or not r.get('slug'):
                continue
            out.append({'slug': r['slug'], 'n': ' '.join(reversed([x.strip() for x in r['player'].split(',', 1)])),
                        'tm': CW_TM.get(r.get('teamTricode'), r.get('teamTricode')), 'grp': grp(r.get('position')),
                        'age': r.get('age'), 'ly': y, 'd': parse_date(r.get('date')), 'L': ln, 'cap': cap,
                        'ct': r.get('contractType')})
    return out


def standings():
    out = {}
    for s in SEASONS:
        d = json.loads(fetch(f'https://api.nhle.com/stats/rest/en/team/summary?cayenneExp=seasonId={s - 1}{s}%20and%20gameTypeId=2',
                             f'nhl_summary_{s}.json'))['data']
        for r in d:
            out[(s, API_TM[r['teamFullName']])] = {'w': r.get('regulationAndOtWins'), 'pts': r['points'], 'gp': r['gamesPlayed'],
                                                     'wins': r['wins']}
    return out


def main():
    war = {s: json.load(open(os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{s}.json')))['players'] for s in SEASONS}
    wgp = collections.defaultdict(dict)       # season -> (name key, grp) -> games
    wtm = collections.defaultdict(dict)       # season -> (name key, grp) -> team
    for y in range(2009, 2027):
        try:
            ps = json.load(open(os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{y}.json')))['players']
        except OSError:
            continue
        for p in ps:
            k = (NM.key(p['n']), p['grp'])
            wgp[y][k] = max(wgp[y].get(k, 0), p.get('gp') or 0)
            wtm[y][k] = p['tm']
    sg = signings()
    # contracts in signing order per slug; seasons are end years (league year Y = season Y+1)
    by_slug = collections.defaultdict(list)
    for c in sg:
        by_slug[c['slug']].append(c)
    hit = collections.defaultdict(dict)      # season -> slug -> contract
    for slug, cs in by_slug.items():
        cs.sort(key=lambda c: (c['d'] or dt.date(c['ly'], 7, 1), c['ly']))
        covered = {}                       # season -> contract in force
        for c in cs:
            k = (NM.key(c['n']), c['grp'])
            d = c['d'] or dt.date(c['ly'], 7, 1)
            off = (d.month, d.day) >= (7, 1) and (d.month, d.day) <= (10, 15)     # signed before the season
            if off:
                s0 = c['ly'] + 1
            elif c['ct'] == 'Std (Ext)':
                s0 = c['ly'] + 2
            else:          # in-season deal: this season if he played in it after signing (approx: any games), else next
                s0 = c['ly'] + 1 if wgp.get(c['ly'] + 1, {}).get(k, 0) > 0 or d.month >= 10 else c['ly'] + 2
            if s0 in covered and (c['ct'] == 'Std (Ext)' or covered[s0]['tm'] == c['tm']):
                while s0 in covered:       # an extension starts when the deal in force ends
                    s0 += 1
            else:                          # a deal with another club ends the old one (trade, buyout, termination)
                for y in [y for y in covered if y >= s0]:
                    del covered[y]
            yrs, s, slides = [], s0, 0
            born = (2026 - c['age']) if c.get('age') else None
            while len(yrs) < c['L']:
                age = (s - 1 - born) if born else 99
                # ELC slide: an 18-19 year old with under 10 NHL games does not use a contract year (at most 2)
                if c['ct'] == 'ELC' and age <= 19 and slides < 2 and s in wgp and wgp[s].get(k, 0) < 10:
                    slides += 1
                else:
                    yrs.append(s)
                s += 1
            for y in yrs:
                covered[y] = c
        for y, c in covered.items():
            if y in SEASONS:
                hit[y][slug] = c
    recent = {s: {k: wtm[y][k] for y in (s - 2, s - 1, s) for k in wgp.get(y, {})} for s in SEASONS}   # last WAR team
    st = standings()
    rows, rep = [], {}
    for s in SEASONS:
        act = hit[s]
        pool = [dict(c, slug=slug) for slug, c in act.items()]
        M = NM.Matcher(pool, name='n', team='tm', pos=None, sport='hockey', team_eq=lambda a, b: a == b)
        used, team_pl = set(), collections.defaultdict(list)
        for p in war[s]:
            k = NM.key(p['n'])
            ex = [c for c in M.by_key.get(k, []) if c['slug'] not in used]
            c = None
            if len(ex) > 1:      # same-name players: team, then position group, then age
                for f in (lambda c: c['tm'] == p['tm'], lambda c: c['grp'] == p['grp'],
                          lambda c: c['age'] is not None and p.get('age') is not None and abs((c['age'] - (2026 - s)) - p['age']) <= 1):
                    ex2 = [c for c in ex if f(c)]
                    if ex2:
                        ex = ex2
                    if len(ex) == 1:
                        break
                if len({(c['cap'], c['tm'], c['d']) for c in ex}) == 1:     # one deal listed under two slugs
                    used.update(c['slug'] for c in ex[1:])
                    ex = ex[:1]
                c = ex[0] if len(ex) == 1 else None
            elif len(ex) == 1:
                c = ex[0]
            else:
                r, how = M.find(p['n'], team=p['tm'], cross_team='variant')
                if r and r['slug'] not in used and r['grp'] == p['grp']:
                    c = r
            if c:
                used.add(c['slug'])
            team_pl[p['tm']].append({'id': p['id'], 'n': p['n'], 'pay': round(c['cap'], 4) if c else None,
                                     'v': p.get('war')})
        floor = 1.5 * NHL_MIN[s - 1]
        for c in pool:
            tm = recent[s].get((NM.key(c['n']), c['grp']))
            if c['slug'] not in used and c['cap'] > floor and tm:
                team_pl[tm].append({'id': 'cw:' + c['slug'], 'n': c['n'], 'pay': round(c['cap'], 4), 'v': None})
        vt = vm = pt = pm = 0.0
        pays = []
        for tm in sorted(team_pl):
            pl = team_pl[tm]
            g = st.get((s, tm))
            if not g:
                print('no standings', s, tm)
                continue
            rows.append({'s': s, 'tm': tm, 'w': g['w'], 'gp': g['gp'], 'pts': g['pts'], 'pl': pl})
            pays.append(sum(x['pay'] or 0 for x in pl))
            for x in pl:
                v = max(x['v'] or 0, 0)
                vt += v
                vm += v if x['pay'] is not None else 0
                pt += x['pay'] or 0
                pm += (x['pay'] or 0) if x['v'] is not None else 0
        cap = NHL_CAP[s - 1]
        rep[s] = (len(pays), vm / vt, pm / pt, sum(pays) / len(pays), cap)
    gp = {s: collections.Counter(r['gp'] for r in rows if r['s'] == s).most_common(1)[0][0] for s in SEASONS}
    out = {'lg': 'nhl', 'unit': 'wins',
           'src': ('Value: site NHL WAR (static/data/nhl-war, wins), one row a player, all of it to his last team (no trade split). '
                   'Pay: CapWages signings 2002-03 on, cap hit of the latest-signed contract in force that season, given to his WAR team '
                   '(cap hit follows the player; retained salary and buried cap not modelled); unmatched contracts above 1.5x the '
                   'minimum, of players with a WAR row in the last two seasons, added to his last WAR team with v null; no dead cap. w = regulation + OT wins, pts = standings points '
                   '(api.nhle.com team summary). ARI/PHX filed as UTA and ATL as WPG, as in the WAR files.'),
           'seasons': {str(s): {'cap': NHL_CAP[s - 1], 'min': NHL_MIN[s - 1], 'gp': gp[s]} for s in SEASONS},
           'rows': rows}
    with gzip.open(os.path.join(HERE, 'panel_nhl.json.gz'), 'wt') as f:
        json.dump(out, f, separators=(',', ':'))
    print('season teams  WAR+%matched  pay$%matched  mean payroll  cap')
    for s, (n, a, b, m, cap) in rep.items():
        print(f'{s}  {n:3d}   {a:6.1%}   {b:6.1%}   {m:6.1f}   {cap:5.1f}')
    print('team-seasons', len(rows))


if __name__ == '__main__':
    main()
