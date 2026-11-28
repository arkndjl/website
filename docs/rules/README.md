# Standing rules

Noah's standing rules for arkndjl.net, written down in the repo so they survive any loss of session memory.
CLAUDE.md at the repo root carries the short form and the per-feature rules; these files carry the detail.

| File | Covers |
| --- | --- |
| [design.md](design.md) | GFX, palette, font, pixel art, logos, mobile |
| [copy-voice.md](copy-voice.md) | Noah's voice, no LLM phrasing, no blurbs, ARKLOG no-AI rule, PROCESS articles, articleGFX |
| [models-tests.md](models-tests.md) | held-out backtests, lockbox, cross-sport rule, context metric rule, ship gate |
| [boards.md](boards.md) | column order, FV display, recruits, next up, standouts, tabs |
| [metrics.md](metrics.md) | metric definitions (FV, XPM family, VORX, WAR, NIL, DECT, Ret%, stars) |
| [sections.md](sections.md) | 1NT, LAURSEN_111, ST. CLAIRE, ARKLIBRARY, Predictions, hidden pages |
| [workflow.md](workflow.md) | posting schedule, merge and check_live, deploy gotchas, effort, threads |

## Keeping these current

- When a standing rule changes, update both this folder (or CLAUDE.md) and project memory in the same thread.
  A rule that lives in only one place is lost the next time the other is rebuilt.
- A weekly scheduled sync compares project memory against these files and opens a pull request with any new
  public rule; each monthly PROCESS #N batch refreshes them too.
- The repo is public. Keep out secrets, private client or business work, personal contact details, betting
  stakes or bankroll, and anything Noah has not made public. Those stay in project memory only.
- Write the rule and the reason in one or two lines. Code paths are fine; chat quotes, PR-by-PR history and
  research numbers belong in git and on Process, not here.
