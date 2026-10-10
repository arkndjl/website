// Play-by-play player metrics for the College Football ARKBOARD, from CFBD plays (one call a week, kept slim
// in scripts/.cache/cfb/plays<season>w<week>.json). The play text names the ball carrier, passer, target and,
// on defense, the sacker and the hurrier ("#22 I.Mozee rush left for 4 yards", "pass complete ... to #13
// C.Durr Jr.", "QB hurried by #24 D.Foster"); each play carries CFBD's EPA (ppa). Per player:
//   rushing   attempts, EPA per carry, explosive rate (15+ yards), red-zone carries and TDs
//   receiving targets, catches, EPA per target, explosive rate (20+ yard catches per target), red-zone targets/TDs
//   pass rush hurries and sacks, and sacks per pressure (conversion)
//   usage     touches + targets per game, by game, for the breakout trend
// Names are matched to rosters by team, first initial and last name (suffixes dropped).
const SUFFIX = /\b(jr|sr|ii|iii|iv|v)\b\.?/g;
export const pbpKey = name => {
  const s = (name || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(SUFFIX, '').replace(/[^a-z. '-]/g, '').trim();
  const parts = s.split(/[\s.]+/).filter(Boolean);
  if (parts.length < 2) return parts[0] || '';
  return parts[0][0] + '.' + parts.slice(1).join('').replace(/['-]/g, '');
};
const NAME = "(?:#\\d+\\s+)?([A-Z][A-Za-z'.\\-]*(?:\\s(?:[A-Z][A-Za-z'.\\-]*|Jr\\.?|Sr\\.?|II|III|IV))*)";
const RX = {
  rush: new RegExp(`^(?:\\(\\d+:\\d+\\)\\s*)?(?:[A-Za-z -]*?(?:Shotgun|Huddle|Pistol|Formation)\\s+)?${NAME}\\s+(?:run|rush|scramble)`),
  pass: new RegExp(`${NAME}\\s+pass\\s+(complete|incomplete)[^#A-Z]*?to\\s+${NAME}`),
  sack: new RegExp(`${NAME}\\s+sacked.*?\\((?:#\\d+\\s+)?([A-Z][A-Za-z'.\\-]+(?:\\s[A-Z][A-Za-z'.\\-]+)*)`),
  hurry: new RegExp(`hurried by\\s+${NAME}`),
};
export function pbpPlayers(plays) {
  const P = {};
  const get = (team, name) => { const k = team + '|' + pbpKey(name); return (P[k] ||= { team, key: pbpKey(name), name: name.trim(), car: 0, ry: 0, rEpa: 0, rExp: 0, rzCar: 0, rTd: 0,
    tgt: 0, rec: 0, recY: 0, cEpa: 0, cExp: 0, rzTgt: 0, cTd: 0, hur: 0, sk: 0, games: {} }); };
  for (const p of plays) {
    const x = (p.x || '').replace(/\s+/g, ' '), t = p.t || '', epa = typeof p.ppa === 'number' ? p.ppa : 0, rz = p.ytg != null && p.ytg <= 20, td = /Touchdown/.test(t);
    if (/^Rush|Rushing Touchdown/.test(t)) {
      const m = RX.rush.exec(x); if (!m) continue;
      const a = get(p.o, m[1]); a.car++; a.ry += p.y || 0; a.rEpa += epa; if ((p.y || 0) >= 15) a.rExp++; if (rz) a.rzCar++; if (td) a.rTd++;
      a.games[p.g] = (a.games[p.g] || 0) + 1;
    } else if (/^Pass (Reception|Incompletion)|Passing Touchdown/.test(t)) {
      const m = RX.pass.exec(x); if (!m) continue;
      const a = get(p.o, m[3]); a.tgt++; a.cEpa += epa; if (rz) a.rzTgt++;
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
