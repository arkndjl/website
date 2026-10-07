+++
title = "eephus.io"
description = "eephus.io is my sabermetrics site and the home of MLB PROSPX, my prospect/farm system evaluation tool: consensus 20-80 FV grades tracked over time, my own metrics, and Statcast data."
keywords = ["eephus.io", "MLB PROSPX", "sabermetrics", "MLB prospects", "farm systems", "baseball analytics", "arkndjl"]
draft = false
+++

{{< card url="https://eephus.io" title="eephus.io" icon="img/eephus-favicon.png" >}}
**my sabermetrics site**, and the home of **MLB PROSPX**, my prospect/farm system evaluation tool. it has consensus 20–80 FV and tool grades tracked over time like a stock chart, my own metrics (WAG, DvM+, RPS+, SC+, Tool+), MLB API + Statcast data, farm system grades, draft/international/overseas boards, scatterplots you can build yourself, and a glossary for all of it.
{{< /card >}}

## watch

[eephus.io Full Website Showcase + Preview (Video)](/posts/eephus-io-video/)

{{< video id="xCu_OGQyEY0" title="eephus.io Full Website Showcase + Preview" width="560" >}}

[watch on YouTube](https://www.youtube.com/watch?v=xCu_OGQyEY0)

## what it is

as a baseball fan, sabermetrics fanatic, and prospect fiend, i always wanted one place for prospect and farm system evaluation, so i built [eephus.io](https://eephus.io). it also has MLB-level evaluation modules and projections. it's been my main passion project since spring 2026, and i keep adding to it as i get more ideas.

the main module is **MLB PROSPX**. it started with one idea: track a prospect's Future Value grade over time, like a stock chart. i combine industry sources into consensus FV and tool grades for every prospect in affiliated baseball (3,135 prospects tracked at the alpha launch) and pull in stats from the MLB API and Statcast. everything else (new metrics, farm system grades, draft and international boards, and the tools to look through it all) is built on top of that.

## what's inside

- **MiLB Prospects**: consensus FV history charts for every prospect (solid line = consensus FV, dotted purple = cumulative Tool+), marked with promotions/demotions, trades, and noted upside. also stats, Statcast, bios, tool grades, health, positional versatility, and ETA projections (based on performance, how close they are to the majors, age, injury history, and how aggressively each org promotes). FV-based "rarity borders" (60+ FV prospects get holographic cards) and chips for breakouts, wide source disagreement, etc. you can star prospects for a watchlist or compare them side by side.
- **Prospect pages**: Overview / Stats & Statcast / Scouting & Tools / Details tabs, with RPS+ (vs. same-age peers), the SC+ composite (100 = pool average), surplus value, and the prospect's FV "stock" movement.
- **Farm Systems**: every organization graded, with acquisition / development / finances / production sub-grades, 6YDvM+ and Tool DvM+ development indices, six-year trajectories, level depth, average age, spend mix (international vs. draft), ROI, and surplus. each system has its own page with a full grade tree and Overview / Roster / Development / Finances / Transactions & Pipeline tabs.
- **Transactions**, **Injured List**, and **Leaderboards** across the whole prospect pool.
- **Debuted**: graduated prospects, with WAG (WAR above Grade): production relative to the expectation set by a prospect's grade.
- **MLB Draft**, **International Amateurs**, and **Overseas** prospect boards.
- **Scatterplots**: pick any prospect group and any two stats for the axes, toggle a least-squares trendline + R², click any dot to open that player.
- **Glossary**: how every metric and indicator works, plus hover-over definitions across the site. there's a dark mode too.

## how i think about it

i think of a consensus grade like a market price, and when sources disagree a lot, that tells you something too (that's what the wide-disagreement flag is for). a prospect's FV changes over time, so i care about the chart as much as the current number. i also think orgs should be graded the same way as players, on what they acquire, what they develop, what it costs, and what it produces.

## timeline

- **May 28, 2026**: MLB PROSPX v0.1 closed alpha, tested by industry experts, prospect writers, and people who work for MLB teams. the [preview article](/posts/mlb-prospx-preview/) goes through every section with screenshots.
- **summer 2026**: open beta, with changes from alpha feedback plus new features and feature requests.
- **now**: live at [eephus.io](https://eephus.io) with prospect analysis and MLB projections. more prospect and MLB-level modules are planned.

## for MLB organizations

MLB PROSPX could work inside a front office. with an org's own scouting data, internal stats, and API access, PROSPX and my metrics ("Arkmetrics") could add to the prospect/farm system tools a team already has, or be the starting point if it doesn't have any. i've already talked with MLB teams about the site. if you work for a team and want to talk, reach me on twitter [@ARKNDJL](https://x.com/ARKNDJL), on [LinkedIn](https://www.linkedin.com/in/noahdengler/), or at [ARKNDJL@gmail.com](mailto:ARKNDJL@gmail.com).

## related writing

- [MLB PROSPX Preview / Closed Alpha](/posts/mlb-prospx-preview/): methodology and a walkthrough of each section
- [Potential 2026 MLB Prospect Breakouts: Introduction](/posts/mlb-prospect-breakouts-2026/): quantitative, qualitative, and mixed-methods indicators of breakouts
- [Evaluating Every U19 Prospect In MiLB (May 2026)](/posts/u19-milb-evaluations-may26/)
- [2026 Prospect Grades: Chicago White Sox](/posts/prospect-grades-chicago-white-sox/)
- [State Of The Mets, Pre Trade Deadline 2026](/posts/state-of-the-mets-pre-deadline/): PROSPX breakout flags used on the Mets
- more: [#prospx](/tags/prospx/) · [#prospect](/tags/prospect/) · [#mlb](/tags/mlb/)
