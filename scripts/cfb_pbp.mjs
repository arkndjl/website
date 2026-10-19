// Play-by-play player metrics for the College Football ARKBOARD, from CFBD plays (one call a week, kept slim
// in scripts/.cache/cfb/plays<season>w<week>.json). The play text names the ball carrier, passer, target and,
// on defense, the sacker and the hurrier ("#22 I.Mozee rush left for 4 yards", "pass complete ... to #13
// C.Durr Jr.", "QB hurried by #24 D.Foster"); each play carries CFBD's EPA (ppa). Per player:
//   rushing   attempts, EPA per carry, explosive rate (15+ yards), red-zone carries and TDs
//   receiving targets, catches, EPA per target, explosive rate (20+ yard catches per target), red-zone targets/TDs
//   pass rush hurries and sacks, and sacks per pressure (conversion)
//   usage     touches + targets per game, by game, for the breakout trend
//   downs     carries + targets and targets alone on standard and passing downs, for the backs' roles (rbRoles)
// Names are matched to rosters by team, first initial and last name (suffixes dropped).
import { key } from './names.mjs';
export const pbpKey = name => {
  const parts = key(name).split(' ').filter(Boolean);   // the shared name key (scripts/names.mjs)
  if (parts.length < 2) return parts[0] || '';
  return parts[0][0] + '.' + parts.slice(1).join('');
};
const NAME = "(?:#\\d+\\s+)?([A-Z][A-Za-z'.\\-]*(?:\\s(?:[A-Z][A-Za-z'.\\-]*|Jr\\.?|Sr\\.?|II|III|IV))*)";
const RX = {
  rush: new RegExp(`^(?:\\(\\d+:\\d+\\)\\s*)?(?:[A-Za-z -]*?(?:Shotgun|Huddle|Pistol|Formation)\\s+)?${NAME}\\s+(?:run|rush|scramble)`),
  pass: new RegExp(`${NAME}\\s+pass\\s+(complete|incomplete)[^#A-Z]*?to\\s+${NAME}`),
  sack: new RegExp(`${NAME}\\s+sacked.*?\\((?:#\\d+\\s+)?([A-Z][A-Za-z'.\\-]+(?:\\s[A-Z][A-Za-z'.\\-]+)*)`),
  hurry: new RegExp(`hurried by\\s+${NAME}`),
};
// passing downs (Football Outsiders / CFBD): 2nd and 8+, 3rd or 4th and 5+; every other down is a standard down
const downOf = p => !(p.dn >= 1 && p.dn <= 4) ? null : (p.dn === 2 && p.ds >= 8) || (p.dn >= 3 && p.ds >= 5) ? 'pd' : 'sd';
export function pbpPlayers(plays) {
  const P = {};
  const get = (team, name) => { const k = team + '|' + pbpKey(name); return (P[k] ||= { team, key: pbpKey(name), name: name.trim(), car: 0, ry: 0, rEpa: 0, rExp: 0, rzCar: 0, rTd: 0,
    tgt: 0, rec: 0, recY: 0, cEpa: 0, cExp: 0, rzTgt: 0, cTd: 0, hur: 0, sk: 0, sdO: 0, pdO: 0, sdT: 0, pdT: 0, games: {} }); };
  for (const p of plays) {
    const x = (p.x || '').replace(/\s+/g, ' '), t = p.t || '', epa = typeof p.ppa === 'number' ? p.ppa : 0, rz = p.ytg != null && p.ytg <= 20, td = /Touchdown/.test(t);
    if (/^Rush|Rushing Touchdown/.test(t)) {
      const m = RX.rush.exec(x); if (!m) continue;
      const a = get(p.o, m[1]); a.car++; a.ry += p.y || 0; a.rEpa += epa; if ((p.y || 0) >= 15) a.rExp++; if (rz) a.rzCar++; if (td) a.rTd++;
      const dn = downOf(p); if (dn) a[dn + 'O']++;
      a.games[p.g] = (a.games[p.g] || 0) + 1;
    } else if (/^Pass (Reception|Incompletion)|Passing Touchdown/.test(t)) {
      const m = RX.pass.exec(x); if (!m) continue;
      const a = get(p.o, m[3]); a.tgt++; a.cEpa += epa; if (rz) a.rzTgt++;
      const dn = downOf(p); if (dn) { a[dn + 'O']++; a[dn + 'T']++; }
      if (m[2] === 'complete') { a.rec++; a.recY += p.y || 0; if ((p.y || 0) >= 20) a.cExp++; if (td) a.cTd++; }
      a.games[p.g] = (a.games[p.g] || 0) + 1;
      const h = RX.hurry.exec(x); if (h) get(p.d, h[1]).hur++;
    } else if (/^Sack/.test(t)) {
      const m = RX.sack.exec(x); if (m) get(p.d, m[2]).sk++;
    }
  }
  return P;
}
// split-half reliability (odd vs even games), Spearman-Brown corrected, of a per-opportunity rate
export function splitHalf(players, num, den, minDen = 20) {
  const xs = [], ys = [];
  for (const a of players) {
    const gs = Object.keys(a._byGame || {}).sort();
    const half = [0, 1].map(par => gs.filter((_, i) => i % 2 === par).reduce((s, g) => { const v = a._byGame[g]; return { n: s.n + num(v), d: s.d + den(v) }; }, { n: 0, d: 0 }));
    if (half[0].d >= minDen / 2 && half[1].d >= minDen / 2) { xs.push(half[0].n / half[0].d); ys.push(half[1].n / half[1].d); }
  }
  const n = xs.length; if (n < 20) return { r: null, n };
  const mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n;
  let sxy = 0, sxx = 0, syy = 0; xs.forEach((x, i) => { sxy += (x - mx) * (ys[i] - my); sxx += (x - mx) ** 2; syy += (ys[i] - my) ** 2; });
  const r = sxy / Math.sqrt(sxx * syy);
  return { r: Math.round(2 * r / (1 + r) * 100) / 100, n };
}
// per-game splits for the reliability test: the same parse, kept by game
export function pbpByGame(plays) {
  const byGame = {};
  for (const p of plays) (byGame[p.g] ||= []).push(p);
  const out = {};
  for (const [g, list] of Object.entries(byGame)) for (const [k, a] of Object.entries(pbpPlayers(list))) ((out[k] ||= { ...a, _byGame: {} })._byGame[g] = a);
  return out;
}

