# Results: visits and expert picks in the commitment model (Nov 17 2026)

Prereg: prereg.md. Tests: visit_tests.py -> visit_tests.json; calibration follow-up: calib.py -> calib.json.
Held out walk-forward by class; features as of the On3 commitment date - H days. LL = per-recruit log loss over his
ESPN list; n = all LIST recruits (16,934 CFB, 1,553 CBB), about a fifth of them matched to On3 (top 400 CFB / 120 CBB).

## CFB, H = 30 (primary)
| family | gain / recruit | t | classes + | Holm | result |
|---|---|---|---|---|---|
| V visits (ov, luv, vlast, vrec) | .0549 | 18.8 | 9/9 | yes | pass |
| E expert picks (esh, eany), 2023-26 | .0627 | 12.5 | 4/4 | yes | pass |
| R RPM snapshot (lrpm, rpm_has), 2024-26 | .0211 | 5.6 | 3/3 | yes | pass alone |

Forward (V, E, R): V; E on top of V .0257 (t 7.5, 4/4) kept; R on top of V+E -.0022 (t -1.4) dropped.
Kept model vs shipped: LL 1.962 -> 1.896 (t 19.7, 9/9), top-1 30.4% -> 32.3%, Brier .803 -> .790.
On3-matched recruits only (n 3,262): base LL 2.365; V alone gains .276.
Visits gain by class: 2018 .017, 2019 .031, 2020 .023, 2021 .001 (dead period), 2022 .063, 2023 .102, 2024 .102, 2025 .082, 2026 .062.

Sensitivity (not gates): H = 7 final gain .102 (t 24.2), H = 90 .036 (t 12.1; R also passes forward there).

## CBB, H = 30
Nothing passes: V .0157 (t 1.59), E -.0028 (t -.16), R .0012 (t .43). 120 recruits a class, picks only 2024-26.

## Calibration of the shown lean (CFB kept model, held out)
Fine through .75; top bins hot: predicted .845 -> .705 hit (n 193), .944 -> .720 (n 164), mostly recruits with
expert picks (.947 -> .738, n 130). Walk-forward temperature fails (t -6.6; T drifts 1.28 -> .98) and a walk-forward
isotonic map of the top % fails overall (Brier t -1.8, 3/7) though it helps the >= .8 tail in 2023-26. Lead: a
tail-only calibration once the 2027 class signs (more picks-era classes).

## Not testable / not used
247 Crystal Ball and 247 visits (bot wall). Finalist / top-school lists (On3 resets the other schools to Offered once
he commits, so there is no dated history). On3's expert-accuracy fields are post hoc (not used).
