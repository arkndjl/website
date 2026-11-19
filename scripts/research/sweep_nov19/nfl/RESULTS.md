# NFL sweep Nov 19 2026: results

prereg.md sha256: ce601d4d88a729eb1d9aa962f6862223926d4ea77bdaf9f6c0e73a0e0a8ed306 (written before any score; copy in the
repo at scripts/research/sweep_nov19/nfl/PREREG.md). Every number below is in results.json (repo: data/nfl_sweep_nov19.json).
Nothing from the 2026 season was read by any test. Branch sweep-nfl, worktree /home/user/wt-nfl.

| Lead | Verdict | n | Split | Effect | t | Holm p | Why |
|---|---|---|---|---|---|---|---|
| 1 Madden launch OVR, pXP/60 prior OL (M1) | FAILED | 435 held player-seasons | tune targets 2017-20 / held 2022-23 | held MSE -.00008 of .0262; tune +.00005 | rows -1.38 (tune +0.47) | n.s. (.84) | tune and held disagree in sign; gain 0.3% of MSE |
| 1 same, LB (M2) | FAILED | 300 | same | held +.00016 (worse) | +0.89 | n.s. | wrong direction both splits |
| 1 same, DB (M3) | FAILED | 474 | same | held +.00043 (worse) | +0.89 | n.s. | wrong direction |
| 1 OL value from launch OVR in XV (M5) | FAILED | 815 held games | tune 2018-21 / held 2022-24 | NNLS weight 0; SSE gain 0.1; team r .9116 vs .9119 | 0.22 | n.s. | part not kept by the fit |
| 7b prior-season honours as OL prior (M4) | FAILED | 844 | tune 2017-20 / held 2021-24 | held -.00007; tune +.00003 | rows -1.10 (season -1.8) | n.s. | under 2, tune opposite sign |
| 2 reserve hazard, weeks served only (R1) | FAILED | 84,696 terms / 24,198 player-weeks | fit 2016-20 / held 2021-25 | log loss .3500 -> .3492 | -0.53 | 0.60 | 4 of 5 held seasons worse |
| 2 reserve hazard, list code x weeks served (R2) | FAILED on the tune-sign rule (strong lead, needs Noah) | 49,691 terms / 14,103 player-weeks | fit 2020-22 / held 2023-25 | log loss .2965 -> .2724 (-.024), 3 of 3 seasons | -4.46 | <.001 | leave-one-season-out inside 2020-22 is +.028 (t +1.0): the 2020 fold (+.209, covid list codes, blank codes) flips it; 2021 fold -.077 (t -5.8), 2022 fold -.033 (t -7.4) |
| 2 game test (R3) | NOT RUN | - | - | - | - | - | only decided how R2 would be wired; R2 did not pass |
| 3a nfelo opens for 2022 (N1) | FAILED tolerance | 2,379 games | parity vs stored opens 2015-21, 2023-25 | mean gap +.007, MAE 1.04 (limit .85); 2022 coverage 271/271 | - | - | a different open from the SBR / ESPN one already stored; not written to the opens store |
| 3b nfelo pre-regression line stacked on the model (N2) | FAILED | 570 held games | tune 2022-23 / held 2024-25 | held MAE 9.887 -> 9.967 (+.080); tune -.118 | +1.04 (tune -1.67) | n.s. | sign flips; nfelo alone 10.10 held |
| 3c nfelo as a displayed column | HELD needs Noah | - | - | - | - | - | not built |
| 5 all-time NFL coaches tab | BUILT display-only | 493 coaches, 2,390 team-seasons 1920-2025 | - | HOF AUC .88 (raw wins .78); movers r .25 (n 75, t 2.2); walk-forward 2010 Score -> next-10 title equity r .39 | - | - | same WAx / cWAR machinery; title weights come out 0 a title + 194 a title-game season |
| 5 coordinator carry (C1) | FAILED | 94 coaches | by decade of first HC season | slope .007, r .08; held gain -.033 | .07 (held -1.26) | n.s. | no coordinator term in Score |
| 6 draft value chart blend vs the mock's curve (D) | FAILED | 224 held trades (435 in all) | fit 2011-18 / held 2019-25 | mean abs imbalance .1340 -> .1340 | 0.01 | 0.99 | registered measure (value received vs the top pick given). Both-sides totals variant, not the registered one: .1166 -> .1012, t 3.12, 6 of 7 years |
| 7 honours label table | BUILT display-only | 6,665 player-seasons 2018-25 | - | WAR AUC vs AP first team: OL .82, RB .75, others .92-.99; XV OL .78 | - | - | study file for Process; AV carries an All-Pro bonus (said in the method line) |
| 8 ffopportunity expected stats in the stat-line ridges | FAILED | QB 2,872 / RB 5,760 / WR 8,640 / TE 2,880 held | selection 2016-20 / held 2021-25 | PPR MAE QB -.003, RB -.001, WR +.000, TE -.001 | -0.52 / -0.70 / +0.30 / -0.41 | n.s. (all) | no position near 2; WR and TE worse on selection |
| 9 defender RAPM, EDGE/DT pressure (X1) | FAILED | 2,127 games 2018-25 | lambda/decay on 2017-20; later half 2022-25 | NNLS weight 0; team r .9119 = live | 1.13 | 0.26 | part not kept |
| 9 defender RAPM, DB dropback EPA (X2) | FAILED on the team-r gate (lead) | 2,127 games | same | missed-games SSE gain 88, later half t 2.43, weight .06 kept; LOSO team r .9113 vs .9119 | 2.67 | .015 | registered pass needed team r higher as well |
| 10 preseason win totals | BLOCKED | 459 games (weeks 1-6, 2016-20) | walk-forward 2015-20 only | MAE 9.888 -> 9.762 (-.126), 5 of 5 seasons | -2.43 | - | free lines end at 2020 (nfldata); positive pre-test, so the 192 hand-entered lines for 2021-26 are worth asking for. The stack also rescales the model, so part of the gain may be shrink |
| Supporting: weekly Madden ledger | BLOCKED | - | - | - | - | - | EA drop-api serves last year's game (Madden NFL 26, iteration "Week 8 Ratings", team and position null); committing it would also republish EA numbers |
| Supporting: FTN 2026 formation tendencies | already live | - | - | - | - | - | nfl_personnel.py already reads this season's FTN |
| Supporting: reserve-list return board | NOT BUILT | - | - | - | - | - | depends on R2 |
| Supporting: surplus under five charts | NOT BUILT (numbers in results.json) | - | - | - | - | - | D failed |

