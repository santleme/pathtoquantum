// Âncoras da SPEC-VISUAL-WOW §8.2 para a fatia F2 (VIS-03/04): lê os JSONs servidos
// e confere contagem de kinds, os 119 itens narrativos do frame final e o lote de
// novos do avanço 0→12. Sai com código != 0 se alguma âncora divergir.
// Uso: node scripts/check-anchors.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frames = JSON.parse(readFileSync(join(here, '../../viewer/frames.json'), 'utf8'));
const ch = frames.chronicle;

const counts = {};
for (const e of ch) counts[e.kind] = (counts[e.kind] ?? 0) + 1;
const narrative = ch.filter((e) => e.kind !== 'flows' && e.text && e.text.trim());
const batch = (from, to) => narrative.filter((e) => e.tick > from && e.tick <= to).length;

const anchors = [
  ['total de eventos', ch.length, 239],
  ['flows (contábil, fora da narrativa)', counts.flows ?? 0, 120],
  ['tool', counts.tool ?? 0, 66],
  ['probe', counts.probe ?? 0, 16],
  ['facility', counts.facility ?? 0, 14],
  ['mine', counts.mine ?? 0, 10],
  ['founding', counts.founding ?? 0, 8],
  ['chain_link (marcos)', counts.chain_link ?? 0, 4],
  ['end', counts.end ?? 0, 1],
  ['itens narrativos tick<=120 (VIS-03)', narrative.filter((e) => e.tick <= 120).length, 119],
  ['itens narrativos vazios', narrative.filter((e) => !e.text.trim()).length, 0],
  ['lote de novos 0->12 (VIS-04)', batch(0, 12), 46],
  ['lote inicial tick<=0 (VIS-04)', narrative.filter((e) => e.tick <= 0).length, 10],
  ['chain_link ticks', JSON.stringify(ch.filter((e) => e.kind === 'chain_link').map((e) => e.tick)), JSON.stringify([1, 2, 5, 8])],
];

let fail = 0;
console.log('kind counts:', JSON.stringify(counts));
for (const [name, got, want] of anchors) {
  const ok = got === want;
  if (!ok) fail++;
  console.log(`${ok ? 'OK ' : 'FAIL'} ${name}: ${got} (esperado ${want})`);
}
if (fail) {
  console.error(`\n${fail} âncora(s) divergem — defeito da fatia, não do script (SPEC §8.2).`);
  process.exit(1);
}
console.log('\nTodas as âncoras F2 conferem.');
