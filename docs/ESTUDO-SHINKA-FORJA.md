# ESTUDO — 3 técnicas do ShinkaEvolve para a forja (issue #21)
### Path to Quantum · 27/10/2026 · Estudo sobre os artefatos da corrida forge-v1 (Version 7) — sem nova corrida, sem mudança de motor

> Escopo: medir, contra os dados da corrida v1, o que cada técnica do
> ShinkaEvolve (SakanaAI, arXiv:2509.19349v1, ICLR 2026) teria mudado,
> e recomendar por técnica: portar / adiar / descartar. O porte em si
> vira issue filha após decisão do fundador — nada muda no código
> neste estudo. Números da v1 são de `results/forge-v1/` (run_log.jsonl,
> archive.json, run_summary.json, final_evaluation.json); números do
> paper são citados com seção; estimativas próprias estão marcadas
> como estimativa.

---

# Sumário executivo

**A v1 não testa as técnicas — ela testa a falta de mutador.** 300/300
iterações, 1 aceita, 299 rejected_llm, 0 rejected_guard, 0 duplicate,
arquivo final com 2 programas (semente + 1 filho pior). Qualquer
"economia" ou "distribuição" calculada sobre a v1 é, na prática, sobre
2 programas — e o estudo diz isso em voz alta em vez de extrapolar.

**Recomendações (decisão do fundador):**

1. **Amostragem de pais — PORTAR, mas a weighted, não só a lei de
   potência.** A configuração validada no paper é a weighted
   (λ=10, peso = desempenho sigmoid × novidade 1/(1+N filhos)); a lei
   de potência é uma opção do repo, não a validada. O driver atual
   (70% melhor da ilha, 20% aleatório, 10% semente, sem fator de
   novidade) é mais guloso que ambas e não tem botão de diversidade.
2. **Rejeição por novidade pré-avaliação — PORTAR SÓ O TIER 1, com
   proxy local, e ADIAR o juiz LLM.** O ganho grande do paper vem do
   embedding (cosseno, limiar 0,95); o juiz agrega pouco (palavra do
   próprio §5) e, na forja, uma chamada extra ao LLM pode custar mais
   que a avaliação economizada (stage1 = 8 episódios). Sem modelo de
   embedding no ambiente Kaggle, o Tier 1 entra como proxy local
   (AST normalizado / similaridade de texto do bloco mutável) —
   calibrado, não importado.
3. **Bandit de LLM — ADIAR até a Version 8 provar uma rota sustentável.**
   Na v7 todas as rotas estavam mortas (429/404): o bandit aprenderia
   "quota", não "qualidade de modelo". Com 1 rota principal (NVIDIA)
   o bandit é vazio; ele só faz sentido com ≥2 rotas vivas + warm-up
   uniforme. Não descartar: a fórmula (recompensa = exp(melhora
   positiva), UCB1) é portável quando houver ensemble vivo.

**O que a SPEC do porte deve fixar antes de qualquer código** (o paper
não decide pela forja): lei de potência (α) OU weighted (λ); limiar
de novidade (0,95 do paper vs 0,99 do repo atual) e escopo (ilha vs
arquivo); modelo/proxy de embedding; cap de tentativas de novidade e
o que acontece ao esgotar; fórmula UCB + normalização da recompensa;
warm-up do bandit. Sem esses números pré-registrados, o porte vira
cópia de default de repo — e o default atual nem é o do paper.

---

# 1. O que a v1 realmente mediu (números, não narrativa)

Fonte: `results/forge-v1/run_summary.json` + `run_log.jsonl` (301
linhas: iteração 0 = semente, 1–300 = loop) + `archive.json`.

- Iterações: 300/300. Contagens: accepted 1, rejected_guard 0,
  rejected_llm 299, error 0, duplicate 0.
- Arquivo final: 2 programas — semente `prog:fcf3162c8751`
  (S1=0,4953125, S2=0,49462890625) e filho `prog:98cd636f8cad`
  (iteração 1, S1=0,43359375, S2=None — abaixo do limiar 0,45 e sem
  recorde, logo sem stage2).
- Programas avaliados no loop: **1** (o filho da iteração 1).
  Episódios de torneio gastos com candidatos: 8 (só stage1).
  Top-diffs da linhagem do campeão: vazio (campeão = semente).
