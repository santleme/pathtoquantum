// Copia em tempo de build os artefatos da corrida servida e o mundo — a FONTE continua
// sendo viewer/*.json e data/world_data.json no repo; public/data/ é artefato gerado.
import { copyFileSync, mkdirSync } from 'node:fs';

mkdirSync(new URL('../public/data/served/', import.meta.url), { recursive: true });
for (const f of ['frames.json', 'chronicle.json', 'scoreboard.json']) {
  copyFileSync(new URL(`../../viewer/${f}`, import.meta.url), new URL(`../public/data/served/${f}`, import.meta.url));
}
copyFileSync(new URL('../../data/world_data.json', import.meta.url), new URL('../public/data/world_data.json', import.meta.url));
console.log('sync:data ok (viewer/*.json + data/world_data.json → public/data/)');
