// Copies the pipeline output (repo-root data/deals.json) into web/src/data/
// so the Astro build can import it as a normal module. Runs automatically
// before `dev` and `build` (see package.json predev/prebuild hooks).
import { mkdirSync, copyFileSync, existsSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url)); // web/scripts
const src = join(here, "..", "..", "data", "deals.json"); // repo-root data/deals.json
const destDir = join(here, "..", "src", "data");
const dest = join(destDir, "deals.json");

mkdirSync(destDir, { recursive: true });

if (existsSync(src)) {
  copyFileSync(src, dest);
  console.log(`[sync-data] copied ${src} -> ${dest}`);
} else {
  const empty = { generated_at: null, count: 0, filters: { cuisines: [], areas: [], deal_types: [] }, deals: [] };
  writeFileSync(dest, JSON.stringify(empty, null, 2), "utf-8");
  console.warn(`[sync-data] ${src} missing — wrote empty dataset to ${dest}. Run: python ingest/db.py --export-json`);
}
