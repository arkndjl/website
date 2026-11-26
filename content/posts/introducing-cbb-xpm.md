+++
title = "Introducing XPM for College Basketball"
date = "2026-11-26T15:00:00-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["college basketball", "statistics"]
keywords = ["xpm", "rxpm", "pxpm", "college basketball", "bpm", "gbpm", "barttorvik", "plus-minus", "projection", "statistics"]
description = "How XPM for college basketball is built from Barttorvik's BPM and game BPM, how rXPM (descriptive) and pXPM (predictive) compare with BPM at describing a season and predicting the next one, and where both are used on the College Basketball ARKBOARD."
showFullContent = false
readingTime = false
hideComments = true
draft = false
Toc = true
+++

XPM (Cross Plus-Minus) for college basketball is an all-in-one impact metric, measured in points per 100 possessions above an average D-I player and split into offense and defense. Like the [NBA version](/posts/introducing-xpm/), there are two versions of it. rXPM is the descriptive version, and it measures what a player did in a given season. It is the number labeled XPM on the site. pXPM is the predictive version, and it is a projection of what a player will do the following season.

Both are built on Bart Torvik's BPM, which is the best public college metric I have tested, so BPM is the metric each version has to beat. In this article I will go through how each version is built and how it compares to BPM. rXPM tracks a team's wins better than BPM in all 19 seasons I tested, and it keeps BPM's split of credit between teammates. pXPM predicts next-season team strength better than BPM in all 14 seasons I tested, with a next-season team R² of .746 compared to .643 for BPM.

## Why It Isn't The NBA Version
NBA XPM is a 50/50 blend of BPM and DPM, and DPM is built on RAPM. The RAPM base is what picks up the defensive and off-ball value that the box score misses. College basketball doesn't have a public equivalent:

- **No public college DPM or RAPM.** The EvanMiya and KenPom player ratings are paid.
- **Lineup data is thin.** ESPN's college play-by-play has no substitutions. NCAA.com's does, but only for about half of 2024-25 and most of 2025-26.
- **A RAPM prior didn't help.** Earlier in November I added a ridge RAPM adjustment from those two seasons of lineups to BPM, and it was worse than BPM alone at predicting held-out game margins at every penalty I tried.

So college XPM has to come from the box score, and Barttorvik already publishes two box score metrics that are fit differently. That is the starting point for rXPM.

## rXPM
### Two BPMs
Barttorvik has two versions of BPM for every player:

- **BPM** is computed on a player's season line, with a team adjustment so that a team's players add up to its adjusted efficiency margin.
- **Game BPM (GBPM)** is computed on each game's box score, and a player's season GBPM is the minutes-weighted average of his games.

They are measuring the same thing, but they have different strengths, and it helps to look at a player rating as two separate parts. The first part is the **team total**, which is how much value the whole roster gets credit for. The second part is the **split**, which is how that total is divided between teammates.

For the team total, GBPM is better. A team's minutes-weighted GBPM tracks its wins more closely than its BPM does, which I showed on November 24 when the site's wins metric (now VORX) moved to GBPM. For the split, BPM is better, which is the new result here.

### Formulation
rXPM takes the team total from GBPM and the split from BPM. Every player on a team is shifted by the same amount on offense and the same amount on defense:

- **O-XPM** = OBPM + team average of (OGBPM − OBPM)
- **D-XPM** = DBPM + team average of (DGBPM − DBPM)

The team averages are weighted by minutes. After the shift, a team's players add up to the same total as their GBPM, and the gap between any two teammates is the same as their gap in BPM.

### The Team Total
For each team-season from 2007-08 to 2025-26, each player's value × his share of the team's minutes is summed across the roster and compared to what the team did that season.

| Metric | Wins above bubble per game R² | Win% R² | Adjusted efficiency margin R² |
| :--- | :---: | :---: | :---: |
| **XPM** | **.888** | **.676** | .9954 |
| GBPM | **.888** | **.676** | .9954 |
| BPM | .880 | .652 | **.9996** |

