# CBB recruits pass, Nov 16 2026: results

Pre-registration: prereg.md (written before any score). Outputs: /mnt/project-files/recruits/cbb-nov16/*.json.
Run: `python3 fv_tests.py`, `python3 line_tests.py`, `python3 cb_tests.py` (history from scripts/data, kit and ESPN
classes from /mnt/project-files).

## Family FV (recruit model = projected FV), classes 2009-16 held out, n 1,997
| test | score | gain | t recruits | classes | verdict |
| --- | --- | --- | --- | --- | --- |
| P1 ordinal ladder | RPS .4005 -> .3945 | .0060 | 2.31 (needs 2.33) | 6/8 | FAIL by .02; MSE 57.04 -> 57.01 (not worse); forward 2017-18 t 2.56, 2/2. Registered for retest (retests_2027.json cbb_recruit_ladder) |
| P2 Poisson value part | MSE 57.04 -> 56.87 | .17 | 0.85 | 6/8 | FAIL |

Consensus rank 1-5: realized 51.0, shipped 45.0, ladder 45.5, Poisson 46.7. Rank 6-10: realized 37.4, shipped 39.2.
No form that is smooth in log rank closes the top-5 gap.

## Family LINE (5-star+), score = held-out FV, place in class
- L1 step in FV55+ on top of ln r + (ln r)^2: held-out log loss gain -.0059, t -0.84, 2/8 classes, k chosen 7 in 5
  folds. FAIL: no step that holds out of sample. Realized FV version t -0.66.
- L2 forward (2017-20, early NBA value, step at 7): z 0.94. Not confirmed.
- Information rule (held-out R2 of realized FV on the six-tier star): none .274; k=1 .279, 2 .282, 3 .288, 4 .302,
  **5 .310**, 6 .304, 7 .302, 8 .296, 10 .292, 12 .284, 15 .276. Best = 5 = the shipped line. 4, 6, 7 sit within one
  jackknife SE; 1-3 are 2+ SE worse.
- FV55+ by place: 1: 50%, 2-3: 38%, 4-5: 44%, 6-8: 17%, 9-12: 9%, 13-20: 8%, 21-35: 3%. Mean realized FV 54 / 50 / 50 /
  39 / 35 / 33 / 29. Tier at 5 a class: 44% FV55+, 64% FV45+, mean 51.4; the 5-star tier below: 11%, 26%, 35.8.
- Decision: the line stays at 5 a class (FV cut 41.43). ARKLIST untouched.

## Family CB (commitment LIST model), walk-forward 2015-26, n 1,553, base LL -1.9318, top-1 24.9%
| test | LL gain | t | classes + | NIL-era t | verdict |
| --- | --- | --- | --- | --- | --- |
| K1 program strength | .0023 | 0.93 | 8/12 | 1.63 | FAIL |
| K2 + strength x grade | .0026 | 0.97 | 8/12 | 1.85 | FAIL (lead: retest when 2027-28 classes sign) |
| K3 NBA pipeline x grade | .0009 | 0.31 | 9/12 | 0.68 | FAIL |
| K4 open minutes at position | .0003 | 0.34 | 9/12 | 0.73 | FAIL |
| K5 within 50 miles | -.0017 | -1.47 | 7/12 | -0.35 | FAIL |
| K6 recency weights (half-life 4) | .0006 | 0.47 | 6/12 | -2.00 | FAIL |

## Fixes shipped (not tests)
- select(): a candidate with one value in every training row (On3's own rank before 2021) could pass the t gate on
  floating-point noise and be listed as a kept driver. Such columns are skipped.
- Live 'old for the class': the flag was read from today's whole-year age, so it drifted up through the year (by
  April half the 18-year-olds flagged were 17 on the history's date). Now the chance he is 18+ on Oct 26 of his
  senior year. Today: +0.1 to +0.2 FV for 45 recruits, no 5-star+ change.

## Deviations
- 21 ESPN schools whose names the shared team key missed were mapped by hand to Barttorvik names before the run.
- The information rule's k = 0 row (no 5-star+ tier) was added for reference.
