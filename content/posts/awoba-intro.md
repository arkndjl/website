+++
title = "aWOBA Introduction (Best MLB Hitters of 2025)"
date = "2025-12-04T15:44:42-06:00"
#dateFormat = "2006-01-02" # This value can be configured for per-post date formatting
author = "ndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["mlb", "statistics"]
keywords = ["awoba", "mlb", "baseball", "statistics"]
description = "An introduction to aWOBA and how this stacks up to the best hitters of the 2025 MLB season."
showFullContent = false
readingTime = false
hideComments = true
draft = false
+++

[Reading](https://web.archive.org/web/20230225050336/https://www.seanlahman.com/baseball-archive/sabermetrics/sabermetric-manifesto/)
## wOBA, xWOBA, and their flaws
### Notes
- There is a clear relationship between a team’s runs scored and allowed and its wins and losses. This relationship isn’t perfect, but it is very strong. A good formula, determined empirically from the data by Bill James, is that a team’s ratio of wins to losses will be equal to the square of the ratio between its runs scored and allowed.

Rank your top five hitters (ignoring defensive and baserunning contributions) based on last season’s performance, with an explanation of how you arrived at your rankings.

In order to identify the top five hitters in the league based on last season’s performance, it is imperative to use the least-flawed metrics for the purpose of identifying hitting production. By far the most evolved outcome-based hitting metric is wOBA, which accounts for the linear weight of each offensive outcome, giving more weight to extra base hits than singles/walks, while simultaneously retaining the importance of walks and singles (compared to other stats like batting average, which doesn’t account for walks/OBP, or OBP, which doesn’t account for the higher value of extra base hits)

However, to truly identify the best hitters of the past season, it is not enough to just sort by wOBA to identify the best hitters based on outcome. Hitters, due to a combination of luck, park factors, weather factors, and infinitely other variables, may be HITTING the ball better than their counterparts, and experiencing worse results. This is where the metric of xWOBA comes in, or the expected wOBA of a hitter based on the expected linear weight result of their offensive production using batting data.

xWOBA has its own flaws, as it fails to account for certain non luck-based outcomes that WOBA does. For example, if a hitter has a particular aptitude for hitting against the shift, or identifying corner infielders playing too far back in order to bunt for a base hit, their xWOBA will be affected negatively, but their WOBA won’t. 

Because of these factors, it is key to use a combination of WOBA and xWOBA to equally account for the luckiness of certain outcomes that would penalize a hitter’s WOBA, while also accounting for intentionally “unexpected” productive outcomes that xWOBA would penalize. 


## Creating aWOBA
Because WOBA represents a player’s tangible production, and xWOBA represents a player’s hypothetically expected production, both are valuable, and both should be equally weighted in the evaluation of a hitter’s production over the past year. In order to this, I will be using “mWOBA” to represent the averaged WOBA value between WOBA and xWOBA. The formula is simple: 

**aWOBA**: (WOBA + xWOBA) / 2

There are still flaws in mWOBA in measuring offensive production, as it doesn’t measure baserunning skill. Additionally, it is a context neutral stat that doesn’t account for win probability or certain hits being more valuable than others in specific situations (ex. a pop fly to the warning track is valuable with a runner on third with one out or less, as it will allow the runner to score via tagging to home, but is effectively equal to any other out if there are no runners on base). However, we will be ignoring baserunning contributions for this exercise, and based on the large sample size of a full season compared to the smaller sample size of context-specific scenarios, we will be ignoring the situational value of specific hits in order to more accurately capture the best hitters over an entire season’s body of work. 

So, to summarize: WOBA and xWOBA are the best metrics for evaluating a hitter’s actual and expected hitting production over the course of a season. We average these together into aWOBA in order to account for the deficiencies in each statistic, while still weighting them equally. We are ignoring baserunning and defensive production for this exercise, so aWOBA will work for our purposes of simply measuring hitting production over the course of a season, as it provides the average of both the actualized production of each hitter and the expected production of each hitter. Further theorizing and experimentation should be done in order to adapt aWOBA for context-dependent purposes, but for this purpose, we will not be accounting for situational or context-based outcomes, just purely measuring the hitting production of each hitter using the average of actual linearly-weighted outcomes and expected linearly-weighted outcomes. 

We will be using a plate appearance / at bat minimum in order to eliminate batters with fewer plate appearances/at bats, as their sample size is not large enough to draw conclusions about them as hitters, especially not as top 5 hitters in the league. Per [FanGraphs](https://library.fangraphs.com/principles/sample-size/), different outcomes have different “stabilization” rates that allow them to be utilized analytically as a sample size. Singles are the limiting variable here, as they have the highest stabilization point out of all statistics in both the WOBA and xWOBA formulas at 290 PA. So, we’ll set the minimum plate appearances at 300. 


We will be using only the 2025 regular season as a basis for our stats, as the postseason is not a large enough sample size to measure hitting production, and has far too many independent variables compared to the reliability of regular season statistics (ex. series format, pitching strategy).

[aWOBA 2025 spreadsheet](https://docs.google.com/spreadsheets/d/1gyvKhuwPhRo6U7o8AYladYRxAa9KrCst8tcSTyQf8sM/edit?gid=0#gid=0)

///

In order to identify my top five hitters in the league based on last season’s performance, it is imperative to use the least-flawed metrics for the purpose of identifying hitting production. In my opinion, WOBA and xWOBA are the most accurate outcome-based and expectation-based stats, accordingly, as they account for the weight of extra base hits linearly while also accounting for the value of getting on base, making it a better and more reliable metric for this exercise than any of AVG, SLG, or OBP, as WOBA/xWOBA encompass all of these statistics while adjusting for the flaws in each. However, there are flaws in both WOBA and xWOBA as well. I created my own metric, "aWOBA", which is the average of WOBA and xWOBA, to account for these flaws. I am averaging these metrics in order to find a clear middle ground between actual outcome and expected outcome, in order to better account for luck-based penalties to WOBA (ex. a rocket hit to left-center that is recorded as an out due to an incredible defensive play, but had an extremely high expected WOBA, hitting is not entirely outcome dependent) and situational-based penalties to xWOBA (ex. hitters who specialize against the shift or situationally drag bunt for hits, hitting is not entirely expectation dependent).

The equation for aWOBA is simple: (wOBA + xWOBA) / 2

aWOBA averages these two metrics in order to create the clearest possible picture of a player's linearly weighted on base average, equally dependent on both the actualized production the hitter provided and the expected production that the hitter provided, to truly capture how well hitters hit the ball this past season. 

Defense and baserunning contributions are ignored in this exercise, so I didn't factor them in. Per [FanGraphs](https://library.fangraphs.com/principles/sample-size/), different outcomes have different “stabilization” rates that allow them to be utilized analytically as a sample size. Singles are the limiting variable here, as they have the highest stabilization point out of all statistics in both the WOBA and xWOBA formulas at 290 PA. So, we’ll set the minimum plate appearances to qualify for my aWOBA leaderboard at 300. 

## aWOBA’s Best Hitters of 2025
We will be using only the 2025 regular season as a basis for our stats, as the postseason is not a large enough sample size to measure hitting production, and has far too many independent variables compared to the reliability of regular season statistics (ex. series format, pitching strategy).

So, with all of that being said, here are my top 5 hitters of the 2025 MLB season, based on aWOBA, with their plate appearances included: 

- Aaron Judge was the overall leader in aWOBA by a significant margin, as he recorded a .4605 aWOBA across 679 plate appearances, and as such, was the best hitter of 2025 based on my analysis.
- Shohei Ohtani was second in aWOBA, recording a 0.4205 aWOBA across 727 PA.
- Juan Soto was third in aWOBA, recording a 0.4085 aWOBA across 715 PA.
- George Springer was fourth in aWOBA, recoridng a 0.406 aWOBA across 576 PA.
- Ronald Acuña Jr. was fifth in aWOBA, recording a 0.399 aWOBA across 412 PA.

- **HM** (6th): Kyle Schwarber, PHI: 0.3965 aWOBA / 724 PA
- **HM** (7th): Nick Kurtz, ATH: 0.395 aWOBA / 489 PA

Because we created a minimum sample size of 300 PA based on FanGraphs analysis of stabilization rates of plate appearance sample sizes, Schwarber and Kurtz will remain ranked at 6th and 7th, despite them recording higher plate appearances than Springer/Acuña. I wanted to put them here honorable mentions because the difference between their aWOBA and Acuña's aWOBA is extremely small, so there is an argument that Schwarber and/or Kurtz were better hitters than Acuña last year due to having an almost identical aWOBA with more plate appearances. However, I believe that the stabilization rate minimum of 300 PA accounts for this, so I will be trusting my created aWOBA metric under these parameters and still giving the edge to Acuña.


