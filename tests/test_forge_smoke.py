"""Testes do smoke da forja (Degrau 2, sub-issue #5) — mutador e driver.

Estruturais e baratos (VM): o mutador programático (substituto do
LLM no smoke, decisão registrada em forge/mutator.py) precisa gerar
programas limpos para a guarda, e o driver em miniatura (2–3
iterações, estágios minúsculos via FORGE_*_EPISODES) precisa fechar
o loop ponta a ponta com o registro completo. O smoke de verdade
(30 iterações, protocolo cheio) é do Kaggle.
"""
from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest

from mundo import tournament as T
from mundo.program import load_program_policy, program_hash, \
    validate_program

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "forge" / "seed_policy.py"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "forge" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mut():
    return _load("forge_mutator", "mutator.py")


@pytest.fixture(scope="module")
def smoke():
    return _load("forge_smoke", "smoke.py")


# ------------------------------------------------------------------ #
# Mutador
# ------------------------------------------------------------------ #
def test_mutator_output_passes_guard(mut):
    source = SEED.read_text(encoding="utf-8")
    rng = random.Random(1234)
    current = source
    for _ in range(25):  # mutantes de mutantes: a linhagem inteira
        current, desc = mut.mutate(current, rng)
        assert desc
        assert validate_program(current) == []
        assert program_hash(current) != program_hash(source)


def test_mutator_deterministic(mut):
    source = SEED.read_text(encoding="utf-8")
    a, desc_a = mut.mutate(source, random.Random(7))
    b, desc_b = mut.mutate(source, random.Random(7))
    assert a == b
    assert desc_a == desc_b


def test_mutator_preserves_structure(mut):
    source = SEED.read_text(encoding="utf-8")
    out, _ = mut.mutate(source, random.Random(3))
    assert "# EVOLVE-BLOCK-START" in out
    assert "# EVOLVE-BLOCK-END" in out
    assert "class EvolvedPolicy(HeuristicPolicy):" in out
    assert "def decide(self, obs):" in out


def test_mutator_param_override_takes_effect(mut, tmp_path):
    source = SEED.read_text(encoding="utf-8")
    rng = random.Random(99)
    out = source
    for _ in range(40):
        out, desc = mut.mutate(out, rng)
        if desc.startswith("param"):
            break
    overrides = mut.current_overrides(out)
    assert overrides, "nenhum override de parâmetro gerado em 40 draws"
    p = tmp_path / "mutant.py"
    p.write_text(out, encoding="utf-8")
    policy = load_program_policy(p)
    for name, value in overrides.items():
        assert policy.p[name] == pytest.approx(value)


def test_mutator_respects_gene_bounds(mut):
    source = SEED.read_text(encoding="utf-8")
    rng = random.Random(2026)
    current = source
    for _ in range(60):
        current, _ = mut.mutate(current, rng)
        for name, value in mut.current_overrides(current).items():
            _v0, lo, hi, _step = mut.GENE_BOUNDS[name]
            assert lo <= value <= hi, (name, value)


# ------------------------------------------------------------------ #
# Driver em miniatura
# ------------------------------------------------------------------ #
def test_smoke_miniature_end_to_end(smoke, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    monkeypatch.setenv("FORGE_STAGE2_EPISODES", "4")
    out_dir = tmp_path / "smoke"
    lines: list[str] = []
    summary = smoke.run_smoke(iterations=3, seed=7, out_dir=out_dir,
                              log=lines.append)
    assert summary["ok"] is True
    assert summary["iterations_completed"] == 3
    records = summary["records"]
    assert len(records) == 4  # semente + 3 iterações
    seed_rec = records[0]
    assert seed_rec["status"] == "seed"
    # aceitação da issue #4: S da semente == S do genoma 0 nos blocos
    # (o valor absoluto muda com o mundo; a igualdade é o invariante)
    from mundo.genome import GENOME0
    blocks = [(s, "F0", False) for s in T.TRAIN_SEEDS[:2]]
    rows = T.evaluate_blocks(GENOME0, blocks, processes=1)
    expected = sum(r["S"] for r in rows) / len(rows)
    assert seed_rec["S1"] == pytest.approx(expected, abs=1e-12)
    assert seed_rec["S2"] is not None  # stage2 roda na semente
    for rec in records[1:]:
        assert rec["status"] in {"accepted", "rejected_guard",
                                 "error", "duplicate"}
        assert "best_S1" in rec and "reason" in rec
    assert summary["best_by_S1"]["S1"] >= seed_rec["S1"]
    # artefatos do smoke no disco
    log_lines = (out_dir / "smoke_log.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 4
    assert json.loads(log_lines[0])["hash"] == seed_rec["hash"]
    on_disk = json.loads((out_dir / "smoke_summary.json").read_text(
        encoding="utf-8"))
    assert on_disk["ok"] is True
    best_src = (out_dir / "best_program.py").read_text(encoding="utf-8")
    assert program_hash(best_src) == summary["best_program_hash"]
    assert validate_program(best_src) == []
