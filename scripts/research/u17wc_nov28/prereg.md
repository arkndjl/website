# U17 World Cup event stats as a soccer prospect FV input (pre-registered Nov 28 2026, before any row is scored)

Data: the U17 World Cup 2026 file as saved after the final (player totals and minutes for every match). Nothing from it
is fit before the scoring date.

Input (one, fixed now): U17E = for each outfield player, the mean over his position template's stats (the file's own
templates and p90 / padj norms) of the z-score against players of the same template with 180+ minutes, shrunk by
minutes / (minutes + 270), times q(opponent) as in scripts/research/soccer_nt_nov23 (mean over his matches). Keepers out.

Rows: the prospect pool as rebuilt at the Jan 15 2027 snapshot (the first snapshot after the tournament), every U17
player joined through scripts/names.py with nation and birth date, the rest of the pool with U17E = 0 and a played flag.

Outcome: the board's FV outcome at the 2029-30 season, the same outcome window the Oct 24 harness uses (three seasons
after the snapshot); scored once, never refit after looking.

Gate: on top of the live board's kept inputs at that snapshot, U17E adds t >= 2 (players clustered, nation-out folds,
2/3 of folds won), top 50 by the new grade not lower in outcome, and the joined players' MSE not worse. A pass is then
refit through soccer_prospects.py --fit and must beat the live fit forward before it ships. A fail is recorded as it is.
