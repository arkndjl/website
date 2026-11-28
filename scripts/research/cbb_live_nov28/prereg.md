# CBB in-season line (Nov 28 2026), written before the runs

No 2026-27 outcome is read. The 2026-27 files are used only for the flip replay (does the source change between runs).

## Test 1: one source for the season line

The live board takes Barttorvik's season line when his file covers the game logs' games (within one), else the line
rebuilt from the game logs (LIVE_FIT recon). The two differ (Ethan Brown, Illinois: BPM 13.0 in his file over 8 games,
16.7 rebuilt over 7), so the grade flips when his file lags.

Past seasons have no dated copies of his file. His conference-only file (getadvstats conyes=1) is his own line on a
known part of each season, so it stands in for a file that covers only some of the games. Seasons 2009-10 to 2025-26,
players whose conference games in the logs match that file's games, 40+ minutes in all.

Target: the grade on his full-season line (what next preseason's board reads), the board's own model (data/cbb_fit.json),
as next_career() builds it. Arms, each recon fit with the season held out:
- A: the rebuilt line on every game (always rebuilt);
- B: the rebuilt line on every game, each recon stat shifted by his file minus the rebuild on the games his file covers
  (his line plus the rebuilt change for the games since).
Primary: squared error of the grade against the target, paired t clustered by player (harness.paired), and seasons
better of 17. Secondary: BPM RMSE against his full line, minutes-weighted.

Gate: an arm is a candidate when it is not worse than the other held out (t < 2 against it). B ships if it is not worse
than A, since it equals his file whenever his file covers every game. Otherwise A ships. The flip replay must show no
source change for a player between two runs a game apart.

## Test 2: rXPM in place of BPM as the in-season FV input

rXPM to date = each side's BPM plus the team's minutes-weighted mean of (side GBPM - side BPM) over the team's lines to
date (the board's XPM). The in-season "now" grade reads rXPM (and its sides) in place of BPM in this season's line.
Earlier seasons stay as they are. PR #1239 tested the board-form pXPM as the FV fit's input (failed held out); this
test is only the in-season line, the model unchanged.

cbb_live_backtest design: seasons 2009-10 to 2018-19 (realized FV), nine checkpoints, the in-season blend with k fit per
arm with one season held out on realized rung deviance. Score: held-out realized rung deviance per row, paired t by
player, seasons better of 10. Pass: t <= -2 and better in 6+ of 10 seasons (the backtest's own gate for k). Secondary:
draft AUC (FV >= 30) of the blended grade by checkpoint.
