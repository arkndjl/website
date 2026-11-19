+++
title = "Soccer :: ARKBOARD"
url = "/arkboard/soccer/"
description = "Soccer match projections, ARK Ranking (power rankings) and season odds for the Premier League, La Liga, Bundesliga, Serie A, Ligue 1, the Eredivisie, Primeira Liga, Belgian Pro League, Süper Lig, Czech First League, Greek Super League, Ekstraklasa, Danish Superliga, Swiss Super League, Eliteserien, Austrian Bundesliga, Scottish Premiership, Allsvenskan, MLS, the Champions League, Europa League and Conference League, and national teams (a world ranking, internationals and the UEFA Nations League): home, draw and away chances from ratings on goals, expected goals (Understat, FotMob) and the market's earlier prices; one power ranking across every league; title, top-four and relegation odds, MLS play-off and MLS Cup odds and UEFA knockout odds from 10,000 simulated seasons; player value (goals above replacement and estimated market value against Transfermarkt's) and xG, xA and xGChain stats for every big-five player."
keywords = ["arkboard", "ark ranking", "soccer", "football", "premier league", "la liga", "bundesliga", "serie a", "ligue 1", "eredivisie", "primeira liga", "danish superliga", "scottish premiership", "super lig", "champions league", "europa league", "conference league", "mls", "mls cup odds", "nations league", "world cup", "euro", "national team rankings", "soccer power rankings", "soccer model", "title odds", "relegation odds", "champions league odds", "expected goals", "xg"]
draft = false
cover = "/og/soccer.png"
+++

{{< arknav >}}

{{< winpane title="soccer.exe :: 2026-27" icon="soccer" sprite="px/hero-soccer" status="ESPN · FotMob · Understat xG · football-data.co.uk" class="winpane--art" />}}

