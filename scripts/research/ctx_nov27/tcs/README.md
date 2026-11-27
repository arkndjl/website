# Metric context audit, Nov 27 2026: tennis, CS2, 1NT, LAURSEN_111

Pre-registered in prereg.md (committed before any score). Lockbox: nothing on or after 2026-11-11 in a test.
Scripts: t1_live_form.py (-> t1.json, ~12 min). results.json holds the test table and the rule fixes.

P = predictive context, D = descriptive. Verdicts: OK, MISMATCH-P, MISMATCH-D, LEAK, DISPLAY.

## Inventory

### Tennis

| consumer | file:line | ctx | input it reads | verdict |
|---|---|---|---|---|
| ARK Ranking (headline, sort) | tennis_model.py:846 ark_board, :488 predict(match=False) | P | Elo + points + games ratings + pPA term, today | OK |
| 1Y / 24 / 36 mo projection | tennis_model.py:1011, :1120; tennis_proj_research.py:98 | P | logit ARK (with PA) at the quarter end, age, volume, rank | OK (fit RMSE .453 / .415 differs from the pre-PA .497 / .461: refit on the PA form) |
| match model (games, game table) | tennis_model.py:488 predict, :313 ctx | P | ratings + rest / age / h2h / form / market memory + pPA gap; CW (WAR a match) weight 0 | OK |
| event odds | tennis_events.py:188, :310 | P | Model.predict on today's ratings | OK |
| picks | tennis_picks.py:270 | P | tennis.json match chance | OK |
| WAR column | tennis_model.py:359 | P | 52 weeks, level weighted | OK (label says so) |
| SV column | tennis_model.py:367 | D | calendar year, every match in full, no level weight | OK |
| serve + return tab sort and lead (PA) | tennisstats.html:14 | D | pPA: every match ever, half-life 365 days, shrunk 300 points | settled pick (PA); carries a multi-season weight, see "For Noah" |
| rPA, SPW, RPW, hold, break, DR | tennis_model.py:348, :898 raw52 | D | last 52 weeks only (rPA shrunk 300 points inside the window) | OK |
| SPW+ / RPW+ / xHold / xBreak | tennis_model.py:1139 | P | Kalman serve / return ratings | OK (labelled opponent-adjusted ratings) |
| badges | tennis_badges.py, tennis_model.py:1128 | P | 52-week ace rate, grass Elo gap; passed held out | OK |
| prospects FV | tennis_prospects.py:295 features, :1285 build | P | snapshot rank, own Elo, age, level counts as of the snapshot | OK (fit rows need rows.pkl, not rerun) |
| all-time peaks / careers | alltime.py:268 | D | year-end Elo over the year's 20th best | MISMATCH-D (lead L3; file belongs to the cross lens, cache missing) |

### CS2

| consumer | file:line | ctx | input it reads | verdict |
|---|---|---|---|---|
| RWA leaders headline, 90d, 6M | cs2_players.py:159 ratings, build | P | RWA rating (half-life 180 d, shrink, opponent credit, tier lift) | OK (ratings board) |
| RAR (RWA leaders, transfer values) | cs2_players.py build row() | D | was rating x last-year rounds | **MISMATCH-D, fixed (R1)** |
| prospects FV, 1Y, T1% | cs2_players.py prospect_rows, prospect_fit, build | P | rating at the cutoff, age, S/A share; target next year's lines | OK |
| series model player term | cs2_players.py Live, game_test | P | five's mean rating: month's first day in the fit, today's in the serve | **LEAK (fit form != serve form), fixed (T1)** |
| ARK Ranking, games, map pool | cs2_model.py build | P | player Elo + VRS + map rating + player term, point in time through replay() | OK |
| event odds, pick'em | cs2_events.py:183, :245; cs2_pickem.py:255 | P | the series logit, same Live term | OK after T1 (monthly fits pick up the day form) |
| team RWA column | cs2_players.py build | P | five's rating | OK |
| xTV / xMV, team values, signings | cs2_value.py:121 | P | rating at the day (first map of the stint for "at signing") | OK |
| transactions | cs2_value.py:386 | P | rating then / now | OK |
| all-time peak seasons, careers | alltime.py:980 | D | year's own lines (window_stats) + tier lift over that year's replacement | OK |
| 1NT world rank | esea_world.py:44 | P | ARK sort key against data/cs2.json arkPool | OK (ARK Ranking, not VRS) |

### 1NT / LAURSEN_111

