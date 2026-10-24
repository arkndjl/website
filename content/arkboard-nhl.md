+++
title = "NHL :: ARKBOARD"
url = "/arkboard/nhl/"
description = "NHL game projections, power rankings, season odds, goalie ratings, WAR leaderboard and backup watch. games: model win chance and fair moneyline, projected score, overtime chance and tonight's starting goalies; power rankings from Elo and expected goals (MoneyPuck xG), Stanley Cup and playoff odds from 10,000 simulated seasons; goalies by goals saved above expected."
keywords = ["arkboard", "nhl", "nhl game projections", "nhl model", "nhl power rankings", "nhl playoff odds", "stanley cup odds", "expected goals", "xg", "goals saved above expected", "gsax", "hockey analytics", "nhl war", "wins above replacement"]
draft = false
+++

{{< arknav >}}

{{< winpane title="nhl.exe :: NHL games and teams" icon="hockey" sprite="px/hero-hockey" status="NHL API · MoneyPuck xG · ESPN · Daily Faceoff" >}}
Win chances come from **Elo**, an **expected-goals rating** (MoneyPuck's adjusted xG for and against, opponent-adjusted, recent games weighted most), **back-to-backs** and **home ice**: the inputs that cut walk-forward log loss on 2016-23 without the 2023-26 seasons disagreeing. Goalies, goals, rest, 5-on-5 and special-teams ratings were tested and didn't add to them. Season odds: 10,000 simulated seasons and playoff brackets. **WAR** is fit to team goal differential: last season's shrunk player rates (on-ice xG, primary assists, individual xG, penalty kill, goalies' saves above expected) predict this season's team results.
{{< /winpane >}}

{{< wintabs groups="games:games,game table|teams:power rankings,season odds,goalies|players:WAR leaders,backup watch" label="NHL views" >}}
{{< nhlgames title="games" tab="games" >}}
{{< nhlgametable title="game table" tab="game table" >}}
{{< nhlpower title="power rankings" tab="power rankings" >}}
{{< nhlsim title="season odds" tab="season odds" >}}
{{< nhlgoalies title="goalies :: goals saved above expected" tab="goalies" >}}
{{< nhlwar title="NHL WAR :: leaderboard" tab="WAR leaders" >}}
{{< backupwatch sport="nhl" title="backup watch" tab="backup watch" >}}
{{< /wintabs >}}
