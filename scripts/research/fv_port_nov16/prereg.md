# FV driver ports across sports: pre-registration (Nov 16 2026)

Ask (Noah): try FV drivers that work in one sport in the other sports. Written before any new test ran.

## Inventory of shipped FV drivers and their analogues

Status per cell: TESTED = an analogue already failed in an earlier pass (memory note named), NEW = run here, N/A = no data or no board.

| Shipped driver (board) | CFB | CBB | Hockey | Soccer | Tennis | CS2 |
|---|---|---|---|---|---|---|
| WJC / youth national team (hockey) | N/A | TESTED (FIBA youth, Olympics; USA Basketball no source) | own | TESTED (U17-U21 caps, senior caps <21) | TESTED (Davis/BJK Cup, junior Slams) | N/A |
| Pro games while a prospect, progp / nany (hockey) | N/A | TESTED (intl level) | own | own (lg_share) | TESTED (tour main-draw / Challenger volume, level progression, seeded share) | own (S/A-tier share) |
| Growth since draft year, nhgrow (hockey) | TESTED (share/usage gains) | TESTED (usage trajectory, trend kept) | own | TESTED (6-month MV change, minutes-at-age) | TESTED (Elo change, Elo below peak) | TESTED (rise) |
| NHL preseason share, pnS (hockey) | N/A (no camp data) | TESTED (combine stage) | own | TESTED (subs, call-up minutes) | TESTED (wildcards, junior exempt) | N/A |
| Durability GP/schedule, dur (hockey k4) | TESTED (availability) | TESTED (game-log absences) | own | TESTED (durability, absences) | TESTED (layoff gapmx, lead) | N/A |
| League strength x minutes share, lg_share (soccer) | TESTED (SOS, team, Elo context) | NEW C2 | TESTED (team GF, share of team goals) | own | N/A | TESTED (teammates' mean, tier share) |
| Detailed position block (soccer) | own (per-position fits) | NEW C1 (7 Barttorvik roles; G/W/B already in) | TESTED (centre, right-shot D) | own | N/A | N/A (bo3.gg has no AWP field) |
| Tree blend .5 linear + .5 GBM (soccer) | N/A (hand-weighted multipliers, no fitted design) | NEW C3 | TESTED (draft LEAD, stages fail Nov 15) | own | TESTED (ATP reverted, WTA fails) | TESTED (series GBM, game model) |
| Train on later expectations, TD (ATP) | TESTED (horizon fix Nov 11) | TESTED (6-season outcome) | N/A (1-4 finished classes) | N/A (0 scoring seasons) | own (WTA fails) | N/A |
| Youth plus (soccer, tennis) | TESTED (removed) | TESTED (age priced by spread) | TESTED | own | own | N/A (badge, not driver) |
| Pooled top rungs (intl basketball with college) | N/A (no rung fit) | own | TESTED (goalies too few; draft one model) | TESTED (GK top slope) | NEW T1 (WTA pooled with ATP) | N/A |
| Stat+ production index (CBB splus) | own (statplus) | own | own (NHLe) | TESTED (per 90, G+A x league) | own (Elo+) | own (RWA) |
| Combine athleticism (CFB, CBB guards) | own | own | N/A (combine tests not free) | TESTED (height = hindsight leak) | TESTED (height leak) | N/A |
| Specialist / special-teams role, return YOE + punter (CFB) | own | N/A | NEW K1 (CHL short-handed points) | N/A (no set-piece data) | N/A | N/A |
| Exact age / youth terms (all) | own | own | own | own | own | own |

NBA: no FV board (XPM projections), so no cells.

## Tests (each added alone to the shipped model)

- C1 CBB returner ladder + last-season Barttorvik role dummies (PG, Combo G, Wing G, Stretch 4, PF/C, C; base Wing F).
- C2 CBB returner ladder + tshare = (z team strength + 2.5) x min_per / 100, team strength = minutes-weighted mean BPM of the team's players that season, z over all team-seasons.
- C3 CBB returner ladder, each rung P = .5 shipped linear logit + .5 HistGradientBoosting (depth 3, 300 iter, lr .05, min leaf 40, l2 1) on the same kept columns.
  CBB gates (cbb_fv_sweep2 rules): class folds clustered t >= 2 and >= 4/5 folds, both player splits positive; held 2017-19 boards top 10/25/50 realized and top-300 corr not worse on average; forward 2020-23 deviance gain >= 0.
- T1 Tennis WTA hurdle fit on WTA + ATP rows: shared slopes on the WTA kept drivers plus a WTA intercept and ridge-shrunk WTA x driver deviations (lambda nested from {1, 10, 100} by inner birth-year-out). Gate: birth-year-out WTA MSE gain clustered t >= 2, >= 12/19 birth years, forward (fit births <= 1993) WTA MSE and top-50 not worse.
- K1 Hockey draft model + chlSH = CHL short-handed points per game in the draft season (0 outside the CHL). Gate: class-out t >= 2, >= 8/12, top-64 MSE and Spearman better, forward 2016-19 MSE and top-64 rho better.

Holm per sport on the primary t (one-sided p): CBB m = 3, tennis m = 1, hockey m = 1. A test ships only if it passes Holm and every co-gate. Shipped FV stays absolute, headline = mean outcome, steps of 1.
