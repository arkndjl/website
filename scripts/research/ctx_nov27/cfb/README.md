# CFB metric context audit (Nov 27 2026)

Rule: predictive consumers read cWAR (tie XV) / Stat+ / FV / pSV/60, point in time; descriptive consumers read season-only
XV / SV / SVAR. Pre-registered in `prereg.md` (committed before scoring). Lockbox: 2026 week 11 on never read.
Rerun: `OMP_NUM_THREADS=1 python3 scripts/research/ctx_nov27/cfb/qb_prior.py` (repo files only, 20 s) -> `results.json`.

## Inventory (P = predictive, D = descriptive)

| consumer | file:line | ctx | input it reads | verdict |
|---|---|---|---|---|
| Game model team rating (Elo, opponent-adjusted EPA, ST, situational) | scripts/cfb_model.mjs:1149+ | P | walk-forward game data, weights fit on earlier weeks | OK |
| Game model preseason prior (PTS_ROSTER) | scripts/cfb_model.mjs:634, scripts/cfb_roster_prior.py | P | last SP+, 247 classes S-3..S, returning skill / QB yards share, transfers-in yards (ESPN boxes; weeks 1-2 leak check on file) | OK; QB input is volume only -> tested C1/C2, FAIL |
| Game model returning production term (`ret`) | scripts/cfb_model.mjs:310-315 | P | last season's PFN score x snaps of players back (cWAR family); avRet / avRest (returning cWAR) retested every run | OK |
| Game model QB-out charge | scripts/cfb_model.mjs:885-899 (qbTable), scripts/cfb_teams.mjs side() | P | season-to-date EPA a play, shrunk to replacement (-.2, K 500); fit form = serve form | OK. Multi-season QB value (prevW .5) lost to 0 in the consumer's harness Oct 29; pSV/60 form = LEAD (cache) |
| Game model injury charge | scripts/cfb_teams.mjs:502, 570 | P | p.sav (season AV, cWAR family) else AV at FV | OK (sav = cWAR tie; XV as input failed Oct 16) |
| Roster talent term | scripts/cfb_model.mjs:699-703, scripts/cfb_rank.mjs:69 | P | 247 composite in the fit, board FV live | OK today: weight dropped (talentUsed false). LEAK if it is ever switched back on (fit form != serve form) |
| ARK Ranking, season odds, CFP bracket | scripts/cfb_rank.mjs:149, cfb_model.mjs sim, scripts/cfb_cfp.py | P | the game model's rating, never refit | OK |
| FV (board, draft board, classes) | scripts/fetch_cfb.mjs | P | this season's Stat+ (PFN), On3 / 247 talent, consensus, frame, badges | OK (settled; Marcel and XV forms failed) |
| Next up (BO%) | scripts/cfb_breakout.py:179-188, 392 | P | PFN score z by season, Marcel history, seasons before only in the fit | OK (Stat+ z is the best within-position repeat, .511) |
| Transfer% | scripts/cfb_transfer.mjs:78-98 | P | this season's PFN score percentile, playing time, pedigree, HC change | OK |
| Team builder | scripts/cfb_transfer.mjs:169+, fetch_cfb.mjs | P | next-season FV (young[].next, dev step), AV at FV | OK |
| xNIL / zNIL | scripts/fetch_cfb.mjs:1636-1662 | P | AV at FV x playing time; fv / sav / ev picked each run by fit to On3 | OK; LEAD: in-sample pick each run can flip the value basis between runs |
| Depth chart tiles | layouts/shortcodes/depthchart.html:41 | P | FV | OK |
| Backup watch grade | scripts/backup_watch_cfb.mjs:66-72 | P | WAA a full-time share (cWAR family), shrunk to replacement K 300 | OK |
| Mock draft (predictive, blended, conviction), UDFA | scripts/cfb_teams.mjs:22, 1256-1261, 1767 | P | consensus + FV (pred), FV grade (conviction) | OK |
| Team talent, class rankings, portal net, transfer watch | layouts/shortcodes/cfbteams.html, cfbportal.html, xferwatch.html | P | FV (AV at FV) | OK |
| Returning tab | layouts/shortcodes/cfbreturning.html | P | the live prior's returning shares and weights | OK |
| Predictive awards (Heisman and the rest) | scripts/awards.py:910-957, scripts/awards_football.py | P (of a vote) | season box line at pace, team record, model win odds | OK |
| Conviction awards | scripts/awards.py:1153-1184 | D | SVAR (data/cfb_season_value.json), season only | OK |
| WAR leaders | assets/js/cfb.js:317, 444 | D | sorted by XV | OK |
| QBs tab | layouts/shortcodes/cfbqb.html:12 | D | ranked by XV | OK |
| QB SV, skill players | layouts/shortcodes/cfbseason.html, scripts/cfb_season_value.py | D | SV key, SVAR, pSV/60 companion (QB); board companion was WAR only | DISPLAY -> fixed: XV beside SV (as the NFL tabs since Nov 24) |
| Standouts | layouts/shortcodes/cfbbreakout.html | D | touches + targets jump, last 2 games; FV shown as a companion | OK |
| True freshmen | scripts/rookies.py:481 | D? | key = FV; pro rookies tabs lead with the describe pick | DISPLAY question for Noah (same on CBB), not changed |
| All-time players / QBs / teams | scripts/alltime.py:520-662, 1055 | D | era-adjusted season lines, SV / SVAR, ridge SRS by season | OK |
| Top performers | layouts/shortcodes/cfbtop.html | D | one week's box score points | OK |
| News weights | scripts/news.py:166 | n/a | FV tier, pre-game model odds | OK |

