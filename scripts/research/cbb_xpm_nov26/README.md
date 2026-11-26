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

## rXPM round 3 (new thread, Nov 26; prereg.md "rXPM round 3" + amendments 1-4)
Game logs 2007-08 ... 2025-26 (19 seasons, 205k team-games), gl.py tables, every target schedule-neutral (adjusted margin =
margin + opponent adjEM - venue). Scripts rxpm4-9.py.

Round 2's D8 does not survive: with an odd-games-only anchor it describes the even games' adjusted margin at .688 (odd-game
GBPM .883) and loses on the raw target too. Its T1/T2 wins were the schedule (raw win%, raw margin, raw anchor).

| question | BPM | GBPM | note |
|---|---|---|---|
| who sat out (credit split; within-team game margin vs rotation ratings, held-out slope) | .00484 | .00420 | BPM better; starters only .00567 / .00494; half-split .00201 / .00179 |
| team adjEM describe | .9996 | .9954 | BPM by construction |
| team WAB a game (schedule-adjusted wins) | .880 | .888 | GBPM (t 11, 19/19) |
| raw win% | .652 | .676 | GBPM; schedule-contaminated target, not a gate |
| split half, odd -> even adjusted margin | .824 (BPM-like) | .883 | GBPM's game-level sums are a better half-season team read than the half's own margin |
| next-season team R2 | .642 | .611 | BPM |

| candidate | result |
|---|---|
| X1 a BPM + (1 - a) GBPM | a = .75 picked; ties BPM on who-sat-out (t .32) |
| X2 college box weights fit on rotation absences (base BPM) | who-sat-out .00484 -> .00567 (t 5.2-5.4, 17-18/19), half-split t 5.2, next season vs same base t 3.3; starters only t .7: FAIL (bar t > 1 in all three designs); its missed-two / turnover weights flip sign on starters (bench-appearance bias) |
| X2 weights fit on starter absences | all three designs pass (t 5.65 19/19, 1.94 14/19, 4.66 15/19) but next-season team R2 .6419 -> .6371 (t -2.1), split half t -8.8: FAIL guard N (pays +1.2 a SD for made threes: shooting luck) |
| X2 weights fit on the half-split / on all three stacked | min t -4.4 / .16: FAIL |
| X3 box weights per side | worse than BPM (t -3.5): FAIL |
| W1 BPM re-anchored to adjEM + wins mix (c .25 / .5) | WAB .901 / .918 by construction, split half t -10.8 / -22, next season t -10.8 / -12.8: FAIL |
| W2 BPM re-anchored to capped game margins (10-30) | worse on WAB, split half and next season at every cap: FAIL (blowouts carry information) |
| R2 leave-the-game-out ratings | invalid design (a leave-one-out rating mirrors the game's own box score); replaced by the half split |

Amendment 5 (rxpm10.py), the two-part read: every test reads either the split of credit inside a team (who sat out) or
the team total (WAB, win%, adjEM). BPM wins the split, GBPM the wins totals. H = BPM - team mean(BPM) + team mean(GBPM),
per side (BPM's split on GBPM's totals):

| H vs | who sat out A / starters / half split | WAB a game | win% | adjEM | next-season team R2 | player r vs next BPM |
| --- | --- | --- | --- | --- | --- | --- |
| GBPM | t 3.03 (14/19) / 4.85 (17/19) / 1.89 (11/19) | .8882 = | .6763 = | .9954 = | .6114 -> .6236 (t 3.37, 12/14) | .620 -> .668 |
| BPM | identical | .8803 -> .8882 (t 11.3, 19/19) | .6521 -> .6763 (19/19) | .9996 -> .9954 (0/19) | .6419 -> .6236 (0/14) | .680 -> .668 |

SD 3.62, r(H, BPM) .998, mean |H - BPM| .24. SHIPS as rXPM (site label XPM): scripts/cbb_xpm.py rxpm_lines; WAR, Stat+,
board XPM column, stats, portal (scripts/cbb_tabs.py; R -1.4, wins a point .01872, r .872). Not a predictive input: BPM
stays the base of pXPM. The audit's "GBPM .658 vs BPM .633" came from raw win%; WAB is the schedule-neutral read.
Lead not taken: GBPM's game-level team sums as an in-season team-strength input (split half .883 vs .824).

## pXPM round 2 (prereg.md "pXPM round 2"; pxpm2.py, pxpm2_down.py)

Walk-forward 14 pairs, blocks added to the shipped box form (v1):

| block | alone: team R2 (t, pairs) | read |
| --- | --- | --- |
| v1 | .7325, r .770, RMSE 2.359 | |
| F3 team context | .7407 (t 7.07, 14/14) | KEPT |
| F2 recruit rating x class | .7405 (t 4.95, 13/14) | KEPT (t 3.84 after F3) |
| F1 late form | .7326 (t 2.38) | nothing once F3 + F2 are in (t .62) |
| F4 role / F5 shape / F6 consistency | t -3.8 / -5.2 / -4.7 | FAIL |
| F7 age | t -.3 | FAIL |
| v2 = v1 + F3 + F2 | .7457 (t 7.87 vs v1, 13/14; vs BPM .6425 t 15.35, 14/14), r .780, RMSE 2.316 | SHIPS as the board form |

Line-derived team context (5 x minutes-weighted mean side BPM of the team's lines) gives the same .7457 (pxpm2_linectx.json),
so production needs no team-results file. Downstream: roster prior .7649 -> .7677 (t 3.74, 13/14); FV driver v2 for v1
+.09 / +.10 (t .87 / .99): tie. Board form = scripts/cbb_xpm.py pxpm2_parts / values2 / frozen (beta2 in
data/cbb_xpm_fit.json, scripts/data/cbb_pxpm_2026.json): pXPM leaders, portal, board hover. FV, roster prior and the game
model stay on the box form (v1) until a full refit of the game model with the board form in the roster prior.
