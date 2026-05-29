+++
title = "MLB PROSPX Preview / Closed Alpha"
date = "2026-05-28T14:00:42-06:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["mlb", "prospect", "prospx"]
keywords = ["mlb", "baseball", "statistics", "prospects"]
description = "Previewing my new tool MLB PROSPX, an all-in-one prospect tracker."
showFullContent = false
readingTime = false
hideComments = true
draft = false
+++


## Introduction  
This article will be discussing the creation and details surrounding my new project, **MLB PROSPX**. MLB PROSPX is an all-in-one prospect/farm system module that derives 20-80 scale FV/tool grades from aggregated industry consensus, using these in conjunction with newly created metrics/features (WAG, DvM+, RPS+, SC+, etc.) to create a comprehensive home for prospect analysis. MLB PROSPX is part of a bigger sabermetric website called EEPHUS.IO, which will feature an extensive array of both prospect and MLB-level evaluation modules, releasing later this year. 

This article is releasing in conjunction with the v0.1 closed Alpha test, where I’m having industry experts, prospect writers, and individuals who work for MLB teams test the site and give feedback. The Beta will be openly available to the public and will release at some point this summer, and will implement feedback from the closed Alpha test, as well as new planned features and feature requests from the closed Alpha test. 

In this article, I wanted to discuss my methodology for creating this site. This site has been a passion project of mine that I’ve spent a ludicrous amount of time on over the past month, and was birthed from my desire as a baseball fan, sabermetrics fanatic, and prospect fiend to have an all-in-one comprehensive home for prospect and farm system evaluations. Throughout the course of creating this project, I’ve had a bit of a scope “issue”, where I keep having more ideas, and more ideas to build upon previous ideas, and ideas to build on those ideas… after an enormous time/effort crunch, I’ve finally gotten the site to a point that I’m happy with, featuring an extensive amount of detail, polish, and features. I’m incredibly proud of what I’ve built and can’t wait to hear feedback from the Alpha test group, and eventually, the world. 

