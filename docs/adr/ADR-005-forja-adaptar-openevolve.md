# ADR-005 — Forja própria adaptada do OpenEvolve, não adotar o motor (retroativo)

**Contexto.** O Degrau 2 pede evolução de políticas-código por LLM. O OpenEvolve é a referência aberta do gênero, mas adotá-lo inteiro importaria um motor de avaliação que não conhece goldens, guarda de informação nem o protocolo de vereditos do projeto.
**Decisão.** **Adaptar**: forja própria (`forge/` + `src/mundo/program.py`) com semente bit-idêntica à v0, guarda AST de escrita, avaliador em cascata e avaliação cega — incorporando as ideias do OpenEvolve sem ceder o núcleo.
**Consequência.** A forja herda os invariantes do projeto (ADR-002/004) e cada corrida imprime veredito no protocolo pré-registrado da issue #6; o custo é manter o mutador/avaliador em casa.
Fontes: `docs/DISSECACAO-OPENEVOLVE-FORJA.md`, `docs/FORGE-LOG.md`.
