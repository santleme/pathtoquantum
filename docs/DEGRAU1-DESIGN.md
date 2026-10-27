# DEGRAU 1 — DESIGN
### Motor com escala de sobra para treino + mundo vivo v2
### 26/10/2026 · decisão do fundador: Degrau 1 ANTES da forja (Degrau 2)

> Este documento desenha o Degrau 1 da escada de complexidade
> (`docs/FRONTEIRA-2026.md`) **corrigido pela medição local**
> (`docs/ESTUDO-MOTOR-AMBIENTE.md`, commit `01f5d3f`). Onde os dois
> divergem, manda a medição — e a divergência é registrada aqui, não
> escondida.

---

## 0. A decisão, a intenção do fundador e o desvio honesto

O fundador pediu "Degrau 1 (motor GPU + mundo vivo) antes da forja".
A **intenção** por trás do pedido é inequívoca: escala de sobra para
treinar políticas de verdade e um mundo que respira além da cadeia.
Este desenho entrega a intenção — mas **não** pelo caminho "reescrever
em JAX agora" que a síntese da fronteira sugeria como leitura rápida.
O estudo de motor mediu o mundo real deste projeto e concluiu:

- O motor Python atual roda a **0,396 ms/tick (8 empresas),
  2,486 ms/tick (100) e 19,68 ms/tick (1.000)**.
- O torneio já aprovado (CMA-ES, 8.192 episódios ≈ 1M ticks) custa
  **~7 min single-core** — a parede de treino **ainda não chegou**.
- A parede (200M de ticks = 1,5–4 dias) só aparece na combinação
  {100 empresas aprendendo juntas + mundo rico + varreduras de
  hiperparâmetros}.
- JAX é o teto de throughput em lote (100–1.000×), mas é uma
  **reescrita de 4–8 semanas** que **perde a bit-identidade** com o
  motor atual e mata a interface de políticas por objetos.

Pagar a reescrita agora seria resolver com o caminho mais caro um
problema que a medição diz que ainda não existe. Não preparar o
caminho seria o erro oposto. A rota adotada é, portanto, a do estudo:

1. **Python otimizado agora** (hotspots medidos, bit-idêntico,
   multiprocessamento de episódios): 2,5–4× por tick, 10–16× efetivo
   em cargas de episódios.
2. **Spike comparativo como Portão 0** (§2): ele decide, com um número
   pré-registrado, se e quando um núcleo nativo entra.
3. **Núcleo nativo (Rust/PyO3; C++/nanobind equivalente) só se o
   portão mandar**: 20–80× no `step()` **preservando bit-identidade**
   (RNG MT19937 replicado, ordem de operações replicada, sem
   contração FMA).
4. **JAX como opção estratégica condicional** (§5, Fase 6): entra se —
   e somente se — o MARL ecológico virar gargalo **medido**. "GPU"
   deixa de ser um ato de fé e vira um gatilho com número.

O mundo vivo (§4) independe da rota de motor: os quatro sistemas do
estudo custam juntos **<5% do tick** e entram sobre o motor Python,
na ordem B1 → B3 → B4a → B2.

---

## 1. Estado medido (a base factual)

Perfil do `step()` a n=100 (estudo, §A1): `_decide` 50,0% ·
`_market` 21,7% · `_emit_flows` 7,8% · `_produce` 7,6% ·
`_note_rivalry` 3,8% · resto ~9%. Hotspots nomeados:

| # | Hotspot | Natureza |
|---|---|---|
| 1 | `HeuristicPolicy.buffer()` — 132 mil chamadas/episódio, embora só dependa de (kinds da empresa, traços) | memoizável por estado de kinds |
| 2 | `pick_deposit()` sem early-exit — ~96 chamadas/tick a n=100 num mundo de 13 depósitos | pré-varredura sem RNG + cache de parcela estática |
| 3 | `_market()` — `sum(offered_left.values())` recomputado por comprador; laço O(compradores×vendedores) sobre dicts | totais por lista alinhada, índices inteiros |
| 4 | Imposto de dicts: `stocks` é `dict[str, float]` por empresa (439 mil `dict.get`/episódio) | **commodities por índice inteiro** — a maior otimização estrutural; é também a fundação SoA de §3 |
| 5 | `_emit_flows` monta dict de todas as empresas por tick | filtrar antes de montar — **muda o payload do evento `flows`**; exige decisão de golden (§3.5), não entra no pacote bit-idêntico |

