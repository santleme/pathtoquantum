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
