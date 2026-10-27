"""Testes do veredito da corrida forge-v1 (Degrau 2, issue #6).

O veredito é pré-registrado: esta suíte fixa a tabela em código —
PROVA / MATA / PARCIAL — nas fronteiras exatas do protocolo, para
nenhum notebook futuro reinterpretar os portões na hora do resultado.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "forge"))

from verdict import forge_verdict


def test_prova_no_limite():
    got = forge_verdict(0.08, 0.01, gates_ok=True,
                        archetype_concentrated=False)
    assert got["verdict"] == "PROVA"


def test_prova_negada_sem_ic():
    got = forge_verdict(0.10, -0.01, gates_ok=True,
                        archetype_concentrated=False)
    assert got["verdict"] == "PARCIAL"
    assert "IC95" in got["reason"]


def test_mata_no_limite():
    got = forge_verdict(0.03, 0.01, gates_ok=True,
                        archetype_concentrated=False)
    assert got["verdict"] == "MATA"


def test_mata_por_portao_mesmo_com_ganho():
    got = forge_verdict(0.15, 0.05, gates_ok=False,
                        archetype_concentrated=False)
    assert got["verdict"] == "MATA"
    assert "portão" in got["reason"]


def test_mata_com_delta_negativo():
    got = forge_verdict(-0.05, -0.01, gates_ok=True,
                        archetype_concentrated=False)
    assert got["verdict"] == "MATA"


def test_parcial_concentrado():
    got = forge_verdict(0.05, 0.01, gates_ok=True,
                        archetype_concentrated=True)
    assert got["verdict"] == "PARCIAL"
    assert "arquétipo" in got["reason"]


def test_parcial_intermediario():
    got = forge_verdict(0.05, 0.01, gates_ok=True,
                        archetype_concentrated=False)
    assert got["verdict"] == "PARCIAL"
    assert "intermediário" in got["reason"]


def test_ci_zero_nao_prova():
    got = forge_verdict(0.12, 0.0, gates_ok=True,
                        archetype_concentrated=False)
    assert got["verdict"] == "PARCIAL"
