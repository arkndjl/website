+++
title = "Introducing XPM: Predictiveness, Stability, & Formulation Process"
date = "2026-11-24T14:00:42-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["nba", "statistics"]
keywords = ["xpm", "rxpm", "pxpm", "stabilization", "plus-minus", "nba", "basketball", "statistics"]
description = "How XPM is built from BPM and DPM, how fast it stabilizes, and how rXPM (descriptive) and pXPM (predictive) compare with BPM, DPM, xRAPM, LEBRON, RAPM, HAPM and on/off."
showFullContent = false
readingTime = false
hideComments = true
draft = false
aliases = ["/posts/xpm-stabilization/"]
Toc = true
+++

XPM (Cross Plus-Minus) is an all-in-one NBA impact metric, measured in points per 100 possessions above an average player. There are two versions of it. rXPM is the descriptive version, and it measures what a player did in a given season. pXPM is the predictive version, and it is a projection of what a player will do the following season.

In this article I will go through how XPM is built, how many games it takes to stabilize, and how it compares to the other public metrics at describing a season and predicting the next one. Out of the metrics I tested (BPM, DPM, xRAPM, LEBRON, one-year RAPM, HAPM, on-court +/- and on/off), rXPM had the closest fit to a team's net rating in the same season. pXPM was the best at predicting the next season out of the metrics with no look-ahead in their historical values, and second overall behind xRAPM, whose historical values were fit with later seasons available. EPM is not included, since its historical values are behind a paywall and its terms don't allow scraping.

## Formulation
### Inputs
XPM is built from two existing metrics:

- **BPM** (Basketball Reference): a regression of plus-minus on box score rates, with a team adjustment so that a team's players add up to its rating.
- **DPM** (databallr): a plus-minus model built on RAPM, with box score priors.

The two metrics have different weaknesses. BPM only uses the box score, so it misses defensive and off-ball value that doesn't show up in a stat line. DPM uses lineup data, so it picks up that value, but it also picks up more of the noise that comes with plus-minus data. Averaging the two offsets some of the error in each.

### Why a 50/50 blend
To decide how to combine them, I tested the blend against BPM and DPM on their own, and against every model I could build on top of the blend, using 480 team-seasons from 2011 to 2026. For each team-season, each player's rating from the prior season(s) is multiplied by his actual minutes that season, and the total is used to predict the team's net rating. Every metric gets the same calibration (scale, replacement value and rookie value), fit only on the training seasons.

| Metric | Net rating RMSE (forward, 1-yr prior) | Net rating RMSE (leave one season out, 2-yr prior) | r with W% |
| :--- | :---: | :---: | :---: |
| **BPM/DPM 50/50 blend** | **3.016** | 2.931 | **.811** |
| Blend + box score ridge correction | 3.028 | 2.915 | .807 |
| Blend with team-anchored defense | 3.027 | 2.927 | .806 |
| BPM | 3.033 | 2.947 | .805 |
| DPM | 3.106 | 2.960 | .800 |
| Box score + on/off ridge model | 3.214 | 2.963 | .777 |

*Points per 100 possessions. Head-to-head comparisons use a season-block bootstrap (4,000 draws).*

The blend beat both of its inputs. The probability that DPM alone is better than the blend was .005 to .007, and for BPM alone it was .08 to .29.

None of the models built on top of the blend held up. A ridge model on box score stats and on/off data was clearly worse than the blend, since box score and on/off data alone can't match the RAPM base that DPM has. A box score correction added to the blend shrank to almost nothing when fit. Freely fitted weights on OBPM, ODPM, DBPM and DDPM were noisier than a fixed 50/50 split. The two closest models were coin flips against the blend (probability of being better between .30 and .67), so the simpler blend stays.

I also checked the weight itself at the player level. The blend that best predicts both a player's next-season BPM and next-season DPM is 40 to 50% BPM (average r of .757 at 40% and .756 at 50%). DPM is better at predicting a player's own next season, and BPM is better at matching team totals, so 50/50 is the split that balances the two.

Offense and defense are blended the same way: **O-XPM = .5 OBPM + .5 ODPM** and **D-XPM = .5 DBPM + .5 DDPM**. A player without a DPM value uses BPM alone.

