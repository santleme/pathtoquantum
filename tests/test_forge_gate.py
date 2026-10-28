"""Testes do endurecimento pós-V8 da forja (branch
forja/portao-sonda, issue #6): portão da sonda DENTRO de
run_forge, poda de rotas mortas, captura alargada por rota — e as
regressões dos dois bugs que a fumaça do bundle src15 (kernel
Version 9) expôs:

1. URL sem barra: as bases NVIDIA/Groq não terminam em "/" e o
   chat() concatenava "chat/completions" direto — TODAS as
   chamadas iam para ".../v1chat/completions" (a Groq confessou
   no próprio erro). NVIDIA+Groq inalcançáveis nas V6–V8; só o
   Gemini (base com "/") funcionava. Regressão = URL final EXATA
   dos 3 provedores travada aqui.
2. 200 ilegível do Gemini: gemini-3-flash-preview respondeu HTTP
   200 sem a chave 'content' na message (KeyError no parse).
   Regressão = parse tolerante (partes, reasoning_content) + erro
   com a forma das chaves, sem vazar conteúdo.

Tudo mockado: nenhuma chave real, nenhuma rede. As mini-corridas
usam estágios tiny fora das seeds de teste, como
tests/test_forge_run.py.
"""
from __future__ import annotations

import http.client
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

DEEPSEEK = "deepseek-ai/deepseek-v4.1-flash"
NEMOTRON = "nvidia/nemotron-3-ultra-550b-a55b"
GPT_OSS = "openai/gpt-oss-120b"
GEM_VOLUME = "gemini-3-flash-preview"
GEM_LEAP = "gemini-3.8-flash"
GROQ_QWEN = "qwen/qwen3.8-27b"

ALL_KEYS = {"nvidia": "k-nvidia", "gemini": "k-gem", "groq": "k-groq"}


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "forge" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def llm():
    return _load("forge_llm_gate", "llm_mutator.py")


@pytest.fixture(scope="module")
def run():
    return _load("forge_run_gate", "run.py")


def _body(content) -> str:
    return json.dumps({"choices": [{"message": {"content": content}}]})


def _diff_response(summary: str = "via rota viva") -> str:
    return (f"SUMMARY: {summary}\n\n"
            f"<<<<<<< SEARCH\n{SEARCH_LINE}\n=======\n{REPLACE_LINE}\n"
            f">>>>>>> REPLACE\n")


class RouteTransport:
    """Roteia por (provedor, modelo); valor Exception é levantado."""

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
        action = self.by_route[(provider, payload["model"])]
        if isinstance(action, Exception):
            raise action
        return action

    def models_called(self) -> list[str]:
        return [p["model"] for _, p in self.calls]


def _ok_routes(**overrides):
    routes = {("nvidia", DEEPSEEK): (200, _body(_diff_response())),
              ("nvidia", NEMOTRON): (200, _body(_diff_response())),
              ("gemini", GEM_VOLUME): (200, _body(_diff_response())),
              ("gemini", GEM_LEAP): (200, _body(_diff_response())),
              ("groq", GPT_OSS): (200, _body(_diff_response())),
              ("groq", GROQ_QWEN): (200, _body(_diff_response()))}
    routes.update(overrides)
    return routes


# ------------------------------------------------------------------ #
# Cadeia nova travada (pesquisa oficial de modelos, pós-V8)
# ------------------------------------------------------------------ #
def test_chain_locks_the_six_routes(llm):
    mut = llm.LLMMutator(keys=dict(ALL_KEYS),
                         transport=RouteTransport(_ok_routes()))
    chain = mut._route_chain(random.Random(0))
    assert chain[0] == ("nvidia", DEEPSEEK)      # principal NVIDIA
    assert chain[1] == ("nvidia", NEMOTRON)       # fallback NVIDIA
    assert set(chain) == {("nvidia", DEEPSEEK), ("nvidia", NEMOTRON),
                          ("gemini", GEM_VOLUME), ("gemini", GEM_LEAP),
                          ("groq", GPT_OSS), ("groq", GROQ_QWEN)}
    assert len(chain) == 6
    assert llm.NVIDIA_VOLUME_MODEL == DEEPSEEK
    assert llm.NVIDIA_FALLBACK_MODELS == (NEMOTRON,)
    assert llm.GEMINI_VOLUME_MODEL == GEM_VOLUME
    assert llm.GEMINI_LEAP_MODEL == GEM_LEAP
    assert llm.GROQ_MODELS == (GPT_OSS, GROQ_QWEN)


