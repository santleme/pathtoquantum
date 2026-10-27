# DEGRAU 1 — LOG DE FASES
### Portões medidos, fase a fase (protocolo: docs/DEGRAU1-DESIGN.md §5)

## Fase 1 — Python oficial enxuto (26/10/2026)

**Entregue**
- Goldens §3.5 congelados como teste executável (`tests/test_golden.py`):
  SHA-256 do `state_dict` completo, calculados sobre o motor pré-Degrau 1
  (seed 42: n=8×24 `e01923e1…`, n=100×24 `24b1b3bf…`, n=8×120 `74412ded…`,
  n=8×24 mundo builtin `83e1fa20…`).
- Fundação struct-of-arrays onde o design manda: `chain.COMMODITY_INDEX`
  (índice inteiro por commodity) + `companies.StockBook` — estoques viram
  UM array plano por empresa (a linha da tabela `stocks (N, C)`), com
  protocolo Mapping completo por nome por fora. Caminhos quentes por
  índice: `_market` (comércio interno e vendas às cidades), `_convert`,
  `_produce` (mina/fábricas) e a transferência de ativos na aquisição.
- `mundo/tables.py`: projeção SoA somente-leitura (`cash (N,)`,
  `stocks (N, C)`, `prices (C,)`, `anchors (C,)`) — a ponte do núcleo
  nativo (Fase 5) e de drivers de treino; provado que não muta o motor.
- `mundo/driver.py`: driver de episódios multiprocesso — specs
  independentes, resultados **na ordem das specs** (agregação
  determinística), série == paralelo == Engine direto (teste).

**Portão medido** (VM de dev, 2 vCPU, Python 3.12.3)
- Suíte: **61/61 verde**; goldens **bit-idênticos** (4/4) após o refactor.
- ms/tick pós-refactor: n=8 **0,334** · n=100 **2,216** — neutro contra o
  baseline do Portão 0 (2,042 a n=100; dentro do ruído entre protocolos).
  Confirma o Portão 0: o ganho da Fase 1 NÃO é micro-otimização de tick.
- Driver (episódios de 120 ticks): n=8 serial **19,5 ep/s** → 4 processos
  **21,0 ep/s** (1,08×); n=100 serial **2,8 ep/s** → **3,6 ep/s** (1,27×).
  A VM tem **2 vCPU** — 4 processos sobrescrevem o hardware; o teto aqui
  é núcleo, não driver (no Kaggle, 4 vCPU, espera-se ~3–4×).
- Projeção recalculada (10M ticks, n=100, mundo rico ×2,5, ÷4 proc.):
  **≈231 min > 45 min** — a Fase 5 (núcleo nativo) segue necessária e
  aberta pelo Portão 0; a fila Fases 2–4 não muda.

**Fora da fase (registrado, não forçado)**
- Hotspot 5 (`_emit_flows` enxuto) muda o payload do evento `flows`:
  continua fora do pacote bit-idêntico, aguardando decisão de regravar
  goldens (design §3.5).
- Hotspot 3 (total corrente no `_market`): ~1,03× sem garantia de
  bit-identidade por construção — não entrou (Portão 0 já o havia
  reprovado como otimização).

## Fase 2 — B1 Mercado vivo (26/10/2026)

**Entregue**
- `Engine(market_v2=True, market_params=None)` — flag nova, desligada por
  padrão. Desligado: nenhum RNG extra, nenhum bloco no `state_dict`,
  goldens da Fase 1 **bit-idênticos** (suíte confirma).
- Mecânica (design §4/B1): demanda das cidades elástica
  `D = D0·(p/p*)^(−ε)·saz(t)` (ε: lítio 0,3; cobre 0,4; ferro 0,5;
  componentes 0,7; device 1,0; supercomputador 1,2); sazonalidade anual
  leve; preço justo = âncora × `exp(−γ(I−I*))` × ruído, com a cobertura
  `I` = estoque AGREGADO ÷ EMA de demanda — pública estilo LME, estoques
  por empresa seguem privados (fog-of-war testado); regimes Markov
  boom/normal/bust com durações médias e deriva de âncora calibradas
  (lítio: boom 24m/bust 30m, σ 9%/mês — ciclo USGS 2020–2025); banda de
  preço [0,25×; 6×] **da âncora** (a antiga, do base fixo, morreu).
  O ajuste por desequilíbrio continua, sobre a demanda elástica.
- Parâmetros como DADO: `data/market_params.json` com nota de
  calibração e fontes por commodity (USGS MCS 2025, LME, World Bank
  Pink Sheet) + loader/validador `mundo/marketdata.py` com fallback
  embutido idêntico (o bundle do Kaggle não carrega `data/`) — teste
  garante que arquivo e fallback nunca divergem.
- Acoplamento preparado (sem B3): âncora `p*` exposta como série
  pública — `engine.anchors`, `result()["market"]`, frames com bloco
  `market` (âncora/cobertura públicas; regime visível só na visão de
  Deus dos frames — empresas inferem do preço) e `tables.anchors_table`.
- Crônica: kinds novos `market_regime` (só entradas em boom/bust) e
  `price_record` (extremo da janela de 24 meses) registrados em
  `chronicle.py`. **Lição de calibração:** a primeira versão gerava
  172 recordes/120 ticks (toda derrapada longa vira "recorde" mensal =
  ruído, viola o princípio B0.4); com recordes por **episódio**
  (reversão ≥5% do extremo encerra o episódio) caiu para **26/120
  ticks** na seed 42, com 27 viradas de regime.
