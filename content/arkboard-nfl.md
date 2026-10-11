+++
title = "NFL :: ARKBOARD"
url = "/arkboard/nfl/"
description = "NFL WAR leaderboards: every NFL player's wins above replacement this season, overall and by position, from Approximate Value rebuilt from play stats and snaps. updates automatically through the season."
keywords = ["arkboard", "nfl", "nfl war", "wins above replacement", "approximate value", "leaderboard"]
draft = false
+++

{{< arknav >}}

{{< winpane title="nfl.exe :: NFL WAR" icon="football" sprite="px/hero-football" status="nflverse · PFR AV" >}}
NFL WAR is wins above replacement: what a player has added to his team this season over a freely available one. it's (AV - 6.2 x snap share) x .091: a replacement player earns about 6.2 AV over a full season of snaps, charged in proportion to the snaps a player takes, and every AV above that is .091 wins (the 2021-25 fit of team wins on team AV, r .84). a team of replacements wins about 3 of 17, so a team's WAR adds up to its wins less 3. below replacement is negative. AV is Approximate Value, rebuilt each week from play stats, snaps and scoring the way Pro Football Reference builds it (team offense and defense pools split by role and production) and fit to PFR's own AV: it tracks PFR at r .91 on a single season of rookies it never saw. pick a position for its leaderboard, or per 17 games for the rate view.
{{< /winpane >}}

{{< nflwar title="NFL WAR :: leaderboards" >}}
