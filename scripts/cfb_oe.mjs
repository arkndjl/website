// Actual vs expected for the College Football ARKBOARD: what a player gains over what the play's context predicts,
// from CFBD play-by-play (the same slim plays as scripts/cfb_pbp.mjs; old and new play-text formats both parse).
// Context is what he doesn't control: down, distance and field position (the baseline, cell means), the defense,
// and on passes the other half of the throw, fitted jointly as crossed ridge effects (as in adjusted plus-minus):
//   rushing    yards a carry (capped at OE.cap) = baseline + rusher + defense: rushing yards over expected (RYOE)
//   dropbacks  ANY/A value a dropback (yards + 20 a TD - 45 an INT; sacks count) = baseline + passer + target +
//              defense, so a QB throwing to Jeremiah Smith doesn't keep Smith's yards and Smith doesn't keep his QB's
//   catch      completion = baseline (plus air yards where the text has the spot the ball was thrown to, 2026 on)
//              + passer + target + defense: completion % over expected (CPOE)
// Each effect is shrunk by its own ridge penalty (in plays: the count at which a player's own average counts for
// half). `oe` is the player's effect a play; `nv` is the same shrinkage of his raw numbers over the baseline alone,
// so oe - nv is how much his context flattered (-) or hid (+) him a play.
// Tested on ESPN play-by-play 2017-26 (scripts/cfb_oe_backtest.mjs): an offense effect (line, scheme) was
// dropped because it took credit from the one player who dominates a team's touches (a bell-cow back, the QB),
// making every test worse; yards after catch over expected (2026 text only) repeated worse than raw YAC.
import { pbpKey } from './cfb_pbp.mjs';

export const OE = {
  cap: [-10, 40],                       // rushing yards a carry, capped: one 80-yard run is mostly blocking and pursuit angles
  ridge: { player: 150, def: 400, target: 400 },   // target 400 beat 50 and 120 for both QBs and receivers (1000 the same)
  iters: 25,
  td: 20, int: -45,                     // ANY/A weights
};

const SUFFIX = /\b(jr|sr|ii|iii|iv|v)\b\.?/gi;
const N1 = "(?:#\\d+\\s+)?([A-Z][A-Za-z'.\\-]*(?:\\s(?:[A-Z][A-Za-z'.\\-]*|Jr\\.?|Sr\\.?|II|III|IV))*)";
const RX = {
  rush: new RegExp(`^(?:\\(\\d+:\\d+\\)\\s*)?(?:[A-Za-z -]*?(?:Shotgun|Huddle|Pistol|Formation)\\s+)?${N1}\\s+(?:run|rush|scramble)`),
  pass: new RegExp(`${N1}\\s+pass(?:\\s+(complete|incomplete|intercepted))?(?:\\s+(short|deep)\\s+(?:left|middle|right))?(?:\\s+to\\s+${N1})?`),
  sackNew: new RegExp(`${N1}\\s+sacked`),
  spot: /(?:caught|thrown) (?:at|to) ([A-Z][A-Za-z&]*?)\s?(\d{1,2})\b/,
  end: /to the ([A-Z][A-Za-z&]*?)\s?(\d{1,2})\b/,
};
const clean = s => (s || '').replace(SUFFIX, '').replace(/\s+/g, ' ').trim();
const isRush = t => t === 'Rush' || t === 'Rushing Touchdown';
const isPass = t => /^Pass (Reception|Incompletion)|^Passing Touchdown|Interception|^Sack/.test(t || '');

// which side of the field each abbreviation in a game's play text means, from end spots ("to the TENN36") of
// plays whose yards-to-goal after the play is known: per game and offense, abbreviation -> 'def' or 'off'
function sides(plays) {
  const v = {};
  for (const p of plays) {
    if (!(isRush(p.t) || p.t === 'Pass Reception') || p.ytg == null || p.y == null) continue;
    const m = RX.end.exec(p.x || ''); if (!m) continue;
    const after = p.ytg - p.y, n = +m[2]; if (n === 50) continue;
    const k = p.g + '|' + p.o + '|' + m[1], s = (v[k] ||= { def: 0, off: 0 });
    if (n === after) s.def++; else if (100 - n === after) s.off++;
  }
  const out = {};
  for (const [k, s] of Object.entries(v)) if (s.def !== s.off) out[k] = s.def > s.off ? 'def' : 'off';
  return out;
}

