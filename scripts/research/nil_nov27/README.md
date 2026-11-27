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
