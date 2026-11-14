# ARKSTARS / recruit grades: pre-registration (2026-11-14, written before any test below was run)

Thread: "Improve ARKSTARS and recruit models with Fable". Commitment (crystal ball) model: owned by the
hometown-distance thread (/mnt/project-files/recruits/commit-distance/prereg.md); only the forward freeze X1 is here.

## Not tests (fixes found while reading the code; reported with before/after, shipped on their own merits)
- L1 NFL link. scripts/cfb_recruit_retarget.py joins recruits to draft picks by ESPN id; ESPN's NFL ids differ from its
  college ids for older drafts (0 of 256 picks in 2014 share one) and the matcher refuses a name join to a row that
  carries another id. 128 drafted recruits (Clowney, Watkins, Beckham, Hargreaves, Jefferson, Neal, G. Wilson) were
  labelled undrafted. Fix: picks whose id is no recruit's id are joined by name + signing school + draft window.
- L2 Re-listed recruits. 727 athletes appear in two ESPN classes (prep year, JUCO or transfer listing). Keep one row
  per ESPN id: the earliest listing with a grade, else the earliest.
- L3 247 feed. 247Sports pages are behind a bot check, so the live composite for the 2027-29 classes is the last
  snapshot. Replace with a source that updates (decided by F1).

## Football (history: ESPN 2011-19 signees after L1 + L2; outcome = mean of NFL AV a season and draft capital on one
horizon, as shipped; folds hold out whole schools, seed 7, as shipped)
Baseline = the shipped index blocks, P(drafted): grade, hinge, size, level, elo, comp, gap; FV | drafted: grade, elo
(refit on the corrected labels; gap247 is 0 where 247's own rank is not available).
Pass rule for an added block (each part separately): out-of-fold loss falls (log loss for P, squared error for FV |
drafted) with paired t >= 2 over recruits (the house rule) AND the block wins in at least 6 of the 9 classes.
With 6 candidate blocks x 2 parts the chance of one false pass is real: a block that passes at 2 <= t < 2.8 (Holm at
12) is reported as a lead and ships only if it also raises the held-out Spearman with the outcome in 6+ classes.

- F1 On3 industry rating (on3.com industry ranking, read through Chromium as scripts/cbb_on3.mjs does): z of the
  industry rating + a no-rating flag. (a) added to the baseline; (b) in place of comp + gap. Decision on L3: if (b) is
  not worse than the baseline (t > -2 both parts), On3 becomes the live composite; otherwise the live composite moves
  to CFBD's copy of the 247 composite.
- F2 Service gaps from On3's table: 247, ESPN and On3 each minus the industry rating (z within class), 0 when missing.
  Rivals is left out (its ratings end with the 2026 class).
- F3 On3 recruitment fields: schools showing interest (residual on rating within class); commit timing (months
  committed before the December signing day of the senior year, capped 0-24; committed before senior season flag).
- F4 Track marks (MileSplit public athlete feeds; sample = ESPN grade >= 75, matched on name key + home state + grad
  year). Block: has-marks flag; sprint z (best of 100m, 200m, 55m, 60m as a z against matched recruits of his position
  group, the best event counting); throws z (shot put, discus) and jumps z (long, high, triple), same construction.
  Missing = 0. Tested inside the grade >= 75 sample.
- F5 Grade by position: the grade slope allowed to differ by position group (10 interactions, ridge as shipped).
- F6 (stretch) Tree blend: gradient-boosted trees on the baseline inputs, averaged .5 with the linear hurdle on E[FV];
  pass = held-out Spearman gain with t >= 2 across classes and 6+ of 9 classes.

## Basketball (history: scripts/data/cbb_recruit_hist.json.gz, On3 classes 2009-25, realized NBA tier)
Shipped: P(reached NBA) on log consensus rank + old-for-class, trained on 2009-16; log(FV - 20) | NBA on rank.
- B1 Train P(reached NBA) on 2009-21 instead of 2009-16 (a 2021 recruit has had five seasons to debut). Score: each
  class 2009-21 held out in turn, log loss of shipped-window vs wide-window fit. Pass: paired t >= 2 across the 13
  classes and 8+ classes won.
- B2 Add the RSCI 1998-2008 classes (basketball-reference recruit rankings: rank, NBA debut) to the P(reached NBA)
  training rows. Same scoring on 2009-21; same pass rule. (No age term for those rows: old = class mean.)

## Commitment forward freeze
- X1 On3's prediction-machine leader for every uncommitted 2027 football and basketball recruit is frozen today in
  scripts/data/ledger/recruit_rpm_2027.json; scored after the February 2027 signing day against the distance thread's
  model (top-1 hit, log loss). No history exists to backtest it (committed recruits show the answer).

## Sources checked and not used
Nike EYBL / Peach Jam stats (Cerebro widget behind a Vercel checkpoint), Adidas 3SSB stats (needs the site's ajax
nonce; not pursued), RealGM AAU (403), 247Sports (bot check), Athletic.net (403), MaxPreps (403 from here),
MileSplit rankings / performance lists (login), sports-reference CFB (403), d1circuit and archive.fiba.com (unreachable).
