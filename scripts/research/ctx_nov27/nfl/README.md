# NFL metric context audit (Nov 27 2026)

Rule: predictive consumers read pXP/60 within a position (AV WAR for team sums), point in time; descriptive consumers read
season-only value (XV on the WAR board, SV / SVAR on the season tabs). Data: the board replayed 2016-25 (`prep.py`, whole
season and through week 9; no 2026 rows). Pre-registration: `prereg.md` (committed before scoring; T1b added after T1,
before its own numbers). Run: `prep.py`, `t1_backup.py`, `t1b_xgap.py`, `t2_xaav.py` (needs pyarrow) -> `results.json`.

## Inventory

| consumer | file:line | context | input it reads | verdict |
|---|---|---|---|---|
| WAR leaders board (rank, ±, Pos rank) | layouts/shortcodes/nflwar.html:149; scripts/board_moves.py:53 | D | XV (season, per 17); WAA, WAR beside it | OK |
| WAR leaders, per 60 view | layouts/shortcodes/nflwar.html:149 | P | pXP/60 (rows `pxp`, scripts/nfl_rate.py) | OK |
| pXP/60 itself | scripts/nfl_rate.py:44; fit scripts/nfl_rate_research.py | P | rXP/60 of S to date, S-1, S-2 + market prior; history file rolls 2023-25 | OK (point in time; contract signed "through S" can be a mid-season extension: trivial) |
| 1Y / 3Y columns | scripts/nfl_war_proj.py:98 | P | board WAR of S, S-1, S-2 (pre special teams, same as the fit frames), snaps, age, market | OK (own fitted form); T3 registered, not run |
| projections tab (P20/50/80) | scripts/player_pctl.py:163, 1089 | P | Marcel WAR a snap 1/.7/.5 shrunk to group, pre-ST board both in fit and live | OK (same form fit and serve) |
| QBs tab | layouts/shortcodes/nflqb.html:11; scripts/nfl_qb.py | D | ranks by SV (season only); Proj column is the game model term, labelled | OK |
| skill / defenders tabs | layouts/shortcodes/nflseason.html:15; scripts/nfl_season_value.py | D | SV, SVAR (season only; opponent shrink within season) | OK |
| specialists | scripts/st_returners.py, st_kickers.py | D | season ST points | OK |
| standouts | scripts/nfl_breakouts.py:100 | D outcome vs P expectation | week's board WAR less Marcel WAR rate x snaps (pctl fit) | OK |
| rookies tab | scripts/rookies.py:157 | D | SV / SVAR views, pXP/60 view labelled | OK |
| next up (BO%) | scripts/nfl_breakout.py | P | workload share, yards an opportunity, age, draft slot (no site value metric) | OK; lead L2 |
| next up, rate column | scripts/next_up.py:88, 153 | P | WAR a 17 games (descriptive) | DISPLAY, fixed: pXP/60 |
| depth chart tiles + backup watch grade | scripts/backup_watch.py:331 | P (who is better now) | board WAR a snap this season, shrunk 300 | MISMATCH-P candidate, T1 FAIL as registered: stays (see caveat, lead L5) |
| backup watch xGap (the rank) | scripts/backup_age.py:33; data/backup_age.json | P (two seasons) | grade gap x terms borrowed from NBA/NHL/soccer | MISMATCH-P, T1b PASS, shipped: pXP/60 gap, NFL's own fit |
| awards, predictive | scripts/awards.py:1009 | D (voter model) | box stats, team wins; `war` read from data/nfl_war.json players (absent, unused) | OK |
| awards, conviction | scripts/awards.py:1160 | D | SVAR to date run out at pace (season only) | OK |
| all-time players | scripts/alltime.py:332 | D | AV WAR a season 2012 on (XV exists only 2018 on), PFR career AV | OK |
| all-time teams / offenses / defenses | scripts/alltime.py | D | season results | OK |
| team WAR tab | layouts/shortcodes/nflteamwar.html | D | board WAR summed | OK |
| game model: injury, trade, reserve terms | scripts/nfl_games.py:438, 842; nfl_trades.py:87 | P team | AV WAR a game (war_ledger: S to the week + S-1), point in time by `thru` | OK (AV is the team pick) |
| game model: roster prior | scripts/nfl_roster.py:158 | P team | AV WAR S-1, S-2 + age + draft slot, week-1 rosters | OK |
| game model: QB term | scripts/nfl_games.py | P | career-weighted EPA a play, shrunk | OK |
| ARK Ranking, season odds, bracket | scripts/nfl_games.py season_views | P | the game model's ratings | OK |
| xAAV / contract value | scripts/xaav.py:237 | P (market) | board WAR S-1, S-2, WAA, snaps, age by position | MISMATCH-P candidate, T2 FAIL: stays |
| fantasy talent term | scripts/nfl_fantasy.py:603 | P | AV WAR a game to date + S-1 at half, offense side, point in time | OK |
| mock draft team needs | scripts/cfb_teams.mjs:950 | P | contracts + draft capital (the WAR need failed its own backtest) | OK |
| predictive badges | scripts/nfl_badges.py | P | part rates regressed, backtested | OK |
| transactions value | scripts/transaction_values.py:82 | D | WAR + SVAR | OK |
| news, search, watch score | scripts/news.py:130; search_index.py:133; watch_games.py:189 | D | board `war` | OK (season to date) |

