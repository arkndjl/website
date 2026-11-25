# Tennis metric audit, Nov 24 2026: pre-registration (written before any metric was scored)

Lockbox: no row with tourney date > 20261110 is read (the export used ends Oct 26 2026). Seasons = calendar years.
Data: /mnt/project-files/tennis/matches.csv.gz + players.json.gz (the pipeline's own history export, Oct 26), Sackmann
year-end rankings (rank, points) from sackmann.tgz. Live fit params (data/tennis_fit.json), walk-forward state.

## Harness (no team: a player is his own team)
Pool: player with 10+ matches (every level) in season n and a 52-week rPA (statistics) at Dec 31 of n.
Scored matches: tour-level main draws (G M A F O, no qualifying, no retirements) between two pool players.
Score: P(winner) = sig(b x (metric winner - metric loser)), one slope b, no intercept. McFadden R2 = 1 - LL / ln 2.
- describe in-sample: metric from all of season n (pass on every row), scored on season n's own matches, b pooled.
- describe held-out: every match split by a fixed hash into halves A / B. Metric from a pass on half A only (every
  season); scored on half B matches of season n; b fit leaving season n out. Ranking / ranking points are not
  computable without the held half: n/a.
- predict: metric at Dec 31 of n (full pass, nothing after n) -> season n+1 matches; b fit leaving the pair out.
  Log loss, Brier, McFadden R2. Player r: metric n vs metric n+1, weighted by n+1 matches (pool in both seasons).
Seasons n 2011-2025 (pairs 2011->12 ... 2025->26, 2026 through Oct 26). 90% intervals: resample seasons (pairs), 2000x.

Metrics: ARK (ratings' chance vs the average top-50, surface mix), Elo overall, TA/538-style Elo (K 250/(n+5)^.4, all
levels, no level discount), points rating (Kalman serve + return), pPA, rPA, WAR (52 weeks), SV (calendar year),
WAR a match (shrunk by 10), wins, W-L, win %, games share, raw SPW, RPW, dominance ratio, official rank (-log), rank
points (log). Prospect FV: not on this harness (its outcome is a peak years later; its own LOBO / forward test stands).

## Candidates (each judged on its own target only)
Family D (descriptive target: describe held-out log loss), Holm over 2:
- D1 SV-L: SV with each match's credit weighted by level (Futures / ITF x0.5, Challenger / WTA 125, qualifying and team
  events x0.85, tour x1).
- D2 rPA-K: rPA shrunk by 300 points (100 x sum PA / (points + 300)), the same shrink pPA uses.
Family P (predictive target: next-season log loss), Holm over 2:
- P1 ARK-PA: ARK with the match blend's points-added term (A logit Elo + B logit points + G games + CP x (pPA - ref
  pPA) / 10, ref = top-50 mean), match weights from the fit file.
- P2 WAR-L: WAR (52 weeks) with the D1 level weights.
Test: per-match log loss difference candidate - base on the same matches, t clustered by tournament; one-sided p,
Holm within family. Pass = Holm p < .05, better in 9+ of 15 seasons, and (value metrics) player r not down by > .01.
Ship only a pass.
