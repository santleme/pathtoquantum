"""Goldens bit-idênticos (DEGRAU1-DESIGN §3.5) — o contrato de qualquer
refactor de motor: SHA-256 do ``state_dict`` completo (estado, RNG,
crônica e frames) de corridas de referência.

Hashes calculados sobre o motor pré-Degrau 1 (commit b8648d6) em
26/10/2026. Se um refactor mudar UM bit aqui, ou o refactor está
errado ou a regravação do golden precisa de commit próprio e decisão
explícita — nunca é efeito colateral silencioso.
"""
import hashlib
import json

from mundo.engine import Engine


def state_hash(seed, n, ticks, **kw):
    eng = Engine(seed=seed, n_companies=n, **kw)
    eng.run(ticks)
    blob = json.dumps(eng.state_dict(), sort_keys=True,
                      ensure_ascii=False, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def test_golden_n8_24():
    assert state_hash(42, 8, 24) == \
        "e01923e16b48cfa6f0aa934fb1a20d93ea0ac053dc9406f620fa1c900e417373"


def test_golden_n100_24():
    assert state_hash(42, 100, 24) == \
        "24b1b3bfdbdf32c3b263056c472ad855f03687d6a24e0d86f2976f0274ee2495"


def test_golden_n8_120():
    assert state_hash(42, 8, 120) == \
        "74412ded5ddd45bc43e62f9ff1643861740abfe2d072a119f9c4321e79c59a05"


def test_golden_n8_24_builtin_world():
    assert state_hash(42, 8, 24, world_data=False) == \
        "83e1fa202f18af9469d52e47bc69bd9ff2957379db78b809cedf2015c9d99baf"
