# In-game injury news as next-game availability (preregistered Nov 17 2026, before any outcome was read)

Question (Noah, Nov 17): RotoWire news written during a game ("won't return Sunday", "questionable to return")
is read as a firm status for the team's next game. NFL: Out means it plays 0%, Questionable 75%. NBA: Out .001,
Questionable .535 (Questionable0), Doubtful .015. It holds until newer news or the league's report replaces it.
Should it be?

## Data
- RotoWire's news feed, backfilled for NFL 2024 and 2025 (Sep to early Jan) and NBA 2024-25 and 2025-26 (Oct to mid-Apr),
  with backfill.py. The 2026 season comes from scripts/data/rotowire_history (NFL wk 1-10, NBA to Nov 16).
- Outcomes: NFL PFR snap counts (nflverse snap_counts_<y>): any offense, defense or special teams snap in the
  team's next game. NBA ESPN box minutes (data/nba hist + current season): minutes > 0 in the team's next game.

## Population
- In-game item: the headline matches the in-game phrase list (IG in ingame.py: won't return, exits, leaves, questionable /
  doubtful to return, carted off, ruled out for the rest, done for the day/game, won't finish). Its day is the
  player's team's game day (ET), or the day after for a game that started at 7 PM ET or later.
- Read with the live readers: NFL nfl_games.status_of(head, else the body's first sentence), NBA rotowire.item_status.
  Groups: Out (Out, Doubtful) and Questionable. Items with no status are left out, since the live code ignores them.
- One row per player-game: the player's last in-game item with a status that day.
- Primary: "still newest". No other status item for him is dated after the game day and before the next game's
  day minus 2 (NFL) or the next game's day (NBA). Secondary: every row.

## Predictions compared
- Current (live): NFL Out 0, Doubtful .02, Questionable .75. NBA Out .001, Doubtful .015, Questionable .535.
- C1 (NFL only, fixed in advance): carried like last week's listing (nfl_games.CARRY: Out .38, Doubtful .55, Questionable .84).
- C2 (both): each group's own play rate, walk-forward by season (fit on the seasons before the test season, with
  a +1/+2 Beta prior). Test seasons 2025 and 2026. 2024 is fit only.

## Metric and pass rule
- Log loss with p clipped to [.02, .98], plus Brier. Paired per row vs current, on the primary population and the
  test seasons only.
- A candidate passes when its held-out log loss is lower with paired t <= -2 (Holm over the NFL pair). Brier must
  move the same way, and the sign must hold in each test season.
- Passed: in-game news becomes a carried status at the passing rates (NFL through CARRY or the fitted rates, NBA
  through the fitted rates). Failed: nothing changes.

## Results (Nov 17 2026)
The backfill files (rw_<sport>_<season>.json.gz, ~1.5 MB each) are kept in the project files under research/ingame-nov17/,
not in the repo. Copy them back here to rerun. Rows: rows.json.gz. Numbers: results.json.

Next-game play rates when the in-game item is still newest:

| | NFL 2024 | NFL 2025 | NFL 2026 | NBA 2024-25 | NBA 2025-26 | NBA 2026-27 |
|---|---|---|---|---|---|---|
| in-game Out/Doubtful | .208 (72) | .174 (86) | .211 (38) | .457 (46) | .483 (29) | .000 (2) |
| in-game Questionable | .554 (177) | .462 (208) | .404 (94) | .625 (8) | .714 (21) | .000 (1) |

Held out (2025 + 2026), still newest:

| | n | current LL | candidate LL | t | Brier t | each season | verdict |
|---|---|---|---|---|---|---|---|
| NFL C2 (fitted rates) | 426 | .853 | .638 | -6.63 | -7.22 | yes | **PASS** |
| NFL C1 (carry rates) | 426 | .853 | .949 | +2.51 | +5.41 | no | fail |
| NBA C2 (fitted rates) | 53 | 1.318 | .685 | -3.04 | -2.35 | no (2026-27: 3 rows, worse) | fail as preregistered |

Every row (secondary): NFL C2 t -8.96, NBA C2 t -3.25.

Shipped:
- NFL: in-game items carry ' (in game)' and play at INGAME (nfl_games.py: Out/Doubtful .196, Questionable .483, fit on
  every season's still-newest rows). The hazard table counts them one game further on, like last week's listing.
- NBA: the slate's games are unchanged, since the preregistered rule failed. The power ranking stops reading in-game items.
  That reading came from PR #1011 and never passed a test. Rerun once 2026-27 has 30+ held-out rows: the pooled
  result points the same way (in-game Outs played 45%).
