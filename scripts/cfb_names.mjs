// Name variants across sources: PFN, On3, ESPN and CFBD spell the same player differently ("Sammy" / "Samuel", "TJ" /
// "T.J.", "Will" / "William", "Smith-Reed" / "Smith"). The rules live in scripts/names.mjs, shared by every sport; this
// keeps the two helpers scripts/fetch_cfb.mjs and scripts/cfb_teams.mjs use, only to choose among candidates on the
// SAME team, and only when exactly one candidate fits.
import { strength, variant as pick } from './names.mjs';

// could two names on the same team be one player (any fit, a one-letter typo or a shortened surname included)
export const sameName = (a, b) => strength(a, b) >= 1;
// the one candidate in a list that matches by name variant (null if none or more than one)
export const variant = (list, name) => pick(list, name);
