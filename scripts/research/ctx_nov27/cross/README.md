# Metric context audit Nov 27 2026: cross-sport lens

Branch `ctx27/cross`. Pre-registration: prereg.md (committed before scoring). Test: t1_conf_then.py -> results_t1.json.

## Inventory

| consumer | file:line | ctx | input it reads | verdict |
|---|---|---|---|---|
| Pick rules: X per market | scripts/games_picks.py fit_rules (~680) | P | walk-forward model margin / recentred total (scripts/data/games_wf) vs the OPEN, judged by clvRet at the close | OK (close is the target, never a feature) |
| Totals recentre | games_picks.py recenter_wf (225) / recenter_live (245) | P | slate opens + the season's past 100 closes | OK (past closes only; fixed Nov 4) |
| Pick segments tier / game / conf | games_picks.py seg_of, conf_map | P | TODAY's conference map on every past game | LEAK (fit form != serve form). Tested T1: CBB fixed, CFB left |
| Pick segments line / role / total band | games_picks.py seg_of | P | the line taken (the open in the fit) | OK |
| Live veto / DU live pairs | games_picks.py live_rec, LIVE_TEST; units.live_pairs | P | 2026-27 live picks judged by the close | OK by Noah's Nov 11 rule (close value, not results); not read in any test here |
| NBA walk-forward rows | scripts/games_wf/nba_wf.py | P | model saw tip-time injury news the open did not | known LEAK, flagged in the file and on the page (upper bound); NBA lens |
| Dengler Units | scripts/units.py fit (367, 399) | P | same wf rows + seg_of labels | follows the segment fix on the next --rules |
| Close predictor | scripts/close_model.py load (156), features (206) | P | open, model - open, cells from the open; RAW model total (picks use the recentred one); today's conference map for tier | display / research only since Oct 28 (paper book reads the picks log). Lead: same two form gaps as the rules |
| Paper book, rule monitor, model monitor, CLV | paper_book.py, rule_monitor.py, model_monitor.py, clv.py | D (record) | the picks log, graded at the close | OK |
| Standings | scripts/fetch_standings.py, layouts/shortcodes/standings.html | D | ESPN tables and leaders only | OK. The page's bracket subtabs are titled "projected bracket" (predictive, labelled so) |
| Rookies NFL | scripts/rookies.py:192 | D | key xv | OK |
| Rookies NBA | rookies.py:278 | D | key vorx (VORX on team-adjusted rXPM) | OK |
| Rookies NHL | rookies.py:334 | D | key war | OK |
| Rookies soccer | rookies.py:406 | D | key svar | OK |
| True freshmen CFB / CBB | rookies.py:481, 533 | P (FV board) | key fv; CBB companions xXPM, NBA% (all predictive); CFB companions WAR, XV, SV | OK as a grade board; the CFB one mixes season columns behind an FV lead (for Noah) |
| First-year hockey / first senior season soccer | rookies.py:585, 607 | P | nhle / fv | OK (sport lenses) |
| Next up, every sport | scripts/next_up.py:226 | P | key EDGE or BO% (breakout odds) | OK |
| Next up NFL companion rate | next_up.py board('nfl') | P | WAR/17 = this season's WAR pace (descriptive) | DISPLAY, fixed: pXP/60 |
| Next up NBA companion rate | next_up.py board('nba') | P | XPM raw this season beside pXPM (x) | DISPLAY minor: pXPM is already on the row; XPM kept as Noah's Nov 23 rate stat (for Noah) |
| Next up soccer companion | next_up.py | P | pg90 (p/90) | OK (Nov 24) |
| Next up CFB companion | next_up.py | P | FV + Stat+ (PFN z, this season) | DISPLAY minor: predict pick is cWAR; Stat+ was Noah's Nov 23 ask (for Noah) |
| Projections tab NBA | scripts/player_pctl.py SPEC nba | P | VORX from the XPM (proj) prior (nba_proj.py) | OK |
| Projections tab NHL | player_pctl.py Rate.prior | P | Marcel 1 / .7 / .5 WAR rate | OK (settled player pick) |
| Projections tab NFL | player_pctl.py Rate.prior | P | Marcel WAR a snap, shrunk to group | MISMATCH-P candidate (settled pick is pXP/60 within position). Not testable offline: no per-season point-in-time pXP in the repo. Lead |
| Awards conviction | scripts/awards.py lead(), SEASON_ONLY (447, 618, 804, 1184-1379) | D | this season's own rate: NBA VORX / D-XPM, NHL WAR / GSAx, CBB XPM, football + soccer SVAR | OK |
| Awards predictive | awards.py voter models | P | sport fits (BPM in CBB by the Nov 26 failed swap) | OK, settled |
| All-time lists | scripts/alltime.py | D | season value era-scaled; tennis = year-end Elo over the 20th best (line 268) | tennis MISMATCH-D lead (from the tennis lens: Elo carries over; SV is the season-only form; needs the alltime_pull cache) |
| News weights | scripts/news.py | D events | transactions, injuries, results (model win% only for upset size), FV moves | OK: no metric mixes contexts; FV moves cite FV |
| Search index | scripts/search_index.py | - | names, pages, tabs | OK (no metric) |
| Leaders NBA / NFL / NHL / soccer | layouts/shortcodes/nbaxpm.html:54, nflwar.html:62, nhlwar.html:53, soccerplayers.html:58 | D | vorx / xv / war / svar in the KEY slot | OK |
| Soccer leaders tab name | content/arkboard-soccer.md wintabs "GAR leaders" | D | the board leads SVAR | DISPLAY (label): for the lead, needs an ALIAS |
| CBB leaders / pXPM / stats | static/data/cbb/war.json, pxpm.json, stats.json | D / P / D | key war (VORX) / pxpm / xpm | OK |
| CBB standouts | static/data/cbb/breakouts.json | D | key xup (xXPM up) | for the CBB lens: a descriptive tab keyed on a projection change |
| Process glossary "Most predictive and most descriptive metric" | data/library.json sections[2].entries[20] | - | CBB line still says "WAR on GBPM / roster prior BPM" | DISPLAY (stale text): replacement lines below |

