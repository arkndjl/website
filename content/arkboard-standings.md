+++
title = "Standings :: ARKBOARD"
url = "/arkboard/standings/"
description = "Standings, no model numbers: NFL, NBA and NHL standings and the playoff picture as it stands; college football and college basketball conference standings with the AP, Coaches and CFP polls; official stat leaders; scores and schedules; 18 soccer league tables, MLS and the UEFA league phases with goals and assists leaders; the ATP and WTA rankings; Valve's CS2 ranking."
keywords = ["arkboard", "standings", "games to watch", "best games this week", "nfl standings", "nba standings", "nhl standings", "college football standings", "college basketball standings", "playoff picture", "stat leaders", "ap poll", "coaches poll", "cfp rankings", "premier league table", "champions league table", "atp rankings", "wta rankings", "valve regional standings", "scores"]
draft = false
+++

{{< arknav >}}

{{< winpane title="standings.exe" icon="standings" sprite="px/hero-standings" status="" class="winpane--art" />}}

{{< wintabs groups="scores:games to watch|football:NFL,CFB|basketball:NBA,CBB|hockey:NHL|soccer:big five,more leagues,MLS,UEFA cups|tennis:ATP ranking,WTA ranking|esports:CS2 ranking" side="true" label="Standings views" >}}
{{< lazytab tab="games to watch" >}}{{< watch tab="games to watch" >}}{{< /lazytab >}}
{{< lazytab tab="ATP ranking" >}}{{< standings part="rank" k="atp" title="ATP ranking" tab="ATP ranking" icon="tennis" >}}{{< /lazytab >}}
{{< lazytab tab="WTA ranking" >}}{{< standings part="rank" k="wta" title="WTA ranking" tab="WTA ranking" icon="tennis" >}}{{< /lazytab >}}
{{< lazytab tab="CS2 ranking" >}}{{< standings part="vrs" title="Counter-Strike" tab="CS2 ranking" >}}{{< /lazytab >}}
{{< wintabs tab="NFL" tabs="NFL standings,NFL playoffs,NFL bracket,NFL leaders,NFL scores" sub="true" label="NFL views" >}}
{{< lazytab tab="NFL standings" >}}{{< standings part="table" k="nfl" title="NFL standings" tab="NFL standings" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="NFL playoffs" >}}{{< standings part="picture" k="nfl" title="NFL playoff picture" tab="NFL playoffs" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="NFL bracket" >}}{{< bracket k="nfl" title="NFL projected bracket" tab="NFL bracket" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="NFL leaders" >}}{{< standings part="leaders" k="nfl" title="NFL stat leaders" tab="NFL leaders" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="NFL scores" >}}{{< standings part="scores" k="nfl" title="NFL scores and schedule" tab="NFL scores" icon="football" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="CFB" tabs="CFB standings,CFB polls,CFB bracket,CFB leaders,CFB scores" sub="true" label="CFB views" >}}
{{< lazytab tab="CFB standings" >}}{{< standings part="table" k="cfb" title="CFB standings" tab="CFB standings" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="CFB polls" >}}{{< standings part="polls" k="cfb" title="CFB polls" tab="CFB polls" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="CFB bracket" >}}{{< bracket k="cfb" title="CFP projected bracket" tab="CFB bracket" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="CFB leaders" >}}{{< standings part="leaders" k="cfb" title="CFB stat leaders" tab="CFB leaders" icon="football" >}}{{< /lazytab >}}
{{< lazytab tab="CFB scores" >}}{{< standings part="scores" k="cfb" title="CFB scores and schedule" tab="CFB scores" icon="football" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="NBA" tabs="NBA standings,NBA playoffs,NBA bracket,NBA leaders,NBA scores" sub="true" label="NBA views" >}}
{{< lazytab tab="NBA standings" >}}{{< standings part="table" k="nba" title="NBA standings" tab="NBA standings" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="NBA playoffs" >}}{{< standings part="picture" k="nba" title="NBA playoff picture" tab="NBA playoffs" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="NBA bracket" >}}{{< bracket k="nba" title="NBA projected bracket" tab="NBA bracket" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="NBA leaders" >}}{{< standings part="leaders" k="nba" title="NBA stat leaders" tab="NBA leaders" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="NBA scores" >}}{{< standings part="scores" k="nba" title="NBA scores and schedule" tab="NBA scores" icon="basketball" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="CBB" tabs="CBB standings,CBB polls,CBB bracket,CBB leaders,CBB scores" sub="true" label="CBB views" >}}
{{< lazytab tab="CBB standings" >}}{{< standings part="table" k="cbb" title="CBB standings" tab="CBB standings" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="CBB polls" >}}{{< standings part="polls" k="cbb" title="CBB polls" tab="CBB polls" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="CBB bracket" >}}{{< bracket k="cbb" title="NCAA tournament projected bracket" tab="CBB bracket" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="CBB leaders" >}}{{< standings part="leaders" k="cbb" title="CBB stat leaders" tab="CBB leaders" icon="basketball" >}}{{< /lazytab >}}
{{< lazytab tab="CBB scores" >}}{{< standings part="scores" k="cbb" title="CBB scores and schedule" tab="CBB scores" icon="basketball" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="NHL" tabs="NHL standings,NHL playoffs,NHL bracket,NHL leaders,NHL scores" sub="true" label="NHL views" >}}
{{< lazytab tab="NHL standings" >}}{{< standings part="table" k="nhl" title="NHL standings" tab="NHL standings" icon="hockey" >}}{{< /lazytab >}}
{{< lazytab tab="NHL playoffs" >}}{{< standings part="picture" k="nhl" title="NHL playoff picture" tab="NHL playoffs" icon="hockey" >}}{{< /lazytab >}}
{{< lazytab tab="NHL bracket" >}}{{< bracket k="nhl" title="NHL projected bracket" tab="NHL bracket" icon="hockey" >}}{{< /lazytab >}}
{{< lazytab tab="NHL leaders" >}}{{< standings part="leaders" k="nhl" title="NHL stat leaders" tab="NHL leaders" icon="hockey" >}}{{< /lazytab >}}
{{< lazytab tab="NHL scores" >}}{{< standings part="scores" k="nhl" title="NHL scores and schedule" tab="NHL scores" icon="hockey" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="big five" tabs="Premier League,La Liga,Bundesliga,Serie A,Ligue 1" sub="true" label="big five views" >}}
{{< lazytab tab="Premier League" >}}{{< standings part="table" k="eng.1" title="Premier League table" tab="Premier League" icon="soccer" >}}{{< standings part="leaders" k="eng.1" title="Premier League" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="La Liga" >}}{{< standings part="table" k="esp.1" title="La Liga table" tab="La Liga" icon="soccer" >}}{{< standings part="leaders" k="esp.1" title="La Liga" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Bundesliga" >}}{{< standings part="table" k="ger.1" title="Bundesliga table" tab="Bundesliga" icon="soccer" >}}{{< standings part="leaders" k="ger.1" title="Bundesliga" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Serie A" >}}{{< standings part="table" k="ita.1" title="Serie A table" tab="Serie A" icon="soccer" >}}{{< standings part="leaders" k="ita.1" title="Serie A" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Ligue 1" >}}{{< standings part="table" k="fra.1" title="Ligue 1 table" tab="Ligue 1" icon="soccer" >}}{{< standings part="leaders" k="fra.1" title="Ligue 1" icon="soccer" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="more leagues" tabs="Eredivisie,Primeira Liga,Pro League,Super Lig,Czech Liga,Greek SL,Ekstraklasa,Superliga,Swiss SL,Eliteserien,Austria,Scottish Prem,Allsvenskan" sub="true" label="more leagues views" >}}
{{< lazytab tab="Eredivisie" >}}{{< standings part="table" k="ned.1" title="Eredivisie table" tab="Eredivisie" icon="soccer" >}}{{< standings part="leaders" k="ned.1" title="Eredivisie" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Primeira Liga" >}}{{< standings part="table" k="por.1" title="Primeira Liga table" tab="Primeira Liga" icon="soccer" >}}{{< standings part="leaders" k="por.1" title="Primeira Liga" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Pro League" >}}{{< standings part="table" k="bel.1" title="Belgian Pro League table" tab="Pro League" icon="soccer" >}}{{< standings part="leaders" k="bel.1" title="Pro League" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Super Lig" >}}{{< standings part="table" k="tur.1" title="Super Lig table" tab="Super Lig" icon="soccer" >}}{{< standings part="leaders" k="tur.1" title="Super Lig" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Czech Liga" >}}{{< standings part="table" k="cze.1" title="Czech Liga table" tab="Czech Liga" icon="soccer" >}}{{< standings part="leaders" k="cze.1" title="Czech Liga" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Greek SL" >}}{{< standings part="table" k="gre.1" title="Greek SL table" tab="Greek SL" icon="soccer" >}}{{< standings part="leaders" k="gre.1" title="Greek SL" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Ekstraklasa" >}}{{< standings part="table" k="pol.1" title="Ekstraklasa table" tab="Ekstraklasa" icon="soccer" >}}{{< standings part="leaders" k="pol.1" title="Ekstraklasa" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Superliga" >}}{{< standings part="table" k="den.1" title="Superliga table" tab="Superliga" icon="soccer" >}}{{< standings part="leaders" k="den.1" title="Superliga" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Swiss SL" >}}{{< standings part="table" k="sui.1" title="Swiss SL table" tab="Swiss SL" icon="soccer" >}}{{< standings part="leaders" k="sui.1" title="Swiss SL" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Eliteserien" >}}{{< standings part="table" k="nor.1" title="Eliteserien table" tab="Eliteserien" icon="soccer" >}}{{< standings part="leaders" k="nor.1" title="Eliteserien" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Austria" >}}{{< standings part="table" k="aut.1" title="Austria table" tab="Austria" icon="soccer" >}}{{< standings part="leaders" k="aut.1" title="Austria" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Scottish Prem" >}}{{< standings part="table" k="sco.1" title="Scottish Prem table" tab="Scottish Prem" icon="soccer" >}}{{< standings part="leaders" k="sco.1" title="Scottish Prem" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Allsvenskan" >}}{{< standings part="table" k="swe.1" title="Allsvenskan table" tab="Allsvenskan" icon="soccer" >}}{{< standings part="leaders" k="swe.1" title="Allsvenskan" icon="soccer" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="MLS" tabs="MLS,MLS bracket" sub="true" label="MLS views" >}}
{{< lazytab tab="MLS" >}}{{< standings part="table" k="usa.1" title="MLS table" tab="MLS" icon="soccer" >}}{{< standings part="leaders" k="usa.1" title="MLS" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="MLS bracket" >}}{{< bracket k="soccer" title="MLS projected bracket" tab="MLS bracket" icon="soccer" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="UEFA cups" tabs="Champions League,Europa League,Conference League,UCL bracket,UEL bracket,UECL bracket" sub="true" label="UEFA cups views" >}}
{{< lazytab tab="Champions League" >}}{{< standings part="table" k="uefa.champions" title="Champions League table" tab="Champions League" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Europa League" >}}{{< standings part="table" k="uefa.europa" title="Europa League table" tab="Europa League" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="Conference League" >}}{{< standings part="table" k="uefa.europa.conf" title="Conference League table" tab="Conference League" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="UCL bracket" >}}{{< bracket k="ucl" title="Champions League projected bracket" tab="UCL bracket" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="UEL bracket" >}}{{< bracket k="uel" title="Europa League projected bracket" tab="UEL bracket" icon="soccer" >}}{{< /lazytab >}}
{{< lazytab tab="UECL bracket" >}}{{< bracket k="uecl" title="Conference League projected bracket" tab="UECL bracket" icon="soccer" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< /wintabs >}}
