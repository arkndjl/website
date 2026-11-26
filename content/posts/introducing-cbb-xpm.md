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

XPM (Cross Plus-Minus) for college basketball is a projection of a player's BPM for the following season, in points per 100 possessions above an average D-I player, split into offense and defense. It is built from a player's last three seasons of Barttorvik BPM and his box score rates.

The NBA version of XPM has two versions. rXPM is the descriptive version, and pXPM is the predictive version. I tried to build both for college basketball. pXPM was much better than BPM at predicting the next season. rXPM was not better than Barttorvik's game BPM (GBPM), which the site already uses for WAR, so there is no college rXPM. Season value on the College Basketball ARKBOARD stays on GBPM-based WAR, and pXPM is used in the FV model and in the preseason team ratings in the game model.

In this article I will go through why the NBA version can't be used for college, how pXPM is built, how it compares to the public college metrics at predicting the next season, and where it is used on the site.

## Why Not Copy The NBA Version
NBA XPM is a 50/50 blend of BPM and databallr's DPM, and DPM is built on RAPM. The RAPM base is what lets it pick up defensive and off-ball value that the box score misses. College basketball doesn't have that:

- **No public college DPM or RAPM.** EvanMiya and KenPom player data is paid.
- **Lineup data is thin.** ESPN's college play-by-play has no substitutions. NCAA.com's play-by-play does, but only for about half of 2024-25 games and almost all of 2025-26. That is two seasons, not enough for a backtest.
- **I already tried a RAPM prior.** In early November I built a college XPM as Barttorvik BPM plus a ridge RAPM adjustment from those two seasons of lineups. It was worse than BPM alone at predicting held-out game margins at every penalty I tried, so the best weight on the lineup data was zero.

This means college XPM has to be built from the box score. BPM is already a regression on the box score, so rebuilding it from the same stats would not add much. The part that can be improved is projection, since BPM is a measure of one season and is not fit to predict the next one.

## Formulation
pXPM is built separately for offense and defense, and the two sides are added together.

**History.** For each side, take the player's BPM over the current season and the two before it, weighted by minutes and by season:

- **Offense**: weights 1, .35 and .2, with 200 minutes of shrink.
- **Defense**: weights 1, .6 and .4, with 100 minutes of shrink.

The shrink pulls the weighted BPM toward the season's average for players with fewer than 200 minutes. A freshman who played 150 minutes gets slightly more weight on that average than on his own BPM, and a senior with three full seasons gets almost all of the weight on his own BPM. Defense puts more weight on the older seasons than offense does, since defensive BPM from a single season is less stable.

**Fit.** The shrunk history goes into a regression on next-season BPM along with:

- **Class** (So, Jr, Sr, compared to Fr): this accounts for development. A freshman projects about a point better the next season than a senior with the same history.
- **Minutes** (ln(1 + minutes / 100)).
- **Twelve box score rates**: steal rate, block rate, offensive and defensive rebound rate, assist rate, turnover rate, free throw rate, 3PA per 100, share of shots at the rim, usage, TS% and height. Each one is z-scored within its season and multiplied by minutes / (minutes + 200), so a 40-minute line can't move the projection much.

Each player is weighted by his minutes the next season, and the box rates have a small ridge penalty. The fit uses every pair of seasons from 2008-09 to 2009-10 through 2024-25 to 2025-26, and nothing from the 2026-27 season is used.

### What The Box Rates Add
BPM already uses most of these rates, so their weights in pXPM show how much BPM gives too much or too little credit to each one when predicting the next season:

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

The largest weight is on TS%. Shooting efficiency is the least stable stat in the box score (in the NBA it took 31 games to reach a split-half r of .50, compared to 14 for XPM), so a player whose BPM was high because of his TS% will usually lose some of it the next season. Usage and turnovers have the opposite sign. A high-usage player with a lot of turnovers is usually the one creating the offense, and more of his value carries over to the next season than his BPM shows.

On defense, BPM doesn't give enough credit to size. Height, offensive rebounding, assists and blocks all predict a better defensive BPM the next season than the player's current defensive BPM shows.

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

