# Hockey (NHL + hockey prospects) port pass, Nov 23 2026
Result: 9 untried cells tested, 0 pass, nothing shipped. Detail + prereg hashes: scripts/research/port_nov23/hockey/.
Fails: early-season win stretch (held t +.16), early totals shrink (tune t +5.6), mdis (held -2.91 but tune -.74: lead, re-score on lockbox),
tdis (-.03), returners in rv (+.30), roster turnover (-.33, tune +.99), aHPM age-adjusted rookie rate (+.92), b2b -> totals (-.84, tune +1.43), rv -> totals (+.12).
Tested before: spots, luck (rating is xG), market rating, pace, coach change, lineup rv, injury charge, rest, MoneyPuck/DRatings stack, FV->rv, NHLe->pWAR.
n/a: attendance, conference hierarchy, lower tier, totals recentre (NHL not in games_picks), Stat+, SV (WAR already season-only).
Needs data: game control (~20.6k play-by-play pulls).