## Tests (Holm over the four run or registered; T3 not run)

| swap | target | before -> after | t | seasons | result |
|---|---|---|---|---|---|
| T1 depth / backup grade: season WAR a snap -> pXP/60 | weeks 10+ rXP/60 within sub-position, from week 9 | R2 .438 -> .344 (MSE .211 -> .246) | +9.04 | 2/10 | FAIL |
| T1 secondary, same swap | next-season rXP/60 | R2 .185 -> .239 | -7.11 | 9/9 | (other way) |
| T1 guard: same-room pairs, who is better weeks 10+ | hit rate | .643 -> .618 | | | worse |
| T1 guard: XV a snap weeks 10+ | R2 | .610 -> .355 | +16.6 | 0/8 | worse |
| T1b xGap input: grade gap -> pXP/60 gap (+ age gap) | two-season gap, WAR per 1,000 snaps, walk-forward 2019-23 | MSE .03748 -> .03574 all pairs | -3.68 | 4/5 | PASS |
| T1b guard: listed pairs only | same | .04285 -> .03746 | -5.13 | 5/5 | holds |
| T2 xAAV: M4 -> M4 + pXP/60 by position | AAV / cap, leave one signing year out | MAE .791 -> .790 | -1.61 | 8/9 | FAIL (forward split t 0.0, 3/5) |
| T3 1Y / 3Y: form E -> E + pXP/60 by group | next-season and three-season WAR | not run | | | lead L1 |

Caveat on T1's weeks 10+ target (found after scoring, not registered): it is the season total less the first nine
weeks, and the XV part of board WAR is z-scored and shrunk on the season to date, so in 2018-25 the difference keeps
part of the first nine weeks and favours the season grade. On the 2016-17 boards (no XV, a clean difference, but pXP/60
has one season of history or none) the two tie: R2 .139 -> .148, t -.48, pairs .560 -> .551. So T1 fails as registered
and the grade stays, but the size of the loss is not to be trusted. A clean retest needs a board built from weeks 10 on
alone (nfl_war.board has `thru`, no `since`): lead L5.

## Shipped
- Backup watch xGap (NFL) = -.0248 + .345 x pXP/60 gap + .0079 x age gap, the NFL's own fit on 2,457 listed pairs
  2016-23 (`python3 scripts/backup_age_fit.py --nfl`; the age term's own held-out t -3.73). Rows carry `px`, `pgap`.
  The grade shown and the listing rule stay on this season's WAR a snap.
- Next up shows pXP/60 where it showed WAR/17.

## Leads
- L1 T3 as registered: `python3 scripts/player_pctl.py --frames nfl` (83 board replays), then a form F in
  scripts/nfl_war_proj_research.py = E + pXP/60 by group at week 9 and the season's end.
- L2 next up odds with a pXP/60 gap term (the CBB analogue passed, the NBA one failed): add it as a candidate in
  scripts/nfl_breakout_research.py; pXP/60 history starts 2016, so the fit window shrinks to 2016-24.
- L3 injury term at pXP/60 x snaps a game instead of AV WAR a game: needs weekly pXP replays and
  `python3 scripts/nfl_games.py --fit` (20 min cold). AV is the settled team pick, so this is a lead, not a mismatch.
- L5 T1 on a clean target: add `since` to nfl_war.season_data / board, replay weeks 10+ alone for 2018-25, rerun t1_backup.py.
- L4 after the 2026 season: extend the replay years in backup_age_fit.py --nfl (it reads the last finished season by itself).
