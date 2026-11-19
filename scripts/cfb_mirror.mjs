// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// CFBD's /plays feed from the sportsdataverse release mirror (scripts/cfb_mirror.py writes one file a week into
// scripts/.cache/cfb/mirror/). mirrorPlays(season, type, week) returns the week's plays in CFBD's own field names, or
// null when the release does not have the week yet or covers too few of its games (the caller then falls back).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache', 'cfb', 'mirror');
let INDEX;
export function mirrorIndex() {
  if (INDEX === undefined) { try { INDEX = JSON.parse(fs.readFileSync(path.join(DIR, 'index.json'), 'utf8')); } catch { INDEX = null; } }
  return INDEX;
}
// games: the ids the caller expects in that week (finished FBS games); the week is taken only when the mirror holds
// at least `cover` of them, so a half-built Saturday file never replaces a full pull
export function mirrorPlays(season, type, week, games = null, cover = 0.9) {
  if (process.env.CFB_MIRROR === '0') return null;
  const w = mirrorIndex()?.[season]?.weeks?.[`${type}|${week}`];
  if (!w) return null;
  if (games?.length) { const have = new Set(w.games.map(String)); if (games.filter(g => have.has(String(g))).length < cover * games.length) return null; }
  try { return JSON.parse(fs.readFileSync(path.join(DIR, `plays${season}-${type}-${week}.json`), 'utf8')); } catch { return null; }
}
export const mirrorStamp = season => mirrorIndex()?.[season]?.modified || null;
