# Port pass Nov 23 2026: NHL + hockey prospects, pre-registration

Written before any test below was run. Lockbox: NHL 2026-27 (S = 2027) is never read. The game history is
scripts/nhl_games_hist.json.gz (seasons 2011..2026 only); the rookie test reads static/data/nhl-war/<S>.json for S <= 2026.

## Common
- Win rows: nhl_games.walk(hist, live fit params, moves=hist_moves) on hist with SBR closes for <= 2019
  (nhl_audit_research.with_sbr). Base win inputs = the live fit's feats (elo, xg, b2b, home, rv). Walk-forward logit
  by season (nhl_games.walk_logit, first 2017, train all games of earlier seasons). Loss = per-game log loss.
- Totals rows: the live history (ESPN closes only, as the live model). Base = TFEATS (xgT, gT, mtot, gkT, one), walk_ols
  first 2021, trained on lined games. Loss = squared error on lined games.
- t = harness.paired(new, base, cluster = game day). Tune = 2017-23 win (2018-23 for stage-2 cells; 2021-23 totals,
  2022-23 for totals stage-2), held = 2024-26.
- Ship rule per cell: tune t <= -1.5 (new better) AND held one-sided p past Holm over all cells in this file at .05.
  Cells with two pre-registered variants pick the variant on tune t only; the held test reads the picked one only.

## Cells
C1 (G2 early-season stretch, win). e = 1 if the game day is within 21 days of the season's first regular-season day.
   z0 = base walk-forward logit. Stage-2 walk_logit on [z0, e*z0, e] vs on [z0] (both first 2018).
C2 (G2 early totals shrink). T0 = base walk-forward total; dm = mean T0 of that day's games. Stage-2 walk OLS on
   [1, T0, e*(T0 - dm)] vs [1, T0], lined, first 2022.
C3 (G5 market disagreement mdis, win). Per team d, 0 at each season start. Feature mdis = d_h - d_a before the game.
   After each game with a close pc: err = (logit(pc) - z0) - (d_h - d_a); d_h += .2 err; d_a -= .2 err. z0 = base
   walk-forward logit (2016 rows: in-sample 2016 fit, training rows only). Add mdis to base win inputs.
C4 (G5 totals disagreement tdis). Per team td, 0 each season. tdis = td_h + td_a. After each lined game:
   err = (tc - T0) - (td_h + td_a); td_h += .2 err; td_a += .2 err. T0 = base walk-forward total (2020 rows: in-sample
   2020 fit). Add tdis to TFEATS.
C5 (G11 returners). In lineup value rv, a skater absent from the S-1 HPM file but in the S-2 file with 20+ GP is
   priced at repl + .85 x (his S-2 HPM, aged by age_line(S-1), minus repl) at his S-2 usual TOI (cap 30 min), instead
   of replacement. Replace rv with this rv in the base inputs.
C6 (G18 roster turnover). Delta_t = team's latest lineup value this season minus the value of its last lineup of
   season S-1, both priced with season S's pricing (nhl_games._war(S)). rdel = Delta_h w_h - Delta_a w_a. Variant A:
   w = exp(-gp/20) (gp = team games played this season); variant B: w = 1. 0 until both teams have played this season.
   Add to base win inputs.
C7 (M1 age-adjusted rookie rate, NHL aHPM). Rookies by the rookies.py Calder rule, skaters, rookie season 2011-2023,
   rookie TOI >= 200. Target: next three seasons' (go + gd) / toi x 60 with 600 minutes at the group's replacement
   HPM added (target shrinks to replacement; missed seasons add 0 minutes). Base: HPM. New: HPM + k (age - 21), age =
   'ax' (decimal), k fit by weighted LS (weight = rookie TOI) leaving the rookie class out. Loss = weighted squared
   error. Pass: t <= -2 clustered by class AND better in 8+ of 13 classes AND Holm as above. Ships as a display column
   aHPM on the NHL rookies board only (rv already ages HPM by age_line); split-half r of k reported (odd vs even classes).
