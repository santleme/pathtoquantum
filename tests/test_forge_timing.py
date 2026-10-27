"""Testes da instrumentação de tempo da forja (branch
forja/instrumentacao-tempo).

A instrumentação é observação pura: estes testes provam que os
campos de tempo são emitidos por iteração no run_log, que o
agregado (summarize_timings) soma/medianiza certo e que o bloco
TEMPOS sai no fim da corrida — tudo com relógio falso injetável e
transporte mockado, sem rede, sem chave e sem rodar a corrida de
verdade (só a mini-corrida estrutural de 2 iterações, como a de
tests/test_forge_run.py).
"""
from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest

from mundo import tournament as T

ROOT = Path(__file__).resolve().parents[1]
SEED = (ROOT / "forge" / "seed_policy.py").read_text(encoding="utf-8")

TINY_BLOCKS = [(777001, "F0", False), (777002, "F2", True)]
TIMING_KEYS = {"mutate_s", "stage1_s", "stage2_s", "routes_s",
               "total_s"}

SEARCH_LINE = '        desired_mines = 1 + int(t["aggression"] ' \
              '* self.p["mines_coef"])'
REPLACE_LINE = '        desired_mines = 2 + int(t["aggression"] ' \
               '* self.p["mines_coef"])'


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "forge" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run():
    return _load("forge_run_timing", "run.py")


@pytest.fixture(scope="module")
def llm():
    return _load("forge_llm_mutator_timing", "llm_mutator.py")


class FakeClock:
    """Cada chamada avança um passo fixo: durações determinísticas."""

    def __init__(self, step: float = 0.25):
        self.t = 1000.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


# ------------------------------------------------------------------ #
# Agregação pura (summarize_timings / format_timing_block)
# ------------------------------------------------------------------ #
def _rec(iteration, timing=None, status="accepted"):
    rec = {"iteration": iteration, "status": status}
    if timing is not None:
        rec["timing"] = timing
    return rec


def test_summarize_timings_aggregates(run):
    records = [
        _rec(0, {"mutate_s": 0.0, "stage1_s": 5.0, "stage2_s": 5.0,
                 "routes_s": {}, "total_s": 10.0}, status="seed"),
        _rec(1, {"mutate_s": 6.0, "stage1_s": 2.0, "stage2_s": 2.0,
                 "routes_s": {"nvidia/x": 5.0}, "total_s": 11.0}),
        _rec(2, {"mutate_s": 4.0, "stage1_s": 1.0, "stage2_s": None,
                 "routes_s": {"nvidia/x": 3.0, "gemini/y": 1.0},
                 "total_s": 7.0}),
        _rec(3, {"mutate_s": 9.0, "stage1_s": None, "stage2_s": None,
                 "routes_s": {"gemini/y": 9.0}, "total_s": 10.0},
             status="rejected_llm"),
        _rec(4),  # sem timing (registro legado): ignorado
    ]
    t = run.summarize_timings(records)
    assert t["iterations_timed"] == 3          # semente fora do loop
    assert t["total_s"] == 28.0
    assert t["mean_s"] == pytest.approx(round(28.0 / 3, 3))
    assert t["median_s"] == 10.0
    assert t["phases_s"] == {"mutate_s": 19.0, "stage1_s": 3.0,
                             "stage2_s": 2.0, "other_s": 4.0}
    assert t["phases_pct"]["mutate_s"] == pytest.approx(67.9)
    assert sum(t["phases_pct"].values()) == pytest.approx(100.0,
                                                          abs=0.2)
    assert t["dominant_phase"] == "mutação LLM"
    assert t["dominant_phase_key"] == "mutate_s"
    # rotas somadas entre iterações, ordenadas por tempo desc.
    assert t["routes_s"] == {"gemini/y": 10.0, "nvidia/x": 8.0}
    assert t["seed_total_s"] == 10.0


def test_summarize_timings_empty(run):
    t = run.summarize_timings([])
    assert t["iterations_timed"] == 0
    assert t["total_s"] == 0.0 and t["mean_s"] == 0.0
    assert t["median_s"] == 0.0 and t["seed_total_s"] is None


def test_format_timing_block(run):
    t = run.summarize_timings([
        _rec(1, {"mutate_s": 30.0, "stage1_s": 5.0, "stage2_s": 4.0,
                 "routes_s": {"nvidia/x": 28.0}, "total_s": 40.0}),
    ])
    t["blind_evaluation_s"] = 12.0
    t["run_wall_s"] = 55.0
    block = run.format_timing_block(t)
    assert "TEMPOS" in block
    assert "fase dominante: mutação LLM" in block
    assert "nvidia/x 28.0s" in block
    assert "avaliação cega: 12.0s" in block
    assert "parede total" in block


