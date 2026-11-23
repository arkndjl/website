# Soccer prospect FV: national team play (pre-registered Nov 23 2026, before any row is scored)

Ask (Noah, Nov 23): factor national team performance into soccer prospect FV (e.g. Victor Froholdt, Denmark).

Already tested, not redone: senior call-up / caps / minutes / debut age / caps x MV (snt_*, Oct 31,
data/soccer_trust_research.json: all fail CV); youth call-ups, minutes, finals, G+A, level (yi_*, Oct 24 + Oct 31,
data/soccer_youth_intl_research.json: fail forward or top 50 on board rows; shipped only for academy-only and
youth-only provisional pools).

New here: opponent strength, own-nation strength and production. Nation strength = scripts/soccer_intl.py goal
ratings walked forward over martj42 results (expected margin vs an average side, neutral), value strictly before the
match day. q(S) = clip(S + 3, 0, 6) / 3 (0 for the weakest nations, 1 near an average side, 2 at the top).

Inputs: Transfermarkt API lineups (minutes, goals, assists) of senior comps EMQ EURO UNLA-D WMQ1-6 FIWC COPA FS and the
17 youth comps (SD.YOUTH_INTL), 2010-26, games strictly before the snapshot, whole career to date.

Candidates (one at a time on top of the board's kept OLS inputs, data/soccer_prospects_fit.json):
- N1 snt_opp   sum senior mins/90 x q(opponent) / 10
- N2 snt_own   sum senior mins/90 x q(own nation) / 10
- N3 snt_ga    senior (G+A) x q(opponent) / (senior mins/90 + 5)   (shrunk production)
- N4 snt_comp  N1 on competitive matches only (no friendlies)
- N5 snt_sh12  share of own nation's senior minutes in the 365 days before the snapshot x q(own)
- N6 yi_opp    sum youth mins/90 x q(opponent senior) x (age cap / 21) / 10
- N7 yi_ga     youth (G+A) x q(opponent) / (youth mins/90 + 5)
- N8 nt_all    N1 + N6 (one index of all international play, opponent-weighted)

Gate (same as the Oct 31 harness, scripts/soccer_trust_research.py test()): Oct 24 snapshot rows 2013-20, outcome FV;
cohort-out folds t >= 2 and 2/3 of folds won; top 50 by base held-out grade MSE not worse and top 50 by new grade not
lower in outcome; forward fit 2013-17 / grade 2018-20 MSE, top-50 MSE not worse, top-50 outcome >= -0.1. Then Jan 15
snapshot must not fail CV in the other direction (t > -2). Family of 8: a pass also needs Holm at .05 on the
cohort-out t (one-sided). A passer is refit through soccer_prospects.py --fit (OLS + trees) and must beat the live fit
on forward MSE at the Oct 24 snapshot before shipping.
