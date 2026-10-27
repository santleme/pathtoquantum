# ESTUDO — MOTOR (performance) + AMBIENTE (o mundo além da cadeia)
### Path to Quantum · 26/10/2026 · Frente A (C++ × Rust × JAX × Python) e Frente B (ambiente vivo)

> Escopo: estudo com microbenchmarks de segundos nesta máquina (2 vCPU,
> Python 3.12.3). Nenhuma corrida de mundo foi executada. Números de
> terceiros são citados com fonte; estimativas próprias estão marcadas
> como estimativa e ancoradas no perfil medido do motor atual.

---

# Sumário executivo

**Frente A — o gargalo futuro é treino, e ele ainda não chegou.** O motor
atual roda a 0,40 ms/tick (8 empresas), 2,49 ms/tick (100) e 19,7 ms/tick
(1.000, mundo saturado). O torneio já aprovado (CMA-ES, 8.192 episódios)
custa ~7 minutos single-core no motor atual. Mesmo um IPPO sério
(10M ticks) custa ~7 min a 8 empresas e ~7 h a 100 empresas single-core —
cabe numa sessão de Kaggle com multiprocessamento. **Recomendação:
otimizar o Python agora (ganho estimado 2,5–4×), paralelizar episódios
por processo, e só construir o núcleo nativo quando o spike de 1 dia
(§A4) provar que precisa — com Rust/PyO3 como escolha desse núcleo**,
porque preserva determinismo bit-idêntico (RNG replicável, sem
contração FMA por padrão), o fundador já sinalizou interesse, e o
ecossistema (Polars, pydantic-core, Ruff) prova a rota em produção.
JAX é o teto de throughput para treino em lote, mas é uma **reescrita**
com novo domínio de determinismo — fica como opção estratégica para
quando houver MARL com 100 empresas aprendendo juntas, não como próximo
passo.

**Frente B — o ambiente vivo é barato de computar e caro de ignorar.**
Os quatro sistemas desenhados (mercado com elasticidade/inventário/
ciclos, equipamentos com desgaste/quebra, país/política com eventos
endógenos, demanda final com adoção e importações) custam juntos
<5% do tick a 100 empresas. O pacote proposto para a v2, em ordem de
construção: **B1 mercado vivo → B3 país e política → B4a importações →
B2 equipamentos** (B4b adoção completa acompanha a Era 2). O acoplamento
que faz o mundo respirar: preço alto (B1) eleva a probabilidade de
nacionalismo de recursos (B3), que eleva custos, que alimenta o próximo
ciclo — o loop que a mineração real viveu em 2021–2025.

---

# FRENTE A — PERFORMANCE DO MOTOR

## A1. Estado atual, medido

Microbenchmark nesta VM (2 vCPU, Python 3.12.3, mundo realdata padrão,
seed 42; `step()` cronometrado, sem `run()`/serialização):

| Empresas | ms/tick | Episódio (120 ticks) | 1M de ticks (1 núcleo) |
|---:|---:|---:|---:|
| 8 | **0,396** | 0,05 s | ~6,6 min |
| 100 | **2,486** | 0,30 s | ~41 min |
| 1.000 | **19,68** | 2,36 s (projetado de 24 ticks) | ~5,5 h |

Notas de honestidade: (i) o número de 100 empresas confirma o benchmark
interno já registrado (2,64 ms/tick); (ii) a 1.000 empresas o mundo
**satura** — só há 13 depósitos e 11 cidades, então a medição captura o
custo dos laços num mundo congestionado, não um mundo de 1.000 empresas
bem desenhado (que teria mais depósitos/cidades e custaria mais no
`pick_deposit`); (iii) a escala é sub-quadrática no intervalo medido
(12,5× empresas → 6,3× tempo; 10× → 7,9×), mas há termos quadráticos
latentes (ver hotspots).

### Para onde vai o tempo (n=100, fases do `step()`)

| Fase | % do tick | Leitura |
|---|---:|---|
| `_decide` (política heurística) | **50,0%** | O laço de decisão domina |
| `_market` | **21,7%** | Segundo; tem termo O(compradores×vendedores) |
| `_emit_flows` (event-sourcing) | 7,8% | Monta dict por empresa por tick |
| `_produce` | 7,6% | Barato: poucas instalações por empresa |
| `_note_rivalry` | 3,8% | Dois `max()` sobre empresas por tick |
| `_check_bankruptcy` | 2,4% | Quase tudo é a fachada por empresa |
| `_snapshot` | 2,0% | Só a cada 12 ticks (amortizado) |
| Deus / resto | ~4,6% | — |

Serialização é custo de **fim de episódio**, não de tick: a 100 empresas
e 120 ticks, `state_dict()` = 61 ms, JSON = 1,29 MB / 29 ms,
`save_outputs()` = 501 ms (inclui reconstruir resultado + salvar a
crônica). Irrelevante para treino se o driver coletar só placar/flows;
relevante se alguém chamar `state_dict()` por tick (não chamar).

### Hotspots nomeados (cProfile, n=100, 120 ticks)

1. **`HeuristicPolicy.buffer()` — 132.000 chamadas/episódio.** É chamado
   por `plan_sells` para cada par (empresa × commodity) = 100 × 11 × 120,
   embora o buffer só dependa de (kinds da empresa, traços) — muda no
   máximo quando uma instalação é construída. Memoizar por tick/empresa
   elimina ~11× dessas chamadas.
