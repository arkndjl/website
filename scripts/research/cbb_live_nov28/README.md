# CBB in-season line (Nov 28 2026)

Pre-registration: `prereg.md`. Data: Barttorvik game logs, season files and conference-only season files 2009-10 to
2026-27 (`fetch.py`, into scripts/.cache/cbb, not committed), careers from the kit (`scripts/cbb_careers_kit.py`).
No 2026-27 outcome read; the 2026-27 files are used for the flip replay only.

## Test 1: one source for the season line (`source.py`, `source.json`)

His conference-only file stands in for a file that covers part of the season. 14,585 player seasons. Target: the grade
on his full-season line. Recon fit with the season held out.

| arm | grade RMSE | BPM RMSE (minutes weighted) |
| --- | --- | --- |
| rebuilt on every game | .301 | .922 |
| his file + the rebuilt change since | .242 | 1.588 |
| his part-season file as it stands | .384 | 2.696 |

Anchored against rebuilt: paired t -2.06, better in 14 of 17 seasons. By the share of games his file covers, anchored
is better on both grade and BPM from half the games up (grade .155 vs .270 at .5-.65, t -5.2; .098 vs .198 at .65-.8,
t -4.0; .117 vs .126 and .301 vs .681 above .8, t -.8 and -1.5); under half, the grade ties (t -.15) and BPM is worse
(2.97 vs 1.13). In production his file lags by a game or two, so it covers nearly all of them. Ships
(`cbb_live.line_of`).

Flips (`history.py`, `replay.py`): in the 19 board runs since Nov 20, 510 players' FV went one way and then back with no
fewer games. The cause was the runner getting a page instead of his file on some runs (Ethan Brown, Illinois: 7 games,
BPM 12.6 from his file, 16.6 rebuilt; FV 45, 40, 43, 40, 43, 45). Replay on today's files, his file read against a page
on the same logs: the old rule's FV differs for 617 of 4,701 players, the new rule's for none (each player's last file
row is kept in scripts/data/cbb_bt_lines.json and anchors the runs that get a page).

## Test 2: rXPM in place of BPM in the in-season line (`xpm_live.py`, `xpm_live.json`)

PR #1239 tested the board-form pXPM as the FV fit's input. This is the season-to-date line only: rXPM to date (side BPM
plus the team's minutes-weighted mean of side GBPM minus side BPM over its lines to date) in place of BPM in the "now"
grade, the model unchanged. 2009-10 to 2018-19, nine checkpoints, 403,797 rows, k per arm with the season held out.

| | BPM | rXPM | t | seasons better |
| --- | --- | --- | --- | --- |
| realized rung deviance (x1e-4 a row), all | .4233 | .4232 | -.33 | 6/10 |
| newcomers | .6083 | .6081 | -.27 | 6/10 |
| returners | .3184 | .3184 | -.23 | 5/10 |
| draft AUC (FV 30+), Mar 15 | .9483 | .9482 | | |

Fails (t > -2). The in-season line stays on BPM. Retest registered (`cbb_live_xpm` in data/retests.json) when one more
season has realized FV. (`devAtBoardK` in the json is on a different normalization, the whole group as one set; not
comparable to devOOS.)
