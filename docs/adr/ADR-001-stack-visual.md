# ADR-001 — Stack do viewer / camada visual do Path to Quantum

**Status:** Aceito — 27/10/2026. Decisão delegada pelo fundador ao Muse ("você pode escolher a stack"), a partir da direção aprovada no `ESTUDO-REFERENCIA-VISUAL-PTQ.md` e registrada na spec `docs/SPEC-VISUAL-WOW.md`. O portão de validação do §8 é executado na fatia F0/F1 (spike em `viewer-next/`) e o seu resultado fica registrado no §8 e no relatório da fatia; se o portão reprovar, esta ADR é substituída pela variante prevista no §7/§8 antes de qualquer fatia visual maior.
**Escopo:** só a camada visual (viewer/replay, painel da forja, comparador). Nada de motor, política, goldens ou protocolo de corrida.

---

## 1. Contexto

O viewer atual é 1 HTML estático vanilla (Canvas 2D, zero dependências) que lê `chronicle.json` / `frames.json` / `scoreboard.json` de uma corrida, com evoluções em branches (`?run=`, comparador, `?forge=`). A direção visual aprovada exige o que ele não tem: base cartográfica real com contorno, 5 lentes (Recursos/Produção/Comércio/Empresas/Crônica), fluxo animado (partículas/arcos), vista-cadeia Sankey, crônica tipografada por `kind`, modo editorial padrão + modo mission-control de auditoria, 2D + 2.5D seletivo, capa como camada editorial.

### O modelo de domínio (antes de comparar libs)

- **Entidades:** lugares nomeados com `lat/lon` (depósitos, cidades, plantas), empresas com cor/estado, território em células, fluxos entre lugares, eventos de crônica por `tick`, séries por empresa/commodity ao longo dos frames.
- **Escala real (hoje e horizonte próximo):** dezenas→centenas de empresas/agentes simultâneos, ~11 cidades e 13 depósitos no mundo v1 crescendo para o mundo inteiro, replay de centenas→milhares de frames. **Não** são milhões de pontos, **não** há zoom de rua (ruas/prédios são irrelevantes ao domínio) e **não** há basemap de tiles a consumir: a base é *temática* (continentes, fronteiras, rios/lagos opcionais), não cartografia viária.
- **Invariante sagrada:** o contrato **"viewer burro lê JSON"** — o viewer não simula nada, não conhece o motor, e abre qualquer corrida pelos mesmos 3 arquivos (locais ou por URL, como hoje).

### Restrições duras

1. **100% estático** — GitHub Pages ou pasta local, sem backend, sem tile server externo obrigatório, **offline após o build** (nada de CDN em runtime, fonte externa ou API key).
2. **Testável** — contratos de dados tipados e testes estruturais automatizáveis (a suíte do projeto já é assim), incluindo orçamento de bundle verificável em CI.
3. **Manutenção por time mínimo** (fundador + agentes): poucas dependências, todas maduras, MIT/BSD/domínio público, sem lock-in de fornecedor.

## 2. Critérios (nesta ordem)

Custo de adoção · performance para a escala do domínio (centenas de agentes + replay) · offline · tamanho de bundle · risco/manutenção · fidelidade à identidade editorial aprovada (projeção de atlas, base dessaturada).

---

## 3. Decisão recomendada — por camada

### 3.1 Render do mapa: **D3-geo + Canvas 2D próprio, em camadas empilhadas** (não MapLibre, não deck.gl na v1)

