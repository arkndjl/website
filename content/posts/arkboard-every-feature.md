+++
title = "How the ARKBOARD Works"
date = "2026-11-02T16:00:00-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["arkboard", "cfb", "nfl", "cbb", "nba", "nhl", "hockey", "soccer", "tennis", "cs2", "draft", "predictions"]
keywords = ["arkboard", "future value", "20-80 scale", "college football", "college basketball", "nfl", "nba", "nhl", "hockey prospects", "soccer", "soccer prospects", "tennis", "counter-strike", "war", "xpm", "gar", "mock draft", "nil", "game model", "predictions", "kelly"]
description = "Every ARKBOARD page: the FV scale and how each board builds it, WAR, XPM, GAR and the other value metrics, the mock drafts, NIL, recruits, team ratings and season odds, the game models, and the Predictions page. How each one is calculated and how it tested."
showFullContent = false
readingTime = false
hideComments = true
Toc = true
draft = false
+++

{{< card url="/arkboard/" title="ARKBOARD" >}}
Every board, model and prediction, by sport.
{{< /card >}}

This post covers every ARKBOARD page: what each tab shows, how it's calculated, and how it tested on seasons it wasn't fit on. The football pages have their own longer write-up, [How the Football ARKBOARD Works](/posts/football-arkboard-every-feature/). This one covers the rest of the site and what has changed in football since.

One rule runs through all of it. An input only gets weight if it improves predictions on data the model didn't see: a held-out season, class or birth year, and for anything with a betting line, the closing line. I list inputs that failed that test too.

This describes the site on November 2, 2026. Tabs get added and moved often, so I'll update it as the pages change. The screenshots are from the live pages that day. Tap one for the full size.

## Layout

Every sport page uses the same tab groups, in the same order: **players**, **games**, **teams**, then sport-specific groups (recruits, mock draft, leagues), then **model**. Within players, the main board comes first, then subset boards, rookies, backup watch and ARKLIST. Within teams, ARK Ranking comes first and the depth chart last.

The main board only shows columns every player has. Stats that only some players have get their own tab. Ranks are computed within whatever tab and filters you have on.

Three pages sit across sports:

- **ARKRANKING** has every sport's ARK Ranking and season odds on one page, plus a title-odds table for every competition: the favourite, the second favourite, the ARK Ranking #1, and how open the race is (contenders = 1 / Σp², the inverse Herfindahl of the title odds).
- **ARKLIST** is my favourites in every sport, marked on the boards.
- **Predictions** is the only place for picks, lines, futures and props. Sport pages keep projections, ARK Rankings and season odds.

[![ARKRANKING title odds: each competition with its favourite](/img/arkboard/arkranking.webp)](/img/arkboard/arkranking.webp)

Clicking a player opens a dropdown with his inputs, the range of outcomes and strengths and concerns, all built from the numbers. Clicking a team opens its rating broken into parts, schedule, key players and young talent. Every table has a **GFX** button that draws a 4:5 card in the site's palette and pixel font, and player and team rows have their own cards. Every view has a link that keeps the tab, sort and player, and each page has a short link (/cfb, /cbb, /nfl, /nba, /nhl, /hockey, /soccer, /u22, /picks). Each data stamp turns "stale" if a sport's feed hasn't updated in 36 hours during its season.

## FV, the 20-80 scale

FV (Future Value) is the main grade on every prospect board: CFB, CBB, hockey, soccer and tennis prospects, plus the baseball boards. Each board has its own scale, tied to what players at that level actually become in that sport. The scales are not converted into each other.

| FV | Tier | Football | Basketball | Hockey | Soccer |
| :---: | ----- | ----- | ----- | ----- | ----- |
| 80 | generational | 5+ time All-Pro | 7+ All-NBA teams | 1 in 4 classes | #1 in 2 birth years |
| 70 | star | 2-time All-Pro | 3+ All-NBA teams | #1 in a class | top 3 in a birth year |
| 60 | plus | Pro Bowler | 2+ All-Star | top 5 in a class | top 20 in a birth year |
| 55 | above average | 6+ seasons starting | above-average starter | top 10 in a class | top 45 in a birth year |
| 50 | average | 4+ seasons starting | average starter | top 20 in a class | top 90 (big-five regular) |
| 45 | below average | 2+ seasons starting | low-end starter | top 30 in a class | top 150 |
| 40 | bench | rotational | end of rotation | top 45 in a class | top 250 (top-flight regular) |
| 30 | organizational | camp body | two-way / fringe | some NHL games | some senior value |
| 20 | non-pro | non-NFL | G League | no NHL games | no senior value |

