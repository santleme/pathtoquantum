# Spike Degrau 1 — Portão 0 (comparativo de motores)

Medição executada em 26/10/2026 nesta VM (2 vCPU, Python 3.12.3,
g++ 13.3, nanobind 3.1.0 + numpy instalados no `.venv` do projeto —
custo de setup: ~15 s de pip). Protocolo e regra de decisão:
`docs/DEGRAU1-DESIGN.md` §2. **Nada aqui é importado pelo pacote
oficial**; o kernel é descartável por construção.

## Como reproduzir

```bash
.venv/bin/python experiments/degrau1/kernel/build_kernel.py   # compila o .so
.venv/bin/python experiments/degrau1/spike_python.py          # manhã: Python
.venv/bin/python experiments/degrau1/spike_native.py          # tarde: nativo
```

## Manhã — teto do Python (overlay bit-idêntico)

Equivalência (hash SHA-256 do `state_dict` completo — estado, RNG,
crônica e frames — baseline × overlay):

| Fixture | Resultado |
|---|---|
| n=8 × 24 ticks | **BIT-IDÊNTICO** |
| n=100 × 24 ticks | **BIT-IDÊNTICO** |
| n=8 × 120 ticks | **BIT-IDÊNTICO** |

Benchmark (ms/tick, mediana; `step()` cronometrado, mundo realdata):

| n | baseline | overlay (hotspots 1–2) | overlay + total corrente (hotspot 3) |
|---:|---:|---:|---:|
| 8 | 0,295 | 0,338 (0,87×) | 0,306 (0,96×) |
| 100 | 2,042 | 2,390 (0,85×) | 1,976 (1,03×) |
| 1.000 | 19,742 | 22,792 (0,87×) | 19,658 (1,00×) |

**Leitura honesta — o overlay NÃO acelera.** Perfil (`cProfile`,
n=100 × 120 ticks) explica: o corpo original de `buffer()` já é
barato (~0,7 µs/chamada; a memoização troca computação por dois
`dict.get` de custo comparável), e o custo do `pick_deposit` é a
sequência de `rng.uniform` por candidato — intocável sem mudar a
história sorteada. A primeira versão do overlay (cache por
tuplas/frozenset + pré-varredura) mediu 0,79–0,81×; a segunda,
0,85–0,87×. O hotspot 3 (total corrente no `_market`) sobreviveu
aos fixtures de equivalência (n=8 e n=100 × 120 ticks bit-idênticos
na prática), mas **não é bit-idêntico por construção** (a ordem das
somas muda; divergência de ulp é possível) e rende só ~1,03× —
porque o `sum()` recomputado é sobre poucos vendedores por
commodity; o custo real do mercado é o laço quadrático de
preenchimento, que é algorítmico, não de soma.

Conclusão da manhã: **a estimativa de 2,5–4× do estudo para
micro-otimizações não se materializa** neste motor sem (a) o
refactor struct-of-arrays (hotspot 4) ou (b) aceitar divergência de
ulp/novos goldens. O melhor Python bit-idêntico medido continua
sendo o motor atual: **2,042 ms/tick a n=100**.

## Tarde — teto do nativo (kernel C++/nanobind)

Kernel descartável (`kernel/market_kernel.cpp`, −O2,
`-ffp-contract=off`, sem `-march=native`) replicando só a aritmética
de `_produce` + `_market` sobre arrays planos sintéticos;
referência Python em laços puros com a mesma sequência de operações.

**Equivalência** (10 passos de produce+market, diff. máx. absoluta):

| n | stocks | cash | prices | remaining |
|---:|---:|---:|---:|---:|
| 100 | 1,1e-13 | 7,5e-09 | **0,0** | **0,0** |
| 1.000 (esparso) | ~1e-13 | 1,5e-08 | **0,0** | **0,0** |

`_produce` isolado é **bit-idêntico**; preços e `remaining` também.
A divergência de ≤1 ulp em caixa/estoques foi rastreada até a causa:
**o `sum()` do CPython ≥3.12 usa somação compensada (Neumaier)** —
o motor e a referência somam com compensação; o kernel somava
ingenuamente. Prova: com as somas da referência trocadas por somas
ingênuas, a diff. kernel × referência cai para **exatamente 0,0**
em 10 passos. Consequência prática para a Fase 5: bit-identidade
com o motor atual exige replicar **três** coisas — MT19937, ordem
das operações/sem FMA **e a somação Neumaier do CPython 3.12** nos
totais do mercado (~15 linhas). Registrado no design (§3.3/§3.5).

**Benchmark** (µs por passo produce+market, mediana):

| n | referência (laços Python) | kernel | speedup |
|---:|---:|---:|---:|
| 100 | 7.123,1 | 162,6 | **43,8×** |
| 1.000 (esparso) | 86.045,2 | 1.880,2 | **45,8×** |

Ressalva de Amdahl: `_produce` + `_market` são ~29,3% do tick —
trocar **só** essas fases limita o ganho do tick a ~1,39×. O caso
do núcleo nativo (§3 do design) é portar o `step()` inteiro sobre
as tabelas SoA (a fase de decisão, 50% do tick, é aritmética da
mesma natureza). A 20× conservadores no passo inteiro, a projeção
do portão cairia para ~11 min.

**Referência de teto JAX (sem compromisso, números do estudo)**:
JaxMARL ~14× wall-clock e até ~12.500× com corridas vetorizadas;
EconoJax treinou a economia do AI Economist em ~13 min contra dias.
O teto em lote do JAX segue 1–2 ordens acima do núcleo nativo —
e continua gated à Fase 6 (gargalo medido de MARL ecológico).

## Veredito do Portão 0 (regra pré-registrada)

Projeção = melhor Python bit-idêntico × 2,5 (mundo rico) ÷ 4
processos, para 10M de ticks a n=100:

```
2,042 ms/tick → 213 min  (> 45 min)   E   kernel 43,8×  (≥ 15×)
```

**PORTÃO ABERTO: núcleo nativo aprovado como Fase 5** (Rust/PyO3
pela preferência do estudo; C++/nanobind é a alternativa medida
equivalente). Observação de robustez: mesmo que as
micro-otimizações entregassem a estimativa otimista do estudo
(0,51–0,82 ms/tick), a projeção seria 53–85 min — ainda acima dos
45 min. O veredito não depende de o overlay ter falhado; depende
da régua, que é estrita por desenho (uma corrida ecológica rica
completa deveria caber folgadamente numa sessão de Kaggle).
