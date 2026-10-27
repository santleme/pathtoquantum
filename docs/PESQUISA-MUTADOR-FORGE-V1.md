# Pesquisa: o mutador LLM da corrida forge-v1 (issue #6)

Data: 27/10/2026. Preços e limites conferidos na web em 27/10/2026
(fontes ao fim). Complementa `docs/DISSECACAO-OPENEVOLVE-FORJA.md` (§3
já estimava a ordem de grandeza; aqui o número é refeito peça por peça
e comparado entre rotas). **Decisão é do fundador** — este doc só
fundamenta. Nada foi implementado nem lançado.

## 1. Quanto a corrida consome (a estimativa, fundamentada)

A corrida é a do `forge/config.yaml` vigente: `max_iterations: 300`,
1 chamada de LLM por iteração (o ensemble sorteia UM modelo por
iteração, pelos pesos 0,8/0,2), mutação por diff SEARCH/REPLACE
(`diff_based_evolution: true`), `max_tokens: 16000` de teto de saída.

Anatomia de UMA chamada (medida sobre os arquivos reais do repo):

| Peça do prompt | Tamanho real | Tokens ≈ |
|---|---|---|
| System message (config.yaml) | ~2,4 mil caracteres | ~500 |
| Programa-pai (semente: `forge/seed_policy.py`, 5.071 car.; filhos crescem, teto `max_code_length` 40 mil car.) | 5–12 mil car. | 1.300–3.000 |
| Inspirações (1–3 programas do banco, texto integral) | 5–15 mil car. | 1.300–3.800 |
| Métricas do pai + dimensões MAP-Elites + histórico evolutivo | — | 300–600 |
| Artefatos do avaliador (`block_summary`: 9 linhas no stage1, 65 no stage2; `chronicle_highlights` ≤ 12 linhas) | 0,8–6,6 mil car. | 200–1.700 |
| Andaime do template de prompt do OpenEvolve (instruções de diff) | — | 600–900 |
| **Entrada total por iteração** | | **~9 mil (faixa 5–15 mil)** |
| **Saída por iteração** (blocos SEARCH/REPLACE sobre um `decide` de ~100 linhas + fachadas; inclui tokens de raciocínio, que o Gemini cobra como saída) | | **~2,5 mil (faixa 1–4 mil)** |

Totais da corrida (300 iterações):

- **Caso mediano: ~2,7M tokens de entrada + ~0,75M de saída ≈ 3,5M.**
- **Caso conservador** (programas grandes + artefatos de stage2 sempre
  + teto de raciocínio): ~6M entrada + ~1,2M saída ≈ 7M — bate com a
  estimativa de 5–7M da dissecação (§3), que assumia prompts de
  15–25k. As duas contas convergem: **a corrida inteira é uma workload
  de um dígito de milhões de tokens — pequena.**
- Avaliação (CPU) não entra no custo de LLM: stage1 ≈ 0,7 s e stage2
  ≈ 6 s por candidato no motor Python, e o motor nativo da Fase 5
  derruba isso mais ~10×. O gargalo da corrida é a latência do LLM,
  não dinheiro nem CPU.

## 2. As rotas

### 2.1 Gemini API (AI Studio) — a rota do desenho original

Preços pagos atuais (US$/1M tokens, entrada/saída):

| Modelo | Entrada | Saída | Free tier |
|---|---|---|---|
| Gemini 2.5 Flash-Lite | $0,10 | $0,40 | Sim |
| Gemini 3.1 Flash-Lite | $0,25 | $1,50 | Sim |
| Gemini 2.5 Flash | $0,30 | $2,50 | Sim |
| Gemini 3.8 Flash | $0,75 | $3,75 (introdutório até 31/12/2026) | Sim |
| Gemini 2.5 Pro | $1,25 | $10,00 | Sim (legado) |
| Gemini 3.1 Pro | $2,00 | $12,00 | Não |