The rules that apply on every board:

- **FV is the mean outcome.** A grade is the average of what past players with the same profile became, busts included. So it sits below the best case. The dropdown shows the odds of each outcome and the 80% range.
- **FV is absolute.** It comes from each player's predicted talent, not his rank on the board or in his class. A strong class gets more high grades. Each board fits one fixed map from model output to FV on pooled history.
- **80 is reachable but rare.** The mean of a capped outcome can't reach 80, so above a knot K (the level about three players a season reach) the scale runs linear up to 80 at the level one player reaches in about five seasons. The knots: CFB 67.8, CBB 46.6, hockey 54.0, soccer 64.1, ATP 63.4, WTA 60.2. The exact mean stays in the tooltip.
- **Grades come in steps of 1.** Chip colours change every 5.
- **Players without a board grade start at 20** and take every input the model has for them. They're ranked with everyone else and tagged provisional.

Each board's **fv model** tab has a scorecard: for each FV band, the mean grade given against the mean outcome reached, with 90% intervals, out of sample. Held out, the slope of reached on given is .99 for CFB, .97 for CBB and 1.00 for soccer, and hockey is calibrated. CFB's 40+ odds run 6-8 points hot in the 40s. The **all-time FV** tab grades every past player the same way, by position.

## College football and the NFL

The [football post](/posts/football-arkboard-every-feature/) has the full method: FV's composite and scarcity steps, Stat+, college WAR, badges, Draft%, NIL, Transfer%, the team builder, recruits, the game model and NFL WAR. What has changed since October 14:

- **FV.** The top of the scale is stretched as above, so 80 is possible. Six badges and two XV parts (LB coverage, EDGE sack rate) feed FV. QBs aren't deflated: they realize a little below their FV, but a QB term failed held out.
- **Three mocks.** The **predictive mock** is the projection of the real draft. The **conviction mock** ranks on FV instead of consensus, with the same needs and trades. The **blended mock** puts each slot halfway between (geometric mean of the two expected picks). Each grades the other's picks: a reach or value chip means the other mock has the player 2.5x and 16+ slots away. 200 simulations give each prospect a range of picks.
- **QB at #1.** A QB-needy team at #1 took a QB 19 of 24 times since 2000, against 1 of 3 without the need. That premium is in the predictive mock in full, the blended at half and the conviction mock not at all. It cut the Brier score on whether a QB goes first from .37 to .15 on fall boards.
- **Stay or declare.** Declare odds come from expected pick and age on draft day, fit on NIL-era drafts (log loss .529 to .379). Prospects under 50% sit out of the mocks. **UDFA signings** lists where undrafted players land after round 7.
- **New tabs.** **True freshmen** (FV, WAR and Stat+ against recruiting rank), **special teams** (below), **top performers**, **coach pay** (market value against public pay), **development** (below) and **redshirts**.
- **CFP odds.** The committee is modelled as a ranking over all FBS teams from rating, record and wins above a bubble team, fit on the 2014-25 committee releases. Held out, the field log loss is .029 against .090 for the old formula.
- **Game model.** Availability reports (SEC, ACC, MAC, American) set each player's chance of playing. Totals now carry market ratings from earlier lines.
- **NFL.** WAR blends XV and AV WAR. Two-way players get WAR on each side. **Breakouts** and **special teams** tabs were added. NFL picks and props went live on Predictions.

### NFL breakouts

Young players (rookies, 2nd/3rd-year players, or 24 and under) with the most WAR over expected in the week. Expected is his WAR rate going into the week × his snaps. A rookie's prior comes from his draft slot (rate = a + b × ln(pick) by position, undrafted = pick 300), which cut the error on rookie rates by 2.3% (t −3.15). The slot prior didn't help rest-of-season projections past week 5, since the season's data swamps it.

[![NFL breakouts: young players by WAR over expected](/img/arkboard/nfl-breakouts.webp)](/img/arkboard/nfl-breakouts.webp)

### Special teams

