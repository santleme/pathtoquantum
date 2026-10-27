# ADR-003 — Núcleo nativo com paridade bit-idêntica obrigatória (retroativo)

**Contexto.** Torneios e forja pedem ordens de magnitude mais episódios do que o motor Python entrega; um backend rápido que *divirja* do motor de referência destruiria o contrato do ADR-002.
**Decisão.** Backend nativo **opt-in** em C++/nanobind (`src/mundo/native_engine.py` + `src/mundo/native/`), mesma superfície do `Engine`, e só é oficial com **paridade 11/11 bit-idêntica** (clássico + mundo vivo, até n=1.000) provada por fixtures — nunca "quase igual". Sem o núcleo compilado, seus testes pulam e o Python segue como referência.
**Consequência.** Fase 5 aprovada: speedup de 13,3× (n=100) a 8,6× (n=1.000) medido no Kaggle. A reprovação da v2 ensinou o custo: a causa era divergência de *tipo* (`remaining` nasce `int`), corrigida em `_restore_int_types` com regressões dedicadas.
Fontes: `docs/DEGRAU1-DESIGN.md`, `docs/DEGRAU1-LOG.md`.
