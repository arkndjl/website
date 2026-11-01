#!/usr/bin/env python3
"""Hockey prospects ARKBOARD (Noah, Oct 24 2026): every 2027 draft prospect and every drafted player still short of
the NHL, graded on the 20-80 FV scale against what past picks became in the NHL.

    python3 scripts/hockey_data.py            # draft classes 2008-26 (picks, NHL ids, season lines, Central Scouting)
    python3 scripts/hockey_prospects.py --fit # outcome scale, driver selection, stage models -> data/hockey_fit.json
    python3 scripts/hockey_prospects.py       # grades -> data/hockey.json (board, pipeline, past classes)

Outcome   Peak NHL value: the mean of a player's best three seasons of descriptive WAR (static/data/nhl-war/,
          scripts/nhl_players.py; since Oct 25 2026, was the projected value, which underrated defencemen: D coefficient
          -0.55 -> +0.28) in his first seven seasons after the draft, missing seasons counted as 0. Goalies are ranked
          among goalies on peak goals saved above expected and given the skater value at the same rarity, so a goalie
          and a skater with the same FV were as rare among picks.
FV scale  By rarity among picks, classes 2008-19 (about 212 picks a class): 80 = one in four classes (McDavid), 75 =
          one in two, 70 = the best of a class, 65 = top 2, 60 = top 5 (first line, top pair, starting goalie), 55 = top
          10, 50 = top 20 (NHL regular), 45 = top 30, 40 = top 45; below that 20 (no NHL games) to 40 by games played.
          Values between cuts are interpolated. Grades in steps of 1.
Draft     FV = OLS on outcome FV, so the headline is the MEAN outcome (Noah, Oct 21). Base: log draft slot (and its
model     square), defense and goalie flags. Candidates (draft-year line: NHLe a full season from the league's
          translation factor, fit since Oct 25 2026 on the careers of every pick (scripts/hockey_nhle.py), goals share; age at the draft; height, weight; league group; Central Scouting rank; the
          season before; a first-round pick in the CHL priority selection at 15, from HockeyTech profiles): added
          forward while they cut leave-one-class-out error with t >= 2 over the 12 classes and win 8 of 12. CHL first-
          rounders came in 1.9 FV under their slot and line (Oct 29 2026: t 2.76, 9/12; top 64 picks MSE -0.23, forward
          fit 2008-15 / grade 2016-19 MSE -0.33, same sign in all three leagues): the NHL draft still pays for junior
          pedigree that the draft-year line already prices.
Stages    Drafted players after k seasons (k = 1-4): OLS on the draft model's out-of-class grade, the latest season's
          NHLe (NHL and AHL lines translated too), age, NHL games and WAR so far, a World Juniors spot that season,
          pro games that season, NHLe growth since the draft year, AHL shots per game over the league's (HockeyTech's
          public AHL feed, 2008-09 on); inputs kept on the same rule (the last four also had to pass top-of-board and
          forward checks, scripts/hockey_fv_drivers.py). Stages 3-4 fit on picks not yet graduated and add any NHL
          game so far and comps: the mean miss from the stage model of the 30 nearest past picks at that stage
          (Oct 30 2026, scripts/fv_comps_test.py; pool in data/hockey_comps.json). Stages 1, 2 and 4 also carry a
          second fit with his share of his NHL team's preseason games the fall after that season (NHL boxscores,
          scripts/hockey_data.py --pre; Oct 31 2026), used from October, once that preseason is in (PRE_STAGES).
Live      2027 class from Tankathon's NHL big board (rank, league, size, birth month, this season's line). Rank stands in
          for the slot: ln slot = m + b (ln rank - m), m the board's mean log rank, b = .81 from Central Scouting's
          January ranks against the June slot (an in-season board regresses toward the middle by the draft). This
          season's NHLe is shrunk to the slot's typical NHLe with NHLE_K games.
Prov      Draft-eligibles in the CHL, AHL and Liiga feeds who are not on Tankathon's board get a provisional grade
          (scripts/hockey_provisional.py, prov = 1) and join the board in FV order; the table shows those graded PROV_SHOW+.
Display   Pipeline players whose latest line is in Liiga or the SHL carry that season's ice time and shots on goal a game
          (etoi, esog; liiga.fi and shl.se, frozen by hockey_data.py --euro; null otherwise). Not a model input: only
          ~45 gradable Euro-pro picks have TOI seasons, too few to fit (round 2 research, Oct 24 2026).
Files     --fit freezes the pulled classes in scripts/data/hockey_rows.json.gz so the daily build (nhl.yml) needs no
          cache; after each June draft rerun hockey_data.py for the new class, then --fit.
"""
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM
import fv_scale as FS   # the headline's stretched top (80 reachable, about one a board every five seasons)
import nhl_data as D

CACHE = os.path.join(HERE, '.cache', 'hockey')
WARD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
FIT = os.path.join(ROOT, 'data', 'hockey_fit.json')
ROWS = os.path.join(HERE, 'data', 'hockey_rows.json.gz')        # the pulled classes, frozen by --fit for the daily build
AHL = os.path.join(HERE, 'data', 'hockey_ahl.json.gz')          # AHL skater shots by season (scripts/hockey_data.py --ahl)
EURO = os.path.join(HERE, 'data', 'hockey_euro.json.gz')        # Liiga/SHL TOI and SOG by season (hockey_data.py --euro)
CHLP = os.path.join(HERE, 'data', 'hockey_chl_priority.json')   # NHL id -> his CHL priority selection (chl_priority)
PRE = os.path.join(HERE, 'data', 'hockey_pre.json.gz')          # NHL preseason games by start year (hockey_data.py --pre)
OUT = os.path.join(ROOT, 'data', 'hockey.json')
TANK = 'https://tankathon.com/nhl/big-board'
FIRST, LAST_FIT, WINDOW = 2008, 2019, 7
NHLE_K = 20
GOALIE_GP = 50          # NHL games in the window before a goalie's GSAx sets his outcome (FV audit, Oct 26 2026)
PROV_SHOW = 22          # provisional rows on the board table: graded above the floor
# nationality -> lowercase ISO 2 (the pixel flag's id, partials/px/flag.html): the NHL API gives ISO 3, Liiga IOC codes,
# HockeyTech country names, Tankathon the flag file's ISO 2
NAT = {'CAN': 'ca', 'USA': 'us', 'SWE': 'se', 'RUS': 'ru', 'FIN': 'fi', 'CZE': 'cz', 'SVK': 'sk', 'BLR': 'by', 'DEU': 'de',
       'GER': 'de', 'CHE': 'ch', 'SUI': 'ch', 'LVA': 'lv', 'LAT': 'lv', 'NOR': 'no', 'KAZ': 'kz', 'AUT': 'at', 'DNK': 'dk',
       'DEN': 'dk', 'CHN': 'cn', 'ITA': 'it', 'SVN': 'si', 'SLO': 'si', 'GBR': 'gb', 'UKR': 'ua', 'POL': 'pl', 'FRA': 'fr',
       'ZAF': 'za', 'AUS': 'au', 'HRV': 'hr', 'CRO': 'hr', 'HUN': 'hu', 'MDA': 'md', 'EST': 'ee', 'LTU': 'lt', 'JPN': 'jp',
       'KOR': 'kr', 'NLD': 'nl', 'NED': 'nl', 'BEL': 'be', 'CYM': 'ky', 'CAY': 'ky',
       'Canada': 'ca', 'United States': 'us', 'USA': 'us', 'Sweden': 'se', 'Russia': 'ru', 'Finland': 'fi', 'Czechia': 'cz',
       'Czech Republic': 'cz', 'Slovakia': 'sk', 'Belarus': 'by', 'Germany': 'de', 'Switzerland': 'ch', 'Latvia': 'lv',
       'Norway': 'no', 'Kazakhstan': 'kz', 'Austria': 'at', 'Denmark': 'dk', 'China': 'cn', 'Italy': 'it', 'Slovenia': 'si',
       'United Kingdom': 'gb', 'Great Britain': 'gb', 'England': 'gb', 'Scotland': 'gb', 'Ukraine': 'ua', 'Poland': 'pl',
       'France': 'fr', 'South Africa': 'za', 'Australia': 'au', 'Croatia': 'hr', 'Hungary': 'hu', 'Moldova': 'md',
       'Estonia': 'ee', 'Lithuania': 'lt', 'Japan': 'jp', 'South Korea': 'kr', 'Netherlands': 'nl', 'Belgium': 'be',
       'Cayman Islands': 'ky'}


