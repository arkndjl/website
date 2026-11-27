# NIL audit, Nov 27 2026 (yNIL / xNIL / zNIL, CFB and CBB)

Anchors (none is fit to; each is a check):
- On3 valuations: 248 CFB players on the board (floor $300K), 42 CBB players.
- College Sports Commission pay percentiles (`csc_rs_football_tables.json` revenue share, `csc_nilgo_data.json` cleared
  third-party deals): football by position, power conferences (A4) and the rest, 10th to 90th percentile, with counts.
  Target = revenue share + NIL Go at the same rank; the board's players at a position are taken as its top-paid.
- ESPN GM / agent survey (Aug 2026): P4 starter pay ranges by position.
- Reported deals independent of On3: 11 CFB players on the board, 5 CBB.
- Reported school budgets: The Athletic (68 P4 football programs, mean $27.2M), CBS Sports (80 high-major basketball
  programs, mean $13.7M). These are now `data/nil_budgets.json`.

CFB yNIL (log error; `anchors.py`, `fit1.py`, `fit2.py`; bootstrap 4,000 draws on the On3 players):

| | CSC rmse | On3 rmse | On3 r | deals rmse | ESPN starters rmse |
|---|---|---|---|---|---|
| before (flat $20M x talent tilt, effective mean $31.5M; k 1.1) | .88 | .484 | .64 | .58 | .19 |
| school budgets | .71 | .479 | .66 | .62 | .23 |
| school budgets + k 1.375 (shipped) | .69 | .49 | .70 | .53 | .23 |

On3 r +.054 (90% CI .014 to .094); On3 rmse +.008 (CI -.016 to .035).

Failed:
- level scaled down to the CSC-implied total (x .735 to .88): CSC better, On3 bias -.07 to -.25, deals and ESPN worse.
- k 1.65 and up: On3 rmse .53+.
- curvature (log share = k s - c s^2): no gain on On3 at any c.
- position prices from the ESPN survey or from CSC: CSC .69 -> .63, On3 rmse .49 -> .52 (RB -.38, CB +.35 against On3).
- G5 / FCS level: model non-A4 total $297M against a CSC revenue-share total near $266M: kept.

CBB yNIL (42 On3 players; 5 reported deals):

| | On3 bias | On3 sd | On3 rmse | On3 r | deals rmse |
|---|---|---|---|---|---|
| before ($6M high-major x tilt) | -1.38 | .58 | 1.50 | .36 | 1.91 |
| high-major mean $13.7M x tilt | -.56 | .59 | .81 | .35 | 1.29 |
| school budgets (shipped) | -.38 | .52 | .65 | .44 | .21 (5), 1.05 with Quinn Ellis |

Failed: concentration 1.25 (On3 rmse .71) and 1.5 (.80). Mid- and low-major levels ($1.2M, $0.25M) have no player-level
anchor (On3 values none), and the CSC non-A4 total brackets both the old levels and The Athletic's survey levels ($2.3M,
$525K): unchanged.

Run from this folder with the On3 pull as `on3_cfb.json` (slug, nil) and the budgets research file beside it; paths in
`base.py` and `calib.py` point at the scratch layout used on the day.

## Whole-roster split and provisional players (same day, after the first rebuild)

The first rebuild on school budgets split each budget among PFN-listed players only: carried rows kept stale values on
top (team totals over budget) and the listed players alone absorbed the reported figure. On the rebuilt board yNIL
against On3 read bias +.27, rmse .554, top yNIL $14.9M. The offline test above had renormalised over carried rows too,
so it did not show this.

