// F6 — VIS-07 (regressão ?compare=/?forge=) e VIS-12 (artefato parcial da forja).
// Fixtures mínimas fiéis aos formatos reais que o legado lia (forge-v1.json,
// final_evaluation.json, run_log.jsonl) — a sumarização é porte 1:1 do legado.
import { describe, expect, it } from 'vitest';
import type { Frame } from '../src/contracts';
import {
  compareHtml,
  compareRuns,
  forgeHtml,
  parseRunLog,
  resolveModeDir,
  summarizeForge,
} from '../src/modes';

const company = (name: string, cash: number, stage: number, alive = true) => ({
  id: name.length,
  name,
  archetype: 'mineradora',
  color: '#111111',
  hq: 'Lima',
  alive,
  cash,
  stage,
  territory: [],
  facilities: [],
  stocks: {},
});
const frame = (tick: number, companies: ReturnType<typeof company>[]): Frame => ({
  tick,
  date: '2030-01',
  prices: {},
  companies: companies as Frame['companies'],
  deposits: [],
});

describe('resolveModeDir (trava do legado)', () => {
  it('ausente → null; presente → dir sem barra final', () => {
    expect(resolveModeDir('', 'compare')).toBeNull();
    expect(resolveModeDir('?compare=results/a/', 'compare')).toBe('results/a');
    expect(resolveModeDir('?forge=results/forge-v1', 'forge')).toBe('results/forge-v1');
  });
  it('".." é rejeitado (modo não liga)', () => {
    expect(resolveModeDir('?compare=../etc', 'compare')).toBeNull();
    expect(resolveModeDir('?forge=a/../../b', 'forge')).toBeNull();
  });
});

describe('compareRuns — último frame, empresa por empresa (nome)', () => {
  const A = [frame(0, [company('Alfa', 10e6, 0)]), frame(120, [company('Alfa', 50e6, 4), company('Beta', 20e6, 2)])];
  const B = [frame(120, [company('Alfa', 65e6, 4), company('Gama', 5e6, 1, false)])];

  it('união de nomes ordenada; quem falta num lado vira null e delta null', () => {
    const cmp = compareRuns(A, B);
    expect(cmp.rows.map((r) => r.name)).toEqual(['Alfa', 'Beta', 'Gama']);
    const [alfa, beta, gama] = cmp.rows;
    expect(alfa).toMatchObject({ cashA: 50e6, cashB: 65e6, delta: 15e6, stageA: 4, stageB: 4 });
    expect(beta.cashB).toBeNull();
    expect(beta.delta).toBeNull();
    expect(gama.cashA).toBeNull();
    expect(gama.aliveB).toBe(false);
    expect(cmp.totalA).toBe(70e6);
    expect(cmp.totalB).toBe(70e6);
  });

  it('HTML mostra totais, Δ sinalizado e falida em texto', () => {
    const html = compareHtml(compareRuns(A, B), 'results/b');
    expect(html).toContain('segunda corrida: results/b');
    expect(html).toContain('+US$ 15,0M');
    expect(html).toContain('† falida');
    expect(html).toContain('elo: dispositivos → dispositivos');
  });

  it('frames vazios não quebram (VIS-12)', () => {
    const cmp = compareRuns([], []);
    expect(cmp.rows).toEqual([]);
    expect(compareHtml(cmp, 'x')).toContain('US$ 0,0M → US$ 0,0M');
  });
});

// Fixture fiel ao formato real da forja v1 (valores da corrida V8 registrada).
const FORGE_V1 = {
  champion: { hash: '038395fa93a1', S1: 0.4797, S2: 0.5175 },
  seed_result: { hash: 'seedhash', S1: 0.44, S2: 0.49 },
  verdict: 'FORGE-V1: REPROVADO/AJUSTAR',
  iterations_completed: 300,
  mutator: 'multi-rota',
  counts: { accepted: 4, rejected_llm: 295, rejected_guard: 0, error: 1, duplicate: 0 },
  mutator_stats: { calls: { nvidia: 300, groq: 295, gemini: 40 }, salvamentos: 4 },
};
const FINAL_EVAL = {
  tournament_champion: 'prog:deadbeef',
  mean_S: { forge_champion: 0.46, seed: 0.44, tournament_champion: 0.5153 },
  delta_vs_tournament: { mean: -0.0553, ci95: [-0.0998, -0.0112] },
  delta_vs_seed: { mean: 0.0197, ci95: [-0.01, 0.05] },
};
const RUN_LOG = [
  '{"iteration": 1, "hash": "h1", "S1": 0.41, "island": "a", "status": "rejected_llm"}',
  '{"iteration": 3, "hash": "h3", "S1": 0.4797, "island": "b", "status": "accepted"}',
  'linha quebrada {',
  '',
  '{"iteration": 7, "hash": "h7", "S1": 0.45, "island": "a", "status": "accepted"}',
].join('\n');

