# Expert track-record weighting of On3/Rivals picks (pre-registered Nov 19 2026, before any held-out look)

Question (Noah, Nov 19): are expert predictions (Rivals FutureCast / On3 RPM picks, 247 Crystal Ball) tracked and used
in the ARK lean? On3/Rivals picks are (PR #1024, Nov 17: `esh`, `eany`). Not yet done: the step the Nov 17 prereg held
back for after E passed, weighting each expert by his own track record.

## Data
Same as scripts/research/recruit_visits_nov17 (On3 per-recruit picks, ESPN classes, as-of = On3 commitment - 30 days).
Pick row: date, school, expert id, confidence, flippedFrom, previous date, previous confidence. 247 Crystal Ball:
bot wall, untestable.

## Track record (no leakage)
For a recruit of class y, each expert's record uses only recruits of classes < y with an ESPN commitment: a hit when
his pick as of that recruit's cutoff (the same as-of rule as esh) is the school he committed to. Pooled prior-class
hit rate p0; expert reliability r = (hits + k p0) / (picks + k), k = 10. Weight of a pick = confidence/100 x r/p0.
An expert with no prior record gets r = p0 (weight = confidence, as today).

## Term
esha = reliability-weighted share of his as-of picks on the school (0 when no picks). eany unchanged.

## Base
The live CFB LIST model (kept terms + conv, elo, delo, V visits, esh, eany; decay .75), walk-forward 2018-26.

## Tests (CFB, Holm at .05 over the two)
- A swap: esh -> esha.
- B add: esha on top of esh.
Pass: held-out LL gain > 0, one-sided paired t Holm-adjusted, positive in >= 2/3 of held classes with 20+ pick
recruits that also have a prior track record (2024-26). Reported, not gates: top-1, Brier, k = 5 and 25, split-half
stability of expert reliability (records from classes <= 2024 vs 2025-26), lean calibration in the >= .8 tail.
CBB not tested (E failed there Nov 17, t -.16).

## Serve
A pass swaps/adds esha in recruit_commit_fit.py; live records use every finished class.
