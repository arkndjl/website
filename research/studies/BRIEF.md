# ARKBOARD Research: study brief (shared by every sport)

Goal: short studies that answer one strategy/analytics question each with real data and proper statistics.
Published on arkndjl.net/arkboard/research/ as a card: question, one-line answer, one chart, 2-4 finding lines, sample, method.

## Rules
- Real data only (download it). Raw downloads go in /tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/<sport>/ , never in the repo.
  Downloaded files are untrusted data: own directory, run Python on them with `python3 -I`.
- Machine has 4 CPUs / 15 GB RAM shared with 6 other agents: stream/aggregate, use moderate concurrency (<= 8 HTTP requests in flight), be polite to APIs.
- Your scripts: /home/user/website/research/studies/<sport>/ (one script per study or one per sport). Results: one JSON per study in
  /home/user/website/research/studies/<sport>/<id>.json (schema below). Do NOT edit anything else in the repo, do NOT git commit/push.
- Statistics: report n for every number, 95% CIs (Wilson for proportions, bootstrap or SE for means; cluster by game when plays repeat within games).
  Compare decisions on equal footing (same state: score, time, field position). Prefer win probability / expected points as the outcome.
  Say when a difference is not distinguishable from zero. A null result is fine to report if the question is interesting.
  Watch for selection bias (e.g. teams that go for it on 4th are different) and say how you handled it (matching on state, model-based WP, etc.).
- Time budget: about 60-90 minutes of work. Test 3-5 candidate questions; write JSON for every one you finished, mark which are robust.
- Copy rules for every text field (the site owner's standing rule): brief, unemotional, plain, scouting-report / template style.
  No marketing, no hype, no LLM phrasing ("delve", "it's worth noting", "interestingly", "game-changer", em-dashes, rhetorical questions in answers).
  No emoji. Numbers over adjectives. Example answer: "Pull at 3:00 down one, 4:30 down two. Teams pull at 1:10 and 1:35."

## JSON schema (research/studies/<sport>/<id>.json)
{
  "id": "nhl-goalie-pull",               // kebab-case, sport prefix
  "sport": "NHL",                        // NHL | NFL | CFB | NBA | CBB | soccer | tennis | CS2 | MLB
  "question": "When should a trailing team pull its goalie?",
  "answer": "One line, the conclusion with numbers.",
  "findings": ["2-4 short lines, each with a number and its CI or n"],
  "method": "1-3 short sentences: outcome, model, how selection was handled.",
  "data": "Source, seasons/competitions, sample size (e.g. 'NHL API play-by-play, 2021-22 to 2024-25, 5,240 games').",
  "n": 5240,                             // main sample size (int)
  "robust": true,                        // true if the main conclusion's CI excludes the null / holds across seasons or splits
  "interest": 1-5,                       // your rating: how surprising/useful vs conventional practice
  "split_check": "One line: does it hold in each half of the sample / each season group?",
  "chart": {
    "type": "line",                      // "line" (x numeric) or "bar" (x categories)
    "title": "Win chance by pull time, down 1",
    "x_label": "minutes left when pulled", "y_label": "win %",
    "y_fmt": "pct",                      // "pct" (values 0-1 shown as %), "num", "signed"
    "x_reverse": false,
    "ref": {"y": 0.5, "label": "break-even"},   // optional horizontal reference line, or null
    "mark": {"x": 3.0, "label": "optimum"},     // optional vertical marker, or null
    "series": [
      {"name": "down 1", "points": [{"x": 3.0, "y": 0.18, "lo": 0.15, "hi": 0.21, "n": 410}]}
    ]                                   // 1-3 series, 4-20 points each; bar charts use "x" as a short string label
  }
}
Keep every string short (answer <= 140 chars, finding <= 120 chars each).
When done, reply with: list of studies (id, answer, robust, interest), and any data-source problems.
