# CFB model audit: game model, ARK Ranking, FV

Walk-forward margins from `node scripts/games_wf/cfb_wf.mjs --hist <out> <espn odds cache>`, scored by `cmp.py`
(paired per-game abs error and log loss, t clustered by game day). Tune 2017-20, held 2021-26 with 2026 weeks 1-10
only (week 11 on is the lockbox). Pre-registrations: `prereg-A/B/C/F.md` beside this file's copy in project files.

Setup that reproduces the committed file: `python3 scripts/cfb_espn_pbp.py --current`,
`python3 scripts/control_ratings.py cfblive`, `node scripts/cfb_ret_war.mjs`, then the walk-forward (about 80 s).

## Diagnosis

Model trails the close by 0.3-0.6 points of MAE overall, 1.0-2.5 in FBS-FCS games and 3.6 in the first five games of a
team new to FBS. The FCS side was one pooled team; a team new to FBS started at a fixed -12.

## Game model (family A, B, C)

| id | candidate | tune t | held t | result |
|---|---|---|---|---|
| A1 | pooled FCS efficiency carried as a preseason prior | | full -1.33 | fail (week-1 bias vs close 2.4 to 0, MAE flat) |
| A2 | new-to-FBS prior anchor = own last final Elo | -1.07 | -2.17 (LL -2.24) | ships as a bug fix |
| A3 | FCS side's own Elo deviation | | | fail |
| A4 | NFL draft value lost in the prior | +1.5 | | fail (worse) |
| A5 | FCS side's own all-D-I margin rating vs the FCS mean (`fcsm`) | -1.59 | -2.48 | pass, Holm ok; FCS games MAE -0.26 |
| B1 | input weights by part of season (kappa grid x stretch) | +2.4..+3.2 | not scored | fail |
| C1 | FCS opponent credit in the efficiency adjustment (c .5, 1) | -0.98, -0.63 | not scored | fail |

Shipped set (A5 + A2) against base: MAE -0.045, t -1.83 tune, -2.78 held, -3.27 full; held log loss t -1.81; FCS games
gap to the close 1.47 to 1.20; fitted `fcsm` weight .449. `FCSM=0` and `NEWFBS=0` turn each off.

## FV (family F)

Own-unit context (opponent-adjusted EPA of a player's side of the ball) on the all-time rows, class held out:
MSE 78.15 to 75.74, class-clustered t -2.09, 7 of 8 classes; whole team t -1.81, 6 of 8. Fails Holm at t(7)
(p .037 against .025) and is weak in 2020-23 classes. Not shipped.

## Leads

- FBS-FCS week-1 level term judged on distance to the close.
- Season-phase weights again when more seasons exist.
- Unit-context FV re-registered on 2020+ classes once the 2024-25 drafts mature.
- Home residual +0.7 to +2 in 2024-26.
- Prediction Tracker and Massey sit behind a bot wall; not used.

`candidates.patch` holds the code of every failed candidate against `scripts/cfb_model.mjs`.
