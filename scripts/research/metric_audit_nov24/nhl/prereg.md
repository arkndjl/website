# NHL + hockey prospects metric audit, pre-registration (Nov 24 2026, written before any scoring)

Data: MoneyPuck season summaries 2007-08 ... 2025-26 + NHL stats API games and game logs (team split). Lockbox: 2026-27 not
read (seasons 2009 ... 2026 only; 2027 files never opened). Harness: scripts/research/team_adj_nov24/core.py conventions
(exposure = ice time hours per team stint, result = regular season GD a game, shootout goal removed, centred a season).

## Metrics scored (season n rate a 60, players with no value filled by the position mean of low ice time players)
- WAR: descriptive goals a 60 over average (`dr`, nhl_players.describe_split). Ours, descriptive.
- pWAR (HPM, nested): Marcel HPM through season n on the weights refit through season n (nhl_hpm_nested.json.gz `w`;
  seasons before 2015 share 2015's weights). Ours, predictive.
- pWAR (HPM, board): same on the stored all-sample weights (data/nhl_war_fit.json), as the season files show it.
- Marcel WAR: the projections tab's descriptive WAR Marcel (1/.7/.5, 1,600 minute shrink). Ours.
- GSAx a 60: goalies only, skaters 0. Ours (goalie column).
- Points a 60 (g + a1 + a2, centred). Traditional.
- MoneyPuck game score a 60 (centred). Public.
- 5v5 on-ice relative xG (evf + eva). Public (MoneyPuck derived).
- Team level: MoneyPuck team xG differential a game, score and venue adjusted xGD, GD itself (describe same season GD,
  predict next season GD).
- Hockey prospect FV: reported from data/hockey_fit.json (class held out MSE vs draft slot); not rescored.

Tests: describe (pooled R2 in sample; held out = slope fit leave one season out, R2 = 1 - SSE/SST), predict team R2
(season n rates x season n+1 ice time), player r (n vs n+1 own value, n+1 ice time weighted, 500+ minutes). 90%
intervals by resampling season pairs (2,000 draws).

## Candidate changes (Holm family of 4, alpha .05, one sided)
- D1 (descriptive WAR, target held out describe): drop the penalties term (drawn minus taken x league net PP goals a
  penalty). The power play xG it creates is already credited through the PP on-ice xG and the team leftover share, so
  the term may double count. Pass: held out describe R2 up, per season paired t, Holm p < .05.
- P1 (pWAR, target predict; memory retest "NHL PP xG weight"): add the Marcel power play on-ice xG component at .2 (the
  descriptive per skater share, 1/5) to HPM. The game model ppw retest itself needs 2026-27 (lockbox), so this is the
  player metric analogue.
- P2 (pWAR): 5v5 on-ice relative xG (evf, eva) from MoneyPuck's score and venue adjusted xG instead of raw xG.
- P3 (pWAR): evf, eva and ixg from flurry + score + venue adjusted xG.
  P1 to P3 keep the nested weights fixed (no refit on the tested seasons). Pass: predict team R2 up with per pair paired
  t, Holm p < .05, AND player r not down by more than .01.
Not tested (already failed, team memory): pWAR aging, team adjustment, KG / K grids, desc WAR blend in rv, EDGE, early
season shrinks, the PP weight in descriptive WAR on describe (team sums are invariant to it by construction).

## Amendment (Nov 24, written after the scoring run; the D1 invariance was spotted while writing audit.py, the refit check
## was added after P3 passed)
- D1 withdrawn as a test: the team's leftover xG share is computed after the penalties term, so each team's summed WAR
  is unchanged by it (and by the PP weight). audit.py still prints the check (describe .97833 vs .9783, identical to
  rounding). No descriptive candidate is left in the family; Holm family = P1 to P3 (3).
- Player r uses season n+1 descriptive WAR (the common outcome) for every metric; ownR (same metric n+1) is reported
  beside it, since pWAR's n+1 Marcel window overlaps season n.
- Confirmation for a passing P candidate (not a new family member): refit_check.py, pWAR's own gate (team design, stored
  K / KG / Marcel / lambda / kept inputs, weights refit per input set), leave one season out and walk forward.
