# Draft pay vs college pay in Ret% (Nov 27 2026): set before running

Question (Noah): can the money a player would get by declaring predict who goes back to school?

Already known (scripts/return_drivers.py, Nov 26): `econ` = ln expected four-year rookie deal at the board slot minus
ln NIL (today's xNIL shape on rank) failed on top of the live models in both sports (CFB t +1.1, CBB board stage t -0.2).
That term is close to a function of board rank alone, so this pass changes what the money is, not the model:

1. `econ4`   yesterday's term, reproduced (four-year totals, today's NIL level), on yNIL (pay) instead of xNIL (worth)
2. `econ1`   ln expected first-year cash if he declares (signing bonus + year-one salary x roster odds; NBA year-one
             scale, second-round exception, two-way, undrafted) minus ln yNIL. Averaged over the pick spread (ln slot
             normal around the board rank, sd 1.28 CFB / .7 CBB), undrafted past the last pick.
3. `econ1p`  the same, point in time: pro pay scaled by that year's salary cap, college pay by the NIL market of
             the season he would return for (Opendorse totals: 2022-23 $1.14B, 2023-24 $1.17B, 2024-25 $2.26B,
             2025-26 $2.6B, 2026-27 $2.8B assumed)
4. `gap`     the dollar difference, asinh((first-year pro cash - college pay) / $0.25M), point in time
5. `pstay`   share of his pick outcomes where college pays more than first-year pro cash, point in time
6. `idx`     time only: ln(NIL market / salary cap) as the era term (CBB stage A: in place of the 2024+ step, and on
             top of it; CFB: in place of the 2024 flag, and on top)

Rows, NIL era only: CFB fall PFF boards of the 2022-25 drafts (Sr. and underclassmen; grads go), leave one draft
out, live = ln xPick + age + 2024 flag per class group. CBB stage B: No Ceilings midseason-ranked players 2022-26,
leave one draft out on top of the shipped stage A + board. CBB stage A (idx only): walk forward 2023-26.

Gate (as return_drivers.py): held-out paired t <= -2 against live, and wins 6 of 8 CFB draft x class cells, 4 of 5
CBB board drafts, 3 of 4 CBB stage A seasons. Six terms per sport: one pass at t -2 is expected by chance about one
time in four, so a pass must also hold in the other form of the same idea (econ1 with econ1p, gap with pstay).

Pay tables are approximate (2026 NFL slotting from OTC anchors and reported signing bonuses; 2026-27 NBA scale at
120%); the pay side moves only with the cap, so errors in level wash into the constant in the log forms.
Not tested: school-level budgets (data/nil_budgets.json is 2026 only, not point in time).
