"""Mutador LLM da forja — corrida forge-v1 (Degrau 2, sub-issue #6).

O adaptador que faltava entre o desenho do OpenEvolve
(docs/DISSECACAO-OPENEVOLVE-FORJA.md) e o loop da casa (forge/run.py):
MESMA interface do mutador programático do smoke —

    mutate(parent_source, rng, feedback) -> (child_source, descrição)

— mas quem muta é um ensemble de LLMs via endpoints OpenAI-compatible:

- **Gemini (primária)**, no desenho da config validado pela pesquisa
  (docs/PESQUISA-MUTADOR-FORGE-V1.md §4), com a EMENDA DE MODELOS de
  27/10/2026: a família Gemini 2.5 retorna 404 para a chave do
  fundador (a Version 6 do kernel morreu assim: 300/300 mutações
  `rejected_llm`), então o volume (peso 0,8) é
  ``gemini-3-flash-preview`` e os saltos (peso 0,2) são
  ``gemini-3.5-flash`` — ambos com sonda HTTP 200 verificada;
- **Groq (fallback)**: se a chamada Gemini falhar (rate limit 429,
  5xx, timeout, resposta vazia/inutilizável), a mutação cai para os
  modelos coder da Groq — ``openai/gpt-oss-120b`` e, persistindo a
  falha, ``qwen/qwen3.8-27b`` (a Groq não serve mais o qwen3-32b).

Sem nenhuma chave, o ensemble é o que houver: só Groq vira rota
única; só Gemini dispensa o fallback. Sem chave nenhuma,
``NoKeysError`` — quem chama (o notebook) transforma isso no
veredito BLOQUEADO, não em crash.

CHAVES: lidas de variáveis de ambiente (``GEMINI_API_KEY`` /
``GROQ_API_KEY``) ou, no Kaggle, do UserSecretsClient — ver
``load_api_keys``. NUNCA são impressas, logadas ou embutidas em
código/notebook; os testes usam transporte MOCKADO, sem chave real.

Formato da mutação (o do OpenEvolve): blocos SEARCH/REPLACE sobre o
fonte do pai, restritos ao EVOLVE-BLOCK — ``enforce_evolve_blocks``
da config é aplicado AQUI também: edição fora do bloco é revertida
para o texto do pai, e o fato entra na descrição. Resposta sem diff
aplicável mas com um programa inteiro cercado (```python) é aceita
como reescrita (e passa pelo mesmo enforce); qualquer outra coisa é
``MutationError`` — o driver registra a rejeição e o loop segue.
"""
from __future__ import annotations

import json
import os
import random
import re
import urllib.error
import urllib.request

# --------------------------------------------------------------------- #
# Rotas e modelos (espelham forge/config.yaml + a pesquisa do mutador)
# --------------------------------------------------------------------- #
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_API_BASE = "https://api.groq.com/openai/v1"

GEMINI_VOLUME_MODEL = "gemini-3-flash-preview"   # peso 0,8 — volume (emenda 27/10: 2.5-flash-lite dá 404 p/ esta chave)
GEMINI_LEAP_MODEL = "gemini-3.5-flash"            # peso 0,2 — saltos (emenda 27/10: 2.5-pro idem; 3.1-pro-preview 429 na cota)
GEMINI_LEAP_WEIGHT = 0.2
GROQ_MODELS = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b")   # qwen3-32b não é mais servido pela Groq

TEMPERATURE = 0.7
MAX_TOKENS = 16000
TIMEOUT_S = 180
MAX_CODE_LENGTH = 40000          # forge/config.yaml: max_code_length

BLOCK_START = "# EVOLVE-BLOCK-START"
BLOCK_END = "# EVOLVE-BLOCK-END"

