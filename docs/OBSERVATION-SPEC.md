# SPEC — Camada de Observation (guarda v2)

**Problema.** A guarda v1 (`src/mundo/program.py`) é um lint por AST:
ela barra *escritas* fora da allowlist, mas AST não enxerga tipo — a
*leitura* de campos que a empresa não deveria ver continua possível
porque a interface `Policy.decide(engine, comp)` entrega os **objetos
vivos do motor**. O caso nomeado na revisão da forja: `deposit.grade`
cru. A correção estrutural é a que o SDD §6.2 já desenhava e que
`docs/ALGORITMOS-DECISAO.md` (achado 1) registrou como pré-requisito
de RL sério: **fog-of-war por tipo, não por disciplina** — a política
recebe uma `Observation` tipada e congelada, construída pelo motor a
cada decisão, contendo só o que a empresa enxerga de si e do mundo
público. Nada de `Engine`, nada de `Company` de ninguém, nem a
própria em forma crua.

Esta spec inventaria o que a política lê hoje (campo a campo, do
código real de `HeuristicPolicy` em `src/mundo/engine.py` e da
semente em `forge/seed_policy.py`), classifica cada item, define o
formato da Observation e fatia a migração com aceitação testável.

---

## 1. Inventário — tudo que a política lê hoje

### 1.1 Da própria empresa (`comp`)

| Acesso | Classificação | Destino na Observation |
|---|---|---|
| `comp.traits` (aggression/risk/vertical/marketing) | PRÓPRIO | `me.traits` (mapping somente-leitura) |
| `comp.cash` | PRÓPRIO | `me.cash` (vivo, só leitura) |
| `comp.stocks[c]` | PRÓPRIO | `me.stocks` (mapping só leitura) |
| `comp.facilities` → `fac["kind"]`, `fac["id"]`, `fac.get("deposit")` | PRÓPRIO | `me.facilities` (tupla de `FacilityView`) |
| `comp.has(kind)`, `comp.chain_stage()` | PRÓPRIO (derivado) | `me.has()`, `me.chain_stage()` (vivos) |
| `comp.knowledge.get(name)` → `(grade, size_t)` sondados | PRÓPRIO | `me.knowledge` (mapping só leitura) |
| `comp.claimed` (pertinência) | PRÓPRIO | `me.claimed` (conjunto só leitura) |
| `comp.name`, `comp.cid`, `comp.hq_city`, `comp.archetype` | PRÓPRIO/público | `me.*` |
| `comp.tools.*_active(tick)` e campos `*_until` | PRÓPRIO | `me.tools` (`ToolsView`) |
| `comp.alive` | PRÓPRIO | `me.alive` |

Escritas na própria empresa (superfície de AÇÃO, não leitura —
viram verbos do `Actuator`, §3): `knowledge[nome] = …` (sondagem),
`claimed.add(célula)`, `add_facility(kind, célula)` +
`fac["deposit"] = nome`, `_offers[c] = q`, `_buys[c] = q`,
`tools.*_until/*_strength = …`.

### 1.2 Do motor (`engine`) — leituras

| Acesso | Classificação | Destino na Observation |
|---|---|---|
| `engine.tick` | PÚBLICO (tempo do mundo) | `world.tick` |
| `engine.equip_v2` (e flags irmãs) | PÚBLICO (regras do mundo) | `world.equip_v2` etc. |
| `engine.deposits` → `.name/.resource/.lat/.lon/.cell` | PÚBLICO (= `deposit_public_info()`) | `world.deposits` (`DepositView`) |
| `engine.claimed_by.get(célula)` | PÚBLICO (mapa de reivindicações, SDD §6.1) | `DepositView.claimed_by` |
| `engine.prices[c]` | PÚBLICO | `world.prices` (mapping só leitura) |
| `engine._city_by_name[sede]` → lat/lon/cell | PÚBLICO (geografia), via atributo **privado** | `me.hq` (`CityView`); `world.cities` |
| `engine.deposit_country(dep)`, `engine.city_country(nome)` | PÚBLICO (geografia política; função pura de tabelas) | `DepositView.country`, `CityView.country` |
| `engine.capex_mult(país)` | PÚBLICO-derivado (função de `S`, que é série pública — `country_state` é documentado como "qualquer empresa lê") | `world.capex_mult(país)` (pré-computado na construção) |
| `engine._countries[*]` → `S`, `fx`, `tau` | PÚBLICO (idem) | `world.countries` (`CountryView`) |
| `engine._equip["policy"]`, `engine._equip["model"]` | DADO (parâmetros `equipdata`, regras do mundo), via atributo **privado** | `world.equip_policy`, `world.equip_model` |
| `engine._fac_equip(fac)` → `age/cond/broken/down_until/repair_cost` | PRÓPRIO (estado das **próprias** instalações; `facility_condition` já é documentado como "a observação LEGAL das próprias instalações"), via método **privado** | `FacilityView.equip` (`EquipView`, preguiçoso — mesma ordem de criação de hoje) |
| `engine.rng.uniform/random` | INFRA (fluxo do motor) | `obs.rng` — fachada forward-only (`uniform`/`random`), sem o objeto `Random` |