- Veredito impresso: FORGE-V1: REPROVADO/AJUSTAR. ΔS vs campeão do
  torneio = −0,0750, IC95 [−0,1153, −0,0339], 64 blocos; ΔS vs semente
  = 0,0000. O rótulo é o do protocolo; a hipótese "mutação por LLM
  melhora a política" **não foi testada** — 299/300 mutações nunca
  chegaram a ser avaliadas.
- Mutator stats (run_summary): chamadas gemini-3-flash-preview 300,
  gemini-3.5-flash 300, groq gpt-oss-120b 299, groq qwen3.8-27b 299;
  fallbacks 898, failures 299. Motivo dominante nas iterações 2–300:
  Gemini HTTP 429 (quota) nas duas rotas + Groq HTTP 404 na rota
  gpt-oss-120b (a razão do log é truncada em 400 caracteres, mas o
  padrão se repete nas 299 linhas).
- Smoke de referência (programático, não LLM):
  `results/smoke-forja/`: 30/30 aceitos, 0 duplicados. Ou seja: nem
  o smoke mede taxa de duplicata — o mutador programático já tem
  retry até hash novo (3 tentativas) e nunca precisou dele ali.

**Consequência honesta para as 3 técnicas:** não há taxa de
duplicata, distribuição de pais nem aprendizado de bandit a medir
na v1, porque não há população. O que o estudo mede é (a) o teto
da economia na v1 (quase zero, por construção), (b) o que cada
técnica mudaria no driver atual (código, não dados), e (c) o
custo de portar vs o custo que ela ataca — com o veredito da v8
(Version 8, NVIDIA + pacing/backoff, em execução sob monitor
próprio) como o dado que falta para o bandit.

# 2. Estado atual do driver (o que seria mudado)

Alvo do porte: `forge/run.py` na linhagem `forja/forge-v1-modelos-kaggle`
— **não** a biblioteca OpenEvolve. A corrida v1 rodou o loop em casa
(semente → pai → mutação LLM → guarda AST → stage1 → stage2); o
OpenEvolve é desenho de referência na dissecação, e `forge/config.yaml`
é espelho documental, não lido pelo driver: as constantes vivem
hardcoded em `run.py` (CASCADE_THRESHOLD=0,45, NUM_ISLANDS=5,
EXPLOITATION=0,7, CHECKPOINT_EVERY=25, MIGRATION_EVERY=50). O porte
tem que mudar `run.py` **e** espelhar `config.yaml`, ou o drift volta.

Seleção de pai hoje (`run.py`, loop, ilha = iteração % 5):
- 70%: melhor S1 da ilha; 20%: membro aleatório da ilha; 10%: semente.
- Sem fator de novidade, sem rank, sem memória de quantos filhos
  cada pai já gerou. Migração do campeão global a cada 50 iterações.
- Já existe, depois da chamada ao LLM e antes da avaliação, um
  filtro de novidade **exato**: hash do candidato em `seen` (tentativas:
  1 para LLM, 3 para programático) — duplicata exata vira
  `duplicate`/`rejected_llm`, sem gastar torneio. O que o Shinka
  acrescenta aqui é o **quase-duplicado** (similaridade, não hash),
  não o estágio em si.

# 3. Técnica 1 — Amostragem de pais

## O que o paper faz (arXiv:2509.19349v1, §3.1)

Duas estratégias, e a distinção importa:

- **Lei de potência:** ordena por fitness (rank r=1 = melhor),
  p ∝ r^(−α). α=0 → uniforme; α→∞ → hill-climbing (só o melhor).
  Depende só do rank, não do valor do fitness. **O paper não dá α.**
  O default atual do repo é `exploitation_alpha=1,0`, mas a
  estratégia default do repo é a weighted, não a power_law — e uma
  survey secundária cita α∈[1,3] sem estar no paper. Não usar como
  fato do paper.
- **Weighted (a validada):** mediana α0 dos fitness; desempenho
  s = σ(λ·(F−α0)), λ=10,0 em todas as configs do paper; novidade
  h = 1/(1+N(pai)) (N = nº de filhos já gerados); peso w = s·h,
  p = w/Σw. A ablação (§5, Fig. 9) compara a weighted — não a lei
  de potência — contra random search e hill climbing, e a weighted
  vence. Todas as tabelas do apêndice trazem
  `Parent selection strategy | weighted`, `λ | 10,0`.

Ilhas à parte: a ilha é sorteada uniformemente primeiro, as ilhas
evoluem em paralelo e o melhor de cada ilha não migra — a
diversidade vem também daí, não só do sampler.

