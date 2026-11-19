# CBB recruit consensus: source-accuracy weights (Nov 19 2026, prereg)

Question (Noah): weight the consensus for CBB recruits by how accurate each source (ESPN, 247, On3) has been,
instead of equal weight.

Data: scripts/data/cbb_recruit_hist.json.gz, each recruit's service ranks (`svc`: 247, ESPN, On3; Rivals is in
the history for 9 rows only, so it is out). On3 ranks exist from the 2021 class on.

Composite: weighted mean of -ln(rank) over the services that ranked the class. A service that published the class
but left the player off gets -ln(1.25 x its deepest rank that class) (same rule for every weighting).
Equal weight = 1 / number of services that ranked the class. Reference: On3's industry rank (`rk`).

Outcomes, both scored as within-class Spearman with the composite:
- NBA: realized FV (`rfv`, the board's role tier), classes 2009-2018 (2019+ careers too young).
- College: best of the first two D-I seasons' value, min% x (BPM + 3)+ (0 if no D-I season; 2025 class has year 1 only).

Fit: walk-forward. For test class c, grid the weight simplex (step .05) for the best pooled Spearman on all earlier
classes of the same era, then shrink toward equal: w = eq + T / (T + 4) x (w_fit - eq), T = training classes.
Eras: 2009-2020 (247, ESPN), 2021-2025 (247, ESPN, On3). At least 2 training classes, so tests:
NBA 2011-18 (8), college 2011-20 (10) and 2023-25 (3).

Pass: paired t >= 2 of (weighted - equal) Spearman across test classes, weighted better in 2/3+ of classes, on the
NBA outcome (main) and not worse on college. Also reported: unshrunk weights, year-to-year stability of each class's
own best weight (does a track record repeat?).

## Results (`python3 scripts/research/cbb_source_weights_nov19/test.py`, results.json): FAILED, equal weight stays

| test | classes | equal | weighted (shrunk k 4) | t | wins | unshrunk t |
|---|---|---|---|---|---|---|
| NBA realized FV | 2011-18 | .4588 | .4567 | -1.59 | 2/8 | -0.53 |
| college value, 247+ESPN | 2011-20 | .4180 | .4183 | 0.31 | 4/10 | 0.14 |
| college value, 247+ESPN+On3 | 2023-25 | .4554 | .4553 | -0.30 | 1/3 | -0.89 |

- Track records don't repeat: each class's own best ESPN share (vs 247) has lag-1 r -.34 (NBA) and .05 (college);
  the 2021-25 own-best weights jump between sources (2021 ESPN .90, 2024 247 1.00, 2025 On3 .55).
- Walk-forward weights leaned ESPN (.52-.83 on NBA) and never beat equal.
- Reference: On3's industry rank (what the site uses) beats our equal composite on NBA (t 3.5, 7/8) and college
  2011-20 (t 1.98, 7/10); on 2023-25 college it trails (n 3, college only), not tested further.
- Nothing ships; the recruit model keeps On3's industry rank. Retest after the 2027-28 classes add On3-era outcomes.