# ------------------------------------------------------------------ #
# Bug 1 da fumaça src15 — URL final exata por provedor
# ------------------------------------------------------------------ #
@pytest.mark.parametrize("provider,url", [
    ("nvidia", "https://integrate.api.nvidia.com/v1/chat/completions"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/"
     "openai/chat/completions"),
    ("groq", "https://api.groq.com/openai/v1/chat/completions"),
])
def test_chat_url_is_exact_per_provider(llm, provider, url):
    seen: list[str] = []

    def transport(u, headers, payload, timeout):
        seen.append(u)
        return 200, _body("OK")

    keys = {"nvidia": None, "gemini": None, "groq": None}
    keys[provider] = "k"
    mut = llm.LLMMutator(keys=keys, transport=transport)
    text = mut.clients[provider].chat("qualquer-modelo",
                                      [{"role": "user",
                                        "content": "oi"}])
    assert text == "OK"
    assert seen == [url]


# ------------------------------------------------------------------ #
# Bug 2 da fumaça src15 — parse tolerante do 200
# ------------------------------------------------------------------ #
def _gemini_client(llm, body: str):
    def transport(url, headers, payload, timeout):
        return 200, body

    mut = llm.LLMMutator(keys={"nvidia": None, "gemini": "k",
                               "groq": None}, transport=transport)
    return mut.clients["gemini"]


def test_parse_content_as_parts_list(llm):
    body = json.dumps({"choices": [{"message": {
        "role": "assistant",
        "content": [{"type": "text", "text": "O"},
                    {"type": "text", "text": "K"}]}}]})
    assert _gemini_client(llm, body).chat(GEM_VOLUME, []) == "OK"


def test_parse_missing_content_falls_back_to_reasoning(llm):
    # a forma que quebrou na fumaça: message SEM a chave 'content'
    body = json.dumps({"choices": [{"message": {
        "role": "assistant", "reasoning_content": "OK"}}]})
    assert _gemini_client(llm, body).chat(GEM_VOLUME, []) == "OK"


def test_parse_null_content_falls_back_to_reasoning(llm):
    body = json.dumps({"choices": [{"message": {
        "role": "assistant", "content": None,
        "reasoning_content": "OK"}}]})
    assert _gemini_client(llm, body).chat(GEM_VOLUME, []) == "OK"


def test_parse_failure_reports_shape_without_leaking(llm):
    body = json.dumps({"choices": [{"message": {
        "role": "assistant", "content": None,
        "debug_payload": "SEGREDO-QUE-NAO-VAZA"}}]})
    with pytest.raises(llm.MutationError) as ei:
        _gemini_client(llm, body).chat(GEM_VOLUME, [])
    msg = str(ei.value)
    assert "message_keys=" in msg and "content" in msg
    assert "content_type=NoneType" in msg
    assert "SEGREDO-QUE-NAO-VAZA" not in msg


# ------------------------------------------------------------------ #
# race_gate — o critério forte do portão da corrida
# ------------------------------------------------------------------ #
def _res(provider, model, ok, error=""):
    return {"provider": provider, "model": model, "ok": ok,
            "error": error}


def test_race_gate_passes_on_foundation(llm):
    results = [_res("nvidia", DEEPSEEK, False, "HTTP 404"),
               _res("nvidia", NEMOTRON, True),
               _res("gemini", GEM_VOLUME, True),
               _res("gemini", GEM_LEAP, False, "HTTP 429"),
               _res("groq", GPT_OSS, False, "HTTP 404"),
               _res("groq", GROQ_QWEN, False, "HTTP 404")]
    passed, reasons = llm.race_gate(results)
    assert passed is True
    assert reasons == []


def test_race_gate_groq_does_not_count_as_foundation(llm):
    results = [_res("nvidia", NEMOTRON, True),
               _res("gemini", GEM_VOLUME, False, "HTTP 429"),
               _res("gemini", GEM_LEAP, False, "HTTP 429"),
               _res("groq", GPT_OSS, True),
               _res("groq", GROQ_QWEN, True)]
    passed, reasons = llm.race_gate(results)
    assert passed is False
    assert any("Gemini" in r for r in reasons)


