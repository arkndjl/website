# FV pass, Nov 15 2026: results

Pre-registration: prereg.md (sha fb644611 at first write, 6a75feec after amendment 1). Scripts: repo
scripts/research/fv_nov15/. Holm family = every test scored. Lockbox 2026-27 not read.

| id | board | test | result | verdict |
|---|---|---|---|---|
| H1 | hockey draft | two-part grade, P(any NHL game) x mean given a game | class-out MSE 87.04 -> 87.21, t -0.79, 3/12; top 64 and forward worse | fail |
| H2 | hockey stage 4 | goalie save% over league (registered retest) | t 1.96, 9/12 (unchanged from Nov 11) | fail |
| H3 | hockey draft | Central Scouting midterm-to-final rise | t -1.92, 6/12, coef +.29 | fail |
| W1 | hockey draft | top-weighted least squares | top-64 MSE 112.33 -> 111.85, t 1.25, 8/12; all picks t -0.88; forward top 64 worse | fail |
| W2 | tennis ATP | top-weighted hurdle | 40+ rows MSE 180.0 -> 180.4, t -0.12 | fail |
| W3 | tennis WTA | top-weighted hurdle | 40+ rows MSE 244.1 -> 238.3, t 1.91, 12/19, p .036; all rows t -0.74 | fail (own gate and Holm) |
| C1 | CS2 prospects | teammates' mean rating | held MSE .8122 -> .8202, t +3.33 (by player +2.61), coef -.057 | fail |
| T1 | hockey stages 1-4 | .5 linear + .5 boosted trees on every stage input | family (mean stage gain by class) +1.26 MSE, t 4.34, p .0006, 11/12: passes Holm. Stage gates: k1 t 3.02 but forward top-64 MSE 106.2 -> 108.7; k2 t 3.16 but forward top-64 83.7 -> 84.9 and top-32 realized 46.96 -> 46.58; k3 t 1.72; k4 t 2.42 but forward MSE 34.63 -> 34.90. With the preseason share in the linear part the blend adds nothing at k2 and k4 (t .06, .04) | not shipped (no stage clears its own gate); lead |
| S1, S2 | soccer | keeper top slope / location (registered Nov 4) | see soccer.md if the rebuild finished | |

Checked, no test needed: CFB outcome horizon (fixed Nov 11, weights unchanged); CBB live level (265 summed NBA odds
on 5,554 players against ~226 on a training board after the Nov 9 floor fix).

Not run, each waits on its registered trigger: tennis year-end batch (recency h=4, gluck, gapmx, WTA age top slope,
ATP tree forward); hockey draft gbm (2020 class after 2026-27); CFB grade-to-outcome map, height at 1.5, TE line,
unit context, early flag (after the 2026 NFL season joins the outcome); soccer FotMob xG (3 seasons of rows only).

Reading: the two-part and top-weighted forms were the two structural ideas no earlier sweep had tried. Neither adds
anything, which says the linear grades are not losing the top of the board to the mass of low grades; what the hockey
tree stack found on Nov 9 is not the floor at 20 and not a top-of-board misfit.

T1 note: the tree gain is real class-out but sits in the body of the pipeline, does not hold forward at the top, and is
already carried by the preseason share where that exists. Same pattern as the soccer and ATP tree stacks on Nov 9.
Registered for the tree_stacks retest (2020 class after 2026-27) with the forward split moved to fit 2008-16, grade 2017-20.
