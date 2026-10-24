+++
title = "Soccer Prospects :: ARKBOARD"
url = "/arkboard/soccer-prospects/"
description = "Soccer Prospects ARKBOARD: every player under 22 at the season start in 33 leagues (the big five, 9 more European top flights, second divisions, Brazil, Argentina, MLS, Premier League 2), graded on the 20-80 FV scale: the mean outcome of past prospects with the same profile, peak senior value at ages 22-26. Backtested on the 2013-20 seasons: age, market value, this season's value at club strength, minutes share, scoring, size, position."
keywords = ["arkboard", "soccer prospects", "football prospects", "wonderkids", "under 21", "under 22", "best young players", "future value", "20-80 scale", "big board", "transfermarkt", "market value"]
draft = false
+++

{{< arknav >}}

{{< winpane title="soccer_prospects.exe :: under-22 big board" icon="soccer" sprite="px/hero-soccer" status="Transfermarkt lineups and values · 33 leagues" >}}
Every player **under 22 on July 1** with a lineup spot last season or this one in the 14 European top flights, the second divisions of the big five, Netherlands and Portugal, Brazil, Argentina, MLS, seven more European leagues, or Premier League 2, graded on what past prospects with the same profile became. Under 22 is where the age curve says a player is still a projection: at 21 the average player still gains about a quarter of his value before his peak, at 23 nothing. **Value** is goals above replacement: minutes times his club's strength (goals a match against an average big-five side, from every result and the squad's market value). **FV** is the mean outcome: peak value, his best three seasons at ages 22-26, ranked by how rare it is within a birth year at his position. The model starts from **age and market value**, then adds what the backtest kept out of sample. Players with no senior minutes yet carry a **prov** tag.
{{< /winpane >}}

{{< wintabs groups="board:big board|history:past prospects,fv model" label="Soccer prospects views" >}}
{{< soccerboard view="board" tab="big board" >}}
{{< soccerboard view="past" tab="past prospects" >}}
{{< soccerboard view="model" title="fv model :: value, scale, drivers, calibration" tab="fv model" >}}
{{< /wintabs >}}
