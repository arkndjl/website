// The NFL draft positions (nflverse draft_picks.csv `position`) a college position group's draftee can carry, for
// every harness that joins a college player to his NFL career by name. nflverse lists most edge rushers as LB (Will
// Anderson Jr., Zack Baun, Jermaine Johnson: 138 LB picks 2020-25 against 16 OLB) and some as DT (DeMarvin Leal);
// before Oct 21 2026 the EDGE list left both out, so 2019-22's drafted EDGEs read as undrafted, 0 AV. Converts
// count too (a TE drafted as a guard).
export const NFLPOS = { QB: ['QB'], RB: ['RB', 'FB'], WR: ['WR'], TE: ['TE', 'OL', 'T', 'G'], EDGE: ['DE', 'OLB', 'EDGE', 'DL', 'LB', 'DT'],
  DL: ['DT', 'DE', 'DL', 'NT'], LB: ['LB', 'ILB', 'OLB', 'MLB', 'DE'] };
// a board position's family, to keep name joins inside it: the front seven together (EDGE, DL and LB trade labels)
export const famOf = pos => /^(QB)/.test(pos) ? 'QB' : /^(RB|FB|HB)/.test(pos) ? 'RB' : /^WR/.test(pos) ? 'WR' : /^TE/.test(pos) ? 'TE'
  : /^(EDGE|DE|DL|DT|NT|LB|ILB|OLB|MLB)/.test(pos) ? 'F7' : /^(OT|OG|OL|IOL|C|G|T)/.test(pos) ? 'OL' : 'DB';
