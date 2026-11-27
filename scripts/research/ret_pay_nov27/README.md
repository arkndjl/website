# Draft pay vs college pay in Ret% (Nov 27 2026)

Noah: can the money a player would get by declaring predict who goes back to school? Protocol and gate in `prereg.md`,
run with `python3 scripts/research/ret_pay_nov27/pay.py` (needs the CBB kit and boards), numbers in `data/return_pay.json`.

Nothing shipped.

| sport | term | on top of live | result |
|---|---|---|---|
| CFB (2022-25 fall boards, 479 rows, 78 returned) | four-year deal / NIL, log ratio | t 1.3, 5/8 | fail |
| CFB | first-year cash / NIL | t 1.3, 5/8 | fail |
| CFB | the same, point in time | t 1.9, 5/8 | fail |
| CFB | dollar gap | t 2.1, 4/8 | fail |
| CFB | share of pick outcomes where college pays more | t 1.9, 5/8 | fail |
| CFB | NIL market / cap, time only | t 5.5, 2/8 | fail |
| CBB board stage (212 ranked, 72 returned, 2022-26) | first-year cash / NIL, today's level | t -1.1, 3/5 | fail |
| CBB | the same, point in time | t -2.5, 5/5 | passes leave-one-draft-out |
| CBB | dollar gap | t -3.2, 5/5 | passes leave-one-draft-out |
| CBB | college pays more share | t -2.6, 5/5 | passes leave-one-draft-out |
| CBB stage A | NIL market / cap in place of the 2024+ step | t 4.7, 1/4 | fail |

Why the CBB passes did not ship (controls added after the first run, not in the prereg):
- The three passing terms differ from the failing one only by a year scale, and leave-one-draft-out lets a term that
  moves by year learn from later drafts. Beside a 2024+ step in the board stage they add nothing (t -0.4 to -0.6, 2/5).
- Walking forward (each draft from the drafts before it, 2023-26): gap t -1.9, log ratio t -1.7, share t -0.9; under
  other NIL market paths for 2025-26 and 2026-27 the gap runs t -1.4 to -2.1. Under the gate.
- Within a year the terms carry rank plus the QB, Power 4 and high-major gaps in NIL, which had already failed on
  their own (return_drivers.py).

What the year level is: board-ranked 31-60 left at 62% in 2022-23 (n 47) and 22% in 2025-26 (n 37); 15-30 went 80% to
61%; the lottery did not move. The held-out model says 45% and 82% for the last two drafts, so Ret% is low for
second-round and late-first names. A plain 2024+ step in the board stage fixes about half of it walking forward
(t -4.0) but wins only 3/5 leaving one draft out (it is a 2025 break, not 2024), so it is under the gate too.

Retest after the 2027 draft (a sixth board year), and with a men's basketball roster-budget series by year in place
of Opendorse's all-sport market if one can be sourced.

Cross-sport: no analogue. Hockey prospects have no stay-or-sign model on the site and entry-level deals are capped
flat, so pay does not vary by slot. Soccer has no draft.
