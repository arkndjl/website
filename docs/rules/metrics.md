# Metric definitions

Names are Noah's. Don't rename a metric without his call; renamed ones keep an alias for old links.

## Shared

- **FV**: future value, absolute true talent on 20-80, headline = mean outcome (see models-tests.md).
- **Stat+**: 100 + 25 per SD.
- **yNIL / xNIL / zNIL**: yNIL = what a player was likely paid going into the season (reported school budgets shared
  by the whole roster); xNIL = what he is worth on the NIL market now (position price x on-field value; never fit
  to On3 valuations); zNIL = xNIL - yNIL (development), per player, team, coach.
- **Ret%**: return-to-school odds for both drafts. **Transfer%**: transfer odds, NIL era only.
- **DECT** (Declare, Even, College, Transfer): decision metric in dollars, separate from Ret% and Transfer%. Never
  "DoR", "DTR", "DEC", "Return", "Equal" or "Toss Up". Detail in CLAUDE.md.
- **ARK stars**: ARK's own recruit stars. **5-star+** (CFB): ARK five-star with P(top-64 pick) over 50%; CBB keeps
  five a class.
- **ARK Ranking**: the team rating used as the headline rank everywhere it applies.
- **Unit badges**: top 25%, display only (they failed every game-model test).
- **ARKLIST**: Noah's hand-picked list, `data/arklist.json`.

## Basketball

- **NBA XPM** = rXPM (same thing): team-adjusted, the #1 descriptive metric. **pXPM** = 3-season weighted, 200-minute
  shrink to role mean plus aging (predictive). **VORX** = value over replacement on team-adjusted rXPM.
  **ARC** (.25) is a game-model input only.
- **CBB XPM** = rXPM: BPM + team mean (GBPM - BPM), per side. **CBB pXPM**: predictive; the box form stays in FV
  and the game prior. **xXPM**: next-season projection. **CBB VORX** (was WAR) =
  (shrunk XPM - R) x min/40 x .68 x .0187, R by position (G, F, C): -1.4 + the position's offset among the 9th-12th men,
  last three finished seasons (Nov 28 2026).
- Qualified NBA and CBB boards sort by XPM, all-player and value boards by VORX; XPM sits before VORX (Noah, Nov 28).

## Replacement levels (Noah, Nov 28 2026)

- Every stat with a replacement level is recalibrated on a schedule and is position-aware: the level is a fitted, dated
  parameter from the current qualified or freely available pool, by position. `scripts/repl_levels.py` writes
  `data/repl_levels.json` (every sport's lines and a change-only history), weekly inside process-refresh.yml; never a
  new workflow.
- A position split or a refit level ships only after it passes held out (models-tests.md); a failed one is registered in
  `data/retests.json`. Nov 28: CBB VORX by position passed; NBA VORX by position and a refit level failed (NBA keeps
  -1.4, tracked); NHL, NFL and soccer WAR were already by position and refit in their own runs; NHL's lines pooled over every season beat the last three seasons on next season's line (F RMSE .051 vs .060, D .085 vs .082, G .173 vs .178), so they stay pooled.

## Football

- **NFL WAR**: two-way, including K, P, KR, PR. **XV**: Noah's own AV for CFB (WAR on stat-line parts that track
  winning). CFB RB/WR FV carry a return term; CFB punters use net yards.

## Hockey and soccer

- **NHL WAR** descriptive, **pWAR** projection.
- **Soccer SV / SVAR**: goals over replacement; the Ballon d'Or model runs on SVAR.

## All-time lists

- Era-adjusted, and every list passes the era gate. Tennis all-time lists on season SV.
