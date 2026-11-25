# Tennis metric audit, Nov 24 2026

Pre-registered in prereg.md (sha256 3eec84fd...) before any score was read. Lockbox: nothing after 20261110 (the history
export used ends Oct 26 2026). Scripts: passes.py (full pass and half-A pass of the live model, Dec 31 snapshot of every
metric), score.py (harness -> results.json), compare.py (paired head-to-heads, per-tour splits -> compare.json).

Harness (no team): pool = 10+ matches in season n and a 52-week rPA; scored = tour-level main-draw matches (no
qualifying, no retirements) between two pool players. P(winner) = sig(b x metric gap), McFadden R2 = 1 - LL / ln 2.
Describe in-sample: season n metric (every row) on season n matches. Describe held out: metric from a pass on half A of
every match (fixed hash), scored on half B, slope left out by season. Predict: Dec 31 metric -> season n+1 matches,
slope left out by pair. Player r: n vs n+1 value, centred by tour-season, weighted by n+1 matches. Seasons 2011-25
(pairs to 2026). 90% intervals: seasons resampled. Matches: 56,363 in-sample, 27,805 held-out half, 54,400 predict.

| metric | describe R2 (in-sample) | describe held-out | predict R2 (next season) | predict player r | n pairs |
|---|---|---|---|---|---|
| ARK (board, before) | .177 [.170, .185] | .131 [.123, .139] | .105 [.098, .114] | .880 [.873, .889] | 15295 |
| **ARK with PA (shipped)** | .181 [.174, .189] | .137 [.129, .146] | **.107 [.100, .116]** | .898 [.891, .906] | 15295 |
| Elo overall (ours) | .185 [.177, .194] | .131 [.123, .139] | .107 [.100, .117] | .928 [.921, .935] | 15295 |
| TA / 538-style Elo (public form) | .187 [.180, .196] | .132 [.125, .140] | .107 [.099, .116] | .915 [.908, .924] | 15295 |
| points rating (serve + return) | .138 [.132, .145] | .100 [.092, .109] | .083 [.077, .091] | .778 [.767, .790] | 15295 |
| **PA (pPA)** | .174 [.167, .182] | **.141 [.133, .151]** | .103 [.095, .112] | .910 [.900, .921] | 15295 |
| rPA raw (before) | .188 [.181, .196] | .128 [.119, .138] | .098 [.091, .109] | .719 [.700, .742] | 15295 |
| rPA shrunk 300 (shipped) | .189 [.182, .197] | .135 [.127, .145] | .100 [.093, .110] | .829 [.819, .841] | 15295 |
| WAR 52 wk (before) | .163 [.154, .174] | .099 [.092, .106] | .083 [.075, .093] | .808 [.792, .821] | 15295 |
| WAR level-weighted (shipped) | .168 [.159, .177] | .098 [.091, .104] | .085 [.077, .095] | .814 [.796, .828] | 15295 |
| SV season WAR (= WAR at Dec 31) | .163 [.154, .173] | .099 [.092, .106] | .083 [.075, .093] | .808 [.790, .820] | 15295 |
| WAR a match (shrunk 10) | .190 [.182, .198] | .102 [.095, .109] | .097 [.089, .106] | .834 [.824, .843] | 15295 |
| wins | .049 | .022 | .009 | .314 | 15295 |
| W-L | .085 | .027 | .024 | .260 | 15295 |
| win % | .095 | .025 | .028 | .327 | 15295 |
| games won % | .079 | .028 | .025 | .384 | 15295 |
| SPW raw | .072 | .039 | .040 | .601 | 15295 |
| RPW raw | .010 | .002 | .001 | .414 | 15295 |
| dominance ratio | .106 | .042 | .049 | .432 | 15295 |
| official rank (-log) | .162 | n/a (uses held half) | .083 | .862 | 15295 |
| official rank points (log) | .157 | n/a | .081 | .800 | 15295 |

Best descriptive: **PA** (pPA). Held out it beats every other metric paired: ARK with PA -32e-4 log loss (t -4.2), rPA
shrunk -42e-4 (t -4.6), Elo -75e-4 (t -6.6), TA-style Elo -65e-4 (t -5.6), 12-14 of 15 seasons. (In-sample, the
unshrunk rates, WAR a match and rPA, lead because they fit the same matches; that is the overfit the held-out half removes.)
Best predictive: **ARK with PA** and Elo tie (ARK-PA minus Elo +0.7e-4, t +0.2); per the tie rule, ARK (our headline,
the match model's own rating). Our Elo beats the TA / 538 form (-6.5e-4, t -4.0, 10/15). Old ARK lost to Elo (t +2.9).
Official rank and points trail Elo / ARK on both targets. Prospect FV: not on this harness (outcome = a peak years
later); its LOBO / forward test in tennis_prospects_fit.json stands.

## Candidates (Holm within family, pass = Holm p < .05, 9+ of 15 seasons better, player r not down > .01)

| candidate | target | before -> after R2 | d log loss x1e4 | t (by tournament) | Holm p | seasons | ATP / WTA t | result |
|---|---|---|---|---|---|---|---|---|
| D1 SV level-weighted | describe held | .0988 -> .0978 | +6.9 | +2.66 | .996 | 4/15 | +2.8 / +1.2 | fail (worse) |
| D2 rPA shrunk 300 | describe held | .1281 -> .1353 | -50.2 | -9.77 | <.001 | 15/15 | -4.3 / -8.7 | **pass** |
| P1 ARK with PA term | predict | .1054 -> .1074 | -13.8 | -8.67 | <.001 | 14/15 | -6.4 / -5.7 | **pass** |
| P2 WAR level-weighted | predict | .0831 -> .0852 | -14.5 | -7.14 | <.001 | 12/15 | -4.2 / -5.8 | **pass** |

P2 is scored on Model.war as shipped (front-trimmed 52-week window); the research copy matched to 1e-15 for ARK and rPA.
Level weights help the predictive WAR and hurt the descriptive SV, so SV keeps the unweighted credit.

## Shipped (on disk, not committed): scripts/tennis_model.py
- `lvw()` new; `Model.value_update` stores the level weight in `wq`; `Model.war` sums credit x weight (SV, war_rate unchanged).
- `Model.rpa(pid, day, k=PA_K)`: shrunk by 300 points (k=0 = raw).
- `Model.predict(match=False)`: A logit Elo + B logit points + G games + CP x (pPA gap) / 10 (match weights);
  `set_ref` gives the reference the top 50's mean pPA; `model_sig` carries `_ark='pa'` so the next build rebases moves.
Rerun: `python3 scripts/tennis_data.py --offline && python3 scripts/tennis_proj_research.py --refresh` (projection is fit on
logit ARK), `python3 scripts/tennis_badge_backtest.py` (badges conditioned on ARK), then `python3 scripts/tennis_model.py`,
`python3 scripts/tennis_events.py`, `python3 scripts/library_build.py`.

## Cross-sport analogues
- Shrink a raw rate toward 0 by a fixed exposure (rPA K): any per-possession / per-snap rate shown raw (Stat+ rates,
  CS2 per-round rates) before it goes on a descriptive tab.
- Put the player-value term the match model already uses into the shown rating (ARK + CP): CS2 ARK / Elo with its RWA term.
- Down-weight lower levels in a predictive value total (WAR): soccer / CBB / CS2 value from minor leagues or tiers.