| consumer | file:line | ctx | input it reads | verdict |
|---|---|---|---|---|
| preview: series win %, projected maps, spread, total | fetch_esea.mjs:1331 RWA_W, :1338 preview | P | elo / talent logit + career RWA gap of the expected five | OK |
| veto model | fetch_esea.mjs:1113 | P | lifetime map-split deviations, de-leaked | OK |
| playoff bracket odds | fetch_esea.mjs:1947, QUOTE | P | the preview logit (league log pricer) | OK |
| regular-season sim, stakes (playoff / seed odds) | fetch_esea.mjs:1689, :1718 | P | FACEIT team elo only | MISMATCH-P (lead L1: season over, git history needed) |
| power rank (ESEA ARK Ranking #) | fetch_esea.mjs:795 | P | .20 round diff, .20 team ARK, .60 elo | MISMATCH-P candidate (lead L2) |
| team RWA column | esea_rwa.py:112 | P | career RWA of the five most used | OK; tooltip said "this season" (DISPLAY, fixed R3) |
| S59 player rankings sort and lead | esea.html:1163 | D | career RWA (.p) | **MISMATCH-D, fixed (R2)** |
| season_stats, players_sNN cards, roster | esea.html:335, :1272, :1306; partial esea/rwa.html | D | season RWA / ARK (.seasons) | OK |
| milestones division ranks | esea_milestones.py:294 | D | season_lines (that season's maps) | OK |
| 1NTERLYTICS rolling table | esea.html:974 | P | career RWA, labelled | OK |
| map box scores, map MVP | fetch_esea.mjs:870 | D | the map's own line + opposing five's career RWA as opponent credit | OK |
| road to pro earnings model | n1_road.py, data/n1_road_inputs.csv | P | population transition rates, live bracket odds | OK |
| LAURSEN_111 CS2 FV | csprofile.html:30, cs2_players.py eseaFv | P | off until the ESEA retest passes | OK |
| LAURSEN_111 PUG form, daily, split | fetch_esea.mjs:894-1040 | D | his own recent maps | OK |

GFX builders in assets/js/gfx.js read the tables' cells; not traced past the source key (shared file).

## Tests

| swap | target | before -> after | t (by month) | k/n | result |
|---|---|---|---|---|---|
| T1 player term fit on series-day ratings (A) vs live now: month fit, day serve (C) | held series log loss, Jul 2025 - Nov 10 2026, 15,975 series | .59476 -> .59460 | +0.47 (row t -1.48) | 10/17 | tie |
| T1 A vs the shipped backtest: month fit, month score (B) | same | .59540 -> .59460 | -0.62 (row t -2.13) | 10/17 | not worse |
| T1 guard: top-50 pairs, A vs C / A vs B | 1,759 series | .64852 -> .64862 / .64854 -> .64862 | +0.05 / +0.41 | 8/17 | holds (< +1) |

Rule 2 of the prereg: a tie on A vs C, A vs B under +2, guard holds -> **ship A as an alignment, no measured gain**.
Holm over one test. Weights: top [.4493, .2412, .7494, 3.333] -> [.4151, .2491, .7509, 3.395]; rest [.8944, .1426, .7573,
3.741] -> [.8441, .1433, .7061, 4.080]. Refit gate (cs2_players game_test, row t): all -11.55, top 50 -2.06 (was -11.4 / -2.06):
the term stays on. Month-start and series-day z correlate .974.

## Shipped

- T1 `scripts/cs2_players.py`: `Snaps` (ratings by day, disk cache in scripts/.cache/cs2), `game_test` and `Live.mean`
  read the series' day; `--game` refits only that block. Ran `python3 scripts/cs2_players.py --game`, then
  `cs2_players.py`, `cs2_value.py`, `board_moves.py cs2`.
- R1 `scripts/cs2_players.py` build: RAR = last year's rounds x (last year's own RWA + tier lift, minus the pool median
  of the same) / 100. 400 board rows: r .987 with the old RAR, mean change 7 rounds, top 7 order unchanged.
- R2 `scripts/esea_rwa.py` writes `seasonAll` {season, p: {FACEIT id: [season RWA, rounds]}}; `layouts/shortcodes/esea.html`
  playerrankings sorts and leads with it, career RWA in the cell hover. Falls back to the career label until the key exists.
- R3 team RWA tooltip says career.

Rerun by workflow: `esea.yml` (esea_rwa.py needs the run's .cache/esea/rounds.json for this season's maps; offline it
sees 0 of 375 live maps), `cs2.yml` (cs2_model.py: upcoming chances and recent results on the new weights; on the 1st
cs2_events --fit and cs2_pickem --prep / --fit refit on the day form).

## Leads

- L1 1NT season sim and stakes on the preview logit instead of FACEIT elo. S59 regular season is over, so nothing on
  the page moves until S60. Test: `git fetch --unshallow && python3 scripts/esea_research.py` (S59 page inputs from the
  history of data/esea.json), sim chance = preview logit vs pEloGap, leave one day out, pass t <= -2. Prior evidence:
  elo alone .586, elo / talent + RWA .516 on the same 154 matches (esea-rwa-nov03).
- L2 1NT power rank: team RWA in place of (or beside) team ARK at .20. Same harness and rule.
- L3 tennis all-time season value on SV (season WAR) instead of year-end Elo: `python3 scripts/alltime_pull.py` then
  `python3 scripts/alltime.py` with the era gate; needs the pull cache.
- L4 the forward league log (scripts/data/esea_league_log.jsonl, 120 lines, first match Nov 16): all lockbox, not read.

## Cross-sport analogues

- T1 (fit a model term on the same freshness the serve reads): any game model whose player or lineup term is fit on
  period-start snapshots and served on today's values: NBA / NHL / CBB lineup value terms, NFL QB term, soccer lineup
  term, tennis market memory (already lagged by CM_LAG in the fit).
- R1 (value-above-replacement totals on the season's own lines, not rating x exposure): NBA VORX / SV, NHL WAR,
  soccer SVAR, CBB VORX, NFL XV totals wherever a board multiplies a predictive rate by season minutes.
- R2 (a league-wide season leaderboard sorted by the season number, career rating in the hover): G League, CBB
  low-division and international boards, soccer league leaders.

## For Noah

- Tennis "serve + return" tab sorts and leads with PA = pPA, which weights every past season (half-life a year). It is
  the settled describe pick and won the held-out half test, the same way CS2's shrink-to-prior season RWA did before
  the season-only rule kept it out. The season-only form is rPA (52 weeks, shrunk 300 points; held-out .135 vs .141).
  Left as is. One-line change if the rule should bind here too: `sort $t.players "rpa" "desc"` in
  layouts/shortcodes/tennisstats.html and swap the bold column.
