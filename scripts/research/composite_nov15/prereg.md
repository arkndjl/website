# M3 pre-registration: 247 composite (CFBD copy) on top of On3 in the CFB recruit index

Written 2026-11-15 before any score in this thread. Family MOVES, test M3 of /mnt/project-files/leads-nov14/prereg.md.

## Prior looks (spent, stated up front)
- The Nov 14 recruit thread (PR #888, memory note recruit-on3-index-nov14) reported "247 composite on top of On3 +
  service gaps still t 2.8" on these same rows (ESPN 2011-19 signees). That look is not in its f_tests.json; this
  test is therefore a re-run of an already seen result on the same data, not an independent confirmation. It is
  reported as such whatever the outcome. No new history exists (classes 2020+ have no matured NFL outcome).
- No CFBD call and no other score has been made in this thread.

## Data
- Rows: scripts/cfb_recruit_retarget.py dataset() as shipped at origin/main 7c547bdb9 (ESPN 2011-19 signees with an
  FBS/FCS school, one row per athlete, NFL link with the Nov 14 label fix), outcome = drafted (P part) and FV |
  drafted (FV part), NFL through 2025. Rebuilt from the public pulls the script makes (ESPN recruiting API,
  cfbfastR schedules, nflverse players + draft_picks); the shipped row count was 24,450 / 1,895 drafted and the
  rebuilt counts are reported beside it.
- Composite: scripts/data/cfb_recruits_cfbd.json.gz as committed (CFBD recruiting/players, classes 2009-25), joined
  by the shipped attach_composite() (name key, CFBD has no home state). 247Sports itself is never requested.
- History caveat (not a test): the file holds each class's final composite; live classes are mid-cycle values.

## Baseline and candidate
- Baseline = the live index blocks in data/cfb_recruit_retarget.json `use`:
  P(drafted): grade, rank, size, level, elo, on3, svc, tm; FV | drafted: grade, elo.
- Candidate (one, fixed): block `comp` exactly as blocks0() defines it: compz = (composite - .87) / .04, noComp flag.
  No grid, no other form. The `gap` block (composite vs ESPN grade, vs 247's own rank) is NOT tested.
- Confirmatory test: `comp` added to the P(drafted) part. The FV | drafted part is computed and reported, descriptive
  only; it does not ship.

## Scoring (the Nov 14 gate, harness scripts/research/recruits_nov14/rh.py test())
- 5 folds holding out whole schools, seed 7, ridge LAM as shipped; per-recruit out-of-fold log loss, d = base - cand.
- Gate (all must hold):
  1. paired t over recruits >= 2 (the Nov 14 house rule), AND the block wins >= 6 of the 9 classes;
  2. if that t is < 2.8, the held-out Spearman of expected FV with the outcome must also rise in >= 6 of 9 classes
     (the Nov 14 rule for the 2-2.8 band);
  3. batch rule, clustered: the same mean gain with a t clustered by signing school, one-sided, must clear Holm at .05
     in family MOVES. Family p-values on file: M1 CFB t 0.10, M1 CBB t 1.47 (p .071). With M3 that is 3 tests, so
     M3 needs one-sided p <= .0167 (t >= 2.13, normal) to pass as the smallest;
  4. tune / held sign: mean out-of-fold gain > 0 on classes 2011-15 (tune) and on classes 2016-19 (held), separately.
- One run. No retune, no second form after seeing the result.

## What ships
- Pass: `comp` joins the index's P(drafted) blocks (scripts/cfb_recruit_retarget.py), index refit, live fit rerun
  (cfb_recruit_fit.py chain as the recruit-retarget note says); live classes read the composite from the CFBD file
  (refreshed weekly, 3 calls, behind the MIN_LEFT 500 guard), never from 247Sports. A class with no CFBD rows keeps
  the model it has now (no noComp shift on a whole class). Registered for the batch's season-end score.
- Fail: no model change. The weekly pull is kept only if the composite has display value on the recruit board under
  the site rules (a labelled column, no model claim); otherwise nothing is added to any workflow.

## CFBD calls
- Budget approved by the owner: 4-call backfill (classes 2026-29, HighSchool) + 3 calls a week. Every call spent in
  this thread is counted in results.md. The container's key availability is checked first; with no key, zero calls
  are spent here and the backfill is a named workflow dispatch for the lead.
