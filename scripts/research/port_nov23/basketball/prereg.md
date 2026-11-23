# Port pass Nov 23 2026: NBA + CBB (pre-registration, written before any run)

Data: scripts/data/games_wf/{nba,cbb}.json.gz (walk-forward model rows m / tm, closes L / T, results). Lockbox: no
row with S >= 2027 is read (files end at S 2026; every script asserts it). In-model walk (B5) masks S <= 2026.
Splits: NBA tune 2015-21, held 2022-26 (model's own split). CBB tune 2016-20, held 2021-26, lined games (L and T set).
Loss: absolute error. Paired t via scripts/harness.py paired, clustered by game day x home team-season.
Parameters are picked on tune only (grid min tune MAE); held is scored once with the tune pick.
Gate (every cell): tune t <= -1.5 AND held d < 0 AND held one-sided p, Holm over B1-B7 (7 tests) <= .05.
Secondary (reported, not a gate): held lined MAE vs the close, slope of (res - L) on the prediction change.

## Cells
- B1 NBA early margin stretch (CFB G2): m' = c x m when min(home games played, away games played) this season < G
  (prior games in the wf rows, regular season and playoffs counted). Grid G {6, 12, 20}, c 1.00..1.30 step .01.
- B2 NBA early totals shrink (CFB G2): tm' = mbar + s (tm - mbar) when min games played < G, mbar = mean tm of the
  same date's games (dates with 1 game unchanged). Grid G {6, 12, 20}, s .50..1.00 step .05.
- B3 NBA mdis (CBB G5): team d starts 0 each season; games by date; m' = m + c (d_h - d_a); after each date, for every
  game e = (L - m) - (d_h - d_a), d_h += K e, d_a -= K e. K .2 fixed (CBB's). Grid c 0..1.50 step .05.
- B4 NBA tdis (CBB G5): same on totals, e = (T - tm) - (d_h + d_a), d_h += K e, d_a += K e, tm' = tm + c (d_h + d_a).
- B5 NBA ldft (CBB G4): nba_games Model walk with each side's free throws over its own FT% to date (lkft shrink, as the
  shipped lwft) taken off the score in the OPPONENT'S defense rating only (offense raw), weight w: ld FT part
  (1 - w') with w' in {.5, 0}; live inputs refit walk-forward (luck_research.nba_design path, base = shipped params).
  Pick w' on tune margin MAE; judged on margin; totals reported (must not be worse held: d <= 0).
- B6 CBB early margin stretch: as B1, grid G {3, 6, 10}, c 1.00..1.30.
- B7 CBB early totals shrink: as B2, grid G {3, 6, 10}, s .50..1.00.

## Metrics (no driver test unless a consumer exists)
- M3 Stat+ in NBA: XPM+ = 100 + 25 x (rXPM - position mean) / position SD among qualified players (CBB rule).
  Ships as display only if computed from the board's own rows; stability = year-to-year r of XPM+ vs rXPM
  (players qualified both seasons) reported. Not a driver (NBA has no FV board; game model uses player values).

## Addendum (written after B1-B7 ran, before any model-to-model run): model-to-model cells
Harness: scripts/nba_proj3y_research.py load() rows (S 2012-23 with a 3-season target y3y, all from 2010-26 files),
season-end f = 1, base = shipped-family form F4 (design('F4')). Leave one season out, training seasons within 3 of
it dropped. Paired t on squared y3y error, players as units (tstat). Gate: t <= -2, Holm over MM1-MM3 at .05
(one-sided normal p from t), more seasons better than worse. Each input known at the end of season S.
- MM1 game model -> 3Y: team strength = his team's season-S mean game margin (scripts/nba_games_hist.json.gz,
  regular season; traded players: last team listed), added as one column.
- MM2 Stat+ -> 3Y: position-group intercepts (G = PG/SG, F = SF/PF, C) added (XPM+ is XPM shifted/scaled by position;
  in a linear form with proj already in, the intercepts carry it).
- MM3 CBB mates_war -> 3Y: teammates' minutes-weighted season-S XPM (same team listed, himself out), one column.
