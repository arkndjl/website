# ARKSTARS top tier (5-star+), CFB and CBB: pre-registration

Written 2026-11-26 before any score below was computed.

## Prior looks (spent, stated up front)
- CFB, Nov 16 (recruits_cfb_nov16): I2 (log industry rank + rating hinge at 95 in the index's P(drafted)) t 2.00, 8/9
  classes, positive on the 2020 and 2021 classes, missed Holm at 3. On those two classes the industry rating held the
  top 3% draft rate better than the index (.46 vs .40) while the index won AUC. Top-64 rate by index place 2011-19:
  1-3 63%, 4-6 41%, 7-10 39%, 11-15 31%, 16-20 40%; plain 5-star 21%. So E1 below is a narrower follow-up of a seen
  lead on mostly the same classes, not an independent confirmation. The clean evidence is the 2022 class, which no
  recruit test has scored.
- CBB, Nov 16 (cbb_recruits_nov16): FV55+ by place 1: 50%, 2-3: 38%, 4-5: 44%, 6-8: 17%; tier at 5 a class 44% FV55+,
  64% FV45+. Service gaps, height for position, program, age vs the old flag: all failed before.
- Not looked at: any top-64 model on the elite pool, any outcome of the CFB 2022 class, position at the top in
  either sport, any FV45+ curve by place.

## CFB data
- H: cfb_recruit_retarget.py dataset(), ESPN 2011-19 signees; the index score (expected rfv) out of fold, 5 school
  folds, seed 7, as shipped. L: 2020 and 2021 classes (drafts through 2026), scored by the index fit on H. F: the 2022
  class (drafts 2025-26: three- and four-year players only), scored by the index fit on H, reported apart.
- Elite pool: per class, the top 100 by the index score plus the top 100 by On3 industry rank.
- Hit: a top-64 pick.

## Family ELITE (CFB; 2 tests, Holm at .05)
A logit for the hit on the elite pool, coefficients from the other classes (leave one class out over 2011-21).
- E0 baseline: the index score alone.
- E1 industry top end: + (ln 400 - ln industry rank, 0 past 400 or missing) and the industry rating hinge at 95
  ((rating - 95) / 5, floor 0). The I2 form, unchanged.
- E3 position: + a quarterback flag and a line flag (OL, DL, EDGE).
Each is added to E0 alone. Loss: hit log loss on the held class. Gate: one-sided p on the t clustered by signing
school, Holm at .05; the candidate wins at least 8 of the 11 classes; mean gain on F (coefficients from 2011-21) >= 0.
Reported, not gated: top-64 rate of each score's top 3 and top 6 a class.
A passing term joins the score that sets the 5-star+ tier only (the star tiers below it stay on the index score).

## CBB data
- Rows as cbb_recruits_nov16/common.py: the shipped hurdle's FV held out by class on 2009-16; forward 2017-20 scored
  by the fit on 2009-16 (NBA through 2026, the 2019-20 classes short of full careers, reported apart).
- Elite pool: the top 50 a class by held-out FV. Hit: realized FV 45+ (two or more seasons as an NBA starter).
  FV 45+ is chosen now as the parallel of a top-64 pick (an expected pro starter); FV 55+ is reported beside it.

## Family ELITE-CBB (1 test)
- B3 position: + a big flag (PF, C) and a point-guard flag on top of the held-out FV, logit for the hit, leave one
  class out over 2009-16. Gate: one-sided p <= .05 on the paired t over recruits, at least 6 of 8 classes, forward
  2017-20 gain >= 0. The E1 analogue does not exist in CBB (the score is the consensus rank already).

## The 5-star+ line (estimate, same rule in both sports)
Rule, fixed now: 5-star+ = the recruits whose held-out chance of the hit is at least one half ("better than even to go
in the top two rounds" / "to start in the NBA"). The chance is the leave-one-class-out logit of the family's winning
score (E0 or B-baseline when nothing passes). The line is the score where that chance is .5, fit on all classes; it
is an absolute score line, so the count moves with the class.
Reported: recruits a class, the tier's held-out hit rate with a 90% class-bootstrap interval, the same for the
shipped line (top 6 CFB at score 39.0; top 5 CBB at FV 41.43) and for the plain 5-star tier under each line, and the
hit rate by tenths of predicted chance (calibration).
The line moves to the rule's value when (a) the new tier's held-out hit rate is at least 50%, (b) its 90% interval's
lower end is above the plain 5-star tier's rate, and (c) it holds at least one recruit a class on average. If the
rule's line is within one recruit a class of the shipped line, the shipped line stays. Forward classes (CFB 2022,
CBB 2017-20) report the tier's hit rate under both lines and do not choose.

## Other sports
Hockey, soccer, tennis and CS2 prospect boards carry FV only, no star tiers and no recruiting class. A term that
passes here is tried there only where the same input exists (position at the top of the board).

## What ships
Only what passes. ARKLIST is a hand list and is not touched.
