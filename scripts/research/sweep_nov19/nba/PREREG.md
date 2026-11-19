# NBA worker pre-registration (Nov 19 2026 sweep)

Written before any outcome was scored. Data fetching (no scoring) began before this file; nothing below was changed
after a result was seen. Lockbox: no 2026-27 NBA / G League outcome is read by any test (2026-27 forecasts are read
only for the ESPN point-in-time check, never a score). All seasons are end years (2026 = 2025-26).

General pass rule (every lead unless a tolerance is stated): pre-registered candidate vs the stated baseline, paired
difference of the stated loss; t clustered at the stated unit <= -2 on the HELD split (lower loss = better), tune and
held share sign, a majority of held seasons have the same sign, Holm at .05 inside the stated family (two-sided normal
p of the held t). No retuning after held, no rescue tests. Ship only on a pass. DARKO leads (1, 11): a pass means
LOGGING on (daily forward log + lockbox score registered here), never a ship (history is retrospective, no vintage).

## Families
- DARKO: 1a, 1b, 11 (3 tests)
- DEF: 2, 3 (2 tests)
- GAME: 4 (1 test, only if its point-in-time gate passes)
- GL: 6a, 6b, 6c (3 tests)
- PLAYER: 7a, 10b (2 tests)
- PLAY: 8 natl, 8 cup, 8 star (3 tests)
- AGE3Y: 10a x 4 interactions (4 tests)
- CAP: cross-sport 2 (1 test: a conjunction of y1 and y3y)

## 1a. DARKO as-of DPM in the game model lineup term
- Data: get_rankings(metric dpm, asof) at 4 sample dates a season, 2016-2026 (Nov 1, Dec 1, Jan 15, Mar 1; 2021: Dec 27,
  Jan 20, Feb 20, Apr 1; in-season dates with projected minutes >= 8). About 500 calls. Joined to the model's ESPN
  players through scripts/names.py.
- Candidate: from the day after each sample date until the next, each matched player's value = (1 - w) x current
  value + w x DPM mapped to the value scale (mean and sd matched on the matched players, as nba_games.arc_blend).
  The season's first sample (Nov 1) applies from Nov 2; games before it keep the shipped values. Team lineup baselines
  are shifted by the same change (baseline of the minutes already played, revalued), so `lin` reads only tonight's
  lineup against the same players. w in {.25, .5, .75}, picked on tune MAE.
- Rows: finished games with a closing line, 2016-2026. Tune 2016-21, held 2022-26.
- Baseline: the committed walk-forward margin (shipped params and feats, nba_games_fit.wf).
- Metric: |margin error|, paired, clustered by game day (harness.paired, day + home-team-season as the research scripts).
  Also reported: win log loss, gap to close by season fifth.
- Pass: tune t <= -1.5 and held t <= -2, >= 3 of 5 held seasons lower, Holm in DARKO. Pass -> LOGGING on.

## 1b. DARKO first-week DPM as a preseason player value (pXPM / Proj prior)
- Rows: player-seasons S 2016-2026 with 500+ MP in S on the XPM board, matched in the first-week snapshot.
- Baseline: a + b x prior_xpm(S), leave-one-season-out. Candidate: a + b x prior + c x DPM(first week), same folds.
- Metric: squared error against season-S XPM, paired, clustered by season. Tune 2016-21, held 2022-26.
- Pass: general rule. Caveat fixed now: XPM is half DPM (same author), so even a pass is an upper bound. Pass -> LOGGING.

## 11. DARKO projected minutes and per-100 rates vs the player lines
- Data: x_minutes, x_pts_100, x_ast_100, x_drb_100, x_orb_100 at Dec 1, Jan 15, Mar 1 of 2024, 2025, 2026 (about 450 calls).
- Rows: the shipped player walk's rows (nba_players.collect: played, has a naive line, role minutes >= 10, no playoffs)
  for games in the 21 days after each sample date, player matched in the snapshot.
- Scorecard (descriptive): MAE of MIN, PTS, REB, AST: DARKO (rate x x_minutes / 48 x league possessions per game of the
  season before / 100) vs the shipped walk-forward line, same rows.
- Stack test: for PTS, REB, AST the candidate = shipped line + c x (DARKO rate x shipped minutes line - shipped line),
  c per stat fit on 2024 rows, scored on 2025-26 (held). PRA = sum. Metric |PRA error|, paired, clustered by game.
- Pass: held t <= -2, both held seasons lower, Holm in DARKO. Pass -> LOGGING on.

## 2. Hustle block for D-XPM (primary: hustle only, since rim files stop at 2025)
- Data: gabriel1200/site_Data hustle.csv (2018-2026 used; S-1 files only). Frame: /mnt/project-files/cbb/xpm/
  nba_player_seasons.csv, players.csv (team minutes), teams.csv (off_rtg, def_rtg), the XPM test's team-season frame.
