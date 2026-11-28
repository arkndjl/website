# Who wins the starting job (college depth charts), pre-registration, Nov 28 2026

Noah, Nov 28: order the depth charts by the chance of winning the starting job, not FV alone (FV can be an input). Test
transfer-in, incumbent, x/yNIL, age and class, last season's snaps, RB role, and each one by position (true freshmen at RB).

## Truth
- CFB: the next season's starters at each spot = the team's top N on PFN's impact rankings by use (QB pass attempts, RB
  carry share, WR, TE, CB and S targets, OL and front seven snaps). N: QB 1, RB 1, WR 3, TE 1, OL 5, DL (EDGE + DT) 4,
  LB 2, DB (CB + S) 4. Candidates = cfbfastR's roster that season at the spot (a player PFN lists takes PFN's spot).
  Not listed = not a starter. QB to LB: PFN 2019 on, so NIL-era origins 2021-24 (outcomes 2022-25). OL and DB: PFN
  2024 on, so one origin (2024 to 2025).
- CBB: the next season's starters = the team's top 5 in minute share (Barttorvik); candidates = everyone who played
  for the team that season. Origins 2021-22 to 2024-25 (outcomes to 2025-26). G / F / C from Barttorvik's guard and
  big flags.
- 2026-27 is the lockbox: never used.

## Base (what the depth chart does now: FV)
No point-in-time FV history exists for CFB, so the base is the value the history has: CFB 247 composite and last
season's PFN score (z in season and spot, 0 and a flag when unlisted); CBB last season's pXPM (freshmen: the recruit
rank line). Both as a z within the room, plus spot intercepts. Logistic regression, ridge .1.

## Drivers (each added to the base alone, then pooled, then by spot)
1. transfer-in (on another school's roster last season)
2. incumbent (a starter on this team last season)
3. class (Fr, So, Jr, Sr+), true freshman (first season), age (CBB only; CFB has none)
4. last season's use (share of the room's starter use; CFB snaps or attempts, CBB minute share)
5. role (last season's rank in his room; RB carry share is in 4 for RB)
6. x/yNIL: no point-in-time history; registered as a retest on the forward logs (On3 NIL snaps from Nov 28)

## Gate
Held-out log loss, leave one origin season out, against the base. Pass = t >= 2 (paired, summed by team) and better in
every fold but one. By spot: the driver x spot model against the pooled driver model, same gate; a spot's own sign is
reported either way. Top-N hit rate (true starters in the model's top N) reported, not gated. OL and DB: two-fold
team split inside the one origin, reported, gated the same way.

Ship: the passing drivers in one model; its P(start) orders the depth chart and shows on each chip. Failures go in
data/retests.json.
