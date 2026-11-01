#!/usr/bin/env python3
"""This season's team badges (scripts/team_badges.py has the method and the tests). For each sport: last season's and
this season's games as events keyed by the team file's team key, every shown badge's shrunk season-to-date value
(n0 from the research), z within this season over the teams with MIN_GAMES games, tiered by the pooled cuts in
data/team_badges.json. Writes data/team_badges/<sport>.json and puts each team's list into
static/data/teams/<sport>.json as 'bdg': [[name, tier, percentile, line]] best first (team_detail.save carries it over).

    python3 scripts/team_badges.py build nfl|nba|cbb|cfb      (NHL and soccer: called from nhl_games / soccer_games)
"""
import collections
import concurrent.futures as cf
import datetime
import gzip
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import style_research as SR  # noqa: E402
import team_badges as T  # noqa: E402

OUTD = os.path.join(ROOT, 'data', 'team_badges')
TEAMS = os.path.join(ROOT, 'static', 'data', 'teams', '{}.json')
TC = os.path.join(HERE, '.cache', 'teambadges')
PCT = {'p': 99, 'g': 97, 's': 90, 'b': 75}


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def fmt(sport, k, v):
    if sport == 'nhl':
        return f'{60 * v:.1f}' if k in ('pp', 'pk') else f'{v:+.2f}' if k in ('fin', 'gk') else f'{v:.2f}'
    if k in ('tov', 'tovf', 'secure', 'take'):
        return f'{100 * v:.1f} per 100'
    if k in ('efg', '3p', 'orb', 'drb', 'ftr', 'ft', 'rim', 'ast', '3pd', '2pd', '3d', '3d_al', 'kick', 'fin', 'keep', 'rush', 'prot', 'havoc', 'expl'):
        return f'{100 * v:.1f}%'
    if k in ('pass_o', 'run_o', 'pass_d', 'run_d', 'bench') and sport != 'cfb':
        return f'{v:+.2f}'
    return f'{v:.1f}' if sport in ('cfb', 'soccer') or k == 'ret' else f'{v:.2f}'


def badges_from(sport, ev, S):
    """ev: events of seasons S-1 and S (team keys = the team file's). -> {team: [[name, tier, pct, line], ...]}"""
    cfg = json.load(open(T.CUTS))['sports'].get(sport)
    if not cfg:
        return {}
    ev = sorted(ev, key=lambda e: e['t'])
    if sport in ('nba', 'nfl', 'cbb'):
        save_prior(sport, ev, S - 1)
    n0, cuts, names = cfg['n0'], cfg['cuts'], cfg['names']
    games = collections.Counter()
    for e in ev:
        if e['S'] == S:
            games[e['h']] += 1
            games[e['a']] += 1
    teams = [t for t, n in games.items() if n >= T.MIN_GAMES[sport]]
    if len(teams) < 8:
        return {}
    prior = None if any(e['S'] == S - 1 for e in ev) else load_prior(sport, S - 1)
    val = collections.defaultdict(dict)
    for v in sorted(set(n0[k] for k in cuts)):
        R = SR.Roll(v)
        if prior:          # last season's totals from the committed file (CI has no history cache)
            for t, d in prior['teams'].items():
                for st, x in d.items():
                    R.cur[(S - 1, t)][st] = list(x)
            for st, x in prior['lg'].items():
                R.lg[S - 1][st] = list(x)
        for e in ev:
            for s, k in (('h', 'sh'), ('a', 'sa')):
                for st, x in (e.get(k) or {}).items():
                    if st in cuts and n0[st] == v:
                        R.add(e['S'], e[s], st, *x)
        for t in teams:
            for st in cuts:
                if n0[st] == v:
                    val[t][st] = R.get(S, t, st)
    out = collections.defaultdict(list)
    for st, cut in cuts.items():
        xs = [val[t][st] for t in teams if val[t].get(st) is not None]
        if len(xs) < 8:
            continue
        m = sum(xs) / len(xs)
        sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5 or 1.0
        nm, ori, what = names[st]
        for t in teams:
            v = val[t].get(st)
            if v is None:
                continue
            z = ori * (v - m) / sd
            tier = next((tr for tr in ('p', 'g', 's', 'b') if z >= cut[tr]), None)
            if tier:
                pct = sum(1 for q in cut['q'] if z >= q) if cut.get('q') else int(round(100 * phi(z)))
                out[t].append([nm, tier, max(pct, PCT[tier]), f'{what} {fmt(sport, st, v)}', z])
    return {t: [b[:4] for b in sorted(bs, key=lambda b: -b[4])] for t, bs in out.items()}


def prior_path(sport):
    return os.path.join(OUTD, f'prior_{sport}.json')


