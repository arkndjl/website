# Class score: top end vs depth against winning (Nov 26 2026)

Noah: can the class score capture top-end talent and depth better, and how does each correlate with winning?
Prereg in prereg.md (three rounds, each written before its numbers). Result: **the plain sum stays in both sports.**

Run order: `cfb_build.py`, `cbb_build.py` (panels into scripts/.cache/classscore; cfb needs the cfbfastR schedule
csvs 2005-26 in scripts/.cache/classscore/sched), `tests.py cfb|cbb [r2]`, `sens.py`, `stock.py`, `concave.py`,
`pack.py` (data/class_score_research.json for the Process term, research/studies/cfb/cfb-class-top-end-depth.json).

| | CFB | CBB |
|---|---|---|
| Round 1 (two prior ratings + three prior classes) | no pass, decay t 2.22 (7/11) | all five pass, but a bare "has a ranked commit" flag beats them all: controls short |
| Round 2 (+ baseline, level) | none, best t 0.03; top 5 .0029, depth .0054 a point (t -0.46) | power x decay .33/.6 t 2.52 (9/12); depth -.0084 a point |
| Roster controls, first season | top -.0002, depth .0069; nothing passes | top .0071, depth .0049 (t .51); every discount loses (t -1.0 to -2.5) |
| Round 3, four classes on the roster | sum over none t 3.49 (13/13); top .0044, depth .0027 (t .70); nothing passes | forms pass (t 2.5 to 4.8) but rating bends with the total (t 4.40) and the roster check above reverses them |
| Position mix (QB, line points) | t -3.09 | |

Read: point for point, top end and depth are worth the same. CBB's negative depth weight is roster turnover (a deep
freshman class follows a thin returning roster), not class structure; with returning and transfer value held fixed it
is positive. Later seasons' returning value includes the class itself, so the roster check uses the first season only.

Lead (ledger retests_2027.json `class_score_top_end`): NIL-era CFB seasons, top 5 .0069 vs depth .0006 a point
(t 1.49, n 511); with first-season roster controls, classes 2021-24: .0156 vs -.0026 (t 1.89). CBB NIL era points the
other way (depth .0165, t -1.65). Retest after the 2027 season.

## Round 4 (second pass, same day)

| Idea | CFB | CBB |
|---|---|---|
| Value basis (roster design) | FV if on t 0.09, year-3 xFV t -1.06, blends t -0.3 / -0.1 | headline FV t 1.28, Y1 FV t -0.48, blends t 0.8 / -0.1 |
| Sum x program development | t -1.91 | t 0.77 |
| Early / late commit points | t -1.20 | t -0.40 |
| Sum x enrol rate | no enrolment history | t 0.79 |
| Class + incoming transfers, first season | t 0.73 (6/10) | **t 6.45 (12/13)**, NIL era t 4.76 |

Only the CBB net class passes. One unit of transfer value (cbb_team_prior `tr`) = .050 rating SD against .0064 for a
class point, so 7.8 class points; per SD transfers .17, class .08. It is a net-class column, not a change to the
high school score, and next season's transfers do not exist until the portal opens (spring), so nothing is on the
board yet. Not testable on stored history: positional need vs the returning roster, decommit risk, per-recruit
Transfer% / Ret%.

No analogue: no other sport on the site has a class score.
