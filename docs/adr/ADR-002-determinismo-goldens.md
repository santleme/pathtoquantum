# ADR-002 — Determinismo e goldens bit-idênticos como contrato (retroativo)

**Contexto.** O produto é assistir à história emergir de um mundo simulado — e comparar políticas, políticas-código e backends entre si. Sem reprodutibilidade exata, nenhum veredito (torneio, forja, paridade) é comparável.
**Decisão.** O motor é determinístico por seed (um único `random.Random` por mundo, nenhum LLM no tick) e a suíte trava a história com **goldens bit-idênticos**: mesma seed e configuração ⇒ mesmos frames, ao dólar.
**Consequência.** Toda mudança de motor precisa ou preservar os goldens ou regravá-los com justificativa explícita; experimentos ganham um chão comum de comparação. Custo: mudanças "inocentes" de ordem/tipo quebram goldens e exigem diagnóstico (ver ADR-003).
Fontes: `docs/SDD.md` §2, testes `tests/test_golden.py`.
