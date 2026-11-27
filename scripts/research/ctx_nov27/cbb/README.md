# CBB metric context audit (Nov 27 2026)

Lens: every College Basketball consumer the Nov 26 BPM -> XPM swap did not cover. Settled picks: describe = VORX on rXPM,
predict = pXPM board form. Pre-registration: `prereg.md` (committed before scoring). No 2026-27 outcome in any test.
Scripts: `h1_builder.py`, `h2_serve.py`, `h3_lowdiv.py` (run from the repo root; h3 needs /mnt/project-files/cbb/kit).

## Tests (Holm over 4)

| swap | target | before -> after | t | folds | result |
|---|---|---|---|---|---|
| H1 team builder next-season value: pXPM after the season for season-end xXPM + class change | next-season rXPM, weighted by next minutes, 2014->15 ... 2024->25 | RMSE 2.570 -> 2.443 (guard, 20%+ minutes both seasons: 2.390 -> 2.294) | 29.6 (guard 14.5) | 11/11 | PASS, shipped |
| H2a Transfer% serve form: pXPM after the season (the fit's form) for season-end xXPM | 2025->26 held out, log loss a row (n 5,047) | .8988 -> .8862, AUC .704 -> .725 | 6.44 | 1 held-out offseason | PASS, shipped |
| H2b landing serve form, same swap | 2025->26 held out, -log P(school) a move (n 1,362) | 5.478 -> 5.419, top 10 15.3% -> 16.5% | 7.46 | 1 held-out offseason | PASS, shipped |
| H3 low-division arrival value input: shrunk rXPM for shrunk BPM | FV above 20, kit arrivals 2009-16 (n 3,739), leave a year out | MSE 1.944 -> 1.974, deviance .489 -> .499 | -.45 (dev -1.08) | 3/8 | FAIL, stays BPM |

H1 for reference: raw season XPM + class change (no blend) 3.414. H2 is a serve/fit mismatch, not a new model: the Nov 26
swap fit both models on pXPM after the season and kept serving the board's xXPM, which with the season played is about
.85 x raw XPM to date; served that way the held-out loss gives back the whole Nov 26 gain (.8999 -> .8862 then).
H3: shrunk rXPM and shrunk BPM correlate .9984 on these rows; the recruit path targets (year 1-3 BPM, college value =
minutes share x (BPM + 3)) follow the same verdict and stay on BPM.

## Shipped

- `scripts/cbb_live.py` writes a board column `pxn`: pXPM after this season (the board form on his career with this
  season's line, `cbb_fit.features` on `next_career`), blended from the preseason number by the in-season weight; the
  weight reaches 1 at the team's last game, where it is exactly the form H1 / H2 scored. `scripts/cbb_market.py px_next`
  reads it for Transfer%, landing and the team builder (frozen pXPM, then xXPM, where a row has none).
- Display: standouts open on XPM over x (was xXPM up, a projection's own move); leaders tab drops the Next view (it sits
  on the pXPM subtab now); true freshmen get an XPM view and their line says XPM; the depth chart card says VORX and
  Stat+ "XPM against his position"; the builder's value column is labelled pXPM.

## Inventory

| consumer | file:line | context | input | verdict |
|---|---|---|---|---|
| Transfer% | scripts/cbb_market.py:247 (feats_move 'bpm') | P | was board xXPM; fit on px2 | LEAK (serve form) -> fixed, H2a |
| Landing spot | scripts/cbb_market.py:490 | P | was board xXPM; fit on px2 | LEAK (serve form) -> fixed, H2b |
| Team builder next-season value | scripts/cbb_market.py:531 nxt | P | was xXPM + class BPM change | MISMATCH-P -> fixed, H1 |
| Team builder rotation -> ARK scale | scripts/cbb_market.py:547 | P | xXPM this season vs ARK rating now | OK |
| xNIL college value | scripts/cbb_market.py:274 | P | minutes x (xXPM + 3) | OK (xXPM carries pXPM) |
| Low-division translation + arrival value | scripts/cbb_lowdiv.py:363-447 | P | first D-I season BPM shrunk 300 min | OK (H3 fail) |
| Recruit path years 1-3, college value, ARK stars | scripts/cbb_recruit_fit.py:75-85, 663-790 | P | BPM if he plays, minutes x (BPM + 3) | OK (target definition; H3) |
| Game model player values (sat out / not yet played) | scripts/cbb_games.py:392 avail, 444 pre_out, 493 last_bpm | P | game BPM to date / last season, shrunk to -1 | MISMATCH-P, untested (lead) |
| Player model lineup value | scripts/cbb_players.py:338 | P | recent BPM a minute, shrunk to bench | same lead |
| Roster prior, FV drivers, game prior | scripts/cbb_roster.py:101, cbb_fit.py:186 | P | pXPM box form | OK (Nov 26 round 3, do not redo) |
| xXPM | scripts/cbb_fit.py:231, cbb_live.py:250 | P | pXPM board form -> rXPM target | OK (PR #1241) |
| Next, next up, depth / backup grade | cbb_next.py, cbb_breakout.py, backup_watch.py:454 | P | pXPM board form | OK (Nov 26) |
| Ret%, NBA mock conviction, school development, award voter models | cbb_declare.py, cbb_mock.py, school_dev.py:82, awards_cbb.py:18 | P / D (fitted) | BPM | OK (Nov 26 swaps failed) |
| Board | layouts/shortcodes/cbbboard.html | P | FV key, xXPM, XPM | OK |
| Leaders: VORX/XPM | scripts/cbb_tabs.py:426 | D | VORX on shrunk rXPM, season only | DISPLAY (Next view) -> fixed |
| Leaders: pXPM | scripts/cbb_tabs.py:444 | P | frozen pXPM | OK |
| Leaders: stats | scripts/cbb_tabs.py:405 | D | XPM key, BPM column | OK |
| Standouts | scripts/cbb_tabs.py:491 | D | opened on xXPM up | DISPLAY -> fixed (XPM over x) |
| True freshmen | scripts/rookies.py:516 | P (board subset) | FV, xXPM, NBA%; line said BPM | DISPLAY -> XPM view + line |
| Top performers | scripts/cbb_tabs.py:522 | D | Game Score, game BPM | OK |
| Draft board, portal tab | scripts/cbb_tabs.py:540, 590 | P | mock slot / pXPM key | OK |
| Depth chart card stats | scripts/depth_stats.py:67 | D | label WAR, "BPM against his position" | DISPLAY -> fixed |
| Team talent / returning | scripts/cbb_tabs.py:633 | P | mean top-8 xXPM, FV | OK |
| Lineups, on/off, lineup leaders | scripts/cbb_lineups.py:514, 617 | D | net rating, within-season shrink only | OK |
| ARK Ranking, season odds, tournament odds, bracket | cbb_games.py, cbb_tourney.py | P | ARK rating (game model) | OK |
| Next up tab rate stat | scripts/next_up.py:15 | P | "best BPM" (the bar is defined on BPM) | OK |
| International board, G League links | scripts/cbb_intl.py | P | FV on NBA peak XPM | OK |
| All-time players | scripts/alltime.py | D | VORX on rXPM | OK (Nov 26) |

## Leads

- pxn between the first game and the last is a blend of two tested end points; the path itself is not backtested
  (needs dated game logs: extend `scripts/cbb_live_backtest.py` checkpoints with target = next-season rXPM).
- Game model absences: frozen pXPM as the prior in `avail(prior=..., pk=...)` and as the value in `pre_out`, through
  `scripts/cbb_inseason_research.py` and the game walk (needs Barttorvik game logs 2017-26), then `cbb_games.py --fit`, `--rules`.

# Round 2 (port round)

Scripts `r1_awards_rate.py`, `r1b_newcomers.py`, `r2_xxpm_prior.py`, `r3_xgap.py`, `r4_prior_leak.py`. R1 / R1b need
Barttorvik game logs ({year}_all_advgames.json.gz, 2016-26, about 11 MB each) in $BTLOG (not committed).

| item | swap | target | before -> after | t | folds | result |
|---|---|---|---|---|---|---|
| R1 (P2) awards games-left rate | prior last season's BPM -> preseason pXPM, K 300 | rest-of-season game BPM, 20+ minute returners at the 5th-20th team game, 2017-26 | MSE 7.347 -> 6.540; top 100 by BPM to date 7.349 -> 7.100 | 17.2 (top 3.1) | 10/10 (top 8/10) | PASS |
| R1 secondary, shipped form | same with K 600 (the walk's pick in 9/9 seasons) | same | 7.347 -> 6.345 (walked 6.377); top 100 6.113 | 25.2 (top 8.6) | 9/9 (top 10/10) | shipped |
| R1b newcomer prior (bug, not pre-registered) | own BPM to date, no shrink -> a prior at K 300 (floor: flat mean) | same pool, no line the season before | 12.52 -> 8.92 | 25.2 | 9/9 | fixed (prior = preseason xXPM) |
| R2 (P3) xXPM: last season's rXPM + VORX beside pXPM, BPM, WAA | reduced harness | next-season team R2 of returners, 2012->13 ... 2024->25 | .7849 -> .7853 (player RMSE 2.4332 -> 2.4322) | 1.56 | 8/13 | FAIL (tie) |
| R3 (P5/P1) backup xGap terms refit on the pXPM grade | shipped a, b, c -> walk-forward refit | two-season gap, 2,586 held pairs | MSE 13.157 -> 13.248; refit b .500 (was .481), c 1.265 (was 1.279) | -4.4 | 4/12 | FAIL, terms not stale |

- R1 shipped in `scripts/awards.py` cbb(): returners' prior = the board's frozen pXPM at KPX 600; newcomers = preseason
  xXPM (xb0) at K 300 (the part labelled 'BPM' it read is gone, so their prior was their own line). Conviction draws
  are unchanged (checked: same output). On today's board the Wooden race goes Coleman 44%, Tanner 12% -> Tanner 16%,
  Coleman 15%. `python3 scripts/awards.py cbb` rewrites data/awards.json (not committed here: every sport shares the file).
  DPOY's D-BPM prior is untested (the board has no D-pXPM column).
- P4: avail() and pre_out() run on the logs to date in the fit (cbb_games.py:1401, 1419) and live
  (cbb_games_live.py:530-531): one form. The roster prior's history rows read pXPM from the frozen coefficients; against
  the walk-forward pXPM the next-season RMSE differs by .008 at most, either sign (r4.json, r .999): no leak to fix.
- P5: fit files against the Nov 26 rebuild. Refit on or after it: cbb_fit (xXPM block), cbb_market_fit, cbb_next_fit,
  cbb_breakout_fit. Read BPM only, so not touched by the rebuild: awards_fit, cbb_declare_fit, cbb_lowdiv, school_dev,
  cbb_ceiling_fit, cbb_freshman_bo_fit. Older and reading the rebuilt number: backup_age.json cbb (R3: same terms) and
  cbb_live_fit.json kb (Nov 3, the xXPM blend weight 583 / 259 minutes, fit on the old xBPM): R1's grid puts the best
  weight of a pXPM prior at 600 minutes, so 583 stands; the full refit is `python3 scripts/cbb_link.py` then
  `python3 scripts/cbb_live_backtest.py` (careers cache + game logs).
- P6: next up's rate column is xXPM (the board's projection, freshmen included) in place of the shrunk BPM; the bar
  (Best) and CEIL stay in BPM, the model's units.