## Site matrix (sport x tab -> context -> lead -> settled pick)

| sport | tab / card | ctx | lead | match |
|---|---|---|---|---|
| NBA | VORX/XPM leaders | D | VORX (rXPM) | yes |
| NBA | rookies | D | VORX | yes |
| NBA | projections | P | VORX p50 from XPM (proj) | yes |
| NBA | next up | P | EDGE / BO%, pXPM + raw XPM | yes (raw XPM beside it) |
| NBA | conviction awards | D | VORX / D-XPM this season | yes |
| NFL | WAR leaders | D | XV | yes |
| NFL | rookies | D | XV | yes |
| NFL | projections | P | WAR p50, Marcel WAR rate | open (pXP/60 untested) |
| NFL | next up | P | EDGE, pXP/60 (was WAR/17) | yes after this branch |
| NFL | conviction awards | D | SVAR | yes |
| NHL | WAR leaders, rookies | D | WAR | yes |
| NHL | projections | P | Marcel WAR | yes |
| NHL | next up | P | BO%, WAR/1k shrunk | yes |
| CFB | boards, true freshmen, mocks | P | FV | yes |
| CFB | WAR leaders | D/P | cWAR preset | NFL/CFB lens |
| CFB | QB SV, skill players, conviction | D | SV / SVAR | yes |
| CFB | next up | P | BO%, FV + Stat+ | lead yes; Stat+ companion is this season's |
| CBB | board, true freshmen, draft, mocks | P | FV | yes |
| CBB | VORX/XPM leaders | D | VORX | yes |
| CBB | pXPM, portal | P | pXPM | yes |
| CBB | standouts | D | xXPM up | CBB lens |
| CBB | next up | P | EDGE, shrunk BPM column | CBB lens |
| Soccer | "GAR leaders" | D | SVAR | metric yes, tab name no |
| Soccer | rookies, conviction | D | SVAR | yes |
| Soccer | next up | P | EDGE, p/90 | yes |
| Tennis | ARK Ranking | P | ARK | yes |
| Tennis | peaks / careers | D | year-end Elo margin | no (lead) |
| CS2 | RWA leaders / all-time | D | season RWA | yes (tennis/CS2 lens) |
| Predictions | picks, paper book | P | model margin / recentred total vs line | yes |
| Standings | tables, leaders | D | results | yes |

