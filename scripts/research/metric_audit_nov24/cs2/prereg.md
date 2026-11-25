# CS2 metric audit, pre-registration (Nov 24 2026, written before any number below was computed)

Data: bo3.gg per-map player rows (scripts/data/cs2_pstats, Maps() of scripts/cs2_players.py), maps dated before
2026-11-11 only (lockbox). Valve series (scripts/data/cs2_history.json.gz) for team ratings, series before 2026-11-11.
Period = calendar month. Months 2024-01 .. 2026-10. Scored pairs: n = 2024-07 .. 2026-09 (n+1 to 2026-10).
Held months for candidate tests = Jul 2025 on (cs2_players HELD); tune = Jul 2024 - Jun 2025.
Point in time: stat weights refit each month n on maps before the end of month n (expanding, from Jan 2024).
Shipped rating settings (h, k, pm, ssg, tp, opp) are taken as given (tuned Nov 2-13 on the tune split; not retuned here).

## Harness (all player metrics)
- describe in-sample: month-n value from all month-n maps; per month-n map x = sum of the five's values (A) minus (B),
  y = A round share - .5; pooled R2 (squared correlation).
- describe held out: month-n maps split in halves by game id hash; values from one half scored on the other half's maps
  (both ways); players with no rounds in the fitting half get the mean of low-exposure (<100 rounds) players.
- predict team: value as of the end of month n (each metric's board form) -> month n+1 maps, same x / y, pooled R2.
- predict player r: month-n value vs month n+1 value of the same metric (month window, 100+ rounds both months),
  weighted by n+1 rounds; also r vs month n+1 box RWA (pm 0, opponent credited) = common value target.
- 90% intervals: bootstrap over month pairs (2,000 draws).

## Metrics
Ours: RWA rating (board, decayed + shrunk, point in time), season/window RWA (alltime.py: window mean of
opponent-credited contributions + tier lift, no shrink), RWA box only (pm 0 window), 6M projection where cheap,
prospect FV (prospect pool only, its own existing backtest reported), team RWA, ARK Ranking (series level).
Public: bo3.gg rating (rt), HLTV 2.0 community approximation (0.0073 KAST + 0.3591 KPR - 0.5329 DPR + 0.2372 Impact +
0.0032 ADR + 0.1587, Impact = 2.13 KPR + 0.42 APR - 0.41), ADR, KAST, KPR, K-D per round, VRS points (team).
HLTV 3.0 is not reproducible (round swing needs per-round win probability; not public) -> not scored.
Public window metrics are scored as the board shows them: last-year (365 d) rounds-weighted mean for predict, month for describe.

Team (series level): ARK live blend (x, v, t; tiered logistic refit expanding on prior months), ARK player Elo alone,
VRS alone, bo3 team map rating alone, team RWA (five's mean rating at month start). Predict = month n+1 series from
ratings frozen at month start (and live in-month, as shipped). Describe = end-of-month rating vs the month's series;
held out = a replay without one hash half of every month's series, scored on that half. ARK settings are not retuned
(rolling monthly seal owns that).

## Candidates (each judged on its own target; Holm within each batch at .05, one-sided, t by month)
Predictive batch (target: held months' next-month map round-share MSE, walk forward, paired by month; also player r vs
next-month box RWA must not drop by more than .01):
 P1. bo3.gg rating per round (rt) as a 14th stat in the RWA stat weights.
 P2. player x map offsets: rating + the player's decayed, shrunk residual on that map (k_map tuned on tune months,
     grid 100/300/1000/3000 rounds).
 P3. stat-weight ridge strength l2 1e-4 -> best of {1e-3, 1e-2, 3e-2} on tune months.
Descriptive batch (target: held-out-half describe R2 by month, held months):
 D1. season RWA with pm 1.0 (full team residual) instead of .5.
 D2. season RWA with pm 0 (box only) instead of .5.
 D3. bo3.gg rating as a 14th stat (as P1) in the season RWA.
 D4. season RWA shrunk toward the player's rating at the window start, k rounds (grid 50/100/200/400 on tune months).
Ship rule: Holm-adjusted p < .05 on held months and the same sign on tune months; predictive also passes the player-r rule.
Not redone: RWA half-life / shrink / pm tuning of the predictive rating, ESEA division prior / drivers, trailing 12-mo
weights, roster-change shrink, two-part prospect target, ARK settings, BPM-style full team adjustment (pm 1 predictive).
