# ADR-006 — Computação pesada só no Kaggle (retroativo)

**Contexto.** A máquina de desenvolvimento é fraca para simulação longa/treino, e o fundador determinou a divisão (26/10/2026, reforçada em 27/10/2026 sem exceção de "plano B local"): experimento que roda local distorce tempo, escala e veredito.
**Decisão.** Na máquina local: só código, auditoria, testes estruturais e gestão do repo. **Toda** corrida longa, torneio completo e treino nasce como notebook Kaggle novo, com veredito impresso pelo próprio notebook no protocolo pré-registrado. Se o Kaggle bloquear, espera-se o desbloqueio — não se migra a corrida.
**Consequência.** Notebooks são artefatos de primeira classe (`notebooks/`, classificados em `notebooks/README.md`) e resultados entram no repo como logs/vereditos, não como "rodei aqui e deu".
Fontes: `DESIGN.md` (regra de computação), `docs/SDD.md`.