Kick and punt returners in CFB and the NFL, ranked on return yards over expected from the same catch spot. Only real returns count: fair catches, touchbacks and penalty plays are out. The rank shrinks each returner's total toward zero:

Adj = Σ(yards − expected) / (returns + k)

where k = σ²/τ² from the spread of returner talent over three seasons (NFL kick returns k 88, punt returns 103; CFB 36 and 20). It's ranked on yards, not EPA, because NFL kick-return EPA over expected doesn't repeat (year-to-year r −.02). Yards over expected repeat at .13 for kick returns and .31 for punt returns. EPA is shown as points.

[![NFL special teams: returners by yards over expected](/img/arkboard/nfl-special-teams.webp)](/img/arkboard/nfl-special-teams.webp)

## College basketball

### FV

The CBB board grades every D-I player and the international prospects. FV is tied to peak XPM: the best three NBA seasons of a 50/50 blend of DPM and BPM, shrunk toward −2 by 500 minutes. The FV ladder was set by rarity on the 2008-16 classes: 80 = 7+ All-NBA teams (about 0.6 a board), 70 = 3+, 60 = 2+ All-Star, 50 = average starter.

The drivers that held up: for newcomers, recruiting rank (mean −ln rank over On3, 247 and Barttorvik), a top-25 hinge and class. For returners, three-season BPM, conference power, age, size, free-throw rate, turnovers, steals and about ten more. A second stage adds the June consensus rank: a preseason ranking predicts the June rank (slope .92), and the model reads that. It raised out-of-sample pseudo-R² from .070 to .089 in all five folds.

**In season** the board moves daily:

E = (1 − w) × preseason + w × now, with w = minutes / (minutes + k)

"Now" is the FV model run on his career with this season's line to date. k is 63 minutes for newcomers and 128 for returners. By March, the board's AUC for reaching the NBA goes from .91 to .94.

**Internationals** are graded on Basketball-Reference lines from 12 leagues, each converted to EuroLeague level (ACB +2.1 Game Score per 100, EuroCup +2.8, up to the CBA +7.2). Age alone hurt the fit, because the boards already price it.

Players without a board grade start at 20 and take height, weight, class, age for class, recruiting, conference and team strength (5-fold R² .77).

[![The 2026-27 D-I board on a phone](/img/arkboard/cbb-board.webp)](/img/arkboard/cbb-board.webp)

### Recruits

The 2027-29 classes are graded on the same FV. P(reaches the NBA) comes from consensus rank and being old for the class, then FV given the NBA from rank. Held-out Spearman .457. ARK stars cut FV at outcome bands (5 = 2+ NBA seasons as a starter, 4 = reached the NBA, 3 = D-I starter, 2 = played D-I), and that fits outcomes better than the industry's stars (R² .266 vs .253).

### Mocks

Same three mocks as football. The **predictive mock** is a seven-board consensus. The **conviction mock** is draft slot plus three-season BPM and age on peak XPM. **Blended** is the geometric mean. Declare odds have two stages: leaving school (recruit rank, BPM, class), then the No Ceilings midseason board on top (log loss .92 to .50). The draft order comes from simulated seasons and the lottery.

[![CBB predictive mock with consensus, our FV and simulated landing spots](/img/arkboard/cbb-mock.webp)](/img/arkboard/cbb-mock.webp)

### Games, ARK Ranking and tournament odds

Margin comes from opponent-adjusted offense and defense ratings (ridge, no recency decay), a market rating from earlier closing lines, home court, conference games at home, altitude, and injuries. Injuries come from the Covers report: a listed rotation player costs his BPM over his team's bench at his chance of sitting. The preseason prior uses last season, returning minutes, transfers, freshmen, the top five roster FVs, minutes-weighted age and the head coach's record against his preseason projections at any school (held-out t −3.9).

Held out on 2021-26, the model misses by 9.25 points a game and the closing line by 8.99.

**Tournament odds** model the committee from rating and wins above a bubble team. Held out on 2015-26, at-large log loss is .057 against .110 for rating alone, with 91% of at-large picks right and 46% of seeds exact. Q1 wins and bad losses added nothing. The **ARK Ranking** picks winners at 77.3% against 76.8% for the AP poll since 2016.

[![NCAA tournament odds: bid, seed, Sweet 16 and Final Four](/img/arkboard/cbb-tourney.webp)](/img/arkboard/cbb-tourney.webp)

