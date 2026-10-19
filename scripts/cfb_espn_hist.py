"""ESPN college football history (free, no CFBD quota): every FBS and FCS game's score by season, and the
pickcenter lines (closing spread and total by provider) for each game with an FBS side. ESPN event and team ids
are CFBD's. Used by scripts/cfb_elo_research.py.
  python3 scripts/cfb_espn_hist.py [first season] [last season]
Raw pulls are cached in scripts/.cache/cfb/espn_hist/ (scoreboards by week, slim summaries by event); the joined
table goes to scripts/.cache/cfb/espn_hist/games<S>.json.
"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist')
BASE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football'
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football'
UA = {'user-agent': 'Mozilla/5.0 (arkndjl.net arkboard)'}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def once(name, url, slim=lambda x: x):
    p = os.path.join(DIR, name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    d = get(url)
    if d is None:
        return None
    v = slim(d)
    with open(p, 'w') as f:
        json.dump(v, f)
    return v


def slim_board(d):
    out = []
    for e in d.get('events', []):
        if not e.get('competitions'):
            continue
        c = e['competitions'][0]
        side = {x['homeAway']: x for x in c['competitors']}
        if 'home' not in side or 'away' not in side:
            continue
        h, a = side['home'], side['away']
        st = c['status']['type']
        out.append({'id': e['id'], 'date': e['date'], 'st': e['season']['type'], 'n': bool(c.get('neutralSite')),
                    'conf': bool(c.get('conferenceCompetition')), 'done': bool(st.get('completed')),
                    'h': h['id'], 'a': a['id'], 'hn': h['team'].get('displayName'), 'an': a['team'].get('displayName'),
                    'hcf': h['team'].get('conferenceId'), 'acf': a['team'].get('conferenceId'),
                    'hp': float(h['score']) if h.get('score') not in (None, '') else None,
                    'ap': float(a['score']) if a.get('score') not in (None, '') else None,
                    'note': (c.get('notes') or [{}])[0].get('headline')})
    return out


def slim_summary(d):
    lines = []
    for p in d.get('pickcenter') or []:
        ho, ao = p.get('homeTeamOdds') or {}, p.get('awayTeamOdds') or {}
        x = {'prov': (p.get('provider') or {}).get('name'), 'spread': p.get('spread'), 'ou': p.get('overUnder'),
             'details': p.get('details'), 'hml': ho.get('moneyLine'), 'aml': ao.get('moneyLine')}
        # newer seasons carry open and close point spreads by side
        for k in ('open', 'close'):
            v = ((ho.get(k) or {}).get('pointSpread') or {}).get('american')
            if v is not None:
                x['h_' + k] = v
        lines.append(x)
    return {'lines': lines}


def slim_core(d):
    # the core odds feed (2023 on, where the summary's pickcenter is often empty): spread is the home line
    return {'lines': [{'prov': (x.get('provider') or {}).get('name'), 'spread': x.get('spread'), 'ou': x.get('overUnder'),
                       'details': x.get('details'), 'h_open': (((x.get('homeTeamOdds') or {}).get('open') or {}).get('pointSpread') or {}).get('american'),
                       'h_close': (((x.get('homeTeamOdds') or {}).get('close') or {}).get('pointSpread') or {}).get('american')}
                      for x in d.get('items', [])]}


def season(S):
    games = {}
    for grp, kind in (('80', 'fbs'), ('81', 'fcs')):
        for stype, weeks in ((2, range(1, 17)), (3, range(1, 2))):
            if grp == '81' and stype == 3:
                continue
            for w in weeks:
                b = once(f'sb{S}_{grp}_{stype}_{w}.json',
                         f'{BASE}/scoreboard?dates={S}&seasontype={stype}&week={w}&groups={grp}&limit=300', slim_board)   # limit 900 caps 2024+ boards at 25
                for g in b or []:
                    g['w'] = w if stype == 2 else 20 + w
                    g.setdefault('grp', kind)
                    if g['id'] not in games or kind == 'fbs':
                        games[g['id']] = g
    fbs_ids = [g['id'] for g in games.values() if g['grp'] == 'fbs' and g['done']]
    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda i: once(f'sum/{i}.json', f'{BASE}/summary?event={i}', slim_summary), fbs_ids))
    for i, r in zip(fbs_ids, res):
        games[i]['lines'] = (r or {}).get('lines', [])
    empty = [i for i in fbs_ids if not games[i]['lines']]
    with ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda i: once(f'odds/{i}.json', f'{CORE}/events/{i}/competitions/{i}/odds', slim_core), empty))
    for i, r in zip(empty, res):
        games[i]['lines'] = (r or {}).get('lines', [])
    out = sorted(games.values(), key=lambda g: g['date'])
    with open(os.path.join(DIR, f'games{S}.json'), 'w') as f:
        json.dump(out, f)
    nl = sum(1 for g in out if g.get('lines'))
    print(S, len(out), 'games,', len(fbs_ids), 'FBS done,', nl, 'with lines', flush=True)


if __name__ == '__main__':
    os.makedirs(os.path.join(DIR, 'sum'), exist_ok=True)
    os.makedirs(os.path.join(DIR, 'odds'), exist_ok=True)
    a, b = (int(x) for x in (sys.argv[1:3] if len(sys.argv) > 2 else (2015, 2025)))
    for S in range(a, b + 1):
        season(S)
