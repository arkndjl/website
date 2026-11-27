# Coach loyalty in Transfer%, landing and recruit leans: pre-registered tests (written Nov 27 2026, before any result)

Noah: "Andrew Zock transferred from Mercer to Toledo with the coaching staff, so maybe he's less likely to leave them
going forward?" Base models, all live and NIL era only: CBB move + land (scripts/cbb_market_fit.py), CFB Transfer% +
landing (scripts/cfb_transfer_fit.py, cfb_landing_fit.py), recruit LIST model (scripts/recruit_commit_fit.py).

Coach history: CBB scripts/data/cbb_coaches.json (Sports Reference, every D-I school 2013-26). CFB
scripts/data/coach_alltime_src.json.gz (FBS head coach + OC + DC by season to 2025) and scripts/data/cfb_hc_start.json
(2026). A tie to a coach is only counted from seasons before the one being predicted.

Gate, every term, added alone on top of the live model: held-out paired log-loss gain with t >= 2 (clustered by team)
on the main fold, and the second fold not against it (t > -1). Holm across the terms of one model is reported.
CBB folds: A fit 2022-24 offseasons, score 2025->26 (main); B fit 2022-23, score 2024->25.
CFB folds: fit 2024->25, score 2025->26 (main); and back.
Recruits: walk-forward by class, NIL-era classes 2022-26 scored (each fit on earlier classes), t over recruits.
A failure is a result; nothing ships on a pass in one fold only.

## Stay / leave (Transfer%)
- T1 came_with: he transferred in and his head coach now was his head coach at the school he left (the Zock term).
- T2 yrs_hc: seasons he has played for this head coach, any school (cap 4).
- T3 inherited: he was at the school before this head coach arrived.
- T4 hc_ten: log(1 + head coach's seasons at the school) (staff continuity).
- T5 leave_x_tie: head coach leaves into next season x (came_with or recruited by him: not inherited). Live this is the
  vacancy odds x the tie, like the existing coach-change term.
- T6 (CFB) coord_new: a new coordinator on his side of the ball this season (FBS, where OC/DC are on file).

## Landing (where a mover goes)
- L1 follow_tie: his head coach took the job x the tie (came_with, or 2+ seasons under him). CBB inside the logit;
  CFB as the follow share among movers whose head coach took another job (share by tie, out of time both ways).
- L2 recruiter: the destination's next head coach is the one who first brought him to college (his first school's coach
  then), when not his coach this season (narrower than the Nov 14 reunion term, which failed at t 1.82 / 1.47).

## Recruit leans (LIST model)
Coach in place when the class signs: CFB class Y = head coach of season Y-1; CBB class Y = head coach of season Y
(the Y-1/Y season). Both are known through the recruit's senior fall.
- R1 newhc: that coach is in his first season at the school.
- R2 hc_ten: log(1 + his seasons at the school).
- R3 hc_from_list: that coach was, the season before, the head coach (CFB: or OC/DC) at another school on the
  recruit's list (the recruit can follow him).
- R4 late change (reported, gated the same): the school changes head coach after that season (the coach who recruited
  him is gone by the time he enrolls). Live only for classes whose carousel has run.
