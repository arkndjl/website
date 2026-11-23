# Soccer awards, Nov 23 2026: pre-registration (written before any of these tests ran)

Engine and gate as scripts/awards_more.py: rank-ordered logit, L2 1, leave one season out, held-out log P(winner),
one-sided paired t vs the null, Holm at .05 over soccer's whole list (Ballon d'Or's p in data/awards_fit.json + every new
race below), gain > 0 and most seasons won. Players and values: the big-five season files
(static/data/soccer-war/<S>.json, Understat, 2014-15 on). A winner outside the big five (or outside the pool) leaves
that season without an outcome (reported).

## A. Races (one voter model each, fixed here; history from Wikipedia)

| race | season | pool | depth | cols | null |
|---|---|---|---|---|---|
| pl_pots Premier League Player of the Season | 2015-2026 | eng.1, top 60 by GAR | 1 | gar, ga, lgw, tppg, prev | gar |
| pfa PFA Players' Player of the Year | 2015-2025 | eng.1 | 1 | same | gar |
| laliga LaLiga best player | 2015-2026 (what the page lists) | esp.1 | 1 | same | gar |
| seriea Serie A Footballer of the Year / MVP | 2015-2026 | ita.1 | 1 | same | gar |
| vdv VDV Player of the Season (Bundesliga) | 2015-2026 | ger.1 | 1 | same | gar |
| ligue1 UNFP Player of the Year | 2015-2026 | fra.1 | 1 | same | gar |
| goldenboy Golden Boy (calendar year Y -> season ending Y) | 2015-2026 | big five, under 21 on Dec 31 of Y (age on the file < 21.5), top 60 by GAR | 1 | gar, ga, ucl, lgw, age, prev | gar |
| kopa Kopa Trophy (top three on the Ballon d'Or page) | 2018-2026 (no 2020) | same as Golden Boy | 3 | gar, ga, ucl, lgw, age | gar |
| yashin Yashin Trophy (top three) | 2019-2026 (no 2020) | big-five keepers, top 40 by GAR | 3 | gar, lgw, ucl, natw, prev | gar |

lgw = his club won its league; tppg = his club's points a match / 3 (club game archive); ucl = Champions League winner
1, beaten finalist .5; natw = his nation won a World Cup / Euro / Copa America that season; prev = earlier wins of the
same award (from 2008 where the page has them).

Golden Boot (each big-five league, goals): a stat title. No to-date archive of big-five scorers (Understat match pages
are not cached), so no as-of test: conviction only (P(lead) on goals at this season's own rate).

## B. Season-only soccer value (for conviction)

GAR's plus-minus term is a three-season ridge, so GAR cannot be conviction. SGAR = season-only GAR from the season
file's own fields, nothing from another season: per 90, relative to the league-season average and shrunk to the
position mean by minutes (300): non-penalty xG, xA, xGBuildup, on-pitch xG difference, on minus off xG difference
(team totals from the same file). Weights: ridge of each club-season's goal difference a match on its players'
minutes-weighted rates of the SAME season (LOSO by season, lambda from {0.1, 1, 5}); replacement by position as GAR's
(regulars of the bottom three sides, finished seasons). League-relative (no league strength term: that rating carries
other seasons). Reported: LOSO R2 of club GD a match, correlation with GAR. Keepers: the file has no shot-stopping
term, so keepers' SGAR is on-pitch terms only and there is no Yashin conviction. Used for conviction only (league
awards, Golden Boy / Kopa, Ballon d'Or); the voter models keep GAR.

## C. Driver add-ons (paired held-out t vs the race's own model, Holm over all driver tests here)

1. goldenboy + fv: soccer prospects FV before the season (point-in-time) — only if a historical point-in-time FV can
   be rebuilt from scripts/data/soccer_prospects_base.json.gz with the live weights without refitting on outcomes;
   else blocked (reported).
2. goldenboy + mv: log Transfermarkt value on the season file (mv) — flagged: the file's value date is the season's,
   not before the vote; run as a check only, never shipped.
3. each league race + age.
4. each league race + ucl (his club in the Champions League final).

## D. Awards -> FV (soccer prospects)

Golden Boy / Kopa P(win) as an input to the soccer prospects FV: test with the board's own harness
(scripts/soccer_fv_drivers.py, LOSO by season, t >= 2 and 6/8) only if its rows rebuild here (they need the
Transfermarkt dump in scripts/.cache, 45 minutes of pulls); else blocked (reported).

## Amendments (after the first run; reported as such)

- Pools: the top-60 / top-40 GAR cuts left three winners out (Kante 2016-17 PL and PFA, Donnarumma 2025 and Unai
  Simon 2026 Yashin), so pools became minutes floors (league awards 1,000+, Golden Boy / Kopa 600+, keepers 900+).
  Mbappe was missing as "Kylian Mbappe-Lottin" (Understat): name alias added (data/name_aliases.json).
- LaLiga best player: awarded 2015-16 and 2023-24 on only (5 seasons with a winner): not tested.
- B (SGAR) not built: scripts/soccer_sv.py (another thread, Nov 23) already writes a season-only SV / SVAR on every
  season-file row, keepers' saves included; conviction uses SVAR, so Yashin gets a conviction view.