### rXPM: the team adjustment
rXPM is the 50/50 blend plus a team adjustment, using the same approach as BPM. Every player on a team is shifted by the same amount on offense and the same amount on defense, so that:

- 5 × (minutes-weighted O-XPM) = team ORtg − league ORtg
- 5 × (minutes-weighted D-XPM) = league DRtg − team DRtg

A player who was traded during the season gets each team's adjustment in proportion to the minutes he played there. The adjustment gives more credit to players on teams that played better than their box scores suggest, and as shown further down, it improves next-season prediction in addition to the same-season fit.

### pXPM: from rXPM to a projection
**pXPM** = (200 × μ + MP × XPM + .35 × MP₋₁ × XPM₋₁ + .1 × MP₋₂ × XPM₋₂) / (200 + MP + .35 × MP₋₁ + .1 × MP₋₂) + aging

- **Seasons**: the current season and the two before it, weighted by minutes at 1, .35 and .1.
- **Shrink**: 200 minutes of a role mean, μ = −2 + ln(1 + MP82 / 100), where MP82 is minutes on an 82-game pace. A player with 300 minutes starts well below average, and a player with 2,500 minutes starts slightly above average.
- **Aging**: the average change in XPM from one season to the next at the player's next age. It is a quadratic in age, weighted by the harmonic mean of the two seasons' minutes, and fit only on seasons before the one being projected.

pXPM uses the blend before the team adjustment. Adding the team adjustment to pXPM raised its team R² from .657 to .670, but it made the next-season player error worse (1.185 to 1.198), and the player error is the target pXPM is fit to. Every pXPM setting was chosen on next-season player XPM, holding out one season at a time (2011-26). The reason the shrink is 200 minutes comes from the stability study, covered in "From Padding To pXPM" below.

## Stability
Every stat is part signal and part noise. The signal is the player's true talent, and the noise is everything else: the opponents, the shooting variance, a hot or cold stretch. Early in a season the noise makes up more of a player's numbers, and late in a season the signal does. So before using any stat, it is important to know how many games it takes before the stat tells us more about the player than about the sample.

Baseball has had an answer to this for over a decade. Russell Carleton's work on stat reliability showed that strikeout rate becomes reliable after about 60 plate appearances, while BABIP needs closer to 800 balls in play. Hockey followed with Blackport's work on shot metrics. Basketball has been behind on this, especially for the plus-minus family of metrics. LumaHoops published a [working paper on the stabilization of NBA plus-minus metrics](https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics) that measures this for on-court +/-, WOWY, RAPM, BPM and their own models. I ran the same tests on XPM.

### The Method
I used the same split-half approach as Carleton and LumaHoops. For each team, take its first 2k games of the season and split them into odd and even games, so each half has k games. Compute each player's value on the odd half and on the even half, and correlate the two across every player in the league. If a stat mostly reflects talent, a player who is good in the odd games will also be good in the even games, and the correlation will be high. If a stat is mostly noise, the two halves won't agree.

The thresholds follow the LumaHoops paper:

| r | Meaning |
| :---: | :--- |
| .50 | **Provisionally stable**: signal and noise carry equal weight |
| .75 | **Stable**: signal is three times the noise |

The .50 point is also the "padding", which is the amount of league-average performance to add to a player's line to regress him properly. At .50, a player's own numbers and the league average get equal weight, so the stat should be shrunk halfway to average. This is also what sets the shrink in pXPM.

To find the number of games to .50, I used the Spearman-Brown relationship, r(k) = k / (k + M), where M is the padding in games, and took the median M across windows of 10 to 41 games per half.

The sample is every regular season from 2013-14 to 2025-26, leaving out the shortened 2019-20 and 2020-21 seasons, using ESPN box scores. A player needs 5+ minutes per team game in each half (about 10 possessions, the same minimum LumaHoops uses), which gives about 3,400 to 4,100 player-seasons per window.

**Box XPM** is the game-level version of XPM. The full XPM blends BPM with DPM and only exists for a full season, so for single games I use a ridge fit of season XPM on per-48 box score rates (relative to the league), with the weights fit only on seasons before the one being measured, so there is no look-ahead.

### How Fast Does XPM Stabilize?

| Metric | Games to .50 (90% CI) | Minutes | Possessions | Games to .75 |
| :--- | :---: | :---: | :---: | :---: |
| **Box XPM** | **14** (13 to 14) | 230 | 490 | 41 |
| On-court +/- | 28 (25 to 32) | 480 | 1,000 | 84 |

