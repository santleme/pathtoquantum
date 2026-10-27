# Issues pendentes de abertura — noite de 27/10/2026

> O fundador autorizou lançar e resolver muitas issues, mas dormindo ele
> não aprova os cartões de escrita do conector GitHub. As escritas via
> conector foram tentadas e ficaram pendentes de aprovação; por isso
> cada issue abaixo está com **título, corpo completo e labels
> sugeridas**, pronta para colar. Nada aqui foi aberto ainda (conferido
> em 27/10/2026: abertas no repo só #1, #5 e #6). Quem abrir: colar,
> conferir duplicidade de novo e riscar da lista.
>
> Estado da noite (contexto): Degrau 1 com Fases 1–5 implementadas;
> veredito da Fase 5 lançado no Kaggle em 27/10 ~00:18 (-03, kernel
> `ptq-veredito-fase5-nucleo-nativo`, bundle src9) — ao fim desta
> sessão os endpoints de leitura desse kernel respondiam 403 de forma
> persistente (kernel consta na listagem; ver item A). O smoke da
> forja (#5) foi lançado pela frente principal como
> `ptq-smoke-forja-v1` (bundle src11, com `forge/smoke.py` próprio) e
> concluiu **SMOKE FORJA: OK** — 30/30 iterações, 30 aceitos, 0
> rejeitados pela guarda, semente S1=0,4953 → melhor filho
> prog:faa2b66c01b0 S1=0,5617 / S2=0,5261. A issue #5 pode ser fechada
> com esse veredito quando o fundador aprovar a escrita.

---

## A. [bug] Kernel do veredito da Fase 5 ilegível pela API (403 persistente)

**Labels sugeridas:** `infra`, `kaggle`, `degrau-1`

### Corpo

O kernel `pascalcoimbra/ptq-veredito-fase-5-nucleo-nativo` (lançado
27/10/2026 ~03:18Z, bundle src9 com o fix de build em diretório
gravável) consta na listagem de kernels do usuário, mas os endpoints
de monitoramento que funcionam para todos os outros kernels do
projeto retornam **403 Forbidden** de forma persistente:

- `GET /api/v1/kernels/status?userName=pascalcoimbra&kernelSlug=ptq-veredito-fase5-nucleo-nativo` → 403
- `GET /api/v1/kernels/output?userName=pascalcoimbra&kernelSlug=ptq-veredito-fase5-nucleo-nativo` → 403

Controle no mesmo instante, mesma credencial: nascimento, B1 e B3
respondem 200 com status `complete` e outputs. Sem leitura, não há
como coletar o veredito da Fase 5 (paridade em escala + benchmark
Kaggle) nem registrar no DEGRAU1-LOG.

**Aceitação:** conseguir ler status/output do kernel (pela API ou
pela UI) e registrar o veredito da Fase 5 no `docs/DEGRAU1-LOG.md`
(APROVADO se paridade 100% e speedup ≥ 15× no Kaggle, conforme o
portão da Fase 5 no DEGRAU1-DESIGN), ou diagnosticar a causa do 403
(versão presa? kernel em estado inválido?) e, se preciso, relançar
com slug novo (`ptq-veredito-fase5-v2`) reaproveitando o bundle src9.

---

## B. [forja] Guarda v2 — camada de Observation tipada (fechar a leitura cega de `deposit.grade`)

**Labels sugeridas:** `degrau-2`, `forja`, `seguranca`

### Corpo

A guarda AST v1 (mergeada, PR #8) endureceu escrita, apelidos,
subscritos e imports — mas tem um limite declarado desde a revisão:
**leitura cega de `deposit.grade`/`size` fora de `comp.knowledge`**
passa, porque a AST não enxerga tipos. No espaço-código, uma política
evoluída pode ler o teor/tamanho verdadeiros de qualquer depósito e
"descobrir" prospecção perfeita — exploit, não estratégia; quebraria
o fog-of-war que sustenta o produto.

**Correção estrutural (desenho):** camada de Observation tipada entre
o motor e a política-programa: `decide(engine, comp)` passa a receber
uma visão (`Observation`) que só expõe o que a empresa conhece —
depósitos via `comp.knowledge`, preços públicos, estado próprio —
sem referência ao `engine` cru. A heurística v0 e a semente da forja
migram para a mesma interface sem mudar comportamento (bit-idêntico
nos goldens).

Nota: já existe `tests/test_observation.py` no repo — conferir o que
ele cobre antes de desenhar; esta issue é o fechamento do canal, não
necessariamente começar do zero.

**Aceitação:** (1) programa-teste que lê `deposit.grade` fora do
knowledge é rejeitado/sem acesso pela nova camada (teste vermelho →
verde); (2) semente da forja segue bit-idêntica (S genoma 0 ==
0,428125 no stage1 de aceitação); (3) suíte verde. Pré-requisito de
qualidade para a corrida oficial (#6) valer como evidência.

---

## C. [v1] Mundo maior — primeiro recorte novo (América do Norte) com dados reais

**Labels sugeridas:** `v1`, `mundo`, `dados-reais`

### Corpo

PRD §10/v1: "Mais Terra: novos recortes (América do Norte, África,
Ásia) e dezenas de depósitos/cidades; mais commodities e elos
intermediários da Era 1." O mundo atual é a América do Sul real
(10 depósitos, 8 cidades). Mundo pequeno demais é risco nomeado no
PRD ("corridas se repetem") — conteúdo é dado real, não level design.

**Fatia:** adicionar o recorte da América do Norte ao
`data/world_data.json` com fonte por item (mesmo padrão de proveniência
do recorte atual: USGS e fontes oficiais por depósito/cidade),
integrado ao mundo builtin sem quebrar os goldens do mundo clássico
(o recorte novo entra como mundo nomeado novo, não como mutação do
atual).

Nota: já existe `tests/test_v1.py` no repo — conferir o que já está
desenhado/coberto antes de implementar.

**Aceitação:** corrida de nascimento do mundo novo no Kaggle
(protocolo dos vereditos: kernel novo, veredito impresso) com ≥ 8
empresas vivas, ledger fechando e crônica com eventos do recorte
novo; suíte verde com goldens antigos intactos.

---

## D. [v1] Viewer — replay completo: scrub fino, câmera nos marcos e comparador de corridas

**Labels sugeridas:** `v1`, `viewer`, `produto`

### Corpo

PRD §10/v1: "Replay completo: viewer com scrub fino, câmera nos
marcos da crônica, comparador de corridas (mesma seed, Deuses
diferentes)." Hoje o `viewer/` é uma página estática alimentada por
`chronicle.json`/`frames.json`/`scoreboard.json` de uma única corrida
fixa — o fundador não consegue carregar a corrida que acabou de rodar
nem comparar duas.

**Fatia:** (1) viewer aceita carregar os três arquivos de qualquer
corrida (arrastar/selecionar ou parâmetro de URL para `results/<corrida>/`);
(2) scrub fino por tick com play/pause e velocidade; (3) clicar num
marco da crônica posiciona o replay naquele tick ("câmera nos
marcos"). O comparador de corridas fica como segunda fatia desta
mesma issue se couber; senão vira issue filha.

**Aceitação:** abrir o viewer com os outputs da corrida de nascimento
e de um veredito recente, navegar por scrub até um marco da crônica
e ver o placar daquele tick — sem editar arquivo nenhum à mão.

---

## E. [v1] Crônica rica — rivalidades detectadas e retrospectiva automática da corrida

**Labels sugeridas:** `v1`, `cronica`, `produto`

### Corpo

PRD §10/v1: "Crônica rica: rivalidades detectadas (quem comprou de
quem, guerras de preço), retrospectiva automática da corrida ('a
década em que...')." A régua do projeto é diversão primeiro: "corrida
sem história é defeito do mundo" (SDD). Hoje a Crônica registra
eventos, mas não deriva narrativa de segundo nível.

**Fatia:** pós-processador determinístico sobre os eventos de uma
corrida que emite (a) rivalidades: pares de empresas com disputas
repetidas pelo mesmo depósito/elo e guerras de preço detectadas na
série de preços; (b) retrospectiva textual por era/década com os
marcos (primeira falência, primeiro supercomputador, viradas de
liderança). Tudo derivado dos dados que o motor já emite — sem tocar
o tick nem os goldens.

**Aceitação:** rodar sobre a crônica da corrida de nascimento e de
um veredito: retrospectiva gerada com pelo menos as viradas de
liderança e o primeiro supercomputador corretos (conferidos contra o
placar), e testes unitários dos detectores com crônicas sintéticas.

---

## F. [v1] Ferramentas simuladas novas — estúdio de vídeo e marketplace (desenho)

**Labels sugeridas:** `v1`, `ferramentas`, `estudo`

### Corpo

PRD §10/v1: "Mais ferramentas: estúdio de vídeo simulado e
marketplace simulado entram como módulos; empresas anunciam em
vídeo e vendem em prateleira disputada." Hoje `src/mundo/tools_sim.py`
traz os simulados de Instagram e WhatsApp, que as empresas usam de
verdade pagando custos realistas.

**Fatia (desenho primeiro, skill pesquisa_antes_de_decidir):**
desenhar os dois módulos no mesmo contrato dos existentes — custo
por uso com dado real ancorado (CPM/CPC de vídeo, taxa de
marketplace), mecânica que muda decisão de verdade (alcance ×
conversão; prateleira disputada por preço/avaliação) e o evento de
crônica correspondente. Implementação entra como issue filha após o
desenho aprovado pelo fundador.

**Aceitação:** documento de desenho em `docs/` com mecânica, custos
ancorados em fonte, impacto esperado na política heurística e o
teste que provaria integração sem quebrar goldens (módulo desligado
= mundo bit-idêntico).

---

## G. [estudo] Núcleo nativo × políticas plugáveis — desenhar a ponte para as temporadas (v2)

**Labels sugeridas:** `v2`, `motor`, `estudo`

### Corpo

Pendência declarada no DEGRAU1-LOG (Fase 5): o núcleo nativo cobre
só a HeuristicPolicy oficial e recusa política customizada com
ValueError; torneio e forja rodam no motor Python de referência. Nas
temporadas do v2 (PRD §10), políticas aprendidas disputam temporadas
inteiras — se a escala pedir o nativo, falta a ponte.

**Fatia (estudo/medição):** medir o custo real da fronteira hoje
(quantas avaliações de política por tick a n=100/1.000 e o que uma
chamada host por decisão custaria ao speedup de 12–19×) e desenhar
as opções: (a) genoma/programa compilado para uma IR que o nativo
executa; (b) política em lote por tick via callback vetorizado;
(c) manter políticas no Python e o nativo só para o mundo
heurístico, com critério de quando cada um basta. Recomendação
fundamentada volta para o fundador decidir (não implementar neste
estudo).

**Aceitação:** documento em `docs/` com a medição e a recomendação;
nenhum código de motor muda neste estudo.

---

## H. [processo] Git canônico: aposentar o sync por snapshot e reconciliar os históricos

**Labels sugeridas:** `infra`, `processo`, `decisao-fundador`

### Corpo

O repo vive hoje com dois históricos: o git local (trabalho real,
com commits por fatia) e a main do GitHub, alimentada por syncs de
snapshot via GitHub App (commits "Sync: ..."). Em 27/10/2026 a
divergência medida era de **59 commits locais × 8 remotos** sem
ancestro comum recente — cada sync novo aumenta a chance de um
merge add/add como o do PR #7.

Desde 27/10 o push por **git normal funciona** nesta VM (chave SSH
registrada na conta, via ssh.github.com:443 — receita em TOOLS.md) e
foi assim que o FANUC subiu com histórico completo e binários.

**Decisão pedida ao fundador:** adotar o git normal como caminho
canônico também no Path to Quantum. Com o ok: reconciliar os
históricos uma única vez (a main remota passa a ser o histórico
local, conferindo arquivo a arquivo que nenhum conteúdo do snapshot
se perde), aposentar o manifesto `*.muse-github-snapshot-sync.json`
deste repo e registrar a convenção no AGENTS.md.

**Aceitação:** main do GitHub == HEAD local (mesmo hash), clone
limpo do zero reproduz a suíte verde, e o próximo PR nasce de branch
git comum, sem sync por snapshot.

---

## I. [épica] v3 — Outros deuses e Era 2 (horizonte, só registro)

**Labels sugeridas:** `v3`, `epica`, `horizonte`

### Corpo

PRD §10/v3: terceiros criam mundos (editor de mundo: mapa,
depósitos, eras) e soltam empresas próprias; ligas entre mundos e
políticas; a Era 2 (Path to Quantum) abre com os elos finais da
cadeia até o computador quântico. Critério de sucesso do PRD: a
primeira história emergente que o fundador assista sem ter criado o
mundo nem as empresas.

Esta épica é **registro de horizonte**: não fatiar nem implementar
nada dela antes de v1 e v2 cumprirem seus critérios. Serve para a
fila enxergar o destino ao priorizar as fatias de v1/v2 (ex.: o
editor de mundo do v3 pede que mundos sejam dados declarativos
desde já — o que a issue C já respeita).
