// College football conference availability reports: the SEC, ACC, MAC and American post every listed player's
// designation for each conference game (SEC/ACC: an initial report three days out, daily updates, a game-day report
// 90 minutes before kickoff; MAC/American: game day only). All four publish through the same public report page
// (HD Intelligence, embedded on secsports.com/fbreports-archive and the others), whose archive keeps every report
// since 2025 (SEC, ACC) or 2026 (MAC, American). The Big Ten and Big 12 post theirs elsewhere behind bot protection
// and are not read.
//   node scripts/cfb_avail_reports.mjs          # open each archive page in Chromium, keep what it loads
//                                              # -> data/cfb_avail_reports.json (merged: old rows stay)
// Each row: { c conference, d game date, t team, o opponent, n jersey, p player, s: [initial, update 1, update 2,
// game day] } with null where that report wasn't filed (ACC 2025 had no second update; MAC/American only game day).
// Read by scripts/fetch_cfb.mjs (the live availability log) and scripts/cfb_avail_backtest.mjs (the status rates).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { teamKey, Matcher } from './names.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
export const REPORTS = path.join(ROOT, 'scripts', 'data', 'cfb_avail_reports.json');
export const CONFS = ['SEC', 'ACC', 'MAC', 'American'];
const STAGES = [['Initial'], ['Update 1', 'Thursday'], ['Update 2', 'Friday'], ['Game Day', 'Gameday']];
const MON = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06', Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' };

// "Sat, 13 Sep 2025 00:00:00 GMT" -> 2025-09-13
const day = w => { const m = /(\d{1,2}) (\w{3}) (\d{4})/.exec(w || ''); return m ? `${m[3]}-${MON[m[2]]}-${m[1].padStart(2, '0')}` : null; };
const clean = s => !s || /^\s*-?\s*$/.test(s) ? null : String(s).trim();

export function rowOf(conf, r) {
  return { c: conf, d: day(r.Week), t: r.TeamDisplay || r.Team, o: (r.OpponentDisplay || r.Opponent || '').replace(/^(at|vs\.?)\s+/i, ''),
    away: /^at\s/i.test(r.OpponentDisplay || r.Opponent || '') ? 1 : 0, n: clean(r.Number), p: clean(r.Player),
    s: STAGES.map(keys => clean(keys.map(k => r[k]).find(v => v != null))) };
}

// the newest designation a row carries (game day, else the latest update): what a reader knows at that point
export const latest = r => [...r.s].reverse().find(Boolean) || null;

// the report's word -> the board's status names (scripts/cfb_avail.mjs statusPlay); game time decision is its own
export function boardStatus(s) {
  if (!s) return null;
  if (/game\s*time/i.test(s)) return 'Game Time Decision';
  if (/1st half|first half/i.test(s)) return 'Active';
  if (/^out/i.test(s)) return 'Out';
  if (/doubt/i.test(s)) return 'Doubtful';
  if (/quest/i.test(s)) return 'Questionable';
  if (/prob/i.test(s)) return 'Probable';
  if (/avail/i.test(s)) return 'Active';
  return null;
}

// report rows -> ESPN games (cfb_teams.mjs fetchGames rows): the game on the report's date (a local day; the kickoff in
// UTC can fall the day after) whose two teams match the report's team and opponent. Returns gid|tid -> rows
const tk = s => teamKey(String(s || '').replace(/\bMich\.?\b/, 'Michigan').replace(/\bSt\.\s*$/, 'State'));
const teamIs = (name, loc, abbr) => { const a = tk(name), l = tk(loc); return a === l || a === tk(abbr) || l.startsWith(a + ' ') || a.startsWith(l + ' '); };
export function matchGames(rows, games) {
  const byDay = {};
  for (const g of games) for (const dd of [0, -1]) (byDay[new Date(Date.parse(g.date) + dd * 864e5).toISOString().slice(0, 10)] ||= []).push(g);
  const out = {};
  for (const r of rows) {
    const g = (byDay[r.d] || []).find(g => teamIs(r.t, g.homeName, g.homeAbbr) && teamIs(r.o, g.awayName, g.awayAbbr) || teamIs(r.t, g.awayName, g.awayAbbr) && teamIs(r.o, g.homeName, g.homeAbbr));
    if (!g) continue;
    const tid = teamIs(r.t, g.homeName, g.homeAbbr) && !teamIs(r.o, g.homeName, g.homeAbbr) ? g.home : g.away;
    (out[g.id + '|' + tid] ||= []).push(r);
  }
  return out;
}

