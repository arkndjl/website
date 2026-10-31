#!/usr/bin/env python3
"""Club logos for the hockey prospects boards (Oct 31 2026): junior and minor-league clubs from HockeyTech (OHL, WHL,
QMJHL, USHL, AHL), NCAA schools from the college boards' logos. Logos are copied to static/img/hockey/<client>/<id>.png so
the GFX canvas can draw them (HockeyTech sends no CORS header).

    python3 scripts/hockey_logos.py   -> data/hockey_logos.json {"<league>|<club as the board writes it>": "/img/hockey/..."}

The board's club names are short ("Saginaw", "USDP", "Baie-Comeau"); a club matches a team by its city, nickname or full
name. Clubs in leagues without a source (Europe) are left out and show no logo.
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import faces as F
import names as NM

OUT = os.path.join(ROOT, 'data', 'hockey_logos.json')
IMG = os.path.join(ROOT, 'static', 'img', 'hockey')
ALIAS = {'USDP': 'USA', 'NTDP': 'USA'}      # the US national development program plays in the USHL as Team USA


def teams(client, key):
    base = F.HT % (key, client)
    seasons = ((F.get(base + '&view=seasons') or {}).get('SiteKit') or {}).get('Seasons') or []
    reg = [s for s in seasons if s.get('career') == '1' and s.get('playoff') == '0']
    out = {}
    for s in reg[:2]:           # this season and last (a drafted prospect's club may be last season's)
        for t in ((F.get(base + f"&view=teamsbyseason&season_id={s['season_id']}") or {}).get('SiteKit') or {}).get('Teamsbyseason') or []:
            out.setdefault(t['id'], t)
    return list(out.values())


def save(client, t):
    fn = os.path.join(IMG, client, f"{t['id']}.png")
    if not os.path.exists(fn):
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        try:
            data = urllib.request.urlopen(urllib.request.Request(t['team_logo_url'], headers={'User-Agent': F.UA}), timeout=30).read()
        except Exception as e:
            print('no logo', client, t.get('name'), e)
            return None
        try:        # 96 px is plenty for a 16-20 px cell and the GFX; smooth resize, full colour (logos are not pixelated)
            from io import BytesIO
            from PIL import Image
            im = Image.open(BytesIO(data)).convert('RGBA')
            im.thumbnail((96, 96), Image.LANCZOS)
            im.save(fn, optimize=True)
        except Exception:
            open(fn, 'wb').write(data)
    return f"/img/hockey/{client}/{t['id']}.png"


def main():
    h = json.load(open(os.path.join(ROOT, 'data', 'hockey.json')))
    clubs = {(r.get('league'), r.get('club')) for r in h['board']}       # drafted prospects show their NHL org's logo
    out = {}
    by = {}
    for lg, (client, key) in F.HT_LEAGUE.items():
        if client in {c for c, _ in by.values()}:
            continue        # NTDP plays in the USHL feed
        try:
            by[lg] = (client, teams(client, key))
        except Exception as e:
            print(lg, 'not read:', e)
            continue
        for t in by[lg][1]:     # every club, so the first-year tab (static/data/rookies/hockey.json) has them too
            if t.get('team_logo_url'):
                save(client, t)
    for lg, club in sorted(c for c in clubs if c[0] in F.HT_LEAGUE and c[1]):
        client, ts = by.get(lg) or by['USHL']
        want = NM.key(ALIAS.get(club, re.sub(r'\s*\(.*\)$', '', club)))
        hit = [t for t in ts if want in (NM.key(t.get('city') or ''), NM.key(t.get('nickname') or ''), NM.key(t['name']),
                                         NM.key(' '.join(reversed(t['name'].split(', ')))))]
        hit = hit or [t for t in ts if want and NM.key(t['name']).startswith(want)]
        if len(hit) == 1 and hit[0].get('team_logo_url'):
            p = save(client, hit[0])
            if p:
                out[f'{lg}|{club}'] = p
    # NCAA: the college boards' school logos
    cbb = json.load(open(os.path.join(ROOT, 'static', 'data', 'cbb-all.json')))
    ti, li = cbb['cols'].index('team'), cbb['cols'].index('logo')
    school = {NM.key(r[ti]): r[li] for r in cbb['rows'] if r[ti] and r[li]}
    for lg, club in clubs:
        if lg == 'NCAA' and club and NM.key(club) in school:
            out[f'NCAA|{club}'] = school[NM.key(club)]
    json.dump(dict(sorted(out.items())), open(OUT, 'w'), indent=0, ensure_ascii=False)
    miss = sorted(f'{lg}|{c}' for lg, c in clubs if c and lg in F.HT_LEAGUE and f'{lg}|{c}' not in out)
    print(f'{len(out)} club logos; no match: {miss[:20]}')


if __name__ == '__main__':
    main()
