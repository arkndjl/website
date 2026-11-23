# Port pass Nov 23 2026: tennis + CS2 (pre-registered before any outcome was read)

Lockbox: tennis rows with tourney date > 20261110 and CS2 series after 2026-11-10 are never read. Holm over all seven
tests below (family of 7, alpha .05, one-sided "better" p).

## Tennis match model (harness scripts/research/tennis_nov13: live walk-forward blend, 3-season window, t by tournament)
Base = the live blend inputs (M.feats). Candidate = base + one extra column (winner's side, A minus B unless stated),
weights refit walk forward exactly as the base (mtests.wf_logit). Tune 2012-22, held 2023 - Nov 10 2026 (4 seasons).
Features come from a separate pass over every row (all levels) in date order, read before the row updates.
- T1 TBL (G4 tiebreak luck): last 364 days, every level: (tiebreak sets won - lost) / (tiebreak sets + 10). A set is a
  tiebreak if its score is 7-6 / 6-7 (or 13-12 / 12-13 with a tiebreak count).
- T2 BPL (G4 break-point luck): last 364 days, matches with stats: sum over matches of (bpSaved - bpFaced x own serve
  point rate in that match) + (break points converted - chances x (1 - opponent's serve point rate in that match)),
  divided by (break points faced + chances + 50).
- T3 TTL (G1 title letdown): 1 if the player's previous match (any level) was a won final ('F') of another event.
- T4 EAR (G2 early-season stretch): 1[tourney date in January] x logit(Elo chance) (one column, not A minus B).
- T5 RET (G11 returner after long absence): 1[either player's last match 180+ days before] x logit(Elo chance).
Pass: tune mean d < 0 with tune t <= -1.0, held Holm-adjusted one-sided p < .05 (t by tournament), held better in 3+ of
4 seasons. Ship only a pass.

## CS2 (harness scripts/cs2_nov13_research.py Lab, live params, tiered logistic by top-50 / rest, t by month)
Tune 2024-08-07 .. 2025-06-30, held 2025-07-01 .. 2026-11-10.
- C1 LD (G1 letdown): team won its previous series as an underdog (pre-series Elo chance < .35 from the row's x) and
  plays again within 4 days; flag A minus B, extra column in the tiered fit.
Pass: tune d < 0, held Holm-adjusted p (t by month) < .05, top-50 held d <= 0.

## CS2 prospect FV (model-to-model, cs2_players.prospect_fit quarterly cutoffs, targets capped at Nov 10 2026)
- C2 PELO: the series model's player Elo at the cutoff (cs2_model.replay snaps, the player's own value, /400) added to
  "rating + age + S/A share". Players with no Elo get 0 and a missing flag. Pass: held weighted MSE paired t <= -2 after
  Holm (one-sided p), tune fit sign kept.

## Metric (display only)
- SV tennis: season WAR, calendar year to date (same per-match WAR increments as the 52-week WAR). Ships as display if
  split-half r (odd vs even matches within a season, players with 30+ matches, seasons 2015-25) >= .5.