- Player hustle index (season s): mean of five within-position (G/F/C) z-scores of per-36 deflections, contested
  shots, charges drawn, defensive box-outs, defensive loose balls recovered (players with 300+ MP set the z scale);
  residualised on D-XPM (dblend) by OLS on the training seasons; shrunk MP / (MP + 600); 0 with no row.
- Team-season t: D_pred = a + b x sum(share_i x dval_i(t-1)); candidate adds c x sum(share_i x hustle_i(t-1));
  share = 5 x MP_i(t) / team MP(t); dval = dblend(t-1) shrunk MP/(MP+600) toward -0.5 (missing: -0.5). O side
  (a + b x sum share x oblend) identical in both. Coefficients forward-chaining (fit on seasons < t).
- Rows: team-seasons t 2021-2026 (hustle t-1 from 2018; first two seasons train only). Tune 2021-22, held 2023-26.
- Metric: squared error of predicted net rating (O_pred - D_pred vs net_rtg), paired, clustered by season; points
  allowed reported too. Pass: general rule on NET (>= 3 of 4 held seasons), Holm in DEF.

## 3. Defensive matchup data (shufinskiy/nba_data matchups_2017..2025, Apache-2.0)
- Player-season metrics: PAOE = points allowed per 100 partial possessions minus expected (expected = partial
  possessions x the offensive player's season points per matchup possession against all defenders), shrunk
  poss / (poss + 300); MD = possession-weighted points per 100 of the players guarded (display metric).
- Reliability gate first: odd/even game split r of PAOE for defenders with 1,000+ partial possessions; r < .3 -> the
  model test is not run and the lead FAILS as a model term.
- Test: frame, split, metric and pass rule of lead 2; candidate adds c x sum(share_i x PAOE_i(t-1)). Rows t 2021-2026
  (same rows as lead 2). Holm in DEF.
- Display: not a test. Built only if time allows; history-only (no 2026-27 source), so it would be a past-season table.

## 4. ESPN BPI predictor stack
- Point-in-time gate (run first; no outcome scored):
  G1 snapshot A (Nov 19 2026 20:40Z: 17 final games Nov 17-18, 19 future games) re-read later in the session; any
     change in teamPredPtDiff > .05 or gameProjection > .1 on a game that was already final = not point-in-time.
  G2 200 random games 2022-2026 (40 a season, seed 20261119): core-API predictor home gameProjection vs the frozen
     pregame home win % in the game's summary winprobability[0]. Point-in-time consistent if median |diff| <= 2
     points of probability and 90th percentile <= 6.
  G3 descriptive: predictor margin MAE vs the close on the same 200 games (a public model beating the close is the
     leak signature).
- If G1 or G2 fails: no stack test; verdict LOGGING on (daily pre-tip snapshot log, scored once on the lockbox:
  margin MAE of walk + bpi vs walk, 2026-27 logged games, t clustered by day <= -2).
- If the gate passes: stack `bpi` (predictor home margin) as one more column of the shipped margin walk on a seeded
  random sample of up to 2,400 lined games 2022-26 (fetch budget 45 minutes); tune 2022-24, held 2025-26; |margin
  error| paired, clustered by day; pass = tune t <= -1.5, held t <= -2, >= 4 of 5 seasons lower.

## 6. G League
- 6a size block: add height (in), weight (lb) and a US-college flag (stats.gleague.nba.com leaguedashplayerbiostats per
  season) to the shipped model's HIST features. Rows and folds = gleague_callup.research (leave one season out,
  2009-2025). Baseline = shipped FEATS. Metric: NBA% log loss per row, paired, clustered by season. Tune = seasons
  to 2017, held = 2018-2025. Pass: general rule, Holm in GL. Missing bio -> season mean + a missing flag.
- 6b call-up hazard: G League game logs (leaguegamelog, one call a season) + NBA game dates from nba_pbox_hist
  (2019-20 on). Snapshots on the 1st and 15th of Dec-Mar, seasons 2020-2025; rows = players with 3+ G League games in
  the 30 days before and no NBA game yet that season; label = first NBA game of the season within 30 days.
  Baseline: ridge logistic on age, games and minutes per game to date, Game Score per 36 to date. Candidate adds
  last-10-game form: minutes per game, Game Score per 36, points per 36 over his last 10 G League games, each minus
  the to-date value. Tune 2020-22 (fit), held 2023-25 (walk-forward: each held season fit on the seasons before).
  Metric: log loss, paired, clustered by snapshot date. Pass: general rule, Holm in GL.
- 6c two-way conversion: Basketball-Reference NBA_<Y>_transactions pages 2018-2025. Rows = players signed to a two-way
  contract before Jan 15 of season Y and not converted or waived by then; label = converted to a standard contract
  from Jan 15 to the season's end. Baseline: logistic on age + signing month. Candidate adds G League games, minutes per
  game and Game Score per 36 through Jan 14 (game logs). Leave-one-season-out; tune 2018-21, held 2022-25; log loss,
  paired, clustered by season. Pass: general rule, Holm in GL.
- 6b and 6c are attempted after every other lead; if the time box ends first they are recorded NOT RUN.

