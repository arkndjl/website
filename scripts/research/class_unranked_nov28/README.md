# Unranked commits in the class score (Nov 28 2026)

Noah: count the commits nobody ranks in the class rankings, 1 star at the lowest, or a 0.5-star tier if that does
better. Prereg in prereg.md. `python3 test.py` (and `--explore`) -> result.json. Needs the nflverse draft picks and
players in scripts/.cache/statplus.

CFB, classes 2011-20, 2,267 draft picks, one row a program and class (FBS and FCS), classes held out one at a time:

| Form | Held-out change in squared error | t (by program) | Classes better | Forward 2018-20 |
|---|---|---|---|---|
| ESPN-listed commits only (today) | | | | |
| + every other commit at his index points (1 star at the lowest) | -.0168 | -2.05 | 2 of 10 | -.0145 (t -1.28) |
| + a separate fitted value for the commits no service rates (0.5-star tier) | -.0164 | -2.01 | 2 of 10 | -.0144 (t -1.27) |
| (not preregistered) the off-board points as their own term | +.0007 | 0.16 | 6 of 10 | |

The 0.5-star tier's fitted value is 0 points. With the listed points held fixed, more off-board commits go with fewer
picks at P4 and G5 (-.020 and -.026 a point; walk-on heavy programs) and with more at FCS (+.042), and none of it
helps held out. **Nothing passes: the class score keeps the board's commits only.** The other commits still show:
they count in the commits and the star buckets at their HS ARK stars (1 at the lowest) and xFV 20, the board's floor,
so they add no points (scripts/class_offboard.py, everyClass in scripts/cfb_recruit.mjs, class_ranks in
scripts/cbb_recruit_fit.py).

CBB: On3's basketball team lists start with the 2024 class in the pack, so no class has an outcome yet; the same rule
applies. Retest when the 2024-25 classes have drafts or three college seasons.
