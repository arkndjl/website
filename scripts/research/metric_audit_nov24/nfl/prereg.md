# NFL metric audit, Nov 24 2026: pre-registration

Written before any candidate is scored. Data 2016-25 regular seasons only (lockbox: no 2026 outcome is read).

## Harness (every metric)
Value = metric per unit of exposure; exposure = share of the team side's snaps on a 17-game scale (`sh`, board), special
teams rows (K, P, returners) = games / 17 on the offense side. Teams centred within season.
- describe (in sample): season n value x season n exposure summed per team side, net per team -> margin a game, R2.
- describe held out: value from weeks 1-9 x weeks 10+ exposure -> weeks 10+ margin a game; slope fit leaving the season
  out, R2 = 1 - SSE / SST held out, plus the plain squared correlation.
- predict team: season n value x season n+1 exposure (n+1 players without an n value get the low-exposure group mean)
  -> n+1 margin a game, pooled R2 (squared correlation); held-out R2 with the slope fit leaving the pair out.
- predict player: n value (shrunk sh / (sh + .2)) vs n+1 value of the same metric, weighted by n+1 exposure, min .4 sh.
- 90% intervals: 2,000 resamples of seasons (describe) or season pairs (predict).
- XV weights: describe without season n; predict without n and n+1 (point in time). pXP/60 K, Marcel prior and market
  slopes are fit leaving the target season's pair out (as scripts/nfl_rate_research.py), inputs seasons n, n-1, n-2 only.

## Metrics scored
Ours: board WAR (.6 AV WAR + .4 XV + special teams, two-way), AV WAR, XV, AV (rebuilt PFR AV), rXP/60, pXP/60,
SV (QB, RB/WR/TE, DL/LB/DB; OL, K, P have none). Public: nflverse EPA (passer qb_epa, rusher, receiver), CPOE (QBs).
PFR season AV is not reachable (403); the board's AV is rebuilt from nflverse and fit to PFR career AV.
Public offense-only numbers are also scored on an offense-only harness (offense side -> points scored a game).

## Candidates (batch of 4, Holm at .05)
Predictive candidates are judged on predict team: held-out squared error of next-season margin a game (slope fit leaving
the pair out), paired t over team-seasons, one-sided; pass = Holm p < .05, at least 5 of 7 pairs better, and player r
(n vs n+1 board WAR rate) not down more than .01.
Descriptive candidates are judged on describe held out (weeks 1-9 -> weeks 10+): paired t on held-out squared error over
team-seasons, one-sided; pass = Holm p < .05 and at least 6 of the seasons better.

- C1 (predictive) pXP/60 + special teams: add each specialist's / returner's special teams credit rate (already shrunk
  to what carries) to the pXP/60 team sum; pXP/60 has no K, P or return value today.
- C2 (predictive) pWAR rate: pXP/60 plus the sub-position's average value a snap (the WAR line), so team sums carry
  positional value (a QB's average is worth more than a fullback's).
- C3 (descriptive) XV fit per side: offense parts fit on points scored a game, defense parts on points allowed, in place
  of both on margin (same ridge, lambda 20, same signs); judged on XV's own held-out describe.
- C4 (descriptive) board WAR without special teams credit vs with it (keep = with is not worse; a pass here means the
  credit helps held out; a significant loss would mean drop it).

Not retested (already decided): the .6/.4 AV/XV blend (Nov 3: retest after the 2026 season), BPM-style team adjustment
(PR #1196), early-season stretch, aXP/60, SV -> pXP/60, fumble-neutral EPA, wins per AV.