### Development

The **development** tab (CBB and CFB) asks which programs develop players. In CBB, a school's effect on realized NBA FV is zero once recruiting is known. Its effect on minutes-weighted BPM is real, and stronger by head coach (Painter, Few, Bennett, Drew, Self at the top), but about half of it is system and team inflation rather than talent. In CFB, schools add about .4 FV per signee beyond recruiting (rolling t 5.3, 6 of 6 seasons): Ohio State, Iowa, Louisiana, Washington, Oklahoma and Michigan at the top.

## NBA

### XPM and VORX

XPM is my NBA impact metric: 50% databallr DPM and 50% Basketball-Reference BPM, on each side. **VORX** is wins over replacement:

VORX = .030 × (XPM + 1.4) × minutes / 48

with both constants fit to team wins out of sample. Low-minute players are shrunk on display:

shown XPM = μ + (XPM − μ) × MP / (MP + 300), μ = −1 + .5 × ln(1 + MP per 82 / 100)

That cut the next-season error from 1.59 to 1.26, and from 7.29 to 1.75 for players under 100 minutes. Full seasons still regress about 12%. **XPM (proj)** blends the season to date with a preseason prior (k 509 minutes for veterans, 809 for newcomers).

I tested RAPM, LEBRON, RAPTOR and LUMA's LOKI as replacements or additions. All failed. LUMA's ARC (CC BY 4.0) helps the game model at a .25 weight and doesn't improve XPM itself.

[![NBA XPM leaders with VORX, raw XPM and badges](/img/arkboard/nba-xpm.webp)](/img/arkboard/nba-xpm.webp)

### Contract value, rookies and projections

**Contract value** is projected VORX × the market price of a win against salary. A win costs $12.65M this season (payroll above the minimum / league VORX), rising 7% a year. Player options are valued at min(0, value − salary) and team options at max(0, value − salary). **Rookies** shows VORX, XPM and surplus against draft slot and pre-draft FV. **Projections** give the 20th, 50th and 80th percentile VORX, points, rebounds, assists, threes, steals and blocks, full season and rest of season. Held out, those percentiles land at 20/50/80 within 3 points.

[![NBA contract value: surplus over the contract](/img/arkboard/nba-contracts.webp)](/img/arkboard/nba-contracts.webp)

### Games

Margin = Elo + opponent-adjusted efficiency + a market rating from earlier closes + tonight's lineup value + rest + home court. Lineup value is each player's prior XPM × minutes × his chance of playing (out 0, doubtful .02, questionable .56, probable .95), with rookies valued by draft slot and final college BPM. Made threes count at .75 of their face value in the ratings, since 3P% is partly luck. Held out on 2022-26, the model misses by 10.76 points against 10.56 for the close.

Back-to-backs (rest days already cover it), travel, time zones, altitude and in-season XPM updates all failed. Referee crews' free-throw tendencies helped in 2022-26 but not 2015-21, so they're logged as a pre-registered forward test instead of going in.

## NHL and hockey prospects

### NHL WAR and goalies

NHL WAR is descriptive: what a player did this season, in goals, converted to wins. The parts: 5v5 on-ice xG for and against relative to teammates, power play and penalty kill xG, finishing (goals − xG), penalties drawn and taken, a share of the team's leftover xG, and for goalies, goals saved above expected. Added up by team, it explains team goal differential with R² .991 and a slope of .99. Replacement is the rate of players outside each team's top 13 forwards, 7 defensemen and 2 goalies.

**pWAR** is the projection: Marcel weights (1/.7/.5), shrunk toward a learned target that sits below average for short histories, with ice time as a share of the team's. Out of sample, R² for next season goes from .23 to .38. Goalie GSAx barely repeats (weight .07), so a goalie with 7 WAR this season projects to about 0.4.

[![NHL WAR leaders with pWAR and HPM](/img/arkboard/nhl-war.webp)](/img/arkboard/nhl-war.webp)

### Games and season odds

Win chance = Elo + an opponent-adjusted xG rating (half-life 120 days) + back-to-backs + home ice, from MoneyPuck xG. Held out on 2024-26, log loss is .6696 against .6645 for the close. Goalie GSAx, the starting goalie, rest, special teams and a goals rating all failed: the market already prices goalies (residual correlation 0). Season odds come from 10,000 simulations with divisional brackets and overtime-loss points.

