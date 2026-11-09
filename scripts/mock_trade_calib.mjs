// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// The NFL mock's projected draft-day trades by round, against real ones (scripts/mock_trade_history.py,
// data/nfl_trade_shapes.json): deals a year, the jump, jumps of 10+ / 16+, and the share sending next year's picks.
//   node scripts/mock_trade_calib.mjs [sims 8] [mode pred] [rounds 7] ['{"gapLn":.2}' TRADE_SHAPE override]
// Runs the mock on the live CFB board (static/data/cfb-all.json) over simulated draft orders; inputs cached in
// scripts/.cache/mock (delete to refetch).
import fs from 'fs';
import { mockDraft, reslotOrder, nflSimOrders, fetchNflOrder, fetchNflNeeds, fetchNflTrades, applyNflTrades, fetchNflRecentR1, TRADE_SHAPE } from './cfb_teams.mjs';
const C = 'scripts/.cache/mock/', SEASON = 2026;
fs.mkdirSync(C, { recursive: true });
const cached = async (f, fn) => fs.existsSync(C + f) ? JSON.parse(fs.readFileSync(C + f)) : (x => (fs.writeFileSync(C + f, JSON.stringify(x)), x))(await fn());
Object.assign(TRADE_SHAPE, JSON.parse(process.argv[5] || '{}'));
const d = JSON.parse(fs.readFileSync('static/data/cfb-all.json'));
const rows = d.rows.map(r => Object.fromEntries(d.cols.map((c, i) => [c, r[i]])));
const tank0 = await cached('tank.json', async () => { const o = await fetchNflOrder(SEASON); o.needs = await fetchNflNeeds(o.teams); return o; });
const tr = await cached('tr27.json', () => fetchNflTrades(SEASON + 1)), tr2 = await cached('tr28.json', () => fetchNflTrades(SEASON + 2));
const r1 = await cached('r1.json', () => fetchNflRecentR1(SEASON + 1));
const priors = { ...JSON.parse(fs.readFileSync('data/cfb_draft_priors.json')), combine: null, futureTrades: tr2 || [], draftYear: SEASON + 1, asof: new Date(d.asof) };
const N = +(process.argv[2] || 8), mode = process.argv[3] || 'pred', rounds = +(process.argv[4] || 7);
const orders = nflSimOrders(SEASON), ups = [];
for (let s = 0; s < N; s++) {
  const tank = structuredClone(tank0); applyNflTrades(tank.order, tr, tank.teams); tank.recentR1 = r1;
  if (orders && s > 0) tank.order = reslotOrder(tank.order, orders[(s * 37) % orders.length]);
  for (const k of mockDraft(rows, tank, rounds, priors, mode))
    if (k.trade?.up) ups.push({ rd: k.round, gap: k.trade.gave[0] - k.pick, cur: k.trade.gave.length, fut: (k.trade.future || []).map(f => f.round) });
}
const real = JSON.parse(fs.readFileSync('data/nfl_trade_shapes.json'));
for (let r = 1; r <= rounds; r++) {
  const L = ups.filter(u => u.rd === r), g = L.map(u => u.gap).sort((a, b) => a - b), k = L.length || 1, f = x => +x.toFixed(3);
  const m = { perYear: f(L.length / N), gapMedian: g[g.length >> 1], gap10: f(g.filter(x => x >= 10).length / k), gap16: f(g.filter(x => x >= 16).length / k),
    futAny: f(L.filter(u => u.fut.length).length / k), futR1: f(L.filter(u => u.fut.includes(1)).length / k), curMean: f(L.reduce((a, u) => a + u.cur, 0) / k) };
  console.log('R' + r, 'mock', JSON.stringify(m), '\n   real', JSON.stringify(Object.fromEntries(Object.keys(m).map(c => [c, real['R' + r]?.[c]]))));
}
