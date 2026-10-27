# viewer-next — Path to Quantum (F0+F1+F2)

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
| Bundle do app (JS+CSS+HTML, gzip, sem geo/dados) | ≤ 180 KiB | **13,3 KiB** (JS 12,0 KiB gzip + HTML 1,3 KiB gzip) | PASSA |
| Geografia embutida no `dist` | ≤ 200 KiB | **114,1 KiB bruto / 40,0 KiB gzip** (mundo land-110m 53,9 KiB + excerto SA-50m 60,2 KiB) | PASSA |
| Frame dinâmico — benchmark sintético 500 empresas / 2.000 partículas | < 8 ms | **dinâmico 1,59 ms · fluxo 0,12 ms · total 2,28 ms/frame (~440 fps-equiv)** | PASSA |

Unidade única desta tabela: **KiB** (bytes ÷ 1024), a mesma que o `measure` calcula
e usa nos tetos — conferido com `npm run build && npm run measure` nesta revisão
(app gzip 13.617 B; geografia 116.809 B bruto / 40.972 B gzip; componentes somam:
53,9 + 60,2 = 114,1 KiB).

Nota sobre a geografia: o `geo/world-110m.json` (land-110m) é **gerado/copiado para o
`dist` no build e entra na conta acima, mas não é carregado na abertura** — a abertura
busca só o `geo/sa-50m.json`. A vista-múndi que usará o land-110m é fatia futura.

Reproduzir: `npm run build && npm run measure && npm run bench`.

Ressalva honesta do benchmark: roda em Node com ctx Canvas stub (conta comandos, não
rasteriza) — mede a lógica de frame (projeção + comandos), não o fps de um browser real.
É o piso comparável/reproduzível; a margem (3,5× abaixo do teto) é a proteção.

Testes: `npm test` (Vitest — contratos §0, fitting da projeção, mundo orientado a dados, feed da crônica F2).

## F2 — A crônica vira show (VIS-03/VIS-04, branch `viewer/wow-v2-fatias`)

- Feed renderizado por `kind`/`company` (`src/feed.ts`): hierarquia da spec —
  **marco** (`chain_link, end, record, bankruptcy, acquisition`) > **estrutural**
  (`facility, mine`) > **fundação/sondagem** (`founding, probe`) > **rotina**
  (`tool, god`) — cada kind com selo SVG próprio e rótulo pt-BR (nada de emoji);
  marcador da empresa na cor do frame **+ nome em texto** (cor nunca é o único
  canal); evento sem `company` não ganha cor nenhuma.
- `flows` fora da narrativa: os 120 eventos contábeis de texto vazio **não viram
  itens** — no frame final o feed tem exatamente os **119 itens narrativos**, em
  ordem cronológica (DOM: mais recente no topo). Kind desconhecido (ex.:
  `rivalry`) cai no estilo genérico de rotina com o texto integral.
- Destaque de novo (VIS-04): avançar o frame marca o lote que entrou
  (`prev.tick < e.tick <= frame.tick`) com selo textual "novo" + pulso; a marca
  migra no avanço seguinte; scrub/jump/clique não marcam nada;
  `prefers-reduced-motion` = marca estática, sem pulso.
- Clique num item do feed (ou Enter/Espaço — o item é um `<button>`) salta o
  replay ao frame do tick do evento — a fiação real do `ptqJumpToTick`, que
  fecha o VIS-07 parcial apontado na revisão de F0/F1.
- Âncoras da fatia: `npm run anchors` (script §8.2 — contagem de kinds, 119
  itens, lote 0→12 = 46, ticks dos `chain_link` 1/2/5/8). Testes: `npm test`
  (Vitest — classificação/hierarquia, 119 sem flows, lote de novos, kind
  desconhecido, clique→salto).

## Fora desta fatia (F3–F6 da spec)

Lentes + placar-ranking completo (F3) · barra da cadeia/Sankey (F4) ·
README/lockup/favicon do repo (F5) · acessibilidade/responsivo/screenshots e o
portão final de regressão (F6).

**VIS-07 — o que ainda se cumpre via viewer legado:** o seletor de arquivo
avulso, o `?compare=` e o `?forge=` seguem só no legado (`../viewer/`, intocado).
Este app cobre play/pause, velocidades, scrub, `?run=` e — desde a F2 — o clique
na crônica para saltar ao marco, além de expor `window.ptqJumpToTick`.
