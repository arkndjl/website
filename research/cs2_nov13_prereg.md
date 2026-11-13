# CS2 model audit, Nov 13 2026: pre-registration

Written and committed before any held-out score was read. Code: `scripts/cs2_nov13_research.py`.

## Data and split

- Series: Valve VRS series in `scripts/data/cs2_history.json.gz` up to Nov 10 2026. Nov 11 2026 on is the 2026-27 lockbox and is not read.
- Tune: Aug 7 2024 to Jun 30 2025. Held: Jul 1 2025 to Nov 10 2026. Same windows as `cs2_model.py --fit`.
- Base: the live four-term series model (player Elo gap, VRS points gap, team map logit, five's mean player rating), logistic weights by tier (both teams VRS top 50 / rest) fit on tune.
- New data: bo3.gg `games/{id}` round rows (`scripts/cs2_rounds.py`: side, pistol flag, equipment value after the buy, per map since Jan 2024), and the four factor values plus the head-to-head adjustment in Valve's VRS detail pages.
- The held window has been read by earlier CS2 tests (about 25). That reuse is not corrected here beyond Holm inside this batch; the lockbox scores whatever ships.

## Series family (8 tests, one held pass each)

Adjusted round share: a round counts as win minus (p minus .5), p = the chance a team in that round's situation wins it, estimated from every round in earlier months (expanding window, by map, shrunk toward all maps with 500 rounds; maps before Jul 2024 use the first half of 2024). Maps without round rows keep the plain share. Grid (picked on tune log loss only): situation = side; side x buy matchup (pistol; eco under 5,000 / force under 20,000 / full, each way); side with class weights (pistol, not-both-full) in (1, .5), (1, .25), (.5, .5), (.5, 1), (2, 1). Span of the share-to-score map in {current, .75 x current}.

| Test | Change | Tuned on tune |
|---|---|---|
| A_elo | player Elo's per-map update reads the adjusted share | config, span .4 / .3 |
| A_tm | team map rating's update reads the adjusted share | config, span .3 / .225 |
| B_vrs_factors | five extra terms by tier: gaps in Bounty Offered, Bounty Collected, Opponent Network, LAN Wins, H2H adjustment / 400 (snapshot before the day; unranked = 0) | none |
| C_tprior | a player first seen after the burn-in starts at mu_new + lambda x (mean Elo of teammates with 10+ series minus mu_new) | lambda in .25, .5, .75, 1 |
| D_ktier | player Elo K x m for series at bo3.gg S or A tier events | m in .75, 1.25, 1.5, 2 |
| E_format | second stage, one coefficient each for both tiers: base logit x [Bo1], base logit x [Bo5] (format from the joined bo3.gg match) | none |
| F_experience | second stage: base logit x u, u = mean over both listed fives of exp(-series played / 100) | none |
| S_stack | boosted trees (sklearn HistGradientBoosting, depth 3, rate .05, 150 rounds, leaf 200, l2 1, seed 0) on base logit, the four terms, top-50 flag, format, u, joined flag; rows mirrored in training and prediction | none |

Pass, all needed:
1. Held paired log-loss difference against the base, t over months (Student t, one-sided), under Holm at .025 across the 8.
2. Top-50 held mean difference no worse than 0.
3. For A, C, D: the picked setting beats the base on tune.

A pass ships. If A_elo and A_tm both pass they ship together only if the pair also beats each alone on held (else the better one).

## Correctness fix (outside the family)

G_valid: bo3.gg lists forfeits and cut-off maps with partial scores (1-0, 0-0, 9-1; about 1,500 of 125,000). The player Elo and the team map rating read them as round shares (a 1-0 forfeit = a 100% share). Fix: only maps with 13+ rounds for the winner update on round share; a series with no such map updates at series level as unjoined series do. Found while checking that the new hooks reproduce the live ratings. Ships unless held gets worse (mean difference above 0 with t over months above 1).

## Player rating family (2 tests)

Metric: walk-forward squared error of the round-share prediction on held months (as `cs2_players.map_sq`), paired by map, t over months, Holm at .025 across the 2. Also needed: beats the shipped rating on the tune months, and the series model with the new rating is no worse than the base on held (mean difference).

| Test | Change | Tuned |
|---|---|---|
| P1_tp | shrink target = tp x the rounds-weighted mean rating of the player's teammates (instead of 0) | tp in .25, .5, .75, 1 |
| P2_adj | plus-minus residual measured against the adjusted round share | config from the grid above |

A pass refits `cs2_players.py --fit` (prospect FV and transfer values follow the rating).

## 1NT / ESEA

Conditional: only if C_tprior or P1_tp passes, the same teammate prior is tested once on the ESEA RWA (tune S54-S57, held S58-S59 match log loss, t by match day, .025).

## Not retested (failed before)

Team-name Elo, roster continuity, inactivity decay, staleness terms, temperatures, top-50 fixed slope, expanding or trailing refits, roster-change shrink, LAN terms, Kalman, map-scale, lineup-unit RWA, tier weights and decay grids in the player rating, badges, per-stat FV drivers, two-part prospect target.