# ------------------------------------------------------------------ #
# Mini-corrida com relógio falso: campos emitidos + bloco no log
# ------------------------------------------------------------------ #
def test_mini_run_emits_timing_with_fake_clock(run, tmp_path,
                                               monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    monkeypatch.setenv("FORGE_STAGE2_EPISODES", "4")
    lines: list[str] = []
    summary = run.run_forge(iterations=2, seed=7,
                            out_dir=tmp_path / "forge-v1",
                            mutator_kind="programmatic", final=True,
                            test_blocks_override=TINY_BLOCKS,
                            final_processes=1, log=lines.append,
                            clock=FakeClock())
    assert summary["ok"] is True
    # TODO registro (semente + iterações) carrega o timing completo
    for rec in summary["records"]:
        assert TIMING_KEYS <= set(rec["timing"])
        assert rec["timing"]["total_s"] >= rec["timing"]["mutate_s"] >= 0
        assert isinstance(rec["timing"]["routes_s"], dict)
    seed_rec = summary["records"][0]
    assert seed_rec["timing"]["stage1_s"] is not None
    assert seed_rec["timing"]["stage2_s"] is not None
    for rec in summary["records"][1:]:
        if rec["status"] == "accepted":
            assert rec["timing"]["stage1_s"] is not None
    # o agregado do resumo bate com os registros do loop
    timings = summary["timings"]
    loop_total = sum(r["timing"]["total_s"]
                     for r in summary["records"][1:])
    assert timings["iterations_timed"] == 2
    assert timings["total_s"] == pytest.approx(loop_total)
    assert timings["blind_evaluation_s"] is not None
    assert timings["run_wall_s"] >= timings["total_s"]
    # o bloco TEMPOS foi impresso no log da corrida
    assert any("TEMPOS DA CORRIDA" in line for line in lines)
    assert any("fase dominante:" in line for line in lines)
    # e o run_log em disco carrega o mesmo timing
    disk = [json.loads(l) for l in
            (tmp_path / "forge-v1" / "run_log.jsonl")
            .read_text(encoding="utf-8").strip().splitlines()]
    assert len(disk) == 3
    assert all("timing" in r for r in disk)


# ------------------------------------------------------------------ #
# Tempo por rota no mutador LLM (relógio falso via llm._perf)
# ------------------------------------------------------------------ #
def _body(content: str) -> str:
    return json.dumps({"choices": [{"message": {"content": content}}]})


def _diff_response() -> str:
    return (f"SUMMARY: open a second mine slot earlier\n\n"
            f"<<<<<<< SEARCH\n{SEARCH_LINE}\n=======\n{REPLACE_LINE}\n"
            f">>>>>>> REPLACE\n")


class _FixedTransport:
    def __init__(self, result):
        self.result = result

    def __call__(self, url, headers, payload, timeout):
        return self.result


def test_route_seconds_accumulate_on_success(llm, monkeypatch):
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(llm, "_perf", lambda: next(ticks))
    mut = llm.LLMMutator(
        keys={"nvidia": "k-nv", "gemini": None, "groq": None},
        transport=_FixedTransport((200, _body(_diff_response()))))
    child, desc = mut.mutate(SEED, random.Random(0), None)
    assert REPLACE_LINE in child
    # a rota tentada (e vencedora) acumulou exatamente o relógio falso
    assert mut.stats["route_seconds"] == {
        "nvidia/qwen/qwen3-coder-480b-a35b-instruct": 2.5}


def test_route_seconds_accumulate_on_failure(llm, monkeypatch):
    ticks = iter([3.0, 4.25])
    monkeypatch.setattr(llm, "_perf", lambda: next(ticks))
    mut = llm.LLMMutator(
        keys={"nvidia": "k-nv", "gemini": None, "groq": None},
        transport=_FixedTransport((500, "boom")))
    with pytest.raises(llm.MutationError):
        mut.mutate(SEED, random.Random(0), None)
    # mesmo falhando, o tempo da rota ficou registrado (é o tempo
    # que some em retries/backoff nas corridas reais)
    assert mut.stats["route_seconds"] == {
        "nvidia/qwen/qwen3-coder-480b-a35b-instruct": 1.25}
    assert mut.stats["failures"] == 1