# Espelho de forge/config.yaml (prompt.system_message) — se o texto
# mudar lá, mude aqui: é ESTE texto que o mutador envia.
SYSTEM_MESSAGE = """You are evolving the decision policy of ONE autonomous company in a simulated world economy (Path to Quantum). The program defines EvolvedPolicy.decide(self, obs), which receives ONLY an Observation (obs.me = the company itself, obs.world = public state) and RETURNS a list of declarative intentions from mundo.intentions (Spend, Probe, RegisterClaim, BuildFacility, Narrate, NoteLink, RepairFacility, MaintainFacility, OverhaulFacility, Buy, Offer, SetTool); the engine validates and executes them in order. Decisions are planned against a Plan shadow (Plan.of(me): cash and facility kinds as they will be after the intentions declared so far). Everything else is inherited from the baseline heuristic and may be overridden inside the EVOLVE-BLOCK (reserve, pick_deposit, maintain_equipment, build_downstream, plan_buys, buffer, plan_sells, use_tools). Companies prospect and mine deposits, refine, build factories/plants/assembly up a production chain toward supercomputers, buy missing inputs, sell surplus and buy marketing tools. Fitness is the tournament index S (cash percentile 50%, chain stage 30%, supercomputers 20%) of your company invading a frozen field of rivals. LEGAL information only: what the company probed (obs.me.knowledge), its own cash/stocks/facilities/traits, and public prices via obs.world. A guard rejects programs that import outside the allowlist (mundo, math), call eval/open/getattr, touch .rng, .companies or .act (there are no verbs to execute during a decision — declare intentions instead), or assign attributes on observed objects — rejected programs score 0 and the violations come back as artifacts. Prefer strategies a human can read and name: legibility is a product requirement, not style. Read the block summary and chronicle highlights in the artifacts: they tell the story of why the parent won or lost each world."""

_DIFF_INSTRUCTIONS = """\
HOW TO MUTATE — reply in EXACTLY this shape:
1. One first line: `SUMMARY: <one short sentence naming the strategic change>`
2. Then 1 to 3 diff blocks in this format (and nothing else after):

<<<<<<< SEARCH
<exact text copied from the parent program>
=======
<the replacement text>
>>>>>>> REPLACE

Rules:
- Edit ONLY inside the EVOLVE-BLOCK (between the `# EVOLVE-BLOCK-START`
  and `# EVOLVE-BLOCK-END` markers). Text outside it is frozen and any
  change there is reverted.
- The SEARCH text must match the parent EXACTLY (whitespace included)
  and appear only once in it.
- Keep `def decide(self, obs):` and the class name `EvolvedPolicy`.
- Make ONE coherent strategic change per mutation — the kind a human
  could name ("probe earlier, claim only rich deposits", "hold a
  bigger buffer before building the plant"). Small, legible, decisive.
- Legal information only (see system message). Programs that break
  the guard score 0.
"""


class MutationError(RuntimeError):
    """A mutação não rendeu um filho utilizável (o loop registra)."""


class NoKeysError(RuntimeError):
    """Nenhuma chave de LLM disponível (Gemini nem Groq)."""


# --------------------------------------------------------------------- #
# Chaves — env ou Kaggle Secrets; valores NUNCA aparecem em saída
# --------------------------------------------------------------------- #
def load_api_keys() -> dict:
    """{'gemini': str|None, 'groq': str|None} sem vazar valor algum."""
    keys = {"gemini": os.environ.get("GEMINI_API_KEY") or None,
            "groq": os.environ.get("GROQ_API_KEY") or None}
    if keys["gemini"] and keys["groq"]:
        return keys
    try:  # no Kaggle: UserSecretsClient (fora dele, o import falha)
        from kaggle_secrets import UserSecretsClient
        client = UserSecretsClient()
        for name, label in (("gemini", "GEMINI_API_KEY"),
                            ("groq", "GROQ_API_KEY")):
            if not keys[name]:
                try:
                    keys[name] = client.get_secret(label) or None
                except Exception:
                    keys[name] = None
    except Exception:
        pass
    return keys