def nat(c):
    """a country as the source gives it -> lowercase ISO 2, or None"""
    c = (c or '').strip()
    if not c:
        return None
    return NAT.get(c) or NAT.get(c.upper()) or (c.lower() if re.fullmatch(r'[a-z]{2}', c) else None)
CUTS = [(80, 0.25), (75, 0.5), (70, 1), (65, 2), (60, 5), (55, 10), (50, 20), (45, 30), (40, 45)]   # FV, picks a class

# NHLe hand constants: NHL points a point in each league (public translation factors; Tankathon's for the CHL and NCAA).
# Since Oct 25 2026 the factors come from data/hockey_nhle.json (scripts/hockey_nhle.py: fit on the careers of every pick
# since 2008, league pairs in the same or the next season, age-adjusted); these stay as the fit's prior, its fallback for a
# league it has no movers for, and the pro / junior cut (PRO_CUT), which is a league tier, not a scoring rate.
HAND = {'NHL': 1.0, 'KHL': .772, 'Rus-KHL': .772, 'Russia': .772, 'SHL': .566, 'Sweden': .566, 'Liiga': .441, 'Finland': .441,
        'SM-liiga': .441, 'NL': .459, 'Swiss': .459, 'Czechia': .469, 'CzRep': .469, 'Czech': .469, 'DEL': .384,
        'Germany': .384, 'AHL': .389, 'VHL': .40, 'Russia2': .40, 'HockeyAllsvenskan': .29, 'Sweden-2': .29,
        'Allsvenskan': .29, 'Slovakia': .27, 'Czechia2': .23, 'CzRep-2': .23, 'Mestis': .21, 'Finland-2': .21,
        'Austria': .3, 'ICEHL': .3, 'EBEL': .3, 'Norway': .17, 'Denmark': .17, 'ECHL': .15,
        'OHL': .323, 'WHL': .302, 'QMJHL': .284, 'NCAA': .333, 'WCHA': .333, 'CCHA': .333, 'H-East': .333, 'ECAC': .333,
        'NCHC': .333, 'Big Ten': .333, 'BIG10': .333, 'Atlantic': .333, 'AHA': .333, 'Hockey East': .333,
        'USHL': .143, 'NTDP': .17, 'USDP': .17, 'USNTDP': .17, 'U.S. National U18 Team': .17, 'MHL': .145,
        'Russia-Jr.': .145, 'J20 Nationell': .19, 'J20 SuperElit': .19, 'Swe-Jr.': .19, 'U20 Nationell': .19,
        'U20 SM-sarja': .15, 'U20 SM-liiga': .15, 'Fin-Jr.': .15, 'Czechia U20': .12, 'CzRep-Jr.': .12,
        'Swiss-Jr.': .12, 'Slovakia-Jr.': .1, 'BCHL': .10, 'NAHL': .10, 'AJHL': .09, 'OJHL': .08, 'CCHL': .08,
        'ON-Jr.A': .08, 'MJHL': .07, 'SJHL': .07, 'CJHL': .08, 'QJHL': .07, 'EJHL': .07, 'USPHL': .06,
        'HockeyEttan': .1, 'Swe-U18': .08, '18U AAA': .04}
TOURN = re.compile(r'^(U-?1[78]|U-?20|WJC|WJ18|WC|OG|Hlinka|IIHF|WHC|U17|U18|5 Nations|4 Nations|World|Int|Olympics)', re.I)
CHL, EPRO = {'OHL', 'WHL', 'QMJHL'}, {'KHL', 'Rus-KHL', 'Russia', 'SHL', 'Sweden', 'Liiga', 'Finland', 'SM-liiga', 'NL', 'Swiss',
                                         'Czechia', 'CzRep', 'Czech', 'DEL', 'Germany', 'VHL', 'Russia2', 'HockeyAllsvenskan',
                                         'Sweden-2', 'Allsvenskan', 'Slovakia', 'Czechia2', 'Mestis', 'Austria', 'ICEHL',
                                         'Norway', 'Denmark', 'AHL', 'NHL'}
NCAA = {'NCAA', 'WCHA', 'CCHA', 'H-East', 'ECAC', 'NCHC', 'Big Ten', 'BIG10', 'Atlantic', 'AHA', 'Hockey East'}
USJR = {'USHL', 'NTDP', 'USDP', 'USNTDP', 'NAHL', 'BCHL', 'AJHL', 'OJHL', 'CCHL', 'ON-Jr.A', 'MJHL', 'SJHL', 'CJHL', 'QJHL',
        'EJHL', 'USPHL', '18U AAA'}


def hand_of(lg):
    if lg in HAND:
        return HAND[lg]
    if lg and (lg.startswith('High') or lg.startswith('USHS')):
        return .05
    return .10


PRO_CUT = .38
NHLE_FILE = os.path.join(ROOT, 'data', 'hockey_nhle.json')
FITTED = json.load(open(NHLE_FILE))['factors'] if os.path.exists(NHLE_FILE) else {}


def nhle_of(lg):
    """the fitted translation factor; a league the fit has no movers for keeps its hand constant on the fitted scale"""
    if lg in FITTED:
        return FITTED[lg]
    return hand_of(lg) * FITTED.get('_unk', 1.0)


def is_pro(lg):
    return hand_of(lg) >= PRO_CUT


def group_of(lg):
    if lg in CHL: return 'chl'
    if lg in NCAA: return 'ncaa'
    if lg in EPRO: return 'epro'
    if lg in USJR or (lg or '').startswith(('High', 'USHS')): return 'usjr'
    return 'ejr'


def main_line(seasons, sid, goalie=False):
    """the season line that best describes a player's season: most games among regular-season club lines"""
    ls = [s for s in seasons if s['season'] == sid and s.get('gameTypeId') == 2 and (s.get('gamesPlayed') or 0) > 0
          and not TOURN.match(s.get('leagueAbbrev') or '')]
    if not ls:
        return None
    # a pro line with real games beats a junior line (a top prospect who split time)
    ls.sort(key=lambda s: -((s['gamesPlayed'] or 0) * (1.5 if is_pro(s['leagueAbbrev']) else 1)))
    return ls[0]


def line_feats(s):
    if not s:
        return None
    gp = s.get('gamesPlayed') or 0
    if gp < 5:
        return None
    f = nhle_of(s['leagueAbbrev'])
    pts = s.get('points') or 0
    return {'lg': s['leagueAbbrev'], 'gp': gp, 'ppg': pts / gp, 'nhle': 82 * f * pts / gp, 'gsh': (s.get('goals') or 0) / max(pts, 1),
            'grp': group_of(s['leagueAbbrev'])}


def post_extra(seasons, sid):
    """a post-draft season beyond the main line: pro games across every club line, and a World Juniors (U20) roster spot"""
    reg = [s for s in seasons if s['season'] == sid and s.get('gameTypeId') == 2 and not TOURN.match(s.get('leagueAbbrev') or '')]
    return {'progp': sum(s.get('gamesPlayed') or 0 for s in reg if is_pro(s['leagueAbbrev'])),
            'wjc': int(any((s.get('leagueAbbrev') or '').startswith('WJC') and s['season'] == sid for s in seasons))}


def ahl_shots(rows):
    """px[k]['ahls']: AHL shots on goal per game that season over the league's (forwards or defence, 20+ GP), None when he
    played fewer than 20 AHL games or the season has no shots in the feed. Joined by birth date + the shared name matcher."""
    A = json.load(gzip.open(AHL, 'rt')) if os.path.exists(AHL) else {}
    by = {}
    for y, t in A.items():
        for p in t['p']:
            if p[1]:
                by.setdefault((int(y), p[1]), []).append(p)
    for r in rows:
        for k, x in (r.get('px') or {}).items():
            t = A.get(str(r['year'] + int(k)))
            c = [p for p in by.get((r['year'] + int(k), r.get('birth')), []) if NM.same(p[0], r['name'])] if t and not r['G'] else []
            x['ahls'] = round(c[0][3] / c[0][2] - t['norm']['D' if r['D'] else 'F'], 4) if len(c) == 1 else None
    return rows


# HockeyTech public feeds (the keys in the leagues' own pages): player search and profiles, whose draft list carries the
# CHL priority selection (OHL and QMJHL at 15, the WHL bantam draft at 14-15) next to the NHL draft
HT = {'OHL': ('f1aa699db3d81487', 'ohl'), 'WHL': ('41b145a848f4bd67', 'whl'), 'QMJHL': ('f322673b6bcae299', 'lhjmq')}


def ht_get(lg, q):
    k, c = HT[lg]
    u = f'https://lscluster.hockeytech.com/feed/index.php?{q}&key={k}&client_code={c}&lang=en&fmt=json'
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': D.UA}), timeout=30).read())['SiteKit']
        except Exception:
            pass
    return {}


