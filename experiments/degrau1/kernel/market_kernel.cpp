// Kernel NATIVO DESCARTÁVEL do spike Degrau 1 (Portão 0, metade "tarde").
//
// Replica SOMENTE a aritmética de `Engine._produce` + `Engine._market`
// sobre arrays planos sintéticos, na mesma ordem de operações do motor
// Python, em IEEE-754 double, compilado com -ffp-contract=off (sem
// contração FMA) para que a comparação com a referência Python seja
// bit-a-bit. Não é código de produção: é o instrumento que mede o
// teto do caminho nativo (docs/DEGRAU1-DESIGN.md §2).
//
// Layout (row-major, C-contíguo):
//   stocks (N,C)  cash (N)  offers (N,C)  buys (N,C)  alive (N) i32
//   prices (C)  base_prices (C)  city_demand (C)  demand_factor (C)
//   mult (N,C)   -> multiplicadores de demanda das cidades já resolvidos
//                   (no motor: InstaSim 2.2 em device, VidSim 2.8, ZapSim
//                   1.3, LojaSim 1.6 — aqui são entrada, não lógica)
//   feepct (N,C) -> comissão tipo LojaSim (0 ou 0.13 em device)
//   order (C)    -> ordem das commodities (a alfabética do motor)
// Instalações em slots ordenados por (dono, criação) — a ordem exata
// do laço do `_produce`:
//   fac_owner (F) i32  fac_kind (F) i32 [0 mina,1 refinaria,2 fábrica,
//   3 planta,4 montadora]  fac_dep (F) i32  fac_cap (F)  fac_cost (F)
//   remaining (D)  grade (D)  dep_resource (D) i32
//   raw_idx/ref_idx (R) i32 — pares bruto->refinado, na ordem do dict
//   receitas das kinds 2..4: rec_in_idx (3,3) i32 (-1 = vazio),
//   rec_in_per (3,3), rec_n_in (3) i32, rec_out (3) i32

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/tuple.h>

#include <cmath>
#include <cstdint>
#include <tuple>
#include <vector>

namespace nb = nanobind;

using ArrD = nb::ndarray<double, nb::c_contig>;
using ArrI = nb::ndarray<int32_t, nb::c_contig>;

// ------------------------------------------------------------------
// _produce: por instalação (ordem (dono, criação) embutida nos arrays)
// ------------------------------------------------------------------
static std::tuple<double, double> produce_step(
    ArrD stocks, ArrD cash, ArrI fac_owner, ArrI fac_kind, ArrI fac_dep,
    ArrD fac_cap, ArrD fac_cost, ArrD remaining, ArrD grade,
    ArrI dep_resource, ArrI raw_idx, ArrI ref_idx, double refine_yield,
    ArrI rec_in_idx, ArrD rec_in_per, ArrI rec_n_in, ArrI rec_out) {
  const int64_t C = stocks.shape(1);
  double* st = stocks.data();
  double* ca = cash.data();
  double* rem = remaining.data();
  const double* gr = grade.data();
  const int64_t F = fac_owner.shape(0);
  const int64_t R = raw_idx.shape(0);
  double ops_total = 0.0, super_total = 0.0;

  for (int64_t f = 0; f < F; ++f) {
    const int64_t n = fac_owner.data()[f];
    const int32_t kind = fac_kind.data()[f];
    const double cap = fac_cap.data()[f];
    const double cost = fac_cost.data()[f];
    double* row = st + n * C;
    if (kind == 0) {  // mina
      const int64_t dep = fac_dep.data()[f];
      double crude = cap < rem[dep] ? cap : rem[dep];
      if (crude <= 0) continue;
      rem[dep] -= crude;
      row[dep_resource.data()[dep]] += crude * gr[dep];
      ca[n] -= crude * cost;
      ops_total += crude * cost;
    } else if (kind == 1) {  // refinaria
      double budget = cap;
      for (int64_t r = 0; r < R; ++r) {
        if (budget <= 0) break;
        const int32_t raw = raw_idx.data()[r];
        double qty = row[raw] < budget ? row[raw] : budget;
        if (qty <= 0) continue;
        budget -= qty;
        row[raw] -= qty;
        row[ref_idx.data()[r]] += qty * refine_yield;
        ca[n] -= qty * cost;
        ops_total += qty * cost;
      }
    } else {  // fábrica / planta / montadora (receitas)
      const int64_t rk = kind - 2;
      const int32_t nin = rec_n_in.data()[rk];
      double max_units = cap;
      for (int32_t i = 0; i < nin; ++i) {
        const int32_t inp = rec_in_idx.data()[rk * 3 + i];
        const double per = rec_in_per.data()[rk * 3 + i];
        const double lim = row[inp] / per;
        if (lim < max_units) max_units = lim;
      }
      const long long units = (long long)max_units;  // int() do Python (>=0)
      if (units <= 0) continue;
      for (int32_t i = 0; i < nin; ++i) {
        const int32_t inp = rec_in_idx.data()[rk * 3 + i];
        row[inp] -= units * rec_in_per.data()[rk * 3 + i];
      }
      row[rec_out.data()[rk]] += units * 1.0;
      ca[n] -= units * cost;
      ops_total += units * cost;
      if (kind == 4) super_total += units;
    }
  }
  return {ops_total, super_total};
}

