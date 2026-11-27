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
