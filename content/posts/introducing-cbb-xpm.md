+++
title = "Introducing XPM for College Basketball"
date = "2026-11-26T15:00:00-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["college basketball", "statistics"]
keywords = ["xpm", "pxpm", "college basketball", "bpm", "barttorvik", "plus-minus", "projection", "statistics"]
description = "How pXPM for college basketball is built from Barttorvik BPM and the box score, how it compares with BPM, GBPM, PRPG and Stat+ at predicting the next season, and where it is now used on the College Basketball ARKBOARD."
showFullContent = false
readingTime = false
hideComments = true
draft = false
Toc = true
+++

XPM for college basketball is a projection. pXPM takes a player's last three seasons of Barttorvik BPM and his box score, and estimates what his BPM will be next season, in points per 100 possessions over an average D-I player, split into offense and defense.

The NBA version of XPM has two parts: rXPM, which describes a season, and pXPM, which projects the next one. I tried to build both for college. pXPM beat BPM clearly. rXPM did not beat what the site already uses (Barttorvik's game BPM, GBPM), so there is no college rXPM. Season value on the College Basketball ARKBOARD stays on GBPM-based WAR, and pXPM is used where the board makes forecasts: the FV model and the preseason team ratings in the game model.

This article goes through why the NBA formula can't be copied, how pXPM is built, how it compares with the public college metrics, and what changed on the site.

## Why Not Copy The NBA Version
NBA XPM is a 50/50 blend of BPM and databallr's DPM, and DPM is built on RAPM. The RAPM base is what lets it pick up defensive and off-ball value that the box score misses. College basketball doesn't have that:

- **No public college DPM or RAPM.** EvanMiya and KenPom player data is paid.
- **Lineup data is thin.** ESPN's college play-by-play has no substitutions. NCAA.com's play-by-play does, but only for about half of 2024-25 games and almost all of 2025-26. That is two seasons, not enough for a backtest.
- **I already tried a RAPM prior.** In early November I built a college XPM as Barttorvik BPM plus a ridge RAPM adjustment from those two seasons of lineups. It was worse than BPM alone at predicting held-out game margins at every penalty I tried, so the best weight on the lineup data was zero.

So college XPM has to come from the box score. BPM is already a box score regression, though, so pXPM has to do something BPM doesn't: it has to project.

## Formulation
pXPM is built separately for offense and defense, and the two sides are added together.

**History.** For each side, take the player's BPM over the current season and the two before it, weighted by minutes and by season:

- **Offense**: weights 1, .35 and .2, with 200 minutes of shrink.
- **Defense**: weights 1, .6 and .4, with 100 minutes of shrink.

The shrink pulls the weighted BPM toward the season's mean for players with fewer than 200 minutes. A freshman who played 150 minutes is mostly the low-minute average, and a senior with three full seasons is mostly himself. Defense keeps more of the older seasons than offense does.

**Fit.** The shrunk history goes into a regression on next-season BPM along with:

- **Class** (So, Jr, Sr, compared to Fr): the development curve. A freshman projects about a point better next season than a senior with the same history.
- **Minutes** (ln(1 + minutes / 100)).
- **Twelve box score rates**: steal rate, block rate, offensive and defensive rebound rate, assist rate, turnover rate, free throw rate, 3PA per 100, share of shots at the rim, usage, TS% and height. Each one is z-scored within its season and multiplied by minutes / (minutes + 200), so a 40-minute line can't move the projection much.

Rows are weighted by next-season minutes, and the box rates get a small ridge penalty. The fit uses every pair of seasons from 2008-09 to 2009-10 through 2024-25 to 2025-26. None of the 2026-27 season goes into it.

### What The Box Rates Add
BPM already uses most of these rates, so their weights in pXPM measure how much BPM over- or under-credits each one for the next season:

| Rate (per SD) | Offense | Defense |
| :--- | :---: | :---: |
| TS% | **−.45** | −.03 |
| Turnover rate | **+.31** | −.06 |
| Offensive rebound rate | **−.27** | **+.26** |
| Defensive rebound rate | +.22 | .00 |
| Usage | +.22 | −.07 |
| Assist rate | −.16 | **+.27** |
| Height | .00 | **+.27** |
| Block rate | +.11 | +.13 |
| 3PA per 100 | +.02 | +.11 |
| Steal rate | .01 | −.01 |

*Weights on next-season BPM after the player's own BPM history, per standard deviation of each rate, before the minutes factor (about .8 for a full season).*

Offense is where the box score regresses the most. Shooting efficiency is the least stable stat in the box score (it took 31 NBA games to reach a split-half r of .50, compared with 14 for XPM), so a player whose BPM was driven by a high TS% gives some of it back the next season. Usage and turnovers go the other way. A high-usage player with a lot of turnovers is usually the one creating the offense, and his BPM undersells how much of that carries over.

On defense, BPM doesn't give enough credit to size. Height, offensive rebounding, assists and blocks all predict a better defensive BPM the next season than the player's current defensive BPM does.

## Predicting The Next Season
I used the same harness as the November 24 metric audit:

- **Team test**: each player's value this season × his minutes next season, summed for the team and compared to the team's Barttorvik adjusted efficiency margin next season. Freshmen and other players with no line get the metric's average for low-minute players.
- **Player test**: correlation with the player's own BPM next season, for players with 300+ minutes in both seasons, weighted by minutes.

There are 14 season pairs (2012-13 to 2013-14 through 2024-25 to 2025-26). pXPM is walk-forward: each pair is predicted with a model fit only on the seasons before it, with its settings chosen inside those seasons.

| Metric | Next-season team R² (90% CI) | Player r with next BPM |
| :--- | :---: | :---: |
| xBPM (ARKBOARD projection, walk-forward) | **.735** | **.795** |
| **pXPM** | .732 (.720 to .743) | .770 |
| pXPM, history and class only | .727 | .763 |
| Stat+ | .662 | .669 |
| Total PRPG (O + D) | .656 | .616 |
| WAR rate (BPM + 2) | .648 | .680 |
| **BPM** | .643 (.625 to .660) | .680 |
| GBPM | .612 | .620 |
| PRPG! (offense) | .500 | .465 |

*90% intervals from 2,000 resamples of season pairs.*

pXPM beats BPM in all 14 season pairs (t = 15.7), and the player error falls from 3.41 points to 2.36. Most of that comes from using three seasons, the shrink and the class curve (.727 with no box rates). The box rates add the rest.

pXPM is not the best projection on the site, though. xBPM, the board's preseason projection of a player's BPM, is slightly ahead (.735 and .795). It uses everything pXPM uses plus recruiting rank, age and team context (returning teammates, the new team's talent and whether a transfer moved up or down a level). I also tested pXPM as one more input to xBPM, and it only moved the team R² from .7348 to .7353, which isn't enough to add it. So xBPM stays as the board's projected BPM.

## Where pXPM Is Used
Following the site's rule that anything that works in one model gets tested in the others, I tested pXPM in the three models that use last season's BPM.

### Preseason Team Ratings
The game model's preseason rating for each team uses a projection of every returning player's BPM. Replacing last-season BPM with pXPM in that projection:

| | Before | With pXPM |
| :--- | :---: | :---: |
| Next-season team R² | .757 | **.765** |
| Game margin MAE, 2016-20 | 9.2643 | **9.2618** |
| Game margin MAE, 2021-26 (held out) | 9.5915 | **9.5892** |

The team R² is better in 13 of 14 seasons (t = 4.1), and the game margin error is lower in 10 of 11 seasons (t = −2.6 in the tuning years, −2.8 held out). The gain is small because the preseason rating only matters early in the season, before game results take over, but it's consistent.

xBPM in the same spot is worse (.752). The preseason rating already has recruiting rank and transfer context, so xBPM counts them twice. pXPM only adds what the box score says about the player.

### FV
For returning players, the FV model picks its drivers by out-of-sample deviance. When pXPM is a candidate, the selection takes it ahead of last-season BPM, which drops out:

| | Before | With pXPM |
| :--- | :---: | :---: |
| Out-of-fold pseudo-R² (nested) | .105 | **.107** |
| FV range RPS | .0802 | **.0789** |
| Top-300 correlation with outcome, 2009-16 boards | .414 | **.431** |
| Realized FV of each board's top 50, 2017-19 boards (held out) | 39.0 | **39.6** |
| Top-300 correlation, 2017-19 boards (held out) | **.434** | .422 |

Head to head against 3-season BPM as a driver, pXPM wins in every fold of both splits (t = 2.5 and 3.1). The one check it doesn't win is the held-out top-300 correlation on the 2017-19 boards (better in 1 of 3), but the top 50 of those boards realized a higher FV, and the NBA AUC improved on every set of boards.

### NBA Mock Draft
The conviction mock projects career peak XPM from draft slot, 3-season BPM and age. pXPM in place of 3-season BPM was a tie (better in 8 of 15 drafts, t = 0.6), and the order of the mock was slightly worse, so the mock stays on 3-season BPM.

## Why There Is No rXPM
For the descriptive version, I tested three versions against GBPM, using each season's team win% held out one season at a time:

| Version | Held-out team win% R² |
| :--- | :---: |
| **GBPM** | **.658** |
| Best blend of BPM and GBPM, by side | .658 (it picks GBPM) |
| GBPM with BPM's team adjustment | .637 |
| Blend with the team adjustment | .636 |
| BPM | .633 |

The team adjustment is what made NBA rXPM the best descriptive metric, but in college it makes things worse. It forces a team's players to add up to its adjusted efficiency margin, and that is exactly what BPM already does, so the adjusted version falls back to BPM's level. GBPM, the average of a player's single-game BPMs, follows winning more closely, and it is already what CBB WAR is built on.

## 2025-26 Leaders

| Player | Team | Class | pXPM | O | D |
| :--- | :--- | :---: | :---: | :---: | :---: |
| Cameron Boozer | Duke | Fr | **16.0** | 10.1 | 5.9 |
| Aday Mara | Michigan | Jr | 13.3 | 4.0 | 9.3 |
| Allen Graves | Santa Clara | Fr | 13.2 | 7.8 | 5.4 |
| Joseph Tugler | Houston | Jr | 12.8 | 3.8 | 9.0 |
| Yaxel Lendeborg | Michigan | Sr | 12.6 | 7.4 | 5.3 |
| Zuby Ejiofor | St. John's | Sr | 12.6 | 6.1 | 6.5 |
| Caleb Wilson | North Carolina | Fr | 11.7 | 6.0 | 5.6 |
| Maliq Brown | Duke | Sr | 11.6 | 4.6 | 7.1 |
| Keaton Wagler | Illinois | Fr | 11.3 | 8.7 | 2.6 |
| Patrick Ngongba | Duke | So | 11.3 | 5.2 | 6.1 |

*Projected BPM for 2026-27 from lines through 2025-26, 500+ minutes.*

Most of this list is gone to the NBA or out of eligibility, which is the point of the FV and team rating inputs: pXPM is a number about next season, and for the players who come back (Tugler and Ngongba here), it now feeds the board's FV and their teams' preseason ratings.

The formula, the coefficients and every test are in the Process tab under pXPM (CBB), and the research scripts are in the site's repository under scripts/research/cbb_xpm_nov26.
