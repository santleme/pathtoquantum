"""Testes da avaliação final cega da forja (Degrau 2, issue #6).

Cobre a trava (sem final=True não roda nada), o caminho cego em
miniatura (1 seed de teste, 12 ticks — precedente em
test_tournament.py), o caminho do genoma CMA-ES, a validação de
seeds, a matemática do delta pareado (ordem e focal inclusos), a
concentração por célula comportamental e os três portões de produto.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "forge"))

from blind import (blind_ecology_program, blind_evaluate_genome,
                   blind_evaluate_program, concentrated_by_cell,
                   paired_delta, product_gates)
from mundo import tournament as T
from mundo.genome import GENOME0

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "forge" / "seed_policy.py"


def _row(seed, field, s, focal=0, stage=0, fac=0):
    return {"seed": seed, "field": field, "S": s, "focal_cid": focal,
            "stage": stage, "facilities": fac}


def test_trava_sem_final():
    with pytest.raises(T.TestSeedLock):
        blind_evaluate_program(str(SEED), ticks=12, processes=1)


def test_trava_genoma_sem_final():
    with pytest.raises(T.TestSeedLock):
        blind_evaluate_genome(GENOME0, ticks=12, processes=1)


def test_cega_recusa_seed_fora_do_conjunto():
    with pytest.raises(ValueError, match="só aceita seeds de TESTE"):
        blind_evaluate_program(str(SEED), final=True, seeds=[7],
                               ticks=12, processes=1)


def test_ecologia_recusa_seed_de_teste():
    with pytest.raises(T.TestSeedLock):
        blind_ecology_program(str(SEED), seeds=[9901], ticks=12,
                              processes=1)


def test_caminho_cego_em_miniatura():
    rows = blind_evaluate_program(str(SEED), final=True, seeds=[9901],
                                  ticks=12, processes=1)
    assert len(rows) == 2
    assert {(r["seed"], r["field"]) for r in rows} == {(9901, "F0"),
                                                       (9901, "F2")}
    assert {r["shocks"] for r in rows} == {False, True}
    for r in rows:
        assert isinstance(r["S"], float)


def test_caminho_genoma_em_miniatura():
    rows = blind_evaluate_genome(GENOME0, final=True, ticks=12,
                                 processes=1)
    assert len(rows) == 64
    assert {(r["seed"], r["field"]) for r in rows} == \
        {(s, f) for s in T.TEST_SEEDS for f in ("F0", "F2")}
    for r in rows:
        assert isinstance(r["S"], float)


def test_delta_pareado_e_ic():
    champ = [_row(9901, "F0", 0.60, 0), _row(9901, "F2", 0.50, 1),
             _row(9902, "F0", 0.70, 2)]
    base = [_row(9901, "F0", 0.50, 0), _row(9901, "F2", 0.50, 1),
            _row(9902, "F0", 0.60, 2)]
    got = paired_delta(champ, base)
    assert got["n_blocks"] == 3
    assert abs(got["delta_s"] - (0.10 + 0.0 + 0.10) / 3) < 1e-12
    assert got["ci_low"] < got["delta_s"] < got["ci_high"]


def test_delta_exige_mesmo_tamanho():
    champ = [_row(9901, "F0", 0.6, 0), _row(9901, "F2", 0.5, 1)]
    base = [_row(9901, "F0", 0.5, 0)]
    with pytest.raises(ValueError, match="desemparelhadas"):
        paired_delta(champ, base)


def test_delta_exige_mesma_ordem_e_focal():
    champ = [_row(9901, "F0", 0.6, 0), _row(9901, "F2", 0.5, 1)]
    base = [_row(9901, "F0", 0.5, 0), _row(9901, "F2", 0.5, 2)]
    with pytest.raises(ValueError, match="sem par"):
        paired_delta(champ, base)


def test_delta_exige_dois_blocos():
    champ = [_row(9901, "F0", 0.6, 0)]
    base = [_row(9901, "F0", 0.5, 0)]
    with pytest.raises(ValueError):
        paired_delta(champ, base)


def test_concentrado_uma_celula():
    champ = [_row(9901, "F0", 0.7, 0, stage=3, fac=2),
             _row(9901, "F2", 0.5, 1, stage=1, fac=1)]
    base = [_row(9901, "F0", 0.5, 0, stage=3, fac=2),
            _row(9901, "F2", 0.5, 1, stage=1, fac=1)]
    concentrated, means = concentrated_by_cell(champ, base)
    assert concentrated
    assert means == {(3, 2): pytest.approx(0.2), (1, 1): pytest.approx(0.0)}


def test_nao_concentrado_duas_celulas():
    champ = [_row(9901, "F0", 0.7, 0, stage=3, fac=2),
             _row(9901, "F2", 0.6, 1, stage=1, fac=1)]
    base = [_row(9901, "F0", 0.5, 0, stage=3, fac=2),
            _row(9901, "F2", 0.5, 1, stage=1, fac=1)]
    concentrated, _ = concentrated_by_cell(champ, base)
    assert not concentrated


def test_portoes_ok():
    ok, reasons = product_gates(
        {"events_per_episode": 10.0, "diversity_cells": 4.0,
         "max_cell_share": 0.40},
        {"events_per_episode": 10.0, "diversity_cells": 4.0,
         "max_cell_share": 0.30})
    assert ok and reasons == []


def test_portoes_eventos_abaixo_de_80():
    ok, reasons = product_gates(
        {"events_per_episode": 7.0, "diversity_cells": 4.0,
         "max_cell_share": 0.40},
        {"events_per_episode": 10.0, "diversity_cells": 4.0,
         "max_cell_share": 0.30})
    assert not ok and any("80%" in r for r in reasons)


def test_portoes_diversidade_abaixo_de_80():
    ok, reasons = product_gates(
        {"events_per_episode": 10.0, "diversity_cells": 3.0,
         "max_cell_share": 0.40},
        {"events_per_episode": 10.0, "diversity_cells": 4.0,
         "max_cell_share": 0.30})
    assert not ok and any("diversidade" in r for r in reasons)


def test_portoes_celula_acima_de_50():
    ok, reasons = product_gates(
        {"events_per_episode": 10.0, "diversity_cells": 4.0,
         "max_cell_share": 0.60},
        {"events_per_episode": 10.0, "diversity_cells": 4.0,
         "max_cell_share": 0.30})
    assert not ok and any("50%" in r for r in reasons)
