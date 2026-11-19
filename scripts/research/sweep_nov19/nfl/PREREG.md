# NFL sweep Nov 19 2026: pre-registration

Written before any score was computed. Data pulled before this file: source pages only (Madden sheets, coach pages,
weekly roster files) and a count of roster status codes by season (no outcomes). Lockbox: nothing from the 2026 season
is read by any test here (all tests end with the 2025 season). Scripts: scripts/research/sweep_nov19/nfl/.

General rules for every test: paired per-row error difference (candidate minus baseline), t clustered at the unit named;
PASS needs (i) held t in the right direction with |t| >= 2, (ii) the tune split the same sign, (iii) a majority of held
seasons the same sign, (iv) Holm at .05 inside the lead's family on the held p (normal approximation of t). Nothing is
retuned after held is seen; a fail ships nothing.

## Lead 1: Madden launch ratings (family M: 5 tests)
- Data: maddenratings.net team sheets, editions 16-25 (seasons 2015-24; the edition for 2025 has no page: gap) and 27
  (season 2026, live use only). Launch sheets only. Join to nflverse by scripts/names.py key + team, position checked.
  Edition E = season 2000 + E - 1. Mapping check: 5 known players a year by hand before scoring.
- M1-M3 (pXP/60 prior): harness scripts/nfl_rate_research.py data (board replay 2016-25). Rows: player-seasons S+1 with
  100+ snaps, targets 2017-25 (launch sheet of season S+1 is dated before week 1 of S+1), for groups OL, LB, DB (three
  tests). Baseline: the live marcelM projection of rXP/60 for S+1 from seasons through S. Candidate: marcelM + b x
  z(OVR within Madden position, that edition), b by group fit by snap-weighted least squares on the residual, leave one
  target season out. Metric: snap-weighted squared error; cluster: target season. Tune = targets 2017-20, held =
  2021-24 (2025 targets cannot be scored: no edition 26), LOSO b on all other seasons. Vets only (3+ years in the
  league) reported beside all rows; the gate is all rows.
- M4 (OL prior from honours, lead 7b): same rows and gate as M1 for OL, candidate = marcelM + b x (first- or second-team
  AP All-Pro or Pro Bowl in season S; 0/1).
- M5 (OL value for missed games): scripts/nfl_xv.py missed-games test, 2018-24. OL XV part = z(launch OVR within OL
  position) shrunk as other parts; baseline live parts (pen only). Tune 2018-21 / held 2022-24. Pass = held gain in the
  missed-games t (candidate XV vs live XV, paired squared error of the missed-games fit, cluster team-season) >= 2 and
  LOSO team r not lower.
- Ship on pass: M1-M3 -> third signal in nfl_market.signal for that group (flag "EA numbers, fan-compiled" for Noah);
  M5 -> PARTS['OL'].

