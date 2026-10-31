#!/usr/bin/env python3
"""Player photos and team logos for tables built from another board's rows (Oct 31 2026): backup watch, ARKLIST and the
like join each row to its sport's main board by name + team (scripts/names.py) and take that board's photo.

    attach(sport, rows, name='name', team='team')   # sets r['photo'] (full URL) and r['logo'] where missing
    python3 scripts/photos.py backup                # data/backup_<sport>.json in place, no refetch

Sources: the same ones the boards draw (scripts/faces.py): NFL nflverse headshot on nfl-war.json, NBA / NHL ESPN ids on
the current nba-xpm / nhl-war season, CFB / CBB ESPN headshots on cfb-all / cbb-all, soccer Transfermarkt portraits on
the current soccer-war season. Logos: static/img/{nfl,nba,nhl}/<abbr>.png, college boards' own, soccer
data/soccer_logos.json.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM

SD = os.path.join(ROOT, 'static', 'data')
ESPN = 'https://a.espncdn.com/combiner/i?img=/i/headshots/{}/players/full/{}.png&w=96&h=70&scale=crop'
NFL = 'https://static.www.nfl.com/image/upload/f_auto,q_auto,w_96/league/{}'
TM = 'https://img.a.transfermarkt.technology/portrait/medium/{}'


def _j(*p):
    return json.load(open(os.path.join(ROOT, *p), encoding='utf-8'))


def _cur(d):
    return max(int(f[:4]) for f in os.listdir(os.path.join(SD, d)) if f[:4].isdigit())


def _cols(d):
    return [dict(zip(d['cols'], r)) for r in d['rows']]


def logo_file(path):
    return path if path and os.path.exists(os.path.join(ROOT, 'static', path.lstrip('/'))) else None


def soccer_logo(club):
    L = _j('data', 'soccer_logos.json')
    e = L.get('espn', {}).get(club or '')
    if e:
        return logo_file(f'/img/soccer/{e}.png')
    t = L.get('tm', {}).get(club or '')
    return logo_file(f'/img/soccer/tm/{t}.png') if t else None


def cfb_photo(r):
    # cfb-all.json writes 1 for ESPN's standard headshot of the player's ESPN id (espnl), as assets/js/cfb.js rebuilds it
    p = r.get('photo')
    if p == 1:
        m = re.search(r'/id/(\d+)', r.get('espnl') or '')
        return f'https://a.espncdn.com/i/headshots/college-football/players/full/{m.group(1)}.png' if m else None
    return p or None


_M = {}


def board(sport):
    """(Matcher over the sport's board, photo(row), logo(team, row))"""
    if sport in _M:
        return _M[sport]
    if sport == 'nfl':
        P = _j('static', 'data', 'nfl-war.json')['players']
        out = (NM.Matcher(P, name='n', team='t', pos=None), lambda p: NFL.format(p['ph']) if p.get('ph') else None,
               lambda t, p: logo_file(f'/img/nfl/{str(t).split("/")[-1].lower()}.png'))
    elif sport in ('nba', 'nhl'):
        d = 'nba-xpm' if sport == 'nba' else 'nhl-war'
        P = _j('static', 'data', d, f'{_cur(d)}.json')['players']
        out = (NM.Matcher(P, name='n', team='tm', pos=None, sport='basketball' if sport == 'nba' else 'hockey'),
               lambda p, s=sport: ESPN.format(s, p['ph']) if p.get('ph') else None,
               lambda t, p, s=sport: logo_file(f'/img/{s}/{str(t).lower()}.png'))
    elif sport in ('cfb', 'cbb'):
        P = _cols(_j('static', 'data', f'{sport}-all.json'))
        out = (NM.Matcher(P, pos=None, sport='football' if sport == 'cfb' else 'basketball'),
               cfb_photo, lambda t, p: (p or {}).get('logo'))
    elif sport == 'soccer':
        P = _j('static', 'data', 'soccer-war', f'{_cur("soccer-war")}.json')['players']
        out = (NM.Matcher(P, name='n', team='team', pos=None, sport='soccer'), lambda p: TM.format(p['ph']) if p.get('ph') else None,
               lambda t, p: soccer_logo(t))
    else:
        raise ValueError(sport)
    _M[sport] = out
    return out


def attach(sport, rows, name='name', team='team'):
    """photo + logo onto rows from the sport's board; returns how many have a photo"""
    M, ph, lo = board(sport)
    for r in rows:
        p, _ = M.find(r[name], team=r.get(team))
        if not r.get('photo') and p:
            r['photo'] = ph(p)
        if not r.get('logo'):
            r['logo'] = lo(r.get(team), p)
    return sum(1 for r in rows if r.get('photo'))


def backup(sports=('nfl', 'nba', 'nhl', 'cbb', 'soccer')):
    for s in sports:
        fn = os.path.join(ROOT, 'data', f'backup_{s}.json')
        d = json.load(open(fn))
        n = attach(s, d['rows'])
        json.dump(d, open(fn, 'w'), indent=0 if s == 'soccer' else 1, allow_nan=False)
        print(f'backup watch {s}: {n} of {len(d["rows"])} with a photo')


if __name__ == '__main__':
    if sys.argv[1:2] == ['backup']:
        backup(tuple(sys.argv[2:]) or ('nfl', 'nba', 'nhl', 'cbb', 'soccer'))
