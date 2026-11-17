# Recruit commitment model: visits and expert picks (pre-registered Nov 17 2026, before any held-out look)

Question (Noah, Nov 17): do visit reports and who a recruit is deciding between improve the ARK lean?

## Data
- On3/Rivals per-recruit records (scripts/recruit_on3_visits.mjs): dated official/unofficial visits, commitment
  date, dated RPM expert picks (expert, school, confidence, the pick it replaced), dated RPM leader snapshots.
  CFB top 600 a class, CBB top 150, classes 2016-2029.
- Joined to the ESPN classes of scripts/recruit_commit_fit.py by class + names.py key + home state; On3 school
  slug -> ESPN team id via ESPN's team slug.
- 247 Crystal Ball: not reachable from the build container (bot wall). Finalist / top-schools lists: not testable
  (On3 resets other schools to "Offered" after the commitment, so history has no dated finalist list).

## As-of rule (no leakage)
Every feature uses only events dated strictly before cutoff = On3 commitment date - H days. Primary H = 30.
Recruits with no On3 commitment date keep zero features (no information, conditional logit ignores them for the new
terms). Expert pick at the cutoff: the pick if dateAdded < cutoff; else the replaced pick (flippedFrom, or the same
school when not a flip) if previousDateAdded < cutoff; else none.

## Base
The live CFB LIST model (BASE + ld + inst + conv/elo/delo, decay .75) and the live CBB LIST model (kept terms),
walk-forward by class exactly as scripts/recruit_commit_fit.py (CFB held 2018-26, CBB 2015-26).

## Tests (one family per sport, Holm at alpha .05 over the three)
- V  visits: ov (official visits to the school before cutoff, capped 1), luv = log(1+unofficial visits), vlast
  (the school is his most recent visit before cutoff), vrec (any visit to the school in the 90 days before cutoff).
- E  expert picks: esh = confidence-weighted share of experts whose pick at cutoff is the school (0 with none),
  eany = his pick list is non-empty and the school has 0 picks (separate the "no picks" case).
- R  RPM snapshot: lrpm = log(RPM % at the last leader snapshot before cutoff, floor 0.5) for the school, 0 when he
  has no snapshot, plus rpm_has (his snapshot exists and the school is not in it).
Each added on top of the base alone, then the passers forward in the order V, E, R.

Pass: per-recruit held-out LL gain > 0, paired t >= 2 (Holm-adjusted within the family), positive in >= 2/3 of the
held classes that have data for the term (E, R: classes with pick coverage only). Also reported: top-1, Brier,
calibration of the shown lean (10 bins), and the gain at H = 7 and H = 90 (sensitivity, not a gate).
Expert track record weighting (each expert's prior-class accuracy, shrunk) is tested only if E passes.

## Serve
A passing term is computed for live uncommitted recruits with cutoff = today (all events to date).
