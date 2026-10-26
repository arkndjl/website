#!/usr/bin/env python3
"""Team breakdowns for the power rankings' dropdowns (static/data/teams/<sport>.json, read by
layouts/partials/teamjs.html on the first click). Display only: nothing here feeds a model.

The game builders call save() with what only they hold (the rating split into its inputs, the CBB preseason prior
split into its roster terms, and the season schedule with each game left at the model's win chance); save() adds the
key players from the committed leaderboards and writes the file:

    {asof, sport, pm: key players' metric, teams: {key: {parts: [[input, value]], pparts: [[term, value]],
     sch: [[date or week, opponent key, 'v' home | '@' away | 'n' neutral, score for, score against, win chance, margin
     (, draw chance: soccer)]],
     pl: [[name, position, metric, note]]}}, nm: {opponent key: name} (opponents off the power table)}

parts are each input's push on the rating against an average team, in the rating's units, so they sum to the rating
(up to rounding). A played game has its score and no win chance; a game left has the win chance and margin the
season sims use (rating gap and home edge) and no score.
"""
import gzip
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'static', 'data', 'teams')
SD = os.path.join(ROOT, 'static', 'data')

# Basketball-Reference team codes -> ESPN's (the NBA power table's keys)
NBA_BR = {'PHO': 'PHX', 'NOP': 'NO', 'CHO': 'CHA', 'SAS': 'SA', 'WAS': 'WSH', 'BRK': 'BKN', 'GSW': 'GS', 'NYK': 'NY', 'UTA': 'UTAH'}