2. **`pick_deposit()` — 11.540 chamadas/episódio (~96/tick).** Quase toda
   empresa chama quase todo tick porque o `desired_mines` nunca é
   atingido num mundo com 13 depósitos disputados; cada chamada varre
   todos os depósitos e sorteia `rng.uniform` por candidato. Early-exit
   quando não há depósito livre/minável poupa a maior parte.
3. **`_market()` — somas repetidas e laço quadrático latente.** O total
   `sum(offered_left.values())` é recomputado a cada comprador (gerador
   com 104 mil chamadas/episódio) e o preenchimento é
   O(compradores × vendedores) por commodity no pior caso. Manter total
   corrente e vetorizar a coleta de ofertas/compras ataca os dois.
4. **`dict.get` — 439.546 chamadas/episódio; `Company.has()` — 195.109.**
   É o imposto de interpretar estruturas de dicts aninhados
   (`stocks` é `dict[str, float]` por empresa). Índices inteiros de
   commodity (enum → lista) em vez de chaves string é a otimização
   estrutural maior disponível sem sair do Python.
5. `_emit_flows` constrói o dict de **todas** as empresas por tick,
   mesmo as sem fluxo; filtrar antes de montar corta parte dos 7,8%.

## A2. O que o futuro realmente pede (a matemática do treino)

O gargalo não é exibição nem a corrida oficial de 120 ticks (0,05–0,30 s:
nada). É volume de treino:

| Carga | Ticks | Motor atual (1 núcleo) | Com 4 processos (Kaggle) |
|---|---:|---:|---:|
| Torneio CMA-ES aprovado (8.192 ep. × 120, n=8) | ~1M | ~7 min | ~2 min |
| IPPO focal sério (n=8) | 10M | ~66 min | ~17 min |
| Treino ecológico (n=100, todas aprendendo) | 10M | ~6,9 h | ~1,7–2 h |
| Idem, mundo v2 rico (custo/tick ×2–3, estimativa) | 10M | 14–21 h | 3,5–5 h |
| PBT/varredura de hiperparâmetros (×20 corridas) | 200M | — | 1,5–4 dias |

Configuração típica atual do Kaggle: 4 vCPU, GPU T4×2 ou P100, sessões
de até 12 h. Leitura: **o Python atual já entrega a v2 de treino
planejada** (torneio + IPPO focal). A parede aparece na combinação
{100 empresas + mundo rico + varreduras} — é para essa parede, e só para
ela, que serve um núcleo nativo ou JAX. Decidir a reescrita agora seria
pagar o custo antes de a demanda existir; não preparar o caminho seria
o erro oposto. Daí o spike (§A4).

## A3. Os caminhos, comparados neste motor

Premissa comum: o passo do motor é **lógica de controle sobre dicts**
(decidir → produzir → mercado), com aritmética trivial por empresa —
alguns milhares de flops por empresa-tick. O custo é interpretação,
dispatch e acesso a dict, não matemática. Isso inverte o ranking
intuitivo: vetorização numpy pura rende pouco onde o trabalho é
ramificado e esparso; quem rende é (a) remover trabalho, (b) compilar os
laços, (c) paralelizar episódios.

### (a) Python otimizado (+ multiprocessamento de episódios)

- **O que é:** aplicar os 5 hotspots de §A1 (buffer memoizado,
  early-exit no `pick_deposit`, total corrente + coleta vetorizada no
  mercado, stocks por índice inteiro, flows preguiçosos) e rodar
  episódios em processos (episódios são independentes por construção).
- **Ganho estimado neste motor:** 2,5–4× no tick (n=100 → ~0,6–1,0
  ms/tick); ×~4 núcleos no Kaggle para cargas de episódios →
  **efetivo 10–16×** em evolução/avaliação/geração de dados.
- **Esforço:** 2–4 dias, dentro do código atual.
- **O que quebra:** nada, se a ordem das operações de ponto flutuante
  nos caminhos do ledger for preservada. Somar com numpy (soma em
  pares) muda os últimos bits — usar numpy só onde o valor é
  apresentação/agregação não-ledger, ou aceitar goldens novos.
  Determinismo e replay intactos; testes intactos.
- **Kaggle:** perfeito (numpy pré-instalado; multiprocessing nativo).

### (e) Cython / Numba (meio-termo)

- **Cython:** compila a semântica Python; em código dict-pesado rende
  tipicamente 1,5–3× (classes `cdef` para `Company` ajudam o acesso a
  atributos). Esforço: dias, incremental por módulo. Não quebra
  determinismo. É (a) com teto um pouco maior e custo de build.
- **Numba:** `njit` não aceita o código atual (dicts de objetos,
  strings, sets por empresa). Só rende **depois** de um refactor
  struct-of-arrays (stocks viram matriz (N, C), instalações viram
  arrays com máscara) — aí os kernels de produção/mercado podem render
  5–20× nessas fases. Ou seja: Numba não é alternativa ao refactor; é
  o prêmio dele. Sem `parallel=True` em reduções, o determinismo se
  preserva.
- **Veredito:** Cython é dominado por (a)+nativo depois; Numba vira
  candidato real **se** o refactor SoA acontecer por outro motivo
  (ele também é a porta de entrada do JAX).