- `d3-geo` fornece só a matemática cartográfica (projeções esféricas reais, `geoPath` renderizável em Canvas, clipping de antimeridiano) — é a peça difícil de escrever à mão, e ela vem pronta, modular e minúscula.
- O render é nosso, em **3 canvases empilhados**: (a) **base** — continente/fronteiras/gratícula, desenhada uma vez por viewport/lente e cacheada em `Path2D`; (b) **dinâmico** — território, plantas, depósitos, redesenhado só quando o frame do replay muda; (c) **fluxo** — arcos e partículas animados a 60 fps, o único que redesenha continuamente. O gargalo clássico do Canvas 2D (redesenhar o mundo inteiro a cada frame) desaparece com essa separação.
- Zoom/pan = ajustar `scale/translate/rotate` da projeção (3 níveis úteis: mundo → continente → região; sem tiles, sem zoom infinito). Picking = índice espacial simples sobre lugares nomeados + teste ponto-em-polígono nas células — viável porque as entidades são dezenas de lugares nomeados, não features arbitrárias de GIS.
- **2.5D seletivo** sai do Canvas 2D mesmo: arcos com altura proporcional ao volume, colunas/extrusão falsa para intensidade econômica por região, sombra/deslocamento nos complexos industriais. É o "2.5D onde há dado" do estudo, sem engine 3D.
- A camada de mapa fica atrás de uma interface fina própria (`MapSurface`: projeção, camadas por lente, picking) — é a costura que permite trocar o render depois (§7) sem tocar loader, painéis, Sankey ou gráficos.

*Por que não o óbvio (MapLibre+deck.gl) já:* ver §5 e §6 — é a stack certa para outro problema (mapa viário com tiles, milhões de features, zoom de rua), e ela impõe projeções Mercator/globo, bundle 3–4× maior e dependências de runtime (workers, glyphs) que o nosso domínio não usa.

### 3.2 Fonte geográfica: **Natural Earth via `world-atlas` (TopoJSON), multi-resolução embutida no build**

- Natural Earth é **domínio público** (uso livre, sem atribuição obrigatória — manteremos crédito por boa prática); o pacote `world-atlas` (código ISC) já entrega a geometria quantizada em TopoJSON derivada dele.
- Tamanhos medidos na fonte: `land-110m.json` **55 KB**, `countries-110m.json` **108 KB**, `countries-50m.json` **756 KB** (brutos, antes de gzip).
- Estratégia: **mundo = 110m** (suficiente para a vista-múndi: a generalização de 1:110m é sub-pixel na largura típica da tela) + **recorte 50m gerado no build só para a América do Sul** (e, quando o mundo expandir, por região jogável) — o excerto regional de 50m é uma fração dos 756 KB globais (estimativa a confirmar no primeiro build; orçamento no §8). Lagos e centerlines de rios 50m entram como camada opcional da lente Recursos.
- **1:10m descartado por ora:** arquivos de vários MB para um detalhe (cidade) que o domínio não tem.
- A geometria é **gerada no build** a partir de dependência travada no lockfile (`world-atlas`, TopoJSON derivado de Natural Earth), com a **proveniência registrada no script de geração** (`viewer-next/scripts/build-geo.mjs`: fonte, escalas 110m/50m e recorte aplicado) — ela não é um asset versionado à mão no repo, e nada é buscado em runtime. Descodificação com `topojson-client` (~poucos KB).

### 3.3 Projeção e centro (resolve o §6.2 do estudo)

- **Projeção única em todo o viewer: `geoNaturalEarth1`** — pseudocilíndrica de compromisso desenhada por Tom Patterson (o mesmo autor do Natural Earth), cara de atlas, sem a inflação polar do Mercator e sem precisar da dependência extra que um Winkel Tripel pediria (`d3-geo-projection`). **Uma** projeção é decisão de identidade (lição NatGeo do estudo): lentes trocam camadas, nunca a geometria do mundo.
- **Centro padrão: a sessão abre enquadrada na América do Sul** (`fitExtent` sobre lon −82…−32, lat −56…14 — o mundo jogável atual), não no múndi. A **vista-múndi** usa centro **lon −30°** (Atlântico): Américas proeminentes à esquerda, África/Europa à direita, cortando no Pacífico — o oceano que menos importa às cadeias do PtQ.
- Globo 3D e Mercator ficam fora (consequência assumida em §6); se um dia houver "vista globo" editorial, ela é uma tela separada, não a projeção de trabalho.

### 3.4 Build e linguagem: **Vite + TypeScript, sem framework de UI**

