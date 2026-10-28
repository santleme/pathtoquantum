import { describe, expect, it } from 'vitest';
import { frameIndexForTick, parseRunData, parseWorldData, resolveRunDir } from '../src/contracts';
import { citiesFromWorld, depositsFromFrame, depositsFromWorld } from '../src/entities';
import { RESOURCE_REGISTRY, resourceInfo } from '../src/resources';
import servedFrames from '../../data/served/frames.json';
import worldData from '../../data/world_data.json';

describe('contratos (SPEC §0)', () => {
  it('parseia a corrida servida real: 11 frames, 8 empresas, 10 depósitos, 239 eventos', () => {
    const run = parseRunData(servedFrames);
    expect(run.frames).toHaveLength(11);
    expect(run.frames[0].companies).toHaveLength(8);
    expect(depositsFromFrame(run.frames[0])).toHaveLength(10);
    expect(run.chronicle).toHaveLength(239);
    expect(Object.keys(run.frames[0].prices)).toHaveLength(11);
  });

  it('rejeita frames.json sem frames', () => {
    expect(() => parseRunData({ frames: [] })).toThrow(/frames/);
    expect(() => parseRunData(null)).toThrow();
  });

  it('frameIndexForTick devolve o último frame com tick <= pedido', () => {
    const run = parseRunData(servedFrames);
    expect(frameIndexForTick(run, 0)).toBe(0);
    expect(frameIndexForTick(run, 12)).toBe(1);
    expect(frameIndexForTick(run, 13)).toBe(1);
    expect(frameIndexForTick(run, 999)).toBe(10);
  });

  it('?run= rejeita ".." e aceita diretório limpo (VIS-07)', () => {
    expect(resolveRunDir('')).toBeNull();
    expect(resolveRunDir('?run=results/nascimento-v0')).toBe('results/nascimento-v0');
    expect(() => resolveRunDir('?run=../etc')).toThrow(/\.\./);
  });
});

describe('mundo orientado a dados (VIS-02)', () => {
  it('world_data tem 11 cidades e 13 depósitos — sem hardcode', () => {
    const world = parseWorldData(worldData);
    const cities = citiesFromWorld(world);
    expect(cities).toHaveLength(11);
    expect(cities.map((c) => c.name)).toContain('Montevidéu');
    expect(cities.map((c) => c.name)).toContain('Assunção');
    expect(cities.map((c) => c.name)).toContain('Medellín');
    expect(cities.map((c) => c.name)).toContain('Rio de Janeiro');
    const deps = depositsFromWorld(world);
    expect(deps).toHaveLength(13);
    expect(deps.map((d) => d.name)).toContain('Salar del Hombre Muerto');
    expect(deps.map((d) => d.name)).toContain('Cerro Verde (Arequipa)');
    expect(deps.map((d) => d.name)).toContain('El Mutún');
  });

  it('registro cobre as 11 commodities de prices, com fallback genérico', () => {
    const run = parseRunData(servedFrames);
    for (const key of Object.keys(run.frames[0].prices)) {
      expect(RESOURCE_REGISTRY[key], key).toBeDefined();
    }
    expect(resourceInfo('unobtanium')).toEqual({ label: 'unobtanium', symbol: '?' });
  });
});
