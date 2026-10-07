// Name variants across sources: PFN, On3, ESPN and CFBD spell the same player differently ("Sammy" /
// "Samuel", "TJ" / "T.J.", "Mike" / "Michael"). Used by scripts/fetch_cfb.mjs and scripts/cfb_teams.mjs
// only to choose among candidates on the SAME team, and only when exactly one candidate fits.
const fold = s => (s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const flat = s => fold(s).replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, '').replace(/[^a-z0-9]/g, '');
// ---- name variants ---------------------------------------------------------------------------
// Sources spell the same player differently ("Sammy" / "Samuel", "TJ" / "T.J.", "Mike" / "Michael").
// sameName: same last name (suffixes dropped) and compatible first names: equal, a known nickname
// pair, one a 3+ letter prefix of the other (Chris / Christopher), or matching initials.
// Only used to pick among candidates on the SAME team, and only when exactly one candidate fits.
const NICK = [['sam', 'sammy', 'samuel'], ['mike', 'michael', 'mikey'], ['bill', 'billy', 'will', 'william', 'willie', 'liam'],
  ['bob', 'bobby', 'rob', 'robbie', 'robert', 'bert'], ['jim', 'jimmy', 'james', 'jamie'], ['chris', 'christopher', 'kris'],
  ['nick', 'nicholas', 'nicolas', 'nico'], ['matt', 'matthew', 'mathew'], ['tony', 'anthony'], ['joe', 'joey', 'joseph', 'jo'],
  ['dan', 'danny', 'daniel'], ['dave', 'david'], ['steve', 'steven', 'stephen'], ['tom', 'tommy', 'thomas'], ['ben', 'benjamin', 'benny'],
  ['alex', 'alexander', 'alec'], ['andy', 'drew', 'andrew'], ['ed', 'eddie', 'edward', 'eddy'], ['zach', 'zack', 'zachary', 'zachariah'],
  ['jon', 'jonathan', 'john', 'johnny', 'jack'], ['josh', 'joshua'], ['nate', 'nathan', 'nathaniel'], ['greg', 'gregory'], ['jake', 'jacob'],
  ['tim', 'timothy', 'timmy'], ['ken', 'kenny', 'kenneth'], ['cam', 'cameron'], ['jay', 'jaylen', 'jaylon'], ['charlie', 'charles', 'chuck'],
  ['dre', 'andre'], ['rick', 'ricky', 'richard', 'rich'], ['ty', 'tyler', 'tyrone'], ['gabe', 'gabriel'], ['manny', 'emmanuel', 'immanuel'],
  ['abe', 'abraham'], ['isaiah', 'isiah'], ['zay', 'isaiah'], ['nicky', 'nick']];
const NICKOF = {}; NICK.forEach((g, i) => g.forEach(n => (NICKOF[n] ||= new Set()).add(i)));
function nameParts(s) {
  const w = fold(s).replace(/\b(jr|sr|ii|iii|iv|v)\b\.?/g, '')
    .replace(/[^a-z\s.'-]/g, ' ').split(/\s+/).filter(Boolean);
  const last = (w.length > 1 ? w[w.length - 1] : '').replace(/[^a-z]/g, '');
  const first = w.slice(0, -1).join(' ');
  return { first: first.replace(/[^a-z]/g, ''), initials: first.split(/[\s.'-]+/).filter(Boolean).map(x => x[0]).join(''), last };
}
export function sameName(a, b) {
  if (flat(a) === flat(b)) return true;
  const x = nameParts(a), y = nameParts(b);
  if (!x.last || x.last !== y.last || !x.first || !y.first) return false;
  const f = x.first, g = y.first;
  if (f === g) return true;
  if ([...(NICKOF[f] || [])].some(i => NICKOF[g]?.has(i))) return true;
  const [s, l] = f.length <= g.length ? [f, g] : [g, f];
  if (s.length >= 3 && l.startsWith(s)) return true;
  // initials: "TJ" ~ "T.J." ~ "Tj"
  if (f.length <= 3 && g.length <= 3 && (x.initials === y.initials || f === y.initials || g === x.initials)) return true;
  return false;
}
// the one candidate in a list that matches by name variant (null if none or more than one)
export const variant = (list, name) => { const hits = (list || []).filter(o => sameName(o.name, name)); return hits.length === 1 ? hits[0] : null; };

