# Soccer context audit, Nov 27 2026

Rule: predictive consumers read p/90 (SV 3 seasons + age) or a tested better point-in-time input; descriptive ones read
season-only SV / SVAR. prereg.md was written before scoring (prereg.sha256). `run.py` (T1 T2 T4) -> results.json,
`inj.py` (T3) -> inj.json, `aw.py` (T6) -> aw.json. Season files 2015..2026 only; 2026-27 never an outcome.
Caches: untar /mnt/project-files/soccer/understat_cache.tgz and tminj_cache.tgz into scripts/.cache/soccer.

## Inventory

| consumer | file:line | context | input it reads | verdict |
|---|---|---|---|---|
| GAR board lead, rank, weekly move | layouts/shortcodes/soccerplayers.html:188, scripts/board_moves.py:60 | D | SVAR (GAR, SV beside it) | OK |
| rookies / standouts | scripts/rookies.py:406 | D | SVAR key; aGAR/90 as its own column | OK |
| all-time peak seasons | scripts/alltime.py:142 | D | SVAR | OK |
| transactions values | scripts/transaction_values.py:118 | D | GAR, SVAR | OK |
| Ballon d'Or + league award conviction | scripts/awards.py:1300, 1377 | D | SVAR pool and rate | OK |
| Ballon d'Or voter model | scripts/awards_soccer.py:17 | D, fitted | GAR (three-season plus-minus inside) | MISMATCH-D, T6 fails on 9 of 11 seasons: keeps GAR |
| Serie A MVP, UNFP voter models | scripts/awards_soccer_more.py:19 | D, fitted | GAR | MISMATCH-D, T6: UNFP not worse, Serie A blocked: lead |
| team dropdown key players | scripts/team_detail.py:100 | D | GAR | DISPLAY, fixed: SVAR |
| site search player order | scripts/search_index.py:170 | D (order only) | GAR | DISPLAY, minor, left |
| badges | scripts/soccer_badges.py | D | season rates' percentiles | OK |
| p/90 | scripts/soccer_players.py rate_attach | P | SV 3 seasons 1/.5/.25 + age | OK |
| depth chart | scripts/depth_stats.py:65 | P | GAR and p/90 | OK |
| next up rate column | scripts/next_up.py:84 | P | p/90 | OK |
| next up breakout odds | scripts/soccer_breakout.py:205-237, data/soccer_breakout_fit.json | P | GAR a 90 shrunk + blocks | LEAK: fit predated the GAR rebuilds (n 9,683 vs 10,270 rows now, rate .060 vs .053). Refit. T4 (+p/90) fails |
| next up ceiling | scripts/soccer_breakout.py ceil_inputs, data/soccer_ceiling_fit.json | P | GAR Marcel 5/4/3 | lead: same staleness likely, not rerun |
| 1Y / 3Y + P20/P80 | scripts/soccer_players.py:930-1014, data/soccer_proj_fit.json | P | GAR pace + GAR of S-1, S-2 | LEAK: fit on the Nov 9 line, served on Nov 27's. Refit. MISMATCH-P prior: T2a passes, shipped |
| xMV | scripts/soccer_mv.py:615, data/soccer_mv_fit.json | P | GAR now / 1 / 2 seasons | LEAK (small): fit Nov 19 on the Nov 9 line, served on Nov 27's (.002-.012 a 90). Blocked: Transfermarkt dump |
| backup watch grade | scripts/soccer_players.py:1079 | P | GAR value over the fringe line, this season + .5 last, K 900 | fit and serve agree (gar_fringe). T1 (p/90) fails: OK |
| backup xGap age term | scripts/backup_age_fit.py:195 | P | gar90 from the season files | minor: fit shrinks to the board line, serve to the fringe line. Lead |
| game model injury term | scripts/soccer_tm_injuries.py:112-124 | P | prior-season GAR a 90 moved to the fringe line | fit and serve agree. T3 (new p/90) fails at tune: OK |
| game model, ARK Ranking, season odds, UEFA, leagues, MLS, international | scripts/soccer_games.py, soccer_intl.py | P | earlier closes + xG team ratings; no player metric but the injury term | OK |
| lineups, props inputs | scripts/soccer_lineups.py, soccer_props_snap.py | P | minutes / shot rates; no GAR, SV or p/90 key | OK |
| prospects FV | scripts/soccer_prospects.py:361-472 | P | its own Transfermarkt-rating value, point in time (audited Nov 11) | OK, not retested |
| news | scripts/news.py:222 | D | transfer market value | OK |