A matemática do treino (estudo, §A2) que este desenho precisa servir:

| Carga | Ticks | Motor atual (1 núcleo) |
|---|---:|---:|
| Torneio CMA-ES aprovado (n=8) | ~1M | ~7 min |
| IPPO focal sério (n=8) | 10M | ~66 min |
| Treino ecológico (n=100, todas aprendendo) | 10M | ~6,9 h |
| Idem, mundo v2 rico (custo/tick ×2–3) | 10M | 14–21 h |
| Varreduras/PBT (×20) | 200M | 1,5–4 dias (4 processos) |

---

## 2. Portão 0 — o spike comparativo (esta entrega)

O spike vive em `experiments/degrau1/` — **fora** do pacote oficial,
descartável por construção. Ele tem duas metades, espelhando o spike
de 1 dia do estudo (§A4):

**Manhã — teto do Python.** Overlay de otimizações bit-idênticas
sobre o motor atual (hotspots 1–2: `buffer` memoizado com
invalidação por mudança de kinds; parcela estática do score do
`pick_deposit` pré-computada). O hotspot 3 foi medido **separado**
(`market_rt.py`): a variante "totais por lista na mesma ordem"
mediu mais lenta e foi descartada; a variante "total corrente por
subtração" sobreviveu aos fixtures mas não é bit-idêntica por
construção e rende ~1,03× — fica como decisão de golden pendente,
não como otimização (resultados completos em
`experiments/degrau1/README.md`):

- *Equivalência*: fixture determinística (seed 42) a n=8 e n=100 —
  baseline × overlay têm de produzir `state_dict`, crônica e placar
  **bit-idênticos** (hash comparado).
- *Medição*: ms/tick a n=8/100/1.000, mesmo protocolo do estudo
  (`step()` cronometrado, sem serialização).

**Tarde — teto do nativo.** Kernel descartável em C++/nanobind
(`experiments/degrau1/kernel/`) replicando **só a aritmética** de
`_produce` + `_market` sobre arrays planos sintéticos com o perfil
de n=100 (e n=1.000 esparso), compilado com `-O2 -ffp-contract=off`:

- *Equivalência*: uma referência Python em laços sobre os mesmos
  arrays executa a mesma sequência de operações; saídas comparadas
  (esperado: bit-idêntico — mesma ordem, IEEE-754 double, sem FMA).
- *Medição*: speedup das duas fases isoladas + projeção Amdahl sobre
  o tick (as duas fases são ~29,3% do tick a n=100 hoje).

**O número que decide** (pré-registrado pelo estudo, adotado aqui):
projetar o custo de **10M de ticks a n=100 no mundo rico** =
ms/tick medido (Python otimizado) × 2,5 (custo estimado do mundo
vivo) ÷ 4 processos (Kaggle):

- Projeção **≤ 45 min** → fica em Python; núcleo nativo adiado sem
  culpa, revisitado quando uma carga real o exigir.
- Projeção **> 45 min** **e** kernel nativo **≥ 15×** nas fases
  portadas → aprovar o núcleo nativo (§3, Fase 5).
- Kernel **< 15×** → o problema é arquitetura de dados, não
  linguagem: refactor struct-of-arrays + Numba **antes** de qualquer
  nativo.

O resultado medido do spike está em `experiments/degrau1/README.md`
e o veredito do portão é registrado como adendo no fim deste
documento (§7).

---

## 3. O núcleo alvo — o desenho que todos os caminhos compartilham

Seja o destino Python otimizado, Rust, Numba ou JAX, todos consomem
a mesma arquitetura de dados. Desenhá-la uma vez é o que torna o
Portão 0 barato e a Fase 5/6 possíveis sem recomeçar.

### 3.1 Estado como arrays tipados (struct-of-arrays)

