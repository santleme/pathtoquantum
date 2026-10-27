// Núcleo nativo do motor do Mundo Autônomo — Fase 5 do Degrau 1.
//
// Segunda implementação do step() do motor Python (src/mundo/engine.py),
// bit-idêntica por construção (DEGRAU1-DESIGN §3.2/§3.3/§3.5):
//   - RNG MT19937 réplica do CPython (mt19937.hpp), gauss com cache;
//   - sum() do CPython >= 3.12 replicado (Neumaier) onde o motor usa
//     sum() sobre floats; somas sequenciais comuns onde ele usa +=;
//   - ordem de iteração de dicts do Python replicada (ordem de
//     inserção) nas estruturas que afetam RNG, somas ou eventos;
//   - compilado com -O2 -ffp-contract=off -fno-fast-math, sem
//     -march=native: mesma ordem de operações IEEE-754 do CPython,
//     que chama a libm do sistema (exp/log/pow/sin/cos idênticos).
// O núcleo NÃO narra: emite registros de evento estruturados e a
// camada Python (mundo/native_engine.py) formata a Crônica com os
// mesmos templates do motor de referência — nenhuma string de
// narrativa nasce aqui, só os valores que a alimentam.
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "mt19937.hpp"

namespace nb = nanobind;
using mundo_native::PyRandom;
using mundo_native::neumaier_sum_it;

