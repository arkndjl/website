# Coach loyalty in Transfer%, landing and recruit leans (Nov 27 2026)

Pre-registration: prereg.md. Scripts: cbb.py, cfb.py, recruits.py. Staff history: scripts/cfb_staff.py
(scripts/data/cfb_staff_hist.json, FBS + FCS 2021-26) and scripts/data/cbb_coaches.json. t > 0 = the term helps held out.

| model | term | main fold | second fold | result |
|---|---|---|---|---|
| CBB Transfer% | head coach tenure at the school | t 2.89 | t .06 | **shipped** (log loss .8862 -> .8831, AUC .725 -> .727) |
| CBB Transfer% | came with his coach (n 124: 16.9% moved vs 20.8%) | -.91 | .83 | fail |
| CBB Transfer% | seasons under the coach | -5.66 | -.02 | fail |
| CBB Transfer% | inherited by the coach | -2.51 | -.81 | fail |
| CBB Transfer% | coach leaves x tie | -1.57 | -1.50 | fail |
| CBB landing | follow x tie | -1.77 | -.94 | fail (followers: 27% with a tie, 35% without) |
| CBB landing | his first college coach's new school | 1.52 | 2.12 | fail on the main fold (lead; 23 of 618 with the option took it) |
| CFB Transfer% | came with his head coach (n 194: 14.4% vs 14.9%) | .98 | 1.51 | fail |
| CFB Transfer% | seasons under the coach | -3.66 | -3.18 | fail |
| CFB Transfer% | inherited | -.31 | -.30 | fail |
| CFB Transfer% | head coach tenure | -2.25 | -.62 | fail |
| CFB Transfer% | coach leaves x tie | 1.37 | -.70 | fail |
| CFB Transfer% | new coordinator on his side | -.00 | .82 | fail |
| CFB follow share | by tie | 36% first season under him, 31% 2+ seasons, 2 of 6 repeat followers | | no lift |
| CFB lean | coach gone after the senior fall (`late`) | t 6.80, 4 of 5 classes | | **shipped** (LL -1.9272 -> -1.9237; with tenure -1.9226) |
| CFB lean | head coach tenure | 3.85, 5 of 5 | on top of `late` 2.25, 3 of 5 | held |
| CFB lean | first-year coach | 1.52 | | fail |
| CFB lean | coach came from a school on his list | 1.07 | | fail |
| CBB lean | all four | -1.18 to .61 | | fail (444 recruits) |

Notes
- Coach ties count only seasons up to the one predicted. CFB roster history starts 2021, FCS staff history too.
- The CFB tests rebuilt scripts/.cache/transfer/rows.json with Wikipedia head coaches from scripts/cfb_staff.py (the batch
  API still answers 429; the raw page endpoint works, one page a request).
- Retest came-with-coach after the 2026-27 cycle: the direction is right in both sports and the sample doubles.