## Notes
- Madden: launch sheets exist for seasons 2015-20, 2022, 2023 only. Edition 22 has a final roster only (leaks the season),
  the "madden-nfl-25" page is the 2013 anniversary game, edition 26 has no page. Nothing Madden ships, so no EA numbers
  are in the repo (raw sheets stayed in scratch and are deleted).
- Join fixes made after the first run (bugs, not retunes): nfelo ids use LAR / OAK (33 games a season were dropped);
  trades.csv gives every pick row the drafted player's pfr id, so "no players" must test pick_season, not pfr_id;
  weekly rosters carry no pfr id for linemen, so honours and Madden join through snap counts.
- Season-cluster t with 2-3 held seasons is not informative (M1 shows -42 on two seasons); the row-level t is quoted.
- Reserve codes (status_description_abbr R01, R48, R04, R05 ...) exist from 2020 only.

## Needs Noah
1. R2 reserve-list state table: held 2023-25 log loss -8% (t -4.5, 3 of 3) but it failed the registered tune-sign rule
   because of the 2020 fold. Ship on owner's call (as `ir` was) or register it for the season-end 2026 score.
2. X2 DB on-field EPA RAPM as a last-season XV part: missed-games t 2.67, later half 2.43, team r .0006 lower.
3. Draft chart blend: fails as registered, passes on both-sides totals (t 3.12).
4. Win totals 2021-26 by hand (192 lines): the 2016-20 pre-test is positive (t -2.43).
5. nfelo shown as a column (their licence allows republishing their own outputs).
6. The honours study is set publish: true (research/studies/nfl/nfl-honours-agreement.json); flip it if not wanted.