def chl_priority(name, birth, lg):
    """[league, round, overall pick, year] of his CHL priority selection, [] when the league lists him without one
    (undrafted, import), None when not found. Search by last name, then birth date (to the month when the day is a
    placeholder, as on Tankathon) and the shared name matcher"""
    if lg not in HT or not birth or not name:
        return None
    last = [w for w in name.split() if w.strip('.').lower() not in NM.SUFFIX][-1]
    s = ht_get(lg, 'feed=modulekit&view=searchplayers&search_term=' + urllib.parse.quote(max(last.split("'"), key=len))).get('Searchplayers') or []
    day = not birth.endswith('-15')
    s = [p for p in s if (p.get('birthdate') or '')[:10 if day else 7] == birth[:10 if day else 7]]
    c = [p for p in s if NM.same(f"{p.get('first_name', '')} {p.get('last_name', '')}", name)]
    if not c:     # a first name the matcher misses (Timothy / Timo): the same birth date and last name
        c = [p for p in s if NM.key(p.get('last_name', '')) == NM.key(last)]
    if len(c) != 1:
        return None
    pr = ht_get(lg, 'feed=modulekit&view=player&category=profile&player_id=' + c[0]['player_id']).get('Player') or {}
    for d in pr.get('draft') or []:
        if d.get('draft_type') in HT and (d.get('draft_rank') or '').isdigit():
            return [d['draft_type'], int(d.get('draft_round') or 0), int(d['draft_rank']), int(d.get('draft_year') or 0)]
    return []


def chl_rows(rows, fetch=False):
    """r['chlp'] for picks whose draft-year line is in the CHL, from the frozen map (fetch: look up the missing ones and
    save the map, for --fit after a new class)"""
    M = json.load(open(CHLP)) if os.path.exists(CHLP) else {}
    new = 0
    for r in rows:
        lg = (r.get('d0') or {}).get('lg')
        if lg not in HT or not r.get('id'):
            continue
        if r['id'] not in M and fetch:
            v = chl_priority(r['name'], r.get('birth'), lg)
            if v is not None:
                M[r['id']] = v; new += 1
        r['chlp'] = M.get(r['id'])
    if new:
        json.dump(M, open(CHLP, 'w'), separators=(',', ':'), sort_keys=True)
    return rows


_EURO = {}


def euro_line(r, season, lg):
    """(TOI minutes a game, shots on goal a game) in Liiga or the SHL that season, or (None, None). Liiga joins on birth date +
    the shared name matcher; the SHL feed has no birth dates, so a unique name match at his position."""
    if not _EURO and os.path.exists(EURO):
        _EURO.update(json.load(gzip.open(EURO, 'rt')))
    key = {'Liiga': 'liiga', 'SHL': 'shl'}.get(lg)
    t = (_EURO.get(str(season)) or {}).get(key) if key else None
    if not t or r['G']:
        return None, None
    pos = 'D' if r['D'] else 'F'
    c = [p for p in t if (p[1] == r.get('birth') if key == 'liiga' else p[2] == pos) and NM.same(p[0], r['name'])]
    if len(c) != 1 or not c[0][4]:
        return None, None
    nm, b, ps, gp, gpt, toi, sog = c[0]
    return round(toi / gpt / 60, 1), round(sog / gp, 2)


def war_tables():
    W = {}
    for fn in os.listdir(WARD):
        if fn[:4].isdigit():
            W[int(fn[:4])] = {p['id']: p for p in json.load(open(os.path.join(WARD, fn)))['players']}
    return W


def landing(pid):
    fn = os.path.join(CACHE, 'landing', f'{pid}.json')
    return json.load(open(fn)) if pid and os.path.exists(fn) else None


def age_at(birth, year):
    try:
        b = dt.date.fromisoformat(birth)
    except (TypeError, ValueError):
        return None
    return (dt.date(year, 9, 15) - b).days / 365.25


def load_rows(W):
    """one row per pick, 2008-26: draft-time features, post-draft lines, NHL outcome"""
    rows = []
    cur = D.current_season()
    for y in range(FIRST, 2027):
        fn = os.path.join(CACHE, f'class_{y}.json')
        if not os.path.exists(fn):
            continue
        d = json.load(open(fn))
        for p in d['picks']:
            L = landing(p.get('id'))
            seasons = (L or {}).get('seasons') or []
            g = p['pos'] == 'G'
            r = {'year': y, 'name': p['name'], 'id': p.get('id'), 'pick': p['pick'], 'team': p['team'], 'pos': p['pos'],
                 'G': int(g), 'D': int(p['pos'] == 'D'), 'ht': p.get('ht'), 'wt': p.get('wt'), 'birth': p.get('birth'),
                 'age': age_at(p.get('birth'), y), 'league': p.get('league'), 'club': p.get('club'), 'country': p.get('country'),
                 'css': p.get('css')}
            r['d0'] = line_feats(main_line(seasons, (y - 1) * 10000 + y))
            r['dm1'] = line_feats(main_line(seasons, (y - 2) * 10000 + y - 1))
            r['post'], r['px'] = {}, {}
            for k in range(1, 5):
                S = y + k
                if S >= cur:
                    break
                r['post'][k] = line_feats(main_line(seasons, (S - 1) * 10000 + S))
                r['px'][k] = post_extra(seasons, (S - 1) * 10000 + S)
            outcome(r, W, cur)
            rows.append(r)
    return chl_rows(ahl_shots(rows), fetch=True)


def outcome(r, W, cur):
    """NHL outcome: WAR seasons in the window (and what is in so far)"""
    wins, gps, gsx = [], 0, []
    for S in range(r['year'] + 1, r['year'] + 1 + WINDOW):
        q = W.get(S, {}).get(r.get('id'))
        if q:
            wins.append(q.get('war') or 0.0); gps += q.get('gp') or 0
            gsx.append(q.get('gsax') or 0.0)
    r['nhl_war'] = wins; r['nhl_gp'] = gps
    r['peak'] = sum((sorted(wins, reverse=True) + [0, 0, 0])[:3]) / 3
    r['gpeak'] = sum((sorted(gsx, reverse=True) + [0, 0, 0])[:3]) / 3
    r['mature'] = r['year'] + WINDOW < cur


def outcome_scale(rows):
    """FV cuts on peak WAR by rarity among 2008-19 picks; goalies mapped by rarity among goalies"""
    fit = [r for r in rows if FIRST <= r['year'] <= LAST_FIT]
    ncls = LAST_FIT - FIRST + 1
    sk = sorted((r['peak'] for r in fit if not r['G']), reverse=True)
    share = len(sk) / len(fit)
    cuts = []
    for fv, per in CUTS:
        k = max(1, int(round(per * ncls * share)))
        cuts.append((fv, sk[k - 1]))
    gk = sorted((r['gpeak'] for r in fit if r['G']), reverse=True)
    return {'cuts': cuts, 'goalie': gk, 'skater': sk, 'classes': ncls}


def fv_of(r, sc):
    """outcome FV of a finished (or in-progress) career"""
    peak = r['peak']
    if r['G']:
        gk, sk = sc['goalie'], sc['skater']
        # a goalie's GSAx ranks him only once he has a real sample (GOALIE_GP): before the gate, any positive best
        # season out-ranked the ~55% of drafted goalies with no games, so 2-5 NHL games graded 45-48 (Wedgewood,
        # Dansk); under it he takes the games path like a skater
        if r['nhl_gp'] < GOALIE_GP:
            peak = 0.0
        else:
            q = sum(1 for v in gk if v > r['gpeak']) / max(len(gk), 1)        # share of goalies above him
            peak = sk[min(int(q * len(sk)), len(sk) - 1)]
    cuts = sc['cuts']
    if peak >= cuts[0][1]:
        return 80.0
    for (f1, v1), (f0, v0) in zip(cuts, cuts[1:]):
        if peak >= v0:
            return f0 + (f1 - f0) * (peak - v0) / max(v1 - v0, 1e-9)
    if r['nhl_gp'] == 0:
        return 20.0
    lo = cuts[-1][1]
    return min(40.0, 30.0 + 10.0 * min(r['nhl_gp'], 200) / 200 * (1 if peak > 0 else 0.6))


