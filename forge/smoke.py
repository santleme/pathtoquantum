"""Driver do smoke da forja (Degrau 2, sub-issue #5 do repo).

O loop ponta a ponta, sem LLM (ver a decisão em forge/mutator.py):

    semente -> [mutação -> guarda AST -> avaliador stage1
                -> stage2 nos melhores] x N iterações

Registro por iteração (JSONL + stdout): hash do programa, pai,
mutação aplicada, status (accepted / rejected_guard / error /
duplicate), S stage1/stage2, o melhor S até aqui e o motivo de cada
rejeição. A iteração 0 é a própria semente, avaliada nos DOIS
estágios — a referência e a prova de que o stage2 roda no loop.

Regra do stage2 (smoke): S1 >= limiar da cascata do config (0,45)
OU S1 novo recorde do loop. As seeds de teste nunca entram — o
avaliador guarda isso (``assert_not_test_seeds``).

Uso no Kaggle (notebook notebooks/smoke-forja.ipynb):
    python forge/smoke.py --iterations 30 --out /kaggle/working/smoke-forja
Local (testes): tamanhos de estágio caem via FORGE_STAGE1_EPISODES /
FORGE_STAGE2_EPISODES, como no avaliador.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mundo.program import program_hash, validate_program  # noqa: E402

FORGE_DIR = Path(__file__).resolve().parent
SEED_PATH = FORGE_DIR / "seed_policy.py"
# cascade_thresholds[0] de forge/config.yaml — merecer o stage2
CASCADE_THRESHOLD = 0.45


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


def run_smoke(iterations: int = 30, seed: int = 42, out_dir=None,
              threshold: float = CASCADE_THRESHOLD, log=print) -> dict:
    """Roda o smoke e devolve o resumo (também gravado em out_dir)."""
    ev = _load_sibling("forge_evaluator", "evaluator.py")
    mut = _load_sibling("forge_mutator", "mutator.py")
    rng = random.Random(seed)
    out = Path(out_dir) if out_dir else Path.cwd() / "smoke-forja"
    prog_dir = out / "programs"
    prog_dir.mkdir(parents=True, exist_ok=True)
    log_path = out / "smoke_log.jsonl"
    log_file = log_path.open("a", encoding="utf-8")

    records: list[dict] = []
    sources: dict[str, str] = {}
    accepted: list[tuple[str, float]] = []  # (hash, S1)
    best_s1: dict | None = None   # melhor por S1: {hash, S1, S2}
    best_s2: dict | None = None   # melhor validado: {hash, S1, S2}

    def emit(rec: dict) -> None:
        records.append(rec)
        log_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log_file.flush()

    def consider(h: str, s1, s2) -> None:
        nonlocal best_s1, best_s2
        if s1 is not None and (best_s1 is None or s1 > best_s1["S1"]):
            best_s1 = {"hash": h, "S1": s1, "S2": s2}
        if s2 is not None and (best_s2 is None or s2 > best_s2["S2"]):
            best_s2 = {"hash": h, "S1": s1, "S2": s2}

    def evaluate(h: str, source: str, want_stage2: bool):
        """Avalia um programa limpo; devolve (S1, S2, erro|None)."""
        path = prog_dir / f"prog_{h}.py"
        path.write_text(source, encoding="utf-8")
        try:
            m1, a1 = _eval_stage(ev, path, 1)
        except Exception as exc:  # avaliador estourou fora da rede dele
            return None, None, f"{type(exc).__name__}: {exc}"[:400]
        if m1.get("valid", 0.0) < 1.0:
            return None, None, _reason(a1, "avaliador devolveu valid=0 "
                                             "no stage1")
        s1 = float(m1["S"])
        s2 = None
        if want_stage2(s1):
            try:
                m2, a2 = _eval_stage(ev, path, 2)
                if m2.get("valid", 0.0) >= 1.0:
                    s2 = float(m2["S"])
                else:
                    log(f"  stage2 invalido prog:{h}: "
                        f"{_reason(a2, 'valid=0')[:200]}")
            except Exception as exc:
                log(f"  stage2 falhou prog:{h}: "
                    f"{type(exc).__name__}: {exc}")
        return s1, s2, None

    summary: dict = {"ok": False, "iterations": iterations, "seed": seed,
                     "threshold": threshold}
    try:
        # ---- iteração 0: a semente, nos dois estágios -------------
        seed_source = SEED_PATH.read_text(encoding="utf-8")
        seed_hash = program_hash(seed_source)
        sources[seed_hash] = seed_source
        t0 = time.time()
        violations = validate_program(seed_source)
        if violations:
            summary["fatal"] = "semente rejeitada pela guarda: " \
                + "; ".join(violations)
            emit({"iteration": 0, "hash": seed_hash, "status": "fatal",
                  "reason": summary["fatal"]})
            return summary
        s1, s2, err = evaluate(seed_hash, seed_source, lambda _s: True)
        if err is not None:
            summary["fatal"] = f"semente falhou na avaliação: {err}"
            emit({"iteration": 0, "hash": seed_hash, "status": "fatal",
                  "reason": err})
            return summary
        consider(seed_hash, s1, s2)
        accepted.append((seed_hash, s1))
        emit({"iteration": 0, "hash": seed_hash, "parent": None,
              "mutation": "semente (geração 0)", "status": "seed",
              "reason": "", "S1": s1, "S2": s2,
              "best_S1": best_s1["S1"], "best_S2": best_s2["S2"],
              "seconds": round(time.time() - t0, 2)})
        log(f"[00/{iterations}] semente prog:{seed_hash} "
            f"S1={s1:.4f} S2={s2:.4f}")

        # ---- o loop ------------------------------------------------
        seen = {seed_hash}
        completed = 0
        for i in range(1, iterations + 1):
            t0 = time.time()
            roll = rng.random()
            if roll < 0.70 and best_s1 is not None:
                parent_hash = best_s1["hash"]
            elif roll < 0.90 and accepted:
                parent_hash = rng.choice(accepted)[0]
            else:
                parent_hash = seed_hash
            parent_source = sources[parent_hash]
            child, desc, child_hash = None, "", None
            cand_hash, mut_error = None, None
            for _attempt in range(3):
                try:
                    cand, cand_desc = mut.mutate(parent_source, rng)
                except Exception as exc:  # mutador sem alvo etc.
                    mut_error = f"{type(exc).__name__}: {exc}"[:400]
                    continue
                cand_hash = program_hash(cand)
                if cand_hash not in seen:
                    child, desc, child_hash = cand, cand_desc, cand_hash
                    break
            base = {"iteration": i, "parent": parent_hash,
                    "mutation": desc if child else "sem mutação nova "
                    "em 3 tentativas"}
            if child is None and mut_error is not None \
                    and cand_hash is None:
                emit({**base, "hash": None, "status": "error",
                      "reason": f"mutador: {mut_error}", "S1": None,
                      "S2": None, "best_S1": best_s1["S1"],
                      "best_S2": best_s2["S2"] if best_s2 else None,
                      "seconds": round(time.time() - t0, 2)})
                completed += 1
                log(f"[{i:02d}/{iterations}] error (mutador): "
                    f"{mut_error[:160]}")
                continue
            if child is None:
                emit({**base, "hash": cand_hash, "status": "duplicate",
                      "reason": "hash já avaliado", "S1": None,
                      "S2": None, "best_S1": best_s1["S1"],
                      "best_S2": best_s2["S2"] if best_s2 else None,
                      "seconds": round(time.time() - t0, 2)})
                completed += 1
                log(f"[{i:02d}/{iterations}] duplicate prog:{cand_hash}")
                continue
            seen.add(child_hash)
            sources[child_hash] = child
            violations = validate_program(child)
            if violations:
                emit({**base, "hash": child_hash,
                      "status": "rejected_guard",
                      "reason": "; ".join(violations)[:400],
                      "S1": None, "S2": None,
                      "best_S1": best_s1["S1"],
                      "best_S2": best_s2["S2"] if best_s2 else None,
                      "seconds": round(time.time() - t0, 2)})
                completed += 1
                log(f"[{i:02d}/{iterations}] rejected_guard "
                    f"prog:{child_hash}: {violations[0][:120]}")
                continue

            def want_stage2(s: float) -> bool:
                return s >= threshold or s > best_s1["S1"]

            s1, s2, err = evaluate(child_hash, child, want_stage2)
            if err is not None:
                emit({**base, "hash": child_hash, "status": "error",
                      "reason": err, "S1": None, "S2": None,
                      "best_S1": best_s1["S1"],
                      "best_S2": best_s2["S2"] if best_s2 else None,
                      "seconds": round(time.time() - t0, 2)})
                completed += 1
                log(f"[{i:02d}/{iterations}] error prog:{child_hash}: "
                    f"{err[:160]}")
                continue
            consider(child_hash, s1, s2)
            accepted.append((child_hash, s1))
            emit({**base, "hash": child_hash, "status": "accepted",
                  "reason": "", "S1": s1, "S2": s2,
                  "best_S1": best_s1["S1"],
                  "best_S2": best_s2["S2"] if best_s2 else None,
                  "seconds": round(time.time() - t0, 2)})
            completed += 1
            log(f"[{i:02d}/{iterations}] accepted prog:{child_hash} "
                f"S1={s1:.4f} S2={s2 if s2 is None else round(s2, 4)} "
                f"best_S1={best_s1['S1']:.4f} ({desc})")

        summary.update({
            "ok": completed == iterations,
            "iterations_completed": completed,
            "counts": {
                "accepted": sum(1 for r in records
                                if r["status"] == "accepted"),
                "rejected_guard": sum(1 for r in records
                                      if r["status"] == "rejected_guard"),
                "error": sum(1 for r in records if r["status"] == "error"),
                "duplicate": sum(1 for r in records
                                 if r["status"] == "duplicate"),
            },
            "seed_result": {"hash": seed_hash, "S1": records[0]["S1"],
                            "S2": records[0]["S2"]},
            "best_by_S1": best_s1,
            "best_by_S2": best_s2,
            "s_curve_best_S1": [r["best_S1"] for r in records],
            "records": records,
        })
        best = best_s2 or best_s1
        if best is not None:
            (out / "best_program.py").write_text(sources[best["hash"]],
                                                 encoding="utf-8")
            summary["best_program_hash"] = best["hash"]
        return summary
    finally:
        (out / "smoke_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1),
            encoding="utf-8")
        log_file.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="smoke-forja")
    ap.add_argument("--threshold", type=float, default=CASCADE_THRESHOLD)
    args = ap.parse_args(argv[1:])
    summary = run_smoke(iterations=args.iterations, seed=args.seed,
                        out_dir=args.out, threshold=args.threshold)
    print(json.dumps({k: v for k, v in summary.items() if k != "records"},
                     ensure_ascii=False, indent=1))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
