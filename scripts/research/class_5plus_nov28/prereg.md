# Class score: a 5-star+ weight (Nov 28 2026)

Written before any number below was run.

**Question.** Noah: 5-star+ recruits should count much more in the class score than their FV points do. Does a weight
on 5-star+ commits beyond their points predict the program's results better than the plain sum (Nov 26 study,
scripts/research/class_score_nov26)? The Nov 26 star premium (sum of points^p) failed; that bends every commit's
points, this one tests the 5-star+ tier alone.

**5-star+ in history.** The live tier is an ARK 5-star with better than even odds of a top-64 pick (CFB, PR #1225;
4 in the 2027 class, all top 4 by composite) and ARK 5-star+ in CBB (about the top 5 of a class). History has no ARK
stars, so 5-star+ = the top K commits of the class by CFBD composite rating (CFB) or consensus rank (CBB).
K is picked inside the training folds from CFB {2, 4, 6, 8, 12}, CBB {2, 3, 5, 8}; the live counts are 4 and 5.

**Forms (each replaces the plain sum).**
1. multiplier: points of 5-star+ commits and points of the rest as two free weights (m = their ratio).
2. count bonus: plain sum + the number of 5-star+ commits.

**Designs.** Primary: round 3's roster stock (four classes on the roster, season rating z; CFB seasons 2013-25, CBB
2016-26), held out by season, controls known before the oldest class signed. Secondary: round 2's one-class rows
(three-season outcome), and the CBB first-season check with returning and transfer value in (round 2's CBB pass was
reversed there). NIL era (seasons 2022+) and win % reported.

**Pass.** Holm at .05 one-sided within the sport's two forms on the primary design, at least two thirds of seasons
improved, forward check (fit through 2019, score 2020 on) positive, and in CBB not reversed by the first-season
roster check. A pass ships m into the class score, ranks and GFX. A fail leaves the plain sum and reports the fitted
m and where the 2027 classes would rank under it.

**Analogue.** No other sport on the site has a class score; both college sports are tested.
