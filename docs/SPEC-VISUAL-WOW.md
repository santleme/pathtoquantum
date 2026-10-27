# Spec — Fatia visual WOW do Path to Quantum

**Status:** Aceita — implementação iniciada pela fatia F0+F1 em `viewer-next/` (branch `viewer/wow-v1`), sobre a issue #12 (viewer/replay) e complementar à #20 (Rerun). Stack decidida em `docs/adr/ADR-001-stack-visual.md`.
**Data:** 27/10/2026 · **Origem:** estudo aprovado pelo fundador — `ESTUDO-REFERENCIA-VISUAL-PTQ.md` (§5 direção, §7 próximo passo), auditoria do visual atual, e conferência direta do viewer e dos JSONs servidos (abaixo, §0).
**Agnóstica de stack:** esta spec descreve comportamento e contrato; a stack vive na ADR-001.

**Decisões do fundador já tomadas (não reabrir nesta spec):** direção do estudo aprovada · tela padrão **editorial**, mission-control como modo · capa como **camada editorial** · **2D + 2.5D seletivo** · escolha da stack delegada ao Muse (ADR-001).

---

## 0. Contrato de dados — conferido nos arquivos reais (27/10/2026)

Tudo nesta spec se ancora no que os artefatos **já** entregam. Nada aqui pede campo novo ao motor.

### 0.1 `viewer/frames.json` (corrida servida hoje)
- Topo: `{seed: 42, ticks: 120, frames: [11], chronicle: [239]}`. Frames em ticks `0,12,…,120` (1 por ano) — **o replay é esparso por desenho dos dados**, não por bug do viewer.
- Frame: `{tick, date, prices, companies, deposits}`.
- `prices`: **11 commodities** — `lithium_ore, copper_ore, iron_ore, oil, lithium, copper, iron, plastic, component, device, supercomputer`. Na corrida servida: minérios e intermediários caem a ~30% do inicial (ex.: `lithium_ore 900→270`), `copper 9000→15520,6` e `iron 700→2100` sobem, **`device` (9500) e `supercomputer` (1200000) são constantes em todos os frames** — nenhuma aceitação pode exigir variação deles.
- `companies[8]`: `{id, name, archetype, color, hq, alive, cash, stage, territory:[[row,col]…], facilities:[{kind, cell}], stocks:{commodity: qty}}`.
  - `color` vem do motor (PALETTE de 8) — o viewer **não** inventa cor de empresa.
  - `stage`: inteiro `0..5`; rótulos atuais no viewer: `['—','extração','refino','componentes','dispositivos','SUPERCOMPUTADOR']`.
  - `facilities[].kind` observados: `mine, refinery, factory, plant` (o viewer atual também mapeia `assembly`, sem ocorrência nesta corrida).
  - `stocks` é **por empresa** (não existe `stocks` no nível do frame): chaves observadas `iron_ore, iron, oil, plastic, lithium_ore, copper_ore, lithium, copper, component`. **`device` e `supercomputer` nunca aparecem em `stocks`** nesta corrida (zero = ausente) — ausência significa 0, nunca erro.
  - Salto de estágio: `max(stage)` vai de 0 (tick 0) a 4 já no frame do tick 12; os marcos intermediários **não estão nos frames** — estão nos eventos `chain_link` da crônica (ticks 1, 2, 5, 8). Progresso de cadeia derivado só de frames perde a história (ver VIS-06).
- `deposits` **nos frames servidos: 10** (mundo v0): `{name, resource, cell, lat, lon, remaining_frac}`, `resource ∈ {lithium_ore, copper_ore, iron_ore, oil}`.
- `viewer/scoreboard.json`: lista final `[{name, archetype, alive, cash, stage, facilities:int}]` — placar de fim de corrida, sem série temporal.

### 0.2 Mundo v1 — `data/world_data.json` (a fonte completa)
- **11 cidades**: São Paulo, Rio de Janeiro, Buenos Aires, Santiago, Lima, Bogotá, Belo Horizonte, Porto Alegre, **Montevidéu, Assunção, Medellín** (cada uma `{name, country, lat, lon, …}`).
- **13 depósitos**: os 10 dos frames + **Salar del Hombre Muerto** (`lithium_ore`), **Cerro Verde (Arequipa)** (`copper_ore`), **El Mutún** (`iron_ore`) — mesmos 4 recursos.
- O viewer atual hardcoda só **8 cidades** (e com nome curto "Rio") em `index.html` — Montevidéu, Assunção e Medellín não existem na tela.
- ⚠️ **Armadilha central desta fatia:** a corrida servida ainda é do mundo v0 (10 depósitos nos frames). A spec exige o viewer **pronto para 13** sem fingir que a corrida atual tem 13: depósito/cidade exibidos vêm dos dados da corrida e da camada-mundo, nunca de lista fixa (VIS-02).

