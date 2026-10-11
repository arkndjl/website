+++
title = "NFL :: ARKBOARD"
url = "/arkboard/nfl/"
description = "NFL WAR leaderboards (every player's wins above replacement this season, overall and by position) and NFL game projections: a model line, win probability and projected score for every game next to the market. updates automatically through the season."
keywords = ["arkboard", "nfl", "nfl war", "nfl game projections", "nfl model", "wins above replacement", "approximate value", "leaderboard"]
draft = false
+++

{{< arknav >}}

{{< winpane title="nfl.exe :: NFL WAR and games" icon="football" sprite="px/hero-football" status="nflverse · PFR AV" >}}
NFL WAR is wins above replacement: what a player has added to his team this season over a freely available one. it's (AV - replacement AV x snap share) x .091. replacement is what a freely available player at the position earns over a full season of snaps (the AV rate of part-timers: TE 2.6, WR 5.0, DB 5.1, OL 6.7, LB 6.9, DL 7.4, QB 7.9, RB 9.0), charged in proportion to the snaps a player takes, and every AV above that is .091 wins (the 2021-25 fit of team wins on team AV, r .84). a team of replacements wins about 3 of 17, so a team's WAR adds up to its wins less 3. below replacement is negative. AV is Approximate Value, rebuilt each week from play stats, snaps and scoring the way Pro Football Reference builds it (team offense and defense pools split by role and production) and fit to PFR's own AV: it tracks PFR at r .91 on a single season of rookies it never saw. pick a position for its leaderboard, or per 17 games for the rate view.

the game model lines up every game with Elo, opponent-adjusted EPA a play, the starting QB against his team's recent QB play, rest and home field, fit on 2012-25. tested on 2021-25 against the closing line, it misses by 10.2 points a game against the market's 9.8 and finds no betting edge, so it's a second opinion to read next to the line, not a picks service.
{{< /winpane >}}

{{< wintabs tabs="WAR leaders,games,game table" label="NFL views" >}}
{{< nflwar title="NFL WAR :: leaderboards" tab="WAR leaders" >}}
{{< nflgames title="games" tab="games" >}}
{{< nflgametable title="game table" tab="game table" >}}
{{< /wintabs >}}
