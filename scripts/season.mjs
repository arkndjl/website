// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Season calendar for Node (same rules as scripts/season.py): a key's value on a day is the last entry in
// data/seasons/<sport>.json "keys" dated on or before it.   node scripts/season.mjs --test
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'data', 'seasons');
const cache = {};
const JS_WD = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };

export function calendar(sport) {
  if (!(sport in cache)) {
    try { cache[sport] = JSON.parse(fs.readFileSync(path.join(DIR, `${sport}.json`), 'utf8')); } catch { cache[sport] = null; }
  }
  return cache[sport];
}

export function nyDate(when = new Date()) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit',
    day: '2-digit' }).formatToParts(when).map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}

export function value(sport, key, day = nyDate(), dflt = null) {
  let v = dflt;
  for (const [a, x] of calendar(sport)?.keys?.[key] ?? []) { if (a <= day) v = x; else break; }
  return v;
}

// the post weekday in JS numbering (Sunday = 0) in force on an ISO day, or dflt when the calendar has none
export function postWd(sport, day, dflt = null) {
  const v = value(sport, 'post', day);
  return v in JS_WD ? JS_WD[v] : dflt;
}

// the last post day before `day` under the post day in force on each day; null for no post day
export function lastPost(sport, day, dflt = null) {
  const t = new Date(`${day}T12:00:00Z`);
  for (let back = 1; back < 15; back++) {
    const d = new Date(+t - back * 86400e3), iso = d.toISOString().slice(0, 10), wd = postWd(sport, iso, dflt);
    if (wd == null) return null;
    if (d.getUTCDay() === wd) return iso;
  }
  return new Date(+t - 7 * 86400e3).toISOString().slice(0, 10);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]) && process.argv.includes('--test')) {
  const eq = (a, b, m) => { if (a !== b) { console.error('FAIL', m, a, b); process.exit(1); } };
  eq(postWd('cfb', '2026-12-02'), 3, 'cfb wed');
  eq(postWd('cfb', '2026-12-07'), 1, 'cfb mon from Dec 7');
  eq(lastPost('cfb', '2026-12-07'), '2026-12-02', 'first Monday post counts from the last Wednesday');
  eq(lastPost('cfb', '2026-12-08'), '2026-12-07', 'then from Monday');
  eq(value('cfb', 'season', '2026-11-28'), 2026, 'cfb season');
  eq(value('cfb', 'draft', '2027-05-03'), 2028, 'draft year after the NFL draft');
  console.log('season.mjs ok');
}
