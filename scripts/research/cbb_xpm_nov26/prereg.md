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

## rXPM round 3 (new thread, Nov 26; Noah: "make rXPM beat BPM descriptively as much as possible")
Written before any round-3 candidate is scored. Scripts: gl.py (game-log tables), rxpm4.py -> rxpm4.json.
Seasons 2008-09 ... 2025-26 (Barttorvik player game logs exist from 2007-08). No 2026-27 data.

Why round 2's D7/D8 are not taken as they stand: their team shift injects the team's RAW (not opponent-adjusted) net
rating, and both T1 (raw win%) and T2 (even-game raw win% / raw margin) reward a soft schedule, which odd and even games
share. A metric that rates a player up for his team's schedule is not a better description of the player. Round 3 scores
every candidate on schedule-neutral targets; D8 is rescored on them (S0 below) before anything else.

Definitions (per season): team-game margin per 100 possessions from summed player points; adjusted margin
a_g = margin + (opponent adjEM - league mean) - h x venue (h fit pooled, home +1 / away -1 / neutral 0), D-I opponents only.
Rotation = players with 8+ games and 10+ minutes a game played, on that team.

Tests
- A "who sat out" (credit split between teammates; the team constant cancels): for team-game g, L_g(v) = minutes-per-game
  weighted mean of v over the rotation players who appeared in g. y = a_g - team season mean, x = L_g - team mean of L.
  Pooled no-intercept slope fit on the other seasons, scored on the held-out season's team-games with x != 0: SSE.
  Season ratings are full-season for every metric (BPM cannot be rebuilt without the game), so the comparison is like for like.
- B split half, leak-free: values from a team's odd games only (by date), any team anchor from odd games only (odd-game
  adjusted margin; opponents' adjEM is the full-season figure, the team's own never enters). Target: the team's even-game
  mean adjusted margin, predictor = even-game minutes x odd-game values (players without odd games take the mean of the
  odd-game sub-150-possession players). And even -> odd. Held-out slope (other seasons), per-season SSE.
  Baselines here: odd-game GBPM (possession-weighted game BPM) and BPM-like (odd GBPM shifted to the odd-game adjusted margin).
- C team level, full season (audit harness): adjEM describe; WAB a game (Barttorvik, schedule-adjusted wins) describe; raw
  win% reported for continuity with rounds 1-2 but NOT a gate.
- Guard G (player metric): SD (300+ minutes) within 1.5x GBPM's; no box weight above 3 points per SD.
- Guard N: next-season team R2 (audit.predict) not below the better of BPM / GBPM by more than .005, player r not lower by > .01.

Candidates
- S0 round-2 D8 (GBPM shifted to .75 raw + .25 adjEM) rescored on B and C: expected to fail; documents the schedule point.
- X1 blend a BPM + (1 - a) GBPM, a in {0, .25, .5, .75, 1}, a chosen leave-one-season-out on test A.
- X2 college box weights on top of the X1 base: v = base + d . z, z = 13 season rates per 100 possessions played
  (2PM, 2P miss, 3PM, 3P miss, FTM, FT miss, ORB, DRB, AST, TOV, STL, BLK, PF) z-scored on the season's rotation players
  x e/(e + 200); d fit by ridge (lambda in {30, 100, 300, 1000}, inner leave-one-season-out) on test A's regression across
  the training seasons (Torvik's BPM weights were fit to NBA RAPM; this refits the split between teammates on college
  games, 18 seasons of absences). The correction is made zero-sum within team (minutes weighted) so team sums = the base's.
- X3 X2 fit per side: offence on adjusted points scored per 100 (vs opponent adjDE), defence on adjusted points allowed.
- X4 partial pooling of the per-game team constant: game BPM's team shift is per game (GBPM) or per season (BPM);
  value = BPM + k x (GBPM - BPM) is X1; X4 instead reweights games by minutes share stability: skipped unless X1 picks
  an interior a (then X1 already covers it).
- W1 win credit: X-best shifted a minute per team to (1 - c) adjEM + c x WAB-equivalent margin, c in {.25, .5}; needs to
  pass B (not worse than its base at t < -1) to count; expected to fail B (luck does not repeat).