- `driver.EpisodeSpec` ganhou `market_v2`/`market_params`.
- Notebook de veredito **preparado, não lançado**:
  `notebooks/veredito-b1.ipynb` — corridas pareadas on/off (seeds
  42/7/11/23, 120 ticks), comparativo de vivacidade (eventos
  salientes, rivalidades, amplitude de preços) + placar + checagem de
  ledger, com regra de aprovação pré-registrada impressa pelo próprio
  notebook. O lançamento no Kaggle é do agente pai (precisa de bundle
  novo do fonte: src3).

**Portão medido** (VM de dev, 2 vCPU)
- Suíte: **76/76 verde** (61 + 15 do B1: ledgers, fog-of-war, replay,
  snapshot/restore cruzando viradas de regime forçadas, banda da
  âncora, episódios de recorde, arquivo==fallback).
- Custo do B1: a estimativa "<1–2% do tick" do estudo/design **não se
  confirmou de primeira** (+12% medido a n=100). Causa: a cobertura
  exige a agregação de estoques que o mercado clássico não fazia, e a
  matemática por commodity é custo fixo por tick. Após otimização
  (totais uma vez por tick via SoA, sazonalidade uma vez por tick,
  fórmulas inline no caminho quente), o custo fixo é ~0,1 ms/tick e as
  medições intercaladas a n=100 caíram para dentro do ruído desta VM
  (medianas entre −8% e +9% conforme a rodada — a VM tem 2 vCPU
  compartilhadas). **Portão de ≤2%: não comprovado nesta VM**; a
  medição limpa fica para a corrida de veredito no Kaggle (4 vCPU).
  Impacto na projeção do Portão 0: desprezível (213 → ~230 min no pior
  caso; a Fase 5 segue aberta e necessária pelo mesmo motivo).

**Fora da fase**
- Calibração fina contra momentos das séries reais (volatilidade,
  autocorrelação, duração de ciclo simulados × USGS/LME): é o notebook
  de calibração previsto no design §5/Fase 2 — o de veredito acima
  mede vivacidade; momentos estatísticos ficam como próximo notebook.
- Observação local (seed 42, 120 ticks): o lítio refinado bate o piso
  da banda no ano 1 (estoque sobe rápido, demanda elástica encolhe com
  preço alto) — comportamento a julgar na calibração, não corrigido
  por achismo aqui.
- B3/B4a/B2: fases seguintes, sem código adiantado além do gancho da
  âncora pública.

## Fase 3 — B3 País/política + B4a Importações (26/10/2026)

**Entregue** (código atrás de flag; a ADOÇÃO aguarda os vereditos do
B1 e desta fase, como o B1 entrou)
- `Engine(country_v2=True, country_params=None)` — flag nova,
  desligada por padrão. Desligado: nenhum RNG extra, nenhum bloco no
  `state_dict`, goldens da Fase 1 **bit-idênticos** (suíte confirma).
- **B3**: estado por país — estabilidade `S` (reversão à média
  0,03/mês + ruído 0,02; baselines WGI/ICRG como DADO: Chile 0,65,
  Brasil 0,45, Peru 0,40, Argentina 0,35, Bolívia 0,30, + Colômbia
  0,38, Uruguai 0,75, Paraguai 0,45), câmbio-índice `e` (persegue a
  estabilidade: país abaixo da própria média desvaloriza) e royalties
  `τ`. Efeitos: capex ×(1 + 0,25·(1−S)) nas minas (país do depósito)
  e no jusante (país da sede), via `Engine.capex_mult` — exatamente
  1,0 desligado; royalties = τ × opex efetivo, **sink nomeado**
  (`spend_royalty` nos flows, agregado por empresa/tick); câmbio
  sobre a fração local do opex (λ=0,45): `opex·[(1−λ) + λ/e]`.
  Motor de eventos endógeno generalizando os atos de Deus —
  probabilidades ANUAIS por país (mensal = perigo constante):
  reforma de royalties 6% **dobrando se o preço de uma commodity do
  país > 1,5× a âncora** (lê `engine.anchors`: com B1, a âncora viva;
  sem B1, o preço-base — o acoplamento B1→B3), restrição de
  exportação 2%, JV estatal 1,5%, paralisação judicial 0,7%,
  subsídio 4%, desastre 1%; eleição a cada 48 ticks (calendário
  escalonado por país) deslocando `S̄` (±0,18) e o regime de `τ`.
  Paralisação/desastre param as minas do país (sem produzir e sem
  opex). `S`/`e`/`τ` são PÚBLICOS (frames e `result()["politics"]`);
  probabilidades, nunca. Crônica: kind `politics` com o tipo em
  `data["event"]`, narrando país, commodity e efeito — transições,
  não ruído mensal.
