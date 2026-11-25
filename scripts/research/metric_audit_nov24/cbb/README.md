# CBB metric audit (Nov 24 2026)

`audit.py` (harness + candidates, `results.json`), `war_check.py` (D1 on the board's own WAR form, `war_check.json`),
`team.py` (team ratings, `team.json`). Pre-registration: `prereg.md`. Data: Barttorvik getadvstats csv + team results
2010-2026 and game logs 2017-2026 (scripts/.cache, not committed); roster prior inputs research_seasons.csv. No 2026-27 data.
Pairs 2012-13 ... 2025-26 (14). Exposure = minutes. Describe target = team win% (actual result; adjEM shown after the slash,
it is Barttorvik's own rating, which his BPM is built to sum to). Predict target = next-season adjEM.

| metric | describe R2 in-sample (win% / adjEM) | describe held-out win% [90%] (adjEM) | predict team R2 [90%] | predict player r (own / vs BPM) | n pairs |
|---|---|---|---|---|---|
| BPM (Torvik; CBB WAA rate; WAR input until today) | .634 / .999 | .633 [.601, .665] (.999) | .643 [.625, .660] | .680 / .680 | 14 |
| WAR rate (BPM + 2) | .626 / .998 | .625 [.591, .658] (.998) | .648 [.632, .665] | .680 / .680 | 14 |
| Stat+ (BPM position z) | .570 / .974 | .568 [.524, .611] (.973) | .662 [.647, .677] | .674 / .669 | 14 |
| GBPM (Torvik game BPM) | .659 / .995 | **.658** [.629, .687] (.995) | .612 [.594, .629] | .636 / .620 | 14 |
| PRPG! (Torvik, offense) | .538 / .825 | .537 [.511, .562] (.825) | .500 [.468, .532] | .568 / .465 | 14 |
| total PRPG (O + D) | .620 / .979 | .618 [.584, .651] (.979) | .656 [.641, .670] | .683 / .616 | 14 |
| roster prior BPM_hat (cbb_roster.py, returners, same fill) | n/a | n/a | .757 [.748, .766] | .762 (vs BPM) | 14 |
| roster prior BPM_hat (with its freshman / newcomer projections) | n/a | n/a | **.783** [.774, .791] | .762 | 14 |
| team: Barttorvik adjEM season n -> n+1 | | | .684 | | 14 |
| team: win% season n -> n+1 adjEM | | | .33 | | 14 |

Not scored: FV (target is the NBA outcome; its own backtests), Next (WAR count on returners, built on the same roster-prior
inputs; held-out record in data/cbb_next_fit.json), EvanMiya / KenPom (no free player data), ORtg / DRtg (not additive).

Best predictive: roster prior BPM_hat (ours), clear of everything (interval .774-.791; best public, total PRPG .656).
Best descriptive: GBPM (Torvik), held-out win% .658 vs BPM .633 (intervals overlap, but 15/15 seasons better, t 9.6);
on adjEM BPM is .999 by construction. With D1 shipped, CBB WAR is GBPM based, so our WAR is the descriptive leader.

## Candidates (Holm over 6)

| candidate | target | before -> after | seasons/pairs better | t | p (Holm) | result |
|---|---|---|---|---|---|---|
| P1 two-year BPM (w = 1 chosen) | next-season team R2 | .643 -> .666 | 14/14 | 8.22 | <.0001 | pass |
| P2 minutes shrink (k = 100 min) | next-season team R2 | .643 -> .664 | 14/14 | 11.09 | <.0001 | pass |
| P3 class step (Fr +1.9, So +1.0, Jr +.8) | next-season team R2 | .643 -> .650 | 14/14 | 8.37 | <.0001 | pass |
| P4 GBPM blend | next-season team R2 | .643 -> .643 (a = 0) | 0/14 | 0 | .5 | fail |
| D1 GBPM in place of BPM (a = 1 chosen) | held-out win% R2 | .633 -> .658 | 15/15 | 9.59 | <.0001 | pass, shipped |
| D2 BPM + total PRPG blend | held-out win% R2 | .633 -> .639 | 13/15 | 2.99 | .010 | pass, superseded by D1 |

P1-P3 pass against raw BPM, but the site's predictive metrics (roster prior, Next, xBPM) already carry all three (3-year BPM,
minutes x BPM, class), and the roster prior beats every raw candidate by .09 team R2. Nothing new to ship there.
D1 on the board's WAR form (`war_check.py`, wins = a x games + b x team WAR, leave one season out 2013-26): held-out wins RMSE
3.441 -> 3.348, 14/14 seasons, t 28.7; board fit on game logs 2017-26: r .861 -> .872, wins a point .0143 -> .0160, R -2.0 -> -2.3.
GBPM is worse for the next season (.612), so it stays out of every predictive input.
