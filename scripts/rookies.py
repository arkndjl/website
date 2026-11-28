#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Rookie and first-year leaderboards (Oct 25 2026): one tab in every pro, college and prospect section that ranks the
newcomers by that section's own value and production metrics, next to their pre-draft (or pre-arrival) grade.
Display only: no new model, every number comes from the section's existing build.

    python3 scripts/rookies.py [nfl nba nhl soccer cfb cbb hockey soccerp]   # default: all
    -> static/data/rookies/<sport>.json, drawn by layouts/shortcodes/rookies.html

Who counts as a rookie / first-year
    nfl      nflverse's rookie flag on the WAR board (years_exp 0 / rookie_year = season); slot from nflverse draft_picks,
             pre-draft FV = the CFB board's last college FV (static/data/cfb-past.json, the --past refit)
    nba      first season on the XPM board (2010-11 on; 2009-10 is the first board, so only that year's picks count);
             slot from scripts/nba_draft.json, pre-draft FV = the CBB board's draft-year FV joined by class + pick
             (static/data/cbb-past.json); current season adds XPM (proj) and contract surplus (static/data/nba-proj.json);
             aXPM = XPM + k (age - A0), k from data/nba_rookie_age_research.json; 3Y = data/nba_rookie_proj_fit.json
    nhl      the Calder rule: under 25 NHL games in any one prior season, not 6+ in each of two prior seasons, under 26 on
             Sep 15 (2011-12 on, the WAR tables start 2009-10); slot from scripts/data/hockey_rows.json.gz, draft FV
             from data/hockey.json (pipeline fv0 by id, past classes by name + class)
    soccer   first big-five season on the GAR board (2015-16 on); prospect FV from data/soccer_prospects.json (board by
             Transfermarkt id through scripts/data/soccer_mv_link.json.gz, past classes by id + season)
    cfb      true freshmen: eligibility year 1, no redshirt (the board's own elig, static/data/cfb-all.json)
    cbb      true freshmen: Fr, eligibility year 1 (static/data/cbb-all.json)
    hockey   CHL and AHL rookies flagged by HockeyTech (first season in the OHL, WHL, QMJHL or AHL); FV from the prospect
             board (coming class, data/hockey.json board) or the pipeline (drafted)
    soccerp  first senior season: on the prospect board with no league minutes last season (min1 = 0)
"""
import datetime as dt
import gzip
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM
import nba_xpm as XP         # role_sxpm: the shrink the rookie 3Y / aXPM fits were trained on

OUT = os.path.join(ROOT, 'static', 'data', 'rookies')
SD = os.path.join(ROOT, 'static', 'data')


def J(*p):
    return json.load(open(os.path.join(ROOT, *p), encoding='utf-8'))


def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')


def r1(x, d=1):
    return None if x is None else round(x, d)


def col(k, l, t, f='1', ph=0, num=1):
    return {'k': k, 'l': l, 't': t, 'f': f, 'ph': ph, 'num': num}


# photo and team-logo URLs for the rows (ph, lo): the same sources the section boards draw from
ESPN_FACE = 'https://a.espncdn.com/combiner/i?img=/i/headshots/{}/players/full/{}.png&w=96&h=70&scale=crop'
NFL_FACE = 'https://static.www.nfl.com/image/upload/f_auto,q_auto,w_96/league/{}'
TM_FACE = 'https://img.a.transfermarkt.technology/portrait/medium/{}'


def hw(ht, wt=None, cm=False):
    """Ht / Wt for the context column: ('6-4 / 222', inches). ht as '6-4', 6' 8", inches, or cm (cm=True)."""
    h = None
    if isinstance(ht, (int, float)) and ht:
        h = ht / 2.54 if cm else float(ht)
    elif isinstance(ht, str):
        m = re.match(r"\s*(\d)\s*(?:-|'|ft)\s*(\d{1,2}(?:\.\d+)?)", ht)
        if m:
            h = int(m.group(1)) * 12 + float(m.group(2))
    try:
        w = int(round(float(wt))) if wt not in (None, '', 0) else None
    except (TypeError, ValueError):
        w = None
    if h is None and w is None:
        return {}
    hs = f"{int(h // 12)}-{int(round(h % 12)) if round(h % 12) < 12 else 11}" if h else '–'
    if cm and h:
        hs = f'{int(round(h * 2.54))} cm'
    return {'hw': hs + (f' / {w}' if w else ''), 'hi': round(h, 1) if h else None}


def logo(path):
    return path if path and os.path.exists(os.path.join(ROOT, 'static', path.lstrip('/'))) else None


def cfb_face(r):
    # cfb-all.json writes 1 for ESPN's standard headshot of the player's ESPN id (espnl), as assets/js/cfb.js rebuilds it
    p = r.get('photo')
    if p == 1:
        m = re.search(r'/id/(\d+)', r.get('espnl') or '')
        return f'https://a.espncdn.com/i/headshots/college-football/players/full/{m.group(1)}.png' if m else None
    return p or None


def hockey_logo(u):
    # HockeyTech's logo URL -> the local copy (scripts/hockey_logos.py), which the GFX canvas can draw
    m = re.match(r'https?://assets\.leaguestat\.com/(\w+)/logos/(\d+)(?:_\d+)?\.\w+$', u or '')
    return (logo(f'/img/hockey/{m.group(1)}/{m.group(2)}.png') if m else None) or u or None


def soccer_logo(club):
    L = J('data', 'soccer_logos.json')
    e = L.get('espn', {}).get(club)
    if e:
        return logo(f'/img/soccer/{e}.png')
    t = L.get('tm', {}).get(club)
    return logo(f'/img/soccer/tm/{t}.png') if t else None


def write(sport, out):
    os.makedirs(OUT, exist_ok=True)
    out = {'sport': sport, 'asof': out.pop('asof', None) or now(), **out}
    fn = os.path.join(OUT, f'{sport}.json')
    json.dump(out, open(fn, 'w', encoding='utf-8'), separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    print('wrote', fn, ' '.join(f"{s['l']}:{len(s['rows'])}" for s in out['seasons']))


def write_ids(sport, ids):
    """<sport>-ids.json: {season: [board ids]}, the same rookies by the leaderboard's own player id, read by the R chip
    on the NBA XPM, NHL WAR and soccer player boards (one small file, so the boards never load the rookie tab)."""
    fn = os.path.join(OUT, f'{sport}-ids.json')
    json.dump({str(k): v for k, v in sorted(ids.items())}, open(fn, 'w', encoding='utf-8'), separators=(',', ':'))
    print('wrote', fn)


def season_pts(fn, groups):
    """(name, team) -> this season's SV over replacement (data/nfl_qb.json spts, data/nfl_season_value.json pts,
    data/cfb_season_value.json pts); id -> SV where the file carries ids."""
    try:
        d = J('data', fn)
    except (OSError, ValueError):
        return [], {}
    out, ids = [], {}
    for g, k in groups:
        for r in d.get(g) or []:
            v = r.get(k)
            if v is None:
                continue
            out.append((r['n'], r.get('t') or '', v))
            if r.get('id'):
                ids[str(r['id'])] = v
    return out, ids


def pts_of(L, n, t):
    m = [v for nn, tt, v in L if NM.same(nn, n) and (not t or not tt or tt == t)]
    return m[0] if len(m) == 1 else None


SPTS_T = ('SV (season value): this season\'s points over replacement a game, opponent-adjusted EPA (QBs: dropbacks + runs; skill: runs + '
          'targets; defenders: credited EPA on negative plays), as on the QBs / skill players / defenders tabs')

SVAR_T = 'SVAR: SV over replacement, season total, in wins: points'


# ---------------------------------------------------------------- NFL
def nfl():
    import nfl_war as N
    b = json.load(open(os.path.join(SD, 'nfl-war.json')))
    y = b['season']
    picks = {}
    try:
        for r in N.rows(N.get('draft_picks.csv', f'{N.REL}/draft_picks/draft_picks.csv')):
            if r['season'] == str(y) and r['pfr_player_id']:
                picks[r['pfr_player_id']] = r
    except Exception as e:      # the board still shows WAR without slots
        print('nfl: draft picks not read:', e)
    # the draft ledger's last snapshot before the draft (scripts/draft_ledger.py, classes 2027 on); cfb-past only holds
    # players still in college, so a class drafted before the ledger began has no pre-draft FV
    prow = []
    ld = os.path.join(HERE, 'data', 'ledger', 'cfb', str(y))
    snaps = sorted(f for f in os.listdir(ld) if f < f'{y}-04-20') if os.path.isdir(ld) else []
    if snaps:
        s = json.load(gzip.open(os.path.join(ld, snaps[-1])))
        prow = [dict(zip(s['cols'], r)) for r in s['rows']]
    M = NM.Matcher(prow, pos=None)
    SP = season_pts('nfl_qb.json', [('rows', 'spts')])[0] + season_pts('nfl_season_value.json', [('skill', 'pts'), ('defense', 'pts')])[0]
    SW = season_pts('nfl_qb.json', [('rows', 'svar')])[0] + season_pts('nfl_season_value.json', [('skill', 'svar'), ('defense', 'svar')])[0]
    rows = []
    for p in b['players']:
        if not p.get('rook'):
            continue
        d = picks.get(p['id'])
        m, _ = M.find(p['n'], team=p.get('col') or None)
        pre = int(d['pick']) if d and d['pick'] else None
        rows.append({'n': p['n'], 'tm': p['tm'], 'pos': p['pos'], 'age': p.get('ax', p.get('age')), 'waa': p.get('waa'), 'waaP': p.get('waaP'), 'war': p['war'], 'xv': p.get('xv'),
                     'pxp': p.get('pxp'), 'xp': p.get('xp') if (p.get('sn') or 0) >= 100 else None,
                     'wav': p.get('wav'), 'pace': p.get('pace'), 'g': p['g'], 'sn': p.get('sn'), 'spts': pts_of(SP, p['n'], p['tm']), 'svar': pts_of(SW, p['n'], p['tm']),
                     'pre': pre, 'preL': f"R{d['round']} #{d['pick']}" if pre else 'UDFA', 'pfv': m['fv'] if m else None,
                     'sub': p.get('col') or '', 'line': p.get('line') or '',
                     'ph': NFL_FACE.format(p['ph']) if p.get('ph') else None, 'lo': logo(f"/img/nfl/{p['tm'].lower()}.png")})
    write('nfl', {
        'asof': b.get('last'), 'title': f'{y} rookies', 'key': 'xv',      # a season board: XV, the most descriptive (metric audit Nov 24)
        'def': 'rookies: first NFL season (nflverse rookie flag). slot = overall pick. pre-draft FV fills from the draft ledger from the 2027 class on.',
        'views': [['xv', 'XV', 'XV: WAR on the stat-line parts that track team margin'],
                  ['waa', 'WAA', 'WAA this season: wins over an average regular at the sub-position, same snaps'],
                  ['war', 'WAR', 'WAR this season: .6 x AV WAR + .4 x XV'],
                  ['pxp', 'pXP/60', 'pXP/60: predictive points over an average regular per 60 snaps (a rookie has no past seasons, so this season alone, shrunk by K snaps to the sub-position mean moved by his draft slot)'], 
                  ['pace', 'WAR/17', 'WAR on a 17-game pace'], ['waaP', 'WAA/17', 'WAA on a 17-game pace'], ['spts', 'SV', SPTS_T], ['svar', 'SVAR', SVAR_T + ' / 36 a win']],
        'cols': [col('xv', 'XV', 'expected value: WAR from the stat line', '2'),
                 col('waa', 'WAA', 'wins over an average regular at the sub-position, same snaps', 's2'), col('war', 'WAR', 'wins above replacement this season', '2'),
                 col('pxp', 'pXP/60', 'predictive points over an average regular at the sub-position per 60 snaps: this season shrunk by K snaps (QB 900, RB 450, WR 900, TE 300, DL 900, LB 1300, OL 2600, DB 3600) to the sub-position mean moved by his draft slot', 's2'),
                 col('xp', 'rXP/60', 'points over an average regular at the sub-position per 60 snaps, this season (100+ snaps)', 's2', 1),
                 col('wav', 'AV WAR', 'WAR from approximate value', '2', 1), col('pace', 'WAR/17', 'WAR on a 17-game pace', '2', 1), col('waaP', 'WAA/17', 'WAA on a 17-game pace', 's2', 1),
                 col('spts', 'SV', SPTS_T + ' (QB, RB, WR, TE, DL, LB, DB)', 's1', 1), col('svar', 'SVAR', SVAR_T + ' / 36 a win', 's2', 1),
                 col('g', 'G', 'games', 'i', 1), col('sn', 'Snaps', 'snaps', 'i', 1), col('line', 'Line', 'season line', 's', 1, 0)],
        'pre': {'l': 'Pick', 't': 'overall pick in the draft (UDFA: undrafted)'}, 'pfv': {'l': 'Pre FV', 't': 'CFB board FV on the eve of the draft (draft ledger, 2027 class on), mean outcome'},
        'pos': ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'EDGE', 'LB', 'CB', 'S', 'K', 'P'], 'posGroup': 1,
        'min': {'k': 'sn', 'l': 'snaps', 'opts': [[0, 'any'], [50, '50+'], [150, '150+'], [300, '300+']], 'def': 50},
        'seasons': [{'s': y, 'l': str(y), 'rows': rows}]})


# ---------------------------------------------------------------- NBA
def nba():
    files = sorted(int(f[:-5]) for f in os.listdir(os.path.join(SD, 'nba-xpm')) if f.endswith('.json'))
    draft = {}
    for yr, lst in json.load(open(os.path.join(HERE, 'nba_draft.json'))).items():
        for pk, bid, n, tm in lst:
            draft[bid] = (int(yr), pk, tm)
    cp = J('static', 'data', 'cbb-past.json')
    cc = cp['cols']
    cbb = {}
    for r in cp['rows']:
        r = dict(zip(cc, r))
        if r.get('draft') and r.get('pick') and r['season'] == r['draft']:
            cbb[(r['draft'], r['pick'])] = r
    proj = json.load(open(os.path.join(SD, 'nba-proj.json')))
    pj = {p['id']: p for p in proj['players']}
    af = J('data', 'nba_rookie_age_research.json')['fit']        # age-adjusted XPM: scripts/nba_rookie_age_research.py
    ak, a0 = af['k'], af['A0']
    pg = J('data', 'nba_rookie_proj_fit.json')['grid']           # rookie projection: scripts/nba_rookie_proj_research.py

    ck = 'cp' if all('cp' in g for g in pg) else 'c'            # XPM given he plays (nba_rookie_proj_play_research.py)

    def r3c(f):                                                 # coefficients at season share f, linear between grid points
        f = min(max(f, pg[0]['f']), 1.0)
        for a, b in zip(pg, pg[1:]):
            if f <= b['f']:
                w = (f - a['f']) / (b['f'] - a['f'])
                return [u + (v - u) * w for u, v in zip(a[ck], b[ck])]
        return pg[-1][ck]
    seen, seasons, ids = set(), [], {}
    for S in files:
        d = json.load(open(os.path.join(SD, 'nba-xpm', f'{S}.json')))
        rows = []
        gms = d.get('games') or 82
        cf = r3c(gms / 82 if S == files[-1] else 1.0)           # only the season in progress is partial
        for p in d['players']:
            first = p['id'] not in seen
            seen.add(p['id'])
            if not first:
                continue
            dr = draft.get(p['id'])
            if S == files[0] and not (dr and dr[0] == S - 1):
                continue            # the first board's veterans
            if not dr and (p.get('age') or 0) > 27:
                continue            # a veteran from before 2009-10 back from abroad, not a rookie
            if dr and dr[0] > S - 1:
                continue
            c = cbb.get((dr[0], dr[1])) if dr else None
            if c and not NM.same(c['name'], p['n']):
                c = None
            row = {'n': p['n'], 'tm': p['tm'], 'pos': p['pos'], 'age': p.get('ax', p.get('age')), 'vorx': p['vorx'], 'xpm': p.get('txpm', p['xpm']),
                   'sx': p.get('sxpm', p['xpm']), 'oxpm': p.get('toxpm', p['oxpm']), 'dxpm': p.get('tdxpm', p['dxpm']), 'mp': p['mp'], 'g': p['g'],
                   'r3': round(cf[0] + cf[1] * XP.role_sxpm(p, gms) + cf[2] * (p['age'] - a0) + cf[3] * math.log1p(p['mp'] * 82 / gms), 1)
                   if p.get('age') and p.get('xpm') is not None else None,
                   'axpm': round(XP.role_sxpm(p, gms) + ak * (p['age'] - a0), 1) if p.get('age') and p.get('xpm') is not None else None,
                   'pre': dr[1] if dr else None, 'preL': (f'{dr[0]} #{dr[1]}' if dr[0] != S - 1 else f'#{dr[1]}') if dr else 'UDFA',
                   'pfv': c['fv'] if c else None, 'sub': c['team'] if c else '', **(hw(c.get('ht')) if c else {}),
                   'ph': ESPN_FACE.format('nba', p['ph']) if p.get('ph') else None, 'lo': logo(f"/img/nba/{p['tm'].lower()}.png")}
            ids.setdefault(S, []).append(p['id'])
            q = pj.get(p['id']) if S == proj['season'] else None
            if S == proj['season']:
                q = q or {}
                row.update({'pxpm': q.get('pxpm'), 'pvorx': q.get('pvorx'), 'sur': q.get('sur'), 'sal': q.get('sal')})
            rows.append(row)
        seasons.append({'s': S, 'l': d['label'], 'rows': rows, 'games': d.get('games'), 'qual': round(1000 * gms / 82), 'mdef': 'q'})
    seasons.reverse()
    write_ids('nba', ids)
    write('nba', {
        'asof': json.load(open(os.path.join(SD, 'nba-xpm', f'{files[-1]}.json'))).get('asof'), 'title': 'rookies', 'key': 'vorx',
        'def': 'rookies: first season on the XPM board. pre-draft FV = the CBB board\'s draft-year FV (college players only); slot = overall pick.',
        'views': [['vorx', 'VORX', 'VORX: wins over replacement, .030 x (XPM + 1.4) x MP / 48'], ['xpm', 'XPM', 'XPM: Cross Plus-Minus, points per 100 over average'],
                  ['sx', 'pXPM', 'pXPM: predictive XPM, next season from this season and the two before, aged'],
                  ['r3', '3Y', 'rookie projection: XPM over the next three seasons when he plays, from XPM, age and minutes per 82 games'],
                  ['axpm', 'aXPM', f"age-adjusted XPM: XPM {'-' if ak < 0 else '+'} {abs(ak):.2f} x (age - {a0})"],
                  ['pxpm', 'Proj', 'XPM (proj): this season blended with the preseason prior by minutes (current season)'],
                  ['sur', 'Surplus', 'contract surplus this season: projected VORX x $ per win - salary, $M (current season)']],
        'cols': [col('vorx', 'VORX', 'wins over replacement', '1'), col('xpm', 'XPM', 'XPM: Cross Plus-Minus, points per 100 over average', 's1'),
                 col('sx', 'pXPM', 'pXPM: predictive XPM, next season from this season and the two before, aged', 's1', 1),
                 col('r3', '3Y', 'rookie projection: XPM over the next three seasons when he plays, from XPM, age and minutes per 82 games', 's1', 1),
                 col('axpm', 'aXPM', f"age-adjusted XPM: XPM {'-' if ak < 0 else '+'} {abs(ak):.2f} x (age - {a0}), fit on 2010-23 rookies' next three seasons", 's1', 1),
                 col('pxpm', 'Proj', 'XPM (proj): season blended with the prior', 's1', 1), col('oxpm', 'Off', 'offensive XPM', 's1', 1),
                 col('dxpm', 'Def', 'defensive XPM', 's1', 1), col('sur', 'Surplus', 'contract surplus this season, $M', 'm', 1),
                 col('sal', 'Salary', 'salary this season, $M', 'm', 1), col('mp', 'MP', 'minutes', 'i', 1)],
        'pre': {'l': 'Pick', 't': 'overall pick (year shown when drafted earlier; UDFA: undrafted)'},
        'pfv': {'l': 'Pre FV', 't': 'draft-year FV on the CBB board, mean outcome'},
        'pos': ['PG', 'SG', 'SF', 'PF', 'C'],
        'min': {'k': 'mp', 'l': 'MP', 'opts': [['q', 'qualified'], [0, 'any'], [100, '100+'], [500, '500+'], [1000, '1,000+']], 'def': 'q'},
        'seasons': seasons})


# ---------------------------------------------------------------- NHL
def nhl():
    files = sorted(int(f[:-5]) for f in os.listdir(os.path.join(SD, 'nhl-war')) if f.endswith('.json'))
    picks = {r['id']: r for r in json.load(gzip.open(os.path.join(HERE, 'data', 'hockey_rows.json.gz'))) if r.get('id')}
    h = J('data', 'hockey.json')
    pipe = {p['id']: p for p in h['pipe'] if p.get('id')}
    past = {(p['year'], p['pick']): p for p in h['past']}
    gp = {}             # id -> [gp by prior season]
    seasons, ids = [], {}
    for S in files:
        d = json.load(open(os.path.join(SD, 'nhl-war', f'{S}.json')))
        rows = []
        if S >= files[0] + 2:
            for p in d['players']:
                g = gp.get(p['id'], [])
                if max(g, default=0) >= 25 or sum(1 for x in g if x >= 6) >= 2 or (p.get('age') or 0) >= 26:
                    continue
                ids.setdefault(S, []).append(p['id'])
                r = picks.get(p['id'])
                fv = None
                if r:
                    q = pipe.get(p['id'])
                    fv = q['fv0'] if q else (past.get((r['year'], r['pick'])) or {}).get('fv')
                    if fv is not None and q is None and not NM.same(past[(r['year'], r['pick'])]['name'], p['n']):
                        fv = None
                rows.append({'n': p['n'], 'tm': p['tm'], 'pos': p['pos'], 'age': p.get('ax', p.get('age')), 'war': p['war'], 'pwar': p.get('pwar'),
                             'hpm': p.get('hpm'), 'toi': p['toi'], 'gp': p['gp'], 'pts': p.get('pts'), 'gsax': p.get('gsax'),
                             'pre': r['pick'] if r else None, 'preL': f"{r['year']} #{r['pick']}" if r else 'undrafted',
                             'pfv': fv, 'sub': '', **(hw(r.get('ht'), r.get('wt')) if r else {}), 'ph': ESPN_FACE.format('nhl', p['ph']) if p.get('ph') else None,
                             'lo': logo(f"/img/nhl/{p['tm'].lower()}.png")})
            seasons.append({'s': S, 'l': d['label'], 'rows': rows, 'games': d.get('games')})
        for p in d['players']:
            gp.setdefault(p['id'], []).append(p['gp'])
    seasons.reverse()
    write_ids('nhl', ids)
    write('nhl', {
        'asof': json.load(open(os.path.join(SD, 'nhl-war', f'{files[-1]}.json'))).get('asof'), 'title': 'rookies', 'key': 'war',
        'def': 'rookies: the Calder rule (under 25 NHL games in any prior season, not 6+ in two, under 26 on Sep 15). draft FV = the hockey prospects board\'s grade at the draft.',
        'views': [['war', 'WAR', 'WAR: wins over replacement this season, what happened'], ['pwar', 'pWAR', 'projected WAR: what this play is worth going forward'],
                  ['hpm', 'HPM', 'HPM: projected goals a 60 over an average player']],
        'cols': [col('war', 'WAR', 'wins over replacement this season', '1'), col('pwar', 'pWAR', 'projected WAR', '1'),
                 col('hpm', 'HPM', 'projected goals a 60 over average', 's2', 1), col('gp', 'GP', 'games', 'i', 1),
                 col('toi', 'TOI', 'minutes on ice', 'i', 1), col('pts', 'Pts', 'points', 'i', 1)],
        'pre': {'l': 'Pick', 't': 'draft class and overall pick'}, 'pfv': {'l': 'Pre FV', 't': 'FV at the draft on the hockey prospects board, mean outcome'},
        'pos': ['C', 'L', 'R', 'D', 'G'],
        'min': {'k': 'toi', 'l': 'TOI', 'opts': [[0, 'any'], [100, '100+'], [400, '400+'], [800, '800+']], 'def': 0},
        'seasons': seasons})


# ---------------------------------------------------------------- soccer
LG = {'eng.1': 'EPL', 'esp.1': 'LaLiga', 'ger.1': 'BuLi', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1'}


SO_SV_T = ("SV (season value): this season's goals over replacement a 90, from this season alone (GAR's weights on its inputs "
           "with a one-season xG plus-minus, plus finishing and keeper saves shrunk by split-half reliability)")
SO_SVAR_T = 'SVAR = SV x 90s played: season total in goals (GAR scale)'


# aGAR/90 (Nov 23 2026, scripts/research/port_nov23/soccer/agar.py): the NBA aXPM form on big-five first seasons. b fit
# on 1,266 rookies (900+ minutes, 2016-17 to 2023-24) against GAR/90 over the next two seasons: .0032 a year (every
# left-out season .0028 to .0036); held out it ranks the next two seasons better than GAR/90 (Spearman .664 vs .654,
# squared error t -2.66, 7 of 8 seasons)
SO_AGAR_B = 0.0032
SO_AGAR_T = 'aGAR/90 = GAR/90 - .0032 x (age - 21): age-adjusted rate, ranks the next two seasons better than GAR/90'


def agar90(g90, age):
    return None if g90 is None or age is None else round(g90 - SO_AGAR_B * (age - 21), 3)


def soccer():
    files = sorted(int(f[:-5]) for f in os.listdir(os.path.join(SD, 'soccer-war')) if f.endswith('.json'))
    link = json.load(gzip.open(os.path.join(HERE, 'data', 'soccer_mv_link.json.gz')))
    tm, dob = link['p'], link['dob']
    sp = J('data', 'soccer_prospects.json')
    board = {p['id']: p for p in sp['board']}
    past = {}
    for p in sp['past']:
        past.setdefault(p['id'], []).append(p)
    cur = max(files)
    seen, seasons, ids = set(), [], {}
    for S in files:
        d = json.load(open(os.path.join(SD, 'soccer-war', f'{S}.json')))
        rows = []
        for p in d['players']:
            first = p['p'] not in seen
            seen.add(p['p'])
            if not first or S < files[0] + 2:
                continue
            ids.setdefault(S, []).append(p['p'])
            t = tm.get(str(p['p']))
            b = dob.get(str(t)) if t else None
            age = None
            if b:
                age = round((dt.date(S - 1, 9, 1) - dt.date.fromisoformat(b)).days / 365.25, 2)
            fv = None
            if t and S == cur and t in board:
                fv = board[t]['fv']
            elif t and t in past:
                fv = max((q for q in past[t] if q['season'] <= S - 1), key=lambda q: q['season'], default={}).get('fv')
            rows.append({'n': p['n'], 'tm': p['team'], 'pos': p['pos'], 'age': age, 'gar': p['gar'], 'par': p.get('par'),
                         'sv': p.get('sv'), 'svar': p.get('svar'),
                         'gar90': p.get('gar90'), 'agar90': agar90(p.get('gar90'), age), 'xmv': p.get('xmv'), 'mv': p.get('mv'), 'min': p['min'], 'g': p.get('g'), 'a': p.get('a'),
                         'pre': None, 'preL': '', 'pfv': fv, 'sub': LG.get(p['lg'], p['lg']),
                         'ph': TM_FACE.format(p['ph']) if p.get('ph') else None, 'lo': soccer_logo(p['team'])})
        if rows:
            seasons.append({'s': S, 'l': d['label'], 'rows': rows, 'games': d.get('games')})
    seasons.reverse()
    write_ids('soccer', ids)
    write('soccer', {
        'asof': json.load(open(os.path.join(SD, 'soccer-war', f'{cur}.json'))).get('asof'), 'title': 'rookies', 'key': 'svar',      # a season board: SVAR, the most descriptive (metric audit Nov 24)
        'def': 'rookies: first big-five league season (Understat, 2015-16 on). prospect FV = the soccer prospects board (U22) where the player was graded.',
        'views': [['svar', 'SVAR', SO_SVAR_T], ['gar', 'GAR', 'goals above replacement this season'], ['gar90', 'GAR/90', 'GAR per 90 minutes'],
                  ['xmv', 'xMV', 'estimated market value, EUR M'], ['sv', 'SV', SO_SV_T]],
        'cols': [col('svar', 'SVAR', SO_SVAR_T, 's1'), col('gar', 'GAR', 'goals above replacement', 's1', 1),
                 col('sv', 'SV', SO_SV_T, 's2', 1), col('xmv', 'xMV', 'estimated market value, EUR M', 'e'),
                 col('mv', 'TM', 'Transfermarkt market value, EUR M', 'e', 1), col('gar90', 'GAR/90', 'GAR per 90', 's2', 1),
                 col('agar90', 'aGAR/90', SO_AGAR_T, 's2', 1),
                 col('par', 'PAR', 'points above replacement', '2', 1), col('min', 'Min', 'minutes', 'i', 1),
                 col('g', 'G', 'goals', 'i', 1), col('a', 'A', 'assists', 'i', 1)],
        'pfv': {'l': 'Pre FV', 't': 'soccer prospects board FV, mean outcome (graded U22 players)'},
        'pos': ['F', 'M', 'D', 'G'],
        'min': {'k': 'min', 'l': 'min', 'opts': [[0, 'any'], [270, '270+'], [900, '900+'], [1800, '1,800+']], 'def': 0},
        'seasons': seasons})


# ---------------------------------------------------------------- CFB true freshmen
# qualifying role by position: share of team snaps, snaps where the share is missing (~11 games at ~65 snaps a side)
FR_SHARE = {'QB': .20, 'RB': .20, 'TE': .20, 'DT': .20, 'DL': .20, 'EDGE': .20, 'LB': .20, 'WR': .25, 'OL': .25, 'CB': .25, 'S': .25}
FR_SNAPS = {p: 130 if v == .20 else 160 for p, v in FR_SHARE.items()}


def qualifies(r):
    p = r.get('pos')
    if p in ('K', 'P'):
        return r.get('war') is not None
    if p not in FR_SHARE:
        return False
    sh, sn = r.get('snapShare'), r.get('snaps')
    if sh is not None and sh >= FR_SHARE[p]:
        return True
    if sn is not None and sn >= FR_SNAPS[p]:
        return True
    return sh is None and not sn and r.get('pfn') is not None


def cfb():
    import cfb_all
    d = cfb_all.read_cfb_all(os.path.join(SD, 'cfb-all.json'))
    c = d['cols']
    fr = [dict(zip(c, r)) for r in d['rows']]
    yr = int(d['asof'][:4]) if d.get('asof') else dt.date.today().year
    # the high school class of this season from 247's composite (scripts/cfb_recruit_247.json), joined by name key; a
    # name also in an earlier class is left out (two players, or a reclass), as are redshirts. Board rows in their
    # first year of eligibility with no composite row (walk-ons, unranked FCS signees) join without a recruiting rank.
    comp = json.load(open(os.path.join(HERE, 'cfb_recruit_247.json')))['composite']
    old = {NM.key(x[0]) for y, v in comp.items() if int(y) < yr for x in v}
    cls = {NM.key(x[0]): x for x in comp.get(str(yr), [])}
    keep = []
    for r in fr:
        k = NM.key(r['name'])
        if r.get('fv') is None or k in old or str(r.get('cls') or '').startswith('RS'):
            continue
        if k in cls and r.get('cls') in ('Fr', None):
            r['_rk'] = cls[k][3]
            keep.append(r)
        elif r.get('elig') == 1:
            keep.append(r)
    # qualifiers only (Noah, Nov 18): a freshman who has not played a real role stays graded on the main board but is left off
    # this one. Snap share of the team's snaps at or above the position bar, or snaps at or above it where the share is
    # missing; neither on file: PFN's own qualifier (a Stat+); K/P (no snap counts): a WAR this season (kicks or punts on file).
    fr = [r for r in keep if qualifies(r)]
    SP, SPI = season_pts('cfb_season_value.json', [('qbs', 'pts'), ('skill', 'pts')])
    SW, SWI = season_pts('cfb_season_value.json', [('qbs', 'svar'), ('skill', 'svar')])

    def cpts(r, L=SP, I=SPI):
        m = re.search(r'/id/(\d+)', r.get('espnl') or '')
        return I.get(m.group(1)) if m and I else pts_of(L, r['name'], r.get('team'))
    rows = [{'n': r['name'], 'tm': r['team'], 'pos': 'DT' if r['pos'] == 'DL' else r['pos'], 'age': r.get('age') or r.get('ageEst'), **hw(r.get('ht'), r.get('wt')), 'fv': r['fv'], 'war': r.get('war'),
             'xv': r.get('xv'), 'pfn': r.get('pfn'), 'sn': r.get('snaps'), 'spts': cpts(r), 'svar': cpts(r, SW, SWI), 'xnil': r['xnil'] / 1e6 if r.get('xnil') else None,
             'pre': r.get('_rk'), 'preL': f"#{r['_rk']}" if r.get('_rk') else '', 'pfv': None,
             'sub': (r.get('pfnLabel') or '') + (f" · {r['div']}" if r.get('div') == 'FCS' else ''), 'div': r.get('div'),
             'ph': cfb_face(r), 'lo': r.get('logo')}
            for r in fr]
    write('cfb', {
        'asof': d.get('asof'), 'title': f'{yr} true freshmen', 'key': 'fv',
        'def': 'true freshmen: the high school class of this season (247 composite), no redshirt, plus first-year walk-ons. Qualifiers only: '
               '20%+ of team snaps (130+ snaps if no share) at QB/RB/TE/DT/EDGE/LB, 25%+ (160+) at WR/OL/CB/S, K/P with kicks or punts on file; '
               'the rest stay graded on the main board. Rec = 247 composite national rank.',
        'views': [['fv', 'FV', 'FV: mean outcome grade'], ['war', 'WAR', 'college WAR this season'], ['pfn', 'Stat+', 'Stat+: position all-in-one, 100 = average'],
                  ['xnil', 'xNIL', 'expected NIL market worth, $M'],
                  ['spts', 'SV', 'SV (season value): this season\'s points over replacement a game from EPA a play (QBs: dropbacks + runs, opponent-adjusted; skill: runs + targets, RB opponent-adjusted), FBS games, as on the QB SV / skill players tabs'], ['svar', 'SVAR', SVAR_T + ' / 53 a win (FBS)']],
        'cols': [col('fv', 'FV', 'FV, mean outcome', 'i'), col('war', 'WAR', 'college WAR this season', '2'),
                 col('pfn', 'Stat+', 'position Stat+, 100 average, 25 per SD', 'i', 1), col('xv', 'XV', 'WAR from the stat line', '2', 1),
                 col('spts', 'SV', 'this season\'s points over replacement a game (QB, RB, WR, TE; FBS games)', 's1', 1),
                 col('svar', 'SVAR', SVAR_T + ' / 53 a win (FBS)', 's2', 1),
                 col('sn', 'Snaps', 'snaps', 'i', 1), col('xnil', 'xNIL', 'expected NIL worth, $M', 'm', 1)],
        'pre': {'l': 'Rec', 't': '247 composite national rank in the high school class'},
        'gfx': ['pfn', 'xnil'],      # GFX columns after the view (Noah, Nov 18): Stat+ and xNIL in place of Rec and its Δ
        'pos': ['QB', 'RB', 'WR', 'TE', 'OL', 'DT', 'EDGE', 'LB', 'CB', 'S', 'K', 'P'], 'posGroup': 1, 'divs': ['FBS', 'FCS'],
        'min': {'k': 'sn', 'l': 'snaps', 'opts': [[0, 'any'], [50, '50+'], [150, '150+'], [300, '300+']], 'def': 0},
        'seasons': [{'s': yr, 'l': str(yr), 'rows': rows}]})


# ---------------------------------------------------------------- CBB true freshmen
def cbb_line(ln, xpm=None):
    """cbb-all 'now' is the live season line (a dict from cbb_live.show_line); the tab shows it as one short string.
    xpm: the board's XPM column (rXPM this season, scripts/cbb_tabs.py board_cols), shown in place of BPM when it is there"""
    if not isinstance(ln, dict):
        return ln or ''
    gp = ln.get('gp') or 0
    if not gp:
        return ''
    f = lambda x: '0' if not x else f"{x:.1f}".rstrip('0').rstrip('.')
    s = f"{gp} g · {f(ln.get('mpg'))} min · {f(ln.get('ppg'))}/{f(ln.get('rpg'))}/{f(ln.get('apg'))}"
    if xpm is not None:
        s += f" · XPM {xpm:+.1f}"
    elif ln.get('bpm') is not None:
        s += f" · BPM {ln['bpm']:+.1f}"
    return s


def cbb():
    d = json.load(open(os.path.join(SD, 'cbb-all.json')))
    c = d['cols']
    fr = [dict(zip(c, r)) for r in d['rows']]
    fr = [r for r in fr if r.get('cls') == 'Fr' and r.get('elig') == 1 and r.get('fv') is not None]
    rows = []
    S = dt.date.today().year + (dt.date.today().month >= 8)
    for r in fr:
        rec = r.get('rec') or {}
        if rec.get('cls') and rec['cls'] < S - 1:
            continue        # a reclassified or returning player listed Fr with an older recruiting class
        if (r.get('now') or {}).get('yr') not in (None, 'Fr'):
            continue        # Barttorvik's class this season says otherwise: a redshirt, a transfer or an upperclassman
        rows.append({'n': r['name'], 'tm': r['team'], 'pos': r['pos'], 'age': r.get('age') or r.get('ageEst'), **hw(r.get('ht'), r.get('wt')), 'fv': r['fv'],
                     'xbpm': r.get('xbpm'), 'nbaP': r['nbaP'] * 100 if r.get('nbaP') is not None else None, 'w': r.get('w'),
                     'pre': rec.get('on3rk'), 'preL': f"#{rec['on3rk']}" if rec.get('on3rk') else '', 'pfv': None,
                     'sub': r.get('conf') or '', 'line': cbb_line(r.get('now'), r.get('xpm')), 'xpm': r.get('xpm'), 'ph': r.get('photo'), 'lo': r.get('logo')})
    write('cbb', {
        'title': 'true freshmen', 'key': 'fv',
        'def': 'true freshmen: Fr, first year of eligibility. pre = On3 national recruiting rank. season lines join once games start.',
        'views': [['fv', 'FV', 'FV: mean outcome grade'], ['xpm', 'XPM', 'XPM this season'], ['xbpm', 'xXPM', 'projected XPM this season'],
                  ['nbaP', 'NBA%', 'chance of an NBA career']],
        'cols': [col('fv', 'FV', 'FV, mean outcome', 'i'), col('xpm', 'XPM', 'XPM this season', 's1'), col('xbpm', 'xXPM', 'projected XPM this season', 's1'),
                 col('nbaP', 'NBA%', 'chance of an NBA career', 'p', 1), col('w', 'Season wt', 'weight on this season\'s line in the grade', '2', 1),
                 col('line', 'Line', 'season line so far', 's', 1, 0)],
        'pre': {'l': 'Rec', 't': 'On3 national recruiting rank'},
        'pos': ['G', 'F', 'C'],
        'seasons': [{'s': S, 'l': f'{S - 1}-{str(S)[2:]}', 'rows': rows}]})


# ---------------------------------------------------------------- hockey prospects: CHL + AHL rookies
def hockey():
    import hockey_prospects as H
    import hockey_provisional as P
    import nhl_data as D
    S = D.current_season()
    h = J('data', 'hockey.json')
    board = NM.Matcher(h['board'], team=None, pos=None)
    pipe = NM.Matcher(h['pipe'], team=None, pos=None)
    rows = []
    for code, lg in (('ohl', 'OHL'), ('whl', 'WHL'), ('lhjmq', 'QMJHL'), ('ahl', 'AHL')):
        raw = P.ht_current(code, P.HTKEY[code], S) or []
        for p in raw:
            if str(p.get('rookie')) != '1' or not P._num(p.get('games_played')):
                continue
            name = P._flip(p.get('name') or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip())
            birth = P._birth(p.get('birthdate'))
            gpn, pts = P._num(p.get('games_played')), P._num(p.get('points'))
            cls = None
            if birth:
                y0 = int(birth[:4]) + 18
                cls = y0 if birth <= f'{y0 - 18}-09-15' else y0 + 1
            b, _ = board.find(name)
            q, _ = (None, None) if b else pipe.find(name)
            if q and birth and abs((H.age_at(birth, S - 1) or 0) - (q.get('age') or 0)) > 1.2:
                q = None
            if lg == 'AHL' and not q and (cls or 0) < S - 4:
                continue        # an older AHL first-year with no draft grade: not a prospect
            age = H.age_at(birth, S - 1) if birth else None
            g = P._num(p.get('goals'))
            rows.append({'n': name, 'tm': P._flip(p.get('team_name')), 'pos': p.get('position') or '', 'age': None if age is None else round(age, 2), 'lg': lg,
                         'nhle': r1(82 * H.nhle_of(lg) * pts / gpn) if p.get('position') != 'G' else None,
                         'ppg': round(pts / gpn, 2), 'gp': int(gpn), 'g': int(g), 'pts': int(pts),
                         'fv': (b or q or {}).get('fv'), 'pre': q['pick'] if q else (b.get('xslot') if b else None),
                         'preL': f"{q['year']} #{q['pick']}" if q else (f"x{b['xslot']}" if b and b.get('xslot') else (f'{cls} class' if cls else '')),
                         **hw((b or {}).get('ht'), (b or {}).get('wt')), 'pfv': q['fv0'] if q else None, 'sub': lg + (f' · {cls} class' if cls and not q else ''),
                         'ph': f"https://assets.leaguestat.com/{code}/240x240/{p['player_id']}.jpg" if p.get('player_id') else None,
                         'lo': hockey_logo(p.get('logo'))})
    if not rows:
        raise SystemExit('hockey: no HockeyTech rows (feed down?), keeping the last file')
    write('hockey', {
        'title': 'first-year: CHL and AHL rookies', 'key': 'nhle',
        'def': 'first-year: rookies in the OHL, WHL, QMJHL or AHL (HockeyTech\'s rookie flag). FV from the prospect board (coming class) or the pipeline (drafted). NHLe = points a game x the fitted league factor x 82.',
        'views': [['nhle', 'NHLe', 'NHL-equivalent points a season'], ['fv', 'FV', 'FV where graded, mean outcome'], ['pts', 'Pts', 'points']],
        'cols': [col('nhle', 'NHLe', 'NHL-equivalent points per 82', '1'), col('fv', 'FV', 'FV, mean outcome (board or pipeline)', 'i'),
                 col('ppg', 'P/GP', 'points a game', '2', 1), col('gp', 'GP', 'games', 'i', 1), col('g', 'G', 'goals', 'i', 1),
                 col('pts', 'Pts', 'points', 'i', 1)],
        'pre': {'l': 'Draft', 't': 'drafted: class and pick; coming class: x = expected slot; else draft class'},
        'pfv': {'l': 'Pre FV', 't': 'FV at the draft (drafted prospects)'},
        'pos': ['C', 'LW', 'RW', 'D', 'G'], 'lgs': ['OHL', 'WHL', 'QMJHL', 'AHL'],
        'min': {'k': 'gp', 'l': 'GP', 'opts': [[0, 'any'], [5, '5+'], [10, '10+'], [20, '20+']], 'def': 5},
        'seasons': [{'s': S, 'l': f'{S - 1}-{str(S)[2:]}', 'rows': rows}]})


# ---------------------------------------------------------------- soccer prospects: first senior season
def soccerp():
    d = J('data', 'soccer_prospects.json')
    rows = [{'n': p['name'], 'tm': p['club'], 'pos': p['grp'], 'age': p.get('age'), 'ageEst': p.get('ageEst'), 'fv': p['fv'], 'gar': p.get('gar'),
             'min': p.get('min'), 'mv': p['mv'] / 1e6 if p.get('mv') else None, 'p50': p['p50'] * 100 if p.get('p50') is not None else None,
             'pre': None, 'preL': '', 'pfv': None, 'sub': p.get('league') or p.get('lg') or '', 'prov': p.get('prov'), **hw(p.get('ht'), cm=True),
             'ph': TM_FACE.format(p['ph']) if p.get('ph') else None, 'lo': soccer_logo(p['club'])}
            for p in d['board'] if not p.get('min1') and (p.get('min') or 0) > 0]
    write('soccerp', {
        'asof': d.get('asof'), 'title': f"first senior season {d.get('season', '')}", 'key': 'fv',
        'def': 'first-year: on the prospect board with no senior league minutes last season (this is the debut season).',
        'views': [['fv', 'FV', 'FV: mean outcome grade'], ['gar', 'tGAR', 'team-share goals above replacement this season (not the senior GAR)'], ['mv', 'MV', 'Transfermarkt value, EUR M']],
        'cols': [col('fv', 'FV', 'FV, mean outcome', 'i'), col('gar', 'tGAR', 'team-share goals above replacement this season (not the senior GAR)', '2'),
                 col('p50', '50+%', 'chance of a 50+ FV outcome', 'p', 1), col('mv', 'MV', 'Transfermarkt market value, EUR M', 'e', 1),
                 col('min', 'Min', 'league minutes', 'i', 1)],
        'pos': ['F', 'M', 'D', 'G'],
        'min': {'k': 'min', 'l': 'min', 'opts': [[0, 'any'], [270, '270+'], [900, '900+']], 'def': 0},
        'seasons': [{'s': 0, 'l': d.get('season', ''), 'rows': rows}]})


ALL = {'nfl': nfl, 'nba': nba, 'nhl': nhl, 'soccer': soccer, 'cfb': cfb, 'cbb': cbb, 'hockey': hockey, 'soccerp': soccerp}

if __name__ == '__main__':
    want = sys.argv[1:] or list(ALL)
    bad = 0
    for s in want:
        try:
            ALL[s]()
        except Exception as e:      # one section's feed failing leaves its last file and the others still build
            print(f'{s}: not updated:', e)
            bad += 1
    sys.exit(1 if bad == len(want) else 0)
