+++
title = "NHL :: ARKBOARD"
url = "/arkboard/nhl/"
description = "NHL game projections, power rankings, season odds, goalie ratings, WAR leaderboard and backup watch. games: model win chance and fair moneyline, projected score, overtime chance and tonight's starting goalies; power rankings from Elo and expected goals (MoneyPuck xG), Stanley Cup and playoff odds from 10,000 simulated seasons; goalies by goals saved above expected."
keywords = ["arkboard", "nhl", "nhl game projections", "nhl model", "nhl power rankings", "nhl playoff odds", "stanley cup odds", "expected goals", "xg", "goals saved above expected", "gsax", "hockey analytics", "nhl war", "wins above replacement"]
draft = false
+++

{{< arknav >}}

{{< winpane title="nhl.exe :: NHL games and teams" icon="hockey" sprite="px/hero-hockey" status="NHL API · MoneyPuck xG · ESPN · Daily Faceoff" class="winpane--art" />}}

{{< wintabs groups="players:WAR leaders,backup watch,ARKLIST|games:games,game table|teams:power rankings,season odds,goalies" label="NHL views" >}}
{{< nhlgames title="games" tab="games" >}}
{{< nhlgametable title="game table" tab="game table" >}}
{{< nhlpower title="power rankings" tab="power rankings" >}}
{{< nhlsim title="season odds" tab="season odds" >}}
{{< nhlgoalies title="goalies :: goals saved above expected" tab="goalies" >}}
{{< nhlwar title="NHL WAR :: leaderboard" tab="WAR leaders" >}}
{{< backupwatch sport="nhl" title="backup watch" tab="backup watch" >}}
{{< arklist sport="nhl" title="ARKLIST :: NHL" tab="ARKLIST" >}}
{{< /wintabs >}}
