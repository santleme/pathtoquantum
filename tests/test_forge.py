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
from mundo.policies import PolicySpec, build_policy
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
    # hash é invariante do build, não cortesia da fábrica
    spec3 = PolicySpec("program", program_path=str(SEED),
                       program_hash=None)
    with pytest.raises(ValueError, match="sem hash"):
        build_policy(spec3)


def test_seed_generation0_bit_identical():
    """Focal semente x focal v0 no MESMO mundo: episódio idêntico.

    No padrão da prova do genoma 0: 3 seeds, protocolo cheio
    (120 ticks, 8 empresas), episódio inteiro comparado.
    """
    for seed in T.TRAIN_SEEDS[:3]:
        base = EpisodeSpec(seed=seed, ticks=120, n_companies=8,
                           policy_specs=tuple(PolicySpec.v0()
                                              for _ in range(8)))
        forged = EpisodeSpec(
            seed=seed, ticks=120, n_companies=8,
            policy_specs=(PolicySpec.program(SEED),)
            + tuple(PolicySpec.v0() for _ in range(7)))
        a, b = run_episode(base), run_episode(forged)
        assert a["scoreboard"] == b["scoreboard"]
        assert a["chronicle"] == b["chronicle"]
        assert a["super_by_cid"] == b["super_by_cid"]


# ------------------------------------------------------------------ #
# Guarda anti-trapaça: uma violação por regra
# ------------------------------------------------------------------ #
CHEATS = [
    ("import os", "import fora da allowlist: os", "import os\n"),
    ("from subprocess", "import fora da allowlist: subprocess",
     "from subprocess import run\n"),
    ("from mundo import tournament", "mundo.tournament",
     "from mundo import tournament\n"),
    ("import mundo.driver", "mundo.driver", "import mundo.driver\n"),
    ("from mundo.program", "mundo.program",
     "from mundo.program import load_program_policy\n"),
    ("eval", "chamada proibida: eval", "x = eval('1')\n"),
    ("open", "chamada proibida: open", "x = open('f')\n"),
    ("getattr", "chamada proibida: getattr", "x = getattr(a, 'b')\n"),
    (".rng", "atributo proibido: .rng",
     "def f(engine):\n    return engine.rng\n"),
    (".companies", "atributo proibido: .companies",
     "def f(engine):\n    return engine.companies\n"),
    ("engine.tick direto", "engine.tick",
     "def f(engine):\n    engine.tick = 3\n"),
    ("comp.cash direto", "comp.cash",
     "def f(comp):\n    comp.cash = 10\n"),
    ("alias de comp", "c.cash",
     "def f(comp):\n    c = comp\n    c.cash = 10\n"),
    ("alias de engine", "e.tick",
     "def f(engine):\n    e = engine\n    e.tick = 0\n"),
    ("atributo em objeto obtido", "t.grade",
     "def f(self):\n    t = self.pick_deposit(None, None)\n"
     "    t.grade = 1.0\n"),
    ("subscrito em comp.stocks", "comp.stocks",
     "def f(comp):\n    comp.stocks['device'] = 5\n"),
    ("subscrito em engine.prices", "engine.prices",
     "def f(engine):\n    engine.prices['copper'] = 1\n"),
    ("del comp.cash", "deleção em atributo proibida: comp.cash",
     "def f(comp):\n    del comp.cash\n"),
    ("for comp.cash", "comp.cash",
     "for comp.cash in [1]:\n    pass\n"),
    ("dunder", "atributo dunder proibido", "x = a.__class__\n"),
]


@pytest.mark.parametrize("needle,code",
                         [(n, c) for _, n, c in CHEATS],
                         ids=[i for i, _, _ in CHEATS])
def test_guard_rejects_cheats(needle, code):
    violations = validate_program(code)
    assert any(needle in v for v in violations), violations