Ações sobre o motor (viram verbos do `Actuator`): `_spend`,
`chronicle.add` (narração), `_note_link`, `repair_facility`,
`maintain_facility`, `overhaul_facility`.

### 1.3 O que a política NÃO lê hoje (fica fora da Observation v1)

- `engine.companies` — caixa/estoques/instalações/knowledge de
  rivais. Nunca lido pela heurística; banido pela AST em programas.
  A Observation **não tem lista de empresas**.
- `engine.remaining` — massa restante por depósito (verdade do mundo
  derivada da extração). Nunca lido. Fora da v1; virar "público
  agregado" exige decisão própria (fatia futura).
- Internos do mercado vivo (`anchors`, `_regime`, `_demand_ema`…):
  a política só lê `prices`.
- Probabilidades de eventos políticos, `demand_factors`, ledger,
  `money_in/out`, `frames`, `state_dict` — internos do motor.

---

## 2. Vazamentos reais achados no inventário

Leitura (a classe que esta camada fecha):

- **L1 — `Deposit.grade` de depósito NÃO sondado.** `pick_deposit`
  devolve o objeto `Deposit` vivo; o `decide` lê `target.grade` /
  `target.size_t` — e qualquer programa pode ler o teor de qualquer
  depósito a qualquer momento, sem pagar sondagem. É o vazamento
  nomeado em `program.py`. O fog-of-war hoje é disciplina.
- **L2 — `Deposit.size_t` idem** (tamanho exato sem sondar).
- **L3 — `engine.god_events` legível**: a lista de eventos de Deus
  *futuros* (tick exato, commodity, fator de choque, descobertas)
  é um atributo comum do objeto entregue à política. Ler = saber
  o choque antes dele = insider trading estrutural. A guarda v1
  não bane (só bane `.rng`/`.companies` e escritas).
- **L4 — `engine._force_events` legível**: eventos políticos
  forçados futuros do B3, via atributo de underscore simples —
  a guarda v1 não cobre leitura de privados que não sejam dunder.
  Mesma classe do L3.
- **L5 — `engine.rng` como objeto** entregue pela interface:
  `getstate`/`setstate` permitiriam clonar/prever/reiniciar o
  fluxo de aleatoriedade do mundo. Para programas a AST já bane
  `.rng`; estruturalmente a interface continua entregando o
  objeto a qualquer `Policy` Python. A Observation entrega só a
  fachada de sorteio.

Escrita (classe adjacente, fechada de quebra pela mesma fatia):

- **E1 — mutação por chamada de método em contêineres vivos.** A
  guarda v1 cobre atribuição/subscrito/delete/for, mas não chamadas:
  `comp.stocks.add(idx, delta)` (o `StockBook` tem método `add`),
  `engine.deposits.append/pop`, `dict.clear()` etc. mutariam o
  mundo sem passar por nenhum verbo. Na Observation nenhum objeto
  exposto tem método mutante: depósitos são tupla de views,
  estoques/knowledge são mappings sem `__setitem__`, e escrita só
  existe nos verbos do `Actuator`.

---

## 3. Formato da Observation

```
Observation            # construída pelo motor a cada _decide
  me: CompanyView      # a empresa focal, só leitura
  world: WorldView     # o público, só leitura
  act: Actuator        # os verbos legais de ação
  rng: RandomFacade    # uniform/random forward-only
```

Decisões de formato, com o critério **menor ruptura + bit-exatidão**:

1. **Views vivas por baixo, congeladas por cima** — não snapshots de
   valores. Motivo: a heurística relê estado *depois de escrever*
   dentro da mesma decisão (`maintain_equipment` confere
   `comp.cash` após cada reparo pago; `chain_stage()` após construir).
   Um snapshot congelado de `cash` mudaria decisões e quebraria os
   goldens. As views guardam a referência viva sob nome
   *name-mangled* e expõem só propriedades sem setter: a política
   **lê o valor vivo, mas não escreve** — "congelada" é sobre a
   superfície, não sobre fotografar o mundo. Onde nada muda durante
   uma decisão (depósitos, cidades, países, capex), a view é cópia
   de escalares — que é também o que impede L1/L2: `DepositView`
   **não tem** os campos `grade`/`size_t`.
2. **A sondagem vira verbo**: `act.probe(nome) -> (grade, size_t)`
   executa, nesta ordem, o gasto (`reason="probe"`), o registro em
   `knowledge` e devolve o par revelado — que a partir daí é
   conhecimento PRÓPRIO e legal. A narração (limiares 0,78/0,35,
   constantes estruturais) continua na política, com os mesmos
   textos e a mesma ordem de eventos.
3. **Intenções continuam imperativas nesta fatia.** O SDD §6.2
   esboça `decide(obs, rng) -> Intentions` (declarativo). Devolver
   intenções muda *quando* o estado muta dentro do tick e é uma
   segunda migração, com risco próprio aos goldens; fica para a
   fatia 3. Na fatia 1 as intenções de compra/venda viram verbos
   (`act.buy`/`act.offer`, que escrevem nos mesmos `_buys`/`_offers`
   que o motor já zera a cada decisão) e as demais ações viram os
   verbos do `Actuator` — mesma ordem de mutação de hoje, bit a bit.
   Desvio registrado e consciente do esboço do SDD.