// ------------------------------------------------------------------
// _market: por commodity (na ordem dada), comércio interno
// proporcional, demanda das cidades por peso, ajuste de preço.
// total_left é RECOMPUTADO por soma na ordem dos vendedores — a mesma
// ordem do motor Python (é o que torna a saída comparável bit-a-bit).
// ------------------------------------------------------------------
static std::tuple<double, double> market_step(
    ArrD stocks, ArrD cash, ArrD offers, ArrD buys, ArrI alive,
    ArrD prices, ArrD base_prices, ArrD city_demand, ArrD demand_factor,
    ArrD mult, ArrD feepct, ArrI order) {
  const int64_t N = stocks.shape(0);
  const int64_t C = stocks.shape(1);
  double* st = stocks.data();
  double* ca = cash.data();
  double* pr = prices.data();
  const double* of = offers.data();
  const double* bu = buys.data();
  double money_in = 0.0, fee_out = 0.0;

  std::vector<int64_t> sellers;
  std::vector<double> left;
  sellers.reserve(N);
  left.reserve(N);

  for (int64_t ci = 0; ci < C; ++ci) {
    const int64_t c = order.data()[ci];
    const double price = pr[c];
    sellers.clear();
    left.clear();
    double total_supply = 0.0, internal_demand = 0.0;
    for (int64_t n = 0; n < N; ++n) {
      if (!alive.data()[n]) continue;
      const double q = of[n * C + c];
      if (q > 0.001) {
        sellers.push_back(n);
        left.push_back(q);
        total_supply += q;
      }
      internal_demand += bu[n * C + c];
    }
    if (total_supply <= 0) continue;
    const int64_t S = sellers.size();
    // 1) comércio entre empresas
    for (int64_t b = 0; b < N; ++b) {
      if (!alive.data()[b]) continue;
      const double want = bu[b * C + c];
      if (want <= 0) continue;
      double total_left = 0.0;
      for (int64_t s = 0; s < S; ++s) total_left += left[s];
      if (total_left <= 0) break;
      const double fill = want < total_left ? want : total_left;
      for (int64_t s = 0; s < S; ++s) {
        const int64_t seller = sellers[s];
        if (seller == b || left[s] <= 0) continue;
        double share = fill * (left[s] / total_left);
        const double cap_cash = price > 0 ? ca[b] / price : 0.0;
        if (left[s] < share) share = left[s];
        if (cap_cash < share) share = cap_cash;
        if (share <= 0.0001) continue;
        st[seller * C + c] -= share;
        st[b * C + c] += share;
        ca[seller] += share * price;
        ca[b] -= share * price;
        left[s] -= share;
      }
    }
    // 2) demanda das cidades
    const double city_q = city_demand.data()[c] * demand_factor.data()[c];
    double left_total = 0.0;
    for (int64_t s = 0; s < S; ++s) left_total += left[s];
    if (city_q > 0 && left_total > 0) {
      double wsum = 0.0;
      for (int64_t s = 0; s < S; ++s)
        wsum += left[s] * mult.data()[sellers[s] * C + c];
      for (int64_t s = 0; s < S; ++s) {
        if (wsum <= 0) break;
        const int64_t seller = sellers[s];
        const double w = left[s] * mult.data()[seller * C + c];
        double qty = city_q * w / wsum;
        if (left[s] < qty) qty = left[s];
        if (qty <= 0.0001) continue;
        st[seller * C + c] -= qty;
        ca[seller] += qty * price;
        money_in += qty * price;
        left[s] -= qty;
        const double fee = qty * price * feepct.data()[seller * C + c];
        if (fee != 0.0) {
          ca[seller] -= fee;
          fee_out += fee;
        }
      }
    }
    // 3) ajuste de preço por desequilíbrio
    const double demand = internal_demand + city_q;
    const double denom = demand > total_supply
                             ? demand
                             : (total_supply > 1.0 ? total_supply : 1.0);
    const double ratio = (demand - total_supply) / denom;
    double factor = 1.0 + 0.10 * ratio;
    if (factor > 1.35) factor = 1.35;
    if (factor < 0.72) factor = 0.72;
    const double base = base_prices.data()[c];
    double np = price * factor;
    if (np > base * 3.0) np = base * 3.0;
    if (np < base * 0.3) np = base * 0.3;
    pr[c] = np;
  }
  return {money_in, fee_out};
}

NB_MODULE(market_kernel, m) {
  m.doc() = "Kernel descartável do spike Degrau 1 (produce+market).";
  m.def("produce_step", &produce_step);
  m.def("market_step", &market_step);
}
