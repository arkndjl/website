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