## O que ela mudaria na forja

- Troca o 70/20/10 fixo por um botão contínuo: com α ou λ, o
  fundador escolhe quanta exploração comprar sem reescrever o loop.
- O fator de novidade h é o ganho real sobre o driver atual: pais
  já muito usados perdem peso mesmo com S alto — hoje um pai
  campeão pode ser sorteado 70% das vezes até cansar.
- Ilustração (cálculo próprio, não do paper): com α=1 e N=40
  (arquivo do paper), o melhor fica com ~23% e o pior com ~0,6%,
  top-10 com ~68%. Com α=2, o melhor salta para ~62% e o top-10
  para ~96% — α alto mata a cauda que justificaria a técnica.
  Com N=300 e α=1, o melhor fica com ~16% e o top-10 com ~47%.

## Medição contra a v1 — e o alerta de escala

- Na v1, o cálculo é vazio: arquivo de 2 programas. Aplicando a
  weighted aos 2 (mediana 0,4644, λ=10): sigmoid semente 0,577,
  filho 0,423; com h (semente já tem 1 filho → 0,5; filho tem 0 →
  1,0), os pesos normalizados ficam **semente 40,5% / filho 59,5%**.
  Ou seja: na escala de S da forja (diferenças de ~0,06), o fator
  de novidade domina o de fitness (razão de sigmoid só 1,36×,
  razão de novidade 2×). Com λ=10 herdado às cegas, a weighted vira
  quase "prefira quem ainda não foi pai" — pode ser o desejado,
  mas tem que ser decisão, não acidente. Se o fundador quiser que
  fitness pese mais, λ tem que subir — e isso é parâmetro da SPEC.
- Custo de porte: baixo (uma função de pesos no lugar do
  70/20/10, atrás de flag, desligada por padrão). Risco: baixo
  (não toca avaliador, guarda ou protocolo; semente bit-idêntica
  com a flag desligada).
- **Recomendação: PORTAR a weighted (λ pré-registrado, com a
  calibração de escala acima), deixando a lei de potência como
  flag alternativa — não como a técnica principal.** A issue #21
  pedia "lei de potência"; o estudo corrige o alvo para a
  configuração validada, sem esconder a correção.

# 4. Técnica 2 — Rejeição por novidade antes da avaliação

## O que o paper faz (§3.2)

- Depois da mutação por LLM, antes da execução/avaliação.
- Tier 1 (barato): embedding só das partes mutáveis (blocos
  EVOLVE-BLOCK), cosseno contra a subpopulação da ilha (a legenda
  da Fig. 3 diz "across the archive" — o paper usa as duas
  formulações; a SPEC fixa o escopo). Modelo nas configs:
  `text-embedding-3-small`; limiar **0,95** (§3.2, §5, configs de
  circle packing/AIME). O repo atual usa 0,99 — deriva de versão,
  não o número do paper.
- Tier 2 (caro, condicional): só se o cosseno máximo exceder o
  limiar, um LLM-juiz avalia se o programa é "meaningfully
  different". O paper **não publica o prompt do juiz nem o critério
  de aceite**, e o §5 ressalva que o juiz agrega pouco: "o ganho
  grande vem do Tier 1; o juiz oferece melhorias marginais".
- Caps: `Max novelty attempts = 3` (AIME) / None (circle packing);
  repo atual: 3. O que acontece ao esgotar as tentativas não é
  especificado — lacuna da SPEC, não do porte.
- Na config ALE-Bench (C++), embedding = None: a técnica foi
  **desligada** ali. É componente opcional com custo próprio,
  não passo obrigatório.

## Medição contra a v1

- Economia na v1: **zero episódios, por construção.** Nenhum
  candidato chegou a ser rejeitado por duplicata (duplicate=0);
  o único filho avaliado gastou 8 episódios de stage1 e não
  passou ao stage2. Se ele fosse quase-duplicado, o Tier 1 teria
  economizado exatamente 8 episódios — 0,3% dos 2.400 episódios
  de stage1 de uma corrida saudável de 300 candidatos, ou 8 de
  8+64 se passasse ao stage2.
