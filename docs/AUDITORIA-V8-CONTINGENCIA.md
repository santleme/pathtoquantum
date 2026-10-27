# Auditoria da Version 8 da forge-v1 + plano de contingência

**Data:** 27/10/2026 (escrita enquanto a V8 roda, ~4h15 após o lançamento
das 14:04:29 -03). **Base:** código da branch `forja/forge-v1-modelos-kaggle`
@ `a564fc6` — exatamente o bundle `pascalcoimbra/mundo-autonomo-src14` que a
V8 está executando. **Escopo:** auditoria e contingência; nenhum código de
produção foi alterado por este documento.

**Para que serve:** quando o log final da V8 sair, classificar o desfecho em
minutos e já saber a decisão. A §1 mapeia os cenários e as linhas exatas que
os discriminam; a §2 traz a decisão mastigada por cenário; a §3 lista o que o
log final **não** vai conseguir dizer (pontos cegos) e a menor instrumentação
que fecharia cada buraco; a §4 confere se a V8 ainda testa a hipótese
pré-registrada da issue #6.

---

## 0. Anatomia do "log final" — de onde sai cada linha

O desfecho da V8 chega em dois canais, produzidos por código distinto:

1. **stdout do notebook** (`notebooks/forge-v1.ipynb`):
   - célula 1: `bundle em <path>` — o caminho contém o slug do dataset
     (`.../mundo-autonomo-src14/...`), prova de qual bundle rodou;
   - célula 2 (sonda): `NVIDIA_API_KEY: presente|ausente`, idem Gemini/Groq;
   - célula 3: chama `run_forge(...)` e ao fim imprime
     `celula da corrida concluida em <N>s` (tempo total de parede); em
     exceção, imprime o traceback inteiro;
   - célula 4: o bloco de veredito delimitado por `====...`, com a linha
     `FORGE-V1: ...`, campeão/semente com S1/S2, ΔS com IC95, contagens,
     `mutador: {stats}` e a curva `best_S1` amostrada a cada 25.
2. **Arquivos de saída** (copiados pela célula 4 para a raiz de
   `/kaggle/working`): `forge-v1.json` (o summary completo),
   `run_log.jsonl`, `archive.json`, `final_evaluation.json`,
   `champion.py`, `top5_diffs.md`. Dentro de `forge-v1/` ficam também
   `run_summary.json`, `programs/` e os demais artefatos.

Diferenças de resolução entre os canais que importam na hora de diagnosticar:

- A linha de iteração no stdout é
  `[{i:03d}/300] {status} prog:{hash}: {reason[:140]}`
  (`forge/run.py`, laço principal) — a `reason` é **truncada em 140
  caracteres** no stdout e em **400** no registro do `run_log.jsonl`.
- A linha de aceita no stdout é
  `[{i:03d}/300] accepted prog:{hash} S1=... S2=... best_S1=... ({desc[:80]})`,
  onde `desc` é `llm[<provedor>/<modelo>] diff|rewrite: <SUMMARY>...`
  (montada em `LLMMutator.mutate`, `forge/llm_mutator.py`). **A rota
  vencedora de cada aceita está no log**; no `run_log.jsonl` o campo
  `mutation` guarda a `desc` sem truncar.
- Só o `run_log.jsonl` tem o campo `seconds` por iteração (tempo de parede
  da iteração inteira: mutação + avaliação). O stdout **não** tem timestamps
  nem durações por iteração.
- As estatísticas do mutador são `{"calls": {…}, "fallbacks": N,
  "failures": N}` (`forge/llm_mutator.py:385`), com `calls` indexado por
  `"<provedor>/<modelo>"` contando **invocações de rota** (uma por tentativa
  de mutação por rota), **não** tentativas HTTP — os retries internos do
  transporte são invisíveis (ver §3).