# -- features ---------------------------------------------------------------------------------------------------
def feats(r, sl=None):
    """draft-time features (sl overrides ln slot for the live board)"""
    d0, dm = r.get('d0'), r.get('dm1')
    ls = math.log(r['pick']) if sl is None else sl
    g = r['G']
    nh = (d0 or {}).get('nhle')
    ht = r.get('ht') or (73.5 if g else 72.5)
    wt = r.get('wt') or 190
    age = r.get('age') if r.get('age') is not None else 18.5
    css = r.get('css') or {}
    lc = math.log(css['final']) if css.get('final') else math.log(250)
    f = {'ls': ls, 'ls2': ls * ls, 'D': r['D'], 'G': g,
         'nhle': 0.0 if g or nh is None else nh / 10, 'nhle_na': int(not g and nh is None),
         'nhleD': 0.0 if g or nh is None else r['D'] * nh / 10,
         'gsh': 0.0 if g or not d0 else d0['gsh'] - 0.4,
         'age': age - 18.5, 'agenh': (age - 18.5) * (0.0 if g or nh is None else nh / 10),
         'ht': ht - 72.5, 'wt': (wt - 190) / 10,
         'chl': int((d0 or {}).get('grp') == 'chl'), 'ncaa': int((d0 or {}).get('grp') == 'ncaa'),
         'epro': int((d0 or {}).get('grp') == 'epro'), 'usjr': int((d0 or {}).get('grp') == 'usjr'),
         'css': lc - ls, 'cssint': int(css.get('reg') == 'INT'),
         'grow': 0.0 if g or nh is None or not dm or dm.get('nhle') is None else (nh - dm['nhle']) / 10, 'cs': 0.0,
         'chl1': int((d0 or {}).get('grp') == 'chl' and bool(r.get('chlp')) and r['chlp'][1] == 1)}
    return f


# Class strength (Noah, Oct 26 2026: FV grades absolute talent, so it can't depend on the class a player is drafted in).
# The slot is a rank within one class, so on slot alone every class's 5th pick grades the same. cs puts the level back:
# the class's top CS_K picks graded on the draft-time inputs that mean the same in any class (NHLe, age, size, league,
# position; the ABS fit, no slot), their mean against the 2008-19 average, applied to top picks and fading out by
# pick 2 x CS_K. Leave-one-class-out MSE 90.37 -> 90.19 (8/12 classes, t 1.6; the S fit redone inside each fold gives
# the same), top 32 MSE 103.8 -> 102.9, forward (fit 2008-15, grade 2016-19) 83.68 -> 83.44. The current grade's
# top-32 class means spread 42.9-44.8 against realized 42.1-49.2 (r with cs .53); kept as a forced term, not by the
# driver gate, because it is the rule the scale is built on and it is no worse out of sample.
CS_K = 32
ABS = ['nhle', 'nhle_na', 'D', 'G', 'age', 'agenh', 'ht', 'wt', 'chl', 'ncaa', 'epro']


def cs_weight(ls):
    return max(0.0, 1 - ls / math.log(2 * CS_K))


def abs_pred(b, f):
    return b[0] + sum(w * f[c] for w, c in zip(b[1:], ABS))


def class_strength(F, cls, b):
    """{class: mean ABS grade of its top CS_K picks} (F carries ls = ln slot, or the board's expected ln slot)"""
    out = {}
    for c in sorted(set(cls)):
        v = [abs_pred(b, f) for f, k in zip(F, cls) if k == c and f['ls'] <= math.log(CS_K) + 1e-9]
        if v: out[c] = float(np.mean(v))
    return out


def set_cs(F, cls, S, mean):
    for f, c in zip(F, cls):
        f['cs'] = (S[c] - mean) * cs_weight(f['ls']) if c in S else 0.0


BASE = ['ls', 'ls2', 'D', 'G']
CANDS = ['nhle', 'nhle_na', 'nhleD', 'gsh', 'age', 'agenh', 'ht', 'wt', 'chl', 'ncaa', 'epro', 'usjr', 'css', 'cssint', 'grow', 'chl1']


def ols(X, y, lam=1.0):
    X1 = np.column_stack([np.ones(len(X)), X])
    P = lam * np.eye(X1.shape[1]); P[0, 0] = 0
    return np.linalg.solve(X1.T @ X1 + P, X1.T @ y)


def pred(b, X):
    return b[0] + np.asarray(X) @ b[1:]


def loco(F, y, cls, cols):
    """leave-one-class-out predictions"""
    X = np.array([[f[c] for c in cols] for f in F])
    out = np.zeros(len(y))
    for c in sorted(set(cls)):
        m = cls == c
        b = ols(X[~m], y[~m])
        out[m] = pred(b, X[m])
    return out


def score(F, y, cls, cols):
    p = np.clip(loco(F, y, cls, cols), 20, 80)
    return np.array([np.mean((p[cls == c] - y[cls == c]) ** 2) for c in sorted(set(cls))]), p


def select(F, y, cls, base, cands, log=None):
    kept = list(base)
    cur, _ = score(F, y, cls, kept)
    ev = {}
    while True:
        best = None
        for c in cands:
            if c in kept:
                continue
            s, _ = score(F, y, cls, kept + [c])
            d = cur - s                                   # per-class MSE gain
            t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std() > 0 else 0
            ev[c] = {'gain': round(float(d.mean()), 3), 't': round(float(t), 2), 'wins': int((d > 0).sum()), 'of': len(d)}
            if t >= 2 and (d > 0).sum() >= math.ceil(len(d) * 2 / 3) and (best is None or d.mean() > best[1]):
                best = (c, d.mean(), s)
        if best is None:
            break
        kept.append(best[0]); cur = best[2]
        if log: log(f'  + {best[0]}  mse {cur.mean():.2f}  {ev[best[0]]}')
    return kept, ev, cur


def stage_feats(r, k, fv0):
    q = r['post'].get(k)
    nh = (q or {}).get('nhle')
    war = sum(r.get('war_k', {}).get(k, [])) if r.get('war_k') else 0.0
    x = (r.get('px') or {}).get(k) or {}
    nh0 = (r.get('d0') or {}).get('nhle')
    pro = int(bool(q) and is_pro(q['lg']))
    return {'wjc': x.get('wjc', 0) * (1 - r['G']), 'progp': min(x.get('progp', 0), 70) / 70,
            'ahls': 0.0 if r['G'] or x.get('ahls') is None else x['ahls'],
            'nhgrow': 0.0 if r['G'] or nh is None or nh0 is None or pro else (nh - nh0) / 10,
            'fv0': fv0, 'nh': 0.0 if r['G'] or nh is None else nh / 10, 'nh_na': int(not r['G'] and nh is None),
            'nhD': 0.0 if r['G'] or nh is None else r['D'] * nh / 10,
            'pro': int(bool(q) and is_pro(q['lg'])), 'age': (r['age'] or 18.5) - 18.5,
            'gp': min(r['gp_k'].get(k, 0), 164) / 82, 'war': war, 'G': r['G'], 'D': r['D'],
            'nany': int(r['gp_k'].get(k, 0) > 0)}


SBASE = ['fv0']
SCANDS = ['nh', 'nh_na', 'nhD', 'pro', 'age', 'gp', 'war', 'G', 'D']
# Oct 24 2026 (scripts/hockey_fv_drivers.py): a World Juniors spot after the draft, pro games played, and NHLe growth
# since the draft year pass the class-out rule at every stage they are offered to below, and also cut error on the first
# 64 picks and on classes 2016-19 graded from a 2008-15 fit. Where a stage is not offered one, it failed those checks.
SNEW = {1: ['wjc'], 2: ['wjc', 'progp', 'nhgrow'], 3: ['progp'], 4: []}
# Oct 24 2026 (AHL shots, HockeyTech feed): AHL shots per game over the league's, offered after the stage's other inputs
# are chosen (as it was tested: on top of them). Passes at k2 only; at k3-4 it cuts class-out error (t 3.9, 8.1) but
# lowers forward top-64 Spearman (-.004, -.009), so it is not offered there.
SLATE = {1: [], 2: ['ahls'], 3: [], 4: []}
# Oct 30 2026 (scripts/fv_comps_test.py): any NHL game so far. The outcome scale steps from 20 (no NHL games) to 30-40
# at the first game, which the linear games term missed. Stages 3-4 now fit on the board's rows (picks not yet
# graduated, as the pipeline shows them) and offer it: class-out MSE k3 59.2 -> 55.3 (t 5.5), k4 43.3 -> 36.6 (t 7.4),
# forward and top-64 better. At k2 it cuts class-out MSE (t 3.2) but raises forward top-64 MSE (91.2 -> 93.5): not offered,
# and k1-2 keep fitting on every pick.
SNEW[3] = SNEW[3] + ['nany']; SNEW[4] = SNEW[4] + ['nany']
GRAD = {0: 100, 1: 50}           # NHL games (skater, goalie) that graduate a pick off the pipeline
POP_STAGES = (3, 4)


