"""Spike Degrau 1 — metade "manhã": teto do Python otimizado.

Protocolo (o mesmo do ESTUDO-MOTOR-AMBIENTE §A1):
- equivalência: fixtures determinísticas (seed 42) a n=8 e n=100 —
  baseline x overlay têm de dar `state_dict` bit-idêntico (hash
  SHA-256 do JSON canônico, que inclui crônica, frames e estado do
  RNG);
- benchmark: `step()` cronometrado (construção fora da medida),
  mediana das repetições, mundo realdata padrão.

Uso: .venv/bin/python experiments/degrau1/spike_python.py
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import market_rt  # noqa: E402
import opt_overlay  # noqa: E402
from mundo.engine import Engine  # noqa: E402


def state_hash(n: int, ticks: int, seed: int = 42) -> str:
    eng = Engine(seed=seed, n_companies=n)
    for _ in range(ticks):
        eng.step()
    blob = json.dumps(eng.state_dict(), sort_keys=True,
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def bench(n: int, ticks: int, reps: int) -> float:
    samples = []
    for _ in range(reps):
        eng = Engine(seed=42, n_companies=n)
        t0 = time.perf_counter()
        for _ in range(ticks):
            eng.step()
        samples.append((time.perf_counter() - t0) / ticks * 1000.0)
    return statistics.median(samples)


def main() -> int:
    print("== equivalência (baseline x overlay) ==")
    ok = True
    for n, ticks in ((8, 24), (100, 24), (8, 120)):
        h0 = state_hash(n, ticks)
        opt_overlay.apply()
        try:
            h1 = state_hash(n, ticks)
        finally:
            opt_overlay.remove()
        same = h0 == h1
        ok &= same
        print(f"  n={n:>4} ticks={ticks:>3}: {'BIT-IDÊNTICO' if same else 'DIVERGIU'}"
              f"  sha256={h0[:16]}…")
    if not ok:
        print("FALHA DE EQUIVALÊNCIA — overlay rejeitado.")
        return 1

    print("== variante hotspot 3 (total corrente): equivalência prática ==")
    for n, ticks in ((8, 120), (100, 120)):
        h0 = state_hash(n, ticks)
        market_rt.apply()
        try:
            h1 = state_hash(n, ticks)
        finally:
            market_rt.remove()
        print(f"  n={n:>4} ticks={ticks:>3}: "
              f"{'sobreviveu (bit-idêntico neste fixture)' if h0 == h1 else 'DIVERGIU'}")

    print("== benchmark (ms/tick, mediana) ==")
    results = {}
    for n, ticks, reps in ((8, 120, 7), (100, 120, 5), (1000, 24, 3)):
        base = bench(n, ticks, reps)
        opt_overlay.apply()
        try:
            fast = bench(n, ticks, reps)
        finally:
            opt_overlay.remove()
        market_rt.apply()
        try:
            rt = bench(n, ticks, reps)
        finally:
            market_rt.remove()
        results[n] = (base, fast)
        print(f"  n={n:>4}: baseline {base:8.3f}  overlay {fast:8.3f}"
              f" ({base / fast:4.2f}x)  overlay+total-corrente {rt:8.3f}"
              f" ({base / rt:4.2f}x)")

    base100, fast100 = results[100]
    best100 = min(base100, fast100)  # o portão usa o melhor bit-idêntico
    proj = best100 * 2.5 / 4 * 10_000_000 / 1000 / 60  # min, 4 processos
    print(f"== projeção do portão (10M ticks, n=100, mundo rico x2,5, "
          f"4 processos, melhor bit-idêntico {best100:.3f} ms/tick): "
          f"{proj:.1f} min (limiar: 45 min) ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
