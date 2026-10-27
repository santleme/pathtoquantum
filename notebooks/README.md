# Notebooks Kaggle — classificação

Regra da casa (ADR-006): **a corrida de verdade roda no Kaggle**; cada experimento é um notebook que imprime o próprio veredito no protocolo pré-registrado. Este índice classifica os notebooks desta base — nenhum foi renomeado (o nome é o histórico do kernel).

| Notebook | Classe | O que é |
|---|---|---|
| `kaggle_mundo_v0.ipynb` (+ `kernel-metadata.json`) | Histórico fundador | A corrida de nascimento (120 ticks) — a primeira corrida do mundo. |
| `veredito-b1.ipynb` (+ `kernel-metadata-b1.json`) | Veredito histórico | Mundo vivo B1 — mercado vivo. |
| `veredito-b2.ipynb` (+ `kernel-metadata-b2.json`) | Veredito histórico | Mundo vivo B2 — equipamentos/desgaste. |
| `veredito-b3.ipynb` | Veredito histórico | Mundo vivo B3 — países/política (metadata embutida no notebook). |
| `diag-fase5.ipynb` (+ `kernel-metadata-diag-fase5.json`) | Diagnóstico | Sonda da Fase 5 que isolou a divergência de paridade (diagnóstico de tipo). |
| `veredito-fase5.ipynb` (+ `kernel-metadata-fase5.json`) | Veredito histórico | Degrau 1: paridade nativa **11/11 aprovada**. |
| `torneio-v1.ipynb` (+ `kernel-metadata-torneio.json`) | Canônico (experimento) | Torneio de políticas CMA-ES/genoma (protocolo em `docs/ALGORITMOS-DECISAO.md`). |
| `smoke-forja.ipynb` (+ `kernel-metadata-smoke-forja.json`) | Smoke | Smoke da forja (#6): semente, guarda e avaliador em corrida curta. |
| `forge-v1.ipynb` (+ `kernel-metadata-forge-v1.json`) | Canônico (experimento) | Corrida v1 da forja (#6): mutador LLM + cascata + avaliação cega. |

Corridas posteriores (V6–V8, instrumentação de tempo) vivem nas branches irmãs da linha Kaggle da forja e são registradas em `docs/FORGE-LOG.md` quando produzem veredito.
