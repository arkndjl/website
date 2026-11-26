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