Hypothetically, **there is a clear path for integration of MLB PROSPX for use by an MLB organization or organizations, where I would utilize scouting data from an organization’s scouts, as well as take advantage of more extensive statistics and API availability within each organization, in order to integrate MLB PROSPX and my Arkmetrics fully into an organization’s pre-existing prospect/farm system evaluation tools (or to create them from scratch).** I’ve been in contact with MLB teams already about the site and would like for PROSPX to contribute to the sabermetric world and to an MLB organization. If you work for an MLB team and are interested in pursuing this, or want to speak with me directly to discuss the site,  please contact me on Twitter @ARKNDJL, connect with me on LinkedIn ([https://www.linkedin.com/in/noahjdengler/](https://www.linkedin.com/in/noahjdengler/)), or email me: [ARKNDJL@gmail.com](mailto:ARKNDJL@gmail.com). I am passionate about sabermetrics, actively seeking internship/employment opportunities in Major League Baseball, and I dream of working for an MLB front office. 

///

This site started with a simple premise: What if you could track prospect FVs visually over time, like a “stock chart”? To do this, I’ve aggregated industry sources and used them to derive consensus FV grades and tool grades for all prospects in MLB baseball. After doing this, the next step was integrating stats from the MLB API and integrating Statcast, as well as creating a farm systems section to evaluate organizational aptitude at acquiring and developing prospects. This expanded further until getting to the amount of sections available today, which is pictured below: 

{{< image src="/img/prospx/img1.png" alt="test" position="center" style="border-radius: 8px;" >}}

This article will be showcase previews of each section, showcasing features and metrics along the way.

Sections  
Here’s a look at how the current MiLB prospects section looks, featuring FV history charts for all prospects, stats, Statcast integration, player bios/information, tool grades, calculated ETA projections (using a combination of performance, level proximity to the MLB, age, injury history, and MLB organization promotional aggression tendencies). Each prospect also has a “rarity border” given by their FV grade. For example, Made and de Vries are \>60 FV prospects, so they’ve been given holographic borders on their player pictures and ranks. Indicators are displayed on FV history charts to mark when prospects have been promoted/demoted between MiLB levels, traded, or have been noted by a source as having upside. The dotted purple curve represents a prospect’s cumulative tool grade (Tool+) over time, while the solid line represents their overall consensusFV grade over time. Prospect health is indicated via the health-symbol glyph, prospects are given different indicators on their FV grade chip based on a variety of factors (ex. the teal star corresponds to a prospect being marked as a “breakout”, the purple W corresponds to a prospect being marked as having a wide-source disagreement between different source FV grades, etc), and there’s a variety of other details (positional versa, RPS+, SC+, etc.) also included here.  
{{< image src="/img/prospx/img2.png" alt="test" position="center" style="border-radius: 8px;" >}}

Users can add prospects to a user-specific “watchlist” by clicking the star button and can compare prospects using the \+, which I’ll showcase below: 

{{< image src="/img/prospx/img3.png" alt="test" position="center" style="border-radius: 8px;" >}}

Let’s look at what prospect detail pages look like when you click on a prospect:  
{{< image src="/img/prospx/img4.png" alt="test" position="center" style="border-radius: 8px;" >}}
There is too much information to fully preview the detail put into these prospect pages, so you’ll have to wait for the full site to see the extensive amount of information available across the Overview, Stats/Statcast, Scouting/Tools, and Details tabs, but I promise that anything you can think of is here.

The site also features dark mode, which looks like this: 

{{< image src="/img/prospx/img5.png" alt="test" position="center" style="border-radius: 8px;" >}}

Here is how the farm systems page looks:   
{{< image src="/img/prospx/img6.png" alt="test" position="center" style="border-radius: 8px;" >}}

Farm system pages also expand into detailed farm system pages when clicking on them, which features extensive information and a grade tree. The grade tree can be expanded to view the entire grade hierarchy, but I’m showing it in “canopy” view here. Farm system pages feature tabs for Overview / Roster / Development / Finances / Transactions & Pipeline. Using DvM+ and ToolDvM+, I’m able to evaluate how farm systems develop players, and there is extensive information and weighting that goes into farm system grades. Here’s an example of what farm system detail pages look like, using the Mariners: 
{{< image src="/img/prospx/img7.png" alt="test" position="center" style="border-radius: 8px;" >}}

Here is how the transactions section looks: 

{{< image src="/img/prospx/img8.png" alt="test" position="center" style="border-radius: 8px;" >}}

Injured List section: 

{{< image src="/img/prospx/img9.png" alt="test" position="center" style="border-radius: 8px;" >}}

Leaderboards: 

{{< image src="/img/prospx/img10.png" alt="test" position="center" style="border-radius: 8px;" >}}

Debuted prospects section (graduates), featuring WAG (WAR above Grade): 

{{< image src="/img/prospx/img11.png" alt="test" position="center" style="border-radius: 8px;" >}}

MLB Draft Section: 

{{< image src="/img/prospx/img12.png" alt="test" position="center" style="border-radius: 8px;" >}}

International Amateurs Section: 

{{< image src="/img/prospx/img13.png" alt="test" position="center" style="border-radius: 8px;" >}}

Overseas prospect section: 

{{< image src="/img/prospx/img14.png" alt="test" position="center" style="border-radius: 8px;" >}}

Scatterplots section: 

{{< image src="/img/prospx/img15.png" alt="test" position="center" style="border-radius: 8px;" >}}

And finally, the glossary:

{{< image src="/img/prospx/img16.png" alt="test" position="center" style="border-radius: 8px;" >}}

You’ll be able to view these pages in more detail very soon. The methodology for new metrics and the site in general is extensively documented in the glossary section, and you’ll be able to hover-over for information on different stats, indicators, and metrics anywhere on the site.

///

Thank you for reading this primer/preview on the site, and I’m excited for you to test the site soon in the upcoming open Beta. The launch for the closed Alpha will be tonight, and I’ll keep a development log going here on my website to document the process towards getting PROSPX ready for launch.

