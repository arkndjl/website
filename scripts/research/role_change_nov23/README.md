# Role-change check (Nov 23 2026, Noah: Trevin Jirak)

Question: does FV penalize players whose early minutes/snaps were low but who now hold full-time roles?

## Trevin Jirak (Iowa So C), Nov 22 board
- Preseason E[FV] 20.6, P(NBA) 5% (2025-26: 17 gp, 8.0 mpg, BPM -1.7).
- This season (5 gp, 105 min, BPM 18.5) graded as if it were his whole season: E 40.4, P(NBA) 92%.
- Returner weight w = 105 / (105 + 156) = 0.40 -> blend 28.6 -> FV 29. Same weight at the 50/50 point (156 min) ~ 7-8 more games.
- Biggest "now" drivers: PORPAG +5.1, D-BPM +4.1, 3-season BPM +4.1, BPM +3.6, BPM trend -2.3 (the model's regression on a big year-over-year jump), Stat+ +2.2.

## CBB in-season blend (build.py, test.py, bias.py, resid.py)
2010-26 Barttorvik game logs, 81,187 player seasons, 698,001 checkpoints (same as cbb_live_backtest.py). Target = season-end grade, one season held out; realized NBA FV (2010-19) as second check.
- Risers (returners, 20+ mpg, mpg 1.5x+ last season) on the board's top 300 that day: blend minus season-end grade +0.39 (Nov 20), +0.29 (Dec 1), +0.23 (Dec 15). Already slightly HIGH; k 90 -> +1.36, k 60 -> +2.09. The "now" grade alone runs +4.8.
- Thin prior (<250 min last season, 20+ mpg): top 300 +0.78 at Nov 20. No underrating.
- A k by last-season minutes, k = kmax (m + 60)/(m + c): every fold picks kmax 156, flat (no change).
- B k by mpg ratio, k0 / rho^g: every fold picks g = 0 (no change).
- C "role run" now-grade (trailing games in the current role when earlier games were a smaller role): MSE .318 -> .333, t +13.6, 0/17 seasons. FAIL. Newcomers: t +16.9, 0/17. FAIL.
- C2 mix of role-run and to-date grade: every fold picks q = 0 (no change).
- Realized NBA FV minus season-end grade, 2010-19 returners: log mpg growth -0.09 (t -1.7); grade 30+ risers +7.6 vs non-risers +6.4 (the known top-end gap the end map handles), difference inside noise; thin prior at grade 30+ -9.2 (t -2.6, i.e. if anything overrated).

## CFB production term (cfb_role.mjs)
PFN last seasons 2019-22 vs NFL weighted AV (cfb_statplus_backtest.mjs universe, 3,210 players). Variant: when the last season's snaps are 1.5x+ the earlier seasons' mean (175 players), earlier seasons' weights x d (d by fold: .25/.25/.5/.1). MSE 1.6467 -> 1.6462, t -0.32, 2/4 seasons. FAIL. Grower residual +0.025 +- 0.094 AV/season (no penalty).

## Other boards
Pro boards carry no FV. Hockey prospects weight the season by GP (not TOI), soccer prospects by minutes on per-90 rates: neither dilutes a rate by early low-minute games beyond the sample itself. Not retested.

Nothing shipped.
