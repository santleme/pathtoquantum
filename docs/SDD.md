# SDD — PATH TO QUANTUM
### Desenho do sistema: motor determinístico, crônica como fonte da verdade, políticas plugáveis
### v1.0 · 26/10/2026 · fundamentado no código v0 (`src/mundo/`)

---

## 1. Arquitetura em uma página

```
                 ┌────────────────────────────────────────────┐
  DEUS (config)  │ seed · nº empresas · eventos de Deus (JSON)│
        ────────►│                                            │
                 │   ENGINE (ticks mensais, determinístico)   │
                 │   ┌─────────┐  ┌──────────┐  ┌──────────┐  │
                 │   │ DECISÃO │─►│ PRODUÇÃO │─►│ MERCADO  │  │
                 │   │(polític.)│  │          │  │          │  │
                 │   └─────────┘  └──────────┘  └──────────┘  │
                 │        │               │            │      │
                 │        ▼               ▼            ▼      │
                 │   CHRONICLE (log de eventos, append-only)  │
                 │   FRAMES (snapshots anuais do estado)      │
                 │   LEDGERS (conservação de massa/dinheiro)  │
                 └────────────────────────────────────────────┘
                        │ frames.json · chronicle.json · scoreboard.json
                        ▼
                 VIEWER (HTML único, desacoplado — só lê JSON)
                        ▲
                 PIPELINE KAGGLE: corridas longas e treinos de
                 políticas rodam em notebook; a VM só codifica/testa.
```

Módulos (`src/mundo/`):

| Módulo | Responsabilidade |
|---|---|
| `world.py` | O mundo estático: grade lat/lon, depósitos e cidades reais. |
| `chain.py` | A árvore de produção: receitas, preços-base, demanda, instalações. |
| `companies.py` | O agente-empresa: estado, personalidade, conhecimento (fog-of-war). |
| `tools_sim.py` | Ferramentas simuladas: custos realistas e efeitos com prazo. |
| `engine.py` | O motor: fases do tick, mercado, falência/aquisição, ledger, frames. |
| `chronicle.py` | O log de eventos narrados (a Crônica) e a data simulada. |
| `cli.py` | O painel de Deus: argumentos → Engine → saídas. |

## 2. Princípios de desenho (invariantes)

1. **Determinismo por seed.** Um único `random.Random(seed)` alimenta o
   mundo inteiro. Mesma seed + mesma config + mesmos eventos de Deus =
   mesma história, bit a bit na crônica e no placar. É o que torna replay,
   comparação de corridas e ciência sobre o mundo possíveis.
2. **Nenhum LLM dentro do tick.** Decisões de tick são computação barata
   e determinística. Inteligência cara (RL treinado, CEO LLM) entra nas
   fronteiras — políticas pré-treinadas ou decisões anuais — nunca no
   laço mensal.
3. **Fog-of-war como invariante de informação, não como flag.** A empresa
   decide exclusivamente a partir do próprio `knowledge`; a verdade oculta
   do depósito (`grade`, `size_t`) só entra no `knowledge` de quem sondou.
   Teste executável garante: ninguém nasce sabendo teor.
4. **Conservação auditável.** Massa e dinheiro têm ledger: toda tonelada é
   extraída, produzida, consumida, desperdiçada ou vendida; todo dólar
   entra por venda às cidades ou sai por construção/sondagem/operação/
   ferramentas (comércio interno é soma-zero). Se o ledger não fecha, a
   corrida é inválida.
5. **A crônica é produto, não debug.** Todo fato que importa para a
   história vira evento estruturado no momento em que acontece (§4).
6. **Viewer burro, motor esperto.** O viewer não conhece regra nenhuma:
   lê `frames.json` e renderiza. Qualquer cliente futuro (outro player,
   vídeo gerado, feed) consome os mesmos JSONs.

## 3. O motor em ticks

Tick = **1 mês simulado**; início em jan/2027 (`START_YEAR`). `Engine.run(ticks)`
executa, por tick, nesta ordem fixa:

1. **Atos de Deus** (`_apply_god_events`): eventos agendados para o tick —
   `price_shock` (multiplica preço e fixa fator de demanda por duração),
   `discovery` (um depósito novo entra no mundo), `sanction` (demanda de
   um recurso e seu refinado cai a 50% por N meses).
2. **Falência** (`_check_bankruptcy`): empresa com caixa < 0 morre; se há
   comprador com caixa > US$ 12M, os ativos (instalações, território,
   estoques) são leiloados a 15% do custo de construção — o pagamento vai
   a credores (sink), nunca ao comprador.
