"""Spike Degrau 1 — metade "tarde": teto do nativo (kernel nanobind).

- Referência Python em laços puros sobre listas, executando a MESMA
  sequência de operações do kernel C++ (que por sua vez espelha
  `Engine._produce` + `Engine._market`).
- Equivalência: mundo sintético semeado (perfil de n=100; variante
  esparsa de n=1.000), 10 passos de produce+market nos dois lados;
  diferença máxima absoluta reportada (esperado: 0.0 — mesma ordem,
  IEEE-754 double, kernel sem contração FMA).
- Benchmark: produce e market cronometrados separados, kernel x
  referência, com restauração do estado a cada 25 passos para o
  mercado não esvaziar.

Uso: .venv/bin/python experiments/degrau1/kernel/build_kernel.py
     .venv/bin/python experiments/degrau1/spike_native.py
"""
from __future__ import annotations

import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "kernel"))

import numpy as np  # noqa: E402

import market_kernel  # noqa: E402
from mundo import chain  # noqa: E402
from mundo.engine import Engine  # noqa: E402

COMMS = chain.COMMODITIES
CIDX = {c: i for i, c in enumerate(COMMS)}
ORDER = [CIDX[c] for c in sorted(COMMS)]          # ordem do motor
RAW_PAIRS = [(CIDX[r], CIDX[f]) for r, f in chain.RAW_TO_REFINED.items()]
RECIPES = {}
for kind, product in ((2, "component"), (3, "device"), (4, "supercomputer")):
    ins = list(chain.RECIPES[product]["inputs"].items())
    RECIPES[kind] = ([CIDX[c] for c, _ in ins], [p for _, p in ins],
                     CIDX[product])
KIND_OF = {"mine": 0, "refinery": 1, "factory": 2, "plant": 3, "assembly": 4}


def make_world(n: int, seed: int = 1234, sparse: bool = False):
    rng = random.Random(seed)
    eng = Engine(seed=42, n_companies=8)  # só para depósitos reais
    deps = eng.deposits
    D = len(deps)
    C = len(COMMS)
    p_offer = 0.12 if sparse else 0.35
    p_buy = 0.08 if sparse else 0.25
    stocks = [[0.0] * C for _ in range(n)]
    for i in range(n):
        for c in COMMS:
            if c in chain.RAW_TO_REFINED or c in chain.RAW_TO_REFINED.values():
                stocks[i][CIDX[c]] = rng.uniform(0, 800)
            elif c == "component":
                stocks[i][CIDX[c]] = rng.uniform(0, 60)
            elif c == "device":
                stocks[i][CIDX[c]] = rng.uniform(0, 30)
    cash = [rng.uniform(5e6, 6e7) for _ in range(n)]
    offers = [[stocks[i][CIDX[c]] * rng.uniform(0.2, 0.9)
               if rng.random() < p_offer else 0.0 for c in COMMS]
              for i in range(n)]
    buys = [[rng.uniform(1, 40) if rng.random() < p_buy else 0.0
             for _ in COMMS] for _ in range(n)]
    prices = [chain.BASE_PRICES[c] * rng.uniform(0.8, 1.3) for c in COMMS]
    mult = [[1.0] * C for _ in range(n)]
    feepct = [[0.0] * C for _ in range(n)]
    for i in range(n):
        r = rng.random()
        if r < 0.15:
            mult[i][CIDX["device"]] *= 2.2
        elif r < 0.25:
            mult[i][CIDX["device"]] *= 2.8
            mult[i][CIDX["supercomputer"]] *= 2.8
        if rng.random() < 0.2:
            for c in range(C):
                mult[i][c] *= 1.3
        if rng.random() < 0.15:
            mult[i][CIDX["device"]] *= 1.6
            feepct[i][CIDX["device"]] = 0.13
    facs = []  # (owner, kind, dep, cap, cost) — ordem (dono, criação)
    p_fac = {"mine": 0.55, "refinery": 0.35, "factory": 0.25,
             "plant": 0.15, "assembly": 0.05}
    for i in range(n):
        for kind_name, p in p_fac.items():
            if rng.random() < p:
                facs.append((i, KIND_OF[kind_name],
                             rng.randrange(D) if kind_name == "mine" else -1,
                             chain.FACILITIES[kind_name]["capacity"],
                             chain.OPERATING_COST[kind_name]))
    return {
        "n": n, "stocks": stocks, "cash": cash, "offers": offers,
        "buys": buys, "prices": prices, "mult": mult, "feepct": feepct,
        "facs": facs,
        "remaining": [d.size_t for d in deps],
        "grade": [d.grade for d in deps],
        "dep_resource": [CIDX[d.resource] for d in deps],
    }