O estado numérico do mundo vira tabelas de forma fixa, com
**índices inteiros** no lugar de nomes (hotspot 4 é a semente):

| Tabela | Forma | Conteúdo |
|---|---|---|
| `cash` | `(N,)` f64 | caixa por empresa |
| `stocks` | `(N, C)` f64 | estoque por empresa × commodity (índice = `chain.COMMODITIES`) |
| `prices`, `anchor` | `(C,)` f64 | preço corrente e âncora B1 |
| `demand_factor` | `(C,)` f64 + `(C,)` i32 | fator e validade (atos de Deus/B3) |
| `remaining`, `grade` | `(D,)` f64 | verdade dos depósitos (grade = fog-of-war: nunca sai daqui) |
| `known_grade`, `known_size`, `known_mask` | `(N, D)` f64/f64/bool | conhecimento por empresa — o fog-of-war como dado |
| `fac_kind`, `fac_owner`, `fac_dep` | `(F,)` i32 | instalações em slots fixos (ordem = (dono, criação), a ordem do `_produce` atual) |
| `fac_age`, `fac_cond`, `fac_down_until` | `(F,)` i32/f64/i32 | B2: idade, condição, retorno de quebra |
| `claimed_by` | `(G,)` i32 | dono por célula da grade (−1 = livre) |
| `tools_until`, `tools_mult` | `(N, C)` i32/f64 | expiração e multiplicador de demanda por ferramenta já resolvidos |
| `stab`, `fx`, `royalty` | `(P,)` f64 | B3: estabilidade, câmbio-índice, regime de royalties por país |
| `regime`, `inv_cover` | `(C,)` i32/f64 | B1: regime de mercado e cobertura de inventário |

Nomes, textos, arquétipos e a Crônica **não** entram nas tabelas:
ficam na camada Python (§3.4). Tabelas de parâmetros (`chain.py`,
`market_params`, `country_data`, `facility_data`) continuam sendo
**dado versionado**, nunca código — princípio B0.1 do estudo.

### 3.2 O tick como função pura + a fronteira Python ↔ núcleo

```
camada Python (orquestra, narra, decide com objetos)
  ├─ atos de Deus / eventos endógenos (B3)         → escrevem nas tabelas
  ├─ políticas (heurística hoje; aprendidas depois) → intenções (buys/offers/capex) nas tabelas
  ├─ NÚCLEO NUMÉRICO: produce → market → ambiente (B1 regimes, B3 deriva, B2 desgaste)
  │     entrada: tabelas + intenções + chaves RNG do tick
  │     saída:   tabelas novas + buffer de eventos estruturados + deltas de ledger
  └─ projeção: Crônica (texto), frames, scoreboard — como hoje (SDD §5.5)
```

Regras da fronteira:

- **Uma chamada por tick** (ou por episódio) — nada de dict cruza a
  fronteira por tick; o overhead de binding é irrelevante por
  construção (lição do estudo §A3b).
- O núcleo **não escreve texto** (§3.4) e **não conhece políticas**:
  recebe intenções já resolvidas. A interface `Policy` por objetos
  do SDD §6.2 sobrevive na camada Python — quem morre é a ilusão de
  que decisão e aritmética precisam viver no mesmo processo lógico.
- **Modo REFERÊNCIA permanente**: o motor Python atual continua
  sendo o golden (§3.5). O núcleo novo nasce como *segunda
  implementação* e só vira oficial passando nos portões da §5.

### 3.3 RNG — dois domínios, nunca misturados

- **Domínio atual (oficial)**: um único `random.Random(seed)`
  (MT19937). O núcleo nativo, se aprovado, **replica** esse gerador
  (semeadura `init_by_array`, `random()` = genrand_res53,
  `uniform`/`shuffle` com a mesma aritmética) — ~100 linhas, e é o
  que preserva todos os goldens. Nenhuma contração FMA
  (`-ffp-contract=off`; Rust não contrai por padrão). **E replica
  a somação do CPython ≥3.12**: o `sum()` embutido usa somação
  compensada (Neumaier) — achado do Portão 0 (§7): sem ela, os
  totais do mercado divergem ~1 ulp do motor atual mesmo com a
  ordem das operações idêntica.
