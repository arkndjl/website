#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""FIBA youth leaders for the CBB international board (scripts/data/cbb_fiba_youth.json, read by cbb_recruit_fit.py).

FIBA's site turns away scripted clients, so the pages are read one at a time with a fetch tool (the yearly refresh
task does this after the summer events) and this script keeps the books:

    python3 scripts/cbb_fiba_youth.py events 2027         # the stats-page URLs to read for that summer
    python3 scripts/cbb_fiba_youth.py lines KEY FILE      # store an event leaderboard: lines name,CODE,gp,mpg,ppg,pid
    python3 scripts/cbb_fiba_youth.py need                # player pages still needed (birth date, height, club)
    python3 scripts/cbb_fiba_youth.py page 'pid|name|YYYY-MM-DD|cm|position|club'   # store one player page
    python3 scripts/cbb_fiba_youth.py build               # rebuild "players" from the last two summers' events
    python3 scripts/cbb_fiba_youth.py stale               # exit 1 when the newest event is from before last summer

KEY is the event key events prints (u18eb27 ...). A stats page is the top 50 scorers among players in more than half
the games. Players kept: not USA, best points per game x event weight >= keep, not already on the CBB board, the
internationals list or an On3 class (cbb_recruit_fit.py checks again on every run)."""
import datetime as dt
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, 'scripts', 'data', 'cbb_fiba_youth.json')
BASE = 'https://www.fiba.basketball/en/events/'
# (key stem, name, slug, weight, years: 0 even, 1 odd)
EVENTS = [('u17wc', 'FIBA U17 World Cup', 'fiba-u17-basketball-world-cup-{y}', 1.0, 0),
          ('u19wc', 'FIBA U19 World Cup', 'fiba-u19-basketball-world-cup-{y}', 1.0, 1),
          ('u18eb', 'FIBA U18 EuroBasket', 'fiba-u18-eurobasket-{y}', 1.0, None),
          ('u16eb', 'FIBA U16 EuroBasket', 'fiba-u16-eurobasket-{y}', .8, None),
          ('u18ac', 'FIBA U18 AmeriCup', 'fiba-u18-americup-{y}', .85, 0),
          ('u16ac', 'FIBA U16 AmeriCup', 'fiba-u16-americup-{y}', .7, 1),
          ('u18afro', 'FIBA U18 AfroBasket', 'fiba-u18-afrobasket-{y}', .7, 0),
          ('u16afro', 'FIBA U16 AfroBasket', 'fiba-u16-afrobasket-{y}', .6, 1),
          ('u18asia', 'FIBA U18 Asia Cup', 'fiba-u18-asia-cup-{y}', .6, 0),
          ('u16asia', 'FIBA U16 Asia Cup', 'fiba-u16-asia-cup-{y}', .5, 1)]
POS = {'Point Guard': 'PG', 'Shooting Guard': 'SG', 'Guard': 'G', 'Small Forward': 'SF', 'Power Forward': 'PF',
       'Forward': 'F', 'Center': 'C', 'Forward/Center': 'PF', 'Guard/Forward': 'G'}
TEAM = {'NZL': 'new-zealand', 'PUR': 'puerto-rico', 'CIV': 'cote-divoire', 'DOM': 'dominican-republic', 'TPE': 'chinese-taipei',
        'TUR': 'turkiye', 'SRB': 'serbia', 'JPN': 'japan', 'SLO': 'slovenia', 'FRA': 'france', 'CAN': 'canada', 'AUS': 'australia',
        'LTU': 'lithuania', 'CHN': 'china', 'ITA': 'italy', 'CMR': 'cameroon', 'VEN': 'venezuela', 'ISR': 'israel', 'SVK': 'slovakia',
        'GRE': 'greece', 'DEN': 'denmark', 'ESP': 'spain', 'BUL': 'bulgaria', 'GER': 'germany', 'AUT': 'austria', 'EST': 'estonia',
        'LAT': 'latvia', 'BEL': 'belgium', 'ROU': 'romania', 'CZE': 'czechia', 'POL': 'poland', 'GEO': 'georgia', 'MEX': 'mexico',
        'BRA': 'brazil', 'ARG': 'argentina', 'MAD': 'madagascar', 'MAR': 'morocco', 'CHA': 'chad', 'GAB': 'gabon', 'NGR': 'nigeria',
        'RWA': 'rwanda', 'EGY': 'egypt', 'TUN': 'tunisia', 'MLI': 'mali', 'SEN': 'senegal', 'QAT': 'qatar', 'BRN': 'bahrain',
        'KOR': 'korea', 'IRI': 'iran', 'IND': 'india', 'SYR': 'syria', 'PHI': 'philippines', 'FIN': 'finland', 'SUI': 'switzerland',
        'CRO': 'croatia', 'MNE': 'montenegro', 'BIH': 'bosnia-and-herzegovina', 'NED': 'netherlands', 'POR': 'portugal',
        'ISL': 'iceland', 'SWE': 'sweden', 'UKR': 'ukraine', 'HUN': 'hungary', 'MKD': 'north-macedonia', 'GBR': 'great-britain',
        'ANG': 'angola', 'RSA': 'south-africa', 'COL': 'colombia', 'CHI': 'chile', 'URU': 'uruguay', 'PAN': 'panama', 'LBN': 'lebanon',
        'JOR': 'jordan', 'KSA': 'saudi-arabia', 'INA': 'indonesia', 'THA': 'thailand', 'KAZ': 'kazakhstan', 'GUI': 'guinea',
        'COD': 'dr-congo', 'UGA': 'uganda', 'KEN': 'kenya', 'CPV': 'cape-verde', 'NOR': 'norway', 'IRL': 'ireland', 'LUX': 'luxembourg'}


def load(): return json.load(open(F, encoding='utf-8'))


def save(d):
    with open(F, 'w', encoding='utf-8') as f: json.dump(d, f, indent=0, ensure_ascii=False)


def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def events(y):
    out = {}
    for k, n, s, w, par in EVENTS:
        if par is None or y % 2 == par:
            out[f'{k}{y % 100:02d}'] = {'name': n, 'year': y, 'url': BASE + s.format(y=y), 'w': w}
    return out


def known():
    seen = set()
    for f in ('cbb-all.json', 'cbb-intl.json'):
        try:
            b = json.load(open(os.path.join(ROOT, 'static', 'data', f)))
            i = b['cols'].index('name')
            seen |= {N.key(r[i]) for r in b['rows']} | {N.key(n) for n in (b.get('overseas') or {})}
        except (OSError, ValueError):
            pass
    try:
        rc = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json')))
        seen |= {N.key(r['name']) for c in rc['classes'] for r in c['list']}
    except (OSError, ValueError):
        pass
    return seen


def pool(d):
    """pid -> name, code, event lines, score (best ppg x weight), over the last two summers' stored events"""
    last = max(e['year'] for e in d['events'].values()) if d['events'] else 0
    out = {}
    for k, rows in d.get('lines', {}).items():
        e = d['events'][k]
        if e['year'] < last - 1: continue
        for name, code, gp, mpg, ppg, pid in rows:
            if code == 'USA': continue
            p = out.setdefault(str(pid), {'name': name, 'code': code, 'ev': [], 's': 0.0})
            p['ev'].append([k, int(gp), float(mpg), float(ppg)])
            p['s'] = max(p['s'], float(ppg) * e['w'])
    return out


