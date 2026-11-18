# ESPN roster backups graded on NFL outcomes (pre-registered Nov 18 2026, before any outcome is read)

Question: the ESPN roster backups (scripts/cfb_espn_backups.mjs, the board's zero/low-snap players) are graded by a ridge
fit that copies the board's own grade on rows that merely lack a snap count (1 QB in 1,723 rows). Does a fit on what
recruits actually became in the NFL grade them better?

Data: the 2011-19 ESPN signees of scripts/cfb_recruit_retarget.py dataset() (same NFL link, horizon and AV map; outcome
`rfv` = realized FV, floor 20). No 2026-27 data is read ([[lockbox-2026-27]]).

A (current): the shipped backup formula, as a freshman (years 1, age for class 0), its ridge fit on today's board,
then the board's mean-outcome step (fv_dist atMean with cfbZ). Fit on today's board, so it never saw these outcomes.

B (candidate): hurdle P(drafted) x FV(drafted) + (1 - P) x 20 on the drivers a backup has: position group, height and
weight z within position, BMI z, 247 composite ((c - .85) x 10), has-composite flag, 6 - ln(composite rank), FCS,
G5. Logit + ridge (lambda as the retarget fit). Leave one class out (9 folds).

Primary test: per-class paired MSE of headline mean vs rfv, B against A. Ships if mean per-class gain t >= 2 and
B wins >= 6 of 9 classes. Secondary (reported, not gates): calibration by composite rank band (1-6, 7-41, 42-143,
144-400, 401+, unrated) and by position; QB rows alone.

Not testable here: years in college without playing (the signee data has no participation). Upperclass backups keep
the shipped class/age step on top of B; this is stated as untested.
