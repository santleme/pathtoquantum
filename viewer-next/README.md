# viewer-next — Path to Quantum (F0+F1+F2+F3+F4+F5+F6 — spec WOW fechada)

App Vite + TypeScript (sem framework) da camada visual — é **o** viewer do projeto.
O player legado de arquivo único (`viewer/`) foi aposentado: tudo que ele fazia vive
aqui (paridade provada no VIS-07). Stack: `docs/adr/ADR-001-stack-visual.md`;
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

- Sem parâmetros: abre a corrida servida (`data/served/*.json`, copiados em build para `dist/data/served/` — a fonte é `data/served/` + `data/world_data.json`).
- `?run=<dir>`: carrega `<dir>/frames.json` (rejeita `..`), como no legado (VIS-07).
- `?compare=<dir>`: painel de comparação de frame final contra outra corrida (F6).
- `?forge=<dir>`: painel da forja a partir dos artefatos do diretório (F6).
- Seletor **arquivo** no header: carrega um `frames.json` avulso (F6, VIS-07).
- Mapa: 3 canvases empilhados atrás da interface `MapSurface` (`src/mapsurface.ts`) — base cacheada em `Path2D` (excerto América do Sul 50m de Natural Earth via `world-atlas`), dinâmico por frame, fluxo animado. Projeção única `geoNaturalEarth1`, abertura enquadrada na América do Sul.
- Entidades 100% orientadas a dados: cidades das 11 de `world_data.json`; depósitos do frame da corrida (10 na corrida v0 servida; 13 quando a corrida for do mundo v1).

## Portão da ADR-001 §8 — resultado (27/10/2026, esta VM)

| Métrica | Teto | Medido | Veredito |
|---|---|---|---|
| Bundle do app (JS+CSS+HTML, gzip, sem geo/dados) | ≤ 180 KiB | **13,3 KiB** na F0/F1 → **77,9 KiB** no fechamento F6 (desse total, o JS puro é 22,9 KiB gzip; o restante são os arquivos estáticos de `public/` — favicon/marca/apple-touch, servidos sob demanda, não bundle) | PASSA |
| Geografia embutida no `dist` | ≤ 200 KiB | **114,1 KiB bruto / 40,0 KiB gzip** (mundo land-110m 53,9 KiB + excerto SA-50m 60,2 KiB) | PASSA |
| Frame dinâmico — benchmark sintético 500 empresas / 2.000 partículas | < 8 ms | F0/F1: total 2,28 ms/frame · **re-medido na F6: dinâmico 0,84 ms · fluxo 0,11 ms · total 0,90 ms/frame** | PASSA |

Unidade única desta tabela: **KiB** (bytes ÷ 1024), a mesma que o `measure` calcula
e usa nos tetos — os números entre parênteses abaixo são a medição da F0/F1,
datada aqui para não confundir com os totais da F6 na tabela acima
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

## F5 — Entrega pública (VIS-09, branch `viewer/wow-v2-fatias`)

