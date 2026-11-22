#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Injury tags on every ARKBOARD player board: one file, static/data/injuries.json, read in the browser by
layouts/partials/injtags.html, which puts a pixel tag (Q, D, O, OFS, IR, DTD, PUP, SUSP) after each listed player's name.

    python3 scripts/injury_tags.py          # odds-snap.yml reruns it every half hour

Display only: the same statuses the game models already price, nothing refit. Sources, best first per sport:
  nfl     data/nfl_injuries.json (league report, ESPN, RotoWire, inactives: the game model's week-scoped statuses)
  nba     data/nba_games.json inj (the official NBA report on the coming slate), then ESPN chart tags, then RotoWire news
  nhl     data/nhl_games.json inj (ESPN), then ESPN chart tags, then RotoWire news
  cfb     data/cfb_injuries.json (availability reports, ESPN, RotoWire; a weekly status lapses after 9 days, season-out stays)
  cbb     data/cbb_injuries.json (Covers), then RotoWire news
  soccer  RotoWire soccer news (scripts/data/rotowire_news.json), newest item per player in the last 10 days
Tennis and CS2 have no injury feed. Probable and Active are not tagged.

Out: {asof, <sport>: {name key (scripts/names.py): [[code, hover title, team logo, team name], ...]}}, plus
<sport>_amb: the name keys two clubs share on the depth charts (static/data/depth/<sport>.json), which the browser tags
only on a row that shows the player's club (its logo or name)."""
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as NM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'static', 'data', 'injuries.json')
NOW = dt.datetime.now(dt.timezone.utc)
LAPSE = 9           # days a weekly CFB status holds without a newer report (the CFB build's lapse)
NEWS_DAYS = 10
ABBR = {'WSH': 'WAS', 'NY': 'NYK', 'SA': 'SAS', 'UTAH': 'UTA', 'PHO': 'PHX', 'NO': 'NOP', 'GS': 'GSW', 'NJ': 'NJD', 'LA': 'LAK',
        'SJ': 'SJS', 'TB': 'TBL', 'WAS': 'WSH', 'CHA': 'CHO', 'BKN': 'BRK', 'PHX': 'PHO', 'UTA': 'UTAH'}      # days a RotoWire news status holds where no report covers the club


