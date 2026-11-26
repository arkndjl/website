# Pre-registration: deep completions side rating (Nov 26 2026)

Written before any run. Source idea: football-docs metric cards (field tilt / final-third entry family); Understat
`deep` is the free proxy we already cache.

- Tune: 2015-22 seasons (Understat starts 2014-15), soccer_games.evaluate's scored set and scoring, all other params at
  the live fit. Grid kd {.08, .15} x wd {.03, .06, .1}, plus one swap (wd .05 taken out of wx).
- Pick: lowest tuning log loss. Go to held only if it beats the base by >= .0002 a match with t(day) <= -2.
- Held: 2023-26, one pass, ship rule as the Nov 13 sweep: diff < 0, t(day) <= -2, at least 3 of 4 seasons better.
- PPDA is not tested: it counts defensive actions, has no goal scale, and a style term failed before.
