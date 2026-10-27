"""Testes da forja (Degrau 2) — semente, guarda, spec e avaliador.

Estruturais e baratos (VM): episódios curtos/pequenos onde dá, o
protocolo completo é do Kaggle. Cobrem as issues #2, #3 e #4 do repo
(épica #1): geração 0 bit-idêntica, guarda anti-trapaça nomeando a
violação, PolicySpec program no roteador, cascata sem seed de teste.
"""
from __future__ import annotations

import importlib.util
import pickle
from pathlib import Path

import pytest

from mundo import tournament as T
from mundo.driver import EpisodeSpec, run_episode
from mundo.engine import HeuristicPolicy
from mundo.policies import PolicySpec, build_policy, build_router
from mundo.program import ProgramRejected, load_program_policy, \
    program_hash, validate_program

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "forge" / "seed_policy.py"


def _load_evaluator():
    spec = importlib.util.spec_from_file_location(
        "forge_evaluator", ROOT / "forge" / "evaluator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ #
# Semente e spec
# ------------------------------------------------------------------ #
def test_seed_passes_guard():
    assert validate_program(SEED.read_text(encoding="utf-8")) == []


def test_seed_loads_as_policy():
    policy = load_program_policy(SEED)
    assert isinstance(policy, HeuristicPolicy)
    assert policy.pid == f"prog:{policy.program_hash}"
    assert policy.program_hash == program_hash(
        SEED.read_text(encoding="utf-8"))


def test_program_spec_roundtrip_and_hash_guard(tmp_path):
    spec = PolicySpec.program(SEED)
    assert pickle.loads(pickle.dumps(spec)) == spec
    policy = build_policy(spec)
    assert policy.program_hash == spec.program_hash
    # arquivo alterado depois da spec = identidade quebrada
    other = tmp_path / "other.py"
    other.write_text(SEED.read_text(encoding="utf-8") + "\n# x\n")
    spec2 = PolicySpec("program", program_path=str(other),
                       program_hash=spec.program_hash)
    with pytest.raises(ValueError, match="hash"):
        build_policy(spec2)


def test_seed_generation0_bit_identical():
    """Focal semente x focal v0 no MESMO mundo: episódio idêntico."""
    seed = T.TRAIN_SEEDS[0]
    base = EpisodeSpec(seed=seed, ticks=60, n_companies=4,
                       policy_specs=tuple(PolicySpec.v0()
                                          for _ in range(4)))
    forged = EpisodeSpec(seed=seed, ticks=60, n_companies=4,
                         policy_specs=(PolicySpec.program(SEED),)
                         + tuple(PolicySpec.v0() for _ in range(3)))
    a, b = run_episode(base), run_episode(forged)
    assert a["scoreboard"] == b["scoreboard"]
    assert a["chronicle"] == b["chronicle"]
    assert a["super_by_cid"] == b["super_by_cid"]


def test_router_accepts_program_focal():
    router = build_router([PolicySpec.program(SEED), PolicySpec.v0()])
    assert router._for(type("C", (), {"cid": 0})()).pid.startswith("prog:")


# ------------------------------------------------------------------ #
# Guarda anti-trapaça: uma violação por regra
# ------------------------------------------------------------------ #
CHEATS = {
    "import fora da allowlist": "import os\n",
    "import fora da allowlist: subprocess":
        "from subprocess import run\n",
    "chamada proibida: eval": "x = eval('1')\n",
    "chamada proibida: open": "x = open('f')\n",
    "chamada proibida: getattr": "x = getattr(a, 'b')\n",
    "atributo proibido: .rng": "def f(engine):\n    return engine.rng\n",
    "atributo proibido: .companies":
        "def f(engine):\n    return engine.companies\n",
    "atribuição direta em engine":
        "def f(engine):\n    engine.tick = 3\n",
    "atribuição direta em comp":
        "def f(comp):\n    comp.cash = 10\n",
    "atributo dunder proibido": "x = a.__class__\n",
}


@pytest.mark.parametrize("needle,code", list(CHEATS.items()),
                         ids=list(CHEATS))
def test_guard_rejects_cheats(needle, code):
    violations = validate_program(code)
    assert any(needle in v for v in violations), violations


def test_guard_rejects_at_load(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import os\nfrom mundo.engine import HeuristicPolicy\n"
                   "class EvolvedPolicy(HeuristicPolicy):\n    pass\n")
    with pytest.raises(ProgramRejected):
        load_program_policy(bad)


def test_load_requires_evolved_policy(tmp_path):
    p = tmp_path / "p.py"
    p.write_text("x = 1\n")
    with pytest.raises(ValueError, match="EvolvedPolicy"):
        load_program_policy(p)


# ------------------------------------------------------------------ #
# Campos e avaliador
# ------------------------------------------------------------------ #
def test_field_specs_with_program_focal():
    spec = PolicySpec.program(SEED)
    specs = T.field_specs(None, "F0", focal_cid=2, block_index=0,
                          block_seed=1101, focal_spec=spec)
    assert specs[2] == spec
    assert all(s.kind == "v0" for i, s in enumerate(specs) if i != 2)


def test_evaluator_stage1_tiny(monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    ev = _load_evaluator()
    out = ev.evaluate_stage1(str(SEED))
    metrics = out["metrics"] if isinstance(out, dict) and "metrics" in out \
        else getattr(out, "metrics", out)
    assert 0.0 <= metrics["combined_score"] <= 1.0
    assert metrics["valid"] == 1.0


def test_evaluator_rejects_cheater_program(tmp_path):
    ev = _load_evaluator()
    bad = tmp_path / "cheat.py"
    bad.write_text("import os\n")
    out = ev.evaluate_stage1(str(bad))
    metrics = out["metrics"] if isinstance(out, dict) and "metrics" in out \
        else getattr(out, "metrics", out)
    assert metrics["combined_score"] == 0.0
    assert metrics["valid"] == 0.0


def test_evaluator_never_touches_test_seeds(monkeypatch):
    ev = _load_evaluator()
    blocks = [(T.TEST_SEEDS[0], "F0", False)]

    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("não deveria avaliar")

    monkeypatch.setattr(ev, "_blocks_for_stage", lambda stage: blocks)
    with pytest.raises(T.TestSeedLock):
        ev.evaluate_stage1(str(SEED))
