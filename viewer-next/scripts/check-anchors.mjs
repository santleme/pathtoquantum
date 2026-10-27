// Âncoras da SPEC-VISUAL-WOW §8.2 para as fatias F2 (VIS-03/04), F3 (VIS-08) e
// F4 (VIS-06): lê os JSONs servidos e confere contagem de kinds, os 119 itens
// narrativos do frame final, o lote de novos do avanço 0→12, a ordem/caixa/elos
// do placar final contra scoreboard.json e os primeiros por elo da cadeia
// (chain_link), o progresso final por empresa e o contexto de mercado. Sai com
// código != 0 se alguma âncora divergir.
// Uso: node scripts/check-anchors.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frames = JSON.parse(readFileSync(join(here, '../../viewer/frames.json'), 'utf8'));
const scoreboard = JSON.parse(readFileSync(join(here, '../../viewer/scoreboard.json'), 'utf8'));
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

// --- Âncoras F3 (VIS-08): placar do frame final × scoreboard.json ---
const fmt = (v) => `US$ ${(v / 1e6).toFixed(1).replace('.', ',')}M`;
const finalFrame = frames.frames[frames.frames.length - 1];
const prevFrame = frames.frames[frames.frames.length - 2];
const ranked = [...finalFrame.companies].sort((a, b) => b.cash - a.cash);
const prevCash = new Map(prevFrame.companies.map((c) => [c.id, c.cash]));
const anchorsF3 = [
  ['placar: ordem = scoreboard.json', JSON.stringify(ranked.map((c) => c.name)), JSON.stringify(scoreboard.map((s) => s.name))],
  ['placar: caixa bate com scoreboard (todas)', ranked.every((c) => Math.abs(c.cash - scoreboard.find((s) => s.name === c.name).cash) < 0.01), true],
  ['placar 1º: Vetor Sul', `${ranked[0].name} ${fmt(ranked[0].cash)}`, 'Vetor Sul US$ 273,0M'],
  ['placar 2º: Ferra Brasil', `${ranked[1].name} ${fmt(ranked[1].cash)}`, 'Ferra Brasil US$ 70,2M'],
  ['placar 3º: Cuprum Andes', `${ranked[2].name} ${fmt(ranked[2].cash)}`, 'Cuprum Andes US$ 60,2M'],
  ['placar 8º: Órbita Systems', `${ranked[7].name} ${fmt(ranked[7].cash)}`, 'Órbita Systems US$ 15,9M'],
  ['segmentos de elo (stage) na ordem do placar', JSON.stringify(ranked.map((c) => c.stage)), JSON.stringify([4, 2, 4, 0, 2, 0, 4, 4])],
  ['Δ Vetor Sul no frame final', fmt(ranked[0].cash - prevCash.get(ranked[0].id)), 'US$ 32,9M'],
  ['Δ PetroPlata negativo', ranked.find((c) => c.name === 'PetroPlata').cash - prevCash.get(ranked.find((c) => c.name === 'PetroPlata').id) < 0, true],
];

// --- Âncoras F4 (VIS-06): barra/vista da cadeia ---
// Derivação independente da do viewer: o elo de cada chain_link sai do texto
// do evento (o motor nomeia o elo dominado); "primeiro" = menor tick por elo.
const STAGE_NAMES = ['extração', 'refino', 'componentes', 'dispositivos', 'supercomputador'];
const firstsByStage = (upToTick) => {
  const out = [null, null, null, null, null];
  for (const e of ch) {
    if (e.kind !== 'chain_link' || e.tick > upToTick) continue;
    const idx = STAGE_NAMES.findIndex((n) => (e.text ?? '').toLowerCase().includes(n));
    if (idx < 0) continue;
    if (!out[idx] || e.tick < out[idx].tick) out[idx] = { company: e.company, tick: e.tick };
  }
  return out;
};
const f120 = firstsByStage(120);
const f0 = firstsByStage(0);
const stageByName = Object.fromEntries(finalFrame.companies.map((c) => [c.name, c.stage]));
const orbita = finalFrame.companies.find((c) => c.name === 'Órbita Systems');
const anchorsF4 = [
  ['cadeia tick 120: elos 1–4 dominados pela Órbita (ticks 1,2,5,8)',
    JSON.stringify(f120.slice(0, 4)),
    JSON.stringify([1, 2, 5, 8].map((tick) => ({ company: 'Órbita Systems', tick })))],
  ['cadeia tick 120: elo 5 (SUPERCOMPUTADOR) aberto', f120[4], null],
  ['cadeia tick 0: nenhum elo dominado', JSON.stringify(f0), JSON.stringify([null, null, null, null, null])],
  ['progresso final (stage/5): Vetor/Cuprum/Nexo/Órbita = 4', [stageByName['Vetor Sul'], stageByName['Cuprum Andes'], stageByName['Nexo Indústrias'], stageByName['Órbita Systems']].join(','), '4,4,4,4'],
  ['progresso final (stage/5): Ferra/PetroPlata = 2', [stageByName['Ferra Brasil'], stageByName['PetroPlata']].join(','), '2,2'],
  ['progresso final (stage/5): Lítio Austral/Andina Prime = 0', [stageByName['Lítio Austral'], stageByName['Andina Prime']].join(','), '0,0'],
  ['mercado tick 120: preço do supercomputador (constante, como está)', finalFrame.prices.supercomputer, 1200000],
  ['mercado tick 120: preço do device (constante, como está)', finalFrame.prices.device, 9500],
  ['stocks Órbita: component > 0 com stage 4', orbita.stocks.component > 0 && orbita.stage === 4, true],
  ['stocks: empresas sem stocks = objeto vazio, não erro',
    ['Lítio Austral', 'Andina Prime'].every((n) => Object.keys(finalFrame.companies.find((c) => c.name === n).stocks ?? {}).length === 0), true],
];

let fail = 0;
console.log('kind counts:', JSON.stringify(counts));
for (const [name, got, want] of [...anchors, ...anchorsF3, ...anchorsF4]) {
  const ok = got === want;
  if (!ok) fail++;
  console.log(`${ok ? 'OK ' : 'FAIL'} ${name}: ${got} (esperado ${want})`);
}
if (fail) {
  console.error(`\n${fail} âncora(s) divergem — defeito da fatia, não do script (SPEC §8.2).`);
  process.exit(1);
}
console.log('\nTodas as âncoras F2+F3+F4 conferem.');
