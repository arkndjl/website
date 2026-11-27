# NHL + hockey prospects: metric context audit (Nov 27 2026)

`prereg.md` (written first), `test.py` -> `results.json`. Data: static/data/nhl-war/2009..2026.json; 2026-27 never read.
Settled picks (Nov 24): describe = WAR; predict = pWAR for teams, Marcel WAR for players.

## Inventory (P = predictive, D = descriptive)
| consumer | file:line | ctx | input it reads | verdict |
|---|---|---|---|---|
| game model lineup value (rv) | scripts/nhl_games.py:440-520 | P | HPM (pWAR rate) of season S-1 from scripts/data/nhl_hpm_nested.json.gz (weights known then), age line fit on seasons before, x last season's TOI | OK (fit = serve: nested 2026 == season file 2026, max diff 5e-6) |
| game model goalie term (gk, totals only) | scripts/nhl_games.py:596-640, 1453, 1567 | P | walked GSAx a game, shrunk (gk_k 50), carry .4 | OK |
| Elo / xG / b2b / home, season odds, bracket, ARK Ranking | scripts/nhl_games.py | P | walked team ratings + rv | OK |
| injury list WAR, warOut on ARK Ranking | scripts/nhl_games.py:1300-1330, 1494 | P (display) | WAR per 82 over 3 seasons at 1/.5/.25 (unshrunk Marcel WAR) | OK |
| WAR leaders (default view, ± key) | layouts/shortcodes/nhlwar.html:96; scripts/board_moves.py:55 | D | war (pWAR, 3Y, HPM are named views) | OK |
| goalies tab | layouts/shortcodes/nhlgoalies.html | P | game model goalie rating, labelled as such | OK |
| rookies / standouts | scripts/rookies.py:301-340 | D | war first (pWAR, HPM views) | OK |
| next up (BO%) | scripts/nhl_breakout.py:228-430 | P | season WAR rate shrunk, best prior, Marcel WAR gap, usage; "site HPM" group not kept | OK |
| projections tab | scripts/player_pctl.py:236, 1040-1085 | P | Marcel WAR (1/.7/.5, K 1600) + this season to date | OK |
| 3Y (p3), IN 3Y | scripts/nhl_players.py:645-700 | P | pWAR + Marcel WAR + age + TOI | OK |
| awards voter models | scripts/awards_nhl.py:17-20, 55-75 | D | season WAR, GSAx, points, team points % | OK |
| awards conviction | scripts/awards.py lead(), nhl_draw SEASON_ONLY | D | this season's own WAR rate | OK |
| **awards predictive: games-left WAR** | scripts/awards.py nhl_draw (was :618) | P | **pwar / toi added to descriptive war** | **MISMATCH-P -> fixed (test A)** |
| awards predictive: points, goals, GSAx | scripts/awards.py nhl_draw | P | season rate blended with last season by games | OK |
| backup watch + depth chart grade | scripts/backup_watch.py:377-400 | P | HPM over 3 season files at 1/.5/.25, shrunk to replacement | candidate (player-level on pWAR): tested, HPM kept (test B) |
| depth chart stat columns | scripts/depth_stats.py:61 | D | WAR, GAR/60 this season | OK |
| contract value (xAAV, SV) | scripts/xaav.py:121-128 | P (market) | war1, war2, pwar, p3, TOI of the season before signing; gated held out | OK; lead: pwar/p3 in past files sit on the latest fit's weights |
| all-time players | scripts/alltime.py:862 | D | war per 82 | OK |
| team detail top players, news movers, games to watch, ARKLIST, transactions | scripts/team_detail.py:92, news.py:132, watch_games.py:199, arklist_perf.py:111, transaction_values.py:103 | D | war | OK (transactions: lead for the cross lens, a move's value is this season's WAR to date) |
| props | scripts/nhl_props.py | P | walked per-game rates, coefficients from seasons before | OK |
| badges | scripts/nhl_badges.py | P (display) | regressed MoneyPuck traits that beat WAR/pWAR/HPM held out | OK |
| hockey FV outcome | scripts/hockey_prospects.py:403-422 | P target | best three pwar seasons (Noah, Nov 11) | OK |
| hockey FV stage input "war" | scripts/hockey_prospects.py:581, 591 | P | pwar summed through season y+k (point in time) | OK; **DISPLAY: labelled WAR in 4 tooltips -> fixed** |
| hockey FV draft inputs | scripts/hockey_prospects.py | P | slot, draft-year NHLe, CHL priority pick | OK |
| NHL mock | scripts/hockey_mock.py | P | order from game model xpts, Tankathon rank, FV | OK |

## Tests (Holm family of 2)
| swap | target | before -> after | t / p Holm | k/n | result |
|---|---|---|---|---|---|
| A. awards games-left rate: pwar/toi -> Marcel WAR a minute | next-season WAR at known ice time, 9,622 player pairs 2011-25 | MSE 1.811 -> 1.471; award pool 4.738 -> 3.199, rho .485 -> .553; goalie bias -1.22 -> +.17 WAR | 10.74 / <.0001 | 15/15 | **PASS, shipped** |
| B. backup watch grade: HPM -> Marcel GAR a 60 | backup passes the starter in ice time a game next season, 4,198 pairs | log loss .4371 -> .4656 | -4.77 / 1.0 | 1/11 | **FAIL, HPM kept** |
| B guard | pair's GAR a 60 gap next season | MSE .3024 -> .2865 | 3.85 | 10/11 | (Marcel wins its own scale, as Nov 24 found) |

A's proxy is season to season: no file in the repo holds mid-season WAR, so the in-season form (this season to date as
the newest Marcel season) is the same formula one season earlier. B: HPM carries the usage a coach rewards (A1, PK,
the ice-time shrink target), so it says who plays; Marcel WAR says who produced.

## Shipped
- scripts/awards.py: nhl_draw runs the games left at Marcel WAR a minute (NHL_MW 1/.7/.5, NHL_MW_K 1600, group mean
  from the seasons before). data/awards.json rerun for nhl (`python3 scripts/awards.py nhl`). Hart: Draisaitl 2% -> 24%.
- hockeyboard.html, prospectjs.html, fvglance.html, hockey_prospects.py: "WAR so far" / "peak WAR" -> pWAR.
  The scorecard note in data/hockey_fit.json changes on the next `hockey_prospects.py --fit`.

## Leads
- Rookies in A shrink to the whole group's mean; the projections tab has a newcomer mean (pctl_fit_nhl mu F:n, D:n, G:n).
- xAAV history reads pwar / p3 on the latest fit's weights; a nested store exists for HPM only.
- transaction_values NHL: this season's WAR to date; a move's value going forward would be Marcel WAR.
