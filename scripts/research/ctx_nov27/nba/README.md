# NBA context audit, Nov 27 2026

Rule: predictive consumers read pXPM (or a tested better form) point in time, descriptive ones season-only rXPM / VORX,
fit form = serve form. `prereg.md` was committed before scoring (addendum for T3b written after T3 / T4, before T3b ran).
No 2026-27 outcome is read (files and games <= 2025-26). Keys: `xpm` box blend, `txpm` rXPM, `sxpm` pXPM, `sx0` Nov 4 shrink,
`vorx` on rXPM, `vorx0` on the box blend.

## Inventory

| consumer | file:line | ctx | input | verdict |
|---|---|---|---|---|
| XPM board (rXPM, VORX, O/D) | scripts/nba_xpm.py:163-193, layouts/shortcodes/nbaxpm.html | D | txpm, vorx (season only) | OK |
| XPM board pXPM column / chip | scripts/nba_xpm.py:290 | P | sxpm, history and aging curve of seasons <= n | OK |
| board rows before a first BPM (`pr`) | scripts/nba_xpm.py:343 | D | prior_xpm shown in the XPM column, 0 minutes | DISPLAY (opening days only, marked `pr`; left) |
| leaders, depth-chart stat tiles | scripts/depth_stats.py:56 | D | txpm, vorx | OK |
| depth chart / backup watch grade | scripts/backup_watch.py:345 | P | 3 seasons of xpm 1/.5/.25, k 500, labelled pXPM | MISMATCH-P + DISPLAY -> fixed (T2) |
| backup watch xGap | scripts/backup_age_fit.py:178 | P | fit on the old grade | LEAK (serve/fit) once the grade moved -> refit |
| lineups / on-off | scripts/nba_lineups.py | D | season play by play | OK |
| game model player value | scripts/nba_games.py:389, 1091 | P | values(): 2 seasons, n0 300 to -2, + ARC .25, box XPM in season | OK (pXPM tested, T1 FAIL) |
| ARK Ranking, season odds, bracket, lottery, tank watch | scripts/nba_games_build.py, nba_preseason.py, nba_lottery.py | P | the game model | OK |
| injury / availability terms | scripts/nba_games.py:1206 | P | same player value x P(play) | OK |
| props | scripts/nba_players.py | P | box rates, game model script; no XPM | OK |
| XPM (proj), interval, surplus, contract years | scripts/nba_proj.py:166-196 | P | prior_xpm (2 seasons, n0 600) blended with XPM to date | MISMATCH-P candidate: T3 passes alone, harms 1Y / 3Y (T4), T3b fails its rule at f .75; not shipped, lead |
| 1Y / 3Y | scripts/nba_proj.py:203, data/nba_proj3y_fit.json | P | H4 form on XPM (proj) | OK (ties pXPM at season end, T4) |
| percentile projections | scripts/player_pctl.py:785, 1017 | P | prior_xpm, nba_proj fit (same form as fit) | OK |
| xAAV / contracts | scripts/xaav.py:413 | P | role shrink (Oct 31), box xpm, vorx0 = fit form | OK (pXPM tested worse Nov 24) |
| next up odds | scripts/nba_breakout.py:360 | P | shrunk BPM + kept blocks | OK (pXPM gap t 1.42 Nov 26) |
| next up ceiling | scripts/nba_breakout.py:258 | P | sx0 = fit form | OK |
| next up pXPM column | scripts/nba_breakout.py:386, 405 | P | sx0 shown under the label pXPM | DISPLAY -> fixed |
| next up young rows | scripts/next_up.py:78, 160 | D col | txpm labelled XPM this season | OK |
| standouts / rookies | scripts/rookies.py:262 | D | vorx, txpm; sx = sxpm; aXPM / 3Y on role shrink (fit form) | OK; pXPM tooltip text stale -> fixed |
| G League call-up, xXPM, 1Y / 3Y term | scripts/gleague_callup.py:216-253, gleague.py | P | NBA history through last season, box xpm / vorx0 targets (fit form) | OK (tested Nov 24) |
| awards voter models | scripts/awards_nba.py:105-166 | D | MVP / DPOY rvorx, rxpm, rdxpm; others vorx0 / box (fit form) | OK (PR #1201) |
| award race draws | scripts/awards.py:447 | D lead / P odds | lead: season xpm; odds: sx0 (awards_asof fits on shrink(), same form) | OK |
| team pages, transactions, ARKLIST, news, board moves, games to watch | team_detail.py:89, transaction_values.py:100, news.py:131, board_moves.py:54, watch_games.py:194 | D | txpm, vorx | OK |
| all-time NBA | scripts/alltime.py --snap | D | season rXPM / VORX overlay | OK |
| badges | scripts/nba_badges.py, nba_badge_backtest.py | P | rates regressed by volume; backtest on sx0 (fit form) | OK |
| mock draft team side, trades | scripts/cbb_mock.py, nba_draft_trades.py | P | pick values, no XPM read | OK |

## Tests (Holm over the five primaries: only T2 and T3 clear it; T3 is blocked by its downstream consumers)

| swap | target | before -> after | t | k/n | result |
|---|---|---|---|---|---|
| T1 A game model value -> pXPM | game margin MAE, walk-forward | 2015-21 9.8957 -> 9.8984; 2022-26 10.7063 -> 10.7041 | +1.66 / -0.71 | 2/7, 4/5 | FAIL |
| T1 B same, no aging | same | 9.8957 -> 9.8958; 10.7063 -> 10.7032 | +0.04 / -1.44 | 1/7, 4/5 | FAIL (needs t <= -1.5 on 2015-21) |
| T2 depth / backup grade -> pXPM | next-season XPM, 250+ MP, weighted | RMSE 1.3013 -> 1.1850 | 12.96 | 15/15 | PASS, shipped |
| T2 guard: backups (< 1,000 MP) | same | 1.4037 -> 1.3361 | 3.86 | 14/15 | holds |
| T2 guard: xGap walk-forward | two-season future gap | MSE 1.508 (gap + age, old grade) -> 1.470 (gap alone, pXPM) | | | holds; age gap term now t +1.8 (worse), dropped |
| T3 XPM (proj) prior -> last season's pXPM | season XPM from the prior alone, 50+ MP | RMSE 1.4006 -> 1.2656 | 14.11 | 14/14 | passes its rule; cover .805 / .796 |
| T4 (T3 downstream) 1Y / 3Y on the pXPM prior | next season / next three, 1,000+ min, LOSO | f 1: 1Y 1.1375 -> 1.1499, 3Y 1.1253 -> 1.1390; worse at every f >= .2 | -4.09 / -4.88 | 2/14, 1/12 | FAIL: T3 not shipped as registered |
| T4 pXPM as the 1Y | next-season XPM, 1,000+ min | 1.1375 (1Y) vs 1.1395 (pXPM) | -0.39 | 6/14 | tie: 1Y stays |
| T3b XPM (proj) on the pXPM prior, in season | simulated rest-of-season XPM | f .1 1.2566 -> 1.1905 (t 11.0, 14/14); .2 1.2054 -> 1.1668 (8.2, 14/14); .35 1.1849 -> 1.1679 (4.8, 13/14); .5 1.2189 -> 1.2118 (2.5, 8/14); .75 1.4282 -> 1.4271 (0.5, 7/14) | | | FAIL on the registered rule (every f); never worse |

## Shipped
- `scripts/backup_watch.py nba()`: grade = the board's pXPM (this season's row, else last season's; older seasons only
  for a player out two years). `scripts/backup_age_fit.py`: NBA pairs graded by pXPM; a sport whose age term is worse
  held out ships gap alone. `data/backup_age.json` NBA block only (the other sports' blocks were left as fit Nov 11).
- `scripts/nba_breakout.py`: the pXPM column reads `sxpm`; ceiling stays on `sx0`.
- `scripts/rookies.py`: pXPM tooltip text.

## Leads
- XPM (proj) on the pXPM prior for the Proj column, interval and surplus only (1Y / 3Y kept on the live-prior form):
  better through mid-season, a tie late. Needs Noah's call or a rule that weights the early season; rerun
  `python3 scripts/research/ctx_nov27/nba/t3b_proj.py`.
- Game model on pXPM without aging: 2022-26 t -1.44 (4/5), 2015-21 flat. Not a pass; retest after 2026-27.
- `data/backup_age.json` NHL / soccer / NFL blocks move on a full rerun (data grew since Nov 11): `python3 scripts/backup_age_fit.py`.

## Cross-sport analogues
- Depth / backup grade on the sport's own predictive metric instead of hand-weighted seasons: NHL (HPM 1/.5/.25 -> pWAR /
  Marcel WAR rate), soccer (GAR/90 1/.5 -> p/90), NFL (WAR/snap this season -> pXP/60), CFB (WAA -> cWAR). CBB done Nov 26.
  Then refit xGap on the new grade; expect the age-gap term to fall away wherever the grade is already aged.
