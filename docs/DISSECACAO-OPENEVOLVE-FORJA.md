# Dissecação: OpenEvolve como motor da forja de políticas (Degrau 2)

Data: 26/10/2026. Fonte: clone raso do repo em 26/10/2026 (v0.2.33,
HEAD 34f5e9d) + leitura do código do PtQ. Complementa docs/FRONTEIRA-2026.md
e docs/ALGORITMOS-DECISAO.md. NÃO muda a ordem decidida pelo fundador:
Degrau 1 primeiro, forja depois. Isto é o mapa para quando a forja chegar.

## 1. O que o OpenEvolve é por dentro

- Pacote Python, Apache-2.0, `pip install openevolve` (PyPI v0.2.33).
  Núcleo `openevolve/`: ~11,3 mil linhas; 94 arquivos de teste; repo ativo
  (push no próprio dia da análise).
- Entrada: três arquivos — `initial_program.py` (a semente),
  `evaluator.py` (a função de fitness) e `config.yaml`. CLI próprio
  (`openevolve-run.py`) ou uso como biblioteca (`run_evolution`).

### O loop (controller.py + process_parallel.py)

1. `ProgramDatabase.sample()` sorteia um **pai** e **inspirações** da ilha
   corrente (estratégia exploration × exploitation configurável).
2. O `PromptSampler` monta o prompt: system message, código do pai,
   métricas dele, "áreas de melhoria" inferidas, histórico evolutivo,
   inspirações, e **artefatos** da avaliação (ver §3).
3. Um **ensemble de LLMs** (modelos com pesos, qualquer endpoint
   OpenAI-compatible via `api_base`) devolve a mutação — por padrão
   *diff-based*: blocos SEARCH/REPLACE sobre o código do pai
   (`diff_based_evolution: true`); rewrite completo é opção.
4. O filho vira arquivo temporário e é avaliado em pool de processos
   (`parallel_evaluations`), com timeout por avaliação.
5. O resultado (dict de métricas) entra no banco; checkpoints periódicos
   e um `evolution_trace` registram tudo (inclui as mensagens do LLM) —
   linhagem completa de graça.

### O banco evolutivo (database.py, 2.832 linhas — o maior arquivo)

- **Ilhas** (default 5), cada uma com sua própria grade **MAP-Elites**.
- Dimensões da grade (`feature_dimensions`) são configuráveis: qualquer
  métrica retornada pelo avaliador (ou característica do código) vira
  eixo comportamental do arquivo.
- Migração entre ilhas a cada 50 gerações (taxa 0,1).
- Rejeição por novidade opcional via embeddings de código.

### O avaliador (evaluator.py)

- Contrato mínimo: `evaluate(program_path) -> dict[str, float]`.
- **Cascata nativa**: `evaluate_stage1/2/3` + `cascade_thresholds` —
  estágio barato elimina candidato antes do estágio caro.
- Canal de **artefatos**: o avaliador pode devolver textos (logs,
  diagnósticos) que são injetados no prompt da próxima mutação. O LLM
  vê *por que* o pai perdeu, não só o placar.

### Marcadores de escopo

- `# EVOLVE-BLOCK-START/END` no programa-semente delimitam a região que
  pode evoluir; o resto fica congelado.

## 2. O encaixe no PtQ — peça por peça

| Peça PtQ (já existe) | Peça OpenEvolve | Encaixe |
|---|---|---|
| HeuristicPolicy (engine.py) | programa-semente | Extrair a política para arquivo próprio, com EVOLVE-BLOCK em volta de `decide` + fachadas (`reserve`, `pick_deposit`, `build_downstream`, `plan_buys`, `buffer`, `plan_sells`, `use_tools`) e imports/helpers congelados fora do bloco |
| Torneio (tournament.py, índice S, campos F0/F1) | `evaluator.py` | O avaliador importa o candidato, monta a focal via PolicyRouter contra o campo congelado e devolve S + métricas comportamentais |
| Cascata pré-registrada (8 eps → 64 eps) | `evaluate_stage1/2` + thresholds | Direto: stage1 = screening 8 episódios; stage2 = 64 episódios; stage3 opcional = campo F1 (liga) |
| Arquivo de espécies / portão de diversidade | MAP-Elites com `feature_dimensions` comportamentais | Eixos sugeridos: elo máximo, taxa de uso de ferramentas, nº de minas (proxy de agressividade) — campeão sem colapsar a ecologia |
| Crônica como feedback | artefatos do avaliador | Devolver excertos da crônica da focal + eventos salientes no artefato: o LLM muta sabendo a história da derrota |
| Linhagem na Crônica | evolution_trace + id do programa | Hash do programa vira o `policy_id` (análogo ao `genome_hash` atual) |
| Ilhas por arquétipo (veredito PARCIAL) | `island_initial_programs` + system message por ilha | Ilhas semeadas: mineradora agressiva, verticalizadora, comerciante — evolução por arquétipo sai da configuração, não de código novo |