*Intervals come from 2,000 resamples of seasons. Possessions use the league's 2.07 possessions per player-minute.*

XPM is provisionally stable after about 14 games, or about 230 minutes. Raw on-court +/- needs twice as many, 28 games, because it includes the noise from the other nine players on the floor in addition to the player's own.

The on-court result also works as a check on the method. LumaHoops found 30 games (1,320 possessions) for on-court +/- over nearly the same seasons, and I found 28. For box score metrics, they found BPM stable at 10 games and 450 possessions, and box XPM is stable at 14 games and 490 possessions, which is very close.

Here is the split-half correlation by window:

| Games per half | 5 | 10 | 15 | 20 | 25 | 30 | 41 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Box XPM** | .30 | .46 | .54 | .60 | .64 | .68 | .71 |
| On-court +/- | .20 | .31 | .37 | .43 | .46 | .50 | .56 |

{{< postchart "xpm-splithalf" >}}

Spearman-Brown predicts that XPM should reach .75 at 41 games per half, which is a full 82-game season, but it actually tops out at .71. The implied padding also increases as the window gets larger (12 games at k = 10, 17 at k = 41). This is because players actually change within a season: they get hurt, change roles, get traded and improve, so the two halves drift apart a little faster than sampling alone would predict. Within a single season, XPM doesn't quite reach the .75 "stable" threshold.

### The Box Score, Stat By Stat
Since XPM is built on box score rates, the next step is to look at which of those rates stabilize quickly and which don't.

| Stat | Games to .50 | Minutes | Games to .75 |
| :--- | :---: | :---: | :---: |
| 3PA rate (3PA / FGA) | 1 | 10 | 2 |
| AST/48 | 2 | 30 | 6 |
| PTS/48 | 3 | 50 | 9 |
| OREB/48 | 3 | 50 | 9 |
| DREB/48 | 3 | 50 | 9 |
| BLK/48 | 5 | 80 | 14 |
| TOV/48 | 8 | 140 | 25 |
| PF/48 | 8 | 140 | 25 |
| **Box XPM** | **14** | **230** | **41** |
| STL/48 | 18 | 310 | 53 |
| On-court +/- | 28 | 480 | 84 |
| TS% | 31 | 540 | 93 |

{{< postchart "xpm-stats" >}}

The box score stats fall into two groups. Role stats, like shot selection (3PA rate), assists, scoring volume and rebounding, stabilize within a week, because they are mostly determined by what a player is asked to do. A center will rebound like a center from his first game.

Stats that depend on the outcome of a skill take much longer. Steals take 18 games, and shooting efficiency (TS%) takes 31, which is longer than raw on-court +/-. This is similar to BABIP in baseball, where whether the ball goes in is a real skill, but there is a lot of variance around it in a small sample.

XPM falls in between, at 14 games, since it combines both groups. Its early stability comes from the role stats, and most of its value comes from the efficiency stats. This is also why a hot shooting month can move a player's rXPM significantly, and why pXPM is needed for projection.

