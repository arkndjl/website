#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ARKLIST performances: each ARKLIST player's season game log (statlines) and next game, from ESPN.

    python3 scripts/arklist_perf.py            # writes static/data/arklist-perf.json
    python3 scripts/arklist_perf.py --only "Adonis Ratliff"

Players come from data/arklist.json, matched to the boards through scripts/names.py for their ESPN athlete id:
college football static/data/cfb-all.json (espnl), college basketball cbb-all.json (links.espn), NBA nba-xpm and NHL
nhl-war (ph), NFL nfl-war and hockey prospects at NCAA programs by name on the team's ESPN roster. High school recruits
and players at clubs ESPN does not cover (internationals, junior hockey) have no feed and are left out.

Per player: athlete gamelog (every game this season, final), athlete overview (next game), and for a game in
progress the event's box score (marked live; replaced by the final line on a later run). Games already in the file
are kept when a fetch fails, so a flaky run drops nothing. Each game carries its US Eastern date (the "day" the
ARKLIST GFX card picks). Stdlib only."""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names  # noqa: E402

OUT = os.path.join(ROOT, 'static', 'data', 'arklist-perf.json')
ET = ZoneInfo('America/New_York')
WEB = 'https://site.web.api.espn.com/apis/common/v3/sports/'
SITE = 'https://site.api.espn.com/apis/site/v2/sports/'
LG = {'college-football': 'football/college-football', 'college-basketball': 'basketball/mens-college-basketball',
      'nfl': 'football/nfl', 'nba': 'basketball/nba', 'nhl': 'hockey/nhl', 'hockey-prospects': 'hockey/mens-college-hockey'}
HEAD = {'college-football': 'college-football', 'college-basketball': 'mens-college-basketball', 'nfl': 'nfl', 'nba': 'nba',
        'nhl': 'nhl', 'hockey-prospects': 'mens-college-hockey'}


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (arkboard data)'})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            if k == tries - 1: return None
            time.sleep(1 + k * 2)


def load(p, d=None):
    try:
        with open(os.path.join(ROOT, p)) as f: return json.load(f)
    except Exception: return d


def rows(d):
    return [dict(zip(d['cols'], r)) for r in d['rows']] if d and d.get('cols') else []


def espn_id(u):
    m = re.search(r'/id/(\d+)', u or '')
    return m.group(1) if m else None


def headshot(sport, i):
    return f'https://a.espncdn.com/combiner/i?img=/i/headshots/{HEAD[sport]}/players/full/{i}.png&w=350&h=254&scale=crop' if i else ''


def local_logo(sport, team_id, abbr, url):
    """the site's own logo file when it has one (same-origin, so the GFX canvas can draw it), else ESPN's"""
    if sport in ('college-football', 'college-basketball', 'hockey-prospects') and team_id and os.path.exists(os.path.join(ROOT, 'static', 'img', 'cfb', 'logos', f'{team_id}.png')):
        return f'/img/cfb/logos/{team_id}.png'
    folder = {'nba': 'nba', 'nhl': 'nhl', 'nfl': 'nfl'}.get(sport)
    if folder and abbr and os.path.exists(os.path.join(ROOT, 'static', 'img', folder, f'{abbr.lower()}.png')):
        return f'/img/{folder}/{abbr.lower()}.png'
    return url or ''


_rosters = {}


def roster_find(sport, team, name):
    """an athlete id by name on the team's ESPN roster (players the boards hold without an ESPN id)"""
    lg = LG[sport]
    if lg not in _rosters:
        d = get(SITE + lg + '/teams?limit=500') or {}
        try: _rosters[lg] = [t['team'] for t in d['sports'][0]['leagues'][0]['teams']]
        except Exception: _rosters[lg] = []
    for t in _rosters[lg]:
        if not (names.same_team(team, t.get('displayName', '')) or names.same_team(team, t.get('location', '')) or team == t.get('abbreviation')):
            continue
        r = get(SITE + lg + f"/teams/{t['id']}/roster") or {}
        flat = [x for grp in r.get('athletes', []) for x in (grp.get('items') or [grp])]
        m = names.Matcher(flat, name='displayName', team=None, pos=None)
        hit, _ = m.find(name)
        if hit: return hit['id'], t
    return None, None


