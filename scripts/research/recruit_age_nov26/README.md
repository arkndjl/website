# Recruit age for the class, Nov 26 2026: results

Pre-registration: prereg.md. Run: `python3 cbb_age.py`, `python3 cbb_path_age.py` (kit in /mnt/project-files/cbb),
`node on3_age_pull.mjs football 8 2011 ... 2019` then `python3 cfb_age.py <on3 json> <nflverse dir>` (players.csv),
`python3 pack.py` -> data/recruit_age_research.json (Process reads it).

## CBB (classes 2009-16 held out, n 1,997; forward 2017-18)
Age on Sep 1 of the class year, day-precise for 1,723: median 18.84, sd .55. NBA rate at about the same mean rank:
under 17.9 38%, 17.9-18.2 32%, 18.2-18.6 31%, 18.6-19.0 23%, 19.0+ 18%.
| test | log-loss gain | t | classes | forward t | verdict |
| --- | --- | --- | --- | --- | --- |
| shipped `old` vs rank alone | .0085 | 2.65 | 6/8 | 0.19 | in the model |
| age alone vs rank (day-precise rows) | .0111 | 3.21 | 7/8 | 0.91 | the signal is real |
| A1 swap `old` for continuous age | .0022 | 1.19 | 7/8 | 1.10 | FAIL |
| A2 add continuous age | .0020 | 1.20 | 7/8 | 1.13 | FAIL |
| A3 add young flag | .0007 | 0.84 | 6/8 | -1.12 | FAIL |
| A4 two hinges for `old` | .0020 | 1.00 | 7/8 | 1.22 | FAIL |
| B1 value part + age | .0004 | 0.52 | 5/8 | 0.80 | FAIL |
Known-only and day-precise-only rows: t 1.29-1.46. College path (C): continuous age loses to `old` in every part
(year-2 BPM swap t -9.2). Lead: A1/A2 are positive in 7 of 8 classes and on the forward classes; retest with the
2017-20 classes once their NBA windows close.

## CFB (On3 top 400 of 2011-19, n 3,599; 1,415 reached the NFL)
Birth dates are known for 100% of drafted recruits and 21% of the rest, so P(drafted) is untestable. Given an NFL
entry: top-64 pick rate 28% at 18.0-18.4 vs 20% at 19.2+ (younger group ranked lower as recruits). Held out by class:
draft slot t 1.75 (6/9), drafted t 1.15 (6/9), top-64 t 0.57. `old` flag on age-known rows t 0.18. FAIL, and On3
lists an age for 26 of the 2027 top 300 (41 of 2028), under the 50% coverage a pass needed.

## Shipped (data, not a model change)
- scripts/recruit_age.py: birth-date bounds from every daily On3 age reading (a birthday pins the date), FIBA roster
  dates, pins. Rows carry `age`, `ageRel`, `dob`.
- CBB `old` reads the bound (all readings so far, FIBA dates) instead of the day's whole-year age alone.
