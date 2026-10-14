// Backtest for the mock draft's order (nflDraftOrder in cfb_teams.mjs): rebuilds each 2020-25 draft's first round
// from the season before (ESPN games, standings and playoffs) and checks it against the real one, by the team
// each pick started with (ESPN's draft API: the holder, or "From X" on a traded pick). Forfeited picks (Miami 2023)
// drop out of the real round, so the comparison is on order, not slot. Run by hand: node scripts/nfl_order_backtest.mjs
import { nflSeason, nflDraftOrder } from './cfb_teams.mjs';
const get = async u => { for (let i = 0; i < 4; i++) { try { const r = await fetch(u); if (r.ok) return r.json(); } catch {} await new Promise(r => setTimeout(r, 1500 * 2 ** i)); } return null; };
let hit = 0, n = 0;
for (let season = 2019; season <= 2024; season++) {
  const S = await nflSeason(season), byId = Object.fromEntries(Object.values(S.teams).map(t => [String(t.id), t.team]));
  const ours = nflDraftOrder(S).map(t => t.team);
  const r1 = await get(`https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/${season + 1}/draft/rounds`);
  const real = (r1?.items?.[0]?.picks || []).map(p => {
    const holder = byId[(p.team?.$ref || '').match(/teams\/(\d+)/)?.[1]], from = (p.tradeNote || '').match(/^From ([A-Z]{2,3})/)?.[1];
    return from ? ({ LAR: 'LAR', JAC: 'JAX', WAS: 'WSH', OAK: 'LV' }[from] || from) : holder;
  });
  const ourR = ours.filter(t => real.includes(t)), miss = [];
  real.forEach((t, i) => { n++; if (ourR[i] === t) hit++; else miss.push(`#${i + 1} real ${t} ours ${ourR[i]}`); });
  console.log(`${season + 1} draft: ${real.length - miss.length}/${real.length} first-round slots match${miss.length ? '; ' + miss.join(', ') : ''}`);
}
console.log(`all: ${hit}/${n}`);
