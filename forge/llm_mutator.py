"""Mutador LLM da forja — corrida forge-v1 (Degrau 2, sub-issue #6).

O adaptador que faltava entre o desenho do OpenEvolve
(docs/DISSECACAO-OPENEVOLVE-FORJA.md) e o loop da casa (forge/run.py):
MESMA interface do mutador programático do smoke —

    mutate(parent_source, rng, feedback) -> (child_source, descrição)

— mas quem muta é um ensemble de LLMs via endpoints OpenAI-compatible:

- **NVIDIA NIM (principal)**, pela EMENDA DE PROVEDOR de 27/10/2026:
  a Version 7 morreu por HTTP 429 nas quatro rotas antigas (rajada
  sem ritmo nem backoff; ver docs/FORGE-V1-LOG.md). A NVIDIA entra
  na frente da cadeia com ``deepseek-ai/deepseek-v4-flash`` no
  volume e ``openai/gpt-oss-120b`` de fallback (chave gratuita
  `nvapi-…` de build.nvidia.com, limite ~40 RPM — daí o
  ritmo/backoff no transporte, ver abaixo). O primário anterior
  foi REMOVIDO na emenda pós-V8: ausente da referência oficial do
  NIM hospedado, o 404 dele era definitivo, não transitório;
- **Gemini**, no desenho da config validado pela pesquisa
  (docs/PESQUISA-MUTADOR-FORGE-V1.md §4), com a EMENDA DE MODELOS de
  27/10/2026: a família Gemini 2.5 retorna 404 para a chave do
  fundador (a Version 6 do kernel morreu assim: 300/300 mutações
  `rejected_llm`), então o volume (peso 0,8) é
  ``gemini-3-flash-preview`` e os saltos (peso 0,2) são
  ``gemini-3.8-flash`` — o salto anterior foi depreciado em
  08/10/2026 e passou a ser roteado silenciosamente para o 3.6;
  troca silenciosa de modelo é inaceitável no pré-registro, então
  a emenda pós-V8 nomeia o 3.8 explicitamente;
- **Groq (fallback final)**: persistindo a falha, a mutação cai para
  os modelos coder da Groq — ``openai/gpt-oss-120b`` e, persistindo a
  falha, ``qwen/qwen3.8-27b`` (a Groq não serve mais o qwen3-32b).

O ensemble é o que houver: qualquer subconjunto de chaves funciona
(só NVIDIA vira rota única; sem NVIDIA a cadeia começa no Gemini).
Sem chave nenhuma, ``NoKeysError`` — quem chama (o notebook)
transforma isso no veredito BLOQUEADO, não em crash.

CHAVES: lidas de variáveis de ambiente (``NVIDIA_API_KEY`` /
``GEMINI_API_KEY`` / ``GROQ_API_KEY``) ou, no Kaggle, do
UserSecretsClient — ver ``load_api_keys``. NUNCA são impressas,
logadas ou embutidas em código/notebook; os testes usam transporte
MOCKADO, sem chave real.

Formato da mutação (o do OpenEvolve): blocos SEARCH/REPLACE sobre o
fonte do pai, restritos ao EVOLVE-BLOCK — ``enforce_evolve_blocks``
da config é aplicado AQUI também: edição fora do bloco é revertida
para o texto do pai, e o fato entra na descrição. Resposta sem diff
aplicável mas com um programa inteiro cercado (```python) é aceita
como reescrita (e passa pelo mesmo enforce); qualquer outra coisa é
``MutationError`` — o driver registra a rejeição e o loop segue.
"""
from __future__ import annotations

import http.client
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------- #
# Rotas e modelos (espelham forge/config.yaml + a pesquisa do mutador)
# --------------------------------------------------------------------- #
NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_API_BASE = "https://api.groq.com/openai/v1"