- Estimativa para corrida saudável (marcada como estimativa, não
  medida): se a taxa de quase-duplicados fosse 10% (chute, sem
  dado — nenhuma corrida existente a mede), a economia seria
  ~30 candidatos × 8 episódios = 240 episódios de stage1, mais
  stage2 dos que passassem. Se a taxa for ~0% (LLM com
  temperatura 0,7 raramente devolve o mesmo bloco), a economia é
  ~0 e o filtro é só seguro contra bloat do arquivo. **O estudo
  não inventa a taxa: ela só aparece na primeira corrida saudável
  (v8, se concluir com mutações de verdade), e o porte deve
  logar a taxa para calibrar o limiar depois.**
- Custo do Tier 1 na forja: sem `text-embedding-3-small` no
  ambiente Kaggle (sem chave OpenAI no kernel), o Tier 1 fiel ao
  paper não roda. Proxy local viável: AST normalizado do bloco
  mutável + similaridade de texto (difflib, já usado em
  `forge/run.py` para top-diffs) — custo desprezível, sem chamada
  externa, sem nova dependência. O proxy mede outra coisa que o
  embedding (texto/estrutura, não semântica) e o limiar tem que
  ser calibrado contra ele, não copiado (0,95 de embedding ≠ 0,95
  de difflib).
- Custo do Tier 2: uma chamada ao LLM-juiz por candidato
  quase-duplicado pode custar mais (latência + tokens) que os 8
  episódios economizados — e o paper diz que ele agrega pouco.
- Risco específico da forja: o limiar mede similaridade de
  **texto de código, não de comportamento**. Na política PtQ, uma
  micro-mutação no bloco pode mudar muito o torneio, e dois
  códigos textualmente distintos podem jogar igual. Copiar 0,95
  às cegas pode rejeitar justamente as micro-mutações que
  importam, ou aceitar duplicatas comportamentais. O escopo
  "só o bloco mutável" (não o programa inteiro) é o acerto a
  copiar — a semente inteira é igual em todos os candidatos.
- **Recomendação: PORTAR SÓ O TIER 1, com proxy local e limiar
  calibrado na primeira corrida saudável; ADIAR o juiz LLM.**
  Aceitação do porte: taxa de rejeição logada por corrida, sem
  mudar S da semente com a flag desligada.

# 5. Técnica 3 — Bandit de LLM

## O que o paper faz (§3.3)

- Sinal **não** é taxa de aceitação: é melhora relativa de fitness.
  r^u = exp(max(r − r^b, 0)) − 1, onde r^b = max(pai, programa
  inicial). Só melhora positiva conta; o resto vira 0. O exp
  promove mutações ousadas de alto risco/alta recompensa sobre
  melhorias seguras pequenas — e o paper afirma normalizar por
  estatísticas acumuladas, **sem imprimir a fórmula**.
- Alocação por **UCB1** (Auer et al., 2002), atualizada ao fim de
  cada geração (não por mutação), coeficiente de exploração 1,0
  nas configs de circle packing e ALE-Bench. A fórmula UCB explícita
  (termo de bônus) também não é impressa — é escolha da SPEC
  (UCB1 clássico é a óbvia, mas é nossa, não citação).
- Escopo real: na config AIME, `LLM dynamic selection = null`,
  coeficiente 0,0 — o bandit **não** foi usado em todos os
  experimentos. E o efeito é descrito de forma inconsistente no
  próprio paper (legenda da Fig. 9: "slightly improves" sobre o
  ensemble fixo; texto do §5: "significantly outperforms" single
  LLM e ensemble fixo). Tratar o ganho como **modesto e dependente
  de tarefa**, não como vitória grande.

## Medição contra a v1 — por que adiar

- Na v7, um bandit teria aprendido a coisa errada: as 4 rotas
  falharam em 299/300 iterações por **quota (429) e rota inexistente
  (404)**, não por qualidade de mutação. A recompensa r^u seria 0
  para todas as rotas em quase todas as iterações (só a iteração 1
  gerou um filho, pior que o pai — também 0, pelo max(·,0)).
  O bandit convergiria para "nenhuma rota presta" — verdade sobre
  a infra da v7, inútil sobre os modelos.
- Na v8, o desenho muda (NVIDIA principal + pacing/backoff), mas
  o bandit continua vazio com 1 rota principal: ele só existe com
  ≥2 rotas **vivas**. E com 300 candidatos e 3–4 braços, são
  ~75–100 puxadas por braço num processo não-estacionário (o
  arquivo muda a cada geração), com recompensa esparsa — o
  aprendizado será ruidoso no início. Warm-up uniforme + coeficiente
  pré-registrado são pré-requisitos, não detalhes.