namespace {

// ------------------------------------------------------------------ //
// Constantes da cadeia (mundo/chain.py) — DADO congelado do motor.   //
// ------------------------------------------------------------------ //
constexpr int NC = 11;  // commodities
// chain.COMMODITIES (ordem de BASE_PRICES):
// 0 lithium_ore, 1 copper_ore, 2 iron_ore, 3 oil, 4 lithium,
// 5 copper, 6 iron, 7 plastic, 8 component, 9 device, 10 supercomputer
const std::array<const char*, NC> COMM_NAMES = {
    "lithium_ore", "copper_ore", "iron_ore", "oil", "lithium", "copper",
    "iron", "plastic", "component", "device", "supercomputer"};
const std::array<double, NC> BASE_PRICES = {
    900.0, 300.0, 110.0, 420.0, 12000.0, 9000.0, 700.0, 1200.0,
    2800.0, 9500.0, 1200000.0};
const std::array<double, NC> CITY_DEMAND = {
    0.0, 0.0, 0.0, 0.0, 90.0, 220.0, 600.0, 120.0, 260.0, 420.0, 7.0};
// RAW_TO_REFINED na ordem do dict literal de chain.py
constexpr int RAW_ORD[4] = {0, 1, 2, 3};        // lithium_ore..oil
constexpr int REFINED_OF[4] = {4, 5, 6, 7};     // lithium..plastic
constexpr double REFINE_YIELD = 0.6;

// Instalações: 0 mine, 1 refinery, 2 factory, 3 plant, 4 assembly
const std::array<const char*, 5> FAC_NAMES = {"mine", "refinery", "factory",
                                              "plant", "assembly"};
const std::array<double, 5> FAC_COST = {2500000.0, 4000000.0, 6000000.0,
                                        8000000.0, 15000000.0};
const std::array<double, 5> FAC_CAPACITY = {420.0, 320.0, 300.0, 130.0, 2.0};
const std::array<double, 5> FAC_OPCOST = {42.0, 130.0, 300.0, 900.0, 60000.0};
constexpr double CLAIM_COST = 200000.0;
constexpr double PROBE_COST = 150000.0;

// Receitas (factory->component, plant->device, assembly->supercomputer)
// pares (índice do insumo, quantidade por unidade), ordem do dict.
struct RecipeIn { int idx; double per; };
const std::array<std::vector<RecipeIn>, 5> RECIPES = {
    std::vector<RecipeIn>{},
    std::vector<RecipeIn>{},
    std::vector<RecipeIn>{{5, 0.020}, {4, 0.005}},              // component
    std::vector<RecipeIn>{{8, 2.0}, {6, 0.050}, {7, 0.020}},    // device
    std::vector<RecipeIn>{{9, 10.0}, {8, 5.0}},                 // supercomputer
};
constexpr int PRODUCT_OF[5] = {-1, -1, 8, 9, 10};

// Ordem ordenada das commodities (sorted(chain.COMMODITIES))
const std::array<int, NC> COMM_SORTED = {8, 5, 1, 9, 6, 2, 4, 0, 3, 7, 10};
// Durações de regime por nome de regime (B1)
enum Regime : int { REG_NORMAL = 0, REG_BOOM = 1, REG_BUST = 2 };
const char* REGIME_NAMES[3] = {"normal", "boom", "bust"};

// Mundo embutido (world.py) — usado SÓ pela resolução nome->país do
// countrydata (vizinho mais próximo sobre os pontos do mundo builtin).
struct KnownPoint { double lat, lon; const char* country; };
const KnownPoint KNOWN_POINTS[] = {
    // depósitos builtin (ordem de world.DEPOSITS, só os com país no mapa)
    {-23.5, -68.2, "Chile"}, {-20.1, -67.5, "Bolívia"},
    {-24.2, -66.2, "Argentina"}, {-24.3, -69.1, "Chile"},
    {-22.3, -68.9, "Chile"}, {-17.3, -70.2, "Peru"},
    {-6.0, -50.3, "Brasil"}, {-20.0, -43.8, "Brasil"},
    {-24.8, -43.5, "Brasil"}, {-38.9, -68.6, "Argentina"},
    // cidades builtin (ordem de world.CITIES, idem)
    {-23.5, -46.6, "Brasil"}, {-22.9, -43.2, "Brasil"},
    {-34.6, -58.4, "Argentina"}, {-33.4, -70.7, "Chile"},
    {-12.0, -77.0, "Peru"}, {4.7, -74.1, "Colômbia"},
    {-19.9, -43.9, "Brasil"}, {-30.0, -51.2, "Brasil"},
};
const std::map<std::string, std::string> DEPOSIT_COUNTRIES = {
    {"Salar de Atacama", "Chile"}, {"Salar de Uyuni", "Bolívia"},
    {"Salinas de Jujuy", "Argentina"},
    {"Escondida (Norte do Chile)", "Chile"}, {"Chuquicamata", "Chile"},
    {"Sul do Peru (Toquepala)", "Peru"}, {"Carajás", "Brasil"},
    {"Quadrilátero Ferrífero", "Brasil"},
    {"Pré-sal (Bacia de Santos)", "Brasil"}, {"Vaca Muerta", "Argentina"},
    {"Salar del Hombre Muerto", "Argentina"},
    {"Cerro Verde (Arequipa)", "Peru"}, {"El Mutún", "Bolívia"},
};
const std::map<std::string, std::string> CITY_COUNTRIES = {
    {"São Paulo", "Brasil"}, {"Rio de Janeiro", "Brasil"},
    {"Belo Horizonte", "Brasil"}, {"Porto Alegre", "Brasil"},
    {"Buenos Aires", "Argentina"}, {"Santiago", "Chile"},
    {"Lima", "Peru"}, {"Bogotá", "Colômbia"}, {"Montevidéu", "Uruguai"},
    {"Assunção", "Paraguai"}, {"Medellín", "Colômbia"},
};

// Nomes/arquetipos de companies.py (make_companies)
const std::array<const char*, 8> COMP_NAMES = {
    "Andina Prime", "Vetor Sul", "Cuprum Andes", "Ferra Brasil",
    "Lítio Austral", "Nexo Indústrias", "PetroPlata", "Órbita Systems"};
struct Archetype { const char* name; double aggr, risk, vert, mkt; };
const std::array<Archetype, 8> ARCHETYPES = {{
    {"Agressiva", 0.90, 0.80, 0.40, 0.50},
    {"Verticalizadora", 0.50, 0.45, 0.95, 0.25},
    {"Marqueteira", 0.55, 0.50, 0.35, 0.95},
    {"Cautelosa", 0.30, 0.20, 0.60, 0.30},
    {"Expansionista", 0.80, 0.65, 0.55, 0.40},
    {"Oportunista", 0.65, 0.85, 0.30, 0.60},
    {"Industrial", 0.45, 0.40, 0.80, 0.20},
    {"Visionária", 0.60, 0.70, 0.70, 0.70},
}};
const std::array<const char*, 8> PALETTE = {
    "#e63946", "#f4a261", "#2a9d8f", "#457b9d",
    "#9b5de5", "#f15bb5", "#00bbf9", "#8ac926"};
constexpr double START_CASH = 40000000.0;

// Ferramentas (tools_sim.py)
constexpr int INSTA_DURATION = 3, ZAP_DURATION = 2;
constexpr int VID_DURATION = 6, LOJA_DURATION = 6;
constexpr double VID_DEMAND_WEIGHT = 2.8, LOJA_DEMAND_WEIGHT = 1.6;
constexpr double LOJA_FEE_PCT = 0.13;

int comm_index(const std::string& name) {
    for (int i = 0; i < NC; ++i)
        if (name == COMM_NAMES[i]) return i;
    throw nb::value_error(("commodity desconhecida: " + name).c_str());
}
int fac_index(const std::string& name) {
    for (int i = 0; i < 5; ++i)
        if (name == FAC_NAMES[i]) return i;
    throw nb::value_error(("instalação desconhecida: " + name).c_str());
}

// int() do Python sobre float: trunca para zero (como o cast C++).
inline int64_t py_int(double x) { return int64_t(x); }
// % do Python para inteiros (módulo com piso; divisor > 0 aqui).
inline int64_t py_mod(int64_t a, int64_t b) {
    int64_t r = a % b;
    return r < 0 ? r + b : r;
}
// round() do Python sem ndigits: nearest, ties-to-even sobre o valor
// binário exato — std::rint com o modo de arredondamento padrão
// (FE_TONEAREST) é exatamente isso.
inline int64_t py_round(double x) { return int64_t(std::rint(x)); }

double dget(const nb::dict& d, const char* key, double dflt) {
    if (!d.contains(key)) return dflt;
    nb::handle h = d[key];
    if (h.is_none()) return dflt;
    return nb::cast<double>(h);
}
int64_t iget(const nb::dict& d, const char* key, int64_t dflt) {
    if (!d.contains(key)) return dflt;
    nb::handle h = d[key];
    if (h.is_none()) return dflt;
    return nb::cast<int64_t>(h);
}
std::string sget(const nb::dict& d, const char* key,
                 const std::string& dflt = "") {
    if (!d.contains(key)) return dflt;
    nb::handle h = d[key];
    if (h.is_none()) return dflt;
    return nb::cast<std::string>(h);
}

// ------------------------------------------------------------------ //
// Parâmetros resolvidos (DADO; a camada Python resolve via          //
// marketdata/countrydata/equipdata e entrega dicts validados).     //
// ------------------------------------------------------------------ //
struct PolicyParams {
    double reserve_base, reserve_risk_span, mines_coef, dist_scale;
    double known_grade_base, size_ref, grade_thr_base, grade_thr_risk;
    double refinery_raw_trigger, factory_need_vertical;
    double factory_need_default, plant_component_trigger;
    double assembly_device_trigger, assembly_cash_cushion;
    double buy_budget_frac, buy_target_scale, buffer_scale;
    double insta_prob_scale, zap_prob_scale, pick_noise;
};

struct MarketComm {
    double elasticity, kappa, gamma, cover_target, sigma_monthly;
    double drift_boom, drift_bust, seasonal_amp;
    int64_t seasonal_phase;
    double dur[3];  // por regime: normal, boom, bust (meses médios)
};
struct MarketParams {
    std::array<MarketComm, NC> comm;
    double ema_alpha = 0.1;
    double band_lo = 0.25, band_hi = 6.0;
    int64_t record_window = 24;
    double record_min_break = 0.005, record_reversal = 0.05;
};

struct CountryModel {
    double capex_premium, local_opex_frac, s_reversion, s_sigma;
    double s_min, s_max, fx_beta, fx_min, fx_max, fx_reversion, fx_sigma;
    int64_t election_period, election_stagger;
    double election_smean_shift;
    std::vector<double> election_tau_steps;
    double tau_min, tau_max, smean_min, smean_max;
    double reform_hot_ratio, reform_tau_step, restriction_parity_surcharge;
    double jv_smean_drop, jv_tau_step, subsidy_tau_step, subsidy_smean_gain;
    double disaster_s_shock;
    int64_t restriction_months, halt_months_judicial, halt_months_disaster;
};
struct CountryParams {
    std::map<std::string, std::pair<double, double>> countries;  // S̄, tau
    CountryModel model;
    double ev_reform, ev_restriction, ev_jv, ev_halt, ev_subsidy, ev_disaster;
    double tariff, freight, capacity_factor, ore_scale, max_spread_mult;
};
struct ForceEvent {
    int64_t tick; std::string country, event, resource; bool has_resource;
};

struct EquipFac { double eta, beta, wear_rate; };
struct EquipParams {
    std::array<EquipFac, 5> fac;
    double age_derate, age_derate_months, hazard_scale, wear_scale;
    double repair_frac_min, repair_frac_max, repair_mu, repair_sigma;
    int64_t repair_ticks_min, repair_ticks_max;
    double maint_frac, maint_restore, maint_downtime_h, overhaul_frac;
    double pol_maint_h_base, pol_maint_h_care_span;
    double pol_repair_mult_care0, pol_repair_mult_care1;
    int64_t pol_overhaul_min_age;
    double pol_overhaul_max_cond;
};

struct GodEvent {
    int64_t tick; std::string type;
    int commodity = -1; double factor = 0, demand_factor = 1.0;
    int64_t duration = 6;
    // discovery
    std::string name; int resource = -1;
    double lat = 0, lon = 0, size_t = 0, grade = 0;
};

// ------------------------------------------------------------------ //
// Estado do mundo                                                    //
// ------------------------------------------------------------------ //
struct Deposit {
    std::string name; int resource; double lat, lon, size_t, grade;
    int cell_r, cell_c;
};
struct City {
    std::string name; double lat, lon, demand_weight;
    int cell_r, cell_c;
};
struct EquipState {
    bool present = false;
    int64_t age = 0; double cond = 1.0; int64_t down_until = -1;
    bool broken = false; double repair_cost = 0.0; int64_t repair_ticks = 0;
};
struct Facility {
    std::string id; int kind; int cell_r, cell_c;
    int deposit = -1;  // índice do depósito (kind == mine)
    EquipState equip;
};
struct Company {
    int cid = 0;
    std::string name, archetype, hq_city, color;
    double tr_aggr = 0, tr_risk = 0, tr_vert = 0, tr_mkt = 0;
    double cash = 0;
    std::array<double, NC> stocks{};
    std::vector<Facility> facilities;                 // ordem de inserção
    std::set<std::pair<int, int>> claimed;            // células
    std::map<std::string, std::pair<double, double>> knowledge;
    int64_t insta_until = -1; double insta_strength = 0.0;
    int64_t zap_until = -1, vid_until = -1, loja_until = -1;
    bool alive = true; int64_t founded_tick = 0; int64_t fac_n = 0;
    uint32_t kinds_mask = 0;
    std::array<double, NC> offers{}, buys{};
    std::map<std::string, std::pair<double, int64_t>> spend_hist;
};
struct Country {
    std::string name;
    double S, S_mean, fx, tau;
    int64_t halt_until = -1;
    std::map<std::string, int64_t> restrictions;  // recurso -> até tick
};
struct EquipStats {
    int64_t fac_ticks = 0, down_ticks = 0, breaks = 0;
    int64_t repairs = 0, maintenances = 0, overhauls = 0;
};
struct LedgerCell {
    double extracted = 0, produced = 0, consumed = 0, wasted = 0;
    double sold_external = 0, imported = 0;
};

std::pair<int, int> cell_of(double lat, double lon) {
    // world.cell_of: grade lat [-56,19], lon [-82,-27], célula 2,5°
    int r = int(py_int((lat + 56.0) / 2.5));
    int c = int(py_int((lon + 82.0) / 2.5));
    r = std::min(29, std::max(0, r));
    c = std::min(21, std::max(0, c));
    return {r, c};
}

std::string nearest_country(double lat, double lon) {
    std::string best;
    double best_dist = 0;
    bool first = true;
    for (const auto& p : KNOWN_POINTS) {
        double dist = std::fabs(lat - p.lat) + std::fabs(lon - p.lon);
        if (first || dist < best_dist) {
            best = p.country; best_dist = dist; first = false;
        }
    }
    return best;
}

}  // namespace
