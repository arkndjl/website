# Copy and voice rules

## Minimal text

- No intro, lede, kicker, subtitle, tagline or descriptive blurb on any page, tab, card or window. Titles, labels,
  column headers, data and numbers only. When unsure, cut.
- Table notes go in hover (`about` in `wintable-close.html`, `<th title>`), never a visible paragraph.
- Method prose lives only in Process. Model and backtest tabs show tables, formulas and numbers.
- Scouting-report tone where a line of text is needed.

## Noah's voice (everything published)

- ARKLOG rows, PR descriptions that become log rows, Process text, articles, GFX text and X posts are all in
  Noah's voice: plain full sentences, numbers as they came out, failures included.
- No LLM phrasing or formatting: no dashes as punctuation, bold lead-ins, "not just X but Y", rhetorical questions,
  fragment lists, one-line kickers or summary closers. No advertising or marketing.
- Articles and Process read academically. Start from Noah's own answers and keep them nearly verbatim; add only
  connectives. Keep his long compound sentences and Oxford commas ("A, B, and C").
- Never add facts, examples or references he did not give (a Works Cited of real studies is fine when he asks).
- Process style details: "t = 2.1", "from .643 to .732" (no arrows), "compared to" not "vs" in sentences, × for
  multiplication, R², "points", lowercase "failed". No dates, PR numbers or changelog framing in prose.
- References: `/posts/introducing-xpm/` and `/posts/introducing-cbb-xpm/`. Ask Noah for writing samples when
  unsure.
- Code comments carry no name, date or PR provenance; history belongs in git. First-party code files keep the
  one-line copyright header.

## ARKLOG

- Copy cleanups (taglines, blurbs, intros, rewrites into Noah's words) are never logged, and no row mentions AI,
  LLMs, Claude or agents (stats models are fine). PR titles for such cleanups say what changed without those words.
  `NOAI` / `AI_LINE` in `scripts/arklog.py`.
- A model or metric test PR ends with `ARKLOG: shipped|part shipped|failed · <metric> a to b · t = x`.
- Never hand-write a row; corrections go in `research/arklog_fix.json`.

## PROCESS monthly articles

- One a month: "PROCESS #N: ... / <month> updates", PROCESS in capitals; front matter `series = "process"`,
  `month = "YYYY-MM"`, tags always include `process` and `arklog`.
- Covers every section that month (models and metrics, features, bug fixes, 1NT, ST. CLAIRE, videos and articles,
  social data, site data) with site screenshots and charts. Leaves out copy cleanups.
- The same batch refreshes the résumé on `/about/` (eephus.io and arkndjl.net panes, jobs, numbers from
  `data/arklog.json`) and these rule files.

## articleGFX (every article)

- Every article gets the articleGFX button: a 16:9 X card plus post text (`buildArticle` in `assets/js/gfx.js`).
- The card is a preview, not a summary: one short verbatim excerpt from each section (personal sections too) under
  its heading, plus the article's own figures. Excerpts may be part of a sentence but stay word for word.
- Front matter `[gfx]`: `quote = [...]`, `post = """..."""`. `scripts/article_gfx.py` (build gate) fails any line
  not in the article word for word. No invented lines, no taglines.
