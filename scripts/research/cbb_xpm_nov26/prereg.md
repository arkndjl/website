# CBB XPM (Nov 26 2026) — pre-registration

Noah: "create XPM for college basketball to improve upon BPM", then "test XPM as a FV driver for CBB vs BPM".
Written before any candidate is scored. Data: Barttorvik getadvstats csv + team results 2008-2026 (no 2026-27: lockbox).
Harness: scripts/research/metric_audit_nov24/cbb/audit.py (same targets, fill, pairs 2012-13 ... 2025-26, 14 pairs).

Not retested (failed, see memory): lineup RAPM delta on a BPM prior (Nov 3, worse than box at every lambda, 2 seasons
of subs only), on/off blends, team adjustment of BPM to adjEM for prediction (Nov 24), BPM+GBPM blend for prediction (P4).

## rXPM (descriptive)
Baselines: BPM (held-out win% R2 .633, adjEM .9985), GBPM (.658 / .995, today's WAR input).
- R1 side blend: O = (1-a)OBPM + a OGBPM, D = (1-c)DBPM + c DGBPM, a, c in {0,.25,.5,.75,1}, chosen leave-one-season-out.
- R2 GBPM team-adjusted per side (O to adjOE - mean, D to mean - adjDE; one shift a minute per team, core.adjust).
- R3 R1's blend, then R2's adjustment.
Pass: held-out win% R2 above GBPM's (paired t over seasons, Holm over 3) AND adjEM describe >= BPM - .001.

## pXPM (predictive)
Baselines: BPM (next-season team R2 .643, player r .680), roster prior BPM_hat for returners/transfers, same fill (.757 / .762).
Per side s (O, D), player at season n, walk-forward (fit only on pairs m with m+1 <= n), target = next-season side BPM
weighted by next-season minutes:
  h_s = sum_k w_k e_k x_k / sum_k w_k e_k over seasons n, n-1, n-2 (w = 1, w2, w3), x = (1-g) BPM_s + g GBPM_s
  s_s = (E h_s + K mu_s) / (E + K), E = sum w_k e_k, mu_s = mean of < 200-minute players in the training seasons
  X1 (history): y = b0 + b1 s_s + class step (Fr/So/Jr/Sr dummies) + b2 ln(1 + e_n/100)
  X2 (history + box): X1 + z-scored stable rates (stl, blk, orb, drb, ast, to, ftr, 3PA/100, rim share, usage, TS, height),
     ridge lambda 10 on the box terms
  Grid w2 {0,.35,.6,1}, w3 {0,.2,.4}, K {0,100,200,400,800}, g {0,.25,.5}; chosen by leave-one-pair-out player MSE
  inside the training pairs.
pXPM = O + D. Pass vs BPM and vs roster prior: next-season team R2 higher (paired t over the 14 pairs, Holm over 4 tests:
X1 and X2 each vs BPM and vs BPM_hat) and player r vs next BPM not lower by more than .01.

## Downstream (cross-sport rule), only for a metric that passes above
- FV driver (Noah's ask): pXPM (and rXPM) in place of bpm3, and added beside it, as a CBB returner driver in
  cbb_fit's nested class-fold protocol; score = the board's own held-out loss; head to head vs bpm3.
- Roster prior / game model: pXPM in place of the last-line BPM in cbb_roster's returner projection (team R2 first;
  game-model walk only if the roster test passes).
- NBA mock conviction: pXPM in place of 3-season BPM.
Lockbox 2026-27 untouched.

## rXPM round 2 (Noah, Nov 26 19:55Z: "Is there anything we can do to get a descriptive rXPM to pass?")
Written before any candidate below is scored. Script: rxpm2.py -> rxpm2.json. Seasons 2013-2026 (14; Barttorvik player game
logs {y}_all_advgames start in 2012-13). No 2026-27 data.
Game logs give, per player-game: game BPM (O/D), possessions x minute share, box counts, opponent, location; team margin
from summed points. Every value is season-only (the descriptive rule): nothing from another season enters a player's rXPM.
Baseline: Barttorvik season GBPM on the same harness (audit.drows, team win%, leave-one-season-out slope).
- D1 pgBPM: possession-weighted mean of the player's game BPMs (minute share x team possessions).
- D2 D1 with blowouts down-weighted: game weight x 1 / (1 + (|margin per 100| / m)^2), m in {10, 20, 40}, LOSO.
- D3 D1 opponent-adjusted: game BPM + k x (opponent adjEM, same season, centred), k in {0, .1, .2, .3, .5}, LOSO.
- D4 GBPM + same-season box correction: team-level ridge of win% on [sum GBPM, sum of 12 within-season box z
  (stl, blk, orb, drb, ast, to, ftr, 3PA/100, rim share, usage, TS, height) x e/(e+200)], lambda in {1, 10, 100}, LOSO;
  player rXPM = GBPM + (c / b) . z.
- D5 metric blend: team-level LOSO regression on minutes-weighted sums of GBPM, BPM and total PRPG per minute; player
  rXPM = the fitted weights' sum.
- D6 D2/D3 value (their LOSO choices) + D4's box correction.
Not tested: same-season stint RAPM / box weights fit to RAPM (NCAA.com substitutions exist for ~1.5 seasons only, the
Nov 3 RAPM prior already failed there); team adjustment (failed round 1).
Gate T1 (ship): held-out win% R2 above GBPM's: paired t over 14 seasons, Holm over D1-D6, and better in >= 9/14 seasons.
Guard T2 (within season, held-out games): values from each team's odd-numbered games (by date) only, box z from those
games; target = the team's even-game win% and margin per 100 possessions; candidate must not be worse than D1-on-odd
games (the same-split GBPM) at t < -1 on either. Guard T3: held-out adjEM describe R2 reported (no gate).
Cross-sport: a passing piece (box correction, blowout weight, opponent adjustment) is then tried in each sport's
descriptive metric with an analogue (NBA rXPM, NHL WAR, CFB/NFL XV, soccer SVAR) on that sport's describe harness.

### Amendment (added after D1-D6 were scored, before D7/D8 were)
D4/D6 beat GBPM on T1 (.650 -> .788) and T2, but D4's player weights are not a player metric (+16.5 rating points per SD
of DRB rate, -6.5 per SD of height): the team-level ridge hands team four-factor / schedule information to whichever
players carry the box rate. Added guard G (all candidates): player rXPM SD (300+ minutes, minutes weighted) within
1.5x GBPM's, and no box weight above 3 points per SD. Added candidates (the NBA analogue, team information spread
equally a minute, as NBA rXPM does with raw net rating):
- D7 GBPM team-adjusted to the team's raw (unadjusted) net rating per 100 possessions from the game logs: one shift a
  minute per team so 5 x minutes-weighted mean = raw net rating (round 1 adjusted to adjEM and failed).
- D8 the same shift to alpha x raw + (1 - alpha) x adjEM, alpha in {.25, .5, .75}, LOSO on T1.
T1 + T2 + G as above (Holm over D1-D8); T3 adjEM reported.
