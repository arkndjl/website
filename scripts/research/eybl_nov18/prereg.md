# EYBL production as a CBB recruit prior: pre-registration, Nov 18 2026

Written before any score. Source: eybl-stats.netlify.app ("EYBL Scout 2026"), 2026 Nike EYBL 15U/16U/17U, snapshot
/mnt/project-files/research/eybl-nov18/ (search-index.json + data bundle, taken Nov 18 2026). No other season exists, so
no player in it has a college outcome today. Nothing ships before the trigger.

## Sample
2026 17U players matched to the class of 2027 recruit list through scripts/names.py (name + team/HS + class + position),
an EYBL row counts with 150+ estimated possessions. Unmatched rows are dropped, not imputed. Match rate is reported.

## Predictor
x = EYBL BPM Blend (possession-weighted across stints), standardized inside 17U, entered as the residual after a
regression on the live recruit model's projected FV (rank + old), so it can only add what rank does not already carry.

## Tests (one family, Holm at .05)
- E1: freshman 2027-28 CBB box BPM (board value, 200+ minutes) on projected FV + x. Gate: x coefficient t >= 2 (HC1),
  sign positive, held-out MSE (leave-one-conference-out) not worse than projected FV alone.
- E2: end-of-freshman-season board FV minus preseason projected FV on x. Gate: same.

## Ship rule
Pass in 2027-28 = provisional term; it goes live only if the class of 2028 (2026 16U rows) confirms with t >= 1.5 and the
same sign after 2028-29. A fail is final for this source on these classes.
