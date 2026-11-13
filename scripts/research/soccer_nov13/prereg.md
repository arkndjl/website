# Soccer game model sweep: pre-registration (Nov 13 2026)

Written before any held-out number for these tests was read. History ends with 2025-26, so the 2026-27 lockbox is
not in the data. Tuning seasons 2013-22 (totals: 2021-22, the first seasons with over/under closes behind them);
held out 2022-23 to 2025-26 (S 2023-2026), one pass, `python3 scripts/research/soccer_nov13/totals.py --held`.

## Explored on tuning seasons only, dropped there (no held-out look)

- Market side ratings from a Kalman filter on log market goals (engine.py kq): best .96642 vs .96603 live.
- Squad value weight raised in a season's first matches (mve): worse at every setting.
- Late-season stakes (a table boundary still in reach, last 6 rounds): the close prices it (.075 log goals each way
  in the last 3 rounds, t 21) but on results the term is t -1.3 (841 matches moved, 8 of 10 seasons).
- The close as teacher (shadow.py: stakes, goals-vs-market rating gap, results form, lagged market lean, rest,
  squad value, injuries -> the close's lean off the model, walk-forward by season): best set t -1.3.
- Club-specific lean in UEFA matches (keu): worse.

## Family (Holm, alpha .05, two tests)

### T: market totals ratings

Projected total = exp(.77 x log(model total x live level) + league term + club lean home + club lean away). The
league term and the club leans move after each league match by .06 and .03 x (log total implied by the match's
closing over/under 2.5 price - log projected total); the league term starts at the first priced match; nothing reads
the match's own price. The split between the sides stays the game model's.
- Rows: every finished league match with an over/under close in the 16 football-data leagues (big five, their second
  tiers, ned, por, bel, tur, gre, sco), S 2023-2026.
- Control: the live projection (model goals x the league's scoring level in the big five, x 1 elsewhere).
- Metric: over 2.5 log loss, treatment minus control; t clustered by match day; one-sided p.
- Pass: Holm, and the big five and the other eleven each better on their own (d < 0).
- Club leans: kept only if the held-out loss with them is below the league-term-only version (kt 0); else ship kt 0.

### D: parity draw boost

Draw chance x exp(.06 x max(0, 1 - |home win - away win| / .15)), renormalised.
- Rows: big-five league matches, S 2023-2026. Control: the live 1X2 chances.
- Metric: 1X2 log loss, treatment minus control; t clustered by match day; one-sided p.
- Pass: Holm.

Tuning-season numbers: scripts/research/soccer_nov13/tune.json.

## Batch 1 result (held out, one pass, prereg sha 75c6724a1dd1)

T passes: 21,763 matches, .68265 -> .67531 (t -8.93, 4/4 seasons); big five -.00199 (t -2.51), other eleven -.00991
(t -8.66); club leans vs league term only -.000415 (t -2.55): kept. D fails: -.000082, t -0.77.

## Batch 2 (written before its held-out pass; alpha .05 / 2 on this split)

### DT: the match's total in the draw chance

1X2 chances from the game model's means x exp(.5 x (z - m)), z = log(totals-ratings total / model total) for the
match, m = the league's mean z over earlier matches (50+ behind it). The ratio between the sides and the league's
average total stay the model's; only the match's total relative to its league moves.
- Rows: league matches with a totals rating in the 16 leagues, S 2023-2026. Control: the live 1X2 chances.
- Metric: 1X2 log loss, treatment minus control, t clustered by match day, one-sided p <= .025.
- Tuning (2021-22): g .25 t -2.42, g .5 t -2.03 (d -.00023), g 1 t -1.25. g .5 is the one tested.
- `python3 scripts/research/soccer_nov13/draw_total.py --held`
