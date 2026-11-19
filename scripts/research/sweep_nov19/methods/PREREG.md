# Pre-registration: methods worker (Nov 19 2026 sweep)

Written before any score, placebo run, coverage number or fit below was computed. Only data loads, row counts and
robots checks were done. Lockbox: no 2026-27 CBB/NBA/NHL/soccer outcome, no NFL/CFB 2026 game from week 11, no
tennis/CS2 result from Nov 11 2026 is read. Every file is cut to that before use (cut rule per lead).
Pass rule (all tests unless stated): held paired t >= 2 in the improving direction (written t <= -2 on a loss
difference candidate minus base), clustered at the named unit; tune and held same sign; majority of held seasons the
same sign; Holm inside the family at .05 (one-sided p from Student t on G-1 df, scripts/harness.py `paired`, `holm`).
No retune after held, no rescue tests.

## M3. Placebo calibration of the ship gate (idea 3) -- measurement, not a ship test

Rows: scripts/data/games_wf/{nba,nfl,cbb,cfb,nhl,soccer}.json.gz (each model's stored walk-forward number).
Cut: nba/cbb/nhl/soccer S <= 2026; nfl S <= 2025 plus 2026 wk <= 10; cfb S <= 2025 plus 2026 wk <= 10.
Test form ("stack", the form most site tests used): target y and model number m per game:
  nba, nfl, cbb, cfb: y = res (home margin), loss = abs error;  nhl: y = home win, m = logit(p), loss = log loss
  (logistic stack);  soccer: y = home goals - away goals, m = l[0] - l[1], loss = abs error.
Base = walk-forward fit of y on [1, m] (each season from all earlier seasons); candidate = [1, m, z], z the placebo.
The first season in the file only trains. Splits (the ledger's): nba tune 2016-21 held 2022-26; nfl 2016-20 /
2021-26; cbb 2017-20 / 2021-26; cfb 2018-20 / 2021-26; nhl 2018-23 / 2024-26; soccer 2014-22 / 2023-26.
Cluster: game day x home team-season (multiway, harness.paired).
Placebo sources (real inputs of the kind that failed, built from the file itself, known before the game):
  rest = days since last game, home minus away (cap 10; first game 10);
  form5 = mean of the team's last 5 signed model misses (result - m from the team's side), home minus away;
  formS = the same over the season to date.
Placebo recipes, 200 per sport, seed 20261119: source drawn uniformly from the three;
  P1 (100): the source column's values permuted across the games of the same day (football: same week);
  P2 (100): team swap inside the season: each home team-season's ordered series of the source is handed to another
  home team-season of the same season (random derangement, aligned by game number, wrapped when lengths differ).
  Each placebo is standardised (z-score) before use.
Gates scored on every placebo:
  G_old  = tune t <= -1.5 AND held t <= -2 AND majority of held seasons d < 0   (the pre-Nov-19 site rule)
  G_brief = held t <= -2 AND tune d < 0 AND majority of held seasons d < 0     (this batch's rule)
  also the bare one-sided held t <= -2 rate (nominal 2.3% at large G) and the sd and 2.5/97.5 percentiles of the
  held t (a valid clustered t has sd 1).
Output: false-pass rate per sport and gate with a Clopper-Pearson 95% interval, and pooled (1,200).
Decision rule, fixed now: if a sport's (or the pooled) G_brief false-pass rate has its point estimate above 7.5%,
the held bar for that sport moves to the placebo held-t quantile that brings G_brief to 5%; otherwise the gate
stands and the ledger's numbers stand. If the held-t sd is above 1.25 in a sport, that is reported as a finding
(the t is over-dispersed) even when the gate rate is under 7.5%.
Secondary (reported, no decision): the same 200 placebos added as a column of the real NBA design
(nba_games_fit.design + wf, the ledger's drop-one path) if the design rebuilds inside 20 minutes.

### M3b. Replication forecast for the lockbox (registered, scored once at season end by the lead/owner)
From data/model_ledger.json as committed today, terms with verdict keep, source rebuilt (not stored), both a tune and
a held record with d, se, n. Shrinkage s = slope through the origin of held effect size (t / sqrt(n)) on tune effect
size across those terms (sign convention: positive = term helps). For term i: lockbox n_L = n_held / (number of held
seasons); predicted P(same sign as shipped on the lockbox) = Phi(s x e_held_i x sqrt(n_L) / deff_i), with
deff_i = sqrt(held deff). Forecast = mean of those P (expected share same sign) and the 10th-90th percentile of a
Poisson-binomial draw (20,000 draws). The forecast file's sha256 goes in results.md. No lockbox outcome is read.
Scoring at season end: realised share of those terms whose lockbox drop-one d has the shipped sign; the forecast is
"calibrated" if the realised share falls inside the 80% interval.

## M7. Conformal bands with a coverage scorecard (idea 7) -- coverage lead, passes on tolerance

Method (one module, numpy): Mondrian split conformal on signed residuals. For a board with a point prediction f and
(where it exists) a current band [lo, hi]:
  with a current band (CQR form): score = max(lo - y, y - hi); new band = [lo - Q_g, hi + Q_g], Q_g the
  ceil((n_g + 1) x .8) / n_g empirical quantile of the calibration scores in group g;
  without one: lower = f + q_g(.1), upper = f + q_g(.9), finite-sample-corrected quantiles of calibration residuals
  y - f in group g.
Calibration residuals are always out of fold (the board's own leave-one-season/class-out predictions) and from
seasons/classes strictly before the scored one (walk forward; first scored season needs >= 3 earlier ones). Immature
classes are excluded, never truncated.
Boards, rows, groups (group = the cells below; "top band" = the highest):
  cbb_fv   static/data/cbb-past.json top-300 rows of boards 2010-16 (fv_dist_fit.cbb_rows), outcome realised FV,
           current band = fv_dist p10/p90 refit out of fold on earlier classes; groups: grade < 35, 35-44, 45+.
  cfb_fv   fv_dist_fit.cfb_rows (needs the --dist export); groups grade < 45, 45-59, 60+. BLOCKED if the export
           cannot be rebuilt here in 20 minutes.
  nba_3y   nba_proj3y_research rows S 2012-23, target y3y, f = the live form leave-one-season-out with its gap;
           no current band; groups: proj < 0, 0-2, 2+.
  nhl_3y   nhl_proj_research rows S 2010-23 skaters, target y3, f = shipped form LOSO; groups pWAR pace < 0.5,
           0.5-2, 2+.
  nfl_3y   nfl_war_proj_research rows at season end if they rebuild from scripts/data/pctl_hist_nfl.json.gz;
           groups by predicted 3Y WAR tercile cut on the first calibration set. Else BLOCKED.
  rank     rank ranges (rank_odds.py rkLo/rkHi): scored only if rank_odds already stores walk-forward checkpoint
           rows; else BLOCKED (no new walk is built).
Metric: coverage of the nominal 80% band on scored seasons, overall and per group, mean width.
Pass per board = |coverage - .80| <= .03 overall AND in every group with 100+ scored rows, AND (where a current
band exists) mean width <= the current band's mean width. A pass ships the conformal band for that board's range
columns; a fail ships nothing for that board. The "held-out coverage" scorecard (current band and conformal band,
per board and group) is a display-only build either way and reports the numbers as they are.
Family: none (tolerance test); every board reported.

## M8. Venue elevation and the altitude gap (idea 8) -- Holm family of 4 (intl, cfb, cbb, mls)

Elevation: api.opentopodata.org srtm90m for venue/city coordinates (robots open). Gap for a game:
  g = [max(0, V - E_away - 1000) - max(0, V - E_home - 1000)] / 1000   (V venue elevation in m; E a side's home
  elevation), so a sea-level visitor at 2,600 m gives g = 1.6 and two sides from the same place give 0.
intl: rows = soccer_intl.load() history, 2000-01-01 to 2026-07-31. City coordinates from a public city list on
  GitHub (name + country match on the results file's city, country); matches whose city does not resolve get the
  home nation's home elevation when not neutral, else g = 0 (coverage reported; pass needs >= 85% of matches at
  V >= 1,500 m resolved by city). E of a nation = median venue elevation of its non-neutral home matches 1990 on
  (venues, not outcomes). Frozen path: one walk of soccer_intl.run with the shipped parameters (keep=True), then
  log lambda_h += c g / 2, log lambda_a -= c g / 2 on the stored lambdas (ratings not re-updated; never --fit).
  Tune 2000-15: c from the grid 0, .05, ..., .50 by 1X2 log loss. Held 2016 to 2026-07-31, one pass.
  Metric: paired 1X2 log loss vs c = 0, clustered by match day. Pass = held t <= -2, tuned c > 0, majority of held
  calendar years improve, and the CONMEBOL-home half and the rest of the g > 0 matches both improve (sign).
cfb, cbb: rows = games_wf file (cut as M3), non-neutral games; E = home venue elevation of each team (repo venue /
  team coordinate files; a team with no coordinates drops its games, coverage reported). Stack form as M3:
  base [1, m], candidate [1, m, g], walk forward, abs margin error, cluster game day x home team-season; splits as M3.
mls: no walk-forward file in the repo. If ESPN scoreboard history (site.api.espn.com, existing host) for usa.1
  2012-2026-07-31 pulls in under 15 minutes: base = walk-forward Elo with a home term (K 20, home fitted on earlier
  seasons), goal-difference stack as above, tune 2013-19, held 2020 to Jul 2026, cluster by match day. Else BLOCKED.
Ship on a pass: intl -> a pre-registered term in soccer_intl.py without --fit (constant c applied in the home term,
  lockbox score registered); cfb/cbb -> named in the report for the sport worker's refit chain, not wired by me.
The elevation table itself (scripts/data/venue_elev.json) is a data build and is kept either way.

## M10. Career-exit hurdle in the 3Y projections (idea 10) -- Holm family of 3 (nba, nhl, nfl)

Rows, folds, baseline: the multiyear-projections-nov03 designs.
  nba: nba_proj3y_research.load(), S 2012-23, target y3y (shrunk XPM; exit = WASH -2), baseline = the live form
       (H4 if the star script rebuilds it, else F4), leave one season out with seasons within 3 dropped.
  nhl: nhl_proj_research rows S 2010-23, skaters and goalies as shipped, target y3, baseline = shipped form, LOSO.
  nfl: nfl_war_proj_research season-end rows S 2015-22, target y3, baseline = live form (no market term), LOSO.
       BLOCKED if the rows do not rebuild from repo data.
Candidate (one form, no search): stay = any appearance (minutes/TOI/snaps > 0) in S+1..S+3.
  p = logistic regression (ridge 1e-3, Newton) of stay on [1, value, age-27, (age-27)^2, ln(1 + playing time),
  share of team games played] with the same fold rule; cond = the baseline's own form refit on stayers only;
  prediction = p x cond + (1 - p) x exit value (NBA -2; NHL, NFL 0). Contract years left: no point-in-time history
  in the repo, not used.
Metric: squared error on the 3Y target, zeros included, paired; cluster = season (primary), players as units
  reported beside it. Pass = t <= -2 season-clustered, most seasons improve, Holm over the three sports. No tune /
  held split (LOSO, as the baseline's own test); the "tune and held share sign" clause is read as first half vs
  second half of seasons both improving.
"Still in the league" column: p3 = logistic of "appears in season S+3" on the same inputs, LOSO. Ships as a display
  column (labelled a chance, not an edge) only if its out-of-fold calibration holds: in ten equal-count bins, every
  bin |mean p - observed| <= .05, and Brier below the age-only logistic. One check per sport, no family.

## Supporting builds

S1 coverage scorecard: falls out of M7 (data file + Process text via library_add.json). Display only.
S2 mixture SPRT for rule_monitor.drift (simulation only, parity lead). Simulate 4,000 rule streams per cell with the
  monitor's own defaults (sd, bounds A = B = 19, minN from rule_monitor.params(); mu1 = .03; 10 bets a day, rho 0;
  cap 3,000 bets), realization r in {-0.69, 0, .25, .5, .75, 1}. Current test: Wald SPRT H1 r = 1 vs H0 r = 0.
  Candidate: mixture likelihood ratio with a uniform prior on r over a 21-point grid in [0, 1] against r = 0 for
  "confirm", and against r = 1 for "pause" (two one-sided mixture tests, same 19:1 bounds):
  L_pause = mean_r exp(llr(r vs 1)),
  L_conf = mean_r exp(llr(r vs 0)), r on the grid; pause at L_pause >= 19, confirm at L_conf >= 19 with the running
  mean above mu1 / 2. Pass (ship into drift) = false-pause rate at r = 1 <= 5.5% AND false-confirm rate at r = 0
  <= 5.5% AND median bets to pause at r = -0.69 and r = 0 both lower than the current test's. A fail changes nothing.
S3 snapshot audit of mutable feeds: a list (feed, reader, point-in-time?, archived daily?) in the impl folder and
  the repo; archive step only for feeds on hosts the brief allows and only where no archive runs. No test.
S4 estimated-return calibration (RotoWire): display only; built only if scripts/data/rotowire_history covers a full
  season per sport; else LOGGING (the archive keeps growing) with the date it becomes runnable.