# --------------------------------------------------------------------- #
# Cliente HTTP OpenAI-compatible (transporte injetável p/ testes)
# --------------------------------------------------------------------- #
# A Cloudflare da Groq bloqueia a assinatura default do urllib
# (erro 1010, verificado 27/10/2026) — um User-Agent comum resolve.
_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _default_transport(url: str, headers: dict, payload: dict,
                       timeout: int):
    """POST JSON via urllib. Devolve (status, corpo_texto)."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": _USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


class LLMClient:
    """Chat completions mínimo, um provedor por instância."""

    def __init__(self, provider: str, api_key: str, transport=None):
        self.provider = provider
        self._api_key = api_key
        self.base = GEMINI_API_BASE if provider == "gemini" \
            else GROQ_API_BASE
        self.transport = transport or _default_transport

    def chat(self, model: str, messages: list[dict]) -> str:
        payload = {"model": model, "messages": messages,
                   "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
        status, body = self.transport(
            self.base + "chat/completions",
            {"Authorization": f"Bearer {self._api_key}"},
            payload, TIMEOUT_S)
        if status != 200:
            raise MutationError(
                f"{self.provider}/{model} HTTP {status}: {body[:200]}")
        try:
            data = json.loads(body)
            text = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise MutationError(
                f"{self.provider}/{model} resposta ilegível: {exc}"
            ) from exc
        if not text or not text.strip():
            raise MutationError(f"{self.provider}/{model} resposta vazia")
        return text


# --------------------------------------------------------------------- #
# Diff SEARCH/REPLACE + enforce do EVOLVE-BLOCK
# --------------------------------------------------------------------- #
_DIFF_RE = re.compile(
    r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
    re.DOTALL)


def _split_blocks(source: str):
    """(antes, bloco, depois) em torno dos marcadores, ou None."""
    i = source.find(BLOCK_START)
    j = source.find(BLOCK_END)
    if i < 0 or j < 0 or j <= i:
        return None
    line_end = source.find("\n", i)
    return source[:line_end + 1], source[line_end + 1:j], source[j:]


def _enforce_evolve_blocks(parent: str, child: str):
    """Reconstrói o filho com o fora-do-bloco DO PAI (config: enforce).

    Devolve (fonte, revertido?) — filho sem marcadores é inválido.
    """
    p = _split_blocks(parent)
    c = _split_blocks(child)
    if p is None:
        raise MutationError("programa-pai sem EVOLVE-BLOCK")
    if c is None:
        raise MutationError("filho sem marcadores EVOLVE-BLOCK")
    reverted = (c[0] != p[0]) or (c[2] != p[2])
    return p[0] + c[1] + p[2], reverted


def _apply_diffs(source: str, response: str):
    """Aplica os blocos SEARCH/REPLACE; None se nenhum bloco casa."""
    blocks = _DIFF_RE.findall(response)
    if not blocks:
        return None
    out = source
    for search, replace in blocks:
        if search not in out:
            return None
        out = out.replace(search, replace, 1)
    return out


def _extract_rewrite(response: str):
    """Programa inteiro cercado em ```python, se houver."""
    m = re.search(r"```(?:python)?\n(.*?)```", response, re.DOTALL)
    if m and BLOCK_START in m.group(1) and "EvolvedPolicy" in m.group(1):
        return m.group(1)
    return None


def build_user_prompt(parent_source: str, feedback: dict | None) -> str:
    fb = feedback or {}
    parts = []
    metrics = fb.get("parent_metrics") or {}
    if metrics:
        parts.append(
            "PARENT PERFORMANCE (tournament index S; stage1 = 8 train "
            "episodes, stage2 = 64 validation episodes):\n"
            f"- parent prog:{fb.get('parent_hash', '?')}: "
            f"S1={metrics.get('S1')} S2={metrics.get('S2')} "
            f"stage_mean={metrics.get('stage_mean')} "
            f"facilities_mean={metrics.get('facilities_mean')} "
            f"super_mean={metrics.get('super_mean')} "
            f"alive_rate={metrics.get('alive_rate')} "
            f"tool_rate={metrics.get('tool_rate')}\n"
            f"- best S1 in the run so far: {fb.get('best_S1')}")
    artifacts = fb.get("artifacts") or {}
    for key, title in (("block_summary", "BLOCK-BY-BLOCK RESULTS"),
                       ("chronicle_highlights", "CHRONICLE HIGHLIGHTS"),
                       ("guard_violations", "GUARD VIOLATIONS OF A "
                        "PREVIOUS CHILD (do not repeat)")):
        if artifacts.get(key):
            parts.append(f"{title}:\n{artifacts[key]}")
    for ins in (fb.get("inspirations") or [])[:2]:
        parts.append(
            f"INSPIRATION — another evolved program, "
            f"prog:{ins.get('hash', '?')} with S1={ins.get('S1')} "
            f"(borrow ideas, do not copy wholesale):\n"
            f"```python\n{ins.get('source', '')}\n```")
    parts.append(f"PARENT PROGRAM:\n```python\n{parent_source}\n```")
    parts.append(_DIFF_INSTRUCTIONS)
    return "\n\n".join(parts)


# --------------------------------------------------------------------- #
# O mutador
# --------------------------------------------------------------------- #
class LLMMutator:
    """Ensemble Gemini (volume/salto) com fallback Groq.

    ``keys``: {'gemini': ..., 'groq': ...} (None = provedor fora).
    ``transport``: injetável — os testes passam um mock que devolve
    respostas fixas no formato OpenAI, sem chave nem rede.
    """

    def __init__(self, keys: dict | None = None, transport=None):
        keys = keys if keys is not None else load_api_keys()
        self.clients: dict[str, LLMClient] = {}
        for provider in ("gemini", "groq"):
            if keys.get(provider):
                self.clients[provider] = LLMClient(
                    provider, keys[provider], transport=transport)
        if not self.clients:
            raise NoKeysError(
                "nenhuma chave de LLM (GEMINI_API_KEY/GROQ_API_KEY) "
                "disponível — cadastre os Secrets no Kaggle")
        self.stats = {"calls": {}, "fallbacks": 0, "failures": 0}

    # -- cadeia de rotas de uma iteração ------------------------------ #
    def _route_chain(self, rng: random.Random) -> list[tuple[str, str]]:
        chain: list[tuple[str, str]] = []
        if "gemini" in self.clients:
            leap = rng.random() < GEMINI_LEAP_WEIGHT
            primary = GEMINI_LEAP_MODEL if leap else GEMINI_VOLUME_MODEL
            other = GEMINI_VOLUME_MODEL if leap else GEMINI_LEAP_MODEL
            chain += [("gemini", primary), ("gemini", other)]
        if "groq" in self.clients:
            chain += [("groq", m) for m in GROQ_MODELS]
        return chain

    def _call(self, provider: str, model: str, messages) -> str:
        key = f"{provider}/{model}"
        self.stats["calls"][key] = self.stats["calls"].get(key, 0) + 1
        return self.clients[provider].chat(model, messages)

    # -- a interface do loop ------------------------------------------ #
    def mutate(self, parent_source: str, rng: random.Random,
               feedback: dict | None = None) -> tuple[str, str]:
        messages = [{"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user",
                     "content": build_user_prompt(parent_source, feedback)}]
        chain = self._route_chain(rng)
        errors: list[str] = []
        for idx, (provider, model) in enumerate(chain):
            if idx > 0:
                self.stats["fallbacks"] += 1
            try:
                response = self._call(provider, model, messages)
            except MutationError as exc:
                errors.append(str(exc)[:160])
                continue
            summary = ""
            m = re.search(r"^SUMMARY:\s*(.+)$", response, re.MULTILINE)
            if m:
                summary = m.group(1).strip()
            child = _apply_diffs(parent_source, response)
            kind = "diff"
            if child is None:
                child = _extract_rewrite(response)
                kind = "rewrite"
            if child is None:
                errors.append(f"{provider}/{model}: sem diff aplicável "
                              "nem reescrita válida")
                continue
            try:
                child, reverted = _enforce_evolve_blocks(parent_source,
                                                         child)
            except MutationError as exc:
                errors.append(f"{provider}/{model}: {exc}")
                continue
            if child == parent_source:
                errors.append(f"{provider}/{model}: mutação vazia")
                continue
            if len(child) > MAX_CODE_LENGTH:
                errors.append(f"{provider}/{model}: filho com "
                              f"{len(child)} chars > {MAX_CODE_LENGTH}")
                continue
            desc = f"llm[{provider}/{model}] {kind}"
            if summary:
                desc += f": {summary}"
            if reverted:
                desc += " (edições fora do EVOLVE-BLOCK revertidas)"
            return child, desc
        self.stats["failures"] += 1
        raise MutationError("todas as rotas falharam: "
                            + " | ".join(errors)[:600])
