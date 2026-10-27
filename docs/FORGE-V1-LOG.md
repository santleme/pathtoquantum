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

(preencher no lançamento: bundle, kernel, sonda de secrets, monitor)
