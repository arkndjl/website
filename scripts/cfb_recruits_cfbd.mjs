// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// 247 composite high-school classes from CFBD (recruiting/players), in place of 247Sports' own pages, which sit behind
// a bot check and are never requested. One call a class. Two files:
//   CFBD_API_KEY=... node scripts/cfb_recruits_cfbd.mjs [first] [last]   signed classes for the CFB FV harnesses and the
//     recruit index -> scripts/data/cfb_recruits_cfbd.json.gz; a class already in the cfbhist cache
//     (scripts/.cache/cfb/hist/recruits-<y>-HighSchool.json) costs nothing and is never fetched again.
//     Rows: [name, rating, stars, ranking, committedTo, height in, weight lb], by class, in ranking order.
//   CFBD_API_KEY=... node scripts/cfb_recruits_cfbd.mjs --live [classes]  the classes being recruited (default: the
//     three after the board's season) -> scripts/data/cfb_recruits_cfbd_live.json, read by the recruit tabs
//     (scripts/cfb_recruit.mjs). A class is fetched again once its last pull is LIVE_DAYS old (default 6.5: one pull a
//     week on a daily job; a class CFBD had no rows for waits 28 days). Rows as above plus [home state, position].
// The quota guard: CFBD counts the month's calls for the whole key (x-calllimit-remaining on every answer). No call is
// made unless that count, less the call, stays at or above MIN_LEFT (default 500, the board's reserve). The count comes
// from the board run earlier in the same job (scripts/.cache/cfb/cfbd_left.json, written by cfb_teams.mjs cfbd()) when
// it is under two hours old, so a pull under the reserve costs nothing; with no such count the first call's own answer
// supplies it and the rest stop there.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DIR = path.join(ROOT, 'scripts', '.cache', 'cfb', 'hist'), OUT = path.join(ROOT, 'scripts', 'data', 'cfb_recruits_cfbd.json.gz');
const LIVE = path.join(ROOT, 'scripts', 'data', 'cfb_recruits_cfbd_live.json'), LEFT = path.join(ROOT, 'scripts', '.cache', 'cfb', 'cfbd_left.json');
const MIN_LEFT = +(process.env.MIN_LEFT || 500), LIVE_DAYS = +(process.env.LIVE_DAYS || 6.5), EMPTY_DAYS = 28;

// ---- the guard (pure, so --test can run it) -----------------------------------------------------------------
// may one more call be made with `left` calls remaining? unknown (null) allows one call, whose answer gives the count
export const mayCall = (left, minLeft = MIN_LEFT) => left == null || left - 1 >= minLeft;
// the classes due for a pull: never pulled, or last pulled `days` ago (EMPTY_DAYS when CFBD had no rows for it)
export function due(classes, at, n, now, days = LIVE_DAYS) {
  return classes.filter(y => { const t = at?.[y] ? Date.parse(at[y]) : null; return t == null || now - t >= (n?.[y] ? days : EMPTY_DAYS) * 864e5; });
}
export const liveRow = x => [x.name, x.rating, x.stars ?? 0, x.ranking ?? null, x.committedTo ?? '', x.height ?? null, x.weight ?? null, x.stateProvince ?? null, x.position ?? null];
const sortRows = v => v.filter(x => x.name && x.rating).sort((p, q) => (p.ranking ?? 1e9) - (q.ranking ?? 1e9));

