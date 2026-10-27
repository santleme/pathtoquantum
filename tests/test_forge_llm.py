"""Testes do mutador LLM da forja (sub-issue #6) — transporte MOCK.

Nenhuma chave real, nenhuma rede: o transporte falso devolve
respostas no formato OpenAI e os testes provam o contrato do
adaptador — diff SEARCH/REPLACE aplicado, reescrita cercada como
fallback, enforce do EVOLVE-BLOCK, fallback Gemini->Groq em erro,
lixo virando MutationError limpa e o prompt carregando o feedback.
"""
from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest

from mundo.program import program_hash, validate_program

ROOT = Path(__file__).resolve().parents[1]
SEED = (ROOT / "forge" / "seed_policy.py").read_text(encoding="utf-8")

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
def llm():
    return _load("forge_llm_mutator", "llm_mutator.py")


def _body(content: str) -> str:
    return json.dumps({"choices": [{"message": {"content": content}}]})


def _diff_response(summary: str = "open a second mine slot earlier") -> str:
    return (f"SUMMARY: {summary}\n\n"
            f"<<<<<<< SEARCH\n{SEARCH_LINE}\n=======\n{REPLACE_LINE}\n"
            f">>>>>>> REPLACE\n")


class MockTransport:
    """Roteia por provedor (URL) e registra as chamadas."""

    def __init__(self, gemini=None, groq=None):
        self.gemini = gemini or (200, _body(_diff_response()))
        self.groq = groq or (200, _body(_diff_response("via groq")))
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, payload))
        if "generativelanguage" in url:
            return self.gemini
        return self.groq


def _mutator(llm, transport, gemini="k-gem", groq="k-groq"):
    return llm.LLMMutator(keys={"gemini": gemini, "groq": groq},
                          transport=transport)


# ------------------------------------------------------------------ #
def test_diff_applied_and_guard_clean(llm):
    mut = _mutator(llm, MockTransport())
    # Random(0): 1º draw 0,844 -> modelo de volume (flash-lite)
    child, desc = mut.mutate(SEED, random.Random(0),
                             {"parent_hash": "abc",
                              "parent_metrics": {"S1": 0.5, "S2": 0.49}})
    assert REPLACE_LINE in child
    assert SEARCH_LINE not in child
    assert validate_program(child) == []
    assert program_hash(child) != program_hash(SEED)
    assert desc.startswith("llm[gemini/gemini-3-flash-preview] diff")
    assert "second mine" in desc


def test_rewrite_fallback(llm):
    rewritten = SEED.replace(SEARCH_LINE, REPLACE_LINE)
    transport = MockTransport(
        gemini=(200, _body(f"Aqui está:\n```python\n{rewritten}\n```")))
    mut = _mutator(llm, transport)
    child, desc = mut.mutate(SEED, random.Random(1), None)
    assert REPLACE_LINE in child
    assert "rewrite" in desc


def test_outside_block_edits_reverted(llm):
    outside = ("<<<<<<< SEARCH\nfrom mundo import chain\n=======\n"
               "from mundo import chain  # mexido fora do bloco\n"
               ">>>>>>> REPLACE\n")
    inside = (f"<<<<<<< SEARCH\n{SEARCH_LINE}\n=======\n{REPLACE_LINE}\n"
              ">>>>>>> REPLACE\n")
    transport = MockTransport(
        gemini=(200, _body("SUMMARY: dois blocos\n\n" + outside + "\n"
                           + inside)))
    mut = _mutator(llm, transport)
    child, desc = mut.mutate(SEED, random.Random(1), None)
    assert REPLACE_LINE in child                     # dentro: ficou
    assert "mexido fora do bloco" not in child       # fora: revertido
    assert "revertidas" in desc


def test_garbage_is_clean_mutation_error(llm):
    transport = MockTransport(
        gemini=(200, _body("não consigo ajudar com isso")),
        groq=(200, _body("também não")))
    mut = _mutator(llm, transport)
    with pytest.raises(llm.MutationError):
        mut.mutate(SEED, random.Random(1), None)
    assert mut.stats["failures"] == 1
    assert mut.stats["fallbacks"] >= 1     # tentou a cadeia inteira


def test_gemini_429_falls_back_to_groq(llm):
    transport = MockTransport(gemini=(429, "rate limited"))
    mut = _mutator(llm, transport)
    child, desc = mut.mutate(SEED, random.Random(1), None)
    assert REPLACE_LINE in child
    assert desc.startswith("llm[groq/openai/gpt-oss-120b]")
    assert mut.stats["fallbacks"] >= 1
    providers = {("gemini" if "generativelanguage" in u else "groq")
                 for u, _ in transport.calls}
    assert providers == {"gemini", "groq"}


def test_no_keys_raises(llm, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(llm.NoKeysError):
        llm.LLMMutator(keys={"gemini": None, "groq": None})


def test_prompt_carries_feedback(llm):
    seen: dict = {}

    def transport(url, headers, payload, timeout):
        seen.update(payload)
        return 200, _body(_diff_response())

    mut = _mutator(llm, transport)
    feedback = {
        "parent_hash": "cafe",
        "parent_metrics": {"S1": 0.51, "S2": 0.5, "stage_mean": 2.0,
                           "facilities_mean": 5.0},
        "artifacts": {"block_summary": "seed 1101 campo F0: S=0.400",
                      "chronicle_highlights": "[t30] mina aberta"},
        "inspirations": [{"hash": "bebe", "S1": 0.55, "source": SEED}],
        "best_S1": 0.55,
    }
    mut.mutate(SEED, random.Random(1), feedback)
    messages = seen["messages"]
    assert messages[0]["content"] == llm.SYSTEM_MESSAGE
    user = messages[1]["content"]
    assert "PARENT PERFORMANCE" in user
    assert "S=0.400" in user                 # artefato do avaliador
    assert "mina aberta" in user             # Crônica
    assert "INSPIRATION" in user
    assert "EvolvedPolicy" in user          # o fonte do pai
    assert seen["model"] in ("gemini-3-flash-preview", "gemini-3.5-flash")


def test_groq_only_route(llm):
    transport = MockTransport()
    mut = _mutator(llm, transport, gemini=None)
    child, desc = mut.mutate(SEED, random.Random(1), None)
    assert desc.startswith("llm[groq/")
    assert all("groq" in u for u, _ in transport.calls)
