# Port round, NHL + soccer + NBA (descriptive only): pre-registration (Nov 24 2026, written before any candidate was scored)

Harnesses reused: round-1 NHL (scripts/research/metric_audit_nov24/nhl/audit.py: seasons 2009..2026, 17 pairs) and
soccer (../soccer/audit.py: 2015..2026, 11 pairs, big five, GD a match centred by league-season). NBA: ESPN box lines
scripts/nba_pbox_hist.json.gz (2019..2026) + bbref team table (project files cbb/xpm/teams.csv, players.csv) + the
rXPM season files static/data/nba-xpm/<S>.json, S <= 2026. LOCKBOX: no 2026-27 file is opened (NHL 2027, soccer 2027,
static/data/nba-xpm/2027.json never read). NBA pXPM is another thread's and is not touched.
Data checks done before writing this (no metric scored): soccer team minute coverage (player minutes / 11 x 90 x matches)
is .995 a season (the gap is red-card time), except 2020 (1.03, ESPN vs Understat match counts) and 2021 (.970, Understat
missing matches); the Understat match cache (scripts/.cache/soccer/usm) and any shot-level data are not in this container.

## Not testable / skipped (decided now)
- (a) idea 1 soccer, game-state adjusted xG for p/90: needs shot minutes + score state (Understat usm or FotMob shot maps);
  none cached. Not testable.
- (b) idea 2 soccer SV/SVAR from match-level values: needs per-match player values (usm); not cached. Not testable.
- (b) idea 2 NHL WAR from game-level values: the stats-API game logs carry goals, assists, shots, +/- and ice time but no
  player-game xG (MoneyPuck player game files not cached), so game-level WAR cannot be built. Not testable.
- (f) idea 7 NHL home-rink player offsets: every team plays 41 home / 41 away, so a player's home offset sums to ~0 in a
  season's team total; no plausible signal on the season predict target. Skipped (prereg).

## Candidates (one Holm family of 6, alpha .05, one sided; each judged on its own target)
N3 (NHL descriptive WAR, idea 3): team WAR sum + c x uncovered skater hours (5 x the team's goalie hours - its skater
   hours, from the split parts), c per held-out season from the grid -1.0..+1.0 by .1 goals a 60 on the other seasons;
   slope LOSO as round 1. Target held-out describe R2 (team GD a game). Per-season paired t on held-out SSE share.
N4 (NHL predictive, idea 4): pWAR rate replaced by a Marcel on season-only descriptive WAR (dr): weights 1, w, w^2,
   w in {.25, .5, .75}, K in {400, 800, 1600, 3200, 6400} minutes toward the F / D / G mean dr of regulars (500+ min) in
   seasons <= n; no age term. Grid picked leave-one-pair-out on team R2. Base = shipped pWAR (HPM, flurry adjusted xG,
   nested weights). Target predict team R2; guard player r (vs n+1 WAR) not down > .01.
N6 (NHL predictive, idea 6): pWAR rate = HPM - season n replacement HPM of the position (F / D / G, players outside each
   team's top 13 F / 7 D / 2 G, as season_table), i.e. pWAR a 60 with the position's value over replacement added back.
   Target predict team R2; same guard.
S3 (soccer GAR, idea 3): team GAR sum + c x uncovered 90s (11 x matches - player 90s, floored at 0), c per held-out
   season from -.30..+.10 by .02 GAR a 90 on the other seasons; slope LOSO. Target held-out describe R2.
S3b (soccer SV/SVAR, idea 3): the same on SVAR.
   Sensitivity (not a test): S3 / S3b without 2020 and 2021; a pass whose sensitivity t is below 1 is not shipped.
B2 (NBA descriptive, idea 2): rXPM-G = per-game mean of a game-level team-adjusted box value. Game box score (Hollinger
   weights where the ESPN line has the stat): PTS + .4 FGM - .7 FGA - .4 (FTA - FTM) + .5 REB + .7 AST + STL + .7 BLK - TOV,
   FGM = (PTS - 3PM - .77 FTA) / 2, FTM = .77 FTA; a 48-minute rate minus the game's minutes-weighted mean, then every player
   in the game moves by one amount so 5 x the minutes-weighted mean = the team's game margin x 48 / game minutes.
   Season value = unweighted mean over his games with 10+ minutes (as GBPM). Team value = sum of value x his minutes share
   of the team's minutes x 5 (ESPN minutes). Target: held-out describe R2 on team win% (rXPM is built to sum to net rating,
   so net is not a fair target; win% as CBB D1), slope LOSO, seasons 2019..2026 (8). Base = rXPM (txpm, bbref minutes).
   Reported beside it, not tested: the same box value anchored once a season (minutes-weighted), BPM, and both on net.
Test for each: per-season (describe) or per-pair (predict) R2 difference, t over seasons / pairs, one-sided p (normal),
Holm over the 6. Pass = Holm significant gain AND guard AND more than half the seasons / pairs better. Ship = pass.

## Diagnostic (not a candidate)
- Soccer idea 6: p/90 is already a rate over the position's replacement line (Marcel on SVAR a 90, shrunk to the SV
  regulars' position mean), i.e. the pXR form. Reported: team predict R2 of p/90 vs p/90 minus its position mean.
- Idea 8 (duplicate games): NHL games, soccer ESPN game log, NBA game log + box: same date + same teams counted twice.

## Amendment 1 (Nov 24, after N3 / N4 / N6 and S3 / S3b were scored; B2 not yet scored)
N6 scored team R2 .403 -> .485 (17/17) but failed its guard (player r .370 -> .344). Its size suggested the n+1 exposure
level, not position value: once a rate's mean is not 0, a team's summed n+1 skater ice time a game (shorter with more
penalty kill time) enters the prediction. Check (not a new test, nhl_n6check.py): (i) one constant for every skater;
(ii) N6 and base with each team's n+1 skater ice time rescaled to 5 hours a game, goalies to 1 (lineup shares). N6 stays failed (guard)
whatever the check shows; the check decides only what the lead is told about the NFL pXR pass.
S3 exploratory (post hoc, not a test): c grid widened to -2.0..+0.2 after the prereg grid's edge (-.30) was picked in
the no-2020/21 sensitivity.
Note (after the first run of the check): rescaling skaters to 5 x goalie ice time left a leak (goalie ice time a game is
shorter for teams that pull the goalie more, i.e. trail more), so (ii) was changed to fixed lineup shares, 5 skater hours
and 1 goalie hour a game; both runs are reported in README.md.
