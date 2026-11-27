# ctx27 cross lens: pre-registration (written Nov 27 2026 before any scoring)

## T1. Pick-rule segments: conference labels as they stood (LEAK: fit form != serve form)

Found: `scripts/games_picks.py` seg_of() labels every walk-forward game with TODAY's conference map
(data/cfb_teams.json, data/cbb_games.json power) for the families tier / game / conf. Live picks read today's map for
today's games (correct), so the fit rows of teams that changed conference since (CFB 2017-25, CBB 2024-25 and 2025-26)
are labelled in a form the serve never sees. Two unmapped teams ('other' / independents) also read as a conference game.
Measured before scoring (labels only, no returns): CBB 'game' label differs from the game's own ESPN conference flag on
481 of 5,284 (2025) and 413 of 5,327 (2026) games with an open.

- Candidate: labels from the game's own season. CFB: homeConference / awayConference / conferenceGame of
  scripts/data/cfb_hist_md.json.gz by game id (Pac-12 a power conference through 2023). CBB: the season's conference
  groups joined by ESPN conference-game flags (scripts/data/cbb_games_hist.json.gz), named by the plurality of today's
  names among members; conference game = the game's own flag. Games not in the history (the season in progress) keep
  today's map. Independents / unmapped teams never make a conference game.
- Target: clvRet (return at the close of the model's side at the open, units.BASE), the consumer's own target.
- Harness: games_picks rule_bets + the fit_segments tuning step, unchanged (X per family value on tuning seasons, EB
  shrink, 25+ tuning picks), run under each labelling in memory. No live 2026-27 record is read: lockbox.
- Split: the consumer's own. CFB tune 2017-20, evaluation 2021-26 (validation 2021-22 + test 2023-26; the file ends
  Nov 4 2026, before the week 11 lockbox). CBB tune 2025, evaluation 2026 (no later season). NBA has no conference
  family: unchanged.
- Score: rules (fam, val, X) of the three conference families chosen on TUNING under each labelling, both sets then
  applied to the evaluation seasons with as-it-stood labels (what serve does). One pick a game and market (the union of
  the family rules), pooled clvRet, t clustered by ET slate; paired difference on the union of the two pick sets (0
  where a set has no pick), slate-clustered t.
- Pass rule: after - before >= 0 on the evaluation clvRet summed over pick-games (point estimate) for each sport
  tested AND guard: mean clvRet per pick under "after" > 0. Holm over the sports tested (CFB, CBB) for any claim of
  improvement; a fit/serve form fix needs only "not worse".
- Fail: ship nothing in the fit path; report as a lead.
- If PASS: code change in games_picks.py only. data/games_picks_rules.json is rewritten by `games_picks.py --rules`
  (which also reads the live record, Noah's Nov 11 rule), so the rerun is left to the lead after the sport lenses' --fit.

## T2 (round 2, P4). Close predictor tier cells: conference as it stood

Found: scripts/close_model.py load() / game_cells() set the tier cell (CFB P4 / G5 / FCS, CBB high / mid / low) from
today's conference map on every past game; a live game reads today's map (its own season's). Table only (closefit).
- Candidate: tier from games_picks.conf_hist (the game's own season; CFB Pac-12 P4 through 2023, CBB P12 high through
  2024); games not in the history keep today's map.
- Target: the consumer's own, close - open (the line move), held-out walk-forward exactly as fit(): spec (knot, ridge)
  chosen on the tuning seasons under each labelling, each held season predicted from a fit on the seasons before it.
- Serve form: held rows are predicted with as-it-stood tiers under both arms; only the fit rows' labels differ.
- Score: paired squared error of the predicted move on held games, t clustered by ET day; per sport x market
  (CFB spread, CFB total, CBB spread, CBB total). Guard: clvRet of the model's held bets at E > 0.
- Pass (per sport, decided here): after SSE <= before SSE in both of the sport's markets and the guard not lower by
  more than 1 se in either. Holm over the two sports for any claim of improvement.
- If PASS for a sport: switch that sport in close_model.py and rerun `close_model.py --fit` (offline, data/close_fit.json).

## T3 (round 2). Tennis all-time season value: year-end Elo margin -> season-only value

Rule fix (MISMATCH-D), no fitted model reads it. Gate, set here: the list on the season-only value must pass
alltime.py era_check (adjusted KL <= the era-blind 95% line) for peaks and careers on both tours, as the Elo lists do
now. Pass -> switch; fail or no offline source rows -> lead with the rerun command.
