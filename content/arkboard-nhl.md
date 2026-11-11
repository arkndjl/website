+++
title = "NHL :: ARKBOARD"
url = "/arkboard/nhl/"
description = "NHL game projections, ARK Ranking (power rankings), season odds, goalie ratings, WAR leaderboard and backup watch. games: model win chance and fair moneyline, projected score, overtime chance and tonight's starting goalies; power rankings from Elo and expected goals (MoneyPuck xG), Stanley Cup and playoff odds from 10,000 simulated seasons; goalies by goals saved above expected. projections: 20th, 50th and 80th percentile WAR, goals, assists, points and shots, full season and rest of season."
keywords = ["arkboard", "ark ranking", "nhl", "nhl game projections", "nhl model", "nhl power rankings", "nhl playoff odds", "stanley cup odds", "expected goals", "xg", "goals saved above expected", "gsax", "hockey analytics", "nhl war", "wins above replacement"]
draft = false
cover = "/og/nhl.png"
+++

{{< arknav >}}

{{< winpane title="nhl.exe :: 2026-27" icon="hockey" sprite="px/hero-hockey" status="NHL API · MoneyPuck xG · ESPN · Daily Faceoff" class="winpane--art" />}}

{{< wintabs groups="players:WAR leaders,goalies,projections,contract value,rookies,ARKLIST|rosters:depth chart,lines,backup watch,transactions|games:games,game table|teams:ARK Ranking,season odds,offense,defense,power play,penalty kill" side="true" label="NHL views" >}}
{{< nhlgames title="games" tab="games" >}}
{{< nhlgametable title="game table" tab="game table" >}}
{{< nhlpower title="ARK Ranking" tab="ARK Ranking" >}}
{{< nhlsim title="season odds" tab="season odds" >}}
{{< lazytab tab="offense" >}}
{{< teamunits sport="nhl" view="offense" title="offense" tab="offense" >}}
{{< /lazytab >}}
{{< lazytab tab="defense" >}}
{{< teamunits sport="nhl" view="defense" title="defense" tab="defense" >}}
{{< /lazytab >}}
{{< lazytab tab="power play" >}}
{{< teamunits sport="nhl" view="power play" title="power play" tab="power play" >}}
{{< /lazytab >}}
{{< lazytab tab="penalty kill" >}}
{{< teamunits sport="nhl" view="penalty kill" title="penalty kill" tab="penalty kill" >}}
{{< /lazytab >}}
{{< nhlgoalies title="goalies" tab="goalies" >}}
{{< nhlwar title="NHL WAR" tab="WAR leaders" >}}
{{< pctl sport="nhl" icon="hockey" title="projections" tab="projections" >}}
{{< xaav sport="nhl" title="contract value" tab="contract value" >}}
{{< rookies sport="nhl" icon="hockey" title="rookies" tab="rookies" >}}
{{< backupwatch sport="nhl" title="backup watch" tab="backup watch" >}}
{{< arklist sport="nhl" title="ARKLIST" tab="ARKLIST" >}}
{{< depthchart sport="nhl" title="depth chart" tab="depth chart" >}}
{{< nhllines title="lines" tab="lines" >}}
{{< lazytab tab="transactions" >}}
{{< transactions sport="nhl" title="transactions" tab="transactions" >}}
{{< /lazytab >}}
{{< /wintabs >}}