def save_prior(sport, ev, S):
    """season S's totals by team (num, den, games) and the league's, when the events hold that season"""
    tm, lg = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, 0])), collections.defaultdict(lambda: [0.0, 0.0, 0])
    for e in ev:
        if e['S'] != S:
            continue
        for s, k in (('h', 'sh'), ('a', 'sa')):
            for st, (n, d) in (e.get(k) or {}).items():
                if n is None or not d or d <= 0:
                    continue
                for x in (tm[e[s]][st], lg[st]):
                    x[0] += n; x[1] += d; x[2] += 1
    if not lg:
        return
    os.makedirs(OUTD, exist_ok=True)
    r6 = lambda x: [round(x[0], 4), round(x[1], 4), x[2]]
    json.dump({'season': S, 'teams': {t: {st: r6(x) for st, x in d.items()} for t, d in sorted(tm.items())},
               'lg': {st: r6(x) for st, x in lg.items()}}, open(prior_path(sport), 'w'), separators=(',', ':'))


def load_prior(sport, S):
    try:
        d = json.load(open(prior_path(sport)))
        return d if d.get('season') == S else None
    except (OSError, ValueError):
        return None


def write(sport, bdg):
    os.makedirs(OUTD, exist_ok=True)
    res = {'sport': sport, 'teams': {t: bdg[t] for t in sorted(bdg)}}
    p = os.path.join(OUTD, f'{sport}.json')
    try:
        old = json.load(open(p))
    except (OSError, ValueError):
        old = None
    if old != res:
        json.dump(res, open(p, 'w'), separators=(',', ':'), ensure_ascii=False)
    tp = TEAMS.format(sport)
    try:
        F = json.load(open(tp))
    except (OSError, ValueError):
        return print(f'team badges {sport}: {len(bdg)} teams (no team file)')
    ch = False
    for k, v in F.get('teams', {}).items():
        new = bdg.get(k)
        if v.get('bdg') != new:
            ch = True
            if new:
                v['bdg'] = new
            else:
                v.pop('bdg', None)
    if ch:
        json.dump(F, open(tp, 'w'), separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    print(f'team badges {sport}: {len(bdg)} teams with a badge, {sum(len(v) for v in bdg.values())} badges')


def saved(sport):
    """the last build's badges (team_detail.save carries them into a rewritten team file)"""
    try:
        return json.load(open(os.path.join(OUTD, f'{sport}.json'))).get('teams', {})
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- per sport
def nfl():
    import team_badges_pull as P
    P.nfl(True)
    y = datetime.date.today().year - (1 if datetime.date.today().month < 3 else 0)
    ev = T.ev_nfl(years=[y - 1, y])
    return badges_from('nfl', ev, y + 1)


def get_json(url):
    import team_badges_pull as P
    b = P.get(url)
    try:
        return json.loads(b) if b else None
    except ValueError:
        return None


def nba_box(gid):
    """one game's box in nba_box_hist form: {team: [[pid, min, pts, fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, ast, stl,
    blk, tov, pf, pm]]} (cached once final)"""
    p = os.path.join(TC, 'nba', gid + '.json')
    if os.path.exists(p):
        return json.load(open(p))
    j = get_json(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}')
    if not j or 'boxscore' not in j:
        return None
    import nba_espn as NE
    out = {}
    for t in j['boxscore'].get('players', []):
        ab = NE.team(t['team']['abbreviation'])
        st = (t.get('statistics') or [{}])[0]
        L = st.get('names') or st.get('labels') or []
        rows = []
        for a in st.get('athletes', []):
            d = dict(zip(L, a.get('stats') or []))
            if not d.get('MIN') or d.get('MIN') in ('--', '0'):
                continue
            ma = lambda k: [float(x) for x in str(d.get(k, '0-0')).split('-')[:2]] if '-' in str(d.get(k, '')) else [0.0, 0.0]
            f = lambda k: float(str(d.get(k, '0')).replace('+', '') or 0) if str(d.get(k, '0')) not in ('--', '') else 0.0
            fg, f3, ft = ma('FG'), ma('3PT'), ma('FT')
            rows.append([a['athlete']['id'], f('MIN'), f('PTS'), fg[0], fg[1], f3[0], f3[1], ft[0], ft[1], f('OREB'), f('DREB'),
                         f('AST'), f('STL'), f('BLK'), f('TO'), f('PF'), f('+/-')])
        out[ab] = rows
    if len(out) == 2:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(out, open(p, 'w'))
    return out


def nba():
    import nba_espn as NE
    hist = {str(g['id']): g for g in json.load(gzip.open(os.path.join(HERE, 'nba_games_hist.json.gz')))['games']}
    S = max(g['S'] for g in hist.values()) + 1
    box = json.load(gzip.open(os.path.join(SR.C, 'nba_box_hist.json.gz'))) if os.path.exists(os.path.join(SR.C, 'nba_box_hist.json.gz')) else {}
    box = {k: v for k, v in box.items() if k in hist and hist[k]['S'] == S - 1}
    d, today = datetime.date(S - 1, 10, 1), datetime.date.today()
    todo = []
    while d < today:
        for g in NE.day(d) or []:
            if g.get('final') and g.get('type', 2) in (2, 3, 5) and g.get('season') == S and str(g['id']) not in hist:
                hist[str(g['id'])] = {'id': str(g['id']), 'tip': g.get('tip') or d.isoformat(), 'S': S, 'h': g['h'], 'a': g['a']}
                todo.append(str(g['id']))
        d += datetime.timedelta(days=1)
    with cf.ThreadPoolExecutor(8) as ex:
        for gid, b in zip(todo, ex.map(nba_box, todo)):
            if b:
                box[gid] = b
    return badges_from('nba', T.ev_nba(box, hist), S)


def cbb():
    import team_badges_pull as P
    S = P.season_now()
    P.cbb(True)
    ev, _ = T.ev_cbb(years=[S - 1, S])
    # Barttorvik names -> ESPN ids, from the games logs (hb/ab beside home/away)
    mp = {}
    for p in (os.path.join(HERE, 'data', 'cbb_games_hist.json.gz'), os.path.join(HERE, 'data', f'cbb_games_{S}.json.gz')):
        try:
            for g in json.load(gzip.open(p)):
                for i, n in ((g.get('home'), g.get('hb')), (g.get('away'), g.get('ab'))):
                    if i and n and g.get('season', S) >= S - 2:
                        mp[n] = str(i)
        except (OSError, ValueError):
            pass
    out = []
    for e in ev:
        h, a = mp.get(e['h']), mp.get(e['a'])
        if h and a:
            out.append(dict(e, h=h, a=a))
    return badges_from('cbb', out, S)


def cfb():
    import team_badges_pull as P
    S = P.season_now() - 1
    p = os.path.join(TC, 'cfb_ids.json')
    os.makedirs(TC, exist_ok=True)
    box = json.load(open(p)) if os.path.exists(p) else {}
    ids = []
    for y in (S - 1, S):
        for wk in range(1, 17):
            j = get_json(f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=400&week={wk}&dates={y}&seasontype=2')
            for e in (j or {}).get('events') or []:
                if (e.get('status') or {}).get('type', {}).get('completed') and str(e['id']) not in box:
                    ids.append((str(e['id']), y, e.get('date')))
    with cf.ThreadPoolExecutor(8) as ex:
        for (gid, y, dt), (_, o) in zip(ids, ex.map(lambda x: P.cfb_one(x[0], ids=True), ids)):
            if o:
                o['S'], o['date'] = y, dt
                box[gid] = o
    json.dump(box, open(p, 'w'))
    ev = []
    for gid, b in box.items():
        if b.get('S') not in (S - 1, S) or 'hid' not in b:
            continue
        try:
            sides, n = T.cfb_sides(b)
        except (ValueError, IndexError, AttributeError):
            continue
        if n >= 30:
            ev.append(dict(t=SR.when(b['date'] or f"{b['S']}-09-01"), S=b['S'], h=b['hid'], a=b['aid'], gid=gid, sh=sides[0], sa=sides[1]))
    return badges_from('cfb', ev, S)


def nhl(rows_last, rows_now, S):
    """called from nhl_games.py with last season's and this season's season_rows"""
    return badges_from('nhl', T.ev_nhl([r for r in rows_last + rows_now if r.get('final', True)]), S)


def soccer(rows):
    """called from soccer_games.py with its rows (football-data shots attached); season = the league season, so each
    league is z-scored on its own and a club's prior is last season's in any league"""
    import soccer_data as D
    by = collections.defaultdict(list)
    for r in rows:
        if r.get('hs') is None or r.get('hst') is None or r.get('ast') is None:
            continue
        sh, sa = T.soccer_sides(r['hs'], r['as'], r['hst'], r['ast'])
        by[r['lg']].append(dict(t=SR.when(r['day']), S=D.season_of(r['day'], r['lg']), h=r['h'], a=r['a'], gid=r['id'], sh=sh, sa=sa))
    out = {}
    for lg, ev in by.items():
        S = max(e['S'] for e in ev)
        ev = [e for e in ev if e['S'] >= S - 1]
        out.update(badges_from('soccer', ev, S))
    return out


def build(sport):
    bdg = {'nfl': nfl, 'nba': nba, 'cbb': cbb, 'cfb': cfb}[sport]()
    write(sport, bdg)


if __name__ == '__main__':
    build(sys.argv[1])