gar_fringe (audit-nov09 lead): the projections and xMV were already refit off the fringe line (garLine bottom3, Nov 19),
so their "earlier fringe line" tooltips were stale (removed). What was left was the Nov 27 line change: both fits were
trained before it. Projections refit here; xMV needs the dump. Backup watch and the injury term still read the fringe
line on purpose and consistently.

## Tests (Holm at .05 over T1, T2a, T2b, T3, T4)

| swap | target | before -> after | t / p | k/n | result |
|---|---|---|---|---|---|
| T1 backup grade -> p/90 | pair gap next two seasons, GAR a 90 (walk-forward MSE) | .002422 -> .002415 | t -0.3 | 2/7 | FAIL (guard SV: t -0.33, 3/7) |
| T2a 1Y/3Y + prior SVAR (PS1) | GAR next season, LOSO RMSE at f .25 .5 .75 1 | 1.516 -> 1.502, 1.423 -> 1.414, 1.368 -> 1.363, 1.310 -> 1.305 | t -3.79, -3.27, -2.38, -2.56; Holm p .0087 <= .01 | 9/9, 8/9, 9/9, 8/9 | PASS. 3Y 3.994 -> 3.969, 3.752 -> 3.737, 3.635 -> 3.626, 3.500 -> 3.491 (7/7 each) |
| T2b prior GAR swapped for prior SVAR | same | 1.516 -> 1.502, 1.423 -> 1.414, 1.368 -> 1.363, 1.310 -> 1.305 | t -3.20, -2.89, -2.15, -2.69; Holm p .0158 > .0125 | 9/9, 8/9, 9/9, 8/9 | FAIL (Holm); T2a is its superset |
| T3 injury term on new p/90 | 1X2 log loss, tune 2013-22 | .966038 -> +.000044 / +.000005 / +.000014 (av .25 .35 .5) | t +0.59, +0.09, +0.24 | 3/10, 2/10, 2/10 | FAIL at tune, held never run |
| T4 breakout + [p/90 - s0] | first-time-at-the-bar log loss, LOSO | vs kept .16256 -> .16220 (vs base .17786 -> .17106, t 8.76) | t 1.60 | 7/11 | FAIL (needs t >= 2 over the kept blocks) |
| T6 Ballon d'Or voter model GAR -> SVAR | held-out log P(winner) | -2.016 -> -2.055 | t -0.85 | 4/9 | FAIL, 2015 and 2016 vote pages not fetched (Wikipedia 429) |
| T6 UNFP voter model | same | -0.868 -> -0.797 | t +0.55 | 7/11 | passes the not-worse rule; not shipped (see leads) |
| T6 Serie A MVP voter model | same | | | | blocked (Wikipedia 429) |

Housekeeping refits (not tests): 1Y on the Nov 27 line, agepos form, RMSE at f 1 1.3266 -> 1.3104, intercept 1.14 -> 1.02
(3Y 2.30 -> 2.01); with PS1 the prior-GAR weight falls to about 0 (.22 -> -.003 at f 1) and PS1 takes .29. Breakout refit:
kept blocks gain vacated minutes and minutes room, held log loss .17786 -> .16247 (t 10.0, 11/11); board mean odds
.139 -> .122, r .94 with the old ones.

## Shipped
- scripts/soccer_players.py proj_x / proj_attach + scripts/soccer_proj_research.py (form agepossv), data/soccer_proj_fit.json,
  data/soccer_proj_pctl.json (pctl.py rerun, coverage gates hold), pj / p3 on every season file (`soccer_players.py --proj`).
- data/soccer_breakout_fit.json + data/soccer_breakout_sweep.json refit, static/data/next-up/soccer*.json rebuilt.
- team dropdown key players on SVAR (static/data/teams/soccer.json); 1Y / 3Y tooltips.

## Leads
- xMV on the Nov 27 line and with SV inputs: `python3 scripts/soccer_mv.py --snaps && python3 scripts/soccer_mv.py --fit`
  with the Transfermarkt dump in scripts/.cache/soccer_prospects/dump; test g0/g1/g2 from SVAR in the same fit (LOSO log MSE).
- T6 rerun when Wikipedia answers: `python3 scripts/research/ctx_nov27/soccer/aw.py`; a pass ships through
  scripts/research/awards_nov23/soccer/run.py races with the svar column for that race.
- Season-so-far input of 1Y / 3Y from SV: snapshots need a partial-season SV (soccer_proj_research.snapshot + soccer_sv).
- `python3 scripts/soccer_ceiling_research.py` (ceiling fit, same age as the old breakout fit) and
  `python3 scripts/backup_age_fit.py` (soccer part; shrink line).