- **Domínio JAX (condicional, Fase 6)**: chaves PRNG com `split`
  por (mundo, tick, empresa, finalidade) — determinismo funcional
  por construção e paralelismo por mundos. É um domínio **novo**:
  reproduzível no mesmo hardware/backend/versão, **não** bit-igual
  ao domínio atual. Corridas oficiais declaram o domínio no
  `scoreboard` (`rng_domain: "mt19937" | "jax-prng"`); misturar
  domínios numa mesma corrida/temporada é proibido.

### 3.4 A Crônica como projeção — o núcleo emite códigos, Python narra

O event-sourcing do SDD §4 já é meio caminho: os eventos `flows`
são numéricos. O desenho completa a separação:

- O núcleo emite, por tick, um **buffer de eventos estruturados**
  de largura fixa: `(tick, kind_code, cid, fid, x, y, z)` —
  códigos inteiros para a taxonomia existente (`probe`, `mine`,
  `facility`, `chain_link`, `record`, `bankruptcy`, …) mais os
  códigos novos do mundo vivo (§4). Payload quantitativo vai nos
  campos numéricos; **nenhuma string** nasce dentro do núcleo/JIT.
- A camada Python projeta o buffer nos `Event` de hoje usando os
  **mesmos templates de texto** de `engine.py`/`chronicle.py` — a
  narrativa que o Deus lê não muda de voz; muda só quem faz a conta.
- Eventos puramente narrativos e raros (atos de Deus, rivalidade,
  resumo de era) podem continuar nascendo 100% em Python: eles são
  O(empresas) por tick no pior caso e não estão no caminho quente.
- Frames e `save_outputs` não mudam de schema (SDD §5.5): viewer e
  pipeline Kaggle sobrevivem a qualquer troca de núcleo.

### 3.5 Coexistência e goldens — como um núcleo novo ganha o cargo

Fixtures executáveis (a suíte atual + duas novas) são o contrato:

1. Determinismo mesma seed / seed diferente muda a história.
2. Snapshot/restore bit-idêntico no meio da corrida.
3. Conservação de massa e dinheiro (ledgers fecham).
4. Fog-of-war: ninguém nasce sabendo teor.
5. **Hash congelado de placar+crônica**: n=8 × 24 ticks e
   n=100 × 24 ticks, seed 42 — o mesmo estilo de golden que o v1 já
   usa para o fallback `world_data=False`.

Regras: núcleo candidato roda as fixtures **contra** o golden do
motor de referência; 100% verde é pré-condição, não meta. O hotspot
5 (`_emit_flows` enxuto) e qualquer outra mudança de payload entram
**somente** com decisão explícita de regravar goldens — registrada
em commit próprio, nunca como efeito colateral de otimização.

---

## 4. Mundo vivo v2 — os quatro sistemas (ordem do estudo)

Ordem de construção adotada do estudo (§B5), pela régua
(realismo + história) ÷ esforço. Para cada sistema: estado novo,
fórmula mínima, observação legal, evento de Crônica, invariante.
Detalhes de calibração e fontes: `ESTUDO-MOTOR-AMBIENTE.md` §B1–B4
(USGS/LME/World Bank Pink Sheet para preços; WGI/ICRG para países;
Weibull β≈1,6 e benchmarks de disponibilidade para equipamentos).
Custo combinado estimado: **<5% do tick a n=100**.

### B1 — Mercado vivo (entra primeiro)

*Por quê primeiro: sem elasticidade e inventário, todos os outros
sistemas jogam sobre um mercado morto — a demanda atual é quantidade
fixa e a banda de preço [0,3×; 3×] não consegue nem representar o
ciclo real do lítio (11× entre 2020 e 2025).*

- **Estado novo** (por commodity): âncora `p*_c` (custo marginal de
  longo prazo), regime `R_c ∈ {boom, normal, bust}`, cobertura de
  inventário `I_c` = estoque agregado ÷ demanda mensal, anel de 24
  meses de preços (público). Parâmetros em `data/market_params.json`:
  `(p*, κ, ε, γ, I*, σ, durações de regime)`.
