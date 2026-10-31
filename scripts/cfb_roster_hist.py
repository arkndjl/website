"""Free roster history for the CFB preseason-prior backtest (scripts/cfb_roster_prior.py): ESPN box scores for every
finished FBS game (who recorded a stat for whom, and what), pulled with the same summary call scripts/cfb_espn_hist.py
makes for lines (both slims are written, so neither pull repeats), and 247Sports' composite recruit classes.
  python3 scripts/cfb_roster_hist.py [first season] [last season]      # boxes (default 2014-2026)
  python3 scripts/cfb_roster_hist.py --247 [first class] [last class]  # 247 composite classes (default 2011-2026)
  python3 scripts/cfb_roster_hist.py --def [first season] [last season] # ESPN season defensive lines (default 2012-2022)
Cached in scripts/.cache/cfb/espn_hist/box/<id>.json, scripts/.cache/cfb/r247/<class>.json and
scripts/.cache/cfb/espn_hist/def<season>.json. Box scores carry tackles and sacks in full only from 2024, so the FV
backtest (scripts/cfb_fv_refit.mjs --wide) reads defenders' seasons from ESPN's season leaderboard instead.
"""
import json
import os
import re
import sys
import html as H
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_espn_hist as E

BOX = os.path.join(E.DIR, 'box')
R247 = os.path.join(E.ROOT, 'scripts', '.cache', 'cfb', 'r247')
KEEP = {'passing': ('C/ATT', 'YDS', 'TD', 'INT'), 'rushing': ('CAR', 'YDS', 'TD'), 'receiving': ('REC', 'YDS', 'TD'),
        'defensive': ('TOT', 'SACKS', 'TFL', 'PD', 'QB HUR'), 'interceptions': ('INT',)}
# CFB_BOX_RETURNS=1 also keeps kick and punt returns (scripts/cfb_fv_extras.py, the Oct 31 2026 FV sweep). Off by default:
# return-only players would join the boxes and change who counts as on a roster in scripts/cfb_roster_prior.py
if os.environ.get('CFB_BOX_RETURNS'):
    KEEP.update({'kickReturns': ('NO', 'YDS', 'TD'), 'puntReturns': ('NO', 'YDS', 'TD')})


def slim_box(d):
    teams = {}
    for t in (d.get('boxscore') or {}).get('players') or []:
        P = teams.setdefault(t['team']['id'], {})
        for s in t.get('statistics') or []:
            keep = KEEP.get(s.get('name'))
            if not keep:
                continue
            L = s.get('labels') or []
            for a in s.get('athletes') or []:
                aid = (a.get('athlete') or {}).get('id')
                if not aid:
                    continue
                row = P.setdefault(aid, {'n': a['athlete'].get('displayName')})
                for k in keep:
                    if k in L:
                        v = a['stats'][L.index(k)] if L.index(k) < len(a.get('stats') or []) else None
                        if k == 'C/ATT':
                            m = re.match(r'(\d+)/(\d+)', v or '')
                            row['cmp'], row['att'] = (int(m[1]), int(m[2])) if m else (0, 0)
                        else:
                            try:
                                row[s['name'][:3] + '_' + k] = float(v)
                            except (TypeError, ValueError):
                                pass
    return teams


def pull_game(i):
    pb, ps = os.path.join(BOX, f'{i}.json'), os.path.join(E.DIR, 'sum', f'{i}.json')
    if os.path.exists(pb):
        return True
    d = E.get(f'{E.BASE}/summary?event={i}')
    if d is None:
        return False
    with open(pb, 'w') as f:
        json.dump(slim_box(d), f)
    if not os.path.exists(ps):
        with open(ps, 'w') as f:
            json.dump(E.slim_summary(d), f)
    return True


def boards(S):
    games = {}
    for grp, kind in (('80', 'fbs'), ('81', 'fcs')):
        for stype, weeks in ((2, range(1, 17)), (3, range(1, 2))):
            if grp == '81' and stype == 3:
                continue
            for w in weeks:
                b = E.once(f'sb{S}_{grp}_{stype}_{w}.json',
                           f'{E.BASE}/scoreboard?dates={S}&seasontype={stype}&week={w}&groups={grp}&limit=300', E.slim_board)
                for g in b or []:
                    if g['id'] not in games or kind == 'fbs':
                        games[g['id']] = {**g, 'grp': kind}
    return [g['id'] for g in games.values() if g['grp'] == 'fbs' and g['done']]


