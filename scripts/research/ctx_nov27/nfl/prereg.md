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

## T1b backup watch xGap input (added after T1 was scored, before any T1b number; Holm now over four)
T1 as registered: primary (weeks 10+) FAIL, secondary (next season) the other way. The tab ranks by xGap, the gap
projected over the next two seasons (scripts/backup_age_fit.py), so its own target is the two-season one. The NFL has
no fit of its own there (it borrows the other pros' terms). This test uses that script's design on the NFL replay.
- Pairs: season S 2016-23, team x sub-position; starter = most snaps, a backup = any other with 50+ snaps.
- Target: backup's minus starter's board WAR per 1,000 snaps over S+1 and S+2 (snap-weighted, shrunk to 0 with 300
  snaps, gone = 0): backup_age_fit's target in the live grade's own units.
- Models: target = a + b gap + c (starter age - backup age); gap = the live grade's gap (now) or the pXP/60 gap.
- Walk-forward as the fit: season S is predicted from pairs whose target was complete before it (S' <= S-3), test
  S = 2019-23. Scored as paired squared error over pairs.
- Guard: the same on the pairs the tab lists (backup's live grade above the starter's).
- Pass: paired t <= -2, most test seasons better, guard not worse (t < 2). Shipping it = xGap on the pXP/60 gap with the
  NFL's own a, b, c; the grade shown and the listing rule stay on this season's WAR a snap (T1 primary).

# Round 2 (port round), registered before scoring. Holm over R1-R4, alpha .05.

## R1 = T3 above, on this audit's replay (season's end and week 9, S 2018-24 for y1, 2018-22 for y3)
Baseline = form E (live). F = E + pXP/60 by group (+ a flag for a rate row). Pass as T3.
## R2 season-only XV of S, S-1, S-2 beside the prior (P3)
G = E + XV a 17 games of S (pace), S-1, S-2 (pooled slopes; 0 and the has flags when absent; XV exists 2018 on, so
S-1 / S-2 are absent for S 2018 / 2018-19). Same rows, same pass rule as T3.
## R3 pXP/60 in the percentile projections' rate prior (scripts/player_pctl.py Rate.prior), downstream
Now: Marcel WAR a snap 1/.7/.5 shrunk to the group rate. Candidate: the same prior plus slope_g x pXP/60's market
shift (the part pXP/60 has and this prior lacks), slope fit leaving the season out. Downstream target: next-season WAR
= rate x next-season snaps actually played (so the exposure model is held fixed), S 2018-24, squared error, leave one
season out. Pass: paired t <= -2, most seasons. If the frames replay finishes in time the fit is rerun through
player_pctl.py --fit instead and its own calibration table is the guard.
## R4 predictive awards, games-left rate (scripts/awards.py football_draw, NFL)
Now: this season's box rate a team game. Candidate: (now x g + last season's rate a team game x g0) / (g + g0), no
last season = .85 x now (the NBA draw's rule), g0 from (2, 4, 6, 8, 12) picked on the training seasons.
Rows: after week 9 of S = 2016-25, the top 40 to date in each of passing yards, scrimmage yards, offensive TDs, sacks.
Target: his rate a team game in weeks 10 on, squared error in units of the stat's own target SD, leave one season out.
Pass: pooled paired t <= -2, most seasons, no single stat worse at t >= 2.
