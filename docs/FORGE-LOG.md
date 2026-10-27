# LOG — Forja de políticas-código (Degrau 2, épica #1)

## 2026-10-27 — Corrida forge-v1 (#6) preparada, lançamento travado

**O que é esta fatia.** A corrida oficial (#6) sai do papel para o
notebook: o veredito pré-registrado virou código, a avaliação final
cega ganhou o caminho para programas (o torneio só a tinha para
genomas) e o notebook `notebooks/forge-v1.ipynb` está pronto para o
Kaggle. Nada foi lançado neste ciclo — o lançamento depende de dois
portões do fundador (abaixo), e lançar sem eles seria furar a fila.

**O que foi construído** (branch `forja/corrida-v1-prep`, a partir
de `obs/guarda-v2`):

- `forge/verdict.py` — `forge_verdict(delta_s, ci_low, gates_ok,
  archetype_concentrated)` traduz a tabela da #6: PROVA (ΔS ≥ +0,08,
  IC95 > 0, portões ok), MATA (ΔS ≤ +0,03 ou portão violado),
  PARCIAL (o resto). Interpretações registradas no docstring: a
  faixa intermediária cai em PARCIAL, e ΔS ≥ +0,08 com IC95 incluindo
  zero não prova (PARCIAL com o motivo explícito).
- `forge/blind.py` — avaliação final cega para programas:
  `blind_evaluate_program(final=True)` nos blocos travados
  (seeds 9901–9932, F0 + F2 com choques, focal girando como o
  avaliador da forja); sem `final=True` levanta `TestSeedLock` e
  não roda nada; seeds fora do conjunto são recusadas, e a
  ecologia recusa seeds de teste. `blind_evaluate_genome` é o
  mesmo caminho para o baseline CMA-ES, via
  `tournament.evaluate_test`. `paired_delta` casa campeão e
  baseline por (seed, campo, focal) em ordem, e devolve média +
  IC95; `concentrated_by_cell` mede a concentração do ganho pela
  célula comportamental do campeão (elo × instalações, os eixos do
  MAP-Elites); `blind_ecology_program` é o espelho de
  `ecology_metrics` para programas; `product_gates` aplica as três
  condições de `tournament.gates_ok` (eventos e diversidade ≥ 80%
  do baseline, nenhuma célula > 50%).
- `data/cmaes_champion.json` — o genoma campeão do torneio
  (`evo:6a94b587701d`, 20 genes, copiado por script de
  `results/torneio-v1/genomas_campeoes.json`, que é gitignored)
  como arquivo rastreável: o notebook da #6 precisa do baseline
  CMA-ES dentro do bundle, com delta pareado de verdade contra
  ele — sem ele, o veredito contra a v0 só poderia ser falso.
- `notebooks/forge-v1.ipynb` — loader recursivo (padrão do projeto,
  incluindo o JSON do CMA-ES), corrida via `run_evolution` do
  OpenEvolve real (API conferida contra o pacote PyPI: semente +
  avaliador + config + 300 iterações; o `forge/config.yaml` do repo
  carrega limpo no `Config.from_yaml`; o melhor programa sai de
  `best_code`, pois `best_program` é um objeto `Program` no
  OpenEvolve 0.4.0), chave LLM via segredo `GEMINI_API_KEY` com
  falha explícita sem ele, avaliação cega dos três braços +
  veredito impresso contra o MELHOR baseline, e salvamento do
  campeão e do JSON do veredito. Os 5 melhores programas com diff
  comentado saem do `evolution_trace` no fechamento da issue (o
  notebook registra o mapa dos outputs).
- `notebooks/kernel-metadata-forge-v1.json` — metadata do kernel
  (dataset src12, a criar no lançamento; `enable_internet: true`,
  pois o notebook instala o OpenEvolve e chama a API do LLM).
- Testes: `tests/test_forge_verdict.py` (8, fronteiras da tabela)
  e `tests/test_forge_blind.py` (16, travas + caminhos cegos em
  miniatura — programa com 1 seed e genoma com as 64 linhas a 12
  ticks — + validação de seeds, simetria do delta, concentração
  por célula e os três portões). Suíte total após as correções:
  246 passed, 18 skipped (só o núcleo nativo, não compilado nesta
  worktree), 0 falhas; goldens intactos.

**Revisão independente (mesmo ciclo).** A primeira versão desta
fatia foi REPROVADA pela revisão, com 4 bloqueantes — todos
corrigidos aqui, sem exceção: (B1) metadata sem internet para um
kernel que instala pacote e chama API; (B2) portão de diversidade
ausente no `product_gates` (o protocolo exige as três condições);
(B3) baseline CMA-ES opcional e silencioso, com ajuste improvisado
no IC — agora o genoma está no repo e o delta é pareado de verdade
contra os dois baselines; (B4) "ganho concentrado" medido por campo
(F0/F2), não por arquétipo — agora medido por célula
comportamental. Sugestões aplicadas junto: `best_code` direto,
simetria total do `paired_delta`, validação de seeds nos dois
caminhos cegos e JSON do veredito com os dois baselines. A
operação "concentrado por célula" e o IC95 normal (1,96×se, n=64)
ficam documentados como interpretações, abertas a refino no
fechamento — não escondidas.

**Portões do fundador antes do lançamento (não furar):**

1. Decisão/chave do mutador — criar o segredo `GEMINI_API_KEY` no
   Kaggle (pesquisa em `docs/PESQUISA-MUTADOR-FORGE-V1.md`).
2. Fechamento formal da #5 (smoke) — o veredito do smoke está
   aprovado em kernel, mas a issue segue aberta aguardando a
   escrita aprovada por ele; a #6 depende da #5 pelo protocolo.

**Lançamento, quando os portões abrirem:** criar o dataset
`mundo-autonomo-src12` a partir desta branch (src/ + forge/ +
data/cmaes_champion.json + pyproject.toml), subir o kernel
`ptq-forge-v1` com o notebook acima, monitorar até concluir e
fechar a #6 com o veredito impresso + top-5 diffs. A operação
"ganho concentrado num arquétipo" (delta por célula
comportamental) e o IC95 normal ficam documentados como
interpretações, abertas a refino no fechamento — não escondidas.