- **B4a**: pseudo-participante elástico na paridade por commodity —
  importação `p*·(1 + tarifa 0,12 + frete 0,08)`, exportação
  `p*·(1 − frete)`, capacidade elástica ∝ spread (fator 2 sobre a
  demanda urbana ou a escala de minério). Acima da paridade, o
  exterior atende compras das empresas não preenchidas e a demanda
  das cidades não atendida; abaixo, absorve o excedente ofertado. O
  fluxo externo entra na formação de preço (importado = oferta
  efetiva, exportado = demanda efetiva) — é assim que a paridade
  tampa explosões do mundo fechado. Contabilidade: massa importada
  vira a chave `imported` do `ledger_mass` (só existe com a flag
  ligada) e exportada soma em `sold_external`; o dinheiro atravessa
  a conta "externo" (`money_to_external`/`money_from_external`) —
  **a conservação fecha incluindo a conta externo**, com invariante
  novo testado. Restrição de exportação do B3 morde por aqui:
  enquanto ativa, multiplica as paridades da commodity bruta e do
  seu refinado por (1 + 0,6).
- Parâmetros como DADO: `data/country_params.json` + loader/
  validador `mundo/countrydata.py` com fallback embutido idêntico
  (teste garante) e os mapas nome→país dos dois mundos (embutido e
  realdata), com normalização de grafia (a fonte oscila
  Bolivia/Bolívia) e fallback por vizinho mais próximo para
  depósitos descobertos por Deus — função pura das tabelas
  estáticas, idêntica antes/depois do restore. `force_events` nos
  parâmetros é o gancho de eventos forçados (teste/Deus) e não
  consome RNG. `driver.EpisodeSpec` ganhou `country_v2`/
  `country_params`; `tables.countries_table` projeta (P, 3) de
  S/e/τ.
- Notebook de veredito **preparado, não lançado**:
  `notebooks/veredito-b3.ipynb` — corridas pareadas (seeds
  42/7/11/23, base B1 × B1+B3/B4a, 120 ticks), métricas de
  vivacidade (eventos políticos por tipo, amplitude de preços,
  falências e causas, royalties pagos, comércio externo) + checagem
  dos dois ledgers com a conta externa, com regra de aprovação
  pré-registrada impressa pelo próprio notebook. O lançamento no
  Kaggle é do agente pai (precisa de bundle novo do fonte).

**Portão medido** (VM de dev, 2 vCPU compartilhadas)
- Suíte: **118/118 verde** (92 + 26 da Fase 3: ledgers com a conta
  externo e a fonte imported, fog-of-war, replay, snapshot/restore
  cruzando 4 eventos políticos forçados, paralisação judicial,
  royalties/câmbio no opex, paridade e restrição, importação/
  exportação unitárias no mercado clássico, goldens intactos).
- Custo combinado B3+B4a: o alvo de <2% do tick **não foi atingido**
  nesta VM. Medianas intercaladas a n=100 (3 lotes, 5–7 rodadas):
  **+7% a +14%** sobre as bases clássica/B1; a n=8, **+26% sobre o
  B1** — o custo tem termos fixos O(países + commodities) por tick
  (avanço político, paridades, blocos de frame) que pesam sobre o
  tick-base pequeno, embora o absoluto seja modesto (~0,3 ms/tick a
  n=8; ~0,4–0,8 ms/tick a n=100). Três rodadas de otimização sem
  mudar aritmética nem RNG (cache de recursos por país, rastreio de
  recebimentos só acima da paridade, varredura do participante
  externo só sobre compradores não atendidos, royalties agregados
  por empresa/tick, memo de capex por (país, S)) derrubaram o custo
  do perfil inicial, mas não abaixo do alvo. Como na Fase 2, a
  medição limpa fica para a corrida de veredito no Kaggle (4 vCPU).
  Impacto na projeção do Portão 0: desprezível — a Fase 5 (núcleo
  nativo) segue aberta e é o remédio estrutural; o tick a n=8 das
  temporadas/vereditos continua em ~1 ms mesmo nesta VM carregada.

**Fora da fase**
- Gancho do BancoSim (spread de juros a partir de `S`, tipo EMBI):
  o desenho do estudo o prevê; entra quando existir banco.
- Importações servindo a demanda das cidades: implementadas como
  atravessamento contábil (imported e sold_external se cancelam no
  estoque, sem tocar `money_in`, que mede vendas DAS empresas) —
  registrado aqui porque é uma decisão de contabilidade, não um
  detalhe: a alternativa (creditar money_in) misturaria receita das
  empresas com receita do exterior.
- B2 (equipamentos): Fase 4, sem código adiantado.

## Fase 3 — lançamento do veredito B3 no Kaggle (26/10/2026)

- Bundle novo do fonte pós-Fase 3 como dataset
  `pascalcoimbra/mundo-autonomo-src5` (ZIP `mundo-src.zip` com `src/` +
  `pyproject.toml`, mesmo mecanismo dos bundles anteriores),
  verificado por download: `engine.py` byte-idêntico ao repo (md5),
  com `country_v2`.
- Kernel `pascalcoimbra/ptq-veredito-b3-pais-e-importacoes`
  (kernelId 141077952) empurrado com
  `datasetDataSources=["pascalcoimbra/mundo-autonomo-src5"]`.
