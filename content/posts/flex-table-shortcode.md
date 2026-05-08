+++
title = "flexTable Shortcode"
date = "2026-05-08T19:14:44Z"
draft = false
+++

## Overview
The `flexTable` shortcode renders standard markdown tables with richer layout controls and responsive behavior. Paste a regular markdown table and optionally add configuration for columns, rows, and individual cells.

## Basic Usage
```
{{< flexTable >}}
| Name | Score | Notes |
|------|------:|-------|
| Alice | 95 | Excellent |
| Bob | 88 | Good |
{{< /flexTable >}}
```

## Configuration Block (YAML/TOML)
Add a frontmatter-style block at the top of the shortcode body to customize rendering:
```
{{< flexTable >}}
---
table:
  caption: "Results"
  zebra: true
  stickyHeader: true
  fontSize: "0.9rem"
  padding: "0.4rem 0.6rem"
  overflow: "auto"
columns:
  - width: "12rem"
    align: "left"
    whiteSpace: "nowrap"
  - align: "right"
rows:
  - emphasis: true
cells:
  - - class: "is-highlighted"
      style: "color: var(--accent)"
    - colspan: 2
---
| Name | Score | Notes |
|------|------:|-------|
| Alice | 95 | Excellent |
| Bob | 88 | Good |
{{< /flexTable >}}
```

## JSON Config Param
You can pass JSON directly via the `config` parameter:
```
{{< flexTable config=`{"table":{"zebra":true,"stickyHeader":true},"columns":[{"width":"10rem","align":"left"}]}` >}}
| Name | Score |
|------|------:|
| Alice | 95 |
| Bob | 88 |
{{< /flexTable >}}
```

## Configuration Reference
### `table`
- `class`, `style`: custom class or inline style for the table.
- `wrapperClass`, `wrapperStyle`: custom class/style for the outer wrapper.
- `responsive` (bool): enable horizontal scrolling wrapper (default `true`).
- `overflow`: overflow-x value when responsive (`auto`, `scroll`, `hidden`).
- `zebra` (bool): zebra striping (default `false`).
- `stickyHeader` (bool): sticky header row (default `false`).
- `caption`: table caption text.
- `fontSize`, `padding`, `whiteSpace`, `layout`: defaults applied to the table.

### `columns` (0-based)
Each entry can include:
- `width`, `align`, `fontSize`, `whiteSpace`
- `class`, `style`
- `headerClass`, `headerStyle`
- `cellClass`, `cellStyle`

### `rows` (0-based, body rows only)
Each entry can include:
- `height`, `background`, `fontSize`, `whiteSpace`, `padding`
- `class`, `style`, `emphasis`, `hidden`

### `cells` (0-based, body rows only)
Nested array of row → column configs:
- `colspan`, `rowspan`
- `class`, `style`, `background`
- `align`, `fontSize`, `whiteSpace`, `padding`
- `truncate` (bool, forces nowrap + ellipsis)

### `headerCells` (0-based)
Per-header-cell overrides:
- `class`, `style`, `align`, `fontSize`, `whiteSpace`, `padding`
- `colspan`, `rowspan`, `background`

### Precedence
When multiple levels specify the same property, overrides apply in this order: cell → row → column → table defaults. Alignment uses cell → column → markdown alignment row.

## Advanced Example
```
{{< flexTable >}}
---
table:
  zebra: true
  stickyHeader: true
columns:
  - width: "8rem"
    align: "left"
  - width: "5rem"
    align: "right"
rows:
  - emphasis: true
cells:
  - - truncate: true
      whiteSpace: "nowrap"
    - class: "score-strong"
---
| Name | Score |
|------|------:|
| Alexandria With A Long Name | 95 |
| Bob | 88 |
{{< /flexTable >}}
```

## Limitations / Tradeoffs
- Escaped pipes (`\|`) are supported, but complex nested markdown (like code blocks with pipes) is not fully parsed.
- Row/colspan values do not automatically adjust other rows; ensure your input aligns with the final layout.
- Multi-row headers are not supported yet.

## Migration Considerations
- Existing markdown tables remain unchanged outside the shortcode.
- Use `flexTable` only where you need advanced control (sticky headers, per-cell overrides, widths, etc.).

## Potential Future Enhancements
- Multi-row header support.
- Richer pipe-escaping and inline parsing.
- Optional row grouping or footer sections.