- Custo de porte: médio (estatísticas por rota, UCB, normalização,
  persistência no checkpoint). Risco: médio (se a normalização
  estiver errada, o exp satura ou explode na escala de S 0–1; se o
  sinal for quota, o bandit desliga a rota certa pelo motivo errado
  — o porte deve separar falha de infra (429/404/timeout, sem
  atualizar o bandit) de mutação ruim (avaliada, S baixo, atualiza)).
- **Recomendação: ADIAR até a v8 (ou a próxima corrida saudável)
  provar ≥2 rotas vivas por ≥100 iterações cada; NÃO descartar.**
  Quando voltar, o gatilho é dado, não opinião: "bandit entra na
  corrida seguinte à primeira em que 2 rotas entregarem mutações
  avaliadas".

# 6. Decisões que a SPEC do porte deve fixar (checklist para o fundador)

1. Pais: weighted OU power_law? Se weighted: λ (10,0 do paper, com
   a ressalva de escala da §3) e definição de N(pai). Se power_law:
   α (o paper não dá; repo atual 1,0) e escopo (ilha, como o paper).
2. Novidade: limiar (0,95 paper / 0,99 repo) **no proxy escolhido**,
   escopo (ilha vs arquivo), proxy (AST normalizado / difflib),
   cap de tentativas (3, como AIME/repo) e comportamento ao esgotar
   (descartar a iteração? gerar de novo? aceitar?).
3. Bandit (quando voltar): fórmula UCB completa, normalização da
   recompensa, warm-up uniforme (quantas iterações), coeficiente de
   exploração, e regra "falha de infra não atualiza o bandit".
4. Juiz LLM (se um dia voltar): modelo pequeno/barato, prompt e
   critério de aceite publicados na SPEC — hoje inexistentes no paper.
5. Flags: cada técnica atrás de flag própria, desligada por padrão;
   com todas desligadas, a corrida reproduz a semente bit-idêntica
   (S genoma 0 / S1 da semente) e a suíte da forja fica verde.
   Sem isso, o porte não entra — é a aceitação da issue #21.

# 7. O que NÃO fazer (armadilhas do porte)

- Não trocar o motor pelo ShinkaEvolve nem pelo OpenEvolve: o porte
  é de 3 técnicas para o loop em casa, não de biblioteca. A dissecação
  já descartou o Shinka como motor (ecossistema menor) e o manteve
  como plano B se o custo de avaliação virar gargalo — e o custo de
  avaliação **não** é o gargalo da forja hoje (o gargalo da v7 foi
  quota de LLM; o da v8, se houver, se mede lá).
- Não copiar limiar, α ou λ sem a versão: paper (0,95 / λ=10) ≠ repo
  atual (0,99 / default weighted). A SPEC cita a versão que usa.
- Não ligar o bandit na próxima corrida por padrão: sem 2 rotas
  vivas, ele é código morto que pode desligar a rota certa por
  motivo de infra.
- Não medir "sucesso do porte" pelo S da primeira corrida com as
  técnicas ligadas: o S mede o mutador + a sorte da rota, não o
  sampler. O sucesso do porte se mede por: taxa de quase-duplicados
  logada, distribuição de pais observada vs prevista, e estabilidade
  do bandit (se ligado) — métricas do loop, não do placar.

# 8. Fontes

- ShinkaEvolve, paper: arXiv:2509.19349v1 (Lange, Imajuku, Cetin,
  Sakana AI) — §3.1 (pais), §3.2 (novidade), §3.3 (bandit), §5/Fig. 9
  (ablações); proceedings ICLR 2026.
- Repositório oficial: github.com/SakanaAI/ShinkaEvolve — defaults
  atuais (weighted, α=1,0, threshold 0,99, max_novelty_attempts 3)
  citados como "repo atual", distintos do paper onde divergem.
- Forja PtQ: `forge/run.py` (loop em casa, linhagem
  forja/forge-v1-modelos-kaggle), `forge/config.yaml` (espelho),
  `docs/DISSECACAO-OPENEVOLVE-FORJA.md` (Shinka como plano B),
  `docs/FORGE-V1-LOG.md` (protocolo e veredito da v7),
  `results/forge-v1/` (artefatos medidos na §1),
  `results/smoke-forja/` (referência programática).
- Issue #21 (pathtoquantum): entrega deste estudo; porte vira issue
  filha após decisão do fundador.