def onboard(r, k):
    """still a prospect k seasons out (the pipeline's population): stages 3-4 fit on these rows"""
    return k not in POP_STAGES or r['gp_k'].get(k, 0) < GRAD[r['G']]


# NHL preseason (Oct 31 2026 FV sweep; NHL game-center boxscores, scripts/hockey_data.py --pre). pnS = his share of his
# NHL team's games in the preseason after the stage's season (the September after season draft year + k): the team's
# own read of where he stands. Each stage keeps its model, and a second fit adds pnS ('pre' in the stage entry); the
# build uses it once that preseason is in (October to July) and the plain model from August to the end of the
# preseason. Seasons without a preseason (2012 lockout, 2020) take the stage mean in the fit. Share, not games: the
# 2026 preseason was cut to 4 games a team from 6-9, and the share held (pipeline means .08-.24 by stage, as before).
# Class-out on the stage rows, on top of the stage model with comps: k1 MSE 83.66 -> 82.09 (t 2.49, 9/12), k2 70.72
# -> 65.30 (t 3.75, 10/12), k4 33.10 -> 30.19 (t 4.62, 10/12); top-64 picks MSE -0.28 / -5.17 / -1.90 and Spearman
# up; forward (fit 2008-15, grade 2016-19) MSE -1.23 / -4.14 / -2.57, top-64 MSE and Spearman better at all three, and
# the same with the 2020 class added to the graded set (6 of 7 seasons in). Stage 3 passes class-out (MSE -4.05, t 2.90,
# 10/12; top-64 and forward MSE better) but forward top-64 Spearman drops .003: not offered. Failed: preseason games
# in the stage's own season (the September before it: t .6-1.8), preseason TOI, points, any game, the first
# preseason after the draft for the draft grade (t 1.9, forward top-64 MSE worse).
PRE_STAGES = (1, 2, 4)
_PRE = {}


def pre_share(r, k):
    """his share of his NHL team's games in the preseason that starts in year draft + k, None when that preseason is
    not in the frozen table (not played yet, or none that year)"""
    if 'd' not in _PRE:
        _PRE['d'] = json.load(gzip.open(PRE, 'rt')) if os.path.exists(PRE) else {}
    t = _PRE['d'].get(str(r['year'] + k))
    if not t:
        return None
    v = t.get(str(r.get('id')))                        # a pick with no NHL player id has never dressed for one
    return min(1.0, v[0] / v[1]) if v else 0.0


def pre_fill(Fk, sub, k, mean=None):
    """pnS on each stage row (the stage mean where the preseason is missing); returns the mean"""
    v = [pre_share(r, k) for r in sub]
    if mean is None:
        a = [x for x in v if x is not None]
        mean = float(np.mean(a)) if a else 0.0
    for f, x in zip(Fk, v):
        f['pnS'] = mean if x is None else x
    return mean


# Comps (Noah, Oct 30 2026: player comps as an FV driver). A stage-k prospect's 30 nearest past picks at the same stage
# (same position group, never his own class; equal weights on the z-scored stage inputs below), and their mean miss
# from the stage model: what picks with his profile went on to do beyond what the linear grade said. Offered after the
# stage's other inputs, on the board's gate. Class-out on the board's rows, eq weights / residual / k 30 (the one
# variant used live; the eq-residual variants pass at stages 2-4 for every k tried), on top of the stage model with
# nany: k3 MSE -2.88 (t 4.2, 11/12), k4 -1.34 (t 4.6, 10/12); top-64 picks and forward (fit 2008-15, grade 2016-19)
# better at both. In the board's own selection (after its other inputs) k3 t 2.65 9/12, k4 t 3.63 10/12; k2 fails
# there (t -.09). Draft-model comps fail (best t 1.7, forward worse); k1 fails forward.
COMP_K = 30
COMP_COLS = ['fv0', 'nh', 'nh_na', 'pro', 'progp', 'wjc', 'gp', 'war', 'age', 'nany']
COMP_STAGES = (3, 4)
COMPS = os.path.join(ROOT, 'data', 'hockey_comps.json')


def comp_grp(r):
    return 2 if r['G'] else (1 if r['D'] else 0)


def comp_of(pool, f, g, own=None, show=0):
    """mean residual of the COMP_K nearest pool rows (same group, other classes than own); show: also the nearest
    few as [name, class, outcome FV]"""
    Z, G_, C, R = pool['_Z'], pool['_g'], pool['_c'], pool['_r']
    z = (np.array([f[c] for c in pool['cols']]) - pool['mu']) / pool['sd']
    m = np.where((G_ == g) if own is None else (G_ == g) & (C != own))[0]
    nn = m[np.argsort(((Z[m] - z) ** 2).sum(1))[:COMP_K]]
    v = float(R[nn].mean())
    return (v, [[pool['names'][i], int(C[i]), int(round(pool['out'][i]))] for i in nn[:show]]) if show else v


def comp_pool(Fk, res, grp, cls, names=None, out=None):
    mu = np.array([np.mean([f[c] for f in Fk]) for c in COMP_COLS])
    sd = np.array([np.std([f[c] for f in Fk]) for c in COMP_COLS]); sd = np.where(sd > 0, sd, 1)
    Z = (np.array([[f[c] for c in COMP_COLS] for f in Fk]) - mu) / sd
    return {'cols': COMP_COLS, 'k': COMP_K, 'mu': mu, 'sd': sd, '_Z': Z, '_g': np.asarray(grp), '_c': np.asarray(cls),
            '_r': np.asarray(res), 'names': names, 'out': out}


def pool_json(p):
    return {'cols': p['cols'], 'k': p['k'], 'mu': [round(float(v), 4) for v in p['mu']], 'sd': [round(float(v), 4) for v in p['sd']],
            'rows': [[round(float(v), 3) for v in z] + [int(g), int(c), round(float(r), 3), n, round(float(o), 1)]
                     for z, g, c, r, n, o in zip(p['_Z'], p['_g'], p['_c'], p['_r'], p['names'], p['out'])]}


def pool_load(j):
    n = len(j['cols'])
    a = np.array([r[:n + 3] for r in j['rows']], float)
    return {'cols': j['cols'], 'k': j['k'], 'mu': np.array(j['mu']), 'sd': np.array(j['sd']), '_Z': a[:, :n],
            '_g': a[:, n].astype(int), '_c': a[:, n + 1].astype(int), '_r': a[:, n + 2],
            'names': [r[n + 3] for r in j['rows']], 'out': [r[n + 4] for r in j['rows']]}


def nhl_so_far(rows, W):
    for r in rows:
        r['gp_k'], r['war_k'] = {}, {}
        gp, wl = 0, []
        for k in range(1, 6):
            q = W.get(r['year'] + k, {}).get(r['id']) if r['id'] else None
            if q:
                gp += q.get('gp') or 0; wl.append(q.get('war') or 0.0)
            r['gp_k'][k] = gp; r['war_k'][k] = list(wl)


def save_rows(rows):
    keep = [{k: v for k, v in r.items() if k not in ('gp_k', 'war_k')} for r in rows]
    with gzip.open(ROWS, 'wt') as f:
        json.dump(keep, f, separators=(',', ':'))


def renhle(q):
    """a frozen line's NHLe on the current factors"""
    if q and q.get('ppg') is not None:
        q['nhle'] = 82 * nhle_of(q['lg']) * q['ppg']
    return q


def read_rows(W):
    """the frozen classes with this season's NHL record laid over them"""
    rows = json.load(gzip.open(ROWS, 'rt'))
    for r in rows:
        r['post'] = {int(k): renhle(v) for k, v in r['post'].items()}
        renhle(r.get('d0')); renhle(r.get('dm1'))
        r['px'] = {int(k): v for k, v in (r.get('px') or {}).items()}
        outcome(r, W, D.current_season())
    return chl_rows(ahl_shots(rows))