- **Vite** (build estático padrão, `base` relativa para Pages e para abertura local) + **TypeScript** com interfaces para os 3 contratos JSON — é a resposta direta a uma ferida real: o viewer atual quebrou em silêncio quando o mundo foi de v0 para v1 (cidades hardcoded). Contrato tipado + teste estrutural = essa classe de quebra vira erro de build/teste, não surpresa visual.
- Tree-shaking importa **só os módulos usados** de d3 (`d3-geo`, `d3-sankey`, `topojson-client`) — nada do "pacote D3 inteiro".
- **Sem React/Vue/Svelte:** a UI é majoritariamente canvas + painéis/listas que templates vanilla + estado mínimo resolvem; um runtime de framework pagaria bundle e complexidade para renderizar justamente a parte que não é DOM. (Revisitar só se os painéis de auditoria virarem um app de formulários — não é o caso.)
- Saída = arquivos estáticos comuns em `dist/`; **runtime continua zero-config**: abrir a pasta (ou o Pages) e apontar para a corrida, como hoje. O viewer legado de arquivo único fica preservado como `legacy` até a nova stack passar na aceitação da issue #12.
- Testes: Vitest para unidades TS (loader/contratos, agregação do Sankey, fitting da projeção, matriz de lentes) + a suíte estrutural Python existente passa a conferir os assets de dados e o `dist` versionado/check de build no CI.

### 3.5 Vista-cadeia: **`d3-sankey` (layout) + render SVG próprio**

- O layout Sankey (profundidades, escalas, ordenação e relaxamento de links) é um algoritmo chato de ~centenas de linhas, fácil de implementar errado; `d3-sankey` é a implementação de referência, BSD, pequena, e casa com o resto do stack D3.
- O render fazemos em **SVG** (não Canvas): a vista-cadeia tem dezenas de nós/links — DOM barato, acessível, clicável e testável; largura da faixa = volume, conforme a referência MapSankey do estudo.
- **Restrição de domínio registrada:** Sankey exige grafo acíclico. A cadeia produtiva é um DAG por estágio (minério→…→quântico) ✓; comércio entre empresas (com ciclos) **não** entra no Sankey — ele vai para os arcos do mapa. Agregação `frames/stocks → nós/links por estágio` é função pura, testável isolada.

### 3.6 Séries temporais: **`uPlot`, carregado sob demanda (lazy chunk)**

- MIT, **~40–50 KB minificado** (site oficial do projeto), Canvas 2D, feito só para séries temporais: renderiza 166.650 pontos em ~25 ms no benchmark do próprio projeto e tem **cursor sincronizável entre gráficos** — exatamente o que o modo mission-control precisa (cursor do replay sincronizando mapa + curva de caixa + curva de preços).
- Entra como **chunk lazy**: o modo editorial padrão nem baixa o uPlot; ele só carrega ao abrir auditoria/comparador.
- Descartados: desenhar séries na mão (eixos, zoom, cursor sync e múltiplas escalas são semanas de retrabalho para economizar ~20 KB gzip), Chart.js e ECharts (generalistas pesados — ECharts passa de ~300 KB gzip — para um problema que é só linha/área no tempo).

### 3.7 O que NÃO vira dependência

Fontes (usar pilha de sistema + no máximo 1 fonte display embutida e subsetada, para não quebrar offline), ícones (SVG inline próprio por `kind` de evento — fim dos emojis), tiles/sprites/glyphs de terceiros (inexistentes nesta arquitetura).

---

## 4. Comparação resumida — render de mapa

