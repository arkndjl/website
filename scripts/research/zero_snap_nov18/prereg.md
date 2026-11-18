# Zero-snap / provisional priors in the other sports (pre-registered Nov 18 2026, before any outcome is read)

Follow-up to PR #1063 (CFB ESPN backups graded by a ridge copy of the board on rows that only lacked a snap count).
Question per sport: is the no-playing-time or provisional grade fit on missing-data rows, on tiny or one-position
cells, or well above what similar prospects reached?

## Tennis (the one board where the cell could not be read off the shipped fit)
Provisional = unranked at the snapshot. The hurdle model grades them with the `unr` flag plus the same linear Elo
term as ranked players. Cells that could be thin: unranked with a high carried Elo (inactive, ranking lapsed), and
unranked with no match in the last 12 months.

Data: scripts/tennis_prospects.py rows (births 1979-97, the fit's cohorts), October snapshot, shipped `kept` inputs.
A (current): leave-one-birth-year-out mean FV (loso), per tour.
Cells: (1) unranked; (2) unranked, Elo >= 1700; (3) unranked, n = 0 (no match in the window); (4) ranked (control).
Bug if in a cell with n >= 100: mean(pred) - mean(real) > 1.0 FV and the per-birth-year paired t >= 2.
B (candidate, only if a cell fails): add `unr x elo` and an idle flag (unranked, n = 0) to the kept inputs.
Ships if B cuts leave-one-birth-year-out MSE with t >= 2, wins two thirds of the birth years and does not raise the
forward test's error (the script's own gate).

## CS2
A missing birth date is scored as age 22 (train and serve). B: a missing-age flag. Walk-forward as prospect_fit
(tune cutoffs before 2025-07-01, scored on held). Ships if held t <= -2.
