import { describe, expect, it } from 'vitest';
import {
  chainBarHtml,
  chainStateListHtml,
  companyProgress,
  eloStocks,
  firstByLink,
  formatPrice,
  frontierStage,
  marketContext,
  progressedStocks,
  sankeyData,
  sankeySvg,
  stocksList,
  stocksListHtml,
} from '../src/chain';
import { parseRunData, type Frame } from '../src/contracts';
import servedFrames from '../../data/served/frames.json';

const run = parseRunData(servedFrames);
const frame0 = run.frames[0];
const finalFrame = run.frames[run.frames.length - 1];
const byName = (f: Frame, name: string) => f.companies.find((c) => c.name === name)!;

describe('primeiros por elo (VIS-06, âncoras da corrida servida)', () => {
  it('frame tick 120: elos 1–4 com Órbita Systems nos ticks 1, 2, 5, 8; elo 5 aberto', () => {
    const firsts = firstByLink(run.chronicle, 120);
    expect(firsts.slice(0, 4)).toEqual([
      { company: 'Órbita Systems', tick: 1 },
      { company: 'Órbita Systems', tick: 2 },
      { company: 'Órbita Systems', tick: 5 },
      { company: 'Órbita Systems', tick: 8 },
    ]);
    expect(firsts[4]).toBeNull();
    expect(frontierStage(firsts)).toBe(5);
  });

  it('frame tick 0: nenhum elo dominado (chain_link é de tick ≥ 1)', () => {
    const firsts = firstByLink(run.chronicle, 0);
    expect(firsts).toEqual([null, null, null, null, null]);
    expect(frontierStage(firsts)).toBe(1);
  });

  it('respeita o tick do frame: até 4, só os elos de ticks 1 e 2 constam', () => {
    const firsts = firstByLink(run.chronicle, 4);
    expect(firsts[0]).toEqual({ company: 'Órbita Systems', tick: 1 });
    expect(firsts[1]).toEqual({ company: 'Órbita Systems', tick: 2 });
    expect(firsts[2]).toBeNull();
    expect(firsts[3]).toBeNull();
  });

  it('barra no frame final: 4 segmentos dominados com Órbita/ticks e elo 5 "ninguém ainda"', () => {
    const colors = new Map(finalFrame.companies.map((c) => [c.name, c.color]));
    const html = chainBarHtml(run.chronicle, finalFrame, colors);
    expect(html.match(/class="cseg dominado"/g)).toHaveLength(4);
    expect(html).toContain('Órbita Systems · tick 1');
    expect(html).toContain('Órbita Systems · tick 8');
    expect(html).toContain('5. SUPERCOMPUTADOR');
    expect(html).toContain('ninguém ainda');
    expect(html).toContain('em disputa');
    const html0 = chainBarHtml(run.chronicle, frame0, colors);
    expect(html0.match(/class="cseg dominado"/g) ?? []).toHaveLength(0);
    expect(html0.match(/ninguém ainda/g)).toHaveLength(5);
  });
});

describe('progresso individual por empresa (VIS-06, mesma função do placar)', () => {
  it('frame final: 4/5, 4/5, 4/5, 4/5, 2/5, 2/5, 0/5, 0/5 (âncora da spec)', () => {
    const expected: Record<string, number> = {
      'Vetor Sul': 4,
      'Cuprum Andes': 4,
      'Nexo Indústrias': 4,
      'Órbita Systems': 4,
      'Ferra Brasil': 2,
      PetroPlata: 2,
      'Lítio Austral': 0,
      'Andina Prime': 0,
    };
    for (const [name, filled] of Object.entries(expected)) {
      const seg = companyProgress(byName(finalFrame, name));
      expect(seg.filled, name).toBe(filled);
      expect(seg.total).toBe(5);
    }
    expect(companyProgress(byName(finalFrame, 'Órbita Systems')).label).toBe('dispositivos');
    expect(companyProgress(byName(finalFrame, 'Ferra Brasil')).label).toBe('refino');
  });
});