Mismatches: MISMATCH-P 1 (roster prior QB input: volume, no quality; tested, fails), MISMATCH-D 0, LEAK 0 live (1 dormant:
talent term), DISPLAY 1 fixed + 1 question.

## Tests (Holm over two, held out 2021-25 + 2026 weeks 1-10, 4,212 FBS games, walk-forward prior)

| swap | target | before -> after | t / p | seasons better | result |
|---|---|---|---|---|---|
| C1 roster prior + returning QB quality (back share x preseason pSV z) | game margin MAE | 12.6304 -> 12.6312 | +0.33 / .63 | 4/6 | FAIL (weight .12 pts a SD) |
| C2 roster prior, QB yards share -> returning QB quality | game margin MAE | 12.6304 -> 12.6442 | +1.14 / .87 | 0/6 | FAIL |

Log loss guard: C1 +.00004, C2 +.0005 (both worse). Weeks 1-4 only: C1 t -0.24, C2 t +1.77.
Harness note: a rebuild of scripts/cfb_roster_prior.py on repo files (games_wf margins 2017-26, cfb_roster_feats.json,
sv_hist.json.gz); base held-out MAE 12.63 vs the original's 13.07 on 2021-26 (different game set: games_wf drops unlined games).

## Not retested (condition unchanged)
- QB-out charge on multi-season QB value: scripts/cfb_qb_backup.mjs grid, prevW {0, .5}: tune picked 0 (Oct 29).
- XV as the game prior / builder / xNIL value (Oct 16), Marcel on cWAR and experience delta (Nov 24), point-in-time FV in
  next up (Nov 23), SV in the game model (Nov 22, t +0.5).

## Leads
- pSV/60 form in the QB-out charge: `python3 scripts/cfb_espn_pbp.py 2015 2026 && node scripts/cfb_qb_backup.mjs build &&
  node scripts/cfb_qb_backup.mjs test` with a spec { prevW: .7, prevW2: .5, k: 650, shrink to the QB mean } (needs the ESPN
  play-by-play cache, hours of pulls).
