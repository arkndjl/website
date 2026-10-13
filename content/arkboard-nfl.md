+++
title = "NFL :: ARKBOARD"
url = "/arkboard/nfl/"
description = "NFL WAR leaderboards (every player's wins above replacement this season, overall and by position), NFL game projections (a model line, win probability and projected score for every game next to the market) and PPR player projections. updates automatically through the season."
keywords = ["arkboard", "nfl", "nfl war", "nfl game projections", "nfl model", "wins above replacement", "approximate value", "leaderboard"]
draft = false
+++

{{< arknav >}}

{{< winpane title="nfl.exe :: NFL WAR and games" icon="football" sprite="px/hero-football" status="nflverse · PFR AV" >}}
NFL WAR is wins above replacement: what a player has added to his team this season over a freely available one. it's (AV - replacement AV x snap share) x .091. replacement is what a freely available player at the position earns over a full season of snaps (the AV rate of part-timers: TE 2.6, WR 5.0, DB 5.1, OL 6.7, LB 6.9, DL 7.4, QB 7.9, RB 9.0), charged in proportion to the snaps a player takes, and every AV above that is .091 wins (the 2021-25 fit of team wins on team AV, r .84). a team of replacements wins about 3 of 17, so a team's WAR adds up to its wins less 3. below replacement is negative. AV is Approximate Value, rebuilt each week from play stats, snaps and scoring the way Pro Football Reference builds it (team offense and defense pools split by role and production) and fit to PFR's own AV: it tracks PFR at r .91 on a single season of rookies it never saw. pick a position for its leaderboard, or per 17 games for the rate view.

the game model lines up every game with Elo, opponent-adjusted EPA a play, the starting QB against his team's recent QB play, rest, home field and injuries, fit on 2012-25. injuries come from the league's game status report, ESPN and Rotoballer's news: each non-QB on the report costs his WAR a game times his chance to miss (out 100%, doubtful 98%, questionable 25%, or 50% if he also missed the last game, probable 5%, from how listed players have played since 2016), and a questionable QB starts at his 60% chance to play, with his backup in for the rest. the injury term cut the 2021-25 miss from 10.18 to 10.13 points a game. tested on 2021-25 against the closing line, the model misses by 10.1 points a game against the market's 9.8 and finds no betting edge, so it's a second opinion to read next to the line, not a picks service.

player projections are PPR points for every QB, RB, WR and TE playing this week: his per-game line with recent games counted more and last season's a little, touchdowns pulled partway toward what his yards usually produce, against the defense's PPR allowed to his position and his team's implied points from the market. each piece was kept only if it lowered the miss on the season it wasn't picked on.
{{< /winpane >}}

{{< wintabs groups="players:WAR leaders,team WAR,QB value|games:games,game table,projections|teams:power rankings,season odds" label="NFL views" >}}
{{< nflwar title="NFL WAR :: leaderboards" tab="WAR leaders" >}}
{{< nflteamwar title="team WAR :: by position group" tab="team WAR" >}}
{{< nflqb title="QB value :: points a game over a replacement QB" tab="QB value" >}}
{{< nflgames title="games" tab="games" >}}
{{< nflgametable title="game table" tab="game table" >}}
{{< nflproj title="projections" tab="projections" >}}
{{< nflpower title="power rankings" tab="power rankings" >}}
{{< nflsim title="season odds" tab="season odds" >}}
{{< /wintabs >}}
