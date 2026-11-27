# CFB context audit, Nov 27 2026: pre-registration (written before any scoring)

Lockbox: 2026 games from week 11 on are never read (scripts/data/games_wf/cfb.json.gz stops at week 10; sv_hist stops at 2025).

## Mismatch under test
The game model's preseason roster prior (scripts/cfb_roster_prior.py -> PTS_ROSTER in scripts/cfb_model.mjs) is a predictive
consumer. Its QB input `qbRet` is the share of last season's passing YARDS thrown by players who are back: volume, no
quality. A predictive QB rate exists in the repo (pSV/60, scripts/cfb_season_value.py add_psv: play weights 1 / .7 / .5,
shrunk to the QB mean with K 650 plays).

## Candidates (two, Holm over two, one-sided)
Point-in-time quality for team T, season S: the QB with the most plays for T in S-1 (scripts/data/sv_hist.json.gz, QB rows,
100+ plays). His preseason pSV rate = (sum_i w_i tot_{S-i} + K m) / (sum_i w_i pl_{S-i} + K), i = 1..3, w = 1 / .7 / .5,
K = 650, m = the QB mean a play in S-1 (all QB rows). Only seasons before S are read. zq = z across FBS teams of S.
Back share s = the live feature qbRet (scripts/data/cfb_roster_feats.json) rescaled 0..1 within the season (it is a z of
the returning share; min = nobody back, max = everyone back). No team QB row in S-1: zq = 0.
- C1 (add): live prior + qbQ, qbQ = s x zq.
- C2 (swap): live prior with qbRet replaced by qbQ.
No hyperparameter is tuned. K, weights, lam, hfa are the shipped ones.

## Harness (the consumer's own design, rebuilt on repo files because scripts/.cache is not in the container)
As scripts/cfb_roster_prior.py: season-end rating = ridge margin rating (Massey, FCS opponents pooled as one team, margin
capped at 28 as a guard against blowouts is NOT applied: plain margins); prior = least squares of the season-end rating on
[1, last, tal247, offRet, qbRet, offIn] (+ candidate), fit on every season before S (walk-forward, 3+ seasons); in-season
rating = Massey shrunk to the prior with lam 3 games, hfa 2.5; each game predicted from the games before it (by week).
Seasons: games_wf has 2017-2026, so `last` exists from 2018; prior fit from 2018; scored (held out) 2021-2025 and 2026
weeks 1-10. Games with an FCS side are predicted but not scored.

## Target, split, pass rule
Target: game margin. Metric: MAE (guard: log loss at sigma 17.131, the file's value). Paired per game, candidate minus base.
PASS = Holm-adjusted one-sided p < .05 on the paired MAE difference (t over games) AND seasons improved >= 4 of 6 AND
log loss not worse. A pass here is a pass on a proxy of the harness: shipping still needs
`OMP_NUM_THREADS=1 python3 scripts/cfb_roster_prior.py` with the candidate added (needs the ESPN box cache), so a pass is
reported as PASS (proxy) with the rerun command, a fail as FAIL.

## Not retested (condition unchanged)
- Game model QB-out charge on multi-season QB value: scripts/cfb_qb_backup.mjs grid prevW {0, .5}, Oct 29: tune picks 0.
  pSV/60 (three seasons, shrink to the mean) is the same idea; rerun needs scripts/.cache/cfb/qb_epa.json.gz.
- XV in the game prior, builder, xNIL (Oct 16, PR #236-238): tie or worse. Marcel on cWAR (Nov 24 P1): worse.

# Round 2 addendum (written before scoring)

## P2 CFB predictive awards: games-left rate
Mismatch: scripts/awards.py football_draw runs the games left at this season's raw box rate a game (descriptive). The CFB
voter models read box lines, so the same-scale predictive rate is the box rate shrunk to the player's own last-season rate:
rate = (stat to date + K x last season's rate a game) / (games + K), K = 4 games, pre-set, not tuned. A player with no line
last season keeps the raw rate.
Harness: `python3 scripts/awards_asof.py cfb` (the consumer's own: 2005-25, checkpoints 25 / 50 / 75%, Heisman, Maxwell,
Walter Camp, O'Brien, leave-one-season-out voter fit, same seeds), base vs `--leftk=4`. --sims=1000 for both (CPU cap).
Target: log loss of the eventual winner (floor as the harness). Paired by season (mean over that season's rows).
PASS = t over seasons <= -2 (one-sided p < .05; one candidate in this family) AND seasons better >= 13 of 21 AND the 75%
checkpoint alone not worse.

## P1 CFB xGap own fit
Planned: own a / b / c on the WAA gap, two seasons on, from PFN history. Feasibility is checked first (does PFN history list
backups and classes); no outcome is read in that check.