### (b) C++ via nanobind (pybind11 é a geração anterior)

- **Evidência 2025–2026:** nanobind (do mesmo autor do pybind11)
  compila ~4× mais rápido, gera binários ~5× menores e tem overhead
  de chamada ~10× menor que pybind11 nos benchmarks oficiais; para
  projeto novo é a escolha corrente.
- **Desenho neste motor:** núcleo C++ com o `step()` inteiro
  (decidir+produzir+mercado) sobre structs; Python mantém config,
  crônica (texto), viewer e drivers. A fronteira é 1 chamada por tick
  (ou por episódio), então o overhead de binding é irrelevante — o que
  importa é que **nada** de dict cruze a fronteira por tick.
- **Ganho estimado neste motor:** o passo vira aritmética sobre arrays
  contíguos: 20–80× no `step()` (n=100 → ~0,03–0,12 ms/tick; 10M ticks
  em 5–20 min single-core). Estimativa por analogia: ambientes C do
  PufferLib sustentam milhões de steps/s contra 100–500 mil de
  ambientes Python puros — ordens de grandeza compatíveis com o perfil
  (nosso tick de 100 empresas ≈ 100 decisões de agente).
- **Esforço:** 3–6 semanas em tempo parcial para o núcleo completo com
  paridade de testes (a política heurística tem ~350 linhas de lógica
  ramificada; o mercado, ~120; produção, ~50).
- **O que quebra:** nada **se** o port replicar (1) o RNG —
  `random.Random` é MT19937 com semeadura `init_by_array` e
  `random()` = genrand_res53: replicável em C++ em ~100 linhas; (2) a
  ordem exata das operações; (3) sem `-ffast-math`/contração FMA
  (`-ffp-contract=off`). Cumprido isso, os goldens atuais
  (determinismo bit-idêntico, snapshot/restore) continuam válidos —
  é a vantagem decisiva sobre JAX. O schema de `state_dict` ganha
  `version: 2`.
- **Kaggle:** g++ presente na imagem; nanobind via pip; compilar o
  núcleo no notebook leva ~1 min — ou pré-compilar e subir o wheel no
  dataset de fontes, no padrão que o projeto já usa.

### (c) Rust via PyO3/maturin

- **Evidência:** é a rota dominante de reescrita de hot-paths em
  produção (Polars, pydantic-core, Ruff, orjson, cryptography);
  benchmarks de tutoriais 2025 mostram 10–100× em laços CPU-bound,
  teto igual ao do C++ (mesmo LLVM).
- **Neste motor:** ganho idêntico ao C++ (20–80×). Diferenças práticas:
  segurança de memória por construção (o núcleo mexe com índices de
  arrays o tempo todo — a classe de bug que o borrow checker elimina
  é exatamente a que corromperia um ledger silenciosamente); o Rust
  **não contrai FMA por padrão**, o que facilita o bit-idêntico;
  `rand` não replica o `random.Random` — o MT19937 compatível precisa
  ser escrito à mão (~100 linhas, mesma tarefa do C++).
- **Esforço:** igual ao C++ (3–6 semanas), com curva inicial maior se
  a equipe não tiver Rust — mitigada pelo interesse declarado do
  fundador e pelo fato de o núcleo ser pequeno e fechado.
- **Kaggle:** toolchain Rust não vem na imagem. Duas rotas: instalar
  via rustup no notebook (rede disponível, ~2–5 min por sessão) ou
  **pré-compilar o wheel e distribuí-lo como asset do dataset de
  fontes** (recomendado: zero custo por sessão, versão travada).

### (d) JAX / Warp — o passo como função vetorizada em GPU

- **Evidência:** PureJaxRL demonstrou ~10× sobre pipeline GPU+CPU e
  até ~4.000× vetorizando várias corridas de treino; JaxMARL reporta
  ~14× em wall-clock e até ~12.500× com corridas vetorizadas; EconoJax
  (já citado na pesquisa de algoritmos) treinou economia com 100
  agentes em 13–15 min contra dias. Warp (NVIDIA, kernels Python→CUDA,
  diferenciável, interop com JAX/PyTorch) é a alternativa imperativa:
  um thread por empresa preserva a lógica sequencial por agente, e
  versões recentes trazem modos determinísticos opt-in (atomics de GPU
  são dependentes de escalonamento por padrão).
- **O que exige mudar no design (o preço real):**
  1. **Estado 100% em arrays de forma fixa:** stocks (N, C); preços
     (C,); depósitos (D,) com `remaining` (D,); instalações em slots
     fixos por empresa (ex.: 32 × tipo) com máscara; conhecimento
     (N, D) com máscara; ferramentas como contadores (N, F). Descoberta
     de Deus vira slot pré-alocado que se ativa.
  2. **Decisões em lote:** a `HeuristicPolicy` vira aritmética com
     máscaras sobre arrays (os ifs por empresa viram `where`); a
     interface `Policy` plugável por objetos **morre** — políticas
     passam a ser funções puras (obs → ações) sobre arrays. O CEO LLM
     continua fora (fronteira anual), sem perda.
  3. **Crônica sai do JIT:** dentro do passo vetorizado não há string.
     O passo emite códigos de evento + payload num buffer de tamanho
     fixo; o texto é materializado em Python depois — o desenho atual
     de event-sourcing com eventos `flows` numéricos é, felizmente,
     meio caminho andado.
  4. **RNG funcional:** chaves PRNG do JAX com split por tick/mundo.
