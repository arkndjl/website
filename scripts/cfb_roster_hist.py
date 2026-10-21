"""Free roster history for the CFB preseason-prior backtest (scripts/cfb_roster_prior.py): ESPN box scores for every
finished FBS game (who recorded a stat for whom, and what), pulled with the same summary call scripts/cfb_espn_hist.py
makes for lines (both slims are written, so neither pull repeats), and 247Sports' composite recruit classes.
  python3 scripts/cfb_roster_hist.py [first season] [last season]      # boxes (default 2014-2026)
  python3 scripts/cfb_roster_hist.py --247 [first class] [last class]  # 247 composite classes (default 2011-2026)
Cached in scripts/.cache/cfb/espn_hist/box/<id>.json and scripts/.cache/cfb/r247/<class>.json.
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
    lo, hi = (int(x) for x in (a[:2] if len(a) > 1 else (2014, 2026)))
    for S in range(lo, hi + 1):
        ids = boards(S)
        with ThreadPoolExecutor(16) as ex:
            ok = list(ex.map(pull_game, ids))
        print(S, len(ids), 'FBS games,', sum(ok), 'boxes', flush=True)