- **Descoberta de infra (kernel-sonda, mesmo dia):** o Kaggle mudou o
  layout do mount de datasets — eles NÃO aparecem mais em
  `/kaggle/input/<slug>/` com o zip dentro, e sim em
  `/kaggle/input/datasets/<dono>/<slug>/` com a árvore JÁ EXTRAÍDA
  (sem zip). O loader antigo dos notebooks (glob
  `/kaggle/input/*/src` + busca do `mundo*.zip`) não encontra o fonte
  nesse layout: foi essa a causa das mortes na largada (a v1 e a v2
  deste kernel, e as do torneio v1) — NÃO prontidão/montagem do
  dataset. Correção aplicada à célula 1 do `veredito-b3.ipynb`
  (commit `3ce0ee9`): busca recursiva
  `glob('/kaggle/input/**/src/mundo/__init__.py', recursive=True)`
  aceitando os dois layouts, com fallback para o zip; a mensagem de
  erro do loader novo traz o marcador "(loader recursivo)" para o
  monitor distinguir falha nova de log de versão antiga. Kernel
  re-empurrado como **versão 3** com o loader corrigido.
- Monitor `monitor-veredito-b3` (cron da meta, ~15 min): nas checagens
  desta entrega o endpoint de outputs ainda não mostrava log nem
  arquivos da v3 e NENHUM sinal de erro (sem PapermillExecutionError,
  sem SystemExit de nenhum dos loaders) — consistente com
  fila/execução; a confirmação positiva de largada e o veredito são
  do monitor, que baixa outputs para `results/veredito-b3/`, commita
  e reporta quando a corrida concluir.

## Fase 4 — B2 Equipamentos (26/10/2026)

**Entregue** (código atrás de flag; a ADOÇÃO aguarda o veredito desta
fase, como nas anteriores)
- `Engine(equip_v2=True, equip_params=None)` — flag nova, desligada
  por padrão. Desligado: nenhum estado por instalação, nenhum RNG,
  nenhum bloco no `state_dict`, goldens da Fase 1 **bit-idênticos**
  (suíte confirma; teste dedicado prova que nenhuma instalação ganha
  a chave "equip" e que os frames ficam byte-idênticos).
- **Mecânica** (design §4/B2): estado por instalação no dict da
  própria instalação (chave "equip", criada preguiçosamente pelo
  motor): `age` (meses), `cond` h ∈ (0,1], `down_until`, `broken` +
  cotação de reparo. Capacidade efetiva
  `capacity · h · (1 − 0,15·min(1, age/240))` aplicada em mina,
  refinaria e fábricas; desgaste `h −= wear_rate · utilização` só
  quando a planta opera (parada não desgasta — mothball é decisão);
  quebra por hazard discreto de Weibull (β=1,6; η por tipo: mina 42,
  refinaria 50, fábrica/planta 46, montadora 60 meses) sorteado por
  mês operado. Quebrada, a instalação NÃO produz, NÃO paga opex e
  espera: reparo é **decisão da política** (8–15% do custo de
  construção, 1–3 ticks de oficina, lognormal de mediana 1);
  manutenção preventiva a 2,2% do custo restaura h em +0,5 (com
  h ≤ 0,3, para 1 tick); overhaul a 60% zera idade e h. Reparo/PM/
  overhaul são **sinks nomeados** nos flows (`spend_repair`,
  `spend_maintenance`, `spend_overhaul`) — o ledger de dinheiro fecha
  sem termo novo; downtime não produz nem consome massa.
- **A decisão na política** (`HeuristicPolicy.maintain_equipment`,
  passo 0 do `decide`, só com a flag): `care = 1 − aggression`
  interpola os limiares DADO da seção "policy" do equipdata — limiar
  de PM de h≈0,34 (Agressiva: roda até quebrar) a ≈0,64 (arquétipos
  cuidadosos); reparo pago quando caixa−reserva supera o custo × mult
  (2,0→1,0 conforme care: quem não cuida, adia o conserto — é daí
  que sai a disponibilidade menor); overhaul com idade ≥150 meses e
  h ≤0,45. NENHUM gene novo no genoma: o B2 diferencia arquétipos
  pelos traços que já existem, e o torneio segue intocado.
- Observação legal respeitada: idade/condição/status das PRÓPRIAS
  instalações via `engine.facility_condition`; de rivais, só o
  sintoma público — a notícia da quebra e, nos frames (só com a flag),
  `age`/`condition`/`down` por instalação.
- Crônica: kinds `breakdown` (toda quebra, com idade, condição,
  custo e estimativa de oficina) e `maintenance` com `data["action"]`
  em repair/preventive/overhaul (PM leve é rotina — registrada nos
  flows, narrada só quando para a planta). A causa de falência ganha
  o modo `quebra` ("rodou a frota até quebrar"). `result()` expõe
  `equipment` (disponibilidade e contadores por empresa + frota);
  `driver.EpisodeSpec` ganhou `equip_v2`/`equip_params`;
  `tables.facilities_table` projeta (F, 4) cid/idade/condição/parada.
- Parâmetros como DADO: `data/facility_params.json` +
  `mundo/equipdata.py` (loader/validador com fallback embutido
  idêntico, matemática pura testável: `weibull_hazard`,
  `effective_capacity`). Os escalares `hazard_scale`/`wear_scale`
  (1,0 no mundo) são as alavancas de teste/Deus — os testes forçam
  quebra e desgaste por override, sem tocar no arquivo.