- **Ganho:** não é "o tick fica X× mais rápido" — é **milhares de
  mundos em paralelo** na GPU: throughput de treino 100–1.000× o do
  Python paralelizado, na faixa que viabiliza MARL ecológico de
  verdade. Por mundo individual, um T4 é *pior* que CPU para este
  passo minúsculo e ramificado.
- **O que quebra:** o bit-idêntico com o motor Python (float32 é o
  padrão; dinheiro exige float64 — no T4, float64 é ~1:64 do float32,
  mas nossos arrays são minúsculos e o paralelismo é por mundos, então
  viável). Nasce um **novo domínio de determinismo**: reproduzível no
  mesmo hardware/backend/versão, não bit-igual entre CPU e GPU. Replay
  por reexecução continua válido *dentro* do motor JAX; os goldens
  atuais viram goldens do motor de referência. Snapshot/restore fica
  até mais simples (dump de arrays).
- **Esforço:** 4–8 semanas — é uma reescrita do núcleo, não um port.
- **Kaggle:** JAX pré-instalado e GPU disponível: o melhor encaixe de
  plataforma de todos os caminhos. Warp exige `pip install warp-lang`.
- **Veredito:** é o caminho certo **se e quando** a pergunta virar
  "treinar 100 empresas aprendendo juntas por dezenas de milhões de
  ticks". Antes disso, é pagar a reescrita para resolver um problema
  que (a)+(c) resolvem por uma fração do custo.

### Tabela-síntese

| Caminho | Ganho neste motor | Esforço | Bit-idêntico atual | Kaggle |
|---|---:|---:|---|---|
| (a) Python otimizado + processos | 2,5–4× (tick); 10–16× efetivo em episódios | 2–4 dias | ✅ preserva | ✅ nativo |
| Cython | 1,5–3× | dias | ✅ | ✅ (compila no notebook) |
| Numba (pós-refactor SoA) | 5–20× nas fases numéricas | 1–2 sem. (refactor) | ✅ se sem reduções paralelas | ✅ pré-instalado |
| C++ nanobind | 20–80× no step | 3–6 sem. | ✅ se RNG+ordem replicados | ✅ g++ na imagem |
| Rust PyO3 | 20–80× no step | 3–6 sem. | ✅ idem (sem FMA por padrão) | ⚠️ wheel pré-compilado no dataset |
| JAX | 100–1.000× throughput em lote | 4–8 sem. (reescrita) | ❌ novo domínio | ✅ melhor encaixe |
| Warp | similar ao JAX, modelo imperativo | 4–8 sem. | ❌ (modo determinístico opt-in) | ⚠️ pip install |

## A4. Recomendação e o spike de 1 dia

**Caminho principal:** (a) agora → núcleo **Rust/PyO3** quando o spike
mandar → JAX apenas se o MARL ecológico virar o gargalo medido.
A ordem importa: (a) é pré-requisito barato de qualquer futuro (o
perfil pós-otimização diz exatamente o que o núcleo nativo precisa
ser), e o refactor SoA — se um dia necessário — serve a Numba, Rust
(arrays contíguos na fronteira) e JAX ao mesmo tempo.

**Spike (1 dia, dois blocos):**

- **Manhã — teto do Python.** Num branch, aplicar os hotspots 1–3 e 5
  de §A1 (buffer memoizado, early-exit do `pick_deposit`, total
  corrente no mercado, flows preguiçosos). Medir ms/tick a n=100 e
  n=1.000 nos mesmos seeds do §A1.
- **Tarde — teto do nativo.** Kernel mínimo fora da árvore (descartável)
  em C++/nanobind (g++ já existe aqui e no Kaggle) replicando **só a
  aritmética** de `_produce` + `_market` sobre arrays sintéticos com o
  perfil de n=100, sem crônica. Medir o speedup dessas fases isoladas.
- **O número que decide:** projetar o custo de **10M de ticks a n=100
  no mundo v2 rico** (multiplicar o ms/tick medido por 2,5 — a
  estimativa de custo dos sistemas da Frente B — e dividir por 4
  processos):
  - Se Python otimizado projetar **≤ 45 min** → fica em Python;
    núcleo nativo adiado sem culpa.
  - Se projetar **> 45 min** *e* o kernel nativo mostrar **≥ 15×** nas
    fases portadas (que são ~30% do tick hoje e crescem com a Frente
    B) → aprovar o núcleo Rust com o desenho de §A3c.
  - Se o kernel mostrar < 15×, o problema é arquitetura de dados, não
    linguagem: fazer o refactor SoA + Numba antes de qualquer nativo.

---

# FRENTE B — AMBIENTE RICO (o mundo além da cadeia)

## B0. Princípios de desenho (valem para os quatro sistemas)

1. **Dado, não código** — como a cadeia já é (`chain.py`): parâmetros
   por commodity/país/instalação vivem em tabelas (`market_data`,
   `country_data`, `facility_data`), calibráveis sem tocar no motor.
