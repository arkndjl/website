# Soccer metric audit, Nov 24 2026: pre-registration

Written before any audit number was computed (hash in prereg.sha256). Data: static/data/soccer-war/<S>.json for
S 2015..2026 (2014-15 .. 2025-26), ESPN game log scripts/soccer_games_hist.json.gz (league goal difference, big five),
FotMob season lists (scripts/.cache/soccer/fms, 2017..2026). LOCKBOX: 2027 (2026-27) is never read.

## Harness (one for every metric)
Exposure = minutes / 90 per club stint. Team result = league GD a match. Teams centred within league-season.
- describe in-sample: centred sum(value x exposure) / matches vs GD a match, same season, pooled R2 (squared r), 12 seasons.
- describe held-out: slope through the origin fit on the other 11 seasons, applied to the left-out season;
  R2 = 1 - SSE / SS over all left-out seasons.
- predict team: season n value x season n+1 exposure (fill for players with no season n value: mean of under-10-90s
  players at the position, core.fillv) -> n+1 GD a match, pooled R2 over 11 pairs (2015->16 .. 2025->26).
- predict player r: season n value vs season n+1 value of the same metric, weighted by n+1 90s (10+); plus a common
  target, season n value vs season n+1 SV a 90 (season-only, shares no season n input).
- 90% intervals: 2000 resamples of seasons (describe) or season pairs (predict).
- Totals (1Y pj, 3Y p3): roster sum (pj split over his n+1 clubs by n+1 minutes, absent = 0) -> n+1 GD a match;
  player r pj vs n+1 GAR total; p3 vs GAR over n+1..n+3 (absent seasons 0, n <= 2023). Compared with GAR total
  in the same form.
- Prospect FV: not on this harness (career outcome); reported from data/soccer_prospects_fit.json cohort-out numbers.

Metrics: GAR (/90), SV/SVAR, aGAR/90, p/90 (pg90), 1Y, 3Y, xMV, Transfermarkt value, G+A/90, npxG+xA/90, xGChain/90,
on-pitch xGD/90, FotMob rating (where matched), team GD of season n (team baseline).

## Candidates (predictive; target = predict team R2, guard = player r vs n+1 SV a 90 may drop <= .01)
Control = shipped p/90 (RATE_W 1/.5/.25, RATE_K F5 M5 D10 GK640 x 90s, RATE_MU), rebuilt from the season files.
P1 pSV/90: same Marcel form on season-only SV a 90 instead of GAR a 90 (GAR's xG plus-minus already spans S-2..S, so
   p/90 counts old seasons twice). Position prior = SV mean of regulars in seasons <= n.
P2 p/90 retune: decay w (weights 1, w, w^2) in {.25,.5,.75,1} x K multiplier in {.5,1,2,4}.
P3 p/90 + age: + cy x min(age - 25, 0) + co x max(age - 29, 0), cy, co in {0, -.002, -.004, -.008}.
P1 takes the P2 grid too. Every grid value is chosen leave-one-pair-out (best pooled team R2 on the other 10 pairs),
so each pair's score is held out. Test: per-pair R2 difference vs control, t over 11 pairs, one-sided p; Holm at .05
over P1-P3. Pass = Holm-significant gain, guard held, 6+ of 11 pairs better. Ship = pass only.

## Descriptive candidates
None new: same-season GD weight fits, first-half to second-half fits, luck shrink k and team adjustment were all tested
(soccer-sv-nov23, team_adj_nov24) and are not redone. Descriptive metrics are scored only.

## Amendment 1 (written after P1-P3 were scored, before this cell ran; post hoc, exploratory label)
P1, P2 and P3 all passed (a dry run with 20 resamples). They change the same column, and no rule picked between them.
P4 = P1 + P3 jointly: pSV/90 on the P2 grid plus the P3 age terms, all four chosen leave-one-pair-out on the same
target. Rule fixed now: ship P4 if it passes against the control AND beats P1 and P3 alone on team R2 (mean per-pair
gain > 0); otherwise ship the single candidate with the largest mean per-pair team gain. P4 is outside the Holm batch
(reported as post hoc). Guard and pairs rule as above.
