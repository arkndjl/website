# Basketball (NBA + CBB) port pass, Nov 23 2026
Result: 7 untried game cells + 3 model-to-model cells tested, 0 pass (Holm 1.0), nothing shipped. Detail: scripts/research/port_nov23/basketball/.
Fails: NBA early stretch / early totals shrink (tune picks no change), CBB same, NBA mdis (held -.08), NBA tdis (tune -2.72, held -1.00 p .16),
NBA ldft opp FT luck (held +1.03 margin, +1.81 totals). Model-to-model into NBA 3Y: team margin t -1.80 (lead), teammates XPM t -1.59 (lead), XPM+ position intercepts t -.27.
Built not shown: NBA XPM+ (Stat+ form by position, yoy r .804); display candidate for the board key-stats thread.
Tested before / exists: spots, game control, 3PT luck, market totals, tempo, coach change, returners, lineup ratings, recentre, rest, BPI, aXPM, raw/shrunk pairs, on/off, xAAV, xNIL.
Needs data: NBA aplmix, attendance, over-expected shots, CBB percentiles. n/a: NBA conference/lower tier/season-out/starter-out, SV (already season-only).