2. **Realismo ancorado, não decorativo** — cada parâmetro nasce de uma
   série ou fato real citado; quando o mundo comprime o tempo (minas
   levam 16,5 anos para desenvolver no mundo real, segundo a Marsh —
   aqui levam ticks), a compressão é declarada no parâmetro.
3. **Observação legal** — tudo que o sistema expõe a uma empresa passa
   pelo que seria público ou dela no mundo real (índices publicados,
   estoques de bolsa, o estado das próprias plantas). Nada de vazar
   verdade oculta: o fog-of-war continua sendo invariante.
4. **A Crônica narra transições, não estados** — regime que muda,
   planta que quebra, país que nacionaliza. Estado contínuo aparece no
   frame (viewer), não como spam de eventos.
5. **Custo por tick desprezível por construção** — todos os sistemas
   são O(commodities + países + instalações); nenhum é O(empresas²).

## B1. Mercado vivo — ciclos, elasticidade, inventário, especulação

### O defeito atual

Hoje a demanda das cidades é **quantidade fixa** (`CITY_DEMAND`),
perfeitamente inelástica: o preço só se move pelo fator de desequilíbrio
com banda [0,72; 1,35]/tick e teto [0,3×; 3×] do base. Resultado: não há
ciclo endógeno, não há castigo por estocar demais, não há memória. O
lítio real saiu de ~US$ 7 mil/t (2020) para ~US$ 80 mil/t (nov/2022) e
desabou para US$ 10–14 mil/t (2025) — um fator de 11× que a banda atual
**não consegue representar** (teto 3×).

### Mecânica mínima

Estado novo por commodity `c`: preço-âncora `p*_c` (custo marginal de
longo prazo), regime `R_c ∈ {boom, normal, bust}`, cobertura de
inventário `I_c` (estoque agregado das empresas ÷ demanda mensal),
série de preços (anel de 24 meses, pública).

Por tick:

1. **Demanda elástica:** `D_c = D0_c · (p_c/p*_c)^(−ε_c) · saz(t) · tendência_c(t)`
   — ε curto-prazo: lítio 0,3; cobre 0,4; ferro 0,5; petróleo/plástico
   0,4; componentes 0,7; dispositivos 1,0; supercomputador 1,2 (capex
   discricionário é o mais elástico).
2. **Pressão de inventário:** multiplicador de preço
   `m = exp(−γ_c · (I_c − I*_c))`, com `I*` ≈ 1,5–2,5 meses de demanda.
   Estoque alto deprime preço **antes** de qualquer venda — é o
   mecanismo do colapso de 2023–24 (destocking) e o que torna a
   especulação das empresas uma decisão com risco real: estocar no boom
   é carregar o ativo que vai desabar.
3. **Regime com memória (Markov de 2–3 estados):** transições mensais
   calibradas para durações médias reais — boom 18–36 meses, bust
   24–48 meses (lítio: boom 2021–22 ≈ 24m; bust 2023–25 ≈ 30m+). No
   boom, `p*` deriva +0,5–1,5%/mês (inflação de custos + euforia de
   demanda); no bust, −0,5–1%/mês. O preço persegue a âncora com
   velocidade `κ_c` (lítio lento = ciclos longos; ferro mais rápido) e
   ruído mensal σ_c (volatilidade: lítio σ≈9%/mês no período 2021–23;
   cobre ≈5%; ferro ≈6%; petróleo ≈8%).
4. **Choques de oferta** entram pelo sistema de eventos (B3/B1-eventos):
   greve/desastre derruba a capacidade efetiva de um depósito/região
   por 2–9 meses (frequência real: bloqueios em Las Bambas pararam a
   mina por centenas de dias acumulados desde 2016; greves em
   Escondida, 2017, duraram 44 dias).
5. O ajuste por desequilíbrio atual **continua**, mas operando sobre a
   demanda elástica e com banda alargada para [0,25×; 6×] da âncora
   variável — o teto deixa de ser constante e passa a ser o regime.

### Calibração (séries reais 2015–2025)

| Commodity | Fatos-âncora (fontes públicas: USGS, LME, World Bank Pink Sheet, Platts) |
|---|---|
| Lítio (carbonato) | Bolha 2015–17 (CNY 40 mil → 180 mil/t → 50 mil em 2019); pico ~US$ 80 mil/t nov/2022; média EUA USGS: US$ 63,7 mil/t (2022) → US$ 11,8 mil (2024) → ~US$ 9 mil (2025). Volatilidade extrema, ciclo ~7–9 anos |
| Cobre (LME) | ~US$ 4,9 mil/t (fundo 2016) → pico ~US$ 10,7 mil (mar/2022) → US$ 9–9,5 mil (2024) → território recorde em 2025 com demanda de data centers de IA (30–40 t de cobre por MW de hyperscale) |
| Minério de ferro (62% Fe) | ~US$ 40/t (fundo 2015) → pico ~US$ 237/t (mai/2021) → faixa US$ 100–130 (2023–25) |
| Petróleo (WTI/Brent) | US$ 26 (fev/2016) → negativo (abr/2020) → ~US$ 120 (jun/2022) → US$ 70–80 (2024–25) |

Entregável de calibração: `data/market_params.json` com
`(p*, κ, ε, γ, I*, σ, durações de regime)` por commodity + notebook de
ajuste no Kaggle comparando momentos simulados (volatilidade,
autocorrelação, duração de ciclo) com os da série real — o mesmo
protocolo de veredito dos outros experimentos.

