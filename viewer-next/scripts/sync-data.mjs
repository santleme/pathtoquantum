// Copia em tempo de build os artefatos da corrida servida e o mundo — a FONTE continua
// sendo data/served/*.json e data/world_data.json no repo; public/data/ é artefato gerado.
// (Até a aposentadoria do viewer legado, a corrida servida morava em viewer/*.json.)
import { copyFileSync, mkdirSync } from 'node:fs';

mkdirSync(new URL('../public/data/served/', import.meta.url), { recursive: true });
for (const f of ['frames.json', 'chronicle.json', 'scoreboard.json']) {
  copyFileSync(new URL(`../../data/served/${f}`, import.meta.url), new URL(`../public/data/served/${f}`, import.meta.url));
}
copyFileSync(new URL('../../data/world_data.json', import.meta.url), new URL('../public/data/world_data.json', import.meta.url));
console.log('sync:data ok (data/served/*.json + data/world_data.json → public/data/)');