A cadeia de rotas de cada mutação (`LLMMutator._route_chain`,
`forge/llm_mutator.py:388`): NVIDIA `qwen/qwen3-coder-480b-a35b-instruct` →
Gemini (volume `gemini-3-flash-preview` ou salto `gemini-3.5-flash`, sorteado
com peso 0,2 para o salto; a outra entra em seguida) → Groq
`openai/gpt-oss-120b` → Groq `qwen/qwen3.8-27b`. Só entram na cadeia os
provedores com chave. O driver chama `mutate` **uma única vez por iteração**
(`attempts = 1` para o mutador LLM, `forge/run.py:375`).

Quando todas as rotas de uma mutação falham, `mutate` levanta
`MutationError("todas as rotas falharam: " + " | ".join(errors))`
(`forge/llm_mutator.py:455`), onde cada erro é
`"<provedor>/<modelo> HTTP <status>: <corpo[:200]>"` (de `LLMClient.chat`,
`forge/llm_mutator.py:260`) ou um erro de formato ("sem diff aplicável nem
reescrita válida", "mutação vazia", "resposta vazia", "resposta ilegível").
O driver classifica a iteração como `rejected_llm` quando a exceção é
`MutationError` (`forge/run.py:436`) e grava essa mensagem como `reason`.

O transporte (`_default_transport`, `forge/llm_mutator.py:205`): até 3
tentativas por chamada para status em `{429, 500, 502, 503, 504}`
(`RETRYABLE_STATUS`, :161) e erros de rede, com backoff de 5s→20s
(`RETRY_BACKOFFS`, :162), timeout de 180s por tentativa (`TIMEOUT_S`, :73) e
pacing mínimo de 1,5s entre tentativas (`DEFAULT_MIN_INTERVAL_S`, :167,
ajustável por `FORGE_LLM_MIN_INTERVAL_S`). Esgotada a rede, devolve
`(503, "network error after retries: ...")` — indistinguível de um HTTP 503
real nas estatísticas, mas o texto aparece no corpo do erro.

---

## 1. Mapa de cenários do desfecho

### (a) Corrida saudável, com aceitas via NVIDIA

**Assinatura no log:**

- Sonda: `NVIDIA_API_KEY: presente`.
- Linhas de aceita com `llm[nvidia/qwen/qwen3-coder-480b-a35b-instruct]`
  na descrição (stdout e campo `mutation` do `run_log.jsonl`).
- `mutator_stats`: `calls` com a chave
  `nvidia/qwen/qwen3-coder-480b-a35b-instruct` alta (≈ nº de iterações
  menos as que a NVIDIA resolveu de primeira menos falhas), `fallbacks`
  baixo, `failures` baixo ou zero.
- `counts.accepted` substancial; campeão ≠ semente (hash do campeão ≠
  `fcf3162c8751`, que é a semente `prog:fcf3162c8751` das V6/V7);
  `iterations_completed` = 300.
- Bloco de veredito completo com ΔS/IC95 reais (qualquer dos três
  rótulos — PROVA, INCONCLUSIVO ou REPROVADO/AJUSTAR — vale como desfecho
  deste cenário: o cenário é sobre a corrida ter funcionado, não sobre a
  barra ter sido atingida).

### (b) NVIDIA lenta, mas viva

**Assinatura:** igual à de (a) nas rotas e nas contagens, mas com tempos
altos: `celula da corrida concluida em <N>s` com N grande (ordem de
5–10h) e, no `run_log.jsonl`, campo `seconds` por iteração alto e
relativamente uniforme (dezenas de segundos a poucos minutos — dominado
pela latência de geração do modelo de 480B na camada gratuita e, nos
candidatos que passam da triagem, pelo stage2 de 64 episódios).
Discrimina de (e): há aceitas via NVIDIA e as `reason` de `rejected_llm`
(nos poucos que houver) **não** são dominadas por erros HTTP. Discrimina
de (a) apenas pelo relógio — é o mesmo cenário, na cauda lenta da
distribuição. Se a lentidão empurrar a corrida para o teto de sessão, o
desfecho degenera para (f) com o loop completo ou quase (ver lá).

### (c) ID de modelo da NVIDIA errado (404 de modelo)

**Assinatura — e ela é traiçoeira:**

- Se Gemini/Groq segurarem as mutações, as iterações são **aceitas
  normalmente**, com descrições `llm[gemini/...]` ou `llm[groq/...]` — a
  palavra "404" pode **não aparecer nenhuma vez no stdout**, porque o
  texto de erro de uma rota só é gravado quando **todas** as rotas da
  mutação falham (a lista `errors` de `mutate` é descartada no sucesso).
- A prova fica na aritmética das estatísticas: `calls` da rota NVIDIA ≈
  300 (ela é tentada em toda mutação e falha sempre), `fallbacks` ≥ ~300
  (toda iteração precisou cair ao menos um degrau), `failures` ≈ 0, e
  **nenhuma** aceita com descrição `llm[nvidia/...]`.
- Se houver algum `rejected_llm`, a `reason` dele mostra o erro na
  íntegra: `nvidia/qwen/qwen3-coder-480b-a35b-instruct HTTP 404: <corpo>`
  — o corpo (200 chars) traz a mensagem da NVIDIA, que distingue "modelo
  não encontrado" de outras causas de 404.
- Detalhe de custo: 404 **não** está em `RETRYABLE_STATUS`, então a rota
  morta custa ~1 tentativa rápida por mutação — este cenário **não**
  explica sozinho uma corrida de muitas horas; se a V8 demorou 6h+ e o
  desfecho for (c), a lentidão veio das rotas reservas ou da avaliação.

### (d) NVIDIA morta (qualquer causa) e as reservas segurando

**Assinatura:** idêntica à de (c) nas estatísticas e nas descrições das
aceitas (só Gemini/Groq). A diferença para (c) é a causa da morte da rota
principal — e ela pode ser **indeterminável a partir do log**: se não
houver nenhum `rejected_llm` na corrida inteira, nenhum texto de erro da
NVIDIA foi gravado em lugar algum (ver §3, ponto cego 3). Se a morte for
por timeout/503 com retries, há um sinal indireto: `seconds` por iteração
alto no `run_log.jsonl` (cada mutação queima até 3 tentativas × 180s +
25s de backoff na rota morta antes de cair para as reservas), mesmo com
aceitas saudáveis via Gemini/Groq. Se a morte for por 401/404 (falha
rápida sem retry), nem esse sinal existe.

### (e) Todas as rotas mortas, com backoff — corrida longa e inválida

**Assinatura:**

- `counts`: `rejected_llm` ≈ 300, `accepted` = 0 (ou ~1), `failures` =
  300 nas estatísticas; `calls` ≈ 300 **por rota** (≈1.500 no total das
  cinco), `fallbacks` ≈ 1.200.
- Campeão = a semente (`prog:fcf3162c8751`), com o mesmo S1/S2 das
  V6/V7; veredito `FORGE-V1: REPROVADO/AJUSTAR` com ΔS vs torneio ≈
  −0,0750 e **ΔS vs semente = +0,0000** — a assinatura numérica de
  "nenhuma mutação foi avaliada".
- As `reason` dos `rejected_llm` mostram o cadáver de cada rota:
  `todas as rotas falharam: nvidia/... HTTP <s1>: ... | gemini/... HTTP
  <s2>: ... | groq/... HTTP <s3>: ...`. No stdout só os primeiros 140
  caracteres aparecem (em geral NVIDIA + início do Gemini); o
  `run_log.jsonl` guarda 400 — suficiente para os status das cinco
  rotas na maioria dos casos. Os status discriminam a causa: 429 em
  tudo = cota/ritmo de novo; 404 na NVIDIA + 429 nas demais = mistura
  de (c) com cota; 401 = chave inválida/revogada; corpo
  "network error after retries" = rede/DNS, não HTTP.

**O ponto estrutural deste cenário (o achado central desta auditoria):**
com backoff, rota morta **não falha rápido**. Cada chamada morta por
status repetível custa ~25s de backoff + 3 tentativas (pacing + latência);
com falhas rápidas de 429, são ~30–35s por rota, ~2,5–3 min por iteração
só de mutação — **300 iterações ≈ 12,5–15h, acima do teto de sessão de
12h do Kaggle**. Ou seja: se todas as rotas estiverem mortas, a V8
provavelmente **não imprime veredito nenhum** — ela degenera para o
cenário (f), morta pelo relógio, ao contrário da V7 (sem backoff), que
falhou em 323,9s e imprimiu o veredito. **Corolário incômodo: as 4h+
de execução já observadas são compatíveis tanto com (a)/(b) quanto com
(e)→(f); o tempo decorrido, sozinho, não discrimina cenário.** Só o log
final discrimina — se ele existir.

### (f) Estouro do limite de sessão de 12h do Kaggle

**Assinatura:** depende de o Kaggle publicar saída parcial da versão
morta, o que é incerto por desenho da plataforma. Os discriminadores,
em ordem de preferência:

- Status da versão na página do kernel: erro/timeout sem a linha de
  veredito — e `kernels/output` continua mostrando a **Version 7**
  (nenhum artefato src14), caso nada da V8 seja publicado.
- Se houver stdout parcial: ele **termina no meio do loop** — última
  linha `[NNN/300] ...` com NNN < 300, **sem** o bloco `====`, sem
  `celula da corrida concluida em`, sem nenhuma linha `FORGE-V1:`.
  Isso discrimina (f) de quebra por exceção: na quebra, a célula 3
  imprime o traceback e a célula 4 imprime `FORGE-V1: FALHOU` + causa.
- Se os arquivos forem publicados: `run_summary.json` no formato de
  **checkpoint** — `{"ok": false, "checkpoint": true,
  "iterations_completed": N, "best_by_S1": ..., "best_by_S2": ...}`
  (gravado a cada 25 iterações por `checkpoint()`, `forge/run.py:328`)
  — e `run_log.jsonl` com exatamente N registros, **sem** os campos do
  summary final (`counts`, `mutator_stats`, `verdict`) no
  `forge-v1.json`. 
- Subcaso (f2): morte **durante a avaliação cega** — o loop completou
  (300 registros, `champion.py` gravado) mas não há veredito; a última
  linha do stdout é `avaliação cega: abrindo as seeds de teste
  (final=True, protocolo da épica)...`. A avaliação cega roda 3 braços
  × 64 blocos (+ o braço-genoma via `evaluate_test`) com 4 processos —
  ela mesma consome um tempo nada trivial no fim da corrida, e uma
  corrida saudável mas lenta pode morrer exatamente aí.

---

## 2. Decisão recomendada por cenário

**(a) Saudável.** Aceitar o veredito como a resposta do protocolo,
seja ele qual for (PROVA / INCONCLUSIVO / REPROVADO/AJUSTAR são os três
desfechos legítimos). Registrar no `docs/FORGE-V1-LOG.md` com os números
da célula 4, arquivar os artefatos e seguir a fila da épica #1. Não
relançar.

**(b) Lenta, mas viva.** Aceitar o veredito, idem (a). Registrar a
distribuição de `seconds` do `run_log.jsonl` (mediana e cauda) como o
custo de parede medido do desenho atual — é o insumo para decidir, na
próxima corrida, se vale mexer em pacing/timeout. Não relançar.

**(c) ID de modelo errado (404), reservas seguraram.** Aceitar o
veredito — a hipótese testada não nomeia o modelo do mutador (ver §4),
e as mutações aceitas vieram de rotas legítimas do ensemble. **Mas**
registrar explicitamente que a rota NVIDIA **nunca foi exercitada**:
qualquer conclusão do tipo "a NVIDIA funciona/não funciona" seria
falsa. Correção antes de qualquer corrida futura: confirmar o ID exato
no catálogo vivo do NIM (`GET /v1/models` com a chave) e corrigir a
constante `NVIDIA_VOLUME_MODEL`. Não relançar a forge-v1 só por isto.

**(d) NVIDIA morta, reservas seguraram.** Aceitar o veredito, idem
(c). A causa da morte provavelmente é indeterminável pelo log (ponto
cego 3) — não gastar horas nela: o que destrava a próxima corrida é a
instrumentação da §3 (contador de erros por rota + sonda de uma chamada
por rota no início, impressa no log), não arqueologia nesta.

**(e) Todas mortas.** Tratar como **teste inválido** da hipótese (a
precedência é a das V6/V7: o rótulo impresso é o do protocolo, mas a
leitura correta é "o mutador nunca produziu um candidato avaliável").
Não interpretar como evidência contra mutação por LLM. Antes de
relançar: sondar **cada rota** com uma chamada única num kernel de
smoke e só relançar com ≥1 rota respondendo HTTP 200 de verdade; se o
bloqueio for 429 de cota nas três, a decisão é esperar a janela de
cota ou trocar de provedor — decisão do fundador, não relançamento
automático.

**(f) Morta pelo relógio (12h).** Nenhum veredito pode ser reivindicado
a partir de corrida parcial — o protocolo exige as 300 iterações + a
final cega, e as seeds de teste **não foram abertas** (a abertura é
`final=True`, uma única vez, no fim). Se `iterations_completed` do
checkpoint for alto, ele serve só como diagnóstico de ritmo. Ajustes
concretos para o relançamento, em ordem de impacto:
1. **Separar loop e final cega em duas versões do kernel** (a primeira
   grava campeão + arquivo; a segunda só roda a avaliação cega) — o
   desfecho do loop passa a ser publicado mesmo se a cega morrer.
2. **Teto de tempo por iteração no driver** (orçamento de mutação:
   esgotou, registra `rejected_llm` e segue) — impede que rotas mortas
   com backoff transformem a corrida num (e)→(f) silencioso.
3. Reduzir `RETRY_BACKOFFS` na configuração da corrida (ex.: 2s/8s) —
   troca resiliência a 429 transitório por teto de parede previsível.
Decisão de relançar e de quais ajustes adotar: do fundador, com este
mapa na mesa.

---

## 3. Pontos cegos do desenho atual — e a menor instrumentação que os fecha

1. **Retries são invisíveis.** `stats["calls"]` conta invocações de
   rota; as até-3 tentativas internas de `_default_transport` (e quantos
   429/5xx elas absorveram) não são contadas nem logadas. Não dá para
   reconstruir quanto tempo o backoff comeu nem quão perto do limite de
   cota cada rota operou. *Menor correção:* contador no transporte
   (`attempts`, `retries_by_status`) exposto nas stats do mutador.
2. **Sem latência por rota.** O único tempo gravado é `seconds` por
   iteração inteira (mutação + guarda + avaliação). Não dá para separar
   "LLM lento" de "avaliação lenta" — os cenários (b) e (d-timeout) só
   se distinguem por esse número decomposto. *Menor correção:* cronometrar
   cada `_call` e acumular soma/máx por rota nas stats.
3. **O erro de uma rota é descartado quando outra salva a mutação.** A
   lista `errors` de `mutate` só sobrevive na exceção total. Se as
   reservas segurarem a corrida inteira, o log **nunca** diz que a
   NVIDIA falhou, nem por quê — os cenários (c) e (d) só se inferem
   pela aritmética de `calls`/`fallbacks`. *Menor correção:* contador
   `errors_by_route` (provedor/modelo → status/contagem) incrementado
   em **toda** falha de rota, tenha a mutação sucesso ou não.
4. **Sem carimbo de tempo.** Nem o stdout nem o `run_log.jsonl` têm
   timestamp de parede (só durações). Não dá para correlacionar trechos
   da corrida com janelas externas (reset de cota, horário). *Menor
   correção:* campo `ts` em cada registro de `emit()` e prefixo de
   hora nas linhas de `log`.
5. **Nenhum banner de configuração no início.** O log não imprime a
   cadeia de rotas ativa, os modelos, o pacing efetivo
   (`FORGE_LLM_MIN_INTERVAL_S` pode vir do ambiente sem deixar rastro)
   nem a política de retry. A atribuição de cenário depende de inferir
   tudo isso das descrições de aceitas. *Menor correção:* uma linha de
   abertura no `run_forge`/`LLMMutator.__init__` com cadeia, modelos,
   intervalo mínimo e backoffs — e, idealmente, uma chamada-sonda por
   rota com o status impresso (fecha também o ponto 3 na largada).
6. **`fallbacks` é um contador global único.** Não diz qual degrau da
   cadeia resgatou as mutações. As descrições das aceitas cobrem isso
   parcialmente (dá para reconstruir pelo `run_log.jsonl`), mas não
   para as falhas. *Menor correção:* `success_by_route` e
   `failure_by_route` nas stats.
7. **As linhas por bloco da avaliação cega não são persistidas.**
   `final_evaluation.json` guarda agregados (médias, ΔS, IC95), não as
   64 linhas por braço que `blind_evaluation` calcula. Se o veredito
   for contestado, o pareamento bloco a bloco dos braços-programa não
   pode ser reauditado a partir dos artefatos (só re-rodando — e as
   seeds de teste não se reabrem por capricho). *Menor correção:*
   incluir `rows` dos braços no JSON da avaliação final.
8. **A célula-markdown de abertura do notebook está desatualizada.**
   Ela descreve a lineup antiga (`gemini-2.5-flash-lite`,
   `gemini-2.5-pro`, `qwen/qwen3-32b`) e o bloqueio como "sem nenhum
   dos dois secrets" — as células executáveis foram emendadas, o texto
   não. Quem lê o topo do notebook é induzido ao erro sobre qual
   corrida está vendo. *Menor correção:* atualizar o markdown para a
   cadeia atual (NVIDIA → Gemini 3.x → Groq) e para a sonda de três
   chaves. (Cosmético, mas já custou confusão real nesta saga.)
9. **`forge/config.yaml` é espelho, não fonte.** Nem `run.py` nem
   `llm_mutator.py` leem o YAML em runtime — os valores vivos são as
   constantes no código (limiar 0,45, 5 ilhas, modelos, timeout). Se um
   dia alguém editar só o YAML achando que mudou a corrida, nada muda.
   *Menor correção:* ou o driver passa a ler o YAML, ou o banner do
   ponto 5 imprime os valores efetivos do código, deixando o espelho
   inofensivo.
10. **Observabilidade durante a corrida é zero por construção.** O
    Kaggle não publica log/arquivos de versão em execução, e o
    checkpoint a cada 25 iterações (`run_summary.json`) só é publicado
    com o restante, no fim. Nada no código muda isso; o mitigador
    honesto é o desenho em duas versões do item (f). Registrar como
    limitação conhecida, não como defeito corrigível nesta versão.

---

## 4. Sanidade do protocolo — a V8 ainda testa a hipótese da issue #6?

**Sim.** Conferidos um a um contra o pré-registro (épica #1 / protocolo
em `docs/FORGE-V1-LOG.md`, espelhado no docstring de `forge/run.py`):

- **300 iterações, seed 42:** a célula 3 chama `run_forge(iterations=300,
  seed=42, mutator_kind='llm', final=True, final_processes=4)`. ✔
- **5 ilhas, seleção e migração:** `NUM_ISLANDS = 5`, exploitation 0,7,
  migração do campeão a cada 50 iterações (`forge/run.py:69-72`). ✔
- **Cascata:** stage1 com 8 episódios (treino F0) e stage2 com 64
  episódios (validação F0+F1) — defaults de `forge/evaluator.py:64-66`
  — disparado quando S1 ≥ 0,45 ou S1 é recorde (`want_stage2` +
  `CASCADE_THRESHOLD = 0.45`, `forge/run.py:68`). ✔
- **Final cega:** campeão × `evo:6a94b587701d` (de
  `forge/tournament_champion.json`, via `T.evaluate_test(genome,
  final=True)`) × semente, nos 64 blocos de teste — 32 seeds
  9901–9932 × (F0, F2 com choques) de `T.test_blocks()`
  (`src/mundo/tournament.py:44,428`). Abertura única, só no fim. ✔
- **Barra de PROVA:** `forge_verdict` (`forge/run.py:160`) exige
  ΔS ≥ 0,08 **e** IC95_lo > 0 **e** ΔS_F2 ≥ 0 **e** ΔS_choques ≥ 0 **e**
  ΔS vs semente > 0 — exatamente a barra pré-registrada. ✔

**Desvios introduzidos pelas emendas — nenhum fere o protocolo:**

- **Lineup de modelos** (Gemini 3-flash-preview/3.5-flash, Groq
  qwen3.8-27b) **e provedor principal novo** (NVIDIA NIM): o protocolo
  fixa iterações, cascata, final cega e barras — **não** fixa a
  identidade do modelo mutador; a hipótese é sobre evolução guiada por
  LLM contra os baselines, e o ensemble é intercambiável por desenho
  ("qualquer subconjunto de chaves funciona"). As trocas foram
  registradas como emendas no `docs/FORGE-V1-LOG.md` antes dos
  relançamentos, não depois dos resultados. Desvio do *anúncio*
  original, não do *protocolo*.
- **Pacing (1,5s) e backoff (5s/20s):** vivem só no transporte HTTP.
  Não tocam prompt, guarda, avaliador, seeds nem barras. O único efeito
  sobre o experimento é converter falhas transitórias (429) em novas
  tentativas em vez de `rejected_llm` — que é exatamente a correção de
  infraestrutura que a V7 pediu. Efeito colateral real, mas de
  *logística*, não de protocolo: o teto de parede da corrida (cenários
  (e)→(f)).
- **Sonda de três chaves:** o bloqueio original era "sem Gemini **e**
  sem Groq"; a sonda emendada bloqueia só se as **três** faltarem —
  coerente com o ensemble de três provedores e registrado em emenda.
  Na V8 as três estão presentes, então o desvio nem sequer é exercido.

**Ressalva de leitura (não é desvio):** se o desfecho for (c) ou (d),
o veredito continua válido como teste da hipótese, mas a corrida terá
sido, na prática, uma corrida Gemini/Groq — e qualquer narrativa que
atribua o resultado à rota NVIDIA estará errada. O registro no LOG deve
nomear as rotas que de fato produziram as aceitas (campo `mutation` do
`run_log.jsonl`).

---

## Resumo de bolso (para quando o log sair)

1. Tem bloco `FORGE-V1:` **e** aceitas via `llm[nvidia/...]` → (a)/(b):
   aceitar o veredito.
2. Tem bloco, aceitas só via Gemini/Groq, `calls` da NVIDIA ≈ 300 e
   `fallbacks` ≥ 300 → (c)/(d): aceitar o veredito; NVIDIA nunca foi
   exercitada; corrigir/conferir o ID no catálogo antes da próxima.
3. Tem bloco, `rejected_llm` ≈ 300, campeão = semente, ΔS vs semente =
   0 → (e): teste inválido; ler os status HTTP nas `reason`; sondar
   rotas antes de qualquer relançamento.
4. **Não** tem bloco nem artefatos novos → (f): morta pelo relógio;
   nenhum veredito pode ser reivindicado; relançamento só com os
   ajustes estruturais da §2(f) e decisão do fundador. Atenção: (f)
   também é o desfecho provável de (e) — a ausência de veredito, com
   12h de execução, é ela mesma um diagnóstico.