### Observação legal · Crônica · Custo

- **Observação:** preços e histórico são públicos (já são); a cobertura
  `I_c` vira **estoque de bolsa público** estilo LME (na vida real,
  warehouse stocks são publicados) — é a peça que torna especulação
  uma decisão informada, não um chute. O regime **não** é observável:
  infere-se do preço, como na vida real.
- **Crônica:** viradas de regime ("o lítio entra em colapso: −52% em
  6 meses, estoques em 4,1 meses de demanda"), recordes de preço,
  escassez extrema. Nada por tick — só transições e extremos.
- **Custo/tick:** O(C) + agregação de estoques que o mercado já faz:
  **<1%** a n=100.

## B2. Equipamentos e operação — desgaste, quebra, manutenção

### Mecânica mínima (por instalação)

Estado novo por instalação: `age` (meses desde a construção/overhaul),
`condition h ∈ (0, 1]`, `down_until`.

1. **Eficiência:** `cap_efetiva = capacity · h · (1 − 0,15·min(1, age/240))`
   — planta de 20 anos perde até 15% mesmo bem mantida.
2. **Desgaste:** a cada tick operando, `h −= desgaste · utilização`,
   com `utilização = throughput/cap_efetiva`. Planta parada não
   desgasta (decisão real: mothball em bust — conecta com B1).
3. **Quebra (hazard de Weibull):** probabilidade mensal
   `q = 1 − exp(−[((a+1)/η)^β − (a/η)^β])`, β ≈ 1,6 (desgaste
   crescente com a idade — estudos de confiabilidade de caminhões de
   mineração ajustam Weibull com β = 1,62; escavadeiras/carregadeiras
   de subsolo: η de centenas de horas no nível do subsistema).
   Calibração no nosso nível (planta inteira, tick mensal): escolher η
   por tipo para que a disponibilidade `A = MTBF/(MTBF+MTTR)` fique em
   **~80–85% sem manutenção** e **~92–95% com manutenção** — faixa dos
   benchmarks reais (frotas escavadeira-caminhão medem 77–78% de
   disponibilidade média; operações boas miram 85%+).
4. **Reparo:** quebra → `down` por 1–3 ticks (lognormal, mediana 1),
   custo 8–15% do custo de construção. Sem reparo automático: a
   política decide reparar, e caixa negativo enquanto isso é problema
   dela.
5. **Manutenção preventiva (decisão nova da política):** gastar
   1,5–3% do custo de construção restaura `h` em +0,5 (teto 1) sem
   downtime se `h > 0,3`; com `h ≤ 0,3`, exige 1 tick parada.
   **Overhaul:** 60% do custo de construção → `age = 0, h = 1`.
   As três verbos — **manter, trocar (overhaul), expandir (construir
   outra)** — são a decisão clássica que hoje não existe: hoje
   instalação é eterna e perfeita.

### Observação legal · Crônica · Custo

- **Observação:** idade, condição e status das **próprias** instalações
  (é dela). De rivais, só o sintoma público: queda de oferta no mercado
  e a notícia da paralisação (na vida real, outage de planta grande é
  notícia de mercado).
- **Crônica:** quebras com consequência ("a refinaria da Vetor Sul
  quebra no pico do cobre — 2 meses parada, US$ 0,6M de reparo"),
  programas de manutenção viram traço visível da Cautelosa; a Agressiva
  que roda até quebrar ganha um modo de falência novo e narrável.
- **Custo/tick:** O(instalações) — poucas por empresa: **<1%**.
- **Interação com políticas:** é o sistema que mais diferencia
  arquétipos sem tocar em IA — e o primeiro que dá às políticas
  aprendidas (v2) uma decisão contínua de verdade para aprender.

## B3. País e política — estabilidade, câmbio, nacionalismo, eventos

### Mecânica mínima

Estado novo por país (cidades e depósitos ganham `country` na tabela
de mundo): índice de estabilidade `S ∈ [0,1]`, câmbio-índice `e`
(moeda local por US$, normalizado), regime de royalties `τ`.

1. **Estabilidade:** passeio aleatório com reversão à média do país,
   `S(t+1) = S + 0,03·(S̄_país − S) + ruído(0,02)`. Baselines ancorados
   nos índices publicados (World Bank WGI — Political Stability;
   ICRG): Chile ~0,65; Brasil ~0,45; Peru ~0,40; Argentina ~0,35;
   Bolívia ~0,30 (percentis convertidos, ordem de grandeza).
2. **Custo de capital e de operação:** capex no país custa
   `× (1 + 0,25·(1−S))` (licenciamento, seguro, atraso — o prêmio de
   risco-país embutido); opex paga surcharge de royalties `τ` por país
   e regime (a reforma chilena de royalties de 2023 levou a carga
   efetiva de grandes mineradoras de cobre a até ~46,5% sobre lucro —
   aqui, simplificado: surcharge de 3–8% sobre opex conforme regime).
   Quando o BancoSim existir, `S` alimenta o spread de juros
   (tipo EMBI: spread ≈ (1−S)·800 bps) — o desenho já deixa o gancho.
3. **Câmbio:** fração local do opex `λ ≈ 0,45` (mão de obra e insumos
   locais) é precificada em moeda local: `opex_USD = opex · [(1−λ) +
   λ·(e0/e)]`. `e` desvaloriza com choques de instabilidade
   (correlação S↓ → e↑). Efeito real e ambíguo, como na vida real:
   desvalorização **barateia** o opex em dólar (a vantagem histórica
   das mineradoras argentinas pós-desvalorização) mas encarece capex
   importado — decisão de onde expandir muda com o câmbio.
4. **Motor de eventos endógeno** (generaliza os atos de Deus atuais:
   Deus continua podendo forçar qualquer evento, mas o mundo também os
   gera). Probabilidades anuais por país, ancoradas na frequência
   latino-americana 2015–2025:

   | Evento | Prob./ano | Âncora real |
   |---|---:|---|
   | Reforma de royalties/imposto | ~6% (dobra se preço > 1,5× âncora) | Chile 2023; onda regional de nacionalismo de recursos 2020–24 (Marsh/EDC) |
   | Restrição de exportação | ~2% | Indonésia (níquel); precedentes regionais |
   | JV forçada / participação estatal | ~1,5% | Estratégia Nacional do Lítio do Chile (abr/2023): Estado com 50,01% nos novos projetos; México: decreto de nacionalização do lítio (fev/2023) |
   | Paralisação judicial/protesto de mina grande | ~0,7% por país-mina | Cobre Panamá: fechamento em 2023 após decisão da Suprema Corte — ~1,5% da oferta mundial de cobre removida; investimento de ~US$ 10 bi |
   | Subsídio/política industrial (positivo) | ~4% | IRA americano como arquétipo; políticas de conteúdo local |
   | Desastre natural regional | ~1% | Frequência sísmica/inundação andina |
   | Eleição (a cada 48 ticks) | determinístico | Desloca `S̄` em ±0,1–0,2 e pode trocar o regime de `τ` |

   A regra de ouro do acoplamento: **a probabilidade de nacionalismo
   sobe com o preço** (B1 → B3). Foi assim em 2003–2013 e em 2021–23:
   governo intervém quando a commodity está cara, não quando está
   barata. É esse feedback que transforma quatro sistemas separados
   num ambiente só.

### Observação legal · Crônica · Custo

- **Observação:** `S`, `e` e `τ` são **públicos** (índices e câmbio são
  publicados na vida real). As probabilidades dos eventos, não — a
  empresa precifica risco pelo nível e pela tendência de `S`, e o traço
  `risk` finalmente ganha um objeto real para precificar.
- **Crônica:** é o sistema de maior densidade narrativa por linha de
  código — eleição, reforma, nacionalização e paralisação são
  manchetes prontas, e dão à Era 1 vilões e viradas que não dependem
  das empresas.
- **Custo/tick:** O(países) + eventos raros: **<1%**.

## B4. Demanda final viva — adoção em S e o resto do planeta

### B4a. Importações (pressão de fora do mapa) — fazer primeiro

Mecânica de uma linha no mercado: um pseudo-vendedor/comprador
"resto do mundo" com oferta elástica ao **preço de paridade de
importação** `p_imp = p*_mundo · (1 + tarifa + frete)`:
- se o preço interno supera `p_imp`, importações entram e tampam o
  preço (oferta adicional crescente com o spread);
- se cai abaixo da paridade de exportação, exportações absorvem o
  excedente (piso mole).
Isso mata o defeito silencioso do mundo fechado (preço explodindo até o
teto da banda por falta de um vendedor só) e cria o canal pelo qual
sanções/tarifas de B3 mordem: sanção = tarifa → ∞ num recurso.
Custo: O(C). Observação: paridade é pública. Crônica: só extremos
("importações de dispositivos inundam o mercado").

### B4b. Adoção tecnológica (curva S de Bass)

Estado: adoção mundial de computação `A(t) ∈ [0,1]`, difusão de Bass
`dA/dt = (p + q·A)·(1 − A)`, com os parâmetros clássicos da literatura
(p ≈ 0,03, q ≈ 0,38 ao ano → convertidos ao tick). A demanda de
dispositivos e supercomputadores escala com `(0,3 + A·escala)`: no
início do mundo quase ninguém quer um supercomputador (demanda atual:
7/mês); com a adoção, a demanda do topo da cadeia **compõe** — a
corrida da Era 1 ganha um relógio econômico, e a Era 2 nasce com
demanda esperando. Choques de substituição (evento raro pós-Era 1):
uma tecnologia nova desloca a demanda entre refinados (âncora real:
a virada LFP derrubou a demanda projetada de níquel/cobalto; a
discussão sódio-íon pressiona o lítio) — implementado como rotação de
participações de demanda entre metais, não como sistema novo.
Observação: índice de adoção é estatística pública. Crônica: marcos de
adoção ("a computação autônoma cruza 25% das grandes empresas do
mundo"). Custo: O(1).

## B5. Ranking e o pacote da v2

Ordenado por **(realismo + história gerados) ÷ esforço**:

| # | Sistema | Esforço | Por que nesta posição |
|---|---|---|---|
| 1 | **B1 — Mercado vivo** | Médio (reescreve o bloco de preço/demanda do `_market` + tabela de parâmetros + calibração) | Muda a economia de **todas** as corridas e de **todas** as decisões; sem elasticidade e inventário, os outros sistemas jogam sobre um mercado morto. É também pré-requisito do acoplamento B1→B3 |
| 2 | **B3 — País e política** | Baixo-médio (reusa o trilho de eventos de Deus; adiciona `country` às tabelas e 3 índices) | Maior densidade de história por esforço do estudo inteiro; dá objeto real ao traço `risk` e geografia real às decisões de expansão |
| 3 | **B4a — Importações** | Baixo (um participante elástico no mercado) | Corrige o mundo fechado e é o canal das sanções de B3; quase grátis depois de B1 |
| 4 | **B2 — Equipamentos** | Médio (estado por instalação + 2 decisões novas na política + hazard) | As melhores decisões micro e o melhor diferenciador de arquétipos — mas exige tocar política e observação, então vem depois que o mundo ao redor existe |
| 5 | **B4b — Adoção (Bass)** | Baixo | Sozinha rende pouco na Era 1 (a demanda do topo é pequena); rende tudo quando a Era 2 abrir — entra junto com ela |

**Pacote v2 do mundo proposto:** B1 + B3 + B4a + B2, nesta ordem de
construção, cada um com (i) tabela de parâmetros com fontes, (ii)
testes de invariante novos (conservação continua fechando com os
sinks/sources novos: royalties e reparos são sink; importação é fonte
de massa externa contabilizada no ledger como tal), (iii) corrida de
veredito no Kaggle comparando a distribuição de histórias (marcos por
corrida, dispersão de preços, falências por causa) antes/depois — pela
régua do PRD: se a crônica não ficar visivelmente mais viva, o sistema
não entra, por mais realista que seja.

**Custo combinado estimado:** <5% do tick a n=100 — a Frente B não muda
a decisão da Frente A; ela só aumenta o multiplicador de custo/tick
(×2–3 com decisões mais ricas nas políticas) que o spike de §A4 já
embute na projeção.

---

# Fontes

**Performance/binding/RL-infra**
- nanobind — benchmarks oficiais (compilação ~4×, binário ~5×, overhead
  ~10× vs pybind11): https://nanobind.readthedocs.io/en/latest/benchmark.html
- PureJaxRL / JaxMARL — speedups de pipelines JAX (10×; até ~4.000× /
  ~12.500× com corridas vetorizadas; JaxMARL ~14× wall-clock):
  https://arxiv.org/html/2311.10090v5
- PufferLib — ambientes C com milhões de steps/s vs 100–500 mil de
  ambientes Python puros: https://eliteai.tools/agent-skills/pufferlib
- PyO3/maturin em produção e ganhos típicos de hot-path (10–100×):
  https://blog.serghei.pl/posts/a-quick-dive-into-ffi-in-python/
- NVIDIA Warp — kernels Python→CUDA, diferenciável, interop JAX/PyTorch,
  determinismo opt-in: https://huggingface.co/blog/nvidia/how-to-use-nvidia-warp-and-mjwarp

**Mercados e calibração**
- Ciclo do lítio 2020–2026 (US$ 7 mil → 80 mil → 10–14 mil/t) e o ciclo
  clássico de sobreinvestimento: https://mbcapitalstrategiesglobal.com/glossary/lithium-stocks.html
- USGS via imprensa especializada: média EUA do carbonato de lítio
  US$ 63,7 mil/t (2022) → US$ 11,8 mil (2024) → ~US$ 9 mil (2025):
  https://articlescad.com/lithium-carbonate-price-history-and-chart-historical-market-trends-and-key-price-movements-310120.html
- Cobre e demanda de data centers de IA (30–40 t/MW):
  https://carboncredits.com/electric-metal-prices-today/

**Confiabilidade de equipamentos**
- Shovel–dumper: Weibull como melhor ajuste; MTBF de 44 h (escavadeira)
  a 55–138 h (caminhões) no nível do subsistema:
  https://www.iieta.org/journals/mmep/paper/10.18280/mmep.050414
- Caminhões de mineração: Weibull β = 1,62 (desgaste crescente):
  https://www.academia.edu/40173413/A_Study_on_Reliability_Analysis_of_Haul_Trucks
- Benchmarks de disponibilidade/OEE de frotas (disponibilidade média
  77–78%, OEE 41–44%): https://farmonaut.com/mining/mining-equipment-key-performance-indicators-top-5-visuals

**País e política**
- Nacionalismo de recursos na América Latina; México (decreto do lítio,
  fev/2023), Chile (parcerias com maioria estatal), Panamá (disputa
  Cobre Panamá); prazo médio de desenvolvimento de mina de lítio:
  16,5 anos: https://www.marsh.com/content/marsh2/en_us/industries/mining/insights/mitigation-strategies-for-mining-companies-navigating-economic-and-political-risk-uncertainty.html
- Estratégia Nacional do Lítio do Chile (abr/2023), Estado com 50,01%:
  https://projects.gbreports.com/chile-mining-2023/lithium-production-and-development
- Cobre Panamá como o exemplo claro recente de risco de expropriação
  (fechamento em 2023 por decisão da Suprema Corte); conflitos e
  interrupções operacionais no Peru e Chile (2000–2020):
  https://www.edc.ca/en/article/canadian-mining-latin-america-risk-opportunity.html
