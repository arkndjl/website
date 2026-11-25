# NHL + hockey prospects metric audit (Nov 24 2026)

`prereg.md` (candidates, amendment), `warm.py` (caches), `audit.py` -> `results.json`, `audit_variant.py` (MoneyPuck column
swap), `refit_check.py` -> `refit_check.json`. Seasons 2008-09 ... 2025-26, 17 pairs, 524 next-season team-seasons,
10,314 player pairs (500+ min next season). 2026-27 never read. Brackets = 90% interval, resampling season pairs.
Player r = season n value vs season n+1 descriptive WAR a 60 (n+1 ice time weighted); own r = vs the same metric n+1.

| metric | describe R2 (in-sample) | describe held-out | predict team R2 | predict player r | own r | n pairs |
|---|---|---|---|---|---|---|
| WAR, descriptive (ours) | **.978** [.974, .982] | **.978** | .250 [.187, .317] | .309 [.286, .328] | .309 | 17 |
| pWAR / HPM, nested weights (ours) | .649 | .647 | **.384** [.289, .477] | .347 [.336, .357] | .925 | 17 |
| pWAR / HPM, board weights (ours) | .653 | .652 | .384 [.289, .475] | .358 [.346, .368] | .921 | 17 |
| Marcel WAR, projections tab (ours) | .790 | .789 | .345 [.278, .416] | **.446** [.430, .461] | .810 | 17 |
| GSAx a 60, goalies (ours) | .285 | .282 | .032 [.014, .055] | .031 | .110 | 17 |
| points a 60 | .644 | .642 | .260 [.186, .338] | .380 [.363, .395] | .792 | 17 |
| MoneyPuck game score a 60 (public) | .637 | .636 | .355 [.302, .408] | .423 [.405, .439] | .744 | 17 |
| 5v5 on-ice relative xG | .076 | .069 | .062 | .272 | .277 | 17 |
| team xGD a game (MoneyPuck) | .596 | | .295 [.249, .341] | | | 522 team pairs |
| team score-venue adj xGD a game | .634 | | .303 [.259, .349] | | | |
| team GD a game | 1 | | .306 [.243, .369] | | | |

- Best descriptive: **WAR** (.978 held out; nothing else above .79).
- Best predictive: **pWAR** for team results (.384; game score .355 and Marcel WAR .345 inside its interval: tie, ours
  kept). For a player's own next season, **Marcel WAR** (.446 vs pWAR .347, intervals apart; game score .423 overlaps).
  pWAR's weights are fit to team GD, so it ranks players less well than the three-season WAR Marcel. 3Y (p3) uses both.
- Hockey prospect FV (data/hockey_fit.json, not rescored): class held out MSE 87.11 vs draft slot 91.63, classes 2008-19.

## Candidates (Holm family of 3; predictive, on the predict test; nested weights fixed)
| candidate | team R2 before -> after | player r | t (pairs) | p Holm | result |
|---|---|---|---|---|---|
| P3 pWAR evf/eva/ixg from flurry + score + venue adjusted xG | .3842 -> .3874 (13/17) | .347 -> .347 | 2.88 | .006 | **PASS** |
| P2 pWAR 5v5 on-ice from score + venue adjusted xG | .3842 -> .3842 | .347 -> .347 | 0.32 | .75 | fail |
| P1 pWAR + PP on-ice xG at .2 (memory retest "NHL PP xG weight") | .3842 -> .3736 (7/17) | .347 -> .352 | -1.19 | .88 | fail |
| D1 WAR without the penalties term | invariant (.97833 vs .9783) | | | | withdrawn |

P3 on pWAR's own gate with weights refit (refit_check.py): LOSO R2 .3734 -> .3759 (t -2.82, 15/17 seasons), walk forward
.3742 -> .3769 (t -3.59, 14/15). The gain is flurry adjustment (P2 alone is flat). PP xG: power-play on-ice xG does not
carry into next season's GD beyond pWAR's inputs, consistent with the game model's ppw lean; the ppw game model retest
itself needs 2026-27 (lockbox) and was not run.
