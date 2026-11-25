# CFB metric audit (Nov 24 2026)

Pre-registered in `prereg.md` (sha256 in `prereg.sha256`; addendum P4/D4 added after the metric table, before scoring).
LOCKBOX: seasons 2019-25 only; 2026 PFN rows, games and scores are never read (export drops them).

Rerun: `node scripts/research/metric_audit_nov24/cfb/export.mjs` (PFN impact pages + ESPN scoreboards, no CFBD),
`python3 .../harness.py` (player.json, ~4 min), `python3 .../qb_team.py`, `python3 .../d1_check.py`;
retests: `python3 scripts/cfb_espn_pbp.py 2016 2025 && python3 scripts/st_teams.py events cfb && python3 .../retest_st.py`,
`cd retest_qb && python3 qb_topend.py && python3 qb_cluster.py`.

Harness: value a full share x exposure (games share filling starter slots) summed a team, centred a season, vs SRS.
Main = seven positions graded since 2019 (QB RB WR TE EDGE DL LB): 7 describe seasons (921 team seasons), 6 predict pairs
(791). Held-out describe = slope fit leave one season out. Player r = n value vs n+1 value (n+1 exposure weighted), pooled /
position means removed. 90% intervals: seasons or pairs resampled.

| metric | describe R2 (in-sample) | describe held-out | predict team R2 | predict player r (pooled / within pos) | n pairs | 10 pos 2024-25: held desc / pred |
|---|---|---|---|---|---|---|
| PFN impact score (public, score - 50) | .419 [.38, .46] | .416 [.37, .46] | .202 [.15, .25] | .439 / .437 | 6 (3,341 players) | .561 / .367 |
| Stat+ z (PFN z, equal position weights) | .554 [.49, .60] | .552 [.48, .60] | .226 [.17, .28] | .514 / **.511** | 6 | .648 / **.393** |
| Season AV (sav) | .657 [.61, .69] | .656 [.61, .69] | .245 [.20, .29] | .638 / .463 | 6 | .775 / .379 |
| cWAR (board war) | .640 [.60, .68] | .639 [.59, .67] | **.256** [.21, .30] | .576 / .461 | 6 | .766 / .380 |
| XV (board xv) | **.690** [.65, .73] | **.689** [.65, .73] | .255 [.21, .30] | .542 / .440 | 6 | **.850** / .389 |

QB block (QB value x QB exposure -> opponent-adjusted offense rating; values standardised a season):

| QB metric | describe in | describe held-out | predict team R2 | player r | n |
|---|---|---|---|---|---|
| Stat+ QB z (PFN) | .650 | **.649** [.62, .68] | .127 [.09, .16] | .421 | 455 |
| XV QB quality | .645 | .643 [.61, .67] | .127 [.09, .17] | **.455** | 455 |
| NCAA passer efficiency (public box) | .561 | .560 | .072 | .341 | 455 |
| NY/A (PFN line) | .486 | .485 | .053 | .313 | 455 |
| SV/60 (ours, EPA) | .454 | .452 | .065 | .243 | 440 |
| pSV/60 (ours, predictive) | .461 | .459 | .074 | .277 (vs next SV/60) | 430 |

Team ratings (2019-25): SRS held-out half of games .474, next-season SRS .411; margin a game .351 / .332; win % .264 / .256;
ESPN FPI final (public) same-season .897 (carries a prior, not held out), next-season SRS **.460**. Elo / ARK Ranking
history is not stored offline, not scored.

**Best descriptive: XV** (ahead of cWAR in 7 of 7 seasons, also 2019-23 where its weights were not fit: .660 vs .617).
**Best predictive (college team next season): cWAR and XV tie** (.256 / .255, intervals overlap); ours, so cWAR named.
Player repeat within position: Stat+ z best (.511). QB: Stat+ QB z ~ XV QB tie on both; SV/pSV trail PFN on team offense.

## Candidates (Holm over eight, one-sided)

| id | target | before -> after (held out) | t | p | seasons | result |
|---|---|---|---|---|---|---|
| P1 Marcel 3 seasons on cWAR | predict | .255 -> .224 | +2.46 | .99 | 2/6 | fail (worse) |
| P2 experience delta | predict | .255 -> .252 | +1.88 | .97 | 2/6 | fail |
| P3 P1 + P2 | predict | .255 -> .216 | +2.86 | 1.0 | 2/6 | fail |
| P4 position weights refit to next season | predict | .255 -> .225 | +1.60 | .95 | 2/6 | fail |
| D1 position weights refit (describe) | describe | .639 -> .656 | -2.52 | .006 | 6/7 | pass, not shipped: XV beats it (t -2.99, 6/7) and its weights cut predict .255 -> .241, player r .576 -> .496 |
| D2 schedule (PFN sos) | describe | .639 -> .632 | +4.31 | 1.0 | 0/7 | fail |
| D3 XV in place of cWAR | describe | .639 -> .689 | -5.39 | <.001 | 7/7 | pass: display (lead descriptive tabs with XV) |
| D4 ungraded starter time at SAV_REPL in team WAR | describe | .639 -> .654 | -3.48 | <.001 | 7/7 | pass, shipped (scripts/cfb_av.mjs teamWar) |

Equal weights (Stat+ z sum) as a predictor, post hoc: .221 (t +1.47), not better.

## Memory retests
- CFB QB top-end FV: FAIL. Pre-specified hinge K60 final seasons MSE 79.2 -> 83.0 (t +1.17); clustered best t -1.36 (bar -2).
  Rows refreshed Nov 23, drafts still end 2023 (2026 NFL AV is lockbox). Retest with the 2024-25 classes in 2027-28.
- CFB team special teams rating in the game model: FAIL. 2026 dropped; vs close tune t .81, held 2023-25 t 2.00, held error
  t -1.84; vs model residual held t 1.98; BH q .37.

## Notes for the lead
- `scripts/research/team_adj_nov24/core.py` divides a team's summed value by games; CFB exposure is already a share, so
  cfb.json there penalises 14-15 game teams, and its 2025->2026 pair reads 2026 (now lockbox). This harness sums without it.
- Season AV describes better than cWAR only through its zero point (an ungraded starter slot counts at q -1); D4 gives WAR
  the same.