def test_race_gate_requires_the_fallback_route_specifically(llm):
    # primário NVIDIA vivo NÃO basta: a fundação é o fallback
    results = [_res("nvidia", DEEPSEEK, True),
               _res("nvidia", NEMOTRON, False, "HTTP 404"),
               _res("gemini", GEM_VOLUME, True)]
    passed, reasons = llm.race_gate(results)
    assert passed is False
    assert any(NEMOTRON in r for r in reasons)


def test_race_gate_blocks_with_named_reasons_when_all_dead(llm):
    results = [_res("nvidia", NEMOTRON, False, "HTTP 404"),
               _res("gemini", GEM_VOLUME, False, "HTTP 429")]
    passed, reasons = llm.race_gate(results)
    assert passed is False
    assert len(reasons) == 2


# ------------------------------------------------------------------ #
# Poda de rotas mortas
# ------------------------------------------------------------------ #
def test_prune_removes_dead_routes_from_chain(llm):
    mut = llm.LLMMutator(keys=dict(ALL_KEYS),
                         transport=RouteTransport(_ok_routes()))
    results = [_res("nvidia", DEEPSEEK, True),
               _res("nvidia", NEMOTRON, True),
               _res("gemini", GEM_VOLUME, False, "HTTP 429"),
               _res("gemini", GEM_LEAP, True),
               _res("groq", GPT_OSS, True),
               _res("groq", GROQ_QWEN, True)]
    pruned = mut.prune_dead_routes(results)
    assert [(p["provider"], p["model"]) for p in pruned] == [
        ("gemini", GEM_VOLUME)]
    assert pruned[0]["error"] == "HTTP 429"
    assert mut.pruned_routes == pruned
    for seed in range(20):   # qualquer sorteio volume/salto
        chain = mut._route_chain(random.Random(seed))
        assert ("gemini", GEM_VOLUME) not in chain
        assert ("gemini", GEM_LEAP) in chain
        assert len(chain) == 5


def test_mutate_never_calls_a_pruned_route(llm):
    transport = RouteTransport(_ok_routes())
    mut = llm.LLMMutator(keys={"nvidia": None, "gemini": "k",
                               "groq": None}, transport=transport)
    mut.prune_dead_routes(
        [_res("gemini", GEM_VOLUME, False, "HTTP 429"),
         _res("gemini", GEM_LEAP, True)])
    child, desc = mut.mutate(SEED, random.Random(1), None)
    assert REPLACE_LINE in child
    assert desc.startswith(f"llm[gemini/{GEM_LEAP}]")
    assert GEM_VOLUME not in transport.models_called()


# ------------------------------------------------------------------ #
# Captura alargada por rota (o vazamento da V8)
# ------------------------------------------------------------------ #
def test_weird_transport_exception_is_route_failure_not_escape(llm):
    routes = _ok_routes()
    routes[("nvidia", DEEPSEEK)] = http.client.BadStatusLine("bogus")
    transport = RouteTransport(routes)
    mut = llm.LLMMutator(keys=dict(ALL_KEYS), transport=transport)
    child, desc = mut.mutate(SEED, random.Random(1), None)
    assert REPLACE_LINE in child
    assert desc.startswith(f"llm[nvidia/{NEMOTRON}]")
    assert mut.stats["failures"] == 0   # a iteração NÃO virou error


def test_all_routes_weird_exceptions_consolidate(llm):
    boom = http.client.BadStatusLine("bogus")
    transport = RouteTransport(
        {route: boom for route in _ok_routes()})
    mut = llm.LLMMutator(keys=dict(ALL_KEYS), transport=transport)
    with pytest.raises(llm.MutationError) as ei:
        mut.mutate(SEED, random.Random(1), None)
    assert "todas as rotas falharam" in str(ei.value)
    assert "BadStatusLine" in str(ei.value)
    assert mut.stats["failures"] == 1


# ------------------------------------------------------------------ #
# O portão dentro de run_forge
# ------------------------------------------------------------------ #
_PASS_RESULTS = [
    _res("nvidia", DEEPSEEK, False, "HTTP 404"),
    _res("nvidia", NEMOTRON, True),
    _res("gemini", GEM_VOLUME, True),
    _res("gemini", GEM_LEAP, False, "HTTP 429"),
    _res("groq", GPT_OSS, False, "HTTP 404"),
    _res("groq", GROQ_QWEN, False, "HTTP 404"),
]
_BLOCKED_RESULTS = [
    _res("nvidia", DEEPSEEK, False, "HTTP 404"),
    _res("nvidia", NEMOTRON, False, "HTTP 404"),
    _res("gemini", GEM_VOLUME, True),
    _res("gemini", GEM_LEAP, False, "HTTP 429"),
    _res("groq", GPT_OSS, False, "HTTP 404"),
    _res("groq", GROQ_QWEN, False, "HTTP 404"),
]
_CHILD = SEED.replace("desired_mines = 1 +", "desired_mines = 2 +", 1)


