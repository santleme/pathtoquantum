"""Políticas-código evoluídas — a ponte da forja (Degrau 2).

Uma política da forja é um ARQUIVO Python com uma classe
``EvolvedPolicy(HeuristicPolicy)`` — código que um LLM pode reescrever
(OpenEvolve), ao contrário do genoma de 20 números do torneio. Este
módulo é a fronteira segura entre esse código e o motor:

- ``validate_program``: a **guarda anti-trapaça** (issue #3 do repo,
  épica #1). Lint por AST que roda ANTES de qualquer avaliação:
  imports por allowlist de MÓDULOS (interface pública do mundo, sem
  torneio/driver/carregador), nada de eval/open/getattr, nada de
  ``engine.rng`` direto (a política não consome nem manipula o fluxo
  de aleatoriedade do motor), nada de ``engine.companies`` (estado
  das rivais). Escrita no mundo só pelos canais legítimos: métodos
  do motor, subscritos ``comp._offers/_buys/knowledge`` e
  ``engine.claimed_by``, atributos ``comp.tools.*`` — a guarda
  rastreia apelidos de ``engine``/``comp`` (taint) e rejeita
  atribuição/deleção de atributo em qualquer outro objeto, deleção
  em geral e subscrito fora dos donos legítimos (revisão do PR #7).

  Limite da v1 — FECHADO pela guarda v2: a AST não enxerga tipo, e
  ler ``deposit.grade`` fora de ``comp.knowledge`` era possível
  porque a política recebia os objetos vivos do motor. A correção
  estrutural é a camada de Observation (docs/OBSERVATION-SPEC.md):
  a política-programa só recebe a ``Observation`` — ``DepositView``
  não tem ``grade``/``size_t``, não há lista de empresas nem eventos
  futuros na superfície, e os internos das views vivem sob nomes
  *name-mangled* que a regra nova desta guarda rejeita no fonte
  (atributo com ``__``). O loader ainda exige a assinatura do
  contrato novo, ``decide(self, obs)``.

- ``load_program_policy``: valida, carrega o módulo de um arquivo e
  devolve a instância, com ``program_hash``/``pid`` para a Crônica
  (análogo ao ``genome_hash`` das políticas-genoma).
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import itertools
from pathlib import Path

from .engine import HeuristicPolicy, Policy

# Imports permitidos, por MÓDULO (não só raiz): o candidato importa a
# interface pública do mundo — nunca o torneio, o driver ou este
# próprio carregador (superfície de episódios aninhados/recursão).
ALLOWED_IMPORT_MODULES = {"mundo", "mundo.chain", "mundo.engine",
                          "mundo.companies", "math"}
# Para ``from mundo import X``: só os submódulos públicos acima.
MUNDO_PACKAGE_NAMES = {"chain", "engine", "companies"}

# Donos legais de escrita por subscrito, como (origem, primeiro
# atributo): as intenções da empresa, o conhecimento dela e o
# registro de claims que o próprio ``decide`` da v0 mantém via motor.
LEGAL_SUBSCRIPT_OWNERS = {("comp", "_offers"), ("comp", "_buys"),
                          ("comp", "knowledge"),
                          ("engine", "claimed_by")}

BANNED_CALLS = {
    "eval", "exec", "open", "__import__", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "compile", "input",
    "breakpoint", "help", "memoryview",
}

# Atributos que o código candidato nunca toca diretamente:
# - ``rng``: o fluxo de aleatoriedade é do motor (os métodos herdados
#   sorteiam; a política, não);
# - ``companies``: o estado das rivais não é leitura legal da focal.
BANNED_ATTRS = {"rng", "companies"}

_load_counter = itertools.count()
_class_cache: dict[str, type] = {}


class ProgramRejected(RuntimeError):
    """O programa candidato violou a guarda anti-trapaça."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__("; ".join(self.violations))


def program_hash(source: str) -> str:
    """Hash curto e estável do código — o ``policy_id`` da Crônica."""
    return hashlib.sha256(source.encode()).hexdigest()[:12]


