# FORGE-V1 — LOG da corrida (Degrau 2, sub-issue #6)

## Protocolo pré-registrado (27/10/2026, ANTES da corrida)

A corrida oficial da forja de políticas-código: o smoke (#5) provou
o pipeline com mutador programático; aqui quem muta é LLM, no
desenho da épica #1 (docs/DISSECACAO-OPENEVOLVE-FORJA.md) e da
pesquisa do mutador (docs/PESQUISA-MUTADOR-FORGE-V1.md).

- **Driver**: `forge/run.py` (o loop do smoke estendido em casa; o
  OpenEvolve segue como desenho de referência — ver dissecação §5).
- **Iterações**: 300 (forge/config.yaml `max_iterations`), seed 42.
  Iteração 0 = semente (geração 0 = v0), avaliada nos dois estágios.
- **Mutador**: `forge/llm_mutator.py` — ensemble Gemini via endpoint
  OpenAI-compatible: `gemini-2.5-flash-lite` no volume (peso 0,8) e
  `gemini-2.5-pro` nos saltos (peso 0,2), temperatura 0,7, teto de
  16.000 tokens de saída. Falha da rota Gemini (429/5xx/timeout/
  resposta inutilizável) ⇒ fallback Groq: `openai/gpt-oss-120b`,
  depois `qwen/qwen3-32b` (o fundador tem as duas chaves; entram só
  como Kaggle Secrets — GEMINI_API_KEY / GROQ_API_KEY — nunca em
  código, notebook ou log).
- **Formato da mutação**: diff SEARCH/REPLACE restrito ao
  EVOLVE-BLOCK (`enforce_evolve_blocks` aplicado no adaptador:
  edição fora do bloco é revertida), com o feedback completo do pai
  no prompt (métricas, resumo bloco a bloco e destaques da Crônica
  do avaliador, violações da guarda de filhos anteriores, até 2
  inspirações da mesma ilha).
- **Guarda**: `mundo.program.validate_program` antes de qualquer
  avaliação — filho rejeitado não pontua e o motivo volta como
  artefato para a próxima mutação daquele pai.
- **Cascata**: stage1 = 8 episódios F0 em seeds de TREINO; stage2 =
  64 episódios (validação F0+F1) quando S1 ≥ 0,45
  (`cascade_thresholds` da config) ou S1 é recorde do loop.
- **População**: arquivo completo dos aceitos com métricas
  comportamentais (stage_mean, facilities_mean — eixos MAP-Elites
  da config); 5 ilhas, seleção exploitation 0,7, migração do melhor
  global a cada 50 iterações; checkpoint a cada 25.
- **Campeão da corrida**: melhor S2 (validação); desempate por S1.

## Avaliação cega (pré-registrada)

Ao fim do loop, FORA dele, com `final=True` — a primeira abertura
das seeds de TESTE (9901–9932) pelo protocolo:

- **Braços** (todos como empresa focal, rotação idêntica): campeão
  da corrida (programa) × campeão do torneio
  (`evo:6a94b587701d`, genoma em forge/tournament_champion.json) ×
  semente (programa).
- **Blocos**: os 64 do torneio — por seed de teste, (F0 sem
  choques) e (F2 com os choques pré-registrados). O braço-genoma
  roda por `tournament.evaluate_test(genome, final=True)`.
- **Métrica**: ΔS pareado por bloco, IC95 por bootstrap (2.000
  réplicas, o mesmo do torneio), no total e nos recortes F2 e
  choques; ΔS também contra a semente.

## Veredito (barras pré-registradas, as do torneio)

ΔS = ΔS(campeão da corrida − campeão do torneio):

- ΔS ≥ 0,08, IC95_lo > 0, ΔS_F2 ≥ 0, ΔS_choques ≥ 0 e
  ΔS(campeão − semente) > 0 ⇒ **FORGE-V1: PROVA**
- ΔS > 0 sem cumprir a barra ⇒ **FORGE-V1: INCONCLUSIVO**
  (o torneio parou aqui: ΔS +0,075, IC95 [+0,034, +0,115])
- ΔS ≤ 0 ⇒ **FORGE-V1: REPROVADO/AJUSTAR**

Relatório da corrida: `final_evaluation.json` (ΔS e IC95 contra
cada baseline) + `top5_diffs.md` (os 5 passos de maior ganho de S1
na linhagem do campeão, com diff legível) + `champion.py`.

Bloqueio pré-registrado: sem NENHUM dos dois secrets no kernel, o
notebook imprime `FORGE-V1: BLOQUEADO — secrets ausentes` e termina
limpo (ação do fundador: cadastrar os secrets; não é erro).

## Registro de execução

- **Bundle**: `pascalcoimbra/mundo-autonomo-src12` (src/ + forge/ +
  pyproject.toml), criado e **verificado por download** —
  `forge/llm_mutator.py`, `forge/run.py`,
  `forge/tournament_champion.json` e `src/mundo/program.py` com md5
  idêntico ao repo (36 arquivos no zip).
- **Kernel**: `pascalcoimbra/ptq-forge-v1` (kernelId 141168190),
  versão 1, internet habilitada, dataset src12 anexado sem fontes
  inválidas. Push via `scripts/kaggle_push_kernel.py`
  (build_payload/push) com o metadata
  `notebooks/kernel-metadata-forge-v1.json`.
- **Largada (27/10/2026, ~10:05)**: loader recursivo achou o bundle,
  `forge/` completa conferida — e a **sonda de secrets respondeu
  AUSENTE para as duas chaves** (GEMINI_API_KEY e GROQ_API_KEY). O
  notebook imprimiu o bloqueio pré-registrado
  `FORGE-V1: BLOQUEADO — secrets ausentes` e terminou limpo, sem
  erro: o fundador tem as chaves, mas elas ainda não estão
  cadastradas como Secrets deste kernel.
- **Próximo passo (ação do fundador)**: cadastrar GEMINI_API_KEY
  e/ou GROQ_API_KEY como Secrets do kernel e relançar — a corrida
  roda sem mudar uma linha. Monitor `monitor-forge-v1` (15 min)
  acompanha e reporta o bloqueio/veredito nesta conversa.
- **Suíte no lançamento**: 252/252 (240 da guarda v2 + 12 novos:
  adaptador LLM mockado, barras do veredito, linhagem/top-diffs e
  mini-corrida ponta a ponta com avaliação cega em blocos tiny).
- Branch: `forja/forge-v1` (commits 73eb02c + c9e32de + este
  registro), a partir de `obs/guarda-v2` @ 5cc1b31.

## Version 6 e emenda de modelos (27/10/2026)

- **Version 6 do kernel** (Save & Run All, 13:01:17 -03): os Secrets
  foram anexados pelo editor e a sonda respondeu **presente** para
  GEMINI_API_KEY e GROQ_API_KEY. A execução concluiu em 163,8 s, mas
  as **300/300 mutações foram `rejected_llm`**: a lineup antiga
  (`gemini-2.5-pro` e `gemini-2.5-flash-lite`) retorna HTTP 404 para
  a chave do fundador e os fallbacks da Groq também falharam.
  Campeão = a própria semente `prog:fcf3162c8751`; veredito impresso
  **FORGE-V1: REPROVADO/AJUSTAR** — inválido como teste da hipótese,
  porque o mutador nunca gerou um candidato.
- **Correção** (branch `forja/forge-v1-modelos-kaggle`, decisão do
  fundador de relançar no Kaggle): lineup emendada para
  `gemini-3-flash-preview` (volume, peso 0,8), `gemini-3.5-flash`
  (saltos, peso 0,2) e fallbacks Groq `openai/gpt-oss-120b` →
  `qwen/qwen3.8-27b` — modelos com sonda HTTP 200 verificada nesta
  chave em 27/10/2026. O transporte HTTP do mutador ganhou o
  User-Agent comum que destrava a Cloudflare da Groq (erro 1010).
  `forge/llm_mutator.py` e `forge/config.yaml` espelhados; testes
  atualizados.
- **Verificação estrutural**: suíte da forja **59/59** com
  `PYTHONPATH=src` deste checkout. Sem o PYTHONPATH, o pytest importa
  `mundo` de outro checkout e um teste falha na allowlist — artefato
  de ambiente, não da corrida: nesta branch `mundo.intentions` está
  permitido e semente/filho passam na guarda.
- **Relançamento**: bundle novo `pascalcoimbra/mundo-autonomo-src-13`
  (slug real gerado pelo Kaggle a partir do título "Mundo Autonomo
  Src 13"; criado pela interface web em 27/10/2026 às 13:27:55 -03,
  privado, 35 arquivos, porque a API respondeu 401 nesta sessão.
  Mesmo mecanismo: ZIP `mundo-src.zip` com src/ + forge/ +
  pyproject.toml) e nova versão do mesmo kernel
  `pascalcoimbra/ptq-forge-v1` com o metadata
  `notebooks/kernel-metadata-forge-v1-src13.json`. Protocolo
  inalterado: 300 iterações, 5 ilhas, cascata e avaliação cega nas
  seeds 9901–9932 com a mesma régua de veredito.

## Version 7 — veredito (27/10/2026)

- **Lançamento**: 13:32:42 -03, Save & Run All pelo editor web;
  concluída com sucesso em 323,9 s. Bundle confirmado de
  `mundo-autonomo-src-13`; sonda: GEMINI_API_KEY e GROQ_API_KEY
  **presentes**. Código do notebook intocado (diff +0 −0).
- **A correção de modelos funcionou**: a iteração 001 foi aceita via
  `gemini/gemini-3-flash-preview` (`prog:98cd636f8cad`, S1=0,4336).
- **Novo gargalo — cota/ritmo (HTTP 429)**: as outras 299 iterações
  foram `rejected_llm`; as 4 rotas foram tentadas em quase todas
  (calls: 300/300 Gemini, 299/299 Groq; fallbacks 898) e todas
  falharam, com erro dominante 429 ("You exceeded your…"). O driver
  dispara ~1.200 chamadas em ~3,5 min, sem ritmo nem backoff —
  qualquer free tier estrangula essa rajada. (A busca local do Plano
  B não bateu nesse muro porque a avaliação lenta da VM espaçava as
  chamadas naturalmente; o transporte local tinha retry com backoff,
  o do Kaggle não tem.)
- **Veredito impresso**: FORGE-V1: REPROVADO/AJUSTAR. Campeão = a
  semente `prog:fcf3162c8751` (o único filho aceito pontuou menos);
  contagens {accepted: 1, rejected_guard: 0, rejected_llm: 299,
  error: 0}; ΔS vs torneio −0,0750, IC95 [−0,1153, −0,0339].
  Experimento **inválido de novo como teste da hipótese** — agora
  por infraestrutura de cota, não por modelo. Próximo passo
  proposto: portar ritmo + retry/backoff do transporte local para o
  mutador do Kaggle e relançar (decisão do fundador).

## Emenda pré-lançamento — NVIDIA principal + ritmo/backoff (27/10/2026)

- **Motivo**: a V7 morreu por HTTP 429 nas quatro rotas (rajada de
  ~1.200 chamadas em ~3,5 min, sem ritmo nem backoff). Pesquisa de
  provedores gratuitos (3 frentes, fontes oficiais): Cerebras virou
  trial com cartão (reprovada), OpenRouter free é 50 req/dia,
  GitHub Models foi aposentado — **NVIDIA NIM** é a rota nova:
  chave gratuita `nvapi-…` (build.nvidia.com, sem cartão), endpoint
  OpenAI-compatible, modelo coder 480B.
- **O que mudou** (branch `forja/forge-v1-modelos-kaggle`):
  - `forge/llm_mutator.py`: provedor `nvidia` (base
    `https://integrate.api.nvidia.com/v1`, modelo de volume
    `qwen/qwen3-coder-480b-a35b-instruct`) na **frente da cadeia**:
    NVIDIA → par Gemini (volume/salto, pesos inalterados) → par
    Groq. `load_api_keys` enxerga `NVIDIA_API_KEY` no mesmo padrão
    dos demais (env + UserSecretsClient); o ensemble roda com
    qualquer subconjunto de chaves e `NoKeysError` só dispara sem
    nenhuma. Transporte default com **ritmo + retry**: intervalo
    mínimo entre tentativas (default 1,5s, env
    `FORGE_LLM_MIN_INTERVAL_S`) e até 3 tentativas com backoff
    5s→20s em HTTP 429/500/502/503/504 e erros de rede — política
    portada do transporte local provado do Plano B
    (`forge/local_transport.py`).
  - `forge/config.yaml`: espelha o provedor/modelo principal
    (`main_provider`/`main_model`/`main_api_base`), demais intactos.
  - `notebooks/forge-v1.ipynb` (só a célula-sonda): sonda também
    `NVIDIA_API_KEY` e o bloqueio pré-registrado passa a ser "sem
    NENHUMA das três chaves" — nenhuma chave individual é exigida.
    `forge/run.py` não mudou: ele já consome `LLMMutator()`/
    `NoKeysError`, sem referência a provedor.
  - Testes: suíte da forja **64/64** (59 + 5 novos: rota só-NVIDIA,
    NVIDIA primeiro na cadeia, `load_api_keys` com NVIDIA, retry
    com backoff em 429 até sucesso e retry esgotado devolvendo o
    último status).
- **Protocolo da corrida inalterado**: 300 iterações, 5 ilhas,
  cascata, avaliação cega nas seeds 9901–9932 e a mesma régua de
  veredito. Relançamento = bundle novo + nova versão do kernel,
  pendente só do cadastro do secret `NVIDIA_API_KEY`.

## Version 8 (27/10/2026, bundle src14) — REPROVADO/AJUSTAR, teste faminto (inválido como teste completo)

- Lançada 14:04:29 -03 (Save & Run All, diff +0 −0, fonte única
  `pascalcoimbra/mundo-autonomo-src14`), concluída `complete` em
  18.546s de log (~5h09), artefatos em `results/forge-v1-v8/`.
- **Veredito impresso: FORGE-V1: REPROVADO/AJUSTAR.** Campeão
  `prog:038395fa93a1` (iteração 004, diff via Gemini "Lower the
  initial cash reserve and mine…"), S1=0,4797, S2=0,5175.
  Avaliação cega (64 blocos, seeds 9901–9932): S médio forja
  0,5261 × semente 0,5063 × torneio 0,5813; ΔS vs torneio
  **−0,0553** IC95 [−0,0998, −0,0112]; ΔS vs semente **+0,0197**
  IC95 [−0,0046, +0,0456] (cruza zero: sinal indistinguível de
  ruído); F2 −0,0328, choques −0,0328.
- **Causa raiz (a terceira falha de infraestrutura, agora
  diagnosticada por completo):** contagens {accepted: 4,
  rejected_llm: 295, rejected_guard: 0, error: 1, duplicate: 0};
  mutador: 1.187 fallbacks, 295 failures.
  - **NVIDIA: HTTP 404 nas 300 chamadas.** O ID
    `qwen/qwen3-coder-480b-a35b-instruct` não existe no catálogo
    hospedado do NIM sob esse nome. A chave estava presente e foi
    usada (a rota foi chamada; 404 = modelo não encontrado, não
    autenticação). A pesquisa prévia havia sinalizado que o ID
    precisava de confirmação no catálogo vivo/sonda antes do
    lançamento — o lançamento saiu sem essa sonda. Erro de
    processo registrado.
  - **Gemini: HTTP 429 quase o tempo todo.** As 4 aceitas saíram
    todas via Gemini (3× flash-preview, 1× 3.5-flash) nas
    iterações 003–011, nos primeiros ~16 min. Leitura: a cota
    diária gratuita já vinha queimada pelas corridas V6 (13:01)
    e V7 (13:32) do mesmo dia — sobraram poucas chamadas e elas
    acabaram na iteração ~012; dali em diante, 429 contínuo.
  - **Groq: chamado 295× por modelo como reserva, sem nenhuma
    mutação salva** — a cadeia inteira falhou em 295/300.
- **Classificação:** NÃO é teste da hipótese de 300 iterações —
  a evolução morreu de fome na iteração 011 e as 289 restantes
  foram só falhas de rota com backoff (~55–60s cada). O campeão
  de 4 mutações ao menos empatou com a semente na cega (ΔS
  +0,0197 com IC cruzando zero). Hipótese segue ABERTA.
- **Correções antes de qualquer relançamento** (auditoria,
  cenário (e)): (1) confirmar o ID exato do modelo no catálogo
  vivo do NIM ou trocar pela oferta confirmada da referência
  oficial (deepseek-v4-pro/flash, gpt-oss-120b via NVIDIA);
  (2) sonda de 1 chamada por rota ANTES da corrida (kernel de
  fumaça), nunca mais lançar 300 iterações sem provar as rotas;
  (3) não rodar duas corridas no mesmo dia sobre as mesmas cotas
  diárias gratuitas; (4) usar a build instrumentada
  (`forja/instrumentacao-tempo`) para o log já nascer com tempos
  por fase e por rota.

## Correção pré-relançamento V9 — sonda pré-voo (ciclo operador, 27/10/2026 ~20h)

- **Fatia**: branch `forja/sonda-pre-voo` (base
  `forja/instrumentacao-tempo` + veredito V8 trazido por cherry-pick
  de 09ba1d1, que faltava nessa base). Cobre as correções (1), (2)
  e (4) da auditoria da V8; a (3) vira regra de lançamento abaixo.
- **O que mudou** (sem tocar em cascata, seeds de teste, avaliador,
  guarda, prompts de mutação ou protocolo de veredito):
  - `forge/llm_mutator.py`: fallback NVIDIA `openai/gpt-oss-120b`
    logo após o primário na cadeia (ID confirmado na tabela de
    modelos suportados da NVIDIA, GPT-OSS-120B); `LLMClient.chat`
    aceita `max_tokens`; `LLMMutator.probe_routes()` faz 1 chamada
    de 32 tokens por rota (primário + fallback NVIDIA, par Gemini,
    par Groq), sem levantar e sem contar em `stats['calls']`;
    `probe_gate()` exige ≥1 rota viva; `format_probe_report()`
    imprime OK/FAIL por rota com o status.
  - `forge/run.py`: `--probe-only` — kernel de fumaça separado da
    corrida: imprime o relatório e `FORGE-PROBE: PASS` (retorno 0)
    ou `FORGE-PROBE: FAIL` (retorno 2, nenhuma rota viva) ou
    `BLOQUEADO` (retorno 3, sem chaves). A corrida normal não muda
    quando a flag está ausente.
  - Testes: `tests/test_forge_probe.py` (9 novos, transporte
    mockado por provedor+modelo): fallback NVIDIA após 404,
    relatório da sonda reproduzindo a V8 em miniatura, payload de
    32 tokens, sonda fora das stats de mutação, portão e os quatro
    caminhos do `--probe-only` (PASS, FAIL, BLOQUEADO,
    programmatic rejeitado); `tests/test_forge_timing.py`
    atualizado para primário + fallback (route_seconds dos dois).
- **Verificação estrutural**: suíte completa da branch verde
  (**254 passed, 18 skipped**; sonda 9/9 após as correções das
  ressalvas); revisão independente de 2 eixos APROVA COM RESSALVAS
  nos dois eixos, sem bloqueio — ressalvas de código corrigidas
  (cadeia única de rotas, portão/relatório usados pelo driver,
  sonda sem escapar exceção, testes BLOQUEADO/programmatic);
  limites restantes declarados abaixo.
- **Regras de relançamento da V9 (não é lançamento neste ciclo)**:
  (a) rodar o kernel de fumaça (`run.py --probe-only`) PRIMEIRO e
  só largar a corrida com `FORGE-PROBE: PASS`; (b) não lançar no
  mesmo dia de outra corrida sobre as mesmas cotas diárias — a V8
  queimou a cota do dia 27/10, então a V9 espera a virada da cota;
  (c) corridas longas rodam DE NOITE (regra do fundador pós-V8);
  (d) a V9 usa esta build instrumentada + sonda.
- **Limites declarados da sonda (revisão independente, sem
  bloqueio)**: (i) a corrida normal NÃO é portada — o que impede
  outra V8 é a regra (a) acima, procedural, não um portão dentro
  de `run_forge` (mudar isso seria alterar o protocolo da corrida,
  decisão do fundador); (ii) a sonda prova vivacidade, não mutação
  utilizável — um modelo que devolva texto sem diff passa e ainda
  assim salvaria zero mutações; (iii) PASS não garante cota para
  300 iterações — a regra (b) continua valendo como regra de
  lançamento. Hipótese da #6 segue ABERTA; nenhum veredito novo
  neste ciclo.

## Emendas pós-V8 — portão interno, poda, captura alargada, cadeia de modelos e os dois bugs da fumaça src15 (27/10/2026)

- **Fatia**: branch `forja/portao-sonda` (base `forja/sonda-pre-voo`
  @ 27974d0), aprovada pelo fundador. Fecha o limite (i) da seção
  anterior (o portão entra no código), revê a cadeia de modelos
  com a pesquisa oficial e corrige na raiz os dois bugs que a
  fumaça do bundle src15 (kernel `ptq-forge-v1` Version 9, 27/10
  ~22:56) expôs. **Infraestrutura apenas**: nenhum prompt,
  cascata (stage1/stage2), threshold, seed, RNG ou scoring
  mudou — troca de modelo do mutador é infraestrutura, como nas
  emendas da V7 e da V8.
- **Bug 1 — a barra que faltava (causa-raiz dos 404 da NVIDIA e
  da Groq)**: `LLMClient.chat()` montava a URL por concatenação
  (`base + "chat/completions"`), mas `NVIDIA_API_BASE` e
  `GROQ_API_BASE` não terminam em `/` — TODAS as chamadas iam
  para `.../v1chat/completions`. A Groq confessou no próprio
  corpo do erro da fumaça: `Unknown request URL: POST
  /openai/v1chat/completions`. **Reinterpretação honesta do
  histórico**: NVIDIA e Groq estavam inalcançáveis em TODAS as
  versões (V6–V8); só o Gemini — cuja base termina em `/` — foi
  testado de verdade até hoje. Os 404 da V8 eram DOIS defeitos
  sobrepostos: a barra E o ID fora do catálogo (abaixo).
  Correção na raiz: a junção base+path é normalizada no cliente
  (`rstrip("/") + "/"`), qualquer que seja a grafia da constante,
  e `tests/test_forge_gate.py` trava a URL final EXATA dos três
  provedores.
- **Bug 2 — o 200 ilegível do Gemini**: na fumaça, o
  `gemini-3-flash-preview` respondeu HTTP 200 e o parse quebrou
  com KeyError 'content' (a message veio sem essa chave). Parse
  defensivo em `_extract_text()`: aceita `content` string,
  `content` como lista de partes e `reasoning_content` quando o
  content falta ou vem None; sem texto utilizável, o erro
  registra a FORMA recebida (nomes das chaves da message + tipo
  do content — nunca o conteúdo), para a próxima sonda
  diagnosticar sem adivinhação. Registro honesto: o log da
  fumaça NÃO traz o corpo da resposta, então a forma exata segue
  não observada — o parse cobre as formas plausíveis e, se uma
  próxima fumaça quebrar, o erro agora diz a forma.
- **Cadeia de modelos (pesquisa oficial de 27/10/2026)**:
  - NVIDIA principal: `deepseek-ai/deepseek-v4-flash` —
    confirmado na referência oficial do NIM hospedado
    (23/10/2026).
  - NVIDIA fallback: `openai/gpt-oss-120b` — mantido, confirmado
    no catálogo; na fumaça, o 404 dele era SÓ o Bug 1.
  - REMOVIDO de vez: `qwen/qwen3-coder-480b-a35b-instruct` —
    ausente da referência oficial do NIM hospedado; o 404 era
    definitivo, não transitório.
  - Gemini volume: `gemini-3-flash-preview` — mantido,
    confirmado vigente (o defeito dele era o Bug 2, no parse,
    não no modelo).
  - Gemini salto: `gemini-3.8-flash` SUBSTITUI o
    `gemini-3.5-flash`, DEPRECIADO em 08/10/2026 e desde então
    roteado silenciosamente para o 3.6 — a única rota "OK" da
    fumaça era um modelo trocado em silêncio, e troca silenciosa
    de modelo é inaceitável no pré-registro.
  - Groq: `openai/gpt-oss-120b` (tier Production) +
    `qwen/qwen3.8-27b` (confirmado; teto de saída de 16.384
    tokens — acima do MAX_TOKENS=16000 da forja, com folga de
    apenas 384).
  - Fontes oficiais: referência de modelos do NIM
    (docs.api.nvidia.com) e changelog da API Gemini
    (ai.google.dev/gemini-api/docs/changelog).
- **Portão dentro de `run_forge()`**: antes da iteração 0, a
  corrida sonda as rotas e se RECUSA a largar — imprime
  `FORGE-GATE: BLOCKED` + motivos, grava `summary["fatal"]` e
  encerra com zero iterações consumidas — a menos que
  `nvidia/openai/gpt-oss-120b` esteja vivo E ≥1 rota Gemini
  esteja viva (`llm_mutator.race_gate`; Groq é reforço e NÃO
  conta para o mínimo). O `probe_gate` fraco (≥1 rota viva)
  segue valendo só para o relatório do kernel de fumaça
  (`--probe-only`). Desligar o portão interno é explícito e
  registrado: `run_forge(probe_gate=False)`,
  `forge/run.py --no-probe-gate`, config `probe_gate` em
  forge/config.yaml — default LIGADO, para smokes/testes antigos
  seguirem o caminho de antes.
- **Poda de rotas mortas**: as rotas reprovadas na sonda saem da
  cadeia daquela corrida (`LLMMutator.prune_dead_routes`; o
  filtro é aplicado depois do sorteio volume/salto — o consumo
  de RNG não muda), com o fato em
  `summary["probe_gate"]["pruned_routes"]` (provedor, modelo e
  erro de cada uma).
- **Captura alargada por rota**: no `mutate()`, qualquer exceção
  de transporte de uma rota (não só `MutationError`) conta como
  falha DAQUELA rota e a cadeia segue para a próxima — fecha o
  vazamento em que uma exceção fora da tupla do transporte
  (ex.: `http.client.BadStatusLine`) escapava do `chat()`,
  pulava o resto da cadeia e a iteração virava `error` no driver
  (mecanismo plausível do `error: 1` da V8). `MutationError`
  consolidado só quando TODAS as rotas falham, como antes.
- **Veredito da fumaça src15 (registro)**: pelo critério forte
  (gpt-oss-120b NVIDIA vivo + ≥1 Gemini), a fumaça NÃO
  qualificou — a corrida V9 segue SEM lançar até bundle novo
  sobre esta branch + nova fumaça aprovada pelo critério forte.
- **Verificação estrutural**: suíte completa da branch verde
  (**292 passed** neste ambiente — 272 da base + 20 novos; nos
  ambientes sem o núcleo nativo compilado, os 18 de paridade
  pulam, como na base). Testes novos em
  `tests/test_forge_gate.py` (20: cadeia travada nas 6 rotas,
  URL exata ×3, parse tolerante ×4, race_gate ×4, poda ×2,
  captura alargada ×2, portão em run_forge ×4) e IDs atualizados
  em test_forge_llm/test_forge_probe/test_forge_timing — nenhum
  teste referencia os IDs mortos.

## Emenda de catálogo NIM — âncora nova do portão (28/10/2026)

A fumaça do bundle src15 reprovou pelo critério forte e a sonda
ampla de 28/10 mostrou o motivo: o catálogo do NIM hospedado
**rotacionou** — IDs que constavam da referência oficial de
23/10/2026 morreram em dias. A sonda com chamadas reais é a
única verdade; esta emenda troca a leitura de catálogo por
**enumeração viva** e substitui os IDs mortos pelos vivos
medidos. Infraestrutura de novo: nenhum prompt, cascata,
threshold, seed, RNG ou scoring muda.

- **Método**: `GET /v1/models` com a chave do projeto (kernels
  de sonda v12/v13 sobre o bundle src16) → **85 modelos** no
  catálogo servido; presença conferida por ID + chamada real
  (chat completion) nos candidatos.
- **Mortos / ausentes do catálogo (410 Gone, com a data de
  morte devolvida pelo NIM)**: `deepseek-ai/deepseek-v4-pro` e
  `deepseek-ai/deepseek-v4-flash` (07/08/2026),
  `openai/gpt-oss-120b` (03/09/2026), `kimi-k3` (15/10/2026),
  `qwen2.5-coder` (12/05/2026) — ou seja, **os dois IDs NVIDIA
  da cadeia pós-V8** (`deepseek-v4-flash` no volume e
  `gpt-oss-120b` no fallback/âncora) já não existiam quando a
  fumaça src15 rodou. `z-ai/glm-5.3` sem resposta (3 timeouts
  de 180s) e `moonshotai/kimi-k2.6` 404 completam o quadro.
- **Vivos medidos com chamada real (kernel v13)**:
  `nvidia/nemotron-3-ultra-550b-a55b` — 200 em **8,0s** (o mais
  rápido); `deepseek-ai/deepseek-v4.1-flash` — 200 em 67,3s
  (provável cold start; latência morna a confirmar na fumaça
  src17); `poolside/laguna-xs-2.1` — 200 em 80,8s;
  `openai/gpt-oss-20b` — 200 em 167,5s (lento).
- **Substituições (branch `forja/portao-sonda`)**:
  `NVIDIA_VOLUME_MODEL`: `deepseek-v4-flash` →
  `deepseek-ai/deepseek-v4.1-flash` (sucessor direto, presente
  no catálogo e vivo). `NVIDIA_FALLBACK_MODELS`:
  `openai/gpt-oss-120b` → `nvidia/nemotron-3-ultra-550b-a55b`
  — como `GATE_REQUIRED_ROUTE` deriva da constante do
  fallback, **a âncora do portão muda junto**: sai o
  gpt-oss-120b (EOL 03/09/2026) e entra o nemotron-ultra (vivo
  e o mais rápido medido). O CRITÉRIO não muda: fundação NVIDIA
  viva (a rota do fallback) + ≥1 rota Gemini viva; Groq segue
  reforço e não conta para o mínimo. IDs espelhados em
  `forge/config.yaml` e nos testes
  (test_forge_gate/test_forge_llm/test_forge_probe/
  test_forge_timing); a rota Groq `openai/gpt-oss-120b`
  PERMANECE — o ID morreu na NVIDIA, não na Groq.
- **`PROBE_MAX_TOKENS` 32 → 512**: a 32 tokens, modelos com
  reasoning devolviam 200 sem texto (o Groq gpt-oss-120b só
  respondeu a 512 na sonda) — o teto antigo reprovava na sonda
  justamente modelos vivos.
- **Verificação estrutural**: suíte completa verde
  (**292 passed**) após a emenda.
- **Próximo passo**: bundle **src17** sobre esta branch +
  fumaça `--probe-only`; corrida V9 só com o critério forte
  PASS (nemotron-ultra OK + ≥1 Gemini OK).