- **Lockup no header:** marca + **Path to Quantum** + a tagline vigente do
  README ("Eight autonomous AI companies. One real Earth…"). A marca é
  derivada da capa (abaixo), não arte nova; `<title>` e `h1` já diziam Path to
  Quantum desde a F0/F1 e nenhuma superfície visível usa "Mundo Autônomo"
  (grep zero em `src/` + `index.html`). O lockup do README do repo (capa +
  título + tagline) foi entregue na vitrine (PR #23) — aqui fecha a parte do
  viewer. Meta social/OG: a spec não a pede no VIS-09 (só limita o peso de
  derivados), então **não** foi inventada.
- **Favicon derivado da capa:** `scripts/build-favicon.py` (reproduzível,
  offline, Pillow) recorta de `assets/cover.webp` o quadrado centrado no
  reator "quantum core" — o centro visual da arte — e gera em `public/`:
  `favicon.ico` (16/32/48), `favicon-16.png`, `favicon-32.png`,
  `ptq-mark-64.png` (a marca do lockup) e `apple-touch-icon.png` (180×180,
  quantizado para paleta adaptativa só para caber no teto). Todos **< 50 KB**
  (733 B – 29,9 KB), como manda a VIS-09; referenciados no `index.html`.
  Regenerar: `python3 scripts/build-favicon.py`.
- **Legenda viva da lente** (`src/legend.ts`, função pura frame+lente →
  itens; `main.ts` só injeta): substitui a legenda fixa de símbolos por —
  empresas **presentes no frame**, com a cor do frame e nome (empresa que sai
  do frame sai da legenda; falida/selecionada marcadas em texto); símbolos do
  mapa (◆ depósito com contagem do frame, ● cidade-mercado com contagem do
  world_data, ◉ seleção); segmentos de elo com a escala de estágios; e os
  selos da crônica por tier, derivados de `KIND_META` (a mesma taxonomia do
  feed). Lente "em breve"/desconhecida não inventa camada: a legenda segue a
  da Empresas com nota explícita. Mudar de frame/lente/seleção re-renderiza a
  legenda junto (via `renderBoard`).
- Testes: `npm test` — 8 novos de legenda (frame real com cor exata do frame,
  troca de frame, seleção/falida em texto, símbolos/elos/tiers, lente em
  breve/desconhecida, frame degradado sem empresas/depósitos/preços).
- Bundle: JS 20,4 KB gzip medidos pelo script da casa; o total "APP" do
  `measure` sobe para 74,8 KB porque o script soma os arquivos estáticos
  novos de `public/` (favicon/marca, ~53 KB somados) — eles **não** são
  bundle JS, são servidos sob demanda, e mesmo o total passa o teto de
  180 KB com folga. Geografia inalterada (114,1 KB bruto / 40,0 KB gzip).

## F6 — Piso e portão final (VIS-07/10/11/12/13 — fecha a spec)

> Numeração conforme a **spec** (§6): VIS-10 = acessibilidade, VIS-11 =
> responsivo. (O despacho desta fatia trazia os dois trocados; vale a spec.)

- **VIS-07 completo no app novo** (`src/modes.ts`, funções puras + fiação):
  `?compare=<dir>` — comparador de frame final empresa por empresa (porte fiel
  de `compareRuns` do legado: união de nomes, quem falta vira `—`, totais,
  Δ sinalizado, falida em texto); `?forge=<dir>` — painel da forja com a
  sumarização 1:1 do legado (campeão S1/S2, semente, veredito, contagens,
  avaliação cega com Δ e IC95, stats do mutador por rota, linha do tempo das
  aceitas) a partir de `forge-v1.json`/`final_evaluation.json`/`run_log.jsonl`,
  **tolerante a artefato parcial** (só um dos arquivos → o que existe renderiza,
  o resto degrada para `—`; nenhum dos dois → mensagem no painel). Os dois
  modos têm cadeia de fetch **independente do replay** (falha neles não quebra
  o replay e vice-versa), mesma trava anti-`..` e mesmo formato de parâmetro.
  **Seletor de arquivo avulso** no header (o que faltava do VIS-07): aplica o
  `frames.json` escolhido pelo mesmo `applyRun` do `?run=`. Divergência
  intencional do legado, registrada na revisão pós-F6: stage fora de 0..5 é
  clampado para o rótulo mais próximo (coerente com VIS-12), em vez do `—`
  que o legado devolvia. A suíte estrutural
  do legado (`node viewer/test_replay.mjs`) segue verde **sem mudança de
  expectativa**, e o legado continua intocado.
- **VIS-10 acessibilidade:** foco visível global (`:focus-visible` dourado);
  todos os controles com rótulo textual (play com `aria-label`, velocidade e
  arquivo com `<label>`, scrub com `aria-label`); segmentos da barra da cadeia
  com estado/primeiro/tick em texto visível (sem foco inerte: o `tabindex` sem
  ação da F6 foi removido na revisão pós-F6); data do
  frame em `aria-live="polite"` discreto e `role="status"` no aviso de lente;
  mapa (canvas) com `role="img"` + descrição apontando a alternativa textual
  sincronizada (placar + legenda + cadeia + crônica em DOM); identidade nunca
  só por cor (F2/F3/F5) e `prefers-reduced-motion` agora também para a camada
  de fluxo (partículas estáticas, redesenhadas por render — sem loop de rAF).
  **Contraste medido** por `npm run contrast` (`scripts/check-contrast.mjs`):
  texto principal **16,01:1** (fundo) / **14,62:1** (painel) ≥ 4,5; secundário
  6,45:1/5,89:1, ouro 13,13:1, verde 11,81:1, rosa 7,99:1, azul 6,98:1 — os 12
  pares da paleta acima dos pisos (secundários ≥ 3:1).
- **VIS-11 responsivo:** breakpoints normativos conferidos por screenshot —
  ≥1024 layout completo (mapa + aside 380px); <1024 aside em pilha sob o mapa
  (mapa 60vh); <640 header quebra em linhas sem sobreposição, scrub em linha
  própria com **28px** de altura efetiva (alvo de toque ≥ 24px), segmentos da
  cadeia ≥128px empilhando 2+2+1, sem overflow horizontal em 390×844.
- **VIS-12 robustez:** `tests/robustness.test.ts` — corrida degradada (frame
  sem `prices`, empresa sem `stocks`, `stage` 7 e −2 clampados, crônica com
  kind desconhecido e evento sem texto, empresa falida) atravessa **todos** os
  renderizadores puros (feed, placar, cadeia, sankey, legenda, compare, forge)
  sem exceção; `frames.json` ausente/inválido cai na mensagem de fallback com
  orientação (seletor de arquivo incluído); artefatos parciais da forja
  cobertos em `tests/modes.test.ts`.
- **VIS-13 viewer burro:** o `dist/` é 100% estático e autocontido — prova
  extra: os screenshots abaixo foram capturados abrindo o `dist` por
  **`file://`** (com `--allow-file-access-from-files`), sem servidor nenhum.
  Motor intacto: pytest do repo **264 passed** e diff em `src/` = zero.
- **Screenshots §8.3** (`scripts/screenshots.mjs`, Chromium headless via CDP;
  nesta VM o Chromium 152 bloqueia até a navegação do próprio browser para
  127.0.0.1 — `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS` — por isso o
  caminho `file://`): `screenshots/` tem 1440×900 e 390×844 nos ticks 0 e 120
  + os modos compare e forge. Elas **pegaram 2 bugs reais**, corrigidos nesta
  fatia: (1) os 3 canvases empilhados tinham `background` opaco — a camada de
  fluxo escondia continente e entidades (o mapa "funcionava" sem nunca ter
  sido visto montado); agora só a base é opaca; (2) a linha do grid sem teto
  (`minmax(0,1fr)`) impedia a rolagem interna do aside. Nos screenshots
  finais: contorno e fronteiras visíveis, **Pré-sal no mar** junto à costa,
  marco `chain_link` distinto de rotina sem ler o texto, barra da cadeia com
  o elo 5 aberto, placar com Δ, painel da forja completo (veredito, campeão,
  cega com IC95, mutador, linha do tempo) e comparador com as 8 empresas
  (fixture `results/nascimento-v0` — a mesma corrida da servida, Δ 0 esperado).

### Definição de pronto (§10) — checklist final

1. **O continente está lá e o mundo é o certo** — ✓ screenshot tick 120:
   contorno/fronteiras da América do Sul, 11 cidades do `world_data`, os 10
   depósitos da corrida servida com nome/recurso/reserva.
2. **A crônica se lê como história** — ✓ F2: marcos óbvios, zero linhas
   vazias (119 itens), lote de novos com selo textual (visível no screenshot
   do modo compare).
3. **A barra da cadeia responde em 5 s quem lidera cada elo e o que falta** —
   ✓ Órbita nos ticks 1/2/5/8, elo 5 aberto + preço do supercomputador, no
   topo de todos os screenshots.
4. **Trocar de corrida via `?run=` muda tudo junto** — ✓ mesmo `applyRun`
   para servida/`?run=`/arquivo; replay, mapa, crônica, lentes e cadeia
   operam sobre a corrida carregada (contratos testados).
5. **Quem chega pelo GitHub vê capa, nome e premissa numa tela só** — ✓
   vitrine (PR #23) + lockup do viewer (F5).
- Suíte estrutural verde (Vitest **77/77** + legado `test_replay.mjs` OK),
  âncoras de dados conferidas por script (`npm run anchors`), screenshots
  batendo com as aceitações e **nenhuma linha de motor alterada**.

### Status dos requisitos (spec §6)

| Req | Status | Onde |
|---|---|---|
| VIS-01 mapa com contorno real | ✓ | F1 (+ correção de camadas na F6) |
| VIS-02 mundo orientado a dados | ✓ | F1 |
| VIS-03 crônica por kind/company | ✓ | F2 |
| VIS-04 destaque de evento novo | ✓ | F2 |
| VIS-05 lentes (mecanismo + Empresas) | ✓ | F3/F5 — demais lentes são fatias próprias (§4 da spec) |
| VIS-06 progresso da cadeia | ✓ | F4 |
| VIS-07 replay compatível | ✓ | F0–F2 parcial via legado → **completo no app novo na F6** |
| VIS-08 placar-ranking | ✓ | F3 |
| VIS-09 entrega pública | ✓ | F5 + vitrine |
| VIS-10 acessibilidade mínima | ✓ | F6 (contraste medido, teclado, foco, alternativa textual) |
| VIS-11 responsivo básico | ✓ | F6 (breakpoints + screenshots) |
| VIS-12 robustez | ✓ | F6 (`tests/robustness.test.ts`) |
| VIS-13 viewer burro | ✓ | dist estático; pytest 264; diff `src/` zero |

**Spec VISUAL-WOW fechada.** O viewer legado (`../viewer/`) segue intocado
como arquivo histórico/compatível; o `viewer-next` é a superfície atual.
