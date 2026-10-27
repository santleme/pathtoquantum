// Gera os assets geográficos embutidos (Natural Earth via world-atlas, domínio público).
// - public/geo/world-110m.json : land-110m (vista-múndi, 1:110m)
// - public/geo/sa-50m.json     : excerto América do Sul de countries-50m, re-topologizado
//   e quantizado (topojson-server) — só os países do recorte jogável atual.
// Proveniência: world-atlas (TopoJSON derivado de Natural Earth). Nada é buscado em runtime.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { feature } from 'topojson-client';
import { topology } from 'topojson-server';

const SA_IDS = new Set([
  '032', // Argentina
  '068', // Bolívia
  '076', // Brasil
  '152', // Chile
  '170', // Colômbia
  '218', // Equador
  '254', // Guiana Francesa
  '328', // Guiana
  '600', // Paraguai
  '604', // Peru
  '740', // Suriname
  '858', // Uruguai
  '862', // Venezuela
  '238', // Ilhas Malvinas/Falkland
]);

mkdirSync(new URL('../public/geo/', import.meta.url), { recursive: true });

const world110 = JSON.parse(readFileSync(new URL('../node_modules/world-atlas/land-110m.json', import.meta.url), 'utf8'));
writeFileSync(new URL('../public/geo/world-110m.json', import.meta.url), JSON.stringify(world110));

const countries50 = JSON.parse(readFileSync(new URL('../node_modules/world-atlas/countries-50m.json', import.meta.url), 'utf8'));
const all = feature(countries50, countries50.objects.countries);
const saFeatures = all.features.filter((f) => SA_IDS.has(String(f.id).padStart(3, '0')));
if (saFeatures.length < 10) throw new Error(`excerto SA suspeito: ${saFeatures.length} países`);
const saTopo = topology({ countries: { type: 'FeatureCollection', features: saFeatures } }, 1e5);
writeFileSync(new URL('../public/geo/sa-50m.json', import.meta.url), JSON.stringify(saTopo));

console.log(`geo: world-110m (${JSON.stringify(world110).length} B) · sa-50m ${saFeatures.length} países (${JSON.stringify(saTopo).length} B)`);
