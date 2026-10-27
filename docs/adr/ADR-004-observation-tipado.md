# ADR-004 — Fog-of-war por construção: Observation tipada + Intentions (retroativo)

**Contexto.** Políticas que recebem o motor inteiro leem o subsolo, eventos futuros e o RNG — o fog-of-war vira convenção, e qualquer política aprendida/evoluída nasce trapaceando. A guarda v1 tinha canais de vazamento reais (eventos de Deus, eventos forçados, RNG).
**Decisão.** A política recebe apenas uma **Observation tipada e congelada** (o público + o próprio estado; `probe` como única revelação) e devolve **Intentions declarativas**, validadas por inteiro antes de executar. O loader exige `decide(self, obs)`; canais legados viram rejeição nomeada.
**Consequência.** Migração fechada em 4 fatias (suíte 240/240 à época, goldens intactos): vazamento virou impossibilidade de tipo, e políticas de torneio/forja/RL futuro compartilham o mesmo contrato honesto.
Fontes: `docs/OBSERVATION-SPEC.md`, `docs/OBSERVATION-LOG.md`.