class FakeLLMMutator:
    """Mutador LLM falso com sonda roteirizada (sem rede)."""

    def __init__(self, probe_results):
        self._probe_results = probe_results
        self.probe_calls = 0
        self.mutate_calls = 0
        self.stats = {"calls": {}, "fallbacks": 0, "failures": 0,
                      "route_seconds": {}}

    def probe_routes(self):
        self.probe_calls += 1
        return self._probe_results

    def prune_dead_routes(self, results):
        return [{"provider": r["provider"], "model": r["model"],
                 "error": r.get("error", "")}
                for r in results if not r.get("ok")]

    def mutate(self, source, rng, feedback=None):
        self.mutate_calls += 1
        return _CHILD, "fake llm"


def test_gate_blocks_by_default_and_consumes_nothing(run, tmp_path):
    fake = FakeLLMMutator(_BLOCKED_RESULTS)
    lines: list[str] = []
    out_dir = tmp_path / "forge-v1"
    summary = run.run_forge(iterations=3, seed=7, out_dir=out_dir,
                            mutator=fake, final=False,
                            log=lines.append)
    assert summary["ok"] is False
    assert "FORGE-GATE: BLOCKED" in summary["fatal"]
    assert any("FORGE-GATE: BLOCKED" in line for line in lines)
    assert fake.probe_calls == 1          # sondou uma vez
    assert fake.mutate_calls == 0         # nenhuma mutação tentada
    assert "records" not in summary       # nenhuma iteração rodou
    log_lines = (out_dir / "run_log.jsonl").read_text(
        encoding="utf-8").strip()
    assert log_lines == ""                # run_log vazio: nem a
    # iteração 0 (semente avaliada) foi consumida
    gate = summary["probe_gate"]
    assert gate["passed"] is False
    assert gate["blocked_reasons"]
    on_disk = json.loads((out_dir / "run_summary.json").read_text(
        encoding="utf-8"))
    assert on_disk["probe_gate"]["passed"] is False


def test_gate_passes_prunes_and_runs(run, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    monkeypatch.setenv("FORGE_STAGE2_EPISODES", "4")
    fake = FakeLLMMutator(_PASS_RESULTS)
    lines: list[str] = []
    summary = run.run_forge(iterations=1, seed=7,
                            out_dir=tmp_path / "forge-v1",
                            mutator=fake, final=False,
                            log=lines.append)
    assert summary["ok"] is True
    assert summary["iterations_completed"] == 1
    assert len(summary["records"]) == 2        # semente + 1 iteração
    gate = summary["probe_gate"]
    assert gate["passed"] is True
    assert {(p["provider"], p["model"])
            for p in gate["pruned_routes"]} == {
        ("nvidia", DEEPSEEK), ("gemini", GEM_LEAP),
        ("groq", GPT_OSS), ("groq", GROQ_QWEN)}
    assert any("FORGE-GATE: PASS" in line for line in lines)
    assert any("podadas" in line for line in lines)


def test_gate_disabled_never_probes(run, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STAGE1_EPISODES", "2")
    monkeypatch.setenv("FORGE_STAGE2_EPISODES", "4")
    fake = FakeLLMMutator(_BLOCKED_RESULTS)   # bloquearia, se sondasse
    summary = run.run_forge(iterations=1, seed=7,
                            out_dir=tmp_path / "forge-v1",
                            mutator=fake, final=False,
                            probe_gate=False, log=lambda *a: None)
    assert fake.probe_calls == 0
    assert summary["ok"] is True
    assert summary["probe_gate"]["enabled"] is False
    assert summary["probe_gate"]["passed"] is None


def test_cli_no_probe_gate_flag_wires_through(run, monkeypatch):
    captured: dict = {}

    def fake_run_forge(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(run, "run_forge", fake_run_forge)
    assert run.main(["run.py", "--mutator", "programmatic",
                     "--no-final"]) == 0
    assert captured["probe_gate"] is True    # default = LIGADO
    captured.clear()
    assert run.main(["run.py", "--mutator", "programmatic",
                     "--no-final", "--no-probe-gate"]) == 0
    assert captured["probe_gate"] is False
