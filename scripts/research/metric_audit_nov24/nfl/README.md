# NFL metric audit (Nov 24 2026)

Regular seasons 2018-25 (XV needs pfr_advstats), pairs 2018-19 ... 2024-25; 2016-17 only as pXP/60 history. No 2026 data.
Run: `python3 scripts/nfl_xv.py --prep`, `prep.py` (board replay, full + weeks 1-9, ~2 min), `sv_prep.py` (pbp), `audit.py`
-> `results.json`. Pre-registration: `prereg.md`. 90% intervals: resampled seasons / season pairs.

Describe = season values x season snaps -> season margin (net of offense and defense). Held out = weeks 1-9 values x
weeks 10+ snaps -> weeks 10+ margin, slope fit without the season. Predict team = season n rate x n+1 snaps -> n+1 margin.
Predict player = n rate vs n+1 rate of the same metric (n+1 exposure weighted, 40%+ snaps).

| metric | describe R2 (in-sample) | describe held-out | predict team R2 | predict player r | n pairs |
|---|---|---|---|---|---|
| WAR (board: .6 AV WAR + .4 XV + K/P/returns) | .961 (.951-.970) | .401 (.349-.470) | .282 (.226-.350) | .598 (.581-.616) | 7 |
| AV WAR | .986 (.979-.992) | .252 (.212-.315) | .282 (.220-.361) | .626 (.604-.645) | 7 |
| XV | .839 (.813-.865) | **.604 (.548-.657)** | .235 (.193-.288) | .443 (.412-.474) | 7 |
| AV (rebuilt PFR AV; PFR season AV is 403) | .973 (.936-.995) | .268 | .317 (.242-.404) | .590 | 7 |
| rXP/60 | .961 | .373 | .223 | .413 | 7 |
| pXP/60 | .793 | .303 | .258 (.208-.323) | .466 vs next rXP/60 | 7 |
| pXR/60 (C2, new: pXP/60 + position value) | .788 | .365 | **.340 (.275-.421)** | **.629 vs next WAR rate** | 7 |
| SV (QB, skill, defense; no OL/K/P) | .727 | .257 | .246 | .786 (own; .561 vs next WAR) | 7 |
| nflverse EPA (offense only) | .614 | .180 | .183 | .604 | 7 |
| nflverse CPOE (QBs only) | .304 | .067 | .034 | .328 | 7 |

Offense only (offense side -> points scored): board .946 / .411 / .251; XV .776 / .583 / .222; SV .800 / .265 / .262;
EPA .805 / .220 / .228; CPOE .379 / .101 / .085. Inside a tab (that family's rows only, held-out describe): QB XV .537,
board .508, SV .284, EPA .234, CPOE .101; skill XV .444, board .343, SV .073, EPA .065; defense XV .267, board .138, SV .045.
In-sample describe favours AV WAR because AV splits each team's points by construction (a ceiling, not a test).

Best descriptive: XV (held out .604, ahead of WAR .401 overall and in each family). Best predictive: pXR/60 at team level (.340; AV .317
overlaps its interval but is not our rate metric); at player level within a position pXP/60 stays best (.466 vs .369).

## Candidates (Holm over 4)
| candidate | target | before -> after | t | p Holm | seasons better | result |
|---|---|---|---|---|---|---|
| C1 pXP/60 + special teams | predict team held-out R2 | .248 -> .253 | -0.96 | .337 | 5/7 | fail |
| C2 pXR/60 (pXP/60 + sub-position value) | predict team held-out R2 | .248 -> .330 | -3.41 | .001 | 7/7 | PASS (player r vs next WAR .444 -> .629) |
| C3 XV fit per side (O on points scored, D on allowed) | describe held out | .604 -> .622 | -2.19 | .043 | 7/8 | PASS, flagged |
| C4 WAR with K/P/return credit vs without | describe held out | .401 -> .401 | +0.25 | .598 | 3/8 | fail (credit neither helps nor hurts) |

C3 flag: the XV fit's own missed-games test gets weaker (XV SSE drop 5,259 -> 4,463, t 4.96 -> 4.48; blend .4 4,808 -> 4,189),
while next-season team R2 (.235 -> .258), XV player r (.443 -> .462), contract rank (.42 -> .45) and WAR's predict team
(.282 -> .293) rise; WAR held-out describe .401 -> .394. Refit picked lambda 5 (CV tie with 20); alpha stays .4 (pinned).

Caveats: AV coefficients and the K/P/return shrink are fit on 2016-25 (structural, not refit per fold); pXP/60
hyper-parameters are fit leaving the target pair out, on board rows whose XV leaves only its own season out.
Not scored: 1Y/3Y projections (volume forecasts with their own held-out test, data/nfl_war_proj_fit.json); Stat+ (no NFL Stat+).