3. **Decisões** (`_decide`, por empresa, em ordem de `cid`): a política
   produz intenções do tick — sondar/reivindicar/construir, construir o
   próximo elo, plano de compras (`_buys`), plano de vendas (`_offers` =
   excedente sobre o buffer de jusante) e uso de ferramentas.
4. **Produção** (`_produce`): instalações operam na ordem cadastrada —
   mina extrai `min(capacidade, restante)` × teor (o resto é rejeito, no
   ledger); refinaria converte bruto→refinado com `REFINE_YIELD = 0,6`;
   fábrica/planta/montadora consomem a receita inteira ou não produzem.
   Custos operacionais são debitados por unidade processada.
5. **Mercado** (`_market`, por commodity, em ordem alfabética):
   (a) comércio entre empresas — compradores atendidos por `cid`,
   vendedores dividem proporcionalmente ao ofertado, ao preço corrente;
   (b) demanda das cidades sobre o restante — `CITY_DEMAND` × fator de
   demanda, dividido por peso, onde InstaSim ativo **pesa 2,2×** na fatia
   de dispositivos e ZapSim ativo **pesa 1,3×** nas vendas do vendedor;
   (c) ajuste de preço por desequilíbrio oferta×demanda, com fator
   limitado a [0,72; 1,35]/tick e preço preso à faixa [0,3×; 3×] do base.
6. **Snapshot**: a cada 12 ticks (e no tick final), um frame (§5).

## 4. Event-sourcing da Crônica

### 4.1 O evento é a unidade da história

```json
{ "tick": 26, "kind": "probe", "company": "Lítio Austral",
  "text": "Lítio Austral sonda Salar de Uyuni e encontra um depósito RICO.",
  "data": {}, "date": "mar/2029" }
```

Campos: `tick`, `kind` (taxonomia abaixo), `text` (a narrativa pronta),
`company` (protagonista, quando há), `data` (payload estruturado para
consultas futuras) e `date` (derivada do tick por `sim_date`).

Taxonomia v0 (`kind`): `founding` · `probe` · `mine` · `facility` ·
`chain_link` (primeira empresa a dominar um elo — registrado uma única
vez por elo em `first_link`) · `tool` · `god` · `bankruptcy` ·
`acquisition` · `record` · `end`.

### 4.2 O log é a fonte da verdade; o estado é uma projeção

Decisão arquitetural que o v0 já pratica pela metade — e que o desenho
formal assume por inteiro:

- **A crônica é append-only e completa para a narrativa**: tudo o que o
  Deus vê (viewer, veredito, retrospectiva) é derivado do log de eventos
  + dos frames. Nada que aparece na tela existe fora dessas duas fontes.
- **Frames são snapshots materializados do estado** em fronteiras anuais:
  a projeção "estado do mundo no tick T" sem precisar reexecutar o mundo.
- **Replay tem dois modos**, ambos suportados pelo desenho:
  1. **Replay por snapshot** (viewer): scrub pelos frames + eventos com
     `tick ≤ frame.tick` — barato, é o modo de assistir.
  2. **Replay por reexecução** (auditoria/ciência): seed + config +
     eventos de Deus reexecutam o motor e **têm** de reproduzir a mesma
     crônica — garantido pelo determinismo (§2.1) e testado
     (`test_determinism_same_seed`).
- **Evolução desenhada (v1+)**: enriquecer `data` dos eventos com os
  deltas quantitativos (quantidades, preços, caixas antes/depois) até o
  ponto em que o estado em qualquer tick seja reconstruível por
  *fold* do log a partir do último snapshot — event-sourcing completo do
  estado, não só da narrativa. O motor não muda; muda a riqueza do log.

### 4.3 Por que não event-sourcing total desde o v0

O estado interno do tick (estoques fracionários, intenções `_buys/_offers`)
é volumoso e efêmero; a narrativa é esparsa e permanente. O v0 grava o
permanente (eventos + snapshots anuais + ledgers agregados) e reconstrói o
efêmero por reexecução determinística quando preciso. É o mesmo contrato
externo (log + snapshots), sem pagar o custo de serializar cada decisão.

## 5. Modelo de dados

### 5.1 Mundo (`world.py`)

- Grade: lat −56…14, lon −82…−32, célula de 2,5° → **28×20 células**;
  `cell_of(lat, lon)` projeta coordenada real em célula.
- `Deposit{name, resource, lat, lon, size_t, grade, cell}` — `size_t` e
  `grade` são **a verdade oculta**; a informação pública de um depósito é
  só nome/recurso/posição (`deposit_public_info()`).
- `City{name, lat, lon, demand_weight, cell}` — mercados. v0: 10 depósitos
  e 8 cidades reais da América do Sul.