NVIDIA_VOLUME_MODEL = "deepseek-ai/deepseek-v4-flash"   # rota principal (emenda pós-V8: confirmado na referência oficial do NIM hospedado, 23/10/2026; o primário anterior saiu da cadeia — 404 definitivo, não transitório)
# Fallback NVIDIA (correção pós-V8): tentado na mesma iteração,
# antes de cair para Gemini/Groq, e é a fundação do portão da
# corrida (race_gate): ID confirmado na referência oficial de
# modelos suportados da NVIDIA (GPT-OSS-120B).
NVIDIA_FALLBACK_MODELS = ("openai/gpt-oss-120b",)
GEMINI_VOLUME_MODEL = "gemini-3-flash-preview"   # peso 0,8 — volume (emenda 27/10: 2.5-flash-lite dá 404 p/ esta chave)
GEMINI_LEAP_MODEL = "gemini-3.8-flash"            # peso 0,2 — saltos (emenda pós-V8: o salto anterior foi depreciado em 08/10/2026 e roteado silenciosamente p/ o 3.6; troca silenciosa é inaceitável no pré-registro)
GEMINI_LEAP_WEIGHT = 0.2
GROQ_MODELS = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b")   # qwen3-32b não é mais servido pela Groq; o 3.8-27b tem teto de saída de 16.384 tokens (≥ MAX_TOKENS)

TEMPERATURE = 0.7
MAX_TOKENS = 16000

# Sonda pré-voo (correção pós-V8): 1 chamada pequena por rota, sem
# mutação e sem torneio. Provar que o modelo existe e a chave vale
# custa 32 tokens de saída; descobrir isso na iteração 300 custou
# 5h09 de backoff na V8.
PROBE_MAX_TOKENS = 32
PROBE_MESSAGES = [{"role": "user",
                   "content": "Reply with the single word OK."}]


def probe_gate(results: list[dict]) -> bool:
    """A corrida só pode largar se PELO MENOS UMA rota estiver viva.
    Zero rotas vivas = abortar antes da primeira iteração, não depois
    de 300 tentativas com backoff."""
    return any(r.get("ok") for r in results)


def format_probe_report(results: list[dict]) -> str:
    lines = []
    for r in results:
        if r.get("ok"):
            lines.append(f"OK {r['provider']}/{r['model']}")
        else:
            lines.append(f"FAIL {r['provider']}/{r['model']} — "
                         f"{r.get('error', '')}")
    return "\n".join(lines)


# Portão DA CORRIDA (emenda pós-V8, branch forja/portao-sonda):
# mais forte que o probe_gate do kernel de fumaça (≥1 rota viva
# basta para o RELATÓRIO da fumaça; para LARGAR 300 iterações, não).
# A fundação mínima da V9 é o fallback NVIDIA confirmado na
# referência oficial (openai/gpt-oss-120b) + redundância Gemini.
# Groq é reforço, não fundação (free tier volátil) — não conta
# para o mínimo.
GATE_REQUIRED_ROUTE = ("nvidia", NVIDIA_FALLBACK_MODELS[0])
GATE_SECOND_PROVIDER = "gemini"


def race_gate(results: list[dict]) -> tuple[bool, list[str]]:
    """(pode largar?, motivos de bloqueio) do portão interno.

    PASS exige: (a) a rota obrigatória
    ``nvidia/openai/gpt-oss-120b`` viva; (b) ≥1 rota Gemini viva.
    Bloqueando, devolve cada motivo nomeado — é o texto que o
    ``FORGE-GATE: BLOCKED`` do driver imprime.
    """
    live = {(r.get("provider"), r.get("model"))
            for r in results if r.get("ok")}
    reasons: list[str] = []
    if GATE_REQUIRED_ROUTE not in live:
        reasons.append(
            f"rota obrigatória morta: {GATE_REQUIRED_ROUTE[0]}/"
            f"{GATE_REQUIRED_ROUTE[1]} (fundação NVIDIA do portão)")
    if not any(p == GATE_SECOND_PROVIDER for p, _m in live):
        reasons.append(
            "nenhuma rota Gemini viva (o mínimo exige ≥1; Groq é "
            "reforço e não conta para a fundação)")
    return not reasons, reasons
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
    """Nenhuma chave de LLM disponível (NVIDIA, Gemini nem Groq)."""


# Relógio da instrumentação de tempo por rota (observação pura):
# injetável para os testes provarem o acúmulo sem rede nem espera.
_perf = time.perf_counter


