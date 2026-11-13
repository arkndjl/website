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