### Hockey prospects

The big board covers the 2027 draft class and every drafted player still short of the NHL. FV is tied to the mean of a player's best three WAR seasons in his first seven, by rarity in a class (80 = one in four classes). Goalies are graded against goalies.

The draft model is draft slot, NHLe and position. NHLe converts a junior or pro line into NHL points with league factors fit on players who played in two leagues (OHL .12, NCAA .21, AHL .41, SHL .48, KHL .55). Going in the first round of the CHL's age-15 priority selection costs 1.9 FV: the NHL draft overpays junior pedigree. After the draft, the model adds new information by stage: a World Juniors spot (+4 FV a year out), pro games (about +9 at two to three years), NHLe growth, NHL preseason games, career save% over league average for goalies, the three nearest comparable past players, and whether he has played an NHL game. Age, height, CSS rank, plus/minus, PIM, playoffs and two dozen other inputs failed.

Unranked CHL players get a provisional grade from NHLe, age and size (MSE 11.16 vs 12.40 flat). **Past classes** shows what every pick became. The three **mocks** use projected standings for the order and Tankathon for pick owners, and the **lottery** tab gives each team's odds of #1.

[![2027 NHL draft big board with FV and NHLe](/img/arkboard/hockey-board.webp)](/img/arkboard/hockey-board.webp)

## Soccer and soccer prospects

### Games

Each club has an attack and defence rating, updated after every match within its league, plus a league strength learned only from cross-league matches. The ratings blend goals implied by earlier closing prices (.93), Understat xG in the big five and FotMob xG in 13 other leagues (.07). Held out from 2022-23, log loss is .972 against .967 for the close. Rest days, shots on target and manager changes failed.

The page covers the big five, 13 more European leagues, MLS (conference tables, Supporters' Shield and MLS Cup odds) and the three UEFA cups. Title, top-four, relegation and knockout odds come from 10,000 simulated seasons, with each league's split format. The **ARK Ranking** puts every European club on one scale. MLS is left off it, since it only meets Europe at the Club World Cup.

[![Soccer ARK Ranking, every European club on one scale](/img/arkboard/soccer-rank.webp)](/img/arkboard/soccer-rank.webp)

### GAR and market value

**GAR** (goals above replacement) weights per-90 rates (on-ball actions, non-penalty xG, xA, xGBuildup, keeper saves) by how much each predicts the next season's team goal difference (held-out R² .61). Replacement is the rate of players under 900 minutes at the position. As player value it predicts next-season club strength better than a WAR built on Understat (R² .70 vs .63) and repeats better (.84 vs .69).

**Estimated market value** is a ridge fit on log Transfermarkt value from GAR over three seasons, minutes, age, position, league and club. Out of sample R² is .68 in October and .78 by July. The gap between our value and Transfermarkt's forecasts its next update: the top fifth by gap rose 31% by season's end and the bottom fifth fell 13%.

[![Soccer player value: GAR leaders](/img/arkboard/soccer-value.webp)](/img/arkboard/soccer-value.webp)

### Soccer prospects

Every player under 22 on July 1 in 33 leagues, plus 38 academy and reserve leagues. Value is club GAR: minutes / 90 × (club rating + 2.5) / 11. The outcome is the best three GAR seasons from 22 to 26, and FV is rarity within a birth year and position group (80 = the best in two birth years).

The model refits at five points in the season. Kept: GAR to date, height, club strength, market value (with forwards' values discounted and keepers' raised, since the market overprices one and underprices the other), minutes share, last season's GAR, age × value, goals and assists per 90, league strength × league minutes, and academy terms (feeder minutes × the parent club's rating). Held out by season, MSE is 59.8 against 67.8 for age and market value alone.

Two leaks came out on the way: "no height listed on Transfermarkt" (players who never make it never get a height) and "any transfer on record" (the dump only keeps histories for players it kept following). Neither is used. EA FIFA ratings, youth caps, Understat rates and comparable players failed.

[![Under-22 soccer big board](/img/arkboard/soccer-prospects.webp)](/img/arkboard/soccer-prospects.webp)

## Tennis and tennis prospects

### ARK Ranking and matches