### Trabalho de integração real (o que NÃO vem pronto)

1. **`PolicySpec(kind="program")`** em policies.py: hoje só existem
   `v0 | genome | mutant`. O roteador precisa instanciar uma política a
   partir de arquivo/hash — é o `build_policy` que falta.
2. **Extração da semente**: a HeuristicPolicy vive dentro de engine.py
   (2.192 linhas) e usa métodos privados do motor (`engine._spend`,
   `engine._note_link`, `engine.chronicle`). A semente precisa ser um
   módulo que recebe `engine`/`comp` pela interface Policy — sem copiar
   o motor junto.
3. **Guarda anti-trapaça (o risco nº 1)**: no espaço-genoma (CMA-ES) a
   política só move 20 constantes clipadas; no espaço-código ela pode
   *inventar regra* — inclusive quebrar o fog-of-war, que hoje é
   convenção, não barreira: o código candidato enxerga `engine.deposits`
   com teor/tamanho verdadeiros. O avaliador precisa de lint por AST
   proibindo acesso direto a `deposit.grade/size_t` fora de
   `comp.knowledge`, manipulação de `engine.rng`, escrita fora de
   `comp._offers/_buys` etc. Sem isso, a forja "descobre" exploit, não
   estratégia.
4. **Trava de seeds continua nossa**: o OpenEvolve não sabe nada das
   seeds de teste 9901–9932. O avaliador só usa treino/validação; a
   avaliação final cega (campo F2 + choques) roda FORA do loop, pelo
   protocolo do torneio, com `final=True`.
5. **Paralelismo aninhado**: o controller do OpenEvolve já usa
   ProcessPool; o driver do PtQ também. Dentro do avaliador, rodar os
   episódios em série (ou pool raso) para não aninhar pools no Kaggle.
6. **Tamanho do programa**: `max_code_length` default (20k caracteres
   no exemplo) é pouco para a política extraída (~350 linhas com as
   fachadas); subir na config.

## 3. Custos

- Avaliação é barata: episódio de torneio ~0,09 s (medido no projeto);
  stage1 (8 eps) ≈ 0,7 s, stage2 (64 eps) ≈ 6 s por candidato. Para
  ~300 candidatos, CPU total fica na casa de dezenas de minutos.
- Quem domina o custo é o **LLM**: 1 chamada por iteração, prompt com
  pai + inspirações na casa de 15–25k tokens. 300 iterações ≈ 5–7M
  tokens — troco com modelo classe Flash-Lite/mini via API; o ensemble
  default do projeto (primário barato 0,8 + forte 0,2) já é o desenho
  certo. A alternativa open-weight local (Qwen3-Coder-30B via servidor
  vLLM apontado em `api_base`, linha do CodeEvolve) elimina custo de
  API mas complica o notebook Kaggle; fica como variante B.
- Teto de custo de LLM pré-declarado no protocolo v1 continua valendo:
  `max_iterations` + ensemble barato executam o teto.

## 4. O que ele NÃO resolve

- Liga/coevolução contra campos congelados: é do avaliador (já temos).
- Multi-objetivo de verdade: o banco ordena por escore combinado —
  o índice S (50/30/20) já escalariza, então não dói.
- Determinismo da mutação: LLM amostrado não é reproduzível; mas cada
  programa gerado é salvo com pai, métricas e diff — a linhagem é
  auditável, que é o que a Crônica precisa.
- Risco de reward hacking além do fog-of-war: thresholds da cascata
  podem selecionar política que passa no screening por sorte de seed;
  mitigação é a mesma do protocolo (validação separada + final cego).

## 5. Veredito

**ADAPTAR — adotar o OpenEvolve como motor da forja v1, escrevendo a
camada PtQ por cima.** Construir o loop em casa (ilhas + MAP-Elites +
pool paralelo + checkpoints + trace) seriam semanas para chegar a um
subconjunto pior do que já existe, testado e Apache-2.0.

Plano de spike (1 dia, quando o Degrau 1 liberar a forja):
extrair a semente → avaliador só com stage1 → 30 iterações de fumaça
com ensemble barato → conferir (a) programas válidos, (b) lint
anti-trapaça segurando, (c) trace legível. Passou, roda o protocolo
completo de ~300 candidatos já pré-registrado.

Comparados e descartados para este papel: ShinkaEvolve (mais novo,
amostra-eficiente, mas ecossistema menor — fica como plano B se o
custo de avaliação virar gargalo; hoje não é), GEPA (ótimo para
otimizar prompt/texto com feedback reflexivo; a forja precisa de
diff de código + arquivo MAP-Elites, que é o OpenEvolve).