## Tests

| swap | target | before -> after | t | k/n | result |
|---|---|---|---|---|---|
| CBB segment labels: today's map -> the season's own | clvRet of tier/game/conf rule picks, 2026 (tune 2025) | 78.37 -> 82.97 units of close value (1,115 -> 1,272 picks; per pick +7.03% -> +6.52%, both t > 10) | paired +4.60 on 277 changed picks, slate t 3.30 (Holm p .001) | spread +0.37 (t .31), total +4.23 (t 5.45): 2/2 | PASS, shipped |
| CFB segment labels: same | same, 2021-26 (tune 2017-20) | 7.41 -> 6.29 (342 -> 417 picks; +2.17% -> +1.51%) | paired -1.12 on 173, t -0.65 | spread +1.34 (t 2.38), total -2.46 (t -1.54): 1/2 | FAIL (noise, not better): CFB stays on today's map |

The prereg's pass line read "for each sport tested"; I shipped per sport (CBB on, CFB unchanged, CONF_THEN = {'cbb'}).
That per-sport reading is mine: say so if the conjunction was meant and the CBB switch should come out.

## Shipped

- scripts/games_picks.py: conf_hist / conf_then, CBB fit rows labelled by their own season (seg_of). Live rows unchanged.
  Rerun (lead, after the sport lenses' game model refits): `python3 scripts/games_picks.py --fit` then `--rules`
  (rewrites data/games_picks_rules.json and the DU fit; reads the live record as designed).
- scripts/next_up.py + layouts/shortcodes/rookies.html: NFL next up shows pXP/60, not WAR/17. Regenerated
  static/data/next-up/nfl-tab.json (the breakout workflow reruns next_up.py).

## Cross-sport analogues

- Point-in-time segment labels: CFB (tested, not better), NBA / NFL have no conference family. Same idea for
  close_model.py tier cells and any game-model feature keyed on today's conference (cbb_games.power already dates the
  Pac-12).
- Predictive-tab companion rate = the predict pick: soccer p/90 (done Nov 24), NFL pXP/60 (done here), NBA pXPM
  (already on the row), NHL pWAR or Marcel WAR in place of this season's WAR/1k, CFB cWAR in place of Stat+, CBB pXPM in
  place of shrunk BPM (the breakout scripts own those columns).

## Leads

- NFL projections rate prior on pXP/60: needs per-season point-in-time pXP (nfl_war.py rebuilt per season from
  nflverse), then `python3 scripts/player_pctl.py --frames nfl && python3 scripts/player_pctl.py --fit nfl`.
- CFB independents (and two unmapped CBB teams, before this branch) read as a conference game in seg_of's today's-map
  path; CFB keeps that until a retest.
- close_model.py fits totals on the raw model total and today's conference tiers; the picks use recentred totals.
  Table only, but its "plain gap rule" comparison is on a different form than the live rule.
- Tennis all-time on season SV (tennis lens message): needs the alltime_pull tennis cache.

# Round 2 (port round)

## Tests

| swap | target | before -> after | t | k/n | result |
|---|---|---|---|---|---|
| T2 close predictor CBB tier cells: today's map -> the season's own | held-out squared error of close - open (2021, 2024-26), held rows on as-it-stood tiers | spread 35,064.2 -> 35,056.9; total 78,737.7 -> 78,715.3. Guard (clvRet of E > 0 bets) +2.32% -> +2.31%, +3.53% -> +3.50% (se .17 / .14) | spread -1.17, total -3.05 | 2/2 | PASS, shipped |
| T2 CFB tier cells: same | same, 2021-26 | spread 23,504.4 -> 23,506.0; total 24,695.8 -> 24,690.9 | +0.08, -1.71 | 1/2 | FAIL (spread not better): CFB stays |
| T3 tennis all-time on season SV (rule fix; gate = era_check under the era-blind 95% line) | KL of top-100 decade share | ATP peak .049 -> .026 (line .063), career .014 -> .023; WTA peak .061 -> .043, career .012 -> .024 | - | 4/4 lists pass | PASS, switched |

