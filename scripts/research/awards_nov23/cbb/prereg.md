# CBB awards, Nov 23 2026: preregistration (written before any of these were run)

Engine and gate as scripts/awards_research.py (Wooden): winner-only rank-ordered logit (depth 1), L2 1, leave one
season out 2008-2026, one-sided paired t vs the null, Holm at .05 over CBB's whole list (Wooden's p in
data/awards_fit.json + the races below = 10), gain > 0 and most seasons won. Pools and features from the Barttorvik
research table (project files cbb/backtest/research_seasons.csv), min% >= 40 and 20+ games, as Wooden. Winners from
Wikipedia (each award's page, the men's table).

## New races

| key | award | seasons | pool | cols | null |
|---|---|---|---|---|---|
| naismith | Naismith POY | 2008-26 | all | bpm, ppg, wp, barthag, mpg, p5 (= Wooden's) | bpm |
| ap | AP POY | 2008-26 | all | as Wooden | bpm |
| dpoy | NABC Defensive POY (Naismith DPOY since 2018: same race; we use NABC's longer history) | 2008-26 | all | dbpm, blk, stl, drb, wp, barthag, mpg, p5 | dbpm |
| frosh | USBWA (Wayman Tisdale) Freshman of the Year | 2008-26 | class Fr | as Wooden | bpm |
| cousy | Bob Cousy (PG) | 2008-26 | role Pure PG / Scoring PG / Combo G | as Wooden | bpm |
| west | Jerry West (SG) | 2015-26 | Combo G / Wing G / Scoring PG | as Wooden | bpm |
| erving | Julius Erving (SF) | 2015-26 | Wing G / Wing F / Stretch 4 | as Wooden | bpm |
| malone | Karl Malone (PF) | 2015-26 | Wing F / Stretch 4 / PF/C | as Wooden | bpm |
| kareem | Kareem Abdul-Jabbar (C) | 2015-26 | PF/C / C | as Wooden | bpm |

Missing Barttorvik role: guard flag -> G roles, big flag -> PF/C, else Wing F. A winner outside the pool is reported.
NABC Freshman of the Year (2017-) and Naismith DPOY (2018-) are too short alone; their winners are compared with the
USBWA / NABC lists.

## Conviction (P(lead), this season's BPM only; DPOY on this season's DBPM)

Every race above gets a conviction view in its own eligible pool (class / role from this season's line).

## Driver tests (add-on to each race's own voter model; paired held-out t; Holm over every test below)

| driver | definition (point-in-time) | races |
|---|---|---|
| pre_fv | FV on the past board of the season before (static/data/cbb-past.json, top 300; 20 if not on it) | all 10 |
| ap_pre | his team's preseason AP rank (Sports-Reference polls page, "Pre" column): 26 - rank, 0 unranked | all 10 |
| bo | last season's held-out next-up BO% (the CBB breakout model's own leave-one-season-out prediction, replicated from scripts/cbb_breakout_research.py; 0 if not in its population) + flag bo_out | all 10 |
| hype | -ln rank on the newest No Ceilings composite dated before March 1 of the season (2022-26 only; -ln 75 if absent) | wooden only (5 seasons) |

Final pre-draft boards (ESPN, NBADraft.net) are dated after the vote, so not point-in-time for a college award: not used.

## Awards -> FV (CBB FV model, returners)

Candidate driver awd = ln of the held-out (leave-one-season-out) season-end P(Wooden) of the voter model for his last
season (no FV, no board input: bpm, ppg, wp, barthag, mpg, p5 only; clipped at ln 1e-4; ln 1e-4 if outside the pool).
Second candidate awd_any = ln of the sum of his held-out P over Wooden + his position award. Gate: the existing FV
driver gate (scripts/cbb_fv_sweep2/3: 2009-16 boards out of fold under the three fold rules, held 2017-19, forward
2020-23). Ship only on a pass.

## Amendment (before any model was fit; after the first pool check)

The first pool check (winners vs pools, no model run) left 9 position-award winners outside their role pool
(Barttorvik's role is a style, not the listed position; 2008-09 have no role at all). Changes: missing role from height
(<= 76 in -> Combo G, >= 81 in -> PF/C, else Wing F) when the guard / big flags are 0; pools widened to adjacent roles:
West + Wing F; Erving + Combo G; Malone + C. Jakob Poeltl / Pöltl added to data/name_aliases.json. Denzel Valentine
(Erving 2016, Pure PG) stays outside.
