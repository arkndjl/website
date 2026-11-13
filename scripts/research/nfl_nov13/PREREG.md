# NFL audit, Nov 13 2026: pre-registration

Written before any of these tests was run. Data: seasons through 2025 only (2026 from week 11 is the lockbox; 2026
weeks 1-10 are not read either). Nothing listed as failed in memory or in scripts/nfl_games.py's docstring is rerun.

## Confirmatory family (7 tests, Holm at .05 over all 7, one-sided)

Game tests use scripts/nfl_games.py's own walk-forward (live params, refit on every season before, 2012 on), paired
per game on absolute error, t clustered by season-week (harness.paired). Settings are picked on 2015-20 only. A test's
p is the held-out 2021-25 one-sided p at the setting 2015-20 picked. Pass = 2015-20 t <= -1.5 AND Holm-adjusted
held-out p <= .05.

A1 `ir` (margin). Non-QBs on a club's reserve lists (weekly roster status RES, PUP, SUS, NWT, RSN, EXE) in the week
   of the game, each at the injury term's own value (nfl_games.player_value on the ledgers to that week, floor 0,
   x 36), x 0.5 ** (n / h), n = club games this season since his last game. Away minus home, its own input.
   Grid (2015-20): scope {in-season: played a game this season; all: n = club games so far when he has not played} x
   h {2, 4, 8, none}. Reason: a player leaves the game status report the day he goes on IR, so his cost drops to 0
   while Elo and the market rating have seen few games without him.
A2 `qbr` (margin). The QB term rebuilt on ESPN QBR's weekly EPA (nflverse espn_data qbr_week_level: epa_total /
   qb_plays, opponent- and credit-adjusted) in place of raw passing + rushing EPA: same career memory (.7 a summer),
   n0 100, replacement = the 2006-14 play-weighted mean - .16. Grid: replace `qb`, or add beside it.
A3 `inj` valued with contracts (margin). Each listed player's value v' = (1 - L) v + L k_g cap%, cap% = APY share of
   the cap of his contract in force (OverTheCap via nflverse: signed before the season, or this year by a rookie or by
   a player on a new club), k_g = last season's WAR a game per cap% in his position group. Grid L {.25, .5, 1}.
B1 `tqb` (total). Both starters' QB term summed (the margin's QB input, home plus away), added to the totals inputs.
B2 `tinj` (total). Injury cost of offensive players minus defensive players, both clubs summed (the injury term's
   costs split by the report's position), added to the totals inputs.
C1 pXP/60 market prior. scripts/nfl_rate_research.py's leave-one-season-out test; new form marcelM = marcel with the
   prior mean moved by draft slot on a rookie deal (seasons since the draft <= 3: -ln pick, undrafted 300) or by
   ln(cap%) of the contract in force (signed through that season) otherwise; slopes per position group fit like
   marcelP's (weighted LS of rate - mean, training seasons only), K refit. p = paired t of marcelM vs marcel
   (player-seasons, snap-weighted). Pass = t <= -2, 7 of 9 seasons, calibration slope .8-1.2, Holm.
C2 1Y / 3Y WAR market term. scripts/nfl_war_proj_research.py's leave-one-season-out test; form E = the live form +
   by group: rookie-deal flag, flag x -ln pick, veteran x ln(cap%). Scored at the season's end and at week 9, y1 and
   y3. p = the largest of the four paired p's (E vs the live form). Pass = every one t <= -2 and most seasons, Holm.

## Research only (not in the family, cannot ship)

D  Public bet share (nfelo market file, Action Network tickets %): slope of result - close on the home side's ticket
   share. The file has no licence, so it is a read, not an input.

## After a pass

Refit (`nfl_games.py --fit`), then `games_picks.py --fit` and `--rules`; 2026 weeks 1-10 reported once as a check, not
a gate. The lockbox scoring at the season's end stays as decided Nov 11.

## Results (Nov 13 2026; data/nfl_audit_nov13.json)

| test | 2015-20 t | 2021-25 t (p) | Holm | result |
|---|---|---|---|---|
| C1 pXP/60 market prior | leave-one-season-out t -4.85, 9/9, slope 1.00 | p 6e-7 | pass | shipped (form marcelM) |
| C2 1Y / 3Y market term | t -2.58 / -3.12 (week 9), -3.07 / -3.58 (end); 30 of 34 folds | p .005 | pass | shipped (form E) |
| A1 ir (pick: in-season, no fade) | -0.22 | -1.73 (.043) | fail | not shipped; lead |
| B1 tqb | -1.58 | -0.82 (.21) | fail | not shipped; lead |
| A2 qbr (pick: add) | +0.99 | +0.45 | fail | replace: +1.70 / -1.69 |
| A3 inj with contracts (pick: L .5) | -0.61 | +0.40 | fail | |
| B2 tinj | +2.00 | -0.04 | fail | |

Read after the results (post hoc, not a test): the weekly roster's status is the gameday one, so a player ruled out
on Friday and moved to IR on Saturday is on both lists (5% of Out players in 2017, 26% in 2025). With those taken
off (`IR_CLEAN=1`), A1 reads 2015-20 t -0.5 to +1.4 and 2021-25 t -1.8 to -3.4 in all 8 cells (scope all, no fade:
MAE -.042, coefficient .65; by season 2021 .000, 2022 -.023, 2023 -.012, 2024 -.059, 2025 -.112). IR with a return
became routine in 2020, and the input starts in 2016, so the 2015-20 walk trains its weight on 0 to 4 seasons.
D (public bet share): not run.

## Registered for the one season-end score (2026 season, every week; the Nov 11 lockbox rules)

L1 `ir`: non-QBs on a reserve list and off that week's game status report, every such player (scope all), no fade,
   its own walk-forward weight, against the model without it. Pass = paired t <= -1.65 by season-week on 2026.
L2 `tqb`: as B1. Pass = paired t <= -1.65 on 2026 totals.