# ------------------------- referência Python -------------------------

def produce_ref(w):
    st, ca = w["stocks"], w["cash"]
    rem = w["remaining"]
    ops = sup = 0.0
    for owner, kind, dep, cap, cost in w["facs"]:
        row = st[owner]
        if kind == 0:
            crude = min(cap, rem[dep])
            if crude <= 0:
                continue
            rem[dep] -= crude
            row[w["dep_resource"][dep]] += crude * w["grade"][dep]
            ca[owner] -= crude * cost
            ops += crude * cost
        elif kind == 1:
            budget = cap
            for raw, ref in RAW_PAIRS:
                if budget <= 0:
                    break
                qty = min(row[raw], budget)
                if qty <= 0:
                    continue
                budget -= qty
                row[raw] -= qty
                row[ref] += qty * chain.REFINE_YIELD
                ca[owner] -= qty * cost
                ops += qty * cost
        else:
            ins, pers, out = RECIPES[kind]
            max_units = cap
            for inp, per in zip(ins, pers):
                max_units = min(max_units, row[inp] / per)
            units = int(max_units)
            if units <= 0:
                continue
            for inp, per in zip(ins, pers):
                row[inp] -= units * per
            row[out] += units * 1.0
            ca[owner] -= units * cost
            ops += units * cost
            if kind == 4:
                sup += units
    return ops, sup


def market_ref(w):
    st, ca, pr = w["stocks"], w["cash"], w["prices"]
    money_in = fee_out = 0.0
    n = w["n"]
    for c in ORDER:
        price = pr[c]
        sellers = [(i, w["offers"][i][c]) for i in range(n)
                   if w["offers"][i][c] > 0.001]
        total_supply = sum(q for _, q in sellers)
        if total_supply <= 0:
            continue
        internal_demand = sum(w["buys"][i][c] for i in range(n))
        left = {i: q for i, q in sellers}
        for b in range(n):
            want = w["buys"][b][c]
            if want <= 0:
                continue
            total_left = sum(left.values())
            if total_left <= 0:
                break
            fill = min(want, total_left)
            for seller, _ in sellers:
                if seller == b or left[seller] <= 0:
                    continue
                share = fill * (left[seller] / total_left)
                share = min(share, left[seller],
                            ca[b] / price if price > 0 else 0.0)
                if share <= 0.0001:
                    continue
                st[seller][c] -= share
                st[b][c] += share
                ca[seller] += share * price
                ca[b] -= share * price
                left[seller] -= share
        city_q = chain.CITY_DEMAND.get(COMMS[c], 0.0) * 1.0
        left_total = sum(left.values())
        if city_q > 0 and left_total > 0:
            weights = {i: left[i] * w["mult"][i][c] for i, _ in sellers}
            wsum = sum(weights.values())
            for seller, _ in sellers:
                if wsum <= 0:
                    break
                qty = min(left[seller], city_q * weights[seller] / wsum)
                if qty <= 0.0001:
                    continue
                st[seller][c] -= qty
                ca[seller] += qty * price
                money_in += qty * price
                left[seller] -= qty
                fee = qty * price * w["feepct"][seller][c]
                if fee != 0.0:
                    ca[seller] -= fee
                    fee_out += fee
        demand = internal_demand + city_q
        ratio = (demand - total_supply) / max(demand, total_supply, 1.0)
        factor = min(1.35, max(0.72, 1.0 + 0.10 * ratio))
        base = chain.BASE_PRICES[COMMS[c]]
        pr[c] = min(base * 3.0, max(base * 0.3, price * factor))
    return money_in, fee_out


# ------------------------- arrays p/ kernel --------------------------

