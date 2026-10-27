# viewer-next — Path to Quantum (F0+F1)

App Vite + TypeScript (sem framework) da camada visual nova. O viewer legado em
`../viewer/` continua intocado e abrindo corridas antigas. Stack: `docs/adr/ADR-001-stack-visual.md`;
comportamento: `docs/SPEC-VISUAL-WOW.md`.

## Como abrir

```bash
cd viewer-next
npm install
npm run dev        # gera geo + sincroniza dados, sobe o Vite
# ou, produção estática:
npm run build      # → dist/ (100% estático, offline após o build)
python3 -m http.server -d dist 8000
```

- Sem parâmetros: abre a corrida servida (`viewer/*.json`, copiados em build para `dist/data/served/` — a fonte continua sendo `viewer/` + `data/world_data.json`).
- `?run=<dir>`: carrega `<dir>/frames.json` (rejeita `..`), como no legado (VIS-07).
- Mapa: 3 canvases empilhados atrás da interface `MapSurface` (`src/mapsurface.ts`) — base cacheada em `Path2D` (excerto América do Sul 50m de Natural Earth via `world-atlas`), dinâmico por frame, fluxo animado. Projeção única `geoNaturalEarth1`, abertura enquadrada na América do Sul.
- Entidades 100% orientadas a dados: cidades das 11 de `world_data.json`; depósitos do frame da corrida (10 na corrida v0 servida; 13 quando a corrida for do mundo v1).

## Portão da ADR-001 §8 — resultado (27/10/2026, esta VM)

| Métrica | Teto | Medido | Veredito |
|---|---|---|---|
| Bundle do app (JS+CSS+HTML, gzip, sem geo/dados) | ≤ 180 KB | **13,3 KB** (JS 12,3 KB gzip) | PASSA |
| Geografia embutida | ≤ 200 KB | **114,1 KB bruto / 40,0 KB gzip** (mundo land-110m 55,2 KB + excerto SA-50m 61,6 KB) | PASSA |
| Frame dinâmico — benchmark sintético 500 empresas / 2.000 partículas | < 8 ms | **dinâmico 1,59 ms · fluxo 0,12 ms · total 2,28 ms/frame (~440 fps-equiv)** | PASSA |

Reproduzir: `npm run build && npm run measure && npm run bench`.

Ressalva honesta do benchmark: roda em Node com ctx Canvas stub (conta comandos, não
rasteriza) — mede a lógica de frame (projeção + comandos), não o fps de um browser real.
É o piso comparável/reproduzível; a margem (3,5× abaixo do teto) é a proteção.

Testes: `npm test` (Vitest — contratos §0, fitting da projeção, mundo orientado a dados).

## Fora desta fatia (F2–F6 da spec)

Crônica por `kind` com hierarquia e destaque de novo (F2) · lentes + placar-ranking
completo (F3) · barra da cadeia/Sankey (F4) · README/lockup/favicon do repo (F5) ·
acessibilidade/responsivo/screenshots (F6). Comparador `?compare=` e painel `?forge=`
seguem no viewer legado nesta fatia (não-regressão deles é da F6).
