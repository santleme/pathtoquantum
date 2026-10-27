"""Mutador programático do SMOKE da forja (Degrau 2, sub-issue #5).

DECISÃO REGISTRADA (smoke, 27/10/2026): o desenho da forja
(docs/DISSECACAO-OPENEVOLVE-FORJA.md) prevê um mutador LLM
(OpenEvolve + ensemble Gemini via endpoint OpenAI-compatible).
No ambiente Kaggle NÃO há chave/endpoint de LLM disponível para
este kernel — e nenhum segredo novo entra sem o fundador. O smoke
existe para provar o PIPELINE (guarda AST → avaliador em cascata →
artefatos → curva de S), não a inteligência do mutador; por isso o
mutador do smoke é programático, em nível de AST:

1. **mutação de parâmetro** (o comportamento de verdade): perturba
   1 gene dos 20 do espaço do torneio (``mundo.genome.GENES``, com
   os mesmos limites [lo, hi] e passos do CMA-ES) gravando um
   ``self.p["gene"] = valor`` num ``__init__`` da ``EvolvedPolicy``
   — canal legal da guarda (escrita em ``self``), equivalente em
   código ao que o genoma fazia por vetor;
2. **jitter de literal**: multiplica um literal numérico do
   EVOLVE-BLOCK por um fator em [0,8; 1,25] — exerce a mutação
   sobre o corpo do bloco, como um diff de LLM faria.

As edições são cirúrgicas (texto, guiadas por AST): comentários,
marcadores EVOLVE-BLOCK e o restante do arquivo sobrevivem byte a
byte. Tudo sorteado por um ``random.Random`` do driver — o smoke é
reproduzível pela seed. Qual LLM entra na corrida de verdade
(forge-v1, sub-issue #6) é decisão do fundador; este mutador NÃO
muda o desenho dela, só destrava a prova do pipeline.
"""
from __future__ import annotations

import ast
import random
import re

from mundo.genome import GENES

GENE_BOUNDS = {name: (v0, lo, hi, step)
               for name, v0, lo, hi, step in GENES}
BLOCK_START = "# EVOLVE-BLOCK-START"
BLOCK_END = "# EVOLVE-BLOCK-END"

_PARAM_LINE = re.compile(
    r'^(?P<indent>\s*)self\.p\["(?P<name>[a-z_0-9]+)"\]\s*=\s*'
    r'(?P<value>[-+0-9.eE_]+)\s*$')
_SUPER_LINE = re.compile(r"super\(\)\.__init__\(")


def _block_span(lines: list[str]) -> tuple[int, int]:
    """[início, fim) em índices de linha do EVOLVE-BLOCK (ou tudo)."""
    start = end = None
    for i, line in enumerate(lines):
        if BLOCK_START in line:
            start = i
        elif BLOCK_END in line:
            end = i
    if start is None or end is None or end <= start:
        return 0, len(lines)
    return start, end


def _class_node(tree) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "EvolvedPolicy":
            return node
    return None


def current_overrides(source: str) -> dict[str, float]:
    """Os ``self.p[...] = valor`` que o programa já carrega."""
    out: dict[str, float] = {}
    for line in source.splitlines():
        m = _PARAM_LINE.match(line)
        if m:
            out[m.group("name")] = float(m.group("value"))
    return out


def _fmt(value: float) -> str:
    return repr(float(value))


