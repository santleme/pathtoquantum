// F6 — VIS-12: varredura de robustez. Corrida degradada (sem prices/stocks,
// crônica parcial, kind desconhecido, stage fora de 0..5, empresa sem campos
// opcionais) atravessa TODOS os renderizadores puros sem exceção — inclusive
// os modos ?compare=/?forge= com artefatos faltando.
import { describe, expect, it } from 'vitest';
import { boardRowHtml, rankCompanies, stageSegments } from '../src/board';
import { chainBarHtml, chainStateListHtml, sankeySvg, selectionProgressHtml, stocksListHtml } from '../src/chain';
import { parseRunData, type Frame } from '../src/contracts';
import { narrativeItems, feedItemHtml, newItemIndexes } from '../src/feed';
import { legendHtml, legendItems } from '../src/legend';
import { compareHtml, compareRuns, forgeHtml, summarizeForge } from '../src/modes';

// Frame degradado: sem prices, empresa sem stocks, stage fora da faixa,
// crônica com kind desconhecido e evento sem texto/empresa.
const DEGRADED = {
  seed: 1,
  ticks: 12,
  frames: [
    {
      tick: 0,
      date: '2027-01',
      // prices ausente de propósito
      companies: [
        {
          id: 1, name: 'Quebrada SA', archetype: 'mineradora', color: '#abc123', hq: 'Lima',
          alive: true, cash: 5e6, stage: 7, territory: [], facilities: [],
          // stocks ausente de propósito
        },
        {
          id: 2, name: 'Zumbi Ltda', archetype: 'integradora', color: '#445566', hq: 'Bogotá',
          alive: false, cash: -1e6, stage: -2, territory: [], facilities: [], stocks: { component: 3 },
        },
      ],
      deposits: [],
    },
  ],
  chronicle: [
    { tick: 0, kind: 'rivalry', text: 'Rivalidade nova entre empresas.', company: 'Quebrada SA', date: '2027-01' },
    { tick: 0, kind: 'flows', text: '', company: null, date: '2027-01' },
    { tick: 1, kind: 'chain_link', text: 'Quebrada SA é a primeira a dominar o elo de extração.', company: 'Quebrada SA', date: '2027-02' },
    { tick: 2, kind: 'misterio', text: '', company: null, date: '2027-03' },
  ],
} as unknown as Parameters<typeof parseRunData>[0];

describe('corrida degradada atravessa todos os renderizadores (VIS-12)', () => {
  const run = parseRunData(DEGRADED);
  const frame: Frame = run.frames[0];
  const colorByName = new Map(frame.companies.map((c) => [c.name, c.color]));

  it('parse: chronicle parcial preservada; frames sem prices/stocks aceitos', () => {
    expect(run.frames).toHaveLength(1);
    expect(run.chronicle).toHaveLength(4);
    expect(frame.prices).toBeUndefined();
  });

  it('feed: kind desconhecido entra genérico; flows e texto vazio fora', () => {
    const items = narrativeItems(run.chronicle, 12);
    expect(items.map((i) => i.event.kind)).toEqual(['rivalry', 'chain_link']);
    for (const item of items) {
      expect(() => feedItemHtml(item, undefined, true)).not.toThrow();
    }
    expect(newItemIndexes(run.chronicle, null, 12).size).toBe(2);
  });

  it('placar: stage 7 clampado a 5 e stage -2 a 0; falida marcada em texto', () => {
    expect(stageSegments(7).filled).toBe(5);
    expect(stageSegments(-2).filled).toBe(0);
    const entries = rankCompanies(frame, null);
    const html = entries.map((e) => boardRowHtml(e, false)).join('');
    expect(html).toContain('† falida');
    expect(html).toContain('(5/5)');
    expect(html).toContain('(0/5)');
  });

  it('cadeia: sem prices degrada o mercado com aviso; sankey sem stocks não quebra', () => {
    // A barra só conta chain_link até o tick do frame: no tick 0, ninguém ainda.
    expect(chainBarHtml(run.chronicle, frame, colorByName)).toContain('ninguém ainda');
    const bar = chainBarHtml(run.chronicle, { ...frame, tick: 12 }, colorByName);
    expect(bar).toContain('preços indisponíveis neste frame');
    expect(bar).toContain('Quebrada SA · tick 1');
    expect(() => sankeySvg(frame)).not.toThrow();
    expect(chainStateListHtml(run.chronicle, frame)).toContain('extração');
    const [q, z] = frame.companies;
    expect(selectionProgressHtml(q)).toContain('5/5');
    expect(stocksListHtml(q)).toContain('sem estoques');
    expect(stocksListHtml(z)).toContain('componentes');
  });

  it('legenda: frame degradado gera itens sem exceção', () => {
    const items = legendItems(frame, 'empresas', { cityCount: 11, selectedId: null });
    expect(items.length).toBeGreaterThan(0);
    expect(() => legendHtml(items)).not.toThrow();
  });

  it('compare/forge com artefatos faltando: sem exceção', () => {
    expect(() => compareHtml(compareRuns([frame], []), 'vazia')).not.toThrow();
    const sum = summarizeForge(undefined, undefined, undefined as never);
    expect(() => forgeHtml(sum, 'nada')).not.toThrow();
  });

  it('parseRunData rejeita o que é inválido de verdade (erro legível, não crash)', () => {
    expect(() => parseRunData(null)).toThrow(/frames\.json inválido/);
    expect(() => parseRunData({ frames: [] })).toThrow(/frames\.json inválido/);
    expect(() => parseRunData({ frames: [{ tick: 'x' }] })).toThrow(/frame inválido/);
  });
});
