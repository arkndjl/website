// Backtest: do data sources FV doesn't use yet predict NFL careers beyond what it already has? Run by hand after
// scripts/cfb_statplus_backtest.mjs (it reuses that script's cached PFN boards and nflverse picks):
//   node scripts/cfb_source_backtest.mjs -> data/cfb_source_backtest.json
// Universe and outcome as in the Stat+ and badge backtests: each player's last PFN season 2019-22 (QB, RB, WR, TE,
// EDGE, DT, LB), weighted NFL AV a season through 2025, undrafted = 0, players in a later draft dropped.
// Candidates (all free, all with 2019-22 history):
//   aa        first-team All-America selectors in the final season (Wikipedia "<year> All-America college football
//             team": AP, AFCA, FWAA, TSN, WCFF, CBS, ESPN, The Athletic, USA Today), as a count
//   senior    Senior Bowl roster the January after the final season (Wikipedia rosters)
//             (the East-West Shrine Bowl has no roster history on Wikipedia, so it can't be tested)
//   combine   invited to the NFL combine (nflverse combine.csv lists every invitee, tested or not)
//   athletic  combine testing (40 as a speed score, vertical, broad, 3-cone, shuttle; z's within position among
//             invitees, mean of what he ran), tested on invitees only
//   pipeline  NFL picks from his program in the five drafts before his (a development / evaluation prior)
// Controls. A: FV's production term (5/4/3 blend, FV_K 3000), the bar the badge test used. B: production plus the
// consensus board (DraftTek's final pre-draft top ~550, log rank and its square, unranked = 700), which is what FV adds for a draft-
// eligible player (CONS_W). A source earns weight only if it passes both (t >= 2 and a leave-one-final-season-out
// R^2 gain): for a player the boards rank, FV already holds the board, and anything the boards see is in it.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { NFLPOS } from './cfb_nflpos.mjs';   // the shared draft-position map (EDGEs listed as LB, Oct 21 2026)

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SP = path.join(ROOT, 'scripts', '.cache', 'statplus'), SRC = path.join(ROOT, 'scripts', '.cache', 'sources');
const OUT = path.join(ROOT, 'data', 'cfb_source_backtest.json');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
fs.mkdirSync(SRC, { recursive: true });
const SPG = { QB: 65, RB: 30, WR: 40, TE: 40, EDGE: 50, DL: 45, LB: 55 };
const NFL_THROUGH = 2025, K = 3000, W = [5, 4, 3], LAST = [2019, 2020, 2021, 2022];

async function cached(file, url) {
  const f = path.join(SRC, file);
  if (!fs.existsSync(f)) { const r = await fetch(url, { headers: { 'user-agent': UA } }); fs.writeFileSync(f, r.ok ? await r.text() : ''); }
  return fs.readFileSync(f, 'latin1');
}
function csv(text) {
  const rows = []; let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else if (c === '"') q = true; else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n') { row.push(cur.replace(/\r$/, '')); rows.push(row); row = []; cur = ''; } else cur += c;
  }
  if (cur || row.length) { row.push(cur); rows.push(row); }
  const [h, ...b] = rows; return b.filter(r => r.length === h.length).map(r => Object.fromEntries(h.map((k, i) => [k, r[i]])));
}
const nm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[^a-z ]/g, '').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
const col = s => nm(s).replace(/\bstate\b/, 'st').replace(/\buniversity\b|\bof\b/g, '').replace(/\s+/g, ' ').trim();
const school = s => col(s).split(' ')[0];
const mean = xs => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sdv = xs => { const m = mean(xs); return Math.sqrt(mean(xs.map(x => (x - m) ** 2))) || 1; };
const r3 = x => x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000;
function solve(A, b) {
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = c + 1; r < n; r++) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  const x = Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) { let s = M[r][n]; for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k]; x[r] = s / M[r][r]; }
  return x;
}
function ols(X, y) {
  const k = X[0].length, A = Array.from({ length: k + 1 }, () => Array(k + 1).fill(0)), b = Array(k + 1).fill(0);
  X.forEach((r, i) => { const z = [1, ...r]; for (let a = 0; a <= k; a++) { b[a] += z[a] * y[i]; for (let c = 0; c <= k; c++) A[a][c] += z[a] * z[c]; } });
  for (let a = 1; a <= k; a++) A[a][a] += 1e-6;
  return solve(A, b);
}
const pred = (co, r) => co[0] + r.reduce((a, x, i) => a + co[i + 1] * x, 0);
// t of the candidate's coefficient (last column) in y ~ controls + x, and the leave-one-final-season-out R^2 gain
function test(P, ctl, x) {
  const S = P.filter(p => x(p) != null);
  if (S.length < 40 || new Set(S.map(x)).size < 2) return null;
  const X = S.map(p => [...ctl(p), x(p)]), y = S.map(p => p.av), co = ols(X, y), k = X[0].length + 1;
  const res = y.map((v, i) => v - pred(co, X[i])), s2 = res.reduce((a, e) => a + e * e, 0) / (S.length - k);
  // (X'X)^-1 last diagonal by solving against the unit vector
  const A = Array.from({ length: k }, () => Array(k).fill(0));
  X.forEach(r => { const z = [1, ...r]; for (let a = 0; a < k; a++) for (let c = 0; c < k; c++) A[a][c] += z[a] * z[c]; });
  const e = Array(k).fill(0); e[k - 1] = 1; const vk = solve(A, e)[k - 1], se = Math.sqrt(s2 * vk);
  const xs = S.map(x), sx = sdv(xs);
  let sse0 = 0, sse1 = 0, sst = 0;
  for (const s of LAST) {
    const tr = S.filter(p => p.last !== s), te = S.filter(p => p.last === s); if (!te.length || tr.length < 30) continue;
    const my = mean(tr.map(p => p.av)), b0 = ols(tr.map(ctl), tr.map(p => p.av)), b1 = ols(tr.map(p => [...ctl(p), x(p)]), tr.map(p => p.av));
    for (const p of te) { sse0 += (p.av - pred(b0, ctl(p))) ** 2; sse1 += (p.av - pred(b1, [...ctl(p), x(p)])) ** 2; sst += (p.av - my) ** 2; }
  }
  const t = co[k - 1] / se, gain = 100 * (sse0 - sse1) / sst;
  return { n: S.length, hits: xs.filter(v => v > 0).length, beta: r3(co[k - 1]), perSd: r3(co[k - 1] * sx), t: Math.round(t * 100) / 100, oosGain: r3(gain), pass: t >= 2 && gain > 0 };
}

