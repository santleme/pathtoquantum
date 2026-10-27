import { describe, expect, it } from 'vitest';
import { CanvasMapSurface } from '../src/mapsurface';
import { cellToLonLat } from '../src/entities';
import type { FeatureCollection } from 'geojson';

// Path2D não existe no ambiente Node do Vitest — stub mínimo (só guardamos a string).
class Path2DStub {
  constructor(public d?: string) {}
}
(globalThis as unknown as { Path2D: unknown }).Path2D = Path2DStub;

const dummyLand: FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [[[-82, 14], [-32, 14], [-32, -56], [-82, -56], [-82, 14]]] },
    },
  ],
};

describe('fitting da projeção (ADR-001 §3.3, VIS-01)', () => {
  it('geoNaturalEarth1 enquadra a América do Sul: pontos do recorte caem dentro do canvas', () => {
    const surface = new CanvasMapSurface(dummyLand);
    surface.resize(960, 640);
    for (const [lon, lat] of [[-46.6, -23.5], [-68.2, -23.5], [-32, -56], [-82, 14], [-58.9, -34.9]] as const) {
      const [x, y] = surface.project(lon, lat);
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(960);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(640);
    }
  });

  it('Pré-sal (lat −24,8 / lon −43,5) projeta a leste de São Paulo (sobre o mar, junto à costa)', () => {
    const surface = new CanvasMapSurface(dummyLand);
    surface.resize(960, 640);
    const [spX] = surface.project(-46.6, -23.5);
    const [preX, preY] = surface.project(-43.5, -24.8);
    expect(preX).toBeGreaterThan(spX);
    expect(preY).toBeGreaterThan(0);
  });

  it('cellToLonLat reproduz a grade do legado (célula 2,5°)', () => {
    expect(cellToLonLat([0, 0])).toEqual({ lon: -80.75, lat: 12.75 });
    expect(cellToLonLat([13, 5]).lon).toBeCloseTo(-68.25);
  });
});
