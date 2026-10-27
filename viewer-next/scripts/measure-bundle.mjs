// Mede o portão de bundle da ADR-001 §8 sobre o dist/ real:
// app (JS+CSS+HTML, sem geografia) ≤ 180 KB gzip · geografia ≤ 200 KB (bruto e gzip).
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';

const dist = new URL('../dist/', import.meta.url).pathname;
if (!existsSync(dist)) { console.error('dist/ não existe — rode npm run build antes'); process.exit(1); }
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    return e.isDirectory() ? walk(p) : [p];
  });
}
let appGzip = 0, geoRaw = 0, geoGzip = 0;
for (const f of walk(dist)) {
  const raw = readFileSync(f);
  const gz = gzipSync(raw, { level: 9 }).length;
  const isGeo = f.includes('/geo/');
  console.log(`${f.replace(dist, '')}\traw ${raw.length}\tgzip ${gz}${isGeo ? '\t[geo]' : ''}`);
  if (isGeo) { geoRaw += statSync(f).size; geoGzip += gz; } else if (!f.includes('/data/')) appGzip += gz;
}
console.log(`\nAPP gzip (sem geo/dados): ${appGzip} B = ${(appGzip / 1024).toFixed(1)} KB → teto 180 KB: ${appGzip <= 180 * 1024 ? 'PASSA' : 'REPROVA'}`);
console.log(`GEO: raw ${geoRaw} B = ${(geoRaw / 1024).toFixed(1)} KB · gzip ${geoGzip} B = ${(geoGzip / 1024).toFixed(1)} KB → teto 200 KB: ${geoRaw <= 200 * 1024 && geoGzip <= 200 * 1024 ? 'PASSA' : 'REPROVA'}`);