def _root_name(node) -> str | None:
    """O nome na raiz de uma cadeia de atributos (``a.b.c`` -> ``a``)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _chain(node) -> tuple[str | None, list[str]]:
    """(nome raiz, [atributos em ordem]) de uma cadeia ``a.b.c``."""
    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    attrs.reverse()
    return (node.id if isinstance(node, ast.Name) else None), attrs


def _taint_map(tree) -> dict[str, str]:
    """Nomes contaminados por ``engine``/``comp``, com a origem.

    A guarda v1 rastreia alias de forma simples e conservadora: um
    nome que recebe valor enraizado em ``engine``/``comp`` herda a
    contaminação (``c = comp`` contamina ``c``; ``tools = comp.tools``
    contamina ``tools`` com origem ``comp.tools``). Nomes de parâmetro
    chamados engine/comp contaminam por nome em qualquer escopo.
    """
    taint: dict[str, str] = {"engine": "engine", "comp": "comp"}

    def origin_of(expr) -> str | None:
        if isinstance(expr, ast.Name):
            return taint.get(expr.id)
        if isinstance(expr, (ast.Attribute, ast.Subscript)):
            root, attrs = _chain(expr.value if isinstance(
                expr, ast.Subscript) else expr)
            origin = taint.get(root) if root else None
            if origin == "comp" and attrs and attrs[0] == "tools":
                return "comp.tools"
            return origin
        return None

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            targets, value = [], None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.For):
                targets, value = [node.target], node.iter
            if value is None:
                continue
            origin = origin_of(value)
            if origin is None:
                continue
            for target in targets:
                # Só nomes ATRIBUÍDOS de fato (alvo simples ou tupla) —
                # nomes dentro de um alvo-subscrito são leitores, não
                # variáveis novas (bug da revisão: engine virava "comp"
                # via engine.claimed_by[...] = comp.cid).
                stack = [target]
                while stack:
                    current = stack.pop()
                    if isinstance(current, ast.Name):
                        if taint.get(current.id) != origin:
                            taint[current.id] = origin
                            changed = True
                    elif isinstance(current, (ast.Tuple, ast.List)):
                        stack.extend(current.elts)
    return taint


def _check_write_target(target, taint, violations, how: str) -> None:
    """Aplica a regra de escrita a um alvo (atribuição/for/delete)."""
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _check_write_target(elt, taint, violations, how)
        return
    if isinstance(target, ast.Attribute):
        root, attrs = _chain(target)
        dotted = ".".join([root or "?"] + attrs)
        if root == "self":
            return
        origin = taint.get(root) if root else None
        # Único canal de atributo legítimo fora de self: comp.tools.*
        if origin == "comp.tools" or (origin == "comp" and attrs
                                       and attrs[0] == "tools"):
            return
        violations.append(
            f"{how} em atributo proibida: {dotted} (escrita legítima: "
            "self.*, comp.tools.* ou pelos métodos do motor)")
        return
    if isinstance(target, ast.Subscript):
        node, attrs = target.value, []
        while isinstance(node, (ast.Attribute, ast.Subscript)):
            if isinstance(node, ast.Attribute):
                attrs.append(node.attr)
            node = node.value
        root = node.id if isinstance(node, ast.Name) else None
        attrs.reverse()
        origin = taint.get(root) if root else None
        if origin is not None and not (
                attrs and (origin, attrs[0]) in LEGAL_SUBSCRIPT_OWNERS):
            dotted = ".".join([root or "?"] + attrs)
            violations.append(
                f"{how} em subscrito proibida: {dotted}[...] (donos "
                "legais: comp._offers/_buys/knowledge, engine.claimed_by)")


def validate_program(source: str) -> list[str]:
    """Devolve a lista de violações da guarda (vazia = programa limpo)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"sintaxe inválida: {exc}"]
    taint = _taint_map(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORT_MODULES:
                    violations.append(
                        f"import fora da allowlist: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                violations.append("import relativo proibido")
            else:
                module = node.module or ""
                if module not in ALLOWED_IMPORT_MODULES:
                    violations.append(
                        f"import fora da allowlist: {module}")
                elif module == "mundo":
                    for alias in node.names:
                        if alias.name not in MUNDO_PACKAGE_NAMES:
                            violations.append(
                                "import fora da allowlist: "
                                f"mundo.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                violations.append(f"chamada proibida: {func.id}()")
            elif isinstance(func, ast.Attribute) \
                    and func.attr in BANNED_CALLS:
                violations.append(f"chamada proibida: .{func.attr}()")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS:
                violations.append(f"atributo proibido: .{node.attr}")
            if node.attr.startswith("__") and node.attr.endswith("__") \
                    and node.attr != "__init__":
                violations.append(f"atributo dunder proibido: {node.attr}")
            elif "__" in node.attr and node.attr != "__init__":
                # Guarda v2: nome com "__" fora do padrão dunder é
                # interno name-mangled das views da Observation
                # (_Actuator__engine, _CompanyView__comp, ...) — a
                # fronteira não se atravessa pelo nome cru.
                violations.append(
                    f"atributo privado proibido: {node.attr}")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                violations.append(f"nome dunder proibido: {node.id}")
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) \
                else [node.target]
            for target in targets:
                _check_write_target(target, taint, violations,
                                     "atribuição")
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                _check_write_target(target, taint, violations, "deleção")
        elif isinstance(node, ast.For):
            _check_write_target(node.target, taint, violations,
                                "atribuição")
    return violations


def load_program_policy(path) -> Policy:
    """Carrega e instancia a ``EvolvedPolicy`` de um arquivo da forja.

    Levanta ``ProgramRejected`` com as violações se a guarda reprovar,
    e ``ValueError`` se o arquivo não definir a classe esperada.
    """
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    h = program_hash(source)
    cls = _class_cache.get(h)
    if cls is None:
        violations = validate_program(source)
        if violations:
            raise ProgramRejected(violations)
        name = f"mundo_program_{h}_{next(_load_counter)}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = getattr(module, "EvolvedPolicy", None)
        if cls is None or not (isinstance(cls, type)
                               and issubclass(cls, HeuristicPolicy)):
            raise ValueError(
                f"{path}: o programa precisa definir "
                "EvolvedPolicy(HeuristicPolicy)")
        # Guarda v2: o contrato é decide(self, obs) — a política
        # recebe SÓ a Observation, nunca (engine, comp).
        try:
            inspect.signature(cls.decide).bind(None, None)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{path}: EvolvedPolicy.decide precisa aceitar "
                f"(self, obs) — a Observation é a única entrada da "
                f"política (guarda v2, docs/OBSERVATION-SPEC.md): "
                f"{exc}") from exc
        _class_cache[h] = cls
    policy = cls()
    policy.program_hash = h
    policy.pid = f"prog:{h}"
    return policy
