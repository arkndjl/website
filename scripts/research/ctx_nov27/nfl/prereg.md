# NFL context audit, Nov 27 2026: pre-registration (written before any scoring)

Data: the board replayed 2016-25 (`prep.py`: whole season and through week 9). No 2026 rows anywhere. Point-in-time
pXP/60 for (season S, point) = the live form (`scripts/nfl_rate.py`: S to the point, S-1, S-2 at 1 / .7 / .5, shrunk
to the sub-position mean moved by the market signal of S) rebuilt from those rows. K, the sub-position means and the
market slopes are the live fit's (data/nfl_rate_fit.json: structural, fit on 2016-25; the caveat the Nov 24 audit
carried). Holm over the three tests, alpha .05.

## T1 depth chart / backup watch grade (scripts/backup_watch.py nfl)
- Now: board WAR this season / (snaps + 300) x 1,000 (season only, shrunk to replacement).
- Candidate: pXP/60 (the board row's `pxp`).
- Rows: players with 50+ snaps through week 9 of S and 100+ snaps in weeks 10 on, 2016-25.
- Target (primary): his weeks 10+ rXP/60 (points over the sub-position's average regular per 60 snaps, from season
  total less through week 9), weights = weeks 10+ snaps. Both grades and the target are centred within season x
  sub-position (the tab compares a backup with the starter at his own slot); the grade's slope is fit on the other
  seasons (leave one season out), scored as weighted squared error on the held-out season.
- Secondary: whole-season grades of S against S+1 rXP/60 (100+ snaps in S+1), same scoring, 2016-24.
- Guards: (a) same-team same-sub-position pairs (more snaps = starter): share of pairs where the grade names the
  player with the higher weeks 10+ rate, must not fall; (b) the primary with XV a snap as the target (2018-25),
  must not be worse at t >= 2.
- Pass: primary paired t <= -2 (player rows, weighted), most held-out seasons better, secondary not worse (t < 2),
  guards hold.

## T2 xAAV (scripts/xaav.py nfl, live form M4/sqrt)
- Now: last season's board WAR and the one before, snaps, games, age by position.
- Candidate: M4 + pXP/60 at the end of the season before the signing, by position (M5).
- Rows: scripts/xaav.py nfl_rows on the replayed boards (signing years 2018-26, contracts from OverTheCap via nflverse;
  2026 signings are offseason contracts, not 2026 outcomes).
- Target: AAV / cap, leave one signing year out (xaav_lib.loyo, sqrt form as live), MAE in cap %.
- Guards: top-end calibration (topCal, 7%+ contracts) stays inside .85-1.15; forward split (fit before 2022, test on)
  not worse.
- Pass: paired t <= -2 on absolute error, most signing years better, guards hold.

## T3 1Y / 3Y WAR projection (scripts/nfl_war_proj.py, form E)
- Now: board WAR of S, S-1, S-2, snaps, age by group, market read.
- Candidate: form E + pXP/60 by group (F).
- Rows: board players at the end of S (f = 1) and through week 9, S = 2018-24 (y1) and 2018-22 (y3); targets next
  season's board WAR before special teams and the next three, 0 when off the board. Leave one season out, RMSE.
  A re-implementation of scripts/nfl_war_proj_research.py's design on this audit's replay (its own frames need an
  83-board replay); the E baseline here must land near the stored fit's RMSE or the test is void.
- Pass (the rule form E passed): paired t <= -2 at week 9 and at the season's end on both targets, most seasons.

## Rule fixes, no test
- Next up tab shows WAR/17 as its rate stat: a predictive tab, so pXP/60 (display only; the odds do not read it).
