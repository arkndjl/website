# NBA context audit, Nov 27 2026: pre-registration (written before any scoring)

Lockbox: no 2026-27 outcome is read. Game rows S <= 2026, player targets from static/data/nba-xpm/ files <= 2026.
pXPM form = scripts/nba_xpm.py pxpm(): three seasons 1 / .35 / .1, k 200 to the role mean, aging curve fit on pairs
ending before the target season. Computed unrounded from the published files, point in time.

Batch of 4 primary tests, Holm at .05 over the primaries.

## T1 game model player value (MISMATCH-P candidate)
- Consumer: scripts/nba_games.py values() (two seasons, w2 .5, n0 300 to -2, no aging), then ARC .25 on top.
- Candidate A (primary): pXPM of season S-1 for every player with an S-1 line; the live value (returner logic included)
  for the rest. ARC .25 and everything else as live.
- Candidate B (secondary): the same without the aging term (aging failed in games Oct 21 and Oct 30).
- Target and harness: game margin, the fit's own walk-forward (scripts/nba_games_fit.py wf on the live feats, as
  scripts/nba_roster_research.py), absolute error.
- Pass rule (the fit's own): paired t <= -1.5 on 2015-21 AND 2022-26 MAE no worse (d <= 0). Guard: 2022-26 MAE.

## T2 depth chart / backup watch grade (MISMATCH-P + DISPLAY: the grade is labelled pXPM, is not pXPM)
- Consumer: scripts/backup_watch.py nba(): seasons n, n-1, n-2 at 1 / .5 / .25 by minutes, shrunk to -1.4 with k 500.
- Candidate: pXPM of season n (his row in the season file); no row = the live grade.
- Target: next season's box XPM, players with 250+ MP next season, squared error weighted by those minutes, target seasons
  2012-2026 (grade formed at the end of n = the state the depth chart opens the next season with).
- Pass: paired t >= 2 on weighted squared-error gain (players as units), a majority of seasons improved, and the guard:
  no worse on backups (under 1,000 MP in season n).
- In-season cuts cannot be rebuilt (no dated XPM files before this season): stated, not tested.

## T3 XPM (proj) prior (MISMATCH-P candidate)
- Consumer: scripts/nba_proj.py project(): prior = nba_xpm.prior_xpm (two seasons, w2 .5, n0 600 to -2; returner rule).
  The same prior feeds the 1Y / 3Y, surplus, contract values and percentile intervals.
- Candidate: pXPM of season S-1 where he has an S-1 line, prior_xpm otherwise.
- Target: season S box XPM, the fit's own rows (50+ MP, not on the prior), squared error weighted by minutes, S 2013-2026.
- Pass: paired t >= 2, majority of seasons, and the guard: the leave-one-season-out 80% interval still covers .78-.82
  after tau / sigma are refit on the new prior.

## T4 1Y projection against pXPM at season end (same quantity, two numbers on one board)
- Consumer: nba_proj.py p1 (H4 form on XPM (proj), age, minutes, history; data/nba_proj3y_fit.json cp).
- Candidate: pXPM as the 1Y. Target: next season's minutes-weighted XPM, 1,000+ minutes, leave one season out for the 1Y
  (its own harness, f = 1.0), S 2012-2025.
- Pass (pXPM replaces the 1Y): paired t >= 2 for pXPM and majority of seasons. If the 1Y wins or ties, the 1Y stays
  (a tested better form for that slot) and nothing changes.

## Not retested (settled; conditions unchanged)
Next up pXPM gap (t 1.42, Nov 26), award voter models (PR #1201), xAAV on pXPM (worse), G League call-up features,
aging inside the game prior on its own, team adjustment inside pXPM, HAPM / LUMA blends, k / weights of pXPM.

## Addendum (written after T3 and T4 ran, before T3b was scored)
T4 showed the 1Y / 3Y get worse when XPM (proj) is rebuilt on the pXPM prior (t -4.1 / -4.9 at season end), so the T3
swap cannot ship as registered: the 1Y / 3Y are consumers of XPM (proj) and the ship rule protects them.
### T3b XPM (proj) on its own target, in season
- Candidate: XPM (proj) = pXPM prior blended with XPM to date (k refit, T3), for the Proj column, interval and surplus only;
  the 1Y / 3Y keep the live-prior XPM (proj) they were fit on.
- Target: rest-of-season XPM implied by the harness's simulated partial seasons (nba_proj3y_research.inputs draws, same
  draws in both arms): (season XPM x MP - to date XPM x MP to date) / MP left, squared error weighted by MP left,
  at f = .1, .2, .35, .5, .75; 100+ MP left.
- Pass: paired t >= 2 (players as units) at every f and a majority of seasons at every f. Counts in the Holm batch.

## Round 2 (port round), written before scoring
### P2 awards games-left rate (scripts/awards.py nba_races x_rest / d_rest: c['sx'], the Nov 4 shrink)
- Candidate A (primary): pXPM form on the to-date line (to-date minutes at 1, the two seasons before at .35 / .1, k 200 to the
  role mean, aging term as the board's sxpm carries it). B: the same without aging (the rest of this season, not the next).
- Harness: scripts/awards_asof.py inputs (in-repo boxes, 2019-2026, shares .25 / .5 / .75, the 'box' stand-in for XPM to
  date, ridge fit leaving the season out). Target: the rest-of-season stand-in XPM (same ridge on the box line after the
  checkpoint), 200+ minutes left, squared error weighted by minutes left; total and defense.
- Pass: paired t >= 2 pooled (players as units) and a majority of seasons, on the total; defense no worse. Then the guard:
  winner log loss of the as-of races no worse (run only if the rate passes).
### P3 season-only rXPM / VORX of prior seasons beside the prior in the 1Y / 3Y
- Live H4 already carries the two seasons before as box XPM (d1, d2, reliability-weighted). A: d1 / d2 on rXPM (txpm) instead.
  B: H4 + the two prior seasons' VORX (vorx on rXPM, per 82 team games).
- Harness and target as T4 (leave one season out, 1,000+ window minutes), every f. Pass: t >= 2 at f 1 on the 1Y or 3Y,
  neither target worse (t > -2) at any f, majority of seasons.
### P4 / P5: code and fit-date checks; a refit only where the fit's input changed after the fit.
### P5a next up ceiling input (found in the P5 check; written before scoring)
- nba_ceiling_research.py reads `sxpm` (pXPM since Nov 24); the build serves sx0. Candidate: pXPM as the ceiling's input, fit and
  serve. Target: pinball loss at .80 on next-season XPM, held out by season, the shipped final columns.
- Pass: t >= 2, majority of seasons, coverage .78-.82. Fail: the research script is pinned to sx0 so a refit matches the serve.