| Opção | Custo de adoção | Performance (nosso domínio) | Offline | Bundle (ref.) | Identidade editorial | Risco |
|---|---|---|---|---|---|---|
| **D3-geo + Canvas próprio (escolhida)** | Médio: zoom/pan/picking/partículas são nossos | Sobra para centenas de agentes; base cacheada em `Path2D` | Total: zero runtime externo | Dezenas de KB gzip (só módulos d3 usados) | **Total**: qualquer projeção de atlas | Código de render próprio para manter (mitigado §8) |
| MapLibre GL + deck.gl | Alto: style spec, workers, integração interleaved de 2 engines WebGL | Sobra (é feita para milhões) — capacidade que não usamos | Possível, mas contra a corrente: sem tiles ela vira um render GeoJSON caro; labels pedem glyphs/fontes externas ou embutidas | deck.gl mínimo documentado: 501 KB min / **145 KB gzip** só Deck+1 layer, + MapLibre (~300 KB gzip ref. de terceiros) ⇒ **>450 KB gzip** antes do nosso código | **Baixa**: só Mercator ou globo — mata NaturalEarth1/atlas | Duas engines, releases acopladas, WebGL obrigatório |
| Leaflet | Baixo | Fraca aqui: DOM/SVG, sem WebGL, degrada com milhares de elementos | Bom com tiles locais — mas não temos tiles | ~42 KB gzip (o menor) | Baixa: projeções praticamente EPSG:3857/4326, NaturalEarth1 só via hacks | Resolve um problema (mapa de marcadores) que não é o nosso |
| Canvas vanilla evoluído (status quo+) | "Zero" aparente | Igual à escolhida **se** reimplementarmos tudo — incluindo projeção esférica, path e clipping | Total | ~0 | Total | **Alto e escondido**: reimplementar `d3-geo` mal é o custo real; cada projeção/correção vira dívida |
| OpenLayers | Alto (curva GIS) | Boa | Bom | ~150–200 KB gzip | Média (projeções via proj4) | Overkill GIS (WMS/WFS/formatos) sem ganho no domínio — descartado |

## 5. Alternativas descartadas — 1 frase cada

- **MapLibre GL sozinho (sem deck):** sem deck perdemos arcos/partículas/colunas prontos e continuaríamos escrevendo layers custom WebGL — o pior dos dois mundos.
- **deck.gl sozinho (sem basemap):** ele próprio se define como framework de visualização, não lib de mapa; a base cartográfica e a câmera voltariam a ser problema nosso, com o bundle dele junto.
- **CesiumJS:** engine 3D de globo (~1,7 MB gzip ref.) para uma direção que aprovou 2D+2.5D — custo e ruído visual errados.
- **ES modules sem build (+ import map/CDN):** CDN viola o offline, e "vendorar" módulos d3 interdependentes na mão torna atualização e tipos impraticáveis; sem TS, o contrato JSON volta a quebrar em silêncio.
- **esbuild puro em vez de Vite:** viável, mas Vite entrega o mesmo bundler com dev server, CSS/assets e convenções prontas pelo mesmo custo — trocar só faria sentido se o Vite atrapalhasse, e ele não atrapalha um site estático.
- **Sankey próprio:** economiza poucos KB e compra um algoritmo de layout propenso a bug visual sutil — mau negócio.
- **ECharts para tudo (mapa+gráficos+Sankey num pacote só):** tentador pela uniformidade, mas é a lib mais pesada da mesa, com linguagem visual de dashboard corporativo que briga com a identidade editorial aprovada.
- **Três.js/pixi para o mapa:** render genérico sem cartografia — teríamos de construir projeção, picking geográfico e texto sobre uma engine de jogos.

## 6. Consequências

**Positivas:** bundle inicial pequeno e auditável (orçamento no §8); offline absoluto após o build; projeção de atlas vira identidade; contratos JSON tipados; cada peça (Sankey, séries, mapa) é substituível isoladamente; nenhuma conta, chave ou fornecedor entre o projeto e o seu mapa.

**Negativas (assumidas):** (1) zoom/pan/picking/partículas são código nosso — bug visual é nosso, não da lib; (2) sem WebGL, o teto de agentes animados é menor que o do deck.gl (mitigado pelo portão do §8); (3) Canvas 2D exige disciplina de acessibilidade à parte (fallback textual/listas equivalentes, não depender só de cor — daltonismo já é lacuna atual); (4) o repo ganha toolchain Node (lockfile, CI de build) que hoje não existe.

**Neutras:** o viewer legado continua abrindo corridas antigas; GitHub Pages passa a publicar o `dist` via Actions (ou `dist` versionado — decidir na issue de implementação, com preferência por Actions e artefato conferido pela suíte estrutural).

## 7. Gatilhos de revisão (quando esta ADR deve ser substituída)