Ship rule: rXPM = the candidate that beats BPM AND GBPM on test A (paired t over 18 seasons, Holm over X1-X3, 12+/18
seasons) without losing test B to odd-game GBPM (t > -1), with C adjEM >= GBPM's and guards G, N. If none beats both,
report which baseline is the better describer on A/B and keep it (no rXPM).
Cross-sport: a passing piece (college-fit box weights via absences; BPM/GBPM-style blend) is tried in each sport with an
analogue: NBA (box weights vs rXPM on NBA game-log absences), NHL / soccer / NFL / CFB where a game-log box metric exists.

### Round 3 amendment (after test A was scored: X2 beat BPM t 4.25 15/19 and GBPM t 10.4 19/19; before B, C, G, N)
Test A's appearances are partly a coach's choice (a 10-minute ninth man plays in blowouts), which could tilt the box
weights toward bench traits, and season ratings include the scored game. Added robustness guards for X2 (rxpm5.py):
- R1 starters only: core = 20+ minutes a game, 8+ games; x = sum over core players who appeared of (mpg/40) x (v - the
  team's non-core mean); X2's weights FROZEN from test A's leave-one-season-out fits must still beat BPM (t > 1).
- R2 leave-the-game-out ratings: box z and game BPM recomputed without game g (BPM_loo = BPM - (pgBPM - pgBPM_loo));
  X2 refit must still beat BPM (t > 1).
- N strengthened: next-season team R2 with X2 must not be below X1's (the same base without the box weights) at t < -1;
  the zero-sum correction only moves the team sum through who stays and who leaves, so this checks the weights on
  roster turnover, independent of in-season appearances.

### Round 3 amendment 2 (after rxpm5: B, C, G, N, R1, R2 scored; before rxpm6)
Read so far: X2 fails the ship rule as written. B: every team-anchored value loses to the un-anchored odd-game GBPM at
describing the other half (.841 vs .883; BPM-like .824), a half-season team anchor carries 15 games of noise; S0 (D8)
drops to .688 there, and loses on the raw target too once the anchor is odd-games-only. R1: frozen weights tie BPM (t .08).
R2 is invalid as designed: a leave-the-game-out rating moves against the game's own box score (jackknife anti-correlation),
so the refit "wins" with weights of 11 a SD and the frozen fit loses; it says nothing. Replaced by R2b.
rxpm6.py (no new candidate family; settles whether the box weights are real and which base share to carry):
- a profile: X2 with base share a in {0, .25, .5, .75, 1}, lambda fixed at 30 (A's pick in 18 of 19 folds), on A.
- R1 refit: box weights refit on starters-only rows (cleanest absences) and frozen-from-A; compared with BPM and own base.
- R2b half-split who-sat-out: ratings from one half of the team's games (game BPM mean; BPM minus the other half's game-BPM
  share; box z of that half), scored on the other half's games; frozen-from-A weights and refit.
The weights count as real if frozen-from-A weights beat their own base on R1 and R2b (t > 1 each) and N's X2 vs X1 holds.

### Round 3 amendment 3 (after rxpm6; before rxpm7)
rxpm6: with the box weights in, a = 1 (BPM base) is best on A (.00568, t 5.44 vs BPM 18/19), R1 and R2b, so the base is
BPM and the team sums stay BPM's (adjEM anchor, as NBA rXPM keeps the net-rating anchor). Frozen-from-A weights: R2b
t 5.79 (17/19), R1 t .93 (11/19): short of the t > 1 bar on starters, and A's weights on missed twos / turnovers flip
sign in the starters refit (the bench-appearance worry was right for those two).
rxpm7.py: one weight set must hold in all three absence designs. Weight sets = fit on A, on R1 (starters), on R2b (half
split), and on the three stacked (each design's rows scaled to unit x variance), all leave-one-season-out, lambda 30,
base BPM. Each set is scored on each design (frozen d, slope refit on the training seasons). Ship the set with the highest
minimum t vs BPM across the three designs, provided that minimum is above 1 and guard N holds for it (next-season team R2
not below BPM's at t < -1). Otherwise no box weights ship.

### Round 3 amendment 4 (after rxpm7/rxpm8; before rxpm9)
rxpm7/8: no box-weight set clears every gate. Starters-fit weights pass the three absence designs (t 5.65 / 1.94 / 4.66)
but lower next-season team R2 (.6419 -> .6371, t -2.07) and the split half (t -8.8): they pay for made threes, i.e. shooting
luck. A-fit weights pass A, R2b, N (t 3.27) but tie on starters (t .7 < 1). By the amendment-3 rule no box weights ship.
Standing facts on the two baselines: BPM splits credit better than GBPM in all three absence designs, describes adjEM
(.9996 vs .9954) and next season (.642 vs .611) better; GBPM describes schedule-adjusted wins better (WAB .888 vs .880).
The one open pre-registered candidate is the team anchor (W1). rxpm9.py scores it with one added family (W2):
- W1: BPM shifted a minute per team to (1 - c) adjEM + c x wins-equivalent, c in {.25, .5}; wins-equivalent = the team's
  mean of (win - P(average D-I team wins that game)) from opponent adjEM and venue, rescaled to adjEM points (pooled slope).
- W2: BPM shifted to the team's mean capped adjusted game margin, cap c in {10, 15, 20, 30} points per 100 (rescaled to
  adjEM points, pooled slope): a 40-point win counts as a c-point win.
Gates (all): WAB a game describe above GBPM's (paired t over 19 seasons, 12+/19) AND adjEM describe >= GBPM's AND test B
(odd-game anchor of the same kind -> even-game mean adjusted margin, both directions) not below the plain odd-game anchor
(BPM-like) at t < -1 AND next-season team R2 not below BPM's at t < -1. Credit split is BPM's by construction (the shift is
one number a team), so A/R1/R2b equal BPM's. The c is picked leave-one-season-out on WAB among the values that pass B.
If one passes: rXPM = BPM re-anchored that way. If none: no rXPM; boards lead descriptive tabs with the better baseline.

## pXPM round 2 (Nov 26, after rXPM round 3; Noah: "make pXPM beat BPM predictively as much as possible")
Written before any block is scored. Script pxpm2.py -> pxpm2.json. Baseline v1 = research X2 at its modal parameters
(O: w .35/.2, K 200, BPM; D: w .6/.4, K 100, 25% GBPM), walk-forward as before (pair n fit on pairs <= n-1), ridge 10
on every added term. Target and harness unchanged (next-season side BPM; audit.predict_rows; 14 pairs 2012-2025).
Blocks (each per side where it has sides; all from season n or earlier):
- F1 late form: possession-weighted game BPM (side) over the player's last third of possessions minus his season mean,
  x e/(e + 200) (game logs).
- F2 recruit rating: Barttorvik rec (0-100, 0 if none) x class (Fr, So, Jr+), plus a has-rating dummy x class.
- F3 team context: the season-n team's adjOE / adjDE (centred, own side), and x class Fr.
- F4 role: G / F / C dummies (Barttorvik role) and height x Fr.
- F5 shape: squared shrunk history, minutes share, change in minutes share vs the prior season.
- F6 consistency: SD of game BPM (possession weighted, season z, x reliability).
- F7 age: age at the next season's Nov 1 minus 21 (dob column; clipped 17-26), and its square.
Rule: score each block alone on v1; then add blocks in order of their single t (next-season team R2, paired over 14
pairs), keeping a block only if it lifts the running model at t > 2 and player r (vs next BPM) does not fall. v2 = v1 +
kept blocks. v2 ships if it beats v1 at t > 2 with 10+/14 pairs, player RMSE not higher, and then holds where pXPM is
used: roster prior team R2 (roster_wf protocol) not below v1's at t < -1, FV returner driver (fv.py protocol) not worse.
Production note: a block that needs game logs or the team file must be available on every line source or it is carried
only where it exists and the fit stores the fallback (zero).

### Round 3 amendment 5 (after rxpm9; before rxpm10): the two-part form H
Every test so far reads one of two parts of a metric: the split of credit inside a team (who sat out: A, R1, R2b see only
within-team differences) or the team total (C sees only the minutes-weighted team sum). BPM wins the first, GBPM the wins
side of the second, and X1's single blend weight has to trade one for the other. H takes each part from its winner, with
no fitted number:  H_i = BPM_i - team mean(BPM) + team mean(GBPM)   (means minutes weighted over the team's players).
Known before running (by construction): A, R1, R2b = BPM's; C (adjEM, WAB, win%) = GBPM's. Not known: N, B, G.
Ship rule for H as rXPM: (i) who-sat-out better than GBPM in all three designs, t > 1 each; (ii) N: next-season team R2
not below GBPM's (the incumbent descriptive metric, today's WAR input) and player r not lower than GBPM's; (iii) B: H
built from odd games (BPM-like deviations + odd-game GBPM team mean) not below odd-game GBPM at t < -1; (iv) G: SD within
1.5x GBPM's. Reported against BPM as it falls: WAB / win% (expected better), adjEM (expected .9954 vs .9996, BPM's own
anchor), N.