### 5.2 Cadeia (`chain.py`) — dados, não código

- `RAW_TO_REFINED`: lithium_ore→lithium, copper_ore→copper,
  iron_ore→iron, oil→plastic; `REFINE_YIELD = 0,6`.
- `RECIPES` por unidade: component = 0,020 t copper + 0,005 t lithium;
  device = 2 components + 0,050 t iron + 0,020 t plastic;
  supercomputer = 10 devices + 5 components.
- `BASE_PRICES` (US$/t ou US$/unidade) e `CITY_DEMAND` (mensal, mundo
  todo) por commodity; `COMMODITIES` deriva de `BASE_PRICES`.
- `FACILITIES{kind: cost, capacity}`: mine 420 t/mês, refinery 320 t/mês,
  factory 300 comp/mês, plant 130 disp/mês, assembly 2 super/mês;
  `OPERATING_COST` por unidade; `CLAIM_COST` e `PROBE_COST` fixos.
- **Eras**: o elo 5 (`assembly`/supercomputador) fecha a **Era 1 — The
  Path to the Supercomputer**. A **Era 2 — Path to Quantum** entra como
  extensão desta mesma tabela (novas commodities, receitas e instalações
  além do supercomputador), sem mudança de motor: a cadeia é dado.

### 5.3 Empresa (`companies.py`)

```
Company{ cid, name, archetype, traits{aggression, risk, vertical,
  marketing}, hq_city, color, cash,
  stocks{commodity -> float}, facilities{fac_id -> {id, kind, cell,
  deposit?}}, claimed{cell}, knowledge{dep_name -> (grade, size_t)},
  tools: ToolEffects, alive, founded_tick }
```

- `chain_stage()` → 0…5 a partir das instalações (o placar da empresa).
- `make_companies(n, rng)`: 8 arquétipos × nomes × paleta fixos; caixa
  inicial ~US$ 40M × U(0,85; 1,2) sorteado pelo RNG do mundo (parte do
  determinismo).
- Reserva de caixa da política: `1,5M + (1 − risk) × 2M` — a cautela mora
  nos números, não em `if` de arquétipo.

### 5.4 Ferramentas (`tools_sim.py`)

Contrato de módulo de ferramenta (o que toda "integração" futura
implementa):

```
ToolEffects{ insta_until, insta_strength, zap_until }  # estado por empresa
custo(tick) -> US$        # faixa real da ferramenta de verdade
aplicar(engine, company)  # debita via ledger e agenda o efeito
efeito no mercado         # peso/prioridade com expiração por tick
```

v0: InstaSim — CPM US$ 9 × 400 mil impressões = US$ 3.600/campanha, 3
ticks, peso 2,2 na demanda de dispositivos; ZapSim — US$ 0,05 × 60 mil
conversas = US$ 3.000/campanha, 2 ticks, peso 1,3 nas vendas.

### 5.5 Saídas (o contrato com o mundo externo)

`Engine.save_outputs(outdir)` grava, e nada além disto cruza a fronteira:

- `frames.json` — `{seed, ticks, frames[], chronicle[]}`; frame =
  `{tick, date, prices{}, companies[{id, name, archetype, color, hq,
  alive, cash, stage, territory[], facilities[{kind, cell, deposit}],
  stocks{}}], deposits[{name, resource, cell, lat, lon,
  remaining_frac}]}`.
- `chronicle.json` — o log de eventos (§4.1).
- `scoreboard.json` — `[{name, archetype, alive, cash, stage,
  facilities}]` ordenado por caixa: o veredito da corrida.

## 6. Arquitetura de políticas plugáveis

### 6.1 Estado atual (v0)

A política é a heurística embutida `Engine._decide` + auxiliares
(`_pick_deposit`, `_build_downstream`, `_plan_buys`, `_plan_sells`,
`_use_tools`), parametrizada pelos `traits` da empresa. Ela só lê o que a
empresa pode saber: próprios estoques/caixa/instalações, `knowledge`,
preços públicos e o mapa público de reivindicações.

### 6.2 O contrato (desenho para v1/v2)

Toda política — heurística, treinada ou CEO — implementa a mesma
interface, e o motor passa a chamá-la em vez de conter a lógica:

```
class Policy:
    def decide(self, obs: Observation, rng) -> Intentions

Observation  # TUDO que a empresa pode ver, e nada além:
  self_view   (caixa, estoques, instalações, knowledge, tools ativos)
  public_view (preços, depósitos públicos, claimed_by, placar público)
Intentions
  probe?/claim?/build? · buys{commodity: qty} · offers{commodity: qty}
  tools{insta: bool, zap: bool}
```

