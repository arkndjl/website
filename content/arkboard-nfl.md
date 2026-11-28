+++
title = "NFL :: ARKBOARD"
url = "/arkboard/nfl/"
description = "NFL WAR leaderboards: wins above replacement by player and position, season to date. game projections: model line, win probability, projected score; lines and picks are on the Predictions page. fantasy projections now live on the Predictions page. updated automatically in season. projections: 20th, 50th and 80th percentile WAR and stats, full season and rest of season."
keywords = ["arkboard", "ark ranking", "nfl", "nfl war", "nfl game projections", "nfl model", "wins above replacement", "approximate value", "leaderboard"]
draft = false
cover = "/og/nfl.png"
+++

{{< arknav >}}

{{< winpane title="nfl.exe :: 2026" icon="football" sprite="px/hero-football" status="nflverse · PFR AV" class="winpane--art" />}}

{{< wintabs groups="players:leaders,projections,standouts,awards,all-time players,ARKLIST|rosters:depth chart,personnel,transactions|games:games,game table|teams:ARK Ranking,units,team builder,all-time|market:payrolls,free agents,contract value" side="true" label="NFL views" >}}
{{< wintabs tab="projections" tabs="projections,OVR" sub="true" label="projections views" >}}
{{< pctl sport="nfl" icon="football" title="projections" tab="projections" >}}
{{< lazytab tab="OVR" >}}{{< ovr sport="nfl" title="NFL :: OVR" tab="OVR" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="payrolls" tabs="payrolls,cap space,contracts" sub="true" label="payrolls views" >}}
{{< lazytab tab="payrolls" >}}{{< payrolls lg="nfl" view="teams" tab="payrolls" >}}{{< /lazytab >}}
{{< lazytab tab="cap space" >}}{{< payrolls lg="nfl" view="space" tab="cap space" >}}{{< /lazytab >}}
{{< lazytab tab="contracts" >}}{{< payrolls lg="nfl" view="contracts" tab="contracts" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< lazytab tab="free agents" >}}{{< payrolls lg="nfl" view="fa" tab="free agents" >}}{{< /lazytab >}}
{{< xaav sport="nfl" title="contract value" tab="contract value" >}}
{{< wintabs tab="standouts" tabs="standouts,next up,rookies" sub="true" label="standouts views" >}}
{{< rookies sport="nfl" icon="football" title="rookies" tab="rookies" >}}
{{< nflbreakouts title="standouts" tab="standouts" >}}
{{< lazytab tab="next up" >}}
{{< rookies sport="nfl" src="data/next-up/nfl-tab.json" icon="football" title="next up" tab="next up" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="awards" tabs="predictive awards,conviction awards" sub="true" label="awards views" >}}
{{< awards sport="nfl" tab="predictive awards" >}}
{{< awards sport="nfl" tab="conviction awards" view="conv" >}}
{{< /wintabs >}}
{{< arklist sport="nfl" title="ARKLIST" tab="ARKLIST" >}}
{{< nflgames title="games" tab="games" >}}
{{< nflgametable title="game table" tab="game table" >}}
{{< nflpersonnel title="personnel" tab="personnel" >}}
{{< lazytab tab="transactions" >}}
{{< transactions sport="nfl" title="transactions" tab="transactions" >}}
{{< /lazytab >}}
{{< wintabs tab="leaders" tabs="WAR leaders,QBs,skill players,defenders,specialists" sub="true" label="leaders views" >}}
{{< nflwar title="WAR leaders" tab="WAR leaders" >}}
{{< nflqb title="QBs" tab="QBs" >}}
{{< nflseason group="skill" title="skill players" tab="skill players" >}}
{{< nflseason group="defense" title="defenders" tab="defenders" >}}
{{< streturners sport="nfl" title="specialists" tab="specialists" >}}
{{< /wintabs >}}
{{< wintabs tab="depth chart" tabs="depth chart,backup watch" sub="true" label="depth chart views" >}}
{{< depthchart sport="nfl" title="depth chart" tab="depth chart" >}}
{{< backupwatch sport="nfl" title="backup watch" tab="backup watch" >}}
{{< /wintabs >}}
{{< wintabs tab="ARK Ranking" tabs="ARK Ranking,team OVR,season odds,bracket" sub="true" label="ARK Ranking views" >}}
{{< lazytab tab="team OVR" >}}{{< ovrteams sport="nfl" title="NFL :: team OVR" tab="team OVR" >}}{{< /lazytab >}}
{{< nflpower title="ARK Ranking" tab="ARK Ranking" >}}
{{< nflsim title="season odds" tab="season odds" >}}
{{< lazytab tab="bracket" >}}{{< bracket k="nfl" title="projected bracket" tab="bracket" icon="football" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="units" tabs="offense,defense,formations,special teams,team WAR" sub="true" label="units views" >}}
{{< lazytab tab="offense" >}}
{{< teamunits sport="nfl" view="offense" title="offense" tab="offense" >}}
{{< /lazytab >}}
{{< lazytab tab="defense" >}}
{{< teamunits sport="nfl" view="defense" title="defense" tab="defense" >}}
{{< /lazytab >}}
{{< lazytab tab="formations" >}}
{{< teamunits sport="nfl" view="formations,fronts" title="formations" tab="formations" >}}
{{< /lazytab >}}
{{< lazytab tab="special teams" >}}
{{< stteams sport="nfl" title="special teams" tab="special teams" >}}
{{< /lazytab >}}
{{< nflteamwar title="team WAR" tab="team WAR" >}}
{{< /wintabs >}}
{{< probuilder lg="nfl" title="team builder" tab="team builder" >}}
{{< wintabs tab="all-time" tabs="all-time teams,all-time offenses,all-time defenses,all-time coaches" sub="true" label="all-time views" >}}
{{< lazytab tab="all-time teams" >}}
{{< alltime sport="nfl" list="teams" title="all-time teams" tab="all-time teams" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time offenses" >}}
{{< alltime sport="nfl" list="offense" title="all-time offenses" tab="all-time offenses" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time defenses" >}}
{{< alltime sport="nfl" list="defense" title="all-time defenses" tab="all-time defenses" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time coaches" >}}
{{< coachalltime sport="nfl" title="all-time coaches" tab="all-time coaches" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="all-time players" tabs="peak seasons,careers,QB peak seasons,QB careers" sub="true" label="all-time players views" >}}
{{< lazytab tab="peak seasons" >}}
{{< alltime sport="nfl" list="peak" title="peak seasons" tab="peak seasons" >}}
{{< /lazytab >}}
{{< lazytab tab="careers" >}}
{{< alltime sport="nfl" list="career" title="careers" tab="careers" >}}
{{< /lazytab >}}
{{< lazytab tab="QB peak seasons" >}}
{{< alltime sport="nfl" list="peak" group="qbs" title="QB peak seasons" tab="QB peak seasons" >}}
{{< /lazytab >}}
{{< lazytab tab="QB careers" >}}
{{< alltime sport="nfl" list="career" group="qbs" title="QB careers" tab="QB careers" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< /wintabs >}}
