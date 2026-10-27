# LOG — Camada de Observation (guarda v2)

Registro da construção da camada de Observation (spec:
`docs/OBSERVATION-SPEC.md`). Branch: `obs/guarda-v2`.

## 2026-10-27 — Fatia 1 entregue

**Base da branch.** A branch nasce da ponta corrente do projeto
(`forja/smoke-v1`, que contém a `main` + forja fatia 1 revisada +
Fase 5 + smoke da forja): é nela que vive a baseline de 202 testes
que a aceitação da fatia usa. A `main` local está 4 commits atrás
dessa ponta (196 testes) — ramificar dela apagaria o smoke do
caminho da suíte.

**Inventário e vazamentos** (detalhe na SPEC §1–2). A heurística lê
~45 pontos de `comp`/`engine`; classificados um a um
(próprio/público/público-derivado/dado/infra). Vazamentos reais de
leitura achados: **grade e size_t crus de depósito não sondado**
(o objeto `Deposit` vivo devolvido por `pick_deposit` — o limite
declarado da guarda v1), **`engine.god_events`** (choques futuros
com tick e fator — insider estrutural, atributo comum, não banido
pela AST) e **`engine._force_events`** (eventos políticos forçados
futuros, via underscore simples). Mais o estrutural
**`engine.rng` como objeto** entregue pela interface (mitigado p/
programas pela AST; fechado agora pela fachada forward-only) e,
adjacente, o buraco de **escrita por método** em contêineres vivos
(`StockBook.add`, `list.append`…), que a Observation fecha por não
expor método mutante nenhum.

**O que foi construído.**

- `src/mundo/observation.py` (novo): `Observation{me, world, act,
  rng}`; views só-leitura vivas por baixo (propriedades sem setter,
  internos *name-mangled*, sem `__dict__`): `CompanyView`,
  `StockView`, `KnowledgeView`, `ClaimedView`, `ToolsView`,
  `FacilityView`, `EquipView`, `WorldView`, `DepositView` (SÓ o
  público — sem `grade`/`size_t`), `CityView`, `CountryView`;
  `Actuator` com os verbos (`spend`, `probe`, `register_claim`,
  `build_facility`, `repair/maintain/overhaul`, `buy/offer`,
  `set_tool`, `narrate`, `note_link`); `RandomFacade` só com
  `uniform`/`random`. Builders `build_observation` /
  `build_company_view` rodam a cada decisão (claims do mesmo tick
  já aparecem para quem decide depois).
- `src/mundo/engine.py`: `Policy.decide(self, obs)`;
  `HeuristicPolicy` inteira reescrita sobre `obs` (método a método,
  mesma ordem de sorteios, gastos, narrações e mutações);
  fachadas do `Engine` (`_decide`, `_reserve`, `_pick_deposit`,
  `_build_downstream`, `_plan_buys`, `_buffer`, `_plan_sells`,
  `_use_tools`) mantidas com a assinatura externa de hoje,
  construindo a Observation por dentro.
- `src/mundo/policies.py`: `PolicyRouter` despacha por
  `obs.me.cid` com a interface nova. `GenomePolicy` não muda
  (herda; genoma 0 e campeões seguem válidos).
- `forge/seed_policy.py`: `decide` da geração 0 reescrito sobre
  `obs`, espelhando a heurística; docstring com o contrato v2.
- `src/mundo/program.py` (guarda v2): AST v1 intacta + regra nova
  (atributo com `__`, exceto `__init__`, é violação — fecha o
  acesso textual aos internos *mangled* das views) + loader exige
  `decide(self, obs)` ligável com um argumento (senão `ValueError`
  com o contrato). Docstring marca o limite L1/L2 como FECHADO.
- Testes: doubles de política migrados para a nova assinatura
  (`test_hardening`: Null/Recording/Suicidal; `test_v1`:
  CapexSuicide; `test_native_parity`: Noop) — **nenhuma asserção
  tocada**, os doubles passam a agir por `obs.act.spend`. Único
  literal de contrato atualizado: `test_forge_smoke` fixa agora
  `def decide(self, obs):` (o teste fixa o texto da assinatura da
  semente, que é exatamente o contrato que esta fatia muda).
  Novo `tests/test_observation.py` com 12 testes (superfície sem
  verdade oculta, probe como única revelação, rival/futuro
  ausentes, rng forward-only, views congeladas, vivacidade
  intra-decisão, claims frescos por decisão, guarda v2 na AST e no
  loader, tentativas de vazamento de programa falhando de forma
  detectável, mundo vivo B1+B3+B2 rodando sobre a Observation).

**Prova de que o mundo não mudou.**

- Baseline antes: 202/202. Depois: **214/214** (202 + 12 novos).
- `tests/test_golden.py` **sem edição**: os 4 hashes da Fase 1
  intactos (clássico n=8/n=100, 120 ticks, mundo builtin).
- `test_seed_generation0_bit_identical` **sem edição**: episódio da
  semente == episódio v0 (scoreboard, crônica, super) em 3 seeds.
- `test_evaluator_seed_matches_genome0_score` e o mini-smoke
  (`test_smoke_miniature_end_to_end`) **sem edição**: S da semente
  == S do genoma 0 a 1e-12.
- `test_native_parity.py` verde: o motor Python segue bit-idêntico
  ao núcleo nativo C++ (que implementa a heurística por dentro) —
  a troca de interface não vazou para o comportamento.

**Decisões de desenho registradas** (SPEC §3): views vivas em vez de
snapshots (a política relê caixa/elo depois de agir no mesmo tick —
snapshot quebraria os goldens); sondagem como verbo que revela;
intenções imperativas via Actuator nesta fatia (as `Intentions`
declarativas do SDD §6.2 são a fatia 3); `rng` do esboço vira
`obs.rng` forward-only e segue banido no fonte de programas
(sorteio, para código evoluído, é serviço dos métodos herdados).

## O que falta (fatias seguintes da SPEC §4)

- **Fatia 2**: `Observation.to_snapshot()` serializável + decisão
  sobre expor séries públicas do mercado vivo e placar público de
  rivais — é o pré-requisito do braço IPPO (A2) sem quebrar o
  fog-of-war.
- **Fatia 3**: `Intentions` declarativas como retorno do `decide`
  (replay de decisões; re-provar goldens ou regravar com decisão
  explícita).
- **Fatia 4**: aposentar as fachadas legadas do `Engine` e os
  canais v1 da guarda (`comp._offers/_buys`, `engine.claimed_by`)
  quando nenhum programa vivo depender deles.
- Nota: a corrida forge-v1 (sub-issue #6) agora roda sobre a
  fronteira v2 — programas novos já nascem no contrato
  `decide(self, obs)`; programas antigos (assinatura legada) são
  rejeitados no loader com a explicação do contrato.
