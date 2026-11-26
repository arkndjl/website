# Class score: top end vs depth against winning (Nov 26 2026)

Written before any outcome was joined to a class.

**Question.** The class score is the sum of every commit's FV points (CFB xFV - 20; CBB E[share] points). PR #1242 split it
into a top end (best 5 CFB, best 2 CBB) and depth (the rest), untested. Does a different weighting of top end and depth
predict the program's results better than the plain sum?

**Rows.** One per program and class. CFB: FBS programs, classes 2012-22 (CFBD composite history from 2009, so the three classes before are known). CBB: D-I programs,
classes 2012-23. A program with no ranked commit has a class of zero.

**Player points in history.** The live model's points mapped from what history has: CFB composite rating by program
level (binned live-class means, interpolated); CBB consensus rank (live classes, interpolated). The map is checked at
the class level against the live class scores before any outcome is read.

**Outcome.** Mean season rating z over the three seasons after signing in which the class plays as non-freshmen in CFB
(seasons C+1..C+3) and its first three seasons in CBB (C+1..C+3, C+1 = freshman season). CFB rating = opponent-adjusted
capped margin (ridge, FBS; the game model's family, since ARK Ranking has no stored history). CBB rating = the
recruit history's program rating. Secondary: win %, final Elo (CFB), each single season, NIL-era classes (2021+).

**Controls (known at signing).** The program's rating in the two seasons before; the plain class scores of the three
classes before. Sensitivity (not point-in-time): outcome-season returning production and incoming transfers
(CFB 2016+ offRet/qbRet/offIn; CBB 2014+ ret/tr), all classes and NIL era.

**Base.** Controls + plain class score.

**Family (each replaces the plain score; its parameter is picked inside the training classes only).**
1. split: top-k points and the rest, free weights. k in CFB {3, 5, 8, 10}, CBB {1, 2, 3}.
2. decay: sum of d^(i-1) x points by rank in class. d in {.80, .85, .90, .95, .975}.
3. cap: the best N commits only. N in CFB {10, 15, 20, 25}, CBB {2, 3, 4, 5}.
4. star premium: sum of points^p. p in {.5, .75, 1.25, 1.5, 2}.
5. average + size: mean points and ln(1 + commits).
6. CFB position mix: plain score + QB points + line (OL, DL, EDGE) points (ESPN positions joined by name, 2012+).

**Test.** Leave one class out. d = base squared error - form squared error per row; t clustered by program; classes
improved. Pass = Holm at .05 one-sided within the sport's family and at least two thirds of classes improved. Forward
check: fit on classes through 2016, score 2017 on. Ship the best passing form as the class score; if none passes the
plain sum stays and top end / depth stay descriptive. Weights reported either way.

**Analogue.** No other sport on the site has a class score (hockey, soccer, tennis and CS2 prospects sign one at a
time), so there is nothing to port; the passing form is tried on both college sports.

## Round 2 (written after round 1, before any round 2 number)

Round 1's check on its own controls failed: in CBB a bare "has a ranked commit" flag beats every form (held-out RMSE
.4747 against .4883 for the plain score), and in CFB a count of commits rated .85+ does the same. Both stand in for
program level, which two seasons of rating do not carry, so round 1's CBB passes are not read as class structure.

**Controls added.** Program baseline: mean rating z of the three seasons before the two already in. CFB: power-conference
flag in the signing season. CBB: rows are programs with at least one ranked commit in the class (the only programs
the class table lists).

**Family.** Round 1's five forms, the same grids, plus one: power x decay, sum of d^(i-1) x points^p with
p in {.33, .5, .75, 1} and d in {.6, .7, .8, .9, 1}, picked inside the training classes. The grid edges were seen on
round 1's rows, so the forward check (fit through 2016, score 2017 on) must also be positive for a pass.

**Pass.** As round 1 (Holm within the sport's six, two thirds of classes), and forward d > 0.

## Round 3: roster stock (written after round 2, before any round 3 number)

One class adds little once the three classes before it are in the controls (plain score against no class score:
CFB t 1.3, CBB t 1.1), so the per-point weights of top end and depth are loose. Same question on the whole roster's
recruiting: rows are program-seasons, the four classes on the roster (CFB classes s-3..s, CBB s-4..s-1) each scored
by the form and summed. Controls are only what was known before the oldest of the four signed: rating z of the two
seasons before, the three-season baseline before those, the CFB power flag. Outcome = that season's rating z
(secondary: win %). Seasons CFB 2013-25, CBB 2016-26; CBB rows need a ranked commit in the four classes.

Forms: split (same k grid), decay, cap, star premium, power x decay, same grids, picked inside training seasons.
Held out by season; t clustered by program; Holm within the sport's five; two thirds of seasons; forward (fit through
2019, score 2020 on) positive. A form ships only if it passes here and is not reversed by the roster-control check
(round 2's CBB pass was: with returning and transfer value in, depth turns positive and the form loses).

## Round 4: other ways to improve the score (written Nov 26 after rounds 1-3, before any round 4 number)

Noah asked for a second pass. Each idea is scored against the plain sum, held out, t clustered by program, Holm at
.05 within the sport's round 4 family, two thirds of folds. Controls as round 2. A CBB pass must also hold with
returning and transfer value in (first season), since round 2's pass did not.

1. **Value basis.** Each commit's points from another live grade, mapped to history the same way: CFB FV if on the
   board - 20 and year-3 xFV - 20 (the score now uses year-1 xFV); CBB headline FV - 20 and Y1 FV - 20 (the score
   now uses expected FV points). Each replaces the sum; also a blend (both columns, free weights). Scored on the
   roster design (round 3) and one class at a time; the roster design decides.
2. **Development.** Sum + sum x the program's development, where development = its mean rating residual on its
   four-class recruiting stock over the three seasons before signing. Development's own term is in the base.
3. **Timing.** Points split by commit date, before Aug 1 ahead of the senior season and after (undated apart), free
   weights. CFB dates from the On3 history (2012+), CBB from the recruit history.
4. **Attrition (CBB).** Sum + sum x the program's enrol rate over the three classes before (ranked commits who
   played for the school they signed with, shrunk to the mean with k = 5). CFB history has no enrolment.
5. **Portal net class.** First season after signing, returning value in the base: does adding incoming transfer
   value (CBB transfer value 2014+, CFB incoming transfer production 2016+) to the class beat the class alone, and
   at what exchange rate. A pass here means a net-class column, not a change to the high school class score.

Not testable on stored history, stated rather than guessed: positional need against the returning roster (the CFB
past boards cover 2024-25, the CBB past boards 300 players a season), decommit risk (the histories hold final
signees; decommitments are logged only from Nov 2026), per-recruit Transfer% and Ret% (fit on college players).
