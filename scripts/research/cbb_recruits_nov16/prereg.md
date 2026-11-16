# CBB recruits pass: pre-registration (2026-11-16, written before any test below was run)

Thread "Improve CBB recruiting, ARKSTARS and FV". Four areas: recruit model / projected FV (one model in CBB: a
recruit's FV is his projected FV), ARK stars incl. the 5-star+ line, crystal ball (commitment lean).
History: scripts/data/cbb_recruit_hist.json.gz (On3 industry classes 2009-25, realized NBA tier rfv), kit
/mnt/project-files/cbb/kit, ESPN classes /mnt/project-files/recruits/commit-distance/espn_classes.

## Prior looks (spent; stated up front)
- data/cbb_recruits.json model.bands: consensus rank 1-5 FV50+ 50%, 6-10 20%, 11-25 11%, 26-50 5.5%.
- stars.plusSweep (held out, classes 2009-16): FV55+ hit rate .44 / .44 / .42 / .44 / .32 / .25 at 1 / 2 / 3 / 5 / 8 / 12
  recruits a class; R2 of realized FV on tier .276 / .280 / .287 / .309 / .296 / .284. The shipped rule (most a class
  within 3 points of the rarest cut's hit rate) gives 5.
- model.calib: predicted 40-45 realized 47.6 (n 37); 45-50 realized 51.2 (n 16); 35-40 realized 34.9 (n 56).
- RESEARCH (Oct 31): isotonic recalibration (MSE t -0.12), linear value part with top-25 hinge (t -1.18, 6/8), kernel
  (worse). Driver fails on file: service gaps, top-5/25 hinges, 5-star+ flag, height for position, weight, program,
  high-major, intl, interest, prep power, commit timing, wide P window, RSCI classes. None is rerun.
- Crystal ball (Nov 14): CBB LIST base LL -1.945, + distance + home state -1.932 (t 3.8). Pipeline, distance x tier,
  distance x grade failed. None is rerun.

## Family FV (recruit model / projected FV). Classes 2009-16, each class held out in turn (8 folds), as shipped.
Baseline = shipped hurdle: P(NBA) logit on lrk + old; log(FV-20) | NBA ridge on lrk, Duan smearing.
Three forms were already tried on the top (above), so the family counts 5: a test needs one-sided p <= .01
(t >= 2.33 over recruits) as the smallest, AND 6+ of 8 classes won.
- P1 Ordinal ladder (continuation ratio). Thresholds T = 30,35,...,80. Rung j: P(rfv >= T_j | rfv >= T_j-1).
  Rung 1 = the shipped P part (lrk, old; lam 1). Rungs for 35..55: logit on lrk, lam 1. Rungs for 60..80: logit on
  lrk, lam 10. Features standardized on the rung's at-risk training rows, clipped +-4, as shipped.
  E[FV] = 20 + 10 P(>=30) + 5 sum_{T>=35} P(>=T). Score: ranked probability score sum_T (P(>=T) - 1[rfv >= T])^2 against
  the shipped hurdle's own P(>=T) (its `above`). Pass: mean RPS gain > 0 at the family t, 6+ of 8 classes, and the
  squared error of E[FV] not worse (t over classes > -1). Ships: FV, P(40+/50+/60+), ceiling and floor read from the
  ladder; ARK star cuts refit on its held-out FV.
- P2 Value part by Poisson quasi-likelihood: E[FV-20 | NBA] = exp(a + b lrk), ridge 2 on the standardized slope, in
  place of log-OLS + smearing (which assumes one residual spread at every rank). P part unchanged. Score: squared
  error of E[FV], paired over recruits; same gate. Reported beside it: mean error on consensus rank 1-5 and 6-10.
  If P1 and P2 both pass, P1 ships.
- No new driver is tested: every field the live On3 feed carries has been through the gate (list above). Sources
  checked today and not usable: USA Basketball U16/U17 rosters (no structured source; Wikipedia event pages carry no
  squads, usab.com all-time roster 404).

## Family LINE (where 5-star+ belongs)
Score = the shipped model's held-out FV (classes 2009-16, class held out). r = a recruit's place in his class by that
score (ties by consensus rank). Elite = rfv >= 55 (All-Star or 6+ seasons as a starter), the band 5-star+ already names.
- L1 Is there a step? Per held-out class c: on the other 7 classes' top 50 by r, fit (a) logit elite ~ ln r + (ln r)^2
  and (b) the same + 1[r <= k], k chosen in those 7 classes by likelihood from {2,3,4,5,6,7,8,10,12,15,20}. Score class
  c's top 50 by log loss. Pass: (b) beats (a) with paired t >= 1.645 over held-out recruits AND in 6+ of 8 classes AND
  the chosen k is the same or adjacent on the grid in 6+ folds. Same test on realized FV (OLS, squared error) reported.
- L2 Forward confirmation (run whatever L1 says; confirmatory only if L1 passes). Classes 2017-20, score from the model
  fit on 2009-16. Early outcome Y = sum of positive NBA value shares in seasons <= class + 6 (history `nba`); event =
  among his class's five largest Y (Y > 0). Step at L1's modal k, added to logit event ~ ln r + (ln r)^2 on the top 50;
  one-sided z >= 1.645 on the step.
- Decision.
  (i) L1 passes and L2's step has the same sign: the line is k.
  (ii) Otherwise there is no step to find and the line is where the label carries the most information: for
  k = 1..15 a class, the held-out R2 of realized FV on the six-tier star (other cuts as shipped, class held out, as
  ark_stars scores it), with a class jackknife SE of each k's gap to the best k. The line stays at the shipped 5 if 5
  is within one SE of the best; otherwise it moves to the best k. Reported for every k: FV55+ and FV45+ rate of the
  tier and of the marginal recruit (slot k alone), mean realized FV, and the same for the 5-star tier left below.
  The line is applied as an FV cut (FV is absolute; the count a class floats).
- A moved line changes stars on the site only after the owner is asked about ARKLIST (filled from the tier Nov 16).

## Family CB (crystal ball, CBB). scripts/recruit_commit_fit.py LIST model, walk-forward, held classes 2015-26.
Baseline = shipped kept terms (pull, tier, gxt, gap, ld, inst). Each candidate is added alone to the baseline.
Gate as Nov 14 (LL gain per recruit > 0, positive in 2/3+ of held classes) with the t over recruits at Holm for 6
tests, one-sided .05: smallest p <= .0083 (t >= 2.40), then .01, .0125, ...
School tables use only seasons / drafts before the class year y (class y enrolls in season y+1).
- K1 Program strength: the school's Barttorvik roster strength z in season y-1 (history `teams`); 0 if unmapped.
- K2 K1 x recruit grade z (added with K1 in the model).
- K3 NBA pipeline: log(1 + the school's NBA draft picks in drafts y-5..y-1) x recruit grade z, with its main effect.
- K4 Open minutes at his position: share of the school's season y-1 minutes at his position group (G / W / B) played
  by seniors and juniors (gone or in their last year when he arrives); position group from Barttorvik role; school
  mean when the recruit's position is unknown.
- K5 Local kink: hometown within 50 miles of campus (on top of log distance and home state).
- K6 Recency weights: training classes weighted .5^((y-1-class)/4) (NIL-era drift), same terms.
Ship: passing terms join the live LIST fit (scripts/recruit_commit_fit.py), leans refreshed.

## Deviations
See README.md.
