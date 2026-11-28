+++
title = "PROCESS #1: Introducing ARKLOG / November updates"
date = "2026-11-28T09:00:00-05:00"
author = "arkndjl"
authorTwitter = "ARKNDJL" #do not include @
tags = ["process", "arklog"]
keywords = ["arklog", "process", "november 2026", "xpm", "dect", "nil", "ark stars", "1nt", "laursen_111", "st. claire", "site data"]
description = "November 2026 on arkndjl.net: ARKLOG, models and metrics that shipped and failed, new features, bug fixes, 1NT, LAURSEN_111, ST. CLAIRE, videos and articles, social data and site data."
series = "process"
month = "2026-11"
showFullContent = false
readingTime = false
hideComments = true
draft = true
Toc = true
+++

This is the first monthly Process update. Every month I will write one of these going through everything that changed on the site, including the models and metrics that shipped or failed, new features, bug fixes, 1NT, LAURSEN_111, ST. CLAIRE, the videos and articles I put out, and how the site and my accounts did. [Process #0](/posts/process-0-design-philosophy/) goes through why the site looks the way it does, and this one goes through what happened in November.

## ARKLOG and Process

ARKLOG is the dated record of every change on the site, and it now lives inside Process along with the traffic, build, and data tabs from the old site data page.

Every row in ARKLOG is one merged change, with its date, the section of the site it belongs to, and its sport. A model or metric test also shows whether it shipped, part shipped or failed, along with the held-out number that decided it (before and after) and its t. The failures are in there with everything else, because people should know what has been tested, tried, and proven to not work. It helps them with their own research, and it shows everything I've thought of trying even when it didn't work.

{{< image src="/img/process-1/arklog.png" alt="The ARKLOG log tab: filters by verdict, month, section, sport and area, a find box, and dated rows with shipped, part shipped and failed tags and their held-out numbers" position="center" >}}

ARKLOG is built from the pull requests behind every change, so nothing in it is typed in by hand. Reading a verdict out of a write-up by pattern got a lot of them wrong, so I read every test through #1304 against its write-up and kept the reviewed verdict, number, and t in a fix file. From now on every test ends its write-up with one line that says what happened, and that line is taken as written.

The calendar tab has every sport's league dates, every step the site takes when a season turns, and where each sport is right now. The scoreboard tab has the tallies and charts by week, sport, area, and section, and each row, the scoreboard, and each sport's sheet can be pulled as a GFX card. The updates tab lists these monthly posts next to each month's tallies.

{{< image src="/img/process-1/arklog-scoreboard.png" alt="The ARKLOG scoreboard: totals of changes, tests shipped, part shipped and failed, with charts by week, sport, area, and section" position="center" >}}

Through Nov 28 there were 648 merged changes and 210 tests in November, and of those tests 72 shipped, 98 part shipped, and 40 failed. There were also 34 research studies. In October there were 623 changes and 220 tests, with 99 shipped, 75 part shipped, and 46 failed.

{{< postchart "p1-weeks" >}}

{{< postchart "p1-sections" >}}

This month Process moved out of ARKBOARD to its own page at /process/, right under donate in the menu, and it was rebuilt into seven sections. Overview has the chain from data sources to mocks, each sport's most descriptive and most predictive metric with its held-out R², the tests by week, the gates, and the latest tests. Philosophy goes through how I think about metrics and design in eight tabs, ARKLOG is the log, Metrics has FV, the FV scales, player value, and player odds, and Models has team ratings, game models, drafts and mocks, and testing. Research and Data come after those.

{{< image src="/img/process-1/process-overview.png" alt="The Process overview tab: the chain of sections with counts, the describe and predict metric for each sport with held-out R², tests by week, the gates and the latest tests" position="center" >}}

Every term has a window with its formula, its held-out test, and charts drawn from the same data as its GFX card, and every term can be pulled as a 16:9 card for Twitter. Each sport also has a sheet with its lead metrics, every term by tab, its studies, and its test record. Everything on the Process page is read from the live fits and refreshes after every board run.

Every acronym and metric label on the site now has a hover that tells you what it stands for, gives one line on what it is, and links to its Process entry, which covers 447 terms.

## Models and Metrics

XPM got two articles this month. In the NBA, rXPM became the descriptive version (the number labeled XPM on the site) and pXPM became the predictive version. rXPM now carries a team adjustment, which took its fit to same-season team net rating from an R² of .640 to .647, and VORX moved onto the team-adjusted rXPM (R² .926 to .938, t = 2.33). pXPM was rebuilt as next season's XPM, shrunk toward a role mean by minutes, and aged, and its next-season RMSE is 1.187 against 1.238 for the old one-dial shrink (t = -7.28).

College basketball got its own XPM as well. Its rXPM takes Barttorvik's game BPM for a team's total and BPM for the split between teammates, and it tracked wins above bubble better than BPM in 19 of 19 seasons. pXPM in board form predicted next-season team strength better than BPM in all 14 seasons I tested, with an R² of .746 against .643, so it replaced BPM in Next, next up, Transfer%, landing, and the depth grades, and WAR became VORX on XPM.

Alongside the XPM work, I ran an audit of every sport to find its most descriptive metric (the one that best explains a season's results) and its most predictive metric (the one that best predicts the next season), held out, and every board now leads with the right one for its context. Descriptive tabs like season boards, standouts, and awards lead with the descriptive pick, and predictive tabs like projections, FV, next up, and mocks lead with the predictive pick. A second pass on Nov 27 checked every model's inputs the same way and moved the predictive tabs and models onto predictive inputs (RMSE 1.301 to 1.185, t = 13).

Award races got two views to match. Predictive awards model the voters and the market, and conviction awards show who leads on this season's value alone, using SV and SVAR, which are season-only value metrics that never borrow from another season.

On the recruiting side, the commitment model (ARK lean) improved in three steps: hometown distance (log loss 2.076 to 2.011, t = 21.7), ARK stars on the NFL index with outcome-fit tiers (2.011 to 1.962, t = 20.4), and On3 and Rivals visits and expert picks (1.962 to 1.896, t = 19.7).

The college basketball recruit board was built to match football, with Y1 FV. ARK stars went platinum, and 5-star+ now means a recruit with better than even odds of being a top-64 pick. Every college player now also has a high school ARK star grade, from classes back to 2008 graded with the same index as the live recruit tabs. The correction for recruits off ESPN's signee list passed forward on 2020-21 (t = 4.94), and reading a lone service's grade on the industry scale failed.

Class rankings got classGFX, a 16:9 card for every school's class, and then leads, visits, and four ARK star buckets. I also tested whether the top end of a class wins more than its depth, and point for point they are worth the same (CFB t = .70, CBB t = .51), so the class score stays a plain sum.

{{< image src="/img/process-1/cfb-class-rankings.png" alt="The CFB class rankings board with ARK stars, class score, top end, depth and ARK star buckets for each school" position="center" >}}

In the market tabs, NIL was rebuilt on the budgets schools actually report, so yNIL is now each school's reported budget shared by its whole roster. Football position pay and the basketball mid-major levels are set on the College Sports Commission's pay report, and the mid-major change took the error on the Commission's percentiles from an RMSE of .451 to .226. A ledger of confirmed deals moves a player's yNIL and xNIL half way to the reported number, lists the deal in the transactions tabs, and posts it to the news feed, and a headline scanner adds deals to it every three hours.

Agencies got their own tab in football and basketball, which ranks NIL agencies by their clients' zNIL, pulled toward the mean so that one client can't put an agency on top. Every row comes from a source. The sweep searched the top 240 football players, the top 130 basketball players, and 265 recruits, and 272 rows have a source.

{{< image src="/img/process-1/cfb-agencies.png" alt="The NIL agencies board ranked by zNIL*, with clients, college and recruit counts, zNIL, zNIL per player, zNIL as a share of pay and xNIL" position="center" >}}

DECT (Declare, Even, College, Transfer) is a decision metric in dollars on the CFB and CBB draft boards. It shows which choice is worth the most to a player, separate from Ret% and Transfer%, which show what he will actually do. Declaring is his rookie deal and later earnings over the spread of where he could be picked, College is what his own school would pay him next season plus the same draft value a year older, and Transfer is the same on his open market price. Each side is a certainty equivalent, because a player only gets one career and a sure dollar counts for more than the same dollar spread over a few possible careers, and Even means the top two are within one standard error. Against who actually went back, the certainty equivalent raised the AUC from .46 to .56 in football.

{{< image src="/img/process-1/cfb-draft-dect.png" alt="The CFB draft board scrolled to Draft%, Ret%, DECT, Xfer% and the NIL columns, with Declare, Transfer and Even verdicts" position="center" >}}

A bigger role elsewhere failed as a transfer term (t = -.6), and DECT failed as an input to Ret%, Transfer%, and landing. The CBB Transfer% lead (t = 1.47 against a bar of 2) will be retested after the 2026-27 cycle.

The team builder was rebuilt to read as next season's team. Each plan opens with strength (projected Elo in football and ARK rating in basketball, with rank and xW), value, and NIL budget, followed by the field and the depth, portal, leaving, class, keep, moves, and targets tabs. Targets are the uncommitted recruits a school is in on, with the chance that each one signs there.

{{< image src="/img/process-1/cfb-team-builder.png" alt="The CFB team builder for LSU: 2027 strength rank and xW from now to the plan, value, NIL budget and spend, and next season's starters and backups by position" position="center" >}}

Coach loyalty passed in two places. Coach tenure in CBB Transfer% and a late coach change in the CFB lean took log loss from .8862 to .8831 (t = 2.89). Players following their coach to a new school failed, and that will be retested after the 2026-27 cycle.

Across every sport, anything I try in one sport gets tried in every sport that has an analogue. The port pass on Nov 23 tried every single-sport idea everywhere and shipped four display metrics. Re-picking a rating's settings every season passed in CS2, NHL, and CBB and failed in tennis, soccer, NFL, and NBA. Every sport now has a cumulative and a rate value metric side by side, like VORX and XPM in the NBA or WAR and pXP/60 in the NFL. NHL WAR now splits traded players across their teams (R² .975 to .991, t = 5.34). In CS2, lower-tier matches in the player Elo (log loss .5522 to .5459, t = -4.2) and the world rank and forfeit wins in the ARK Ranking (.6248 to .6025, t = -5.6) both shipped, and the ARK rating now retunes every month.

40 tests failed in November, including the soccer national team play test for prospect FV, deep completions in the soccer game model, the CS2 market tests against bookmaker closes, a gradual fade of the CFB absence charge, the CFB QB-change era weighting, expert track-record weights in the recruit leans, draft pay in dollars in Ret%, and a postseason-only title layer in every sport. Every one of them is in ARKLOG with its number.

## The Site

Beyond the models, a lot of the site itself changed in November. Every sport page was regrouped into the same side strip (players, rosters, games, teams, market, recruits, draft, and model), with subtabs for views of one thing and a two-row menu on phones, and site search was added to the header bar of every page, covering players, teams, tabs, Process terms, and articles. There is now a news ticker on every page, a /news/ page, and a daily news GFX, along with award races (predictive and conviction) on every sport page, next up (the young players most likely to break out) on six sport pages, led by EDGE where it tests better, and standings with official standings, playoff pictures, polls, leaders, scores, and games to watch for every sport. Every sport also got projected brackets, with the CFP committee's memory in the CFB bracket, era-adjusted all-time players and teams, and transactions with player values on every move. The GFX cards were overhauled with percentile colors, pixel bars, and boxed column groups, and they got weekly moves, recruit photos, and a recruit card with predictions, moves, and visits. The site also got a tip page with Ko-fi.

There were bug sweeps on Nov 1, 2, 5, 9, 11, and 27. The Nov 27 audit alone covered data fixes (duplicates, lost names, and bogus FV moves), GFX cards, the CFB, CBB, NFL, NBA, and NHL pages, phone tables, filters, workflows, and the live site's shared code. Deploys now run after each data workflow, and a deploy check restarts the Cloudflare hook when a push stalls.

Every sport now moves from one season to the next on its own. Each sport has a calendar with its league dates and phases (preseason, regular season, postseason, and offseason), along with the season, draft year, recruit class, and weekly post day that every board reads. A workflow runs twice a day and does each step on its date: it archives the finished season, moves the hard-coded years, checks that everything still builds and passes its tests, and puts everything back if anything fails. Anything that needs a hand step, like a refit, a freeze or new source ids, opens an issue ahead of time instead.

Playoffs follow the real results now. The NFL fixes every playoff game that has been played and shows the score, the NHL plays each series on from its real game count, and the UEFA knockouts use the real ties and the legs already played. ESEA moves to the next season by itself, and the CS2 Majors are a list (Singapore, Buenos Aires, Shanghai).

The CFB post moves to Monday from Dec 7 through the bowls and goes back to Wednesday at the 2027 opener. Recruit classes roll to 2028-2030, on Jan 1 for CFB and on Apr 7 for CBB.

{{< image src="/img/process-1/calendar.png" alt="ARKLOG calendar tab: every sport's league dates, the site's season steps and each sport's current phase" position="center" >}}

## Counter-Strike

1NT went 8-6 in ESEA Main for Season 59, finished 30th of 83, and made the playoffs, where we beat Tractors 2-1 in our first playoff series. Our next match is against Kings Gambit on Sunday, Nov 29 at 9 PM ET, and mf_ is playing.

{{< image src="/img/process-1/1nt.png" alt="The 1NT page" position="center" >}}

On the site, 1NT got RWA (round win added) as the headline player stat, a season summary window and GFX, a milestones tab with every finish, playoff series, and division rank, the ESEA playoff bracket in double elimination, Bo3 series pricing and box scores, and a Road to Pro tab with live playoff odds. On Nov 23 1NT reached its best world rank, 272nd of 315 ranked teams.

LAURSEN_111 got its own hub this month, separate from 1NT. It has PUG box scores from FACEIT and Premier with RWA, a form window, Elo and rating trends, a daily report, the laursen111.log journal, and a social data tab with goals, projections, and a milestone log. LAURSEN_111 also got a provisional FV of 20 on the CS2 prospects board.

{{< image src="/img/process-1/laursen.png" alt="The LAURSEN_111 page" position="center" >}}

## ST. CLAIRE, Videos, and Articles

The ARKNDJL section was renamed ST. CLAIRE, with a new monogram, a shards logo, a stone texture, and a lilac, pearl, grey, and black palette. Music now shows each song's public play count, and WAVE launched with drops, band merch, NYC shows, a screen tab, and a fashion catalog with collection showcases, sales, and 36 suggested brands.

{{< image src="/img/process-1/wave.png" alt="The ST. CLAIRE WAVE page" position="center" >}}

The home page has a video player now, video.exe, with the newest LAURSEN_111 and ARKNDJL long-form videos and an upcoming tab for ARKMIXES.

{{< image src="/img/process-1/home-video.png" alt="The video.exe player on the home page" position="center" >}}

The biggest video of the month was DAVID GABRIEL GEORGES 5*+ RB HS Highlights (ARKMIX) on Nov 23, with 13,829 views and 125 likes so far. I also put out the 1NT full VODs from ESEA Main Season 59 against THE GUILD (Nov 18) and Kaos (Nov 20), and nine LAURSEN_111 shorts since Nov 16, the most watched of which was "insane spraydown ez reads" with 2,406 views.

I also published [How the ARKBOARD Works](/posts/arkboard-every-feature/) on Nov 2, [27 Strategy Questions, Answered](/posts/arkboard-research-27-questions/) on Nov 2, [Introducing XPM: Predictiveness, Stability, & Formulation Process](/posts/introducing-xpm/) on Nov 24, [Introducing XPM for College Basketball](/posts/introducing-cbb-xpm/) on Nov 26, and [PROCESS #0: My Design Philosophy, Anti-Minimalism, and the Beauty of Friction](/posts/process-0-design-philosophy/) on Nov 27.

## Social and Site Data

Tracking started on Nov 17 for LAURSEN_111 and Nov 18 for ARKNDJL. Since then @ARKNDJL on X went from 2,420 followers to 2,459, and the ARKNDJL YouTube channel went from 17 subscribers to 24, mostly from the David Gabriel Georges video.

LAURSEN_111 went from 274 to 278 followers on Twitch, 100 to 111 on TikTok, and 38 to 46 on X, and stayed at 42 on YouTube. The best stream peaked at 16 viewers.

{{< postchart "p1-laursen" >}}

The site averaged 719 page views a day in November through the 27th, against 368 in October, so traffic nearly doubled. The best day was Nov 4, with 1,525 page views.

{{< postchart "p1-traffic" >}}
