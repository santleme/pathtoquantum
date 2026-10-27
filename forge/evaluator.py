"""Avaliador da forja — o contrato do OpenEvolve sobre o torneio PtQ.

O OpenEvolve chama ``evaluate_stage1``/``evaluate_stage2`` com o
caminho do programa candidato; cada estágio devolve métricas (o
``combined_score`` é o índice S do torneio) e artefatos de texto que
voltam ao prompt do LLM — aqui, o resumo bloco a bloco e eventos
salientes da Crônica da empresa focal.

Cascata do protocolo (épica #1, issue #4):
- stage1: screening, 8 episódios, campo F0, seeds de TREINO;
- stage2: 64 episódios (32 de validação x campos F0 e F1).

As seeds de TESTE (9901–9932) nunca entram aqui — ``assert_not_test_seeds``
guarda cada bloco, e a avaliação final cega roda fora do loop.
Episódios rodam em série de propósito: o OpenEvolve já paraleliza
candidatos por fora; nada de pool dentro de pool.

Tamanhos podem ser reduzidos por ambiente (testes/fumaça):
``FORGE_STAGE1_EPISODES``, ``FORGE_STAGE2_EPISODES``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mundo import tournament as T
from mundo.driver import EpisodeSpec, run_episodes
from mundo.policies import PolicySpec
from mundo.program import program_hash, validate_program

try:  # artefatos só existem com o OpenEvolve instalado (Kaggle)
    from openevolve.evaluation_result import EvaluationResult
except ImportError:  # testes locais sem a dependência: métricas puras
    EvaluationResult = None

SALIENT = {"mine", "facility", "supercomputer", "bankruptcy", "probe"}


def _zero(reason: str):
    metrics = {"combined_score": 0.0, "S": 0.0, "stage_mean": 0.0,
               "super_mean": 0.0, "facilities_mean": 0.0,
               "alive_rate": 0.0, "tool_rate": 0.0, "valid": 0.0}
    return metrics, {"evaluation_error": reason}


def _focal_events(res, focal_cid: int, kind: str) -> int:
    names = {c["cid"]: c["name"] for c in res["companies"]}
    chron = res["chronicle"]
    events = chron["events"] if isinstance(chron, dict) else chron
    return sum(1 for e in events if isinstance(e, dict)
               and e.get("company") == names[focal_cid]
               and e.get("kind") == kind)


def _n(env: str, default: int) -> int:
    return int(os.environ.get(env, str(default)))


def _blocks_for_stage(stage: int):
    if stage == 1:
        n = _n("FORGE_STAGE1_EPISODES", 8)
        return [(s, "F0", False) for s in T.TRAIN_SEEDS[:n]]
    n = _n("FORGE_STAGE2_EPISODES", 64)
    seeds = T.VAL_SEEDS[: n // 2]
    return [(s, "F0", False) for s in seeds] + \
           [(s, "F1", False) for s in seeds]


def _chronicle_highlights(results, focals, limit: int = 12) -> list[str]:
    """Eventos salientes da Crônica da focal — a história por trás do S."""
    out: list[str] = []
    for res, focal_cid in zip(results, focals):
        names = {c["cid"]: c["name"] for c in res["companies"]}
        chron = res["chronicle"]
        events = chron["events"] if isinstance(chron, dict) else chron
        for e in events:
            if isinstance(e, dict) and e.get("company") == names[focal_cid] \
                    and e.get("kind") in SALIENT:
                out.append(f"[t{e.get('tick')}] {e.get('text')}")
                if len(out) >= limit:
                    return out
    return out


def _evaluate(program_path, stage: int):
    source = Path(program_path).read_text(encoding="utf-8")
    violations = validate_program(source)
    if violations:
        metrics, _ = _zero("guarda")
        artifacts = {"guard_violations":
                     "Programa REJEITADO pela guarda anti-trapaça:\n- "
                     + "\n- ".join(violations)}
        return metrics, artifacts
    spec = PolicySpec.program(program_path)
    blocks = _blocks_for_stage(stage)
    T.assert_not_test_seeds([s for s, _, _ in blocks],
                            where="avaliador da forja")
    specs, focals = [], []
    for i, (seed, field, shocks) in enumerate(blocks):
        focal_cid = i % T.N_COMPANIES
        focals.append(focal_cid)
        specs.append(EpisodeSpec(
            seed=seed, ticks=T.TICKS, n_companies=T.N_COMPANIES,
            god_events=T.TEST_SHOCKS if shocks else None,
            policy_specs=T.field_specs(None, field, focal_cid, i, seed,
                                       focal_spec=spec)))
    try:
        results = run_episodes(specs, processes=1)
        rows = []
        for res, (seed, field, _), focal_cid in zip(results, blocks,
                                                    focals):
            row = T.block_score(res, focal_cid)
            row.update({"seed": seed, "field": field,
                        "focal_cid": focal_cid,
                        "tools": _focal_events(res, focal_cid, "tool")})
            rows.append(row)
    except Exception as exc:  # candidato quebrou: fitness 0 + o porquê
        import traceback
        return _zero("O programa quebrou durante a avaliação — corrija "
                     "e tente de novo:\n"
                     + "".join(traceback.format_exception(exc))[-1500:])
    n = len(rows)
    metrics = {
        "combined_score": sum(r["S"] for r in rows) / n,
        "S": sum(r["S"] for r in rows) / n,
        "stage_mean": sum(r["stage"] for r in rows) / n,
        "super_mean": sum(r["super"] for r in rows) / n,
        "facilities_mean": sum(r["facilities"] for r in rows) / n,
        "alive_rate": sum(1.0 for r in rows if r["alive"]) / n,
        "tool_rate": sum(r["tools"] for r in rows) / n,
        "valid": 1.0,
    }
    lines = [f"programa prog:{program_hash(source)} | estágio {stage} | "
             f"S médio {metrics['S']:.3f} em {n} blocos"]
    for r in rows:
        lines.append(
            f"seed {r['seed']} campo {r['field']}: S={r['S']:.3f} "
            f"caixa={r['cash']:,.0f} elo={r['stage']} "
            f"super={r['super']:.0f} instalações={r['facilities']} "
            f"viva={r['alive']}")
    worst = min(rows, key=lambda r: r["S"])
    lines.append(f"pior bloco: seed {worst['seed']} "
                 f"(S={worst['S']:.3f}) — investigue esse mundo.")
    artifacts = {"block_summary": "\n".join(lines)}
    highlights = _chronicle_highlights(results, focals)
    if highlights:
        artifacts["chronicle_highlights"] = "\n".join(highlights)
    return metrics, artifacts


def _wrap(metrics, artifacts):
    if EvaluationResult is not None:
        return EvaluationResult(metrics=metrics, artifacts=artifacts)
    return metrics


def evaluate_stage1(program_path):
    """Screening barato: 8 episódios F0 em seeds de treino."""
    metrics, artifacts = _evaluate(program_path, stage=1)
    return _wrap(metrics, artifacts)


def evaluate_stage2(program_path):
    """Avaliação completa do loop: 64 episódios em validação (F0+F1)."""
    metrics, artifacts = _evaluate(program_path, stage=2)
    return _wrap(metrics, artifacts)


def evaluate(program_path):
    """Sem cascata (fallback): equivale ao stage2."""
    return evaluate_stage2(program_path)
