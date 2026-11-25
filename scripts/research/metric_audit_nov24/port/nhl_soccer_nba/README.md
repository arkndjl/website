# Port round: NHL, soccer, NBA (descriptive), Nov 24 2026

Prereg `prereg.md` (+ Amendment 1; hash of the first version in `prereg.sha256`). Scripts: `nhl.py` -> `nhl.json`,
`nhl_n6check.py` -> `nhl_n6check.json`, `soccer.py` -> `soccer.json`, `nba.py` -> `nba.json`. All of it: `results.json`
(with the Holm table). Harnesses are round 1's (NHL 2009..2026, 17 pairs; soccer 2015..2026, 12 seasons / 11 pairs;
NBA 2019..2026, 8 seasons, 240 team-seasons). No 2026-27 file was read. NBA pXPM was not touched.

NHL control here is the shipped pWAR as it now stands (nested weights refit by the lead after round 1, history back to
2007 for 2009): team R2 .403, player r .370 (round 1 read .387 / .347 before the refit).

| idea | sport | candidate | target | before -> after | t | pairs / seasons better | result |
|---|---|---|---|---|---|---|---|
| 1 game-state xG | soccer | p/90 on game-state adjusted xG | predict | not testable: no shot data with minute / score state cached | | | n/a |
| 2 per-game mean | soccer | SV / SVAR from match values | describe | not testable: no per-match player values cached | | | n/a |
| 2 per-game mean | NHL | WAR from game-level values | describe | not testable: no player-game xG (stats-API logs only) | | | n/a |
| 2 per-game mean | NBA | B2 rXPM-G (game-anchored box, mean of games) vs rXPM | held-out describe win% | .9303 -> .9232 | -1.80 | 2/8 | fail |
| 3 uncovered time | soccer | S3 GAR + uncovered 90s at c | held-out describe | .8755 -> .8756 | 0.04 | 8/12 | fail |
| 3 uncovered time | soccer | S3b SVAR + uncovered 90s at c | held-out describe | .8942 -> .8935 | -0.66 | 7/12 | fail |
| 3 uncovered time | NHL | N3 WAR + uncovered skater hours at c | held-out describe | .97819 -> .97819 (c = 0 in every fold) | 0 | 0/18 | fail |
| 4 season-only Marcel | NHL | N4 Marcel on WAR, pos mean, no age (LOPO pick .75 / 400 min) | predict team | .403 -> .362 (player r .370 -> .442) | -0.71 | 7/17 | fail |
| 6 position add-back | NHL | N6 HPM - position replacement HPM | predict team | .403 -> .485 (player r .370 -> .344) | 7.59 | 17/17 | fail (guard; gain is leakage, below) |
| 6 position add-back | soccer | p/90 already over the position line (diagnostic) | predict team | shipped .650 vs centred by position .643 | 4.97 | 10/11 | already in form |
| 7 venue offsets | NHL | home-rink player offsets | | skipped (prereg: 41/41 home-away split, no season signal) | | | n/a |
| 8 duplicates | all three | same date + same teams twice | | NHL 0, soccer 0 (182,980 matches), NBA 0 (two same UTC day pairs are real back-to-backs, different scores) | | | clean |

Holm over the six tests (N3, N4, N6, S3, S3b, B2): only N6 is significant, and it fails its guard. Nothing ships; no
pipeline file was changed.

## N6 is mostly exposure leakage (matters for the NFL pXR pass)
Once a rate's mean is not 0, the team sum picks up the level of season n+1 exposure a game. NHL skater ice time a game
is shorter for teams with more penalty kill time, so it carries n+1 results.
| version (nhl_n6check.json) | team R2 | player r |
|---|---|---|
| base pWAR, raw n+1 ice time | .403 | .370 |
| N6, raw n+1 ice time | .485 | .344 |
| one +.21 constant for every skater (no position information), raw ice time | .483 | .334 |
| base, lineup shares (5 skater hours + 1 goalie hour a game) | .424 | .368 |
| N6, lineup shares | .426 (t 2.79, 13/17) | .342 |
| one constant, lineup shares | .424 (t -.98) | .332 |
A first rescale to 5 x goalie hours still leaked (base .395, N6 .426, constant .425) through pulled-goalie time.
The real positional effect is +.002 to +.003 R2 and costs .026 player r. The NFL pXR gain (.248 -> .330) should be
rechecked the same way: add one constant to every player's pXP/60, and rerun with n+1 snaps as lineup shares.
Note also that lineup-share exposure lifts the NHL base itself (.403 -> .424): a harness point, not a metric change.

## Other notes
- N4: every fold picks w .75, K 400 min. Season-only WAR Marcel again ranks players better (.442 vs .370) and teams worse,
  as round 1's Marcel WAR. pWAR's components are season-only already, so soccer's double-count fix has no NHL target.
- N3: WAR's team leftover share and penalties term already absorb short-handed time; c = 0 in all 18 folds.
- S3: red-card time is the only real gap (.5% of minutes); 2020 / 2021 gaps are ESPN vs Understat match counts.
  Without 2020-21 the prereg grid hits its edge (c -.30, t 1.86 GAR, 1.24 SVAR); widened post hoc to -2..+.2: t .70 / .56.
- B2: the per-game mean is worse than the same box value anchored once a season (t -3.46, 1/8), the opposite of CBB.
  rXPM .930, BPM .933, season-anchored box .935 on win%, all within .005.
