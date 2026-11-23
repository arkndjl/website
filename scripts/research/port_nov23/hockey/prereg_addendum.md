# Addendum (model-to-model), written after C1-C7 ran, before M1-M2 ran

Same rows, splits and t as prereg.md "Totals rows" (ESPN-lined live history, tune 2021-23, held 2024-26, squared error,
walk_ols first 2021 trained on lined games). Ship rule: tune t <= -1.5 and held one-sided p past Holm over M1-M2.
M1 b2b (shipped win/margin term) into the totals model: b2bT = [home on 0 rest days] + [away on 0 rest days], added to TFEATS.
M2 rv (shipped win/margin lineup value) into the totals model: rvT = home lineup value + away lineup value (each team's
   lineup() vs the league's average lineup, as the walk computes rv; 0 before a team has played), added to TFEATS.