DEF = ('soloTackles', 'assistTackles', 'totalTackles', 'sacks', 'tacklesForLoss', 'passesDefended')


def def_season(S):
    # every athlete with a defensive line that season, D-I wide (FBS filtered downstream), 200 a page
    p = os.path.join(E.DIR, f'def{S}.json')
    if os.path.exists(p):
        return
    url = (f'https://site.web.api.espn.com/apis/common/v3/sports/football/college-football/statistics/byathlete?region=us&lang=en'
           f'&contentorigin=espn&isqualified=false&limit=200&category=defense&sort=defensive.totalTackles:desc&season={S}&seasontype=2&page=')
    first = E.get(url + '1')
    pages = [first] + [E.get(url + str(i)) for i in range(2, ((first or {}).get('pagination') or {}).get('pages', 1) + 1)]
    out = []
    for d in pages:
        names = {c['name']: c['names'] for c in (d or {}).get('categories') or []}
        for a in (d or {}).get('athletes') or []:
            at, row = a['athlete'], {}
            for c in a.get('categories') or []:
                if c.get('splitId') not in (None, '0') and c['name'] in row:
                    continue
                for k, v in zip(names.get(c['name'], []), c.get('values') or []):
                    if k in DEF or (c['name'], k) in (('general', 'gamesPlayed'), ('general', 'fumblesForced'), ('defensiveinterceptions', 'interceptions')):
                        row[k] = v
            out.append({'id': at.get('id'), 'n': at.get('displayName'), 'pos': (at.get('position') or {}).get('abbreviation'), 'team': at.get('teamId'), **row})
    with open(p, 'w') as f:
        json.dump(out, f)
    print('def', S, len(out), flush=True)


def get_html(url, tries=4):
    for i in range(tries):
        r = subprocess.run(['curl', '-sS', '-f', '-A', 'Mozilla/5.0', url], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        time.sleep(2 ** i)
    return ''


def r247(y, pages=90):
    p = os.path.join(R247, f'{y}.json')
    if os.path.exists(p):
        return
    out = []
    for pg in range(1, pages + 1):
        h = get_html(f'https://247sports.com/season/{y}-football/compositerecruitrankings/?ViewPath=~/Views/SkyNet/PlayerSportRanking/_SimpleSetForSeason.ascx&Page={pg}')
        items = h.split('rankings-page__list-item"')[1:]
        for x in items:
            g = lambda pat: (re.search(pat, x, re.S) or [None, None])[1]
            sc = g(r'class="score">([\d.]+)')
            if not sc:
                continue
            out.append({'name': H.unescape(g(r'name-link"[^>]*>([^<]*)') or ''), 'pos': (g(r'class="position">\s*([^<]*?)\s*</div>') or '').strip(),
                        'comp': float(sc), 'school': H.unescape(g(r'class="img-link"[^>]*>\s*<img alt="([^"]*)"') or '') or None})
        if len(items) < 50:
            break
    with open(p, 'w') as f:
        json.dump(out, f)
    print('247', y, len(out), sum(1 for r in out if r['school']), 'committed', flush=True)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--247':
        os.makedirs(R247, exist_ok=True)
        lo, hi = (int(x) for x in (a[1:3] if len(a) > 2 else (2011, 2026)))
        for y in range(lo, hi + 1):
            r247(y)
        sys.exit()
    if a and a[0] == '--def':
        lo, hi = (int(x) for x in (a[1:3] if len(a) > 2 else (2012, 2022)))
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(def_season, range(lo, hi + 1)))
        sys.exit()
    os.makedirs(BOX, exist_ok=True); os.makedirs(os.path.join(E.DIR, 'sum'), exist_ok=True)
    lo, hi = (int(x) for x in (a[:2] if len(a) > 1 else (2014, 2026)))
    for S in range(lo, hi + 1):
        ids = boards(S)
        with ThreadPoolExecutor(16) as ex:
            ok = list(ex.map(pull_game, ids))
        print(S, len(ids), 'FBS games,', sum(ok), 'boxes', flush=True)
