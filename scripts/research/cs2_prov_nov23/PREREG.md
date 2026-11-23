# CS2 provisional (ESEA-only) FV drivers: pre-registration (Nov 23 2026, written before any outcome is looked at)

Noah: "Can we test adding more FV drivers for provisionally graded CS2 players?" + "LAURSEN_111 finished 3rd in IM at one
point and won prize money, + is now in Main and has good stats in Main, maybe some FV drivers there?"

## Rows (point in time)
- Unit: an ESEA league player in season s (Intermediate / Main / Advanced, any region) with 3+ finished league matches.
- Cutoff T = the day after season s's last league match (any region, playoffs included). Features use only matches before T.
- Provisional = under 300 bo3.gg rounds in the year before T (the pro prospect pool needs 300+), linked to a bo3.gg player
  by `cs2_prospects_lowtier_research.esea_ids` (nickname + 2 teammates or team name).
- Target (the pro prospect target, unchanged): opponent-credited bo3.gg rating over (T, T+365] for players with 600+
  rounds there, weight min(rounds, 3000). Robustness only (not a gate): 6-month window, 300+ rounds.

## Split
- Primary: tune = cutoffs of seasons 46-52 (`research/*_early.json.gz`, fetched for this test), held = seasons 53-54
  (the last with a full year after). If the early fetch returns nothing, tune = S53, held = S54.
- Never refit on held rows. One set of coefficients per spec from tune rows (weighted OLS).

## Specs (nested, in this order; each step tested against the one before it)
- B   constant = tune mean (what any linked ESEA player who reaches 600 pro rounds averages). Current site = FV 20 flat.
- S1  division: level (Intermediate -1, Main 0, Advanced 1) of the player's highest division in season s, EU dummy, level x EU.
- S2  S1 + team results in season s: team regular-season round share (Bo1 scores), made playoffs, playoff match wins
      (log 1 + w), top-3 finish in the playoffs (Noah's "3rd in IM"):
      the last three teams standing in a bracket (bracket = teams joined by playoff matches in one season / region /
      division / stage; ordered by their last playoff match). Defined from 1NT's S56 IM Playoffs A run before any outcome.
- S3  S2 + movement: promoted this season (division above the one he played in season s-1), relegated, ESEA seasons
      played in the last 4 (experience).
- S4  S3 + FACEIT skill level at match time (mean over season s, the only point-in-time FACEIT rating we hold) and its
      change from season s-1 (trajectory).
- S5  (NA only, box lines exist only for NA) S1 + individual stats relative to the division: player K-D per round
      percentile within his division-season. Tested on NA rows against S1 fit on the same NA tune rows.

## Gate
- Held weighted MSE, loss difference per row summed within player (clustered), t of the mean difference.
- A step passes when its clustered t < -2 against the step before it AND survives Holm over the 5 steps (one-sided,
  family alpha .05), with |bias t| < 2 and a held slope (outcome on prediction) between .5 and 1.5.
- Ship rule: the deepest passing nested spec (S1..S4) grades ESEA-only players on the pro FV scale (`fv_of`, Tier-1
  starters mean 50 SD 10, floor 20). Graded players lose the provisional tag (a graded 20 shows as 20, not 20 prov).
  Prospects tab lists them only above 20, like every prospect. If S1 fails nothing changes.

## Not testable (no point-in-time history held): FACEIT Elo (only level), Premier / Leetify ratings, age (FACEIT has no
birth dates), LAN appearances, role, pug stats, prize money (placing stands in). Listed, not tested.

## Cross-sport: whatever passes is tried for provisional players in sports with an analogue (team results / playoffs /
promotion for hockey provisional and soccer prospects).

## Amendment 1 (after the early fetch landed, before any outcome was computed)
- bo3.gg history starts 2024-01: a cutoff needs 90+ days of it before T, else an established pro would read as
  ESEA-only. Earlier cutoffs are dropped from tune.
