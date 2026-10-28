"""Testes da sonda pré-voo da forja (correção pós-V8, issue #6).

A Version 8 morreu de fome: NVIDIA 404 nas 300 chamadas (o ID
primário não era servido no NIM hospedado),
Gemini 429 o resto do dia e Groq sem salvar nenhuma mutação — e a
corrida só descobriu isso iteração a iteração, com backoff. A sonda
prova as rotas ANTES da corrida, com 1 chamada pequena por rota:
nenhuma mutação, nenhum torneio, nenhum seed tocado. Tudo mockado,
sem chave real e sem rede.
"""
from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEED = (ROOT / "forge" / "seed_policy.py").read_text(encoding="utf-8")

SEARCH_LINE = '        desired_mines = 1 + int(t["aggression"] ' \
              '* self.p["mines_coef"])'
REPLACE_LINE = '        desired_mines = 2 + int(t["aggression"] ' \
               '* self.p["mines_coef"])'

PRIMARY = "deepseek-ai/deepseek-v4-flash"
FALLBACK = "openai/gpt-oss-120b"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "forge" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def llm():
    return _load("forge_llm_probe", "llm_mutator.py")


@pytest.fixture(scope="module")
def run():
    return _load("forge_run_probe", "run.py")


def _body(content: str) -> str:
    return json.dumps({"choices": [{"message": {"content": content}}]})


def _diff_response(summary: str = "via fallback") -> str:
    return (f"SUMMARY: {summary}\n\n"
            f"<<<<<<< SEARCH\n{SEARCH_LINE}\n=======\n{REPLACE_LINE}\n"
            f">>>>>>> REPLACE\n")


class ModelTransport:
    """Roteia por (provedor, modelo) — o mock por URL só não basta
    para provar fallback dentro do mesmo provedor (NVIDIA), e o mock
    só por modelo confundiria o gpt-oss da NVIDIA com o da Groq."""

    def __init__(self, by_route: dict):
        self.by_route = by_route
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, payload))
        if "integrate.api.nvidia.com" in url:
            provider = "nvidia"
        elif "generativelanguage" in url:
            provider = "gemini"
        else:
            provider = "groq"
        return self.by_route.get((provider, payload["model"]),
                                 (404, "model not found"))


def _mutator(llm, transport, **keys):
    full = {"nvidia": "k-nvidia", "gemini": "k-gem", "groq": "k-groq"}
    full.update(keys)
    return llm.LLMMutator(keys=full, transport=transport)


def _v8_like_transport():
    """Reproduz a V8 em miniatura: NVIDIA primária 404, Gemini 429,
    Groq 404 — só o fallback NVIDIA responde."""
    return ModelTransport({
        ("nvidia", PRIMARY): (404, "model not found"),
        ("nvidia", FALLBACK): (200, _body("OK")),
        ("gemini", "gemini-3-flash-preview"): (429, "quota exceeded"),
        ("gemini", "gemini-3.8-flash"): (429, "quota exceeded"),
        ("groq", "openai/gpt-oss-120b"): (429, "quota exceeded"),
        ("groq", "qwen/qwen3.8-27b"): (404, "model not found"),
    })


# ------------------------------------------------------------------ #
# Cadeia NVIDIA com fallback
# ------------------------------------------------------------------ #
def test_nvidia_fallback_follows_primary_in_chain(llm):
    mut = _mutator(llm, ModelTransport({}))
    chain = mut._route_chain(random.Random(1))
    nvidia = [m for p, m in chain if p == "nvidia"]
    assert nvidia[:2] == [PRIMARY, FALLBACK]


def test_mutate_falls_through_to_nvidia_fallback_on_404(llm):
    transport = ModelTransport({
        ("nvidia", PRIMARY): (404, "model not found"),
        ("nvidia", FALLBACK): (200, _body(_diff_response())),
    })
    mut = _mutator(llm, transport)
    child, desc = mut.mutate(SEED, random.Random(1), None)
    assert REPLACE_LINE in child
    assert desc.startswith(f"llm[nvidia/{FALLBACK}]")
    models = [p["model"] for _, p in transport.calls]
    assert models[0] == PRIMARY
    assert models[1] == FALLBACK


