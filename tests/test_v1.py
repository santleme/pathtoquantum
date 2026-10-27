"""Testes do salto v1 — mundo maior, ferramentas novas, crônica rica.

Fixtures minúsculas como no resto da suíte: a corrida de verdade roda
no Kaggle. Aqui se prova estrutura, determinismo e os invariantes.
"""
import pytest

from mundo import world
from mundo.engine import Engine


# --------------------------------------------------------------------- #
# 1) Mundo maior
# --------------------------------------------------------------------- #
def test_grid_expanded_anchors_kept():
    assert (world.ROWS, world.COLS) == (30, 22)
    # âncoras do v0 intactas: nada que existia muda de célula
    for d in world.DEPOSITS:
        assert d.cell == world.cell_of(d.lat, d.lon)
    for c in world.CITIES:
        assert c.cell == world.cell_of(c.lat, c.lon)
    # o norte novo é endereçável sem clamp (lat 17 era fora da grade v0)
    r, col = world.cell_of(17.0, -60.0)
    assert r == 29 and 0 <= col < world.COLS


def test_v1_world_counts_default_and_fallback():
    eng = Engine(seed=7, n_companies=8)                    # dataset real (v1)
    assert eng.world_source == "realdata"
    assert len(eng.deposits) == 13 and len(eng.cities) == 11
    names = {d.name for d in eng.deposits}
    assert {"Salar del Hombre Muerto", "Cerro Verde (Arequipa)",
            "El Mutún"} <= names
    assert {"Montevidéu", "Assunção", "Medellín"} <= \
        {c.name for c in eng.cities}
    off = Engine(seed=7, n_companies=8, world_data=False)  # fallback = v0
    assert len(off.deposits) == 10 and len(off.cities) == 8
    assert {d.name for d in off.deposits} == {d.name for d in world.DEPOSITS}


def test_v1_new_deposits_hidden_until_probed():
    eng = Engine(seed=3, n_companies=8)
    mutun = eng._deposit_by_name["El Mutún"]
    assert eng.remaining["El Mutún"] == mutun.size_t > 0
    for comp in eng.companies:                 # fog-of-war vale p/ os novos
        assert "El Mutún" not in comp.knowledge
        assert "Cerro Verde (Arequipa)" not in comp.knowledge