- Notebook de veredito **preparado, não lançado**:
  `notebooks/veredito-b2.ipynb` — já nasce com o loader recursivo
  pós-mudança do Kaggle. Corridas pareadas (seeds 42/7/11/23, base =
  mundo vivo completo B1+B3/B4a × B2 off/on, 120 ticks), regra
  pré-registrada impressa pelo notebook: ledgers fecham (dinheiro c/
  externo, massa c/ imported) E salientes ON > OFF em ≥3/4 seeds E
  ≥3 quebras por corrida ON em ≥3/4 E disponibilidade da frota ON em
  [0,78; 0,95] em ≥3/4 E nenhum arquétipo falido em todas as corridas
  ON E ≥4 empresas vivas por corrida ON.

**Portão medido** (VM de dev, 2 vCPU compartilhadas)
- Suíte: **144/144 verde** (118 + 26 do B2: fórmulas puras, ledgers
  com os sinks, quebra forçada e parada de produção, reparo como
  decisão — inclusive o adiamento com caixa apertado —, PM
  leve/pesada, overhaul, causa "quebra", replay, snapshot/restore
  cruzando quebras forçadas em todo tick, driver e tabelas).
- Custo do B2: a n=100, dentro do ruído desta VM (mediana
  intercalada: b1+b3 8,40 ms/tick × b1+b3+b2 8,09 ms/tick — sem
  adição mensurável; o custo é O(instalações) e pequeno). A n=8 a
  medição local deu +31% sobre a base b1+b3, mas em números absolutos
  suspeitos (o clássico mediu 0,84 ms/tick contra 0,33 da Fase 1 —
  VM carregada por outras frentes); como nas Fases 2–3, a medição
  limpa fica para a corrida de veredito no Kaggle (4 vCPU).
- Fumaça estrutural (seed 42, 120 ticks, tudo ligado): 87 quebras,
  reparos e PM acontecendo em todos os arquétipos, ledger fechando.
  **Ressalva honesta de calibração:** a disponibilidade da frota
  nessa fumaça deu 0,965 — ACIMA do teto da faixa do design
  [0,78; 0,95]. Leitura: em 120 ticks as frotas são jovens (o
  overhaul, aos 150 meses, nem chega a existir) e o reparo decidido
  no tick seguinte + oficina de 1–3 ticks dá MTTR curto contra um
  MTBF de planta nova de ~40–54 meses. Se o veredito confirmar >
  0,95 nas 4 seeds, é AJUSTAR com as alavancas nomeadas (η menor
  e/ou oficina mais longa) — não mexi por achismo antes do veredito,
  como o lítio do B1 na Fase 2.

**Fora da fase**
- Adoção do B2 (virar padrão) aguarda o veredito do notebook acima,
  que aguarda por sua vez os vereditos do B1 e do B3 — a fila de
  adoção é sequencial por desenho.
- A Fase 5 (núcleo nativo) porta o `step()` final já com o B2 dentro:
  as tabelas de instalações do design §3.1 (`fac_age`, `fac_cond`,
  `fac_down_until`) têm agora conteúdo real para portar.

## Infra Kaggle — novo layout de mount; loaders corrigidos e relançamentos (26/10/2026)

**Diagnóstico** (kernel-sonda `pascalcoimbra/ptq-sonda-input`): o Kaggle
mudou o layout de mount de datasets. Agora os datasets aparecem em
`/kaggle/input/datasets/<dono>/<slug>/` com a árvore **já extraída**
(arquivos individuais, SEM o `mundo-src.zip` dentro); os caminhos
clássicos `/kaggle/input/<slug>/` não existem mais. A célula 1 dos
notebooks procurava `glob('/kaggle/input/*/src/mundo/__init__.py')` e o
zip — ambos vazios no layout novo → `SystemExit` "Fonte do pacote nao
encontrada" na largada. O anexo (`datasetDataSources`) sempre esteve
certo: foi essa a causa das 3 falhas do torneio v1, NÃO prontidão do
dataset (a hipótese anterior estava errada).

**Correção** (só a célula 1; nenhuma outra célula tocada — diff
conferido célula a célula): busca recursiva
`glob('/kaggle/input/**/src/mundo/__init__.py', recursive=True)`
(cobre os dois layouts), `src_root` = raiz acima de `src/mundo/`;
fallback para o `mundo-src.zip` (layout antigo) e, no torneio, para o
`src/` local (fumaça). Aplicada em `notebooks/torneio-v1.ipynb` e
`notebooks/veredito-b1.ipynb`; JSON válido e célula compilando nos
dois. `veredito-b3.ipynb` fica para a frente da Fase 3 corrigir com o
mesmo padrão ao lançar. Criado `notebooks/kernel-metadata-b1.json`
(push do B1 por metadata própria; o `kernel-metadata.json` da raiz é
do nascimento).

**Relançamentos e estado observado**
- **Torneio v1 → versão 4** do kernel `ptq-torneio-de-politicas-v1`
  (kernelId 141075565, dataset src4). Log capturado da execução nova:
  passou da célula 1 e chegou à célula In[11] (`gera_config`/CMA-ES),
  sem `SystemExit`. Depois disso o endpoint `kernels/output` passou a
  devolver log vazio de forma intermitente para esse kernel em
  execução longa (o monitor reativado segue vigiando o mesmo slug).
