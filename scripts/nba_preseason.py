#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Preseason starts for the player projections' first ten games (scripts/data/nba_preseason.json).

    python3 scripts/nba_preseason.py            # this season, once its preseason is over (skipped when already stored)
    python3 scripts/nba_preseason.py 2019 2027  # seasons from..to (end years)

{season: {team: {espn player id: share of the team's last two preseason games he started}}}, from ESPN's preseason
scoreboard (seasontype 1) and box scores over the 25 days before opening night. nba_players.team_rows reads it as
'ps' (share x e) and 'psb' (share x base minutes x e), e = 1 - games played / 10 (0 from game 11).
Test (scripts/research/sweep_nov19/nba/PREREG.md 7a): minutes in games 1-10, held 2024-26 MAE 4.714 -> 4.676,
t -3.48 clustered by game, 3/3 seasons lower, tune 2021-22 t -1.97. Stdlib only."""
import datetime as dt, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nba_espn as E

OUT = os.path.join(HERE, 'data', 'nba_preseason.json')
SB = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}{x}'
SUM = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={e}'


def opening(S):
    """the season's first regular-season day: the first day on ESPN's calendar with a regular-season game"""
    j = E.get(SB.format(d=f'{S - 1}1101', x='')) or {}
    days = sorted({c[:10] for lg in j.get('leagues', []) for c in lg.get('calendar', []) if isinstance(c, str)})
    for d in days:
        if d < f'{S - 1}-10-01':
            continue
        k = E.get(SB.format(d=d.replace('-', ''), x='&seasontype=2')) or {}
        time.sleep(1.1)
        if any(ev.get('season', {}).get('type') == 2 for ev in k.get('events', [])):
            return dt.date.fromisoformat(d)
    return dt.date(S - 1, 10, 20)


def season(S):
    """{team: {pid: share}} or None when the preseason is not over"""
    first = opening(S)
    if dt.date.today() < first:
        return None
    games = {}
    for k in range(1, 26):
        d = first - dt.timedelta(days=k)
        j = E.get(SB.format(d=d.strftime('%Y%m%d'), x='&seasontype=1')) or {}
        time.sleep(1.1)
        for ev in j.get('events', []):
            if ev.get('season', {}).get('type') != 1:
                continue
            s = E.get(SUM.format(e=ev['id'])) or {}
            time.sleep(1.1)
            for tm in s.get('boxscore', {}).get('players', []):
                t = E.team(tm['team'].get('abbreviation'))
                if not t:
                    continue
                st = [a['athlete']['id'] for x in tm.get('statistics', []) for a in x.get('athletes', []) if a.get('starter') and a.get('athlete', {}).get('id')]
                if st:
                    games.setdefault(t, []).append((ev['date'], st))
    out = {}
    for t, gl in games.items():
        last = sorted(gl)[-2:]
        sh = {}
        for _, st in last:
            for p in st:
                sh[p] = round(sh.get(p, 0.0) + 1.0 / len(last), 3)
        out[t] = sh
    return out


def load():
    try:
        return json.load(open(OUT))
    except (OSError, ValueError):
        return {}


def main():
    a = [int(x) for x in sys.argv[1:3]]
    import nba_xpm
    lo, hi = (a[0], a[1]) if len(a) == 2 else (nba_xpm.current_season(),) * 2
    have = load()
    for S in range(lo, hi + 1):
        if str(S) in have and len(a) != 2:
            continue
        r = season(S)
        if r:
            have[str(S)] = r
            print('nba preseason', S, len(r), 'teams', flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(have, f, separators=(',', ':'), sort_keys=True)


if __name__ == '__main__':
    main()