def resolve(lists):
    """every ARKLIST entry ESPN covers, as {s, n, t, lo, ph, pos, id}"""
    pools = {}
    pools['college-football'] = [dict(name=r['name'], team=r['team'], logo=r['logo'], pos=r['pos'], id=espn_id(r.get('espnl'))) for r in rows(load('static/data/cfb-all.json'))]
    pools['college-basketball'] = [dict(name=r['name'], team=r['team'], logo=r['logo'], pos=r['pos'], id=espn_id((r.get('links') or {}).get('espn'))) for r in rows(load('static/data/cbb-all.json'))]
    nba = load(f"static/data/nba-xpm/{(load('data/nba_xpm.json', {}) or {}).get('current', 2027)}.json", {}) or {}
    pools['nba'] = [dict(name=p['n'], team=p['tm'], logo=f"/img/nba/{str(p['tm']).lower()}.png", pos=p.get('pos'), id=p.get('ph')) for p in nba.get('players', [])]
    nhl = load(f"static/data/nhl-war/{(load('data/nhl_war.json', {}) or {}).get('current', 2027)}.json", {}) or {}
    pools['nhl'] = [dict(name=p['n'], team=p['tm'], logo=f"/img/nhl/{str(p['tm']).lower()}.png", pos=p.get('pos'), id=p.get('ph')) for p in nhl.get('players', [])]
    nfl = load('static/data/nfl-war.json', {}) or {}
    pools['nfl'] = [dict(name=p['n'], team=p['tm'], logo=f"/img/nfl/{str(p['tm']).split('/')[-1].lower()}.png", pos=p.get('pos'), id=None) for p in nfl.get('players', [])]
    hk = load('data/hockey.json', {}) or {}
    pools['hockey-prospects'] = [dict(name=r['name'], team=r.get('club'), logo='', pos=r.get('pos'), id=None) for r in hk.get('board', []) if r.get('league') == 'NCAA']
    out = []
    for sport, pool in pools.items():
        if not lists.get(sport): continue
        M = names.Matcher(pool)
        for e in lists[sport]:
            n, _, t = str(e).partition('|')
            r, _ = M.find(n.strip(), t.strip() or None)
            if not r: continue
            pid, team = r['id'], None
            if not pid and r.get('team'):
                pid, team = roster_find(sport, r['team'], r['name'])
            if not pid: continue
            logo = r['logo'] or (local_logo(sport, team.get('id'), team.get('abbreviation'), (team.get('logos') or [{}])[0].get('href')) if team else '')
            out.append(dict(s=sport, n=r['name'], t=r['team'], lo=logo, ph=headshot(sport, pid), pos=r.get('pos') or '', id=str(pid)))
    return out


# ---- statlines: ESPN's labels (gamelog and box score) to one display list per sport ----
def num(v):
    try: return float(str(v).replace('+', ''))
    except Exception: return None


def nz(v): return (num(v) or 0) != 0


def line_bb(s):
    out = [['PTS', s.get('PTS')], ['REB', s.get('REB')], ['AST', s.get('AST')]]
    for k in ('STL', 'BLK'):
        if nz(s.get(k)): out.append([k, s.get(k)])
    for k in ('FG', '3PT', 'FT'):
        if s.get(k) and s.get(k) != '0-0': out.append([k, s.get(k)])
    if nz(s.get('TO')): out.append(['TO', s.get('TO')])
    if s.get('MIN') is not None: out.append(['MIN', s.get('MIN')])
    return [x for x in out if x[1] not in (None, '')]


def line_hk(s):
    if s.get('SV') is not None or s.get('GA') is not None:
        out = [['SV', s.get('SV')], ['GA', s.get('GA')]]
        if s.get('SV%'): out.append(['SV%', s.get('SV%')])
    else:
        g, a = num(s.get('G')) or 0, num(s.get('A')) or 0
        out = [['G', int(g)], ['A', int(a)], ['PTS', int(g + a)]]
        if s.get('+/-') not in (None, ''): pm = num(s.get('+/-')) or 0; out.append(['+/-', ('+' if pm > 0 else '') + str(int(pm))])
        sog = s.get('S') if s.get('S') not in (None, '') else s.get('SOG')   # the box score's S is shots on goal
        if sog not in (None, ''): out.append(['SOG', sog])
        if s.get('TOI'): out.append(['TOI', s.get('TOI')])
    return [x for x in out if x[1] not in (None, '')]


