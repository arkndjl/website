// ESPN college box scores, offense only, one file per finished game (scripts/.cache/cfb/box/<id>.json; a final
// box score doesn't change, so each game is pulled once). Who played each game and what he did: the
// availability model and the projection backtest (scripts/cfb_avail.mjs) read them. ESPN lists a player only
// when he recorded a stat, so "played" means touched the ball, threw it or was targeted for a catch.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache', 'cfb', 'box');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const num = s => { const v = parseFloat(s); return Number.isFinite(v) ? v : 0; };

// one game's box: { id, teams: { tid: { athleteId: { n, pos?, att, cmp, passYds, passTd, int, car, rushYds, rushTd, rec, recYds, recTd } } } }
function compact(id, d) {
  const teams = {};
  for (const t of d?.boxscore?.players || []) {
    const P = (teams[t.team.id] = {});
    for (const s of t.statistics || []) {
      const L = s.labels || [];
      const ix = k => L.indexOf(k);
      for (const a of s.athletes || []) {
        const aid = a.athlete?.id; if (!aid) continue;
        const v = a.stats || [], p = (P[aid] ||= { n: a.athlete.displayName });
        if (s.name === 'passing') {
          const [c, at] = (v[ix('C/ATT')] || '0/0').split('/').map(num);
          Object.assign(p, { cmp: c, att: at, passYds: num(v[ix('YDS')]), passTd: num(v[ix('TD')]), int: num(v[ix('INT')]) });
        } else if (s.name === 'rushing') Object.assign(p, { car: num(v[ix('CAR')]), rushYds: num(v[ix('YDS')]), rushTd: num(v[ix('TD')]) });
        else if (s.name === 'receiving') Object.assign(p, { rec: num(v[ix('REC')]), recYds: num(v[ix('YDS')]), recTd: num(v[ix('TD')]) });
      }
    }
    for (const [k, p] of Object.entries(P)) if (p.att == null && p.car == null && p.rec == null) delete P[k];
  }
  return { id, teams };
}

async function pull(id) {
  for (let i = 0; i < 4; i++) {
    try {
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=${id}`, { headers: { 'user-agent': UA } });
      if (r.ok) return await r.json();
    } catch {}
    await sleep(1500 * 2 ** i);
  }
  return null;
}

// box scores for finished games (rows from cfb_teams.mjs fetchGames), id -> box; cached ones are read, the rest
// pulled a few at a time. A game ESPN returns without player stats isn't cached (it may fill in later).
export async function fetchBoxes(games, { conc = 6, log = true } = {}) {
  fs.mkdirSync(DIR, { recursive: true });
  const out = {}, todo = [];
  for (const g of games) {
    if (!g.done) continue;
    const f = path.join(DIR, `${g.id}.json`);
    try { out[g.id] = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { todo.push(g.id); }
  }
  let i = 0, got = 0;
  await Promise.all(Array.from({ length: conc }, async () => {
    while (i < todo.length) {
      const id = todo[i++], d = await pull(id);
      if (!d) continue;
      const b = compact(id, d);
      if (Object.keys(b.teams).length < 2) continue;
      fs.writeFileSync(path.join(DIR, `${id}.json`), JSON.stringify(b));
      out[id] = b; got++;
      if (log && got % 100 === 0) console.log(`box scores: ${got} of ${todo.length} pulled`);
    }
  }));
  if (log) console.log(`box scores: ${Object.keys(out).length} games (${got} new)`);
  return out;
}

// a week's full box scores (offense, defense and kicking) from ESPN in CFBD's games/players shape, for the top
// performers when CFBD is out of quota (it answers 429 once the month's calls are spent). Cached per game in
// scripts/.cache/cfb/boxfull/<id>.json; a game without both teams' stats isn't cached.
const FULL = path.join(path.dirname(DIR), 'boxfull');
export async function fetchFullBoxes(games, { conc = 6 } = {}) {
  fs.mkdirSync(FULL, { recursive: true });
  const out = [], todo = [];
  for (const g of games) {
    if (!g.done) continue;
    try { out.push(JSON.parse(fs.readFileSync(path.join(FULL, `${g.id}.json`), 'utf8'))); } catch { todo.push(g.id); }
  }
  let i = 0;
  await Promise.all(Array.from({ length: conc }, async () => {
    while (i < todo.length) {
      const id = todo[i++], d = await pull(id), side = {};
      for (const c of d?.header?.competitions?.[0]?.competitors || []) side[c.team?.id] = c.homeAway;
      const teams = (d?.boxscore?.players || []).map(t => ({ team: t.team.location || t.team.displayName, homeAway: side[t.team.id] || null,
        categories: (t.statistics || []).map(s => ({ name: s.name, types: (s.labels || []).map((lab, j) => ({ name: lab,
          athletes: (s.athletes || []).filter(a => a.athlete?.id).map(a => ({ id: a.athlete.id, name: a.athlete.displayName, stat: a.stats?.[j] ?? '0' })) })) })) }));
      if (teams.length < 2) continue;
      const b = { id: Number(id), teams };
      fs.writeFileSync(path.join(FULL, `${id}.json`), JSON.stringify(b));
      out.push(b);
    }
  }));
  return out;
}
