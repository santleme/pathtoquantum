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

## 2026-10-27 — Fatia 2 entregue

**`Observation.to_snapshot()`** (em `src/mundo/observation.py`,
com `to_snapshot()` por view e o conversor estrito `_jsonify`):
fotografia da decisão em valores JSON puros — `{"me": …, "world":
…}`, round-trip `json.dumps`/`loads` idêntico provado em teste.
Captura a focal inteira (identidade, caixa, traits, stocks,
knowledge sondado, claims ordenados, ferramentas, sede,
instalações com `equip` quando o B2 está ligado, elo derivado) e o
mundo público inteiro (tick, flags, preços, depósitos/cidades/
países públicos, capex por país, parâmetros do B2). `act`/`rng`
ficam fora por desenho: são capacidades, não observação.

Leitura **pura**, com duas provas fortes:

- **Replay bit-idêntico**: uma política que fotografa TODA decisão
  (e serializa em JSON) antes de decidir reproduz o episódio sem
  fotografia com `state_dict()` idêntico — no clássico e no mundo
  vivo completo (B1+B3+B2), 36 ticks.
- **Sem escrita escondida**: o `equip` de uma instalação nunca
  lida entra no snapshot com os valores canônicos iniciais SEM
  materializar o dict preguiçoso no mundo (teste confere o dict
  cru antes/depois) — fotografar não escreve.

**Vazamento zero no snapshot** (teste dedicado): varredura
recursiva de chaves e valores com sentinelas — grade de depósito
não sondado (0,4242424242), fator de evento de Deus futuro
(7,777001), tick de evento político forçado (987654) e caixa de
rival (123.456.789) não aparecem em nível nenhum; chaves proibidas
(`grade`, `size_t`, `god_events`, `force_events`, `regime`,
`demand_ema`, `cover`, `remaining`, `companies`, …) idem.