- **Veredito B1 → versão 3** do kernel `ptq-veredito-b1-mercado-vivo`
  (kernelId 141074479, dataset src3). A célula 1 imprimiu
  `pacote em /kaggle/input/datasets/pascalcoimbra/mundo-autonomo-src3`
  — o caminho do layout novo, prova direta da correção. Corrida
  **completa**: 8/8 corridas pareadas e **VEREDITO B1: APROVADO** —
  eventos salientes ON > OFF em 4/4 seeds (138×119, 153×129, 155×106,
  151×95), amplitude mediana de preços 3,33× → 4,00×, ledger fecha em
  todas as corridas, ≥ 4 empresas vivas em todas as corridas ON.
  Arquivo `veredito-b1.json` gerado nos outputs do kernel (coleta
  para `results/veredito-b1/` é do monitor do B1). A adoção do B1
  como oficial segue a régua: veredito aprovado → mercado vivo vira
  o padrão na próxima consolidação do motor.

## Fase 4 — Recalibração do B2 pós-veredito v1 (26/10/2026)

**Veredito B2 v1: REPROVADO/AJUSTAR por um único portão.** A
disponibilidade da frota ON ficou em 0,953–0,963, acima do teto 0,95
da faixa pré-registrada [0,78; 0,95] (0/4 seeds nesse critério). Todo
o resto passou: salientes ON > OFF em 4/4, 91–102 quebras por corrida
ON, ledgers fechando, ≥ 4 empresas vivas, nenhum arquétipo falido em
todas as seeds. Diagnóstico do próprio notebook: a frota quebra
bastante, mas o reparo devolve rápido demais.

**Ajuste — só as alavancas nomeadas no pré-registro** (η menor e
oficina mais longa); nenhuma mecânica nova, nenhum parâmetro fora de
`data/facility_params.json` + fallback em `src/mundo/equipdata.py`
(regenerado do JSON; a identidade dos dois é garantida por teste):

- **η de Weibull × 0,8 em todos os tipos** (MTBF = η·Γ(1 + 1/β),
  β = 1,6, cai na mesma proporção): assembly 60 → 48 meses
  (MTBF ≈ 54 → 43), factory 46 → 36,8 (≈ 41 → 33), mine 42 → 33,6
  (≈ 38 → 30), plant 46 → 36,8 (≈ 41 → 33), refinery 50 → 40
  (≈ 45 → 36). Notas de calibração do JSON atualizadas juntas.
- **Oficina mais longa**: `repair_ticks_min` 1 → 2,
  `repair_ticks_max` 3 → 6 e `repair_ticks_lognorm_mu` 0,0 → 0,7
  (σ = 0,6 inalterado). O μ faz parte da mesma alavanca "duração da
  oficina": a duração sorteada é `round(LogNormal(μ, σ))` com clamp
  em [min, max] — só mover o clamp mal mudaria a média, porque a
  distribuição vive ancorada na mediana e^μ = 1.

**Aritmética da estimativa (1ª ordem).** E[reparo] sobe de 1,31 para
2,67 ticks (× 2,04); a taxa de quebras por mês operado sobe × 1,25
(MTBF × 0,8); o downtime esperado sobe ≈ × 2,55. Aplicado à
indisponibilidade observada na v1 (0,037–0,047): nova indisponibilidade
≈ 0,094–0,120 → **disponibilidade prevista ≈ 0,88–0,91**, no meio da
faixa-alvo 0,88–0,92 e com margem dos dois lados do portão [0,78; 0,95].
Ressalvas: estimativa de 1ª ordem — ignora que planta quebrada não
envelhece nem desgasta enquanto espera, e o tempo de espera pela
decisão de reparo da política (inalterado pelas alavancas).

**Testes.** Suíte 144/144 verde. Atualizados os testes que travavam
os valores antigos em `tests/test_equip_v2.py` (clamp 1–3 → 2–6 em
`test_equip_params_match_the_design` e no reparo forçado de
`test_forced_break_stops_production_and_counts_downtime`; pin novo
do μ = 0,7). Goldens da Fase 1 intactos — com a flag desligada o
motor segue bit-idêntico, como a suíte prova.

**Preparo do relançamento.** Bundle novo
`pascalcoimbra/mundo-autonomo-src7` com o fonte recalibrado
(verificado por download) e `notebooks/kernel-metadata-b2.json`
apontando para ele. O push do kernel é etapa posterior: o monitor
da v1 fecha a coleta dela antes.

## Torneio de políticas v1 — VEREDITO: INCONCLUSIVO (26/10/2026)

Kernel `pascalcoimbra/ptq-torneio-de-politicas-v1` (versão 4,
RUN_FINAL, bundle src4): CMA-ES em liga com 8.192 episódios de treino,
128 de seleção e avaliação final em 64 blocos pareados nas seeds de
teste travadas.

- **ΔS (A1 − A0) = +0,075, IC95 [+0,034, +0,115]** — o intervalo é
  todo positivo, mas o ΔS ficou abaixo da barra de PROVA do protocolo
  pré-registrado: **VEREDITO: INCONCLUSIVO** (nem PROVA, nem MATA).
- ΔS F2 = +0,054; ΔS choques = +0,054; portões de produto OK.
- Braço A2 (IPPO focal) **não implementado** neste notebook —
  PLANO_B inalcançável por construção; o veredito ficou entre
  PROVA/MATA/INCONCLUSIVO.