# --------------------------------------------------------------------- #
# Chaves — env ou Kaggle Secrets; valores NUNCA aparecem em saída
# --------------------------------------------------------------------- #
# (nome interno, variável/secret) — UM padrão só para os três
# provedores: env primeiro, UserSecretsClient do Kaggle no que faltar.
_KEY_LABELS = (("nvidia", "NVIDIA_API_KEY"),
               ("gemini", "GEMINI_API_KEY"),
               ("groq", "GROQ_API_KEY"))


def load_api_keys() -> dict:
    """{'nvidia': str|None, 'gemini': str|None, 'groq': str|None}
    sem vazar valor algum."""
    keys = {name: os.environ.get(label) or None
            for name, label in _KEY_LABELS}
    if all(keys.values()):
        return keys
    try:  # no Kaggle: UserSecretsClient (fora dele, o import falha)
        from kaggle_secrets import UserSecretsClient
        client = UserSecretsClient()
        for name, label in _KEY_LABELS:
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


# Retry com backoff (emenda 27/10/2026, pós-429 da Version 7):
# status transitórios valem outra tentativa — política portada do
# transporte local provado (forge/local_transport.py do Plano B:
# 3 tentativas, backoff 5s/20s). Constantes de módulo para os
# testes poderem zerar os intervalos.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_BACKOFFS = (5.0, 20.0)

# Ritmo (pacing): intervalo mínimo entre tentativas HTTP, para a
# rajada do driver não estrangular os free tiers (~40 RPM na
# NVIDIA, janelas curtas nos demais). Ajustável por ambiente.
DEFAULT_MIN_INTERVAL_S = 1.5
_MIN_INTERVAL_ENV = "FORGE_LLM_MIN_INTERVAL_S"
_last_attempt_at = 0.0


def _min_interval_s() -> float:
    try:
        return max(0.0, float(os.environ.get(
            _MIN_INTERVAL_ENV, DEFAULT_MIN_INTERVAL_S)))
    except ValueError:
        return DEFAULT_MIN_INTERVAL_S


def _pace() -> None:
    """Espera até o intervalo mínimo desde a última tentativa."""
    global _last_attempt_at
    now = time.monotonic()
    wait = _last_attempt_at + _min_interval_s() - now
    if wait > 0:
        time.sleep(wait)
        now = time.monotonic()
    _last_attempt_at = now