- **Free tier:** Flash e Flash-Lite são "free of charge" via AI Studio,
  **sem cartão** — só criar a chave. O Google **não publica** os limites
  (RPM/TPM/RPD aparecem só dentro do AI Studio, por projeto, e "não
  são garantidos"); relatos de terceiros convergem para ~5–15 RPM e
  ~1.000–1.500 requisições/dia nos Flash. Uma corrida de 300 chamadas
  cabe num dia se o RPD do projeto for ≥ 300 — verificar no AI Studio
  antes de prometer corrida 100% grátis. Ressalvas do free tier: o
  conteúdo pode ser usado pelo Google para melhorar os produtos (o
  nosso programa-política não é segredo industrial — o repo é do
  fundador e a política evoluída é artefato de jogo) e não há Batch
  API nem caching garantidos.
- **Custo pago da corrida:** com o ensemble **da config atual**
  (80% Flash-Lite + 20% Flash): **≈ US$ 1 (mediano) a US$ 2
  (conservador)**. Com o secundário trocado para **2.5 Pro** (o salto
  de verdade — ver §3): **≈ US$ 4–8**. Corrida 100% Pro: US$ 11–26.
- **Encaixe técnico perfeito:** a config já aponta para o endpoint
  OpenAI-compatible do Gemini (`generativelanguage.googleapis.com/
  v1beta/openai/`); é trocar modelo/peso, não código. No Kaggle, a
  chave entra como **Kaggle Secret** (UserSecretsClient) e o kernel
  roda com internet ligada — precedente interno: o kernel da Fase 5
  já fez `pip install` com `enable_internet: true`. A chave **nunca**
  vai para o repo nem para o notebook.
- **Precedente de desenho:** o AlphaEvolve (DeepMind) usa exatamente
  este padrão — ensemble Gemini Flash (amplitude/volume) + Gemini Pro
  (profundidade/salto). A nossa config é a miniatura fiel disso.

### 2.2 OpenAI API

| Modelo | Entrada | Saída |
|---|---|---|
| gpt-5-nano | $0,05 | $0,40 |
| gpt-5-mini | $0,25 | $2,00 |
| gpt-5.4-mini | $0,75 | $4,50 |
| GPT-6.1 Sol (forte atual) | $2,00 | $10,00 |

- Ensemble equivalente (80% gpt-5-mini + 20% GPT-6.1 Sol):
  **≈ US$ 4 (mediano) a US$ 8 (conservador)**; 100% mini ≈ US$ 2.
- Sem free tier de API utilizável para isto; exige conta + saldo
  pré-pago. Input em cache sai a 10%, mas ajuda pouco aqui: o pai
  muda a cada iteração (só o system message é estável).
- Qualidade de mutação: a família GPT é forte em diff cirúrgico;
  ganho sobre o Gemini Flash não é evidente para este formato
  (SEARCH/REPLACE curto com feedback rico). Trocar de provedor não
  compra qualidade clara — compra uma segunda conta para gerenciar.

### 2.3 Anthropic API

| Modelo | Entrada | Saída |
|---|---|---|
| Claude Haiku 5.5 (prompts ≤ 100k tok) | $0,10 | $0,50 |
| Claude Haiku 4.5 | $1,00 | $5,00 |
| Claude Sonnet 5.5 | $2,00 | $10,00 |
| Claude Opus 5.5 | $4,00 | $20,00 |

- Ensemble equivalente (80% Haiku 5.5 + 20% Sonnet 5.5):
  **≈ US$ 3 (mediano) a US$ 6 (conservador)** — com um asterisco: o
  tokenizer dos Claude ≥ 4.7 gera ~30% mais tokens pelo mesmo texto,
  então o custo real tende ao topo da faixa (~US$ 4–8).
- Sem free tier. Atrito de setup maior: o `api_base` do OpenEvolve é
  OpenAI-compatible; a Anthropic entra pela camada de compatibilidade
  dela ou por um proxy (LiteLLM) — uma peça a mais para quebrar
  dentro do kernel.
- Qualidade: Sonnet é provavelmente o melhor "modelo de salto" das
  três casas para código; mas a 20% das iterações, a diferença para o
  Pro do Gemini é marginal frente ao atrito extra.

### 2.4 Open-weight LOCAL no Kaggle (GPU T4) — mutador dentro do kernel

O desenho já previa esta rota (racional de GPU do projeto; a
dissecação a chamou de "variante B": servidor local apontado no
`api_base` do OpenEvolve, linha do CodeEvolve).

**Hardware real:** Kaggle GPU = T4 ×2 (2 placas de 16 GB — memória
NÃO soma sem sharding) ou P100 16 GB; sessão ≤ ~12 h; **cota de
~30 h/semana de GPU, compartilhada com os treinos PPO do FANUC**.

| Candidato | Pesos (4-bit) | Cabe na T4? | Decode estimado (T4, 1 stream) |
|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct (Q4_K_M) | ~4,7 GB | Sim, folgado | ~35–45 tok/s |
| Qwen2.5-Coder-14B-Instruct (Q4_K_M) | ~9 GB | Sim (1 placa) | ~15–25 tok/s |
| Qwen3-Coder-30B-A3B (MoE, Q3_K_XL) | ~13,8 GB (+KV) | No limite (1 placa) ou dividido nas 2 | ~20–37 tok/s (MoE, 3B ativos) |
| Qwen3-Coder-30B-A3B (Q4_K_M) | ~18,6 GB | Não em 1 placa; split nas 2×T4 via llama.cpp | idem, com risco de setup |
| Qwen2.5-Coder-32B (Q4) | ~19,9 GB | Não | — |

**Throughput da corrida:** por mutação ≈ prefill de ~9k tokens
(6–12 s) + ~2,5k de saída a 15–37 tok/s (70–170 s) ⇒ **~1,5–3 min
por iteração ⇒ 300 iterações ≈ 8–15 h de GPU** — 1 a 2 sessões
(checkpoint a cada 25 iterações permite retomar), consumindo **um
terço a metade da cota semanal de GPU da conta** naquela semana.

**Qualidade esperada:** os Qwen-Coder são bons programadores, mas um
degrau abaixo das APIs de fronteira justamente no que a forja pede:
diff cirúrgico obedecendo formato, respeitando a guarda AST e
aproveitando feedback narrativo (Crônica). Cada diff inválido ou
programa rejeitado pela guarda é uma iteração queimada (fitness 0) —
a taxa de desperdício esperada é maior que nas rotas API, e o custo
"grátis" se paga em iterações efetivas menores e em horas de cota.

**Atrito de setup (o maior das quatro rotas):** empacotar 5–19 GB de
pesos como dataset Kaggle, subir servidor vLLM/llama.cpp dentro do
kernel, apontar o `api_base` para localhost, depurar quantização/
contexto — trabalho de engenharia de ~1 dia antes da primeira
mutação, contra ~10 minutos das rotas API.

**A favor:** custo em dinheiro = US$ 0 para sempre, nenhuma chave,
nenhuma conta nova, nenhuma dependência externa durante a corrida;
e a rota escala para corridas recorrentes (v2, v3…) sem custo
marginal — é a rota certa **quando a forja virar rotina**, não
necessariamente para a primeira corrida.

### 2.5 Híbrido

- **Híbrido que faz sentido (e já é o desenho):** barato para volume +
  forte para salto, **ambos via API** (padrão AlphaEvolve). É a
  recomendação da §3.
- **Híbrido local-volume + API-salto:** economiza ~80% de um custo que
  já é de US$ 1–4 e paga o preço cheio do atrito local + da cota de
  GPU. Não se paga na v1. Passa a fazer sentido se um dia o volume for
  10–50× maior (corridas semanais de milhares de iterações) — aí o
  local vira a base e a API fica só para os saltos.

## 3. Tabela comparativa — custo da corrida forge-v1 completa (300 iterações)

| Rota | Custo $ mediano | Custo $ conservador | Qualidade de mutação esperada | Atrito de setup | Riscos principais |
|---|---|---|---|---|---|
| Gemini **free tier** (Flash-Lite/Flash) | **US$ 0** | US$ 0 (se o RPD aguentar) | Boa (Flash) | Baixo: chave no AI Studio, sem cartão | RPD não publicado/não garantido pode truncar a corrida; conteúdo usado p/ treino do Google |
| Gemini pago — config atual (Lite 0,8 + Flash 0,2) | ~US$ 1 | ~US$ 2 | Boa | Baixo | Nenhum relevante |
| **Gemini pago — Lite/Flash 0,8 + Pro 0,2 (recomendada)** | **~US$ 4** | **~US$ 8** | **Boa no volume, forte no salto** | Baixo | Nenhum relevante |
| Gemini pago — teto (100% Pro / 3.1 Pro) | US$ 11–14 | US$ 20–26 | Máxima da casa | Baixo | Nenhum relevante |
| OpenAI (mini 0,8 + Sol 0,2) | ~US$ 4 | ~US$ 8 | Boa/forte | Baixo-médio (conta + saldo) | Segunda conta; sem ganho claro p/ o formato |
| Anthropic (Haiku 5.5 0,8 + Sonnet 0,2) | ~US$ 3 | ~US$ 6–8 (tokenizer +30%) | Boa/forte (melhor salto?) | Médio (compat/proxy) | Peça extra no kernel; sem free tier |
| Local Kaggle T4 (Qwen-Coder) | US$ 0 | US$ 0 | Média (mais diffs inválidos) | **Alto** (~1 dia + dataset de pesos) | 8–15 h da cota de 30 h/sem GPU (disputa com FANUC); sessão de 12 h pode cortar a corrida |
| Híbrido local + API-salto | ~US$ 1 | ~US$ 2 | Média no volume, forte no salto | Alto | Soma os atritos; economia irrelevante na v1 |

## 4. Recomendação

**Rodar a forge-v1 pela API do Gemini, no desenho que a config já
traz, com UMA troca: o modelo de salto (secundário, peso 0,2) sobe de
Gemini 2.5 Flash para Gemini 2.5 Pro; o primário (peso 0,8) fica no
2.5 Flash-Lite (ou 3.1 Flash-Lite). Começar pelo free tier e deixar o
pago como fallback automático da mesma chave/conta.**

Por quê:

1. **O dinheiro é um não-problema.** A corrida inteira custa US$ 4–8
   nessa configuração — menos que o erro de estimativa de qualquer
   outra decisão do projeto. Otimizar centavos aqui comprando atrito
   (rota local) ou uma segunda conta (OpenAI/Anthropic) é trocar o
   recurso escasso (tempo de engenharia + cota de GPU compartilhada
   com o FANUC) pelo recurso abundante (dólares de API barata).
2. **É o desenho validado pela referência do campo:** o AlphaEvolve
   roda Flash × Pro exatamente assim — volume barato para amplitude,
   modelo forte para os saltos. A config da forja já é essa miniatura;
   a troca Flash→Pro no secundário é o que faltava para o "salto" ser
   salto de verdade.
3. **Atrito mínimo e reversível:** chave do AI Studio (sem cartão no
   free tier) → Kaggle Secret → kernel com internet. Se o free tier
   truncar por RPD, o fallback pago na mesma conta destrava sem mudar
   uma linha. Se a qualidade decepcionar, trocar `primary_model`/
   `secondary_model` no YAML é uma decisão de 1 linha, não um projeto.
4. **A rota local não morre — ela espera a v2.** Quando a forja virar
   rotina (corridas recorrentes, milhares de iterações), o mutador
   open-weight no Kaggle se paga: custo marginal zero e independência
   total. Para a PRIMEIRA corrida — cujo objetivo é provar que
   políticas-código LLM batem o campeão do torneio CMA-ES (ΔS +0,075,
   inconclusivo) — o que interessa é a maior taxa de mutações válidas
   e úteis por iteração, e isso hoje é API de fronteira.

**O que muda se o fundador quiser o teto de qualidade:** subir o
peso do Pro para 0,35–0,5 ou rodar 100% Pro (2.5 Pro; 3.1 Pro se
quiser o máximo da casa): a corrida vai para **US$ 11–26** — continua
sendo troco. O teto real da forja v1 não é o modelo nem o dinheiro:
é a taxa de programas que passam na guarda e no stage1, e isso se
mede na corrida, não se compra antes dela.

**A decisão que falta do fundador, em uma frase:** autorizar a
criação da chave no Google AI Studio (2 minutos, sem cartão) e o
cadastro dela como Secret no Kaggle — todo o resto já está desenhado
na config.

## Fontes (conferidas em 27/10/2026)

- Preços Gemini e free tier: https://benchlm.ai/google/api-pricing ;
  https://creditforstartups.com/pricing/gemini-api-pricing ;
  limites do free tier (não publicados pelo Google; por projeto no AI
  Studio): https://www.memetik.ai/guides/gemini-api-free-tier-limits
- Preços OpenAI: https://www.g2.com/articles/openai-api-pricing ;
  https://www.promptunit.ai/blog/openai-api-too-expensive-what-to-do
- Preços Anthropic: https://www.finout.io/blog/anthropic-api-pricing ;
  https://www.sentra.app/articles/claude-api-pricing
- Kaggle (cota ~30 h/semana de GPU, sessões ~12 h, T4 ×2 16 GB):
  https://www.geeksforgeeks.org/how-to-use-gpu-in-kaggle/?type=article&id=1314455 ;
  https://masterprompting.net/blog/colab-vs-kaggle-vs-paid-gpu-for-fine-tuning-small-models
- Qwen3-Coder-30B-A3B (tamanhos por quantização):
  https://www.thinkfacility.com/run-locally/qwen/ ; decode MoE em T4:
  https://inferprice.pages.dev/articles/llama-cpp-moe-expert-cache
- AlphaEvolve (ensemble Flash × Pro):
  https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
- Arquivos do repo: `forge/config.yaml`, `forge/seed_policy.py`
  (5.071 caracteres), `forge/evaluator.py` (artefatos),
  `docs/DISSECACAO-OPENEVOLVE-FORJA.md` §3.