- Campeão A1: `evo:6a94b587701d` (S = 0,563 na seleção). Ecologia do
  campeão mais viva que a A0: 130,0 vs 108,5 eventos/episódio,
  4,375 vs 3,75 células de diversidade.
- Genes que mais mudaram vs o genoma 0 (em passos do otimizador):
  `size_ref` +3,74 (800 mil → 1,549 mi), `assembly_device_trigger`
  +3,17 (25 → 88,4), `buffer_scale` +2,82 (1,0 → 2,13), `pick_noise`
  +2,40 (0,10 → 0,29), `mines_coef` +2,17 (2,0 → 3,08),
  `factory_need_default` −2,14 (2,6 mi → 1,315 mi), `dist_scale`
  −2,00 (25 → 5,0, no piso), `buy_target_scale` −2,00 (1,0 → 0,20,
  no piso), `factory_need_vertical` −1,97 (1,2 mi → 412,6 mil),
  `reserve_base` −1,90 (1,5 mi → 549,8 mil).
- Outputs em `results/torneio-v1/` (`genomas_campeoes.json` +
  `stdout.txt`; `results/` é gitignored — só disco).

## Veredito B3+B4a — APROVADO; mundo vivo CONGELADO (26/10/2026)

Kernel `pascalcoimbra/ptq-veredito-b3-pais-e-importacoes` (versão 3,
loader recursivo, bundle src5): 8 corridas pareadas B1 × B1+B3/B4a,
seeds 42/7/11/23, 120 ticks.

- **VEREDITO B3+B4a: APROVADO** — todos os portões pré-registrados.
- Eventos salientes ON > OFF em 4/4 seeds: 182×138, 226×153,
  231×155, 188×151.
- Eventos políticos por corrida ON: 17, 25, 26, 22 (≥ 6 em 4/4);
  90 no total — election 60, royalty_reform 13, subsidy 6,
  judicial_halt 4, export_restriction 3, disaster 3, state_jv 3.
- Royalties pagos: US$ 16,63 mi no total (3,40 / 5,27 / 4,61 /
  3,34 mi por corrida ON).
- Comércio externo ativo em 4/4: massa importada ≈ 251 mil
  (81,4 / 58,1 / 66,6 / 44,8 mil por corrida) e valor exportado
  US$ 922,9 mi (191,3 / 294,0 / 279,5 / 158,1 mi).
- Ledger fecha em 8/8 corridas, incluindo a conta externo; 8/8
  empresas vivas e 0 falências em todas; amplitude mediana de
  preços ON 2,35–4,00 vs OFF 3,81–4,00.
- Com B1 (mercado vivo), B2 (equipamentos) e B3+B4a (país/política +
  importações) aprovados, **as mecânicas do mundo vivo estão
  CONGELADAS** — a Fase 5 (núcleo nativo Rust/PyO3) está liberada.
- Outputs em `results/veredito-b3/` (`veredito-b3.json` +
  `stdout.txt`; só disco).

## Fase 5 — núcleo nativo C++/nanobind (26/10/2026)

- **ROTA: C++/nanobind** (não Rust/PyO3). A VM não tem
  cargo/rustc/maturin; instalar a toolchain Rust seria peso e risco de
  versão contra o Python 3.12, e a rota C++/nanobind é a PROVADA no
  spike do Portão 0 nesta mesma VM (43,8× a n=100, 45,8× a n=1.000) —
  o design a nomeia alternativa equivalente. Compilação:
  `g++ -O2 -ffp-contract=off -fno-fast-math`, sem `-march=native`
  (build em `src/mundo/native/build.py`, sob demanda; o .so não é
  versionado).
- **Arquitetura híbrida:** o núcleo (`src/mundo/native/core.cpp`,
  ~2.950 linhas + `mt19937.hpp`) detém TODO o estado numérico e o
  `step()` completo — política heurística, produção, mercado clássico
  + B1, B3/B4a (política, paridades, comércio externo), B2
  (desgaste/quebra/reparo/PM/overhaul), falência/aquisição,
  rivalidade, resumos de era — e emite registros de evento
  estruturados. A camada Python (`src/mundo/native_engine.py`,
  `NativeEngine` com a MESMA assinatura do `Engine`) formata a
  Crônica com os templates do motor de referência e monta
  frames/`result()`/`state_dict()`. Opt-in total: o caminho Python
  puro não muda um bit; política customizada é recusada com
  ValueError (o backend cobre a HeuristicPolicy, a política oficial).
- **PARIDADE — O PORTÃO: BIT-IDÊNTICA, sem tolerância.** Hash
  SHA-256 do `state_dict()` (protocolo dos goldens) E do `result()`
  iguais aos do Python em: clássico n=8 (24 e 120 ticks — inclusive o
  golden `e01923e1…` da Fase 1 reproduzido pelo nativo), n=100, mundo
  builtin, eventos de Deus; mundo vivo completo n=8 (48/120 ticks) e
  n=100 (48), seeds 42/7/123; flags isoladas e em pares;
  `force_events` políticos (os 7 tipos de evento); restore cruzado
  py→nat, nat→py e nat→nat (30 + restore + 30 == contínua de 60) no
  clássico e no vivo. Ingredientes: MT19937 réplica do CPython —
  incluído o detalhe de que o `lognormvariate` do 3.12 usa
  `normalvariate` (Kinderman–Monahan), NÃO `gauss`; Neumaier onde o
  motor usa `sum()`; `rint` no `round()` dos ticks de reparo; ordem
  de iteração dos dicts do Python replicada nas estruturas que
  afetam RNG, somas e eventos. Detalhe de serialização: campos
  inteiros da fonte Python (ex.: `size_t` int do mundo builtin)
  voltam como int no `state_dict` — tipos preservados pela camada
  Python, ou o hash mudaria sem a simulação mudar.
