#!/usr/bin/env node
// 1NT's live win chance for the homepage ticker (Noah, Nov 1 2026: 1NT first).
//
//   node scripts/nt_live.mjs --due      # prints "due" when a 1NT match starts within 45 min or is under way
//   FACEIT_API_KEY=... node scripts/nt_live.mjs [--once]
//
// The FACEIT Data API has the match room's status, the vetoed map(s) and each finished map's winner, but no live
// round score (that only reaches FACEIT's own site), so the number moves on the veto and on each map result:
//   before the veto: the preview's match win chance (data/esea.json preview.p.win)
//   map picked:      that map's veto win chance (preview.maps[].p), and a bo3 plays out map by map (LiveWP.csSeries)
//   finished:        100 or 0.
// The page reads live/1nt.json from raw.githubusercontent.com (no site rebuild; GitHub caches it up to 5 minutes).
// Each change is committed with [skip ci], so Cloudflare does not rebuild. The loop polls every 60 s from 15 minutes
// before the start until the match is finished (at most 4 h). Started by .github/workflows/nt-live.yml, which the
// odds-snap workflow dispatches when --due says so.
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { createRequire } from 'node:module';

const ROOT = path.dirname(path.dirname(new URL(import.meta.url).pathname));
const W = createRequire(import.meta.url)(path.join(ROOT, 'static', 'js', 'livewp.js'));
const OUT = path.join(ROOT, 'live', '1nt.json');
const TEAM_ID = 'a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a';   // 1NT
const KEY = process.env.FACEIT_API_KEY;
const args = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function esea() { return JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'esea.json'), 'utf8')); }

// the match to follow: not finished, starting within `lead` ms or started under 4 h ago
function current(d, lead) {
  const now = Date.now();
  return (d.matches || []).filter(m => !m.result && m.at && !['CANCELLED', 'FINISHED'].includes(m.status)
    && m.at - lead <= now && now <= m.at + 4 * 3600e3).sort((a, b) => a.at - b.at)[0] || null;
}

const mapName = x => String(x?.game_map_id || x?.class_name || x?.name || x || '').toLowerCase().replace(/^de_/, '');

// win chance (0-100) for 1NT from the room's state and the preview
export function chance(st, pv) {
  if (st.winner) return st.winner === 'us' ? 100 : 0;
  const same = pv && pv.id === st.id;
  const pre = same ? pv.p?.win : null;
  const mp = m => {
    const r = same ? (pv.maps || []).find(x => x.map === m) : null;
    return r?.p != null ? r.p / 100 : null;
  };
  if (!st.picks.length) return pre;
  const bo = st.bo || 1, pAvg = pre != null ? (bo === 1 ? pre / 100 : mapAvg(pre / 100, bo)) : 0.5;
  const maps = st.picks.map(mp);
  return Math.round(100 * W.csSeries(bo, st.won, st.lost, maps, null, pAvg));
}
// the per-map chance that gives a series chance p in a best-of-bo
function mapAvg(p, bo) {
  let lo = 0.01, hi = 0.99;
  for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; if (W.csSeries(bo, 0, 0, [], null, m) < p) lo = m; else hi = m; }
  return (lo + hi) / 2;
}

async function room(id) {
  for (let a = 0; a < 4; a++) {
    const r = await fetch(`https://open.faceit.com/data/v4/matches/${id}`, { headers: { Authorization: `Bearer ${KEY}`, Accept: 'application/json' } }).catch(() => null);
    if (r && r.ok) return r.json();
    await sleep(3000 * (a + 1));
  }
  return null;
}

function state(m, j) {
  const us = j.teams?.faction1?.faction_id === TEAM_ID ? 'faction1' : 'faction2';
  const picks = (j.voting?.map?.pick || []).map(mapName).filter(Boolean);
  let won = 0, lost = 0;
  for (const r of j.detailed_results || []) { if (r.winner === us) won++; else if (r.winner) lost++; }
  const fin = j.status === 'FINISHED' && j.results?.winner;
  return {
    id: m.id, at: new Date(m.at).toISOString().replace('.000', ''), status: j.status || m.status, bo: j.best_of || m.best_of || 1,
    picks, won, lost, winner: fin ? (j.results.winner === us ? 'us' : 'them') : null,
  };
}

function write(st) {
  const old = fs.existsSync(OUT) ? fs.readFileSync(OUT, 'utf8') : '';
  const strip = s => { try { const o = JSON.parse(s); delete o.asof; return JSON.stringify(o); } catch { return ''; } };
  const out = { ...st, asof: new Date().toISOString().replace(/\.\d+Z$/, 'Z') };
  const txt = JSON.stringify(out, null, 1) + '\n';
  if (strip(old) === strip(txt)) return false;
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, txt);
  return true;
}

function push(msg) {
  if (!process.env.GITHUB_ACTIONS) return;
  const sh = c => execSync(c, { cwd: ROOT, stdio: 'inherit' });
  sh('git add live/1nt.json');
  try { sh(`git commit -q -m "${msg} [skip ci]"`); } catch { return; }
  for (let i = 0; i < 5; i++) {
    try { sh('git pull -q --rebase origin main'); sh('git push -q origin HEAD:main'); return; } catch { execSync(`sleep ${2 ** (i + 1)}`); }
  }
}

async function main() {
  if (args.includes('--due')) { console.log(current(esea(), 45 * 60e3) ? 'due' : 'none'); return; }
  if (!KEY) { console.log('FACEIT_API_KEY not set'); return; }
  const stop = Date.now() + 5.5 * 3600e3;
  let d = esea(), m = current(d, 5 * 3600e3);
  if (!m) { console.log('no 1NT match within 5 h'); return; }
  const wait = m.at - 15 * 60e3 - Date.now();
  if (wait > 0 && !args.includes('--once')) { console.log(`waiting ${Math.round(wait / 60e3)} min for ${m.opp?.name}`); await sleep(wait); }
  while (Date.now() < stop) {
    const j = await room(m.id);
    if (j) {
      const st = state(m, j);
      st.opp = m.opp?.name || null;
      st.p = chance(st, d.preview);
      if (write(st)) { console.log(new Date().toISOString(), st.status, st.picks.join(','), `${st.won}-${st.lost}`, st.p); push(`1NT live: ${st.status} ${st.p ?? ''}`); }
      if (st.winner || ['CANCELLED', 'FINISHED'].includes(j.status)) break;
    }
    if (args.includes('--once') || Date.now() > m.at + 4 * 3600e3) break;
    await sleep(60e3);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) main();
