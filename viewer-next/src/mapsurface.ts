// MapSurface — a costura da ADR-001 §3.1/§7: loader, painéis e (futuro) Sankey/séries
// falam com esta interface, nunca com d3-geo/Canvas diretamente. Se um gatilho do §7
// disparar, troca-se a implementação (MapLibre tile-less) sem tocar o resto.
import { geoGraticule10, geoNaturalEarth1, geoPath, type GeoProjection } from 'd3-geo';
import type { Feature, FeatureCollection, Geometry } from 'geojson';

export interface MapSurface {
  readonly projection: GeoProjection;
  resize(width: number, height: number): void;
  project(lon: number, lat: number): [number, number];
  /** Desenha a base (continente/gratícula) no ctx, cacheando Path2D por tamanho. */
  drawBase(ctx: CanvasRenderingContext2D): void;
  invalidateBase(): void;
}

/** Objeto de enquadramento: América do Sul (mundo jogável atual, SPEC §0). */
export const SA_FIT_OBJECT: Feature<Geometry> = {
  type: 'Feature',
  properties: {},
  geometry: {
    type: 'Polygon',
    coordinates: [[[-82, 14], [-32, 14], [-32, -56], [-82, -56], [-82, 14]]],
  },
};

export class CanvasMapSurface implements MapSurface {
  readonly projection: GeoProjection;
  private readonly saLand: FeatureCollection;
  private baseCache: { w: number; h: number; land: Path2D; grat: Path2D } | null = null;

  constructor(saLand: FeatureCollection) {
    this.saLand = saLand;
    this.projection = geoNaturalEarth1();
  }

  resize(width: number, height: number): void {
    // Abertura enquadrada na América do Sul (ADR-001 §3.3); a projeção é única.
    this.projection.fitExtent(
      [
        [8, 8],
        [Math.max(9, width - 8), Math.max(9, height - 8)],
      ],
      SA_FIT_OBJECT,
    );
    this.baseCache = null;
  }

  project(lon: number, lat: number): [number, number] {
    const p = this.projection([lon, lat]);
    return p ? [p[0], p[1]] : [NaN, NaN];
  }

  invalidateBase(): void {
    this.baseCache = null;
  }

  drawBase(ctx: CanvasRenderingContext2D): void {
    const w = ctx.canvas.width;
    const h = ctx.canvas.height;
    if (!this.baseCache || this.baseCache.w !== w || this.baseCache.h !== h) {
      const toSvg = geoPath(this.projection);
      const landSvg = toSvg(this.saLand as never) ?? '';
      const gratSvg = toSvg(geoGraticule10() as never) ?? '';
      this.baseCache = { w, h, land: new Path2D(landSvg), grat: new Path2D(gratSvg) };
    }
    ctx.save();
    ctx.fillStyle = '#0d1526'; // oceano
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = '#16223c'; // gratícula discreta (VIS-01: não é mais o único referencial)
    ctx.lineWidth = 0.5;
    ctx.stroke(this.baseCache.grat);
    ctx.fillStyle = '#27395c'; // terra
    ctx.fill(this.baseCache.land);
    ctx.strokeStyle = '#5b7ba6'; // costa
    ctx.lineWidth = 1;
    ctx.stroke(this.baseCache.land);
    ctx.restore();
  }
}
