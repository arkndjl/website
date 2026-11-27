# Soccer context audit, Nov 27 2026: pre-registration

Written before any of these tests was scored. LOCKBOX: 2026-27 (season file 2027.json, matches from 2026-07-01) is never
read for a fit choice or a test. Data: static/data/soccer-war/2015..2026.json as committed (GAR on the Nov 27 line,
SV / SVAR, pg90 = p/90 after the Nov 24 swap, all written from that season and earlier), the Oct 24 Understat cache
(scripts/.cache/soccer us/ usm/), the Transfermarkt spell cache (tminj). Holm at .05 over T1, T2a, T2b, T3, T4 (the
predictive swaps); T6 is a rule fix with its own not-worse gate.

Not a test (housekeeping, shipped whatever it shows unless the fit's own gate fails): soccer_proj_research.py --snaps
and the fit rerun on the Nov 27 replacement line, so pj / p3 are trained on the GAR the board serves.

## T1 backup watch grade (predictive): GAR this season + .5 last, shrunk K 900 -> p/90
Harness: scripts/backup_age_fit.py soccer set-up (shapes GK1 D4 M4 F2, 270+ minutes, strings 2-3). Pair universe fixed
by the control and NOT filtered on either grade's sign: every backup with the lowest-control-grade starter at his spot.
Target (the harness's own): the pair's gap over the next two seasons in GAR a 90 (minutes-weighted, K 900 to 0; a
missing player = 0). Predictors: A = gap in the control grade; B = gap in pg90 of season y (file value, point in time).
Model target = a + b gap + c age gap, walk-forward as fit() (train = pairs whose target was complete). Paired squared
error over pairs, t; seasons with lower MSE k/n. Guard: the same with the target in SV a 90 (sv, same weighting).
Pass: t <= -2 on the own target, more than half the seasons, guard not worse (guard t < +2 and guard MSE not higher).

## T2 1Y / 3Y projection inputs (predictive): prior seasons from GAR -> SV
Harness: scripts/soccer_proj_research.py (LOSO by season, players as units, own target = GAR next season / next three).
Control = the live form (agepos) refit on the Nov 27 line. PS1 = SVAR of S-1 and S-2 pooled per 90, shrunk to 0 with
900 minutes, x M0 / 90 (the SV twin of P1; whole past seasons, so point in time at every share f).
T2a: control + PS1. T2b: control with P1 replaced by PS1.
Pass (each): 1Y paired t <= -2 at every f (.25 .5 .75 1) with most seasons won, held slope .8-1.2; guard = 3Y RMSE not
higher at any f. The season-so-far input stays GAR (snapshots carry no partial-season SV; that is a lead, not a test).

## T3 game model injury term (predictive): prior-season GAR a 90 -> p/90 (retest)
Failed Nov 23 as C8 with the OLD pg90 (Marcel on GAR). Condition changed: pg90 was rebuilt Nov 24 (SV 3 seasons + age).
Same harness and rule as scripts/research/port_nov23/soccer/prereg.md C8: grid av .25 .35 .5 on tune 2013-2022; if no
grid value has d < 0 on tune the cell fails and held is never run; else one held pass 2023-2026 (rows before
2026-07-01), pass = d < 0 with t <= -2 clustered by match day and big five / UEFA not both worse.

## T4 next up breakout odds (predictive): add p/90
Harness: scripts/soccer_breakout_research.py breakout() (LOSO logistic, log loss, L.compare). Candidate block
'p/90' = [pg90 of the base season - s0] where s0 is the base's shrunk GAR a 90 (stints: minutes-weighted pg90).
Scored (a) added to the base, (b) added to the base + the kept blocks. Pass: (b) t >= 2 and 7+/11 seasons; (a) is reported.

## T6 award voter models (descriptive number in a fitted model): GAR -> SVAR
GAR's plus-minus term spans three seasons, so a voter model on GAR carries other seasons. Races with a shipped voter
model (data/awards_fit.json soccer, test.pass true): swap the gar column for svar (stints summed), pools unchanged.
Engine and gate as scripts/awards_more.py test() (rank-ordered logit, L2, LOSO, held-out log P(winner)).
Reported: model(svar) vs model(gar), paired t over seasons, wins. Ship rule (rule fix, so not-worse): mean held-out
log P(winner) with svar >= with gar, and the svar model still beats its own null [svar] with gain > 0 and most seasons.
A race that fails keeps GAR and is reported as a standing descriptive mismatch.

## Blocked before scoring (leads, not tests)
xMV inputs (GAR now / 1 / 2 seasons -> SV): needs the Transfermarkt dump (scripts/.cache/soccer_prospects/dump).
