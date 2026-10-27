"""Paridade do núcleo nativo (Degrau 1, Fase 5) contra o motor Python.

O PORTÃO da Fase 5: o backend nativo (mundo.native_engine.NativeEngine,
núcleo C++/nanobind em src/mundo/native/) reproduz o motor de
referência BIT A BIT — mesmo hash SHA-256 do state_dict (o mesmo
protocolo dos goldens da Fase 1) e mesmo result(), no clássico e no
mundo vivo completo (market_v2 + country_v2 + equip_v2), incluindo
snapshot/restore cruzado nos dois sentidos.

Sem toolchain C++ na máquina, os testes pulam (o núcleo é opt-in;
o caminho Python puro nunca depende dele).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from mundo import native
from mundo.engine import Engine

pytestmark = pytest.mark.skipif(not native.available(),
                                reason="núcleo nativo não compilado")

from mundo.native_engine import NativeEngine  # noqa: E402

LIVING = dict(market_v2=True, country_v2=True, equip_v2=True)
GOD = [
    {"tick": 5, "type": "price_shock", "commodity": "copper",
     "factor": 1.8},
    {"tick": 10, "type": "discovery", "name": "Serra Nova",
     "resource": "lithium_ore", "lat": -20.0, "lon": -45.0,
     "size_t": 9000, "grade": 0.8},
    {"tick": 15, "type": "sanction", "resource": "copper_ore",
     "duration": 8},
]
FORCE = {"force_events": [
    {"tick": 3, "country": "Chile", "event": "election"},
    {"tick": 6, "country": "Brasil", "event": "export_restriction",
     "resource": "iron_ore"},
    {"tick": 9, "country": "Argentina", "event": "disaster"},
    {"tick": 12, "country": "Peru", "event": "royalty_reform"},
    {"tick": 15, "country": "Chile", "event": "state_jv"},
    {"tick": 18, "country": "Brasil", "event": "subsidy"},
    {"tick": 21, "country": "Peru", "event": "judicial_halt"},
]}


def _hash(x) -> str:
    return hashlib.sha256(
        json.dumps(x, sort_keys=True, ensure_ascii=False,
                   default=str).encode()).hexdigest()


def _steps(eng, n):
    for _ in range(n):
        eng.step()


def assert_parity(ticks, **kw):
    py = Engine(**kw)
    py.run(ticks)
    nat = NativeEngine(**kw)
    nat.run(ticks)
    assert _hash(nat.state_dict()) == _hash(py.state_dict())
    assert _hash(nat.result()) == _hash(py.result())


def test_golden_classico_n8():
    """O nativo reproduz até o GOLDEN da Fase 1 (hash conhecido)."""
    nat = NativeEngine(seed=42, n_companies=8)
    nat.run(24)
    assert _hash(nat.state_dict()) == \
        "e01923e16b48cfa6f0aa934fb1a20d93ea0ac053dc9406f620fa1c900e417373"


def test_parity_classico_n8_120():
    assert_parity(120, seed=42, n_companies=8)


def test_parity_classico_n100():
    assert_parity(24, seed=42, n_companies=100)


def test_parity_classico_builtin():
    assert_parity(24, seed=42, n_companies=8, world_data=False)


def test_parity_god_events():
    assert_parity(60, seed=7, n_companies=8, god_events=GOD)


def test_parity_mundo_vivo_n8():
    assert_parity(48, seed=42, n_companies=8, **LIVING)


def test_parity_mundo_vivo_n8_longo():
    assert_parity(120, seed=42, n_companies=8, **LIVING)


def test_parity_mundo_vivo_n100():
    assert_parity(48, seed=42, n_companies=100, **LIVING)


def test_parity_mundo_vivo_outra_seed():
    assert_parity(60, seed=123, n_companies=8, **LIVING)


def test_parity_flags_isoladas():
    assert_parity(60, seed=42, n_companies=8, market_v2=True)
    assert_parity(60, seed=42, n_companies=8, country_v2=True)
    assert_parity(60, seed=42, n_companies=8, equip_v2=True)


def test_parity_force_events():
    assert_parity(48, seed=42, n_companies=8, country_params=FORCE,
                  **LIVING)


@pytest.mark.parametrize("flags", [{}, LIVING], ids=["classico", "vivo"])
def test_restore_cruzado(flags):
    """state_dict atravessa os backends nos dois sentidos e a corrida
    restaurada é idêntica à contínua (30 ticks + restore + 30)."""
    ref_py = Engine(seed=42, n_companies=8, **flags)
    _steps(ref_py, 60)
    ref_nat = NativeEngine(seed=42, n_companies=8, **flags)
    _steps(ref_nat, 60)

    a = Engine(seed=42, n_companies=8, **flags)
    _steps(a, 30)
    b = NativeEngine.from_state(a.state_dict())
    _steps(b, 30)
    assert _hash(b.state_dict()) == _hash(ref_py.state_dict())

    c = NativeEngine(seed=42, n_companies=8, **flags)
    _steps(c, 30)
    d = Engine.from_state(c.state_dict())
    _steps(d, 30)
    assert _hash(d.state_dict()) == _hash(ref_nat.state_dict())

    e = NativeEngine.from_state(c.state_dict())
    _steps(e, 30)
    assert _hash(e.state_dict()) == _hash(ref_nat.state_dict())


def test_politica_customizada_recusada():
    from mundo.engine import Policy

    class Noop(Policy):
        def decide(self, engine, comp):
            pass

    with pytest.raises(ValueError):
        NativeEngine(seed=42, n_companies=8, policy=Noop())