4. **O `rng` do esboço vira `obs.rng`** (um argumento a menos):
   fachada com só `uniform(a, b)` e `random()` — os dois sorteios
   que a heurística usa — repassando ao `Random` do motor na mesma
   ordem. Para programas, a guarda mantém `.rng` banido no fonte:
   sorteio, para código evoluído, é serviço embutido nos métodos
   herdados, nunca objeto alcançável.
5. **Guarda v2 = v1 + fronteira.** A AST v1 fica intacta (todas as
   suas regras e testes valem). A v2 soma: (a) a fronteira de
   runtime — programas só recebem a `Observation`; (b) regra AST
   nova: nome de atributo contendo `__` (exceto `__init__`) é
   violação — fecha o acesso textual aos internos *mangled* das
   views (`_Actuator__engine` e cia.); (c) o loader exige a
   assinatura nova: `decide(self, obs)` precisa ligar com um único
   argumento posicional, senão `ValueError` na carga com a
   explicação do contrato.

---

## 4. Plano de migração em fatias

### Fatia 1 — Observation + heurística/genoma/programa sobre ela (ESTA)

- `src/mundo/observation.py`: views, `Actuator`, `RandomFacade`,
  `build_observation(engine, comp)` / `build_company_view(...)`.
- `HeuristicPolicy` (e, por herança, `GenomePolicy`) reescrita
  sobre `obs`; `Policy.decide(self, obs)`; `PolicyRouter`
  despachando por `obs.me.cid`; fachadas do `Engine`
  (`_decide/_reserve/_pick_deposit/…`) mantidas com a assinatura
  externa de hoje, construindo a Observation por dentro.
- `forge/seed_policy.py`: o `decide` da geração 0 reescrito sobre
  `obs`, espelhando a heurística método a método.
- `mundo/program.py`: guarda v2 (regra `__`, checagem de assinatura
  no loader, docstring com o limite L1/L2 marcado como FECHADO).
- Doubles de política nos testes (`test_hardening`, `test_v1`,
  `test_native_parity`) migrados para a assinatura nova — sem tocar
  em nenhuma asserção; o literal de estrutura do
  `test_forge_smoke` (que fixa o texto da assinatura do `decide` da
  semente) é atualizado para `def decide(self, obs):` — é o único
  ponto em que um teste fixa o contrato que esta fatia muda.

**Aceitação da fatia 1 (testável):**
- Goldens da Fase 1 intactos (`tests/test_golden.py` sem edição).
- `test_seed_generation0_bit_identical` e
  `test_evaluator_seed_matches_genome0_score` verdes sem edição
  (S da semente == S do genoma 0; episódio da semente == episódio v0).
- Suíte inteira verde: 202 + testes novos de `tests/test_observation.py`.
- Testes novos provam: grade/size de depósito não sondado
  inalcançáveis (`AttributeError`); estado de rival ausente da
  Observation; `god_events`/`_force_events` invisíveis; views
  imutáveis (escrever em `me.cash`, `me.knowledge`, `me.stocks`,
  `world.*` levanta erro); programa que tenta vazar falha de forma
  detectável (guarda rejeita `_Actuator__engine`; runtime levanta
  `AttributeError` para `.grade` e para `obs.world.companies`;
  assinatura antiga rejeitada no loader); `act.probe` revela e
  registra em `knowledge` com o mesmo custo/fluxo de hoje.

### Fatia 2 — Observation serializável + séries públicas novas

- `Observation.to_snapshot() -> dict` (valores, sem referências
  vivas): o formato que um wrapper de episódio p/ IPPO consome —
  pré-requisito do braço A2 sem quebrar o fog-of-war.
- Decisão própria (com spec): expor séries públicas do mercado vivo
  (âncoras/regimes) e placar público de rivais (o que a crônica já
  narra) — só o que for público por desenho.
- Aceitação: snapshot == valores da view viva no mesmo tick;
  episódio com política lendo snapshot reproduz o episódio da view
  (para a heurística, nos blocos de treino do torneio).

### Fatia 3 — Intentions declarativas (o esboço literal do SDD §6.2)

- `decide(obs) -> Intentions`; o motor aplica as intenções na ordem
  canônica. Habilita replay de decisões e políticas que não executam
  código no caminho quente.
- Aceitação: goldens re-provados bit a bit OU regravação explícita
  com decisão registrada (nunca silenciosa).

### Fatia 4 — Aposentar a superfície v1

- Remover as fachadas legadas do `Engine` se nenhum chamador restar,
  e os canais v1 da guarda (`comp._offers/_buys/knowledge`,
  `engine.claimed_by`) quando nenhum programa vivo depender deles.
- Aceitação: suíte verde; `grep` sem chamadores; guarda rejeitando
  os canais antigos com mensagem apontando para os verbos novos.
