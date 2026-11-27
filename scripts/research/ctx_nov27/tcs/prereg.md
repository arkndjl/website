# Metric context audit, Nov 27 2026: tennis / CS2 / 1NT / LAURSEN_111 (lens tcs)

Written before any score was read. Lockbox: no series, map or match on or after 2026-11-11 enters a fit choice or a test.

## T1 (LEAK, model-affecting): CS2 series model player term, fit form vs serve form

Finding: `cs2_players.Live.mean` gives the five's mean RWA rating **as of the first day of the series' month** for every
historical row (what `game_test` fits the term's weight on, and what cs2_events / cs2_pickem fits read), but **today's
ratings** (`d == "now"`) for every upcoming series. The weight is fit on ratings 0-30 days stale and served on fresh ones.

Forms (same replay rows, same tiered logistic on [player Elo, VRS, map rating, z], tune 2024-08-07..2025-06-30, held
2025-07-01..2026-11-10):
- B  month fit, month score: the shipped backtest (z from the month's first day in tune and held).
- C  month fit, day score: what is live now (weights from B, z from ratings at the series day, maps before that day).
- A  day fit, day score: the aligned candidate (z from ratings at the series day in tune and held).

Target: held-out series log loss. Unit for t: calendar month (mean paired difference by month, t over months).
Guard: top-50 pairs' held log loss (t by month < +1).

Pass rule, fixed now:
1. A vs C is primary. If t <= -2 and more than half the months improve and the guard holds: ship A (fit on day ratings).
2. If |t| < 2 on A vs C: ship A only if A vs B has t < +2 and the guard holds (it removes the fit / serve difference at no
   held-out cost); reported as an alignment, not a gain.
3. If A is worse than B at t >= +2: keep the month fit and make the serve read the month's first day too (B aligned).
One test in the batch (Holm over 1 = the raw p).

Implementation if A ships: `Live.mean` keys its snapshot by day for historical rows; `game_test` reads day ratings;
rerun `python3 scripts/cs2_players.py --fit`, then cs2_events / cs2_pickem fits and the builds.

## Rule fixes (no model, no test)

- R1 CS2 RAR (RWA leaders, transfer values tabs): "rounds above replacement over the last year" is a descriptive total but
  is built from the decayed, prior-shrunk RWA rating x last-year rounds. Swap to the season-only form the all-time lists
  already use (scripts/alltime.py cs2_players): last 365 days' opponent-credited lines (window_stats, no decay) + tier
  lift, over the pool's median of the same number, x rounds / 100.
- R2 1NT S59 player rankings: a season board sorted and headlined by career RWA. Swap to the season's RWA (same formula
  as the 1NT season cards, written for every division player).
- R3 tooltips that call a career rating "this season".

## Leads (cannot be scored here)

- L1 1NT season sim and stakes read FACEIT team elo alone; the preview logit (elo / talent + RWA) is the more
  predictive point-in-time form. Test: S59 page inputs as they stood (data/esea.json git history; this checkout is
  shallow), leave one day out, match log loss, sim chance = preview logit vs elo; pass t <= -2.
- L2 1NT power rank (ARK Ranking) reads team ARK (.20); team RWA is the predictive form. Same harness and rule.