pXPM is better than BPM in all 14 season pairs (t = 15.7), and the player error goes from 3.41 points to 2.36. Most of the improvement comes from using three seasons, the shrink and the class terms (.727 without the box rates), and the box rates add the rest.

xBPM, the board's preseason projection of a player's BPM, is slightly better than pXPM (.735 and .795). It uses everything pXPM uses, plus recruiting rank, age and team context (returning teammates, the new team's talent and whether a transfer moved up or down a level). I also tested pXPM as an input to xBPM, and it only raised the team R² from .7348 to .7353, which isn't enough to add it, so xBPM stays as the board's projected BPM.

## Where pXPM Is Used
I tested pXPM in the three models on the site that use a player's BPM from the previous season.

### Preseason Team Ratings
The game model's preseason rating for each team uses a projection of every returning player's BPM. Replacing last-season BPM with pXPM in that projection:

| | Before | With pXPM |
| :--- | :---: | :---: |
| Next-season team R² | .757 | **.765** |
| Game margin MAE, 2016-20 | 9.2643 | **9.2618** |
| Game margin MAE, 2021-26 (held out) | 9.5915 | **9.5892** |

The team R² is better in 13 of 14 seasons (t = 4.1), and the game margin error is lower in 10 of 11 seasons (t = −2.6 in the seasons used to fit it, −2.8 held out). The improvement in game margins is small, since the preseason rating only has much weight early in the season, before the model has many game results for each team.

Using xBPM in place of pXPM here is worse (.752). The preseason rating already includes recruiting rank and transfer context, so xBPM counts them twice, while pXPM only adds information from the box score.

### FV
For returning players, the FV model picks its drivers by out-of-sample deviance. When pXPM is a candidate, the selection takes it ahead of last-season BPM, which drops out:

| | Before | With pXPM |
| :--- | :---: | :---: |
| Out-of-fold pseudo-R² (nested) | .105 | **.107** |
| FV range RPS | .0802 | **.0789** |
| Top-300 correlation with outcome, 2009-16 boards | .414 | **.431** |
| Realized FV of each board's top 50, 2017-19 boards (held out) | 39.0 | **39.6** |
| Top-300 correlation, 2017-19 boards (held out) | **.434** | .422 |

Head to head against 3-season BPM as a driver, pXPM is better in every fold of both splits (t = 2.5 and 3.1). The only test it is worse on is the held-out top-300 correlation on the 2017-19 boards (better in 1 of 3 boards). The top 50 of those boards had a higher realized FV, and the AUC for reaching the NBA was higher on every set of boards.

### NBA Mock Draft
The conviction mock projects career peak XPM from draft slot, 3-season BPM and age. Using pXPM in place of 3-season BPM was about even (better in 8 of 15 drafts, t = 0.6), and the order of the mock was slightly worse, so the mock stays on 3-season BPM.

## Why There Is No rXPM
For the descriptive version, I tested three versions against GBPM, using each season's team win% held out one season at a time:

| Version | Held-out team win% R² |
| :--- | :---: |
| **GBPM** | **.658** |
| Best blend of BPM and GBPM, by side | .658 (it picks GBPM) |
| GBPM with BPM's team adjustment | .637 |
| Blend with the team adjustment | .636 |
| BPM | .633 |

In the NBA, the team adjustment is what made rXPM the best descriptive metric, but in college it makes the fit worse. It makes a team's players add up to its adjusted efficiency margin, which BPM already does, so the adjusted version ends up at about the same level as BPM. GBPM, the average of a player's single-game BPMs, has a closer fit to winning, and it is already what CBB WAR is built on.

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

Most of the players on this list are now in the NBA or out of eligibility. For the players who returned (Tugler and Ngongba here), pXPM is used in their FV and in their teams' preseason ratings.

The formula, coefficients and test results are in the Process tab under pXPM (CBB), and the research scripts are in the site's repository under scripts/research/cbb_xpm_nov26.
