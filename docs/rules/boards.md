# Board rules

## Columns

- Only columns every player on the board has. Ranks are within the open tab and filters.
- Lead with the key stat for the context, then what it takes to read it:
  `RK | Player | ± | KEY | Pos | Team | Class/Age | Ht/Wt | sample | key's companions | other metrics | market/draft`.
  Boards: FV + Δ is the key. Team tables: `RK | ± | Team | Conf | KEY | G | rest`.
  Mock drafts lead with PICK, transactions with DATE.
- No name suffixes that duplicate a column.
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
