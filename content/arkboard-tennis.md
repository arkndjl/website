+++
title = "Tennis :: ARKBOARD"
url = "/arkboard/tennis/"
description = "Tennis on ARKBOARD: an ARK Ranking for every ATP and WTA singles player from our own ratings (surface Elo on wins, a games-won rating and opponent-adjusted serve and return point ratings run through the game, set and match chain), win chances and fair odds for the week's matches, and serve and return metrics: points won over average against the opponents faced, expected hold and break, dominance ratio and break points over expected. Built on every ATP and WTA match since 2005 at every level, backtested out of sample and against the closing line."
keywords = ["arkboard", "ark ranking", "tennis", "atp", "wta", "tennis elo", "surface elo", "tennis rankings", "tennis model", "tennis win probability", "serve points won", "return points won", "hold percentage", "break percentage", "dominance ratio"]
draft = false
+++

{{< arknav >}}

{{< winpane title="tennis.exe" icon="tennis" sprite="px/hero-tennis" status="Sackmann archive · weekly tour feed · ESPN" class="winpane--art" />}}

{{< wintabs groups="players:ATP,WTA,all-time|games:games,game table,event odds|model:model" side="true" label="Tennis views" >}}
{{< tennismatches title="games" tab="games" >}}
{{< tennismatches view="results" title="game table" tab="game table" >}}
{{< lazytab tab="event odds" >}}{{< tennisevents tab="event odds" >}}{{< /lazytab >}}
{{< tennismodel title="model" tab="model" >}}
{{< wintabs tab="ATP" tabs="ATP ARK Ranking,ATP serve + return" sub="true" label="ATP views" >}}
{{< tennisrank tour="atp" title="ATP :: ARK Ranking" tab="ATP ARK Ranking" >}}
{{< lazytab tab="ATP serve + return" >}}{{< tennisstats tour="atp" title="ATP :: serve + return" tab="ATP serve + return" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="WTA" tabs="WTA ARK Ranking,WTA serve + return" sub="true" label="WTA views" >}}
{{< lazytab tab="WTA ARK Ranking" >}}{{< tennisrank tour="wta" title="WTA :: ARK Ranking" tab="WTA ARK Ranking" >}}{{< /lazytab >}}
{{< lazytab tab="WTA serve + return" >}}{{< tennisstats tour="wta" title="WTA :: serve + return" tab="WTA serve + return" >}}{{< /lazytab >}}
{{< /wintabs >}}
{{< wintabs tab="all-time" tabs="ATP peaks,ATP careers,WTA peaks,WTA careers" sub="true" label="all-time views" >}}
{{< lazytab tab="ATP peaks" >}}
{{< alltime sport="atp" list="peak" title="ATP peaks" tab="ATP peaks" >}}
{{< /lazytab >}}
{{< lazytab tab="ATP careers" >}}
{{< alltime sport="atp" list="career" title="ATP careers" tab="ATP careers" >}}
{{< /lazytab >}}
{{< lazytab tab="WTA peaks" >}}
{{< alltime sport="wta" list="peak" title="WTA peaks" tab="WTA peaks" >}}
{{< /lazytab >}}
{{< lazytab tab="WTA careers" >}}
{{< alltime sport="wta" list="career" title="WTA careers" tab="WTA careers" >}}
{{< /lazytab >}}
{{< /wintabs >}}
{{< /wintabs >}}