**A decisão das séries públicas** (detalhe e fundamentação na
SPEC §4): entram **`world.anchors`** (a âncora p* — "série
pública" nas palavras do próprio motor) e **`world.price_history`**
(o "anel público de 24 meses" de preços, copiado por decisão;
teste: janela == anel do motor, limitada à janela dos parâmetros,
cópia que não envelhece com o mundo). Ficam fora o **regime**
("só Deus vê — as empresas inferem do preço", no frame do motor),
`cover`/EMA/ruído (internos; `cover` é agregado de estoques
privados) e qualquer **placar ao vivo de rivais** (não existe
canal de decisão que o exponha hoje; a crônica narrar marcos não
é uma série — virar série mudaria o jogo informacional).

**O mundo não mudou**: suíte **221/221** (214 + 7 novos, todos em
`tests/test_observation.py`); `test_golden.py` sem edição, os 4
hashes da Fase 1 intactos; S da semente e episódio bit-idêntico
da fatia 1 sem edição e verdes. A heurística não lê as séries
novas (só as expõe) — quem prova é a suíte inteira + o replay.

## 2026-10-27 — Fatia 3 entregue

**O contrato declarativo** (desenho completo na SPEC §4):
`decide(obs)` devolve a lista ordenada de intenções e o motor
valida e executa — a política não executa verbo nenhum durante a
decisão e não tem efeito colateral fora da lista declarada.

- `src/mundo/intentions.py` (novo): o vocabulário espelho 1:1 do
  `Actuator` — `Spend`, `Probe`, `RegisterClaim`, `BuildFacility`,
  `Narrate`, `NoteLink`, `RepairFacility`, `MaintainFacility`,
  `OverhaulFacility`, `Buy`, `Offer`, `SetTool` — dataclasses
  congeladas com serialização JSON (`intention_to_dict`/
  `from_dict`, tag `"type"`, round-trip provado tipo a tipo) e a
  companheira `Narration`. Os dois verbos que devolviam valor no
  meio da decisão viraram dado: `Probe` carrega as narrações
  candidatas (rica/pobre) e os limiares 0,78/0,35 — o executor
  narra a que o teor revelado selecionar, na mesma posição da
  sequência; `BuildFacility` carrega a narração anexa sem `fid` e
  o executor injeta o id criado ao narrar.
- **A sombra (`Plan`)** é o mecanismo da equivalência: caixa e
  tipos de instalação como ficarão após as intenções já
  declaradas. As fases da heurística testam limiares contra a
  sombra — reparo do B2 abatendo o caixa do teste da instalação
  seguinte, fábrica construída neste tick puxando compras e
  buffer, caixa "vivo" no ramo da montadora, `chain_stage()` da
  sombra virando o `NoteLink` pós-construção. Duas fidelidades
  nomeadas: o `spendable` da mineração continua congelado no
  caixa inicial (ele nasce antes da fase de equipamentos e não
  abate reparos — comportamento de hoje, preservado de propósito)
  e os sorteios seguem na decisão (planejar sorteia; executar
  intenção, não) — a ordem de consumo do RNG não muda um draw.
- `Engine._apply_intentions`: **validação total antes de qualquer
  execução** (atomicidade por decisão) e execução em ordem via
  `Actuator`. A validação rejeita com `IntentionError`: retorno
  que não seja lista de intenções (programa legado devolvendo
  `None` cai aqui, com a explicação do contrato), objeto forjado
  que não seja instância das classes (campo privado/desconhecido
  nem constrói numa dataclass congelada), gasto/quantidade
  negativa ou não-finita, commodity/depósito/ferramenta fora do
  vocabulário, reparo/manutenção/overhaul em instalação de
  OUTRA empresa, claim em célula de rival ou fora de depósito,
  construção com célula divergente do depósito, elo fora de 1–5.
- O selo: a observação que o `decide` recebe nasce com
  `sealed_act=True` — `obs.act` é um `SealedActuator` cujos verbos
  levantam `RuntimeError` com o contrato. O `Actuator` de verdade
  segue como ferramenta do executor e dos testes de verbos
  (`build_observation` sem selo, fatia 1 intacta). Na forja, a
  guarda soma `.act` aos atributos banidos e a allowlist ganha
  `mundo.intentions`; a semente da geração 0 foi reescrita
  declarativa espelhando a heurística, e o prompt do mutador
  (`forge/config.yaml`) descreve o contrato novo.
- Fases com os mesmos nomes, novo retorno: `maintain_equipment`,
  `build_downstream` (devolve `(construiu?, intenções)`),
  `plan_buys`, `plan_sells`, `use_tools` devolvem intenções e
  aceitam a sombra de quem orquestra; fachadas do `Engine` e
  `PolicyRouter` despacham e aplicam como antes.

**Prova de que o mundo não mudou.**

- Suíte: **232/232** (221 da fatia 2 + 11 novos em
  `tests/test_intentions.py`). Na árvore compartilhada com a
  frente do smoke foram 234 (os 2 testes de metadata dela).
- `tests/test_golden.py` **sem edição**: os 4 hashes da Fase 1
  intactos. `test_seed_generation0_bit_identical` e
  `test_evaluator_seed_matches_genome0_score` **sem edição** e
  verdes: S da semente == S do genoma 0; episódio da semente
  bit-idêntico.
- **Replay de decisões provado**: uma política que serializa cada
  lista de intenções em JSON e devolve a desserializada reproduz
  o episódio bit a bit (clássico e mundo vivo completo, 36
  ticks, `state_dict` inteiro).
- Doubles migrados sem tocar asserções (`NullPolicy` devolve
  `[]`, `RecordingPolicy` propaga o retorno). Os dois doubles
  "suicidas" (`test_hardening`, `test_v1`) agora declaram o
  `Spend` devastador em vez de executá-lo: o montante passa a ser
  calculado sobre o caixa do início da decisão (é o dado do
  plano — na execução ele sai depois dos gastos da própria
  heurística, como antes) e a falência/causa seguem as mesmas —
  as asserções não fixam o montante e seguem verdes sem edição.
- Nota operacional: esta fatia foi construída com o clone
  compartilhado trocado de branch por outra frente no meio da
  sessão (`noite/prep-smoke-forja`); o trabalho foi isolado num
  worktree próprio da `obs/guarda-v2` e a árvore principal foi
  devolvida como encontrada.

## 2026-10-27 — Fatia 4 entregue (migração da guarda v2 FECHADA)

**Fachadas do Engine aposentadas.** Grep no repo inteiro (código,
testes, notebooks, scripts, docs) provou **zero chamadores** de
cada uma — as fases vivem na política (`HeuristicPolicy`) e quem as
orquestra é o `decide`:

- `Engine._pick_deposit` — removida.
- `Engine._build_downstream` — removida.
- `Engine._plan_buys` — removida.
- `Engine._buffer` — removida.
- `Engine._plan_sells` — removida.

(O overlay histórico de `experiments/degrau1/` não era chamador:
ele remenda métodos da *política*, que seguem intactos.)

**Exceções fundamentadas** — fachadas com chamador vivo não
previsto na SPEC, mantidas e registradas conforme a regra da
fatia:

- `Engine._decide` — deixou de ser fachada: é a entrada canônica
  da decisão (zera `_offers`/`_buys`, constrói a Observation
  selada, valida e aplica as intenções), chamada pelo passo do
  motor (`step`) e por testes de equipamentos/intenções.
- `Engine._reserve` — chamador vivo único: `tests/test_equip_v2.py`
  monta o caixa do cenário a partir da reserva da política por ele.
- `Engine._use_tools` — chamadores vivos: `tests/test_engine.py` e
  `tests/test_v1.py` exercitam a fase de ferramentas isolada por
  ele. Removê-lo exigiria reescrever a mecânica desses testes sem
  ganho de fronteira — o canal não é alcançável por programas.

**Canais v1 da guarda aposentados** (`src/mundo/program.py`): os
quatro donos legais de subscrito da era v0/v1 — `comp._offers`,
`comp._buys`, `comp.knowledge` e `engine.claimed_by` — saíram de
`LEGAL_SUBSCRIPT_OWNERS` (a constante virou
`RETIRED_SUBSCRIPT_OWNERS`) e viraram **rejeição nomeada**:
"canal v1 aposentado (guarda v2, fatia 4): a decisão é
declarativa; devolva intenções de mundo.intentions em
decide(self, obs) — Buy/Offer para ordens, Probe para sondagem e
conhecimento, RegisterClaim para claims". Vale para atribuição,
deleção e apelido contaminado de `comp`; a mensagem genérica dos
demais subscritos do mundo foi atualizada para o mesmo contrato.
Nenhum programa vivo dependia dos canais: a semente da geração 0
é declarativa desde a fatia 3 e grep em `forge/` não achou fonte
nenhuma com os canais. Nota de escopo: a tolerância histórica de
atributos `comp.tools.*` na guarda permanece — fora do escopo
nomeado desta fatia e inalcançável na prática, pois o programa só
recebe a Observation.

**Prova de que o mundo não mudou.**

- Suíte: **240/240** (232 da base da branch + 8 novos: seis casos
  de rejeição dos canais aposentados — os quatro canais, apelido
  e deleção —, a rejeição na carga via `load_program_policy` e a
  prova estrutural das fachadas removidas/mantidas).
- `tests/test_golden.py` **sem edição**: os 4 hashes da Fase 1
  intactos; `test_seed_generation0_bit_identical` e
  `test_evaluator_seed_matches_genome0_score` **sem edição** e
  verdes (S da semente == S do genoma 0; episódio bit-idêntico).
- `test_native_parity.py` verde: o motor Python segue
  bit-idêntico ao núcleo nativo C++.
- Único teste reescrito: `test_guard_allows_legal_channels`
  (`tests/test_forge.py`) — os quatro canais aposentados saíram
  da lista de legais, que é exatamente a aceitação desta fatia;
  as asserções dos canais restantes (`self.*`, `comp.tools.*`,
  dict próprio) não mudaram.
- Nota operacional: a fatia foi construída em worktree próprio
  sobre a `obs/guarda-v2`; a árvore principal compartilhada ficou
  exatamente como encontrada (branch `noite/prep-smoke-forja`).

## Estado final

A migração da guarda v2 está **fechada** (fatias 1–4 entregues):
a política — heurística, genoma ou programa — só enxerga a
Observation tipada, só age por intenções declarativas validadas
pelo motor, e a superfície v1 (fachadas do `Engine` e canais de
escrita da guarda) foi aposentada. Nota viva: a corrida forge-v1
(sub-issue #6) roda sobre esta fronteira — programas novos já
nascem no contrato `decide(self, obs)`; programas antigos
(assinatura legada ou canais v1) são rejeitados na carga com a
explicação do contrato.

## Revisão independente — ciclo do operador, 27/10/2026 (~02h, -03)

Revisão da migração fechada (fatias 1–4) por agente que não escreveu
o código, nos dois eixos do manifesto (padrões do repo × fidelidade
à SPEC §4), em worktree próprio sobre `obs/guarda-v2` @ 1931b7b.
Árvore principal intacta (branch `noite/prep-smoke-forja`).

- **Suíte reproduzida do zero: 240/240** (109,8 s, `PYTHONPATH=src`,
  venv do repo) — mesmo número declarado no fechamento da fatia 4.
- **Goldens intactos:** `tests/test_golden.py` idêntico à `main`
  local (`git diff` vazio); `test_native_parity.py` verde.
- **Contrato declarativo:** `decide(self, obs)` em
  `policies.py`, `engine.py` e `forge/seed_policy.py`; a semente
  da forja tem **zero acesso `engine.*`** no fonte.
- **Canais v1 aposentados provados:** `test_guard_rejects_cheats`
  + `test_guard_rejects_retired_v1_channels` verdes — os 6
  variantes (comp._offers/_buys/knowledge, engine.claimed_by,
  apelido contaminado, deleção) são rejeitados pela guarda
  (`RETIRED_SUBSCRIPT_OWNERS` em `program.py`); o subconjunto
  forge/observation/golden/intentions soma 76 testes verdes.
- **Ressalva de escopo (não é falha):** `claimed_by`/`_offers`/
  `_buys`/`god_events` ainda aparecem dentro do `Engine` e do
  executor (`observation.py`) — são estado interno do motor e
  da execução de intenções validadas, não canais da política.
  O que a política-programa pode tocar é o que a guarda veta,
  e isso está vetado.
- **Veredito da revisão: APROVADA para revisão do fundador.**
  Não houve merge (regra do modo autônomo). PR draft limpo
  contra a `main` remota ainda não é possível: a `main` local
  está 62 commits à frente e 8 atrás da remota (históricos
  divergentes — é a issue H do lote pendente, decisão do
  fundador). Um PR aberto agora carregaria o atraso inteiro
  junto com a guarda v2. Próximo passo da fila: decisão H;
  depois, PR draft só da guarda v2; depois, a corrida
  forge-v1 (#6), que ainda depende da chave LLM do fundador
  (decisão do mutador, `docs/PESQUISA-MUTADOR-FORGE-V1.md`).
