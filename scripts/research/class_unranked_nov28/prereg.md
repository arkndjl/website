# Unranked commits in the class score (Nov 28 2026), written before any numbers

Noah: count commits nobody ranks in the class rankings, 1 star at the lowest, or a 0.5-star tier if it does better.

Today a CFB class counts only the commits ESPN grades (the board's recruit list); CBB only the recruits a service ranks.
On3's team commit lists (scripts/on3_commits.mjs, the HS ARK stars pack) name the rest.

CFB test, classes 2011-20 (drafts three to six years on, through 2026), one row a program and class, FBS and FCS:
- outcome: the class's NFL draft picks (count), from the HS ARK stars labels (scripts/arkstars_hist.py label)
- score = sum over commits of (index score - 20), the HS ARK stars index (the class score's points on the index scale)
- none: ESPN-listed commits only (today). graded: plus every other commit at his own index score (1 star at the
  lowest). half: as graded, but commits no service rates get their own value, fit on the training classes (the 0.5-star
  tier), the rest as graded.
- y = a + b x score by level (P4, G5, FCS), classes held out one at a time; squared error against none, t clustered by
  program; forward: fit 2011-17, score 2018-20.
- Ship the form with the larger held-out gain if its t >= 2 and the forward gain is above zero; else none stays and
  Noah's call decides (he asked for it either way).

CBB: On3's basketball team lists start with the 2024 class in the pack (no class with an outcome yet), so no test is
possible; unranked commits go in at the 1-star floor on Noah's call, scored at the rank curve's tail.
