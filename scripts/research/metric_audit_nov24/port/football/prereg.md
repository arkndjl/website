# Football port round (CFB + NFL), pre-registration, Nov 24 2026

Written before any candidate below was scored. Same harnesses as round 1 (../../cfb/harness.py, ../../nfl/audit.py).
LOCKBOX: CFB seasons 2019-25 only (2026 rows, games, scores never read); NFL regular seasons 2016-25 only (no 2026 file read).
No CFBD call: cfbfastR release parquets (sportsdataverse GitHub mirror) for CFB plays, nflverse caches for NFL.
One batch, Holm over the tests run (alpha .05, one-sided, candidate better). Test statistic: paired difference in held-out
squared error a team-season (candidate minus base), t over team-seasons; seasons/pairs better reported.
Pass = Holm-significant, at least 2/3 of seasons (pairs) better, and (predictive) player r not down more than .01.

## Tests
(a) CFB XV fit per side [describe held out]. Seven positions 2019-25. Both arms refit every fold, leaving the scored
season out (XV fit as scripts/cfb_xv_backtest.py fit(): score z less SAV_REPL by position unpenalized + parts ridge lam 50
with sign-dropping). Base: all positions on team SRS. Candidate: offense (QB RB WR TE) on the opponent-adjusted offense
rating (points scored, ridge 2, home), defense (EDGE DL LB) on the defense rating (points prevented). Team XV = sum of
both sides, slope on SRS fit on the other seasons, scored on the held-out season's SRS.
(b) CFB pXR form of the predictive value [predict team]. Base: cWAR as round 1, whole value shrunk v E/(E+.2).
Candidate: only the quality part is shrunk, the position's line (CWAR_V) is added back whole:
CWAR_V + SAV_W z E/(E+.2) (NFL pXR: rate over position mean, shrunk, plus the position's value over replacement).
pSV/60 + QB value is not testable as a separate change: it adds one constant to every QB and the QB block standardises
it away (noted, not scored).
(c) NFL uncovered starter snaps at a replacement line [describe held out]. Run only if some team-sides have snap share
not covered by a WAR row (sum of shares below 11 a side on a 17-game scale by more than .05 in some team-season); if
coverage is complete, a replacement value for uncovered time is 0 by construction and the test is void.
(d) CFB level weighting [predict team]. Predictor quality for a player whose season-n team is G5 (not SEC, Big Ten,
Big 12, ACC, Pac-12, Notre Dame) is z - c, c from {0, .25, .5, .75, 1} chosen on the other pairs (cWAR line on top,
same shrink). FCS rows do not exist in the PFN pool (newcomers from FCS take the fill), so FCS weighting is not testable.
(e1) NFL neutral EPA in the predictive chain [predict team]. XV's EPA inputs (passing, rushing, receiving EPA) are moved
to the player's EPA a play on plays with 0.10 <= wp <= 0.90 (nflverse wp; raw a play if fewer than 20 neutral plays),
times all his plays. XV weights, the pXP/60 history and hyper-parameters all rebuilt on those inputs; descriptive XV and
WAR keep raw. Target: pXR/60 (shipped predictive) team predict held out. pXP/60 and XV predict reported beside it.
(e2) CFB neutral EPA in pSV/60 [predict]. QB points over replacement a play on plays with 0.10 <= wp_before <= 0.90
(raw if fewer than 20) times all plays, then pSV/60 as shipped (1/.7/.5, K 650). Target: QB block next-season team
offense held out (qb_team.py harness); secondary: player r vs next-season raw SV/60.
(f) NFL age decline on pXR/60: skipped unless pXR changes the age fit. pXR = pXP + a sub-position constant that does not
depend on age, so the player-level age hinge fit (Nov 11 fail) is the same fit; not rerun.
