# Índice de documentos — `docs/`

**Como ler este projeto:** comece por [`ARQUITETURA.md`](ARQUITETURA.md) (o sistema como ele é hoje) e pelo [`../README.md`](../README.md) (a vitrine). Todo o resto é profundidade, decisão ou história — rotulado abaixo para ninguém confundir log com desenho vigente.

| Documento | Tipo | Status | Quando ler |
|---|---|---|---|
| [`ARQUITETURA.md`](ARQUITETURA.md) | Canônico | **Vigente** (27/10/2026) | Sempre primeiro: componentes, invariantes, índice de módulos. |
| [`PRD.md`](PRD.md) | Produto | Histórico (v1.0, 26/10/2026) | A régua de produto e o plano de versões v0→v3; a arquitetura vigente não é ele. |
| [`SDD.md`](SDD.md) | Desenho | Histórico (v0, 26/10/2026) | O desenho original do motor; o que ele esboçava como futuro (Policy/Observation) foi implementado — ver ARQUITETURA. |
| [`OBSERVATION-SPEC.md`](OBSERVATION-SPEC.md) | Spec | Vigente (guarda v2, migração fechada) | O contrato Observation/Intentions em detalhe, fatia a fatia. |
| [`ALGORITMOS-DECISAO.md`](ALGORITMOS-DECISAO.md) | Decisão | Vigente | Por que CMA-ES/genoma (e não MARL agora); o protocolo do torneio. |
| [`DEGRAU1-DESIGN.md`](DEGRAU1-DESIGN.md) | Desenho | Histórico (implementado) | O desenho do núcleo nativo e seus portões de paridade. |
| [`PESQUISA-MUTADOR-FORGE-V1.md`](PESQUISA-MUTADOR-FORGE-V1.md) | Estudo | Vigente como referência | Rotas/modelos do mutador da forja e seus critérios. |
| [`DISSECACAO-OPENEVOLVE-FORJA.md`](DISSECACAO-OPENEVOLVE-FORJA.md) | Estudo | Histórico (decisão tomada) | A dissecação que fundamentou adaptar — não adotar — o OpenEvolve. |
| [`ESTUDO-MOTOR-AMBIENTE.md`](ESTUDO-MOTOR-AMBIENTE.md) | Estudo | Histórico (implementado por fases) | Mercado vivo, equipamentos, países: desenho e âncoras de calibração das fases B1–B4. |
| [`FRONTEIRA-2026.md`](FRONTEIRA-2026.md) | Estudo | Histórico (26/10/2026) | O mapa de fronteira de algoritmos/ambientes que orientou as escolhas. |
| [`DEGRAU1-LOG.md`](DEGRAU1-LOG.md) | Log | Histórico | Diário do Degrau 1: fases, vereditos Kaggle e o diagnóstico de paridade. |
| [`OBSERVATION-LOG.md`](OBSERVATION-LOG.md) | Log | Histórico | Diário da guarda v2, fatia a fatia, até o fechamento da migração. |
| [`FORGE-LOG.md`](FORGE-LOG.md) | Log | Vivo (atualizado por corrida) | Vereditos e artefatos das corridas da forja (#6). |
| [`EPICA-V3-OUTROS-DEUSES-ERA2.md`](EPICA-V3-OUTROS-DEUSES-ERA2.md) | Decomposição | Horizonte (registro, épica #17) | O destino v3 destrinchado em frentes, portões e perguntas ao fundador; nenhuma fatia antes do veredito da forja (#6) e da chamada dele. |
| [`adr/`](adr/README.md) | Decisões | Vivo | ADRs curtos das decisões que ainda mandam + o índice (incl. ADR-001, da frente visual). |

Fora de `docs/`: [`../DESIGN.md`](../DESIGN.md) é o manifesto/visão do fundador (raiz, vigente) e [`../notebooks/README.md`](../notebooks/README.md) classifica os notebooks Kaggle. Registros de processo que **não** são documentos do projeto: os JSONs de geração de mídia em `assets/` foram removidos do versionamento em commit próprio (a arte final é só `assets/cover.webp`).