def line_fb(s):
    out = []
    ca = s.get('passing.C/ATT') or (f"{s['passing.CMP']}/{s['passing.ATT']}" if s.get('passing.ATT') else None)
    if ca and ca.split('/')[-1] not in ('0', ''):
        out += [['C/ATT', ca], ['PASS YDS', s.get('passing.YDS')]]
        if nz(s.get('passing.TD')): out.append(['PASS TD', s.get('passing.TD')])
        if nz(s.get('passing.INT')): out.append(['INT', s.get('passing.INT')])
    if nz(s.get('rushing.CAR')):
        out += [['CAR', s.get('rushing.CAR')], ['RUSH YDS', s.get('rushing.YDS')]]
        if nz(s.get('rushing.TD')): out.append(['RUSH TD', s.get('rushing.TD')])
    if nz(s.get('receiving.REC')):
        out += [['REC', s.get('receiving.REC')], ['REC YDS', s.get('receiving.YDS')]]
        if nz(s.get('receiving.TD')): out.append(['REC TD', s.get('receiving.TD')])
    tk = s.get('defensive.TOT')
    if nz(tk) or nz(s.get('defensive.SACKS')) or nz(s.get('interceptions.INT')) or nz(s.get('defensive.PD')):
        out.append(['TKL', tk or 0])
        for k, lab in (('defensive.TFL', 'TFL'), ('defensive.SACKS', 'SACK'), ('defensive.PD', 'PD'), ('interceptions.INT', 'INT'), ('defensive.FF', 'FF')):
            if nz(s.get(k)): out.append([lab, s.get(k)])
    if s.get('kicking.FG') and s.get('kicking.FG') != '0/0': out += [['FG', s.get('kicking.FG')], ['XP', s.get('kicking.XP')]]
    if nz(s.get('punting.NO')): out += [['PUNTS', s.get('punting.NO')], ['AVG', s.get('punting.AVG')]]
    for c, lab in (('kickReturns', 'KR'), ('puntReturns', 'PR')):
        if nz(s.get(c + '.NO')): out += [[lab, s.get(c + '.NO')], [lab + ' YDS', s.get(c + '.YDS')]]
    return [x for x in out if x[1] not in (None, '')]


def statline(sport, s):
    if sport in ('college-basketball', 'nba'): return line_bb(s)
    if sport in ('nhl', 'hockey-prospects'): return line_hk(s)
    return line_fb(s)


CAT = {'tackles': 'defensive', 'defense': 'defensive'}
LAB = {'SACK': 'SACKS', 'LNG': 'LONG', 'TOI/G': 'TOI', 'S': 'S', 'TOTALREBOUNDS': 'REB'}


def gamelog_stats(d, stats):
    """one gamelog row as {label or category.label: value}; football labels carry their category"""
    labels = d.get('labels') or []
    cats = []
    for c in d.get('categories') or []: cats += [CAT.get(c['name'], c['name'])] * int(c.get('count') or 0)
    out = {}
    for j, lab in enumerate(labels):
        if j >= len(stats): break
        lab = LAB.get(lab, lab)
        k = (cats[j] + '.' + lab) if j < len(cats) and cats else lab
        if k not in out: out[k] = stats[j]
    if 'passing.CMP' in out and 'passing.ATT' in out: out['passing.C/ATT'] = f"{out['passing.CMP']}/{out['passing.ATT']}"
    if 'SV' not in out and 'SAVES' in out: out['SV'] = out['SAVES']
    return out


def box_stats(summary, pid):
    """the player's line from an event box score, or None when he has none (did not play)"""
    out, seen = {}, False
    for t in (summary.get('boxscore') or {}).get('players') or []:
        for st in t.get('statistics') or []:
            cat = CAT.get(st.get('name') or '', st.get('name') or '')
            labels = st.get('labels') or []
            for a in st.get('athletes') or []:
                if str((a.get('athlete') or {}).get('id')) != pid: continue
                if a.get('didNotPlay') or not a.get('stats'): continue
                seen = True
                for lab, v in zip(labels, a['stats']):
                    lab = LAB.get(lab, lab)
                    key = (cat + '.' + lab) if cat in ('passing', 'rushing', 'receiving', 'defensive', 'interceptions', 'kicking', 'punting', 'kickReturns', 'puntReturns', 'fumbles') else lab
                    out.setdefault(key, v)
    if not seen: return None
    if 'S' in out and 'SOG' not in out: pass
    return out