Three ratings, blended in log-odds: surface Elo, a games-won rating, and opponent-adjusted serve and return point ratings run through the game, set and match chain. The ARK Ranking is each player's win chance against an average top-50 player over a year's mix of surfaces. On 2023-26 tour main draws, log loss is .596 against .603 for Elo alone. The closing line is better still (by about .015), but the model predicts which way the line moves (.27 logits per logit of model minus open), which is where the tennis picks come from (below).

The **serve + return** tabs show points won over average against the opponents faced, expected hold and break, dominance ratio and break points over expected. Two badges passed for ATP players, Big Server and Grass Court.

[![ATP ARK Ranking](/img/arkboard/tennis-rank.webp)](/img/arkboard/tennis-rank.webp)

### Prospects

Every ATP and WTA player under 22 with a ranking or a pro match in the last year. The outcome is the best three seasons of ranking points from 22 to 28, and FV is rarity within a birth year (80 = once in 8 years, 65 = the best of a year, 50 = 7th). Kept: age, rank, Elo on every pro match at every level, win rate over 52 weeks, years since pro debut, and Futures volume (ATP) or tour qualifying volume (WTA). Held-out R² .50 ATP and .46 WTA. Height is out: the archive only fills heights for players who made it.

## Counter-Strike

An ARK Ranking of pro CS2 teams. Each player has an Elo that follows him between rosters, updated per map on round share, and a team is the mean of its five. A team map rating with a simulated veto and Valve's regional points (VRS) are blended in. Held out from July 2025, log loss is .559 against .667 for VRS alone. Roster continuity, inactivity and team-name Elo failed. There's no free closing-odds history, so CS2 picks stay off until the forward archive can test them.

[![Counter-Strike ARK Ranking with player Elo and VRS](/img/arkboard/cs2-rank.webp)](/img/arkboard/cs2-rank.webp)

## Baseball

