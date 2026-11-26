# FotMob GAR / SV stand-in: pre-registration (Nov 26 2026, written before any result was read)

Question: while Understat is down, is a value built from FotMob's season lists a better board than the frozen
Understat numbers, and is it worth blending in when Understat is up?

Data: big five, seasons 2021..2026 (2020-21 .. 2025-26: FotMob lists xG for every player from 2020-21). 2027 never
read. Truth = the Understat season files' GAR and SVAR (static/data/soccer-war/<S>.json). Freezes = Understat rebuilt
from its cached match files with only the matches before the cut, at f = .25, .5, .75 of each league's season
(snaps.py). FotMob is only available as end-of-season totals, so every freeze is scored at the end of the season
(an outage running from the cut to the last match).

Model (scripts/soccer_fm_gar.py): ridge per position, FotMob rates a 90 relative to the league-season and shrunk by
minutes + the side's xG for / against a match -> the player's league-relative Understat value a 90 (GAR's, SV's).
GAR form also reads his Understat value a 90 from the season before. Ridge strength and shrink minutes picked on the
training seasons only (inner leave-one-season-out), outer leave-one-season-out for every number below.

Candidates for a player's end-of-season total (rate x FotMob minutes, 90+ minutes):
- C0 frozen: Understat's total at the cut (what the site shows today).
- C1 frozen rate x minutes now (the cheapest fix: FotMob only for minutes; a player with no frozen row gets 0 over
  replacement at his position's frozen mean).
- C2 FotMob estimate alone.
- C3 blend: w x frozen rate + (1 - w) x FotMob estimate, one w per f fit on the training seasons, w -> the frozen
  rate's share by the minutes Understat saw (w x umin / (umin + k) form, k fit).

Scored: RMSE of the season total across players (GAR and SVAR), per season; paired t on squared error with players as
units, seasons won. Also on the Nov 24 audit harness: same-season team goal difference from the roster sum
(describe R2) and Spearman of the top 150 by SVAR (the Ballon d'Or pool).

Gates
1. Fallback ships for a metric (GAR, SVAR) at a freeze depth f if the best FotMob candidate (C2 or C3) beats BOTH C0
   and C1 held out: paired t <= -2 and at least 4 of 6 seasons. Depths that pass define when the boards switch (the
   live outage is at about f = .75 by matches: 10 of 13-14 rounds seen).
2. Blended replacement (Understat up, f = 1): FotMob estimate blended into the Understat rate must raise next-season
   team R2 on the audit harness (season n values x n+1 minutes -> n+1 goal difference) with t >= 2 over the season
   pairs and most pairs better. Prior: fails (FotMob rates added nothing to GAR on Nov 1, t .3-1.1).
3. If gate 1 fails everywhere, ship only C1 if C1 beats C0 by the same rule; otherwise nothing changes.

One pass on the outer folds. No retuning after reading them.
