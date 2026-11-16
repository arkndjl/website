# CFB recruit pass, 2026-11-16: results (prereg.md written and committed first)

Rows: ESPN 2011-19 signees (24,450; 1,895 drafted), school-held-out folds. Lockbox: 2020 class (2,726; 174 drafted,
drafts 2023-26) and 2021 class (2,632; 181 drafted, one draft short), never fit, never scored before.

## INDEX (Holm at 3): nothing ships
| test | gain | t (school) | p | classes | 2020 lockbox | result |
|---|---|---|---|---|---|---|
| I2 top-end curve (log industry rank, rating hinge at 95) | LL .00061 | 2.00 | .023 | 8/9 | + (.00019; 2021 +.00117) | fails Holm (.0167): lead |
| I3 service dispersion | LL .00008 | 0.89 | .185 | 5/9 | - | fail |
| I1 ordinal fit of P(drafted) | SE .021 | 0.75 | .228 | 5/9 | 0 | fail |

Lockbox, shipped index against the services (never-seen classes): AUC for drafted .818 / .824 (2020 / 2021) vs ESPN
grade .775 / .799, On3 industry .747 / .798, 247 composite .745 / .781; rank correlation with draft capital .271 /
.285 vs .235 / .266 (ESPN). Top 3% draft rate: index .402 / .443, industry .463 / .463 (the industry rating is as good
or better at the very top; I2 is the lead that addresses it).

## STARS (Holm at 3)
| test | result | t (classes) | classes | ships |
|---|---|---|---|---|
| S0 stars on the NFL index vs year-3 board xFV | star rho with outcome .2509 vs .2438 | 3.87 | 9/9 | yes (lockbox star rho .270 vs .260, .286 vs .278) |
| S3 outcome-fit tier shares vs live shares | tier R2 .1303 vs .1190 | 3.01 | 9/9 | yes |
| S2 5-star+ by score line vs fixed count | tier R2 .1194 vs .1190 | 0.10 | 6/9 | no difference (the live score line is kept) |

S1, the 5-star+ line (index score, top N a class, 9 classes): top-64 pick rate by marginal band: ranks 1-3 63%, 4-6
41%, 7-10 39%, 11-15 31%, 16-20 40%, 21-30 34%, 31-40 24%; the plain 5-star tier 21%. Rule (band >= 50% top-64 and
above the plain tier): N* = 3, 90% class-bootstrap interval 0-6. Six is inside it, so the line stays at 6 a class
(top 6: 74% drafted, 37% top-32, 52% top-64, 44% NFL starters). Lockbox top 6 (n 12): 67% drafted, 50% top-64.

New tiers (held-out score, per class): 5-star+ 6 (76% drafted), 5 35 (56%), 4 102 (29%), 3 265 (18%), 2 611 (9%),
1 1,698 (3%). Shares below 2/3/4/5 stars: .625, .85, .9475, .985 (were .428, .614, .878, .972).

## COMMIT (CFB LIST model, walk-forward 2018-26, n 16,934; Holm at 5)
| test | LL gain | t | classes + | NIL era | result |
|---|---|---|---|---|---|
| C1 conversion (signed / listed, prior 3 classes) | .0303 | 15.6 | 8/9 | +.027 (t 9.2) | pass |
| C2 Elo z and its change | .0183 | 13.3 | 9/9 | +.013 (t 6.9) | pass |
| C5 recency weights .75 a class | .0059 | 14.0 | 8/9 | +.002 (t 3.1) | pass |
| C3 top-tier / nearest school in his list | .0016 | 3.5 | 5/9 | | fail (classes) |
| C4 high-school pipeline | .0006 | 1.5 | 7/9 | | fail |
Joint (C1 + C2 + C5): log loss 2.011 -> 1.962 (t 20.4, 8/9), top-1 29.2% -> 30.4%, top-3 59.9% -> 61.9%.

## XFV (board fit, classes 2023-26; Holm at 3): nothing ships
- V1 P(on) on the recruit blocks directly: log loss .6638 -> .6525 (t 5.31), tier calibration fixed (5-star P(on) .778
  predicted vs .779; unrated .360 vs .359; before .687 vs .779 and .421 vs .356), expected-FV r .355 -> .390. The
  pre-registered guard fails: the year-3 xFV's rank correlation with the NFL outcome falls .2467 -> .2349 (class t
  -4.4, 1/9). Not shipped. Lead: with the stars now on the index, xFV only feeds On%, xFV and class ranks; whether
  those should be board-calibrated at that cost is the owner's call.
- V2 position by year: P(on) t 0.68, FV(on) t -1.10. Fail.
