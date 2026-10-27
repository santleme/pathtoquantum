# viewer-next — Path to Quantum (F0+F1+F2+F3+F4)

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

Testes: `npm test` (Vitest — contratos §0, fitting da projeção, mundo orientado a dados, feed da crônica F2, lentes e placar F3, cadeia F4).

Bundle após a F3 (re-medido com `npm run build && npm run measure`): app
**16,9 KiB gzip** (teto 180 KiB) — cresceu 3,6 KiB sobre os 13,3 KiB da F0/F1
pelos módulos novos (`lenses.ts` + `board.ts`) e pelo CSS do placar/lentes no
`index.html`; geografia inalterada (114,1 KiB bruto / 40,0 KiB gzip).

Bundle após a F4 (re-medido, mesmos comandos): app **21,9 KiB gzip**
(22.430 B; teto 180 KiB) — Δ de **+5,0 KiB** sobre a F3, quase todo do
`d3-sankey` (dependência prevista na ADR-001 §3.5) e do módulo `chain.ts`;
geografia inalterada. Longe do teto: nenhuma troca de stack se impõe.

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

## F3 — Lente Empresas + placar-ranking (VIS-05/VIS-08, branch `viewer/wow-v2-fatias`)

- Mecanismo de lentes (`src/lenses.ts`): registro **único e declarativo**
  `{id, label, layer, status}` — lente nova é 1 entrada no registro, nenhum
  `if` no código de desenho. **Empresas** é a lente padrão e a única ativa;
  Recursos/Produção/Comércio/Crônica aparecem no seletor como **"em breve"**:
  clicar nelas só mostra o aviso — a camada, o tick e o frame **não mudam**
  (nenhum JSON é recarregado na troca).
- Seleção de empresa: clique numa linha do placar **ou no mapa** (instalação/
  território mais próximo) seleciona; clicar de novo (ou no vazio do mapa)
  desseleciona. A selecionada ganha **anel dourado + rótulo `◉ nome`** nas
  instalações, contorno no território e selo textual "selecionada" no placar;
  as demais recuam em alpha (0,3) no mapa e nas rotas — seleção nunca é
  comunicada só por cor.
- Placar-ranking (`src/board.ts`): posição numerada **1..n**, nome, arquétipo,
  caixa formatado, **elo como segmentos preenchidos (n de 5) + rótulo textual**
  ("elo: dispositivos (4/5)"), e **Δ de caixa desde o frame anterior** com seta
  (▲/▼/±; no primeiro frame, "—" sem frame anterior). Empresa falida
  (`alive: false`) é marcada com selo **"† falida"** além do esmaecimento.
  Mapa e placar usam **exatamente** as cores `color` do frame (mesma fonte).
- Âncoras: `npm run anchors` agora cobre também o VIS-08 — ordem e caixa do
  frame final contra `scoreboard.json` (**Vetor Sul US$ 273,0M > Ferra Brasil
  70,2M > Cuprum Andes 60,2M > Lítio Austral > PetroPlata > Andina Prime >
  Nexo Indústrias > Órbita Systems 15,9M**), segmentos `[4,2,4,0,2,0,4,4]` e
  Δ da Vetor Sul (+US$ 32,9M). Testes: `npm test` (registro de lentes, troca
  sem mover o frame, seleção não-cor, placar/âncora, falida por fixture,
  Δ, clique-no-mapa).

## F4 — Barra/vista da cadeia (VIS-06, branch `viewer/wow-v2-fatias`)

- Barra sempre visível sob o header (`src/chain.ts`): os 5 elos nomeados
  (extração, refino, componentes, dispositivos, SUPERCOMPUTADOR) como
  segmentos; por elo, **quem dominou primeiro** — derivado dos eventos
  `chain_link` (o elo sai do texto do evento, com fallback ordinal; ticks
  reais, **sem interpolar frames**: o `stage` salta 0→4 entre frames anuais,
  a barra ancora nos marcos, spec §9) — ou "ninguém ainda". Âncoras da
  corrida servida: no tick 120, elos 1–4 dominados com **Órbita Systems
  primeira nos ticks 1, 2, 5 e 8** e o elo 5 aberto; no tick 0, nenhum.
- Progresso individual na mesma escala (`stage/5`): a função pura única é
  `companyProgress`, que delega aos segmentos do placar da F3 — barra,
  placar e painel de seleção leem a mesma verdade. Frame final: Vetor Sul,
  Cuprum Andes, Nexo Indústrias e Órbita Systems em 4/5; Ferra Brasil e
  PetroPlata em 2/5; Lítio Austral e Andina Prime em 0/5.
- Vista-cadeia **Sankey** (aside): layout `d3-sankey` + render SVG próprio
  (ADR-001 §3.5). **O que a largura representa, exatamente:** os artefatos
  não trazem fluxo elo→elo, então a largura do link k→k+1 é uma derivação —
  a soma das unidades das commodities de **saída** do elo k em poder de
  empresas que já dominaram o elo k+1 (`stage > k`): o estoque "qualificado"
  por progresso, não uma medição de transferência. Sem fluxo positivo
  (tick 0), a vista cai em caixas iguais com a nota "sem fluxo entre elos
  neste frame". Comércio entre empresas (cíclico) não entra — é DAG da
  cadeia; comércio fica nos arcos do mapa. Ao lado do SVG, a **lista textual
  equivalente** (estado de cada elo + estoque total do elo) cobre a
  acessibilidade da vista.
- Contexto de mercado na barra: preços (`prices` do frame) das commodities
  do **elo mais alto em disputa** (o primeiro não dominado) — no frame final,
  o supercomputador a US$ 1.200.000, **mostrado como está**: `device` e
  `supercomputer` são constantes nesta corrida e a spec proíbe exigir
  variação deles. Frame sem `prices` degrada para "preços indisponíveis
  neste frame", sem erro (VIS-12); `stocks` ausente = 0.
- Painel de seleção (F3) agora mostra os **estoques da empresa selecionada**
  por commodity (rótulo legível + quantidade, maior primeiro) — `stocks`
  deixou de ser dado morto. Ex.: selecionar a Órbita mostra copper_ore,
  lithium, component, lithium_ore e copper do frame.
- Âncoras: `npm run anchors` cobre também o VIS-06 (primeiros por elo,
  tick 0 vazio, progresso final por empresa, preços constantes, stocks).
  Testes: `npm test` (primeiros-por-elo, tick 0, derivação Sankey com frame
  real e com frame degradado sem `prices`/`stocks`).

## Fora desta fatia (F5–F6 da spec)

README/lockup/favicon do repo (F5) · acessibilidade/responsivo/screenshots
e o portão final de regressão (F6).

**VIS-07 — o que ainda se cumpre via viewer legado:** o seletor de arquivo
avulso, o `?compare=` e o `?forge=` seguem só no legado (`../viewer/`, intocado).
Este app cobre play/pause, velocidades, scrub, `?run=` e — desde a F2 — o clique
na crônica para saltar ao marco, além de expor `window.ptqJumpToTick`.
