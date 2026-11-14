// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// J5 of PREREG.md: how often a player RotoWire's news lists as questionable, doubtful, out or cleared is in the next
// ESPN box score, 2026 weeks 1-10. Rates fit on games through Oct 3, scored on Oct 4 to week 10.
//   node scripts/research/inj_nov14/cfb_news_status.mjs   -> data/inj_nov14_cfb_news.json
import fs from 'node:fs';
import zlib from 'node:zlib';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchGames, statusOf } from '../../cfb_teams.mjs';
import { fetchBoxes } from '../../cfb_box.mjs';
import { timelines, states, pBox, statusPlay, reportPlay } from '../../cfb_avail.mjs';
import { Matcher, key } from '../../names.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const FIT = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'cfb_avail_fit.json'), 'utf8'));
const clip = p => Math.min(0.995, Math.max(0.005, p));
const ll = (p, y) => -(y ? Math.log(clip(p)) : Math.log(1 - clip(p)));
const r3 = x => Math.round(x * 1000) / 1000;
const usDay = iso => new Date(new Date(iso).getTime() - 6 * 3600e3).toISOString().slice(0, 10);

const games = (await fetchGames(2026)).filter(g => g.done && g.week <= 10);
const boxes = await fetchBoxes(games, { log: false });
const items = Object.values(JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, 'scripts/data/rotowire_history/cfootball.json.gz')))).items);
const byTeam = {};
const nameOf = {};
for (const g of games) { nameOf[g.home] = g.homeName; nameOf[g.away] = g.awayName; }
const tkey = s => key(s).replace(/\bst\b/g, 'state');
const tid = Object.fromEntries(Object.entries(nameOf).map(([id, n]) => [tkey(n), id]));
let unTeam = 0;
for (const it of items) {
  const st = statusOf(it.head) || statusOf((it.body || '').split(/(?<=\.)\s/)[0] || '', true); if (!st) continue;
  const t = tid[tkey(it.team)] || tid[tkey(it.abbr)]; if (!t) { unTeam++; continue; }
  (byTeam[t] ||= []).push({ d: it.d, st, player: it.player });
}
const tl = timelines(games, boxes);
const obs = [];
for (const [t, list] of Object.entries(tl)) for (let k = 2; k < list.length; k++) {
  const S = states(list, k, FIT.m ?? 0);
  const M = new Matcher(Object.entries(S).map(([pid, x]) => ({ pid, name: x.n, team: t })), { team: 'team' });
  const day = usDay(list[k].date), prev = usDay(list[k - 1].date);
  const cur = {};
  for (const it of (byTeam[t] || []).filter(i => i.d > prev && i.d < day).sort((a, b) => a.d.localeCompare(b.d))) {
    const [hit] = M.find(it.player, { team: t }); if (hit) cur[hit.pid] = it.st;
  }
  for (const [pid, st] of Object.entries(cur)) {
    const x = S[pid]; if (st === 'Out (season)') continue;
    obs.push({ t, day, pid, st, ml: x.streak >= 1, p0: pBox(FIT.coef, x), ppg: x.ppg, y: list[k].players[pid] ? 1 : 0 });
  }
}
const cell = o => o.st + (o.ml ? '|missed last' : '|played last');
const table = o => statusPlay(FIT, o.st, o.ml) ?? o.p0;                               // the registered base: the status table
const live = o => statusPlay(FIT, o.st, o.ml, o.p0) ?? o.p0;                          // what the board prices news at today (the reports' fit)
const A = obs.filter(o => o.day <= '2026-10-03'), B = obs.filter(o => o.day > '2026-10-03');
const rate = {};
for (const c of new Set(obs.map(cell))) {
  const o = A.filter(x => cell(x) === c), base = table({ st: c.split('|')[0], ml: c.endsWith('missed last'), p0: 0.5 });
  rate[c] = { n: o.length, played: o.reduce((a, x) => a + x.y, 0), table: r3(base), p: r3((o.reduce((a, x) => a + x.y, 0) + 10 * base) / (o.length + 10)) };
}
const cand = o => rate[cell(o)].p;
const paired = (os, f, g) => {
  const C = {}; for (const o of os) C[o.day] = (C[o.day] || 0) + ll(f(o), o.y) - ll(g(o), o.y);
  const v = Object.values(C), n = os.length, m = v.reduce((a, x) => a + x, 0) / n;
  const se = Math.sqrt(v.length / (v.length - 1) * v.reduce((a, x) => a + x * x, 0)) / n;
  return { n, days: v.length, base: r3(os.reduce((a, o) => a + ll(g(o), o.y), 0) / n), cand: r3(os.reduce((a, o) => a + ll(f(o), o.y), 0) / n), d: r3(m), t: r3(m / se) };
};
const heldRates = Object.fromEntries([...new Set(B.map(cell))].sort().map(c => { const o = B.filter(x => cell(x) === c);
  return [c, { n: o.length, played: r3(o.reduce((a, x) => a + x.y, 0) / o.length), cand: rate[c].p, table: rate[c].table, live: r3(o.reduce((a, x) => a + live(x), 0) / o.length) }]; }));
const out = { prereg: 'scripts/research/inj_nov14/PREREG.md', items: items.length, unmatchedTeams: unTeam, rows: { tune: A.length, held: B.length }, tuneRates: rate, heldRates,
  registered_vsTable: { tune: paired(A, cand, table), held: paired(B, cand, table) }, vsLivePricing: { tune: paired(A, cand, live), held: paired(B, cand, live) },
  liveVsTable: { held: paired(B, live, table) } };
console.log(JSON.stringify(out, null, 1));
fs.writeFileSync(path.join(ROOT, 'data', 'inj_nov14_cfb_news.json'), JSON.stringify(out, null, 1));