## Shipped

- scripts/close_model.py: TIER_THEN = {'cbb'} (tier from games_picks.conf_hist); data/close_fit.json refit
  (`python3 scripts/close_model.py --fit`). Table only (closefit shortcode).
- scripts/alltime.py tennis_players: season value = SV (the year's wins over what a replacement player, the year's
  101st-150th by year-end Elo, would win against the same opponents), z against the year's #20 SV in SDs of the top
  100. Columns SV+ and SV (was Elo+ and peak Elo). New `--snap --tennis` flag; snapshot and data/alltime.json atp / wta
  blocks regenerated (other sports' blocks left as committed). scripts/alltime_ref.py text edited, NOT run.
  For Noah: SV is a volume stat. WTA careers: Serena Williams 3rd -> 9th (short schedules), Virginia Wade 4th; ATP:
  Federer passes Djokovic, Lendl 3rd; peak seasons now McEnroe 1984, Federer 2006, Vilas 1977; Evert 1975, Graf 1989.
- scripts/transaction_values.py + layouts/shortcodes/transactions.html: NHL rows show pWAR beside WAR this season (the
  second slot was empty; a move is read forward). data/transactions/values.json regenerated.

## Inventory, the parts not reached in round 1

| consumer | file:line | ctx | input | verdict |
|---|---|---|---|---|
| Weekly board moves | scripts/board_moves.py:51-64 BOARDS | follows the board | cbb fv, nfl xv, nba vorx, nhl war, soccer svar, nbaproj pxpm, cs2 rwa, prospects fv | OK: each tracks its board's lead |
| Board moves, other views | board_moves.py EXTRA | - | nfl pxp, nba txpm / sxpm, nhl pwar / p3 / hpm | OK |
| Player badges (all sports) | scripts/<sport>_badges.py, layouts/partials/badges.html | P (by design) | one stat regressed by volume, shown only if it predicts next season beyond the board value | OK, display only (read at docstring + memory level, backtests not rerun) |
| Unit badges | scripts/unit_badges.py | P | midseason unit value held toward half of last season, tested on rest of season | OK (a predictive badge; the prior is by design) |
| Player moves | scripts/player_moves.py:246 | events | recruit ARK + xFV on recruit rows | OK |
| Mock shared code | scripts/mock_noise_backtest.py, mock_roster_backtest.py, mock_fall_curve_backtest.py | P | board rank -> pick curve, need terms | OK |
| Transactions NHL | scripts/transaction_values.py:103 | P (a move) | WAR to date only | DISPLAY, fixed (pWAR added) |
| Transactions NFL / NBA / soccer | transaction_values.py:84-120 | P (a move) | WAR + SVAR; XPM + VORX; GAR + SVAR, all this season | DISPLAY lead: pXP/60, pXPM, p/90 as the second number (not changed: both slots are taken, Noah's call) |
| GFX CFB player card VALUE band | assets/js/gfx.js:1102-1103 | D (this season) | order Stat+, WAR, WAA, XV | DISPLAY: put the XV cell first (XV, WAR, WAA, Stat+) |
| GFX player card, NBA | assets/js/gfx.js:1808-1815 | both | VORX tile unshifted first on every NBA card, predictive tables too | DISPLAY: on a predictive table (projections, next up, contract value) unshift pXPM (xp.sxpm); VORX stays on season tables |
| GFX CBB team plan | assets/js/gfx.js:743-751 (and layouts/shortcodes/cbbbuilder.html:48-51) | P (next season) | rotation sorted by `bpm`, header 'BPM' | DISPLAY: header to 'xXPM' if the CBB lens's builder now writes the XPM form under `bpm`; else leave |
| GFX recruit card | assets/js/gfx.js:1645 buildRCard | P | FV, Y1 FV, predictions | OK by CLAUDE.md, not re-read |

Not read line by line: buildDepth, buildTeamCard, buildRank, buildPerf, buildWatch (gfx.js 2159-4171).

## Analogues

- As-it-stood conference labels: passed for CBB twice (segments, close tiers), failed for CFB twice. Nothing left to port.
- Season-only all-time value: tennis done; the other all-time lists already read season value.
