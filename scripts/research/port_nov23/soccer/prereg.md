# Soccer port pass, Nov 23 2026: pre-registration

Written before any number for these cells was computed. Data: scripts/soccer_games_hist.json.gz rows + market, squad
value and injury terms (engine.load_rows of scripts/research/soccer_nov13), Understat line-ups and shots
(scripts/.cache/soccer/usm, the Oct 24 cache), Transfermarkt spells (tminj cache). LOCKBOX: every row dated
2026-07-01 or later is dropped before anything runs (2026-27 and calendar 2026 second halves); nothing reads them.

Harness: soccer_games.run / evaluate scoring (big five + UEFA cups, 90-minute 1X2 log loss, extra-time ties on their
90-minute result). Tune seasons S 2013-2022 (end-year labels), held S 2023-2026, one pass. Control = the live model
(soccer_games.params(), data/soccer_games_fit.json) with every shipped term. Treatment = control + one cell's term.
Per match d = treatment LL - control LL; t clustered by match day (soccer_games.cl_t); one-sided p from t (normal).

Tuning: each cell's grid is scored on tune only; the value with the lowest tune LL is taken; if no grid value beats the
control on tune (d < 0), the cell fails at tune and is never run on held. Held: one pass of the chosen value.
Family: Holm at alpha .05 over the cells taken to held (C1, C2, C3, C4, C6). Pass = Holm-significant d < 0 on held,
and the big five and UEFA parts not both worse. Ship only a pass (edit soccer_games, rerun --fit).

## Cells

C1 early-season spread stretch (G2, CFB weeks 1-3 x1.13). In a domestic league match where either club has played
fewer than 4 matches since its season began (Ratings.n), the half log-rate gap is multiplied by (1 + e).
Grid e: -.15, -.10, -.05, .05, .10, .15.

C2 returner (G11, NBA/CBB returners). A player whose injury or absence spell ended in the 21 days before match day,
after lasting 28+ days, adds his prior-season GAR a 90 (same value table and V0 as avz) x his usual minutes (mean of his
last 10 club appearances before the spell began, 3+ needed) / 90 to his club. rtz = (home - away) / 2, a term
rt x rtz added the way avz is (home log rate up, away down). Grid rt: .1, .2, .35, .5.

C3 charge until the club has played 3 matches without him (G13, CFB season-out charge). The avz rule with the fresh
21-day test replaced by: the spell is counted while the club has played fewer than 3 matches (any competition, from the
line-up sequence) since the spell began. Replaces avz; av picked on tune from .25, .35, .5.

C4 starting keeper out (G17, QB1 / NHL starter). A club's regular keeper = the GK with the most minutes in the club's
line-up window (the avz window: last 10 matches, 3+ healthy, 30-day stale cut) who started 6+ of them; out on match
day (the avz out rule, any spell age) -> gk = 1. The opponent's log scoring rate rises by kg (on top of avz).
Grid kg: .03, .06, .10, .15.

C6 game-control rating (G3, CFB/CBB). Control = mean over minutes 1-90 of the home side's expected points share
(win + draw/2) from the score at that minute (Understat shot list goals; matches whose shot goals don't equal the
final score are skipped) and Poisson goals for the minutes left at 1.35 a side a 90. Club rating c, carried across
seasons: after each scored match with control y, e = y - (.5 + c_h - c_a + hc), c_h += kc e, c_a -= kc e, hc += .002 e.
Term: home log rate + wc (c_h - c_a), away log rate - wc (c_h - c_a), when both clubs have 10+ control matches.
Grid: kc .02, .05 x wc .1, .2, .4.

## Marked without a test (reasons in results.json): G1 tested Oct 28 (spots_research), G4 xG blend = luck stripping
(wx tuned; npxG failed Oct 25), G5 market ratings are the base model (wm, wn 1), G6 pace Oct 29, G7 no attendance
cached, G8 league strength built in, G9 promoted clubs carry their tier-2 rating (prom tuned 0), G10 managers Oct 29 /
Nov 19, G12 XI value Oct 31, G14 totals ratings Nov 13, G15 r45 Nov 1, G16 no free public club rating, G18 needs
squad lists (dump), pre-lineup continuity failed Nov 2.

## Amendment 1 (model-to-model addendum, written before any cell ran)

Passed-elsewhere player metrics as the injured player's value in the game model's avz term (to model: game model;
from model: player boards). Point-in-time: the value is read from season S-1's file for a match in season S, as avz
does; neither metric is built from the game model's output or match results' 1X2.
C7 prior-season SV a 90 (soccer_sv, shipped Nov 23) in place of GAR a 90, same fringe shift, same V0.
C8 prior-season pg90 (predictive GAR a 90, Marcel, shipped Nov 14) in place of GAR a 90, same fringe shift, same V0.
Each replaces avz; av picked on tune from .25, .35, .5. Both join the Holm family.

## Amendment 2 (metrics)

M9 percentiles (display; its gates were in pctl.py's docstring before it ran, copied here after it ran): ships as display if every coverage gate holds (overall +-.03,
share +-.05, position +-.06, season +-.08) and split-half r of the bin quantiles >= .8.
M1 (written before it ran) age-adjusted rookie rate aGAR90 = GAR/90 - b (age - 21) (NBA aXPM): rookies = first season on the big-five GAR board
(2017-2024 seasons with 900+ minutes; files from 2015 so a first season is known for 2017 on). Target = GAR/90 over the
next two seasons (minutes-weighted, 900+ minutes). b fit leave one season out; gate: rank correlation (Spearman, each
season, mean) of aGAR90 with the target above raw GAR/90's, t <= -2 on squared error (players) of the linear fit on
aGAR90 vs on GAR/90, 2/3 of seasons. Pass = shown as a column on the soccer rookies board (one column).