## Lead 2: reserve-list return hazard (family R: 3 tests)
- Rows: every player-week (season, week w, team, gsis) with a reserve gameday status (RES, PUP, NWT, RSN, SUS, EXE) on
  roster_weekly, regular season, team plays in week w. Outcome for j = 1..4: he misses the team's j-th game after week
  w (status not ACT; row ends when he is off that team's roster file). One log-loss term per (row, j).
- Weeks served = number of consecutive weekly files up to w with a reserve status on that team (1 = first week), bucket
  0 (first week), 1-3, 4-7, 8+ more weeks (i.e. served 1 / 2-4 / 5-8 / 9+).
- R1 (weeks served, all seasons): baseline = P(miss j) by j only (all reserve rows). Candidate = by bucket x j, shrunk
  to the baseline with 40 pseudo-rows. Fit 2016-20, held 2021-25; tune sign from leave-one-season-out inside 2016-20.
- R2 (list code x weeks served, primary): code = status_description_abbr folded to R01, R48, R04, R05 (R06 with it),
  R27/R40/R30/R33/W03 as 'other', blank or anything else 'none'. The codes exist from 2020 only, so fit 2020-22, held
  2023-25, tune sign from LOSO inside 2020-22. Baseline = j only fit on the same seasons; candidate = code x bucket x j
  shrunk (40) to code x j shrunk (40) to j.
- Cluster: season-week of the row. Metric: mean log loss, probabilities clipped to [.001, .999].
- R3 (game test): margin MAE of regular-season games at week w+k (k 1-4), as scripts/nfl_inj_hazard.py gameTest: the
  walk-forward ratings as of week w, coefficient 'ir' x reserve value carried at P(miss j). Old = the placement-based
  'Reserve' row applied to every reserve player (the live rule); new = the R2 table (R1 table before 2020). Tables fit on
  seasons before the scored one. Held 2023-25, tune 2021-22; cluster season-week.
- Ship: R2 pass -> the state table replaces the 'Reserve' row in the later sim weeks and gives the depth chart an
  expected return week, provided R3 held mean difference is not positive (non-inferiority; an R3 pass is not required).
  The 'ir' coefficient, its fade and the game-week input are not touched.

## Lead 3: nfelo (family N: 2 tests)
- N1 (2022 spread opens, coverage/parity): nfelo_games.csv home_line_open. Pass = on seasons where odds_opens.py
  already has an NFL open (2015-21 SBR, 2023-25 ESPN) mean signed gap within +-0.15 and MAE <= 0.85 (the ESPN-vs-SBR
  figure), and >= 95% of 2022 regular-season games get an open. Ship: 2022 opens into the opens store.
- N2 (stack): rows = played games 2021-25 with a ledger row in historic_projected_spreads.csv (home_line_pre_regression,
  sign set so positive = home favoured, checked on r with the result). Baseline = live model walk-forward margin
  (coefficients fit on earlier seasons). Candidate = a x model + b x nfelo, a and b by least squares on ledger seasons
  before the scored one (2021 has none: scored from 2022). Tune 2022-23, held 2024-25. Metric: margin absolute error;
  cluster season-week. Pass t <= -2 held, tune same sign, both held seasons negative. A ledger row is used only if its
  week equals the game's week; rows are append-only as published.
- Display of nfelo as a column: not built (needs Noah).

## Lead 5: all-time NFL coaches (display; descriptive checks, no gate)
- pro-football-history.com coach pages (521 head coaches): year, team, role, record. Team-season rating = points margin
  a game from the repo's game results. Same WAx / cWAR / Score machinery as the other sports in coach_alltime.py.
- Reported checks (as coach-alltime-nov14): mover r, HOF AUC vs raw wins, walk-forward 2000 Score -> next-10-season
  title share.
- C1 (coordinator carry, family C: 1 test): for head coaches whose page lists OC/DC seasons before the first HC season,
  HC WAx (seasons 1990-2025) regressed on prior coordinator team wins over expectation; held by decade (fit on the other
  decades), pass t >= 2 clustered by coach. Fail = shown raw or left out, no weight in Score.

## Lead 6: draft value charts (family D: 1 test)
- Rows: draft-day pick-for-pick trades (no players) 2011-25 from nflverse trades, the mock_trade_history.py deal filter;
  a later-draft pick is valued at the middle pick of its round x .48 per year out.
- Imbalance = ln(value received by the team moving down / value of the top pick it gave). Charts: live curve
  exp(-.148 (pick-1)^.698), stuart, johnson, hill, otc, pff (nfldata draft_values.csv), each scaled to pick 1 = 1.
- Candidate = geometric blend of the six charts, weights on the simplex in steps of .1 minimising mean |imbalance| on
  2011-18. Held 2019-25: paired |imbalance| live minus blend, cluster draft year, pass t >= 2, tune same sign (it is by
  construction), majority of held years. Ship on pass: the blend as the mock's trade curve, then the calibration rerun.
- Display regardless: surplus under each chart (research file; page columns only if the surplus view takes them cleanly).

## Lead 7: honours (display + M4)
- Wikipedia raw pages: AP All-Pro teams and Pro Bowl rosters for seasons 2016-25.
- Table: by position group, AUC of WAR, XV, rXP/60, pXP/60 (and Madden OVR where held) for same-season first-team AP
  All-Pro among qualified players, 2018-25 (XV exists from 2018); bootstrap CI by season. Descriptive, goes to Process.

## Lead 8: ffopportunity (family F: 4 tests)
- Rows: nfl_fantasy.collect player-games at the live memory params, fantasy-relevant pool as evaluate(). Baseline = the
  live walk-forward stat-line ridges. Candidate = the same ridges with one extra column in each of py, ptd, ry, rtd, rc,
  wy, wtd: the player's trailing mean of ffopportunity's expected value of that stat over his last 8 games played
  (this and last season, before the game), shrunk by 2.5 pseudo-games of zero.
- Metric: PPR points absolute error, by position (QB, RB, WR, TE), cluster season-week. Selection 2016-20 (sign), held
  2021-25, pass t <= -2 and Holm over the four. Ship on pass after reading the licence file.

## Lead 9: defender on-field RAPM (family X: 2 tests)
- Plays: dropbacks 2016-25 with pbp_participation defense_players. Per season ridge: outcome (a) pressure for EDGE/DT,
  (b) EPA for CB/S, columns = defenders on the field, offence team-season as nuisance; rating_S shrunk toward decay x
  rating through S-1. lambda in {1000, 3000}, decay in {0, .5} picked on 2017-20 by next-season rating r (stability).
- The part enters nfl_xv only as last season's rating (z within sub-position, shrunk). X1 = EDGE/DT pressure part, X2 =
  DB EPA part. Pass each = LOSO team r higher and missed-games paired t >= 2 (2018-25), later half (2022-25) not negative.

## Lead 10: win totals (expected BLOCKED)
- Confirm no free machine source for 2021-26. If the walk-forward harness is up in time: descriptive test 2015-20 only,
  weeks 1-6 margin MAE with the carried rating blended with a win-total-implied rating (weight fit on prior seasons).
  Cannot ship either way.

## Supporting builds (no test)
- Weekly Madden snapshot ledger (EA drop-api) as its own workflow: logging only.
- FTN 2026 formation tendencies on the personnel tab, reserve-list return board: built only if their lead's data lands
  and time allows; otherwise recorded as not built.