*19 seasons. Wins above bubble (Barttorvik's WAB) is a team's wins compared to what a bubble team would be expected to win against the same schedule.*

XPM is ahead of BPM on wins above bubble in 19 of 19 seasons (t = 11.3), and on win% in 19 of 19. Wins above bubble is the better of the two tests, since it accounts for schedule, and win% doesn't.

{{< postchart "cbb-rxpm-wab" >}}

BPM is ahead on adjusted efficiency margin, but that is the number BPM's team adjustment is set to, so it matches almost exactly by construction. Efficiency margin gives a team full credit for the size of every win, and wins don't. XPM gives up a small amount of fit to efficiency margin in exchange for a closer fit to winning.

### The Split
The harder part to test is the split, since every player on a team shares the same results. The test I used is based on who sat out. Players miss games, and their minutes change from game to game, so the group of players on the floor is a little different every night. If a metric splits credit between teammates correctly, then a team should play better than its own average in games where its minutes went to its higher-rated players.

For every game, I took the team's margin per 100 possessions, adjusted for the opponent and the site, minus the team's average for the season. That is compared to the minutes-weighted rating of the players who played in that game. I ran it three ways: with every rotation player, with only starters (20+ minutes per game), and with the season split into halves, where ratings built from one half of a team's games predict the games in the other half, so a rating never includes the game being predicted.

| Design | GBPM R² | XPM R² | Seasons XPM ahead | t |
| :--- | :---: | :---: | :---: | :---: |
| All rotation players | .0042 | **.0048** | 14 of 19 | 3.0 |
| Starters only | .0049 | **.0057** | 17 of 19 | 4.9 |
| Split halves | .0018 | **.0020** | 11 of 19 | 1.9 |

*Each R² is the share of a team's game-to-game variation explained by who played. They are small because most of a single game's margin is noise.*

XPM is ahead of GBPM in all three designs. Against BPM this test is a tie, since XPM's split is BPM's split. So XPM matches GBPM on the team total and beats it on the split, and it matches BPM on the split and beats it on the team total.

The split also carries over to the next season. Applying each metric to next season's minutes, XPM's next-season team R² is .624 compared to .611 for GBPM (better in 12 of 14 seasons, t = 3.4). BPM is still the best of the three at this (.642), which is the reason pXPM is built on BPM and not on XPM.

### How Different Is It From BPM?
For most players it is a small change. Across every player-season, the correlation between XPM and BPM is .998, and the average gap is .24 points per 100. Everyone on a team moves together, so the change is in how teams compare to each other. In 2025-26 the largest shifts down were for Purdue (−1.0), Alabama and Wisconsin (−.9), and the largest shifts up were for Western Illinois (+.9) and Maryland Eastern Shore (+.7). The top of the 2025-26 leaderboard is in the same order as BPM's.

### What Didn't Work
| Test | Result |
| :--- | :--- |
| Best blend of BPM and GBPM | No better than BPM in who sat out. **Fail.** |
| New box score weights fit to who sat out | Passed who sat out, but the weights paid for made threes, and next-season team R² fell (.642 to .637). **Fail.** |
| Team totals set to wins, or to capped game margins | Worse split-half reliability and worse next season. **Fail.** |
| GBPM moved toward raw net rating | Win% R² went up, but only because it removed the schedule adjustment. On schedule-adjusted results it was worse. **Fail.** |

## pXPM
### Formulation
pXPM is fit separately for offense and defense. The target is the player's BPM on that side the next season, and the inputs are:

- **BPM history**: the last three seasons, weighted by minutes. Offense weights the previous two seasons at .35 and .2 and is shrunk 200 minutes toward the average of low-minute players. Defense weights them at .6 and .4 and is shrunk 100 minutes. Defense carries more from the older seasons, since one season of defensive BPM is noisier.
- **Minutes and class**: ln(1 + minutes / 100), and whether the player is a freshman, sophomore, junior or senior.
- **Twelve box score rates**: steal rate, block rate, offensive and defensive rebound rate, assist rate, turnover rate, free throw rate, 3PA per 100, share of shots at the rim, usage, TS% and height. Each one is z-scored within its season and multiplied by minutes / (minutes + 200), so a 40-minute line can't move the projection much.
- **Team context**: the offensive and defensive rating of the team he played on.
- **Recruit rating**: his rating out of high school, with a separate weight for freshmen, sophomores and upperclassmen.

Each player is weighted by his minutes the next season. The fit uses every pair of seasons from 2008-09 to 2009-10 through 2024-25 to 2025-26, and nothing from the 2026-27 season is used.

### What The Inputs Add
BPM already uses most of the box score rates, so their weights in pXPM show where a player's BPM gives too much or too little credit when the goal is the next season:

| Input (per SD) | Offense | Defense |
| :--- | :---: | :---: |
| 3PA per 100 | **+.33** | +.08 |
| Defensive rebound rate | +.19 | +.11 |
| Usage | +.17 | −.16 |
| TS% | **−.17** | −.02 |
| Block rate | +.03 | **+.30** |
| Assist rate | +.09 | **+.29** |
| Height | −.08 | **+.25** |
| Offensive rebound rate | +.01 | **+.24** |

*Weights on next-season BPM after the player's own BPM history and team, per standard deviation of each rate, before the minutes factor (about .8 for a full season).*

On offense, the largest positive weight is on three-point volume, and TS% is negative. Shooting efficiency is the least stable stat in the box score (in the NBA it took 31 games to reach a split-half r of .50, compared to 14 for XPM), so a player whose BPM was high because of his TS% will usually lose some of it the next season. How many threes a player takes is a much more stable sign that he can shoot. On defense, BPM doesn't give enough credit to size. Height, blocks and offensive rebounding all predict a better defensive BPM the next season than the player's current defensive BPM shows.

Team context adds .42 points on offense and .15 on defense for every 10 points of team rating. A player on a better team projects higher the next season than a player with the same BPM on a worse team. Recruit rating matters most for freshmen (.68 on offense and .50 on defense per 100 points of rating) and less each year after, but it still has a weight for juniors and seniors.

### Predicting The Next Season
- **Team test**: each player's value this season × his minutes next season, summed for the team and compared to the team's adjusted efficiency margin next season. Freshmen and other players with no line get the metric's average for low-minute players.
- **Player test**: correlation with the player's own BPM next season, for players with 300+ minutes in both seasons, weighted by minutes.

pXPM is scored walk-forward. For each of the 14 seasons from 2012-13 to 2025-26, it is refit using only the seasons before it.

| Metric | Next-season team R² | Player r | Player RMSE |
| :--- | :---: | :---: | :---: |
| **pXPM** | **.746** | **.780** | **2.32** |
| pXPM without team context and recruit rating | .733 | .770 | 2.36 |
| BPM | .643 | .680 | 3.41 |
| XPM (rXPM) | .624 | .668 | |
| GBPM | .611 | .620 | |

*14 season pairs, 27,602 player-seasons in the player test.*

pXPM is ahead of BPM in 14 of 14 seasons (t = 15.4). Team context and recruit rating account for .013 of the team R², and that step is better in 13 of 14 seasons (t = 7.9).

{{< postchart "cbb-pxpm-pairs" >}}

The board's xBPM, which is the site's projection of this season's BPM and also uses recruiting and team context, is still slightly ahead on the player test (r = .795), and behind on the team test (.735).

### What Didn't Work
| Test | Result |
| :--- | :--- |
| Late-season form (last third of the season) | t = 2.4 alone, nothing once team context is in. **Fail.** |
| Age on top of class | Tie (t = −.3). **Fail.** |
| Position, and height for freshmen | Worse in 12 of 14 seasons. **Fail.** |
| Minutes share and its change from the season before | Worse in 13 of 14 seasons. **Fail.** |
| Game-to-game consistency | Worse in 13 of 14 seasons. **Fail.** |

## Where XPM Is Used
**rXPM** is the descriptive number across the College Basketball ARKBOARD:

- **Board**: the XPM column is a player's rXPM this season.
- **VORX**: wins over replacement on XPM = (XPM + 1.4) × minutes / 40 × .68 × .0187 wins per point, the college version of the NBA board's VORX with the same replacement level. XPM is shrunk 100 minutes toward the season average first, and replacement level is the average 9th man. Team VORX + .39 × games has a correlation of .87 with team wins over 3,485 team-seasons.
- **Stat+**: XPM compared to the player's position, on a scale where 100 is average and 25 is one standard deviation.

**pXPM** is used where the question is about next season:

- **pXPM leaders**: every returning player's projection for 2026-27, under leaders.
- **Portal**: transfers are ranked by pXPM at their new school.
- **Preseason team ratings**: the game model's preseason rating uses pXPM in place of last-season BPM for returning players. That raised its next-season team R² from .757 to .765 (13 of 14 seasons) and lowered the held-out game margin error in 2021-26 from 9.5915 to 9.5892.
- **FV**: pXPM is a driver for returning players. When it was added, the model's selection took it and dropped last-season BPM, and the realized FV of each held-out board's top 50 went from 39.0 to 39.6.

The game model and FV use pXPM without team context and recruit rating, since both models already have their own inputs for those. I tested the full version in both anyway. It improved the preseason rating again (.765 to .768, 13 of 14 seasons), but game margins came out slightly worse with it in all 11 seasons (held-out error 9.589 to 9.590 points), and FV ranked the 2017-19 boards a little worse (correlation with outcome .386 to .377). Both stay on the simpler version. In the NBA mock draft, pXPM was about even with 3-season BPM (t = .6), so the mock stays on 3-season BPM.

## Leaders
### XPM, 2025-26

| | Player | Team | XPM | O-XPM | D-XPM | VORX |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| 1 | Cameron Boozer | Duke | +15.4 | +9.7 | +5.7 | 6.3 |
| 2 | Yaxel Lendeborg | Michigan | +14.7 | +8.5 | +6.2 | 5.8 |
| 3 | Aday Mara | Michigan | +13.8 | +3.7 | +10.1 | 4.1 |
| 4 | Zuby Ejiofor | St. John's | +13.5 | +6.4 | +7.0 | 4.9 |
| 5 | Allen Graves | Santa Clara | +13.5 | +8.0 | +5.6 | 3.3 |
| 6 | Ugonna Onyenso | Virginia | +13.3 | +1.9 | +11.3 | 2.8 |
| 7 | Maliq Brown | Duke | +13.2 | +4.1 | +9.2 | 3.2 |
| 8 | Joseph Tugler | Houston | +12.8 | +3.6 | +9.3 | 3.6 |
| 9 | Oscar Cluff | Purdue | +12.4 | +7.7 | +4.7 | 3.9 |
| 10 | Tarris Reed Jr. | Connecticut | +12.2 | +4.2 | +7.9 | 3.8 |

*500+ minutes.*

### pXPM, 2026-27

| | Player | Team | Class | pXPM | O-pXPM | D-pXPM | XPM 2025-26 |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| 1 | Joseph Tugler | Houston | Sr | +12.5 | +3.8 | +8.7 | +12.8 |
| 2 | Patrick Ngongba II | Duke | Jr | +11.5 | +5.3 | +6.2 | +11.2 |
| 3 | Motiejus Krivas | Arizona | Sr | +10.7 | +4.1 | +6.6 | +11.1 |
| 4 | Flory Bidunga | Louisville | Jr | +10.7 | +3.3 | +7.4 | +11.0 |
| 5 | David Mirkovic | Illinois | So | +10.5 | +7.0 | +3.4 | +8.0 |
| 6 | Johann Grunloh | Virginia | So | +10.5 | +3.6 | +6.9 | +9.4 |
| 7 | Aiden Sherrell | Indiana | Jr | +10.0 | +5.1 | +4.8 | +9.7 |
| 8 | Amari Allen | Alabama | So | +9.9 | +6.4 | +3.5 | +7.9 |
| 9 | JT Toppin | Texas Tech | Sr | +9.9 | +5.4 | +4.5 | +8.5 |
| 10 | Zvonimir Ivisic | Illinois | Sr | +9.9 | +3.5 | +6.4 | +9.6 |

*Players on a 2026-27 D-I roster with a D-I season behind them. Projections are from before the season and don't change during it.*

The pXPM list is mostly big men who defend. Nine of the ten are frontcourt players, and six of the ten have a higher projection on defense than on offense. The three sophomores (Mirkovic, Grunloh and Allen) are projected above what they did as freshmen, since the class and recruit rating terms add the most for players coming off their first season.

## Summary
- **XPM for college basketball** is built on Barttorvik's BPM and game BPM, in points per 100 possessions above an average D-I player, with an offensive and a defensive side.
- **rXPM** (shown as XPM) = BPM plus the team's average gap between game BPM and BPM. It has game BPM's team totals and BPM's split between teammates.
- rXPM's team totals track **wins above bubble better than BPM in 19 of 19 seasons** (R² .888 vs .880), and win% in 19 of 19 (.676 vs .652).
- rXPM's split **beats game BPM at predicting which games a team plays above its average**, based on who played, in all three designs (t = 1.9 to 4.9).
- **pXPM** = three seasons of BPM by side, shrunk, plus minutes, class, twelve box score rates, team context and recruit rating, fit to next-season BPM.
- pXPM **beats BPM at predicting next-season team strength in 14 of 14 seasons** (team R² .746 vs .643), with a next-season player error of 2.32 compared to 3.41.
- rXPM is the input to **VORX, Stat+ and the board's XPM column**. pXPM is on the **pXPM leaders and portal tabs**, and it feeds the **preseason team ratings and FV**.

Data: [Barttorvik](https://barttorvik.com) (season lines, player game logs, team results). Code ([github.com/arkndjl/website](https://github.com/arkndjl/website)): `scripts/cbb_xpm.py`, `scripts/cbb_tabs.py`, `scripts/research/cbb_xpm_nov26/`.
