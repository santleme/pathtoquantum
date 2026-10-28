"""Driver da corrida forge-v1 (Degrau 2, sub-issue #6 do repo).

O loop do smoke (forge/smoke.py) estendido para o protocolo da
épica #1, pré-registrado em docs/FORGE-V1-LOG.md:

    semente -> [seleção de pai em ilhas -> mutação (LLM) -> guarda
    AST -> avaliador stage1 -> stage2 nos melhores] x 300 iterações
    -> campeão -> AVALIAÇÃO CEGA nas seeds de TESTE travadas

Peças do protocolo:

- **População/arquivo**: todo programa aceito entra no arquivo com
  métricas comportamentais (stage_mean, facilities_mean — os eixos
  MAP-Elites da config) e linhagem; 5 ilhas (config) com seleção
  exploitation 0,7 e migração do melhor global a cada 50 iterações.
- **Mutador**: LLM (forge/llm_mutator.py — Gemini volume/salto com
  fallback Groq) recebendo o feedback completo do pai (métricas +
  artefatos do avaliador + inspirações da ilha). O programático do
  smoke segue disponível (``--mutator programmatic``) para testes e
  ensaios sem chave.
- **Cascata**: stage1 (8 eps treino F0) -> stage2 (64 eps validação
  F0+F1) quando S1 >= 0,45 (config) ou S1 é recorde do loop.
- **Avaliação cega** (fora do loop, ao final): campeão da corrida x
  campeão do torneio (genoma evo:6a94b587701d, de
  forge/tournament_champion.json) x semente, TODOS como empresa
  focal nos 64 blocos de teste do torneio (32 seeds 9901–9932 x
  (F0 sem choques, F2 com os choques pré-registrados)), ΔS pareado
  com IC95 por bootstrap. É a abertura das seeds de teste pelo
  protocolo: só com ``final=True``, uma única vez, no fim.

Veredito (pré-registrado, barras do torneio): ΔS(campeão − campeão
do torneio) >= 0,08 com IC95_lo > 0, sem colapso em F2/choques e
ΔS(campeão − semente) > 0 ⇒ "FORGE-V1: PROVA"; ΔS > 0 sem a barra
⇒ INCONCLUSIVO; senão REPROVADO/AJUSTAR.

Artefatos em out_dir: programs/ (todo programa avaliado), run_log
.jsonl, run_summary.json (checkpoint a cada 25 iterações),
archive.json, champion.py, final_evaluation.json, top5_diffs.md.

Instrumentação de tempo (observação pura — não muda prompt,
cascata, portão nem seed, e nunca toca no RNG): cada registro do
run_log carrega ``timing`` (mutação LLM total e por rota, stage1,
stage2 e total da iteração) e o fim da corrida imprime o bloco
TEMPOS com os agregados (total, média/mediana por iteração, soma
por fase, fase dominante). É assim que se descobre onde as horas
do Kaggle foram: geração LLM, avaliação ou retries/backoff.

Portão da sonda (emenda pós-V8, branch forja/portao-sonda —
infraestrutura, fora do protocolo: nenhum prompt, cascata,
threshold, seed, RNG ou scoring muda): com o mutador LLM,
``run_forge`` sonda as rotas ANTES da iteração 0 e se recusa a
largar (``FORGE-GATE: BLOCKED`` + motivos, zero iterações
consumidas) sem ``nvidia/nvidia/nemotron-3-ultra-550b-a55b``
vivo + ≥1 rota
Gemini viva (critério em ``llm_mutator.race_gate``; Groq é
reforço e não conta para o mínimo). As rotas mortas na sonda são
podadas da cadeia da corrida, com o fato em
``summary["probe_gate"]``. Desligar — só para smokes/testes
antigos: ``probe_gate=False`` ou ``--no-probe-gate`` (config
``probe_gate`` em forge/config.yaml, default LIGADO). O kernel de
fumaça separado (``--probe-only``) segue existindo como
diagnóstico, mas a corrida não depende mais de disciplina
procedural para não repetir a V8.

Porte ShinkaEvolve (issue #21, estudo docs/ESTUDO-SHINKA-FORJA.md)
— ATIVADO por decisão expressa do fundador em 28/10/2026: as duas
técnicas são o DEFAULT desta linhagem (merge do PR #27 + commit de
ativação). A ativação foi antecipada em relação ao staging
original (pós-veredito da #6) por decisão dele, e NÃO alcança a
corrida V9: ela roda o bundle congelado src17, montado antes —
a ativação vale para as corridas montadas desta branch em diante.
(1) Amostragem de pais ``weighted`` — peso σ(λ·(F−mediana)) ×
1/(1+N filhos gerados), λ=10, a configuração validada do paper
(§3.1); ``power_law`` (rank^(−α)) como estratégia alternativa —
no lugar do 70/20/10 fixo. (2) Filtro de novidade Tier 1 com
proxy LOCAL (sem embedding externo): AST normalizado do
EVOLVE-BLOCK + similaridade difflib contra a subpopulação da
ilha, rejeitando quase-duplicado ANTES da cascata (status
``rejected_novelty``) e logando a taxa no summary — o limiar
(0,98) é da escala do proxy, NÃO o 0,95 do embedding do paper.
O Tier 2 (juiz LLM) e o bandit de modelos NÃO foram portados:
o estudo os adia (o bandit exige ≥2 rotas vivas provadas).
Desligar continua possível e bit-idêntico ao comportamento
pré-porte: ``--parent-sampling off`` + ``--no-novelty-filter``
(ou os argumentos de ``run_forge``).

Uso no Kaggle (notebook notebooks/forge-v1.ipynb):
    python forge/run.py --iterations 300 --out /kaggle/working/forge-v1
Local (testes): FORGE_STAGE1_EPISODES / FORGE_STAGE2_EPISODES
encolhem os estágios, como no avaliador.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import importlib.util
import json
import math
import random
import statistics
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mundo import tournament as T  # noqa: E402
from mundo.driver import EpisodeSpec, run_episodes  # noqa: E402
from mundo.policies import PolicySpec  # noqa: E402
from mundo.program import program_hash, validate_program  # noqa: E402

FORGE_DIR = Path(__file__).resolve().parent
SEED_PATH = FORGE_DIR / "seed_policy.py"
CHAMPION_PATH = FORGE_DIR / "tournament_champion.json"

CASCADE_THRESHOLD = 0.45     # forge/config.yaml: cascade_thresholds[0]
NUM_ISLANDS = 5              # forge/config.yaml: database.num_islands
EXPLOITATION = 0.7           # forge/config.yaml: exploitation_ratio
CHECKPOINT_EVERY = 25        # forge/config.yaml: checkpoint_interval
MIGRATION_EVERY = 50         # dissecação: migração entre ilhas
PROBE_GATE_ENABLED = True    # forge/config.yaml: probe_gate (emenda pós-V8)

# Porte ShinkaEvolve (issue #21 — ATIVADO por decisão do fundador
# em 28/10/2026: defaults LIGADOS nesta linhagem; a V9 roda o
# bundle congelado src17 e não é afetada).
PARENT_SAMPLING = "weighted"  # forge/config.yaml: parent_sampling
                             # (off | weighted | power_law)
PARENT_LAMBDA = 10.0         # forge/config.yaml: parent_lambda
                             # (λ da weighted, paper §3.1)
PARENT_ALPHA = 1.0           # forge/config.yaml: parent_alpha
                             # (α da power_law; default do repo
                             # Shinka — o paper não fixa α)
NOVELTY_FILTER = True        # forge/config.yaml: novelty_filter
NOVELTY_THRESHOLD = 0.98     # forge/config.yaml: novelty_threshold
                             # (escala do proxy AST+difflib; NÃO é
                             # o 0,95 do embedding do paper)


def _load_sibling(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, FORGE_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _eval_stage(ev, path: Path, stage: int):
    """(métricas, artefatos) de um estágio do avaliador da forja."""
    if hasattr(ev, "_evaluate"):
        return ev._evaluate(str(path), stage)
    fn = ev.evaluate_stage1 if stage == 1 else ev.evaluate_stage2
    out = fn(str(path))
    metrics = out["metrics"] if isinstance(out, dict) and "metrics" in out \
        else getattr(out, "metrics", out)
    return metrics, {}


def _reason(artifacts: dict, fallback: str) -> str:
    for key in ("evaluation_error", "guard_violations"):
        if artifacts.get(key):
            return str(artifacts[key])[:400]
    return fallback


# --------------------------------------------------------------------- #
# Mutadores intercambiáveis (mesma interface de mutate)
# --------------------------------------------------------------------- #
class ProgrammaticMutator:
    """O mutador AST do smoke, adaptado à interface com feedback."""

    def __init__(self):
        self._mut = _load_sibling("forge_mutator", "mutator.py")
        self.stats = {"calls": {"programmatic/ast": 0}, "fallbacks": 0,
                      "failures": 0, "route_seconds": {}}

    def mutate(self, source, rng, feedback=None):
        self.stats["calls"]["programmatic/ast"] += 1
        t0 = time.perf_counter()
        try:
            return self._mut.mutate(source, rng)
        finally:
            acc = self.stats["route_seconds"]
            acc["programmatic/ast"] = acc.get("programmatic/ast", 0.0) \
                + (time.perf_counter() - t0)


def build_mutator(kind: str):
    if kind == "programmatic":
        return ProgrammaticMutator()
    if kind == "llm":
        llm = _load_sibling("forge_llm_mutator", "llm_mutator.py")
        return llm.LLMMutator()      # NoKeysError se não houver chave
    raise ValueError(f"mutador desconhecido: {kind!r}")


# --------------------------------------------------------------------- #
# Avaliação cega (a abertura das seeds de teste)
# --------------------------------------------------------------------- #
def _evaluate_blocks_focal(focal_spec, blocks, processes: int = 1):
    """evaluate_blocks do torneio, mas com a focal = uma PolicySpec
    qualquer (programa) — mesmos blocos, mesma rotação da focal."""
    specs, focals = [], []
    for i, (seed, field, shocks) in enumerate(blocks):
        focal_cid = i % T.N_COMPANIES
        focals.append(focal_cid)
        specs.append(EpisodeSpec(
            seed=seed, ticks=T.TICKS, n_companies=T.N_COMPANIES,
            god_events=T.TEST_SHOCKS if shocks else None,
            policy_specs=T.field_specs(None, field, focal_cid, i, seed,
                                       focal_spec=focal_spec)))
    results = run_episodes(specs, processes=processes)
    rows = []
    for res, (seed, field, shocks), focal_cid in zip(results, blocks,
                                                     focals):
        row = T.block_score(res, focal_cid)
        row.update({"seed": seed, "field": field, "shocks": shocks,
                    "focal_cid": focal_cid})
        rows.append(row)
    return rows


def _delta(rows_a, rows_b, filt=None) -> dict:
    a = [r for r in rows_a if filt is None or filt(r)]
    b = [r for r in rows_b if filt is None or filt(r)]
    deltas = T.paired_deltas(a, b)
    lo, hi = T.bootstrap_ci(deltas)
    return {"mean": sum(deltas) / len(deltas), "ci95": [lo, hi],
            "n_blocks": len(deltas)}


def forge_verdict(delta: float, ci_lo: float, delta_f2: float,
                  delta_shock: float, delta_seed: float) -> str:
    """As barras pré-registradas (as do torneio, docs/FORGE-V1-LOG)."""
    if delta >= 0.08 and ci_lo > 0 and delta_f2 >= 0 \
            and delta_shock >= 0 and delta_seed > 0:
        return "PROVA"
    if delta > 0:
        return "INCONCLUSIVO"
    return "REPROVADO/AJUSTAR"


def blind_evaluation(arms: dict, blocks, *, final: bool = False,
                     processes: int = 1) -> dict:
    """Os braços como focal nos MESMOS blocos; ΔS pareado + IC95.

    ``arms``: nome -> PolicySpec (programas) — o braço-genoma entra
    por ``genome_arm`` separado porque a abertura oficial das seeds
    de teste é ``T.evaluate_test(genome, final=True)``.
    """
    out = {"n_blocks": len(blocks), "arms": {}, "rows": {}}
    for name, spec in arms.items():
        rows = _evaluate_blocks_focal(spec, blocks, processes)
        out["rows"][name] = rows
        out["arms"][name] = sum(r["S"] for r in rows) / len(rows)
    return out


def top_diffs(records_by_hash: dict, champion_hash: str,
              sources: dict, k: int = 5) -> list[dict]:
    """Os k passos da linhagem do campeão com maior ganho de S1.

    Cada item: a mutação (descrição), o ΔS1 do passo e o diff
    unificado pai->filho (aparado) — o relatório legível da corrida.
    """
    lineage = []
    h = champion_hash
    while h is not None:
        rec = records_by_hash[h]
        lineage.append(rec)
        h = rec.get("parent")
    lineage.reverse()
    steps = []
    for rec in lineage[1:]:            # a semente não é um passo
        parent = records_by_hash[rec["parent"]]
        if rec.get("S1") is None or parent.get("S1") is None:
            continue
        diff = "\n".join(difflib.unified_diff(
            sources[rec["parent"]].splitlines(),
            sources[rec["hash"]].splitlines(),
            fromfile=f"prog:{rec['parent']}", tofile=f"prog:{rec['hash']}",
            lineterm="", n=3))
        steps.append({
            "iteration": rec["iteration"], "hash": rec["hash"],
            "parent": rec["parent"],
            "mutation": rec.get("mutation", ""),
            "S1_parent": parent["S1"], "S1_child": rec["S1"],
            "delta_S1": rec["S1"] - parent["S1"],
            "diff": "\n".join(diff.splitlines()[:120]),
        })
    steps.sort(key=lambda s: -s["delta_S1"])
    return steps[:k]


def _top_diffs_md(steps: list[dict], champion_hash: str) -> str:
    lines = [f"# Top-{len(steps)} diffs da linhagem do campeão "
             f"prog:{champion_hash}",
             "",
             "Os passos com maior ganho de S1 (stage1) entre a semente "
             "e o campeão — o que as mutações vencedoras mudaram.",
             ""]
    for i, s in enumerate(steps, 1):
        lines += [f"## {i}. Iteração {s['iteration']} — "
                  f"ΔS1 {s['delta_S1']:+.4f} "
                  f"({s['S1_parent']:.4f} → {s['S1_child']:.4f})",
                  "",
                  f"Mutação: {s['mutation']}",
                  "",
                  "```diff",
                  s["diff"],
                  "```",
                  ""]
    return "\n".join(lines)


# --------------------------------------------------------------------- #
# Instrumentação de tempo (observação pura)
# --------------------------------------------------------------------- #
_PHASE_LABELS = {"mutate_s": "mutação LLM",
                 "stage1_s": "avaliação stage1",
                 "stage2_s": "avaliação stage2",
                 "other_s": "outro (seleção, guarda e E/S)"}


def _route_seconds_of(mut) -> dict:
    """Cópia do acumulado de tempo por rota do mutador (se houver)."""
    stats = getattr(mut, "stats", None) or {}
    return dict(stats.get("route_seconds") or {})


def _route_delta(before: dict, after: dict) -> dict:
    """Quanto cada rota gastou entre dois instantâneos do acumulado."""
    return {k: round(after[k] - before.get(k, 0.0), 3) for k in after
            if after[k] - before.get(k, 0.0) > 0}


def summarize_timings(records: list[dict]) -> dict:
    """Agrega os ``timing`` dos registros do run_log.

    Média/mediana e somas por fase cobrem só as iterações do loop
    (iteration >= 1); a semente (iteração 0) entra à parte em
    ``seed_total_s`` e nas rotas. ``other_s`` é o resíduo do total
    (seleção de pai, guarda AST, escrita de arquivos). Função pura:
    os testes a exercem com registros sintéticos e relógio falso.
    """
    timed = [r for r in records if isinstance(r.get("timing"), dict)]
    loop = [r for r in timed if (r.get("iteration") or 0) >= 1]

    def _sum(rows, key):
        return sum((r["timing"].get(key) or 0.0) for r in rows)

    totals = [r["timing"].get("total_s") or 0.0 for r in loop]
    total = sum(totals)
    phases = {"mutate_s": _sum(loop, "mutate_s"),
              "stage1_s": _sum(loop, "stage1_s"),
              "stage2_s": _sum(loop, "stage2_s")}
    phases["other_s"] = max(0.0, total - sum(phases.values()))
    dominant_key = max(phases, key=lambda k: phases[k]) if loop \
        else "other_s"
    routes: dict[str, float] = {}
    for r in timed:
        for k, v in (r["timing"].get("routes_s") or {}).items():
            routes[k] = routes.get(k, 0.0) + v
    seed_rec = next((r for r in timed if r.get("iteration") == 0), None)
    return {
        "iterations_timed": len(loop),
        "total_s": round(total, 3),
        "mean_s": round(total / len(loop), 3) if loop else 0.0,
        "median_s": round(statistics.median(totals), 3) if totals
        else 0.0,
        "phases_s": {k: round(v, 3) for k, v in phases.items()},
        "phases_pct": {k: (round(100.0 * v / total, 1) if total > 0
                           else 0.0) for k, v in phases.items()},
        "dominant_phase": _PHASE_LABELS[dominant_key],
        "dominant_phase_key": dominant_key,
        "routes_s": {k: round(v, 3) for k, v in sorted(
            routes.items(), key=lambda kv: -kv[1])},
        "seed_total_s": (round(seed_rec["timing"].get("total_s") or 0.0,
                               3) if seed_rec is not None else None),
    }


def format_timing_block(timings: dict) -> str:
    """O bloco TEMPOS impresso no fim da corrida (espírito do veredito)."""
    p, pct = timings["phases_s"], timings["phases_pct"]
    lines = [
        "TEMPOS DA CORRIDA (instrumentação — observação pura, "
        "sem efeito nas decisões):",
        f"  loop: {timings['total_s']:.1f}s em "
        f"{timings['iterations_timed']} iterações "
        f"(média {timings['mean_s']:.2f}s, mediana "
        f"{timings['median_s']:.2f}s por iteração)",
        f"  mutação LLM {p['mutate_s']:.1f}s ({pct['mutate_s']:.1f}%) | "
        f"stage1 {p['stage1_s']:.1f}s ({pct['stage1_s']:.1f}%) | "
        f"stage2 {p['stage2_s']:.1f}s ({pct['stage2_s']:.1f}%) | "
        f"outro {p['other_s']:.1f}s ({pct['other_s']:.1f}%)",
        f"  fase dominante: {timings['dominant_phase']}",
    ]
    if timings.get("routes_s"):
        rotas = "; ".join(f"{k} {v:.1f}s"
                          for k, v in timings["routes_s"].items())
        lines.append("  rotas (tempo acumulado, inclui retries e "
                     f"backoff do transporte): {rotas}")
    if timings.get("seed_total_s") is not None:
        lines.append(f"  semente (iteração 0): "
                     f"{timings['seed_total_s']:.1f}s")
    if timings.get("blind_evaluation_s") is not None:
        lines.append(f"  avaliação cega: "
                     f"{timings['blind_evaluation_s']:.1f}s")
    if timings.get("run_wall_s") is not None:
        lines.append(f"  parede total (run_forge): "
                     f"{timings['run_wall_s']:.1f}s")
    return "\n".join(lines)


# --------------------------------------------------------------------- #
# Porte ShinkaEvolve (issue #21) — funções puras, atrás de flags
# --------------------------------------------------------------------- #
_BLOCK_START = "# EVOLVE-BLOCK-START"
_BLOCK_END = "# EVOLVE-BLOCK-END"


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def parent_weights(members: list[str], fitness: dict, children: dict,
                   strategy: str, lam: float = PARENT_LAMBDA,
                   alpha: float = PARENT_ALPHA) -> list[float]:
    """Pesos (não normalizados) de cada membro, na ordem de entrada.

    ``weighted`` (a configuração validada do paper, §3.1):
    desempenho s = σ(λ·(F − mediana dos F)) e novidade
    h = 1/(1 + N), com N = filhos já GERADOS pelo pai (candidatos
    produzidos, aceitos ou não); peso w = s·h. ``power_law``
    (alternativa do repo, não a validada): w = rank^(−α), rank 1
    = maior fitness, desempate determinístico pelo hash.
    """
    if strategy == "weighted":
        med = statistics.median(fitness[h] for h in members)
        return [_sigmoid(lam * (fitness[h] - med))
                / (1 + children.get(h, 0)) for h in members]
    if strategy == "power_law":
        order = sorted(members, key=lambda h: (-fitness[h], h))
        rank = {h: i + 1 for i, h in enumerate(order)}
        return [rank[h] ** (-alpha) for h in members]
    raise ValueError(f"parent_sampling desconhecido: {strategy!r}")


def sample_parent(members: list[str], fitness: dict, children: dict,
                  strategy: str, rng: random.Random,
                  lam: float = PARENT_LAMBDA,
                  alpha: float = PARENT_ALPHA) -> str:
    """Sorteia um pai da ilha pelos pesos da estratégia (1 sorteio)."""
    weights = parent_weights(members, fitness, children, strategy,
                             lam=lam, alpha=alpha)
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for h, w in zip(members, weights):
        acc += w
        if r < acc:
            return h
    return members[-1]


def _mutable_block(source: str) -> str:
    """O texto entre os marcadores EVOLVE-BLOCK (o programa inteiro
    se os marcadores faltarem) — é só sobre ele que a novidade do
    Tier 1 mede: o resto da semente é idêntico em todo candidato."""
    i = source.find(_BLOCK_START)
    j = source.find(_BLOCK_END)
    if i != -1 and j > i:
        return source[i + len(_BLOCK_START):j]
    return source


def _normalized_form(source: str) -> str:
    """Forma normalizada do bloco mutável para o proxy de novidade:
    o dump do AST (apaga formatação e comentários); se o bloco não
    parsear (a guarda o rejeitaria de qualquer forma), o texto
    dedentado cru."""
    block = textwrap.dedent(_mutable_block(source))
    try:
        return ast.dump(ast.parse(block))
    except SyntaxError:
        return block.strip()


def block_similarity(source_a: str, source_b: str) -> float:
    """Similaridade (difflib, 0..1) entre os blocos mutáveis
    normalizados de dois programas — o proxy local do Tier 1."""
    return difflib.SequenceMatcher(
        None, _normalized_form(source_a),
        _normalized_form(source_b)).ratio()


def max_block_similarity(candidate: str, member_sources) -> float:
    """Maior similaridade do candidato contra a subpopulação
    (escopo do Tier 1 na forja: a ilha do candidato)."""
    return max((block_similarity(candidate, s) for s in member_sources),
               default=0.0)


# --------------------------------------------------------------------- #
# A corrida
# --------------------------------------------------------------------- #
def run_forge(iterations: int = 300, seed: int = 42, out_dir=None,
              mutator_kind: str = "llm",
              threshold: float = CASCADE_THRESHOLD, log=print,
              final: bool = True, test_blocks_override=None,
              final_processes: int = 4, mutator=None,
              probe_gate: bool | None = None,
              parent_sampling: str | None = None,
              novelty_filter: bool | None = None,
              clock=time.time) -> dict:
    """Roda a corrida e devolve o resumo (também gravado em out_dir).

    ``clock``: relógio da instrumentação de tempo (injetável nos
    testes); só observa — nenhuma decisão lê o relógio.
    ``probe_gate``: portão da sonda pré-voo (emenda pós-V8) —
    None = config (``PROBE_GATE_ENABLED``, default LIGADO);
    False desliga, só para smokes/testes antigos.
    ``parent_sampling`` / ``novelty_filter``: porte Shinka (#21)
    — None = config (``PARENT_SAMPLING``/``NOVELTY_FILTER``,
    defaults ATIVOS desde a ativação de 28/10/2026: weighted +
    filtro ligado); passar ``"off"``/``False`` reproduz o
    comportamento pré-porte, bit-idêntico.
    """
    sampling = PARENT_SAMPLING if parent_sampling is None \
        else parent_sampling
    if sampling not in ("off", "weighted", "power_law"):
        raise ValueError(
            f"parent_sampling desconhecido: {sampling!r}")
    novelty_on = NOVELTY_FILTER if novelty_filter is None \
        else novelty_filter
    run_t0 = clock()
    ev = _load_sibling("forge_evaluator", "evaluator.py")
    mut = mutator if mutator is not None else build_mutator(mutator_kind)
    rng = random.Random(seed)
    out = Path(out_dir) if out_dir else Path.cwd() / "forge-v1"
    prog_dir = out / "programs"
    prog_dir.mkdir(parents=True, exist_ok=True)
    log_path = out / "run_log.jsonl"
    log_file = log_path.open("a", encoding="utf-8")

    records: list[dict] = []
    sources: dict[str, str] = {}
    archive: dict[str, dict] = {}        # hash -> registro completo
    islands: list[list[str]] = [[] for _ in range(NUM_ISLANDS)]
    guard_feedback: dict[str, str] = {}  # pai -> violações do último filho
    best_s1: dict | None = None
    best_validated: dict | None = None   # melhor por S2: {hash, S1, S2}

    def emit(rec: dict) -> None:
        records.append(rec)
        log_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log_file.flush()

    def consider(h: str, s1, s2) -> None:
        nonlocal best_s1, best_validated
        if s1 is not None and (best_s1 is None or s1 > best_s1["S1"]):
            best_s1 = {"hash": h, "S1": s1, "S2": s2}
        if s2 is not None and (best_validated is None
                               or s2 > best_validated["S2"]):
            best_validated = {"hash": h, "S1": s1, "S2": s2}

    def evaluate(h: str, source: str, want_stage2: bool):
        """(S1, S2, métricas, artefatos, erro|None, tempos) de um
        programa — tempos = {"stage1_s": ..., "stage2_s": ...|None},
        medidos com o relógio injetado (observação pura)."""
        path = prog_dir / f"prog_{h}.py"
        path.write_text(source, encoding="utf-8")
        timing = {"stage1_s": None, "stage2_s": None}
        t_s1 = clock()
        try:
            m1, a1 = _eval_stage(ev, path, 1)
        except Exception as exc:
            timing["stage1_s"] = round(clock() - t_s1, 3)
            return None, None, {}, {}, \
                f"{type(exc).__name__}: {exc}"[:400], timing
        timing["stage1_s"] = round(clock() - t_s1, 3)
        if m1.get("valid", 0.0) < 1.0:
            return None, None, {}, a1, _reason(
                a1, "avaliador devolveu valid=0 no stage1"), timing
        s1 = float(m1["S"])
        s2, m2, a2 = None, {}, {}
        if want_stage2(s1):
            t_s2 = clock()
            try:
                m2, a2 = _eval_stage(ev, path, 2)
                if m2.get("valid", 0.0) >= 1.0:
                    s2 = float(m2["S"])
                else:
                    log(f"  stage2 invalido prog:{h}: "
                        f"{_reason(a2, 'valid=0')[:200]}")
                    m2 = {}
            except Exception as exc:
                log(f"  stage2 falhou prog:{h}: "
                    f"{type(exc).__name__}: {exc}")
                m2 = {}
            timing["stage2_s"] = round(clock() - t_s2, 3)
        metrics = {"S1": s1, "S2": s2,
                   "stage_mean": m1.get("stage_mean"),
                   "facilities_mean": m1.get("facilities_mean"),
                   "super_mean": m1.get("super_mean"),
                   "alive_rate": m1.get("alive_rate"),
                   "tool_rate": m1.get("tool_rate")}
        artifacts = a2 if s2 is not None else a1
        return s1, s2, metrics, artifacts, None, timing

    def register(h, source, parent, iteration, island, desc, s1, s2,
                 metrics, artifacts):
        archive[h] = {"hash": h, "parent": parent,
                      "iteration": iteration, "island": island,
                      "mutation": desc, "S1": s1, "S2": s2,
                      "metrics": metrics, "artifacts": artifacts}
        if h not in islands[island]:
            islands[island].append(h)
        consider(h, s1, s2)

    def checkpoint(done: int) -> None:
        partial = {"ok": False, "checkpoint": True,
                   "iterations_completed": done,
                   "best_by_S1": best_s1, "best_by_S2": best_validated,
                   "timings": summarize_timings(records)}
        (out / "run_summary.json").write_text(
            json.dumps(partial, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (out / "archive.json").write_text(json.dumps(
            [{k: v for k, v in rec.items() if k != "artifacts"}
             for rec in archive.values()],
            ensure_ascii=False, indent=1), encoding="utf-8")

    summary: dict = {"ok": False, "iterations": iterations, "seed": seed,
                     "threshold": threshold, "mutator": mutator_kind}
    summary["parent_sampling"] = {
        "strategy": sampling, "lambda": PARENT_LAMBDA,
        "alpha": PARENT_ALPHA, "enabled": sampling != "off"}
    summary["novelty"] = {
        "enabled": bool(novelty_on), "threshold": NOVELTY_THRESHOLD,
        "scope": "ilha (EVOLVE-BLOCK; proxy AST normalizado + difflib)"}
    try:
        # ---- portão da sonda pré-voo (emenda pós-V8) -------------
        # Infraestrutura, fora do protocolo: sonda ANTES da
        # iteração 0 e, sem a fundação mínima viva, a corrida NÃO
        # larga — FORGE-GATE: BLOCKED, zero iterações consumidas,
        # nenhuma seed de teste tocada. Com a fundação viva, as
        # rotas mortas são podadas da cadeia desta corrida.
        gate_on = PROBE_GATE_ENABLED if probe_gate is None \
            else probe_gate
        if gate_on and hasattr(mut, "probe_routes"):
            llm_mod = _load_sibling("forge_llm_mutator",
                                    "llm_mutator.py")
            results = mut.probe_routes()
            passed, reasons = llm_mod.race_gate(results)
            pruned = mut.prune_dead_routes(results) \
                if hasattr(mut, "prune_dead_routes") else []
            summary["probe_gate"] = {
                "enabled": True, "passed": passed,
                "routes": results, "pruned_routes": pruned,
                "blocked_reasons": reasons}
            for line in llm_mod.format_probe_report(
                    results).splitlines():
                log(f"  sonda: {line}")
            if pruned:
                log("  portão: rotas mortas podadas da cadeia: "
                    + ", ".join(f"{p['provider']}/{p['model']}"
                                for p in pruned))
            if not passed:
                summary["fatal"] = "FORGE-GATE: BLOCKED — " \
                    + "; ".join(reasons)
                log(f"FORGE-GATE: BLOCKED — {'; '.join(reasons)}")
                return summary
            log("FORGE-GATE: PASS — fundação viva "
                "(nvidia/nvidia/nemotron-3-ultra-550b-a55b "
                "+ ≥1 rota Gemini); "
                "corrida liberada")
        else:
            summary["probe_gate"] = {
                "enabled": bool(gate_on), "passed": None,
                "pruned_routes": [], "blocked_reasons": [],
                "note": "portão desligado (probe_gate=False) ou "
                        "mutador sem sonda (programático)"}

        # ---- iteração 0: a semente, nos dois estágios -------------
        seed_source = SEED_PATH.read_text(encoding="utf-8")
        seed_hash = program_hash(seed_source)
        sources[seed_hash] = seed_source
        t0 = clock()
        seed_timing = {"mutate_s": 0.0, "stage1_s": None,
                       "stage2_s": None, "routes_s": {}}
        violations = validate_program(seed_source)
        if violations:
            summary["fatal"] = "semente rejeitada pela guarda: " \
                + "; ".join(violations)
            emit({"iteration": 0, "hash": seed_hash, "status": "fatal",
                  "reason": summary["fatal"],
                  "timing": {**seed_timing,
                             "total_s": round(clock() - t0, 3)}})
            return summary
        s1, s2, metrics, artifacts, err, ev_timing = evaluate(
            seed_hash, seed_source, lambda _s: True)
        seed_timing.update(ev_timing)
        if err is not None:
            summary["fatal"] = f"semente falhou na avaliação: {err}"
            emit({"iteration": 0, "hash": seed_hash, "status": "fatal",
                  "reason": err,
                  "timing": {**seed_timing,
                             "total_s": round(clock() - t0, 3)}})
            return summary
        register(seed_hash, seed_source, None, 0, 0, "semente (geração 0)",
                 s1, s2, metrics, artifacts)
        emit({"iteration": 0, "hash": seed_hash, "parent": None,
              "mutation": "semente (geração 0)", "status": "seed",
              "reason": "", "S1": s1, "S2": s2, "island": 0,
              "best_S1": best_s1["S1"], "best_S2": best_validated["S2"],
              "seconds": round(clock() - t0, 2),
              "timing": {**seed_timing,
                         "total_s": round(clock() - t0, 3)}})
        log(f"[000/{iterations}] semente prog:{seed_hash} "
            f"S1={s1:.4f} S2={s2:.4f}")

        # ---- o loop -------------------------------------------------
        seen = {seed_hash}
        completed = 0
        attempts = 1 if mutator_kind == "llm" else 3
        children_generated: dict[str, int] = {}
        novelty_stats = {"checked": 0, "rejected": 0,
                         "max_similarity": 0.0}
        for i in range(1, iterations + 1):
            t0 = clock()
            island = i % NUM_ISLANDS
            members = islands[island] or [seed_hash]
            if sampling != "off":
                # Porte Shinka (#21): sorteio ponderado na ilha.
                parent_hash = sample_parent(
                    members,
                    {h: archive[h]["S1"] for h in members},
                    children_generated, sampling, rng)
            else:
                roll = rng.random()
                if roll < EXPLOITATION:
                    parent_hash = max(members,
                                      key=lambda h: archive[h]["S1"])
                elif roll < 0.9:
                    parent_hash = rng.choice(members)
                else:
                    parent_hash = seed_hash
            parent_source = sources[parent_hash]
            parent_rec = archive[parent_hash]
            inspirations = []
            others = [h for h in members if h != parent_hash]
            if others:
                best_other = max(others, key=lambda h: archive[h]["S1"])
                inspirations.append({"hash": best_other,
                                     "S1": archive[best_other]["S1"],
                                     "source": sources[best_other]})
                rest = [h for h in others if h != best_other]
                if rest:
                    h2 = rng.choice(rest)
                    inspirations.append({"hash": h2,
                                         "S1": archive[h2]["S1"],
                                         "source": sources[h2]})
            fb_artifacts = dict(parent_rec.get("artifacts") or {})
            if guard_feedback.get(parent_hash):
                fb_artifacts["guard_violations"] = \
                    guard_feedback[parent_hash]
            feedback = {"parent_hash": parent_hash,
                        "parent_metrics": parent_rec["metrics"],
                        "artifacts": fb_artifacts,
                        "inspirations": inspirations,
                        "best_S1": best_s1["S1"] if best_s1 else None}

            child, desc, child_hash = None, "", None
            cand_hash, last_exc = None, None
            novelty_rejected_iter = False
            novelty_sim_iter: float | None = None
            routes_before = _route_seconds_of(mut)
            t_mut = clock()
            for _attempt in range(attempts):
                try:
                    cand, cand_desc = mut.mutate(parent_source, rng,
                                                 feedback)
                except Exception as exc:  # mutador falhou (LLM ou AST)
                    last_exc = exc
                    continue
                cand_hash = program_hash(cand)
                if cand_hash in seen:
                    continue
                if novelty_on:
                    # Tier 1 (porte Shinka #21): quase-duplicado da
                    # ilha é descartado ANTES da guarda e da cascata;
                    # consome a tentativa como uma duplicata exata.
                    sim = max_block_similarity(
                        cand, [sources[h] for h in members])
                    novelty_stats["checked"] += 1
                    novelty_stats["max_similarity"] = max(
                        novelty_stats["max_similarity"], sim)
                    novelty_sim_iter = sim
                    if sim >= NOVELTY_THRESHOLD:
                        novelty_rejected_iter = True
                        novelty_stats["rejected"] += 1
                        continue
                child, desc, child_hash = cand, cand_desc, cand_hash
                break
            if cand_hash is not None:
                # N do fator de novidade da weighted: filhos GERADOS
                # pelo pai (candidatos produzidos, aceitos ou não).
                children_generated[parent_hash] = \
                    children_generated.get(parent_hash, 0) + 1
            iter_timing = {"mutate_s": round(clock() - t_mut, 3),
                           "stage1_s": None, "stage2_s": None,
                           "routes_s": _route_delta(
                               routes_before, _route_seconds_of(mut))}
            base = {"iteration": i, "parent": parent_hash,
                    "island": island,
                    "mutation": desc if child else
                    f"sem mutação nova em {attempts} tentativa(s)"}
            if sampling != "off":
                base["parent_sampling"] = sampling
            if novelty_on and novelty_sim_iter is not None:
                base["novelty_max_similarity"] = \
                    round(novelty_sim_iter, 4)
            tail = {"S1": None, "S2": None,
                    "best_S1": best_s1["S1"],
                    "best_S2": best_validated["S2"]
                    if best_validated else None,
                    "seconds": round(clock() - t0, 2)}
            if child is None:
                if last_exc is not None:
                    status = "rejected_llm" if "MutationError" in \
                        type(last_exc).__name__ else "error"
                    reason = \
                        f"{type(last_exc).__name__}: {last_exc}"[:400]
                elif novelty_rejected_iter:
                    status = "rejected_novelty"
                    reason = (
                        "quase-duplicado da ilha (Tier 1, proxy "
                        f"AST+difflib): similaridade "
                        f"{novelty_sim_iter:.3f} >= limiar "
                        f"{NOVELTY_THRESHOLD} — descartado ANTES da "
                        "cascata (porte Shinka #21)")[:400]
                else:
                    status = "duplicate"
                    reason = "hash já avaliado"
                emit({**base, "hash": cand_hash, "status": status,
                      "reason": reason, **tail,
                      "timing": {**iter_timing,
                                 "total_s": round(clock() - t0, 3)}})
                completed += 1
                log(f"[{i:03d}/{iterations}] {status} "
                    f"prog:{cand_hash}: {reason[:140]}")
                continue
            seen.add(child_hash)
            sources[child_hash] = child
            violations = validate_program(child)
            if violations:
                guard_feedback[parent_hash] = \
                    "Programa REJEITADO pela guarda anti-trapaça:\n- " \
                    + "\n- ".join(violations)
                emit({**base, "hash": child_hash,
                      "status": "rejected_guard",
                      "reason": "; ".join(violations)[:400], **tail,
                      "timing": {**iter_timing,
                                 "total_s": round(clock() - t0, 3)}})
                completed += 1
                log(f"[{i:03d}/{iterations}] rejected_guard "
                    f"prog:{child_hash}: {violations[0][:120]}")
                continue

            def want_stage2(s: float) -> bool:
                return s >= threshold or s > best_s1["S1"]

            s1, s2, metrics, artifacts, err, ev_timing = evaluate(
                child_hash, child, want_stage2)
            iter_timing.update(ev_timing)
            if err is not None:
                emit({**base, "hash": child_hash, "status": "error",
                      "reason": err, **tail,
                      "timing": {**iter_timing,
                                 "total_s": round(clock() - t0, 3)}})
                completed += 1
                log(f"[{i:03d}/{iterations}] error prog:{child_hash}: "
                    f"{err[:140]}")
                continue
            register(child_hash, child, parent_hash, i, island, desc,
                     s1, s2, metrics, artifacts)
            emit({**base, "hash": child_hash, "status": "accepted",
                  "reason": "", "S1": s1, "S2": s2,
                  "best_S1": best_s1["S1"],
                  "best_S2": best_validated["S2"]
                  if best_validated else None,
                  "seconds": round(clock() - t0, 2),
                  "timing": {**iter_timing,
                             "total_s": round(clock() - t0, 3)}})
            completed += 1
            log(f"[{i:03d}/{iterations}] accepted prog:{child_hash} "
                f"S1={s1:.4f} S2={s2 if s2 is None else round(s2, 4)} "
                f"best_S1={best_s1['S1']:.4f} ({desc[:80]})")
            if i % MIGRATION_EVERY == 0:
                champ = (best_validated or best_s1)["hash"]
                for isl in islands:
                    if champ not in isl:
                        isl.append(champ)
                log(f"  migração: campeão prog:{champ} semeado em "
                    "todas as ilhas")
            if i % CHECKPOINT_EVERY == 0:
                checkpoint(i)

        # ---- campeão + avaliação cega -------------------------------
        champion = best_validated or best_s1
        summary["novelty"].update({
            "checked": novelty_stats["checked"],
            "rejected": novelty_stats["rejected"],
            "max_similarity": round(novelty_stats["max_similarity"], 4)})
        summary.update({
            "ok": completed == iterations,
            "iterations_completed": completed,
            "counts": {st: sum(1 for r in records if r["status"] == st)
                       for st in ("accepted", "rejected_guard",
                                  "rejected_llm", "rejected_novelty",
                                  "error", "duplicate")},
            "seed_result": {"hash": seed_hash, "S1": records[0]["S1"],
                            "S2": records[0]["S2"]},
            "champion": champion,
            "s_curve_best_S1": [r["best_S1"] for r in records],
            "mutator_stats": getattr(mut, "stats", {}),
            "records": records,
        })
        if champion is not None:
            (out / "champion.py").write_text(sources[champion["hash"]],
                                             encoding="utf-8")
            summary["champion_hash"] = champion["hash"]
        blind_s = None
        if final and champion is not None:
            log("avaliação cega: abrindo as seeds de teste "
                "(final=True, protocolo da épica)...")
            t_blind = clock()
            fe = run_blind_evaluation(
                out, prog_dir, champion["hash"], seed_hash,
                test_blocks_override, final_processes, log)
            blind_s = clock() - t_blind
            summary["final_evaluation"] = fe
            summary["verdict"] = f"FORGE-V1: {fe['verdict']}"
            steps = top_diffs(archive, champion["hash"], sources)
            summary["top_diffs"] = steps
            (out / "top5_diffs.md").write_text(
                _top_diffs_md(steps, champion["hash"]), encoding="utf-8")
            log(f"avaliação cega: ΔS vs torneio "
                f"{fe['delta_vs_tournament']['mean']:+.4f} "
                f"IC95 {fe['delta_vs_tournament']['ci95']} | "
                f"vs semente {fe['delta_vs_seed']['mean']:+.4f} -> "
                f"{summary['verdict']}")
        timings = summarize_timings(records)
        if blind_s is not None:
            timings["blind_evaluation_s"] = round(blind_s, 3)
        timings["run_wall_s"] = round(clock() - run_t0, 3)
        summary["timings"] = timings
        log(format_timing_block(timings))
        checkpoint(completed)
        return summary
    finally:
        (out / "run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1),
            encoding="utf-8")
        log_file.close()


def run_blind_evaluation(out: Path, prog_dir: Path, champion_hash: str,
                         seed_hash: str, override, processes: int,
                         log=print) -> dict:
    """Campeão x campeão do torneio x semente, nos blocos de teste.

    Sem override (a corrida de verdade): os blocos são os 64 do
    torneio e o braço-genoma abre as seeds travadas pela porta
    oficial, ``T.evaluate_test(genome, final=True)``. Com override
    (testes locais): blocos pequenos fora das seeds de teste — a
    guarda ``assert_not_test_seeds`` prova que nada vaza.
    """
    champ_data = json.loads(CHAMPION_PATH.read_text(encoding="utf-8"))
    genome = tuple(float(v) for v in champ_data["genome"])
    if override is None:
        blocks = T.test_blocks()
        genome_rows = T.evaluate_test(genome, final=True,
                                      processes=processes)
    else:
        blocks = list(override)
        T.assert_not_test_seeds([s for s, _, _ in blocks],
                                where="avaliação cega (override)")
        genome_rows = None
    arms = {
        "forge_champion": PolicySpec.program(
            str(prog_dir / f"prog_{champion_hash}.py")),
        "seed": PolicySpec.program(str(SEED_PATH)),
    }
    if genome_rows is None:
        arms["tournament_champion"] = PolicySpec.of_genome(genome)
    res = blind_evaluation(arms, blocks, final=True,
                           processes=processes)
    rows = res["rows"]
    if genome_rows is not None:
        rows["tournament_champion"] = genome_rows
        res["arms"]["tournament_champion"] = \
            sum(r["S"] for r in genome_rows) / len(genome_rows)
    d_tourn = _delta(rows["forge_champion"], rows["tournament_champion"])
    d_f2 = _delta(rows["forge_champion"], rows["tournament_champion"],
                  filt=lambda r: r["field"] == "F2")
    d_shock = _delta(rows["forge_champion"], rows["tournament_champion"],
                     filt=lambda r: r["shocks"])
    d_seed = _delta(rows["forge_champion"], rows["seed"])
    verdict = forge_verdict(d_tourn["mean"], d_tourn["ci95"][0],
                            d_f2["mean"], d_shock["mean"], d_seed["mean"])
    fe = {"verdict": verdict,
          "champion_hash": champion_hash,
          "tournament_champion": champ_data["policy_id"],
          "tournament_delta_s_vs_a0": champ_data.get(
              "tournament_delta_s_vs_a0"),
          "n_blocks": len(blocks),
          "mean_S": res["arms"],
          "delta_vs_tournament": d_tourn,
          "delta_vs_tournament_F2": d_f2,
          "delta_vs_tournament_shocks": d_shock,
          "delta_vs_seed": d_seed}
    (out / "final_evaluation.json").write_text(
        json.dumps(fe, ensure_ascii=False, indent=1), encoding="utf-8")
    return fe


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="forge-v1")
    ap.add_argument("--mutator", choices=("llm", "programmatic"),
                    default="llm")
    ap.add_argument("--threshold", type=float, default=CASCADE_THRESHOLD)
    ap.add_argument("--no-final", action="store_true",
                    help="pula a avaliação cega (ensaio)")
    ap.add_argument("--probe-only", action="store_true",
                    help="sonda pré-voo pós-V8: 1 chamada pequena por "
                    "rota de LLM e veredito PASS/FAIL, sem corrida, "
                    "sem torneio, sem tocar nas seeds de teste")
    ap.add_argument("--no-probe-gate", action="store_true",
                    help="desliga o portão da sonda DENTRO da corrida "
                    "(emenda pós-V8; default = portão LIGADO, config "
                    "probe_gate) — só para smokes/testes antigos")
    ap.add_argument("--parent-sampling",
                    choices=("off", "weighted", "power_law"),
                    default=None,
                    help="porte Shinka (#21): amostragem de pais "
                    "weighted (λ=10) ou power_law no lugar do "
                    "70/20/10 (default: config parent_sampling = "
                    "weighted, ATIVO desde 28/10/2026; 'off' volta "
                    "ao 70/20/10 legado)")
    ap.add_argument("--novelty-filter", action="store_true",
                    help="porte Shinka (#21): liga o filtro de "
                    "novidade Tier 1 com proxy local (AST+difflib) "
                    "antes da cascata (default: LIGADO desde "
                    "28/10/2026)")
    ap.add_argument("--no-novelty-filter", action="store_true",
                    help="porte Shinka (#21): DESLIGA o filtro de "
                    "novidade Tier 1 (comportamento pré-porte); "
                    "se --novelty-filter tambem for passado, "
                    "o --no- vence (desligar tem precedencia)")
    ap.add_argument("--final-processes", type=int, default=4)
    args = ap.parse_args(argv[1:])
    if args.probe_only:
        if args.mutator != "llm":
            print("FORGE-PROBE: FAIL — probe-only só vale para o "
                  "mutador llm")
            return 2
        try:
            mutator = build_mutator("llm")
        except Exception as exc:
            if type(exc).__name__ == "NoKeysError":
                print("FORGE-V1: BLOQUEADO — secrets ausentes")
                return 3
            raise
        results = mutator.probe_routes()
        llm_mod = _load_sibling("forge_llm_mutator", "llm_mutator.py")
        print(llm_mod.format_probe_report(results))
        if llm_mod.probe_gate(results):
            print("FORGE-PROBE: PASS — pelo menos uma rota viva; "
                  "a corrida pode largar")
            return 0
        print("FORGE-PROBE: FAIL — nenhuma rota viva; abortar "
              "antes da corrida, não depois de 300 iterações")
        return 2
    try:
        summary = run_forge(iterations=args.iterations, seed=args.seed,
                            out_dir=args.out, mutator_kind=args.mutator,
                            threshold=args.threshold,
                            final=not args.no_final,
                            probe_gate=not args.no_probe_gate,
                            parent_sampling=args.parent_sampling,
                            novelty_filter=False
                            if args.no_novelty_filter else (
                                True if args.novelty_filter else None),
                            final_processes=args.final_processes)
    except Exception as exc:
        if type(exc).__name__ == "NoKeysError":
            print("FORGE-V1: BLOQUEADO — secrets ausentes")
            return 3
        raise
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("records", "top_diffs")},
                     ensure_ascii=False, indent=1))
    if summary.get("verdict"):
        fe = summary["final_evaluation"]
        print(f"{summary['verdict']} | ΔS vs torneio "
              f"{fe['delta_vs_tournament']['mean']:+.4f} "
              f"IC95 {fe['delta_vs_tournament']['ci95']} | "
              f"ΔS vs semente {fe['delta_vs_seed']['mean']:+.4f}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
