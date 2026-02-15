+++
title = "The State Of Analytics Across Team Sports"
date = "2026-02-14T17:30:42-06:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["sports", "statistics"]
keywords = ["statistics"]
description = "My analysis of the state of data analytics across team sports (baseball, basketball, hockey, volleyball, soccer, CounterStrike, American football) as well as extensive backgrounds for analytical foundations in these sports and potential expansions upon current cutting-edge metrics."
showFullContent = false
readingTime = false
hideComments = true
draft = false
+++

**Introduction**  
This article seeks to focus on the state of analytical development that major team sports are in, analyzing the discrepancies and similarities between different metrics, scouting tools, and development level of these sports and identifying ideas for analytical development in each sport that statiscians can use to expand upon. 

In order to establish some level of hierarchy across these different sports, I will be using a tier system that generally just seeks to group sports into different levels of analytical development. The tier system will be numbered in descending order, with Tier 1 being the cutting-edge of analytical development in athletics. There is no specific order within tiers.

### 

### TIER 1: THE CUTTING EDGE

**BASEBALL**  

_**Background**_
There are not enough words to describe my love for baseball analytics, the field that I am actively pursuing a career in and the field that inspired my love for economics, data science, and advanced analytics in sports as a whole. Baseball is so integral to analytics that it has it’s own term for statistics based around baseball, “sabermetrics”, and a book/movie about their inception in *Moneyball*. Sabermetrics are the cutting edge of sports analytics, hoisted on the shoulder of analytical titans and contributors who have all identified the facts that allow for baseball to be not just a perfect model for statistical analysis, but a microcosm of the increasingly algorithmic world and its economy. 

Baseball, as a data set:

