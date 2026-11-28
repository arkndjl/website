# Team builder years 2 and 3: pre-registered test (written Nov 28 2026, before any result)

Noah: "make college team builders better with expanded depth charts, recruit lookaheads for multiple years of
recruiting classes". The builder projects next season (the plan). This adds the two seasons after it, from what is
on the roster and committed today, and asks whether that roster chain says more than the team's strength today.

## The roster chain (point in time, origin season y, horizon k = 1, 2, 3)
Each player on the roster at the end of season y is on the same team in y + k with the chained chance of staying a
season at his class (Fr, So, Jr, Sr; a Sr stays a Sr), read from the three origin seasons before y. His value moves
with the mean change of stayers at each class (same three seasons). The committed class of y + 1 enters as freshmen
on the same chain. Talent_k = the sum over players of P(there in y + k) x value above replacement.
- CBB: value = pXPM after the season (the kit's px; BPM when missing) less replacement (-3), times his minutes share;
  a recruit's value is the fresh BPM from his rank and the freshman minutes fit (data/cbb_market_fit.json fresh).
  Rosters: Barttorvik player seasons (scripts/data, cbb_market_fit.player_rows). Strength: season SRS from the games.
- CFB: value = the 247 composite rating above .80, x 10 (no season FV history exists before 2025); rosters by season
  from cfbfastR (ESPN athlete ids, class year), rating joined by name and class window from the CFBD recruit pack;
  unmatched players count .80. Strength: season SRS from the FBS games (scripts/data/cfb_hist_md.json.gz).

## Model and gate
z = strength or talent standardised within its season. Base: z(y + k) = a + b z(y). Candidate adds c z(Talent_k).
NIL era origins only, targets before the 2026-27 lockbox: CBB y = 2022-25 (k = 1), 2022-24 (k = 2), 2022-23 (k = 3);
CFB y = 2021-24, 2021-23, 2021-22. Leave one origin out. Pass for a horizon: held-out squared error lower with paired
t >= 2 (clustered by team) and lower in every held-out origin but at most one. A horizon that passes is shown with
the fitted (a, b, c) on all its origins; one that fails is shown with the base only (strength regressed to the mean),
and its roster list stays as a list.
The CFB composite stands in for FV in the history; live, the same composite chain is used so the fit applies as fit.

## Player development (added Nov 28 2026, Noah: "project development using aging curves / predictive statistics")
Written before any result. CBB only: CFB has no season-by-season FV before the 2025 board, so its development test is
registered as a retest (data/retests.json) and the CFB chain keeps the class means.
- Target: a player's value k seasons on (pXPM after that season, the kit's px), any D-I team, k = 1, 2.
- Base: his value now plus the class means (the chain as tested above).
- Candidate D1: a ridge on his class, age against his class's mean age, his value now and his minutes share (a curve
  that lets good players regress and young ones grow), fit on the origin seasons before the test one.
- Gate: walk forward over origins 2022-25 (k = 1), 2022-24 (k = 2); squared error lower, t >= 2 clustered by team, and
  lower in every origin but one. Then the team test above is rerun with D1's values in the chain; it ships only if the
  team test is no worse at every horizon (t > -1 against the class-mean chain).