- A column labelled with the predictive metric's name that reads an older form (NBA next up): check NHL pWAR, NFL pXP/60 and
  CBB pXPM labels on next up, depth and rookies tabs.
- A better preseason prior that hurts a regression fit on the old blend (T3 / T4): any sport that swaps a prior under a
  fitted multi-year projection (NHL / soccer / NFL projections) must refit and rescore the downstream form, not the prior alone.
- Game model player value on the board's predictive metric (T1 fail): NHL game lineup value on pWAR, NFL on pXP/60.

## Round 2 (port round)

| item | swap / check | target | before -> after | t | k/n | result |
|---|---|---|---|---|---|---|
| P2 award games-left rate | Nov 4 shrink (sx0) -> pXPM form on the to-date line | rest-of-season stand-in XPM, 2019-26, 200+ min left | RMSE 1.4574 -> 1.3967 (defense .6300 -> .6183) | 7.64 (3.03) | 8/8 (6/8) | PASS |
| P2 guard | as-of races, winner log loss (72 races, 1,500 sims) | MVP / DPOY / ROY | 1.8613 -> 1.8242; by award 1.507 -> 1.485, 2.865 -> 2.787, 1.212 -> 1.200 | 1.55 | 6/8 | holds, shipped |
| P2 B (no aging) | same | same | 1.4574 -> 1.3937 | 8.03 | 8/8 | passes too; A shipped (the board's own column) |
| P3 A | 1Y / 3Y history terms on rXPM in place of box XPM | next season / next three, LOSO | f 1: 1Y 1.1375 -> 1.1383, 3Y 1.1253 -> 1.1254 | -2.35 / -0.40 | 4/14, 6/12 | FAIL |
| P3 B | 1Y / 3Y + prior two seasons' VORX | same | 1Y 1.1375 -> 1.1378, 3Y 1.1253 -> 1.1284 | -0.46 / -3.29 | 6/14, 4/12 | FAIL |
| P4 game model | fit form vs serve form | code | serve = the same Model class walked to today (nba_games_build.py:213, F['params']); values() reads the two seasons before, ARC the same; no in-season board value (ik 0) | | | OK, no change |
| P5a next up ceiling | sx0 -> pXPM as the input | pinball .80, LOSO | .30605 -> .30298, cover .799 -> .800 | 1.34 | 12/16 | FAIL; research script pinned to sx0 |

P5 fit forms against the Nov 24 rebuild (git history is a single commit here, so checked by refit, not by date):
- ceiling: refit on sx0 reproduces the shipped coefficients exactly (max diff 0). The research script read `sxpm`
  (pXPM since Nov 24): a refit would have trained on a form the build does not serve. Pinned to sx0.
- rookie aXPM age slope: same pattern (`sxpm` in nba_rookie_age_research.py; the build feeds role_sxpm). Pinned; refit
  reproduces the shipped file byte for byte.
- G League call-up / xXPM (box xpm, vorx0), xAAV (role_sxpm, vorx0), badges (sx0), awards voter fits (vorx0 / rvorx by
  award), XPM (proj) fit and 1Y / 3Y (box xpm): read keys the rebuild left unchanged. Not stale.
- as-of award backtest (scripts/awards_asof.py) crashed on every sport's voter races since the conviction lead was
  added (spec had no 'null'): fixed. NBA arm now runs the games-left rate through nba_xpm.pxpm, as the live draw.
  NBA temperature in data/awards_temp.json is 0, so nothing depends on a refit.

Leads from round 2:
- scripts/player_pctl.py:804 scores the NBA percentile fit against `vorx` (rXPM since Nov 24) while its draws are
  .030 x (box XPM + 1.4) x MP / 48: target `vorx0` or move the draws. Needs the pctl box cache to refit.
- scripts/nba_proj.py:195 adds VORX to date (rXPM) to the rest of season on the box-blend projection; $ per win
  renormalises it, so the surplus effect is small. Same for nba_proj3y_research.py:91 (research only).
- The full NBA as-of run (2012-13 on) needs the ESPN box backfill: `python3 scripts/awards_asof.py nba --box --noscore`.
