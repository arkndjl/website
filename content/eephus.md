+++
title = "eephus.io"
description = "eephus.io is my sabermetrics site and the home of MLB PROSPX: an all-in-one prospect and farm system evaluation tool built on consensus 20-80 FV grades tracked over time, original metrics, and Statcast integration."
keywords = ["eephus.io", "MLB PROSPX", "sabermetrics", "MLB prospects", "farm systems", "baseball analytics", "arkndjl"]
draft = false
+++

{{< card url="https://eephus.io" title="eephus.io" >}}
**my sabermetrics site**, and the home of **MLB PROSPX**: an all-in-one prospect / farm system evaluation tool. consensus 20–80 FV and tool grades tracked over time like a stock chart, original metrics (WAG, DvM+, RPS+, SC+, Tool+), MLB API + Statcast integration, farm system grades, draft / international / overseas boards, build-your-own scatterplots, and a glossary documenting all of it.
{{< /card >}}

## what it is

[eephus.io](https://eephus.io) is the site i built to be the thing i always wanted as a baseball fan, sabermetrics fanatic, and prospect fiend: one comprehensive home for prospect and farm system evaluation, with MLB-level evaluation modules and projections layered on top. it's been my main passion project since spring 2026, and the scope has kept growing from one idea to the next.

the core module is **MLB PROSPX**. it started with a simple premise: what if you could track a prospect's Future Value grade visually over time, like a stock chart? to do that, i aggregate industry sources into consensus FV and tool grades for every prospect in affiliated baseball (3,135 prospects tracked at the alpha launch), integrate stats from the MLB API and Statcast, and build everything else outward from there: new metrics, farm system evaluation, draft and international boards, and tooling to explore all of it.

## what's inside

- **MiLB Prospects** — consensus FV history charts for every prospect (solid line = consensus FV, dotted purple = cumulative Tool+), with markers for promotions/demotions, trades, and noted upside. stats, Statcast, bios, tool grades, health, positional versatility, and calculated ETA projections (performance, proximity to the majors, age, injury history, and each organization's promotional aggressiveness). FV-based "rarity borders" (60+ FV prospects get holographic cards) and chip indicators for breakouts, wide source disagreement, and more. star a prospect for your watchlist, or compare prospects side by side.
- **Prospect pages** — Overview / Stats & Statcast / Scouting & Tools / Details tabs, with RPS+ (vs. same-age peers), the SC+ composite (100 = pool average), surplus value, and the prospect's FV "stock" movement.
- **Farm Systems** — every organization graded, with acquisition / development / finances / production sub-grades, 6YDvM+ and Tool DvM+ development indices, six-year trajectories, level depth, average age, spend mix (international vs. draft), ROI, and surplus. each system expands into a detail page with a full grade tree and Overview / Roster / Development / Finances / Transactions & Pipeline tabs.
- **Transactions**, **Injured List**, and **Leaderboards** across the whole prospect pool.
- **Debuted** — graduated prospects, featuring WAG (WAR above Grade): production relative to the expectation set by a prospect's grade.
- **MLB Draft**, **International Amateurs**, and **Overseas** prospect boards.
- **Scatterplots** — pick any prospect group and any two stats for the axes, toggle a least-squares trendline + R², click any dot to open that player.
- **Glossary** — the methodology for every metric and indicator, plus hover-over definitions anywhere on the site. dark mode included.

## how i think about it

a few ideas run through the whole site. a consensus grade is a market price, and the spread between sources is information in its own right (hence the wide-disagreement flag). a prospect's FV is a time series, not a snapshot, so the chart matters at least as much as the number. and organizations deserve to be graded on the same curve as players: what they acquire, what they develop, what it costs, and what it produces.

## timeline

- **May 28, 2026** — MLB PROSPX v0.1 closed alpha, tested by industry experts, prospect writers, and people who work for MLB teams. the [preview article](/posts/mlb-prospx-preview/) walks through every section with screenshots.
- **summer 2026** — open beta, incorporating alpha feedback plus new features and feature requests.
- **now** — live at [eephus.io](https://eephus.io) with detailed prospect analysis and MLB projections, with more prospect and MLB-level evaluation modules planned.

## for MLB organizations

there is a clear path to integrating MLB PROSPX inside a front office: plug in an organization's own scouting data and its internal statistics and API access, and PROSPX plus my metrics ("Arkmetrics") can extend an existing prospect / farm system evaluation stack, or stand one up from scratch. i've already been in contact with MLB teams about the site. if you work for a team and want to talk, reach me on twitter [@ARKNDJL](https://x.com/ARKNDJL), on [LinkedIn](https://www.linkedin.com/in/noahjdengler/), or at [ARKNDJL@gmail.com](mailto:ARKNDJL@gmail.com).

## related writing

- [MLB PROSPX Preview / Closed Alpha](/posts/mlb-prospx-preview/) — methodology and a section-by-section tour
- [Potential 2026 MLB Prospect Breakouts: Introduction](/posts/mlb-prospect-breakouts-2026/) — quantitative, qualitative, and mixed-methods indicators of breakouts
- [Evaluating Every U19 Prospect In MiLB (May 2026)](/posts/u19-milb-evaluations-may26/)
- [2026 Prospect Grades: Chicago White Sox](/posts/prospect-grades-chicago-white-sox/)
- [State Of The Mets, Pre Trade Deadline 2026](/posts/state-of-the-mets-pre-deadline/) — PROSPX breakout flags in the wild
- more: [#prospx](/tags/prospx/) · [#prospect](/tags/prospect/) · [#mlb](/tags/mlb/)
