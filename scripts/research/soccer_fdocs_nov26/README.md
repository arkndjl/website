# football-docs review, Nov 26 2026

football-docs (withqwerty/football-docs, MIT, npm `football-docs` 0.17.10) is an MCP index of provider docs, metric
cards (xG, xA, PPDA, xT, VAEP, field tilt, progressive passes/carries) and a paper search. It holds no match data.
Its free-sources notes match what we already found (FBref advanced data gone Jan 2026, ClubElo behind auth and a
Cloudflare check, dcaribou Transfermarkt dump frozen since Jul 11 2026). Checked: none of our scripts reads the dump's
`current_club_id`, which the docs flag as not the club at the valuation date (soccer_mv.link uses appearances).

| test | result |
|---|---|
| Reep register (reep.football, CC0, release 2026-11-23.1) as Understat -> Transfermarkt ids | 5,137 pairs; 4,469 shared with our name link, 77 disagree, ours right on all 77 (Reep joins namesakes). Taken only when the Transfermarkt player has league minutes for the matched club that season: +20 players, all checked by hand right (Zambo Anguissa, Kelvin Amian, Amath Ndiaye, Savinho, Tanguy Nianzou). SHIPPED in soccer_mv.link + live squad match |
| Deep completions as a side rating (deep.py, prereg.md sha 27109907e95b) | tune 2015-22, every setting worse (+.02 to +.46 x1000 log loss; for .05 of xG weight +.21). FAIL, held untouched |
| PPDA | not tested (no goal scale; style term failed before) |
| xT, VAEP, field tilt, progressive actions | need event data (passes); none free for our leagues. Not testable |

Run deep.py: needs /mnt/project-files/soccer/{understat_cache,tminj_cache}.tgz in scripts/.cache/soccer.
