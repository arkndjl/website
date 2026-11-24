# BPM-style team adjustment, ported from rXPM (Nov 24 2026)

rXPM (PR #1195, `scripts/nba_rxpm_research.py`) shifts every player on a team by one amount per side so the minutes-weighted
sum matches team results. Same-season fit rises by construction, so the pass rule is out of sample:
next-season team test (season n values x season n+1 playing time -> n+1 team result, pooled R2) must not fall, and
next-season player r (n value vs n+1 unadjusted value, weighted by n+1 exposure) must not drop by more than .01.
Shared harness `core.py` (teams centred within league-season; per side where the sport has O/D results).

| sport / metric | describe base -> adj | next-season team R2 base -> adj | player r base -> adj | pairs better | result |
|---|---|---|---|---|---|
| NBA rXPM (shipped #1195) | .963 -> .999 | .640 -> .647 | .786 -> .782 | 6/9 | PASS |
| NHL descriptive WAR (`nhl.py`) | .979 -> 1.0 | .251 -> .248 | .309 -> .308 | 6/17 | fail (team) |
| NFL WAR .6 AV + .4 XV, per side (`nfl.py`) | .960 -> 1.0 | .279 -> .315 | .564 -> .457 | 5/7 | fail (player r -.107) |
| NFL AV WAR alone | .987 -> 1.0 | .283 -> .290 | .627 -> .450 | 4/7 | fail |
| NFL XV alone | .839 -> 1.0 | .235 -> .282 | .444 -> .398 | 5/7 | fail |
| CFB cWAR driver, all ten positions 2024-26 (`cfb.py`) | .646 -> 1.0 | .294 -> .341 | .572 -> .561 | 2/2 | fail (player r -.011) |
| CFB 2019-26 (seven positions before 2024) | .485 -> 1.0 | .162 -> .279 | .576 -> .555 | 7/7 | fail (player r -.021) |
| CBB Barttorvik BPM, per side (`cbb.py`) | .999 -> 1.0 | .643 -> .641 | .680 -> .679 | 4/14 | fail (already team-adjusted) |
| Soccer GAR (`soccer.py`) | .876 -> 1.0 | .648 -> .616 | .789 -> .764 | 1/11 | fail |
| Soccer SVAR | .895 -> 1.0 | .630 -> .609 | .682 -> .668 | 3/11 | fail |
| CS2 RWA, pm 1 vs shipped pm .5 (`cs2.py`) | .936 -> 1.0 (per map) | held next-month map MSE t +2.47 (worse) | .495 -> .493 | | fail |
| Tennis | no team analogue (a player is his own team; SV already sums his results) | | | | n/a |

Nothing ships beyond NBA. Where the team test gains (NFL, CFB) it is the team's residual (scheme, coaching, program,
luck) carried forward on returning players; it costs the player-level read, which the rule protects. NHL, soccer and CBB
already add up (or are fit) to team results through xG / Torvik's own adjustment, and pinning them to actual goals adds
finishing and keeper luck. CS2 RWA already takes half the map residual (pm .5, tuned); the full share is worse held out.

Data: NHL MoneyPuck + stats API (nhl_players loaders); NFL nflverse (`python3 scripts/nfl_xv.py --prep`), XV weights fit
without seasons n and n+1; CFB PFN impact scores + ESPN SRS (`node cfb_export.mjs`); CBB barttorvik csv + team results;
soccer static/data/soccer-war rows + ESPN game log (Understat down); CS2 bo3.gg map rows (held months Jul 2025+).
Re-test CFB on the board's own cWAR (Stat+ x snap share) once 2026 and 2027 are complete.
