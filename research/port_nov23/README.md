# Port pass Nov 23 2026: every single-sport idea, metric and passing input, tried in every sport

Noah: try every fix/input/driver/metric from one sport in all sports, and test anything that passes held out as an input to the other models.
Brief: /mnt/project-files/port-nov23/BRIEF.md. Per-sport scripts, prereg (sha256 recorded before running) and results: scripts/research/port_nov23/<sport>/.
Lockbox (2026-27) not read. Holm within each sport's family.

## Score
| sport | untried cells tested | passed | shipped |
|---|---|---|---|
| NFL + CFB | 7 | 1 | CFB pSV/60 (QB predictive SV rate), t -11.7, display |
| NBA + CBB | 10 | 0 | none (NBA XPM+ built, left for the board key-stats thread) |
| NHL + hockey prospects | 9 | 0 | none |
| soccer | 9 + 1 metric | 2 | aGAR/90 on rookies (t -2.66), 1Y P20/P80 range on player board |
| tennis, CS2, 1NT | 8 + 1 metric | 1 | tennis SV (season WAR) column on ARK Ranking |
| total | 43 tests + 3 new metrics | 4 | 4 display metrics, no game-model change |

## Matrix: idea x sport (S = shipped earlier / origin, P = passed today, F = failed today, f = failed before, x = n/a, d = needs data, o = owned by another thread)
| idea | NFL | CFB | NBA | CBB | NHL | soccer | tennis | CS2 |
|---|---|---|---|---|---|---|---|---|
| G1 letdown / look-ahead | f | S | f (lead) | f | f | f | F title letdown (lead) | F |
| G2 early-season stretch / totals shrink | F / F | S | F / F | F / F | F / F | F | F | f |
| G3 game control | f | S | f | S | d | F | f | f |
| G4 luck-stripped (3PT, FT, fumbles, TB, BP) | F fumbles | S | S 3PT, F opp FT | S | f (xG) | f (xG) | F TB, F BP | f |
| G5 market disagreement / market totals | f / S | S | F mdis, F tdis / S | S | F mdis (lead), F tdis / S | S | S | S |
| G6 tempo | f | f | d / f | S | f | f | x | f |
| G7 home x attendance | x | d | d | S | x | d | f | f |
| G8 conference / league hierarchy | x | f | x | S | x | S | x | S |
| G9 lower-tier carry | x | S | x | S | x | S | S | o |
| G10 coach / manager change | f | S | f | f | f | f | d | d |
| G11 lost-season returners | f | d | S | S | F | F | F layoff | f |
| G12 lineup-adjusted ratings | f | x | S | f | S | f | x | S |
| G13 season-out charge / re-price | f | S | x / f | f / S | f | F | f | x |
| G14 totals recentre | x | S | S | S | x | S | x | f |
| G15 rest | S | S | S | f | S | S | S | f |
| G16 public-rating stack | d | S | f | S | f | x | f | S |
| G17 starter out (QB, goalie, keeper) | S | S | x | x | S | F keeper | x | f |
| G18 roster turnover prior | S | S | f | S | F | d | x | f |
| M1 age-adjusted rate | F aXP/60 | x | S aXPM | f | F aHPM | P aGAR/90 | f | S |
| M2 raw / predictive pair | S | P pSV/60 | S | S | S | f | S | S |
| M3 Stat+ | x | S | built XPM+ | S | x | x | S | not run |
| M4 SV / SVAR | S | S | x (season) | x (season) | x (season) | S | P SV | x |
| M5 over expected | f | S | d | d | S | f | S | S |
| M9 percentiles | S | not run | S | d | S | P 1Y P20/P80 | not run | not run |

## Model-to-model (passing input -> another model)
Tested today, all failed: NBA team margin -> NBA 3Y (t -1.80, lead), CBB-style teammates XPM -> NBA 3Y (t -1.59, lead), XPM+ -> 3Y (-.27);
NFL SV -> pXP/60 prior (-.42); NHL b2b -> totals (-.84, tune +1.43), NHL rv -> totals (+.12); soccer prior SV/90 -> injury term (+.59),
soccer pg90 -> injury term (-.28); CS2 series player Elo -> CS2 prospect FV (-1.62, gate -2).
Tested before (fail unless noted): FV -> game models every sport (CBB fvtop/fvfrm shipped), pXP/60 and SV -> NFL game, QB SV -> CFB/NFL game,
draft slot/cap -> NFL pXP/60 (shipped), NHLe -> pWAR, pPA gap -> tennis match (shipped), RWA -> CS2 series (shipped), ESEA RWA -> 1NT preview (shipped).
Owned by open threads (candidates handed over): WAR/SV/SVAR -> awards conviction, FV/SV/pSV -> mocks, young FV -> next up.
Not yet tested (leads): NFL team ratings -> 1Y/3Y, NFL questionable model -> percentile exposure, CFB pSV -> CFB game QB term,
Challenger K -> tennis prospects Elo, tennis P20/P80 bands, CS2 Stat+/percentiles, CFB school development -> recruits.

## Re-score after the 2026-27 lockbox (held-only near misses)
NHL mdis (held t -2.91, every held season better), NBA letdown (held -2.5), tennis title letdown (held -1.56, 4/4), NBA tdis (held -1.00).