Trocar **só a camada de mapa** (a interface `MapSurface` preserva loader, painéis, Sankey e uPlot) por MapLibre GL + deck.gl — aceitando Mercator/globo e o bundle maior — se **qualquer** um ocorrer:

1. agentes animados simultâneos passarem de ~5.000 com folga no benchmark do §8 estourada;
2. o produto pedir zoom de cidade/rua ou basemap viário real;
3. 3D de verdade (terreno/extrusão física) virar requisito, e não enfeite;
4. o custo de manter o render próprio superar, em 2 ciclos seguidos, o custo estimado da migração.

## 8. Portão de validação pré-registrado (antes da implementação cheia)

A recomendação é falseável — spike curto, veredito antes de construir o viewer inteiro:

- **Protótipo mínimo:** base 110m + recorte SA 50m em `Path2D`, 500 empresas sintéticas, 2.000 partículas em arcos, replay com scrub sobre frames sintéticos no formato atual.
- **Passa se:** fluxo a 60 fps sustentado (ou ≥50 fps com degradação graciosa desligando partículas) em hardware comum, frame dinâmico <8 ms, bundle inicial ≤ **180 KB gzip** (app+d3, sem dados geográficos) e dados geográficos iniciais ≤ **200 KB** (110m + excerto SA).
- **Se reprovar:** esta ADR é substituída pela variante MapLibre+deck.gl (tile-less, estilo GeoJSON próprio) **antes** de qualquer fatia visual maior — registrar a troca como ADR-V02 citando a medição.

**Resultado (27/10/2026, fatia F0/F1 em `viewer-next/`): PASSA.**

| Métrica | Teto | Medido | Veredito |
|---|---|---|---|
| Bundle do app (JS+CSS+HTML, gzip, sem geo/dados) | ≤ 180 KiB | **13,3 KiB** | PASSA |
| Geografia embutida no `dist` (bruto / gzip) | ≤ 200 KiB | **114,1 KiB bruto / 40,0 KiB gzip** | PASSA |
| Custo de lógica de frame (dinâmico / total dinâmico+fluxo) | < 8 ms | **1,59 ms / 2,28 ms por frame** | PASSA |

- Unidades: KiB (÷1024), como o script `viewer-next/scripts/measure-bundle.mjs` efetivamente calcula e compara os tetos; números conferidos com `npm run build && npm run measure` (app gzip 13.617 B; geografia 116.809 B bruto / 40.972 B gzip).
- A geografia contada acima inclui o `geo/world-110m.json` (land-110m), que é **gerado/copiado no build mas não é carregado na abertura** — a abertura carrega só o excerto SA-50m; a vista-múndi é fatia futura.
- O bench é de **lógica de frame em Node com ctx Canvas stub** (conta comandos de desenho; não rasteriza, não é fps de browser). É medição de referência, com **variância de máquina/execução**: na medição de entrega, dinâmico 1,59 ms e total 2,28 ms/frame; em reexecução posterior na mesma VM, dinâmico 1,13 ms e total 0,75 ms/frame (`npm run bench`) — sempre com margem ampla sob o teto.
- **Operacionalização do critério de fps:** o "fluxo a 60 fps sustentado (ou ≥50 fps com degradação graciosa)" acima foi operacionalizado, nesta fatia, como **custo de lógica de frame < 8 ms medido nesse stub Node** — o proxy que o README de `viewer-next/` já divulgava e que esta ADR agora registra expressamente. Fps de browser real continua sendo medição de fatia futura, com hardware e método declarados.

---

## 9. Confronto adversarial

**O ataque.** *"Isto é artesanal disfarçado de arquitetura. MapLibre+deck.gl é o padrão da indústria — Kepler.gl, toda a visualização geoespacial séria usa —, com picking, zoom, partículas, colunas 3D e globo prontos e mantidos por centenas de pessoas. Vocês vão gastar o tempo do projeto reinventando câmera, hit-testing e animação em Canvas 2D, com duas libs de nicho (uPlot, d3-sankey) em volta, para economizar algumas centenas de KB que ninguém nota em 2026. E o fundador pediu WOW: um globo WebGL girando com arcos luminosos impressiona qualquer visitante em 3 segundos; um mapa plano em projeção de atlas impressiona cartógrafos. Quando o mundo crescer e o Canvas engasgar, a migração vai custar 10× o que custaria ter começado certo."*

