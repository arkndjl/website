# NHL context audit, Nov 27 2026: pre-registration (written before any scoring)

Data: static/data/nhl-war/2009..2026.json only (season files in the repo; 2027 = 2026-27 is never read). Note the
files' pwar / hpm sit on the latest fit's weights, which favours the "before" side of both tests.

Family of 2, Holm at .05 on the one-sided season-clustered p.

## A. Predictive awards: games-left WAR rate (scripts/awards.py nhl_draw)
- Mismatch: the predictive draw runs the games left at `pwar / toi` and adds it to descriptive `war`; the voter models
  read descriptive WAR. Settled pick for a player's own future WAR is Marcel WAR, and pWAR sits on another scale
  (its own replacement level, goalies near 0).
- Before: pwar_n / toi_n. After: Marcel WAR rate = (war_n + .7 war_n-1 + .5 war_n-2 + K mu_grp) /
  (toi_n + .7 toi_n-1 + .5 toi_n-2 + K), the projections tab's form (MARCEL 1/.7/.5, K 1600 minutes, mu = the group's
  WAR a minute over the seasons before n: walk forward). K fixed at the projections tab's stored 1600, not tuned here.
- Target: WAR_n+1 (descriptive), prediction = rate x toi_n+1. Rows: toi_n >= 200 and toi_n+1 >= 200, n = 2011..2025.
- Score: squared error per player; season means paired (15 seasons), t = mean diff / se, k = seasons improved.
  Also the award pool: each season's top 50 by WAR_n plus goalies with 20+ GP (MSE and Spearman).
- Pass: all rows t >= 2 and k >= 10/15, and the award pool's MSE not worse (guard), Spearman in the pool not lower by
  more than .01.
- Ship if pass: nhl_draw reads the Marcel WAR rate (this season to date as the newest season) when not SEASON_ONLY.

## B. Backup watch grade (scripts/backup_watch.py nhl; depth chart grade)
- Mismatch: a player-level predictive grade on HPM (pWAR's rate); the settled player pick is Marcel WAR.
- Before: the live grade: hpm weighted by toi x (1, .5, .25) over n, n-1, n-2, shrunk to the file's replacement with
  600 minutes (goalies 1500). After: Marcel GAR a 60 (gar, weights 1/.7/.5, K 1600 minutes toward 0 = replacement).
- Pairs (fixed, not grade dependent): season n, team (last listed), position (C, L, R one starter; D two; G one) by
  ice time; each of the next 2 x shape players by ice time with 100+ minutes against each starter.
- Target 1 (neutral, primary): the backup's ice time a game in n+1 is above the starter's (both 20+ GP in n+1).
  Logistic on the standardized grade gap, fit on seasons before n (from the 5th season), log loss on n.
- Target 2 (guard): the pair's GAR a 60 gap in n+1 (both 200+ minutes), linear walk forward, MSE.
- Pass: target 1 log loss lower with season-clustered t >= 2 and k >= 2/3 of seasons, target 2 not worse.
- Skaters and goalies scored together; goalies also reported apart.

# Round 2 (port round), written before scoring. Family of 2, Holm at .05.

## C. xGap own fit with the Marcel WAR gap (P1; the grade stays HPM)
- Pairs and target exactly as scripts/backup_age_fit.py (HPM grade, backup above the lowest-graded starter, target =
  the pair's HPM gap over the next two seasons). Before: a + b gap + c age gap. After: + d (Marcel GAR a 60 gap,
  1/.7/.5, K 1600 minutes). Walk forward as fit(): paired squared errors, t; seasons won.
- Guard: the pair's descriptive GAR a 60 gap over the next two seasons (same shrink), same walk forward, not worse.
- Pass: t <= -2 on the harness target, most seasons won, guard not worse.

## D. Awards Marcel WAR rate: newcomer mean for players with no prior season (round 1 lead)
- Rows: season n players with no row in n-1 and n-2, toi_n >= 200 and toi_n+1 >= 200, n = 2012..2025.
- Before: shrink to the group's mean WAR a minute over seasons before n. After: to the mean of such newcomers
  (same seasons before n). Target WAR_n+1 at known ice time; season means paired.
- Pass: t >= 2 and 2/3 of seasons.
