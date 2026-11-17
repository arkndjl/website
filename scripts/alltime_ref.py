#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Writes the Reference (Glossary/Methodology) entry for the all-time team and player rankings into research/library.json
from data/alltime.json, then rerun scripts/library_build.py.

    python3 scripts/alltime.py && python3 scripts/alltime_ref.py && python3 scripts/library_build.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERM = 'All-time teams and players'
NAME = {'cfb': 'CFB', 'nfl': 'NFL', 'cbb': 'CBB', 'nba': 'NBA', 'nhl': 'NHL', 'soccer': 'soccer', 'cs2': 'CS2', 'atp': 'ATP', 'wta': 'WTA'}


def main():
    d = json.load(open(os.path.join(ROOT, 'data', 'alltime.json')))
    T = {k: d[k]['teams'] for k in NAME if 'teams' in d.get(k, {})}
    P = {k: d[k]['players'] for k in NAME if 'players' in d.get(k, {})}
    span = lambda x: f"{x['from']}-{x['to']}"
    chk = '; '.join(f"{NAME[k]} {t['teams_check'][0]:.3f} vs {t['teams_check'][1]:.3f}" for k, t in T.items() if 'teams_check' in t)
    pchk = '; '.join(f"{NAME[k]} {p['peak_check'][0]:.3f}" + (f" vs {p['peak_check'][1]:.3f}" if p['peak_check'][1] != p['peak_check'][0] else '') for k, p in P.items())
    e = dict(term=TERM,
             short='Best team-seasons (overall, offense, defense) and best player seasons and careers in each sport, each season measured against its own league. One sport at a time: no cross-sport scale.',
             body=[
                 'Rtg+ / Off+ / Def+ = 100 + 25 z (the Stat+ scale): z = (rating - that season\'s league mean) / SD, the SD pooled over the season and the two either side (ratings demeaned by season). 100 = an average team that season; 125 = one SD better; 175 = three.',
                 'Why z and not raw points: scoring levels and the spread between the best and worst teams change by era (fewer, deeper leagues; 1900s college blowouts; dead-ball hockey). Dominance over the league you played in is the comparable quantity; the raw rating is shown beside it.',
                 f"Team ratings: CFB ridge SRS on every major-college game (margin capped at 35, home edge, offense / defense the same ridge on capped points; jhowell.net scores {span(T['cfb'])}); NFL the same ridge on every NFL, AFL and AAFC game including playoffs (FiveThirtyEight scores to 1998, nflverse from 1999; {span(T['nfl'])}); CBB Sports Reference SRS / OSRS / DSRS ({span(T['cbb'])}); NBA Basketball Reference SRS, ORtg and DRtg against the league average ({span(T['nba'])}; off / def from 1951-52); NHL Hockey Reference SRS, goals for / against a game against the league + half the SOS ({span(T['nhl'])}, no 2004-05); soccer big-five clubs, goals a match vs the big-five average at season end ({span(T['soccer'])}); CS2 best Valve VRS points in a calendar year, each snapshot's top 50 as the league ({span(T['cs2'])}).",
                 'Lists: the top 250 plus the top 25 of every decade, so the Era filter shows each decade\'s best. CH = champion (CFB national title share, NFL league / Super Bowl winner).',
                 f'Era check: share of the top 100 by decade against the decade\'s share of all team-seasons, KL divergence (0 = every decade represented by its size), era-adjusted vs raw: {chk}.',
                 'Players: peak = best single season, career = sum of seasons, each season valued over replacement in its own league and scaled to a full season where seasons were short.',
                 f"NBA: VORP per 82 games (Basketball Reference; (BPM + 2) x share of team minutes); before 1973-74 BPM is estimated from WS/48 and PER (fit on 1974-85 players with 500+ minutes, r {d['nba']['players'].get('fit_r', 0.90):.2f}; tagged est); minutes start 1951-52. NHL: point shares per 82 games (Hockey Reference; skaters OPS + DPS, goalies GPS). CBB: the site's CBB WAR on every Barttorvik season from 2007-08. NFL: peak = the site's AV WAR (rebuilt AV, no special teams) from 2012 (snap counts); career = Pro Football Reference weighted career AV (nflverse draft_picks; drafted players 1980 on). Soccer: the site's GAR, big-five seasons from 2014-15.",
                 'Tennis: Elo on every tour-level singles match 1968 on (Sackmann archive; K = 250 / (matches + 5)^0.4, Slams x 1.1). Elo+ = 100 + 25 x (peak Elo that year - the year\'s #20 year-end Elo) / SD of the year\'s top 100; peak counts after 40 career matches. Career = sum over years (20+ matches) of the year-end Elo over the #20 line in those SDs.',
                 'NBA and NHL seasons are put in today\'s units: (value - the season\'s regular mean) / its SD (regulars: half the games, NBA 12+ minutes a game; SD pooled over the season and two either side), times the 2011-12 to 2025-26 SD plus that mean. Without it, 1920s hockey (24-game seasons, 60-minute stars) and early-NBA heavy minutes fill the peak list.',
                 f'Player era check (peak list, KL as above, adjusted vs as played): {pchk}.',
                 'Not ranked: CFB players (no season value on file before 2014), CS2 players (no rating history before the current board). Display only; no model reads these lists.',
             ],
             where='all-time tab (teams group: all-time teams, offenses, defenses) and all-time players tab (players group: peak seasons, careers) on the CFB, CBB, NFL, NBA, NHL and soccer pages; tennis all-time (ATP / WTA peaks and careers); CS2 all-time teams',
             sports=['CFB', 'CBB', 'NFL', 'NBA', 'NHL', 'Soccer', 'Tennis', 'CS2'])
    p = os.path.join(ROOT, 'research', 'library.json'); lib = json.load(open(p))
    sec = next(s for s in lib['sections'] if s['id'] == 'teams')
    sec['entries'] = [x for x in sec['entries'] if x['term'] != TERM] + [e]
    json.dump(lib, open(p, 'w'), ensure_ascii=False, indent=1)
    print('ref entry written')


if __name__ == '__main__':
    main()
