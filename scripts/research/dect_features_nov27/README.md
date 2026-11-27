# DECT and its inputs as features (Nov 27 2026)

Noah: "Can we use DECT to further inform team builder, transfer%, etc?" Protocol and gate in `prereg.md`. Nothing shipped.

    python3 scripts/research/dect_features_nov27/hist.py       # DECT's own history rows (runs scripts/dect.py into a scratch file)
    python3 scripts/research/dect_features_nov27/ret.py        # Ret%       -> results_ret.json
    python3 scripts/research/dect_features_nov27/cbb_move.py   # CBB Transfer% and landing -> results_cbb_move.json
    python3 scripts/cfb_transfer_fit.py && python3 scripts/research/dect_features_nov27/cfb_move.py   # CFB Transfer% -> results_cfb_move.json

t below is held out; for Ret% a positive t means the term made log loss worse.

| model | term | main | second | result |
|---|---|---|---|---|
| CFB Ret% (626 board rows, 2022-25) | staying edge (CE) | t 2.96 worse, 2 of 8 cells | walk forward 1.55 worse | fail |
| CFB Ret% | edge over declare value | 2.73 worse | 1.54 worse | fail |
| CFB Ret% | College / Declare verdict | 1.00 / 0.63 worse | | fail |
| CBB Ret% (212 ranked, 2022-26) | staying edge | 0.72 worse, 2 of 5 | 0.15 worse | fail |
| CBB Ret% | edge over declare, verdicts | -0.04 to 0.92 | | fail |
| CBB Transfer% (fit 2022-24, score 2025-26) | DECT edge, ranked players | t 1.47 | 2024-25: 4.31 | fail on the main fold |
| CBB Transfer% | school pay per market dollar (k) | 1.61 | 2.96 | fail on the main fold |
| CBB Transfer% | market price over school pay (zgap) | 0.17 | 3.62 | fail |
| CBB Transfer% | price one level up | 1.07 | 2.85 | fail |
| CBB landing | destination k | 1.15 | 1.78 | fail |
| CFB Transfer% | DECT edge, College verdict | untestable | | the 2025 season has no fall PFF board (2026 draft: one board 3 days out) |

Notes
- Ret%: DECT's edge is mostly ln xPick and age, which the base already holds; what is left adds noise.
- The CBB pay terms all help on 2024-25 and not on 2025-26. School pay per market dollar and the DECT edge are the leads:
  retest after the 2026-27 cycle. Past pay is rebuilt from each season's lines with today's formula (no NIL by season on file).
- CFB: retest DECT in Transfer% after the 2026-27 cycle, with the November 2026 board as the fall board.
- The team builder shows DECT on returners and departures for reading only.
