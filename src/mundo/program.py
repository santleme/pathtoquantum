"""Políticas-código evoluídas — a ponte da forja (Degrau 2).

Uma política da forja é um ARQUIVO Python com uma classe
``EvolvedPolicy(HeuristicPolicy)`` — código que um LLM pode reescrever
(OpenEvolve), ao contrário do genoma de 20 números do torneio. Este
módulo é a fronteira segura entre esse código e o motor:

- ``validate_program``: a **guarda anti-trapaça v1** (issue #3 do repo,
  épica #1). Lint por AST que roda ANTES de qualquer avaliação:
  imports por allowlist, nada de eval/open/getattr, nada de
  ``engine.rng`` direto (a política não consome nem manipula o fluxo
  de aleatoriedade do motor), nada de ``engine.companies`` (estado das
  rivais), nenhuma atribuição de atributo em ``engine``/``comp``
  (escrita no mundo é pelos métodos do motor ou pelos subscritos
  ``comp._offers/_buys/knowledge``).

  Limite declarado da v1: AST não enxerga tipo — ler
  ``deposit.grade`` fora de ``comp.knowledge`` continua possível em
  tese. A correção estrutural é a camada de Observation (gap
  registrado em docs/ALGORITMOS-DECISAO.md), guarda v2.

- ``load_program_policy``: valida, carrega o módulo de um arquivo e
  devolve a instância, com ``program_hash``/``pid`` para a Crônica
  (análogo ao ``genome_hash`` das políticas-genoma).
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import itertools
from pathlib import Path

from .engine import HeuristicPolicy, Policy

ALLOWED_IMPORT_ROOTS = {"mundo", "math"}

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


def validate_program(source: str) -> list[str]:
    """Devolve a lista de violações da guarda (vazia = programa limpo)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"sintaxe inválida: {exc}"]
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORT_ROOTS:
                    violations.append(
                        f"import fora da allowlist: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                violations.append("import relativo proibido")
            elif (node.module or "").split(".")[0] not in \
                    ALLOWED_IMPORT_ROOTS:
                violations.append(
                    f"import fora da allowlist: {node.module}")
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
            if node.attr.startswith("__") and node.attr.endswith("__"):
                violations.append(f"atributo dunder proibido: {node.attr}")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                violations.append(f"nome dunder proibido: {node.id}")
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) \
                else [node.target]
            # Só o alvo-atributo DIRETO é escrita proibida; atributo
            # dentro de subscrito (``engine.claimed_by[cell] = cid``,
            # ``comp._offers[c] = q``) é o canal legal de escrita.
            stack = list(targets)
            while stack:
                target = stack.pop()
                if isinstance(target, ast.Attribute):
                    root = _root_name(target)
                    if root in ("engine", "comp"):
                        violations.append(
                            f"atribuição direta em {root}.{target.attr} "
                            "proibida (escreva pelos métodos do motor)")
                elif isinstance(target, (ast.Tuple, ast.List)):
                    stack.extend(target.elts)
    return violations


def load_program_policy(path) -> Policy:
    """Carrega e instancia a ``EvolvedPolicy`` de um arquivo da forja.

    Levanta ``ProgramRejected`` com as violações se a guarda reprovar,
    e ``ValueError`` se o arquivo não definir a classe esperada.
    """
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    violations = validate_program(source)
    if violations:
        raise ProgramRejected(violations)
    h = program_hash(source)
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
    policy = cls()
    policy.program_hash = h
    policy.pid = f"prog:{h}"
    return policy
