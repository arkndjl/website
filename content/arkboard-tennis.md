+++
title = "Tennis :: ARKBOARD"
url = "/arkboard/tennis/"
description = "Tennis on ARKBOARD: an ARK Ranking for every ATP and WTA singles player from our own ratings (surface Elo on wins, a games-won rating and opponent-adjusted serve and return point ratings run through the game, set and match chain), win chances and fair odds for the week's matches, and serve and return metrics: points won over average against the opponents faced, expected hold and break, dominance ratio and break points over expected. Built on every ATP and WTA match since 2005 at every level, backtested out of sample and against the closing line."
keywords = ["arkboard", "ark ranking", "tennis", "atp", "wta", "tennis elo", "surface elo", "tennis rankings", "tennis model", "tennis win probability", "serve points won", "return points won", "hold percentage", "break percentage", "dominance ratio"]
draft = false
+++

{{< arknav >}}

{{< winpane title="tennis.exe :: the ATP and WTA tours" icon="tennis" sprite="px/hero-tennis" status="Sackmann archive · weekly tour feed · ESPN" class="winpane--art" />}}

{{< wintabs groups="matches:matches,results|ATP:ATP ARK Ranking,ATP serve + return|WTA:WTA ARK Ranking,WTA serve + return|model:model" label="Tennis views" >}}
{{< tennismatches title="matches :: ATP + WTA singles" tab="matches" >}}
{{< tennismatches view="results" title="results :: the last three days, against the model" tab="results" >}}
{{< tennisrank tour="atp" title="ATP :: ARK Ranking" tab="ATP ARK Ranking" >}}
{{< lazytab tab="ATP serve + return" >}}{{< tennisstats tour="atp" title="ATP :: serve + return" tab="ATP serve + return" >}}{{< /lazytab >}}
{{< lazytab tab="WTA ARK Ranking" >}}{{< tennisrank tour="wta" title="WTA :: ARK Ranking" tab="WTA ARK Ranking" >}}{{< /lazytab >}}
{{< lazytab tab="WTA serve + return" >}}{{< tennisstats tour="wta" title="WTA :: serve + return" tab="WTA serve + return" >}}{{< /lazytab >}}
{{< tennismodel title="model :: how the ratings are built and how they score" tab="model" >}}
{{< /wintabs >}}
