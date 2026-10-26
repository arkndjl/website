// Player names across sources, every sport: the Node twin of scripts/names.py (same rules, same alias file,
// data/name_aliases.json). Keep the two in step: `node scripts/names.mjs --test` and `python3 scripts/names.py --test`
// run the same cases, and the parity check in scripts/names.py compares their keys on every board name.
//   key(name)       the exact key: accents, case, periods, apostrophes, hyphens, spaced initials, suffixes (Jr., III)
//                   folded, then the hand-kept aliases applied (Neo Avdalas = Neoklis Avdalas)
//   compact(name)   the key without spaces (the old fetch_cfb.mjs norm() shape)
//   strength(a, b)  3 the same key, 2 the same player by the rules (nickname, initials, a joined two-part surname),
//                   1 a one-letter difference or one part of a two-part surname (trust it only with the team), 0 no
//   Matcher         index one source; .find(name, {team, pos, id, crossTeam}) -> [row, how] or [null, null]
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const ALIAS_FILE = path.join(ROOT, 'data', 'name_aliases.json');

const LETTERS = { 'ø': 'o', 'Ø': 'o', 'ł': 'l', 'Ł': 'l', 'đ': 'd', 'Đ': 'd', 'ð': 'd', 'þ': 'th', 'ß': 'ss', 'æ': 'ae', 'Æ': 'ae',
  'œ': 'oe', 'Œ': 'oe', 'ı': 'i', 'ħ': 'h' };
const SUFFIX = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v', 'vi', 'll', 'lll']);   // ll: II typed with lowercase Ls
let DATA = {};
try { DATA = JSON.parse(fs.readFileSync(ALIAS_FILE, 'utf8')); } catch {}
const NICK = DATA.nicknames || [];   // first-name groups: any two names in a group are the same first name
const NICKOF = {};
NICK.forEach((g, i) => g.forEach(n => (NICKOF[n] ||= new Set()).add(i)));

let ALIASES = null;
function aliases() {
  if (!ALIASES) {
    ALIASES = {};
    for (const g of DATA.players || []) {
      const names = Array.isArray(g) ? g : g.names, canon = base(names[0]);
      for (const n of names.slice(1)) ALIASES[base(n)] = canon;
    }
  }
  return ALIASES;
}

const ENT = { amp: '&', apos: "'", quot: '"', lt: '<', gt: '>', nbsp: ' ' };
export function fold(s) {
  s = String(s ?? '').replace(/&(#\d+|#x[0-9a-f]+|[a-z]+);/gi, (m, e) => e[0] === '#'
    ? String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : +e.slice(1)) : ENT[e.toLowerCase()] ?? m);
  s = [...s].map(c => LETTERS[c] ?? c).join('');
  return s.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
}