{{< wintabs groups="players:leaders,rookies,next up,awards,all-time players,ARKLIST|rosters:depth chart,lineups,transactions|games:games,game table|teams:ARK Ranking,units,all-time,managers|leagues:big five,more leagues,MLS,UEFA cups,national teams" side="true" label="Soccer views" >}}
{{< soccergames title="games" tab="games" >}}
{{< soccergametable title="game table" tab="game table" >}}
{{< lazytab tab="ARK Ranking" >}}{{< soccerpower title="ARK Ranking" tab="ARK Ranking" >}}{{< /lazytab >}}
{{< rookies sport="soccer" icon="soccer" title="rookies" tab="rookies" >}}
{{< lazytab tab="next up" >}}
{{< rookies sport="soccer" src="data/next-up/soccer-tab.json" icon="soccer" title="next up" tab="next up" >}}
{{< /lazytab >}}
{{< lazytab tab="awards" >}}{{< awards sport="soccer" tab="awards" >}}{{< /lazytab >}}
{{< arklist sport="soccer" title="ARKLIST" tab="ARKLIST" >}}
{{< soccerlineups title="lineups" tab="lineups" >}}
{{< lazytab tab="transactions" >}}
{{< transactions sport="soccer" title="transactions" tab="transactions" >}}
{{< /lazytab >}}
{{< wintabs tab="leaders" tabs="GAR leaders,player stats,top speed" sub="true" label="leaders views" >}}
{{< soccerplayers view="value" title="GAR leaders" tab="GAR leaders" >}}
{{< soccerplayers view="stats" title="player stats" tab="player stats" >}}
{{< lazytab tab="top speed" >}}{{< soccerextra k="speed" tab="top speed" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="depth chart" tabs="depth chart,backup watch" sub="true" label="depth chart views" >}}
{{< depthchart sport="soccer" title="depth chart" tab="depth chart" >}}
{{< backupwatch sport="soccer" title="backup watch" tab="backup watch" >}}
{{< /wintabs >}}
{{< wintabs tab="units" tabs="offense,defense,set pieces" sub="true" label="units views" >}}
{{< lazytab tab="offense" >}}
{{< teamunits sport="soccer" view="attack" title="offense" tab="offense" >}}
{{< /lazytab >}}
{{< lazytab tab="defense" >}}
{{< teamunits sport="soccer" view="defence" title="defense" tab="defense" >}}
{{< /lazytab >}}
{{< lazytab tab="set pieces" >}}
{{< teamunits sport="soccer" view="set pieces" title="set pieces" tab="set pieces" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="big five" tabs="Premier League,La Liga,Bundesliga,Serie A,Ligue 1" sub="true" label="big five views" >}}
{{< soccerleague lg="eng.1" title="Premier League" tab="Premier League" >}}
{{< soccerleague lg="esp.1" title="La Liga" tab="La Liga" >}}
{{< soccerleague lg="ger.1" title="Bundesliga" tab="Bundesliga" >}}
{{< soccerleague lg="ita.1" title="Serie A" tab="Serie A" >}}
{{< soccerleague lg="fra.1" title="Ligue 1" tab="Ligue 1" >}}
{{< /wintabs >}}
{{< wintabs tab="more leagues" tabs="Eredivisie,Primeira Liga,Pro League,Super Lig,Czech Liga,Greek SL,Ekstraklasa,Superliga,Swiss SL,Eliteserien,Austria,Scottish Prem,Allsvenskan" sub="true" label="more leagues views" >}}
{{< lazytab tab="Eredivisie" >}}{{< soccerleague lg="ned.1" title="Eredivisie" tab="Eredivisie" >}}{{< /lazytab >}}
{{< lazytab tab="Primeira Liga" >}}{{< soccerleague lg="por.1" title="Primeira Liga" tab="Primeira Liga" >}}{{< /lazytab >}}
{{< lazytab tab="Pro League" >}}{{< soccerleague lg="bel.1" title="Belgian Pro League" tab="Pro League" >}}{{< /lazytab >}}
{{< lazytab tab="Super Lig" >}}{{< soccerleague lg="tur.1" title="Süper Lig" tab="Super Lig" >}}{{< /lazytab >}}
{{< lazytab tab="Czech Liga" >}}{{< soccerleague lg="cze.1" title="Czech First League" tab="Czech Liga" >}}{{< /lazytab >}}
{{< lazytab tab="Greek SL" >}}{{< soccerleague lg="gre.1" title="Greek Super League" tab="Greek SL" >}}{{< /lazytab >}}
{{< lazytab tab="Ekstraklasa" >}}{{< soccerleague lg="pol.1" title="Ekstraklasa" tab="Ekstraklasa" >}}{{< /lazytab >}}
{{< lazytab tab="Superliga" >}}{{< soccerleague lg="den.1" title="Danish Superliga" tab="Superliga" >}}{{< /lazytab >}}
{{< lazytab tab="Swiss SL" >}}{{< soccerleague lg="sui.1" title="Swiss Super League" tab="Swiss SL" >}}{{< /lazytab >}}
{{< lazytab tab="Eliteserien" >}}{{< soccerleague lg="nor.1" title="Eliteserien" tab="Eliteserien" >}}{{< /lazytab >}}
{{< lazytab tab="Austria" >}}{{< soccerleague lg="aut.1" title="Austrian Bundesliga" tab="Austria" >}}{{< /lazytab >}}
{{< lazytab tab="Scottish Prem" >}}{{< soccerleague lg="sco.1" title="Scottish Premiership" tab="Scottish Prem" >}}{{< /lazytab >}}
{{< lazytab tab="Allsvenskan" >}}{{< soccerleague lg="swe.1" title="Allsvenskan" tab="Allsvenskan" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="MLS" tabs="MLS,MLS bracket,MLS players,MLS keepers" sub="true" label="MLS views" >}}
{{< lazytab tab="MLS" >}}{{< soccermls tab="MLS" >}}{{< /lazytab >}}
{{< lazytab tab="MLS bracket" >}}{{< bracket k="soccer" title="projected bracket" tab="MLS bracket" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="MLS players" >}}{{< soccerextra k="mls" tab="MLS players" >}}{{< /lazytab >}}
{{< lazytab tab="MLS keepers" >}}{{< soccerextra k="mlsgk" tab="MLS keepers" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< lazytab tab="managers" >}}{{< soccerextra k="managers" tab="managers" >}}{{< /lazytab >}}
{{< wintabs tab="UEFA cups" tabs="Champions League,Europa League,Conference League,UCL bracket,UEL bracket,UECL bracket" sub="true" label="UEFA cups views" >}}
{{< socceruefa lg="uefa.champions" title="Champions League" tab="Champions League" >}}
{{< socceruefa lg="uefa.europa" title="Europa League" tab="Europa League" >}}
{{< socceruefa lg="uefa.europa.conf" title="Conference League" tab="Conference League" >}}
{{< lazytab tab="UCL bracket" >}}{{< bracket k="ucl" title="Champions League projected bracket" tab="UCL bracket" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="UEL bracket" >}}{{< bracket k="uel" title="Europa League projected bracket" tab="UEL bracket" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="UECL bracket" >}}{{< bracket k="uecl" title="Conference League projected bracket" tab="UECL bracket" icon="soccer" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="national teams" tabs="world ranking,internationals,Nations League,scorers" sub="true" label="national teams views" >}}
{{< lazytab tab="world ranking" >}}{{< soccerintl view="ranking" title="world ranking" tab="world ranking" >}}{{< /lazytab >}}
{{< lazytab tab="internationals" >}}{{< soccerintl view="games" title="internationals" tab="internationals" >}}{{< /lazytab >}}
{{< lazytab tab="Nations League" >}}{{< soccerintl view="nl" title="Nations League" tab="Nations League" >}}{{< /lazytab >}}
{{< lazytab tab="scorers" >}}{{< soccerextra k="scorers" tab="scorers" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="all-time" tabs="all-time teams,all-time offenses,all-time defenses" sub="true" label="all-time views" >}}
{{< lazytab tab="all-time teams" >}}
{{< alltime sport="soccer" list="teams" title="all-time teams" tab="all-time teams" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time offenses" >}}
{{< alltime sport="soccer" list="offense" title="all-time offenses" tab="all-time offenses" >}}
{{< /lazytab >}}
{{< lazytab tab="all-time defenses" >}}
{{< alltime sport="soccer" list="defense" title="all-time defenses" tab="all-time defenses" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="all-time players" tabs="peak seasons,careers" sub="true" label="all-time players views" >}}
{{< lazytab tab="peak seasons" >}}
{{< alltime sport="soccer" list="peak" title="peak seasons" tab="peak seasons" >}}
{{< /lazytab >}}
{{< lazytab tab="careers" >}}
{{< alltime sport="soccer" list="career" title="careers" tab="careers" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< /wintabs >}}