def et_day(iso):
    t = dt.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    return t.astimezone(ET).strftime('%Y-%m-%d')


def iso(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).strftime('%Y-%m-%dT%H:%MZ')


def from_summary(sport, p, eid):
    s = get(SITE + LG[sport] + '/summary?event=' + eid)
    if not s: return None
    comp = ((s.get('header') or {}).get('competitions') or [{}])[0]
    st = (comp.get('status') or {}).get('type') or {}
    if st.get('state') == 'pre': return None
    stats = box_stats(s, p['id'])
    if stats is None: return None
    cs = comp.get('competitors') or []
    me = next((c for c in cs if names.same_team(p['t'], (c.get('team') or {}).get('displayName', '')) or names.same_team(p['t'], (c.get('team') or {}).get('location', ''))), None)
    if me is None:
        ids = {str(t['team']['id']) for t in (s.get('boxscore') or {}).get('players') or [] for st2 in t.get('statistics') or [] for a in st2.get('athletes') or [] if str((a.get('athlete') or {}).get('id')) == p['id']}
        me = next((c for c in cs if str(c.get('id')) in ids), cs[0] if cs else {})
    op = next((c for c in cs if c is not me), {})
    ot = op.get('team') or {}
    ms, os_ = me.get('score'), op.get('score')
    g = dict(e=eid, d=iso(comp.get('date') or s['header'].get('date', '')), day=et_day(comp.get('date')), ha='vs' if me.get('homeAway') == 'home' else '@',
             o=ot.get('abbreviation') or ot.get('displayName'), on=ot.get('location') or ot.get('displayName'),
             ol=local_logo(sport, ot.get('id'), ot.get('abbreviation'), ((ot.get('logos') or [{}])[0]).get('href') or ot.get('logo')),
             sc=f'{ms}-{os_}' if ms not in (None, '') else '', st=statline(sport, stats))
    if st.get('completed'):
        g['r'] = 'W' if me.get('winner') else ('L' if op.get('winner') else 'T')
    else:
        g['live'] = st.get('shortDetail') or 'live'
    return g


_sched = {}


def team_next(p, log):
    """the team's next scheduled game (the athlete overview leaves it out for football)"""
    tid = next((str((e.get('team') or {}).get('id')) for e in ((log or {}).get('events') or {}).values() if (e.get('team') or {}).get('id')), None)
    if not tid: return None
    k = (p['s'], tid)
    if k not in _sched: _sched[k] = get(SITE + LG[p['s']] + f'/teams/{tid}/schedule') or {}
    now = dt.datetime.now(dt.timezone.utc)
    for e in _sched[k].get('events') or []:
        c = (e.get('competitions') or [{}])[0]
        if ((c.get('status') or {}).get('type') or {}).get('state') != 'pre': continue
        if dt.datetime.fromisoformat(e['date'].replace('Z', '+00:00')) < now: continue
        cs = c.get('competitors') or []
        me = next((x for x in cs if str(x.get('id')) == tid), {})
        op = next((x for x in cs if x is not me), {})
        ot = op.get('team') or {}
        return dict(e=e['id'], d=iso(e['date']), ha='vs' if me.get('homeAway') == 'home' else '@', o=ot.get('abbreviation') or ot.get('displayName'),
                    on=ot.get('displayName'), ol=local_logo(p['s'], ot.get('id'), ot.get('abbreviation'), ((ot.get('logos') or [{}])[0]).get('href')))
    return None