The baseball boards are hand graded: the 2026 draft hitters, every U19 prospect in MiLB, and the White Sox top 64. They use the FanGraphs 20-80 scale (80 = top-five player, 50 = average regular, about 2 WAR a season). MiLB prospects after the draft are on [eephus.io](https://eephus.io).

## Tabs every sport shares

- **ARK Ranking.** Each sport's game-model rating on a neutral field, broken into its parts. Every row has an 80% rank range and odds of finishing #1 or top 4, from how much ratings still move with the share of the season left (CBB rating sd 3.9 points at the start to 1.6 at the end). NFL and NBA show the rating with today's injuries and at full strength. NFL, NBA and NHL show summed rest-of-season player projections beside it.
- **Season odds.** 10,000 simulated seasons from the ratings, with rating error that shrinks as the season goes.
- **Projections.** 20th, 50th and 80th percentile WAR, VORX and stat lines for the NFL, NBA and NHL, season to date plus rest of season. Each is tested for calibration by season stage, position and season.
- **Rookies / true freshmen / first-year.** Each sport's first-year players against their pre-draft or recruiting rank.
- **Backup watch.** Second- and third-string players producing above the starter. Rows rank on the gap projected over the next two seasons, with age (a young backup over an old starter ranks higher). Held out, adding age beat the gap alone in every sport tested.

[![NBA backup watch](/img/arkboard/backup-watch.webp)](/img/arkboard/backup-watch.webp)
- **Depth chart.** Every team, one card per slot, coloured by FV in college and by position percentile in the pros.
- **Badges.** Each badge is one stat regressed toward the position mean by volume, with tiers at the 75th, 90th, 97th and 99th percentiles. A badge is shown only if it predicts the sport's own outcome beyond the main value metric, held out. Usage and volume traits pass (NBA Shot Creator, NFL Target Magnet, NHL Play Driver, soccer Chance Creator). Efficiency rates mostly fail or run the wrong way once value is known. **Team badges** follow the same rule, and 59 of 72 passed. One (NFL return game) also improved the NFL game model.

## Predictions

### Games and the game table

Every game in every sport with a model line, win chance and projected score, against the market. The game table lists every upcoming spread, total and moneyline sorted by edge: the model's chance minus the no-vig market chance.

### Picks

A pick is the model's side when it's at least X points off the line. X is set per sport and market on tuning seasons, as the smallest gap where the edge at a Novig −103 price is above zero, with every backtest edge halved to allow for betting after the open has moved. A market only turns on if its held-out picks beat the closing line. Picks are judged by the close, not by wins and losses, because the close needs far fewer bets to separate skill from noise (CBB 5+ points off the open: about 228 bets for t 2 by the close, 402 by results).

The markets on now, with their held-out records (return at the closing price):

| Market | X | Held-out picks | Return at close | t |
| ----- | :---: | :---: | :---: | :---: |
| CFB total | 2.5 | 983 | +3.6% | 9.2 |
| NFL spread | 4 | 132 | +9.6% | 8.8 |
| NFL total | 1.5 | 414 | +3.3% | 5.4 |
| CBB spread | 2.5 | 4,167 | +3.6% | 20.6 |
| CBB total | 2 | 7,154 | +4.9% | 37.4 |
| NBA total | 3 | 734 | +12.0% | 22.9 |
| ATP/WTA match | 4 pts of win% | 1,935 | +3.2% | 13 |

The NBA record is an upper bound: the walk-forward model saw tip-time injury reports, so its edge counts at half for sizing. CFB and NBA spreads are off (no cut beat the close on the tuning seasons). Moneylines are off because the history has no opening moneylines to judge them by. NHL and soccer have no picks: neither model beats the close at any cut.

**Stakes** are shown as Kelly %, the share of the bankroll:

Kelly = (b × p − q) / b

at full Kelly on the calibrated chance, compounding. In the walk-forward test, full Kelly gave the most log growth at the backtest edge and at half of it, and fractional Kelly only wins if the live edge is under .44 of the backtest's. Every bet is capped at 5% of the bankroll, and each night is capped at 40% across all sports: when open picks add up to more, every stake that night is scaled by 40 / total. Over 1,492 backtest nights, the 40% cap cut the odds of a 50% drawdown from .27 to .12 at a modest cost in growth.

[![The picks tab: stakes as Kelly %, judged by the close](/img/arkboard/picks.webp)](/img/arkboard/picks.webp)

**NFL props** are on the board too: one prop per player per game (the one with the largest Kelly stake), the week's props scaled to 50% of the bankroll. Held out on 2025-26, props the model gave 60%+ went 55.3% over 3,732 bets. NHL goalie saves are in a separate paper test. NBA props failed against the close.

### Players and futures

**NBA players** and **CBB players** project points, rebounds and assists for every game, with minutes freed by injured teammates passed to the rest of the roster (NBA held-out PRA error 6.20 against 6.46 for season averages). **NFL fantasy**, **NFL rankings** and **NFL breakouts** are the fantasy tabs from the football post. **Futures** compares our title and division odds with the market's. Neither the NBA nor NFL futures has beaten the line, and the tab says so.

### Record

- **Picks backtest.** Every market's held-out record, by gap and by bet timing, and the close predictor: how much each market's close moves toward the model per point of gap (CFB spread .10, NBA total .42).
- **Game models.** Each model's live loss against what its backtest expects for that month.
- **Paper book.** Every pick from the picks tab, at the posted line and stake, compounding from the October 28 reset.
- **Rule monitor.** Two tests run on every live rule. One stops a rule when its last 300 picks lose to the close (t below −1) or a CUSUM crosses its limit. The other is a sequential test of live edge against the backtest's: it pauses a rule at 19-to-1 odds that the edge is gone.

[![Picks backtest: each live rule against its backtest](/img/arkboard/picks-backtest.webp)](/img/arkboard/picks-backtest.webp)

## Inputs that failed

A partial list, from across the site. Most of these are tested again when a new season of data comes in.

- **Game models:** polls (CBB, CFB), byes and short weeks, travel and time zones (NBA), back-to-backs (NBA), team home-court edges, penalty and foul rates, 52 style-matchup terms, ESPN's BPI and FPI predictors, coach career records (CFB), goalie GSAx (NHL), manager changes (soccer).
- **FV:** a shared cross-sport value scale, college dominator rating (CFB), all-conference honours, McDonald's All-American, self-creation (CBB), age and size at the draft (hockey), youth caps and EA FIFA ratings (soccer), Davis Cup and junior Slams (tennis), program development as an FV driver.
- **Player value:** RAPM, LEBRON, RAPTOR and LOKI (NBA), offensive line on-field parts (NFL), versatility (CFB), finishing over xG (soccer), break points and tiebreaks (tennis).
