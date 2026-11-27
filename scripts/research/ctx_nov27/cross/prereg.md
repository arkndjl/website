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
