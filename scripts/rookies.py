#!/usr/bin/env python3
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
             (static/data/cbb-past.json); current season adds XPM (proj) and contract surplus (static/data/nba-proj.json)
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
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM

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


def write(sport, out):
    os.makedirs(OUT, exist_ok=True)
    out = {'sport': sport, 'asof': out.pop('asof', None) or now(), **out}
    fn = os.path.join(OUT, f'{sport}.json')
    json.dump(out, open(fn, 'w', encoding='utf-8'), separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    print('wrote', fn, ' '.join(f"{s['l']}:{len(s['rows'])}" for s in out['seasons']))


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
    rows = []
    for p in b['players']:
        if not p.get('rook'):
            continue
        d = picks.get(p['id'])
        m, _ = M.find(p['n'], team=p.get('col') or None)
        pre = int(d['pick']) if d and d['pick'] else None
        rows.append({'n': p['n'], 'tm': p['tm'], 'pos': p['pos'], 'age': p.get('age'), 'war': p['war'], 'xv': p.get('xv'),
                     'wav': p.get('wav'), 'pace': p.get('pace'), 'g': p['g'], 'sn': p.get('sn'),
                     'pre': pre, 'preL': f"R{d['round']} #{d['pick']}" if pre else 'UDFA', 'pfv': m['fv'] if m else None,
                     'sub': p.get('col') or '', 'line': p.get('line') or ''})
    write('nfl', {
        'asof': b.get('last'), 'title': f'{y} rookies', 'key': 'war',
        'def': 'rookies: first NFL season (nflverse rookie flag). slot = overall pick. pre-draft FV fills from the draft ledger from the 2027 class on.',
        'views': [['war', 'WAR', 'WAR this season: .6 x AV WAR + .4 x XV'], ['xv', 'XV', 'XV: WAR on the stat-line parts that track team margin'],
                  ['pace', 'pace', 'WAR on a 17-game pace']],
        'cols': [col('war', 'WAR', 'wins above replacement this season', '2'), col('xv', 'XV', 'expected value: WAR from the stat line', '2'),
                 col('wav', 'AV WAR', 'WAR from approximate value', '2', 1), col('pace', 'Pace', 'WAR on a 17-game pace', '2', 1),
                 col('g', 'G', 'games', 'i', 1), col('sn', 'Snaps', 'snaps', 'i', 1), col('line', 'Line', 'season line', 's', 1, 0)],
        'pre': {'l': 'Pick', 't': 'overall pick in the draft (UDFA: undrafted)'}, 'pfv': {'l': 'Pre FV', 't': 'CFB board FV on the eve of the draft (draft ledger, 2027 class on), mean outcome'},
        'pos': ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'EDGE', 'LB', 'CB', 'S'], 'posGroup': 1,
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
    seen, seasons = set(), []
    for S in files:
        d = json.load(open(os.path.join(SD, 'nba-xpm', f'{S}.json')))
        rows = []
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
            row = {'n': p['n'], 'tm': p['tm'], 'pos': p['pos'], 'age': p.get('age'), 'vorx': p['vorx'], 'xpm': p['xpm'],
                   'oxpm': p['oxpm'], 'dxpm': p['dxpm'], 'mp': p['mp'], 'g': p['g'],
                   'pre': dr[1] if dr else None, 'preL': (f'{dr[0]} #{dr[1]}' if dr[0] != S - 1 else f'#{dr[1]}') if dr else 'UDFA',
                   'pfv': c['fv'] if c else None, 'sub': c['team'] if c else ''}
            q = pj.get(p['id']) if S == proj['season'] else None
            if S == proj['season']:
                q = q or {}
                row.update({'pxpm': q.get('pxpm'), 'pvorx': q.get('pvorx'), 'sur': q.get('sur'), 'sal': q.get('sal')})
            rows.append(row)
        seasons.append({'s': S, 'l': d['label'], 'rows': rows, 'games': d.get('games')})
    seasons.reverse()
    write('nba', {
        'asof': json.load(open(os.path.join(SD, 'nba-xpm', f'{files[-1]}.json'))).get('asof'), 'title': 'rookies', 'key': 'vorx',
        'def': 'rookies: first season on the XPM board. pre-draft FV = the CBB board\'s draft-year FV (college players only); slot = overall pick.',
        'views': [['vorx', 'VORX', 'VORX: wins over replacement, .030 x (XPM + 1.4) x MP / 48'], ['xpm', 'XPM', 'XPM: points per 100 over average'],
                  ['pxpm', 'XPM (proj)', 'XPM (proj): this season blended with the preseason prior by minutes (current season)'],
                  ['sur', 'surplus', 'contract surplus this season: projected VORX x $ per win - salary, $M (current season)']],
        'cols': [col('vorx', 'VORX', 'wins over replacement', '1'), col('xpm', 'XPM', 'XPM, points per 100 over average', 's1'),
                 col('pxpm', 'Proj', 'XPM (proj): season blended with the prior', 's1', 1), col('oxpm', 'Off', 'offensive XPM', 's1', 1),
                 col('dxpm', 'Def', 'defensive XPM', 's1', 1), col('sur', 'Surplus', 'contract surplus this season, $M', 'm', 1),
                 col('sal', 'Salary', 'salary this season, $M', 'm', 1), col('mp', 'MP', 'minutes', 'i', 1)],
        'pre': {'l': 'Pick', 't': 'overall pick (year shown when drafted earlier; UDFA: undrafted)'},
        'pfv': {'l': 'Pre FV', 't': 'draft-year FV on the CBB board, mean outcome'},
        'pos': ['PG', 'SG', 'SF', 'PF', 'C'],
        'min': {'k': 'mp', 'l': 'MP', 'opts': [[0, 'any'], [100, '100+'], [500, '500+'], [1000, '1,000+']], 'def': 0},
        'seasons': seasons})


# ---------------------------------------------------------------- NHL
def nhl():
    files = sorted(int(f[:-5]) for f in os.listdir(os.path.join(SD, 'nhl-war')) if f.endswith('.json'))
    picks = {r['id']: r for r in json.load(gzip.open(os.path.join(HERE, 'data', 'hockey_rows.json.gz'))) if r.get('id')}
    h = J('data', 'hockey.json')
    pipe = {p['id']: p for p in h['pipe'] if p.get('id')}
    past = {(p['year'], p['pick']): p for p in h['past']}
    gp = {}             # id -> [gp by prior season]
    seasons = []
    for S in files:
        d = json.load(open(os.path.join(SD, 'nhl-war', f'{S}.json')))
        rows = []
        if S >= files[0] + 2:
            for p in d['players']:
                g = gp.get(p['id'], [])
                if max(g, default=0) >= 25 or sum(1 for x in g if x >= 6) >= 2 or (p.get('age') or 0) >= 26:
                    continue
                r = picks.get(p['id'])
                fv = None
                if r:
                    q = pipe.get(p['id'])
                    fv = q['fv0'] if q else (past.get((r['year'], r['pick'])) or {}).get('fv')
                    if fv is not None and q is None and not NM.same(past[(r['year'], r['pick'])]['name'], p['n']):
                        fv = None
                rows.append({'n': p['n'], 'tm': p['tm'], 'pos': p['pos'], 'age': p.get('age'), 'war': p['war'], 'pwar': p.get('pwar'),
                             'hpm': p.get('hpm'), 'toi': p['toi'], 'gp': p['gp'], 'pts': p.get('pts'), 'gsax': p.get('gsax'),
                             'pre': r['pick'] if r else None, 'preL': f"{r['year']} #{r['pick']}" if r else 'undrafted',
                             'pfv': fv, 'sub': ''})
            seasons.append({'s': S, 'l': d['label'], 'rows': rows, 'games': d.get('games')})
        for p in d['players']:
            gp.setdefault(p['id'], []).append(p['gp'])
    seasons.reverse()
    write('nhl', {
        'asof': json.load(open(os.path.join(SD, 'nhl-war', f'{files[-1]}.json'))).get('asof'), 'title': 'rookies', 'key': 'war',
        'def': 'rookies: the Calder rule (under 25 NHL games in any prior season, not 6+ in two, under 26 on Sep 15). draft FV = the hockey prospects board\'s grade at the draft.',
        'views': [['war', 'WAR', 'WAR: wins over replacement this season, what happened'], ['pwar', 'pWAR', 'projected WAR: what this play is worth going forward'],
                  ['hpm', 'HPM', 'HPM: projected goals a 60 over an average player']],
        'cols': [col('war', 'WAR', 'wins over replacement this season', '1'), col('pwar', 'pWAR', 'projected WAR', '1'),
                 col('hpm', 'HPM', 'projected goals a 60 over average', 's2', 1), col('gp', 'GP', 'games', 'i', 1),
                 col('toi', 'TOI', 'minutes on ice', 'i', 1), col('pts', 'Pts', 'points', 'i', 1)],
        'pre': {'l': 'Pick', 't': 'draft class and overall pick'}, 'pfv': {'l': 'Draft FV', 't': 'FV at the draft on the hockey prospects board, mean outcome'},
        'pos': ['C', 'L', 'R', 'D', 'G'],
        'min': {'k': 'toi', 'l': 'TOI', 'opts': [[0, 'any'], [100, '100+'], [400, '400+'], [800, '800+']], 'def': 0},
        'seasons': seasons})


# ---------------------------------------------------------------- soccer
LG = {'eng.1': 'EPL', 'esp.1': 'LaLiga', 'ger.1': 'BuLi', 'ita.1': 'Serie A', 'fra.1': 'Ligue 1'}


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
    seen, seasons = set(), []
    for S in files:
        d = json.load(open(os.path.join(SD, 'soccer-war', f'{S}.json')))
        rows = []
        for p in d['players']:
            first = p['p'] not in seen
            seen.add(p['p'])
            if not first or S < files[0] + 2:
                continue
            t = tm.get(str(p['p']))
            b = dob.get(str(t)) if t else None
            age = None
            if b:
                age = int((dt.date(S - 1, 9, 1) - dt.date.fromisoformat(b)).days / 365.25)
            fv = None
            if t and S == cur and t in board:
                fv = board[t]['fv']
            elif t and t in past:
                fv = max((q for q in past[t] if q['season'] <= S - 1), key=lambda q: q['season'], default={}).get('fv')
            rows.append({'n': p['n'], 'tm': p['team'], 'pos': p['pos'], 'age': age, 'gar': p['gar'], 'par': p.get('par'),
                         'gar90': p.get('gar90'), 'xmv': p.get('xmv'), 'mv': p.get('mv'), 'min': p['min'], 'g': p.get('g'), 'a': p.get('a'),
                         'pre': None, 'preL': '', 'pfv': fv, 'sub': LG.get(p['lg'], p['lg'])})
        if rows:
            seasons.append({'s': S, 'l': d['label'], 'rows': rows, 'games': d.get('games')})
    seasons.reverse()
    write('soccer', {
        'asof': json.load(open(os.path.join(SD, 'soccer-war', f'{cur}.json'))).get('asof'), 'title': 'rookies', 'key': 'gar',
        'def': 'rookies: first big-five league season (Understat, 2015-16 on). prospect FV = the soccer prospects board (U22) where the player was graded.',
        'views': [['gar', 'GAR', 'goals above replacement this season'], ['gar90', 'GAR/90', 'GAR per 90 minutes'],
                  ['xmv', 'xMV', 'estimated market value, EUR M']],
        'cols': [col('gar', 'GAR', 'goals above replacement', '2'), col('xmv', 'xMV', 'estimated market value, EUR M', 'e'),
                 col('mv', 'MV', 'Transfermarkt market value, EUR M', 'e', 1), col('gar90', 'GAR/90', 'GAR per 90', '3', 1),
                 col('par', 'PAR', 'points above replacement', '2', 1), col('min', 'Min', 'minutes', 'i', 1),
                 col('g', 'G', 'goals', 'i', 1), col('a', 'A', 'assists', 'i', 1)],
        'pfv': {'l': 'Prosp FV', 't': 'soccer prospects board FV, mean outcome (graded U22 players)'},
        'pos': ['F', 'M', 'D', 'G'],
        'min': {'k': 'min', 'l': 'min', 'opts': [[0, 'any'], [270, '270+'], [900, '900+'], [1800, '1,800+']], 'def': 0},
        'seasons': seasons})


# ---------------------------------------------------------------- CFB true freshmen
def cfb():
    d = json.load(open(os.path.join(SD, 'cfb-all.json')))
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
    fr = keep
    rows = [{'n': r['name'], 'tm': r['team'], 'pos': r['pos'], 'age': r.get('age') or r.get('ageEst'), 'fv': r['fv'], 'war': r.get('war'),
             'xv': r.get('xv'), 'pfn': r.get('pfn'), 'sn': r.get('snaps'), 'xnil': r['xnil'] / 1e6 if r.get('xnil') else None,
             'pre': r.get('_rk'), 'preL': f"#{r['_rk']}" if r.get('_rk') else '', 'pfv': None,
             'sub': (r.get('pfnLabel') or '') + (f" · {r['div']}" if r.get('div') == 'FCS' else ''), 'div': r.get('div')}
            for r in fr]
    write('cfb', {
        'asof': d.get('asof'), 'title': f'{yr} true freshmen', 'key': 'fv',
        'def': 'true freshmen: the high school class of this season (247 composite), no redshirt, plus first-year walk-ons. Rec = 247 composite national rank.',
        'views': [['fv', 'FV', 'FV: mean outcome grade'], ['war', 'WAR', 'college WAR this season'], ['pfn', 'Stat+', 'Stat+: position all-in-one, 100 = average'],
                  ['xnil', 'xNIL', 'expected NIL market worth, $M']],
        'cols': [col('fv', 'FV', 'FV, mean outcome', 'i'), col('war', 'WAR', 'college WAR this season', '2'),
                 col('pfn', 'Stat+', 'position Stat+, 100 average, 25 per SD', 'i', 1), col('xv', 'XV', 'WAR from the stat line', '2', 1),
                 col('sn', 'Snaps', 'snaps', 'i', 1), col('xnil', 'xNIL', 'expected NIL worth, $M', 'm', 1)],
        'pre': {'l': 'Rec', 't': '247 composite national rank in the high school class'},
        'pos': ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'EDGE', 'LB', 'CB', 'S'], 'posGroup': 1, 'divs': ['FBS', 'FCS'],
        'min': {'k': 'sn', 'l': 'snaps', 'opts': [[0, 'any'], [50, '50+'], [150, '150+'], [300, '300+']], 'def': 0},
        'seasons': [{'s': yr, 'l': str(yr), 'rows': rows}]})


# ---------------------------------------------------------------- CBB true freshmen
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
        rows.append({'n': r['name'], 'tm': r['team'], 'pos': r['pos'], 'age': r.get('age') or r.get('ageEst'), 'fv': r['fv'],
                     'xbpm': r.get('xbpm'), 'nbaP': r['nbaP'] * 100 if r.get('nbaP') is not None else None, 'w': r.get('w'),
                     'pre': rec.get('on3rk'), 'preL': f"#{rec['on3rk']}" if rec.get('on3rk') else '', 'pfv': None,
                     'sub': r.get('conf') or '', 'line': r.get('now') or ''})
    write('cbb', {
        'title': 'true freshmen', 'key': 'fv',
        'def': 'true freshmen: Fr, first year of eligibility. pre = On3 national recruiting rank. season lines join once games start.',
        'views': [['fv', 'FV', 'FV: mean outcome grade'], ['xbpm', 'xBPM', 'projected NBA BPM'], ['nbaP', 'NBA%', 'chance of an NBA career']],
        'cols': [col('fv', 'FV', 'FV, mean outcome', 'i'), col('xbpm', 'xBPM', 'projected NBA BPM', 's1'),
                 col('nbaP', 'NBA%', 'chance of an NBA career', 'p', 1), col('w', 'Season wt', 'weight on this season\'s line in the grade', '2', 1),
                 col('line', 'Line', 'season line so far', 's', 1, 0)],
        'pre': {'l': 'Rec', 't': 'On3 national recruiting rank'},
        'pos': ['G', 'W', 'F', 'B'],
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
            rows.append({'n': name, 'tm': P._flip(p.get('team_name')), 'pos': p.get('position') or '', 'age': r1(age), 'lg': lg,
                         'nhle': r1(82 * H.nhle_of(lg) * pts / gpn) if p.get('position') != 'G' else None,
                         'ppg': round(pts / gpn, 2), 'gp': int(gpn), 'g': int(g), 'pts': int(pts),
                         'fv': (b or q or {}).get('fv'), 'pre': q['pick'] if q else (b.get('xslot') if b else None),
                         'preL': f"{q['year']} #{q['pick']}" if q else (f"x{b['xslot']}" if b and b.get('xslot') else (f'{cls} class' if cls else '')),
                         'pfv': q['fv0'] if q else None, 'sub': lg + (f' · {cls} class' if cls and not q else '')})
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
        'pfv': {'l': 'Draft FV', 't': 'FV at the draft (drafted prospects)'},
        'pos': ['C', 'LW', 'RW', 'D', 'G'], 'lgs': ['OHL', 'WHL', 'QMJHL', 'AHL'],
        'min': {'k': 'gp', 'l': 'GP', 'opts': [[0, 'any'], [5, '5+'], [10, '10+'], [20, '20+']], 'def': 5},
        'seasons': [{'s': S, 'l': f'{S - 1}-{str(S)[2:]}', 'rows': rows}]})


# ---------------------------------------------------------------- soccer prospects: first senior season
def soccerp():
    d = J('data', 'soccer_prospects.json')
    rows = [{'n': p['name'], 'tm': p['club'], 'pos': p['grp'], 'age': p.get('age'), 'fv': p['fv'], 'gar': p.get('gar'),
             'min': p.get('min'), 'mv': p['mv'] / 1e6 if p.get('mv') else None, 'p50': p['p50'] * 100 if p.get('p50') is not None else None,
             'pre': None, 'preL': '', 'pfv': None, 'sub': p.get('league') or p.get('lg') or '', 'prov': p.get('prov')}
            for p in d['board'] if not p.get('min1') and (p.get('min') or 0) > 0]
    write('soccerp', {
        'asof': d.get('asof'), 'title': f"first senior season {d.get('season', '')}", 'key': 'fv',
        'def': 'first-year: on the prospect board with no senior league minutes last season (this is the debut season).',
        'views': [['fv', 'FV', 'FV: mean outcome grade'], ['gar', 'GAR', 'goals above replacement this season'], ['mv', 'MV', 'Transfermarkt value, EUR M']],
        'cols': [col('fv', 'FV', 'FV, mean outcome', 'i'), col('gar', 'GAR', 'goals above replacement this season', '2'),
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