let left = null, calls = 0;
async function pull(y) {
  const r = await fetch(`https://api.collegefootballdata.com/recruiting/players?year=${y}&classification=HighSchool`, { headers: { Authorization: `Bearer ${process.env.CFBD_API_KEY}`, accept: 'application/json', 'user-agent': 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)' } });
  calls++; const h = r.headers.get('x-calllimit-remaining'); if (h != null) left = +h; else if (left != null) left--;
  if (!r.ok) { console.log(`${y}: CFBD ${r.status}`); return null; }
  return r.json();
}

async function hist(A = 2009, B = 2025) {
  fs.mkdirSync(DIR, { recursive: true });
  const out = fs.existsSync(OUT) ? JSON.parse(zlib.gunzipSync(fs.readFileSync(OUT))) : {};
  for (let y = A; y <= B; y++) {
    const f = path.join(DIR, `recruits-${y}-HighSchool.json`);
    let v = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : null;
    if (!v) {
      if (!mayCall(left)) { console.log(`skip ${y}: ${left} calls left`); continue; }
      v = await pull(y); if (!v) continue;
      fs.writeFileSync(f, JSON.stringify(v));
    }
    out[y] = sortRows(v).map(x => liveRow(x).slice(0, 7));
    console.log(y, out[y].length, `(${left ?? '?'} left)`);
  }
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, zlib.gzipSync(JSON.stringify(out)));
  console.log('wrote', OUT, 'classes', Object.keys(out).length, 'CFBD calls', calls);
}

async function live(classes) {
  if (!classes.length) {
    const next = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_recruits.json'), 'utf8')).next;
    classes = [next, next + 1, next + 2];
  }
  const cur = fs.existsSync(LIVE) ? JSON.parse(fs.readFileSync(LIVE, 'utf8')) : { at: {}, classes: {} };
  const n = Object.fromEntries(Object.entries(cur.classes).map(([y, v]) => [y, v.length]));
  const todo = due(classes, cur.at, n, Date.now());
  if (!todo.length) { console.log('CFBD composite: every class pulled inside', LIVE_DAYS, 'days, no call'); return; }
  if (!process.env.CFBD_API_KEY) { console.log('CFBD composite: no CFBD_API_KEY, no call'); return; }
  try { const m = JSON.parse(fs.readFileSync(LEFT, 'utf8')); if (Date.now() - m.at < 2 * 36e5) left = m.left; } catch {}
  let wrote = 0;
  for (const y of todo) {
    if (!mayCall(left)) { console.log(`CFBD composite: skip ${y}, ${left} calls left (reserve ${MIN_LEFT})`); continue; }
    const v = await pull(y); if (!v) continue;
    const rows = sortRows(v).map(liveRow);
    // a class CFBD answers empty for keeps the rows it had (none, the first time)
    if (rows.length || !cur.classes[y]) cur.classes[y] = rows;
    cur.at[y] = new Date().toISOString(); wrote++;
    console.log(`CFBD composite ${y}: ${rows.length} rows (${left ?? '?'} left)`);
  }
  // classes that have signed leave the file
  for (const y of Object.keys(cur.classes)) if (!classes.includes(+y)) { delete cur.classes[y]; delete cur.at[y]; }
  if (wrote) { fs.writeFileSync(LIVE, JSON.stringify(cur) + '\n'); try { fs.writeFileSync(LEFT, JSON.stringify({ at: Date.now(), left })); } catch {} }
  console.log(`CFBD composite: ${calls} calls this run, ${left ?? '?'} left this month`);
}

function test() {
  const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.error('FAIL', m, a, b); process.exitCode = 1; } };
  eq(mayCall(null, 500), true, 'unknown count allows the probe call');
  eq(mayCall(501, 500), true, '501 left: one call leaves 500');
  eq(mayCall(500, 500), false, '500 left: a call would cut into the reserve');
  eq(mayCall(268, 500), false, 'under the reserve');
  const now = Date.parse('2026-12-02T12:00:00Z'), d = 864e5;
  eq(due([2027, 2028, 2029], {}, {}, now), [2027, 2028, 2029], 'first run: every class');
  eq(due([2027, 2028], { 2027: new Date(now - 3 * d).toISOString(), 2028: new Date(now - 7 * d).toISOString() }, { 2027: 9, 2028: 9 }, now), [2028], 'weekly');
  eq(due([2029], { 2029: new Date(now - 10 * d).toISOString() }, { 2029: 0 }, now), [], 'an empty class waits 28 days');
  eq(due([2029], { 2029: new Date(now - 29 * d).toISOString() }, { 2029: 0 }, now), [2029], 'then is asked again');
  eq(liveRow({ name: 'A B', rating: .9, ranking: 3, committedTo: 'X', height: 74, weight: 200, stateProvince: 'TX', position: 'QB' }), ['A B', .9, 0, 3, 'X', 74, 200, 'TX', 'QB'], 'row');
  // a month of weekly pulls: three classes, five Wednesdays
  let at = {}, c = 0;
  for (let day = 0; day < 31; day++) { const t = Date.parse('2026-12-01T18:00:00Z') + day * d; for (const y of due([2027, 2028, 2029], at, { 2027: 1, 2028: 1, 2029: 1 }, t)) { at[y] = new Date(t).toISOString(); c++; } }
  eq(c, 15, 'at most 15 calls in a 31-day month');
  if (!process.exitCode) console.log('cfb_recruits_cfbd: ok');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const a = process.argv.slice(2);
  if (a[0] === '--test') test();
  else if (a[0] === '--live') await live(a.slice(1).map(Number).filter(Boolean));
  else await hist(...a.map(Number));
}
