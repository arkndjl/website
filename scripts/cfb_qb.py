# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFB QB leaderboard (layouts/shortcodes/cfbqb.html) -> data/cfb_qb.json. Display only, nothing is fit here.

Rows = the board's QBs (static/data/cfb-all.json via scripts/cfb_all.py) with an ESPN id, a WAR line and 50+ pass
attempts this regular season, so every row has every column. From the board: WAA, WAR, FV, school, conference, division, class.
From ESPN's season line (core API athletes/<id>/statistics, the id on the board's ESPN link):
  att, cmp (completion %), ya (yards / attempt), anya = (pass yds + 20 TD - 45 INT - sack yds) / (att + sacks),
  td / int (% of attempts), sk = sacks / (att + sacks), eff (NCAA passer efficiency), ry / rtd (rushing yards, TD, as ESPN
  lists them: college counts sacks as runs), g (games)."""
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import cfb_all  # noqa: E402

UA = {'User-Agent': 'Mozilla/5.0 (arkboard)'}
MIN_ATT = 50


def get(u, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if getattr(e, 'code', None) == 404:
                return None
            time.sleep(1.5 * (k + 1))
    return None


def line(season, aid):
    d = get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/{season}/types/2/athletes/{aid}/statistics')
    if not d:
        return None
    S = {}
    for c in (d.get('splits') or {}).get('categories', []):
        for s in c.get('stats', []):
            S[c['name'] + '.' + s['name']] = s.get('value') or 0.0
    g = lambda k: S.get(k, 0.0)  # noqa: E731
    att, sk = g('passing.passingAttempts'), g('passing.sacks')
    if att < MIN_ATT:
        return None
    yds, td, it, sky = g('passing.passingYards'), g('passing.passingTouchdowns'), g('passing.interceptions'), g('passing.sackYardsLost')
    r1 = lambda x, k=1: round(x, k)  # noqa: E731
    return {'att': int(att), 'cmp': r1(100 * g('passing.completions') / att), 'ya': r1(yds / att),
            'anya': r1((yds + 20 * td - 45 * it - sky) / (att + sk), 2), 'td': r1(100 * td / att), 'int': r1(100 * it / att),
            'sk': r1(100 * sk / (att + sk)), 'eff': r1(g('passing.QBRating')), 'ry': int(g('rushing.rushingYards')),
            'rtd': int(g('rushing.rushingTouchdowns')), 'g': int(g('general.gamesPlayed'))}


def main():
    A = cfb_all.read_cfb_all()
    c = A['cols']
    P = [dict(zip(c, r)) for r in A['rows']]
    season = int(str(A.get('asof') or '')[:4] or 0)
    season = season if (str(A.get('asof') or '')[5:7] or '12') >= '07' else season - 1
    qbs = []
    for p in P:
        m = re.search(r'/id/(\d+)', p.get('espnl') or '')
        if p.get('pos') == 'QB' and m:
            qbs.append((m.group(1), p))
    with ThreadPoolExecutor(8) as ex:
        L = list(ex.map(lambda q: line(season, q[0]), qbs))
    rows = []
    for (aid, p), ln in zip(qbs, L):
        if not ln or p.get('waa') is None:
            continue
        rows.append(dict(ln, n=p['name'], t=p.get('team'), lo=p.get('logo'), conf=p.get('conf'), div=p.get('div') or 'FBS',
                         cls=p.get('cls'), waa=p.get('waa'), war=p.get('war'), fv=p.get('fv'),
                         ph=f'https://a.espncdn.com/combiner/i?img=/i/headshots/college-football/players/full/{aid}.png&w=96&h=70&scale=crop&cquality=60' if p.get('photo') else None))
    rows.sort(key=lambda r: (-(r['waa'] if r['waa'] is not None else -99), -(r['war'] or 0)))
    out = {'season': season, 'asof': A.get('asof'), 'rows': rows}
    with open(os.path.join(ROOT, 'data', 'cfb_qb.json'), 'w') as fh:
        json.dump(out, fh, separators=(',', ':'), allow_nan=False)
    print(f'cfb_qb: {len(rows)} QBs with {MIN_ATT}+ attempts of {len(qbs)} board QBs with an ESPN id')


if __name__ == '__main__':
    main()
