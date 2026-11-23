# Football (NFL + CFB) port pass, Nov 23 2026
Result: 1 SHIPPED: CFB pSV/60 (QB predictive SV rate: 3 seasons weighted 1/.7/.5, shrunk to QB mean K 650 plays), next-season wMSE .0258 -> .0159, t -11.7, 10/10 seasons. Display column on CFB QB SV tab (scripts/cfb_season_value.py add_psv).
Fails: NFL early margin stretch (wants shrink s .90, held t -.75), NFL early totals shrink (held -1.78, Holm .26), NFL fumble-neutral EPA margin (held -.75) / totals (-1.07),
NFL rookie aXP/60 (t -.64), NFL SV -> pXP/60 prior (t -.42).
Tested before: spots, game control, market totals/mdis, tempo, coach change, returners, lineup ratings, season-out charge, rest, QB out, roster prior, CPOE, RAPM, pXP/60/SV -> game model, FV -> game/rookie.
Needs data: CFB attendance, CFB lost-season returners, NFL FPI stack, CFB school development -> recruits. Leads: NFL team ratings -> 1Y/3Y, questionable model -> percentile exposure, pSV -> CFB game QB term.