Regras do contrato:

- **Simetria de informação é do motor**: a `Observation` é construída
  pelo motor a partir do estado da empresa — política nenhuma recebe o
  `Engine`. Fog-of-war deixa de ser disciplina e vira tipo.
- **A heurística v0 vira a política de referência** (`HeuristicPolicy`),
  usada como baseline de toda temporada e como fallback de qualquer
  política que quebre.
- **Ordem de decisão determinística**: empresas decidem em ordem de `cid`
  e toda aleatoriedade da política vem do `rng` sorteado pelo motor —
  políticas aprendidas entram em modo avaliação (sem exploração) nas
  corridas oficiais.
- **Políticas treinadas (v2)**: treinadas no Kaggle (ambientes = o próprio
  motor via wrapper de episódio), exportadas como artefato versionado e
  **congeladas** durante uma temporada; a crônica registra qual versão de
  política cada empresa rodou (proveniência no `data` dos eventos dela).
- **CEO LLM (v2+)**: chamado só em fronteiras anuais, recebe a crônica e
  o placar da própria empresa e devolve diretivas estratégicas (ex.:
  "vertical := 0,9; foco: lithium") que parametrizam a política do ano
  seguinte. O tick nunca espera um LLM.

## 7. Pipeline Kaggle (a regra de computação)

- **Na VM de desenvolvimento**: escrever código e rodar **testes
  estruturais** (fixtures de poucos ticks). Nenhuma corrida de verdade,
  nenhum treino.
- **No Kaggle**: `scripts/kaggle_push_kernel.py --bundle-src` empacota
  `src/` + `pyproject.toml` no dataset privado
  `pascalcoimbra/mundo-autonomo-src` e empurra o kernel
  `pascalcoimbra/mundo-autonomo-nascimento-v0` (payload `slug` +
  `newTitle` ≤ 50 caracteres).
- O notebook instala o pacote a partir do dataset, roda a corrida
  (v0: 120 ticks, 8 empresas, seed 42), imprime os **marcos da crônica e
  o placar** como veredito no próprio log, e salva os três JSONs (§5.5)
  em `/kaggle/working` para download → pasta `viewer/` local.
- Treinos de políticas (v2) seguem o mesmo trilho: notebook novo por
  experimento, veredito impresso pelo notebook, artefato de política
  versionado como dataset.

## 8. Viewer

`viewer/index.html` — arquivo único, zero dependências, zero build.
Consome `frames.json` (com a crônica embutida) e oferece: player
(play/pause/velocidade/scrub), mapa de células com território colorido
por empresa (paleta de `companies.py`), instalações, depósitos com
`remaining_frac`, cidades-mercado, placar lateral e feed da crônica
sincronizado ao frame. Por só conhecer o schema §5.5, o viewer sobrevive
a qualquer mudança de motor — e qualquer outro cliente também.

## 9. Testes como especificação executável

Os 9 testes de `tests/test_engine.py` são as cláusulas deste desenho:

| Teste | Cláusula |
|---|---|
| `test_determinism_same_seed` / `test_different_seed_differs` | §2.1 determinismo |
| `test_mass_conservation` / `test_money_conservation` | §2.4 ledgers fecham |
| `test_fog_of_war_knowledge_only_by_probing` | §2.3 / §5.1 informação |
| `test_chain_requires_inputs` | §5.2 receita é obrigatória |
| `test_instasim_debits_and_expires` | §5.4 custo e expiração de ferramenta |
| `test_frames_and_chronicle_shape` | §5.5 contrato de saída |
| `test_god_price_shock_event` | §3.1 atos de Deus |

## 10. Decisões, trade-offs e evolução

- **Grade 2,5° em vez de mapa vetorial**: barato, legível no viewer e
  suficiente para território; precisão geográfica fina é problema de
  conteúdo (v1 adiciona recortes), não de motor.
- **Preços por desequilíbrio com banda limitada**: evita explosão/
  colapso de preço em mundo pequeno, ao custo de realismo em choques
  extremos — aceito no v0; choques de Deus existem justamente para
  forçar a banda.
- **Sem finanças no v0** (juros, ações, crédito): o dinheiro é caixa e
  sink/fonte nas cidades. Banco simulado entra como *ferramenta* (§5.4)
  antes de virar sistema monetário.
- **Evolução planejada, nesta ordem**: (1) `data` rico nos eventos →
  event-sourcing completo do estado (§4.2); (2) extrair `Policy` formal
  (§6.2) sem mudar comportamento; (3) eras como dado — tabela da Era 2
  (Path to Quantum) ao lado da Era 1; (4) mundos maiores por recortes
  múltiplos da grade.