# ------------------------------------------------------------------ #
# Sonda pré-voo
# ------------------------------------------------------------------ #
def test_probe_reports_each_route_without_raising(llm):
    transport = _v8_like_transport()
    mut = _mutator(llm, transport)
    results = mut.probe_routes()
    by_key = {(r["provider"], r["model"]): r for r in results}
    assert by_key[("nvidia", PRIMARY)]["ok"] is False
    assert "404" in by_key[("nvidia", PRIMARY)]["error"]
    assert by_key[("nvidia", FALLBACK)]["ok"] is True
    assert by_key[("gemini", "gemini-3-flash-preview")]["ok"] is False
    assert by_key[("groq", "openai/gpt-oss-120b")]["ok"] is False
    assert by_key[("groq", "qwen/qwen3.8-27b")]["ok"] is False


def test_probe_uses_tiny_payload_and_no_mutation_stats(llm):
    transport = _v8_like_transport()
    mut = _mutator(llm, transport)
    mut.probe_routes()
    assert transport.calls, "a sonda precisa chamar as rotas"
    assert all(p["max_tokens"] == 32 for _, p in transport.calls)
    assert mut.stats["calls"] == {}, \
        "sonda não conta como chamada de mutação"


def test_probe_gate_and_report(llm):
    ok = {"provider": "nvidia", "model": FALLBACK, "ok": True,
          "error": ""}
    bad = {"provider": "nvidia", "model": PRIMARY, "ok": False,
           "error": "nvidia/qwen 404"}
    assert llm.probe_gate([bad]) is False
    assert llm.probe_gate([]) is False
    assert llm.probe_gate([bad, ok]) is True
    report = llm.format_probe_report([bad, ok])
    assert "OK nvidia/openai/gpt-oss-120b" in report
    assert "FAIL nvidia/deepseek-ai/deepseek-v4-flash" in report


# ------------------------------------------------------------------ #
# Modo --probe-only do driver
# ------------------------------------------------------------------ #
def test_run_probe_only_passes_with_one_live_route(run, monkeypatch,
                                                   capsys):
    class FakeMutator:
        def probe_routes(self):
            return [{"provider": "nvidia", "model": FALLBACK, "ok": True,
                     "error": ""},
                    {"provider": "nvidia", "model": PRIMARY, "ok": False,
                     "error": "HTTP 404"}]

    monkeypatch.setattr(run, "build_mutator",
                        lambda kind: FakeMutator())
    rc = run.main(["run.py", "--probe-only"])
    assert rc == 0
    assert "FORGE-PROBE: PASS" in capsys.readouterr().out


def test_run_probe_only_fails_with_no_live_route(run, monkeypatch,
                                                 capsys):
    class FakeMutator:
        def probe_routes(self):
            return [{"provider": "nvidia", "model": PRIMARY, "ok": False,
                     "error": "HTTP 404"}]

    monkeypatch.setattr(run, "build_mutator",
                        lambda kind: FakeMutator())
    rc = run.main(["run.py", "--probe-only"])
    assert rc == 2
    assert "FORGE-PROBE: FAIL" in capsys.readouterr().out


def test_run_probe_only_blocked_without_keys(run, monkeypatch, capsys):
    class NoKeysError(RuntimeError):
        pass

    def _raise(kind):
        raise NoKeysError("sem chaves")

    monkeypatch.setattr(run, "build_mutator", _raise)
    rc = run.main(["run.py", "--probe-only"])
    assert rc == 3
    assert "BLOQUEADO" in capsys.readouterr().out


def test_run_probe_only_rejects_programmatic_mutator(run, monkeypatch,
                                                     capsys):
    def _must_not_run(kind):
        raise AssertionError("probe-only não constrói mutador "
                             "programático")

    monkeypatch.setattr(run, "build_mutator", _must_not_run)
    rc = run.main(["run.py", "--probe-only", "--mutator",
                   "programmatic"])
    assert rc == 2
    assert "FORGE-PROBE: FAIL" in capsys.readouterr().out
