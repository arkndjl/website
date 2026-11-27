# DECT and its inputs in Transfer%, landing, Ret% and team builder: pre-registered tests (written Nov 27 2026, before any result)

Noah: "Can we use DECT to further inform team builder, transfer%, etc?"

DECT (scripts/dect.py, owned by its own thread, read here and not edited) prices three ways out of the stay-or-go
decision as certainty equivalents: declare, college (xNIL x the school's pay per market dollar) and transfer (xNIL).
Its inputs that a behaviour model does not already hold: the risk-adjusted edge of staying over declaring (`ce`), the
verdict (`lab`), the school's pay per market dollar (`k` = roster yNIL / roster xNIL) and the market's price over the
school's pay for one player (`zgap` = ln xNIL - ln yNIL, the transfer side less the college side).

Point in time. No NIL number is on file by season. As in the DECT history check and ret_pay_nov27, a past season's NIL
is today's shape (by board rank, position, level) scaled to that season's market (pay.py NILM), and for the roster
models xNIL / yNIL are rebuilt from that season's own stats with today's formula (value shares x the level's budget;
yNIL from the stats known going into the season). NIL era only: offseasons 2022 on (CBB), 2024-25 and 2025-26 (CFB).

Gate, every term, added alone on top of the live model: held-out paired log-loss gain with t >= 2 on the main fold
(clustered by team where rows share a team) and the second fold not against it (t > -1). Ret%: the return_drivers gate
(t <= -2 on loss and 4 of 5 drafts CBB, 6 of 8 cells CFB), and because a dollar term moves by year it also has to hold
walking forward (each draft from the drafts before it) and beside a 2024+ step, the two controls that undid the
ret_pay passes. A failure is a result. Nothing ships on one fold.

## Ret% (who goes back)
Base: CFB declare model (ln xPick, age z, era; class groups), 2022-25 fall boards. CBB board stage (stage A odds,
board, ranked flag), 2022-26.
- R1 `ce`: DECT's certainty-equivalent edge of staying, asinh($M / .25).
- R2 `ce_rel`: the same over the certainty equivalent of declaring (how big the edge is against what he gives up).
- R3 `college`: the verdict reads College (edge past one standard error).
- R4 `declare`: the verdict reads Declare.
ret_pay tested mean dollars and first-year cash. These are the risk-adjusted forms, which sorted returners inside rank
thirds (AUC .56 CFB, .74 CBB) where the mean did not.

## Transfer% (who moves)
CBB move model (scripts/cbb_market_fit.py), folds A fit 2022-24 score 2025->26 (main), B fit 2022-23 score 2024->25.
- T1 `zgap`: ln(xNIL / yNIL) for every player, rebuilt point in time (market price over school pay).
- T2 `k`: his school's ln(roster yNIL / roster xNIL).
- T3 `up_pay`: ln(his price at the next level up / his price at his own level), 0 for a high-major (DECT's transfer
  side where it differs from the college side).
- T4 `dect_ce` (board-ranked players, 0 and a flag otherwise): the staying edge, on the moved and gone branches.
CFB Transfer% (scripts/cfb_transfer_fit.py rows, 2024->25 and 2025->26, each scored from the other).
- T5 `dect_ce` and T6 `dect_college` for players on the fall PFF board (0 and a flag otherwise).
- T7 `up_pay`: a G5 or FCS player's price at the Power 4 rate over his own level's (level x production).
CFB has no team budgets or xNIL by season before 2026, so `zgap` and `k` are not testable there until a second
season of both is on file. Recorded as untestable, not failed.

## Landing (where a mover goes)
CBB landing model, same folds.
- L1 `dest_k`: the destination's budget over the market price of the roster it has coming back (money per market
  dollar free there), ln.
- L2 `pay_step`: ln(his price at the destination's level / his school's pay for him).
CFB landing: no dollars by season on file; untestable for the same reason.

## Team builder (next season's team)
- B1 CBB: next season's team rating from the builder's returning roster, each returner weighted by P(back) from the
  live models, against the same with the DECT-informed P(back) of any term that passes above. Scored on next season's
  actual rating, 2023-26. Runs only if a term passes.
- B2 both sports: the budget rule. The builder now caps spend at the reported school budget (data/nil_budgets.json)
  where the old one used roster yNIL + 4%. Budgets exist for one season, so this is a definition change, not a test.