### 0.3 `viewer/chronicle.json` / `frames.json → chronicle` (239 eventos)
Evento: `{tick, kind, text, company, data, date}`. Distribuição real na corrida servida:

| kind | n | `company` | `data` | papel visual |
|---|---:|---|---|---|
| `flows` | 120 | `null` | `{companies:{cid:{delta, cash, flows:{…}}}}` | contábil, **`text` vazio** — não é narrativa |
| `tool` | 66 | empresa | `{}` | narrativa menor (campanhas InstaSim etc.) |
| `probe` | 16 | empresa | `{}` | narrativa (sondagem/achado) |
| `facility` | 14 | empresa | `{cid, fid, facility_kind, cell}` | narrativa estrutural |
| `mine` | 10 | empresa | `{cid, fid, facility_kind, cell, deposit}` | narrativa estrutural |
| `founding` | 8 | empresa | `{cid, cash, archetype, hq}` | narrativa fundadora |
| `chain_link` | 4 | empresa | `{}` | **marco** (primeira a dominar um elo) |
| `end` | 1 | `null` | `{}` | **marco** final |

- Taxonomia do SDD §4.1 prevê ainda, sem ocorrência nesta corrida: `god, bankruptcy, acquisition, record` — e o PRD/branches de crônica trabalham com noções de rivalidade/retrospectiva. **Kind desconhecido é caso esperado, não exceção** (VIS-03/VIS-12).
- Bug latente do viewer atual: `drawFeed` renderiza `flows` como itens vazios ("data — ") — metade do feed é ruído em branco.

### 0.4 Replay existente (branches, comportamento a preservar)
- `viewer/replay-url-marcos`: `?run=<dir>` carrega `<dir>/frames.json` (rejeita `..`), eventos da crônica têm `cursor:pointer` e clique salta ao frame do tick (`jumpToTick`), existe teste estrutural `viewer/test_replay.mjs` (Node `vm` + DOM stub, sem servidor).
- `viewer/comparador-corridas`: `?compare=<dir>` preenche painel de comparação de frame final; sem o parâmetro, nada muda.
- `viewer/painel-forja`: `?forge=…` painel da forja na mesma página/linguagem.
- Sem parâmetro nenhum: carrega `frames.json` ao lado e o seletor de arquivo continua existindo.

### 0.5 Capa e README (conferido)
- `assets/cover.webp` (849 KB) existe; `README.md` (158 linhas) tem **zero** referências a imagem (`img/webp/png/jpg` = 0 ocorrências). Viewer: `<title>` e `h1` ainda dizem "Mundo Autônomo / MUNDO AUTÔNOMO", sem favicon.

---

## 1. Problema

O PtQ é um produto para ser **assistido**, mas a sua superfície visual não sustenta isso:

1. O mapa promete "a Terra de verdade" e entrega uma grade lat/lon abstrata, sem contorno, com o mundo desatualizado (8 de 11 cidades, recursos reduzidos a 4 letras).
2. A crônica — o show do produto, nas palavras do PRD — renderiza 239 eventos ricos como texto idêntico, metade deles itens contábeis vazios.
3. Os dados mais eloquentes da simulação (`prices` de 11 commodities, `stocks` por empresa, progressão de `stage`) **já são gerados e nunca desenhados**: não há um gráfico, uma barra de cadeia ou um sinal de gargalo.
4. A identidade pública é zero: a melhor ilustração do projeto está órfã e quem acha o repositório encontra um README sem imagem e um viewer com o nome antigo do projeto.

Resultado: um visitante (ou o próprio fundador abrindo uma corrida nova) não enxerga em 5 segundos **onde** a história acontece, **quem** está ganhando, **em que elo** a corrida travou nem **o que acabou de acontecer**. É esse "WOW com leitura instantânea" que esta fatia entrega — sem tocar no motor.

## 2. Público

- **Primário — o fundador-observador:** abre o replay de uma corrida, acompanha a crônica como quem assiste a uma temporada, audita por que uma empresa travou/faliu, compara corridas. Técnico, mas está ali para assistir, não para depurar JSON.
- **Secundário — o visitante do GitHub:** chega pelo README, vê a capa, entende a premissa em uma tela ("empresas de IA numa corrida pela cadeia, na Terra real"), abre o viewer e a primeira tela tem de confirmar a promessa.
- **Não-público desta fatia:** jogadores (o PtQ não se joga como empresa), operadores de produção, leitores de tela como público principal (acessibilidade aqui é piso mínimo digno, VIS-10 — não certificação).

## 3. Escopo