def fit(frozen=False, scorecard=False):
    """frozen: refit on scripts/data/hockey_rows.json.gz instead of the pulled cache; scorecard: write only the
    held-out FV scorecard (scripts/fv_scorecard.py) into data/hockey_fit.json and leave the fit as it is"""
    W = war_tables()
    rows = read_rows(W) if frozen else load_rows(W)
    if not frozen and not scorecard:
        save_rows(rows)
    nhl_so_far(rows, W)
    sc = outcome_scale(rows)
    tr = [r for r in rows if FIRST <= r['year'] <= LAST_FIT]
    y = np.array([fv_of(r, sc) for r in tr])
    cls = np.array([r['year'] for r in tr])
    F = [feats(r) for r in tr]
    print('picks', len(tr), 'outcome FV mean', round(y.mean(), 2), 'cuts', [(f, round(v, 2)) for f, v in sc['cuts']])
    base_s, base_p = score(F, y, cls, BASE)
    print('slot-only LOCO mse', round(base_s.mean(), 2))
    kept, ev, cur = select(F, y, cls, BASE, CANDS, log=print)
    # class strength (CS_K): the ABS fit on every pick, then each class's level against the 2008-19 average
    babs = ols(np.array([[f[c] for c in ABS] for f in F]), y)
    S = class_strength(F, cls, babs); Smean = float(np.mean(list(S.values())))
    set_cs(F, cls, S, Smean)
    s_cs, _ = score(F, y, cls, kept + ['cs'])
    d = cur - s_cs
    ev['cs'] = {'gain': round(float(d.mean()), 3), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'wins': int((d > 0).sum()), 'of': len(d)}
    print('  + cs (forced: class strength)', ev['cs'])
    kept = kept + ['cs']
    s_all, p0 = score(F, y, cls, kept)
    X = np.array([[f[c] for c in kept] for f in F]); b = ols(X, y)
    coef = dict(zip(['const'] + kept, [round(float(v), 4) for v in b]))
    print('kept', kept, 'mse', round(s_all.mean(), 2), 'vs slot', round(base_s.mean(), 2)); print(coef)
    # calibration of the out-of-class grades: bands of 5
    calib = []
    for lo in range(20, 80, 5):
        m = (p0 >= lo) & (p0 < lo + 5)
        if m.sum() >= 5:
            calib.append({'band': lo, 'n': int(m.sum()), 'pred': round(float(p0[m].mean()), 1), 'real': round(float(y[m].mean()), 1),
                          'nhl': round(float(np.mean([tr[i]['nhl_gp'] > 0 for i in np.where(m)[0]])), 3)})
    print(calib)
    if scorecard:
        from fv_scorecard import card
        sc_ = card(p0, y, cls=cls, note=f'{len(tr):,} draft picks {FIRST}-{LAST_FIT}, each graded by a fit that left his draft class out; '
                   'outcome: the FV his first NHL seasons earned on WAR; tier odds from a logistic on that grade, also class-out')
        print('scorecard', sc_['summary'])
        cur_fit = json.load(open(FIT)); cur_fit['scorecard'] = sc_
        json.dump(cur_fit, open(FIT, 'w'), indent=1)
        return
    # stage models: k seasons after the draft
    oof = {id(r): float(p) for r, p in zip(tr, p0)}
    stages = {}
    pools = {}
    for k in range(1, 5):
        sub = [r for r in tr if r['year'] + k < D.current_season() and onboard(r, k)]
        Fk = [stage_feats(r, k, oof[id(r)]) for r in sub]
        yk = np.array([fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub])
        s0, _ = score(Fk, yk, ck, SBASE)
        kk, evk, curk = select(Fk, yk, ck, SBASE, SCANDS + SNEW[k])
        if SLATE[k]:
            kk, ev2, curk = select(Fk, yk, ck, kk, SLATE[k]); evk.update(ev2)
        if k in COMP_STAGES:
            # each row's comps carry their class-out miss from the stage model; a row never draws on its own class
            pool = comp_pool(Fk, yk - np.clip(loco(Fk, yk, ck, kk), 20, 80), [comp_grp(r) for r in sub], ck,
                             [r['name'] for r in sub], yk)
            for f, r, c in zip(Fk, sub, ck):
                f['comp'] = comp_of(pool, f, comp_grp(r), own=c)
            kk, ev2, curk = select(Fk, yk, ck, kk, ['comp']); evk.update(ev2)
            if 'comp' in kk:
                pools[k] = pool_json(pool)
        Xk = np.array([[f[c] for c in kk] for f in Fk]); bk = ols(Xk, yk)
        stages[k] = {'kept': kk, 'coef': dict(zip(['const'] + kk, [round(float(v), 4) for v in bk])),
                     'mse': round(float(curk.mean()), 2), 'mseDraft': round(float(s0.mean()), 2), 'ev': evk}
        print('stage', k, kk, 'mse', stages[k]['mse'], 'vs draft grade', stages[k]['mseDraft'])
        if k in PRE_STAGES:
            pm = pre_fill(Fk, sub, k)
            kp, evp, curp = select(Fk, yk, ck, kk, ['pnS'])
            if 'pnS' in kp:
                bp = ols(np.array([[f[c] for c in kp] for f in Fk]), yk)
                stages[k]['pre'] = {'kept': kp, 'coef': dict(zip(['const'] + kp, [round(float(v), 4) for v in bp])),
                                    'mse': round(float(curp.mean()), 2), 'mseDraft': stages[k]['mseDraft'], 'ev': evp, 'pnMean': round(pm, 4)}
                print('  + preseason', 'mse', stages[k]['pre']['mse'], evp['pnS'])
    # slot <- in-season rank: Central Scouting midterm (January) vs the June slot, NA skaters ranked both times
    xs, ys = [], []
    for y0 in range(FIRST, 2027):
        for r in rows:
            c = r.get('css') or {}
            if r['year'] == y0 and c.get('cat') == 1 and c.get('mid') and c.get('final'):
                xs.append(math.log(c['mid'])); ys.append(math.log(r['pick']))
    A = np.column_stack([np.ones(len(xs)), xs]); ab = np.linalg.lstsq(A, np.array(ys), rcond=None)[0]
    rs = np.array(ys) - A @ ab
    # the slot's typical draft-year NHLe (the shrink target for a short season)
    nn = [(math.log(r['pick']), r['d0']['nhle']) for r in tr if not r['G'] and r.get('d0') and r['d0'].get('nhle') is not None]
    nb = np.polyfit([a for a, _ in nn], [v for _, v in nn], 1)
    out = {'asof': dt.date.today().isoformat(), 'classes': [FIRST, LAST_FIT], 'window': WINDOW, 'picks': len(tr),
           'cuts': [[f, round(v, 3)] for f, v in sc['cuts']], 'goalie': [round(v, 2) for v in sc['goalie']],
           'skater': [round(v, 3) for v in sc['skater']],
           'kept': kept, 'coef': coef, 'ev': ev, 'mse': round(float(s_all.mean()), 2), 'mseSlot': round(float(base_s.mean()), 2),
           'calib': calib, 'stages': stages, 'rank2slot': {'a': round(float(ab[0]), 3), 'b': round(float(ab[1]), 3),
                                                         'sd': round(float(rs.std()), 3), 'n': len(xs)},
           'nhleSlot': [round(float(v), 3) for v in nb], 'nhleK': NHLE_K, 'odds': odds_fit(p0, y),
           'abs': {'cols': ABS, 'coef': [round(float(v), 5) for v in babs], 'k': CS_K, 'mean': round(Smean, 3),
                   'byClass': {str(c): round(v, 2) for c, v in S.items()}}}
    json.dump(out, open(FIT, 'w'), indent=1)
    json.dump({'asof': out['asof'], 'k': COMP_K, 'stages': pools}, open(COMPS, 'w'), separators=(',', ':'))
    print('rank2slot', out['rank2slot'], 'nhleSlot', out['nhleSlot'], 'comp pools', {k: len(v['rows']) for k, v in pools.items()})