\-HAS AN EXTREMELY HIGH SAMPLE SIZE (both in terms of At Bats and in terms of Games Played). This allows for metrics to have high levels of stabilization and reliability, as they’re measured across long periods of time and large quantities of data.   
(Additional reading: [https://library.fangraphs.com/principles/sample-size/](https://library.fangraphs.com/principles/sample-size/))  
\-FOCUSES ON ISOLATED EVENTS. Baseball can be broken down into two parts: an extremely isolated “duel” between the pitcher and the batter, and the batted-ball result of that “duel” in isolation with defensive play. This factor allows for us to isolate events from each other and evaluate statistics in a vacuum, drastically limiting statistical “noise” and allowing for outcomes to be evaluated independent of each other.   
\-HAS A CLEAR “CURRENCY”. Bill James identifies in his groundbreaking *Baseball Abstract* that baseball is won and lost in the currency of runs. This consistent “base” currency lays the groundwork for extreme analytical development by allowing for all following metrics to be building off the same established, proven fact: you win baseball games by scoring more runs than the other team, which is done by producing runs on offense and limiting runs on defense. This may sound like a basic concept, but it’s a crucial element that prevents other sports from having the same cohesion across different metrics. 

These three factors are key for what has allowed baseball to flourish as a statistical medium, both within itself for evaluating baseball, and outside of itself as a microcosm of the world. 

_**Baseball As A Microcosm**_ 
The inception of sabermetrics happened because of, in conjunction with, and as an origin of the development of a world hyperfocused on algorithms and statistics. Paul DePodesta, famously a Harvard economist, was a Bill James disciple. The creation and development of sabermetrics occurred and continues to work in parallel with the creation and development of economic analytics in the real world, while also serving as a framework for other sports to develop their own analytics using the rise of sabermetrics as a base point to build off of. 

This relationship exists because sabermetrics WORK. The Moneyball-era revolution that occurred within the world of baseball wasn’t just a different way of looking at the game, it was an example of an extremely rare phenomenon \- the occurrence of factions (in this case, MLB franchises) being able to actually OVERCOME extreme resource deficits (in an entirely, non salary capped market) through the sheer brilliance of applied analytics. Teams at drastically lower payrolls, with drastically less resources, found a way to spend money more efficiently, by using metrics to identify underpaid and overpaid talent, by using statistics to evaluate the “true value” of baseball players and creating an edge in the market.

Of course, after some time, bigger franchises and their capitalist owners “bought out” these advantages. If David vs. Goliath occurred in the year 2026, Goliath would have come back a week later with a crossbow. This is the nature of “created edges” and resource-deficit brilliance under capitalism \- any advantage is temporary, only existing before it’s identified by those with resources who can better maximize the advantage in question with larger resources and developmental capabilities.

Baseball metrics continue to develop, with resource-strapped franchises continually being required to push sabermetrics further in an endless battle with the resource-laden franchises who have every advantage except one \- the necessity to adapt, which can create temporary advantages and windows for victory. 

If this sounds a bit maudlin, I feel that you’re failing to understand the depth of sabermetrics and what they represent. Because baseball exists as an entirely laissez-faire free market model for capitalism, with few rules and regulations for the way franchises can spend their money (especially compared to other sports, but even compared to the real world’s economy), baseball exists statistically as pure lightning-in-a-bottle. Economic and performance advantages created in baseball are so cutting edge that they can actually translate directly to real world economic strategies and edges, being “ported over” or used as foundation for the development of real-world economic edges. 

_**The State Of Baseball Analytics**_  
With all of that out of the way, it should come as no surprise that baseball analytics are unbelievably developed. Every single aspect of baseball, at this point in time, is being measured, recorded, analyzed in some way. For a simple look at the developmental path of sabermetrics, I like to use a simple example.

The first real stat for recording offensive production, way back in the days of Tungsten Arm O’Doyle and the New York Gothams, was a purely box score stat \- hits. Quantity of hits by players represented offensive production.

The next development came through the creation of batting average, which sought to not just measure how many hits a player had, but what rate at which they were getting hits. 

Batting average is an extremely flawed metric that fails to measure a number of factors, including the value of contact, the value of different types of hits, and the situational context that hits occur in. The first hurdle that was tackled in this regard came from the creaton of OBP, or On-Base Percentage, which accounted for the near-equal value of a walk and a single: both get you to first base. 

What about the value of different hits? There’s two schools of thought that developed from trying to measure this, one being OPS (On-Base Plus Slugging Percentage) and the other being wOBA (Weighted On Base Percentage). Both have their strengths and weaknesses, but the purpose of identifying both here is to show the development from measuring the rate at which a player gets on base to measuring both the rate and WEIGHT of how a player gets on base.

To go even further, sabermetrics have developed to the point where they can measure expected outcomes (metrics like xWOBA seek to account for “bad luck” batted ball outcomes) and have additionally been simplified to work on an easier scale for the human mind (metrics like OPS+ or wRC+ simplify run production by using “100” as the average MLB hitter; as such, a 123 wRC+ player produces 23% more run production than the average hitter). 

This example seeks to show how metrics develop. Flawed metrics are “corrected” over time. There is never a truly “perfect” metric, this is the beauty of analytics, the eternal edge that can be created by necessity: there is always a path to developing analytics further. 

_**Evaluation/Resources**_
Baseball analytics are the cutting edge of sports analytics, due to tireless work based on the foundation of a terrific sport to analyze. 

Personal Favorite Website: [https://www.fangraphs.com/](https://www.fangraphs.com/)

### TIER 2: DEVELOPING RAPIDLY

**HOCKEY**  

_**Background**_   
Hockey shares some analytical advantages with baseball. There is a large sample size of games played, and frequent line changes and a common currency of goals allows for variables to be evaluated in a better context than most team sports, not to mention the limited amount of players per team on the ice (6) relative to sports like soccer or football. Hockey’s downside comes from a limited box score that fails to truly capture the impact of player and team performances, though this is something that advanced analytics within hockey have really began hyperexpanding upon. 

_**The State Of Hockey Analytics**_  
Hockey analytics are developing rapidly. I highly recommend checking out [https://hockeystats.com/](https://hockeystats.com/) for more on this, but applied sabermetric concepts like WAR in baseball are being used in hockey and have a clear correlation with team success, matchup predictability, and evaluating players, both as prospects and as NHL performers. Hockey is developing catch-all statistics like an adopted form of WAR from sabermetrics and rate-based WAR alternatives to account for the high amount of injuries / inconsistent play times in hockey that result from line changes, penalty minutes, and physicality. 

_**Evaluation/Resources**_  
Favorite Website: [https://hockeystats.com/](https://hockeystats.com/)

**BASKETBALL**  

_**Background**_  
Basketball is somewhat difficult to measure as a sport in comparison with hockey or baseball, but the people in the space developing these analytics are extremely passionate and have found their way around some of the difficulties of basketball. Basketball’s advantages come from a common currency of points and a high sample size, as well as a solid foundation of extensive box score statistics and only 5 players on the court at a time per team. 

_**The State Of Basketball Analytics**_  
Through the shining success rate of analytics in basketball, the NBA world has finally begun to come around on their power. This can be attributed to analytical darlings like Nikola Jokic and Isaiah Hartenstein becoming as valuable as they are, coaches/GMs like Sam Hinkie and Daryl Morey being willing to take extreme analytical-based strategies towards team-building (the Process era Sixers) and on-court strategy (the three point revolution), and a ferverous fan community based around the NBA Draft that has continuously pushed the analytical space forward by identifying and building upon correlating rate-based analytics with NBA success. 

Basketball has a ways to go, but it’s getting there rapidly as teams and the NBA community as a whole continue to create and be shown the value of analytics through the success of applied analytics on the hardwood. Basketball is developing catch-all statistics like BPM, PORPAGTU\!, and xRAPM that are proving themselves to be extremely correlated with NBA production and winning. 

_**Evaluation/Resources**_  
Favorite Website (Collegiate): [https://barttorvik.com/\#](https://barttorvik.com/#)  
Favorite Website (NBA): [https://xrapm.com/table\_pages/xRAPM.html](https://xrapm.com/table_pages/xRAPM.html) // [https://apanalytics.shinyapps.io/DARKO/](https://apanalytics.shinyapps.io/DARKO/)

### TIER 3: DEVELOPING

**SOCCER**

_**Background**_  
Soccer is complicated because it’s an incredibly hard sport to measure. It has some advantages \- there are a lot of games played, there is a common currency of goals scored/allowed, and 90 minute games with few stoppages allow for individual games to be analyzed well. The disadvantages come from 11 players per team on the field, a limited box score that fails to truly capture every positive/negative action a player takes across a large amount of playtime, and a large field who’s gameplay format is extremely based around space creation.

_**The State Of Soccer Analytics**_  
Soccer’s main claim to success in terms of player evaluation and analytical development comes from the unbelievably developed international academy system. Soccer probably has the best scouting development out of any sport here other than baseball, and a lot of that is due to a similar free-market structure to baseball that has created extreme financial incentives to find the next “wonderkid” like Lamine Yamal or Lionel Messi (sorry, I’m a Barca fan). In terms of catch-all metrics, websites like Opta Analyst and SofaScore are developing individual match ratings and expected stats like xG/xA that are starting to push soccer player evaluations beyond just the eye test, although there’s a lot of work still to be done in this regard, mainly in the necessary adaptation of a WAR-like stat. 

_**Evaluation/Resources**_  
Favorite Website: [https://theanalyst.com/](https://theanalyst.com/) // [https://www.sofascore.com/](https://www.sofascore.com/)

### TIER 4: OVERDEVELOPED RELATIVE TO SIZE

**VOLLEYBALL**  

_**Background**_  
Volleyball has a lot of statistical advantages as sample size. Teams play a lot, outcomes are mostly isolated, and box score stats are extremely translatable to game events, which allows for an extremely solid framework to build advanced analytics off of. 

_**The State Of Volleyball Analytics**_  
Volleyball analytics are overdeveloped relative to the size of the sport. Evollve is a really good website and there are several others that have identified the advantages of measuring volleyball statistically. Volleyball is somewhat limited in terms of statistical developmental ceiling due to the lack of resources in the sport as a whole, but it deserves a place on this list because it’s the only team sport outside of the “big 5” of soccer, hockey, football, basketball, baseball that really has a developed analytical scene with correlation to winning games. 

_**Evaluation/Resources**_  
Favorite Website (Collegiate): [https://evollve.net/](https://evollve.net/)

**COUNTER STRIKE**  

_**Background**_  
This is technically not a sport, but rather an eSport, but I thought it deserved a spot on this list anyway because of the significant developments in statistical analysis across the Counter-Strike scene. Counter Strike has several advantages as a sample size \- there are a LOT of matches played, a lot of noise is eliminated by virtue of being a “digital” sport where outcomes are server-dependent and easily measurable/inspectable through code, which takes care of a lot of the resource-intensive investment other sports have to do in order to measure outcomes and record different results (ex. Counter Strike doesn’t have to worry about investing in the necessary equipment to physically record things like velocity, because it all takes place within a digital vaccuum). Counter Strike has been around since 2001 with the same core gameplay across several iterations of gameplay, which has allowed for a statistical and analytical based community to develop within the game and begin forming it’s own statistical language. Counter Strike is also relevant economically, as it is one of the only team sports to share the “ideal” statistical economic model for analysis, an international free market (baseball/soccer being the other two). In the same way that soccer teams are incentivized to find wonderkids, Counter Strike organizations are not shackled by partnership systems like other eSports (cough cough Riot Games) and have developed extensive academy systems as a result to find top talent (almost all top talent in the current Counter Strike scene come from an organization’s academy team). Counter Strike has a lot of economic investment in it, not just for an eSport but for a non “Big 5” team sport in general, due to Valve’s ingenuity regarding the creation of a skin-based economy that’s also tied into the eSports scene that has developed into an entirely self-sustaining economy (more on this in a later article). 

_**The State Of Counter Strike Analytics**_  
Counter Strike analytics are surprisingly advanced, even when you account for all of the positives that exist for analyzing Counter Strike as a sample size. HLTV, the leader of Counter Strike analysis, is currently on its third iteration of a rating system that weights player impact, and the metric has extreme correlation with player impact and winning. Further development in this field should be done with “weighted” kills in mind in relation to the hyper-importance of team economy within the game. 

_**Evaluation/Resources**_  
Favorite Website: [https://www.hltv.org/stats](https://www.hltv.org/stats)

### TIER 5: UNDERDEVELOPED RELATIVE TO SIZE 

**AMERICAN FOOTBALL**  

_**Background**_  
Football is sadly at the intersection of many disadvantages as a sport for analysis. There is no free market, there is a hyper-restrictive salary cap. There is a limited sample size of games, players get injured extremely often, and there are no developmental leagues outside of the NCAA. There are 11 players on the field per team at all times, which adds a lot of noise, and to extend the disadvantages even further, there is no clear “shared currency” of football. You can argue points, but there are situations where scoring points is bad\! The “true” currency of football is yardage, but this gets very noisy with the weighted importance of red zone yardage, which gets into the flaws of analyzing the red zone in relation to different team strengths (conversion rates, kickers, explosivity rate)... 

All of this has created a world where football, by far the highest-grossing sport in terms of revenue in America, lags behind several other team sports in analytical development. There are so many difficulties with evaluating football. Positional value is impossible to translate across different positions, which makes the development of a WAR-like metric seem nearly impossible. Formations change pretty much every play, players change almost every play, and the NFL is far too involved with the analytics that DO exist to the point where all analytical development is almost too subsidized by the NFL itself to exist independently and create potential advantages for teams. Even in scouting, top prospects routinely bust on a level unseen in other sports like basketball, which is problematic because it’s the one area where football could potentially have an analytic edge over other sports because of the 3-year requirement for college football players to remain in college prior to declaring for the draft, which should stabilize prospect evaluations more than other sports. 

Even relative to the disadvantages, football is woefully underdeveloped relative to the resources that exist in football, both at the collegiate level and in the NFL. I’ll go into this further in the next section and look at potential ways I’ve thought of advancing the space. 

_**The State Of Football Analytics**_  
We've seen teams finally start to use analytics more in regards to 3rd/4th down decisionmaking and it's been a revalation for winning, but there are so many more ways I'd like for football to develop analytically. 

Spiral rotation rate and thrown ball velocity need to be measured. They seem to be extremely sticky indicators for QB translation to the NFL.

Blocking/block shedding is something that occurs almost entirely in isolation, yet expected stats for the run/pass game lag behind.

The concept of the "red zone" is entirely flawed and is entirely reductionist to the "scoring range" of different teams based on their kickers, 3rd/4th down conversion rates, and explosivity. The true currency of football shouldn't be points, but yardage.

Defensive metrics are absolutely atrocious, including PFF. People still use INTs and sacks to evaluate defensive impact\!\!\! We are only just starting to move towards using pressures by edge rushers and yards allowed by CBs instead of these inherently obsolete box stats.

Punting/special teams is extremely, extremely valuable, especially in college, because of the unbelievable statistical impact that field position has. This has to be developed into measuring a team's "expected points scored" based on their field position.

Football's one area of development that supercedes a lot of other sports is the tremendous amount of formation-based and pre-snap tacticality, but little to no statistical research has actually been performed in regards to formation vs. formation expected success rates.

The only real way to measure football holistically is going to come from measuring formations against formations by expected and real yards/WPA above average. This is the only way to really evaluate a sport with so many moving parts and complexities.

_**Evaluation/Resources**_  
Favorite Website (Collegiate): [https://www.cfb-graphs.com/protected/teams](https://www.cfb-graphs.com/protected/teams)  
Favorite Website (NFL): [https://nextgenstats.nfl.com/](https://nextgenstats.nfl.com/)  

### CLOSING THOUGHTS

Thank you so much for reading.

If you have any feedback or resources regarding anything you feel I don’t properly cover or evaluate in this article, please email me at [ARKNDJL@GMAIL.COM](mailto:ARKNDJL@GMAIL.COM) or contact me on Twitter @ARKNDJL. 

