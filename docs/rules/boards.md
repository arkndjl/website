# Board rules

## Columns

- Only columns every player on the board has. Ranks are within the open tab and filters.
- Lead with the key stat for the context, then what it takes to read it:
  `RK | Player | ± | KEY | Pos | Team | Class/Age | Ht/Wt | sample | key's companions | other metrics | market/draft`.
  Boards: FV + Δ is the key. Team tables: `RK | ± | Team | Conf | KEY | G | rest`.
  Mock drafts lead with PICK, transactions with DATE.
- No name suffixes that duplicate a column.
- No stat-toggle tables (Noah, Nov 28 2026): never buttons, chips or selects that swap which stats a table shows or
  ranks by (VORX / XPM / offense, this week / rest of season, per 17 / per 60, a percentile span). Every stat is a
  sortable column in one fixed order; a header click ranks the board by that column (RK, ± and the position rank
  follow, a second click flips it). Phones scroll sideways with the name column pinned. Filters are only for row
  subsets (position, team, age, minutes, qualified, season). A stat some rows lack shows only when a filter leaves
  rows that all have it (a position chip). New boards follow this. Kept as choices: league scoring (PPR / half /
  standard) and switches between different sets of rows (5-man units / pairs, returners / kickers, awards).
- Injured starters stay atop the depth chart with a fill-in tag.

## Recruits

- Recruits show only current FV (whole number) and Y1 FV (CBB: IF NBA). No year 2-3 path on recruit cards or tables.
- Class tables, both sports, in this order: Recruit, ARK, Pos, Team, xFV, Y1 FV, xNIL, On% (CFB) or D-I% (CBB).
- Class tabs show uncommitted recruits with FV and the ARK lean in every sport.
- Class score = plain sum (top-end vs depth reweighting failed held out). A school's top three commits are ordered
  by ARK stars then xFV, so a 5-star+ never drops out.
- Recruit boards: one team filter entry per team; Δ★ and Δ Rk (ARK vs industry) columns.

## Tab names and groups

- "Standouts" tabs for season standouts. "Next up" = young players only (underclassmen; pro age cutoffs from
  `data/next_up_young.json`), leading with the breakout edge (CFB/NHL BO%), plus position, class, age and FV.
- SV = season-only value; SVAR boards.
- Group order and subtab rules are in CLAUDE.md ("ARKBOARD tabs").

## Odds and picks

- Free price sources only. Predictions is the only place for picks; sport pages keep xWins, season odds and
  power rankings. Never betting lines in the news feed.
- Weekly board deltas use the 10 AM ET posting-day snapshot as the baseline.
- Class rankings list every board program in every class, schools with no commit too, and every commit On3's team
  lists name; commits the board does not grade count at their HS ARK stars (1 at the lowest) and xFV 20, adding no
  class points (their points failed held out, Nov 28). classGFX shows leads, visits and offers on every card.
