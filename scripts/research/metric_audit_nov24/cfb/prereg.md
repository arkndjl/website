# CFB metric audit, pre-registration (Nov 24 2026, written before any candidate was scored)

Data: PFN impact rows 2019-25 (FBS; seven positions QB RB WR TE EDGE DL LB graded every season, OL CB S from 2024),
ESPN FBS results 2019-25 -> SRS (the cfb_export ridge). LOCKBOX: no 2026 row, game or score is read (2026 PFN rows
are dropped at export). Exposure = games played / team games filling each position's starter slots (team_adj cfb.py).

Harness (harness.py), main = seven positions 2019-25 (7 describe seasons, 6 predict pairs); ten positions 2024-25 shown.
- describe in-sample: centred team sum of value x exposure vs same-season SRS, pooled R2.
- describe held out: slope (and any weights) fit leave one season out, out-of-sample R2 = 1 - SSE/SS on the left-out season.
- predict team: season n value x season n+1 exposure (newcomers = low-exposure group mean) -> n+1 SRS, pooled R2;
  OOS version with the slope fit on the other pairs.
- predict player: n value (shrunk v E/(E+.2)) vs n+1 value of the same metric, weighted by n+1 exposure (>= .4).
- 90% intervals: 2,000 resamples of seasons (describe) or season pairs (predict).

Metrics scored: PFN impact score (raw), PFN z (Stat+ input), Season AV (sav, q = PFN z), cWAR driver (CWAR_V + SAV_W z),
XV (CWAR_V + XV quality), QB block (PFN QB z, SV/game, pSV/60, NY/A, passer rating -> team offense), team ratings
(SRS, margin a game, win %, ESPN FPI final) on held-out half of games and next-season SRS.

## Candidates (one batch, Holm over the six at alpha .05, one-sided in the stated direction)
Test statistic for each: paired difference in squared error a team-season, out of sample (slope / weights fit without the
scored season or pair), t over team-seasons with season-cluster check (seasons better count reported).

Predictive (target = next-season team SRS from returning value, OOS; secondary player r must not drop > .01):
- P1 Marcel: predictor quality = shrunk mean of PFN z over n, n-1, n-2 (weights 1/.7/.5 x share), toward 0 by K share
  units, K chosen on the other pairs from {.25,.5,1,2}. cWAR line on top.
- P2 Experience: predictor = z + d[exp], exp = prior graded seasons at the position (0,1,2+), d = mean (z n+1 - z n) of
  returning players by exp, fit on the other pairs.
- P3 P1 + P2.
Descriptive (target = held-out same-season SRS):
- D1 Position weights refit: team value = sum over positions w_pos x (z x exposure) + line, w by ridge (lam 1) on the
  other seasons, against fixed SAV_W.
- D2 Schedule: z + c x (PFN sos z within position-season), c fit on the other seasons.
- D3 XV in place of cWAR as the descriptive metric (fixed published weights).

Ship rule: Holm-passing held-out gain on the candidate's own target. Fixed weights fit on 2024-25 (SAV_W, XV) leak into
those seasons; the 2019-23 held-out part is reported apart.

## Memory retests (own bars, as first run)
- R1 CFB QB top-end FV stretch (/mnt/project-files/fv/qb-topend-nov01 qb_topend.py, same rows, same bar t >= 2 clustered).
- R2 CFB team special teams rating as a game-model input vs the close (st_teams.py research cfb, tune 2017-22, held
  2023-25; 2026 left out for the lockbox). Pass = held t clears 2 in the right direction on both the spread and
  held-out error.

## Addendum (Nov 24, after the metric table, before any candidate was scored)
The metric table showed two things the batch did not cover: equal position weights (PFN z) predict next season's team
better than SAV_W weights, and a metric's zero point matters because ~12% of starter time has no graded player. Added to
the same Holm batch (eight tests):
- P4 Predictor position weights refit: next-season SRS on per-position returning sums (z x n+1 exposure), ridge lam 1,
  fit on the other pairs, against cWAR (SAV_W). Equal weights (PFN z) are reported beside it but are post hoc, not a test.
- D4 Ungraded starter time valued at CWAR_V + SAV_W x c (c on the other seasons from -2..0 by .5) in team cWAR sums,
  against 0 (cWAR as is).
Player r is also reported with position means removed (pooled r across positions rewards position constants).
