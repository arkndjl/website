# Model and test rules

## Ship gate

- A model, metric or input change ships only if it passes an out-of-sample test (held-out seasons or classes,
  walk-forward folds, point in time). Ship what passes; record what fails, with its numbers, and don't redo it
  without a new reason.
- Pre-register the test (what counts as a pass) before running it. Report results as they came out, including when
  ours does not win.
- Every feature a fit reads must be point in time: what was known on that date, never later data.
- Shared scoring harness: `scripts/harness.py` / `scripts/harness.mjs` (cluster-robust paired tests, BH across
  models). Ledger in `data/model_ledger.json`.

## Scheduled retests

- Every test that fails or is deferred with a reason to look again later (more seasons, a class maturing, a data pull,
  a forward window) goes into `data/retests.json` in the same pull request: what, the last result, the trigger, the
  gate, and a date (`after` = a calendar event in `data/seasons` plus a lag, else `due`). Never leave a retest only in
  a note or in memory (Noah, Nov 28 2026: he will forget them).
- `scripts/retests.py` (retests workflow, twice a week) runs what is due: watched tests are read from the workflow
  that already reruns them, auto tests run there and ship only on a pass, hand tests open a "retest due" GitHub issue
  (label retest) and the monthly retest task runs them. A retest runs once on its trigger with the gate it was
  registered with; only a pass ships, a fail is recorded with its numbers.
- The pull request that runs a hand retest adds `result` {d, v, e, tt, pr} to its entry and ends with its ARKLOG line.
  ARKLOG > retests and the Process overview show what is scheduled and what has run.

## Lockbox

- The 2026-27 seasons are a lockbox: no threshold, term choice, refit selection or "held" check may read their
  outcomes. Each shipped model is scored on it once at season end. Live monitoring may watch it for breakage only.

## Cross-sport rule

- Any fix, driver or metric tried in one sport is tried in every sport with an analogue.
- Anything that passes held out in one model is tested as an input to the others (FV, game, team, awards, mocks,
  next up), point in time.

## Context metric rule

- Predictive contexts (projections, FV, next up, mocks, game models) lead with and feed on the sport's most
  predictive metric; descriptive contexts (season boards, standouts, awards, SV) use the most descriptive one.
- Conviction and awards use season-only stats (shrinking toward league average within the season is fine).

## Eras

- Transfer, roster-turnover and NIL terms are fit and tested inside the portal / NIL era (July 2021 on), weighted
  toward recent seasons. Transfer% and the team builder are NIL era only.

## FV

- FV is absolute true talent on the 20-80 scale (50 average regular, 60 plus, 70 star, 80 generational, attainable
  but extremely rare via the stretched top, `scripts/fv_scale.py`).
- Never class- or board-relative: never map a score to FV by its rank within the current board or class.
- No shared cross-sport scale and no share-of-a-team units (the rejected value scale; never redo it).
- Headline FV = the mean outcome, whole numbers, steps of 1. Ranges and distributions only in dropdowns.
- Provisional players start at 20 FV with a provisional tag.

## Process numbers

- Every number on Process, glossary cards and research cards is read from the live fit files by scripts and
  refreshed by `process-refresh.yml`. Never type or hand-edit a number.
