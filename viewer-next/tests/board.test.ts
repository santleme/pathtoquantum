import { describe, expect, it } from 'vitest';
import { parseRunData, type Company, type Frame } from '../src/contracts';
import { boardRowHtml, deltaView, money, nearestCompanyId, rankCompanies, stageSegments } from '../src/board';
import servedFrames from '../../viewer/frames.json';
import servedScoreboard from '../../viewer/scoreboard.json';

const run = parseRunData(servedFrames);
const finalFrame = run.frames[run.frames.length - 1];
const prevFrame = run.frames[run.frames.length - 2];

describe('placar-ranking (VIS-08, corrida servida)', () => {
  it('ordem e caixa do frame final conferem com scoreboard.json (âncora da spec)', () => {
    const entries = rankCompanies(finalFrame, prevFrame);
    expect(entries.map((e) => e.company.name)).toEqual(servedScoreboard.map((s) => s.name));
    expect(entries.map((e) => e.position)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(entries[0].company.name).toBe('Vetor Sul');
    expect(money(entries[0].company.cash)).toBe('US$ 273,0M');
    expect(entries[1].company.name).toBe('Ferra Brasil');
    expect(money(entries[1].company.cash)).toBe('US$ 70,2M');
    expect(entries[2].company.name).toBe('Cuprum Andes');
    expect(money(entries[2].company.cash)).toBe('US$ 60,2M');
    expect(entries[7].company.name).toBe('Órbita Systems');
    expect(money(entries[7].company.cash)).toBe('US$ 15,9M');
    for (const e of entries) {
      const sb = servedScoreboard.find((s) => s.name === e.company.name)!;
      expect(e.company.cash).toBeCloseTo(sb.cash, 2);
    }
  });

  it('segmentos de elo: n de 5 preenchidos + rótulo textual (nunca só um dos dois)', () => {
    expect(stageSegments(4)).toEqual({ filled: 4, total: 5, label: 'dispositivos' });
    expect(stageSegments(2)).toEqual({ filled: 2, total: 5, label: 'refino' });
    expect(stageSegments(0)).toEqual({ filled: 0, total: 5, label: '—' });
    // clamp de stage fora de 0..5 (VIS-12)
    expect(stageSegments(7).filled).toBe(5);
    expect(stageSegments(-1).filled).toBe(0);
    const [vetor] = rankCompanies(finalFrame, prevFrame);
    const html = boardRowHtml(vetor, false);
    expect(html.match(/class="seg on"/g)).toHaveLength(4);
    expect(html.match(/class="seg"/g)).toHaveLength(1);
    expect(html).toContain('elo: dispositivos (4/5)');
  });

  it('linha do placar: posição numerada, nome, arquétipo, caixa formatado e cor do frame', () => {
    const entries = rankCompanies(finalFrame, prevFrame);
    for (const e of entries) {
      const html = boardRowHtml(e, false);
      expect(html).toContain(`>${e.position}.<`);
      expect(html).toContain(e.company.name);
      expect(html).toContain(e.company.archetype);
      expect(html).toContain(money(e.company.cash));
      // VIS-05: a cor da linha é EXATAMENTE a color do frame (a mesma do mapa)
      expect(html).toContain(`background:${e.company.color}`);
    }
    const coresFrame = new Set(finalFrame.companies.map((c) => c.color));
    const coresPlacar = new Set(entries.map((e) => e.company.color));
    expect(coresPlacar).toEqual(coresFrame);
  });

  it('Δ de caixa desde o frame anterior: seta e valor por empresa', () => {
    const entries = rankCompanies(finalFrame, prevFrame);
    const byName = new Map(entries.map((e) => [e.company.name, e]));
    expect(byName.get('Vetor Sul')!.delta).toBeGreaterThan(0);
    expect(deltaView(byName.get('Vetor Sul')!.delta).arrow).toBe('▲');
    expect(byName.get('PetroPlata')!.delta).toBeLessThan(0);
    expect(deltaView(byName.get('PetroPlata')!.delta).arrow).toBe('▼');
    expect(byName.get('Lítio Austral')!.delta).toBe(0);
    expect(deltaView(0)).toEqual({ arrow: '±', text: 'US$ 0,0M', cls: 'flat' });
    // o HTML sinaliza o Δ (nunca um retrato mudo)
    expect(boardRowHtml(byName.get('Vetor Sul')!, false)).toContain('▲');
    expect(boardRowHtml(byName.get('PetroPlata')!, false)).toContain('▼');
  });

  it('primeiro frame: Δ é null e a linha mostra "—" (sem frame anterior)', () => {
    const entries = rankCompanies(run.frames[0], null);
    expect(entries.every((e) => e.delta === null)).toBe(true);
    expect(deltaView(null).cls).toBe('none');
    expect(boardRowHtml(entries[0], false)).toContain('sem frame anterior');
  });

  it('empresa falida (fixture alive:false): marcada por texto/ícone além do esmaecimento', () => {
    const dead: Company = { ...finalFrame.companies[0], alive: false };
    const frame: Frame = { ...finalFrame, companies: [dead] };
    const [entry] = rankCompanies(frame, null);
    const html = boardRowHtml(entry, false);
    expect(html).toContain('class="brow dead"');
    expect(html).toContain('tag-dead');
    expect(html).toContain('falida');
    expect(html).toContain('†');
  });
});

describe('seleção de empresa (VIS-05)', () => {
  it('selecionada ganha selo textual e classe própria — canal não-cor', () => {
    const [entry] = rankCompanies(finalFrame, prevFrame);
    const html = boardRowHtml(entry, true);
    expect(html).toContain('brow selected');
    expect(html).toContain('selecionada');
    expect(html).toContain('aria-pressed="true"');
    expect(boardRowHtml(entry, false)).not.toContain('tag-sel');
  });

  it('clique no mapa: nearestCompanyId acha a empresa da instalação clicada (projeção identidade)', () => {
    const identity = (lon: number, lat: number): [number, number] => [lon, lat];
    const withFac = finalFrame.companies.find((c) => c.facilities.length > 0)!;
    // centro da célula da primeira instalação, pela mesma conversão do desenho
    const [row, col] = withFac.facilities[0].cell;
    const lon = -82 + col * 2.5 + 1.25;
    const lat = 14 - row * 2.5 - 1.25;
    expect(nearestCompanyId(finalFrame.companies, identity, lon, lat)).toBe(withFac.id);
    expect(nearestCompanyId(finalFrame.companies, identity, lon + 0.4, lat - 0.4)).toBe(withFac.id);
    // longe de tudo = null (clique no vazio limpa a seleção, não inventa empresa)
    expect(nearestCompanyId(finalFrame.companies, identity, 0, 80)).toBeNull();
  });
});
