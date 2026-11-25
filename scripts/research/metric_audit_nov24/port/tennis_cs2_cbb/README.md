# Port round: tennis, CS2 players, CBB, duplicate games (Nov 24 2026)

Prereg: `prereg.md` (sha256 in `prereg.sha256`), written before any score. Lockbox untouched (tennis rows to the export's
Oct 26 2026 end, CS2 maps before 2026-11-11, CBB no 2026-27). Scripts: `tennis_surface.py`, `tennis_rpa_mean.py`,
`cs2_port.py` (on `_cs2_players_dedup.py` = scripts/cs2_players.py + `cs2_maps_dedupe.patch`), `cbb_port.py`,
`cbb_war_guard.py`, `dups.py`, `dups2.py`. All numbers in `results.json`.

| idea | sport | candidate | target | before -> after | t | result |
|---|---|---|---|---|---|---|
| 7 | tennis | T-P1 player x surface residual offsets (k 10, h 365 on tune) | held 2020-26 log loss | .58740 -> .58770 | +2.95 (1/7 seasons) | fail (tune slope negative) |
| 2 | tennis | T-D1 rPA as per-match mean (k 2.24 matches) | describe held R2 | .1353 -> .1268 | +13.0 (0/15) | fail |
| 2 | tennis | SV as per-match mean | | SV is already the sum of match credits | | not a change |
| 5 | CS2 | C-P1 B/C/D-tier maps x0.7 in RWA rating | held next-month map MSE | .027826 -> .027843 | +1.65 (8/16, tune -1.3) | fail |
| 5 | CS2 | C-D1 season RWA shrunk toward 0 (k 50) | describe held R2 | .0961 -> .0869 | -3.22 (4/16) | fail |
| 2 | CS2 | C-D2 season RWA as per-map mean | describe held R2 | .0961 -> .0914 | -7.46 (0/16) | fail |
| 5 | CS2 | C-D3 K-D per round shrunk to mean (k 50) | describe held R2 | .0433 -> .0324 | -4.66 | fail |
| 5 | CS2 | C-D4 ADR shrunk to mean (k 50) | describe held R2 | .0261 -> .0177 | -4.82 | fail |
| 5 | CBB | B-P1 games vs teams outside the top 200 down-weighted | next-season team R2 (2017-25) | .6078 -> .6075 (lam 1 chosen 8/9) | -1.0 | fail |
| 5 | CBB | **B-D1 GBPM shrunk 100 min toward season mean** | half-B GBPM MSE | 16.21 -> 11.45 | 8.47 (10/10), Holm p < .001 | **pass, shipped** |
| 5 | CBB | B-D1 guard on WAR form (team wins, LOSO 2013-26) | held RMSE | 3.348 -> 3.331 | 8.2 (14/14) | holds |
| 7 | CBB | B-C1 home-court player offsets | gate: split-half r of home minus away GBPM | r .012 (17,837 players) | | not plausible, not tested |

Why the shrinks fail in CS2 and help in CBB: CS2's low-round players sit below the league mean, so pulling them to the
mean (or 0) moves them the wrong way; the round-1 fill (low-exposure mean) already does better. CBB GBPM per game is noisy
enough that 100 minutes of shrink wins every season even toward the plain mean.

Round-1 note for the lead: CS2 D4 (season RWA shrunk toward the rating at the window start) uses a prior rating, which the
season-only rule forbids; it is also not in scripts/cs2_players.py or scripts/alltime.py on disk now (alltime ships the
unshrunk window mean). C-D1 is its season-only version and fails.

## Duplicate games (idea 8)

| log (loader) | games | repeated id | same date + pair | team twice on one local date | alias / same box | action |
|---|---|---|---|---|---|---|
| nhl_games_hist (nhl_games) | 20,591 | 0 | 0 | 0 | 0 | none |
| nba_games_hist (nba_games) | 18,112 | 0 | 2 (UTC midnight, other scores) | 1 (GS Mar 1 2020, scores differ: date anomaly) | 0 | report |
| cbb_games_hist (cbb_games) | 76,938 | 0 | 126 UTC-date, 0 local | 3 (2 non-D-I doubleheader, 1 forfeit 2-0 row id 401527877) | 0 | report |
| Barttorvik player logs 2017-26 | 1,100,149 rows | 0 pid-date repeats | | | 0 | none |
| cfb_hist_md (cfb_model) | 16,498 | 0 | 0 | 0 | 0 | none |
| nflverse games.csv (nfl_games) | 7,439 | 0 | 0 | 0 | 0 | none |
| soccer_games_hist (soccer_games) | 182,980 | 0 | 0 | 15 | 15 one club under two ids (swe.1 2016 12, 2011 3) | **fixed in loader** |
| tennis matches.csv.gz | 1,078,400 | n/a | satellite legs only | | 336 re-meetings within 7 days with the same winner and score (1.87% vs .85% a year apart: about 180 excess, 297 at ITF level, 8 touch tour level); 4 non-RR alias suspects | report |
| ESEA esea_matches.json.gz | 18,217 | 0 | 0 | | 0 same ten + score | none |
| bo3.gg CS2 maps (cs2_players.Maps) | 62,134 | 0 | | | 90 maps twice (35 inside one match id, 55 under a second match / alias team) | **patch file** (cs2_players owned by the CS2 worker) |
| Valve series (cs2_history) | | | | | round 1: 27% repeats | owned by the CS2 dedupe worker |

## Files changed (not committed)
- `scripts/cbb_tabs.py`: `GBPM_K = 100`, `wx(L, mins, mu)` shrinks GBPM toward the season's minutes-weighted mean, `gmu()`;
  fit_wpp, the frozen 2025-26 lines, the live lines and the portal fallback use it; `REPL` -2.3 -> -1.6 (shrunk 9th man,
  2025-26); frozen file gains `mu`; docstring and WAR tooltip updated. fit_wpp now: wpp .0186, a .38, r .872.
- `scripts/alltime.py` cbb_players(): same shrink (per-season mean), REPL from cbb_tabs.
- `scripts/soccer_games.py`: `drop_alias_dups()` in load_rows and the three fit/backtest loads (182,980 -> 182,965 rows).
- Patch for the CS2 worker: `cs2_maps_dedupe.patch` (Maps skips a map with the same ten players, map, rounds and day).

Reruns: `python3 scripts/cbb_tabs.py --freeze && python3 scripts/cbb_tabs.py`, `python3 scripts/alltime.py`;
soccer: `python3 scripts/soccer_games.py --fit` (or the next refit workflow) then the daily build; after the CS2 patch:
`python3 scripts/cs2_players.py --fit && python3 scripts/cs2_players.py`; then `python3 scripts/library_build.py`.

## Process text (CBB WAR glossary, for the lead)
WAR's box input is GBPM shrunk 100 minutes toward that season's minutes weighted mean: (GBPM x min + 100 x mean) / (min + 100).
Tested Nov 24 2026 (pre-registered): a player's half A games predict his half B GBPM better shrunk (MSE 16.2 to 11.4, 10 of 10
seasons, t 8.5), and team WAR tracks held out team wins better (RMSE 3.348 to 3.331, 14 of 14 seasons, t 8.2).
Replacement is the 9th man's shrunk GBPM in 2025-26, -1.6. Season only: no earlier season enters a season's WAR.