- **Fórmula mínima** (por tick):
  demanda elástica `D_c = D0_c · (p_c/p*_c)^(−ε_c) · saz(t)`;
  multiplicador de inventário `m = exp(−γ_c·(I_c − I*_c))` sobre o
  preço; regime Markov com durações médias reais (boom 18–36m, bust
  24–48m) derivando `p*` (±0,5–1,5%/mês); preço persegue a âncora
  com velocidade `κ_c` + ruído `σ_c`; o ajuste por desequilíbrio
  atual continua, sobre a demanda elástica, com banda alargada
  para [0,25×; 6×] da âncora variável.
- **Observação legal**: preços e histórico (já públicos); `I_c` como
  **estoque de bolsa público** estilo LME — é o que torna a
  especulação uma decisão informada. O regime **não** é observável:
  infere-se do preço, como na vida real.
- **Crônica**: só transições e extremos — virada de regime
  ("o lítio entra em colapso: −52% em 6 meses, estoques em 4,1
  meses de demanda"), recordes de preço, escassez extrema.
- **Invariante**: conservação intacta (B1 não cria nem destrói
  massa/dinheiro; muda preços e quantidades demandadas). Calibração
  validada por notebook no Kaggle comparando momentos simulados
  (volatilidade, autocorrelação, duração de ciclo) com a série real.

### B3 — País e política (entra em seguida)

*Maior densidade narrativa por esforço do estudo inteiro; dá objeto
real ao traço `risk` e geografia real às decisões de expansão.*

- **Estado novo** (por país; cidades e depósitos ganham `country`):
  estabilidade `S ∈ [0,1]`, câmbio-índice `e`, regime de royalties
  `τ`. Baselines ancorados em WGI/ICRG (Chile ~0,65; Brasil ~0,45;
  Peru ~0,40; Argentina ~0,35; Bolívia ~0,30).
- **Fórmula mínima**: `S` = passeio com reversão à média do país
  (0,03/mês) + ruído 0,02; capex no país `×(1 + 0,25·(1−S))`;
  royalties = surcharge de 3–8% sobre o opex conforme `τ`; câmbio:
  fração local do opex `λ≈0,45` precificada em moeda local —
  desvalorização barateia o opex em US$ e encarece capex importado;
  **motor de eventos endógeno** (eleição a cada 48 ticks desloca
  `S̄`/`τ`; reforma de royalties ~6%/ano, **dobrando se preço >
  1,5× âncora**; restrição de exportação ~2%/ano; JV forçada
  ~1,5%/ano; paralisação ~0,7%/ano; subsídio ~4%/ano; desastre
  ~1%/ano — frequências latino-americanas 2015–2025).
- **O acoplamento que faz o mundo respirar**: preço alto (B1) →
  nacionalismo provável (B3) → custos sobem → próximo ciclo. É o
  loop que a mineração real viveu em 2021–2025.
- **Observação legal**: `S`, `e`, `τ` públicos (índices e câmbio são
  publicados). Probabilidades dos eventos, não.
- **Crônica**: eleição, reforma, nacionalização, paralisação —
  manchetes prontas; vilões e viradas que não dependem das empresas.
- **Invariante**: royalties são **sink** nomeado no ledger
  (`money_out` com motivo `royalty`); nenhum evento cria massa.

### B4a — Importações: o resto do planeta (entra com B3)

- **Estado novo**: nenhum por empresa — um participante "resto do
  mundo" no mercado, com preço de paridade
  `p_imp = p*_mundo · (1 + tarifa + frete)` por commodity.
- **Fórmula mínima**: preço interno acima da paridade → importações
  entram como oferta elástica crescente no spread (tampa o preço);
  abaixo da paridade de exportação → exportações absorvem o
  excedente (piso mole). Sanção (B3/Deus) = tarifa → ∞ num recurso:
  é por aqui que sanções mordem.
- **Observação legal**: paridade é pública.
- **Crônica**: só extremos ("importações de dispositivos inundam o
  mercado").
- **Invariante**: importação é **fonte de massa externa**
  contabilizada no ledger como tal (`imported`), e exportação é
  `sold_external` — a conservação continua auditável distinguindo
  massa do mundo de massa importada.

### B2 — Equipamentos: desgaste, quebra, manutenção (entra por último)

*As melhores decisões micro e o melhor diferenciador de arquétipos —
mas exige tocar política e observação, então vem depois que o mundo
ao redor existe. É também a primeira decisão contínua de verdade
para as políticas aprendidas do Degrau 2.*

- **Estado novo** (por instalação, §3.1): `age` (meses),
  `condition h ∈ (0,1]`, `down_until`.
- **Fórmula mínima**: eficiência `cap_efetiva = capacity · h ·
  (1 − 0,15·min(1, age/240))`; desgaste `h −= desgaste·utilização`
  (planta parada não desgasta — **mothball** em bust vira decisão);
  quebra por hazard de Weibull (β≈1,6) calibrado para
  disponibilidade **~80–85% sem manutenção, ~92–95% com**; reparo
  1–3 ticks a 8–15% do custo de construção, **decidido pela
  política** (nada de reparo automático); manutenção preventiva
  1,5–3% do custo restaura `h` (+0,5); **overhaul** a 60% do custo
  zera `age` e `h`. Os verbos manter / overhaul / expandir são a
  decisão que hoje não existe — instalação hoje é eterna e perfeita.
- **Observação legal**: idade/condição/status das **próprias**
  instalações; de rivais, só o sintoma público (queda de oferta,
  notícia da paralisação).
- **Crônica**: quebras com consequência ("a refinaria da Vetor Sul
  quebra no pico do cobre — 2 meses parada, US$ 0,6M de reparo");
  a Agressiva que roda até quebrar ganha um modo de falência novo
  e narrável.
- **Invariante**: reparo/manutenção/overhaul são sinks nomeados no
  ledger; downtime não produz nem consome — só deixa de produzir.

### B4b — Adoção tecnológica (curva S de Bass) — **fora do pacote v2**

Demanda do topo da cadeia escalando com `(0,3 + A·escala)`,
`dA/dt = (p + q·A)(1 − A)` (p≈0,03, q≈0,38/ano). Sozinha rende
pouco na Era 1; rende tudo quando a Era 2 abrir. **Entra junto com
a Era 2**, registrada aqui para não ser reinventada.

---

## 5. Plano de migração em fases (com portões numéricos)

| Fase | Conteúdo | Portão de saída (número, não opinião) |
|---|---|---|
| **0 — Spike** | `experiments/degrau1/`: overlay bit-idêntico + kernel nanobind descartável (§2) | Veredito registrado pela regra dos **45 min / 15×** (§2); equivalências verdes |
| **1 — Python otimizado oficial** | Hotspots 1–3 no motor oficial; commodities por índice inteiro (hotspot 4) se a projeção pedir; driver de episódios multiprocesso para treino/avaliação | Goldens §3.5 **100% bit-idênticos**; projeção 10M ticks (mundo rico, 4 proc.) recalculada e registrada; suíte completa verde |
| **2 — B1 Mercado vivo** | §4/B1 + `market_params.json` + notebook de calibração | Ledger fecha; corrida de veredito no Kaggle: dispersão de preços e marcos/corrida **≥ baseline** (régua do PRD — crônica visivelmente mais viva, ou não entra); custo adicional ≤2% do tick |
| **3 — B3 + B4a** | §4/B3 e §4/B4a integrados (sanção via paridade) | Idem Fase 2; eventos endógenos com frequências dentro das faixas ancoradas (±50% em 10 anos simulados × 20 seeds) |
| **4 — B2 Equipamentos** | §4/B2 + decisões novas na `Observation`/política | Idem; disponibilidade média das frotas dentro de 78–95% conforme manutenção; nenhum arquétipo com falência 100% por quebra (balanceamento) |
| **5 — Núcleo nativo (CONDICIONAL → ABERTA pelo Portão 0, §7)** | Rust/PyO3 (preferência do estudo: sem FMA por padrão, ecossistema provado) com C++/nanobind como alternativa equivalente; wheel pré-compilado distribuído no dataset de fontes do Kaggle | Portão 0 mediu: **projeção 213 min > 45 min E kernel 43,8× ≥ 15×** — fase aberta (a execução aguarda a fila das Fases 1–4, que mudam o conteúdo que o núcleo vai portar). Para virar oficial: fixtures §3.5 bit-idênticas 100% (incl. somação Neumaier, §3.3) + speedup medido ≥15× nas fases portadas |
| **6 — JAX (ESTRATÉGICA, CONDICIONAL)** | Reescrita do núcleo como funções puras sobre as tabelas §3.1; batch de mundos em GPU; domínio RNG próprio (§3.3) | Só abre com gargalo **medido**: temporada de MARL ecológico projetada em **≥50M de ticks** ou treino a n=100 que não caiba em sessão de Kaggle após as Fases 1+5. Entrada exige ADR próprio aceitando o novo domínio de determinismo |

Ordem de valor: Fases 1–4 entregam o Degrau 1 que o fundador
assiste (mundo vivo + treino com folga para o torneio e o IPPO
focal). Fases 5–6 são **infraestrutura sob demanda medida** — o
projeto nunca mais paga reescrita por antecipação.

Dependências com o Degrau 2 (forja): o torneio `ptq-policy-tournament-v1`
roda sobre a Fase 1; a forja consome o avaliador como está. O mundo
vivo muda o *conteúdo* das temporadas seguintes, não o protocolo.

---

## 6. O que NÃO muda (invariantes herdados do SDD)

- Determinismo por seed, fog-of-war como invariante de informação,
  conservação auditável, **nenhum LLM dentro do tick** (SDD §2).
- Contrato de saídas `frames/chronicle/scoreboard` (SDD §5.5) e o
  viewer burro (SDD §8).
- Pipeline Kaggle: na VM só código/testes/spikes curtos; corridas e
  treinos de verdade são notebooks com veredito impresso (SDD §7).
- A régua do PRD manda no mundo vivo: sistema que não deixa a
  crônica visivelmente mais viva **não entra**, por mais realista
  que seja.

## 7. Adendo — resultado do Portão 0 (medido em 26/10/2026)

Números completos, protocolo e reprodução:
`experiments/degrau1/README.md`. Resumo:

- **Equivalência do overlay Python**: bit-idêntica nos três
  fixtures (n=8×24, n=100×24, n=8×120 — hash do `state_dict`
  completo).
- **Teto do Python bit-idêntico**: o overlay dos hotspots 1–2
  mediu **mais lento** (0,85–0,87×); o hotspot 3 rende ~1,03× sem
  garantia de bit-identidade. A estimativa de 2,5–4× do estudo
  **não se materializou** em micro-otimizações — o melhor Python
  bit-idêntico é o motor atual: **2,042 ms/tick a n=100**.
  Projeção do portão: **213 min > 45 min**. (Robustez: com a
  estimativa otimista do estudo, 0,51–0,82 ms/tick, a projeção
  seria 53–85 min — o veredito não depende da falha do overlay.)
- **Teto do nativo**: kernel C++/nanobind a **43,8×** (n=100) e
  **45,8×** (n=1.000) sobre a referência em laços, nas fases
  `_produce` + `_market`. `_produce` bit-idêntico; divergência de
  ≤1 ulp em caixa/estoques **explicada e removível**: o `sum()` do
  CPython 3.12 é compensado (Neumaier) — com somas ingênuas na
  referência, a diff. cai a exatamente 0,0. A Fase 5 herda a
  obrigação de replicar a somação (§3.3).

**Veredito: PORTÃO ABERTO — núcleo nativo aprovado (Fase 5).**
A ordem de execução não muda: Fases 1–4 primeiro (o mundo vivo
define o conteúdo final do `step()` que o núcleo vai portar;
portar antes seria pagar a paridade duas vezes). A Fase 1 fica
reduzida ao que tem valor próprio — driver multiprocesso de
episódios e, se entrar, o refactor SoA (hotspot 4) como fundação
do núcleo, não como micro-otimização.