## Descriptiveness And Predictiveness
A stat can be stable without being useful (a player's height is very stable), so the next question is whether XPM actually tracks winning. I used the same describe/predict setup as the LumaHoops paper:

- **Describe**: a player's season value × his share of his team's minutes (× 5), summed across the roster, compared to the team's net rating that same season.
- **Predict**: this season's values × next season's minutes, compared to next season's net rating. This measures how well last season's values, applied to next season's roster, predict how good the team is next season. Players with no value from the previous season (rookies and returning players) get the metric's average for low-minute players.

Every metric is scored on the same nine season pairs (2013-14 to 2014-15 through 2024-25 to 2025-26, leaving out the shortened 2019-20 and 2020-21 seasons), with no refitting. RAPM's public data ends in 2022-23, so it only has seven pairs.

| Metric | Describe R² | Predict R² (90% CI) | P(better than rXPM) |
| :--- | :---: | :---: | :---: |
| xRAPM | .958 | **.663 (.63 to .70)** | .83 |
| **pXPM** | .922 | .657 (.63 to .70) | .75 |
| **rXPM** | **.999** | .647 (.60 to .70) | |
| BPM | .988 | .644 (.61 to .69) | .38 |
| DPM | .875 | .623 (.58 to .67) | .03 |
| LEBRON | .898 | .599 (.56 to .64) | .03 |
| RAPM (1-yr) | .987 | .569 (.53 to .62) | |
| HAPM (1-yr) | .767 | .563 (.52 to .61) | .00 |
| On-court +/- | .994 | .481 (.42 to .55) | .00 |
| On/off | .239 | .373 (.32 to .43) | .00 |

*90% intervals and P(better) come from 2,000 resamples of season pairs, with every metric scored on the same resamples. pXPM's settings were chosen on next-season player XPM, not on this test. With its settings refit while holding out each season, pXPM scores .654.*

{{< postchart "xpm-predict" >}}

rXPM has the highest describe R² of the metrics tested at .999, ahead of on-court +/- (.994), BPM (.988) and one-year RAPM (.987). This is mostly due to the team adjustment, which makes a team's rXPM add up to its net rating, the same way BPM and on-court +/- do. Without the adjustment, the BPM/DPM blend describes at .963. Because a high describe score can be built in this way, the predict column is the more important test.

The team adjustment also improves prediction. It raises rXPM's next-season R² from .640 to .647, and the adjusted version is better in 97% of resamples. This puts rXPM above BPM (.644) and DPM (.623), although rXPM and BPM are close (BPM is better in 38% of resamples).

xRAPM has the highest predict R² at .663, with pXPM second at .657, ahead of rXPM, BPM, DPM, LEBRON, RAPM, HAPM and both on/off measures. The gap between xRAPM and pXPM is small (pXPM is better in 37% of resamples and in 3 of the 9 season pairs), and xRAPM's historical values were fit with later seasons available (see below), so its score is likely a little high. Out of the metrics with no look-ahead, pXPM is first. At the team level its margin over rXPM is small (better in 75% of resamples), but at the player level, which is what pXPM is fit to, the gap is much larger (see the next section).

On-court +/- describes its own season almost perfectly (.994), since team net rating is the minutes-weighted sum of its players' on-court numbers, but it drops to .48 when predicting the next season, below every box score-based metric. The metrics that take the longest to stabilize (on/off, on-court +/- and one-year RAPM) are also the worst at predicting, which matches the conclusion of the LumaHoops paper with a different test and data set.

It is also worth noting that the xRAPM, LEBRON and HAPM histories were fit with later seasons available (for xRAPM, the box score prior's weights were fit on the full history of APM), so their past values have some look-ahead built in. XPM, BPM and DPM do not. xRAPM values come from the season pages on xrapm.com, matched to Basketball Reference ids (99.6% to 100% of minutes matched).

## From Padding To pXPM
pXPM uses a 200-minute shrink because that matches the stabilization point.

The within-season padding is about 230 minutes, which is the point where a player's own XPM and the average get equal weight. That only accounts for sampling noise. From one season to the next there is also real change from aging, role changes, new teammates and injuries. Season box XPM has a year-to-year correlation of **r = .75** (2,427 player pairs with 500+ minutes in both seasons). Removing the sampling noise using the 230-minute padding gives a true-talent year-to-year correlation of about **.87**.

Combining both into a single shrink gives **.87 × MP / (MP + 230)**, which is a weight of .78 for a player with 2,000 minutes. A single shrink with k = 600 gives almost the same weight (2,000 / 2,600 = .77), and k = 600 is what a single-shrink pXPM picks when it is fit, in every held-out fold.

{{< postchart "xpm-shrink" >}}

With a single shrink, the one parameter has to account for both the sampling noise and the year-to-year change. Most of the year-to-year change comes from aging, and some of it can be seen in the previous seasons. When aging and the previous seasons are included as separate terms, the shrink only has to account for sampling noise, and the fit lands at **200 minutes**, close to the 230-minute padding. All 15 held-out folds chose 200 minutes and the full aging curve, and 9 of the 15 chose every setting exactly as used.

| | Next-season RMSE | Next-season team R² |
| :--- | :---: | :---: |
| BPM | 1.95 | .644 |
| XPM blend (no shrink) | 1.58 | .640 |
| DPM | 1.38 | .623 |
| Single shrink (k = 600) | 1.24 | .619 |
| **pXPM** | **1.19** | **.654** |

*Next-season XPM, 2011-26, leaving out one season at a time. Team R² for pXPM is held out.*

{{< postchart "xpm-rmse" >}}

pXPM beats the single-shrink version in 14 of 15 seasons (paired t = −7.3), and it is better on both the player and team tests. The difference is largest for small samples: for players under 100 minutes, the raw next-season error is above 7 points.

To see which part of pXPM matters most, I removed each part one at a time:

| Without | Next-season RMSE | Next-season team R² |
| :--- | :---: | :---: |
| nothing (pXPM) | 1.185 | .657 |
| aging | 1.250 | .633 |
| the two previous seasons | 1.238 | .661 |
| the role mean slope | 1.187 | .648 |
| the 200-minute shrink (600 instead) | 1.223 | .654 |

Aging matters the most on both tests. The two previous seasons help the player projection but not the team test, likely because the team test already uses next season's minutes, which contain a lot of the same information. The role mean slope mostly helps the team test, since it keeps low-minute players from being treated as average players.

## What Didn't Work
| Test | Result |
| :--- | :--- |
| Separate shrink for offense and defense | RMSE 1.2357 vs 1.2357, better in 6 of 15 seasons. **Fail.** |
| More BPM in the blend (rXPM) | Next-season player r is highest at 40 to 50% BPM (.757 vs .756 at 50/50). More BPM only improves the team test, by .001. **Fail.** |
| More BPM inside pXPM (.4 to .7) | At most +.001 team R², with a worse player error. **Fail.** |
| Team adjustment inside pXPM | Team R² .657 to .670, but next-season player error 1.185 to 1.198. **Fail**, since player error is pXPM's target. |

A separate shrink for offense and defense didn't help, because both sides of XPM are already built from a mix of fast- and slow-stabilizing stats, so the noise from steals and TS% is already averaged in before the shrink.

## Summary
- **Formulation**: rXPM is a 50/50 blend of BPM and DPM, with offense and defense blended the same way, plus BPM's team adjustment. Over 480 team-seasons, the blend beat both of its inputs and every model built on top of it.
- **pXPM** uses three seasons of the blend, weighted 1, .35 and .1 by minutes, shrunk 200 minutes toward a role mean, plus aging.
- XPM is **provisionally stable after about 14 games** (230 minutes, 490 possessions), twice as fast as on-court +/- (28 games) and close to BPM in the LumaHoops paper. Within a single season it reaches a split-half reliability of **.71**.
- **Role stats** (shot selection, assists, rebounding, scoring volume) stabilize within a week. **TS%** (31 games) and **steals** (18 games) take the longest.
- **rXPM** had the highest same-season team R² of the metrics tested (.999), and it predicted the next season better than BPM, DPM, LEBRON, RAPM and HAPM.
- **pXPM** was the most predictive metric tested with no look-ahead: next-season team R² of .657 (.654 held out), second to xRAPM (.663) overall, and next-season player error of 1.19, compared to 1.38 for DPM, 1.58 for the unshrunk blend and 1.95 for BPM.
- pXPM's **200-minute shrink matches the 230-minute stabilization point**, with aging and the two previous seasons accounting for the year-to-year change.

**Works Cited**
Awoyemi, A. (2026). Stabilization of NBA Plus-Minus Metrics (Working paper v1). LUMA Basketball Research. [https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics](https://lumahoops.org/research/stabilization-of-nba-plus-minus-metrics)

Carleton, R. (2012). Baseball Therapy: It's a Small Sample Size After All. *Baseball Prospectus*.

Blackport, D. (2014). Shot metric reliability. *Hockey-Graphs*.

Medvedovsky, K. (2020). On-court plus-minus padding (as cited in Awoyemi, 2026).

Data: ESPN box scores; Basketball Reference (BPM, on-court and on/off); DPM; xRAPM (xrapm.com); LEBRON (BBall Index via nbarapm.com); one-year RAPM (gabriel1200); HAPM (LumaHoops, CC BY 4.0). Code ([github.com/arkndjl/website](https://github.com/arkndjl/website)): `scripts/nba_xpm_stability_research.py`, `scripts/nba_xpm_predictive_research.py`, `scripts/nba_rxpm_research.py`, `scripts/nba_pxpm_research.py`.