def load(*p):
    try:
        with open(os.path.join(ROOT, *p)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def code(status):
    """(tag, hover title) for a status string from any feed; None = not tagged (active, probable, unknown)"""
    s = (status or '').strip()
    t = s.lower()
    if not t or t.startswith(('active', 'probable')):
        return None
    if 'season' in t:
        return 'OFS', 'out for season'
    if 'injured reserve' in t or t == 'ir':
        return 'IR', 'injured reserve'
    if 'physically unable' in t or t == 'pup':
        return 'PUP', 'physically unable to perform'
    if 'non-football' in t or t == 'nfi':
        return 'NFI', 'non-football injury'
    if 'susp' in t:
        return 'SUSP', 'suspended'
    if 'day-to-day' in t or t in ('dd', 'dtd', 'gtd'):
        return 'DTD', 'day-to-day'
    q = re.search(r'\((last week|in game)\)', t)
    q = ' (' + q.group(1) + ')' if q else ''
    if t.startswith('doubtful') or t == 'd':
        return 'D', 'doubtful' + q
    if t.startswith('questionable') or t == 'q':
        return 'Q', 'questionable' + q
    if t.startswith('out') or t == 'o':
        return 'O', 'out' + q
    return None


def depth(sport):
    """(teams by abbreviation, teams by logo, teams by name key, {name key: set(team)}, [(name, team, chart tag)])"""
    d = load('static', 'data', 'depth', f'{sport}.json') or {}
    T = d.get('teams') or []
    T = list(T.values()) if isinstance(T, dict) else T
    by_t, by_logo, by_key, who, tags = {}, {}, {}, defaultdict(set), []
    for t in T:
        by_t[t['t']] = t
        if t.get('logo'):
            by_logo[t['logo']] = t
        by_key[NM.team_key(t.get('n') or t['t'])] = t
        by_key.setdefault(NM.team_key(t['t']), t)
        for u in t.get('units') or []:
            for _, pl in u.get('s') or []:
                for p in pl:
                    if not p or not p[0]:
                        continue
                    who[NM.key(p[0])].add(t['t'])
                    if len(p) > 3 and p[3]:
                        tags.append((p[0], t, p[3]))
    return by_t, by_logo, by_key, who, tags


class Board:
    def __init__(self, sport):
        self.sport = sport
        self.by_t, self.by_logo, self.by_key, self.who, self.tags = depth(sport)
        self.rows = {}           # (name key, team) -> entry; the first source to list a player wins

    def team(self, abbr=None, logo=None, name=None):
        if abbr and abbr not in self.by_t:      # ESPN's short codes (NO, GS, WSH, NJ, TB...) against the charts' (NOP, GSW, WAS...)
            abbr = ABBR.get(abbr, abbr)
            if abbr not in self.by_t:
                c = [t for t in self.by_t if t.startswith(abbr)]
                abbr = c[0] if len(c) == 1 else abbr
        return (self.by_t.get(abbr) if abbr else None) or (self.by_logo.get(logo) if logo else None) or \
               (self.by_key.get(NM.team_key(name)) if name else None)

    def add(self, name, status, team=None, detail=None, logo=None, tname=None):
        if not name:
            return
        k = NM.key(name)
        tk = team['t'] if team else NM.team_key(tname or '')
        if (k, tk) in self.rows:      # a better source already spoke (an Active or Probable there holds too)
            return
        c = code(status)
        if not c:
            self.rows[(k, tk)] = None
            return
        title = c[1] + (' · ' + detail.lower() if detail and detail.lower() not in c[1] and detail.lower() != 'undisclosed' else '')
        self.rows[(k, tk)] = [c[0], title, (team or {}).get('logo') or logo or '', (team or {}).get('n') or tname or '']

    def out(self):
        o = defaultdict(list)
        for (k, _), v in self.rows.items():
            if v:
                o[k].append(v)
        amb = sorted(k for k in o if len(self.who.get(k, ())) > 1 or len(o[k]) > 1)
        return dict(sorted(o.items())), amb


def news(sport_rw, board, days=NEWS_DAYS):
    """newest RotoWire item per player in the last days, by its status reader (scripts/rotowire.py)"""
    import rotowire as RW
    d = load('scripts', 'data', 'rotowire_news.json') or {}
    cut = NOW.timestamp() - days * 86400
    best = {}
    for it in (d.get('items') or {}).values():
        if it.get('sport') != sport_rw or (it.get('ts') or it.get('seen') or 0) < cut:
            continue
        k = (NM.key(it.get('player')), NM.team_key(it.get('team')))
        if k not in best or (it.get('ts') or 0) > (best[k].get('ts') or 0):
            best[k] = it
    for it in best.values():
        st = RW.item_status(it)
        inj = it.get('inj') if it.get('inj') and it.get('inj') not in ('GTD', 'Undisclosed') else None
        t = board.team(abbr=it.get('abbr'), name=it.get('team'))
        board.add(it.get('player'), st, t, inj, tname=it.get('team'))


def nfl():
    b = Board('nfl')
    d = load('data', 'nfl_injuries.json') or {}
    nm = d.get('names') or {}
    for tm, ps in (d.get('teams') or {}).items():
        for pid, (st, _src) in ps.items():
            b.add(nm.get(pid), st, b.team(abbr=tm), logo=f'/img/nfl/{tm.lower()}.png')
    return b


def games(sport, rw):
    b = Board(sport)
    g = load('data', f'{sport}_games.json') or {}
    for x in sorted(g.get('games') or [], key=lambda x: (bool(x.get('final')), str(x.get('tip') or x.get('day') or ''))):
        for side in ('home', 'away'):
            tm = x.get(side)
            t = b.team(abbr=tm)
            for p in ((x.get('inj') or {}).get(side) or []):
                b.add(p.get('name'), p.get('status'), t, logo=f'/img/{sport}/{str(tm).lower()}.png')
    for name, t, tag in b.tags:
        b.add(name, tag, t)
    news(rw, b)
    return b


def cfb():
    b = Board('cfb')
    d = load('data', 'cfb_injuries.json') or {}
    for p in (d.get('players') or {}).values():
        st = p.get('status') or ''
        try:
            age = (NOW - dt.datetime.fromisoformat(p['date'].replace('Z', '+00:00'))).days
        except (KeyError, ValueError, TypeError):
            age = 0
        if 'season' not in st.lower() and age > LAPSE:
            continue
        m = re.search(r'\(([a-z][a-z \-]+)\)', p.get('note') or '')
        logo = f"/img/cfb/logos/{p.get('tid')}.png" if p.get('tid') else ''
        b.add(p.get('name'), st, b.team(logo=logo), m.group(1) if m and m.group(1) != 'undisclosed' else None, logo=logo)
    return b


def cbb():
    b = Board('cbb')
    d = load('data', 'cbb_injuries.json') or {}
    for p in d.get('players') or []:
        b.add(p.get('name'), p.get('status'), b.team(name=p.get('team')), p.get('detail'), tname=p.get('team'))
    news('cbasketball', b)
    return b


def soccer():
    b = Board('soccer')
    news('soccer', b)
    return b


def main():
    o = {'asof': NOW.strftime('%Y-%m-%dT%H:%MZ')}
    for sport, f in (('nfl', nfl), ('nba', lambda: games('nba', 'basketball')), ('nhl', lambda: games('nhl', 'hockey')),
                     ('cfb', cfb), ('cbb', cbb), ('soccer', soccer)):
        try:
            rows, amb = f().out()
        except Exception as e:  # noqa: BLE001  (one feed failing keeps the others' tags)
            print(f'{sport}: skipped ({e})', flush=True)
            old = load('static', 'data', 'injuries.json') or {}
            rows, amb = old.get(sport) or {}, old.get(sport + '_amb') or []
        o[sport], o[sport + '_amb'] = rows, amb
        n = defaultdict(int)
        for v in rows.values():
            for e in v:
                n[e[0]] += 1
        print(f'{sport}: {sum(n.values())} tagged {dict(sorted(n.items()))}, {len(amb)} shared names', flush=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(o, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(tmp, OUT)


if __name__ == '__main__':
    main()
