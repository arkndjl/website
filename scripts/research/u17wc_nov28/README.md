# Soccer prospect FV: U17 World Cup event stats (Nov 28 2026), result: not testable yet, forward test registered

Source: u17-world-cup-stats.vercel.app (Noah, Nov 28). One static file, data.js, rebuilt by the author's own build.py and
credited to @bola_ao_ar. The player ids, slugs and stat names are Flashscore's. No license is stated, robots.txt is
absent, and the page is a plain static file, so one read is no load on anyone, but the numbers are a third party's copy of
Flashscore data and nothing on the site may be republished from it. The repo keeps no copy.

What it holds (read Nov 28 2026, 00:26 UTC build): the 2026 tournament only, group stage only (72 matches, Nov 19-27,
48 nations), 911 players (725 born 2009, 160 born 2010), 404 with 180 minutes or more, 82 stat types per player (xG, xA,
xGOT, box touches, progressive passes and carries, duels, recoveries, keeper goals prevented), position templates, and
club for 430 of them.

Why no test now: a point in time, held out test needs past tournaments with outcomes, and this covers one tournament
whose players have none. The parts Transfermarkt also carries (U17 World Cup minutes, goals and assists) were tested on
2013-20 classes and failed forward or at the top of the board (yi_opp, yi_ga, nt_all; scripts/research/soccer_nt_nov23).
The new part, the event stats, exists for no earlier tournament in any source the site may read: FotMob's API is barred
by its robots.txt for new fetchers (Nov 19) and Flashscore's feed is not a public API. Reach is also small: 3 of the 911
are on the 2000-player board today (Iago Machado, Kaue Furquim, Lucas Emanuel), all FV 33 to 35.

Forward test (prereg.md): the file is saved after the final to project storage (not the repo); the 2026 cohort is scored
once their outcome window opens (data/retests.json `u17wc_event_stats`).

Cross-sport: hockey's analogue is the WJC and U18 tournament lines on NHL landing pages. The WJC spot ships in the
post-draft stages (Oct 24); WJC and U18 spots and points per game before the draft failed then. Hockey has no event
stats at U18 beyond goals, assists and shots, and nothing here passed, so no new hockey test is owed.
