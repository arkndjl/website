+++
title = "NBA :: ARKBOARD"
url = "/arkboard/nba/"
description = "NBA game projections and XPM leaderboard. games: model line, win probability and projected score, with tonight's injuries; ARK Ranking (power rankings) and season odds. XPM leaderboard: XPM, the ARKBOARD's NBA impact metric (50/50 databallr DPM + Basketball-Reference BPM), ranked by VORX, wins over replacement fit to NBA team wins, with offense and defense splits, and XPM (proj), the season to date blended with a preseason prior. contract value: projected wins x the market $ per win against salary, this season and over the contract. every season since 2009-10, filter by minutes, position, team and age. projections: 20th, 50th and 80th percentile VORX, points, rebounds, assists, 3s, steals and blocks, full season and rest of season."
keywords = ["arkboard", "ark ranking", "nba", "nba game projections", "nba model", "nba power rankings", "nba playoff odds", "xpm", "dpm", "bpm", "nba leaderboard", "plus minus", "vorp", "nba impact metric", "g league", "g league call-ups", "two-way contracts"]
draft = false
cover = "/og/nba.png"
+++

{{< arknav >}}

{{< winpane title="nba.exe :: 2026-27" icon="basketball" sprite="px/hero-basketball" status="databallr DPM · Basketball-Reference BPM · LUMA ARC (CC BY 4.0) · ESPN · NBA injury report" class="winpane--art" />}}

{{< wintabs groups="players:leaders,projections,rookies,awards,all-time players,ARKLIST|rosters:depth chart,lineups,transactions|games:games,game table|teams:ARK Ranking,units,all-time|market:payrolls,free agents,contract value" side="true" label="NBA views" >}}
{{< wintabs tab="leaders" tabs="VORX/XPM leaders,matchups" sub="true" label="leaders views" >}}
{{< nbaxpm title="NBA XPM" tab="VORX/XPM leaders" >}}
{{< lazytab tab="matchups" >}}
{{< nbamatchups title="matchups" tab="matchups" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< pctl sport="nba" icon="basketball" title="projections" tab="projections" >}}
{{< wintabs tab="payrolls" tabs="payrolls,cap space,contracts" sub="true" label="payrolls views" >}}
{{< lazytab tab="payrolls" >}}{{< payrolls lg="nba" view="teams" tab="payrolls" >}}{{< /lazytab >}}
{{< lazytab tab="cap space" >}}{{< payrolls lg="nba" view="space" tab="cap space" >}}{{< /lazytab >}}
{{< lazytab tab="contracts" >}}{{< payrolls lg="nba" view="contracts" tab="contracts" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< lazytab tab="free agents" >}}{{< payrolls lg="nba" view="fa" tab="free agents" >}}{{< /lazytab >}}
{{< nbasurplus title="contract value" tab="contract value" >}}
{{< wintabs tab="rookies" tabs="rookies,next up,G League" sub="true" label="rookies views" >}}
{{< rookies sport="nba" icon="basketball" title="rookies" tab="rookies" >}}
{{< lazytab tab="next up" >}}
{{< rookies sport="nba" src="data/next-up/nba-tab.json" icon="basketball" title="next up" tab="next up" >}}
{{< /lazytab >}}
{{< gleague title="G League" tab="G League" >}}
{{< /wintabs >}}
{{< wintabs tab="awards" tabs="predictive awards,conviction awards" sub="true" label="awards views" >}}
{{< awards sport="nba" tab="predictive awards" >}}
{{< awards sport="nba" tab="conviction awards" view="conv" >}}
{{< /wintabs >}}
{{< arklist sport="nba" title="ARKLIST" tab="ARKLIST" >}}
{{< nbagames title="games" tab="games" >}}
{{< nbagametable title="game table" tab="game table" >}}
{{< lazytab tab="transactions" >}}
{{< transactions sport="nba" title="transactions" tab="transactions" >}}
{{< /lazytab >}}
{{< wintabs tab="depth chart" tabs="depth chart,backup watch" sub="true" label="depth chart views" >}}
{{< depthchart sport="nba" title="depth chart" tab="depth chart" >}}
{{< backupwatch sport="nba" title="backup watch" tab="backup watch" >}}
{{< /wintabs >}}
{{< wintabs tab="lineups" tabs="lineups,on/off,lineup leaders" sub="true" label="lineups views" >}}
{{< nbalineups title="lineups" tab="lineups" >}}
{{< nbalineups title="on/off" tab="on/off" view="onoff" >}}
{{< lineupleaders sport="nba" title="lineup leaders" tab="lineup leaders" >}}
{{< /wintabs >}}
{{< wintabs tab="ARK Ranking" tabs="ARK Ranking,season odds,bracket" sub="true" label="ARK Ranking views" >}}
{{< nbapower title="ARK Ranking" tab="ARK Ranking" >}}
{{< nbasim title="season odds" tab="season odds" >}}
{{< lazytab tab="bracket" >}}{{< bracket k="nba" title="projected bracket" tab="bracket" icon="basketball" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="units" tabs="offense,defense" sub="true" label="units views" >}}
{{< lazytab tab="offense" >}}
{{< teamunits sport="nba" view="offense" title="offense" tab="offense" >}}
{{< /lazytab >}}
{{< lazytab tab="defense" >}}
{{< teamunits sport="nba" view="defense" title="defense" tab="defense" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="all-time" tabs="all-time teams,all-time offenses,all-time defenses,all-time coaches" sub="true" label="all-time views" >}}
{{< lazytab tab="all-time teams" >}}
{{< alltime sport="nba" list="teams" title="all-time teams" tab="all-time teams" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time offenses" >}}
{{< alltime sport="nba" list="offense" title="all-time offenses" tab="all-time offenses" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time defenses" >}}
{{< alltime sport="nba" list="defense" title="all-time defenses" tab="all-time defenses" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time coaches" >}}
{{< coachalltime sport="nba" title="all-time coaches" tab="all-time coaches" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="all-time players" tabs="peak seasons,careers" sub="true" label="all-time players views" >}}
{{< lazytab tab="peak seasons" >}}
{{< alltime sport="nba" list="peak" title="peak seasons" tab="peak seasons" >}}
{{< /lazytab >}}
{{< lazytab tab="careers" >}}
{{< alltime sport="nba" list="career" title="careers" tab="careers" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< /wintabs >}}
