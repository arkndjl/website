# Recruit age for the class, Nov 26 2026: pre-registration

Written before any score. Question (Noah): does a recruit's age relative to his class (young or old for it) add to
the recruit model (projected FV, ARK stars) beyond what is in it?

Age for the class `agec` = age in years on Sep 1 of the class year (the fall he enrolls), from a day-precise birth
date. A year-only date (Barttorvik's Oct 15 placeholder) counts as Jul 1 of that year. Unknown = the training mean.

## CBB (scripts/cbb_recruit_fit.py; shipped: P(NBA) on log rank + `old`, value on log rank)
Birth dates: the recruit's D-I line in the kit (Barttorvik), so known only for recruits who played D-I. Classes
2009-16 held out one at a time, the fit script's own gate: per-class paired t >= 2 and 6 of 8 classes; a pass must
also not be worse on the 2017-18 forward classes. Holm inside each family.
- A1 swap `old` for `agec` in P(NBA) (log loss vs shipped).
- A2 add `agec` on top of `old`.
- A3 add `young` (17.9 or younger on Sep 1, about the youngest fifth) on top of `old`.
- A4 two hinges around 18.4 (years older, years younger) in place of `old`.
- B1 add `agec` to the value part (log(FV-20) given NBA, squared error). B2 add `old` there.
- Known-only check for anything that passes: the same test on rows with a birth date (the missing rows are mostly
  recruits who never played D-I, so an imputed mean can leak).
- C college path years 1-3 (minutes share, BPM given he plays; NIL-era seasons): `agec` in place of / beside `old`,
  the path's own gate.

## CFB (scripts/cfb_recruit_retarget.py index, classes 2011-19, NFL outcome)
Birth dates exist only for recruits who reached the NFL (nflverse players) or whom On3 lists (mostly pros): known-ness
is the outcome, so P(drafted) cannot be tested. Registered: (1) coverage of On3 birth dates on live classes; (2) given
an NFL entry, `agec` on the NFL target beside the index score, classes held out, t >= 2 and 7 of 9. A pass on (2)
ships only if live coverage in the top 300 is 50%+; otherwise it is a lead.

## Other sports
Hockey late birthday (draft model, Oct 24: t 1.35) and soccer birth month (failed) are the same test on unchanged
data: cited, not rerun. Tennis and CS2 have no class; age enters their FV as a continuous term already.