// ---- sources ------------------------------------------------------------------------------------------------
const picksAll = csv(fs.readFileSync(path.join(SP, 'draft_picks.csv'), 'utf8'));
const picks = picksAll.filter(r => +r.season >= 2020 && +r.season <= 2025);
const combine = csv(await cached('combine.csv', 'https://github.com/nflverse/nflverse-data/releases/download/combine/combine.csv'));
const wikiRaw = t => cached(t.replace(/[^\w-]/g, '_') + '.txt', `https://en.wikipedia.org/w/index.php?title=${encodeURIComponent(t)}&action=raw`);
const linkName = s => s.replace(/\{\{sortname\|([^|}]+)\|([^|}]+)[^}]*\}\}/g, '$1 $2').replace(/\[\[(?:[^\]|]*\|)?([^\]]+)\]\]/g, '$1').replace(/<[^>]+>|'''|''|\*/g, '').replace(/\(.*?\)/g, '').trim();
// All-America: the per-position lists ("*[[Name]], [[team|School]] <small>(selectors)</small>")
const aa = {};
for (const y of LAST) {
  const t = await wikiRaw(`${y} All-America college football team`);
  for (const m of t.matchAll(/^\*+\s*(.+?),\s*\[\[[^\]|]*\|([^\]]+)\]\][^\n]*?<small>\s*\(([^)]*)\)/gm)) {
    const n = nm(linkName(m[1])), sel = m[3].split(',').filter(s => s.trim()).length;
    const k = y + '|' + n; aa[k] = Math.max(aa[k] || 0, sel); aa[k + '|' + school(m[2])] = aa[k];
  }
}
// all-star rosters: wikitable rows "| no || [[Name]] || POS || ht/wt || [[team|School]]"
async function roster(title) {
  const t = await wikiRaw(title), out = new Set();
  for (const line of t.split('\n')) {
    const c = line.split('||'); if (c.length < 4) continue;
    const name = nm(linkName(c[1] || '')); if (name && name.split(' ').length >= 2) out.add(name);
  }
  return out;
}
const senior = {};
for (const y of LAST) senior[y + 1] = await roster(`${y + 1} Senior Bowl`);
// DraftTek final big boards
const board = {};
for (const D of LAST.map(y => y + 1)) {
  board[D] = {};
  for (let pg = 1; pg <= 6; pg++) {
    const s = (await cached(`dt_${D}_${pg}.html`, `https://www.drafttek.com/${D}-NFL-Draft-Big-Board/Top-NFL-Draft-Prospects-${D}-Page-${pg}.asp`)).replace(/<!--.*?-->/gs, '');
    for (const tr of s.matchAll(/<tr[^>]*>(.*?)<\/tr>/gs)) {
      const td = [...tr[1].matchAll(/<td[^>]*>(.*?)<\/td>/gs)].map(m => m[1].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").trim());
      if (td.length >= 8 && /^\d+$/.test(td[0])) { const k = nm(td[2]); if (!(k in board[D])) board[D][k] = +td[0]; }
    }
  }
}
// combine invitees and testing
const comb = {};
for (const r of combine) if (+r.season >= 2020 && +r.season <= 2023) comb[r.season + '|' + nm(r.player_name)] = r;
const athGroup = p => ({ QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', DE: 'EDGE', OLB: 'EDGE', EDGE: 'EDGE', DT: 'DL', DL: 'DL', NT: 'DL', ILB: 'LB', LB: 'LB', MLB: 'LB',
  OT: 'OL', T: 'OL', OG: 'OL', G: 'OL', C: 'OL', OL: 'OL', CB: 'CB', S: 'S', SAF: 'S', FS: 'S', SS: 'S', DB: 'CB' })[p];
const ath = {};
{ // athletic z within NFL position group among invitees 2010-25: speed score (wt x 200 / 40^4), vertical, broad, -cone, -shuttle
  const grp = athGroup;
  const met = r => ({ spd: +r.forty ? +r.wt * 200 / (+r.forty) ** 4 : null, vert: +r.vertical || null, broad: +r.broad_jump || null, cone: +r.cone ? -r.cone : null, shut: +r.shuttle ? -r.shuttle : null });
  const pool = {};
  for (const r of combine) { const g = grp(r.pos); if (!g || +r.season < 2010) continue; const m = met(r); for (const [k, v] of Object.entries(m)) if (v != null) (pool[g + k] ||= []).push(v); }
  for (const r of combine) {
    const g = grp(r.pos); if (!g || +r.season < 2020 || +r.season > 2023) continue;
    const zs = Object.entries(met(r)).filter(([, v]) => v != null).map(([k, v]) => (v - mean(pool[g + k])) / sdv(pool[g + k]));
    if (zs.length >= 2) ath[r.season + '|' + nm(r.player_name)] = mean(zs);
  }
  // centred on the mean tester at the group since 2010, as fetchCombine does for the board (the fits have intercepts,
  // so this moves no test result)
  const tm = {};
  for (const r of combine) { const g = grp(r.pos); if (!g || +r.season < 2010) continue;
    const zs = Object.entries(met(r)).filter(([, v]) => v != null).map(([k, v]) => (v - mean(pool[g + k])) / sdv(pool[g + k]));
    if (zs.length >= 2) (tm[g] ||= []).push(mean(zs)); }
  for (const r of combine) { const k = r.season + '|' + nm(r.player_name); if (k in ath && +r.season >= 2020 && +r.season <= 2023) ath[k] -= mean(tm[grp(r.pos)]); }
}
// program pipeline: picks a year from the school in the five drafts before
const progPicks = {};
for (const r of picksAll) (progPicks[school(r.college)] ||= {})[r.season] = ((progPicks[school(r.college)] || {})[r.season] || 0) + 1;
const pipeline = (team, D) => { const p = progPicks[school(team)] || {}; let n = 0; for (let y = D - 5; y < D; y++) n += p[y] || 0; return n / 5; };

// ---- universe -----------------------------------------------------------------------------------------------
const out = { asof: new Date().toISOString().slice(0, 10), method: 'see scripts/cfb_source_backtest.mjs', coverage: {}, positions: {}, pooled: {} };
const CANDS = {
  aa: p => p.aa, aaAny: p => (p.aa > 0 ? 1 : 0), aaPrev: p => p.aaPrev, senior: p => p.senior,
  combine: p => p.combine, athletic: p => p.ath, pipeline: p => p.pipe,
};
const all = [];
for (const g of Object.keys(SPG)) {
  const rows = JSON.parse(fs.readFileSync(path.join(SP, `pfn_${g}.json`))).filter(r => r.division === 'FBS'), cz = {};
  for (const r of rows) (cz[r.season] ||= []).push(r.score);
  for (const s of Object.keys(cz)) cz[s] = [mean(cz[s]), sdv(cz[s])];
  const byId = {};
  for (const r of rows) { r._z = (r.score - cz[r.season][0]) / cz[r.season][1]; r._v = (typeof r.snapsQ === 'number' ? r.snapsQ : null) ?? (typeof r.snaps === 'number' ? r.snaps : null) ?? ((r.gp ?? r.gamesQ ?? 0) * SPG[g]); (byId[r.id] ||= {})[r.season] = r; }
  const P = [];
  for (const by of Object.values(byId)) {
    const last = Math.max(...Object.keys(by).map(Number)); if (last > 2022) continue;
    const r = by[last], D = last + 1, n = nm(r.name), cand = picks.filter(p => nm(p.pfr_player_name) === n && NFLPOS[g].includes(p.position));
    const pk = cand.find(p => +p.season === D && school(p.college) === school(r.team)) || cand.find(p => +p.season === D);
    if (!pk && cand.some(p => +p.season > D)) continue;
    let a = 0, d = 0; W.forEach((w, k) => { const x = by[last - k]; if (x) { a += w * x._v * x._z; d += w * x._v; } });
    const rk = board[D][n];
    const cb = comb[D + '|' + n], cbOk = cb && (!cb.school || school(cb.school) === school(r.team) || pk);
    P.push({ g, last, name: r.name, prod: a / (d + K), lrank: Math.log(rk || 700), ranked: !!rk, av: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0,
      aa: aa[last + '|' + n + '|' + school(r.team)] ?? (aa[last + '|' + n] && r._z > 1 ? aa[last + '|' + n] : 0),
      aaPrev: last > 2019 ? Math.max(0, ...LAST.filter(y => y < last && by[y]).map(y => aa[y + '|' + n + '|' + school(by[y].team)] || 0)) : null,
      senior: senior[D].has(n) ? 1 : 0, combine: cbOk ? 1 : 0, ath: cbOk ? ath[D + '|' + n] ?? null : null, pipe: pipeline(r.team, D) });
  }
  const res = { n: P.length, drafted: P.filter(p => p.av > 0 || picks.some(() => false)).length, A: {}, B: {} };
  for (const [k, x] of Object.entries(CANDS)) {
    res.A[k] = test(P, p => [p.prod], x);
    res.B[k] = test(P, p => [p.prod, p.lrank, p.lrank ** 2], x);
  }
  out.positions[g] = res; all.push(...P);
}
// pooled, with position intercepts and production slopes by position folded in as dummies x production
const GS = Object.keys(SPG);
const ctlA = p => [p.prod, ...GS.slice(1).map(g => +(p.g === g)), ...GS.slice(1).map(g => (p.g === g) * p.prod)];
const ctlB = p => [...ctlA(p), p.lrank, p.lrank ** 2];
for (const [k, x] of Object.entries(CANDS)) out.pooled[k] = { A: test(all, ctlA, x), B: test(all, ctlB, x) };
// draft-eligible seniors only (the all-star pool): all-star games invite only players out of eligibility, so underclassmen
// who declare early would read as non-invitees. Proxy: players DraftTek ranks or the combine invited
const elig = all.filter(p => p.ranked || p.combine);
for (const k of ['senior', 'aa', 'aaPrev', 'athletic', 'pipeline']) out.pooled[k].Bprospects = test(elig, ctlB, CANDS[k]);
// the weight: athletic and production per SD in the same fit (control B, invitees), as FV_BADGE converts badges
{ const S = all.filter(p => p.ath != null), X = S.map(p => [...ctlB(p), p.ath]), co = ols(X, S.map(p => p.av));
  const prodSd = sdv(S.map(p => p.prod)), athSd = sdv(S.map(p => p.ath));
  out.athleticWeight = { n: S.length, prodPerSd: r3(co[1] * prodSd), athPerSd: r3(co[X[0].length] * athSd), athSd: r3(athSd) }; }
// board only: every combine invitee 2020-23 at every position (OL, CB and S have no PFN history before 2024, so this is
// their only test): NFL AV a season ~ DraftTek log rank (+ square) + athletic z, by group and pooled with group dummies
{ const B = [];
  for (const r of combine) {
    const D = +r.season, g = athGroup(r.pos), n = nm(r.player_name); if (D < 2020 || D > 2023 || !g || ath[D + '|' + n] == null) continue;
    const pk = picksAll.find(p => +p.season === D && nm(p.pfr_player_name) === n), rk = board[D][n];
    B.push({ g, last: D - 1, av: pk ? (+pk.w_av || 0) / (NFL_THROUGH - D + 1) : 0, lrank: Math.log(rk || 700), ath: ath[D + '|' + n] });
  }
  const G = [...new Set(B.map(p => p.g))].sort(), ctl = p => [p.lrank, p.lrank ** 2, ...G.slice(1).map(g => +(p.g === g))];
  out.boardOnly = { pooled: test(B, ctl, p => p.ath), byGroup: Object.fromEntries(G.map(g => [g, test(B.filter(p => p.g === g), p => [p.lrank, p.lrank ** 2], p => p.ath)])) }; }
out.coverage = { players: all.length, ranked: all.filter(p => p.ranked).length, aa: all.filter(p => p.aa > 0).length, senior: all.filter(p => p.senior).length,
  combine: all.filter(p => p.combine).length, athletic: all.filter(p => p.ath != null).length };
fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
console.log(JSON.stringify(out.coverage));
for (const [k, v] of Object.entries(out.pooled)) console.log(k.padEnd(9), JSON.stringify(v));
console.log('athleticWeight', JSON.stringify(out.athleticWeight)); console.log('boardOnly', JSON.stringify(out.boardOnly, null, 0));
for (const g of GS) console.log(g, Object.entries(out.positions[g].B).map(([k, v]) => `${k} ${v ? v.t + '/' + v.oosGain : '-'}`).join('  '));
