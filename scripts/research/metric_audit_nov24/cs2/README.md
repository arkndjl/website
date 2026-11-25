# CS2 metric audit (Nov 24 2026)

Prereg: `prereg.md` (sha256 d3515dc6...). Scripts: `harness.py` (players, ~5 min), `team.py` (series, four replays,
~5 min), `candidates.py` (~15 min), `results.py` -> `results.json`. Lockbox: maps/series before 2026-11-11 only.
Period = month; 28 months described (Jul 2024 - Oct 2026), 27 month pairs predicted, 18,560 player pairs (100+ rounds both months).
Describe = month values -> that month's maps (five summed, A minus B, vs round share); held out = values from one hash
half of the month's maps scored on the other half. Predict team = value at month end (board form: rating, or last-year
mean for public stats) -> next month's maps. Player r = month-end value vs next month's box RWA (pm 0), rounds-weighted.
90% intervals: month bootstrap.

| metric | describe R2 (in-sample) | describe held-out | predict team R2 | predict player r | n pairs |
|---|---|---|---|---|---|
| RWA rating (board) | .235 | **.151** [.141, .161] | **.124** [.115, .133] | **.820** [.812, .828] | 27 / 18,560 |
| season RWA (all-time seasons) | **.317** [.308, .325] | .091 | .069 | .730 | 27 / 18,560 |
| season RWA + D4 shrink (passed, not shipped) | | .147 (held months) | | | 16 months |
| box RWA (pm 0) | .300 | .091 | .069 | .732 | 27 / 18,560 |
| K-D per round | .239 | .042 | .075 | .577 | 27 / 18,560 |
| HLTV 2.0 (community approx.) | .196 | .044 | .069 | .555 | 27 / 18,560 |
| bo3.gg rating | .217 | .035 | .065 | .531 | 27 / 18,560 |
| ADR | .173 | .024 | .045 | .368 | 27 / 18,560 |
| KPR | .182 | .024 | .035 | .463 | 27 / 18,560 |
| KAST | .060 | .021 | .032 | .347 | 27 / 18,560 |

Public stats as monthly values predict worse still (.018-.034). HLTV 3.0 not reproducible (round swing needs a win model
HLTV does not publish). Prospect FV (own backtest, data/cs2_players_fit.json): held MSE .905 rating now -> .813 live (t -7.1).

Team (series, walk-forward tiered logistic, held Jul 2025+ log loss; `team.json`):

| rating | all rows (as shipped backtest) | Valve repeats dropped |
|---|---|---|
| ARK live blend (player Elo, VRS, map rating) | .5538 | **.6134** |
| ARK live, replay with repeats removed | .5506 | .6113 (t by month -2.6 vs shipped) |
| ARK player Elo alone, live | .5670 | .6384 |
| team RWA (five's rating, month start) | .6262 | .6245 |
| ARK player Elo, month start | .6480 | .6429 |
| bo3 team map rating | .6500 | .6473 |
| VRS points | .6670 | .6637 |
| team-name Elo | .6806 | .6803 |

Describe (team): ARK player Elo at month end R2 .257 in-sample, .102 on the held half; team RWA .171; VRS .068.

**Data finding.** 8,847 of 32,643 Valve series rows (27%) repeat an earlier row the same day with the same ten players
under other team names (98.4% same winner): one series listed several times. The replay predicts each copy after
updating on the first, so the shipped ARK backtest (.5538) and the rolling-seal walk-forward read leaked rows. On
repeats live ARK player Elo scores .306; on first rows it is no better than ratings frozen at the day's start.

Best predictive: RWA rating (players), ARK live blend (teams; still first with repeats dropped).
Best descriptive: season RWA in-sample; held out RWA rating .151 vs shipped season RWA .147 (overlap, pick season RWA).

## Candidates (Holm within batch, t by month on held months Jul 2025 - Oct 2026)

| candidate | target | before -> after | t | p (Holm) | months | tune t | result |
|---|---|---|---|---|---|---|---|
| P1 bo3.gg rating as 14th stat | next-month map MSE | .027816 -> .027815 | -0.18 | .43 | 7/16 | +0.96 | fail |
| P2 player x map offsets, kmap 1000 | next-month map MSE | .027816 -> .027691 | -7.02 | 6e-6 | 15/16 | -3.74 | **PASS** (player r .4957 = .4957) |
| P3 ridge l2 1e-3 | next-month map MSE | .027816 -> .027816 | -0.26 | .80 | 11/16 | +0.17 | fail |
| D1 season RWA pm 1.0 | held-out describe R2 | .097 -> .093 | -4.99 | 1.0 | 2/16 | -6.93 | fail (worse) |
| D2 season RWA pm 0 | held-out describe R2 | .097 -> .097 | -0.06 | 1.0 | 8/16 | +1.26 | fail |
| D3 bo3.gg rating as 14th stat | held-out describe R2 | .097 -> .097 | +0.43 | 1.0 | 10/16 | -0.81 | fail |
| D4 shrink to window start rating, k 400 | held-out describe R2 | .097 -> .147 | +10.4 | 6e-8 | 16/16 | +8.36 | PASS held out; NOT shipped (season values stay season-only, Noah's rule) |

Implemented (Nov 24, on the lead's follow-up): P2 in `scripts/cs2_players.py` (map_key, map_offsets, map_offset_score
-> fit "mapOffsets", board rows "mp"). D4 reverted. Valve repeat rows: `scripts/cs2_model.py` repeats_dropped(), applied inside
replay() (every CS2 replay: cs2_model fit/build, cs2_ark_loop, game_test, cs2_events, cs2_pickem, cs2_poly, esea_world) and
team_elo. Reran cs2_model --fit, cs2_ark_loop --force, cs2_players --fit, cs2_model, cs2_players. Clean rows: ARK + VRS held
.5540 -> .6105; loop record t -8.66 (16/16, top 50 -0.06, slope .964), picks span .3 (Kmin 180 no longer picked); series
player term t -11.4, top 50 -2.06. team.py numbers above were computed before the fix. alltime.py not rerun (needs caches).