def _load(path):
    try:
        with (gzip.open(path, 'rt') if path.endswith('.gz') else open(path)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _latest(folder):
    try:
        fs = sorted(f for f in os.listdir(os.path.join(SD, folder)) if re.match(r'\d{4}\.json$', f))
    except OSError:
        return None
    return _load(os.path.join(SD, folder, fs[-1])) if fs else None


def _board(path):
    d = _load(path)
    if not d:
        return []
    c = {k: i for i, k in enumerate(d['cols'])}
    return [{k: r[i] for k, i in c.items()} for r in d['rows']]


def _top(by, n=5):
    return {t: [p[1] for p in sorted(v, key=lambda x: -x[0])[:n]] for t, v in by.items()}


def players(sport):
    """(metric label, {team key: [[name, pos, metric, note], ...]}) from the committed leaderboards"""
    by = defaultdict(list)
    if sport == 'cbb':
        for r in _board(os.path.join(SD, 'cbb-all.json')):
            m = re.search(r'/(\d+)\.png', r.get('logo') or '')
            if m and r.get('fv'):
                note = ' · '.join(x for x in (r.get('cls'), r.get('role')) if x)
                by[m[1]].append((r['fv'] + (r.get('ovr') or 0) * 1e-6, [r['name'], r.get('pos') or '', r['fv'], note]))
        return 'FV', _top(by)
    if sport == 'cfb':
        for r in _board(os.path.join(SD, 'cfb-all.json')):
            m = re.search(r'/(\d+)\.png', r.get('logo') or '')
            if m and r.get('war') is not None:
                note = f"FV {r['fv']}" if r.get('fv') else ''
                by[m[1]].append((r['war'], [r['name'], r.get('pos') or '', round(r['war'], 2), note]))
        return 'WAR', _top(by)
    if sport == 'nfl':
        for p in (_load(os.path.join(SD, 'nfl-war.json')) or {}).get('players', []):
            by[p['t']].append((p['war'], [p['n'], p['pos'], round(p['war'], 2), p.get('line') or '']))
        return 'WAR', _top(by)
    if sport == 'nba':
        for p in (_latest('nba-xpm') or {}).get('players', []):
            if (p.get('mp') or 0) >= 30:
                by[NBA_BR.get(p['tm'], p['tm'])].append((p.get('vorx') or 0, [p['n'], p['pos'], p['xpm'], f"{p['g']} G, {p['mp']} min"]))
        return 'XPM', _top(by)
    if sport == 'nhl':
        for p in (_latest('nhl-war') or {}).get('players', []):
            note = f"{p['gp']} GP" + (f", {p['pts']} pts" if p.get('grp') != 'G' else (f", {p['gsax']:+.1f} GSAx" if p.get('gsax') is not None else ''))
            by[p['tm']].append((p['war'], [p['n'], p['pos'], round(p['war'], 2), note]))
        return 'WAR', _top(by)
    if sport == 'soccer':
        ids = (_load(os.path.join(ROOT, 'data', 'soccer_logos.json')) or {}).get('espn', {})
        for p in (_latest('soccer-war') or {}).get('players', []):
            t = ids.get(p['team'])
            if t and p.get('gar') is not None:
                by[t].append((p['gar'], [p['n'], p['pos'], round(p['gar'], 2), f"{p['g']} G, {p['a']} A in {p['min']} min"]))
        return 'GAR', _top(by)
    return '', {}


def save(sport, teams, names=None, asof=None):
    """teams: {key: {'parts': [...], 'pparts': [...], 'sch': [...]}} (any may be missing); names: {opponent key: name}"""
    pm, pl = players(sport)
    out = {}
    for k, v in teams.items():
        v = {a: b for a, b in v.items() if b}
        if pl.get(k):
            v['pl'] = pl[k]
        out[k] = v
    for k in pl:
        out.setdefault(k, {'pl': pl[k]})
    res = {'asof': asof or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'sport': sport, 'pm': pm, 'teams': out,
           'nm': {k: v for k, v in (names or {}).items()}}
    res = _finite(res)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'{sport}.json')
    old = _load(path)
    if old and {k: v for k, v in old.items() if k != 'asof'} == {k: v for k, v in json.loads(json.dumps(res)).items() if k != 'asof'}:
        return print(f'team breakdowns: {path} unchanged')
    with open(path, 'w') as f:
        json.dump(res, f, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    print(f'team breakdowns: {path} ({len(out)} teams)')


def _finite(x):
    """NaN / inf -> null (a bare NaN breaks the strict JSON check), numpy scalars -> floats"""
    import math
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    if isinstance(x, bool) or x is None or isinstance(x, (int, str)):
        return x
    try:
        f = float(x)
    except (TypeError, ValueError):
        return x
    return f if math.isfinite(f) else None


def center(comps, rating, rest=None, nd=2):
    """{team: [[input, push]]}: comps = {team: {input: points}} each taken against the teams' mean; with rest, what
    the shown rating has beyond the parts (a constant across teams, such as this week's league-wide absences) goes
    into that input so the parts sum to it"""
    keys = list(next(iter(comps.values())).keys()) if comps else []
    mu = {k: sum(c.get(k, 0.0) for c in comps.values()) / len(comps) for k in keys}
    out = {}
    for t, c in comps.items():
        p = {k: c.get(k, 0.0) - mu[k] for k in keys}
        if rest is not None and t in rating:
            p[rest] = p.get(rest, 0.0) + rating[t] - sum(p.values())
        out[t] = [[k, round(v, nd)] for k, v in p.items()]
    return out


def sched_rows(games, key):
    """[[date, opp, ha, for, against, p, m]] for one team from games = [{'d', 'h', 'a', 'n' neutral, 'hs', 'as', 'p' home
    win chance, 'm' home margin}], in date order"""
    out = []
    for g in games:
        if key not in (g['h'], g['a']):
            continue
        home = g['h'] == key
        ha = 'n' if g.get('n') else ('v' if home else '@')
        if g.get('hs') is not None:
            out.append([g['d'], g['a'] if home else g['h'], ha, g['hs'] if home else g['as'], g['as'] if home else g['hs'], None, None])
        else:
            p, m = g.get('p'), g.get('m')
            dr = g.get('dr')
            if dr is not None and p is not None and not home:      # soccer: win chance = away win, draw kept
                p = 1 - p - dr
            elif p is not None and not home:
                p = 1 - p
            row = [g['d'], g['a'] if home else g['h'], ha, None, None, None if p is None else round(p, 3),
                   None if m is None else round(m if home else -m, 2 if dr is not None else 1)]
            if dr is not None:
                row.append(round(dr, 3))
            out.append(row)
    out.sort(key=lambda r: (isinstance(r[0], str), r[0]))
    return out


def schedules(games, keys):
    by = defaultdict(list)
    for g in games:
        by[g['h']].append(g); by[g['a']].append(g)
    return {k: sched_rows(by.get(k, []), k) for k in keys}


def cfb():
    """CFB: the ranking's parts are on data/cfb_rank.json already (the table reads them); this adds each FBS team's
    season from ESPN's team schedules, every game left at the ranking's score gap plus the game model's home edge
    (data/cfb_model.json beta.home) at its margin sd. The board job runs it after the rankings are written."""
    import math
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    rank = _load(os.path.join(ROOT, 'data', 'cfb_rank.json'))
    rep = (_load(os.path.join(ROOT, 'data', 'cfb_model.json')) or {}).get('report') or {}
    if not rank:
        return print('team breakdowns: no data/cfb_rank.json')
    hfa = (rep.get('beta') or {}).get('home', 2.0)
    sig = (rep.get('params') or {}).get('sigma', 14.2)
    score = {t['tid']: t['score'] for t in rank['teams']}
    season = int(rank['asof'][:4])

    def one(tid):
        url = f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{tid}/schedule?season={season}'
        for _ in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return tid, json.load(r).get('events') or []
            except Exception:
                continue
        return tid, None
    games, names, got = {}, {}, set()
    with ThreadPoolExecutor(12) as ex:
        for tid, evs in ex.map(one, list(score)):
            if evs is None:
                continue
            got.add(tid)
            for e in evs:
                c = (e.get('competitions') or [{}])[0]
                cs = {x['homeAway']: x for x in c.get('competitors') or []}
                if 'home' not in cs or 'away' not in cs:
                    continue
                h, a = cs['home']['id'], cs['away']['id']
                for x in (cs['home'], cs['away']):
                    if x['id'] not in score:
                        names[x['id']] = (x.get('team') or {}).get('shortDisplayName') or (x.get('team') or {}).get('displayName') or x['id']
                d = (datetime.strptime(e['date'][:16], '%Y-%m-%dT%H:%M') - __import__('datetime').timedelta(hours=5)).strftime('%Y-%m-%d')
                g = {'d': d, 'h': h, 'a': a, 'n': bool(c.get('neutralSite'))}
                st = (c.get('status') or {}).get('type') or {}
                sc = lambda x: (x.get('score') or {}).get('value') if isinstance(x.get('score'), dict) else x.get('score')
                if st.get('completed') and sc(cs['home']) is not None:
                    g.update(hs=int(float(sc(cs['home']))), **{'as': int(float(sc(cs['away'])))})
                elif h in score and a in score:
                    m = score[h] - score[a] + (0 if g['n'] else hfa)
                    g.update(m=m, p=0.5 * (1 + math.erf(m / sig / math.sqrt(2))))
                games[e['id']] = g
    if not got:
        return print('team breakdowns: ESPN schedules unavailable')
    old = (_load(os.path.join(OUT, 'cfb.json')) or {}).get('teams', {})
    S = schedules(list(games.values()), list(score))
    save('cfb', {t: {'sch': S[t] if t in got else (old.get(t) or {}).get('sch')} for t in score}, names=names)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['cfb']:
        cfb()
    elif sys.argv[1:]:
        save(sys.argv[1], {t: {'sch': v.get('sch'), 'parts': v.get('parts'), 'pparts': v.get('pparts')}
                           for t, v in ((_load(os.path.join(OUT, f'{sys.argv[1]}.json')) or {}).get('teams') or {}).items()},
             names=(_load(os.path.join(OUT, f'{sys.argv[1]}.json')) or {}).get('nm'))