def tankathon():
    """the 2027 board: [{rk, name, pos, club, league, ht, wt, birth (year-month-15), gp, g, a, p}]"""
    req = urllib.request.Request(TANK, headers={'User-Agent': D.UA})
    try:
        html = urllib.request.urlopen(req, timeout=60).read().decode('utf8', 'replace')
    except Exception as e:
        print('tankathon:', e, file=sys.stderr)
        return None, None
    m = re.search(r'<h1 class="page-title">(\d{4}) NHL Draft', html)
    year = int(m.group(1)) if m else None
    mon = {m: i for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], 1)}
    out = []
    for chunk in html.split('<div class="mock-row nhl"')[1:]:
        def g(rx, d=None):
            x = re.search(rx, chunk)
            return x.group(1).strip() if x else d
        rk, nm = g(r'mock-row-pick-number">(\d+)'), g(r'mock-row-name">([^<]*)')
        if not rk or not nm:
            continue
        sp = g(r'mock-row-school-position">([^<]*)', '')
        pos, _, club = sp.partition('|')
        ht = g(r'class="height">([^<]*)')
        hti = None
        if ht:
            hm = re.match(r"(\d+)&#39;(\d+)", ht) or re.match(r"(\d+)'(\d+)", ht)
            hti = int(hm.group(1)) * 12 + int(hm.group(2)) if hm else None
        yr = re.findall(r'class="year">(\d{4})', chunk); mo = g(r'class="month">([A-Z]{3})')
        vals = dict(re.findall(r'<div class="label">([A-Za-z%]+)</div><div class="value total"[^>]*>([^<]*)', chunk))
        num = lambda k: float(vals[k]) if vals.get(k) not in (None, '', '-') else None
        out.append({'rk': int(rk), 'name': nm.replace('&#39;', "'"), 'pos': pos.strip().split('/')[0], 'posFull': pos.strip(),
                    'club': club.strip().replace('&amp;', '&'), 'league': (g(r'league-name">([^<]*)') or '').replace('\u2011', '-'),
                    'ht': hti, 'wt': int(g(r'class="weight">(\d+)')) if g(r'class="weight">(\d+)') else None,
                    'birth': f"{yr[0]}-{mon.get(mo, 6):02d}-15" if yr else None,
                    'gp': num('GAMES'), 'g': num('GOALS'), 'a': num('ASSISTS'), 'p': num('POINTS'),
                    'nat': nat(g(r'mock-row-logo">\s*<img[^>]*/flags/([a-z]{2})-'))})
    return year, out


TK_LEAGUE = {'Slovak': 'Slovakia', 'HA': 'HockeyAllsvenskan', 'Allsvenskan': 'HockeyAllsvenskan', 'Mestis': 'Mestis', 'NL': 'NL', 'DEL': 'DEL', 'U20 SM-sarja': 'U20 SM-sarja', 'Czechia': 'Czechia', 'Sweden J20': 'J20 Nationell', 'J20 Nationell': 'J20 Nationell',
             'USNTDP': 'NTDP', 'NTDP': 'NTDP', 'USHL': 'USHL', 'Liiga': 'Liiga', 'SHL': 'SHL', 'KHL': 'KHL', 'MHL': 'MHL', 'VHL': 'VHL'}


def grade(fitd, f):
    b = fitd['coef']
    v = b['const'] + sum(b[k] * f.get(k, 0.0) for k in fitd['kept'])
    return min(80.0, max(20.0, v))


def sgrade(st, f):
    b = st['coef']
    return min(80.0, max(20.0, b['const'] + sum(b[k] * f[k] for k in st['kept'])))


def odds(fitd, x):
    """P(40+ outcome: an NHL career) and P(50+: a regular) from the grade, logistic on the out-of-class grades"""
    o = fitd['odds']
    return [1 / (1 + math.exp(-(a + b * (x - 30)))) for a, b in (o['p40'], o['p50'])]


def odds_fit(p0, y, cuts=(('p40', 40), ('p50', 50))):
    out = {}
    for k, cut in cuts:
        t = (y >= cut).astype(float); x = p0 - 30
        a, b = 0.0, 0.1
        for _ in range(50):                                    # Newton steps, two parameters
            z = a + b * x; q = 1 / (1 + np.exp(-z)); w = q * (1 - q)
            g = np.array([np.sum(t - q), np.sum((t - q) * x)])
            H = np.array([[np.sum(w), np.sum(w * x)], [np.sum(w * x), np.sum(w * x * x)]]) + 1e-6 * np.eye(2)
            a, b = np.array([a, b]) + np.linalg.solve(H, g)
        out[k] = [round(float(a), 4), round(float(b), 4)]
    return out


# scouting-report dropdowns: inputs that move together show as one push on the grade
PART = {'ls': 'slot', 'ls2': 'slot', 'D': 'pos', 'G': 'pos', 'nhle': 'nhle', 'nhle_na': 'nhle', 'nhleD': 'nhle',
        'nh': 'nh', 'nh_na': 'nh', 'nhD': 'nh'}


def parts(coef, kept, f, mean):
    """each input's push on the grade against the average 2008-19 pick (stage models: the average pick that far out)"""
    out = {}
    for k in kept:
        g = PART.get(k, k)
        out[g] = out.get(g, 0.0) + coef[k] * (f[k] - mean[k])
    return [[g, round(v, 2)] for g, v in sorted(out.items(), key=lambda kv: -abs(kv[1])) if abs(v) >= .05]


