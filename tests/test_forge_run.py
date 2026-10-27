"""Testes do driver da corrida forge-v1 (sub-issue #6).

Estruturais e baratos (VM): as barras do veredito, o relatório de
diffs da linhagem e uma mini-corrida ponta a ponta com o mutador
programático — incluindo a avaliação cega em blocos tiny FORA das
seeds de teste (a abertura de verdade, 9901–9932 com final=True,
é só do Kaggle). O LLM é testado à parte, mockado
(tests/test_forge_llm.py).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mundo import tournament as T
from mundo.program import program_hash, validate_program

ROOT = Path(__file__).resolve().parents[1]
SEED = (ROOT / "forge" / "seed_policy.py").read_text(encoding="utf-8")

TINY_BLOCKS = [(777001, "F0", False), (777002, "F2", True)]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "forge" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run():
    return _load("forge_run", "run.py")


# ------------------------------------------------------------------ #
# Barras do veredito (pré-registradas em docs/FORGE-V1-LOG.md)
# ------------------------------------------------------------------ #
def test_verdict_bars(run):
    v = run.forge_verdict
    assert v(0.09, 0.01, 0.02, 0.03, 0.10) == "PROVA"
    assert v(0.075, 0.034, 0.05, 0.05, 0.20) == "INCONCLUSIVO"  # torneio
    assert v(0.09, -0.01, 0.02, 0.03, 0.10) == "INCONCLUSIVO"   # IC toca 0
    assert v(0.09, 0.01, -0.02, 0.03, 0.10) == "INCONCLUSIVO"   # F2 colapsa
    assert v(0.02, 0.01, 0.02, 0.03, 0.10) == "INCONCLUSIVO"
    assert v(0.0, -0.05, 0.0, 0.0, 0.05) == "REPROVADO/AJUSTAR"
    assert v(-0.03, -0.08, -0.01, -0.01, -0.02) == "REPROVADO/AJUSTAR"


# ------------------------------------------------------------------ #
# Top diffs da linhagem
# ------------------------------------------------------------------ #
def test_top_diffs_picks_biggest_gains(run):
    src_a = SEED.replace("desej", "desej")  # semente intacta
    child = SEED.replace("desired_mines = 1 +", "desired_mines = 2 +")
    grandchild = child.replace("desired_mines = 2 +",
                               "desired_mines = 3 +")
    hs, ha, hb = (program_hash(s) for s in (src_a, child, grandchild))
    archive = {
        hs: {"hash": hs, "parent": None, "iteration": 0,
             "mutation": "semente", "S1": 0.40},
        ha: {"hash": ha, "parent": hs, "iteration": 1,
             "mutation": "sobe minas", "S1": 0.55},
        hb: {"hash": hb, "parent": ha, "iteration": 2,
             "mutation": "sobe minas de novo", "S1": 0.57},
    }
    sources = {hs: src_a, ha: child, hb: grandchild}
    steps = run.top_diffs(archive, hb, sources)
    assert [s["hash"] for s in steps] == [ha, hb]     # maior ganho 1º
    assert steps[0]["delta_S1"] == pytest.approx(0.15)
    assert "desired_mines = 2" in steps[0]["diff"]


# ------------------------------------------------------------------ #
# A trava das seeds de teste no caminho do override
# ------------------------------------------------------------------ #
def test_blind_override_refuses_test_seeds(run, tmp_path):
    with pytest.raises(T.TestSeedLock):
        run.run_blind_evaluation(
            tmp_path, tmp_path, "x", "y",
            [(9901, "F0", False)], processes=1, log=lambda *a: None)


# ------------------------------------------------------------------ #
# Mini-corrida ponta a ponta (mutador programático, estágios tiny)
# ------------------------------------------------------------------ #
def test_mini_run_end_to_end_with_blind_evaluation(run, tmp_path,
                                                   monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    monkeypatch.setenv("FORGE_STAGE2_EPISODES", "4")
    out_dir = tmp_path / "forge-v1"
    lines: list[str] = []
    summary = run.run_forge(iterations=2, seed=7, out_dir=out_dir,
                            mutator_kind="programmatic", final=True,
                            test_blocks_override=TINY_BLOCKS,
                            final_processes=1, log=lines.append)
    assert summary["ok"] is True
    assert summary["iterations_completed"] == 2
    assert len(summary["records"]) == 3          # semente + 2
    assert summary["seed_result"]["S1"] is not None
    assert summary["champion_hash"]
    # avaliação cega rodou nos blocos tiny, contra os DOIS baselines
    fe = summary["final_evaluation"]
    assert fe["n_blocks"] == 2
    assert fe["tournament_champion"] == "evo:6a94b587701d"
    for key in ("delta_vs_tournament", "delta_vs_seed",
                "delta_vs_tournament_F2", "delta_vs_tournament_shocks"):
        assert fe[key]["n_blocks"] >= 1
        assert len(fe[key]["ci95"]) == 2
    assert summary["verdict"] in ("FORGE-V1: PROVA",
                                  "FORGE-V1: INCONCLUSIVO",
                                  "FORGE-V1: REPROVADO/AJUSTAR")
    # as seeds de teste de verdade nunca foram tocadas: o avaliador
    # do loop trava isso (assert_not_test_seeds) e a avaliação cega
    # rodou SÓ nos blocos do override (n_blocks == 2, acima)
    for rec in summary["records"][1:]:
        assert rec["status"] in {"accepted", "rejected_guard",
                                 "rejected_llm", "error", "duplicate"}
    # artefatos no disco
    champ = (out_dir / "champion.py").read_text(encoding="utf-8")
    assert program_hash(champ) == summary["champion_hash"]
    assert validate_program(champ) == []
    fe_disk = json.loads((out_dir / "final_evaluation.json").read_text(
        encoding="utf-8"))
    assert fe_disk["verdict"] == fe["verdict"]
    assert (out_dir / "top5_diffs.md").exists()
    log_lines = (out_dir / "run_log.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 3
    on_disk = json.loads((out_dir / "run_summary.json").read_text(
        encoding="utf-8"))
    assert on_disk["verdict"] == summary["verdict"]
