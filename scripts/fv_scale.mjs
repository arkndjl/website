// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// The headline FV's stretched top (Noah, Oct 31 2026: 80 reachable, about one a board every five seasons): the mean
// below each board's knot K, linear above it to 80 at T. K and T per board in data/fv_scale.json (fit and documented
// in scripts/fv_scale.py, which this mirrors). fvx stays the exact mean on every row; only the whole-number fv moves.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
let S = null;
const scale = () => {
  if (!S) { try { S = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'fv_scale.json'), 'utf8')).boards; } catch { S = {}; } }
  return S;
};

// the headline on the stretched scale, with decimals
export function fvShow(board, x) {
  const s = scale()[board];
  if (x == null || !s || x <= s.K) return x;
  return Math.min(80, s.K + (x - s.K) * (80 - s.K) / (s.T - s.K));
}

// the whole-number headline for an exact mean x; fv (the board's own rounding) is kept below the knot
export function fvOf(board, x, fv) {
  if (x == null) return fv;
  const s = scale()[board];
  if (!s || x <= s.K) return fv ?? Math.round(x);
  return Math.round(fvShow(board, x));
}

// JSON.stringify replacer for files written from the raw board in memory: a player's fv (from his fvx when the row has
// one), fv0 and fvNow go out on the stretched scale; everything computed in memory (team builder, mocks, portal AV,
// team talent) stays on the mean. Only on objects with a name, so tier tables and counts are untouched. Each row also
// carries the exact mean it was stretched from (fvx / fv0x / fvNowx: the row's own when it has one, else the value it
// held in memory), so scripts/fv_scale.py --restate restates from the mean and never stretches a shown value twice.
const KEYS = ['fv', 'fv0', 'fvNow'];
export const fvReplacer = board => function (k, v) {
  if (!v || typeof v !== 'object' || Array.isArray(v) || (v.name == null && v.n == null)) return v;
  let o = null;
  for (const key of KEYS) {
    const val = v[key];
    if (typeof val !== 'number') continue;
    const xk = key + 'x', x = typeof v[xk] === 'number' ? v[xk] : val;
    o ??= { ...v };
    o[xk] = x;
    o[key] = Number.isInteger(val) ? fvOf(board, x, val) : Math.round(fvShow(board, x) * 10) / 10;
  }
  return o ?? v;
};