describe('parseRunLog', () => {
  it('ignora linhas vazias e quebradas', () => {
    const entries = parseRunLog(RUN_LOG);
    expect(entries).toHaveLength(3);
    expect(parseRunLog('')).toEqual([]);
    expect(parseRunLog(null)).toEqual([]);
  });
});

describe('summarizeForge + forgeHtml — formato completo', () => {
  const sum = summarizeForge(FORGE_V1, FINAL_EVAL, parseRunLog(RUN_LOG));

  it('campeão com S1/S2, veredito, contagens e mutador', () => {
    expect(sum.champion).toEqual({ hash: '038395fa93a1', S1: 0.4797, S2: 0.5175 });
    expect(sum.verdict).toBe('FORGE-V1: REPROVADO/AJUSTAR');
    expect(sum.iterationsCompleted).toBe(300);
    const html = forgeHtml(sum, 'results/forge-v1');
    expect(html).toContain('prog:038395fa93a1');
    expect(html).toContain('S1 0.4797 · S2 0.5175');
    expect(html).toContain('aceitas <b>4</b>');
    expect(html).toContain('rejeitadas (LLM) <b>295</b>');
    expect(html).toContain('erros <b>1</b>');
  });

  it('avaliação cega com Δ e IC95', () => {
    const html = forgeHtml(sum, 'results/forge-v1');
    expect(html).toContain('campeão do torneio');
    expect(html).toContain('ΔS vs torneio');
    expect(html).toContain('−0.0553');
    expect(html).toContain('IC95 [-0.0998, -0.0112]');
    expect(html).toContain('ΔS vs semente');
  });

  it('stats do mutador: rotas ordenadas por chamadas + chips numéricos', () => {
    const html = forgeHtml(sum, 'x');
    expect(html).toContain('nvidia');
    expect(html).toContain('300 chamadas');
    expect(html.indexOf('nvidia')).toBeLessThan(html.indexOf('groq'));
    expect(html).toContain('salvamentos <b>4</b>');
  });

  it('linha do tempo só com aceitas, na ordem do log', () => {
    expect(sum.timeline.map((t) => t.iteration)).toEqual([3, 7]);
    const html = forgeHtml(sum, 'x');
    expect(html).toContain('#3 · prog:h3');
    expect(html).not.toContain('prog:h1');
  });
});

describe('summarizeForge — artefato parcial (VIS-12, aceitação explícita)', () => {
  it('só final_evaluation: veredito derivado, resto degrada para —', () => {
    const sum = summarizeForge(null, { verdict: 'APROVADO', delta_vs_seed: { mean: 0.1, ci95: [0.02, 0.2] } }, []);
    expect(sum.verdict).toBe('FORGE-V1: APROVADO');
    expect(sum.champion.hash).toBeNull();
    expect(sum.counts).toBeNull();
    const html = forgeHtml(sum, 'results/parcial');
    expect(html).toContain('FORGE-V1: APROVADO');
    expect(html).toContain('S1 — · S2 —');
    expect(html).toContain('Nenhuma iteração aceita no log.');
  });

  it('só forge-v1 mínimo (champion_hash antigo, sem counts/mutator)', () => {
    const sum = summarizeForge({ champion_hash: 'abc123', iterations: 12 }, null, []);
    expect(sum.champion.hash).toBe('abc123');
    expect(sum.iterationsCompleted).toBe(12);
    expect(sum.verdict).toBeNull();
    expect(() => forgeHtml(sum, 'x')).not.toThrow();
  });

  it('nada (null, null, []) não lança e produz sumário vazio', () => {
    const sum = summarizeForge(null, null, []);
    expect(sum.timeline).toEqual([]);
    expect(sum.blind.vsTournament).toBeNull();
    expect(() => forgeHtml(sum, 'x')).not.toThrow();
  });

  it('final_evaluation embutida no forge-v1 é usada quando o arquivo falta', () => {
    const sum = summarizeForge({ final_evaluation: FINAL_EVAL }, null, []);
    expect(sum.blind.vsTournament?.mean).toBe(-0.0553);
  });
});