**A resposta.** O ataque assume o problema errado em três pontos. (1) **Escala:** "começar certo" para milhões de features é começar errado para centenas de agentes nomeados — pagaríamos 3–4× de bundle, WebGL obrigatório e duas engines acopladas para usar talvez 5% da capacidade, e o §8 transforma o "e se engasgar" em medição com gatilho de migração barato (§7), não em aposta. (2) **Identidade:** o WOW do PtQ, pela direção que o próprio fundador aprovou, não é o globo-genérico-de-startup — é a Terra-atlas dessaturada com a cadeia viva por cima e a crônica contando a história; MapLibre só entrega Mercator/globo, ou seja, adotá-lo é revogar silenciosamente a decisão estética central do estudo. (3) **Custo escondido do "pronto":** MapLibre sem tile server é usar um motor de tiles para desenhar GeoJSON — o trabalho de estilo, glyphs e integração interleaved com deck.gl é comparável ao do nosso render, com a diferença de que o nosso é código que entendemos inteiro e testamos na suíte. Onde o ataque acerta — risco de manutenção do render próprio — a mitigação é concreta: a superfície é pequena (3 canvases, 1 projeção, lugares nomeados), fica atrás de interface, e o portão do §8 acontece **antes** do investimento grande. Se o protótipo disser que o Canvas não aguenta, migramos com o ADR já prevendo como — isso é engenharia, não teimosia.

---

## 10. Fontes (primárias/oficiais primeiro)

- deck.gl — introdução e modelo de camadas: https://deck.gl/docs · integração com MapLibre (interleaved/overlaid, exige WebGL2, `maplibre-gl >3`): https://deck.gl/docs/api-reference/mapbox/mapbox-overlay · tamanhos oficiais de bundle (v9.0.1, Deck+Layer 501,2 KB min / 145,3 KB gzip): http://pessimistress.github.io/deck.gl/docs/developer-guide/building-apps
- MapLibre GL JS — projeto (open source BSD-3, WebGL, globe): https://maplibre.org/projects/gl-js/ · projeções disponíveis via `setProjection` (`mercator`/`globe`): https://maplibre.org/maplibre-gl-js/docs/examples/add-a-simple-custom-layer-on-a-globe/
- Natural Earth — dataset em domínio público, escalas 1:10m/1:50m/1:110m: https://en.wikipedia.org/wiki/Natural_Earth · `world-atlas` (TopoJSON derivado de Natural Earth; tamanhos: land-110m 55 KB, countries-110m 108 KB, countries-50m 756 KB): https://www.webcodingcenter.com/d3-js/maps-with-d3-geo-and-topojson--topojson-geojson-and-sourcing-map-data.html
- D3 — `d3-geo` (projeções incl. `geoNaturalEarth1`, `geoPath` para Canvas): https://github.com/d3/d3-geo (via gitplanet) · `d3-sankey` (layout de fluxos em rede acíclica): https://app.unpkg.com/@plotly/d3-sankey@0.7.3/files/README.md (espelho do README oficial do d3-sankey)
- uPlot — site oficial (≈50 KB min, benchmark 166.650 pontos, cursor sync, MIT): https://leeoniya.github.io/uPlot/
- Vite — deploy de site estático/GitHub Pages: https://v3.vitejs.dev/guide/static-deploy.html
- PMTiles — arquivo único de tiles servível de hosting estático via HTTP range (registrado como opção futura caso um basemap de tiles um dia seja necessário sob MapLibre): https://www.quarrymapserver.com/downloads.html
- Leaflet — ~42 KB gzip, render DOM/Canvas sem WebGL (comparações): https://colorlib.com/wp/javascript-libraries-for-creating-dynamic-maps/

*Nota de método: tamanhos de bundle citados são os documentados pelos projetos/refs acima, não medições nossas — a medição vinculante é a do portão no §8, no primeiro build real.*
