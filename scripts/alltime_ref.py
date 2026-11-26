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
    ln = lambda c: f" (line {c[2]:.3f})" if len(c) > 2 and c[2] else ''
    chk = '; '.join(f"{NAME[k]} {t[g + '_check'][0]:.3f} vs {t[g + '_check'][1]:.3f}{ln(t[g + '_check'])}" + ('' if g == 'teams' else f' {g}')
                    for k, t in T.items() for g in ('teams', 'offense', 'defense') if g + '_check' in t)
    P.update({'cfbqb': d['cfb']['qbs'], 'nflqb': d['nfl']['qbs']} if 'qbs' in d.get('cfb', {}) else {})
    NAME.update(cfb='CFB RB / WR / TE', cfbqb='CFB QBs', nflqb='NFL QBs')
    pchk = '; '.join(f"{NAME[k]} {p['peak_check'][0]:.3f}" + (f" vs {p['peak_check'][1]:.3f}" if p['peak_check'][1] != p['peak_check'][0] else '') + ln(p['peak_check'])
                     for k, p in P.items() if p.get('peak_check'))
    e = dict(term=TERM,
             short='The best team-seasons (overall, offense, defense) and the best player seasons and careers in each sport, with each season measured against its own league. It is one sport at a time, with no scale across sports.',
             body=[
                 'Rtg+ / Off+ / Def+ = 100 + 25 z (the Stat+ scale), where z = (rating - that season\'s league mean) / s. s is the upper semi-deviation × sqrt 2, sqrt(2 × mean of max(rating - mean, 0)^2), pooled over the season and the two on either side. s equals the SD in a symmetric season, but it isn\'t stretched by a long bottom tail (a floor of 0 points allowed in low-scoring eras, blowout losers, a wide spread of weak programs). 100 is an average team that season, 125 is one s better and 175 is three.',
                 'I use z instead of raw points because scoring levels and the spread between the best and worst teams change by era (fewer, deeper leagues; 1900s college blowouts; dead-ball hockey). Dominance over the league a team played in is the number that compares across eras, and the raw rating is shown next to it.',
                 f"Team ratings. CFB: a ridge SRS on every major-college game (margin capped at 35, home edge, offense and defense from the same ridge on capped points; jhowell.net scores {span(T['cfb'])}). NFL: the same ridge on every NFL, AFL and AAFC game including playoffs (FiveThirtyEight scores to 1998, nflverse from 1999; {span(T['nfl'])}). CBB: Sports Reference SRS / OSRS / DSRS ({span(T['cbb'])}). NBA: Basketball Reference SRS, ORtg and DRtg against the league average ({span(T['nba'])}; off / def from 1951-52). NHL: Hockey Reference SRS, goals for and against a game against the league + half the SOS ({span(T['nhl'])}, no 2004-05). Soccer: big-five clubs, goals a match against the big-five average at season end ({span(T['soccer'])}). CS2: the best Valve VRS points in a calendar year, with each snapshot's top 50 as the league ({span(T['cs2'])}).",
                 'The lists are the top 250 plus the top 25 of every decade, so the Era filter shows the best of each decade. CH is a champion (CFB national title share, NFL league or Super Bowl winner).',
                 f'Era check: the share of the top 100 by decade against the decade\'s share of all rows, as a KL divergence (0 means every decade is represented by its size), era-adjusted against raw. The line is the 95th percentile of the KL when the top 100 are drawn era-blind (4,000 multinomial draws on the decade shares), and a list passes if the adjusted number is under the line. Player lists count each player\'s best season once, since one player\'s run, such as Gretzky\'s eight 1980s seasons, isn\'t an era. Hockey prospects are binned by draft class (5 years). Teams: {chk}.',
                 'Players: peak seasons rank every player-season on its own (one player can hold several rows), and a career is the sum of seasons. Each season is valued over replacement in its own league and scaled to a full season where seasons were short.',
                 f"NBA: VORX per 82 games (XPM is the DPM + BPM blend from 2009-10, and BPM before). Before 1973-74, BPM is estimated from WS/48 and PER (fit on 1974-85 players with 500+ minutes, r {d['nba']['players'].get('fit_r', 0.90):.2f}; tagged est), and minutes start in 1951-52. NHL: point shares per 82 games (Hockey Reference; skaters OPS + DPS, goalies GPS). CBB: the site's CBB VORX on every Barttorvik season from 2007-08. NFL: peak is the site's AV WAR (rebuilt AV, no special teams) from 2012 (snap counts), and career is Pro Football Reference weighted career AV (nflverse draft_picks; drafted players 1980 on). Soccer: the site's GAR, on big-five seasons from 2014-15.",
                 'Tennis: Elo on every tour-level singles match from 1968 (Sackmann archive; K = 250 / (matches + 5)^0.4, Slams × 1.1). Elo+ = 100 + 25 × (peak Elo that year - the year\'s #20 year-end Elo) / SD of the year\'s top 100, and a peak counts after 40 career matches. Career is the sum over years (20+ matches) of the year-end Elo over the #20 line in those SDs.',
                 'Era adjustment (rate + volume): a season\'s rate is set against that season\'s regulars, rate\' = mean_ref + SD_ref × (rate - season mean) / season SD (SD pooled over the season and two on either side), and its volume against that season\'s load, vol\' = vol × q_ref / q_season (q is the 90th percentile of the regulars\' volume). The sport\'s own value formula then runs on rate\' and vol\'. _ref is the mean over the last 10 seasons, so the values read in today\'s units. Unadj is as played.',
                 'By sport. NBA: the rate is XPM and the volume is minutes per 82 team games, VORX = .030 × (XPM\' + 1.4) × min\' / 48 (BPM is per 100 possessions, so pace and the 3-point era are in the rate, and the volume term takes out the 45-minute loads of the 1960s). NHL: WAR per 82 against the season, with skaters and goalies apart (there is no ice time before 2008-09, so no volume term). CBB: the rate is BPM (regulars 400+ min) and the volume is minutes (the short 2020-21 season is scaled up). Soccer: the rate is GAR per 90 (regulars 900+ min) and the volume is minutes. CS2: calendar years from 2024, where the rate is RWA over that year\'s replacement (the median of 1,000+ round players, with opponents at their year-end ratings) and the volume is rounds (the current year to date is scaled to a full year), RAR = RWA\' × rounds\' / 100. Hockey prospects: drafted skaters\' seasons outside the NHL (20+ games, ages 16-21), NHLe+ = 100 + 25 z of log(NHLe + 5) against drafted skaters of the same age and position that season. Tennis: Elo against the year\'s #20 in SDs of the year\'s top 100 is already a rate against the season, so there is no volume term (peak Elo).',
                 'NFL WAR seasons: rosters grew (1,734 WAR rows in 2013, 2,055 in 2021) and the top thinned, so each season\'s WAR is set against that season\'s starters at the position (the top k by WAR, where k is the position\'s share of rows × 704 = 32 teams × 22 starters), in the last 10 seasons\' units. CFB QB and RB / WR / TE Yds+: the over-average value is multiplied by the last 10 seasons\' SD over the season\'s SD (pooled over the season and two on either side; QBs use TAY/P of qualified passers, and skill players use AY of the season\'s starters at the position).',
                 f'Player era check (peak list, KL as above, adjusted against as played): {pchk}.',
                 'These lists are display only, and no model reads them.',
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