// this week's designations for the board: each team's report for its next game (not yet final, within 8 days), matched
// to ESPN's roster. people: [{ id, name, tid, pos }]. Returns { list: [{ a (the roster row), status, stage ('pre' or
// 'gd'), streak (his team's earlier reported games in a row he was listed out), raw, d }], teams: Set of tids that filed }
export function weekStatuses(rows, games, people, now = Date.now()) {
  const M = matchGames(rows, games), G = Object.fromEntries(games.map(g => [g.id, g]));
  // each team's reported games in order, for the out streak
  const hist = {};
  for (const [k, R] of Object.entries(M)) { const [gid, tid] = k.split('|'); (hist[tid] ||= []).push({ gid, date: G[gid].date, R }); }
  for (const h of Object.values(hist)) h.sort((a, b) => a.date.localeCompare(b.date));
  const byTeam = {}; for (const a of people) (byTeam[a.tid] ||= []).push(a);
  const list = [], teams = new Set();
  for (const [tid, h] of Object.entries(hist)) {
    const next = h.find(x => !G[x.gid].done && Date.parse(G[x.gid].date) > now - 6 * 3600e3 && Date.parse(G[x.gid].date) < now + 8 * 864e5);
    if (!next) continue;
    teams.add(tid);
    const prior = h.filter(x => x.date < next.date).reverse();
    const mt = new Matcher(byTeam[tid] || [], { team: 'tid' });
    for (const r of next.R) {
      const raw = latest(r), status = boardStatus(raw); if (!status) continue;
      const [a] = mt.find(r.p, { team: tid }); if (!a) continue;
      let streak = 0;
      for (const x of prior) { if (x.R.some(q => mt.find(q.p, { team: tid })[0]?.id === a.id && /^out/i.test(boardStatus(latest(q)) || ''))) streak++; else break; }
      list.push({ a, status, stage: r.s[3] ? 'gd' : 'pre', streak, raw, d: r.d });
    }
  }
  return { list, teams };
}

export function loadReports() {
  try { return JSON.parse(fs.readFileSync(REPORTS, 'utf8')); } catch { return { asof: null, rows: [] }; }
}

async function scrape() {
  let pw = null;
  for (const spec of ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs']) { try { pw = await import(spec); break; } catch {} }
  if (!pw) throw new Error('needs playwright: npm i --no-save playwright && npx playwright install chromium');
  const { chromium } = pw;
  const b = await chromium.launch();
  const got = [];
  try {
    for (const conf of CONFS) {
      const p = await b.newPage(), seen = [];
      p.on('response', async r => {
        if (!/get-archive/.test(r.url())) return;
        try { const d = await r.json(); for (const x of d?.data || []) seen.push(rowOf(conf, x)); } catch {}
      });
      const url = `https://app.hdintelligence.com/?source=${encodeURIComponent(conf)}&sport=Football&conf=${encodeURIComponent(conf)}&type=archive`;
      try {
        await p.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
        await p.waitForTimeout(1500);
        // earlier seasons sit behind a button on the same page
        await p.getByText('View Seasons Prior').first().click({ timeout: 5000 }).catch(() => {});
        await p.waitForTimeout(3000);
      } catch (e) { console.log(`${conf}: ${e.message.slice(0, 120)}`); }
      console.log(`${conf}: ${seen.length} rows`);
      got.push(...seen);
      await p.close();
    }
  } finally { await b.close(); }
  return got;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const old = loadReports(), rows = await scrape();
  const key = r => [r.c, r.d, r.t, r.p, r.n].join('|');
  const M = new Map(old.rows.map(r => [key(r), r]));
  for (const r of rows) if (r.d && r.p) M.set(key(r), r);
  if (!rows.length) { console.log('no rows read; file left as it was'); process.exit(0); }
  const all = [...M.values()].sort((a, b) => a.d.localeCompare(b.d) || a.c.localeCompare(b.c) || a.t.localeCompare(b.t) || (a.p || '').localeCompare(b.p || ''));
  fs.writeFileSync(REPORTS, JSON.stringify({ asof: new Date().toISOString(), rows: all }) .replace(/\},\{/g, '},\n{') + '\n');
  console.log(`cfb availability reports: ${all.length} rows (${rows.length} read this run)`);
}