def build():
    fitd = json.load(open(FIT))
    W = war_tables()
    rows = read_rows(W)
    nhl_so_far(rows, W)
    cur = D.current_season()
    sc = {'cuts': fitd['cuts'], 'goalie': fitd['goalie'], 'skater': fitd['skater']}
    # out-of-class grades of the 2008-19 picks: the 30 and 60 rungs of the outcome odds (40 and 50 are in the fit),
    # and the average pick each input's push is measured against
    tr = [r for r in rows if FIRST <= r['year'] <= LAST_FIT]
    Fp = [feats(r) for r in tr]
    y = np.array([fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr])
    # class strength for every drafted class (2008 on), from the frozen picks' draft-time lines
    A = fitd.get('abs')
    Sall = class_strength([feats(r) for r in rows], [r['year'] for r in rows], A['coef']) if A else {}
    csOf = lambda f, c: (Sall[c] - A['mean']) * cs_weight(f['ls']) if A and c in Sall else 0.0
    for f, c in zip(Fp, cls): f['cs'] = csOf(f, c)
    _, p0 = score(Fp, y, cls, fitd['kept'])
    rung = {**fitd['odds'], **odds_fit(p0, y, (('p30', 30), ('p60', 60)))}
    sig = lambda k, x: 1 / (1 + math.exp(-(rung[k][0] + rung[k][1] * (x - 30))))
    mean0 = {k: float(np.mean([f[k] for f in Fp])) for k in fitd['kept']}
    oof = {id(r): float(p) for r, p in zip(tr, p0)}
    meank = {}
    pools = {int(k): pool_load(v) for k, v in json.load(open(COMPS))['stages'].items()} if os.path.exists(COMPS) else {}
    for k, st in fitd['stages'].items():
        sub_r = [r for r in tr if r['year'] + int(k) < cur and onboard(r, int(k))]
        sub = [stage_feats(r, int(k), oof[id(r)]) for r in sub_r]
        if 'comp' in st['kept']:
            for f, r in zip(sub, sub_r):
                f['comp'] = comp_of(pools[int(k)], f, comp_grp(r), own=r['year'])
        meank[k] = {c: float(np.mean([f[c] for f in sub])) for c in st['kept']}
        if st.get('pre'):
            pre_fill(sub, sub_r, int(k), st['pre']['pnMean'])
            meank[k + 'pre'] = {c: float(np.mean([f[c] for f in sub])) for c in st['pre']['kept']}
    r2s, ns = fitd['rank2slot'], fitd['nhleSlot']
    # 1. the coming draft class
    year, tk = tankathon()
    board = []
    seen = set(); tk = [t for t in tk or [] if not ((t['rk'], t['name']) in seen or seen.add((t['rk'], t['name'])))]
    # an overall board: the June slot regresses toward the board's middle at the in-season rate (b), centred on it
    mlr = sum(math.log(t['rk']) for t in tk) / max(len(tk), 1)
    import concurrent.futures as cf
    chlq = [t for t in tk if TK_LEAGUE.get(t['league'], t['league']) in HT]
    with cf.ThreadPoolExecutor(8) as ex:
        chlp = dict(zip([t['name'] for t in chlq], ex.map(lambda t: chl_priority(t['name'], t['birth'], TK_LEAGUE.get(t['league'], t['league'])), chlq)))
    print('CHL priority selections', sum(1 for v in chlp.values() if v), 'of', len(chlq), 'CHL players on the board', flush=True)
    live = []
    for t in tk:
        g = t['pos'] == 'G'
        ls = mlr + r2s['b'] * (math.log(t['rk']) - mlr)
        lg = TK_LEAGUE.get(t['league'], t['league'])
        f0 = nhle_of(lg)
        prior = ns[0] * ls + ns[1]
        gp = t['gp'] or 0
        nh = (82 * f0 * (t['p'] or 0) + NHLE_K * prior) / (gp + NHLE_K) if gp else prior
        nh_raw = 82 * f0 * t['p'] / gp if gp and t['p'] is not None else None
        r = {'pick': 1, 'G': int(g), 'D': int(t['pos'] in ('D', 'LD', 'RD')), 'ht': t['ht'], 'wt': t['wt'], 'age': age_at(t['birth'], year or cur),
             'd0': None if g else {'nhle': nh, 'gsh': (t['g'] or 0) / max(t['p'] or 0, 1) if gp else 0.4, 'grp': group_of(lg)}, 'css': None,
             'chlp': chlp.get(t['name']) if lg in HT else None}
        f = feats(r, sl=ls)
        f['css'] = 0.0
        live.append((t, g, lg, gp, nh_raw, r, f, ls))
    # the class's strength from its top CS_K on the board (in-season NHLe already shrunk toward the slot's typical line)
    S_live = class_strength([f for *_, f, _ in live], [0] * len(live), A['coef']).get(0) if A else None
    for t, g, lg, gp, nh_raw, r, f, ls in live:
        if S_live is not None: f['cs'] = (S_live - A['mean']) * cs_weight(f['ls'])
        x = grade(fitd, f)
        p40, p50 = odds(fitd, x)
        board.append({'rk': t['rk'], 'name': t['name'], 'pos': 'D' if r['D'] else t['pos'], 'posFull': t['posFull'], 'club': t['club'],
                      'league': t['league'], 'grp': group_of(lg), 'ht': t['ht'], 'wt': t['wt'], 'age': round(r['age'], 1) if r['age'] else None,
                      'gp': int(gp), 'pts': int(t['p']) if t['p'] is not None else None, 'nhle': round(nh_raw, 1) if nh_raw is not None else None,
                      'nat': t.get('nat'), 'xslot': round(math.exp(ls)), 'fvx': round(x, 2), 'fv': FS.fv_of('hockey', x), 'p40': round(p40, 3), 'p50': round(p50, 3),
                      'p30': round(sig('p30', x), 3), 'p60': round(sig('p60', x), 3), 'parts': parts(fitd['coef'], fitd['kept'], f, mean0)})
    # provisional grades (Oct 25 2026): draft-eligibles in the CHL, AHL and Liiga feeds who are not on Tankathon's board,
    # graded up from the 20 floor (scripts/hockey_provisional.py) and ranked with the board; the table shows those above
    # the floor (22+), the rest are counted
    import hockey_provisional as HP
    prov = HP.live(year or cur, board, rows) if tk else []
    nprov = len(prov)
    board += [p for p in prov if p['fv'] >= PROV_SHOW]
    board.sort(key=lambda r: (-r['fvx'], r['rk'] or 999))
    # 2. drafted, not yet NHL regulars: the newest five classes
    pipe, pairs = [], []
    for r in rows:
        k = (cur - 1) - r['year']                      # completed seasons since the draft
        if k < 0 or k > 4 or r['year'] < cur - 6:
            continue
        gp_all = sum((W.get(S, {}).get(r['id']) or {}).get('gp') or 0 for S in range(r['year'] + 1, cur + 1)) if r['id'] else 0
        if gp_all >= (50 if r['G'] else 100):
            continue                                    # graduated: an NHL player now (NHL WAR board)
        f0 = feats(r)
        f0['cs'] = csOf(f0, r['year'])
        x0 = grade(fitd, f0)
        comps = None
        if k == 0:
            x, pp = x0, parts(fitd['coef'], fitd['kept'], f0, mean0)
        else:
            st, fk = fitd['stages'][str(k)], stage_feats(r, k, x0)
            mk = meank[str(k)]
            if 'comp' in st['kept']:
                fk['comp'], comps = comp_of(pools[k], fk, comp_grp(r), show=3)
            pn = pre_share(r, k)
            if st.get('pre') and pn is not None:            # his team's preseason since that season is in
                st, fk['pnS'], mk = st['pre'], pn, meank[str(k) + 'pre']
            x, pp = sgrade(st, fk), parts(st['coef'], st['kept'], fk, mk)
        px = (r.get('px') or {}).get(k) or {}
        p40, p50 = odds(fitd, x)
        q = r['post'].get(k) if k else r['d0']
        tm = W.get(cur, {}).get(r['id'], {}).get('tm') if r['id'] else None
        etoi, esog = euro_line(r, r['year'] + k, (q or {}).get('lg'))
        pipe.append({'name': r['name'], 'id': r['id'], 'year': r['year'], 'pick': r['pick'], 'team': r['team'], 'pos': r['pos'],
                     'nat': nat(r.get('country')),
                     'age': round(age_at(r['birth'], cur - 1), 1) if r['birth'] else None, 'k': k,
                     'league': (q or {}).get('lg'), 'gp': (q or {}).get('gp'),
                     'ahls': (r['px'].get(k) or {}).get('ahls') if k else None, 'etoi': etoi, 'esog': esog, 'nhle': round(q['nhle'], 1) if q and not r['G'] else None,
                     'nhlgp': gp_all, 'fv0': FS.fv_of('hockey', x0), 'fv0x': round(x0, 2), 'fvx': round(x, 2), 'fv': FS.fv_of('hockey', x), 'p40': round(p40, 3), 'p50': round(p50, 3),
                     'p30': round(sig('p30', x), 3), 'p60': round(sig('p60', x), 3), 'parts': pp,
                     'nh0': round(r['d0']['nhle'], 1) if not r['G'] and (r.get('d0') or {}).get('nhle') is not None else None,
                     'wjc': int(bool(px.get('wjc'))) if k else 0, 'progp': px.get('progp') if k else None,
                     'war': round(sum(r.get('war_k', {}).get(k, [])), 2) if k and r.get('war_k') else None, 'comps': comps,
                     'pre': round(pn, 2) if k and pn is not None else None})
        pairs.append((pipe[-1], r))
    # predictive badges (scripts/hockey_badges.py, display only): the CHL line of a stage he has a tested badge for
    try:
        import hockey_badges as HB
        print('hockey badges:', HB.assign(pairs), 'pipeline players', flush=True)
    except Exception as e:
        print('hockey badges skipped:', e)
    pipe.sort(key=lambda r: -r['fvx'])
    pipe = [p for i, p in enumerate(pipe) if i < 300 or p['fv'] >= 35]
    # 3. past classes: the out-of-class draft grade and what each pick became
    past = []
    for r, pg, yo in zip(tr, p0, y):
        past.append({'name': r['name'], 'year': r['year'], 'pick': r['pick'], 'team': r['team'], 'pos': r['pos'],
                     'fv': FS.fv_of('hockey', pg), 'fvx': round(float(pg), 2), 'out': int(round(yo)), 'gp': r['nhl_gp'], 'peak': round(r['peak'], 2) if not r['G'] else None,
                     'gpeak': round(r['gpeak'], 1) if r['G'] else None})
    past = [p for p in past if p['pick'] <= 64 or p['fv'] >= 35 or p['out'] >= 45]
    asof = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    pf = json.load(open(HP.FIT)) if os.path.exists(HP.FIT) else None
    out = {'asof': asof, 'year': year, 'season': cur, 'board': board, 'pipe': pipe, 'past': past,
           'prov': {'n': nprov, 'shown': sum(1 for b in board if b.get('prov')), 'min': PROV_SHOW,
                    'fit': {k: pf[k] for k in ('classes', 'boardN', 'n', 'drafted', 'nhl', 'meanFv', 'kept', 'coef', 'ev', 'mse', 'mseFlat',
                                               'mseLate', 'vsFlat', 'vsLate', 'picks', 'top5', 'calib')} if pf else None},
           'nhle': {k: v for k, v in json.load(open(NHLE_FILE)).items() if k in ('asof', 'lines', 'players', 'test')} if os.path.exists(NHLE_FILE) else None,
           'teams': sorted({p['team'] for p in pipe if p['team']}),
           'leagues': sorted({b['league'] for b in board if b['league']}),
           'fit': {k: fitd[k] for k in ('classes', 'window', 'picks', 'cuts', 'kept', 'coef', 'ev', 'mse', 'mseSlot', 'calib', 'rank2slot', 'odds')},
           'classStrength': {'k': CS_K, 'live': round(S_live - A['mean'], 2) if A and S_live is not None else None,
                             'byClass': {str(c): round(v - A['mean'], 2) for c, v in Sall.items()} if A else {}},
           'rungs': rung,
           'stages': {k: {kk: (v.get('pre') or v)[kk] for kk in ('kept', 'coef', 'mse', 'mseDraft')} for k, v in fitd['stages'].items()}}
    try:   # headshots from the CHL/USHL HockeyTech rosters (scripts/faces.py); the board builds without them
        import faces
        print('hockey faces:', faces.hockey_attach(board), 'of', len(board))
    except Exception as e:
        print('hockey faces skipped:', e)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, len(board), 'board', nprov, 'provisional', len(pipe), 'pipeline', len(past), 'past')


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit(frozen='--frozen' in sys.argv)
    elif '--scorecard' in sys.argv:
        fit(frozen=True, scorecard=True)
    else:
        build()
