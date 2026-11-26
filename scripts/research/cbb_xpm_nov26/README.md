# CBB XPM (Nov 26 2026)

Pre-registration: `prereg.md`. Shipped form: `scripts/cbb_xpm.py` (D side on BPM only; GBPM is not on every line source).
Data: Barttorvik getadvstats csv + team results 2008-2026 in scripts/.cache/team_adj (not committed). No 2026-27 outcome read.
`loso.py` writes pxpm_loso.json.gz (not committed; rerun it, ~5 s) for roster/fv/mock/xbpm/game.

| test | script | result |
|---|---|---|
| pXPM vs BPM, next-season team adjEM R2 (walk-forward, 14 pairs) | xpm.py | .643 -> .732 (14/14, t 15.7); player r .680 -> .770, RMSE 3.41 -> 2.36: pass |
| pXPM vs roster prior BPM_hat alone | xpm.py | .757 -> .732 (t -4.3): fail (BPM_hat has recruit rank, transfer context) |
| pXPM vs the board's xBPM (walk-forward) | xbpm.py | xBPM .735 / r .795 better; pXPM as an xBPM input .7348 -> .7353 (t 2.09): not added |
| rXPM: side blend / GBPM team-adjusted / both, held-out win% vs GBPM .658 | xpm.py | .658 (t .09) / .637 / .636: fail, WAR stays on GBPM |
| pXPM in the roster prior (for last-season BPM) | roster.py, roster_wf.py, prod_check.py | .757 -> .765 (13/14, t 4.1-4.3): pass; xBPM there .752 (t -3.2) fail |
| game walk with that roster prior | game.py, prod_check.py | MAE 2016-20 9.2643 -> 9.2618 (t -2.6), 2021-26 9.5915 -> 9.5892 (t -2.8), lined t -2.9, 10/11: pass |
| FV returner driver (cbb_fv_drivers protocol) | fv.py | add t 3.4/3.7 5/5; for bpm3 t 2.5/3.1; for bpm t 3.2/3.5: pass |
| FV: cbb_fit selection + gates | fit_pxpm.py, cbb_fv_core.py gate | kept (over bpm); nested .105 -> .107; RPS .0802 -> .0789; corr300 2009-16 .414 -> .431 (8/8); 2017-19 top 50 39.0 -> 39.6, corr300 .434 -> .422 (1/3) |
| NBA mock conviction (for 3-season BPM) | mock.py | RMSE 1.3633 -> 1.3579 but t .6, 8/15, slot error worse: fail |

## rXPM round 2 (unfinished, handed to a new thread Nov 26 20:02Z)
Prereg: prereg.md "rXPM round 2" + amendment. Scripts rxpm2.py (D1-D6, rxpm2.json), rxpm3.py (D7/D8, rxpm3.json).
Seasons 2013-2026, Barttorvik game logs in scripts/.cache/cbb/games_bt. GBPM held-out win% R2 .650 (BPM .624).

| candidate | T1 win% R2 (t, seasons) | T2 odd -> even games, win% / margin | note |
|---|---|---|---|
| D1 possession-weighted game BPM | .648 (t -5.5, 1/14) | baseline .494 / .614 | fail |
| D2 blowouts down-weighted | .632 (t -14.3) | .487 / .605 | fail |
| D3 opponent-adjusted (k chosen 0) | .648 | same as D1 | fail |
| D4 GBPM + team-fit box correction | .788 (t 15.5, 14/14) | .520 / .634 (t 6.0 / 6.5) | fails guard G: player SD 16.3 vs GBPM 3.7, +16.5 per SD of DRB rate; not a player metric |
| D5 GBPM/BPM/PRPG blend | .748 (t 10.2, 14/14) | not run | weights collapse on PRPG; guard not checked |
| D6 D2/D3 + box | .787 | .518 / .630 | as D4 |
| D7 GBPM team-adjusted to raw net rating | .874 (t 19.5, 14/14) | .472 / .560 (t -2.7 / -6.7) | fails T2: schedule noise |
| D8 GBPM team-adjusted to .75 raw + .25 adjEM | .838 (t 21.9, 14/14) | .525 / .630 (t 5.0 / 2.6; 13/14, 10/14) | passes T1, T2, G (SD 3.28); adjEM describe .886 vs GBPM .995 |

D8 is the live candidate: not yet verified (alpha grid edge .75 was the smallest raw share that still won, so try
alpha lower/finer; T1 is partly mechanical because the shift injects the team's own raw margin, so T2 is the honest
test; T2 used odd-game raw net with full-season adjEM, which leaks even games through adjEM: redo with an odd-game-only
opponent adjustment). Nothing shipped; WAR still on GBPM.
