# CFB recruit index, ARK stars, commitment model, recruit xFV: pre-registration

Written 2026-11-16 before any score below was computed. Football only (basketball has its own pass).

## Prior looks (spent, stated up front)
- Seen before writing: data/cfb_recruit_retarget.json (shipped evals: held-out rho nfl .2553, shipped .2476, star tiers),
  data/cfb_recruit_fit.json (board CV, tier calibration: P(on) 5-star .687 predicted vs .779 actual, unrated .421 vs
  .356; the 5-star+ sweep on the board's top 0.5%), the Nov 14 and Nov 15 results (recruit-on3-index-nov14, composite M3).
- Not looked at: any outcome of the 2020 or 2021 classes; any score of any candidate below.

## Data
- History H: scripts/cfb_recruit_retarget.py dataset() as shipped (ESPN 2011-19 signees, 24,450 rows, 1,895 drafted;
  rebuilt today with the same counts). Outcome: drafted, and rfv (mean of NFL AV a season and draft capital on the FV
  scale, undrafted 20).
- Lockbox L (new, never scored): the ESPN 2020 class (drafts 2023-26, the full window) and the 2021 class (drafts
  2024-26, one draft short; reported apart). Same build with CLASSES extended and the 2026 draft read. Outcome for L is
  drafted and draft capital only (AV is not mature). Every model scored on L is fit on H alone.
- Folds on H: 5 folds holding out whole schools, seed 7, ridge LAM 30, as shipped. t values are clustered by signing
  school. One-sided p from the normal.

## Family INDEX (the NFL index's P(drafted) part; 3 tests, Holm at .05)
Baseline = shipped `use` (P: grade, rank, size, level, elo, on3, svc, tm; FV | drafted: grade, elo).
- I1 ordinal fit. The P-part coefficients come from a proportional-odds logit on four ordered bands (undrafted, pick
  101+, pick 33-100, pick 1-32) instead of the binary logit, same blocks, same ridge. P(drafted) is read at the first
  threshold. Loss: squared error of expected rfv (p x max(20, FV part) + (1 - p) x 20), paired over recruits.
  Guard: binary log loss not worse with t <= -2.
- I2 top-end curve. Block: log industry rank (ln 400 - ln rank, 0 past 400 or missing) and a hinge of the industry
  rating at 95 ((rating - 95) / 5, floor 0). Loss: P(drafted) log loss.
- I3 service dispersion. Block: |247 vs industry|, |ESPN vs industry| (the svc block's two gaps in absolute value).
  Loss: P(drafted) log loss.
Gate (all): Holm-adjusted one-sided p <= .05 on the school-clustered t; the candidate wins >= 6 of 9 classes; the mean
gain on the 2020 lockbox class (fit on H) is >= 0 on the same loss (I1: Spearman of the score with draft capital).

## Family STARS (3 tests, Holm at .05, plus one estimate)
Scores on H, out of fold: `shipped` = the live year-3 xFV (retarget stage_b); `index` = the NFL index's expected rfv
(retarget `nfl`). Tiers are cut within each class at the live shares with the top 6 as 5-star+ unless a test says
otherwise. Star outcome = rfv. "Tier R2" = share of rfv variance explained by tier means taken from the other classes.
- S0 stars on the index. Cut ARK stars on the index score instead of the year-3 board xFV (which adds the board's
  position, year and program terms to the index). Gate: per-class Spearman of the star tiers with rfv, index minus
  shipped, t across the 9 classes (one-sided, Holm) and >= 7 of 9 classes; and on L the top 3% by `index` holds at
  least the draft rate of the top 3% by `shipped`.
- S2 absolute line. 5-star+ by a fixed score threshold (set on the other eight classes at the same average count)
  against a fixed count per class. Gate: tier R2 by held-out class, threshold minus count, t across classes (Holm) and
  >= 7 of 9 classes.
- S3 outcome-fit cuts. The four lower cuts (2/3/4/5 stars) placed where they maximise tier R2 on the other eight
  classes (coordinate search over score quantiles), against the live shares. Gate: tier R2 by held-out class, t across
  classes (Holm), >= 7 of 9 classes.
- S1 the 5-star+ line (estimate, on the score S0 picks). For N = 1..40 a class: draft rate, top-32 and top-64 rate,
  starter rate (3+ AV a season) and mean rfv of the top N and of each marginal recruit band (ranks 1-3, 4-6, 7-10,
  11-15, 16-20, 21-30, 31-40), and tier R2 with the top N split off. Decision rule, fixed now: N* = the largest N whose
  marginal band still clears BOTH (a) top-64 rate >= 50% and (b) a top-64 rate above the plain 5-star tier's by a
  one-sided school-bootstrap p <= .05. The line moves from 6 only if 6 lies outside the 90% class-bootstrap interval
  of N*; otherwise it stays. L reports the same table, not used to choose.

## Family COMMIT (the LIST model in scripts/recruit_commit_fit.py, CFB; 5 tests, Holm at .05)
Baseline = shipped kept terms (pull, tier, gxt, gap, ld, inst). Walk-forward by class, held 2018-26, as shipped.
Each term is added to the baseline alone (not forward-chained); passing terms are then refit together and the joint
model must also beat the baseline.
- C1 conversion. log((signed + 1) / (listed + 5)) for the school over the prior three classes: the share of recruits
  listing it that it landed.
- C2 on-field strength. The school's final Elo z of the season before the class year, and its change from the
  season before that (cfbfastR schedules).
- C3 place in his list. Two flags: the top-tier school in his list; the nearest school in his list.
- C4 high-school pipeline. log(1 + signees from his high school to that school in the prior three classes), ESPN
  high-school id with the not_hs() cleaning (a college named in the field counts as missing).
- C5 recency. Same terms, training recruits weighted .75^(held class - 1 - class).
Gate (each): mean log-loss gain > 0 with paired t over recruits, Holm one-sided p <= .05; positive in >= 2/3 of the
held classes; NIL-era (2022+) gain not negative at t <= -1.

## Family XFV (the live board fit, classes 2023-26, school folds; 2 tests, Holm at .05)
Baseline = shipped IDX_BLOCKS in both parts.
- V1 free P(on). P(on the board) is a real outcome (snaps), not a pedigree grade: its part uses the recruit blocks
  directly (the Oct 14 board-fit P blocks, without the 247 composite blocks the live classes cannot read: grade, hinge,
  rank, pos, year, grade_year, pos_year1, size, level, elo, on3, svc) instead of the NFL index. FV(on) keeps the index.
  Loss: P(on) log loss. Guard: the year-3 xFV's Spearman with rfv on H (stage_b form) is not lower with class t <= -2.
- V2 position by year. Block: position dummies x (k - 1) in both parts, on top of V1's winner.
  Loss: P(on) log loss and FV(on) squared error, each part its own gate; both count in the Holm.
Gate: Holm one-sided p <= .05 on the school-clustered t; tier calibration reported.

## What ships
Only what passes its gate. A moved 5-star+ line changes the site's stars; ARKLIST membership is not touched without
the owner's call. No CFBD calls are needed for any test here.
