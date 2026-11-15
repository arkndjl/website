# FV pass, Nov 15 2026: pre-registration

Written before any candidate here was fit or scored. Lockbox 2026-27 is not read by any test.

## Not run (and why)

The saved leads are each registered for a later trigger in `scripts/data/ledger/retests_2027.json` or in memory,
with "no look before the trigger". Running them now on the same samples would be a second look.
- Tennis recency h=4, gluck, gapmx, WTA age top slope, ATP tree forward: trigger = ATP and WTA year-end rankings final.
- Hockey draft gbm stack: trigger = 2020 class after 2026-27.
- CFB grade to outcome map (p .035), CFB height at 1.5, TE line, unit context: trigger = 2024-25 drafts mature.
- Basketball international FV: another thread.
- NBA and NFL carry no FV grade (their draft grades are the CBB and CFB boards).

## Family (Holm at .05 over every test below that is scored)

### Hockey (frozen rows, 2008-19 classes, class-out; scripts/data/hockey_rows.json.gz)
- H1 two-part draft grade. Outcome FV has a mass at 20 (no NHL game). p = logistic(any NHL game) on the live kept
  inputs; m = OLS of outcome FV on the same inputs among picks with an NHL game; grade = 20 + p * (m - 20), clipped
  20-80. Same inputs as live (ls, ls2, D, G, nhle, cs); logit ridge 1.0 like the OLS. No tuning.
  Gate: class-out fold t >= 2 and 8/12 classes, top-64 picks MSE not worse, forward (fit 2008-15, grade 2016-19) MSE
  and top-64 MSE not worse. If it passes, stage models are refit on the new fv0 and must not get worse at any stage
  (class-out MSE).
- H2 goalie save% over league at stage 4 (gsvc k4) with class strength nested: registered Nov 11 as "retest at next
  hockey refit". Scored as the board's own selection reports it (t >= 2, 8/12). Counted in the family.

### Soccer (only if the caches rebuild; Oct 24 rows, cohort-out)
- S1, S2 keeper top slope / keeper location, exactly as registered Nov 4 (sweep-nov04/intl/prereg.md).
- S3 two-part grade as H1 (logistic any positive outcome value x OLS among positives, live kept inputs), compared
  with the live linear part before the tree blend and isotonic map; shipped only if the full live chain with the
  two-part linear part beats the live chain cohort-out (t >= 2, 6/8) with top-50 and forward not worse.

### CS2 prospects (walk-forward cutoffs, held = cutoffs from HELD on, targets end before Nov 11 2026)
- C1 teammates' mean rating over the last year (rounds-weighted mean rating of the four he played with) added to
  rating + age + S/A share. Gate: held weighted-MSE t <= -3.3 (the board's Bonferroni cut) and lower MSE.

## Corrections (not hypothesis tests; shipped if the defect is confirmed)
- CFB outcome horizon (audit Nov 9 FV-1): AV a season is divided by seasons elapsed, so the same slot is worth 1.9x
  for a 2023 draftee as for a 2015 one. Fix = equal-horizon outcome. Any weight change after the fix goes through the
  harness's one-weight-at-a-time stage with BH q .10 and the top-32 and forward gates, as on Oct 26.
- CBB live grade level (audit Nov 9 lead): summed live NBA odds 327 against 226 on training boards. Find the cause;
  a fix ships only if a simulated live board on past seasons shows the same excess and the fix removes it.

## Amendment 1 (Nov 15, 23:05Z; written after H1, H2 and C1 were scored and before any test below was fit)

Results so far: H1 t -0.79 (fail), H2 t 1.96 9/12 (fail, same as Nov 11), C1 held t +3.33 worse (fail).
Checked and dropped from the corrections list: the CFB outcome horizon was already fixed Nov 11 (scripts/cfb_horizon.mjs,
weights unchanged on it); the CBB live level is 265 summed NBA odds against ~226 on a training board after the Nov 9
floor fix, no defect found. Soccer S3 (two-part) is withdrawn unscored: H1 failed and the soccer grade already has a
tree blend and an isotonic map.

Added to the same Holm family (family size = every test scored: H1, H2, C1 and those below):
- H3 hockey draft, Central Scouting rise: crise = ln(midterm rank) - ln(final rank) for a skater ranked on both lists
  (same list), else 0. One more input on the live kept set. Gate: board rule (class-out t >= 2, 8/12), top-64 and
  forward not worse.
- W top-weighted least squares (the fit minimises error where the board is read). First pass = the live fit inside the
  training fold; weight w = 1 + max(0, g0 - 30) / 10 on each training row (g0 = its first-pass grade); refit with w.
  No tuning of the weight form.
  - W1 hockey draft model. Gate: top-64 picks MSE gain, class folds t >= 2 and 8/12; all-picks MSE fold t > -2;
    forward (fit 2008-15, grade 2016-19) top-64 MSE and Spearman not worse.
  - W2 tennis ATP, W3 tennis WTA: October rows, births 1979-97, live kept inputs, finished births only (the selection
    harness); w on both the logit and the given-value OLS. Gate: MSE on rows whose base grade is 40+, birth-year
    folds t >= 2 and 13/19; all-rows MSE fold t > -2; forward (fit births <= 1993) top-50 realized mean not lower.
- Soccer S1, S2 stay as registered Nov 4 and run only if the rebuild completes.

Note: the amendment's clock time above was estimated; the file write was at about 22:58Z by the container clock. Order of events is as stated.

## Amendment 2 (23:01Z container clock; written after H3, W1, W2, W3 were scored: all fail; before T1 was fit)

- T1 hockey stage tree blend (stages 1-4; the Nov 9 tree test and its 2027 retest cover the DRAFT model only; the stage
  models, where the comps already pass at k3-4, have never had one). Stage grade = .5 x live linear stage model (kept
  inputs as in data/hockey_fit.json, comps included where kept, no preseason share) + .5 x HistGradientBoosting
  (depth 3, lr .05, 300 iters, leaf 40, l2 1, seed 0: the settings of the shipped soccer blend) on every stage input
  (wjc, progp, ahls, nhgrow, fv0, nh, nh_na, nhD, pro, age, gp, war, G, D, nany, dur, gsvc; no comp, no pnS), class
  held out, stage rows as fit() builds them (class-out draft grade as fv0).
  ONE family test: per class, the mean over stages of the class-out MSE gain; one-sided t over the 12 classes, Holm
  with the rest of the family (H1, H2, H3, W1, W2, W3, C1, T1, and S1/S2 if scored).
  Ships at a stage only if the family test passes AND that stage's own gate holds: class-out t >= 2 and 8/12, top-64
  picks MSE not worse, forward (fit 2008-15, grade 2016-19) MSE and top-64 MSE not worse, and each class's top 32 by
  grade realize a mean no lower. Where the stage has a preseason fit, the blend with that linear part must also not
  be worse class-out.
