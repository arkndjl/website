+++
title = "Hockey Prospects :: ARKBOARD"
url = "/arkboard/hockey-prospects/"
description = "Hockey Prospects ARKBOARD: the 2027 NHL draft class and every drafted player still short of the NHL, graded on the 20-80 FV scale (the mean outcome, peak NHL WAR). The draft model is backtested on the 2008-19 classes: draft slot, draft-year production translated to NHL points (NHLe) and league; refit each season after the draft. Past classes with what every pick became. 2027 NHL mock drafts: predictive, blended, conviction."
keywords = ["arkboard", "hockey prospects", "nhl draft", "2027 nhl draft", "nhl draft rankings", "nhl prospects", "future value", "20-80 scale", "big board", "nhle", "nhl mock draft", "2027 nhl mock draft"]
draft = false
+++

{{< arknav >}}

{{< winpane title="hockey_prospects.exe :: 2027 NHL draft and prospects" icon="hockey" sprite="px/hero-hockey" status="NHL API · Tankathon · Central Scouting · MoneyPuck" >}}
Grades are the **mean NHL outcome** of past picks with the same profile: peak value is the best three WAR seasons in a player's first seven after the draft, and the 20-80 cuts come from how rare each peak was among 2,541 picks from 2008-19. The draft model starts from **draft slot** (for the 2027 class, the slot Tankathon's rank points to) and adds **draft-year production** translated to NHL points (NHLe), with the discount the backtest found for **CHL** scoring; age, size, Central Scouting's rank and the other inputs didn't add out of sample. After the draft, each season's line, pro or junior, and NHL games refit the grade. **Mock drafts**: the projected standings order from the NHL page's simulated seasons, three ways (consensus, our FV, the midpoint).
{{< /winpane >}}

{{< wintabs groups="draft:big board,drafted prospects|mock draft:predictive mock,blended mock,conviction mock,lottery|history:past classes,fv model" label="Hockey prospects views" >}}
{{< hockeyboard view="board" tab="big board" >}}
{{< hockeyboard view="pipe" tab="drafted prospects" >}}
{{< hockeymock mode="pred" tab="predictive mock" >}}
{{< hockeymock mode="blend" tab="blended mock" >}}
{{< hockeymock mode="conv" tab="conviction mock" >}}
{{< hockeymock mode="lottery" tab="lottery" >}}
{{< hockeyboard view="past" tab="past classes" >}}
{{< hockeyboard view="model" title="fv model :: scale, drivers, calibration" tab="fv model" >}}
{{< /wintabs >}}