export function tokens(s) {
  const t = fold(s).replace(/\./g, '. ').replace(/[.'`’‘ʻ]/g, '').replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean);
  const out = []; let run = '';
  for (const w of t) {
    if (w.length === 1) { run += w; continue; }
    if (run) { out.push(run); run = ''; }
    out.push(w);
  }
  if (run) out.push(run);
  while (out.length > 2 && SUFFIX.has(out[out.length - 1])) out.pop();
  if (out.length === 2 && SUFFIX.has(out[1]) && out[1] !== 'v') out.pop();
  return out;
}
const base = s => tokens(s).join(' ');
export function key(s) { const b = base(s); return aliases()[b] ?? b; }
export const compact = s => key(s).replace(/ /g, '');

function oneOff(a, b, least = 6) {
  if (a === b) return true;
  if (Math.min(a.length, b.length) < least || Math.abs(a.length - b.length) > 1) return false;
  if (a.length === b.length) {
    const d = [];
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) d.push(i);
    return d.length === 1 || (d.length === 2 && d[1] === d[0] + 1 && a[d[0]] === b[d[1]] && a[d[1]] === b[d[0]]);
  }
  if (a.length > b.length) [a, b] = [b, a];
  let i = 0;
  while (i < a.length && a[i] === b[i]) i++;
  return a.slice(i) === b.slice(i + 1);
}

export function firstFits(f, g) {
  if (f === g) return 2;
  const f0 = f.split(' ').filter(Boolean), g0 = g.split(' ').filter(Boolean);
  if (!f0.length || !g0.length) return 0;
  const a = f0[0], b = g0[0];
  if (a === b) return 2;
  if ([...(NICKOF[a] || [])].some(i => NICKOF[b]?.has(i))) return 2;
  const [s, l] = a.length <= b.length ? [a, b] : [b, a];
  if (s.length >= 5 && l.startsWith(s)) return 2;
  const ia = f0.map(w => w[0]).join(''), ib = g0.map(w => w[0]).join('');
  if (a.length <= 3 && b.length <= 3 && (a === ib || b === ia)) return 2;
  if (a[0] === b[0] && oneOff(a, b, 4)) return 1;   // Jalen / Jaylen; Devin / Kevin are two names
  if (s.length >= 3 && l.startsWith(s)) return 1;
  if (s.length === 1 && l.startsWith(s)) return 1;   // a lone initial (tennis feeds' "Sinner J."): only with the team
  if (f0.length === 1 && a.length >= 2 && a.length <= 3 && a === ib) return 1;   // initials of two first names (J. M. = Juan Manuel)
  if (g0.length === 1 && b.length >= 2 && b.length <= 3 && b === ia) return 1;
  return 0;
}

export function strength(a, b) {
  const ka = key(a), kb = key(b);
  if (!ka || !kb) return 0;
  if (ka === kb || ka.replace(/ /g, '') === kb.replace(/ /g, '')) return 3;
  const ta = ka.split(' '), tb = kb.split(' ');
  if (ta.length < 2 || tb.length < 2) return 0;
  const f = ta.slice(0, -1).join(' '), l = ta[ta.length - 1], g = tb.slice(0, -1).join(' '), m = tb[tb.length - 1];
  if (l === m) return firstFits(f, g);
  if (ta.length === 3 && tb.length === 3 && ta.slice(1).join(' ') === tb.slice(1).join(' ')) return firstFits(ta[0], tb[0]);
  if (ta.length === 3 && ta[1] + ta[2] === m && ta[0] === g) return 3;
  if (tb.length === 3 && tb[1] + tb[2] === l && tb[0] === f) return 3;
  if (Math.min(l.length, m.length) >= 6 && oneOff(l, m)) return Math.min(1, firstFits(f, g));
  if ((ta.length === 3 && ta[1] === m && ta[0] === g) || (tb.length === 3 && tb[1] === l && tb[0] === f)) return 1;
  return 0;
}
export const same = (a, b) => strength(a, b) >= 2;

const TEAM_ALIAS = { uconn: 'connecticut', olemiss: 'mississippi', lsu: 'louisianastate', usc: 'southerncalifornia',
  byu: 'brighamyoung', smu: 'southernmethodist', tcu: 'texaschristian', ucf: 'centralflorida', unlv: 'nevadalasvegas',
  vcu: 'virginiacommonwealth', unc: 'northcarolina', uva: 'virginia', pitt: 'pittsburgh', umass: 'massachusetts',
  utep: 'texaselpaso', utsa: 'texassanantonio', fiu: 'floridainternational', fau: 'floridaatlantic', miamifl: 'miami',
  miamiflorida: 'miami', stjohns: 'saintjohns', stmarys: 'saintmarys', ncstate: 'northcarolinastate', gatech: 'georgiatech',
  washst: 'washingtonstate', mizzou: 'missouri', cal: 'california', ucberkeley: 'california', texasam: 'texasam', tamu: 'texasam',
  unm: 'newmexico', uh: 'houston', etsu: 'easttennesseestate', fgcu: 'floridagulfcoast', liu: 'longisland', uab: 'alabamabirmingham',
  ucsb: 'ucsantabarbara' };
export function teamKey(s) {
  let t = fold(s).replace(/&/g, '').replace(/'/g, '');
  t = t.replace(/^st\.?\s/, 'saint ');
  t = t.replace(/^s\.?\s/, 'south ').replace(/^n\.?\s/, 'north ').replace(/\bst\b\.?/g, 'state');
  t = t.replace(/\buniv(ersity)?\b|\bof\b|\bthe\b|\bu\b/g, ' ').replace(/[^a-z0-9]/g, '');
  return TEAM_ALIAS[t] ?? t;
}
export const sameTeam = (a, b) => !!a && !!b && teamKey(a) === teamKey(b);

const POSGRP = { QB: 'QB', RB: 'RB', FB: 'RB', HB: 'RB', WR: 'WR', SWR: 'WR', TE: 'TE', OL: 'OL', OT: 'OL', T: 'OL', G: 'OL', OG: 'OL',
  C: 'OL', IOL: 'OL', LT: 'OL', RT: 'OL', LG: 'OL', RG: 'OL', DL: 'DL', DT: 'DL', NT: 'DL', DE: 'DL', EDGE: 'DL', ED: 'DL', IDL: 'DL',
  DI: 'DL', LB: 'LB', ILB: 'LB', OLB: 'LB', MLB: 'LB', WLB: 'LB', SLB: 'LB', CB: 'DB', NCB: 'DB', S: 'DB', SAF: 'DB', FS: 'DB',
  SS: 'DB', DB: 'DB', K: 'K', P: 'K', PK: 'K', LS: 'K', ATH: null };
const NEAR = new Set(['DL|LB', 'LB|DB', 'RB|WR', 'WR|DB', 'TE|WR', 'TE|OL', 'DL|OL', 'RB|DB', 'QB|WR'].flatMap(p => [p, p.split('|').reverse().join('|')]));
export function posFits(a, b, sport = 'football') {
  if (!a || !b || sport !== 'football') return true;
  const x = POSGRP[String(a).toUpperCase().split('/')[0]], y = POSGRP[String(b).toUpperCase().split('/')[0]];
  if (x == null || y == null || x === y) return true;
  return NEAR.has(`${x}|${y}`);
}

// name / team / pos / id: field names or functions of the row; teamEq(wanted, row's team) defaults to sameTeam
export class Matcher {
  constructor(rows, { name = 'name', team = 'team', pos = 'pos', id = null, sport = 'football', teamEq = sameTeam } = {}) {
    this.rows = [...rows]; this.f = { name, team, pos, id }; this.sport = sport; this.teamEq = teamEq;
    this.byKey = new Map(); this.byLast = new Map(); this.byId = new Map();
    for (const r of this.rows) {
      const n = this.get(r, 'name');
      if (!n) continue;
      const k = key(n), t = k.split(' ');
      push(this.byKey, k, r);
      if (t[0]) push(this.byLast, t[t.length - 1], r);
      if (t.length === 3) push(this.byLast, t[1], r);   // a two-part surname under its first part too
      const i = this.get(r, 'id');
      if (i != null && i !== '') push(this.byId, String(i), r);
    }
    this.lasts = [...this.byLast.keys()];
  }
  get(r, f) { const k = this.f[f]; return k == null ? null : typeof k === 'function' ? k(r) : r[k]; }
  fit(r, pos) { return !pos || posFits(pos, this.get(r, 'pos'), this.sport); }
  candidates(name, least = 1) {
    const t = key(name).split(' ').filter(Boolean);
    if (!t.length) return [];
    const last = t[t.length - 1];
    let pool = [...(this.byLast.get(last) || [])];
    if (t.length === 3) pool = pool.concat(this.byLast.get(t[1]) || []);
    if (last.length >= 6) for (const l2 of this.lasts) {
      if (l2 !== last && Math.abs(l2.length - last.length) <= 1 && l2[0] === last[0] && oneOff(l2, last)) pool = pool.concat(this.byLast.get(l2));
    }
    return [...new Set(pool)].filter(r => { const s = strength(name, this.get(r, 'name')); return s >= least && s < 3; });
  }
  find(name, { team = null, pos = null, id = null, crossTeam = 'exact' } = {}) {
    if (id != null && id !== '' && this.byId.has(String(id))) {
      const c = this.byId.get(String(id));
      if (c.length === 1) return [c[0], 'id'];
    }
    // a row that carries a different id is another player, whatever the name says
    const ok = r => id == null || id === '' || this.get(r, 'id') == null || this.get(r, 'id') === '' || String(this.get(r, 'id')) === String(id);
    const exact = (this.byKey.get(key(name)) || []).filter(ok);
    const hasTeam = !!team && this.f.team != null;
    if (hasTeam) {
      let c = exact.filter(r => this.teamEq(team, this.get(r, 'team')));
      if (c.length === 1) return [c[0], 'name+team'];
      if (c.length > 1) { c = c.filter(r => this.fit(r, pos)); return c.length === 1 ? [c[0], 'name+team'] : [null, null]; }
      const v = this.candidates(name).filter(r => this.teamEq(team, this.get(r, 'team')) && ok(r));
      if (v.length === 1 && this.fit(v[0], pos)) return [v[0], 'variant+team'];
    }
    if (hasTeam && crossTeam === 'none') return [null, null];
    if (exact.length > 1) {
      const c = pos ? exact.filter(r => this.fit(r, pos)) : [];
      return c.length === 1 ? [c[0], 'name+pos'] : [null, null];
    }
    if (exact.length === 1) return this.fit(exact[0], pos) ? [exact[0], 'name'] : [null, null];
    if (!hasTeam || crossTeam === 'variant') {
      const v = this.candidates(name, 2).filter(ok);
      if (v.length === 1 && this.fit(v[0], pos)) return [v[0], 'variant'];
    }
    return [null, null];
  }
}
function push(m, k, v) { const a = m.get(k); if (a) a.push(v); else m.set(k, [v]); }

// the one row in a list (already one team's) whose name fits: the strongest unique fit, null if none or a tie
export function variant(list, name, nameOf = o => o.name) {
  for (const least of [2, 1]) {
    const hits = (list || []).filter(o => strength(nameOf(o), name) >= least);
    if (hits.length === 1) return hits[0];
    if (hits.length > 1) return null;
  }
  return null;
}

if (process.argv[1] === fileURLToPath(import.meta.url) && process.argv.includes('--test')) {
  const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exit(1); } };
  for (const [a, b] of [['Neo Avdalas', 'Neoklis Avdalas'], ['T.J. Watt', 'TJ Watt'], ['A. J. Brown', 'AJ Brown'], ['Nikola Jokić', 'Nikola Jokic'],
    ['Nikola Joksimović', 'Nikola Joksimovic'], ["D'Andre Swift", 'DAndre Swift'], ['Marvin Harrison Jr.', 'Marvin Harrison'],
    ['Kenneth Walker III', 'Kenneth Walker'], ['Jaxon Smith-Njigba', 'Jaxon Smith Njigba'], ['Luka Dončić', 'Luka Doncic'], ['Brian Blades ll', 'Brian Blades II']])
    ok(key(a) === key(b), [a, b, key(a), key(b)]);
  for (const [a, b] of [['Sammy Brown', 'Samuel Brown'], ['Chris Bell', 'Christopher Bell'], ['Cam Coleman', 'Cameron Coleman'], ['Will Holmes', 'William Holmes'], ['Jaxon Smith-Njigba', 'Jaxon Njigba']])
    ok(same(a, b), [a, b]);
  for (const [a, b] of [['Josh Allen', 'Jordan Allen'], ['Chris Bell', 'Charles Bell'], ['Malik Brown', 'Malachi Brown'], ['AJ Green', 'AJ Greene'], ['Dan Jackson', 'Dante Jackson'], ['Jalen Smith', 'Jaylen Smith']])
    ok(!same(a, b), [a, b]);
  ok(strength('Sylvester Smith-Reed', 'Sylvester Smith') === 1 && strength('Bryce Underwood', 'Bryce Underwod') === 1 && strength('Devin Jackson', 'Devon Jackson') === 1, 'strength 1');
  ok(strength('J. M. Cerundolo', 'Juan Manuel Cerundolo') === 1 && strength('J. Sinner', 'Jannik Sinner') === 1 && strength('J. Sinner', 'Matteo Sinner') === 0, 'initial');
  ok(sameTeam('N. Carolina', 'North Carolina') && sameTeam('UConn', 'Connecticut') && !sameTeam('Michigan', 'Michigan State'), 'teams');
  const m = new Matcher([{ name: 'Josh Allen', team: 'Buffalo' }, { name: 'Josh Allen', team: 'Jacksonville' }, { name: 'Neoklis Avdalas', team: 'Virginia Tech' }]);
  ok(m.find('Josh Allen')[0] === null && m.find('Josh Allen', { team: 'Jacksonville' })[0].team === 'Jacksonville', 'dup names');
  ok(m.find('Neo Avdalas', { team: 'North Carolina' })[0].team === 'Virginia Tech', 'alias');
  if (process.argv.includes('--keys')) {   // parity: print the key of every line on stdin
    const lines = fs.readFileSync(0, 'utf8').split('\n');
    process.stdout.write(lines.map(key).join('\n'));
  } else console.log('names.mjs: ok');
}