def to_arrays(w):
    i32 = np.int32
    rec_in_idx = np.full((3, 3), -1, dtype=i32)
    rec_in_per = np.zeros((3, 3))
    rec_n_in = np.zeros(3, dtype=i32)
    rec_out = np.zeros(3, dtype=i32)
    for kind, (ins, pers, out) in RECIPES.items():
        rk = kind - 2
        rec_n_in[rk] = len(ins)
        rec_out[rk] = out
        for j, (inp, per) in enumerate(zip(ins, pers)):
            rec_in_idx[rk, j] = inp
            rec_in_per[rk, j] = per
    facs = w["facs"]
    return {
        "stocks": np.array(w["stocks"]), "cash": np.array(w["cash"]),
        "offers": np.array(w["offers"]), "buys": np.array(w["buys"]),
        "alive": np.ones(w["n"], dtype=i32),
        "prices": np.array(w["prices"]),
        "base_prices": np.array([chain.BASE_PRICES[c] for c in COMMS]),
        "city_demand": np.array([chain.CITY_DEMAND.get(c, 0.0)
                                 for c in COMMS]),
        "demand_factor": np.ones(len(COMMS)),
        "mult": np.array(w["mult"]), "feepct": np.array(w["feepct"]),
        "order": np.array(ORDER, dtype=i32),
        "fac_owner": np.array([f[0] for f in facs], dtype=i32),
        "fac_kind": np.array([f[1] for f in facs], dtype=i32),
        "fac_dep": np.array([f[2] for f in facs], dtype=i32),
        "fac_cap": np.array([f[3] for f in facs]),
        "fac_cost": np.array([f[4] for f in facs]),
        "remaining": np.array(w["remaining"]),
        "grade": np.array(w["grade"]),
        "dep_resource": np.array(w["dep_resource"], dtype=i32),
        "raw_idx": np.array([r for r, _ in RAW_PAIRS], dtype=i32),
        "ref_idx": np.array([f for _, f in RAW_PAIRS], dtype=i32),
        "rec_in_idx": rec_in_idx, "rec_in_per": rec_in_per,
        "rec_n_in": rec_n_in, "rec_out": rec_out,
    }


def kernel_produce(a):
    return market_kernel.produce_step(
        a["stocks"], a["cash"], a["fac_owner"], a["fac_kind"],
        a["fac_dep"], a["fac_cap"], a["fac_cost"], a["remaining"],
        a["grade"], a["dep_resource"], a["raw_idx"], a["ref_idx"],
        chain.REFINE_YIELD, a["rec_in_idx"], a["rec_in_per"],
        a["rec_n_in"], a["rec_out"])


def kernel_market(a):
    return market_kernel.market_step(
        a["stocks"], a["cash"], a["offers"], a["buys"], a["alive"],
        a["prices"], a["base_prices"], a["city_demand"],
        a["demand_factor"], a["mult"], a["feepct"], a["order"])


def max_diff(x, y):
    return float(np.max(np.abs(np.array(x) - np.array(y))))


def bench(fn, steps, reset=None):
    samples = []
    for chunk in range(0, steps, 25):
        if reset:
            reset()
        t0 = time.perf_counter()
        for _ in range(min(25, steps - chunk)):
            fn()
        samples.append((time.perf_counter() - t0) / min(25, steps - chunk))
    return statistics.median(samples) * 1e6  # µs/passo


def main() -> int:
    print("== equivalência (referência Python x kernel C++) ==")
    for n, sparse in ((100, False), (1000, True)):
        w_ref = make_world(n, sparse=sparse)
        w_ker = make_world(n, sparse=sparse)
        a = to_arrays(w_ker)
        for _ in range(10):
            produce_ref(w_ref)
            market_ref(w_ref)
            kernel_produce(a)
            kernel_market(a)
        d = max(max_diff(w_ref["stocks"], a["stocks"]),
                max_diff(w_ref["cash"], a["cash"]),
                max_diff(w_ref["prices"], a["prices"]),
                max_diff(w_ref["remaining"], a["remaining"]))
        print(f"  n={n:>4}: diff máx após 10 passos = {d:.3e}"
              f"  ({'BIT-IDÊNTICO' if d == 0.0 else 'divergência de ulp'})")

    print("== benchmark (µs/passo produce+market, mediana) ==")
    for n, sparse, k_steps, r_steps in ((100, False, 250, 250),
                                        (1000, True, 100, 20)):
        w0 = make_world(n, sparse=sparse)
        import copy
        pristine = copy.deepcopy(w0)
        w_ref = copy.deepcopy(w0)
        a = to_arrays(copy.deepcopy(w0))

        def reset_ref():
            w_ref.update(copy.deepcopy(pristine))

        def reset_ker():
            fresh = to_arrays(copy.deepcopy(pristine))
            for k, v in fresh.items():
                a[k][...] = v

        t_ref = bench(lambda: (produce_ref(w_ref), market_ref(w_ref)),
                      r_steps, reset_ref)
        t_ker = bench(lambda: (kernel_produce(a), kernel_market(a)),
                      k_steps, reset_ker)
        print(f"  n={n:>4}: referência {t_ref:10.1f} µs  kernel "
              f"{t_ker:10.1f} µs  speedup {t_ref / t_ker:6.1f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