- **Suíte: 192/192** (178 anteriores + 14 novos em
  `tests/test_native_parity.py`, que pulam sem toolchain C++).
  Goldens da Fase 1 intactos no caminho Python.
- **Benchmark (esta VM, mundo vivo ligado, `step()` cronometrado,
  mediana):** n=100 — Python 161,9 ticks/s × nativo 1.955,5
  ticks/s = **12,1×**; n=1.000 — 13,6 × 254,8 ticks/s = **18,7×**.
  Abaixo do spike do Portão 0 (43,8×/45,8×) porque o spike media só
  `_produce`+`_market` do mundo CLÁSSICO; aqui é o `step()` inteiro
  do mundo vivo, com política, política de país e a travessia dos
  registros de evento pela fronteira nanobind a cada tick. A medição
  em escala (Kaggle, 4 vCPU) é do notebook de veredito.
- **Notebook `notebooks/veredito-fase5.ipynb` PREPARADO** com
  protocolo pré-registrado (paridade em escala — até n=1.000 — +
  benchmark no Kaggle; o kernel compila o núcleo das fontes do
  bundle). **NÃO lançado** — o lançamento é do agente principal,
  como nos vereditos anteriores.
- **Pendências declaradas:** políticas plugáveis arbitrárias seguem
  só no motor Python (por desenho — o torneio/forja usam o Engine de
  referência); Fase 6 (JAX) continua condicional a gargalo medido.

## Fase 5 — veredito v2 REPROVADO (7/11), diagnóstico e correção; v3 APROVADO 11/11 (27/10/2026)

- **Veredito v2 (bundle src9): REPROVADO/AJUSTAR — paridade 7/11.**
  Divergentes: `vivo n=8 t=120`, `vivo n=1000 t=24`, `vivo+force
  t=48` e `restore cruzado vivo`. Benchmarks (informativos): 9,9× a
  n=100 e 11,4× a n=1.000. Localmente a suíte seguia verde nas
  mesmas configurações — divergência só no ambiente Kaggle.
- **Diagnóstico instrumentado** (kernel `ptq-diag-fase-5-paridade`,
  outputs em `results/diag-fase5/`): (1) micro-sondas de semântica —
  sequências de `random()`/`gauss`/`normalvariate`/`lognormvariate`/
  `uniform`/`choice` e valores de `math` (exp/log/pow/cos/sin)
  idênticos entre o CPython 3.12.3 local e o 3.13.15 do Kaggle:
  **a semântica do `random` NÃO mudou** e a libm bate; (2) diff tick
  a tick com resumo do stream MT19937: streams idênticos (índice,
  palavras e `gauss_next` iguais); (3) diff tipado nos estados
  finais das 11 configurações + restores: **zero divergência de
  valor** (hash normalizado bate em 100%, `result()` idêntico em
  tudo) e **exatamente um campo divergente, só de tipo**:
  `state.remaining.Chuquicamata` — `int` no Python, `float` no
  nativo.
- **Causa raiz (duas camadas):** no motor Python, `remaining` nasce
  `int` (o `size_t` da fonte) e só vira `float` na primeira
  extração (a subtração só executa com `crude > 0`, nos dois
  motores); o núcleo guarda `double` e emitia `float` sempre, e o
  `_restore_int_types` do wrapper — que já normalizava depósitos e
  `knowledge` — não cobria o `remaining`. A suíte local não via
  porque o mundo local (`data/world_data.json`, 13 depósitos)
  extrai o Chuquicamata nas configurações testadas; no Kaggle o
  bundle não leva `data/`, o mundo é o **builtin** (10 depósitos)
  e nele o Chuquicamata nunca é extraído sob a dinâmica do mundo
  vivo. Reproduzido localmente com `world_data=False`.
- **Correção:** `_restore_int_types` normaliza `remaining` pelo
  mesmo critério dos demais campos (`size_t` declarada int na fonte
  + valor == `size_t` ⟺ depósito intacto — regra exata, pois
  `remaining` é monótono e a subtração exige `crude > 0`). O portão
  não foi afrouxado: paridade bit-idêntica segue sendo a exigência.
  Regressão: paridade vivo builtin (120t), force builtin, restore
  cruzado vivo builtin e tipo do `remaining` — **suíte 196/196**.
  Commit `782bc1b`; bundle novo **src10** (verificado por download,
  md5 idêntico ao repo).
- **Veredito v3 (bundle src10): APROVADO — paridade 11/11 corridas
  bit-idênticas** (clássico, vivo em n=8/100/1.000, seeds 7/123,
  eventos de Deus, force_events, restore cruzado nos dois sentidos).
  Benchmarks no Kaggle: **13,3× a n=100** (259,8 × 3.443,5 ticks/s)
  e **8,6× a n=1.000** (35,1 × 303,5 ticks/s). Outputs em
  `results/veredito-fase5/`. **Fase 5 encerrada; Degrau 1 completo.**