## 7. Preseason box scores (ESPN seasontype 1, 25 days before each opening night, 2019-2026)
- 7a minutes in a team's first 10 games. Rows: nba_players.collect rows (played, naive line, role >= 10, regular
  season) with the team's game number <= 10, seasons with a walk-forward fit. Per player: ps = share of his team's
  last two preseason games he started (0 if he did not play). Candidate = shipped MIN feats + two columns,
  ps x e and ps x base x e, e = 1 - (team game number - 1) / 10; walk-forward as shipped (each season fit on the
  seasons before, all rows; columns are 0 after game 10). Tune = first two scored seasons, held = 2024-26.
  Metric |minutes error| on the game 1-10 rows, paired, clustered by game. Pass: general rule, Holm in PLAYER.
- 7b Summer League for rookie XPM and 7c margin: NOT RUN (fetch and time budget; recorded as such).

## 8. National TV / NBA Cup / PPP stars in the play-chance model (j3)
- Data: ESPN scoreboard geoBroadcasts market type National and notes (NBA Cup / In-Season Tournament) per game,
  2020-2026, as listed now (flex leak: reported, late-season rows rerun without them is NOT done; stated limit).
  Star = All-Star or All-NBA in any of the three seasons before (awards column of the XPM frame's players.csv).
- Candidates (each alone, added to j3's numeric inputs): natl = national TV game; cup = NBA Cup game; star = star x
  (natl or cup) x season >= 2024 (the policy seasons).
- Rows: nba_play.rows (rotation players in reported games). Walk-forward as shipped (season s fit on seasons < s,
  from 2022). Tune 2022-23, held 2024-26. Metric: log loss weighted by role minutes, paired, clustered by game day.
  Pass: general rule on all rows, Holm in PLAY. Star rows reported separately.

## 10a. Archetype aging in the 3Y projection
- Four candidates, each H4 + one column (age - 27) x z, z within season among 500+ MP players, 0 when missing:
  FT% (shotzone FtPoints / FTA, 50+ FTA), three-point rate (FG3A / (FG2A + FG3A)), drives per 36 (tracking.csv type
  drives), self-created share (passing.csv UAFGM / (FGM from shotzone)). Season S files (inputs at the end of S).
- Rows, folds, targets: nba_proj3y_star_research harness at f = 1, S 2014-2025 (tracking starts 2014). Tune S <= 2018,
  held S >= 2019. Metric: squared error on y1 and y3y, paired, players as clusters (the harness's unit), season-
  clustered t reported. Pass: held t <= -2 on BOTH y1 and y3y, tune same sign, majority of held seasons, Holm over 4.

## 10b. Potential assists as the assists prior
- Column pa = role minutes x last season's potential assists per minute x last season's league AST / potential AST
  (passing.csv, S-1; players without a row use their base assists line). Candidate = shipped AST feats + pa.
- Rows and walk as the shipped player fit (tune 2022-23, held 2024-26). Metric |AST error|, paired, clustered by game.
  Pass: general rule, Holm in PLAYER.

## Cross-sport 2. Salary cap share in the 1Y / 3Y projections (port of NFL form E)
- Data: Basketball-Reference team-season salary tables 2012-2026 (salaries2), cap by season (league figures).
  Salary used for a row of season S = his salary in season S (known before S began; no later contract).
- Candidate M = H4 + three columns: rk (first-round pick in his first four seasons after the draft), rk x -ln(pick),
  (1 - rk) x ln(max(salary, 0.25% of cap) / cap) (no salary row: the 0.25% floor). One form, no search.
- Rows, folds, targets: nba_proj3y_star_research harness, S 2012-2025 (y3y to 2023). Tune S 2012-18, held S 2019+.
- Metric: squared error on y1 and y3y, paired, players as clusters; season-clustered t and seasons won reported.
- Pass: at f = 1 and f = .5 held t <= -2 on both targets, tune same sign, majority of held seasons lower at f = 1,
  and t <= 0 at every other f. The proj 4+ band bias is reported, not gated. Pass -> refit chain and live wiring
  (nba_proj.py reads this season's salary from the contracts page).

## Lockbox registrations (scored once at season end, no selection)
- Any LOGGING lead: the test above re-run on 2026-27 logged rows only, same candidate, same metric, t <= -2.

## Addendum A (Nov 19 2026 21:00Z; written before any lead 8 row was scored; original file sha256 33d9990d85d73212b7c74648c45ad1a9e4c6ed439bf3ecf88779df47aafe3697)
- Lead 8 `star` flag is zero before 2024 by construction, so a walk-forward fit has no policy row to learn from until
  2025 and the tune split (2022-23) cannot have a sign. For this flag only: scored on 2025-26 (the seasons whose fit
  has seen a policy season); pass = t <= -2 on 2025-26 all rows with both seasons lower, Holm in PLAY; no tune-sign
  condition. natl and cup keep the general rule (cup also has no row before 2024: same treatment as star).
