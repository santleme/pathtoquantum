"""Veredito da corrida forge-v1 (Degrau 2, issue #6) — pré-registrado.

O protocolo da #6 não muda depois do resultado; esta função é a
tradução dele em código, para o notebook da corrida imprimir o
veredito em vez de um humano o interpretar na hora:

- **PROVA**: ΔS >= +0,08 sobre o melhor baseline, IC95 > 0, portões
  de produto ok -> Degrau 2 vira arquitetura oficial.
- **MATA**: ΔS <= +0,03 ou portão de produto violado -> o
  investimento volta ao Degrau 1.
- **PARCIAL**: o resto — ganho concentrado num arquétipo (evolução
  por arquétipo, ilhas semeadas) ou ganho intermediário, abaixo do
  portão PROVA sem ser MATA.

Dois pontos de interpretação, registrados aqui para não virarem
decisão silenciosa no notebook:

1. A faixa intermediária (0,03 < ΔS < 0,08) sem concentração num
   arquétipo cai em PARCIAL: não é PROVA (não bateu +0,08) nem
   MATA (não é <= +0,03). O motivo distingue os dois casos.
2. PROVA exige IC95 > 0: um ΔS >= +0,08 cujo intervalo inclui zero
   não prova nada — cai em PARCIAL com o motivo explícito.

``gates_ok`` agrega os portões de produto da #6 (ecologia do
campeão com eventos narráveis e diversidade comportamental >= 80%
dos do baseline; nenhuma célula comportamental com > 50% das
empresas — as três condições de ``tournament.gates_ok``); quem os
calcula é ``forge/blind.py`` (``product_gates``). Esta função só
aplica a tabela — não mede nada.
"""

from __future__ import annotations

PROOF_DELTA = 0.08
KILL_DELTA = 0.03


def forge_verdict(delta_s: float, ci_low: float, *, gates_ok: bool,
                  archetype_concentrated: bool) -> dict:
    """(veredito, motivo) da corrida forge-v1, pelo protocolo da #6.

    ``delta_s``: S cego do campeão menos S cego do melhor baseline.
    ``ci_low``: limite inferior do IC95 da diferença (pareada, ver
    ``forge/blind.py::paired_delta``). ``gates_ok``: portões de
    produto ok. ``archetype_concentrated``: o ganho vem de um só
    arquétipo (medido na avaliação cega / ecologia).
    """
    if not gates_ok:
        return {"verdict": "MATA",
                "reason": "portão de produto violado (ecologia do "
                          "campeão abaixo de 80% da v0 ou célula "
                          "comportamental com mais de 50% das empresas)"}
    if delta_s >= PROOF_DELTA and ci_low > 0:
        return {"verdict": "PROVA",
                "reason": f"ΔS = {delta_s:+.3f} >= +0,08 com IC95 > 0 "
                          f"(limite inferior {ci_low:+.3f}) e portões ok"}
    if delta_s <= KILL_DELTA:
        return {"verdict": "MATA",
                "reason": f"ΔS = {delta_s:+.3f} <= +0,03"}
    if archetype_concentrated:
        return {"verdict": "PARCIAL",
                "reason": f"ΔS = {delta_s:+.3f} concentrado num arquétipo "
                          "— evolução por arquétipo (ilhas semeadas)"}
    if delta_s >= PROOF_DELTA:
        return {"verdict": "PARCIAL",
                "reason": f"ΔS = {delta_s:+.3f} >= +0,08 mas o IC95 não "
                          f"exclui zero (limite inferior {ci_low:+.3f})"}
    return {"verdict": "PARCIAL",
            "reason": f"ΔS = {delta_s:+.3f} intermediário: abaixo do "
                      "portão PROVA (+0,08) e acima do portão MATA (+0,03)"}
