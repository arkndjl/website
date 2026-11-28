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

{{< wintabs groups="players:leaders,projections,rookies,awards,all-time players,ARKLIST|rosters:depth chart,lines,transactions|games:games,game table|teams:ARK Ranking,units,team builder,all-time|market:payrolls,free agents,contract value" side="true" label="NHL views" >}}
{{< nhlgames title="games" tab="games" >}}
{{< nhlgametable title="game table" tab="game table" >}}
{{< wintabs tab="projections" tabs="projections,OVR" sub="true" label="projections views" >}}
{{< pctl sport="nhl" icon="hockey" title="projections" tab="projections" >}}
{{< lazytab tab="OVR" >}}{{< ovr sport="nhl" title="NHL :: OVR" tab="OVR" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="payrolls" tabs="payrolls,cap space,contracts" sub="true" label="payrolls views" >}}
{{< lazytab tab="payrolls" >}}{{< payrolls lg="nhl" view="teams" tab="payrolls" >}}{{< /lazytab >}}
{{< lazytab tab="cap space" >}}{{< payrolls lg="nhl" view="space" tab="cap space" >}}{{< /lazytab >}}
{{< lazytab tab="contracts" >}}{{< payrolls lg="nhl" view="contracts" tab="contracts" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< lazytab tab="free agents" >}}{{< payrolls lg="nhl" view="fa" tab="free agents" >}}{{< /lazytab >}}
{{< xaav sport="nhl" title="contract value" tab="contract value" >}}
{{< wintabs tab="rookies" tabs="rookies,next up" sub="true" label="rookies views" >}}
{{< rookies sport="nhl" icon="hockey" title="rookies" tab="rookies" >}}
{{< lazytab tab="next up" >}}
{{< rookies sport="nhl" src="data/next-up/nhl-tab.json" icon="hockey" title="next up" tab="next up" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="awards" tabs="predictive awards,conviction awards" sub="true" label="awards views" >}}
{{< awards sport="nhl" tab="predictive awards" >}}
{{< awards sport="nhl" tab="conviction awards" view="conv" >}}
{{< /wintabs >}}
{{< arklist sport="nhl" title="ARKLIST" tab="ARKLIST" >}}
{{< nhllines title="lines" tab="lines" >}}
{{< lazytab tab="transactions" >}}
{{< transactions sport="nhl" title="transactions" tab="transactions" >}}
{{< /lazytab >}}
{{< wintabs tab="leaders" tabs="WAR leaders,goalies" sub="true" label="leaders views" >}}
{{< nhlwar title="NHL WAR" tab="WAR leaders" >}}
{{< nhlgoalies title="goalies" tab="goalies" >}}
{{< /wintabs >}}
{{< wintabs tab="depth chart" tabs="depth chart,backup watch" sub="true" label="depth chart views" >}}
{{< depthchart sport="nhl" title="depth chart" tab="depth chart" >}}
{{< backupwatch sport="nhl" title="backup watch" tab="backup watch" >}}
{{< /wintabs >}}
{{< wintabs tab="ARK Ranking" tabs="ARK Ranking,team OVR,season odds,bracket" sub="true" label="ARK Ranking views" >}}
{{< lazytab tab="team OVR" >}}{{< ovrteams sport="nhl" title="NHL :: team OVR" tab="team OVR" >}}{{< /lazytab >}}
{{< nhlpower title="ARK Ranking" tab="ARK Ranking" >}}
{{< nhlsim title="season odds" tab="season odds" >}}
{{< lazytab tab="bracket" >}}{{< bracket k="nhl" title="projected bracket" tab="bracket" icon="hockey" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="units" tabs="offense,defense,power play,penalty kill" sub="true" label="units views" >}}
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
{{< /wintabs >}}
{{< probuilder lg="nhl" title="team builder" tab="team builder" >}}
{{< wintabs tab="all-time" tabs="all-time teams,all-time offenses,all-time defenses,all-time coaches" sub="true" label="all-time views" >}}
{{< lazytab tab="all-time teams" >}}
{{< alltime sport="nhl" list="teams" title="all-time teams" tab="all-time teams" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time offenses" >}}
{{< alltime sport="nhl" list="offense" title="all-time offenses" tab="all-time offenses" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time defenses" >}}
{{< alltime sport="nhl" list="defense" title="all-time defenses" tab="all-time defenses" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time coaches" >}}
{{< coachalltime sport="nhl" title="all-time coaches" tab="all-time coaches" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="all-time players" tabs="peak seasons,careers" sub="true" label="all-time players views" >}}
{{< lazytab tab="peak seasons" >}}
{{< alltime sport="nhl" list="peak" title="peak seasons" tab="peak seasons" >}}
{{< /lazytab >}}
{{< lazytab tab="careers" >}}
{{< alltime sport="nhl" list="career" title="careers" tab="careers" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< /wintabs >}}
