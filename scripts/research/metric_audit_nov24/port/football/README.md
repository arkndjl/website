# Football port round (CFB + NFL), Nov 24 2026

Pre-registered in `prereg.md` (sha256 `prereg.sha256`) before any test was scored. One Holm batch over the five tests run.
LOCKBOX: CFB 2019-25 rows/games only, NFL 2016-25 only (no 2026 file read). No CFBD call (cfbfastR mirror parquets, nflverse caches).

Run (from this folder): `python3 cfb_port.py` (a, b, d), `python3 cfb_neutral.py` (e2; downloads not scripted: cfbfastR
`play_by_play_<y>.parquet` 2017-25 into scripts/.cache/cfb/fastr/, then cached as qb_neutral.json; needs pyarrow),
`python3 nfl_neutral_prep.py` + `NEUTRAL=0 python3 nfl_neutral.py` + `NEUTRAL=1 python3 nfl_neutral.py` (e1),
`python3 cfb_g5_diag.py` (post hoc), `python3 combine.py` -> `results.json`.

| idea | sport | target | before -> after (held out) | t | p | better | result |
|---|---|---|---|---|---|---|---|
| (a) 6 XV fit per side | CFB | describe | .714 -> .714 | -0.22 | .41 | 5/7 | fail |
| (b) 6 pXR form (position line unshrunk) | CFB | predict team | .255 -> .211 | +3.32 | 1.0 | 1/6 | fail (player r .576 -> .608) |
| (c) 3 uncovered snaps at replacement | NFL | describe | void | | | | NFL WAR is over replacement: uncovered time already counts at 0 (found a 2020 data bug, below) |
| (d) 5 G5 level weight (z - c, c .75) | CFB | predict team | .255 -> .284 | -2.78 | .003 | 5/6 | fail: Holm-significant but player-r guard fails (.576 -> .523) |
| (e) 1 neutral EPA (wp .1-.9) -> pXR/60 | NFL | predict team | .330 -> .326 | +1.10 | .86 | 2/7 | fail (pXP .248 -> .247, XV .229 -> .223) |
| (e) 1 neutral EPA -> pSV/60 | CFB | predict team (QB block) | .073 -> .065 | +1.02 | .85 | 2/6 | fail (player r .272 -> .260) |
| (f) 4 age decline on pXR/60 | NFL | | skipped | | | | pXR = pXP + an age-free sub-position constant: the player-level age fit (Nov 11 fail) is the same fit |

Notes
- (a) Both arms refit XV every fold on seven positions (cfb_xv_backtest.py fit). Post hoc, not tested: that per-fold 7-position
  refit holds out at .714 against .689 for the shipped weights (fit on 2024-25, ten positions); a lead for a refit test next round.
- (d) Post hoc (cfb_g5_diag.json): the discount lowers player r for G5 -> P4 movers (.463 -> .332) and for players staying at
  their tier (.572 -> .537), so the team gain is a tier prior on G5 teams (their returning value overstates next season's
  SRS), not a better player value. If wanted it belongs in the team/game model's prior with its own test, not in player value.
- (e) Neutral plays are 74-80% of NFL plays, 64-67% of CFB QB plays. Raw arms reproduce round 1 (pXR/60 .330, pSV/60 .073).
- NFL data bug (from the (c) coverage check): 2020 nflverse snap counts list two spots (C/G 12, G/T 11, G/C 8, WR/R, FB/D,
  DE/L, DT/D). `scripts/nfl_war.py` group_of maps none of them, so ~60 player-team seasons (3.1% of 2020 scrimmage snaps;
  BAL offense covers 7.5 of 11 slots, NO 7.9, HOU 8.5) get no AV, WAR or XV row; 2020 team pools split among the rest and
  the AV fit (2016-25), XV fit (2018-25) and pXP history read the gap. 2016-19, 2021-26 have only K/P/LS unmapped (by design).
  Not edited (the lead is rerunning nfl_war.py); suggested patch in group_of: `if pos not in GROUP and '/' in pos: pos = pos.split('/')[0]`.

## Addendum (lead's request): pXR leakage check, as nhl_n6check.py (`nfl_pxr_leak.py`, `cfb_pxr_leak.py`)
NFL round-1 C2, predict team held out; constant k = .0165 a share (mean position value, no position information).
| harness | pXP/60 | pXR/60 | constant | pXR vs base | constant vs base | pXR vs constant |
|---|---|---|---|---|---|---|
| raw n+1 snaps | .248 | .330 | .318 | t -3.41, 7/7 | t -3.31, 5/7 | t -0.94, 4/7 |
| lineup shares (11 a side, ST rows out) | .250 | .335 | .321 | t -3.72, 7/7 | t -3.63, 5/7 | t -1.00, 4/7 |
Player r vs next board WAR rate: pXP .444, pXR .629, constant .433. Within sub-position: pXP .458, pXR .447, constant .447.
Verdict: rescaling to lineup shares does not remove the gain, but a constant with no position information gets most
of it, and pXR does not beat the constant (t -1.0, 4/7). The gain is not positional. The constant still helps on fixed
lineups because the predictor is shrunk E/(E+.2) on season-n exposure, so a positive level counts in proportion to
returning exposure (a continuity signal). pXR's player r gain comes from position levels matching the board WAR target;
within a position it is .011 below pXP.
CFB (b), same check: on lineup shares base cWAR .246, pXR form .222, constant .205. Leaving the level unshrunk loses
here (pXR vs base t +2.08, 1/6), so it fails either way.

## 2020 position patch (applied)
`scripts/nfl_war.py` group_of: a two-spot label maps by its first spot (2020 adds 54 player-team rows: 2,105 -> 2,159 XV rows).
AV fit (refit into scratch, data file not written): coefficients unchanged to 3 decimals except RB rec .541 -> .543; fit
rmse 3.78 -> 3.76, 2024-25 test r .941 both. XV margin weights with patched 2020 vs current: corr .9994, max change .09
(RB fd 1.15 -> 1.06). Not material to either fit. What it does change is 2020 board rows and pools (and so 2020-22 history).
Rerun: `python3 scripts/nfl_war.py --fit` (optional, immaterial), board replay for 2020 history, `python3 scripts/nfl_xv.py --prep 2020`
then `--fit`, `nfl_rate` (pXP history 2020-22), then the usual downstream. The 2026 board is unaffected.