def keepers(d):
    seen = known()
    return {pid: p for pid, p in pool(d).items() if p['s'] >= d['keep'] and N.key(p['name']) not in seen
            and pid not in (d.get('skip') or [])}


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else ''
    if cmd == 'events':
        for k, e in events(int(a[1])).items(): print(k, e['url'] + '/stats')
        return
    d = load()
    if cmd == 'lines':
        k = a[1]
        y = int('20' + k[-2:])
        d['events'].setdefault(k, events(y)[k])
        rows = []
        for ln in open(a[2], encoding='utf-8'):
            x = [s.strip() for s in ln.strip().split(',')]
            if len(x) == 6 and x[5].isdigit(): rows.append(x)
        d.setdefault('lines', {})[k] = rows
        save(d); print(k, len(rows), 'lines')
    elif cmd == 'need':
        pg = d.get('pages', {})
        for pid, p in keepers(d).items():
            if pid in pg: continue
            k = max(p['ev'], key=lambda e: e[3] * d['events'][e[0]]['w'])[0]
            team = TEAM.get(p['code'], slug(p['code']))
            print(f"{d['events'][k]['url']}/teams/{team}/{pid}-{slug(p['name'])}")
    elif cmd == 'page':
        pid, name, dob, cm, pos, club = (a[1].split('|') + [''] * 6)[:6]
        d.setdefault('pages', {})[pid] = {'dob': dob if re.match(r'\d{4}-\d\d-\d\d$', dob) else None, 'cm': int(cm) if cm.isdigit() else None,
                                          'pos': POS.get(pos, pos) or None, 'club': None if club in ('', 'Free Agent') else club}
        save(d)
    elif cmd == 'build':
        pg = d.get('pages', {})
        out = []
        for pid, p in keepers(d).items():
            q = pg.get(pid, {})
            out.append({'pid': int(pid), 'name': p['name'], 'nat': p['code'], 'dob': q.get('dob'), 'cm': q.get('cm'), 'pos': q.get('pos'),
                        'club': q.get('club'), 's': round(p['s'], 1),
                        'ev': sorted(p['ev'], key=lambda e: (-d['events'][e[0]]['year'], -e[3]))})
        for x in out:
            if str(x['pid']) in (d.get('pin') or {}): x.update(d['pin'][str(x['pid'])])
        d['players'] = sorted(out, key=lambda x: x['name'])
        d['asof'] = dt.date.today().isoformat()
        save(d); print(len(out), 'players,', sum(1 for x in out if not x['dob']), 'without a birth date')
    elif cmd == 'stale':
        last = max(e['year'] for e in d['events'].values())
        t = dt.date.today()
        due = t.year if t >= dt.date(t.year, 10, 1) else t.year - 1    # last summer's events, counted from October
        print('newest event', last, 'due', due)
        sys.exit(1 if last < due else 0)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
