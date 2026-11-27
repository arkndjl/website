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