def _single_attempt(url: str, headers: dict, payload: dict,
                    timeout: int):
    """Uma tentativa de POST JSON via urllib -> (status, corpo)."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": _USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _default_transport(url: str, headers: dict, payload: dict,
                       timeout: int):
    """POST JSON com ritmo + retry. Devolve (status, corpo_texto).

    Até len(RETRY_BACKOFFS)+1 tentativas para status em
    ``RETRYABLE_STATUS`` e para erros de rede; esgotado em HTTP,
    devolve o último (status, corpo); esgotado em rede, devolve
    (503, "network error after retries: ...") — assim a cadeia de
    fallback do mutador trata a falha como falha da rota, igual ao
    transporte local provado. Cada tentativa respeita o pacing de
    ``_pace()``.
    """
    attempts = len(RETRY_BACKOFFS) + 1
    for attempt in range(attempts):
        last = attempt == attempts - 1
        _pace()
        try:
            status, body = _single_attempt(url, headers, payload,
                                           timeout)
        except (urllib.error.URLError, OSError,
                http.client.RemoteDisconnected) as exc:
            if not last:
                time.sleep(RETRY_BACKOFFS[attempt])
                continue
            return 503, f"network error after retries: {exc}"
        if status in RETRYABLE_STATUS and not last:
            time.sleep(RETRY_BACKOFFS[attempt])
            continue
        return status, body
    raise AssertionError("inalcançável: o laço sempre devolve")


_PROVIDER_BASES = {"nvidia": NVIDIA_API_BASE,
                   "gemini": GEMINI_API_BASE,
                   "groq": GROQ_API_BASE}


def _extract_text(data: dict, label: str) -> str:
    """O texto da 1ª choice, tolerante às formas dos provedores.

    Formas aceitas: ``content`` string; ``content`` como lista de
    partes (``{"type": "text", "text": ...}``); ``content``
    ausente/None com ``reasoning_content`` utilizável — a forma do
    200 ilegível da fumaça src15 (gemini-3-flash-preview respondeu
    HTTP 200 e o parse antigo quebrou com KeyError 'content').
    Sem texto utilizável, MutationError com a FORMA recebida
    (nomes das chaves da message e o tipo do content — nunca o
    conteúdo), para a próxima sonda diagnosticar sem adivinhação.
    """
    try:
        message = data["choices"][0].get("message") or {}
    except Exception as exc:
        raise MutationError(
            f"{label} resposta ilegível: sem choices ({exc})"
        ) from exc
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        text = "".join(p.get("text", "") for p in content
                       if isinstance(p, dict))
        if text.strip():
            return text
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    raise MutationError(
        f"{label} resposta sem texto utilizável "
        f"(message_keys={sorted(message)}, "
        f"content_type={type(content).__name__})")


class LLMClient:
    """Chat completions mínimo, um provedor por instância."""

    def __init__(self, provider: str, api_key: str, transport=None):
        self.provider = provider
        self._api_key = api_key
        # Junção base+path NORMALIZADA (correção pós-V8 — a
        # causa-raiz dos 404 históricos): as bases NVIDIA/Groq
        # NÃO terminam em "/" e o chat() concatenava
        # "chat/completions" direto, então TODAS as chamadas iam
        # para ".../v1chat/completions": NVIDIA e Groq ficaram
        # inalcançáveis em TODAS as versões V6–V8 e só o Gemini
        # (base com "/" final) foi testado de verdade. Normalizar
        # aqui torna a junção correta qualquer que seja a grafia
        # da constante; tests/test_forge_gate.py trava a URL final
        # exata dos 3 provedores.
        self.base = _PROVIDER_BASES[provider].rstrip("/") + "/"
        self.transport = transport or _default_transport

    def chat(self, model: str, messages: list[dict],
             max_tokens: int = MAX_TOKENS) -> str:
        payload = {"model": model, "messages": messages,
                   "temperature": TEMPERATURE, "max_tokens": max_tokens}
        status, body = self.transport(
            self.base + "chat/completions",
            {"Authorization": f"Bearer {self._api_key}"},
            payload, TIMEOUT_S)
        if status != 200:
            raise MutationError(
                f"{self.provider}/{model} HTTP {status}: {body[:200]}")
        try:
            data = json.loads(body)
        except Exception as exc:
            raise MutationError(
                f"{self.provider}/{model} resposta ilegível: {exc}"
            ) from exc
        return _extract_text(data, f"{self.provider}/{model}")


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
    """Ensemble: NVIDIA (volume) -> par Gemini -> par Groq.

    ``keys``: {'nvidia': ..., 'gemini': ..., 'groq': ...}
    (None/ausente = provedor fora da cadeia).
    ``transport``: injetável — os testes passam um mock que devolve
    respostas fixas no formato OpenAI, sem chave nem rede.
    """

    def __init__(self, keys: dict | None = None, transport=None):
        keys = keys if keys is not None else load_api_keys()
        self.clients: dict[str, LLMClient] = {}
        for provider in ("nvidia", "gemini", "groq"):
            if keys.get(provider):
                self.clients[provider] = LLMClient(
                    provider, keys[provider], transport=transport)
        if not self.clients:
            raise NoKeysError(
                "nenhuma chave de LLM (NVIDIA_API_KEY/GEMINI_API_KEY/"
                "GROQ_API_KEY) disponível — cadastre os Secrets no "
                "Kaggle")
        self.stats = {"calls": {}, "fallbacks": 0, "failures": 0,
                      "route_seconds": {}}
        # Poda pós-sonda (emenda pós-V8): None = cadeia inteira;
        # depois de prune_dead_routes(), só as rotas vivas.
        self._live_routes: set | None = None
        self.pruned_routes: list[dict] = []

    # -- cadeia de rotas de uma iteração ------------------------------ #
    def _route_chain(self, rng: random.Random) -> list[tuple[str, str]]:
        chain: list[tuple[str, str]] = []
        if "nvidia" in self.clients:
            chain += [("nvidia", NVIDIA_VOLUME_MODEL)]
            chain += [("nvidia", m) for m in NVIDIA_FALLBACK_MODELS]
        if "gemini" in self.clients:
            leap = rng.random() < GEMINI_LEAP_WEIGHT
            primary = GEMINI_LEAP_MODEL if leap else GEMINI_VOLUME_MODEL
            other = GEMINI_VOLUME_MODEL if leap else GEMINI_LEAP_MODEL
            chain += [("gemini", primary), ("gemini", other)]
        if "groq" in self.clients:
            chain += [("groq", m) for m in GROQ_MODELS]
        if self._live_routes is not None:
            # A poda filtra DEPOIS da montagem: o sorteio
            # volume/salto do Gemini já consumiu o RNG — podar não
            # muda o consumo de sorteios de ninguém.
            chain = [r for r in chain if r in self._live_routes]
        return chain

    def _call(self, provider: str, model: str, messages) -> str:
        key = f"{provider}/{model}"
        self.stats["calls"][key] = self.stats["calls"].get(key, 0) + 1
        # Instrumentação: o tempo da rota inclui retries/backoff do
        # transporte (é dentro de chat() que eles dormem) — medir aqui
        # é medir onde as horas vão, sem tocar em decisão alguma.
        t0 = _perf()
        try:
            return self.clients[provider].chat(model, messages)
        finally:
            acc = self.stats.setdefault("route_seconds", {})
            acc[key] = acc.get(key, 0.0) + (_perf() - t0)

    # -- sonda pré-voo ------------------------------------------------ #
    def _probe_chain(self) -> list[tuple[str, str]]:
        """A mesma cadeia de _route_chain, com RNG fixo: a sonda prova
        cada modelo da cadeia real (a ordem volume/salto do Gemini
        não importa aqui — os dois modelos entram de qualquer forma),
        sem duplicar a lista de rotas em dois lugares."""
        return self._route_chain(random.Random(0))

    def probe_routes(self) -> list[dict]:
        """1 chamada pequena por rota. Nunca levanta: rota morta — ou
        transporte que levante qualquer exceção — vira registro FAIL
        com o status, para o kernel de fumaça decidir. Não toca
        stats['calls']: sonda não é mutação."""
        results: list[dict] = []
        for provider, model in self._probe_chain():
            try:
                self.clients[provider].chat(
                    model, PROBE_MESSAGES, max_tokens=PROBE_MAX_TOKENS)
                results.append({"provider": provider, "model": model,
                                "ok": True, "error": ""})
            except Exception as exc:
                results.append({"provider": provider, "model": model,
                                "ok": False, "error": str(exc)[:160]})
        return results

    def prune_dead_routes(self, results: list[dict]) -> list[dict]:
        """Poda (emenda pós-V8): fixa a cadeia DESTA instância nas
        rotas que a sonda aprovou — rota morta não é paga de novo
        a cada iteração (na V8, a cadeia inteira degradada custava
        ~1–2,4 min/iteração de retries). Devolve os registros
        podados ({provider, model, error}) para o driver gravar no
        summary. A sonda roda ANTES da poda: sondar depois só
        retesta as vivas."""
        self._live_routes = {(r["provider"], r["model"])
                             for r in results if r.get("ok")}
        self.pruned_routes = [
            {"provider": r["provider"], "model": r["model"],
             "error": r.get("error", "")}
            for r in results if not r.get("ok")]
        return self.pruned_routes

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
            except Exception as exc:
                # Captura alargada (emenda pós-V8): o transporte
                # default só traduz URLError/OSError/
                # RemoteDisconnected; fora dessa tupla (ex.:
                # http.client.BadStatusLine) a exceção escapava do
                # chat(), pulava o RESTO da cadeia da iteração e o
                # driver registrava `error` — mecanismo plausível
                # do error:1 da V8. Agora qualquer exceção de
                # transporte é falha DESTA rota e a cadeia segue;
                # MutationError consolidado só quando TODAS
                # falharem (fim do laço, como antes).
                errors.append(f"{provider}/{model}: "
                              f"{type(exc).__name__}: {exc}"[:160])
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
