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
NAME = {'cfb': 'CFB', 'nfl': 'NFL', 'cbb': 'CBB', 'nba': 'NBA', 'nhl': 'NHL', 'hkp': 'hockey prospects', 'soccer': 'soccer', 'cs2': 'CS2', 'atp': 'ATP', 'wta': 'WTA'}


def main():
    d = json.load(open(os.path.join(ROOT, 'data', 'alltime.json')))
    T = {k: d[k]['teams'] for k in NAME if 'teams' in d.get(k, {})}
    P = {k: d[k]['players'] for k in NAME if 'players' in d.get(k, {})}
    span = lambda x: f"{x['from']}-{x['to']}"
    chk = '; '.join(f"{NAME[k]} {t['teams_check'][0]:.3f} vs {t['teams_check'][1]:.3f}" for k, t in T.items() if 'teams_check' in t)
    pchk = '; '.join(f"{NAME[k]} {p['peak_check'][0]:.3f}" + (f" vs {p['peak_check'][1]:.3f}" if p['peak_check'][1] != p['peak_check'][0] else '') for k, p in P.items() if p.get('peak_check'))
    e = dict(term=TERM,
             short='Best team-seasons (overall, offense, defense) and best player seasons and careers in each sport, each season measured against its own league. One sport at a time: no cross-sport scale.',
             body=[
                 'Rtg+ / Off+ / Def+ = 100 + 25 z (the Stat+ scale): z = (rating - that season\'s league mean) / SD, the SD pooled over the season and the two either side (ratings demeaned by season). 100 = an average team that season; 125 = one SD better; 175 = three.',
                 'Why z and not raw points: scoring levels and the spread between the best and worst teams change by era (fewer, deeper leagues; 1900s college blowouts; dead-ball hockey). Dominance over the league you played in is the comparable quantity; the raw rating is shown beside it.',
                 f"Team ratings: CFB ridge SRS on every major-college game (margin capped at 35, home edge, offense / defense the same ridge on capped points; jhowell.net scores {span(T['cfb'])}); NFL the same ridge on every NFL, AFL and AAFC game including playoffs (FiveThirtyEight scores to 1998, nflverse from 1999; {span(T['nfl'])}); CBB Sports Reference SRS / OSRS / DSRS ({span(T['cbb'])}); NBA Basketball Reference SRS, ORtg and DRtg against the league average ({span(T['nba'])}; off / def from 1951-52); NHL Hockey Reference SRS, goals for / against a game against the league + half the SOS ({span(T['nhl'])}, no 2004-05); soccer big-five clubs, goals a match vs the big-five average at season end ({span(T['soccer'])}); CS2 best Valve VRS points in a calendar year, each snapshot's top 50 as the league ({span(T['cs2'])}).",
                 'Lists: the top 250 plus the top 25 of every decade, so the Era filter shows each decade\'s best. CH = champion (CFB national title share, NFL league / Super Bowl winner).',
                 f'Era check: share of the top 100 by decade against the decade\'s share of all team-seasons, KL divergence (0 = every decade represented by its size), era-adjusted vs raw: {chk}.',
                 'Players: peak seasons = every player-season ranked on its own (one player can hold several rows), career = sum of seasons, each season valued over replacement in its own league and scaled to a full season where seasons were short.',
                 f"NBA: VORX per 82 games (XPM: DPM + BPM blend from 2009-10, BPM before); before 1973-74 BPM is estimated from WS/48 and PER (fit on 1974-85 players with 500+ minutes, r {d['nba']['players'].get('fit_r', 0.90):.2f}; tagged est); minutes start 1951-52. NHL: point shares per 82 games (Hockey Reference; skaters OPS + DPS, goalies GPS). CBB: the site's CBB WAR on every Barttorvik season from 2007-08. NFL: peak = the site's AV WAR (rebuilt AV, no special teams) from 2012 (snap counts); career = Pro Football Reference weighted career AV (nflverse draft_picks; drafted players 1980 on). Soccer: the site's GAR, big-five seasons from 2014-15.",
                 'Tennis: Elo on every tour-level singles match 1968 on (Sackmann archive; K = 250 / (matches + 5)^0.4, Slams x 1.1). Elo+ = 100 + 25 x (peak Elo that year - the year\'s #20 year-end Elo) / SD of the year\'s top 100; peak counts after 40 career matches. Career = sum over years (20+ matches) of the year-end Elo over the #20 line in those SDs.',
                 'Era adjustment (rate + volume, Nov 20 2026): a season\'s rate is set against that season\'s regulars, rate\' = mean_ref + SD_ref x (rate - season mean) / season SD (SD pooled over the season and two either side), and its volume against that season\'s load, vol\' = vol x q_ref / q_season (q = 90th percentile of the regulars\' volume); the sport\'s own value formula then runs on rate\' and vol\'. _ref = the mean over the last 10 seasons, so values read in today\'s units. Unadj = as played.',
                 'Per sport. NBA: rate XPM, volume minutes per 82 team games, VORX = .030 x (XPM\' + 1.4) x min\' / 48 (BPM is per 100 possessions, so pace and the 3-point era are in the rate; the volume term takes out 45-minute 1960s loads). NHL: WAR per 82 against the season, skaters and goalies apart (no ice time before 2008-09, so no volume term). CBB: rate BPM (regulars 400+ min), volume minutes (short 2020-21 season scaled up). Soccer: rate GAR per 90 (regulars 900+ min), volume minutes. CS2: calendar years 2024 on, rate RWA over that year\'s replacement (median of 1,000+ round players; opponents at their year-end ratings), volume rounds (current year to date scaled to a full year), RAR = RWA\' x rounds\' / 100. Hockey prospects: drafted skaters\' seasons outside the NHL (20+ games, ages 16-21), NHLe+ = 100 + 25 z of log(NHLe + 5) against drafted skaters of the same age and position that season. Tennis: Elo against the year\'s #20 in SDs of the year\'s top 100 is already a rate against the season; no volume term (peak Elo).',
                 f'Player era check (peak list, KL as above, adjusted vs as played): {pchk}.',
                 'Display only; no model reads these lists.',
             ],
             where='all-time tab (teams group: all-time teams, offenses, defenses) and all-time players tab (players group: peak seasons, careers) on the CFB, CBB, NFL, NBA, NHL and soccer pages; tennis all-time (ATP / WTA peaks and careers); CS2 all-time teams + all-time players; hockey prospects peak seasons',
             sports=['CFB', 'CBB', 'NFL', 'NBA', 'NHL', 'Soccer', 'Tennis', 'CS2'])
    p = os.path.join(ROOT, 'research', 'library.json'); lib = json.load(open(p))
    sec = next(s for s in lib['sections'] if s['id'] == 'teams')
    sec['entries'] = [x for x in sec['entries'] if x['term'] != TERM] + [e]
    json.dump(lib, open(p, 'w'), ensure_ascii=False, indent=1)
    print('ref entry written')


if __name__ == '__main__':
    main()