// one play -> { kind: 'rush' | 'drop', team, def, actor, target, comp, td, int, sack, air, yac, y, situation }
export function parsePlays(plays) {
  const side = sides(plays), out = [];
  for (const p of plays) {
    const t = p.t || '', x = (p.x || '').replace(/\s+/g, ' ');
    if (!(p.dn >= 1 && p.dn <= 4) || p.ytg == null || /NO PLAY|Kneel|kneel|spike/.test(x)) continue;
    const base = { g: p.g, team: p.o, def: p.d, dn: p.dn, ds: p.ds, ytg: p.ytg, y: p.y ?? 0, td: /Touchdown|TOUCHDOWN|for a TD/.test(t + ' ' + x) };
    if (isRush(t)) {
      const m = RX.rush.exec(x) || /^(.+?)\s+(?:run|rush)\s+for/.exec(x); if (!m) continue;
      out.push({ ...base, kind: 'rush', actor: pbpKey(clean(m[1])) });
    } else if (isPass(t)) {
      if (/^Sack/.test(t)) {
        const m = RX.sackNew.exec(x) || /^(.+?)\s+sacked/.exec(x); if (!m) continue;
        out.push({ ...base, kind: 'drop', sack: true, actor: pbpKey(clean(m[1])), td: false });
        continue;
      }
      const m = RX.pass.exec(x); if (!m) continue;
      const int = /intercept/i.test(t) || m[2] === 'intercepted', comp = !int && (t === 'Pass Reception' || t === 'Passing Touchdown' || m[2] === 'complete');
      const tgt = m[4] ? pbpKey(clean(m[4].replace(/\s+(for|caught|thrown)$/, ''))) : null;
      let air = null;
      const s = RX.spot.exec(x);
      if (s) { const sd = side[p.g + '|' + p.o + '|' + s[1]], n = +s[2]; const at = n === 50 ? 50 : sd === 'def' ? n : sd === 'off' ? 100 - n : null; if (at != null) air = p.ytg - at; }
      out.push({ ...base, kind: 'drop', actor: pbpKey(clean(m[1])), target: tgt, comp, int, depth: m[3] || null, air,
        yac: comp && air != null ? (p.y ?? 0) - air : null, td: base.td && !int });
    }
  }
  return out;
}

// baseline cells: down (1, 2, 3+), distance and field position buckets; optional extra key (air yards)
const dsB = d => d <= 2 ? 0 : d <= 5 ? 1 : d <= 9 ? 2 : d === 10 ? 3 : 4;
const ytgB = y => y <= 5 ? 0 : y <= 10 ? 1 : y <= 20 ? 2 : y <= 50 ? 3 : 4;
const sit = e => `${Math.min(e.dn, 3)}|${dsB(e.ds)}|${ytgB(e.ytg)}`;
export const airB = a => a == null ? 'u' : a <= 0 ? 0 : a <= 5 ? 1 : a <= 10 ? 2 : a <= 15 ? 3 : a <= 20 ? 4 : a <= 30 ? 5 : 6;
function baseline(rows, key, val, k = 30) {
  let s = 0; for (const r of rows) s += val(r); const mu = s / Math.max(1, rows.length);
  const c = {}; for (const r of rows) { const q = (c[key(r)] ||= [0, 0]); q[0] += val(r); q[1]++; }
  const b = {}; for (const [q, [sum, n]] of Object.entries(c)) b[q] = (sum + k * mu) / (n + k);
  return r => b[key(r)] ?? mu;
}

// crossed ridge effects by backfitting: y - baseline = sum over groups of effect[group key], each shrunk by its λ
function ridge(rows, resid, groups, iters) {
  const eff = groups.map(() => ({})), r = rows.map((row, i) => resid[i]);
  for (let it = 0; it < iters; it++) {
    groups.forEach(([key, lam], gi) => {
      const sum = {}, n = {}, E = eff[gi];
      rows.forEach((row, i) => { const k = key(row); if (k == null) return; const cur = r[i] + (E[k] || 0); sum[k] = (sum[k] || 0) + cur; n[k] = (n[k] || 0) + 1; });
      const next = {}; for (const k of Object.keys(sum)) next[k] = sum[k] / (n[k] + lam);
      rows.forEach((row, i) => { const k = key(row); if (k == null) return; r[i] += (E[k] || 0) - next[k]; });
      eff[gi] = next;
    });
  }
  return eff;
}
// the same player's shrunk average over the baseline alone (no opponent, no teammates): what his raw numbers
// say on the same scale, so oe - naive is how much his context helped (-) or hurt (+) him a play
function naive(rows, resid, key, lam) {
  const s = {}, n = {};
  rows.forEach((row, i) => { const k = key(row); if (k == null) return; s[k] = (s[k] || 0) + resid[i]; n[k] = (n[k] || 0) + 1; });
  return Object.fromEntries(Object.keys(s).map(k => [k, s[k] / (n[k] + lam)]));
}