describe('vista-cadeia Sankey — derivação a partir de stocks/stage', () => {
  it('frame real final: links = estoque do elo em poder de quem passou dele', () => {
    const { nodes, links } = sankeyData(finalFrame);
    expect(nodes).toHaveLength(5);
    expect(links).toHaveLength(4);
    // elo 1→2: minérios das 4 empresas stage 4 (todas as detentoras de minério)
    const orbita = byName(finalFrame, 'Órbita Systems');
    expect(links[0].value).toBeCloseTo(eloStocks(finalFrame, 1), 6);
    expect(links[0].value).toBeGreaterThan(orbita.stocks.copper_ore);
    // elo 3→4: componentes das empresas stage 4 = todo o estoque de componentes
    expect(links[2].value).toBeCloseTo(eloStocks(finalFrame, 3), 6);
    expect(links[2].value).toBeGreaterThan(0);
    // elo 4→5: ninguém tem stage 5 → fluxo derivado é 0 (sem inventar fluxo)
    expect(links[3].value).toBe(0);
    // elo 2→3 exclui quem está no elo 2 (Ferra: iron; PetroPlata: plastic)
    const ferra = byName(finalFrame, 'Ferra Brasil');
    expect(progressedStocks(finalFrame, 2)).toBeCloseTo(
      eloStocks(finalFrame, 2) - (ferra.stocks.iron + byName(finalFrame, 'PetroPlata').stocks.plastic),
      6,
    );
  });

  it('tick 0: sem stocks, todos os links são 0 e o SVG cai no fallback textual', () => {
    const { links } = sankeyData(frame0);
    expect(links.every((l) => l.value === 0)).toBe(true);
    const svg = sankeySvg(frame0);
    expect(svg).toContain('sem fluxo entre elos neste frame');
    expect(svg).toContain('role="img"');
  });

  it('frame final: SVG tem 5 nós e links com largura > 0 (exceto o elo 4→5)', () => {
    const svg = sankeySvg(finalFrame);
    expect(svg.match(/class="snode/g)).toHaveLength(5);
    expect(svg.match(/class="slink"/g)).toHaveLength(3);
    expect(svg).toContain('SUPERCOMPUTADOR');
  });

  it('lista textual equivalente: estados dos elos e estoque por elo (acessibilidade)', () => {
    const html = chainStateListHtml(run.chronicle, finalFrame);
    expect(html).toContain('dominado primeiro por Órbita Systems (tick 1)');
    expect(html).toContain('5. SUPERCOMPUTADOR</b> — ninguém ainda');
    expect(html).toContain('estoque do elo:');
    const html0 = chainStateListHtml(run.chronicle, frame0);
    expect(html0.match(/ninguém ainda/g)).toHaveLength(5);
  });
});

describe('contexto de mercado e stocks (VIS-06)', () => {
  it('frame final: elo em disputa é o 5 e o preço do supercomputador sai como está', () => {
    const market = marketContext(finalFrame, firstByLink(run.chronicle, 120));
    expect(market.stage).toBe(5);
    expect(market.closed).toBe(false);
    expect(market.prices).toEqual([
      { resource: 'supercomputer', label: 'supercomputador', price: 1200000 },
    ]);
    // device/supercomputer são constantes nesta corrida — mostrar o valor, sem exigir variação
    expect(formatPrice(1200000)).toContain('1.200.000');
    const html = chainBarHtml(run.chronicle, finalFrame, new Map());
    expect(html).toContain('supercomputador');
    expect(html).toContain('1.200.000');
  });

  it('tick 0: elo em disputa é a extração, com os 4 minérios precificados', () => {
    const market = marketContext(frame0, firstByLink(run.chronicle, 0));
    expect(market.stage).toBe(1);
    expect(market.prices.map((p) => p.resource)).toEqual([
      'lithium_ore',
      'copper_ore',
      'iron_ore',
      'oil',
    ]);
  });

  it('stocks da Órbita: 5 commodities > 0, maior primeiro; vazia = lista vazia', () => {
    const orbita = byName(finalFrame, 'Órbita Systems');
    const lines = stocksList(orbita);
    expect(lines.map((l) => l.resource)).toEqual([
      'copper_ore',
      'lithium',
      'component',
      'lithium_ore',
      'copper',
    ]);
    expect(lines[0].amount).toBeCloseTo(32155.2, 6);
    expect(stocksListHtml(orbita)).toContain('componentes');
    expect(stocksList(byName(finalFrame, 'Lítio Austral'))).toEqual([]);
    expect(stocksListHtml(byName(finalFrame, 'Lítio Austral'))).toContain('sem estoques neste frame');
  });
});

describe('robustez (VIS-12): frame degradado sem prices/stocks', () => {
  const degraded = {
    tick: 36,
    date: '2033-01',
    companies: [
      {
        id: 0,
        name: 'Degradada SA',
        archetype: 'mineradora',
        color: '#ffffff',
        hq: 'Lima',
        alive: true,
        cash: 1000,
        stage: 3,
        territory: [],
        facilities: [],
        // stocks ausente de propósito
      },
    ],
    deposits: [],
    // prices ausente de propósito
  } as unknown as Frame;

  it('nada lança: sankey zerado, mercado vazio, stocks = 0', () => {
    expect(() => sankeyData(degraded)).not.toThrow();
    expect(sankeyData(degraded).links.every((l) => l.value === 0)).toBe(true);
    expect(() => sankeySvg(degraded)).not.toThrow();
    expect(marketContext(degraded, firstByLink(run.chronicle, 36)).prices).toEqual([]);
    expect(eloStocks(degraded, 1)).toBe(0);
    expect(stocksList(degraded.companies[0])).toEqual([]);
    const html = chainBarHtml(run.chronicle, degraded, new Map());
    expect(html).toContain('preços indisponíveis neste frame');
    // stage 3 continua legível no progresso mesmo sem stocks/prices
    expect(companyProgress(degraded.companies[0]).filled).toBe(3);
  });
});