def _mutate_param(lines: list[str], rng: random.Random):
    """Perturba 1 gene via ``self.p[...]`` no ``__init__`` da classe.

    Devolve (linhas_novas, descrição) ou None se não achou alvo.
    """
    source = "\n".join(lines)
    tree = ast.parse(source)
    cls = _class_node(tree)
    if cls is None:
        return None
    overrides = current_overrides(source)
    names = list(GENE_BOUNDS)
    rng.shuffle(names)
    chosen = None
    for name in names:
        v0, lo, hi, step = GENE_BOUNDS[name]
        cur = overrides.get(name, v0)
        delta = step * rng.choice([-2, -1, 1, 2]) * rng.uniform(0.5, 1.0)
        new = min(hi, max(lo, cur + delta))
        if new == cur:
            new = min(hi, max(lo, cur + step * rng.choice([-1, 1])))
        if new != cur:
            chosen = (name, cur, new)
            break
    if chosen is None:
        return None
    name, cur, new = chosen
    desc = f"param {name} {cur:g} -> {new:g}"
    # 1) já existe a linha do override: troca só o número
    for i, line in enumerate(lines):
        m = _PARAM_LINE.match(line)
        if m and m.group("name") == name:
            lines[i] = f'{m.group("indent")}self.p["{name}"] = {_fmt(new)}'
            return lines, desc
    init = next((n for n in cls.body
                 if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
                None)
    stmt = f'self.p["{name}"] = {_fmt(new)}'
    if init is not None:
        # depois da chamada super().__init__(...), se houver; senão,
        # como primeiro statement do corpo
        insert_at = None
        for i in range(init.lineno - 1, init.end_lineno):
            if _SUPER_LINE.search(lines[i]):
                insert_at = i + 1
                break
        if insert_at is None:
            first = init.body[0]
            insert_at = first.lineno - 1
        indent = " " * (init.col_offset + 4)
        lines.insert(insert_at, indent + stmt)
        return lines, desc
    # 2) sem __init__: cria o método logo após a docstring da classe
    method = [
        "    def __init__(self, params=None):",
        "        super().__init__(params)",
        f"        {stmt}",
        "",
    ]
    first = cls.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
            and isinstance(first.value.value, str):
        insert_at = first.end_lineno  # índice 0-based da linha seguinte
    else:
        insert_at = cls.lineno  # logo após a linha do class
    lines[insert_at:insert_at] = method
    return lines, desc


def _mutate_literal(lines: list[str], rng: random.Random):
    """Multiplica um literal numérico do bloco por U(0,8; 1,25)."""
    source = "\n".join(lines)
    tree = ast.parse(source)
    start, end = _block_span(lines)
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) \
                and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool) \
                and start < node.lineno <= end \
                and node.end_lineno == node.lineno \
                and not _PARAM_LINE.match(lines[node.lineno - 1]):
            candidates.append(node)
    if not candidates:
        return None
    node = rng.choice(candidates)
    old = node.value
    if isinstance(old, float):
        new = old * rng.uniform(0.8, 1.25)
        if new == old:
            return None
        text = _fmt(new)
    else:
        new = round(old * rng.uniform(0.8, 1.25))
        if new == old:
            new = old + (1 if old == 0 else rng.choice([-1, 1]))
        if new < 0:
            new = old + 1
        text = str(new)
    line = lines[node.lineno - 1]
    lines[node.lineno - 1] = line[:node.col_offset] + text \
        + line[node.end_col_offset:]
    return lines, f"literal {old:g} -> {new:g} (linha {node.lineno})"


def mutate(source: str, rng: random.Random) -> tuple[str, str]:
    """Uma mutação do programa. Devolve (fonte_novo, descrição).

    Mistura do smoke: ~65% parâmetro, ~20% literal, ~15% os dois.
    Se o tipo sorteado não tem alvo, cai para o outro; o resultado
    nunca é o fonte intacto.
    """
    roll = rng.random()
    kinds = ["param"] if roll < 0.65 else \
        ["literal"] if roll < 0.85 else ["param", "literal"]
    descs: list[str] = []
    current = source
    for kind in kinds:
        fn = _mutate_param if kind == "param" else _mutate_literal
        got = fn(current.splitlines(), rng)
        if got is not None:
            new_lines, desc = got
            current = "\n".join(new_lines)
            descs.append(desc)
    if current == source:  # nenhum tipo achou alvo: tenta o outro
        for fn in (_mutate_param, _mutate_literal):
            got = fn(source.splitlines(), rng)
            if got is not None:
                new_lines, desc = got
                if "\n".join(new_lines) != source:
                    return "\n".join(new_lines), desc
        raise ValueError("mutador sem alvo no programa")
    return current, "; ".join(descs)
