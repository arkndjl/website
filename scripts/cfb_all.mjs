// The College Football board's player file, in two parts so neither nears Cloudflare's 25 MiB per-file limit and
// phones parse only what the table needs:
//   static/data/cfb-all.json     {asof, dk, cols, rows}: every column the table, filters, ARKLIST and GFX read
//   static/data/cfb-detail.json  {asof, dk, cols: DETAIL_COLS, rows}: the scouting-report columns, same row order,
//                                fetched by assets/js/cfb.js when a dropdown or player card first opens
// dk (a hash of the detail rows) ties the two together; a reader merges only when both carry the same dk.
// Scripts read and write the board through readCfbAll / writeCfbAll (Python: scripts/cfb_all.py), which see one
// merged {asof, cols, rows} as the single file used to be.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const DETAIL_COLS = ['report', 'parts', 'fvd', 'mk'];
export const cfbAllPath = (root = ROOT) => path.join(root, 'static', 'data', 'cfb-all.json');
export const cfbDetailPath = (root = ROOT) => path.join(root, 'static', 'data', 'cfb-detail.json');

// the merged board {asof, cols, rows} (null when there is no file); a detail file that doesn't match is left off
export function readCfbAll(root = ROOT) {
  const f = cfbAllPath(root); if (!fs.existsSync(f)) return null;
  const A = JSON.parse(fs.readFileSync(f, 'utf8')), g = cfbDetailPath(root);
  const D = fs.existsSync(g) ? JSON.parse(fs.readFileSync(g, 'utf8')) : null;
  delete A.dk;
  if (D && D.rows.length === A.rows.length && D.dk != null) {
    const keep = D.cols.map((c, j) => [c, j]).filter(([c]) => !A.cols.includes(c));
    A.cols = [...A.cols, ...keep.map(([c]) => c)];
    A.rows = A.rows.map((r, i) => [...r, ...keep.map(([, j]) => D.rows[i][j] ?? null)]);
  }
  return A;
}

// write a merged board as the two files; returns the byte size of each
export function writeCfbAll(A, root = ROOT) {
  const ci = Object.fromEntries(A.cols.map((c, i) => [c, i]));
  const dcols = DETAIL_COLS.filter(c => c in ci), core = A.cols.filter(c => !dcols.includes(c));
  const drows = A.rows.map(r => dcols.map(c => r[ci[c]] ?? null));
  const dk = crypto.createHash('sha1').update(JSON.stringify(drows)).digest('hex').slice(0, 12);
  const extra = Object.fromEntries(Object.entries(A).filter(([k]) => !['asof', 'dk', 'cols', 'rows'].includes(k)));
  const coreBody = JSON.stringify({ asof: A.asof ?? null, dk, ...extra, cols: core, rows: A.rows.map(r => core.map(c => r[ci[c]] ?? null)) });
  const detailBody = JSON.stringify({ asof: A.asof ?? null, dk, cols: dcols, rows: drows });
  fs.mkdirSync(path.dirname(cfbAllPath(root)), { recursive: true });
  // detail first: a reader between the two writes sees a dk mismatch and skips the reports, never the wrong ones
  fs.writeFileSync(cfbDetailPath(root), detailBody);
  fs.writeFileSync(cfbAllPath(root), coreBody);
  return { core: Buffer.byteLength(coreBody), detail: Buffer.byteLength(detailBody) };
}

// node scripts/cfb_all.mjs --split: rewrite the current file(s) in the split form
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]) && process.argv.includes('--split')) {
  const s = writeCfbAll(readCfbAll());
  console.log(`cfb-all ${(s.core / 2 ** 20).toFixed(1)} MiB, cfb-detail ${(s.detail / 2 ** 20).toFixed(1)} MiB`);
}