Fix and test (`full.py`, `full2.py`; listed players reweighted exactly, carried rows on their own old yNIL moved by the
listed players' median change, ESPN backups at d x the median listed player at his position on the team). CSC = log
rmse on the A4 pay percentiles with every rostered player counted:

| k | d | CSC A4 | CSC non-A4 | On3 bias | On3 rmse | On3 r | deals rmse | ESPN starters rmse | top yNIL |
|---|---|---|---|---|---|---|---|---|---|
| 1.375 | listed only (first rebuild) | 1.43 | .43 | +.27 | .554 | .69 | .71 | .21 | $14.9M |
| 1.375 | 0 | 1.22 | .48 | +.11 | .503 | .69 | .70 | .23 | $12.7M |
| 1.1 | 0 | 1.23 | .49 | +.04 | .491 | .64 | .69 | .23 | $8.4M |
| 1.25 | 0 | 1.23 | .48 | +.08 | .493 | .67 | .69 | .23 | $10.6M |
| 1.25 | .03 | .70 | .48 | +.04 | .487 | .67 | .70 | .28 | $10.2M |
| 1.25 | .05 (shipped) | .64 | .47 | +.01 | .484 | .67 | .71 | .30 | $9.8M |
| 1.25 | .10 | .71 | .48 | -.05 | .486 | .67 | .73 | .35 | $9.4M |
| 1.25 | .15 | .82 | .48 | -.10 | .494 | .67 | .75 | .41 | $8.8M |

A projected yNIL for provisional players halves the CSC error against a blank (1.23 to .64) and leaves On3 flat. P4
median provisional yNIL $24K (CSC bottom-quartile to median: $0 to $75K). k 1.375 dropped to 1.25: the r gain no longer
pays for the top-end error once the whole roster shares the budget.

xNIL and zNIL for provisional players, tested on backups provisional on Nov 5 and graded by Nov 27 (111 FBS, 157 FCS),
log error against the xNIL they got once graded:

| | FBS rmse | FCS rmse |
|---|---|---|
| worth formula at the provisional FV, no snaps | .44 | .57 |
| formula at half playing time | .47 | .31 |
| median graded teammate at the position (naive) | .41 | .29 |

The formula does not beat the naive value, and the naive value is only right for the ones who go on to play: left
blank. The FV slope of pay within provisional players was tested too (.018 log per FV point in P4): no change in any
score, dropped. CBB has no analogue: its budget loop already covers the whole roster (newcomers on the freshman
projection).

## Premiums, market tracking, budgets by year, coverage (same day, third pass)

Top-end and scarce-position premiums (`prem.py`, `prem2.py`, `rec.py`, `rec2.py`). yNIL split with the team total held:

| | CSC A4 | On3 rmse | On3 r | deals rmse | top yNIL |
|---|---|---|---|---|---|
| shipped | .642 | .484 | .673 | .71 | $9.8M |
| every QB x e^.30 | .651 | .487 | .707 | .70 | $12.2M |
| starting QB x e^.30 | .634 | .485 | .711 | .70 | $12.4M |
| convex (listed players' exponent 1.1) | .637 | .489 | .690 | .71 | $11.8M |

No score moves by more than .01: fail. CSC top quantiles (q .75+), model against actual: QB -.11, LB +.08, OL +.19,
TE +.43, DL +.46, WR +.51, RB +.65. The model is not short at the top or at QB; it overpays the top RB, WR, TE and DL
(repricing those from CSC failed against On3 in the first pass). CBB (27 On3 players): slope of log(On3 / yNIL) on FV
-.008, no position pattern: fail.

Recruits (95 of the 2027 class with an On3 high-school valuation): xNIL carries no position. QB recruits sit .50 under
On3 (n 9, se .12). The college board's position prices on recruit xNIL, no parameter fit on recruits:

| position term | sd | rmse | r | P(rmse better) |
|---|---|---|---|---|
| none | .500 | .520 | .39 | |
| half, fit coefficients | .462 | .492 | .50 | .99 |
| full, fit coefficients | .466 | .503 | .52 | .76 |
| half, board medians (the form the build can use) | .466 | .501 | .49 | .92 |

Mixed: the weight is picked in sample, the buildable form's interval crosses zero, and The Athletic's ranges (five-star
QB $750K to $1M, top-150 QB not starting $300K to $400K) fit the unadjusted numbers ($960K, $380K to $550K) better than
the adjusted ones ($1.46M, $570K to $830K). Not shipped.

Market tracking (`on3_history_pull.py`, `on3_history.py`, `on3_vs_deals.py`): 371 players' daily On3 valuations, Nov 24
2025 to Nov 27 2026. On3 moves in steps: 553 changes in a year, 314 of them in July 2026, none since August. The July
step by position: QB +.47, EDGE +.42, LB +.39, S +.39, RB +.37, WR +.35, IOL +.26, CB +.25, OT +.21, DL +.17. The board
refits its position prices on On3 at every run, so it follows On3 the same day, but On3 itself is months behind.
Reports lead it: the three deals reported above the player's On3 value (Mestemaker Jan, Leavitt Feb, Seaton May) were
each followed by On3 moving toward the report (.43 of 1.19, .11 of .40, .88 of .88 in logs; about half the gap on
average). Kamario Taylor: On3 $1.5M, reported $7.5M on Nov 25. A position-level deal signal could not be tested (two
positions with reports before July).

Shipped: `data/nil_deals.json`; a report moves the player half way (geometric) from the model's number: yNIL when the
deal is for this season, xNIL when reported in the last year, and the price fit's target for him. Forward check on the
five 2026 deals against On3's later value, yNIL log rmse .60 to .28.

Budgets by year and overspend (`bud.py`): paying each listed school the top of its reported range, CSC .642 to .682,
On3 bias +.01 to +.08: fail (the official total sits under the reported budgets as it is). Team mean On3 residual
against log budget r -.61 (22 teams): On3 scales less with the budget than pay shares do. Shipped: a list from an
earlier season carries forward at the market's growth (11% a year, Opendorse 2024-26) in place of falling back to
the flat levels.

Coverage: kickers and punters had no NIL. Paid XNIL.spec .20 x e^(.10 (FV - 37)) x the team's median listed player
(ESPN backups .01): CSC kicker and punter percentiles log rmse 1.53 blank to .40; fit on kickers and scored on punters
.49 (blank 1.50), the reverse .48 (blank 1.55). Backups' and specialists' xNIL: the group's pay in its market shared
by worth (zNIL sums to zero in the group); there is no outside anchor for it. Small pay is kept to the nearest $100.

## Noah's calls (Nov 27, fourth pass)

Basketball mid- and low-major levels (`cbb_levels.py`). The Commission's school report has men's basketball outside
the power conferences (n 3,667 rostered players; 90th percentile $165,000, 75th $50,000, median $8,500, a quarter
unpaid). The board's players outside the four power conferences, log error at the 90th / 75th / median:

| mid-major | low-major | rmse | 90th | 75th | median |
|---|---|---|---|---|---|
| $1.2M | $0.25M (before) | .451 | -.50 | -.45 | +.39 |
| $2.3M | $0.525M (The Athletic's survey) | .671 | +.06 | +.25 | +1.13 |
| $2.3M | $0.25M (shipped) | .226 | .00 | .00 | +.39 |
| $1.2M | $0.525M | .629 | -.25 | -.03 | +1.06 |

The mid-major survey level passes, the low-major one fails (the median player would be paid three times the report).

Football position pay (`pos.py`, `pos2.py`), Noah's call to follow what schools report over On3. A log offset on RB,
WR, TE and DL / EDGE, team totals held, solved so each sits at the other positions' mean error against the
Commission's power-conference percentiles. The defensive line is scored with linebackers: the board has 1,322 P4 DL
and EDGE against the report's 1,060 defensive linemen, 795 linebackers against 858. Offsets RB -.55, WR -.26, TE -.31,
DL / EDGE -.41.

| | CSC A4 | CSC non-A4 (not solved on) | spread of position errors | On3 rmse | On3 r | deals rmse | ESPN starters |
|---|---|---|---|---|---|---|---|
| before | .644 | .477 | .207 | .476 | .688 | .62 | .30 |
| offsets | .599 | .447 | .109 | .510 | .669 | .62 | .33 |

On3 by position after: RB -.42, TE -.20, DL -.15, EDGE -.08, WR -.05, QB +.13, OL +.16, CB +.20, LB +.21, S +.22.
Solved without pooling the front seven the DL offset was -.73 (On3 DL -.42): the listing difference, not pay.

Headline scanner (`scripts/nil_deal_scan.py`): 30 days of Google News on Nov 27, 267 items, 12 with NIL and a dollar
amount, none a new confirmed deal (valuations, questions, budgets, opinion pieces); the one it read as a deal
(a $12M multi-year total in an opinion headline) is now rejected twice over (opinion pattern, $8M cap).