def test_guard_allows_legal_channels():
    # Fatia 4: os subscritos comp._offers/_buys/knowledge e
    # engine.claimed_by saíram daqui — viraram canais aposentados
    # (test_guard_rejects_retired_v1_channels). Restam legais:
    # atributo em self, comp.tools.* e subscrito em objeto próprio.
    code = (
        "from mundo.engine import HeuristicPolicy\n"
        "class EvolvedPolicy(HeuristicPolicy):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.extra = 1\n"
        "    def decide(self, engine, comp):\n"
        "        tools = comp.tools\n"
        "        tools.insta_until = 9\n"
        "        own = {}\n"
        "        own['a'] = 1\n")
    assert validate_program(code) == []


RETIRED_CHANNELS = [
    ("_offers",
     "def f(comp):\n    comp._offers['copper'] = 3\n"),
    ("_buys",
     "def f(comp):\n    comp._buys['copper'] = 1\n"),
    ("knowledge",
     "def f(comp):\n    comp.knowledge['X'] = (0.5, 10)\n"),
    ("claimed_by",
     "def f(engine, comp):\n    engine.claimed_by[(0, 0)] = comp.cid\n"),
    ("_buys",  # via apelido contaminado de comp
     "def f(comp):\n    c = comp\n    c._buys['copper'] = 1\n"),
    ("claimed_by",  # deleção também é escrita no canal
     "def f(engine):\n    del engine.claimed_by[(0, 0)]\n"),
]


@pytest.mark.parametrize("attr,code", RETIRED_CHANNELS,
                         ids=["comp._offers", "comp._buys",
                              "comp.knowledge", "engine.claimed_by",
                              "alias._buys", "del claimed_by"])
def test_guard_rejects_retired_v1_channels(attr, code):
    """Fatia 4 da guarda v2: cada canal de escrita da v1 é rejeitado
    com a mensagem que aponta o contrato atual (decide(self, obs)
    devolvendo intenções de mundo.intentions)."""
    violations = validate_program(code)
    assert any(attr in v and "canal v1 aposentado" in v
               and "mundo.intentions" in v for v in violations), \
        violations


def test_guard_rejects_retired_channel_at_load(tmp_path):
    p = tmp_path / "legacy.py"
    p.write_text(
        "from mundo.engine import HeuristicPolicy\n"
        "class EvolvedPolicy(HeuristicPolicy):\n"
        "    def decide(self, obs):\n"
        "        comp._offers['copper'] = 3\n"
        "        return []\n")
    with pytest.raises(ProgramRejected, match="canal v1 aposentado"):
        load_program_policy(p)


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
    assert "tool_rate" in metrics


def test_evaluator_seed_matches_genome0_score(monkeypatch):
    """Aceitação da issue #4: S da semente == S do genoma 0 nos blocos."""
    from mundo.genome import GENOME0
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    ev = _load_evaluator()
    out = ev.evaluate_stage1(str(SEED))
    metrics = out["metrics"] if isinstance(out, dict) and "metrics" in out \
        else getattr(out, "metrics", out)
    blocks = [(s, "F0", False) for s in T.TRAIN_SEEDS[:2]]
    rows = T.evaluate_blocks(GENOME0, blocks, processes=1)
    expected = sum(r["S"] for r in rows) / len(rows)
    assert metrics["combined_score"] == pytest.approx(expected, abs=1e-12)


def test_evaluator_broken_program_scores_zero(tmp_path):
    ev = _load_evaluator()
    bad = tmp_path / "boom.py"
    bad.write_text(
        "from mundo.engine import HeuristicPolicy\n"
        "class EvolvedPolicy(HeuristicPolicy):\n"
        "    def decide(self, engine, comp):\n"
        "        raise RuntimeError('boom deliberado')\n")
    out = ev.evaluate_stage1(str(bad))
    metrics = out["metrics"] if isinstance(out, dict) and "metrics" in out \
        else getattr(out, "metrics", out)
    assert metrics["combined_score"] == 0.0
    assert metrics["valid"] == 0.0


def test_chronicle_highlights_shape():
    ev = _load_evaluator()
    res = run_episode(EpisodeSpec(seed=T.TRAIN_SEEDS[0], ticks=60,
                                  n_companies=4))
    out = ev._chronicle_highlights([res], [0])
    assert isinstance(out, list)
    assert all(isinstance(x, str) and x.startswith("[t") for x in out)


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