// players: { 'team|key': { team, key, rush: {n, y, x, oe, nv}, drop: {n, v, x, oe, nv}, tgt: {n, v, x, oe, nv}, cmp: {n, c, x, oe, nv} } }
// n plays, the actual total and the baseline's total (x), oe the ridge player effect a play, nv the raw-only one
export function overExpected(events, c = OE) {
  const P = {}, at = (team, key) => (P[team + '|' + key] ||= { team, key });
  const pk = e => e.team + '|' + e.actor, tk = e => e.target ? e.team + '|' + e.target : null;
  const capY = y => Math.max(c.cap[0], Math.min(c.cap[1], y));
  // rushing
  const rush = events.filter(e => e.kind === 'rush' && e.actor);
  if (rush.length) {
    const val = e => capY(e.y), b = baseline(rush, sit, val), res = rush.map(e => val(e) - b(e));
    const [pl] = ridge(rush, res, [[pk, c.ridge.player], [e => e.def, c.ridge.def]], c.iters);
    rush.forEach((e, i) => { const s = (at(e.team, e.actor).rush ||= { n: 0, y: 0, x: 0 }); s.n++; s.y += val(e); s.x += b(e); });
    const nv = naive(rush, res, pk, c.ridge.player);
    for (const [k, v] of Object.entries(pl)) if (P[k]?.rush) { P[k].rush.oe = v; P[k].rush.nv = nv[k]; }
  }
  // dropbacks: ANY/A value
  const drop = events.filter(e => e.kind === 'drop' && e.actor);
  if (drop.length) {
    const val = e => e.y + (e.td ? c.td : 0) + (e.int ? c.int : 0), b = baseline(drop, sit, val), res = drop.map(e => val(e) - b(e));
    const [pl, tg] = ridge(drop, res, [[pk, c.ridge.player], [tk, c.ridge.target], [e => e.def, c.ridge.def]], c.iters);
    for (const e of drop) {
      const s = (at(e.team, e.actor).drop ||= { n: 0, v: 0, x: 0 }); s.n++; s.v += val(e); s.x += b(e);
      if (e.target) { const t = (at(e.team, e.target).tgt ||= { n: 0, v: 0, x: 0 }); t.n++; t.v += val(e); t.x += b(e); }
    }
    const nv = naive(drop, res, pk, c.ridge.player), nt = naive(drop, res, tk, c.ridge.target);
    for (const [k, v] of Object.entries(pl)) if (P[k]?.drop) { P[k].drop.oe = v; P[k].drop.nv = nv[k]; }
    for (const [k, v] of Object.entries(tg)) if (P[k]?.tgt) { P[k].tgt.oe = v; P[k].tgt.nv = nt[k]; }
  }
  // completion over expected: aimed throws (sacks out), by situation and air yards where known
  const att = drop.filter(e => !e.sack);
  if (att.length) {
    const key = e => sit(e) + '|' + (e.air != null ? airB(e.air) : e.depth || 'u'), val = e => (e.comp ? 1 : 0), b = baseline(att, key, val, 20), res = att.map(e => val(e) - b(e));
    const [pl] = ridge(att, res, [[pk, c.ridge.player], [tk, c.ridge.target], [e => e.def, c.ridge.def]], c.iters);
    for (const e of att) {
      const s = (at(e.team, e.actor).cmp ||= { n: 0, c: 0, x: 0 }); s.n++; s.c += val(e); s.x += b(e);
    }
    const nv = naive(att, res, pk, c.ridge.player);
    for (const [k, v] of Object.entries(pl)) if (P[k]?.cmp) { P[k].cmp.oe = v; P[k].cmp.nv = nv[k]; }
  }
  return P;
}

// the FV term (FV_OE in fetch_cfb.mjs): players carry g and oe = { season: line from overExpected }. Per metric and
// season, dz = (oe - nv) / SD of oe among the position's qualifiers (c.min plays); seasons blend by weights[season]
// x plays; oeZ = sum of c.k[g][metric] x dz, capped at ±c.cap. Sets p.oeDz { metric: dz } and p.oeZ.
export function oeContext(players, c, weights) {
  for (const [g, ks] of Object.entries(c.k)) {
    const grp = players.filter(p => p.g === g && p.oe), seasons = [...new Set(grp.flatMap(p => Object.keys(p.oe)))];
    for (const f of Object.keys(ks)) for (const sn of seasons) {
      const ok = s => s && s.n >= c.min[f] && s.oe != null && s.nv != null;
      const xs = grp.map(p => p.oe[sn]?.[f]).filter(ok).map(s => s.oe);
      if (xs.length < 10) continue;
      const m = xs.reduce((a, b) => a + b, 0) / xs.length, sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length) || 1;
      for (const p of grp) { const s = p.oe[sn]?.[f]; if (ok(s)) s.dz = (s.oe - s.nv) / sd; }
    }
    for (const p of grp) {
      let z = 0;
      for (const [f, k] of Object.entries(ks)) {
        let num = 0, w = 0;
        for (const [sn, a] of Object.entries(p.oe)) { const s = a[f]; if (s?.dz == null) continue; const x = (weights[sn] || 0) * s.n; num += x * s.dz; w += x; }
        if (w) { (p.oeDz ||= {})[f] = num / w; z += k * num / w; }
      }
      if (p.oeDz) p.oeZ = Math.max(-c.cap, Math.min(c.cap, z));
    }
  }
}