def player(p, prev):
    lg = LG[p['s']]
    log = get(WEB + lg + f"/athletes/{p['id']}/gamelog")
    ov = get(WEB + lg + f"/athletes/{p['id']}/overview")
    games = {g['e']: g for g in (prev or {}).get('g', [])}
    if log and log.get('events'):
        ev = log['events']
        for stype in log.get('seasonTypes') or []:
            for cat in stype.get('categories') or []:
                for row in cat.get('events') or []:
                    e = ev.get(row.get('eventId'))
                    if not e or not e.get('gameDate'): continue
                    op = e.get('opponent') or {}
                    sc = e.get('score') or ''
                    # ESPN writes the winner's score first: put the player's team first
                    hs, as_ = e.get('homeTeamScore'), e.get('awayTeamScore')
                    home = str(e.get('homeTeamId')) == str((e.get('team') or {}).get('id'))
                    if hs not in (None, '') and as_ not in (None, ''): sc = f'{hs}-{as_}' if home else f'{as_}-{hs}'
                    games[e['id']] = dict(e=e['id'], d=iso(e['gameDate']), day=et_day(e['gameDate']), ha='vs' if e.get('atVs') == 'vs' else '@',
                                          o=op.get('abbreviation') or op.get('displayName'), on=op.get('displayName'),
                                          ol=local_logo(p['s'], op.get('id'), op.get('abbreviation'), op.get('logo')),
                                          sc=sc, r=e.get('gameResult') or '', st=statline(p['s'], gamelog_stats(log, row.get('stats') or [])))
    nxt = None
    for e in (((ov or {}).get('nextGame') or {}).get('league') or {}).get('events') or []:
        state = ((e.get('fullStatus') or {}).get('type') or {}).get('state') or e.get('status')
        cs = e.get('competitors') or []
        me = next((c for c in cs if names.same_team(p['t'], c.get('displayName', '')) or c.get('abbreviation') == p['t']), None)
        if me is None and len(cs) == 2:
            # the board's team name may differ from ESPN's: the side whose logo or id the player's gamelog shows
            tid = str(((log or {}).get('events') or {}).get(next(iter((log or {}).get('events') or {}), ''), {}).get('team', {}).get('id', ''))
            me = next((c for c in cs if str(c.get('id')) == tid), cs[1])
        op = next((c for c in cs if c is not me), {})
        if state == 'pre':
            nxt = dict(e=e['id'], d=iso(e['date']), ha='vs' if (me or {}).get('homeAway') == 'home' else '@', o=op.get('abbreviation') or op.get('displayName'),
                       on=op.get('displayName'), ol=local_logo(p['s'], op.get('id'), op.get('abbreviation'), op.get('logo')))
        elif e['id'] not in games or games[e['id']].get('live'):
            g = from_summary(p['s'], p, e['id'])
            if g: games[e['id']] = g
    if not nxt and not any(g.get('live') for g in games.values()):
        nxt = team_next(p, log)
    # a game logged live on an earlier run that the gamelog hasn't finalised yet: read its box score again
    for eid, g in list(games.items()):
        if g.get('live') and (not nxt or nxt['e'] != eid):
            g2 = from_summary(p['s'], p, eid)
            if g2: games[eid] = g2
    gl = sorted(games.values(), key=lambda g: g['d'], reverse=True)
    if nxt and any(g['e'] == nxt['e'] for g in gl): nxt = None
    out = dict(p)
    out['g'] = gl
    if nxt: out['nx'] = nxt
    out['ok'] = bool(log or ov)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only')
    a = ap.parse_args()
    lists = load('data/arklist.json', {}) or {}
    ps = resolve(lists)
    if a.only: ps = [p for p in ps if names.same(p['n'], a.only)]
    old = {(p['s'], p['id']): p for p in (load('static/data/arklist-perf.json', {}) or {}).get('players', [])}
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda p: player(p, old.get((p['s'], p['id']))), ps))
    for r in res:
        r.pop('ok', None)
    if a.only:
        print(json.dumps(res, indent=1)[:4000]); return
    doc = dict(asof=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), players=res)
    new = json.dumps(doc, separators=(',', ':'), ensure_ascii=False)
    try:
        with open(OUT) as f: cur = json.load(f)
        if cur.get('players') == res: return print('arklist perf: no change')
    except Exception: pass
    with open(OUT, 'w') as f: f.write(new)
    print(f'arklist perf: {len(res)} players, {sum(len(r["g"]) for r in res)} games, {sum(1 for r in res if r.get("nx"))} next games')


if __name__ == '__main__':
    main()
