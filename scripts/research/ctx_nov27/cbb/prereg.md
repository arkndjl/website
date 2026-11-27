# CBB context audit, pre-registration (Nov 27 2026, written before any scoring)

Lockbox: no 2026-27 outcome enters any fit or test. Point-in-time inputs from scripts/data/cbb_xpm_hist.json.gz (pXPM
coefficients refit walking forward). Holm over the batch (H1, H2a, H2b, H3). Pass = paired t >= 2 after Holm, most folds
won, guard no worse.

## H1 team builder, next-season player value (cbb_market.py nxt)
- Now: xXPM of this season (at season end: about .85 x XPM to date + .15 x preseason, cbb_live kb 583 returner / 259
  newcomer) + mean next-season BPM change by class (fit['dev'], 20%+ minutes both seasons).
- Candidate: pXPM board form after the season (px2), the number that is fit to next season.
- Target: next-season rXPM of players with a line both seasons, weighted by next-season minutes. Pairs 2014->15 ...
  2024->25 (11); the class change for a pair is the mean over earlier pairs only (from 2011->12 on).
- Score: weighted squared error per pair; paired t over pairs, k/n. Guard: unweighted RMSE among 20%+ minute players
  both seasons (the group the class change was fit on) no worse.

## H2 Transfer% and landing, serve form (cbb_market.py feats_move / feats_land 'bpm' slot)
- Fit form (since Nov 26): px2 after the season. Serve form: the board's xXPM this season, which at portal time is
  about .85 x raw XPM to date (wider scale than px2).
- Test: models fit on px2 (2022-24 offseasons, the Nov 26 protocol, scripts/research/xpm_swap_nov26/market.py); the
  held-out 2025->26 rows scored twice: input = px2 (candidate serve) and input = season-end xXPM emulation (now).
  Emulation: xn = rXPM, n = minutes, xb0 = px2 of the season before (no earlier line: the minutes-weighted mean rXPM of
  first-line players in 2022-24), rate = (xb0 kb + xn n) / (kb + n), xXPM = (xn n + rate kb) / (n + kb).
- H2a move log loss per row (guard AUC); H2b landing log P(school) per move (guard top 10).

## H3 low-division arrival value input (cbb_lowdiv.py bs_of): shrunk rXPM for shrunk BPM
- Target: FV above 20 of the kit's 2009-16 arrivals from below D-I (arrival_frame), the consumer's own. Leave one
  first-season year out (8 folds), the shipped fit_arrive with the shipped 'keep'.
- Score: held-out squared error of the mapped value, paired t over rows; k/8 years. The translation target would
  follow the arrival input only if this passes.

## Not tested, with the reason
- Recruit path year 1-3 "BPM if he plays" and college value (minutes share x (BPM + 3)): a target definition with no
  outside outcome; rXPM adds a team shift a recruit's features cannot see. Follows H3's verdict.
- Game model player values (avail / pre_out on last season's game BPM): needs the full game walk and Barttorvik game
  logs for 2017-26; left as a lead with the rerun command.

# Round 2 (port round), written before scoring

Holm over R1, R2, R3. Same pass rule (paired t >= 2 after Holm, most folds, guard no worse).

## R1 (P2) awards games-left rate (scripts/awards.py cbb draw): prior = pXPM in place of last season's BPM
- Now: rest-of-season mean = (BPM to date x m0 + prior x 300) / (m0 + 300), prior = last season's BPM (8+ games).
- Candidate: prior = his preseason pXPM board form (px2 of the season before, point in time), K 300 unchanged.
  Secondary (reported, not the pass test): K picked on earlier seasons from 300 / 450 / 600 / 900 / 1200.
- Data: Barttorvik game logs 2017-2026 (game BPM by minutes). Checkpoints after the team's 5th, 10th, 15th, 20th game.
  Pool as the race's: 20+ minutes a game to date, played 60%+ of team games, a line last season with 8+ games.
- Target: his minutes-weighted game BPM over the team's remaining games (50+ minutes left). Score: squared error
  weighted by remaining minutes, per season; paired t over the 10 seasons, k/10. Guard: the top 100 by BPM to date
  at each checkpoint (the award pool's top) no worse.

## R2 (P3) xXPM returners: season-only prior value (last season's rXPM and VORX) beside the model prior
- The shipped ridge already holds last season's BPM, 3-season BPM and WAA beside pXPM, so the open form is rXPM / VORX.
  Reduced harness (the full one needs the careers cache): walk-forward least squares, target next-season rXPM weighted
  by next minutes, pairs 2012->13 ... 2024->25. Base = [px2, last BPM, last BPM x minutes share (WAA form), ln minutes].
  Candidate = base + [last rXPM, last VORX]. Downstream score (the rule from NBA T3/T4): next-season team R2 of the
  returners' minutes-weighted projection against their minutes-weighted actual rXPM, by pair; paired t over pairs.
  A pass here is a lead for the full refit (cbb_fit.py --xbpm), not a ship.

## R3 (P5 / P1) backup watch xGap terms, fit before the grade moved to pXPM (data/backup_age.json cbb, Nov 11)
- Pairs as scripts/backup_age_fit.py cbb_pairs but graded as the live grade is now (last season's slot = px2 after
  that season, point in time). Before: the shipped a, b, c (fit on BPM-graded pairs) applied to these pairs. After:
  walk-forward refit on these pairs (the script's own fit()). Score: squared error of the two-season gap on held
  seasons, paired t over pairs, seasons improved.

## Not a test
- P4: the game model's absence terms run the same functions on logs to date in history and live (static read); the
  one check is the roster prior's history rows, which read pXPM from the frozen full-sample coefficients: compare its
  next-season error with the walk-forward pXPM on 2012-2018 lines (a gap over .01 RMSE = a leak worth a walk).
- P6: next up companion column to pXPM (display).