- Mapa com contorno real sobre a projeção atual, camada-mundo completa e orientada a dados (VIS-01, VIS-02).
- Crônica desenhada por `kind`/`company`, com hierarquia e destaque de novidade (VIS-03, VIS-04).
- Mecanismo de **lentes** com a lente **Empresas** implementada, e cor resolvida por lente (VIS-05); placar refeito como ranking legível (VIS-08).
- Vista de progresso da cadeia a partir de `stage` + `chain_link` + `prices`/`stocks` existentes (VIS-06).
- Replay/scrub preservando `?run=`, clique-em-marco, `?compare=` e `?forge=` (VIS-07).
- Entrega pública: lockup capa+nome no README e viewer renomeado com favicon (VIS-09).
- Piso de acessibilidade e responsivo (VIS-10, VIS-11), robustez a corridas antigas/parciais (VIS-12) e preservação do contrato "viewer burro" (VIS-13).

## 4. Fora de escopo (explícito)

- **Motor, políticas, goldens, Kaggle:** nenhum arquivo de `src/mundo/` muda; nenhum experimento/corrida é lançado por esta fatia; nenhum campo novo é exigido dos artefatos.
- **Stack:** escolha de lib/framework, bundler, migração para app com build — ADR separado. Se a stack escolhida exigir build, VIS-13 define o que não pode quebrar.
- **Lentes Recursos, Produção, Comércio e Crônica** completas: esta fatia entrega o mecanismo de lentes + Empresas (VIS-05). As demais viram fatias próprias reusando o mecanismo.
- **Mission-control completo** (painéis compósitos estilo OpenMCT): é modo futuro; aqui só não se pode fechar a porta (o scrub continua sendo a fonte única de tempo, VIS-07).
- **Comparador e painel da forja refeitos visualmente:** só não-regressão (VIS-07). Redesenho deles é fatia deles.
- **Zoom/câmera livre, globo 3D, mapa do mundo inteiro além do recorte atual** (lon −82..−32, lat −56..14): a base deve ser extensível a novos recortes, mas nenhum recorte novo entra agora.
- **Rerun (#20):** continua exportador complementar; nenhum `.rrd` é gerado ou embutido aqui.
- **Arte nova:** nenhuma ilustração nova é encomendada/gerada; usa-se a capa existente. Derivados mecânicos (recorte/redimensionamento para favicon/OG) são permitidos.
- **Destaque visual de ferramentas específicas (VidSim/LojaSim) e ZapSim:** pendência da v1.1 fora desta fatia — eventos `tool` são tratados genericamente por `kind`.
- **Social preview do repositório** (imagem de preview nas configurações do GitHub): é ajuste manual de settings, fora do código; o README é a superfície pública desta entrega.

## 5. Princípios de desenho (da direção aprovada)

1. **Base estável, camada mutável** (Helsinki): o contorno e a geografia não mudam por lente nem por frame; quem muda é a camada de dados.
2. **Cor tem dono por lente** (estudo §5): nunca três paletas fortes ao mesmo tempo. Na lente Empresas, cor = empresa (a `color` do frame); estado (selecionada/em crise/falida) usa canal separado (anel, ícone, rótulo), padrão Flightradar24.
3. **Fluxo e progresso desenhados, não tabelados:** o que já está nos JSONs vira forma (segmentos de cadeia, faixas, marcadores), não mais texto.
4. **A crônica é narrativa:** evento contábil (`flows`) não disputa a tela com marco de cadeia.
5. **Dado manda, lista fixa não:** cidade, depósito, recurso e empresa vêm dos artefatos/camada-mundo versionada junto do viewer — nunca de array literal no código de desenho (a regressão das "8 cidades" não pode voltar).
6. **Viewer burro preservado:** artefato estático, sem servidor próprio, abrível do repositório; degrada com mensagem clara quando um JSON falta (o comportamento atual de fallback do `fetch` é o piso).

---

## 6. Requisitos

> Formato: cada requisito tem aceitação em dado/quando/então, verificável pelo método indicado em §8. "Corrida servida" = os `viewer/*.json` atuais (§0). "Corrida-fixture v1" = fixture mínima construída para teste com 11 cidades/13 depósitos (Tarefa F1), sem rodar o motor.

### VIS-01 — Mapa com contorno real
O mapa desenha o contorno reconhecível da América do Sul (costa, limites do recorte) sob os dados, na mesma projeção lat/lon atual, a partir de dado geográfico estático versionado com o viewer (sem fetch externo em runtime).
- **Dado** o viewer aberto com a corrida servida, **quando** o primeiro frame renderiza, **então** o contorno do continente é visível atrás de territórios/depósitos/cidades, e a grade de 10° deixa de ser o único referencial geográfico (pode permanecer, discreta, ou sair).
- **Dado** qualquer frame, **quando** o scrub avança, **então** o contorno é pixel-idêntico entre frames (a base não é redesenhada com variação).
- **Dado** um depósito em `lat −24,8 / lon −43,5` (Pré-sal), **quando** renderizado, **então** cai sobre o mar junto à costa — não sobre terra nem solto na grade (conferência visual por screenshot, §8).
- **Dado** o dado geográfico ausente/corrompido, **quando** o viewer carrega, **então** ele degrada para a grade atual com aviso no feed — nunca tela em branco.

### VIS-02 — Mundo completo e orientado a dados (fim do hardcode)
Cidades, depósitos e recursos renderizam a partir de dados, cobrindo o mundo v1 inteiro.
- **Dado** a corrida-fixture v1, **quando** o viewer carrega, **então** as **11 cidades** de `world_data.json` aparecem nomeadas (incl. Montevidéu, Assunção, Medellín e "Rio de Janeiro" por extenso) e os **13 depósitos** aparecem (incl. Salar del Hombre Muerto, Cerro Verde, El Mutún).
- **Dado** a corrida servida (v0, 10 depósitos nos frames), **quando** carrega, **então** renderiza exatamente os 10 dos frames — sem inventar os 3 ausentes no mapa de depósitos, e sem erro.
- **Dado** o código entregue, **quando** auditado, **então** não existe lista literal de cidades no código de desenho (a lista vive em dado: camada-mundo derivada de `world_data.json`, versionada no viewer).
- **Dado** um depósito, **quando** renderizado, **então** mostra nome (em rótulo, tooltip ou seleção), recurso com **nome legível** (não só a letra) e `remaining_frac` como barra/anel além do percentual textual atual.
- **Dado** o registro de recursos, **quando** consultado, **então** cobre as **11 commodities** de `prices` (4 minérios + `lithium, copper, iron, plastic, component, device, supercomputer`), cada uma com rótulo pt-BR e símbolo distinto; recurso desconhecido cai num fallback genérico rotulado com o nome cru do campo — sem sumir e sem quebrar.

### VIS-03 — Crônica por `kind`/`company`, com hierarquia
Cada evento renderiza conforme seu tipo e protagonista, numa hierarquia visual explícita.
- Hierarquia mínima (decrescente): **marco** (`chain_link, end, record, bankruptcy, acquisition`) > **estrutural** (`facility, mine`) > **fundação/sondagem** (`founding, probe`) > **rotina** (`tool, god`) > **contábil** (`flows`).
- **Dado** a corrida servida, **quando** o feed renderiza em qualquer frame, **então** nenhum item aparece vazio: os 120 eventos `flows` **não** viram itens narrativos individuais (são omitidos do feed ou agregados num resumo contábil expansível, à escolha da implementação — desde que nunca como linha em branco).
- **Dado** um evento com `company`, **quando** renderizado, **então** carrega o marcador da empresa na **cor do frame** + nome legível (cor nunca é o único canal — ver VIS-10); evento sem empresa (`company: null`) não ganha cor de empresa nenhuma.
- **Dado** um evento `chain_link`, **quando** renderizado, **então** é visualmente distinto de um `tool` sem precisar ler o texto (peso, selo de marco, agrupamento — forma livre, distinção obrigatória).
- **Dado** um `kind` fora da taxonomia conhecida (ex.: fixture com `kind: "rivalry"`), **quando** renderizado, **então** aparece com o estilo genérico de rotina e o texto integral — sem erro, sem sumir.
- **Dado** o frame final (tick 120), **quando** o feed é conferido contra `chronicle.json`, **então** os itens narrativos visíveis correspondem em contagem e ordem aos eventos não-`flows` com `tick ≤ 120` (239 − 120 = **119 itens** na corrida servida, se `flows` for omitido; se agregado, 119 + no máximo 1 resumo por período exibido).

### VIS-04 — Destaque de evento novo
Avançar o replay marca o que entrou — a lacuna nomeada da v1.1.
- Definição normativa: ao passar do frame anterior `F−1` ao frame `F`, são "novos" os eventos narrativos com `F−1.tick < e.tick ≤ F.tick` (no primeiro frame, os de `tick ≤ F.tick`; ao voltar o scrub, nenhum evento é "novo").
- **Dado** o replay parado no frame do tick 0, **quando** avança para o frame do tick 12, **então** os eventos com `1 ≤ tick ≤ 12` recebem a marca de novo (classe/anel/pulso — forma livre) e os de `tick 0` não recebem.
- **Dado** um evento marcado, **quando** o replay avança outro frame, **então** a marca sai dele e passa aos recém-chegados (a marca é do lote atual, não permanente).
- **Dado** o usuário arrasta o scrub para trás, **quando** o frame renderiza, **então** nenhum evento exibe a marca.
- **Dado** `prefers-reduced-motion` ativo, **quando** eventos novos entram, **então** a marca é estática (sem animação/pulso).

### VIS-05 — Lentes: mecanismo + lente Empresas, cor por lente
Existe um seletor de lentes; trocar de lente muda a camada sobre a **mesma** base e o **mesmo** frame.
- **Dado** o viewer carregado, **quando** o usuário troca a lente ativa, **então** mapa, placar e feed permanecem no mesmo `tick`/frame — só a camada de ênfase muda, sem recarregar JSON.
- **Dado** a lente **Empresas** ativa (a padrão), **quando** o mapa renderiza, **então** território/instalações usam a `color` de cada empresa vinda do frame, e o placar usa exatamente as mesmas cores para as mesmas empresas.
- **Dado** a lente Empresas ativa, **quando** uma empresa é selecionada (clique no placar ou no mapa), **então** ela ganha destaque por canal não-cor (anel/contorno/rótulo) e as demais recuam (alpha reduzido) — seleção nunca é comunicada só por troca de cor.
- **Dado** o mecanismo entregue, **quando** auditado, **então** registrar uma lente nova é declarar `{id, rótulo, camada}` num ponto único — as lentes futuras (Recursos/Produção/Comércio/Crônica) **não** são implementadas aqui, mas o seletor não pode ser um `if` espalhado pelo código de desenho.
- **Dado** uma lente que não seja Empresas selecionada nesta fatia (se a implementação expuser placeholders), **quando** ativada, **então** ela se apresenta como "em breve" sem alterar a camada — nunca como camada quebrada ou vazia sem aviso.

### VIS-06 — Progresso da cadeia (a vista que falta)
Uma vista sempre visível (barra de cadeia) mostra o estado da corrida rumo ao supercomputador/quântico, derivada **só** de `stage`, eventos `chain_link`, `prices` e `stocks` existentes.
- Conteúdo mínimo: os 5 elos nomeados (`extração, refino, componentes, dispositivos, SUPERCOMPUTADOR`) como segmentos; por elo, **quem o dominou primeiro** (dos `chain_link`) ou o estado "ninguém ainda".
- **Dado** a corrida servida no frame do tick 120, **quando** a barra renderiza, **então** os elos 1–4 constam como dominados com **Órbita Systems** como primeira (ticks 1, 2, 5, 8 nos `chain_link`) e o elo 5 consta aberto — conferível contra §0.1/§0.3.
- **Dado** o frame do tick 0, **quando** a barra renderiza, **então** nenhum elo consta dominado (os `chain_link` são de tick ≥ 1 e o `stage` de todas é 0).
- **Dado** qualquer frame, **quando** a barra renderiza, **então** cada empresa tem seu progresso individual visível como posição na mesma escala (`stage/5`, ex.: no placar ou na própria barra) — no frame final da corrida servida: Vetor Sul, Cuprum Andes, Nexo Indústrias e Órbita Systems em 4/5; Ferra Brasil e PetroPlata em 2/5; Lítio Austral e Andina Prime em 0/5.
- **Dado** os `prices` do frame, **quando** a vista de cadeia renderiza seu contexto de mercado, **então** mostra no mínimo o preço atual das commodities do elo mais alto em disputa **sem exigir variação** de `device`/`supercomputer` (constantes nesta corrida) e sem tratar ausência de `stocks` como erro (ausente = 0).
- **Dado** uma empresa com `stocks.component > 0` e `stage < 4`, **quando** inspecionada (seleção na lente Empresas), **então** seus estoques por commodity são legíveis em algum lugar da tela (lista/painel de seleção) — `stocks` deixa de ser dado morto.

### VIS-07 — Replay compatível (não-regressão das branches)
O comportamento conquistado nas branches é contrato, não sugestão.
- **Dado** a URL sem parâmetros, **quando** o viewer abre, **então** carrega o `frames.json` local, o scrub cobre todos os frames, play/pause e as 4 velocidades atuais funcionam, e o seletor de arquivo continua carregando um `frames.json` avulso.
- **Dado** `?run=<dir>`, **quando** o viewer abre, **então** carrega `<dir>/frames.json` (com rejeição a `..`), e toda a fatia visual nova (mapa, crônica, lentes, cadeia) opera sobre **essa** corrida — não sobre a servida.
- **Dado** um evento clicável na crônica, **quando** clicado, **então** o replay salta ao frame correspondente ao `tick` do evento (o de maior `tick ≤` o do evento), com o evento clicado visível e marcado no feed.
- **Dado** `?compare=<dir>` e `?forge=…`, **quando** presentes, **então** comparador e painel da forja continuam funcionando como nas branches de origem (o redesenho pode re-estilizá-los na nova linguagem, sem mudar o que mostram).
- **Dado** a suíte estrutural do viewer (padrão `viewer/test_replay.mjs`), **quando** executada, **então** os casos pré-existentes de `?run=`/`jumpToTick` passam sem alteração de expectativa.

### VIS-08 — Placar como ranking legível
- **Dado** qualquer frame, **quando** o placar renderiza, **então** cada empresa aparece com posição numerada (1..n), nome, arquétipo, caixa formatado e elo como **segmentos preenchidos** (n de 5) além do rótulo textual.
- **Dado** o frame final da corrida servida, **quando** o placar é conferido contra `scoreboard.json`, **então** a ordem é Vetor Sul (US$ 273,0M) > Ferra Brasil (US$ 70,2M) > Cuprum Andes (US$ 60,2M) > Lítio Austral > PetroPlata > Andina Prime > Nexo Indústrias > Órbita Systems (US$ 15,9M).
- **Dado** uma empresa com `alive: false` (fixture), **quando** renderizada, **então** consta marcada como falida por texto/ícone além do esmaecimento atual — nunca só por opacity/riscado.
- **Dado** dois frames diferentes, **quando** o usuário alterna entre eles, **então** a variação de caixa de cada empresa desde o frame anterior é sinalizada (seta/Δ) ou a ausência dessa sinalização é decisão registrada na PR — o placar não pode continuar um retrato mudo se houver Δ disponível nos próprios frames.

### VIS-09 — Entrega pública: capa, lockup e nome certo
- **Dado** o `README.md` entregue, **quando** aberto no GitHub, **então** a primeira tela mostra **lockup**: `assets/cover.webp` embutida no topo + título **Path to Quantum** + a tagline já existente no texto ("Eight autonomous AI companies. One real Earth…"), com `alt` descritivo na imagem.
- **Dado** o viewer entregue, **quando** aberto, **então** `<title>` e `h1` dizem **Path to Quantum** (o subtítulo pode citar a corrida/era), e **nenhuma** superfície visível usa "Mundo Autônomo" como nome do projeto.
- **Dado** o viewer e o README, **quando** auditados, **então** existe favicon derivado da capa (arquivo versionado) referenciado pelo viewer, e a legenda do mapa deixa de ser a explicação de 4 letras — substituída pela legenda viva da lente ativa (VIS-05).
- **Dado** a capa de 849 KB, **quando** embutida, **então** o README não ganha nenhum outro binário pesado nesta fatia (derivados de favicon/OG são arquivos pequenos, < 50 KB cada).

### VIS-10 — Acessibilidade mínima
- **Dado** qualquer empresa/evento/recurso, **quando** renderizado, **então** sua identidade nunca depende só de cor: empresa = cor + nome; recurso = símbolo + rótulo; estado (falida/selecionada/novo) = ícone/texto além da cor.
- **Dado** o feed da crônica, **quando** navegado por teclado, **então** eventos clicáveis (VIS-07) são focáveis e acionáveis por Enter/Espaço, com foco visível.
- **Dado** os controles (play, velocidade, scrub, lente, seletor de arquivo), **quando** auditados, **então** todos têm rótulo textual associado (o estado atual de `label` solto se mantém ou melhora — nunca regride para ícone sem nome).
- **Dado** texto sobre os fundos da paleta (base `--ink #e8ecf6` sobre `--bg #0b1020` e equivalentes novos), **quando** medido, **então** o contraste do texto principal é ≥ 4,5:1 e o do texto secundário ≥ 3:1; a paleta nova documenta os pares medidos na PR.
- **Dado** o mapa (canvas ou equivalente), **quando** inspecionado, **então** existe alternativa textual do estado do frame (a própria combinação placar+crônica em DOM conta, desde que sincronizada ao mesmo frame — VIS-05).

### VIS-11 — Responsivo básico
- Breakpoints normativos: **≥ 1024 px** layout completo (mapa + aside 380 px, como hoje); **< 1024 px** aside vira pilha abaixo do mapa; **< 640 px** controles do header quebram em duas linhas sem sobreposição.
- **Dado** viewport de 390×844, **quando** o viewer abre, **então** mapa, placar e crônica são alcançáveis por rolagem, nenhum texto é cortado horizontalmente e o scrub continua operável com o dedo (alvo ≥ 24 px de altura efetiva).
- **Dado** viewport de 1440×900, **quando** o viewer abre, **então** o layout é o completo atual ou melhor — sem regressão de densidade de informação.

### VIS-12 — Robustez a corridas reais (antigas, futuras, parciais)
- **Dado** uma corrida sem `prices` num frame (fixture degradada) ou com commodities fora do registro, **quando** renderiza, **então** mapa/crônica/placar funcionam e só a vista dependente degrada com aviso.
- **Dado** uma corrida com `stage` fora de `0..5` ou `kind` desconhecido, **quando** renderiza, **então** o item é clampado/rotulado genericamente — nunca exceção que pare o `render()`.
- **Dado** `frames.json` ausente, **quando** o viewer abre, **então** aparece a mensagem de fallback atual (ou equivalente) orientando o seletor de arquivo — comportamento de hoje é o piso.
- **Dado** artefatos parciais no estilo do painel da forja (só parte dos JSONs), **quando** carregados via `?run=`, **então** o que existe renderiza e o que falta degrada por painel, sem derrubar a página.

### VIS-13 — Contrato "viewer burro" preservado
- **Dado** o repositório clonado, **quando** o viewer é servido como arquivos estáticos (ex.: `python -m http.server` na raiz ou abertura via servidor simples), **então** tudo nesta spec funciona sem etapa de build obrigatória, sem servidor de aplicação e sem chamada de rede externa (ADR de stack pode propor build, mas a fatia só fecha se o artefato servido continuar estático e autocontido no repo).
- **Dado** a suíte do projeto, **quando** executada, **então** motor e goldens estão intactos (nenhum arquivo de `src/mundo/` alterado por esta fatia — conferência por diff).

---

## 7. Fatiamento (uma sessão por tarefa)

Ordem pensada para o **menor loop ponta-a-ponta verificável primeiro**: ao fim da F1 já existe algo que um visitante reconhece como "a Terra, com o mundo certo" — o resto empilha sobre essa base.

| Fatia | Entrega | Requisitos | Depende de | Paralelo com |
|---|---|---|---|---|
| **F0 — Base de integração** | Branch única da fatia a partir da linha do viewer mais avançada (`viewer/comparador-corridas`, que já inclui `?run=`+marcos), trazendo `?forge=` do painel; suíte estrutural do viewer verde antes de qualquer desenho. | VIS-07 (linha de base) | — | F5 (pode começar pelo README) |
| **F1 — A Terra de verdade** | Contorno estático versionado + fim do hardcode: camada-mundo em dado (11 cidades), depósitos por dado com nome/recurso/`remaining_frac` desenhado; fixture v1 mínima para teste. **É o loop mínimo:** abrir → ver o continente e o mundo certo. | VIS-01, VIS-02 | F0 | F2, F5 |
| **F2 — A crônica vira show** | Feed por `kind`/`company` com hierarquia, `flows` fora da narrativa, fallback de kind desconhecido, destaque de evento novo. | VIS-03, VIS-04 | F0 (não depende do mapa) | F1, F5 |
| **F3 — Lente Empresas + placar** | Mecanismo de lentes (registro único), lente Empresas padrão com seleção por canal não-cor; placar como ranking com posição, segmentos de elo e estado de falida. | VIS-05, VIS-08 | F1 (usa a camada de empresas sobre a base nova) | F5 |
| **F4 — Barra da cadeia** | Vista de progresso por elo (primeiro a dominar, por empresa, contexto de preços/stocks na seleção). | VIS-06 | F2 (consome `chain_link` já classificado) e F3 (seleção de empresa) | — |
| **F5 — Entrega pública** | Lockup capa+nome no README, viewer renomeado, favicon derivado, legenda viva substituindo a legenda de 4 letras (esta última parte espera F3). | VIS-09 | — (favicon/README desde já); legenda espera F3 | todas |
| **F6 — Piso e portão final** | Passada de acessibilidade/responsivo sobre tudo; testes de robustez (fixtures degradadas); regressão completa `?run=`/`?compare=`/`?forge=`; screenshots finais desktop+mobile arquivados na PR. | VIS-10, VIS-11, VIS-12, VIS-13, VIS-07 (portão) | F1–F5 | — |

Regras do fatiamento: cada fatia fecha com sua verificação (§8) verde antes de a próxima começar sobre ela — exceto os pares marcados como paralelos, que tocam regiões disjuntas (F1=mapa, F2=aside/crônica, F5=README/cabeçalho). Divergência de branch do viewer é o risco histórico nº 1 (auditoria §1): **proibido** abrir segunda branch de viewer enquanto uma fatia estiver aberta.

## 8. Verificação (como provar cada aceitação)

1. **Teste estrutural (padrão da casa):** estender o modelo de `viewer/test_replay.mjs` (Node `vm` + DOM/canvas stub, sem servidor, sem DOM real). Casos mínimos novos: (a) sem parâmetros carrega `frames.json` local; (b) fixture v1 → 11 cidades e 13 depósitos presentes na saída de desenho/DOM; (c) fixture servida → feed narrativo com 119 itens e 0 itens vazios; (d) avanço tick 0→12 → lote "novo" = eventos `1..12`; (e) clique em evento → frame salta; (f) kind desconhecido e frame sem `prices` → render sem exceção.
2. **Conferência de dados contra os JSONs (script, não olho):** script de checagem que lê `frames.json/chronicle.json/scoreboard.json` e imprime os valores-âncora desta spec — ordem e caixa do placar final (VIS-08), primeiros por elo e ticks (VIS-06), contagem de kinds (VIS-03), 11 commodities do registro de recursos (VIS-02). A PR cola a saída; divergência entre âncora e tela é defeito da fatia, não do script.
3. **Screenshot (prova visual):** capturas em 1440×900 e 390×844, frames tick 0 e tick 120, lente Empresas: (a) contorno reconhecível e Pré-sal no mar (VIS-01); (b) marco `chain_link` distinto de `tool` sem ler texto (VIS-03); (c) barra da cadeia com elo 5 aberto (VIS-06). Screenshot é evidência anexada à PR, não teste automatizado de pixel.
4. **Auditoria de código:** busca por lista literal de cidades no código de desenho (VIS-02) e por "Mundo Autônomo" em superfícies visíveis (VIS-09) — ambas têm de retornar zero (exceto menções históricas em docs/changelog).
5. **Regressão:** suíte estrutural pré-existente do viewer verde sem mudança de expectativa (VIS-07); suíte Python do projeto verde com diff vazio em `src/mundo/` (VIS-13).

## 9. Riscos

| Risco | Impacto | Mitigação nesta spec |
|---|---|---|
| **Frames esparsos** (11 frames/120 ticks): estágio salta 0→4 entre dois frames; usuário pode ler a barra da cadeia como "teletransporte" | Alto na leitura da VIS-06 | Barra ancora marcos nos `chain_link` (ticks reais 1, 2, 5, 8), não interpola frames; destaque de novo é por lote de ticks (VIS-04), nunca por evento individual fingindo granularidade que o dado não tem |
| **Corrida servida ainda é v0** (10 depósitos) enquanto o mundo v1 tem 13 | Alto: "consertar" hardcodando 13 falsifica a corrida atual | VIS-02 é orientado a dados nos dois sentidos, com aceitação explícita para 10 (servida) e 13 (fixture) |
| **`flows` domina a crônica** (120/239, texto vazio) | Médio: feed continua ruído se tratado como narrativa | VIS-03 tira `flows` da narrativa com aceitação contável (119 itens) |
| **Dado geográfico do contorno**: fonte, licença e peso do polígono podem inchar o viewer ou criar dependência externa | Médio | VIS-01 exige dado estático versionado, sem fetch em runtime; simplificação do polígono é decisão da F1 registrada na PR (fonte pública tipo Natural Earth, domínio público, é o caminho esperado — registro, não imposição) |
| **Divergência de branches do viewer** (3 evoluções já viveram separadas) | Alto e já aconteceu | F0 fixa a linha de base e a regra de branch única por fatia (§7) |
| **Paleta de 8 empresas × daltonismo** e colisão cor-de-empresa × cor-de-estado | Médio | Cor nunca é canal único (VIS-05, VIS-08, VIS-10); estado usa anel/ícone/texto |
| **Preços constantes** (`device`, `supercomputer`) lidos como bug da vista | Baixo | VIS-06 proíbe exigir variação e manda mostrar o valor como está |
| **Capa pesada (849 KB) no README** | Baixo | VIS-09 limita binário novo e aceita a capa como está (otimização de peso é fatia futura, se incomodar) |
| **Kinds futuros** (`rivalry`, `era_summary`, `record`, `bankruptcy`, `acquisition`, `god`) quebrarem o feed ao chegarem | Médio e provável | VIS-03/VIS-12 tratam kind desconhecido como caso esperado, com fixture de teste |

## 10. Definição de pronto da fatia WOW

A fatia está pronta quando, abrindo o viewer com a corrida servida: **(1)** o continente está lá e o mundo é o certo; **(2)** a crônica se lê como história — marcos óbvios, nada de linhas vazias, o que é novo salta aos olhos; **(3)** a barra da cadeia responde em 5 segundos "quem lidera cada elo e o que falta"; **(4)** trocar de corrida via `?run=` muda tudo isso junto; e **(5)** quem chega pelo GitHub vê capa, nome e premissa numa tela só. Tudo isso com a suíte estrutural verde, as âncoras de dados conferidas por script e os screenshots da PR batendo com as aceitações — sem uma linha de motor alterada.
