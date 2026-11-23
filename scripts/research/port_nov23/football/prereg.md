# Port pass Nov 23 2026, football (NFL + CFB): pre-registration

Written before any test below was scored. Lockbox: NFL/CFB 2026 from week 11 is never read (wf rows stop at week 10).
Every game test: absolute error paired per game, t clustered by season-week (scripts/harness.py paired). Tune 2015-20
(walk-forward rows, NFL) ; held 2021-25 (+ 2026 weeks 1-10 where the wf file has them). Pass = tune mean d < 0 AND held
one-sided p survives Holm at .05 across the six tests in this file (N1, N2, N3a, N3b, N4, C1).

## N1 NFL early-season margin stretch (G2, CFB EARLY x1.13)
Rows: scripts/data/games_wf/nfl.json.gz, regular season weeks 1-3 (wk <= 3). Candidate m' = s x m. s = slope through the
origin of res on m over the tune rows (2015-20, weeks 1-3). Applied unchanged to held rows. Loss |res - m'| vs |res - m|.

## N2 NFL early-season totals shrink (G2, CFB weeks 2-6 x .75)
Rows: weeks 2-6 with tm and tot. w = mean tm of that season-week's rows. tm' = w + c (tm - w); c = OLS slope through the
origin of (tot - w) on (tm - w) over tune rows. Loss |tot - tm'| vs |tot - tm|.

## N3 NFL fumble-neutral EPA (G4, CFB FUMN)
Offense EPA per game (nfl_games.load: passing_epa + rushing_epa) is made fumble neutral from the player-week counts:
epa_fn = epa + 3.80 (rushing_fumbles_lost - .418 rushing_fumbles) + 3.30 (sack_fumbles_lost - .528 sack_fumbles).
Constants from 2015-20 play-by-play only (rush fumble lost -4.41 vs recovered -0.61 EPA, lost share .418; sack -4.60 vs
-1.29, .528). The same walk (data/nfl_games_fit.json params) is run twice, raw and fumble-neutral box; the live fit()
walk-forward (lstsq on seasons before each season, 2015-25) scores:
- N3a margin: FEATS + epa_fn vs FEATS (live margin model has no EPA input).
- N3b totals: TFEATS with epa -> epa_fn vs TFEATS.
Tune 2015-20, held 2021-25.

## N4 NFL rookie age-adjusted rate aXP/60 (M1, NBA aXPM)
Rookie = a player's first board season (scripts/.cache/nfl/rate_rows_<y>.json, nfl_rate_research --prep) in 2016-22
with 1+ snaps, age = years on Sep 1 of that season (players.csv birth_date). Base = rookie pXP/60 as the board shows it
(season shrunk by the group K, nfl_rate_fit). Candidate aXP/60 = pXP/60 + k (age - 22), one pooled k fit leaving the
rookie's class out. Target = next three seasons' snap-weighted rXP/60, players with 100+ snaps in them, weight = those
snaps capped at 2000. Loss = weighted squared error; paired t by player, plus classes better of 7. Pass = Holm as above
and 5+ of 7 classes. Ship = display column on the NFL rookies tab only (the age hinge as a pXP/60 driver failed Nov 11).

## C1 CFB predictive season value pSV (M2, NFL pXP/60)
scripts/data/sv_hist.json.gz cfb rows (QB, RB; 2014-25). Rate = tot / pl (season points a play). Forms predicting next
season's rate (players with 100+ plays next season, weight = next plays): raw; marcel = seasons S, S-1, S-2 at play
weights 1 / .7 / .5, shrunk to the group's play-weighted mean of the training seasons, K per group from
(50 ... 3600) chosen on the training seasons. Leave one target season out (2016-25). Pass = marcel vs raw paired t <= -2
(Holm), 7+ of 10 seasons better, calibration slope .8-1.2. Ship = display data field + one column on the CFB QB SV tab.

## Not tested (other cells): see results.json matrix.

## Addendum (03:50Z brief addendum, written before N5 ran; N1-N3 had been scored, N4 and C1 not yet)
Holm family becomes seven tests (N1-N5, C1).

## N5 model-to-model: NFL SV (season value, scripts/nfl_season_value.py / sv_hist) -> pXP/60 next-season projection
Base = the shipped pXP/60 form marcelM reproduced leaving one target season out (nfl_rate_research means / mslopes /
fit_k / pred on the training seasons). Candidate = base + b_g x v, v = SV season points / (plays + 200) at season S
(0 when the player has no SV row), b_g = weighted LS slope of (target - base) on v per group, fit on the training
seasons only. Target, weights and pairs exactly as nfl_rate_research (next season rXP/60, 100+ next snaps). Circularity:
SV is built from season S play-by-play EPA; the target is season S+1 WAA (AV/XV); no shared season. Pass = Holm, 7+ of 9
target seasons better, paired t as nfl_rate_research paired().