// each offense's scrimmage plays on standard and passing downs (the passing-down share sets how a back's overall
// snap share splits between the two)
export function pbpTeamDowns(plays) {
  const T = {};
  for (const p of plays) {
    if (!/^(Rush|Pass|Sack)|Rushing Touchdown|Passing Touchdown|Interception/.test(p.t || '')) continue;
    const dn = downOf(p); if (dn) (T[p.o] ||= { sd: 0, pd: 0 })[dn]++;
  }
  return T;
}

// Running back roles: early-down, 3rd-down and every-down backs, from estimated snap shares on standard and
// passing downs. No public college data has snaps by down, so they are estimated: the overall snap share (the
// level) is split by how a back's share of his backfield's carries + targets tilts between the two situations.
// Calibrated on the 2024 NFL season (nflverse play-by-play plus participation, which has the true snaps by down;
// 73 backs with 15%+ of their team's snaps):
//   touch share tracks snap share: r .98 on standard downs, .85 on passing downs (passing-down touches are thin
//   and 3rd-down backs are on the field to block, which earns no touch), and the passing-down tilt at r .91;
//   adding the tilt in target share lifts that to .93 (.82 over the first six weeks, a college sample), so
//   snap tilt = .6 x touch tilt + .35 x target tilt - .02, each passing-down share regressed toward the back's
//   standard-down share by 5 opportunities (k)
//   labels from the estimates match labels from the true snaps for 82% of backs (81% over weeks 1-6), and every
//   miss is a neighbour (every-down vs early-down, or a role vs none); none mix up early-down and 3rd-down
// Labels, on the estimated shares (sd standard downs, pd passing downs):
//   every-down  sd >= .50 and pd >= .50: on the field for most snaps whatever the down
//   early-down  sd >= .30 and pd <= sd - .10: a real early-down share that drops 10+ points on passing downs
//   3rd-down    pd >= .30 and pd >= sd + .10: the mirror image
//   otherwise none (a committee or rotational back). A back needs 20+ carries + targets to be labelled
export const RB_ROLE = { k: 5, touch: 0.6, target: 0.35, shift: -0.02, every: 0.5, min: 0.3, gap: 0.1, minOpp: 20 };
export const RB_ROLE_NAME = { every: 'Every Down Back', early: 'Early Down Back', third: '3rd Down Back' };
// backs: [{ id, team, snapShare, sdO, pdO, sdT, pdT }], every back on each team (they make the denominators);
// teamDowns: { team: { sd, pd } }. Returns { id: { role, sd, pd } }, role null for a committee back
export function rbRoles(backs, teamDowns, c = RB_ROLE) {
  const out = {}, byTeam = {};
  for (const b of backs) (byTeam[b.team] ||= []).push(b);
  for (const [team, list] of Object.entries(byTeam)) {
    const sum = f => list.reduce((s, b) => s + (b[f] || 0), 0), tot = { sdO: sum('sdO'), pdO: sum('pdO'), sdT: sum('sdT'), pdT: sum('pdT') };
    const td = teamDowns[team], f = td && td.sd + td.pd ? td.pd / (td.sd + td.pd) : 0.3;
    for (const b of list) {
      if (b.snapShare == null || (b.sdO || 0) + (b.pdO || 0) < c.minOpp || !tot.sdO) { out[b.id] = { role: null, sd: null, pd: null }; continue; }
      const sdSh = b.sdO / tot.sdO, sdTs = tot.sdT ? b.sdT / tot.sdT : sdSh;
      const tilt = (b.pdO + c.k * sdSh) / (tot.pdO + c.k) - sdSh, tTilt = (b.pdT + c.k * sdTs) / (tot.pdT + c.k) - sdSh;
      const d = c.touch * tilt + c.target * tTilt + c.shift;
      const sd = Math.min(1, Math.max(0, b.snapShare - f * d)), pd = Math.min(1, Math.max(0, b.snapShare + (1 - f) * d));
      const role = sd >= c.every && pd >= c.every ? 'every' : sd >= c.min && pd <= sd - c.gap ? 'early' : pd >= c.min && pd >= sd + c.gap ? 'third' : null;
      out[b.id] = { role, sd: Math.round(sd * 100) / 100, pd: Math.round(pd * 100) / 100 };
    }
  }
  return out;
}