- Transfers-in QB quality (pSV of the incoming QB) needs the ESPN box cache for who is on the roster in August.
- Roster talent term: if `talent` ever re-enters the game model, fit it on point-in-time board FV (scripts/data/cfb_ret_fv.json)
  or serve the 247 composite; today the weight is 0.

## Round 2 (port round)

| item | what was checked | result |
|---|---|---|
| P1 CFB xGap own fit on the cWAR (WAA) gap | PFN history pages 2019-25 pulled (pfn_pull.py). Past seasons list qualifiers only (QB 148-190 a season over 128-136 teams, WR 316-370, LB 188-345), no class column, OL / CB / S only 2024-25. No backups, so no depth chart two seasons back. | BLOCKED by data, not run. CFB keeps the borrowed CBB terms. The live gap SD (.0504) still equals the SD the terms were scaled on (.0505, Nov 11). |
| P2 CFB predictive awards, games-left rate | Candidate pre-registered: box rate shrunk to the player's last-season rate, K 4 games. Hook added: `LEFT_K` in scripts/awards.py (0 = unchanged), `--leftk=` and `prev` rates in scripts/awards_asof.py. Player boxes download fine; Wikipedia (Heisman votes, award winners) answers 429 from this container, so the harness has no outcomes. | BLOCKED, not scored. Rerun: `python3 scripts/awards_asof.py cfb --noscore --sims=1000 --tag=_ctx_base && python3 scripts/awards_asof.py cfb --noscore --sims=1000 --tag=_ctx_k4 --leftk=4`, then compare winner log loss by season (pass rule in prereg.md). |
| P4 Transfer% / landing / team builder, serve form vs fit form | Fit (scripts/cfb_transfer_fit.py) and serve (scripts/cfb_transfer.mjs pfnIndex) build `q`, `pct`, `starter` the same way, but the PFN pool differs: the 2026 page lists WR 509 / LB 479 / CB 643 / QB 179 FBS rows against 323-370 / 188-337 / 505-521 / 151-190 in the fit seasons 2024-25. Live `q` flags more players and `pct` is a percentile over a deeper pool, so the same player reads higher live (feeds pct, pct_tal -1.12, pct_g5 +.58, the entrenched-starter rule at pct >= .75, landing `_prod`). Builder value is next-season FV: same form. | LEAK (serve form drifts from fit form), not fixed: the fit rows cache (scripts/.cache/transfer) is not in the container, so the aligned form cannot be scored. Proposed fix: in pfnIndex keep the top N by volume a position (N = mean rows of the fit seasons on the same page) before the percentile; test with `python3 scripts/cfb_transfer_fit.py` scoring 2025->26 with 2025 cut the same way. |
| P5 stale fits | Fit dates against the metric they read: cWAR lines last moved Oct 13-14 (cfb_war_backtest Oct 14, cfb_war_pos Oct 14), XV Oct 16 (cfb_xv_backtest Oct 16), Nov 24 changed team WAR only (no fit reads it). Transfer fit Oct 11 and breakout / dev fits read PFN score, not rebuilt. backup_age CFB terms Nov 11 on the current gap scale. | None stale. (git log is squashed in this checkout, so dates are the files' own asof.) |
| P6 next up companion | Next up is a player-level predictive tab; Stat+ z is the best within-position repeat (.511 vs cWAR .461, Nov 24 table). cWAR is the team-level pick. | OK, Stat+ stays. |
| P6 true freshmen | Season board of freshmen who play, led with FV; pro rookies tabs lead with the describe pick. | DISPLAY fixed: key XV, FV second view (scripts/rookies.py, static/data/rookies/cfb.json regenerated; 650 of 767 rows carry XV, the rest sort last as they did on WAR). CBB analogue: scripts/rookies.py:533. |

Round 2 commits: 97b69e7 prereg addendum, 694cb75 true freshmen lead with XV, plus the awards hook and this section.
For Noah: true freshmen now open on XV; FV is one tap away. Say so if the college tabs should stay FV first.
